import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import inventory_helpers  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
