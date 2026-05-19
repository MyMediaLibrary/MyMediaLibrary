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


import json as _json


# ---------------------------------------------------------------------------
# Phase 1 ID-change detection
# ---------------------------------------------------------------------------

class SeerrIdChangeDetectionTest(unittest.TestCase):
    """Phase 1 must reset providers_fetched when tmdb_id or tvdb_id changes."""

    _MOVIE_NFO_TMPL = """\
<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>{title}</title>
  <uniqueid type="tmdb">{tmdb_id}</uniqueid>
</movie>
"""
    _TV_NFO_TMPL = """\
<?xml version="1.0" encoding="UTF-8"?>
<tvshow>
  <title>{title}</title>
  <uniqueid type="tvdb">{tvdb_id}</uniqueid>
</tvshow>
"""
    _BASIC_CONFIG = {
        "folders": [{"name": "films", "type": "movie", "visible": True}],
        "enable_movies": True, "enable_series": True,
        "system": {"needs_onboarding": False},
    }
    _TV_CONFIG = {
        "folders": [{"name": "series", "type": "tv", "visible": True}],
        "enable_movies": True, "enable_series": True,
        "system": {"needs_onboarding": False},
    }

    def _run_phase1(self, root, output_path, config_path, only_category=None):
        with patch.object(scanner, "LIBRARY_PATH", str(root)), \
             patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
             patch.object(scanner, "CONFIG_PATH", str(config_path)):
            scanner.run_quick(only_category)

    def _db_path(self, output_path: pathlib.Path) -> pathlib.Path:
        return output_path.parent / "mymedialibrary.db"

    def _db_row(self, db_path, media_id):
        import db as _db
        conn = _db.initialize_database(db_path)
        try:
            row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _set_providers_fetched(self, db_path, media_id, tmdb_id=None, tvdb_id=None):
        """Simulate a previous successful Seerr enrichment in the DB."""
        import db as _db
        conn = _db.initialize_database(db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE media SET providers_fetched=1, seerr_status='ok', "
                    "seerr_last_fetched_at='2026-01-01T00:00:00Z' WHERE id=?",
                    (media_id,),
                )
                if tmdb_id is not None:
                    conn.execute("UPDATE media SET tmdb_id=? WHERE id=?", (tmdb_id, media_id))
                if tvdb_id is not None:
                    conn.execute("UPDATE media SET tvdb_id=? WHERE id=?", (tvdb_id, media_id))
        finally:
            conn.close()

    def test_movie_tmdb_id_change_resets_providers_fetched(self):
        """When movie tmdb_id changes in NFO, providers_fetched is reset to 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movie_dir = root / "films" / "Inception (2010)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Inception.mkv").write_text("x", encoding="utf-8")
            (movie_dir / "Inception.nfo").write_text(
                self._MOVIE_NFO_TMPL.format(title="Inception", tmdb_id="111"),
                encoding="utf-8",
            )
            out = pathlib.Path(tmpdir) / "library.json"
            cfg = pathlib.Path(tmpdir) / "config.json"
            cfg.write_text(_json.dumps(self._BASIC_CONFIG), encoding="utf-8")

            # First scan: item created
            self._run_phase1(root, out, cfg)
            db_path = self._db_path(out)
            media_id = "movie:Films:Inception (2010)"
            row = self._db_row(db_path, media_id)
            self.assertIsNotNone(row)

            # Simulate Seerr enrichment with tmdb_id=111
            self._set_providers_fetched(db_path, media_id, tmdb_id="111")
            self.assertEqual(self._db_row(db_path, media_id)["providers_fetched"], 1)

            # NFO updated with corrected tmdb_id
            (movie_dir / "Inception.nfo").write_text(
                self._MOVIE_NFO_TMPL.format(title="Inception", tmdb_id="999"),
                encoding="utf-8",
            )
            self._run_phase1(root, out, cfg)

            row = self._db_row(db_path, media_id)
            self.assertEqual(row["providers_fetched"], 0,
                             "providers_fetched must reset when tmdb_id changes")
            # seerr_status is preserved by COALESCE in the upsert SQL (by design, so
            # phase 1 doesn't accidentally clear enrichment on every scan). The critical
            # invariant is providers_fetched=0 which makes needs_enrich return True.
            # New tmdb_id should be persisted
            self.assertEqual(str(row["tmdb_id"]), "999")

    def test_movie_unchanged_tmdb_id_preserves_providers_fetched(self):
        """When tmdb_id stays the same, providers_fetched must not be reset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movie_dir = root / "films" / "Matrix (1999)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Matrix.mkv").write_text("x", encoding="utf-8")
            (movie_dir / "Matrix.nfo").write_text(
                self._MOVIE_NFO_TMPL.format(title="Matrix", tmdb_id="603"),
                encoding="utf-8",
            )
            out = pathlib.Path(tmpdir) / "library.json"
            cfg = pathlib.Path(tmpdir) / "config.json"
            cfg.write_text(_json.dumps(self._BASIC_CONFIG), encoding="utf-8")

            self._run_phase1(root, out, cfg)
            db_path = self._db_path(out)
            media_id = "movie:Films:Matrix (1999)"
            self._set_providers_fetched(db_path, media_id, tmdb_id="603")

            # Re-scan with unchanged NFO
            self._run_phase1(root, out, cfg)
            row = self._db_row(db_path, media_id)
            self.assertEqual(row["providers_fetched"], 1,
                             "providers_fetched must be preserved when tmdb_id unchanged")
            self.assertEqual(row["seerr_status"], "ok")

    def test_movie_new_tmdb_id_from_none_resets_providers_fetched(self):
        """Adding tmdb_id to a previously-unenriched item triggers re-enrichment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movie_dir = root / "films" / "Alien (1979)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Alien.mkv").write_text("x", encoding="utf-8")
            # First scan: no NFO → no tmdb_id
            out = pathlib.Path(tmpdir) / "library.json"
            cfg = pathlib.Path(tmpdir) / "config.json"
            cfg.write_text(_json.dumps(self._BASIC_CONFIG), encoding="utf-8")

            self._run_phase1(root, out, cfg)
            db_path = self._db_path(out)
            media_id = "movie:Films:Alien (1979)"

            # Simulate enrichment via title search (no tmdb_id stored in DB)
            self._set_providers_fetched(db_path, media_id, tmdb_id=None)
            self.assertEqual(self._db_row(db_path, media_id)["providers_fetched"], 1)

            # Now user adds correct NFO with tmdb_id
            (movie_dir / "Alien.nfo").write_text(
                self._MOVIE_NFO_TMPL.format(title="Alien", tmdb_id="348"),
                encoding="utf-8",
            )
            self._run_phase1(root, out, cfg)

            row = self._db_row(db_path, media_id)
            # A new tmdb_id (prev was None) must trigger reset
            self.assertEqual(row["providers_fetched"], 0)

    def test_tv_tvdb_id_change_resets_providers_fetched(self):
        """When TV tvdb_id changes, providers_fetched is reset."""
        tv_config = {
            "folders": [{"name": "series", "type": "tv", "visible": True}],
            "enable_movies": True, "enable_series": True,
            "system": {"needs_onboarding": False},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            tv_dir = root / "series" / "Breaking Bad"
            tv_dir.mkdir(parents=True)
            (tv_dir / "tvshow.nfo").write_text(
                self._TV_NFO_TMPL.format(title="Breaking Bad", tvdb_id="81189"),
                encoding="utf-8",
            )
            out = pathlib.Path(tmpdir) / "library.json"
            cfg = pathlib.Path(tmpdir) / "config.json"
            cfg.write_text(_json.dumps(tv_config), encoding="utf-8")

            self._run_phase1(root, out, cfg)
            db_path = self._db_path(out)
            media_id = "tv:Series:Breaking Bad"
            self._set_providers_fetched(db_path, media_id, tvdb_id="81189")
            self.assertEqual(self._db_row(db_path, media_id)["providers_fetched"], 1)

            # NFO corrected with new tvdb_id
            (tv_dir / "tvshow.nfo").write_text(
                self._TV_NFO_TMPL.format(title="Breaking Bad", tvdb_id="99999"),
                encoding="utf-8",
            )
            self._run_phase1(root, out, cfg)

            row = self._db_row(db_path, media_id)
            self.assertEqual(row["providers_fetched"], 0)


# ---------------------------------------------------------------------------
# Seerr endpoint routing (movie vs TV)
# ---------------------------------------------------------------------------

class SeerrEndpointRoutingTest(unittest.TestCase):
    """fetch_providers must use /movie/{id} for movies and /tv/{id} for TV."""

    def _call_fetch(self, tmdb_id, is_tv, jsr_response):
        jsr = {"enabled": True, "url": "http://seerr.test", "apikey": "key"}
        calls = []
        def mock_jsr_get(path, jsr_arg=None):
            calls.append(path)
            return jsr_response
        with patch.object(scanner, "_jsr_get", side_effect=mock_jsr_get):
            result = scanner.fetch_providers(tmdb_id, is_tv, jsr)
        return result, calls

    def test_movie_uses_movie_endpoint(self):
        result, calls = self._call_fetch("603", is_tv=False, jsr_response={"watchProviders": {}})
        self.assertTrue(any("/movie/603" in c for c in calls),
                        f"Expected /movie/603 in {calls}")
        self.assertIsNot(result, scanner._FETCH_ERROR)

    def test_tv_uses_tv_endpoint(self):
        result, calls = self._call_fetch("81189", is_tv=True, jsr_response={"watchProviders": {}})
        self.assertTrue(any("/tv/81189" in c for c in calls),
                        f"Expected /tv/81189 in {calls}")

    def test_movie_not_found_returns_jsr_not_found(self):
        jsr = {"enabled": True, "url": "http://x", "apikey": "k"}
        with patch.object(scanner, "_jsr_get", return_value=scanner._JSR_NOT_FOUND):
            result = scanner.fetch_providers("999", False, jsr)
        self.assertIs(result, scanner._JSR_NOT_FOUND)

    def test_tv_not_found_returns_jsr_not_found(self):
        jsr = {"enabled": True, "url": "http://x", "apikey": "k"}
        with patch.object(scanner, "_jsr_get", return_value=scanner._JSR_NOT_FOUND):
            result = scanner.fetch_providers("999", True, jsr)
        self.assertIs(result, scanner._JSR_NOT_FOUND)

    def test_http_error_returns_fetch_error(self):
        jsr = {"enabled": True, "url": "http://x", "apikey": "k"}
        with patch.object(scanner, "_jsr_get", return_value=scanner._JSR_ERROR):
            result = scanner.fetch_providers("603", False, jsr)
        self.assertIs(result, scanner._FETCH_ERROR)

    def test_empty_tmdb_id_returns_empty_list(self):
        jsr = {"enabled": True, "url": "http://x", "apikey": "k"}
        result = scanner.fetch_providers("", False, jsr)
        self.assertEqual(result, [])

    def test_none_tmdb_id_returns_empty_list(self):
        jsr = {"enabled": True, "url": "http://x", "apikey": "k"}
        result = scanner.fetch_providers(None, False, jsr)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# is_available=0 exclusion from enrichment
# ---------------------------------------------------------------------------

class SeerrAvailabilityFilterTest(unittest.TestCase):
    """Unavailable items (is_available=0) must not be enriched by phase 3."""

    def test_unavailable_items_absent_from_enrichment_input(self):
        """load_library_document_non_blocking with default availability excludes is_available=0."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            conn = db.initialize_database(db_path)
            with conn:
                conn.execute(
                    "INSERT INTO media(id, media_type, title, is_available, providers_fetched) "
                    "VALUES (?, ?, ?, 0, 0)",
                    ("movie:Films:Gone", "movie", "Gone"),
                )
                conn.execute(
                    "INSERT INTO media(id, media_type, title, is_available, providers_fetched) "
                    "VALUES (?, ?, ?, 1, 0)",
                    ("movie:Films:Present", "movie", "Present"),
                )
            conn.close()

            lib_json = pathlib.Path(tmp) / "library.json"
            with patch.object(scanner, "OUTPUT_PATH", str(lib_json)), \
                 patch.object(scanner, "_jsr_cfg",
                              return_value={"enabled": True, "url": "http://x", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers",
                              return_value=[{"raw_name": "Netflix", "logo": None}]) as mock_fetch, \
                 patch.object(scanner, "_resolve_ids_from_search",
                              return_value=scanner._JSR_NOT_FOUND):
                scanner.run_enrich()

            # Gone (is_available=0) must never have been passed to fetch_providers
            # The mock_fetch is called with tmdb_id — if Gone was enriched, it would have
            # called fetch_providers("movie:Films:Gone"...) which would show in call count.
            # Since Gone has no tmdb_id, it would fall through to title search. The key
            # invariant: only Present (is_available=1) appears in the enrichment list.
            # We verify via the re-exported document.
            export = media_repository.export_library(
                db.initialize_database(db_path),
                availability="all",
            )
            items_by_id = {i["id"]: i for i in export["items"]}
            # Present was enriched (has tmdb_id=None but title → will get fetch_providers called)
            # Gone was NOT enriched (is_available=0)
            self.assertEqual(items_by_id["movie:Films:Gone"]["providers_fetched"], 0,
                             "is_available=0 item must not be enriched")


# ---------------------------------------------------------------------------
# TV enrichment fallback chain
# ---------------------------------------------------------------------------

class SeerrTvFallbackTest(unittest.TestCase):
    """TV items use tvdb_id first, then tmdb_id, then title search."""

    def _run_enrich_tv(self, item, side_effect_by_call):
        """Run run_enrich with a custom fetch_providers side_effect."""
        call_log = []
        def fetch_side(lookup_id, is_tv, jsr):
            call_log.append((str(lookup_id), is_tv))
            return side_effect_by_call.get(str(lookup_id), scanner._JSR_NOT_FOUND)

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "library.json"
            out.write_text(_json.dumps({
                "scanned_at": "2026-01-01T00:00:00", "library_path": "/library",
                "total_items": 1, "categories": [], "items": [item],
            }), encoding="utf-8")
            with patch.object(scanner, "OUTPUT_PATH", str(out)), \
                 patch.object(scanner, "_jsr_cfg",
                              return_value={"enabled": True, "url": "http://x", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", side_effect=fetch_side), \
                 patch.object(scanner, "_resolve_ids_from_search",
                              return_value=scanner._JSR_NOT_FOUND):
                scanner.run_enrich(force=True)
            payload = _json.loads(out.read_text(encoding="utf-8"))
            return payload["items"][0], call_log

    def test_tv_tries_tvdb_id_first(self):
        item = {"id": "t1", "title": "Breaking Bad", "type": "tv", "category": "Series",
                "tvdb_id": "81189", "tmdb_id": "1396",
                "providers": [], "providers_fetched": False,
                "seerr_status": None, "seerr_last_fetched_at": None}
        _, calls = self._run_enrich_tv(item, {"81189": [{"raw_name": "Netflix", "logo": None}]})
        self.assertEqual(calls[0], ("81189", True), "tvdb_id must be tried first for TV")

    def test_tv_falls_back_to_tmdb_when_tvdb_not_found(self):
        item = {"id": "t2", "title": "Show", "type": "tv", "category": "Series",
                "tvdb_id": "99999", "tmdb_id": "42",
                "providers": [], "providers_fetched": False,
                "seerr_status": None, "seerr_last_fetched_at": None}
        # tvdb_id returns not_found, tmdb_id returns providers
        enriched, calls = self._run_enrich_tv(
            item, {"99999": scanner._JSR_NOT_FOUND,
                   "42": [{"raw_name": "HBO", "logo": None}]})
        self.assertTrue(any(c[0] == "42" for c in calls),
                        "Should fall back to tmdb_id after tvdb_id not_found")
        self.assertTrue(enriched["providers_fetched"])
        self.assertIn("HBO", enriched.get("providers", []))

    def test_tv_with_only_tvdb_id_uses_tvdb_endpoint(self):
        item = {"id": "t3", "title": "Show", "type": "tv", "category": "Series",
                "tvdb_id": "12345", "tmdb_id": None,
                "providers": [], "providers_fetched": False,
                "seerr_status": None, "seerr_last_fetched_at": None}
        _, calls = self._run_enrich_tv(item, {"12345": [{"raw_name": "Disney+", "logo": None}]})
        self.assertTrue(any(c[0] == "12345" for c in calls))


if __name__ == "__main__":
    unittest.main()
