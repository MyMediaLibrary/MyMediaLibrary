import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "conf"))

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


if __name__ == "__main__":
    unittest.main()
