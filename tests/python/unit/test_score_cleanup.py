import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class ScoreCleanupTest(unittest.TestCase):
    def _make_scan_item(self, media_dir, root, cat, prev, enable_score=True):
        item = {
            "path": str(media_dir.relative_to(root)),
            "title": media_dir.name,
            "category": cat["name"],
            "type": cat["type"],
        }
        if enable_score:
            item["quality"] = {"score": 80}
        return item

    def test_category_only_scan_strips_score_fields_from_preserved_items_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "library"
            movies = root / "Movies"
            series = root / "Series"
            (movies / "MovieA").mkdir(parents=True)
            (series / "ShowA").mkdir(parents=True)
            out_path = pathlib.Path(tmp) / "library.json"

            existing = {
                "items": [
                    {
                        "path": "Series/ShowA",
                        "title": "ShowA",
                        "category": "Series",
                        "type": "tv",
                        "quality": {"score": 45},
                        "score": 45,
                    }
                ]
            }
            out_path.write_text(json.dumps(existing), encoding="utf-8")

            cfg = {
                "score": {"enabled": False},
                "system": {"inventory_enabled": False},
                "folders": [
                    {"name": "Movies", "folder": "Movies", "type": "movie", "enabled": True},
                    {"name": "Series", "folder": "Series", "type": "tv", "enabled": True},
                ],
            }
            categories = [
                {"name": "Movies", "folder": "Movies", "type": "movie"},
                {"name": "Series", "folder": "Series", "type": "tv"},
            ]

            with patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "migrate_env_to_config", return_value=None), \
                 patch.object(scanner, "load_config", return_value=cfg), \
                 patch.object(scanner, "sync_folders", return_value=False), \
                 patch.object(scanner, "normalize_folder_enabled_flags", return_value=False), \
                 patch.object(scanner, "build_categories_from_config", return_value=categories), \
                 patch.object(scanner, "scan_media_item", side_effect=self._make_scan_item):
                scanner.run_quick(only_category="Movies")

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            for root_key in ("config", "meta", "providers_meta", "providers_raw", "providers_raw_meta", "enriched_at"):
                self.assertNotIn(root_key, payload)
            for item in payload["items"]:
                self.assertNotIn("quality", item)
                self.assertNotIn("score", item)
                self.assertNotIn("runtime", item)
                self.assertNotIn("audio_codec_display", item)

    def test_category_only_scan_keeps_score_fields_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "library"
            movies = root / "Movies"
            series = root / "Series"
            (movies / "MovieA").mkdir(parents=True)
            (series / "ShowA").mkdir(parents=True)
            out_path = pathlib.Path(tmp) / "library.json"

            existing = {
                "items": [
                    {
                        "path": "Series/ShowA",
                        "title": "ShowA",
                        "category": "Series",
                        "type": "tv",
                        "quality": {"score": 61},
                    }
                ]
            }
            out_path.write_text(json.dumps(existing), encoding="utf-8")

            cfg = {
                "score": {"enabled": True},
                "system": {"inventory_enabled": False},
                "folders": [
                    {"name": "Movies", "folder": "Movies", "type": "movie", "enabled": True},
                    {"name": "Series", "folder": "Series", "type": "tv", "enabled": True},
                ],
            }
            categories = [
                {"name": "Movies", "folder": "Movies", "type": "movie"},
                {"name": "Series", "folder": "Series", "type": "tv"},
            ]

            with patch.object(scanner, "LIBRARY_PATH", str(root)), \
                 patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "migrate_env_to_config", return_value=None), \
                 patch.object(scanner, "load_config", return_value=cfg), \
                 patch.object(scanner, "sync_folders", return_value=False), \
                 patch.object(scanner, "normalize_folder_enabled_flags", return_value=False), \
                 patch.object(scanner, "build_categories_from_config", return_value=categories), \
                 patch.object(scanner, "scan_media_item", side_effect=self._make_scan_item):
                scanner.run_quick(only_category="Movies")

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            for root_key in ("config", "meta", "providers_meta", "providers_raw", "providers_raw_meta", "enriched_at"):
                self.assertNotIn(root_key, payload)
            by_path = {item["path"]: item for item in payload["items"]}
            self.assertIn("quality", by_path["Movies/MovieA"])
            self.assertIn("quality", by_path["Series/ShowA"])
            self.assertIn("score", by_path["Movies/MovieA"]["quality"])
            self.assertNotIn("level", by_path["Movies/MovieA"]["quality"])


if __name__ == "__main__":
    unittest.main()
