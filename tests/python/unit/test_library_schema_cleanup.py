import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class LibrarySchemaCleanupTest(unittest.TestCase):
    def test_enrich_stores_raw_provider_names_and_drops_legacy_root_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Films"],
                        "items": [
                            {
                                "title": "Movie",
                                "type": "movie",
                                "category": "Films",
                                "tmdb_id": "123",
                                "providers": [],
                                "providers_fetched": False,
                            }
                        ],
                        "config": {"library_path": "/library"},
                        "meta": {"score_enabled": True},
                        "providers_meta": {"Netflix": {"logo": "x"}},
                        "providers_raw": ["Netflix Standard with Ads"],
                        "providers_raw_meta": {"Netflix Standard with Ads": {"logo": "x"}},
                        "enriched_at": "2026-04-19T00:00:00",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "https://example.test", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "load_provider_map", return_value={}), \
                 patch.object(
                     scanner,
                     "fetch_providers",
                     return_value=[
                         {
                             "raw_name": "Netflix Standard with Ads",
                             "name": "Netflix",
                             "logo": None,
                             "logo_url": None,
                         }
                     ],
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]

            self.assertEqual(item["providers"], ["Netflix Standard with Ads"])
            self.assertTrue(item["providers_fetched"])
            for root_key in ("config", "meta", "providers_meta", "providers_raw", "providers_raw_meta", "enriched_at"):
                self.assertNotIn(root_key, payload)

    def test_enrich_cleans_raw_provider_strings_and_excludes_autres(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Films"],
                        "items": [
                            {
                                "title": "Movie",
                                "type": "movie",
                                "category": "Films",
                                "tmdb_id": "123",
                                "providers": [],
                                "providers_fetched": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "https://example.test", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "load_provider_map", return_value={}), \
                 patch.object(
                     scanner,
                     "fetch_providers",
                     return_value=[
                         {"raw_name": "  HBO   Max. Amazon Channel. ", "name": "HBO Max", "logo": None, "logo_url": None},
                         {"raw_name": "Autres", "name": "Autres", "logo": None, "logo_url": None},
                         {"raw_name": "Netflix   ", "name": "Netflix", "logo": None, "logo_url": None},
                         {"raw_name": "Netflix", "name": "Netflix", "logo": None, "logo_url": None},
                     ],
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item["providers"], ["HBO Max. Amazon Channel", "Netflix"])
            self.assertNotIn("Autres", item["providers"])

    def test_sanitize_item_converts_unknown_sentinels_to_null(self):
        item = {
            "audio_codec": "UNKNOWN",
            "audio_languages_simple": "unknown",
            "codec": "Unknown",
            "resolution": "  unknown  ",
            "providers": [" Netflix  "],
        }
        clean = scanner._sanitize_item_for_library_json(item)
        self.assertIsNone(clean["audio_codec"])
        self.assertIsNone(clean["audio_languages_simple"])
        self.assertIsNone(clean["codec"])
        self.assertIsNone(clean["resolution"])
        self.assertEqual(clean["providers"], ["Netflix"])


if __name__ == "__main__":
    unittest.main()
