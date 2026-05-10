"""Tests for incremental Phase 1 scan behavior."""

import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import scanner  # noqa: E402
from repositories import media_repository  # noqa: E402


_BASIC_CONFIG = {
    "folders": [{"name": "films", "type": "movie", "visible": True}],
    "enable_movies": True,
    "enable_series": True,
    "system": {"needs_onboarding": False, "scan_cron": "0 3 * * *", "log_level": "INFO"},
}

_TWO_FOLDER_CONFIG = {
    "folders": [
        {"name": "films", "type": "movie", "visible": True},
        {"name": "series", "type": "tv", "visible": True},
    ],
    "enable_movies": True,
    "enable_series": True,
    "system": {"needs_onboarding": False, "scan_cron": "0 3 * * *", "log_level": "INFO"},
}


def _make_movie_dir(parent: pathlib.Path, name: str) -> pathlib.Path:
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.mkv").write_text("x", encoding="utf-8")
    return d


def _run_phase1(root, output_path, config_path, only_category=None):
    with patch.object(scanner, "LIBRARY_PATH", str(root)), \
         patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
         patch.object(scanner, "CONFIG_PATH", str(config_path)):
        scanner.run_quick(only_category)


def _db_path_for(output_path: pathlib.Path) -> pathlib.Path:
    return output_path.parent / "mymedialibrary.db"


def _media_ids_in_db(db_path: pathlib.Path) -> set[str]:
    conn = db.initialize_database(db_path)
    try:
        rows = conn.execute("SELECT id FROM media ORDER BY id").fetchall()
        return {row["id"] for row in rows}
    finally:
        conn.close()


class IncrementalPhase1Test(unittest.TestCase):
    """Integration tests for run_quick() incremental behavior."""

    def test_new_media_added_to_db(self):
        """Media found on disk is inserted into the SQLite media table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)

            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertIn("movie:Films:Inception (2010)", ids)

    def test_removed_media_deleted_from_db(self):
        """Media removed from disk is deleted from the media table on re-scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            matrix_dir = _make_movie_dir(root / "films", "Matrix (1999)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)

            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertIn("movie:Films:Inception (2010)", ids)
            self.assertIn("movie:Films:Matrix (1999)", ids)

            shutil.rmtree(matrix_dir)
            _run_phase1(root, output_path, config_path)

            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertIn("movie:Films:Inception (2010)", ids)
            self.assertNotIn("movie:Films:Matrix (1999)", ids)

    def test_removed_media_absent_from_snapshot(self):
        """Media removed from disk does not appear in the library.json snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            matrix_dir = _make_movie_dir(root / "films", "Matrix (1999)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)
            shutil.rmtree(matrix_dir)
            _run_phase1(root, output_path, config_path)

            doc = json.loads(output_path.read_text(encoding="utf-8"))
            item_ids = {item["id"] for item in doc.get("items", [])}
            self.assertIn("movie:Films:Inception (2010)", item_ids)
            self.assertNotIn("movie:Films:Matrix (1999)", item_ids)
            self.assertEqual(doc["total_items"], 1)

    def test_existing_media_preserved_in_db(self):
        """Media still on disk survives re-scan without data loss."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)
            _run_phase1(root, output_path, config_path)

            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertIn("movie:Films:Inception (2010)", ids)

    def test_enriched_quality_preserved_on_rescan(self):
        """Quality data written by Phase 3 is kept intact during Phase 1 re-scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)

            # Simulate Phase 3 writing quality into the snapshot
            doc = media_repository.load_library(output_path)
            for item in doc.get("items", []):
                item["quality"] = {"score": 85, "video": 50, "audio": 35}
            with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                media_repository.save_library(doc, output_path)

            # Phase 1 re-scan should preserve the quality
            _run_phase1(root, output_path, config_path)

            result = media_repository.load_library(output_path)
            items = result.get("items", [])
            self.assertEqual(len(items), 1)
            self.assertIn("quality", items[0])
            self.assertEqual(items[0]["quality"]["score"], 85)

    def test_media_id_stable_between_scans(self):
        """The same media_id is assigned on first and subsequent Phase 1 scans."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)
            ids1 = {item["id"] for item in json.loads(output_path.read_text())["items"]}

            _run_phase1(root, output_path, config_path)
            ids2 = {item["id"] for item in json.loads(output_path.read_text())["items"]}

            self.assertEqual(ids1, ids2)

    def test_category_scoped_deletion(self):
        """When only_category is set, only stale entries for that category are removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            tv_dir = root / "series" / "Breaking Bad"
            tv_dir.mkdir(parents=True)
            (tv_dir / "tvshow.nfo").write_text(
                "<tvshow><title>Breaking Bad</title></tvshow>",
                encoding="utf-8",
            )
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_TWO_FOLDER_CONFIG), encoding="utf-8")

            # Full scan: both categories
            _run_phase1(root, output_path, config_path)
            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertIn("movie:Films:Inception (2010)", ids)
            self.assertIn("tv:Series:Breaking Bad", ids)

            # Remove Inception from disk
            shutil.rmtree(root / "films" / "Inception (2010)")

            # Category-scoped scan on Films only
            _run_phase1(root, output_path, config_path, only_category="Films")

            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertNotIn("movie:Films:Inception (2010)", ids)
            # TV entry is outside the scanned category — must not be touched
            self.assertIn("tv:Series:Breaking Bad", ids)


class ScanMediaItemQualityTest(unittest.TestCase):
    """Unit tests for quality preservation in scan_media_item."""

    def _make_cat(self, media_type: str = "movie") -> dict:
        return {"name": "Films", "type": media_type}

    def test_no_quality_without_prev(self):
        """scan_media_item produces no quality field when prev has no quality."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Test (2024)"
            media_dir.mkdir(parents=True)
            (media_dir / "test.mkv").write_text("x", encoding="utf-8")
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), {}, enable_score=False)
            self.assertNotIn("quality", item)

    def test_quality_preserved_from_prev_when_score_disabled(self):
        """scan_media_item copies quality from prev when enable_score=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Test (2024)"
            media_dir.mkdir(parents=True)
            (media_dir / "test.mkv").write_text("x", encoding="utf-8")
            prev = {"quality": {"score": 72, "video": 40, "audio": 32}}
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), prev, enable_score=False)
            self.assertIn("quality", item)
            self.assertEqual(item["quality"]["score"], 72)

    def test_quality_level_stripped_from_prev(self):
        """The 'level' sub-key is removed from preserved quality (same as Phase 3 behavior)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Test (2024)"
            media_dir.mkdir(parents=True)
            (media_dir / "test.mkv").write_text("x", encoding="utf-8")
            prev = {"quality": {"score": 60, "level": "gold"}}
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), prev, enable_score=False)
            self.assertIn("quality", item)
            self.assertNotIn("level", item["quality"])


class DeleteStaleMediaTest(unittest.TestCase):
    """Unit tests for media_repository.delete_stale_media."""

    def _setup_db(self, db_path: pathlib.Path, entries: list[tuple]) -> None:
        conn = db.initialize_database(db_path)
        try:
            for row in entries:
                conn.execute(
                    "INSERT INTO media(id, media_type, title, category) VALUES (?, ?, ?, ?)",
                    row,
                )
            conn.commit()
        finally:
            conn.close()

    def test_deletes_rows_not_in_scanned_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [
                ("movie:Films:A", "movie", "A", "Films"),
                ("movie:Films:B", "movie", "B", "Films"),
            ])

            removed = media_repository.delete_stale_media(
                json_path, {"movie:Films:A"}, db_path=db_path
            )
            self.assertEqual(removed, 1)
            self.assertEqual(_media_ids_in_db(db_path), {"movie:Films:A"})

    def test_category_scope_limits_deletion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [
                ("movie:Films:A", "movie", "A", "Films"),
                ("tv:Series:X", "tv", "X", "Series"),
            ])

            removed = media_repository.delete_stale_media(
                json_path, set(), "Films", db_path=db_path
            )
            self.assertEqual(removed, 1)
            self.assertEqual(_media_ids_in_db(db_path), {"tv:Series:X"})

    def test_safety_guard_empty_ids_no_category(self):
        """When scanned_ids is empty and category is None, nothing is deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [("movie:Films:A", "movie", "A", "Films")])

            removed = media_repository.delete_stale_media(json_path, set(), db_path=db_path)
            self.assertEqual(removed, 0)
            self.assertEqual(len(_media_ids_in_db(db_path)), 1)

    def test_returns_zero_when_nothing_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [("movie:Films:A", "movie", "A", "Films")])

            removed = media_repository.delete_stale_media(
                json_path, {"movie:Films:A"}, db_path=db_path
            )
            self.assertEqual(removed, 0)
            self.assertEqual(_media_ids_in_db(db_path), {"movie:Films:A"})


if __name__ == "__main__":
    unittest.main()
