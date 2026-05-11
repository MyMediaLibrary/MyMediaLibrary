"""Tests for availability filtering in db_export.export_library and media_repository.export_library."""

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import db_export  # noqa: E402


def _make_conn(tmp_dir):
    db_path = pathlib.Path(tmp_dir) / "test.db"
    return db.initialize_database(db_path)


def _insert_media(conn, media_id, title, is_available, category="Movies"):
    data = {
        "id": media_id,
        "title": title,
        "category": category,
        "type": "movie",
        "size": "1 GB",
        "is_available": is_available,
    }
    conn.execute(
        """
        INSERT OR REPLACE INTO media (id, title, category, media_type, size_total, is_available, data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (media_id, title, category, "movie", 0, 1 if is_available else 0, json.dumps(data)),
    )
    conn.commit()


class TestDbExportLibraryAvailability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)
        _insert_media(self.conn, "id_available_1", "Available Movie 1", True)
        _insert_media(self.conn, "id_available_2", "Available Movie 2", True)
        _insert_media(self.conn, "id_absent_1", "Absent Movie 1", False)
        _insert_media(self.conn, "id_absent_2", "Absent Movie 2", False)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_available_returns_only_available(self):
        result = db_export.export_library(self.conn, availability="available")
        self.assertEqual(result["total_items"], 2)
        ids = {item["id"] for item in result["items"]}
        self.assertIn("id_available_1", ids)
        self.assertIn("id_available_2", ids)
        self.assertNotIn("id_absent_1", ids)
        self.assertNotIn("id_absent_2", ids)

    def test_absent_returns_only_absent(self):
        result = db_export.export_library(self.conn, availability="absent")
        self.assertEqual(result["total_items"], 2)
        ids = {item["id"] for item in result["items"]}
        self.assertIn("id_absent_1", ids)
        self.assertIn("id_absent_2", ids)
        self.assertNotIn("id_available_1", ids)
        self.assertNotIn("id_available_2", ids)

    def test_all_returns_all_items(self):
        result = db_export.export_library(self.conn, availability="all")
        self.assertEqual(result["total_items"], 4)

    def test_default_is_available(self):
        result = db_export.export_library(self.conn)
        # Default should be 'available'
        self.assertEqual(result["total_items"], 2)
        for item in result["items"]:
            self.assertTrue(item["is_available"])

    def test_is_available_comes_from_db_column(self):
        # Insert item with stale data_json (is_available=True in JSON but DB has 0)
        stale_data = {"id": "stale_id", "title": "Stale", "is_available": True, "category": "Movies", "type": "movie", "size": "1 GB"}
        self.conn.execute(
            "INSERT OR REPLACE INTO media (id, title, category, media_type, size_total, is_available, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("stale_id", "Stale", "Movies", "movie", 0, 0, json.dumps(stale_data)),
        )
        self.conn.commit()

        # absent filter should include this item because DB says is_available=0
        result = db_export.export_library(self.conn, availability="absent")
        ids = {item["id"] for item in result["items"]}
        self.assertIn("stale_id", ids)

        # Find the stale item and verify is_available is False (from DB, not data_json)
        stale_item = next(i for i in result["items"] if i["id"] == "stale_id")
        self.assertFalse(stale_item["is_available"])

    def test_is_available_field_correct_for_available(self):
        result = db_export.export_library(self.conn, availability="available")
        for item in result["items"]:
            self.assertTrue(item["is_available"])

    def test_is_available_field_correct_for_absent(self):
        result = db_export.export_library(self.conn, availability="absent")
        for item in result["items"]:
            self.assertFalse(item["is_available"])

    def test_is_available_field_correct_for_all(self):
        result = db_export.export_library(self.conn, availability="all")
        available_ids = {"id_available_1", "id_available_2"}
        absent_ids = {"id_absent_1", "id_absent_2"}
        for item in result["items"]:
            if item["id"] in available_ids:
                self.assertTrue(item["is_available"])
            elif item["id"] in absent_ids:
                self.assertFalse(item["is_available"])

    def test_unknown_availability_defaults_to_all(self):
        # Any unrecognized value should be handled (no WHERE clause applied or treated as 'all')
        # We just test it doesn't raise
        result = db_export.export_library(self.conn, availability="bogus")
        # 'bogus' doesn't match any branch, so no WHERE clause — same as 'all'
        self.assertEqual(result["total_items"], 4)


class TestMediaRepositoryExportLibraryAvailability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)
        _insert_media(self.conn, "id_available_1", "Available Movie 1", True)
        _insert_media(self.conn, "id_absent_1", "Absent Movie 1", False)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_available_filter(self):
        try:
            from repositories import media_repository
        except ImportError:
            import repositories.media_repository as media_repository

        result = media_repository.export_library(self.conn, availability="available")
        ids = {item["id"] for item in result["items"]}
        self.assertIn("id_available_1", ids)
        self.assertNotIn("id_absent_1", ids)

    def test_absent_filter(self):
        try:
            from repositories import media_repository
        except ImportError:
            import repositories.media_repository as media_repository

        result = media_repository.export_library(self.conn, availability="absent")
        ids = {item["id"] for item in result["items"]}
        self.assertIn("id_absent_1", ids)
        self.assertNotIn("id_available_1", ids)

    def test_all_filter(self):
        try:
            from repositories import media_repository
        except ImportError:
            import repositories.media_repository as media_repository

        result = media_repository.export_library(self.conn, availability="all")
        ids = {item["id"] for item in result["items"]}
        self.assertIn("id_available_1", ids)
        self.assertIn("id_absent_1", ids)


if __name__ == "__main__":
    unittest.main()
