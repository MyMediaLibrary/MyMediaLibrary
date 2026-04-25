import json
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import runtime_paths  # noqa: E402
import scanner  # noqa: E402


class ScannerRuntimePathsTest(unittest.TestCase):
    def test_scanner_defaults_use_canonical_paths(self):
        self.assertEqual(scanner.LIBRARY_PATH, str(runtime_paths.LIBRARY_DIR))
        self.assertEqual(scanner.OUTPUT_PATH, str(runtime_paths.LIBRARY_JSON))
        self.assertEqual(scanner.INVENTORY_OUTPUT_PATH, str(runtime_paths.INVENTORY_JSON))
        self.assertEqual(scanner.RECOMMENDATIONS_OUTPUT_PATH, str(runtime_paths.RECOMMENDATIONS_JSON))
        self.assertEqual(scanner.DEFAULT_CONFIG_PATH, str(runtime_paths.DEFAULT_CONFIG_JSON))
        self.assertEqual(scanner.CONFIG_PATH, str(runtime_paths.CONFIG_JSON))
        self.assertEqual(scanner.SECRETS_PATH, str(runtime_paths.SECRETS_FILE))
        self.assertEqual(scanner.PROVIDERS_MAPPING_RUNTIME_PATH, str(runtime_paths.PROVIDERS_MAPPING_JSON))
        self.assertEqual(scanner.PROVIDERS_LOGO_PATH, str(runtime_paths.PROVIDERS_LOGO_JSON))
        self.assertEqual(scanner.RECOMMENDATIONS_RULES_PATH, str(runtime_paths.RECOMMENDATIONS_RULES_JSON))
        self.assertEqual(scanner.SCAN_LOCK_PATH, str(runtime_paths.SCAN_LOCK))
        self.assertEqual(scanner._log_file, str(runtime_paths.SCANNER_LOG))

    def test_load_config_creates_missing_config_in_conf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = pathlib.Path(tmpdir) / "conf" / "config.json"
            default_path = pathlib.Path(tmpdir) / "defaults" / "config.json"
            default_path.parent.mkdir()
            default_path.write_text('{"system":{"log_level":"DEBUG"},"folders":[]}', encoding="utf-8")
            with patch.object(scanner, "CONFIG_PATH", str(config_path)), \
                 patch.object(scanner, "DEFAULT_CONFIG_PATH", str(default_path)):
                cfg = scanner.load_config()

            self.assertTrue(config_path.exists())
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), cfg)
            self.assertEqual(cfg["folders"], [])
            self.assertEqual(cfg["system"]["log_level"], "DEBUG")

    def test_save_config_writes_to_conf_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = pathlib.Path(tmpdir) / "conf" / "config.json"
            payload = {"system": {"log_level": "DEBUG"}, "folders": []}
            with patch.object(scanner, "CONFIG_PATH", str(config_path)):
                scanner.save_config(payload)

            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), payload)

    def test_secrets_are_loaded_from_conf_and_saved_0600(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = pathlib.Path(tmpdir) / "conf" / ".secrets"
            secrets_path.parent.mkdir()
            secrets_path.write_text('{"seerr_apikey": "from-conf"}', encoding="utf-8")
            with patch.object(scanner, "SECRETS_PATH", str(secrets_path)):
                self.assertEqual(scanner._load_secrets()["seerr_apikey"], "from-conf")
                scanner._save_secrets({"seerr_apikey": "saved"})

            self.assertEqual(json.loads(secrets_path.read_text(encoding="utf-8")), {"seerr_apikey": "saved"})
            self.assertEqual(stat.S_IMODE(secrets_path.stat().st_mode), 0o600)

    def test_provider_mapping_and_logo_bootstrap_to_conf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            mapping_src = root / "defaults" / "providers_mapping.json"
            logo_src = root / "defaults" / "providers_logo.json"
            mapping_dst = root / "conf" / "providers_mapping.json"
            logo_dst = root / "conf" / "providers_logo.json"
            mapping_src.parent.mkdir()
            mapping_src.write_text('{"Netflix":"Netflix"}', encoding="utf-8")
            logo_src.write_text('{"Netflix":"netflix.webp"}', encoding="utf-8")

            with patch.object(scanner, "PROVIDERS_MAPPING_SOURCE_PATH", str(mapping_src)), \
                 patch.object(scanner, "PROVIDERS_MAPPING_RUNTIME_PATH", str(mapping_dst)), \
                 patch.object(scanner, "PROVIDERS_LOGO_SOURCE_PATH", str(logo_src)), \
                 patch.object(scanner, "PROVIDERS_LOGO_PATH", str(logo_dst)):
                scanner._ensure_runtime_provider_mapping()
                scanner._ensure_runtime_providers_logo()

            self.assertEqual(json.loads(mapping_dst.read_text(encoding="utf-8")), {"Netflix": "Netflix"})
            self.assertEqual(json.loads(logo_dst.read_text(encoding="utf-8")), {"Netflix": "netflix.webp"})

    def test_recommendations_phase_uses_conf_rules_and_data_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            library_path = root / "data" / "library.json"
            recs_path = root / "data" / "recommendations.json"
            rules_path = root / "conf" / "recommendations_rules.json"
            default_rules_path = root / "defaults" / "recommendations_rules.json"
            library_path.parent.mkdir()
            rules_path.parent.mkdir()
            default_rules_path.parent.mkdir()
            library_path.write_text('{"items":[]}', encoding="utf-8")

            with patch.object(scanner, "OUTPUT_PATH", str(library_path)), \
                 patch.object(scanner, "RECOMMENDATIONS_OUTPUT_PATH", str(recs_path)), \
                 patch.object(scanner, "RECOMMENDATIONS_RULES_PATH", str(rules_path)), \
                 patch.object(scanner, "RECOMMENDATIONS_DEFAULT_RULES_PATH", str(default_rules_path)), \
                 patch.object(scanner, "load_config", return_value={"score": {"enabled": True}, "recommendations": {"enabled": True}}), \
                 patch.object(scanner, "ensure_user_rules") as ensure_rules, \
                 patch.object(scanner, "load_recommendation_rules", return_value=[]) as load_rules, \
                 patch.object(scanner, "generate_recommendations", return_value=[]) as generate:
                scanner.run_recommendations()

            ensure_rules.assert_called_once_with(str(default_rules_path), str(rules_path))
            load_rules.assert_called_once_with(str(rules_path))
            generate.assert_called_once()
            self.assertTrue(recs_path.exists())

    def test_scan_lock_uses_tmp_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = pathlib.Path(tmpdir) / "tmp" / "scan.lock"
            with patch.object(scanner, "SCAN_LOCK_PATH", str(lock_path)):
                with scanner._scan_lock("unit"):
                    self.assertTrue(lock_path.exists())

    def test_runtime_code_has_no_legacy_storage_paths(self):
        forbidden = (
            "/data/config.json",
            "/app/.secrets",
            "/data/providers_mapping.json",
            "/data/providers_logo.json",
            "/data/recommendations_rules.json",
            "/data/.scan.lock",
        )
        runtime_files = [
            ROOT / "backend" / "scanner.py",
            ROOT / "docker" / "entrypoint.sh",
        ]
        for path in runtime_files:
            source = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(value, source, f"{value} found in {path}")


if __name__ == "__main__":
    unittest.main()
