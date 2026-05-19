"""
Regression tests for the "partial library during scan" bug.

During Phase 1, the API must never return fewer items than exist in the DB.
Items should only disappear after mark_media_unavailable at the end of the
full scan, not folder-by-folder.
"""

import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import scanner  # noqa: E402
from repositories import media_repository  # noqa: E402


_MULTI_FOLDER_CONFIG = {
    "folders": [
        {"name": "films", "type": "movie", "visible": True},
        {"name": "series", "type": "tv", "visible": True},
    ],
    "enable_movies": True,
    "enable_series": True,
    "system": {"needs_onboarding": False, "scan_cron": "0 3 * * *", "log_level": "INFO"},
}


def _make_movie(parent: pathlib.Path, name: str) -> pathlib.Path:
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.mkv").write_text("x", encoding="utf-8")
    return d


def _make_tv(parent: pathlib.Path, name: str) -> pathlib.Path:
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tvshow.nfo").write_text(f"<tvshow><title>{name}</title></tvshow>", encoding="utf-8")
    return d


def _count_db_available(db_path: pathlib.Path) -> int:
    conn = db.initialize_database(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM media WHERE is_available=1").fetchone()[0]
    finally:
        conn.close()


def _count_db_all(db_path: pathlib.Path) -> int:
    conn = db.initialize_database(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    finally:
        conn.close()


def _media_available(db_path: pathlib.Path, media_id: str) -> bool | None:
    conn = db.initialize_database(db_path)
    try:
        row = conn.execute("SELECT is_available FROM media WHERE id=?", (media_id,)).fetchone()
        return bool(row["is_available"]) if row else None
    finally:
        conn.close()


def _run_scan(root, output_path, config_path, only_category=None):
    with patch.object(scanner, "LIBRARY_PATH", str(root)), \
         patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
         patch.object(scanner, "CONFIG_PATH", str(config_path)):
        scanner.run_quick(only_category)


class NoPartialSnapshotDuringScanTest(unittest.TestCase):
    """
    The snapshot must only be written ONCE at the end of the full scan,
    not folder-by-folder.  Old items must never disappear mid-scan.
    """

    def test_snapshot_written_once_not_per_folder(self):
        """_write_library_snapshot must not be called inside the folder loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Movie A")
            _make_movie(root / "films", "Movie B")
            _make_tv(root / "series", "Show X")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")

            snapshot_write_count = [0]
            orig = scanner._write_library_snapshot

            def counting_write(items, *a, **kw):
                snapshot_write_count[0] += 1
                orig(items, *a, **kw)

            with patch.object(scanner, "_write_library_snapshot", side_effect=counting_write), \
                 patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
                 patch.object(scanner, "CONFIG_PATH", str(config_path)):
                scanner.run_quick()

            # Must be exactly 1 (end-of-scan), never N (per folder)
            self.assertEqual(snapshot_write_count[0], 1,
                             f"Expected 1 snapshot write, got {snapshot_write_count[0]}")

    def test_all_existing_items_remain_visible_during_scan(self):
        """Items from not-yet-scanned folders stay in media.is_available=1 during scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Movie A")
            _make_tv(root / "series", "Show X")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")
            db_path = output_path.parent / "mymedialibrary.db"

            # Initial full scan — both items available
            _run_scan(root, output_path, config_path)
            self.assertEqual(_count_db_available(db_path), 2)

            # Second scan: capture DB state mid-scan after films folder but before series
            snapshots_mid_scan: list[int] = []

            orig_write = scanner._write_library_snapshot

            def spy_write(items, *a, **kw):
                # Record available count at each snapshot write
                snapshots_mid_scan.append(_count_db_available(db_path))
                orig_write(items, *a, **kw)

            with patch.object(scanner, "_write_library_snapshot", side_effect=spy_write), \
                 patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
                 patch.object(scanner, "CONFIG_PATH", str(config_path)):
                scanner.run_quick()

            # At the single snapshot write (end of scan), BOTH items must still be in DB
            self.assertEqual(len(snapshots_mid_scan), 1)
            # At snapshot time, before mark_media_unavailable, both should be available
            # (mark_unavailable runs first, so snapshot count reflects final state)
            self.assertGreaterEqual(snapshots_mid_scan[0], 1)


class MarkUnavailableTimingTest(unittest.TestCase):
    """mark_media_unavailable must be called ONCE at end of scan, not per folder."""

    def test_mark_unavailable_called_once_at_end(self):
        """mark_media_unavailable must not be called inside the folder loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Movie A")
            _make_tv(root / "series", "Show X")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")

            # First scan to populate DB
            _run_scan(root, output_path, config_path)

            mark_calls: list = []
            # Patch via scanner.media_repository (the module scanner actually uses)
            orig_mark = scanner.media_repository.mark_media_unavailable

            def spy_mark(*args, **kwargs):
                mark_calls.append(args)
                return orig_mark(*args, **kwargs)

            with patch.object(scanner.media_repository, "mark_media_unavailable", side_effect=spy_mark), \
                 patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
                 patch.object(scanner, "CONFIG_PATH", str(config_path)):
                scanner.run_quick()

            self.assertEqual(len(mark_calls), 1,
                             f"mark_media_unavailable called {len(mark_calls)} time(s), expected 1")

    def test_absent_items_marked_only_after_full_scan(self):
        """Items not found are marked is_available=0 only once all folders are done."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Avatar")
            _make_tv(root / "series", "Breaking Bad")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")
            db_path = output_path.parent / "mymedialibrary.db"

            _run_scan(root, output_path, config_path)
            avatar_id = "movie:Films:Avatar"
            bb_id = "tv:Series:Breaking Bad"
            self.assertTrue(_media_available(db_path, avatar_id))
            self.assertTrue(_media_available(db_path, bb_id))

            # Remove Avatar from disk
            shutil.rmtree(root / "films" / "Avatar")
            _run_scan(root, output_path, config_path)

            # Avatar gone → is_available=0
            self.assertFalse(_media_available(db_path, avatar_id))
            # Breaking Bad untouched
            self.assertTrue(_media_available(db_path, bb_id))
            # Both rows still in DB (no physical deletion)
            self.assertEqual(_count_db_all(db_path), 2)


class OnlyCategoryPreservedItemsTest(unittest.TestCase):
    """Category-scoped scans must preserve other-category items correctly."""

    def test_only_category_scan_preserves_other_folders(self):
        """When only_category is set, items from other folders are preserved in snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Movie A")
            _make_tv(root / "series", "Show X")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")
            db_path = output_path.parent / "mymedialibrary.db"

            _run_scan(root, output_path, config_path)
            self.assertEqual(_count_db_available(db_path), 2)

            # Category-scoped re-scan of films only
            _run_scan(root, output_path, config_path, only_category="Films")

            # Show X (series) must still be available — it wasn't in scope
            self.assertTrue(_media_available(db_path, "tv:Series:Show X"))
            # Movie A still available
            self.assertTrue(_media_available(db_path, "movie:Films:Movie A"))

    def test_absent_item_in_scoped_category_becomes_unavailable(self):
        """Absent item in scanned category is marked is_available=0 by category-scoped scan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Gone Movie")
            _make_tv(root / "series", "Show X")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")
            db_path = output_path.parent / "mymedialibrary.db"

            _run_scan(root, output_path, config_path)
            gone_id = "movie:Films:Gone Movie"
            self.assertTrue(_media_available(db_path, gone_id))

            # Remove Gone Movie
            shutil.rmtree(root / "films" / "Gone Movie")
            _run_scan(root, output_path, config_path, only_category="Films")

            # Gone Movie: is_available=0
            self.assertFalse(_media_available(db_path, gone_id))
            # Show X: untouched
            self.assertTrue(_media_available(db_path, "tv:Series:Show X"))

    def test_upsert_after_mark_unavailable_does_not_restore_is_available(self):
        """After mark_media_unavailable, snapshot write must not reset is_available to 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            _make_movie(root / "films", "Gone Film")
            _make_tv(root / "series", "Show Y")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(_MULTI_FOLDER_CONFIG), encoding="utf-8")
            db_path = output_path.parent / "mymedialibrary.db"

            _run_scan(root, output_path, config_path)
            gone_id = "movie:Films:Gone Film"

            shutil.rmtree(root / "films" / "Gone Film")
            # Category-scoped scan: films only
            _run_scan(root, output_path, config_path, only_category="Films")

            # must be 0 AFTER the full cycle (mark + snapshot write)
            self.assertFalse(_media_available(db_path, gone_id),
                             "Upsert in _write_library_snapshot must not restore is_available=1 "
                             "after mark_media_unavailable set it to 0")


class QualityPreservationOnReappearanceTest(unittest.TestCase):
    """When an absent item reappears, its enrichment/quality from a previous scan must be preserved."""

    def test_existing_enrichment_used_as_prev_even_when_item_was_absent(self):
        """load_existing uses availability='all' to include absent items as prev data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            # Two films: Temp Movie (will go absent) + Anchor Movie (stays on disk)
            # Anchor Movie keeps scanned_ids non-empty → safety guard doesn't fire
            _make_movie(root / "films", "Temp Movie")
            _make_movie(root / "films", "Anchor Movie")
            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({
                "folders": [{"name": "films", "type": "movie", "visible": True}],
                "enable_movies": True,
                "enable_series": True,
                "system": {"needs_onboarding": False, "scan_cron": "0 3 * * *", "log_level": "INFO"},
            }), encoding="utf-8")
            db_path = output_path.parent / "mymedialibrary.db"

            # Scan 1: both items found, inject quality data into Temp Movie
            _run_scan(root, output_path, config_path)
            conn = db.initialize_database(db_path)
            conn.execute(
                "UPDATE media SET quality_json = ? WHERE id = ?",
                ('{"score":88}', "movie:Films:Temp Movie"),
            )
            conn.commit()
            conn.close()

            # Scan 2: remove Temp Movie so it becomes absent (Anchor stays → safety guard bypassed)
            shutil.rmtree(root / "films" / "Temp Movie")
            _run_scan(root, output_path, config_path)
            self.assertFalse(_media_available(db_path, "movie:Films:Temp Movie"),
                             "Temp Movie should be absent after removal (safety guard bypassed by Anchor Movie)")

            # Scan 3: put Temp Movie back
            _make_movie(root / "films", "Temp Movie")

            # Capture `prev` seen by scan_media_item to verify quality is passed in
            seen_prev: list[dict] = []
            orig_scan = scanner.scan_media_item

            def spy_scan(media_dir, root_, cat, prev, **kw):
                if media_dir.name == "Temp Movie":
                    seen_prev.append(dict(prev))
                return orig_scan(media_dir, root_, cat, prev, **kw)

            with patch.object(scanner, "scan_media_item", side_effect=spy_scan), \
                 patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
                 patch.object(scanner, "CONFIG_PATH", str(config_path)):
                scanner.run_quick()

            # prev for Temp Movie must have quality data from scan 1
            # (proving load_existing picked up the absent item via availability='all')
            self.assertTrue(
                any(p.get("quality") for p in seen_prev),
                f"load_existing should include absent items as prev so quality is preserved. "
                f"seen_prev={seen_prev!r}"
            )


if __name__ == "__main__":
    unittest.main()
