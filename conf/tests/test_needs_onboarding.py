import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "conf"))

import scanner  # noqa: E402


class NeedsOnboardingBackendTest(unittest.TestCase):
    def test_missing_config_file_is_first_run(self):
        cfg = {"system": {}, "folders": []}
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=False))

    def test_default_config_loaded_in_memory_without_file_still_requires_onboarding(self):
        cfg = dict(scanner._DEFAULT_CONFIG)
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=False))

    def test_saved_config_without_initial_scan_keeps_onboarding_true(self):
        cfg = {
            "system": {"needs_onboarding": True},
            "folders": [{"name": "Movies", "type": "movie", "missing": False}],
        }
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=True))

    def test_initial_scan_start_switches_onboarding_to_false(self):
        cfg = {
            "system": {"needs_onboarding": True},
            "folders": [{"name": "Movies", "type": "movie", "missing": False}],
        }
        cfg["system"]["needs_onboarding"] = False
        self.assertFalse(scanner._derive_needs_onboarding(cfg, config_exists=True))

    def test_scan_failure_v1_keeps_false_once_scan_was_started(self):
        cfg = {
            "system": {"needs_onboarding": False},
            "folders": [],
        }
        # Product choice (V1): once initial scan is launched, onboarding stays completed.
        self.assertFalse(scanner._derive_needs_onboarding(cfg, config_exists=True))

    def test_valid_config_without_library_json_does_not_restore_onboarding(self):
        cfg = {
            "system": {"needs_onboarding": False},
            "folders": [{"name": "TV", "type": "tv", "missing": False}],
        }
        # _derive_needs_onboarding is intentionally independent from library.json presence.
        self.assertFalse(scanner._derive_needs_onboarding(cfg, config_exists=True))

    def test_full_reset_back_to_first_run(self):
        cfg = {
            "system": {},
            "folders": [{"name": "Movies", "type": "movie", "missing": False}],
        }
        self.assertTrue(scanner._derive_needs_onboarding(cfg, config_exists=False))


if __name__ == "__main__":
    unittest.main()
