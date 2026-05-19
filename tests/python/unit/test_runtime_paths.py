import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import runtime_paths as paths  # noqa: E402


class RuntimePathsTest(unittest.TestCase):
    def test_canonical_directories_are_fixed(self):
        self.assertEqual(paths.DATA_DIR, pathlib.Path("/data"))
        self.assertEqual(paths.LEGACY_CONF_DIR, pathlib.Path("/conf"))
        self.assertEqual(paths.TMP_DIR, pathlib.Path("/tmp"))
        self.assertEqual(paths.LIBRARY_DIR, pathlib.Path("/library"))

    def test_generated_files_stay_under_data(self):
        self.assertEqual(paths.LIBRARY_JSON, pathlib.Path("/data/library.json"))
        self.assertEqual(paths.LIBRARY_PROBE_JSON, pathlib.Path("/data/library_probe.json"))
        self.assertEqual(paths.MEDIA_PROBE_CACHE_JSON, pathlib.Path("/data/media_probe_cache.json"))
        self.assertEqual(paths.RECOMMENDATIONS_JSON, pathlib.Path("/data/recommendations.json"))
        self.assertEqual(paths.SCANNER_LOG, pathlib.Path("/data/scanner.log"))
        self.assertEqual(paths.SQLITE_DB, pathlib.Path("/data/mymedialibrary.db"))
        self.assertEqual(set(paths.GENERATED_FILES), {
            pathlib.Path("/data/scanner.log"),
            pathlib.Path("/data/mymedialibrary.db"),
        })

    def test_legacy_json_import_sources_stay_under_data(self):
        self.assertEqual(paths.CONFIG_JSON, pathlib.Path("/data/config.json"))
        self.assertEqual(paths.PROVIDERS_MAPPING_JSON, pathlib.Path("/data/providers_mapping.json"))
        self.assertEqual(paths.PROVIDERS_LOGO_JSON, pathlib.Path("/data/providers_logo.json"))
        self.assertEqual(paths.RECOMMENDATIONS_RULES_JSON, pathlib.Path("/data/recommendations_rules.json"))
        self.assertEqual(paths.SECRETS_FILE, pathlib.Path("/data/.secrets"))
        self.assertEqual(paths.LEGACY_SECRETS_FILE, pathlib.Path("/conf/.secrets"))

    def test_tmp_only_contains_scan_lock(self):
        self.assertEqual(paths.SCAN_LOCK, pathlib.Path("/tmp/scan.lock"))

    def test_legacy_paths_are_migration_only_sources(self):
        migrations = {(item.source, item.destination) for item in paths.LEGACY_MIGRATIONS}
        self.assertEqual(migrations, {
            (pathlib.Path("/app/.secrets"), pathlib.Path("/data/.secrets")),
            (pathlib.Path("/conf/.secrets"), pathlib.Path("/data/.secrets")),
        })
        self.assertEqual(paths.LEGACY_MIGRATIONS[0].source, pathlib.Path("/conf/.secrets"))

    def test_fresh_install_defaults_are_python_constants(self):
        from defaults import (
            DEFAULT_CONFIG, DEFAULT_PROVIDERS, DEFAULT_PROVIDER_LOGOS,
            DEFAULT_RECOMMENDATION_RULES, DEFAULT_AUDIO_CODEC_MAPPING,
            DEFAULT_GENRE_MAPPING, DEFAULT_AUDIO_LANGUAGES,
        )
        self.assertIsInstance(DEFAULT_CONFIG, dict)
        self.assertIn("system", DEFAULT_CONFIG)
        self.assertGreater(len(DEFAULT_PROVIDERS), 100)
        self.assertGreater(len(DEFAULT_PROVIDER_LOGOS), 0)
        self.assertEqual(len(DEFAULT_RECOMMENDATION_RULES), 16)
        self.assertIsInstance(DEFAULT_AUDIO_CODEC_MAPPING, dict)
        self.assertIsInstance(DEFAULT_GENRE_MAPPING, dict)
        self.assertIsInstance(DEFAULT_AUDIO_LANGUAGES, dict)
        # CONFIG_FILES entries no longer carry a default_path (defaults are Python constants)
        for item in paths.CONFIG_FILES:
            self.assertIsNone(item.default_path)


if __name__ == "__main__":
    unittest.main()
