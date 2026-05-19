"""Tests for scan_run_repository — one row per scan, no JSON columns."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
from repositories import scan_run_repository as repo  # noqa: E402


def _make_db(tmp_dir: str) -> pathlib.Path:
    path = pathlib.Path(tmp_dir) / "test.db"
    conn = db.initialize_database(path)
    conn.close()
    return path


class CreateAndCompleteTest(unittest.TestCase):
    def test_create_returns_nonzero_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            self.assertGreater(run_id, 0)

    def test_create_sets_running_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="cron", mode="default", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], run_id)
            self.assertEqual(rows[0]["status"], "running")
            self.assertEqual(rows[0]["trigger_type"], "cron")
            self.assertEqual(rows[0]["mode"], "default")

    def test_mark_completed_sets_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            repo.mark_completed(run_id, total_duration_sec=12.5, db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows[0]["status"], "completed")
            self.assertAlmostEqual(rows[0]["total_duration_sec"], 12.5, places=2)
            self.assertIsNotNone(rows[0]["completed_at"])

    def test_mark_failed_sets_status_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="startup", mode="default", db_path=db_path)
            repo.mark_failed(run_id, error="disk full", total_duration_sec=3.0, db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows[0]["status"], "failed")
            self.assertEqual(rows[0]["error"], "disk full")

    def test_unknown_trigger_type_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="bogus_type", mode="default", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows[0]["trigger_type"], "unknown")


class PhaseColumnsTest(unittest.TestCase):
    def test_mark_phase_completed_writes_enabled_duration_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            repo.mark_phase_completed(run_id, "1", duration_sec=5.2, summary="42 items", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            row = rows[0]
            self.assertEqual(row["phase1_enabled"], 1)
            self.assertAlmostEqual(row["phase1_duration_sec"], 5.2, places=2)
            self.assertEqual(row["phase1_summary"], "42 items")

    def test_all_phases_stored_on_same_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            for phase_id, summary in [
                ("1", "100 items"), ("2", "50 probed"), ("3", "10 enriched"),
                ("4", "100 scored"), ("5", "5 recommendations"),
            ]:
                repo.mark_phase_completed(run_id, phase_id, duration_sec=1.0, summary=summary, db_path=db_path)
            repo.mark_completed(run_id, total_duration_sec=5.0, db_path=db_path)
            conn = db.open_connection(db_path)
            count = conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1, "All phases must be on the same row")
            rows = repo.get_recent_scan_runs(db_path=db_path)
            row = rows[0]
            self.assertEqual(row["phase1_summary"], "100 items")
            self.assertEqual(row["phase2_summary"], "50 probed")
            self.assertEqual(row["phase5_summary"], "5 recommendations")

    def test_score_only_phase_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="save_settings", mode="score_only", db_path=db_path)
            repo.mark_phase_completed(run_id, "score_only", duration_sec=2.1, summary="3319 items scored", db_path=db_path)
            repo.mark_completed(run_id, total_duration_sec=2.1, db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            row = rows[0]
            self.assertEqual(row["score_only_enabled"], 1)
            self.assertEqual(row["score_only_summary"], "3319 items scored")

    def test_invalid_phase_id_is_silently_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            run_id = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            repo.mark_phase_completed(run_id, "99", duration_sec=1.0, summary="oops", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows[0]["status"], "running")  # no crash


class ScanRunRecorderTest(unittest.TestCase):
    def test_recorder_start_complete_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            recorder = repo.ScanRunRecorder(trigger_type="manual", mode="default", db_path=db_path)
            recorder.start()
            recorder.record_phase("1", 3.0, "100 items")
            recorder.complete()
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(rows[0]["phase1_summary"], "100 items")

    def test_recorder_fail_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            recorder = repo.ScanRunRecorder(trigger_type="cron", mode="default", db_path=db_path)
            recorder.start()
            recorder.fail("something went wrong")
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows[0]["status"], "failed")
            self.assertEqual(rows[0]["error"], "something went wrong")

    def test_recorder_total_duration_is_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            recorder = repo.ScanRunRecorder(trigger_type="manual", mode="default", db_path=db_path)
            recorder.start()
            time.sleep(0.01)
            recorder.complete()
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertGreater(rows[0]["total_duration_sec"], 0)

    def test_recorder_with_zero_run_id_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            recorder = repo.ScanRunRecorder(trigger_type="manual", mode="default", db_path=db_path)
            # Do NOT call start() — run_id stays 0
            recorder.record_phase("1", 1.0, "should not crash")
            recorder.complete()


class GetRecentScanRunsTest(unittest.TestCase):
    def test_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            id1 = repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            id2 = repo.create_scan_run(trigger_type="cron", mode="default", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            self.assertEqual(rows[0]["id"], id2)
            self.assertEqual(rows[1]["id"], id1)

    def test_limit_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            for _ in range(5):
                repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            rows = repo.get_recent_scan_runs(limit=3, db_path=db_path)
            self.assertEqual(len(rows), 3)

    def test_no_json_columns_in_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _make_db(tmp)
            repo.create_scan_run(trigger_type="manual", mode="default", db_path=db_path)
            rows = repo.get_recent_scan_runs(db_path=db_path)
            row = rows[0]
            for key in row:
                self.assertFalse(key.endswith("_json"), f"JSON column found: {key}")
            self.assertNotIn("summary_json", row)
            self.assertNotIn("phases", row)


if __name__ == "__main__":
    unittest.main()
