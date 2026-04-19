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
    def test_fetch_providers_collects_all_fr_provider_groups(self):
        response = {
            "watchProviders": {
                "FR": {
                    "flatrate": [{"provider_name": "Netflix"}],
                    "free": [{"provider_name": "Arte"}],
                    "ads": [{"provider_name": "Pluto TV"}],
                    "buy": [{"provider_name": "Canal VOD"}],
                    "rent": [{"provider_name": "Orange VOD"}],
                }
            }
        }
        with patch.object(scanner, "_jsr_get", return_value=response):
            providers = scanner.fetch_providers(tmdb_id="123", is_tv=False, jsr={"enabled": True})
        self.assertEqual([p["raw_name"] for p in providers["flatrate"]], ["Netflix"])
        self.assertEqual([p["raw_name"] for p in providers["free"]], ["Arte"])
        self.assertEqual([p["raw_name"] for p in providers["ads"]], ["Pluto TV"])
        self.assertEqual([p["raw_name"] for p in providers["buy"]], ["Canal VOD"])
        self.assertEqual([p["raw_name"] for p in providers["rent"]], ["Orange VOD"])

    def test_fetch_providers_keeps_distinct_raw_names_even_if_map_would_merge_them(self):
        response = {
            "watchProviders": {
                "FR": {
                    "flatrate": [
                        {"provider_name": "Amazon Prime Video"},
                        {"provider_name": "Prime Video"},
                    ]
                }
            }
        }
        with patch.object(scanner, "_jsr_get", return_value=response):
            providers = scanner.fetch_providers(tmdb_id="123", is_tv=False, jsr={"enabled": True})
        self.assertEqual([p["raw_name"] for p in providers["flatrate"]], ["Amazon Prime Video", "Prime Video"])

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
                 patch.object(
                     scanner,
                     "fetch_providers",
                     return_value={
                         "flatrate": [{"raw_name": "Netflix Standard with Ads", "logo": None, "logo_url": None}],
                         "free": [],
                         "ads": [],
                         "buy": [],
                         "rent": [],
                     },
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]

            self.assertEqual(
                item["providers"],
                {
                    "flatrate": ["Netflix Standard with Ads"],
                    "free": None,
                    "ads": None,
                    "buy": None,
                    "rent": None,
                },
            )
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
                 patch.object(
                     scanner,
                     "fetch_providers",
                     return_value={
                         "flatrate": [
                             {"raw_name": "  HBO   Max. Amazon Channel. ", "logo": None, "logo_url": None},
                             {"raw_name": "Autres", "logo": None, "logo_url": None},
                             {"raw_name": "Netflix   ", "logo": None, "logo_url": None},
                             {"raw_name": "Netflix", "logo": None, "logo_url": None},
                         ],
                         "free": [],
                         "ads": [],
                         "buy": [],
                         "rent": [],
                     },
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item["providers"]["flatrate"], ["HBO Max. Amazon Channel", "Netflix"])
            self.assertNotIn("Autres", item["providers"]["flatrate"])
            self.assertIsNone(item["providers"]["free"])

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
        self.assertEqual(clean["providers"]["flatrate"], ["Netflix"])
        self.assertIsNone(clean["providers"]["free"])


if __name__ == "__main__":
    unittest.main()
