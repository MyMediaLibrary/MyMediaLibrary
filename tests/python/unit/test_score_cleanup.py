import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402

try:
    from backend import db as _db
except Exception:
    import db as _db  # type: ignore


class ScoreCleanupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cls_tmp = tempfile.TemporaryDirectory()
        cls._db_path = pathlib.Path(cls._cls_tmp.name) / "mymedialibrary.db"
        cls._old_db_env = os.environ.get(_db.DB_PATH_ENV)
        os.environ[_db.DB_PATH_ENV] = str(cls._db_path)
        conn = _db.initialize_database(cls._db_path)
        conn.close()

    @classmethod
    def tearDownClass(cls):
        if cls._old_db_env is None:
            os.environ.pop(_db.DB_PATH_ENV, None)
        else:
            os.environ[_db.DB_PATH_ENV] = cls._old_db_env
        cls._cls_tmp.cleanup()
    def _make_scan_item(self, media_dir, root, cat, prev, enable_score=True, **kwargs):
        item = {
            "path": str(media_dir.relative_to(root)),
            "title": media_dir.name,
            "category": cat["name"],
            "type": cat["type"],
        }
        if enable_score:
            item["quality"] = {"score": 80}
        return item

    def test_category_only_scan_preserves_quality_from_prev_for_other_categories(self):
        """Quality from a previous Phase 3 run is kept for preserved (non-scanned) items."""
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
            by_path = {item["path"]: item for item in payload["items"]}
            # Legacy top-level score field must be stripped everywhere
            for item in payload["items"]:
                self.assertNotIn("score", item)
                self.assertNotIn("runtime", item)
                self.assertNotIn("audio_codec_display", item)
            # Newly scanned movie has no quality (prev had none, score disabled)
            self.assertNotIn("quality", by_path["Movies/MovieA"])
            # Preserved series item retains quality from previous Phase 3 enrichment
            self.assertIn("quality", by_path["Series/ShowA"])

    def test_category_only_scan_preserves_quality_from_prev_when_score_feature_enabled(self):
        """Quality from prev is preserved even when the score feature flag is enabled."""
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
            # Newly scanned movie: no quality (prev had none, Phase 1 never computes quality)
            self.assertNotIn("quality", by_path["Movies/MovieA"])
            # Preserved series item: quality retained from previous Phase 3 run
            self.assertIn("quality", by_path["Series/ShowA"])


if __name__ == "__main__":
    unittest.main()
