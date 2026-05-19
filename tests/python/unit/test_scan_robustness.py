"""
Robustness tests: scan lock, phase exceptions, scan_run lifecycle, Seerr errors.

Covers:
- Lock released on normal exit and on exception
- Concurrent scan attempt raises BlockingIOError
- _is_scan_locked() accuracy
- Phase N exception → status=failed, earlier phases preserved, lock released
- Recovery: next scan succeeds after a failed scan
- _make_recorder no-op stub doesn't crash run_phases
- Seerr: HTTP errors / timeouts don't crash; other items continue
- fetch_providers: 500, timeout, malformed JSON → sentinel returns, no exception
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db                                          # noqa: E402
import scanner                                     # noqa: E402
from repositories import scan_run_repository as repo  # noqa: E402
from repositories.scan_run_repository import ScanRunRecorder  # noqa: E402


def _make_db(tmp_dir: str | pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(tmp_dir) / "test.db"
    db.initialize_database(path).close()
    return path


def _make_library_json(tmp_dir: str | pathlib.Path, items=None) -> pathlib.Path:
    path = pathlib.Path(tmp_dir) / "library.json"
    payload = {
        "scanned_at": "2026-01-01T00:00:00",
        "library_path": "/library",
        "total_items": len(items or []),
        "categories": [],
        "items": items or [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Scan lock robustness
# ---------------------------------------------------------------------------

class ScanLockRobustnessTest(unittest.TestCase):
    """_scan_lock() releases the lock in all exit scenarios."""

    def _lock_path(self, tmpdir: str) -> pathlib.Path:
        p = pathlib.Path(tmpdir) / "scan.lock"
        return p

    def test_lock_released_after_normal_exit(self):
        """Lock is released when the context manager exits normally."""
        with tempfile.TemporaryDirectory() as tmp:
            lp = self._lock_path(tmp)
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                with scanner._scan_lock("test"):
                    pass
                # Must be acquirable again after normal exit
                with scanner._scan_lock("test2"):
                    pass

    def test_lock_released_after_exception_in_context(self):
        """Lock is released even when an exception propagates out of the context."""
        with tempfile.TemporaryDirectory() as tmp:
            lp = self._lock_path(tmp)
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                try:
                    with scanner._scan_lock("test"):
                        raise RuntimeError("simulated scan error")
                except RuntimeError:
                    pass
                # Lock must be free: re-acquire must succeed
                with scanner._scan_lock("test2"):
                    pass

    def test_concurrent_lock_raises_blocking_io_error(self):
        """A second _scan_lock() while the first is held raises BlockingIOError."""
        with tempfile.TemporaryDirectory() as tmp:
            lp = self._lock_path(tmp)
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                with scanner._scan_lock("holder"):
                    with self.assertRaises(BlockingIOError):
                        with scanner._scan_lock("contender"):
                            pass  # should never reach

    def test_is_scan_locked_false_without_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lp = self._lock_path(tmp)
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                self.assertFalse(scanner._is_scan_locked())

    def test_is_scan_locked_true_while_lock_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            lp = self._lock_path(tmp)
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                with scanner._scan_lock("holder"):
                    self.assertTrue(scanner._is_scan_locked())

    def test_is_scan_locked_false_after_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            lp = self._lock_path(tmp)
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                with scanner._scan_lock("holder"):
                    pass
                self.assertFalse(scanner._is_scan_locked())


# ---------------------------------------------------------------------------
# scan_runs lifecycle on phase exception
# ---------------------------------------------------------------------------

class ScanRunPhaseFailureTest(unittest.TestCase):
    """Phase exception → scan_run status=failed + error; earlier phases preserved."""

    def _recorder(self, db_path: pathlib.Path) -> ScanRunRecorder:
        return ScanRunRecorder(trigger_type="manual", mode="test", db_path=db_path)

    def test_phase_exception_marks_scan_run_failed(self):
        """Exception in any phase causes recorder.fail() to set status=failed."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rec = self._recorder(db_path)
            rec.start()

            with self.assertRaises(ValueError):
                try:
                    with patch.object(scanner, "run_quick", side_effect=ValueError("disk full")):
                        scanner.run_phases([scanner.PHASE_SCAN], recorder=rec)
                except ValueError as exc:
                    rec.fail(str(exc))
                    raise

            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "failed")
            self.assertIn("disk full", rows[0]["error"])

    def test_earlier_phases_preserved_when_later_phase_fails(self):
        """Phase 1 and 2 complete normally; phase 3 throws — phases 1+2 data survives."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rec = self._recorder(db_path)
            rec.start()

            try:
                with patch.object(scanner, "run_quick", return_value="12 items"), \
                     patch.object(scanner, "run_probe", return_value="10 probed"), \
                     patch.object(scanner, "run_enrich", side_effect=RuntimeError("seerr down")):
                    scanner.run_phases([
                        scanner.PHASE_SCAN,
                        scanner.PHASE_PROBE,
                        scanner.PHASE_ENRICH,
                    ], recorder=rec)
            except RuntimeError as exc:
                rec.fail(str(exc))

            rows = repo.get_recent_scan_runs(db_path=db_path)
            row = rows[0]
            # Overall status
            self.assertEqual(row["status"], "failed")
            self.assertIn("seerr down", row["error"])
            # Phase 1 — must be fully written
            self.assertEqual(row["phase1_enabled"], 1)
            self.assertIsNotNone(row["phase1_duration_sec"])
            self.assertEqual(row["phase1_summary"], "12 items")
            # Phase 2 — must be fully written
            self.assertEqual(row["phase2_enabled"], 1)
            self.assertIsNotNone(row["phase2_duration_sec"])
            self.assertEqual(row["phase2_summary"], "10 probed")
            # Phase 3 — started (enabled) but no duration (threw before finish)
            self.assertEqual(row["phase3_enabled"], 1)
            self.assertIsNone(row["phase3_duration_sec"])

    def test_failed_scan_run_has_completed_at(self):
        """A failed scan_run has completed_at and total_duration_sec set."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            rec = self._recorder(db_path)
            rec.start()
            time.sleep(0.01)
            rec.fail("test error")

            rows = repo.get_recent_scan_runs(db_path=db_path)
            row = rows[0]
            self.assertEqual(row["status"], "failed")
            self.assertIsNotNone(row["completed_at"])
            self.assertGreater(row["total_duration_sec"], 0)

    def test_error_message_truncated_to_2000_chars(self):
        """Very long error messages are stored safely (≤2000 chars)."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="manual", mode="test", db_path=db_path)
            long_error = "x" * 5000
            repo.mark_failed(run_id, error=long_error, db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertLessEqual(len(rows[0]["error"]), 2000)

    def test_mark_failed_with_zero_run_id_is_safe(self):
        """mark_failed(0, ...) does nothing and does not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            # Should not raise
            repo.mark_failed(0, error="ignored", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# Scan recovery
# ---------------------------------------------------------------------------

class ScanRecoveryTest(unittest.TestCase):
    """After a failed scan, the lock is free and the next scan runs normally."""

    def test_lock_free_after_phase_exception(self):
        """Lock is released when a phase throws, allowing immediate re-acquisition."""
        with tempfile.TemporaryDirectory() as tmp:
            lp = pathlib.Path(tmp) / "scan.lock"
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lp)):
                # First scan: phase throws
                try:
                    with scanner._scan_lock("scan1"):
                        raise RuntimeError("simulated failure")
                except RuntimeError:
                    pass
                # Second scan: must succeed immediately
                acquired = False
                with scanner._scan_lock("scan2"):
                    acquired = True
                self.assertTrue(acquired)

    def test_subsequent_scan_run_recorded_independently(self):
        """A second scan creates its own row regardless of the previous failed scan."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)

            # First scan: fails
            rec1 = ScanRunRecorder(trigger_type="manual", mode="test", db_path=db_path)
            rec1.start()
            rec1.fail("first error")

            # Second scan: succeeds
            rec2 = ScanRunRecorder(trigger_type="manual", mode="test", db_path=db_path)
            rec2.start()
            rec2.complete()

            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(len(rows), 2)
            # Newest first
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(rows[1]["status"], "failed")

    def test_stale_running_scan_does_not_block_history_api(self):
        """A scan_run stuck at status=running (crash) doesn't corrupt history listing."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            # Simulate a crash: scan_run created but never completed/failed
            run_id = repo.create_scan_run(trigger_type="startup", mode="default", db_path=db_path)
            self.assertGreater(run_id, 0)

            # History API must return it as-is (status=running)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "running")
            # Subsequent normal scan adds a new row
            run_id2 = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            repo.mark_completed(run_id2, total_duration_sec=5.0, db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# _make_recorder no-op stub completeness
# ---------------------------------------------------------------------------

class MakeRecorderStubTest(unittest.TestCase):
    """_make_recorder no-op stub exposes all methods called by run_phases."""

    def test_noop_stub_has_start_phase(self):
        """_Noop stub must have start_phase so run_phases() doesn't AttributeError."""
        with patch.object(scanner, "ScanRunRecorder", None):
            rec = scanner._make_recorder("manual", "test")
        self.assertTrue(hasattr(rec, "start_phase"))

    def test_noop_stub_has_finish_phase(self):
        """_Noop stub must have finish_phase so run_phases() doesn't AttributeError."""
        with patch.object(scanner, "ScanRunRecorder", None):
            rec = scanner._make_recorder("manual", "test")
        self.assertTrue(hasattr(rec, "finish_phase"))

    def test_noop_stub_run_phases_does_not_crash(self):
        """run_phases() with _Noop recorder must not raise AttributeError."""
        with patch.object(scanner, "ScanRunRecorder", None), \
             patch.object(scanner, "run_quick", return_value="0 items"):
            rec = scanner._make_recorder("manual", "quick")
            rec.start()
            results = scanner.run_phases([scanner.PHASE_SCAN], recorder=rec)
        self.assertEqual(len(results), 1)

    def test_noop_stub_complete_and_fail_are_no_ops(self):
        with patch.object(scanner, "ScanRunRecorder", None):
            rec = scanner._make_recorder("manual", "test")
        rec.start()
        rec.complete()   # must not raise
        rec.fail("err")  # must not raise


# ---------------------------------------------------------------------------
# Seerr external error resilience
# ---------------------------------------------------------------------------

class SeerrExternalErrorTest(unittest.TestCase):
    """Seerr HTTP errors and malformed responses return sentinels, never crash."""

    def _call_seerr_get(self, urlopen_side_effect):
        """Call scanner._jsr_get with a mocked urlopen."""
        import urllib.error
        jsr = {"enabled": True, "url": "http://seerr.test", "apikey": "key"}
        with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            return scanner._jsr_get("/api/v1/movie/1", jsr=jsr)

    def test_http_404_not_found_body_returns_jsr_not_found(self):
        import urllib.error
        error = urllib.error.HTTPError(
            url="http://x", code=404,
            msg="Not Found",
            hdrs=None,
            fp=__import__("io").BytesIO(b"Unable to retrieve"),
        )
        result = self._call_seerr_get(error)
        self.assertIs(result, scanner._JSR_NOT_FOUND)

    def test_http_500_not_found_body_returns_jsr_not_found(self):
        import urllib.error
        error = urllib.error.HTTPError(
            url="http://x", code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=__import__("io").BytesIO(b"Unable to retrieve info"),
        )
        result = self._call_seerr_get(error)
        self.assertIs(result, scanner._JSR_NOT_FOUND)

    def test_http_500_other_body_returns_jsr_error(self):
        import urllib.error
        error = urllib.error.HTTPError(
            url="http://x", code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=__import__("io").BytesIO(b"Database connection failed"),
        )
        result = self._call_seerr_get(error)
        self.assertIs(result, scanner._JSR_ERROR)

    def test_connection_refused_returns_jsr_error(self):
        import urllib.error
        result = self._call_seerr_get(ConnectionRefusedError("refused"))
        self.assertIs(result, scanner._JSR_ERROR)

    def test_timeout_returns_jsr_error(self):
        import socket
        result = self._call_seerr_get(socket.timeout("timed out"))
        self.assertIs(result, scanner._JSR_ERROR)

    def test_malformed_json_returns_jsr_error(self):
        """urlopen succeeds but response body is invalid JSON → _JSR_ERROR."""
        class FakeResponse:
            def read(self): return b"not json {{{"
            def __enter__(self): return self
            def __exit__(self, *a): pass

        jsr = {"enabled": True, "url": "http://seerr.test", "apikey": "key"}
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = scanner._jsr_get("/api/v1/movie/1", jsr=jsr)
        # json.loads raises → caught by except Exception → _JSR_ERROR
        self.assertIs(result, scanner._JSR_ERROR)

    def test_one_item_fetch_error_others_still_enriched(self):
        """A FETCH_ERROR on one item leaves other items enriched normally."""
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_library_json(tmp, items=[
                {"id": "m1", "title": "OK Movie", "type": "movie", "category": "Films",
                 "tmdb_id": "1", "providers": [], "providers_fetched": False,
                 "seerr_status": None, "seerr_last_fetched_at": None},
                {"id": "m2", "title": "Error Movie", "type": "movie", "category": "Films",
                 "tmdb_id": "2", "providers": [], "providers_fetched": False,
                 "seerr_status": None, "seerr_last_fetched_at": None},
            ])

            call_count = [0]
            def mock_fetch_providers(tmdb_id, is_tv, jsr):
                call_count[0] += 1
                if str(tmdb_id) == "1":
                    return [{"raw_name": "Netflix", "logo": None}]
                return scanner._FETCH_ERROR

            with patch.object(scanner, "OUTPUT_PATH", str(out)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "http://x", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "_resolve_ids_from_search", return_value=scanner._JSR_NOT_FOUND), \
                 patch.object(scanner, "fetch_providers", side_effect=mock_fetch_providers):
                summary = scanner.run_enrich(force=True)

            payload = json.loads(out.read_text(encoding="utf-8"))
            items_by_id = {i["id"]: i for i in payload["items"]}
            # m1 was enriched
            self.assertTrue(items_by_id["m1"]["providers_fetched"])
            self.assertEqual(items_by_id["m1"]["seerr_status"], "ok")
            # m2 had a FETCH_ERROR — providers_fetched stays False, status stays None
            self.assertFalse(items_by_id["m2"]["providers_fetched"])
            self.assertIsNone(items_by_id["m2"]["seerr_status"])
            # Summary must mention both an enriched count and an error count
            self.assertIn("enriched", summary)
            self.assertIn("error", summary)

    def test_all_items_fetch_error_produces_zero_enriched_summary(self):
        """All items failing produces a coherent summary (0 enriched / N error)."""
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_library_json(tmp, items=[
                {"id": f"m{i}", "title": f"Movie {i}", "type": "movie", "category": "Films",
                 "tmdb_id": str(i), "providers": [], "providers_fetched": False,
                 "seerr_status": None, "seerr_last_fetched_at": None}
                for i in range(3)
            ])

            with patch.object(scanner, "OUTPUT_PATH", str(out)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "http://x", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "_resolve_ids_from_search", return_value=scanner._JSR_NOT_FOUND), \
                 patch.object(scanner, "fetch_providers", return_value=scanner._FETCH_ERROR):
                summary = scanner.run_enrich(force=True)

            self.assertIn("0 enriched", summary)
            self.assertIn("error", summary)


# ---------------------------------------------------------------------------
# DB migration chain robustness
# ---------------------------------------------------------------------------

class MigrationChainTest(unittest.TestCase):
    """Verify full migration from key historical versions to current SCHEMA_VERSION."""

    from backend import db_migrations, db_schema

    def _migrate_from(self, setup_sql: list[str], from_version: int) -> dict:
        """Create a DB with given SQL + user_version, run migrate(), return final state."""
        import sqlite3
        from backend import db_migrations, db_schema
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            for sql in setup_sql:
                conn.execute(sql)
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                         "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute(f"PRAGMA user_version = {from_version}")
            conn.commit()
            db_migrations.migrate(conn)
            version = db_migrations.get_schema_version(conn)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            media_cols = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()} \
                if "media" in tables else set()
            conn.close()
            return {"version": version, "tables": tables, "media_cols": media_cols}

    def _minimal_v8_sql(self) -> list[str]:
        return [
            """CREATE TABLE media (
                id TEXT PRIMARY KEY,
                media_type TEXT NOT NULL,
                title TEXT NOT NULL,
                is_available INTEGER NOT NULL DEFAULT 1,
                quality_json TEXT,
                missing_since TEXT
            )""",
            """CREATE TABLE seasons (
                media_id TEXT,
                season_number INTEGER,
                quality_json TEXT,
                PRIMARY KEY (media_id, season_number)
            )""",
            """CREATE TABLE providers (
                id INTEGER PRIMARY KEY,
                raw_name TEXT NOT NULL UNIQUE,
                mapped_name TEXT
            )""",
            """CREATE TABLE media_providers (
                media_id TEXT NOT NULL,
                provider_id INTEGER NOT NULL,
                PRIMARY KEY (media_id, provider_id)
            )""",
            """CREATE TABLE app_config (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE recommendations (
                id TEXT PRIMARY KEY,
                media_id TEXT,
                recommendation_type TEXT NOT NULL
            )""",
        ]

    def _minimal_v18_sql(self) -> list[str]:
        """Return SQL for a near-v18 DB (missing scan_runs, folders, probe cache)."""
        base = self._minimal_v8_sql()
        base += [
            """CREATE TABLE score_rules (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                group_key TEXT NOT NULL,
                value_key TEXT NOT NULL,
                score_value REAL NOT NULL,
                UNIQUE(category, group_key, value_key)
            )""",
            """CREATE TABLE score_size_profiles (
                id INTEGER PRIMARY KEY,
                media_type TEXT NOT NULL,
                resolution_key TEXT NOT NULL,
                codec_key TEXT NOT NULL,
                min_gb REAL NOT NULL,
                max_gb REAL NOT NULL,
                UNIQUE(media_type, resolution_key, codec_key)
            )""",
            """CREATE TABLE recommendation_rules (
                id INTEGER PRIMARY KEY,
                rule_key TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1
            )""",
            """CREATE TABLE auth_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                auth_enabled INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE active_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL
            )""",
        ]
        return base

    def test_migrate_from_v8_reaches_current_version(self):
        """Full migration chain from v8 must reach SCHEMA_VERSION."""
        from backend import db_schema
        state = self._migrate_from(self._minimal_v8_sql(), from_version=8)
        self.assertEqual(state["version"], db_schema.SCHEMA_VERSION)

    def test_migrate_from_v8_core_tables_exist(self):
        """After v8→current migration, tables present in the start schema survive."""
        state = self._migrate_from(self._minimal_v8_sql(), from_version=8)
        # These tables were in the starting schema — they must survive migration
        for tbl in ("media", "seasons", "providers", "media_providers",
                    "app_config", "recommendations"):
            self.assertIn(tbl, state["tables"], f"Table {tbl!r} dropped by migration")

    def test_migrate_from_v8_drops_dead_columns(self):
        """After v8→current migration, quality_json and root_path absent from media."""
        state = self._migrate_from(self._minimal_v8_sql(), from_version=8)
        self.assertNotIn("missing_since", state["media_cols"])
        self.assertNotIn("root_path", state["media_cols"])
        self.assertNotIn("original_title", state["media_cols"])

    def test_migrate_from_v18_reaches_current_version(self):
        """Migration from v18 (pre-scan_runs/probe-cache) reaches SCHEMA_VERSION."""
        from backend import db_schema
        state = self._migrate_from(self._minimal_v18_sql(), from_version=18)
        self.assertEqual(state["version"], db_schema.SCHEMA_VERSION)

    def test_migration_idempotent_when_run_twice(self):
        """Running migrate() on an already-current DB is a no-op."""
        import sqlite3
        from backend import db_migrations, db_schema
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            conn = db.initialize_database(db_path)
            # First time: already at SCHEMA_VERSION
            db_migrations.migrate(conn)
            v1 = db_migrations.get_schema_version(conn)
            # Second time: still same version, no errors
            db_migrations.migrate(conn)
            v2 = db_migrations.get_schema_version(conn)
            conn.close()
        self.assertEqual(v1, db_schema.SCHEMA_VERSION)
        self.assertEqual(v2, db_schema.SCHEMA_VERSION)

    def test_fresh_db_has_no_dead_columns(self):
        """Fresh DB (no migration needed) must not have original_title or root_path."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            conn = db.initialize_database(db_path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
            conn.close()
        self.assertNotIn("original_title", cols)
        self.assertNotIn("root_path", cols)
        self.assertNotIn("missing_since", cols)


if __name__ == "__main__":
    unittest.main()
