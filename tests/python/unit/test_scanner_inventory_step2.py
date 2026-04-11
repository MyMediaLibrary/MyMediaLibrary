import pathlib
import sys
import tempfile
import unittest
import json
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "conf"))

import scanner  # noqa: E402


class ScannerInventoryStep2Test(unittest.TestCase):
    def test_build_library_inventory_with_movie_and_tv_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)

            movie_dir = root / "Films" / "Inception (2010)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")

            tv_dir = root / "Series" / "Dark"
            season_dir = tv_dir / "Season 01"
            season_dir.mkdir(parents=True)
            (season_dir / "Dark.S01E01.mkv").write_text("x", encoding="utf-8")

            entries = [
                {"media_dir": movie_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"},
                {"media_dir": tv_dir, "cat": {"name": "Series", "type": "tv"}, "title": "Dark"},
            ]

            generated_at = datetime(2026, 4, 11, 23, 55, 0, tzinfo=timezone.utc)
            inventory = scanner.build_library_inventory(entries, scan_mode="full", now=generated_at)

            self.assertEqual(inventory["version"], 1)
            self.assertEqual(inventory["generated_at"], "2026-04-11T23:55:00Z")
            self.assertEqual(inventory["scan_mode"], "full")
            self.assertFalse(inventory["missing_reconciliation"])
            self.assertEqual(len(inventory["items"]), 2)

            movie_item = inventory["items"][0]
            self.assertEqual(movie_item["id"], "movie:Films:Inception (2010)")
            self.assertEqual(movie_item["status"], "present")
            self.assertEqual(movie_item["video_files"][0]["name"], "Inception (2010).mkv")
            self.assertEqual(movie_item["first_seen_at"], "2026-04-11T23:55:00Z")
            self.assertEqual(movie_item["last_seen_at"], "2026-04-11T23:55:00Z")

            tv_item = inventory["items"][1]
            self.assertEqual(tv_item["id"], "tv:Series:Dark")
            self.assertEqual(tv_item["video_files"], [])
            self.assertEqual(len(tv_item["subfolders"]), 1)
            self.assertEqual(tv_item["subfolders"][0]["name"], "Season 01")
            self.assertEqual(tv_item["subfolders"][0]["video_files"][0]["name"], "Dark.S01E01.mkv")

    def test_inventory_write_failure_is_non_blocking(self):
        with patch("scanner.write_json", side_effect=OSError("disk full")):
            scanner.write_inventory_json_non_blocking([], scan_mode="quick")

    def test_invalid_existing_inventory_falls_back_to_current_inventory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = pathlib.Path(tmpdir) / "library_inventory.json"
            output_path.write_text("{ invalid json", encoding="utf-8")

            movie_dir = pathlib.Path(tmpdir) / "Films" / "Inception (2010)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")
            entries = [
                {"media_dir": movie_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"},
            ]

            with patch.object(scanner, "INVENTORY_OUTPUT_PATH", str(output_path)):
                scanner.write_inventory_json_non_blocking(entries, scan_mode="quick")

            written = scanner.load_existing_inventory_document_non_blocking(str(output_path))
            self.assertIsNotNone(written)
            self.assertEqual(len(written["items"]), 1)
            self.assertEqual(written["items"][0]["id"], "movie:Films:Inception (2010)")

    def test_inventory_merge_failure_falls_back_to_current_inventory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = pathlib.Path(tmpdir) / "library_inventory.json"
            output_path.write_text(
                '{"items":[{"id":"movie:Films:Legacy","first_seen_at":"2026-04-01T00:00:00Z"}]}',
                encoding="utf-8",
            )

            movie_dir = pathlib.Path(tmpdir) / "Films" / "Inception (2010)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")
            entries = [
                {"media_dir": movie_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"},
            ]

            with patch.object(scanner, "INVENTORY_OUTPUT_PATH", str(output_path)):
                with patch("scanner.merge_inventory_documents", side_effect=RuntimeError("merge failed")):
                    scanner.write_inventory_json_non_blocking(entries, scan_mode="quick")

            written = scanner.load_existing_inventory_document_non_blocking(str(output_path))
            self.assertIsNotNone(written)
            self.assertEqual(len(written["items"]), 1)
            self.assertEqual(written["items"][0]["id"], "movie:Films:Inception (2010)")

    def test_full_scan_reconciliation_failure_keeps_flow_non_blocking_and_marks_flag_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = pathlib.Path(tmpdir) / "library_inventory.json"
            movie_dir = pathlib.Path(tmpdir) / "Films" / "Inception (2010)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")
            entries = [
                {"media_dir": movie_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"},
            ]

            with patch.object(scanner, "INVENTORY_OUTPUT_PATH", str(output_path)):
                with patch("scanner.reconcile_inventory_missing_states", side_effect=RuntimeError("reconcile failed")):
                    scanner.write_inventory_json_non_blocking(entries, scan_mode="full")

            written = scanner.load_existing_inventory_document_non_blocking(str(output_path))
            self.assertIsNotNone(written)
            self.assertFalse(written["missing_reconciliation"])
            self.assertEqual(len(written["items"]), 1)
            self.assertEqual(written["items"][0]["id"], "movie:Films:Inception (2010)")

    def test_full_scan_can_explicitly_skip_missing_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = pathlib.Path(tmpdir) / "library_inventory.json"
            movie_dir = pathlib.Path(tmpdir) / "Films" / "Inception (2010)"
            movie_dir.mkdir(parents=True)
            (movie_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")
            entries = [
                {"media_dir": movie_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"},
            ]

            with patch.object(scanner, "INVENTORY_OUTPUT_PATH", str(output_path)):
                scanner.write_inventory_json_non_blocking(entries, scan_mode="full", reconcile_missing=False)

            written = scanner.load_existing_inventory_document_non_blocking(str(output_path))
            self.assertIsNotNone(written)
            self.assertFalse(written["missing_reconciliation"])

    def test_run_quick_still_writes_library_json_if_inventory_sidecar_call_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movies = root / "films"
            item_dir = movies / "Inception (2010)"
            item_dir.mkdir(parents=True)
            (item_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")

            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "folders": [{"name": "films", "type": "movie", "visible": True}],
                    "enable_movies": True,
                    "enable_series": True,
                    "system": {"needs_onboarding": False, "scan_cron": "0 3 * * *", "log_level": "INFO"},
                }),
                encoding="utf-8",
            )

            with patch.object(scanner, "LIBRARY_PATH", str(root)):
                with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                    with patch.object(scanner, "CONFIG_PATH", str(config_path)):
                        with patch("scanner.write_inventory_json_non_blocking", side_effect=RuntimeError("boom")):
                            scanner.run_quick(scan_mode="quick")

            with open(output_path, encoding="utf-8") as f:
                written_library = json.load(f)
            self.assertEqual(written_library["total_items"], 1)
            self.assertEqual(written_library["items"][0]["title"], "Inception")

    def test_run_quick_skips_inventory_when_flag_disabled_or_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movies = root / "films"
            item_dir = movies / "Inception (2010)"
            item_dir.mkdir(parents=True)
            (item_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")

            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "folders": [{"name": "films", "type": "movie", "visible": True}],
                    "enable_movies": True,
                    "enable_series": True,
                    "system": {"needs_onboarding": False, "scan_cron": "0 3 * * *", "log_level": "INFO"},
                }),
                encoding="utf-8",
            )

            with patch.object(scanner, "LIBRARY_PATH", str(root)):
                with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                    with patch.object(scanner, "CONFIG_PATH", str(config_path)):
                        with patch("scanner.write_inventory_json_non_blocking") as inventory_write:
                            scanner.run_quick(scan_mode="quick")
                            inventory_write.assert_not_called()

    def test_run_quick_runs_inventory_when_flag_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movies = root / "films"
            item_dir = movies / "Inception (2010)"
            item_dir.mkdir(parents=True)
            (item_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")

            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "folders": [{"name": "films", "type": "movie", "visible": True}],
                    "enable_movies": True,
                    "enable_series": True,
                    "system": {
                        "needs_onboarding": False,
                        "scan_cron": "0 3 * * *",
                        "log_level": "INFO",
                        "inventory_enabled": True,
                    },
                }),
                encoding="utf-8",
            )

            with patch.object(scanner, "LIBRARY_PATH", str(root)):
                with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                    with patch.object(scanner, "CONFIG_PATH", str(config_path)):
                        with patch("scanner.write_inventory_json_non_blocking") as inventory_write:
                            scanner.run_quick(scan_mode="quick")
                            inventory_write.assert_called_once()

    def test_disabling_inventory_does_not_delete_existing_inventory_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movies = root / "films"
            item_dir = movies / "Inception (2010)"
            item_dir.mkdir(parents=True)
            (item_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")

            output_path = pathlib.Path(tmpdir) / "library.json"
            inventory_output_path = pathlib.Path(tmpdir) / "library_inventory.json"
            inventory_output_path.write_text('{"version":1,"items":[{"id":"legacy"}]}', encoding="utf-8")
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "folders": [{"name": "films", "type": "movie", "visible": True}],
                    "enable_movies": True,
                    "enable_series": True,
                    "system": {
                        "needs_onboarding": False,
                        "scan_cron": "0 3 * * *",
                        "log_level": "INFO",
                        "inventory_enabled": False,
                    },
                }),
                encoding="utf-8",
            )

            with patch.object(scanner, "LIBRARY_PATH", str(root)):
                with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                    with patch.object(scanner, "CONFIG_PATH", str(config_path)):
                        with patch.object(scanner, "INVENTORY_OUTPUT_PATH", str(inventory_output_path)):
                            with patch("scanner.write_inventory_json_non_blocking") as inventory_write:
                                scanner.run_quick(scan_mode="quick")
                                inventory_write.assert_not_called()

            self.assertTrue(inventory_output_path.exists())
            self.assertEqual(
                inventory_output_path.read_text(encoding="utf-8"),
                '{"version":1,"items":[{"id":"legacy"}]}',
            )

    def test_run_quick_full_category_scope_does_not_trigger_missing_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir) / "library"
            movies = root / "films"
            item_dir = movies / "Inception (2010)"
            item_dir.mkdir(parents=True)
            (item_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")

            output_path = pathlib.Path(tmpdir) / "library.json"
            config_path = pathlib.Path(tmpdir) / "config.json"
            config_path.write_text(
                json.dumps({
                    "folders": [{"name": "films", "type": "movie", "visible": True}],
                    "enable_movies": True,
                    "enable_series": True,
                    "system": {
                        "needs_onboarding": False,
                        "scan_cron": "0 3 * * *",
                        "log_level": "INFO",
                        "inventory_enabled": True,
                    },
                }),
                encoding="utf-8",
            )

            with patch.object(scanner, "LIBRARY_PATH", str(root)):
                with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                    with patch.object(scanner, "CONFIG_PATH", str(config_path)):
                        with patch("scanner.write_inventory_json_non_blocking") as inventory_write:
                            scanner.run_quick(only_category="Films", scan_mode="full")
                            inventory_write.assert_called_once()
                            _, kwargs = inventory_write.call_args
                            self.assertIn("reconcile_missing", kwargs)
                            self.assertFalse(kwargs["reconcile_missing"])


if __name__ == "__main__":
    unittest.main()
