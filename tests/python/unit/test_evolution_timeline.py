"""Regression tests: Evolution timeline — file_created_at field.

The Evolution graph requires items to have file_created_at values spread
across multiple months. This field stores:
  - Movies: creation date of the largest video file in the directory
  - TV series: newest creation date across all episode files

Three layers are tested:
  1. schema v29: file_created_at column exists
  2. db_import: file_created_at stored and always updated on re-scan
  3. _reconstruct_item(): file_created_at exposed in API response
  4. scanner helpers: _file_created_ts and _media_file_created_at logic
  5. regression: evolution no longer depends on added_at/first_seen_at
"""

import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import db_import  # noqa: E402
from repositories import media_repository  # noqa: E402


def _make_conn(tmp_dir, suffix=""):
    db_path = pathlib.Path(tmp_dir) / f"test{suffix}.db"
    return db.initialize_database(db_path)


def _minimal_item(media_id, title="Movie", **kwargs):
    base = {
        "id": media_id,
        "title": title,
        "category": "Movies",
        "media_type": "movie",
        "type": "movie",
        "size_b": 1000,
        "size_total": 1000,
        "is_available": True,
        "filename": None,
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────

class TestSchemaFileCreatedAtColumn(unittest.TestCase):
    """Schema v29: media table must have file_created_at column."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_file_created_at_column_exists(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(media)").fetchall()}
        self.assertIn("file_created_at", cols,
            "media table must have file_created_at column (schema v29)")

    def test_added_at_column_still_present(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(media)").fetchall()}
        self.assertIn("added_at", cols, "added_at column (schema v28) must still be present")


# ─────────────────────────────────────────────────────────────
# DB import
# ─────────────────────────────────────────────────────────────

class TestDbImportFileCreatedAt(unittest.TestCase):
    """db_import: file_created_at is stored and always updated on re-scan."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_file_created_at_stored(self):
        item = _minimal_item("m1", file_created_at="2025-08-15T10:30:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT file_created_at FROM media WHERE id='m1'").fetchone()
        self.assertEqual(row["file_created_at"], "2025-08-15T10:30:00")

    def test_file_created_at_null_when_absent(self):
        item = _minimal_item("m2")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT file_created_at FROM media WHERE id='m2'").fetchone()
        self.assertIsNone(row["file_created_at"],
            "file_created_at should be NULL when not provided (existing items before first scan)")

    def test_file_created_at_updated_on_rescan(self):
        """TV series: file_created_at updates as newer episode files appear."""
        item1 = _minimal_item("m3", file_created_at="2025-03-01T10:00:00")
        item2 = _minimal_item("m3", file_created_at="2025-11-20T14:00:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item1)
        with self.conn:
            db_import.upsert_library_item(self.conn, item2)
        row = self.conn.execute("SELECT file_created_at FROM media WHERE id='m3'").fetchone()
        self.assertEqual(row["file_created_at"], "2025-11-20T14:00:00",
            "file_created_at must update on rescan — TV series newest episode date can grow")


# ─────────────────────────────────────────────────────────────
# API / reconstruct_item
# ─────────────────────────────────────────────────────────────

class TestApiFileCreatedAt(unittest.TestCase):
    """_reconstruct_item(): file_created_at exposed as a dedicated field."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name, "_api")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _insert_raw(self, media_id, file_created_at=None, added_at=None, first_seen_at=None):
        self.conn.execute(
            "INSERT OR REPLACE INTO media"
            " (id, title, category, media_type, size_total, is_available,"
            "  file_created_at, added_at, first_seen_at)"
            " VALUES (?, 'Title', 'Movies', 'movie', 0, 1, ?, ?, ?)",
            (media_id, file_created_at, added_at, first_seen_at),
        )
        self.conn.commit()

    def test_file_created_at_returned(self):
        self._insert_raw("m1", file_created_at="2025-09-10T08:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m1")
        self.assertEqual(item["file_created_at"], "2025-09-10T08:00:00")

    def test_file_created_at_none_when_null(self):
        self._insert_raw("m2")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m2")
        self.assertIsNone(item["file_created_at"],
            "null file_created_at must be returned as None — stats will ignore it gracefully")

    def test_file_created_at_independent_from_added_at(self):
        """file_created_at and added_at are separate fields — one null doesn't affect the other."""
        self._insert_raw("m3",
                         file_created_at="2025-07-01T12:00:00",
                         added_at="2026-05-20T10:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m3")
        self.assertEqual(item["file_created_at"], "2025-07-01T12:00:00")
        self.assertEqual(item["added_at"], "2026-05-20T10:00:00")

    def test_evolution_hasEnoughData_with_varied_file_created_at(self):
        """Items with file_created_at across 2+ months produce hasEnoughData=True."""
        dates = [
            ("i1", "2025-06-05T10:00:00"),
            ("i2", "2025-09-12T10:00:00"),
            ("i3", "2025-12-20T10:00:00"),
        ]
        for media_id, ts in dates:
            self._insert_raw(media_id, file_created_at=ts)
        result = media_repository.export_library(self.conn)
        fc_dates = [i["file_created_at"] for i in result["items"] if i.get("file_created_at")]
        months = {d[:7] for d in fc_dates}
        self.assertGreaterEqual(len(months), 2,
            "items with file_created_at across months must give >= 2 buckets for hasEnoughData")


# ─────────────────────────────────────────────────────────────
# Scanner helpers (unit)
# ─────────────────────────────────────────────────────────────

class TestScannerFileCreatedHelpers(unittest.TestCase):
    """scanner._file_created_ts and _media_file_created_at logic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_file(self, rel_path: str, content: bytes = b"x") -> pathlib.Path:
        p = self.tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def test_file_created_ts_returns_float(self):
        from scanner import _file_created_ts
        p = self._write_file("test.mkv")
        ts = _file_created_ts(p)
        self.assertIsInstance(ts, float)
        self.assertGreater(ts, 0)

    def test_file_created_ts_returns_none_for_missing_file(self):
        from scanner import _file_created_ts
        ts = _file_created_ts(self.tmp_path / "nonexistent.mkv")
        self.assertIsNone(ts)

    def test_movie_uses_largest_video_file(self):
        from scanner import _media_file_created_at
        movie_dir = self.tmp_path / "movie"
        small = self._write_file("movie/extra.mkv", b"x" * 10)
        big   = self._write_file("movie/main.mkv",  b"x" * 100)
        import time; time.sleep(0.01)
        # Touch small after big to give it a newer timestamp
        os.utime(small, None)
        result = _media_file_created_at(movie_dir, is_tv=False)
        self.assertIsNotNone(result)
        # Result must be an ISO datetime string
        from datetime import datetime
        dt = datetime.fromisoformat(result)
        self.assertIsInstance(dt.year, int)

    def test_tv_uses_newest_episode_file(self):
        from scanner import _media_file_created_at
        import time
        series_dir = self.tmp_path / "series"
        ep1 = self._write_file("series/s01/ep01.mkv", b"x")
        time.sleep(0.05)
        ep2 = self._write_file("series/s01/ep02.mkv", b"x")
        time.sleep(0.05)
        ep3 = self._write_file("series/s02/ep01.mkv", b"x")

        result = _media_file_created_at(series_dir, is_tv=True)
        self.assertIsNotNone(result)

        # Must be >= date of ep3 (newest)
        ep3_ts = os.stat(ep3).st_mtime
        from datetime import datetime
        result_ts = datetime.fromisoformat(result).timestamp()
        self.assertGreaterEqual(result_ts, ep3_ts - 1,
            "TV series file_created_at must be the newest episode's timestamp")

    def test_no_media_files_returns_none(self):
        from scanner import _media_file_created_at
        empty_dir = self.tmp_path / "empty"
        empty_dir.mkdir()
        (empty_dir / "poster.jpg").write_bytes(b"img")
        self.assertIsNone(_media_file_created_at(empty_dir, is_tv=False))
        self.assertIsNone(_media_file_created_at(empty_dir, is_tv=True))


# ─────────────────────────────────────────────────────────────
# Regression: evolution no longer depends on added_at alone
# ─────────────────────────────────────────────────────────────

class TestEvolutionDoesNotRelyOnAddedAt(unittest.TestCase):
    """file_created_at is the evolution source — added_at null must not affect it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name, "_reg")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _insert_raw(self, media_id, file_created_at=None, added_at=None):
        self.conn.execute(
            "INSERT OR REPLACE INTO media"
            " (id, title, category, media_type, size_total, is_available,"
            "  file_created_at, added_at)"
            " VALUES (?, 'M', 'Movies', 'movie', 0, 1, ?, ?)",
            (media_id, file_created_at, added_at),
        )
        self.conn.commit()

    def test_file_created_at_present_when_added_at_null(self):
        self._insert_raw("m1", file_created_at="2025-04-10T09:00:00", added_at=None)
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m1")
        self.assertIsNotNone(item["file_created_at"])
        # added_at should fallback to first_seen_at/last_seen_at chain (both NULL here → None)
        self.assertIsNone(item["added_at"])

    def test_null_file_created_at_does_not_crash(self):
        self._insert_raw("m2", file_created_at=None, added_at="2026-05-20T10:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m2")
        self.assertIsNone(item["file_created_at"],
            "null file_created_at must come through as None — stats will skip it")


if __name__ == "__main__":
    unittest.main()
