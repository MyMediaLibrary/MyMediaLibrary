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


def _media_row(db_path: pathlib.Path, media_id: str) -> dict | None:
    """Return a media row as a dict, or None if not found."""
    conn = db.initialize_database(db_path)
    try:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


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

            row = _media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")
            self.assertIsNotNone(row)
            self.assertEqual(row["is_available"], 1)

    def test_removed_media_marked_unavailable(self):
        """Media removed from disk is marked is_available=0 (not deleted) on re-scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            matrix_dir = _make_movie_dir(root / "films", "Matrix (1999)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)

            db_path = _db_path_for(output_path)
            self.assertEqual(_media_row(db_path, "movie:Films:Matrix (1999)")["is_available"], 1)

            shutil.rmtree(matrix_dir)
            _run_phase1(root, output_path, config_path)

            # Matrix still in DB — but marked unavailable
            row = _media_row(db_path, "movie:Films:Matrix (1999)")
            self.assertIsNotNone(row)
            self.assertEqual(row["is_available"], 0)
            # last_seen_at unchanged (was last seen before the removal)
            self.assertIsNotNone(row["last_seen_at"])
            # Inception stays available
            self.assertEqual(_media_row(db_path, "movie:Films:Inception (2010)")["is_available"], 1)

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

    def test_restored_media_becomes_available_again(self):
        """A previously unavailable media is marked available again when it returns on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            # Keep Matrix on disk so scanned_ids is never empty (safety guard would block otherwise)
            _make_movie_dir(root / "films", "Matrix (1999)")
            inception_dir = _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            # First scan: both available
            _run_phase1(root, output_path, config_path)
            # Remove Inception and re-scan: Matrix scanned, Inception becomes unavailable
            shutil.rmtree(inception_dir)
            _run_phase1(root, output_path, config_path)
            self.assertEqual(_media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")["is_available"], 0)

            # Restore Inception and re-scan: available again
            _make_movie_dir(root / "films", "Inception (2010)")
            _run_phase1(root, output_path, config_path)
            self.assertEqual(_media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")["is_available"], 1)

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

            row = _media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")
            self.assertIsNotNone(row)
            self.assertEqual(row["is_available"], 1)

    def test_first_seen_at_preserved_on_rescan(self):
        """first_seen_at is never overwritten once set — it marks the initial appearance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)
            row1 = _media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")
            first_seen = row1["first_seen_at"]

            _run_phase1(root, output_path, config_path)
            row2 = _media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")
            self.assertEqual(row2["first_seen_at"], first_seen)

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

    def test_media_id_independent_from_filename(self):
        """media_id must not change when the video filename changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            inception_dir = _make_movie_dir(root / "films", "Inception (2010)")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)
            media_id_before = list(json.loads(output_path.read_text())["items"])[0]["id"]

            # Rename the video file (upgrade scenario)
            (inception_dir / "Inception (2010).mkv").rename(inception_dir / "Inception.2010.2160p.BluRay.mkv")
            _run_phase1(root, output_path, config_path)
            media_id_after = list(json.loads(output_path.read_text())["items"])[0]["id"]

            self.assertEqual(media_id_before, media_id_after)

    def test_category_scoped_unavailable(self):
        """When only_category is set, only entries in that category are marked unavailable."""
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

            # Full scan: both categories available
            _run_phase1(root, output_path, config_path)
            db_path = _db_path_for(output_path)
            self.assertEqual(_media_row(db_path, "movie:Films:Inception (2010)")["is_available"], 1)
            self.assertEqual(_media_row(db_path, "tv:Series:Breaking Bad")["is_available"], 1)

            # Remove Inception from disk; category-scoped scan on Films only
            shutil.rmtree(root / "films" / "Inception (2010)")
            _run_phase1(root, output_path, config_path, only_category="Films")

            # Inception marked unavailable (in scanned category)
            self.assertEqual(_media_row(db_path, "movie:Films:Inception (2010)")["is_available"], 0)
            # Breaking Bad untouched (different category)
            self.assertEqual(_media_row(db_path, "tv:Series:Breaking Bad")["is_available"], 1)

    def test_no_global_delete_from_media(self):
        """Phase 1 never issues a global DELETE FROM media — rows are preserved."""
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

            # Both rows exist: Inception (available) + Matrix (unavailable)
            ids = _media_ids_in_db(_db_path_for(output_path))
            self.assertIn("movie:Films:Inception (2010)", ids)
            self.assertIn("movie:Films:Matrix (1999)", ids)


class FilenameExtractionTest(unittest.TestCase):
    """Unit tests for filename extraction in scan_media_item."""

    def _make_cat(self, media_type: str = "movie") -> dict:
        return {"name": "Films", "type": media_type}

    def test_filename_set_for_movie(self):
        """scan_media_item sets filename to the video file name for movies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Inception (2010)"
            media_dir.mkdir(parents=True)
            (media_dir / "Inception.2010.mkv").write_text("x", encoding="utf-8")
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), {}, enable_score=False)
            self.assertEqual(item.get("filename"), "Inception.2010.mkv")

    def test_filename_largest_file_wins_for_movie(self):
        """scan_media_item picks the largest video file when multiple exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Inception (2010)"
            media_dir.mkdir(parents=True)
            (media_dir / "small.mkv").write_bytes(b"x" * 100)
            (media_dir / "main.mkv").write_bytes(b"x" * 1000)
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), {}, enable_score=False)
            self.assertEqual(item.get("filename"), "main.mkv")

    def test_filename_none_if_no_video_files(self):
        """scan_media_item returns None for filename when no video file is found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Empty"
            media_dir.mkdir(parents=True)
            (media_dir / "info.nfo").write_text("<movie/>", encoding="utf-8")
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), {}, enable_score=False)
            self.assertIsNone(item.get("filename"))

    def test_filename_dict_for_tv(self):
        """scan_media_item builds a S/E dict for TV series."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            series_dir = root / "Series" / "Breaking Bad"
            s01 = series_dir / "Season 01"
            s01.mkdir(parents=True)
            (s01 / "Breaking.Bad.S01E01.mkv").write_text("x", encoding="utf-8")
            (s01 / "Breaking.Bad.S01E02.mkv").write_text("x", encoding="utf-8")
            cat = {"name": "Series", "type": "tv"}
            item = scanner.scan_media_item(series_dir, root, cat, {}, enable_score=False)
            fn = item.get("filename")
            self.assertIsInstance(fn, dict)
            self.assertIn("S01", fn)
            self.assertIn("E01", fn["S01"])
            self.assertIn("E02", fn["S01"])

    def test_media_id_independent_from_video_filename(self):
        """media_id is derived from folder name, never from the video filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Inception (2010)"
            media_dir.mkdir(parents=True)
            (media_dir / "inception.mkv").write_text("x", encoding="utf-8")
            item = scanner.scan_media_item(media_dir, root, self._make_cat(), {}, enable_score=False)
            self.assertEqual(item["id"], "movie:Films:Inception (2010)")
            self.assertNotIn("inception.mkv", item["id"])


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


class MarkMediaUnavailableTest(unittest.TestCase):
    """Unit tests for media_repository.mark_media_unavailable."""

    def _setup_db(self, db_path: pathlib.Path, entries: list[tuple]) -> None:
        conn = db.initialize_database(db_path)
        try:
            for row in entries:
                conn.execute(
                    "INSERT INTO media(id, media_type, title, category, is_available) VALUES (?, ?, ?, ?, 1)",
                    row,
                )
            conn.commit()
        finally:
            conn.close()

    def _available(self, db_path: pathlib.Path) -> set[str]:
        conn = db.initialize_database(db_path)
        try:
            rows = conn.execute("SELECT id FROM media WHERE is_available = 1").fetchall()
            return {r["id"] for r in rows}
        finally:
            conn.close()

    def _unavailable(self, db_path: pathlib.Path) -> set[str]:
        conn = db.initialize_database(db_path)
        try:
            rows = conn.execute("SELECT id FROM media WHERE is_available = 0").fetchall()
            return {r["id"] for r in rows}
        finally:
            conn.close()

    def test_marks_rows_not_in_scanned_ids_as_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [
                ("movie:Films:A", "movie", "A", "Films"),
                ("movie:Films:B", "movie", "B", "Films"),
            ])

            marked = media_repository.mark_media_unavailable(
                json_path, {"movie:Films:A"}, db_path=db_path
            )
            self.assertEqual(marked, 1)
            self.assertEqual(self._available(db_path), {"movie:Films:A"})
            self.assertEqual(self._unavailable(db_path), {"movie:Films:B"})

    def test_no_row_deleted(self):
        """mark_media_unavailable never deletes rows — both rows remain in DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [
                ("movie:Films:A", "movie", "A", "Films"),
                ("movie:Films:B", "movie", "B", "Films"),
            ])

            media_repository.mark_media_unavailable(json_path, {"movie:Films:A"}, db_path=db_path)

            all_ids = {r["id"] for r in db.initialize_database(db_path).execute("SELECT id FROM media").fetchall()}
            self.assertEqual(all_ids, {"movie:Films:A", "movie:Films:B"})

    def test_category_scope_limits_update(self):
        """Only entries in the given category are considered for the update."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [
                ("movie:Films:A", "movie", "A", "Films"),
                ("tv:Series:X", "tv", "X", "Series"),
            ])

            # Mark all Films not in scanned set as unavailable
            marked = media_repository.mark_media_unavailable(
                json_path, set(), "Films", db_path=db_path
            )
            self.assertEqual(marked, 1)
            # Series entry must remain available
            self.assertIn("tv:Series:X", self._available(db_path))
            self.assertIn("movie:Films:A", self._unavailable(db_path))

    def test_safety_guard_empty_ids_no_category(self):
        """No update when scanned_ids is empty and no category filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [("movie:Films:A", "movie", "A", "Films")])

            marked = media_repository.mark_media_unavailable(json_path, set(), db_path=db_path)
            self.assertEqual(marked, 0)
            self.assertEqual(self._available(db_path), {"movie:Films:A"})

    def test_returns_zero_when_all_already_available(self):
        """No rows updated if all media in scope are already marked available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library.json"
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            self._setup_db(db_path, [("movie:Films:A", "movie", "A", "Films")])

            marked = media_repository.mark_media_unavailable(
                json_path, {"movie:Films:A"}, db_path=db_path
            )
            self.assertEqual(marked, 0)


class FilenameHistoryTest(unittest.TestCase):
    """Tests for filename_history tracking in the repository."""

    def test_filename_history_updated_when_filename_changes(self):
        """Old filename is appended to filename_history when the video file is replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            inception_dir = root / "films" / "Inception (2010)"
            inception_dir.mkdir(parents=True)
            video = inception_dir / "Inception.2010.mkv"
            video.write_bytes(b"x" * 100)

            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)

            db_path = _db_path_for(output_path)
            row = _media_row(db_path, "movie:Films:Inception (2010)")
            self.assertIsNotNone(row["filename"])
            old_filename_json = row["filename"]

            # Replace with a different (larger) file
            video.unlink()
            (inception_dir / "Inception.2010.2160p.BluRay.mkv").write_bytes(b"x" * 10000)
            _run_phase1(root, output_path, config_path)

            row2 = _media_row(db_path, "movie:Films:Inception (2010)")
            new_filename_json = row2["filename"]
            history_json = row2["filename_history"]

            self.assertNotEqual(new_filename_json, old_filename_json)
            history = json.loads(history_json or "[]")
            self.assertIn(old_filename_json, history)

    def test_filename_history_not_updated_when_filename_unchanged(self):
        """filename_history is not modified when the video file is the same."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            inception_dir = root / "films" / "Inception (2010)"
            inception_dir.mkdir(parents=True)
            (inception_dir / "inception.mkv").write_text("x", encoding="utf-8")

            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_BASIC_CONFIG), encoding="utf-8")

            _run_phase1(root, output_path, config_path)
            _run_phase1(root, output_path, config_path)

            row = _media_row(_db_path_for(output_path), "movie:Films:Inception (2010)")
            history = json.loads(row["filename_history"] or "[]")
            self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
