"""Regression tests: export_library scanned_at must come from scan_runs, never epoch 1970."""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
from repositories import media_repository  # noqa: E402


def _make_conn(tmp_dir):
    db_path = pathlib.Path(tmp_dir) / "test.db"
    return db.initialize_database(db_path)


def _insert_media(conn, media_id="m1", title="Movie", is_available=1):
    conn.execute(
        "INSERT OR REPLACE INTO media (id, title, category, media_type, size_total, is_available)"
        " VALUES (?, ?, 'Movies', 'movie', 0, ?)",
        (media_id, title, is_available),
    )
    conn.commit()


def _insert_scan_run(conn, status, started_at, completed_at=None):
    conn.execute(
        "INSERT INTO scan_runs (trigger_type, mode, status, started_at, completed_at)"
        " VALUES ('manual', 'default', ?, ?, ?)",
        (status, started_at, completed_at),
    )
    conn.commit()


class TestScannedAtFromScanRuns(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = _make_conn(self.tmp.name)
        _insert_media(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_no_scan_runs_returns_none(self):
        result = media_repository.export_library(self.conn)
        self.assertIsNone(result["scanned_at"],
            "scanned_at must be None when no scan has ever run — not epoch 1970")

    def test_completed_scan_uses_completed_at(self):
        _insert_scan_run(self.conn, "completed",
                         started_at="2026-05-20T10:00:00+00:00",
                         completed_at="2026-05-20T10:05:00+00:00")
        result = media_repository.export_library(self.conn)
        self.assertEqual(result["scanned_at"], "2026-05-20T10:05:00+00:00",
            "completed scan must use completed_at, not started_at")

    def test_running_scan_uses_started_at(self):
        _insert_scan_run(self.conn, "running",
                         started_at="2026-05-20T11:00:00+00:00")
        result = media_repository.export_library(self.conn)
        self.assertEqual(result["scanned_at"], "2026-05-20T11:00:00+00:00",
            "running scan must use started_at when completed_at is absent")

    def test_latest_scan_wins(self):
        _insert_scan_run(self.conn, "completed",
                         started_at="2026-05-19T08:00:00+00:00",
                         completed_at="2026-05-19T08:10:00+00:00")
        _insert_scan_run(self.conn, "completed",
                         started_at="2026-05-20T09:00:00+00:00",
                         completed_at="2026-05-20T09:15:00+00:00")
        result = media_repository.export_library(self.conn)
        self.assertEqual(result["scanned_at"], "2026-05-20T09:15:00+00:00",
            "must return the most recent scan, not an older one")

    def test_empty_media_table_no_scan_runs_returns_none(self):
        conn2 = _make_conn(self.tmp.name + "_empty")
        try:
            result = media_repository.export_library(conn2)
            self.assertIsNone(result["scanned_at"],
                "empty library with no scan_runs must return scanned_at=None")
        finally:
            conn2.close()

    def test_empty_media_table_with_completed_scan_returns_timestamp(self):
        conn2 = _make_conn(self.tmp.name + "_empty2")
        try:
            _insert_scan_run(conn2, "completed",
                             started_at="2026-05-20T07:00:00+00:00",
                             completed_at="2026-05-20T07:30:00+00:00")
            result = media_repository.export_library(conn2)
            self.assertEqual(result["scanned_at"], "2026-05-20T07:30:00+00:00",
                "empty media table must still report the last scan timestamp")
        finally:
            conn2.close()

    def test_scanned_at_is_never_epoch(self):
        """Guard against the 01/01/1970 regression."""
        _insert_scan_run(self.conn, "completed",
                         started_at="2026-05-20T10:00:00+00:00",
                         completed_at="2026-05-20T10:05:00+00:00")
        result = media_repository.export_library(self.conn)
        ts = result.get("scanned_at") or ""
        self.assertFalse(ts.startswith("1970"),
            f"scanned_at must never be epoch; got: {ts!r}")


if __name__ == "__main__":
    unittest.main()
