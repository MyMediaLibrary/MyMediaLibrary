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
        self.assertEqual([p["raw_name"] for p in providers], ["Netflix", "Arte", "Pluto TV", "Canal VOD", "Orange VOD"])

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
        self.assertEqual([p["raw_name"] for p in providers], ["Amazon Prime Video", "Prime Video"])

    def test_fetch_providers_tv_supports_results_structure_and_multiple_regions(self):
        response = {
            "watchProviders": {
                "results": {
                    "FR": {
                        "flatrate": [{"provider_name": "Disney+"}],
                        "buy": [{"provider_name": "Canal VOD"}],
                    },
                    "US": {
                        "flatrate": [{"provider_name": "Hulu"}, {"provider_name": "Disney+"}],
                        "ads": [{"provider_name": "Tubi"}],
                    },
                }
            }
        }
        with patch.object(scanner, "_jsr_get", return_value=response):
            providers = scanner.fetch_providers(tmdb_id="999", is_tv=True, jsr={"enabled": True})
        self.assertEqual([p["raw_name"] for p in providers], ["Disney+", "Hulu", "Tubi", "Canal VOD"])

    def test_resolve_ids_from_search_prefers_tv_title_and_year(self):
        response = {
            "results": [
                {"mediaType": "movie", "id": 1, "title": "Paradise", "releaseDate": "2025-01-01", "tvdbId": 11},
                {"mediaType": "tv", "id": 99, "name": "Paradise", "firstAirDate": "2024-01-01", "tvdbId": 991},
                {"mediaType": "tv", "id": 321, "name": "Paradise", "firstAirDate": "2025-01-26", "tvdbId": 3321},
            ]
        }
        with patch.object(scanner, "_jsr_get", return_value=response):
            resolved = scanner._resolve_ids_from_search("Paradise", 2025, is_tv=True, jsr={"enabled": True})
        self.assertEqual(resolved["tmdb_id"], 321)
        self.assertEqual(resolved["tvdb_id"], 3321)

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
                     return_value=[{"raw_name": "Netflix Standard with Ads", "logo": None, "logo_url": None}],
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]

            self.assertEqual(
                item["providers"],
                ["Netflix Standard with Ads"],
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
                     return_value=[
                         {"raw_name": "  HBO   Max. Amazon Channel. ", "logo": None, "logo_url": None},
                         {"raw_name": "Autres", "logo": None, "logo_url": None},
                         {"raw_name": "Netflix   ", "logo": None, "logo_url": None},
                         {"raw_name": "Netflix", "logo": None, "logo_url": None},
                     ],
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item["providers"], ["HBO Max. Amazon Channel", "Netflix"])
            self.assertNotIn("Autres", item["providers"])

    def test_enrich_tv_item_without_providers_still_marks_fetch_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Series"],
                        "items": [
                            {
                                "title": "Paradise",
                                "type": "tv",
                                "category": "Series",
                                "tmdb_id": "7777",
                                "tvdb_id": "7777",
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
                     return_value=[],
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertTrue(item["providers_fetched"])
            self.assertEqual(item["providers"], [])

    def test_enrich_tv_item_on_fetch_error_keeps_providers_fetched_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Series"],
                        "items": [
                            {
                                "title": "Paradise",
                                "type": "tv",
                                "category": "Series",
                                "tmdb_id": "7777",
                                "tvdb_id": "7777",
                                "providers": ["Legacy"],
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
                 patch.object(scanner, "fetch_providers", return_value=scanner._FETCH_ERROR):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertFalse(item["providers_fetched"])
            self.assertEqual(item["providers"], ["Legacy"])

    def test_enrich_tv_retries_with_search_resolved_tvdb_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 3,
                        "categories": ["Series"],
                        "items": [
                            {
                                "title": "Paradise",
                                "year": "2025",
                                "type": "tv",
                                "category": "Series",
                                "tmdb_id": None,
                                "tvdb_id": "bad-id-1",
                                "providers": [],
                                "providers_fetched": False,
                            },
                            {
                                "title": "Andor",
                                "year": "2022",
                                "type": "tv",
                                "category": "Series",
                                "tmdb_id": None,
                                "tvdb_id": "bad-id-2",
                                "providers": [],
                                "providers_fetched": False,
                            },
                            {
                                "title": "La Casa de Papel",
                                "year": "2017",
                                "type": "tv",
                                "category": "Series",
                                "tmdb_id": None,
                                "tvdb_id": "bad-id-3",
                                "providers": [],
                                "providers_fetched": False,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            providers_disney = [{"raw_name": "Disney+", "logo": None, "logo_url": None}]
            providers_hulu = [{"raw_name": "Hulu", "logo": None, "logo_url": None}]
            providers_netflix = [{"raw_name": "Netflix", "logo": None, "logo_url": None}]

            def fake_fetch(identifier, is_tv, jsr):
                mapping = {
                    "bad-id-1": scanner._JSR_NOT_FOUND,
                    "bad-id-2": scanner._JSR_NOT_FOUND,
                    "bad-id-3": scanner._JSR_NOT_FOUND,
                    "9991": providers_disney,
                    "9992": providers_hulu,
                    "9993": providers_netflix,
                    # TMDB fallback path should stay unused in this test.
                    "9001": scanner._JSR_NOT_FOUND,
                    "9002": scanner._JSR_NOT_FOUND,
                    "9003": scanner._JSR_NOT_FOUND,
                }
                return mapping.get(str(identifier), scanner._JSR_NOT_FOUND)

            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "https://example.test", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(
                     scanner,
                     "fetch_providers",
                     side_effect=fake_fetch,
                 ), \
                 patch.object(
                     scanner,
                     "_resolve_ids_from_search",
                     side_effect=[
                         {"tmdb_id": "9001", "tvdb_id": "9991"},
                         {"tmdb_id": "9002", "tvdb_id": "9992"},
                         {"tmdb_id": "9003", "tvdb_id": "9993"},
                     ],
                 ):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            by_title = {item["title"]: item for item in payload["items"]}
            self.assertEqual(by_title["Paradise"]["tvdb_id"], "9991")
            self.assertEqual(by_title["Andor"]["tvdb_id"], "9992")
            self.assertEqual(by_title["La Casa de Papel"]["tvdb_id"], "9993")
            self.assertEqual(by_title["Paradise"]["tmdb_id"], "9001")
            self.assertEqual(by_title["Andor"]["tmdb_id"], "9002")
            self.assertEqual(by_title["La Casa de Papel"]["tmdb_id"], "9003")
            self.assertEqual(by_title["Paradise"]["providers"], ["Disney+"])
            self.assertEqual(by_title["Andor"]["providers"], ["Hulu"])
            self.assertEqual(by_title["La Casa de Papel"]["providers"], ["Netflix"])
            self.assertTrue(by_title["Paradise"]["providers_fetched"])
            self.assertTrue(by_title["Andor"]["providers_fetched"])
            self.assertTrue(by_title["La Casa de Papel"]["providers_fetched"])

    def test_enrich_movie_retries_with_search_resolved_tmdb_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Movies"],
                        "items": [
                            {
                                "title": "Back in Action",
                                "year": "2025",
                                "type": "movie",
                                "category": "Movies",
                                "tmdb_id": None,
                                "providers": [],
                                "providers_fetched": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            providers_netflix = [{"raw_name": "Netflix", "logo": None, "logo_url": None}]
            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "https://example.test", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", side_effect=[providers_netflix]), \
                 patch.object(scanner, "_resolve_ids_from_search", return_value={"tmdb_id": "11001", "tvdb_id": None}):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item["tmdb_id"], "11001")
            self.assertEqual(item["providers"], ["Netflix"])
            self.assertTrue(item["providers_fetched"])

    def test_enrich_movie_nominal_uses_tmdb_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Movies"],
                        "items": [
                            {
                                "title": "Rebel Moon - Partie 1",
                                "year": "2023",
                                "type": "movie",
                                "category": "Movies",
                                "tmdb_id": "934632",
                                "providers": [],
                                "providers_fetched": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            providers_netflix = [{"raw_name": "Netflix", "logo": None, "logo_url": None}]
            jsr_cfg = {"enabled": True, "url": "https://example.test", "apikey": "k"}
            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value=jsr_cfg), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", return_value=providers_netflix) as fetch_mock:
                scanner.run_enrich(force=True)

            fetch_mock.assert_called_once_with("934632", False, jsr_cfg)

    def test_enrich_tv_nominal_uses_tvdb_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Tv"],
                        "items": [
                            {
                                "title": "Andor",
                                "year": "2022",
                                "type": "tv",
                                "category": "Tv",
                                "tmdb_id": "83867",
                                "tvdb_id": "361753",
                                "providers": [],
                                "providers_fetched": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            providers_disney = [{"raw_name": "Disney+", "logo": None, "logo_url": None}]
            jsr_cfg = {"enabled": True, "url": "https://example.test", "apikey": "k"}
            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value=jsr_cfg), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", return_value=providers_disney) as fetch_mock:
                scanner.run_enrich(force=True)

            fetch_mock.assert_called_once_with("361753", True, jsr_cfg)

    def test_enrich_tv_fallbacks_to_tmdb_when_tvdb_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": 1,
                        "categories": ["Tv"],
                        "items": [
                            {
                                "title": "Debris",
                                "year": "2021",
                                "type": "tv",
                                "category": "Tv",
                                "tmdb_id": "99901",
                                "tvdb_id": "bad-tvdb",
                                "providers": [],
                                "providers_fetched": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            providers_apple = [{"raw_name": "Apple TV+", "logo": None, "logo_url": None}]
            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "https://example.test", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", side_effect=[scanner._JSR_NOT_FOUND, providers_apple]):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(item["providers"], ["Apple TV+"])
            self.assertTrue(item["providers_fetched"])

    def test_enrich_has_no_implicit_category_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = pathlib.Path(tmp) / "library.json"
            items = [
                {"title": "AnimA", "type": "movie", "category": "Animation", "tmdb_id": "1", "providers": [], "providers_fetched": False},
                {"title": "MovieA", "type": "movie", "category": "Movies", "tmdb_id": "2", "providers": [], "providers_fetched": False},
                {"title": "ShowA", "type": "movie", "category": "Spectacles", "tmdb_id": "3", "providers": [], "providers_fetched": False},
                {"title": "TvA", "type": "tv", "category": "Tv", "tvdb_id": "4", "tmdb_id": "40", "providers": [], "providers_fetched": False},
                {"title": "AnimeA", "type": "tv", "category": "Anime", "tvdb_id": "5", "tmdb_id": "50", "providers": [], "providers_fetched": False},
            ]
            out_path.write_text(
                json.dumps(
                    {
                        "scanned_at": "2026-04-19T00:00:00",
                        "library_path": "/library",
                        "total_items": len(items),
                        "categories": ["Animation", "Movies", "Spectacles", "Tv", "Anime"],
                        "items": items,
                    }
                ),
                encoding="utf-8",
            )

            default_providers = [{"raw_name": "Netflix", "logo": None, "logo_url": None}]

            def fake_fetch(identifier, is_tv, jsr):
                return default_providers

            with patch.object(scanner, "OUTPUT_PATH", str(out_path)), \
                 patch.object(scanner, "_jsr_cfg", return_value={"enabled": True, "url": "https://example.test", "apikey": "k"}), \
                 patch.object(scanner, "load_config", return_value={}), \
                 patch.object(scanner, "build_categories_from_config", return_value=[]), \
                 patch.object(scanner, "fetch_providers", side_effect=fake_fetch):
                scanner.run_enrich(force=True)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["items"]), len(items))
            by_title = {item["title"]: item for item in payload["items"]}
            for key in ("AnimA", "MovieA", "ShowA", "TvA", "AnimeA"):
                self.assertEqual(by_title[key]["providers"], ["Netflix"])
                self.assertTrue(by_title[key]["providers_fetched"])

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
