"""Regression tests: evolution timeline date field round-trip.

Covers two data paths that can produce added_at=null, silently collapsing
the Evolution stats tab into a blank page:
  1. db_import.py — items from old JSON that have added_at but not first_seen_at
  2. media_repository._reconstruct_item() — first_seen_at NULL with last_seen_at fallback
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


class TestDbImportAddedAtFallback(unittest.TestCase):
    """db_import: old JSON with added_at but no first_seen_at → first_seen_at preserved."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_import_uses_first_seen_at_when_present(self):
        item = _minimal_item("m1", first_seen_at="2026-03-10T08:00:00", added_at="2026-01-01T00:00:00")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT first_seen_at FROM media WHERE id='m1'").fetchone()
        self.assertEqual(row["first_seen_at"], "2026-03-10T08:00:00",
            "first_seen_at should be used when explicitly provided")

    def test_import_falls_back_to_added_at_when_first_seen_at_missing(self):
        item = _minimal_item("m2", added_at="2026-02-15T12:00:00")
        # no first_seen_at key in item
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT first_seen_at FROM media WHERE id='m2'").fetchone()
        self.assertEqual(row["first_seen_at"], "2026-02-15T12:00:00",
            "first_seen_at must fall back to added_at so the evolution timeline is populated")

    def test_import_first_seen_at_null_when_both_missing(self):
        item = _minimal_item("m3")
        with self.conn:
            db_import.upsert_library_item(self.conn, item)
        row = self.conn.execute("SELECT first_seen_at FROM media WHERE id='m3'").fetchone()
        self.assertIsNone(row["first_seen_at"],
            "first_seen_at should be NULL when neither first_seen_at nor added_at is provided")


class TestReconstructItemAddedAt(unittest.TestCase):
    """media_repository.export_library: added_at must never be None when last_seen_at is available."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name, "_repo")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _insert_raw(self, media_id, first_seen_at, last_seen_at):
        self.conn.execute(
            "INSERT OR REPLACE INTO media (id, title, category, media_type, size_total, is_available, first_seen_at, last_seen_at)"
            " VALUES (?, 'Title', 'Movies', 'movie', 0, 1, ?, ?)",
            (media_id, first_seen_at, last_seen_at),
        )
        self.conn.commit()

    def test_added_at_comes_from_first_seen_at_when_both_set(self):
        self._insert_raw("m1", "2026-04-01T10:00:00", "2026-05-01T10:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m1")
        self.assertEqual(item["added_at"], "2026-04-01T10:00:00",
            "added_at should prefer first_seen_at")

    def test_added_at_falls_back_to_last_seen_at_when_first_seen_at_null(self):
        self._insert_raw("m2", None, "2026-03-20T08:00:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m2")
        self.assertEqual(item["added_at"], "2026-03-20T08:00:00",
            "added_at must fall back to last_seen_at when first_seen_at is NULL "
            "— without this the evolution timeline is always empty for migrated items")

    def test_added_at_is_none_when_both_null(self):
        self._insert_raw("m3", None, None)
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m3")
        self.assertIsNone(item["added_at"],
            "added_at is None only when both first_seen_at and last_seen_at are absent")

    def test_evolution_never_epoch(self):
        """Guard: added_at must never produce a date that renders as 01/01/1970."""
        self._insert_raw("m4", "2026-05-15T09:30:00", "2026-05-16T09:30:00")
        result = media_repository.export_library(self.conn)
        item = next(i for i in result["items"] if i["id"] == "m4")
        ts = item.get("added_at") or ""
        self.assertFalse(ts.startswith("1970"), f"added_at must not be epoch; got {ts!r}")


if __name__ == "__main__":
    unittest.main()
