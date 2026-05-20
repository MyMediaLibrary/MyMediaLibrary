"""Regression tests: Evolution timeline — added_at field round-trip.

The Evolution stats graph requires items to have varied added_at dates spread
across multiple months. Three layers must cooperate:

  1. media table has added_at column (schema v28) storing filesystem mtime
  2. db_import stores item["added_at"] (scanner's mtime) into that column
  3. _reconstruct_item() reads added_at → first_seen_at → last_seen_at in order
"""

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


class TestSchemaAddedAtColumn(unittest.TestCase):
    """Schema v28: media table must have an added_at column."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_added_at_column_exists(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(media)").fetchall()}
        self.assertIn("added_at", cols, "media table must have added_at column (schema v28)")


class TestDbImportAddedAt(unittest.TestCase):
    """db_import: added_at (filesystem mtime) is stored and preserved correctly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_added_at_stored_when_present(self):
        item = _minimal_item("m1", added_at="2025-11-05T14:30:00", first_seen_at="2026-05-20T10:00:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT added_at FROM media WHERE id='m1'").fetchone()
        self.assertEqual(row["added_at"], "2025-11-05T14:30:00",
            "added_at column must store the scanner's mtime (filesystem add date)")

    def test_added_at_preserved_on_rescan(self):
        item1 = _minimal_item("m2", added_at="2025-08-01T10:00:00", first_seen_at="2025-08-01T10:00:00")
        item2 = _minimal_item("m2", added_at="2026-05-20T10:00:00", first_seen_at="2026-05-20T10:00:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item1)
        with self.conn:
            db_import.upsert_library_item(self.conn, item2)
        row = self.conn.execute("SELECT added_at FROM media WHERE id='m2'").fetchone()
        self.assertEqual(row["added_at"], "2025-08-01T10:00:00",
            "added_at must be preserved on re-scan (COALESCE keeps original mtime)")

    def test_added_at_null_when_not_provided(self):
        item = _minimal_item("m3", first_seen_at="2026-05-20T10:00:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT added_at FROM media WHERE id='m3'").fetchone()
        self.assertIsNone(row["added_at"], "added_at should be NULL when item has no mtime")

    def test_first_seen_at_fallback_for_legacy_json_import(self):
        """Old JSON items had added_at but no first_seen_at — first_seen_at should fallback."""
        item = _minimal_item("m4", added_at="2025-06-15T12:00:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT added_at, first_seen_at FROM media WHERE id='m4'").fetchone()
        self.assertEqual(row["added_at"], "2025-06-15T12:00:00")
        self.assertEqual(row["first_seen_at"], "2025-06-15T12:00:00",
            "first_seen_at must fall back to added_at for legacy JSON items")


class TestReconstructItemAddedAt(unittest.TestCase):
    """_reconstruct_item(): added_at in API uses added_at column first, then fallbacks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name, "_repo")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _insert_raw(self, media_id, added_at=None, first_seen_at=None, last_seen_at=None):
        self.conn.execute(
            "INSERT OR REPLACE INTO media"
            " (id, title, category, media_type, size_total, is_available, added_at, first_seen_at, last_seen_at)"
            " VALUES (?, 'Title', 'Movies', 'movie', 0, 1, ?, ?, ?)",
            (media_id, added_at, first_seen_at, last_seen_at),
        )
        self.conn.commit()

    def test_added_at_column_takes_priority(self):
        self._insert_raw("m1", added_at="2025-07-10T08:00:00",
                         first_seen_at="2026-05-20T10:00:00", last_seen_at="2026-05-20T10:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m1")
        self.assertEqual(item["added_at"], "2025-07-10T08:00:00",
            "added_at column (mtime) must be preferred over first_seen_at/last_seen_at scan times")

    def test_falls_back_to_first_seen_at(self):
        self._insert_raw("m2", added_at=None,
                         first_seen_at="2026-03-01T10:00:00", last_seen_at="2026-05-20T10:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m2")
        self.assertEqual(item["added_at"], "2026-03-01T10:00:00",
            "added_at must fall back to first_seen_at when added_at column is NULL")

    def test_falls_back_to_last_seen_at(self):
        self._insert_raw("m3", added_at=None, first_seen_at=None,
                         last_seen_at="2026-03-20T08:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m3")
        self.assertEqual(item["added_at"], "2026-03-20T08:00:00",
            "added_at must fall back to last_seen_at when both added_at and first_seen_at are NULL")

    def test_added_at_none_when_all_null(self):
        self._insert_raw("m4", added_at=None, first_seen_at=None, last_seen_at=None)
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m4")
        self.assertIsNone(item["added_at"])

    def test_evolution_never_epoch(self):
        self._insert_raw("m5", added_at="2025-09-15T09:30:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m5")
        ts = item.get("added_at") or ""
        self.assertFalse(ts.startswith("1970"), f"added_at must not be epoch; got {ts!r}")

    def test_varied_mtimes_fill_multiple_months(self):
        """Sanity: items with distinct monthly mtimes produce >= 2 allByMonth buckets (hasEnoughData)."""
        dates = [
            ("i1", "2025-08-05T10:00:00"),
            ("i2", "2025-09-12T10:00:00"),
            ("i3", "2025-10-20T10:00:00"),
        ]
        for media_id, ts in dates:
            self._insert_raw(media_id, added_at=ts)
        result = media_repository.export_library(self.conn)
        returned_dates = [i["added_at"] for i in result["items"] if i["added_at"]]
        months = {ts[:7] for ts in returned_dates}
        self.assertGreaterEqual(len(months), 2,
            "items with mtimes across multiple months must produce >= 2 month buckets "
            "so hasEnoughData is true and the Evolution graph is displayed")


if __name__ == "__main__":
    unittest.main()
