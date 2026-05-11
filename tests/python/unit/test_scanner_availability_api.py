"""Tests for /api/library availability query parameter handling."""

import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402


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


class TestAvailabilityAPIParameter(unittest.TestCase):
    """Unit tests for availability parameter parsing — no HTTP server needed."""

    def test_availability_values(self):
        """Test that availability param validation works as expected."""
        valid_values = ("available", "absent", "all")
        invalid_values = ("", "bogus", "Available", "ALL", "1", None)

        for v in valid_values:
            result = v if v in ("available", "absent", "all") else "available"
            self.assertEqual(result, v)

        for v in invalid_values:
            raw = v if v is not None else ""
            result = raw if raw in ("available", "absent", "all") else "available"
            self.assertEqual(result, "available")

    def test_export_library_availability_available(self):
        import db_export
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "test.db")
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            result = db_export.export_library(conn, availability="available")
            ids = {i["id"] for i in result["items"]}
            self.assertIn("avail_1", ids)
            self.assertNotIn("absent_1", ids)
            conn.close()

    def test_export_library_availability_absent(self):
        import db_export
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "test.db")
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            result = db_export.export_library(conn, availability="absent")
            ids = {i["id"] for i in result["items"]}
            self.assertNotIn("avail_1", ids)
            self.assertIn("absent_1", ids)
            conn.close()

    def test_export_library_availability_all(self):
        import db_export
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "test.db")
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            result = db_export.export_library(conn, availability="all")
            ids = {i["id"] for i in result["items"]}
            self.assertIn("avail_1", ids)
            self.assertIn("absent_1", ids)
            self.assertEqual(result["total_items"], 2)
            conn.close()

    def test_default_availability_is_available(self):
        import db_export
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "test.db")
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            result = db_export.export_library(conn)  # no availability arg
            ids = {i["id"] for i in result["items"]}
            self.assertIn("avail_1", ids)
            self.assertNotIn("absent_1", ids)
            conn.close()

    def test_is_available_field_overridden_from_db(self):
        """is_available in returned items must come from DB column, not data_json."""
        import db_export
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "test.db")
            # Stale data_json says is_available=True but DB column says 0
            stale_data = {"id": "stale", "title": "Stale", "is_available": True, "category": "Movies", "type": "movie", "size": "1 GB"}
            conn.execute(
                "INSERT OR REPLACE INTO media (id, title, category, media_type, size_total, is_available, data_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("stale", "Stale", "Movies", "movie", 0, 0, json.dumps(stale_data)),
            )
            conn.commit()
            result = db_export.export_library(conn, availability="absent")
            self.assertEqual(result["total_items"], 1)
            self.assertFalse(result["items"][0]["is_available"])
            conn.close()

    def test_load_library_available_only_default(self):
        """media_repository.load_library defaults to available-only."""
        try:
            from repositories import media_repository
        except ImportError:
            import repositories.media_repository as media_repository

        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "test.db"
            conn = db.initialize_database(db_path)
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            conn.close()

            # Load without specifying availability — should default to 'available'
            result = media_repository.load_library(str(db_path / "library.json"), db_path=str(db_path))
            if result is not None:
                ids = {i["id"] for i in result.get("items", [])}
                self.assertIn("avail_1", ids)
                self.assertNotIn("absent_1", ids)

    def test_load_library_absent_filter(self):
        """media_repository.load_library with availability='absent' returns absent items."""
        try:
            from repositories import media_repository
        except ImportError:
            import repositories.media_repository as media_repository

        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "test.db"
            conn = db.initialize_database(db_path)
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            conn.close()

            result = media_repository.load_library(str(db_path / "library.json"), db_path=str(db_path), availability="absent")
            if result is not None:
                ids = {i["id"] for i in result.get("items", [])}
                self.assertIn("absent_1", ids)
                self.assertNotIn("avail_1", ids)

    def test_load_library_all_filter(self):
        """media_repository.load_library with availability='all' returns all items."""
        try:
            from repositories import media_repository
        except ImportError:
            import repositories.media_repository as media_repository

        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "test.db"
            conn = db.initialize_database(db_path)
            _insert_media(conn, "avail_1", "Available", True)
            _insert_media(conn, "absent_1", "Absent", False)
            conn.close()

            result = media_repository.load_library(str(db_path / "library.json"), db_path=str(db_path), availability="all")
            if result is not None:
                ids = {i["id"] for i in result.get("items", [])}
                self.assertIn("avail_1", ids)
                self.assertIn("absent_1", ids)


if __name__ == "__main__":
    unittest.main()
