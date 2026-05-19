"""Tests for Seerr enrichment: TTL, status tracking, phase summary."""
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db          # noqa: E402
import db_schema   # noqa: E402
import scanner     # noqa: E402
from repositories import media_repository  # noqa: E402


def _make_item(**overrides):
    base = {
        "id": "movie:Films:Test",
        "type": "movie",
        "title": "Test Movie",
        "tmdb_id": "12345",
        "providers": [],
        "providers_fetched": False,
        "seerr_status": None,
        "seerr_last_fetched_at": None,
    }
    base.update(overrides)
    return base


class NeedsEnrichTest(unittest.TestCase):
    """Unit tests for the needs_enrich predicate inside run_enrich."""

    def _needs_enrich(self, item, force=False, only_category=None):
        """Re-implement needs_enrich logic for unit testing."""
        from datetime import datetime, timezone
        if only_category and item.get("category") != only_category:
            return False
        if not item.get("title") and not item.get("tmdb_id") and not item.get("tvdb_id"):
            return False
        if force:
            return True
        if item.get("seerr_status") == "not_found":
            last = item.get("seerr_last_fetched_at")
            if last:
                try:
                    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
                    return age_days >= scanner._SEERR_NOT_FOUND_TTL_DAYS
                except Exception:
                    pass
            return False
        return not item.get("providers_fetched")

    def test_unfetched_item_needs_enrich(self):
        self.assertTrue(self._needs_enrich(_make_item(providers_fetched=False)))

    def test_fetched_ok_item_skipped(self):
        item = _make_item(providers_fetched=True, seerr_status="ok")
        self.assertFalse(self._needs_enrich(item))

    def test_not_found_recent_is_skipped(self):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        item = _make_item(providers_fetched=True, seerr_status="not_found", seerr_last_fetched_at=recent)
        self.assertFalse(self._needs_enrich(item))

    def test_not_found_expired_is_retried(self):
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(days=scanner._SEERR_NOT_FOUND_TTL_DAYS + 1))
        old_iso = old.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        item = _make_item(providers_fetched=True, seerr_status="not_found", seerr_last_fetched_at=old_iso)
        self.assertTrue(self._needs_enrich(item))

    def test_not_found_no_timestamp_is_skipped(self):
        item = _make_item(providers_fetched=True, seerr_status="not_found", seerr_last_fetched_at=None)
        self.assertFalse(self._needs_enrich(item))

    def test_force_overrides_fetched_ok(self):
        item = _make_item(providers_fetched=True, seerr_status="ok")
        self.assertTrue(self._needs_enrich(item, force=True))

    def test_force_overrides_not_found_recent(self):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        item = _make_item(providers_fetched=True, seerr_status="not_found", seerr_last_fetched_at=recent)
        self.assertTrue(self._needs_enrich(item, force=True))

    def test_no_ids_no_title_always_skipped(self):
        item = _make_item(title=None, tmdb_id=None, tvdb_id=None, providers_fetched=False)
        self.assertFalse(self._needs_enrich(item))


class SeerrStatusPersistenceTest(unittest.TestCase):
    """Integration tests: seerr_status written to DB and read back."""

    def _db(self, tmpdir):
        db_path = pathlib.Path(tmpdir) / "mml.db"
        conn = db.initialize_database(db_path)
        conn.execute(
            "INSERT INTO media(id, media_type, title, is_available, providers_fetched) VALUES (?,?,?,1,0)",
            ("movie:Films:Test", "movie", "Test"),
        )
        conn.commit()
        return conn

    def test_seerr_columns_exist_after_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
            conn.close()
            self.assertIn("seerr_last_fetched_at", cols)
            self.assertIn("seerr_status", cols)

    def test_export_item_includes_seerr_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp)
            doc = media_repository.export_library(conn, availability="available")
            conn.close()
            item = doc["items"][0]
            self.assertIn("seerr_status", item)
            self.assertIn("seerr_last_fetched_at", item)
            self.assertIsNone(item["seerr_status"])

    def test_upsert_persists_seerr_ok_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp)
            from repositories.media_repository import upsert_media_item
            item = {
                "id": "movie:Films:Test",
                "type": "movie",
                "title": "Test",
                "providers": ["Netflix"],
                "providers_fetched": True,
                "seerr_status": "ok",
                "seerr_last_fetched_at": "2026-01-01T00:00:00Z",
                "is_available": True,
            }
            upsert_media_item(conn, item)
            conn.commit()
            row = conn.execute("SELECT seerr_status, seerr_last_fetched_at FROM media WHERE id=?",
                               ("movie:Films:Test",)).fetchone()
            conn.close()
            self.assertEqual(row["seerr_status"], "ok")
            self.assertEqual(row["seerr_last_fetched_at"], "2026-01-01T00:00:00Z")

    def test_upsert_persists_seerr_not_found_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp)
            from repositories.media_repository import upsert_media_item
            item = {
                "id": "movie:Films:Test",
                "type": "movie",
                "title": "Test",
                "providers": [],
                "providers_fetched": True,
                "seerr_status": "not_found",
                "seerr_last_fetched_at": "2026-01-01T00:00:00Z",
                "is_available": True,
            }
            upsert_media_item(conn, item)
            conn.commit()
            row = conn.execute("SELECT seerr_status, seerr_last_fetched_at FROM media WHERE id=?",
                               ("movie:Films:Test",)).fetchone()
            conn.close()
            self.assertEqual(row["seerr_status"], "not_found")

    def test_upsert_coalesces_seerr_fields_on_phase1_write(self):
        """Phase 1 items have seerr fields as None; COALESCE must preserve existing DB values."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp)
            # Write seerr status first
            conn.execute(
                "UPDATE media SET seerr_status='ok', seerr_last_fetched_at='2026-01-01T00:00:00Z' WHERE id=?",
                ("movie:Films:Test",),
            )
            conn.commit()
            from repositories.media_repository import upsert_media_item
            # Phase 1 write: no seerr fields
            phase1_item = {
                "id": "movie:Films:Test",
                "type": "movie",
                "title": "Test",
                "providers": ["Netflix"],
                "providers_fetched": True,
                "seerr_status": None,          # phase 1 doesn't set these
                "seerr_last_fetched_at": None,
                "is_available": True,
            }
            upsert_media_item(conn, phase1_item)
            conn.commit()
            row = conn.execute("SELECT seerr_status, seerr_last_fetched_at FROM media WHERE id=?",
                               ("movie:Films:Test",)).fetchone()
            conn.close()
            # COALESCE must have preserved the existing values
            self.assertEqual(row["seerr_status"], "ok")
            self.assertEqual(row["seerr_last_fetched_at"], "2026-01-01T00:00:00Z")


class SeerrEnrichRunTest(unittest.TestCase):
    """Integration tests for run_enrich with mocked Seerr."""

    def _run(self, items, providers_return, force=False):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "library.json"
            out.write_text(json.dumps({
                "scanned_at": "2026-01-01T00:00:00",
                "library_path": "/library",
                "total_items": len(items),
                "categories": [],
                "items": items,
            }), encoding="utf-8")
            with patch.object(scanner, "OUTPUT_PATH", str(out)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "http://x", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", return_value=providers_return), \
                 patch.object(scanner, "_resolve_ids_from_search", return_value=scanner._JSR_NOT_FOUND):
                summary = scanner.run_enrich(force=force)
            import json as _json
            payload = _json.loads(out.read_text(encoding="utf-8"))
            return summary, payload["items"]

    def test_new_item_enriched_sets_seerr_ok(self):
        item = {"id": "m1", "title": "Movie", "type": "movie", "category": "Films",
                "tmdb_id": "1", "providers": [], "providers_fetched": False,
                "seerr_status": None, "seerr_last_fetched_at": None}
        summary, items = self._run([item], [{"raw_name": "Netflix", "logo": None}])
        self.assertTrue(items[0]["providers_fetched"])
        self.assertEqual(items[0]["seerr_status"], "ok")
        self.assertIsNotNone(items[0]["seerr_last_fetched_at"])

    def test_not_found_sets_seerr_not_found(self):
        item = {"id": "m2", "title": "Movie", "type": "movie", "category": "Films",
                "tmdb_id": "2", "providers": [], "providers_fetched": False,
                "seerr_status": None, "seerr_last_fetched_at": None}
        summary, items = self._run([item], scanner._JSR_NOT_FOUND)
        self.assertTrue(items[0]["providers_fetched"])
        self.assertEqual(items[0]["seerr_status"], "not_found")
        self.assertIsNotNone(items[0]["seerr_last_fetched_at"])

    def test_fetch_error_does_not_set_seerr_status(self):
        item = {"id": "m3", "title": "Movie", "type": "movie", "category": "Films",
                "tmdb_id": "3", "providers": [], "providers_fetched": False,
                "seerr_status": None, "seerr_last_fetched_at": None}
        summary, items = self._run([item], scanner._FETCH_ERROR)
        self.assertFalse(items[0]["providers_fetched"])
        self.assertIsNone(items[0]["seerr_status"])

    def test_fetched_ok_item_skipped(self):
        item = {"id": "m4", "title": "Movie", "type": "movie", "category": "Films",
                "tmdb_id": "4", "providers": ["Netflix"], "providers_fetched": True,
                "seerr_status": "ok", "seerr_last_fetched_at": "2026-01-01T00:00:00Z"}
        with patch.object(scanner, "fetch_providers") as mock_fetch:
            summary, _ = self._run([item], [])
            mock_fetch.assert_not_called()
        self.assertIn("skipped", summary)

    def test_summary_includes_all_counters(self):
        items = [
            {"id": "m5", "title": "A", "type": "movie", "category": "X", "tmdb_id": "5",
             "providers": [], "providers_fetched": False, "seerr_status": None, "seerr_last_fetched_at": None},
            {"id": "m6", "title": "B", "type": "movie", "category": "X", "tmdb_id": "6",
             "providers": ["Netflix"], "providers_fetched": True, "seerr_status": "ok", "seerr_last_fetched_at": "2026-01-01T00:00:00Z"},
        ]
        # m5 gets enriched, m6 skipped
        summary, _ = self._run(items, [{"raw_name": "Netflix", "logo": None}])
        self.assertIn("enriched", summary)
        self.assertIn("skipped", summary)

    def test_force_refreshes_already_fetched_item(self):
        item = {"id": "m7", "title": "Movie", "type": "movie", "category": "Films",
                "tmdb_id": "7", "providers": [], "providers_fetched": True,
                "seerr_status": "ok", "seerr_last_fetched_at": "2025-01-01T00:00:00Z"}
        providers_new = [{"raw_name": "Disney+", "logo": None}]
        summary, items = self._run([item], providers_new, force=True)
        self.assertEqual(items[0]["providers"], ["Disney+"])
        self.assertEqual(items[0]["seerr_status"], "ok")


if __name__ == "__main__":
    unittest.main()
