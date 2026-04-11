import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "conf"))

import inventory_helpers  # noqa: E402


class InventoryMergeStep3Test(unittest.TestCase):
    def _doc(self, generated_at: str, items: list[dict]):
        return {
            "version": 1,
            "generated_at": generated_at,
            "scan_mode": "quick",
            "missing_reconciliation": False,
            "items": items,
        }

    def test_merge_without_existing_returns_current(self):
        current = self._doc("2026-04-12T10:00:00Z", [{"id": "movie:Films:Inception (2010)"}])
        merged = inventory_helpers.merge_inventory_documents({"items": []}, current)
        self.assertEqual(merged, current)

    def test_merge_existing_item_preserves_first_seen_and_updates_last_seen(self):
        existing_item = {
            "id": "movie:Films:Inception (2010)",
            "media_type": "movie",
            "category": "Films",
            "title": "Inception",
            "root_folder_path": "/media/Films/Inception (2010)",
            "status": "present",
            "first_seen_at": "2026-04-01T10:00:00Z",
            "last_seen_at": "2026-04-05T10:00:00Z",
            "video_files": [],
        }
        current_item = {
            **existing_item,
            "title": "Inception (Updated)",
            "last_seen_at": "2026-04-12T10:00:00Z",
        }
        merged = inventory_helpers.merge_inventory_items(existing_item, current_item)
        self.assertEqual(merged["first_seen_at"], "2026-04-01T10:00:00Z")
        self.assertEqual(merged["last_seen_at"], "2026-04-12T10:00:00Z")
        self.assertEqual(merged["title"], "Inception (Updated)")
        self.assertEqual(merged["status"], "present")

    def test_merge_adds_new_root_item(self):
        existing = self._doc("2026-04-10T10:00:00Z", [])
        current = self._doc("2026-04-12T10:00:00Z", [{"id": "movie:Films:New Movie"}])
        merged = inventory_helpers.merge_inventory_documents(existing, current)
        self.assertEqual(len(merged["items"]), 1)
        self.assertEqual(merged["items"][0]["id"], "movie:Films:New Movie")

    def test_merge_existing_video_file_preserves_first_seen(self):
        existing_files = [{
            "name": "Dark.S01E01.mkv",
            "status": "present",
            "first_seen_at": "2026-04-01T10:00:00Z",
            "last_seen_at": "2026-04-05T10:00:00Z",
        }]
        current_files = [{
            "name": "Dark.S01E01.mkv",
            "status": "present",
            "first_seen_at": "2026-04-12T10:00:00Z",
            "last_seen_at": "2026-04-12T10:00:00Z",
        }]
        merged = inventory_helpers.merge_inventory_video_files(existing_files, current_files)
        self.assertEqual(merged[0]["first_seen_at"], "2026-04-01T10:00:00Z")
        self.assertEqual(merged[0]["last_seen_at"], "2026-04-12T10:00:00Z")

    def test_merge_adds_new_video_file(self):
        existing_files = []
        current_files = [{
            "name": "Dark.S01E02.mkv",
            "status": "present",
            "first_seen_at": "2026-04-12T10:00:00Z",
            "last_seen_at": "2026-04-12T10:00:00Z",
        }]
        merged = inventory_helpers.merge_inventory_video_files(existing_files, current_files)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "Dark.S01E02.mkv")

    def test_merge_existing_subfolder_preserves_timestamps(self):
        existing_subfolders = [{
            "name": "Season 01",
            "status": "present",
            "first_seen_at": "2026-04-01T10:00:00Z",
            "last_seen_at": "2026-04-05T10:00:00Z",
            "video_files": [],
        }]
        current_subfolders = [{
            "name": "Season 01",
            "status": "present",
            "first_seen_at": "2026-04-12T10:00:00Z",
            "last_seen_at": "2026-04-12T10:00:00Z",
            "video_files": [],
        }]
        merged = inventory_helpers.merge_inventory_subfolders(existing_subfolders, current_subfolders)
        self.assertEqual(merged[0]["first_seen_at"], "2026-04-01T10:00:00Z")
        self.assertEqual(merged[0]["last_seen_at"], "2026-04-12T10:00:00Z")

    def test_old_unseen_elements_are_kept_without_missing_status(self):
        existing = self._doc("2026-04-10T10:00:00Z", [{
            "id": "movie:Films:Legacy",
            "status": "present",
            "first_seen_at": "2026-04-01T10:00:00Z",
            "last_seen_at": "2026-04-05T10:00:00Z",
            "video_files": [],
        }])
        current = self._doc("2026-04-12T10:00:00Z", [])
        merged = inventory_helpers.merge_inventory_documents(existing, current)
        self.assertEqual(len(merged["items"]), 1)
        self.assertEqual(merged["items"][0]["id"], "movie:Films:Legacy")
        self.assertEqual(merged["items"][0]["status"], "present")


if __name__ == "__main__":
    unittest.main()
