import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import inventory_helpers  # noqa: E402
import scanner  # noqa: E402


class InventoryHelpersTest(unittest.TestCase):
    def test_build_inventory_id(self):
        self.assertEqual(
            inventory_helpers.build_inventory_id("movie", "Films", "Inception (2010)"),
            "movie:Films:Inception (2010)",
        )
        self.assertEqual(
            inventory_helpers.build_inventory_id("tv", "Series", "Dark"),
            "tv:Series:Dark",
        )

    def test_build_inventory_video_file(self):
        result = inventory_helpers.build_inventory_video_file(
            name="Dark.S01E01.mkv",
            first_seen_at="2026-04-01T21:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        self.assertEqual(
            result,
            {
                "name": "Dark.S01E01.mkv",
                "status": "present",
                "first_seen_at": "2026-04-01T21:00:00Z",
                "last_seen_at": "2026-04-11T23:55:00Z",
            },
        )

    def test_build_inventory_subfolder(self):
        file_entry = inventory_helpers.build_inventory_video_file(
            name="Dark.S01E01.mkv",
            first_seen_at="2026-04-01T21:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        result = inventory_helpers.build_inventory_subfolder(
            name="Season 01",
            video_files=[file_entry],
            first_seen_at="2026-04-01T21:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        self.assertEqual(
            result,
            {
                "name": "Season 01",
                "status": "present",
                "first_seen_at": "2026-04-01T21:00:00Z",
                "last_seen_at": "2026-04-11T23:55:00Z",
                "video_files": [
                    {
                        "name": "Dark.S01E01.mkv",
                        "status": "present",
                        "first_seen_at": "2026-04-01T21:00:00Z",
                        "last_seen_at": "2026-04-11T23:55:00Z",
                    }
                ],
            },
        )

    def test_build_inventory_movie_item(self):
        file_entry = inventory_helpers.build_inventory_video_file(
            name="Inception (2010).mkv",
            first_seen_at="2026-04-01T20:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        result = inventory_helpers.build_inventory_movie_item(
            category="Films",
            title="Inception",
            root_folder_name="Inception (2010)",
            root_folder_path="/media/Films/Inception (2010)",
            video_files=[file_entry],
            first_seen_at="2026-04-01T20:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        self.assertEqual(result["id"], "movie:Films:Inception (2010)")
        self.assertEqual(result["media_type"], "movie")
        self.assertEqual(result["root_folder_path"], "/media/Films/Inception (2010)")
        self.assertEqual(result["video_files"], [file_entry])

    def test_build_inventory_tv_item(self):
        file_entry = inventory_helpers.build_inventory_video_file(
            name="Dark.S01E01.mkv",
            first_seen_at="2026-04-01T21:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        subfolder = inventory_helpers.build_inventory_subfolder(
            name="Season 01",
            video_files=[file_entry],
            first_seen_at="2026-04-01T21:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
        )
        result = inventory_helpers.build_inventory_tv_item(
            category="Series",
            title="Dark",
            root_folder_name="Dark",
            root_folder_path="/media/Series/Dark",
            first_seen_at="2026-04-01T21:00:00Z",
            last_seen_at="2026-04-11T23:55:00Z",
            subfolders=[subfolder],
        )
        self.assertEqual(result["id"], "tv:Series:Dark")
        self.assertEqual(result["media_type"], "tv")
        self.assertEqual(result["video_files"], [])
        self.assertEqual(result["subfolders"], [subfolder])

    def test_build_inventory_document_deep_copies_items(self):
        item = {
            "id": "movie:Films:Inception (2010)",
            "video_files": [{"name": "Inception (2010).mkv"}],
        }
        result = inventory_helpers.build_inventory_document(
            items=[item],
            generated_at="2026-04-11T23:55:00Z",
            scan_mode="full",
            missing_reconciliation=True,
        )

        item["video_files"][0]["name"] = "MUTATED.mkv"
        self.assertEqual(result["items"][0]["video_files"][0]["name"], "Inception (2010).mkv")

    def test_full_scan_marks_missing_root_item(self):
        existing_doc = {
            "items": [
                {"id": "movie:Films:Inception (2010)", "status": "present", "first_seen_at": "2026-04-01T00:00:00Z", "last_seen_at": "2026-04-09T00:00:00Z", "video_files": []},
                {"id": "movie:Films:Interstellar (2014)", "status": "present", "first_seen_at": "2026-04-02T00:00:00Z", "last_seen_at": "2026-04-09T00:00:00Z", "video_files": []},
            ]
        }
        current_doc = {
            "items": [
                {"id": "movie:Films:Interstellar (2014)", "status": "present", "first_seen_at": "2026-04-11T00:00:00Z", "last_seen_at": "2026-04-11T00:00:00Z", "video_files": []},
            ]
        }
        merged = inventory_helpers.merge_inventory_documents(existing_doc, current_doc)
        reconciled = inventory_helpers.reconcile_inventory_missing_states(merged)
        by_id = {item["id"]: item for item in reconciled["items"]}
        self.assertEqual(by_id["movie:Films:Inception (2010)"]["status"], "missing")
        self.assertEqual(by_id["movie:Films:Interstellar (2014)"]["status"], "present")

    def test_quick_scan_does_not_mark_missing_root_item(self):
        existing_doc = {
            "items": [
                {"id": "movie:Films:Inception (2010)", "status": "present", "first_seen_at": "2026-04-01T00:00:00Z", "last_seen_at": "2026-04-09T00:00:00Z", "video_files": []},
            ]
        }
        current_doc = {"items": []}
        merged = inventory_helpers.merge_inventory_documents(existing_doc, current_doc)
        self.assertEqual(merged["items"][0]["status"], "present")
        cleaned = inventory_helpers.cleanup_inventory_transient_fields(merged)
        self.assertNotIn("_seen_in_scan", cleaned["items"][0])

    def test_full_scan_marks_missing_subfolder_and_video_file(self):
        existing_doc = {
            "items": [
                {
                    "id": "tv:Series:Dark",
                    "media_type": "tv",
                    "status": "present",
                    "first_seen_at": "2026-04-01T00:00:00Z",
                    "last_seen_at": "2026-04-09T00:00:00Z",
                    "video_files": [],
                    "subfolders": [
                        {
                            "name": "Season 01",
                            "status": "present",
                            "first_seen_at": "2026-04-01T00:00:00Z",
                            "last_seen_at": "2026-04-09T00:00:00Z",
                            "video_files": [
                                {"name": "Dark.S01E01.mkv", "status": "present", "first_seen_at": "2026-04-01T00:00:00Z", "last_seen_at": "2026-04-09T00:00:00Z"},
                            ],
                        },
                        {
                            "name": "Season 02",
                            "status": "present",
                            "first_seen_at": "2026-04-01T00:00:00Z",
                            "last_seen_at": "2026-04-09T00:00:00Z",
                            "video_files": [
                                {"name": "Dark.S02E01.mkv", "status": "present", "first_seen_at": "2026-04-01T00:00:00Z", "last_seen_at": "2026-04-09T00:00:00Z"},
                            ],
                        },
                    ],
                }
            ]
        }
        current_doc = {
            "items": [
                {
                    "id": "tv:Series:Dark",
                    "media_type": "tv",
                    "status": "present",
                    "first_seen_at": "2026-04-11T00:00:00Z",
                    "last_seen_at": "2026-04-11T00:00:00Z",
                    "video_files": [],
                    "subfolders": [
                        {
                            "name": "Season 01",
                            "status": "present",
                            "first_seen_at": "2026-04-11T00:00:00Z",
                            "last_seen_at": "2026-04-11T00:00:00Z",
                            "video_files": [
                                {"name": "Dark.S01E01.mkv", "status": "present", "first_seen_at": "2026-04-11T00:00:00Z", "last_seen_at": "2026-04-11T00:00:00Z"},
                            ],
                        },
                    ],
                }
            ]
        }
        merged = inventory_helpers.merge_inventory_documents(existing_doc, current_doc)
        reconciled = inventory_helpers.reconcile_inventory_missing_states(merged)
        dark_item = reconciled["items"][0]
        season_by_name = {season["name"]: season for season in dark_item["subfolders"]}
        self.assertEqual(season_by_name["Season 02"]["status"], "missing")
        season2_files = {video_file["name"]: video_file for video_file in season_by_name["Season 02"]["video_files"]}
        self.assertEqual(season2_files["Dark.S02E01.mkv"]["status"], "missing")

    def test_missing_item_seen_again_becomes_present_and_keeps_first_seen(self):
        existing_doc = {
            "items": [
                {
                    "id": "movie:Films:Inception (2010)",
                    "status": "missing",
                    "first_seen_at": "2026-04-01T00:00:00Z",
                    "last_seen_at": "2026-04-03T00:00:00Z",
                    "video_files": [
                        {"name": "Inception (2010).mkv", "status": "missing", "first_seen_at": "2026-04-01T00:00:00Z", "last_seen_at": "2026-04-03T00:00:00Z"},
                    ],
                }
            ]
        }
        current_doc = {
            "items": [
                {
                    "id": "movie:Films:Inception (2010)",
                    "status": "present",
                    "first_seen_at": "2026-04-11T00:00:00Z",
                    "last_seen_at": "2026-04-11T00:00:00Z",
                    "video_files": [
                        {"name": "Inception (2010).mkv", "status": "present", "first_seen_at": "2026-04-11T00:00:00Z", "last_seen_at": "2026-04-11T00:00:00Z"},
                    ],
                }
            ]
        }
        merged = inventory_helpers.merge_inventory_documents(existing_doc, current_doc)
        reconciled = inventory_helpers.reconcile_inventory_missing_states(merged)
        item = reconciled["items"][0]
        self.assertEqual(item["status"], "present")
        self.assertEqual(item["first_seen_at"], "2026-04-01T00:00:00Z")
        self.assertEqual(item["last_seen_at"], "2026-04-11T00:00:00Z")

    def test_full_scan_missing_keeps_last_seen_at_and_keeps_entries(self):
        existing_doc = {
            "items": [
                {"id": "movie:Films:Inception (2010)", "status": "present", "first_seen_at": "2026-04-01T00:00:00Z", "last_seen_at": "2026-04-08T00:00:00Z", "video_files": []},
                {"id": "movie:Films:Interstellar (2014)", "status": "present", "first_seen_at": "2026-04-02T00:00:00Z", "last_seen_at": "2026-04-09T00:00:00Z", "video_files": []},
            ]
        }
        current_doc = {
            "items": [
                {"id": "movie:Films:Interstellar (2014)", "status": "present", "first_seen_at": "2026-04-11T00:00:00Z", "last_seen_at": "2026-04-11T00:00:00Z", "video_files": []},
            ]
        }
        merged = inventory_helpers.merge_inventory_documents(existing_doc, current_doc)
        reconciled = inventory_helpers.reconcile_inventory_missing_states(merged)
        by_id = {item["id"]: item for item in reconciled["items"]}
        self.assertEqual(len(reconciled["items"]), 2)
        self.assertEqual(by_id["movie:Films:Inception (2010)"]["last_seen_at"], "2026-04-08T00:00:00Z")

    def test_inventory_missing_reconciliation_default_is_false_during_build(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            item_dir = pathlib.Path(tmp_dir) / "Inception (2010)"
            item_dir.mkdir()
            scanned_entries = [{"media_dir": item_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"}]
            quick_inventory = scanner.build_library_inventory(scanned_entries, scan_mode="quick")
            full_inventory = scanner.build_library_inventory(scanned_entries, scan_mode="full")

        self.assertFalse(quick_inventory["missing_reconciliation"])
        self.assertFalse(full_inventory["missing_reconciliation"])

    def test_written_inventory_sets_missing_reconciliation_by_scan_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = pathlib.Path(tmp_dir) / "library_inventory.json"
            item_dir = pathlib.Path(tmp_dir) / "Films" / "Inception (2010)"
            item_dir.mkdir(parents=True)
            (item_dir / "Inception (2010).mkv").write_text("x", encoding="utf-8")
            scanned_entries = [{"media_dir": item_dir, "cat": {"name": "Films", "type": "movie"}, "title": "Inception"}]

            with patch.object(scanner, "INVENTORY_OUTPUT_PATH", str(output_path)):
                scanner.write_inventory_json_non_blocking(scanned_entries, scan_mode="full")
                full_written = scanner.load_existing_inventory_document_non_blocking(str(output_path))
                scanner.write_inventory_json_non_blocking(scanned_entries, scan_mode="quick")
                quick_written = scanner.load_existing_inventory_document_non_blocking(str(output_path))

        self.assertTrue(full_written["missing_reconciliation"])
        self.assertFalse(quick_written["missing_reconciliation"])


if __name__ == "__main__":
    unittest.main()
