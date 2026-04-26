import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import runtime_paths as paths  # noqa: E402


class RuntimePathsTest(unittest.TestCase):
    def test_canonical_directories_are_fixed(self):
        self.assertEqual(paths.DATA_DIR, pathlib.Path("/data"))
        self.assertEqual(paths.CONF_DIR, pathlib.Path("/conf"))
        self.assertEqual(paths.TMP_DIR, pathlib.Path("/tmp"))
        self.assertEqual(paths.LIBRARY_DIR, pathlib.Path("/library"))

    def test_generated_files_stay_under_data(self):
        self.assertEqual(paths.LIBRARY_JSON, pathlib.Path("/data/library.json"))
        self.assertEqual(paths.LIBRARY_PROBE_JSON, pathlib.Path("/data/library_probe.json"))
        self.assertEqual(paths.INVENTORY_JSON, pathlib.Path("/data/library_inventory.json"))
        self.assertEqual(paths.RECOMMENDATIONS_JSON, pathlib.Path("/data/recommendations.json"))
        self.assertEqual(paths.SCANNER_LOG, pathlib.Path("/data/scanner.log"))
        self.assertEqual(set(paths.GENERATED_FILES), {
            pathlib.Path("/data/library.json"),
            pathlib.Path("/data/library_probe.json"),
            pathlib.Path("/data/library_inventory.json"),
            pathlib.Path("/data/recommendations.json"),
            pathlib.Path("/data/scanner.log"),
        })

    def test_config_files_stay_under_conf(self):
        self.assertEqual(paths.CONFIG_JSON, pathlib.Path("/conf/config.json"))
        self.assertEqual(paths.PROVIDERS_MAPPING_JSON, pathlib.Path("/conf/providers_mapping.json"))
        self.assertEqual(paths.PROVIDERS_LOGO_JSON, pathlib.Path("/conf/providers_logo.json"))
        self.assertEqual(paths.RECOMMENDATIONS_RULES_JSON, pathlib.Path("/conf/recommendations_rules.json"))
        self.assertEqual(paths.SECRETS_FILE, pathlib.Path("/conf/.secrets"))

    def test_tmp_only_contains_scan_lock(self):
        self.assertEqual(paths.SCAN_LOCK, pathlib.Path("/tmp/scan.lock"))

    def test_legacy_paths_are_migration_only_sources(self):
        migrations = {(item.source, item.destination) for item in paths.LEGACY_MIGRATIONS}
        self.assertEqual(migrations, {
            (pathlib.Path("/data/config.json"), pathlib.Path("/conf/config.json")),
            (pathlib.Path("/data/providers_mapping.json"), pathlib.Path("/conf/providers_mapping.json")),
            (pathlib.Path("/data/providers_logo.json"), pathlib.Path("/conf/providers_logo.json")),
            (pathlib.Path("/data/recommendations_rules.json"), pathlib.Path("/conf/recommendations_rules.json")),
            (pathlib.Path("/app/.secrets"), pathlib.Path("/conf/.secrets")),
        })

    def test_fresh_install_defaults_are_bundled_under_app_defaults_conf(self):
        self.assertEqual(paths.DEFAULT_CONF_DIR, pathlib.Path("/app/defaults/conf"))
        defaults = {item.path: item.default_path for item in paths.CONFIG_FILES}
        self.assertEqual(defaults[pathlib.Path("/conf/config.json")], pathlib.Path("/app/defaults/conf/config.json"))
        self.assertEqual(defaults[pathlib.Path("/conf/providers_mapping.json")], pathlib.Path("/app/defaults/conf/providers_mapping.json"))
        self.assertEqual(defaults[pathlib.Path("/conf/providers_logo.json")], pathlib.Path("/app/defaults/conf/providers_logo.json"))
        self.assertEqual(defaults[pathlib.Path("/conf/recommendations_rules.json")], pathlib.Path("/app/defaults/conf/recommendations_rules.json"))
        self.assertIsNone(defaults[pathlib.Path("/conf/.secrets")])


if __name__ == "__main__":
    unittest.main()
