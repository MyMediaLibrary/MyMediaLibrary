import json
import os
import pathlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class LanguageNormalizationCriticalTest(unittest.TestCase):
    def test_expected_language_scenarios(self):
        cases = [
            ("fre", ["fra"], "VF"),
            ("french", ["fra"], "VF"),
            ("fr", ["fra"], "VF"),
            ("ru", ["rus"], "VO"),
            ("freru", ["fra", "rus"], "MULTI"),
            ("engfre", ["eng", "fra"], "MULTI"),
            ("jpneng", ["jpn", "eng"], "VO"),
            ("freijo", ["fra"], "VF"),
            ("fregsw", ["fra", "gsw"], "MULTI"),
            ("frefrenob", ["fra", "fra", "nob"], "MULTI"),
            ("vf", ["fra"], "VF"),
            ("vo", [], "UNKNOWN"),
            ("multi", [], "UNKNOWN"),
            ("fr_en+ja|ita", ["fra", "eng", "jpn", "ita"], "MULTI"),
            ("und", ["und"], "UNKNOWN"),
            ("", [], "UNKNOWN"),
            (None, [], "UNKNOWN"),
        ]
        for raw, parsed_expected, simplified in cases:
            with self.subTest(raw=raw):
                parsed = scanner._parse_lang_raw(raw)
                self.assertEqual(parsed, parsed_expected)
                self.assertEqual(scanner.simplify_audio_languages(parsed), simplified)

    def test_long_or_malformed_values_never_crash(self):
        self.assertEqual(scanner._parse_lang_raw("fre" * 600), ["fra"] * 600)
        self.assertEqual(scanner._parse_lang_raw("abcdef" * 500), [])
        self.assertEqual(scanner._parse_lang_raw("z" * 3000), [])

    def test_parse_audio_languages_from_xml(self):
        xml = ET.fromstring(
            """
            <movie>
              <fileinfo><streamdetails>
                <audio><language>fre</language></audio>
                <audio><language>ru</language></audio>
              </streamdetails></fileinfo>
            </movie>
            """
        )
        self.assertEqual(scanner.parse_audio_languages(xml), ["fra", "rus"])
        self.assertEqual(scanner.simplify_audio_languages(scanner.parse_audio_languages(xml)), "MULTI")

    def test_und_language_is_treated_as_unknown_without_polluting_parsed_codes(self):
        xml = ET.fromstring(
            """
            <movie>
              <fileinfo><streamdetails>
                <audio><language>und</language></audio>
              </streamdetails></fileinfo>
            </movie>
            """
        )
        parsed = scanner.parse_audio_languages(xml)
        self.assertEqual(parsed, [])
        self.assertEqual(scanner.simplify_audio_languages(parsed), "UNKNOWN")


class AudioCodecNormalizationCriticalTest(unittest.TestCase):
    def test_audio_codec_mapping_priority_and_display(self):
        cases = [
            ("AC-3", "Dolby Digital", "Dolby Digital"),
            ("EAC-3", "Dolby Digital Plus", "Dolby Digital Plus"),
            ("EAC3 ATMOS", "Dolby Atmos", "Dolby Atmos"),
            ("TRUEHD ATMOS", "Dolby Atmos", "Dolby Atmos"),
            ("TrueHD", "Dolby Atmos", "Dolby Atmos"),
            ("DTS", "DTS", "DTS"),
            ("DTS-HD MA", "DTS", "DTS"),
            ("DTS-HD HRA", "DTS", "DTS"),
            ("DTS-X", "DTS:X", "DTS:X"),
            ("SOMETHING-ELSE", "UNKNOWN", "Unknown"),
            ("", "UNKNOWN", "Unknown"),
            (None, "UNKNOWN", "Unknown"),
        ]
        for raw, normalized, display in cases:
            with self.subTest(raw=raw):
                result = scanner.normalize_audio_codec(raw)
                self.assertEqual(result["normalized"], normalized)
                self.assertEqual(result["display"], display)


class OnboardingFlagCriticalTest(unittest.TestCase):
    def test_missing_config_always_requires_onboarding(self):
        cfg = {"system": {}, "folders": []}
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=False))

    def test_existing_config_without_usable_folders_requires_onboarding(self):
        cfg = {"system": {}, "folders": [{"name": "Movies", "type": None}]}
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=True))

    def test_existing_config_with_usable_folder_defaults_to_no_onboarding(self):
        cfg = {"system": {}, "folders": [{"name": "Movies", "type": "movie", "missing": False}]}
        self.assertFalse(scanner._derive_needs_onboarding(cfg, config_exists=True))

    def test_explicit_flag_is_source_of_truth(self):
        cfg = {"system": {"needs_onboarding": True}, "folders": [{"name": "Movies", "type": "movie"}]}
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=True))
        cfg["system"]["needs_onboarding"] = False
        self.assertFalse(scanner._derive_needs_onboarding(cfg, config_exists=False))


class InventoryFlagCriticalTest(unittest.TestCase):
    def test_default_config_inventory_flag_is_disabled(self):
        self.assertIs(scanner._DEFAULT_CONFIG["system"]["inventory_enabled"], False)

    def test_missing_inventory_flag_falls_back_to_disabled(self):
        self.assertFalse(scanner._is_inventory_enabled({"system": {}}))
        self.assertFalse(scanner._is_inventory_enabled({"system": {"inventory_enabled": "true"}}))
        self.assertTrue(scanner._is_inventory_enabled({"system": {"inventory_enabled": True}}))

    def test_deep_merge_system_inventory_flag_preserves_other_system_fields(self):
        base = {"system": {"scan_cron": "0 3 * * *", "log_level": "INFO"}}
        merged = scanner.deep_merge(base, {"system": {"inventory_enabled": True}})
        self.assertEqual(merged["system"]["scan_cron"], "0 3 * * *")
        self.assertEqual(merged["system"]["log_level"], "INFO")
        self.assertTrue(merged["system"]["inventory_enabled"])


class ScoreFeatureFlagCriticalTest(unittest.TestCase):
    def test_default_config_score_flag_is_disabled(self):
        self.assertIs(scanner._DEFAULT_CONFIG["score"]["enabled"], False)

    def test_score_flag_parser_defaults_to_disabled(self):
        self.assertFalse(scanner._is_score_enabled({"score": {}}))
        self.assertFalse(scanner._is_score_enabled({"system": {"enable_score": "true"}}))
        self.assertTrue(scanner._is_score_enabled({"score": {"enabled": True}}))
        self.assertFalse(scanner._is_score_enabled({"score": {"enabled": False}}))
        self.assertTrue(scanner._is_score_enabled({"system": {"enable_score": True}}))
        self.assertFalse(scanner._is_score_enabled({"system": {"enable_score": False}}))

    def test_scan_media_item_skips_quality_payload_when_score_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Test Movie (2024)"
            media_dir.mkdir(parents=True)
            (media_dir / "test.mkv").write_text("x", encoding="utf-8")
            cat = {"name": "Films", "type": "movie"}
            item = scanner.scan_media_item(media_dir, root, cat, {}, enable_score=False)
            self.assertNotIn("quality", item)
            self.assertNotIn("runtime", item)
            self.assertNotIn("audio_codec_display", item)
            self.assertIsNone(item["audio_codec"])
            self.assertIsNone(item["audio_languages_simple"])

    def test_scan_media_item_tv_keeps_tmdb_and_tvdb_separate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Series" / "Andor"
            media_dir.mkdir(parents=True)
            (media_dir / "tvshow.nfo").write_text("<tvshow/>", encoding="utf-8")
            cat = {"name": "Series", "type": "tv"}
            prev = {"tmdb_id": "legacy", "tvdb_id": "legacy-tvdb"}
            with patch.object(scanner, "parse_tvshow_nfo", return_value={"title": "Andor", "tmdb_id": "228068", "tvdb_id": "83867"}), \
                 patch.object(scanner, "collect_series_episode_metadata", return_value=[]), \
                 patch.object(scanner, "aggregate_series_metadata", return_value={"seasons": [], "season_count": 1, "episode_count": 12}):
                item = scanner.scan_media_item(media_dir, root, cat, prev, enable_score=False)
            self.assertEqual(item["tmdb_id"], "228068")
            self.assertEqual(item["tvdb_id"], "83867")
            self.assertIn("seasons", item)
            self.assertIsNone(item.get("episodes_expected"))
            self.assertIsNone(item.get("complete"))

    def test_aggregate_audio_languages_does_not_promote_single_episode_outlier(self):
        episodes = [
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["fra", "eng"]},
            {"audio_languages": ["eng"]},
            {"audio_languages": ["jpn"]},
        ]
        langs = scanner._aggregate_audio_languages_from_episodes(episodes)
        self.assertEqual(langs, ["eng", "fra"])

    def test_merge_series_expected_counts_from_seerr_sets_completeness(self):
        item = {
            "episode_count": 18,
            "season_count": 2,
            "seasons": [
                {"season": 1, "episodes_found": 10},
                {"season": 2, "episodes_found": 8},
            ],
        }
        merged = scanner.merge_series_expected_counts_from_seerr(
            item,
            {
                "episodes_expected": 20,
                "season_count_expected": 2,
                "season_episode_counts": {1: 10, 2: 10},
            },
        )
        self.assertEqual(merged["episodes_expected"], 20)
        self.assertFalse(merged["complete"])
        self.assertEqual(merged["seasons"][0]["episodes_expected"], 10)
        self.assertEqual(merged["seasons"][1]["episodes_expected"], 10)


class FolderEnabledCompatibilityTest(unittest.TestCase):
    def test_enabled_falls_back_to_visible_when_missing(self):
        self.assertTrue(scanner.is_folder_enabled({"visible": True}))
        self.assertFalse(scanner.is_folder_enabled({"visible": False}))

    def test_enabled_has_priority_over_visible(self):
        self.assertFalse(scanner.is_folder_enabled({"enabled": False, "visible": True}))
        self.assertTrue(scanner.is_folder_enabled({"enabled": True, "visible": False}))

    def test_enabled_defaults_to_true_when_no_flag(self):
        self.assertTrue(scanner.is_folder_enabled({"name": "Movies"}))
        self.assertTrue(scanner.is_folder_enabled({}))

    def test_normalize_folder_enabled_flags_migrates_visible_to_enabled(self):
        cfg = {"folders": [{"name": "Movies", "type": "movie", "visible": False}]}
        changed = scanner.normalize_folder_enabled_flags(cfg, drop_visible=False)
        self.assertTrue(changed)
        self.assertIs(cfg["folders"][0]["enabled"], False)
        self.assertIn("visible", cfg["folders"][0])

    def test_normalize_folder_enabled_flags_can_drop_visible(self):
        cfg = {"folders": [{"name": "Movies", "type": "movie", "visible": True}]}
        changed = scanner.normalize_folder_enabled_flags(cfg, drop_visible=True)
        self.assertTrue(changed)
        self.assertIs(cfg["folders"][0]["enabled"], True)
        self.assertNotIn("visible", cfg["folders"][0])


class SeerrApiKeyPersistenceTest(unittest.TestCase):
    def test_payload_without_apikey_preserves_existing_secret(self):
        payload = {"seerr": {"enabled": True, "url": "https://example.test"}}
        secrets = {"seerr_apikey": "existing-secret"}

        action = scanner._apply_seerr_secret_update(payload, secrets)

        self.assertEqual(action, "not modified")
        self.assertEqual(secrets["seerr_apikey"], "existing-secret")
        self.assertNotIn("apikey", payload["seerr"])

    def test_payload_with_new_apikey_updates_secret(self):
        payload = {"seerr": {"apikey": "  new-secret  "}}
        secrets = {"seerr_apikey": "old-secret"}

        action = scanner._apply_seerr_secret_update(payload, secrets)

        self.assertEqual(action, "updated")
        self.assertEqual(secrets["seerr_apikey"], "new-secret")
        self.assertNotIn("seerr", payload)

    def test_payload_with_empty_apikey_does_not_overwrite_secret(self):
        payload = {"seerr": {"apikey": "   "}}
        secrets = {"seerr_apikey": "existing-secret"}

        action = scanner._apply_seerr_secret_update(payload, secrets)

        self.assertEqual(action, "preserved")
        self.assertEqual(secrets["seerr_apikey"], "existing-secret")

    def test_payload_with_explicit_clear_flag_removes_secret(self):
        payload = {"seerr": {"clear_apikey": True}}
        secrets = {"seerr_apikey": "existing-secret"}

        action = scanner._apply_seerr_secret_update(payload, secrets)

        self.assertEqual(action, "cleared")
        self.assertNotIn("seerr_apikey", secrets)
        self.assertNotIn("seerr", payload)


class SeerrConfigMigrationTest(unittest.TestCase):
    def test_normalize_seerr_config_migrates_legacy_block(self):
        cfg = {
            "jellyseerr": {"enabled": True, "url": "https://legacy.example"},
            "other": {"keep": True},
        }
        normalized, changed = scanner.normalize_seerr_config(cfg)

        self.assertTrue(changed)
        self.assertIn("seerr", normalized)
        self.assertNotIn("jellyseerr", normalized)
        self.assertEqual(normalized["seerr"]["enabled"], True)
        self.assertEqual(normalized["seerr"]["url"], "https://legacy.example")
        self.assertEqual(normalized["other"], {"keep": True})

    def test_normalize_seerr_secret_keys_migrates_legacy_secret_name(self):
        secrets = {"jellyseerr_apikey": "legacy-key"}
        normalized, changed = scanner._normalize_seerr_secret_keys(secrets)

        self.assertTrue(changed)
        self.assertEqual(normalized.get("seerr_apikey"), "legacy-key")
        self.assertNotIn("jellyseerr_apikey", normalized)


class ProvidersMappingRuntimeBootstrapTest(unittest.TestCase):
    def test_bootstrap_runtime_mapping_copies_source_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "providers_mapping.source.json"
            dst = pathlib.Path(tmp) / "providers_mapping.runtime.json"
            src.write_text('{"Netflix":"Netflix"}', encoding="utf-8")
            with patch.object(scanner, "PROVIDERS_MAPPING_SOURCE_PATH", str(src)), \
                 patch.object(scanner, "PROVIDERS_MAPPING_RUNTIME_PATH", str(dst)):
                scanner._ensure_runtime_provider_mapping()
            self.assertEqual(
                json.loads(dst.read_text(encoding="utf-8")),
                {"Netflix": "Netflix"},
            )

            dst.write_text('{"Netflix":"NFX-custom"}', encoding="utf-8")
            with patch.object(scanner, "PROVIDERS_MAPPING_SOURCE_PATH", str(src)), \
                 patch.object(scanner, "PROVIDERS_MAPPING_RUNTIME_PATH", str(dst)):
                scanner._ensure_runtime_provider_mapping()
            self.assertEqual(
                json.loads(dst.read_text(encoding="utf-8")),
                {"Netflix": "NFX-custom"},
            )

    def test_upsert_runtime_mapping_adds_missing_raw_providers_with_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "providers_mapping.source.json"
            dst = pathlib.Path(tmp) / "providers_mapping.runtime.json"
            src.write_text('{"Netflix":"Netflix"}', encoding="utf-8")
            dst.write_text('{"Netflix":"Netflix","Disney+":"Disney+"}', encoding="utf-8")
            items = [
                {"providers": ["Netflix", "Premiere Max", "Premiere Max"]},
                {"providers": ["Disney+", "Canal VOD"]},
                {"providers": []},
            ]
            with patch.object(scanner, "PROVIDERS_MAPPING_SOURCE_PATH", str(src)), \
                 patch.object(scanner, "PROVIDERS_MAPPING_RUNTIME_PATH", str(dst)):
                added = scanner._upsert_runtime_provider_mapping(items)
            self.assertEqual(added, 2)
            self.assertEqual(
                json.loads(dst.read_text(encoding="utf-8")),
                {
                    "Netflix": "Netflix",
                    "Disney+": "Disney+",
                    "Premiere Max": None,
                    "Canal VOD": None,
                },
            )

    def test_jsr_cfg_uses_preserved_secret_for_scan_config(self):
        cfg = {"seerr": {"enabled": True, "url": "https://example.test/"}}
        secrets = {"seerr_apikey": "kept-secret"}

        with patch.object(scanner, "load_config", return_value=cfg), patch.object(scanner, "_load_secrets", return_value=secrets):
            jsr = scanner._jsr_cfg()

        self.assertTrue(jsr["enabled"])
        self.assertEqual(jsr["url"], "https://example.test")
        self.assertEqual(jsr["apikey"], "kept-secret")


class SeerrEnvBootstrapTest(unittest.TestCase):
    def test_bootstrap_url_when_config_empty_uses_legacy_alias_and_trims(self):
        cfg = {"seerr": {"enabled": False, "url": ""}}
        secrets = {}

        with patch.dict(os.environ, {"JELLYSEER_URL": " https://bootstrap.example/ "}, clear=True), \
             patch.object(scanner, "load_config", return_value=cfg), \
             patch.object(scanner, "_load_secrets", return_value=secrets), \
             patch.object(scanner, "_save_secrets") as save_secrets, \
             patch.object(scanner, "save_config") as save_config:
            scanner.migrate_env_to_config()

        save_config.assert_called_once()
        saved_cfg = save_config.call_args.args[0]
        self.assertEqual(saved_cfg["seerr"]["url"], "https://bootstrap.example")
        save_secrets.assert_not_called()

    def test_bootstrap_url_does_not_overwrite_existing_config_value(self):
        cfg = {"seerr": {"enabled": True, "url": "https://existing.example"}}
        secrets = {}

        with patch.dict(os.environ, {"JELLYSEER_URL": "https://bootstrap.example"}, clear=True), \
             patch.object(scanner, "load_config", return_value=cfg), \
             patch.object(scanner, "_load_secrets", return_value=secrets), \
             patch.object(scanner, "_save_secrets") as save_secrets, \
             patch.object(scanner, "save_config") as save_config:
            scanner.migrate_env_to_config()

        save_config.assert_called_once()
        saved_cfg = save_config.call_args.args[0]
        self.assertEqual(saved_cfg["seerr"]["url"], "https://existing.example")
        save_secrets.assert_not_called()

    def test_bootstrap_apikey_when_secret_absent_writes_only_internal_secrets(self):
        cfg = {"seerr": {"enabled": True, "url": "https://existing.example"}}
        secrets = {}

        with patch.dict(os.environ, {"JELLYSEER_APIKEY": "  boot-key  "}, clear=True), \
             patch.object(scanner, "load_config", return_value=cfg), \
             patch.object(scanner, "_load_secrets", return_value=secrets), \
             patch.object(scanner, "_save_secrets") as save_secrets, \
             patch.object(scanner, "save_config") as save_config:
            scanner.migrate_env_to_config()

        save_secrets.assert_called_once_with({"seerr_apikey": "boot-key"})
        save_config.assert_called_once()
        saved_cfg = save_config.call_args.args[0]
        self.assertNotIn("apikey", saved_cfg.get("seerr", {}))

    def test_bootstrap_apikey_does_not_overwrite_existing_secret(self):
        cfg = {"seerr": {"enabled": True, "url": "https://existing.example"}}
        secrets = {"seerr_apikey": "existing-key"}

        with patch.dict(os.environ, {"JELLYSEER_APIKEY": "boot-key"}, clear=True), \
             patch.object(scanner, "load_config", return_value=cfg), \
             patch.object(scanner, "_load_secrets", return_value=secrets), \
             patch.object(scanner, "_save_secrets") as save_secrets, \
             patch.object(scanner, "save_config") as save_config:
            scanner.migrate_env_to_config()

        save_secrets.assert_not_called()
        save_config.assert_called_once()

    def test_bootstrap_ignores_blank_values(self):
        cfg = {"seerr": {"enabled": False, "url": ""}}
        secrets = {}

        with patch.dict(os.environ, {"JELLYSEER_URL": "   ", "JELLYSEER_APIKEY": "   "}, clear=True), \
             patch.object(scanner, "load_config", return_value=cfg), \
             patch.object(scanner, "_load_secrets", return_value=secrets), \
             patch.object(scanner, "_save_secrets") as save_secrets, \
             patch.object(scanner, "save_config") as save_config:
            scanner.migrate_env_to_config()

        save_secrets.assert_not_called()
        save_config.assert_called_once()
        saved_cfg = save_config.call_args.args[0]
        self.assertEqual(saved_cfg["seerr"]["url"], "")

    def test_bootstrap_no_env_vars_keeps_existing_values(self):
        cfg = {"seerr": {"enabled": True, "url": "https://existing.example"}}
        secrets = {"seerr_apikey": "existing-key"}

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(scanner, "load_config", return_value=cfg), \
             patch.object(scanner, "_load_secrets", return_value=secrets), \
             patch.object(scanner, "_save_secrets") as save_secrets, \
             patch.object(scanner, "save_config") as save_config:
            scanner.migrate_env_to_config()

        save_secrets.assert_not_called()
        save_config.assert_called_once()
        saved_cfg = save_config.call_args.args[0]
        self.assertEqual(saved_cfg["seerr"]["url"], "https://existing.example")


class HdrFallbackSafetyTest(unittest.TestCase):
    def test_scan_media_item_drops_stale_hdr_type_when_current_scan_has_no_hdr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "Films" / "Test Movie (2024)"
            media_dir.mkdir(parents=True)
            (media_dir / "test.mkv").write_text("x", encoding="utf-8")

            prev = {
                "resolution": "1080p",
                "codec": "H.264",
                "hdr": True,
                "hdr_type": "Dolby Vision",
                "quality": {"video": 30, "audio": 8, "languages": 3, "size": 5, "score": 46, "level": 2},
            }
            cat = {"name": "Films", "type": "movie"}
            item = scanner.scan_media_item(media_dir, root, cat, prev)

            self.assertFalse(item["hdr"])
            self.assertIsNone(item["hdr_type"])
            self.assertEqual(item["quality"]["video"], 30)


if __name__ == "__main__":
    unittest.main()
