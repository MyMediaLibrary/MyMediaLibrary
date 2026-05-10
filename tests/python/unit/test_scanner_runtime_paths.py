import json
import os
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

try:
    from backend import db as _db
except Exception:
    import db as _db  # type: ignore


class ScannerRuntimePathsTest(unittest.TestCase):
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

    def test_scanner_defaults_use_canonical_paths(self):
        self.assertEqual(scanner.LIBRARY_PATH, str(runtime_paths.LIBRARY_DIR))
        self.assertEqual(scanner.OUTPUT_PATH, str(runtime_paths.LIBRARY_JSON))
        self.assertEqual(scanner.RECOMMENDATIONS_OUTPUT_PATH, str(runtime_paths.RECOMMENDATIONS_JSON))
        self.assertEqual(scanner.DEFAULT_CONFIG_PATH, str(runtime_paths.DEFAULT_CONFIG_JSON))
        self.assertEqual(scanner.CONFIG_PATH, str(runtime_paths.CONFIG_JSON))
        self.assertEqual(scanner.SECRETS_PATH, str(runtime_paths.SECRETS_FILE))
        self.assertEqual(scanner.PROVIDERS_MAPPING_RUNTIME_PATH, str(runtime_paths.PROVIDERS_MAPPING_JSON))
        self.assertEqual(scanner.PROVIDERS_LOGO_PATH, str(runtime_paths.PROVIDERS_LOGO_JSON))
        self.assertEqual(scanner.RECOMMENDATIONS_RULES_PATH, str(runtime_paths.RECOMMENDATIONS_RULES_JSON))
        self.assertEqual(scanner.SCAN_LOCK_PATH, str(runtime_paths.SCAN_LOCK))
        self.assertEqual(scanner._log_file, str(runtime_paths.SCANNER_LOG))

    def test_scanner_bootstraps_sqlite_runtime_database(self):
        with patch.object(scanner.sqlite_db, "bootstrap_runtime_database", return_value=True) as bootstrap:
            self.assertTrue(scanner._bootstrap_sqlite_runtime())

        bootstrap.assert_called_once()
        self.assertIs(bootstrap.call_args.kwargs.get("logger"), scanner.log)

    def test_scanner_bootstrap_requires_sqlite(self):
        with patch.object(scanner.sqlite_db, "bootstrap_runtime_database", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                scanner._bootstrap_sqlite_runtime()

    def test_load_config_requires_seeded_sqlite_config_without_creating_conf_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = pathlib.Path(tmpdir) / "conf" / "config.json"
            default_path = pathlib.Path(tmpdir) / "defaults" / "config.json"
            default_path.parent.mkdir()
            default_path.write_text('{"system":{"log_level":"DEBUG"},"folders":[]}', encoding="utf-8")
            with patch.object(scanner, "CONFIG_PATH", str(config_path)), \
                 patch.object(scanner.config_repository, "load_config", return_value=None), \
                 patch.object(scanner, "DEFAULT_CONFIG_PATH", str(default_path)):
                with self.assertRaises(RuntimeError):
                    scanner.load_config()

            self.assertFalse(config_path.exists())

    def test_load_config_prefers_sqlite_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = pathlib.Path(tmpdir) / "conf" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text('{"system":{"log_level":"JSON"},"folders":[]}', encoding="utf-8")
            db_cfg = {
                "system": {"log_level": "DEBUG"},
                "folders": [],
                "score": {"enabled": False},
                "score_configuration": {},
                "recommendations": {"enabled": False},
                "media_probe": {"enabled": False, "mode": "compare", "workers": 4, "cache_enabled": True},
            }

            with patch.object(scanner, "CONFIG_PATH", str(config_path)), \
                 patch.object(scanner.config_repository, "load_config", return_value=db_cfg):
                cfg = scanner.load_config()

            self.assertEqual(cfg["system"]["log_level"], "DEBUG")

    def test_save_config_requires_sqlite_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = pathlib.Path(tmpdir) / "conf" / "config.json"
            payload = {"system": {"log_level": "DEBUG"}, "folders": []}
            with patch.object(scanner, "CONFIG_PATH", str(config_path)), \
                 patch.object(scanner.config_repository, "save_config", side_effect=RuntimeError("db unavailable")):
                with self.assertRaises(RuntimeError):
                    scanner.save_config(payload)

            self.assertFalse(config_path.exists())

    def test_secrets_are_loaded_from_data_and_saved_0600(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = pathlib.Path(tmpdir) / "data" / ".secrets"
            secrets_path.parent.mkdir()
            secrets_path.write_text('{"seerr_apikey": "from-data"}', encoding="utf-8")
            with patch.object(scanner, "SECRETS_PATH", str(secrets_path)):
                self.assertEqual(scanner._load_secrets()["seerr_apikey"], "from-data")
                scanner._save_secrets({"seerr_apikey": "saved"})

            self.assertEqual(json.loads(secrets_path.read_text(encoding="utf-8")), {"seerr_apikey": "saved"})
            self.assertEqual(stat.S_IMODE(secrets_path.stat().st_mode), 0o600)

    def test_provider_mapping_and_logo_bootstrap_do_not_copy_defaults_to_conf(self):
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
                 patch.object(scanner, "PROVIDERS_LOGO_PATH", str(logo_dst)), \
                 patch.object(scanner.providers_repository, "load_provider_mappings", return_value={}) as load_mapping, \
                 patch.object(scanner.providers_repository, "load_provider_logos", return_value={}) as load_logos:
                scanner._ensure_runtime_provider_mapping()
                scanner._ensure_runtime_providers_logo()

            load_mapping.assert_called_once_with(str(mapping_dst))
            load_logos.assert_called_once_with(str(logo_dst))
            self.assertFalse(mapping_dst.exists())
            self.assertFalse(logo_dst.exists())

    def test_recommendations_phase_uses_sqlite_rules_and_no_json_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            recs_path = root / "data" / "recommendations.json"
            rules_path = root / "conf" / "recommendations_rules.json"
            default_rules_path = root / "defaults" / "recommendations_rules.json"
            recs_path.parent.mkdir()
            rules_path.parent.mkdir()
            default_rules_path.parent.mkdir()

            with patch.object(scanner, "OUTPUT_PATH", str(root / "data" / "library.json")), \
                 patch.object(scanner, "RECOMMENDATIONS_OUTPUT_PATH", str(recs_path)), \
                 patch.object(scanner, "RECOMMENDATIONS_RULES_PATH", str(rules_path)), \
                 patch.object(scanner, "RECOMMENDATIONS_DEFAULT_RULES_PATH", str(default_rules_path)), \
                 patch.object(scanner, "load_config", return_value={"score": {"enabled": True}, "recommendations": {"enabled": True}}), \
                 patch.object(scanner, "ensure_user_rules") as ensure_rules, \
                 patch.object(scanner, "load_library_document_non_blocking", return_value={"items": []}), \
                 patch.object(scanner, "_load_runtime_recommendation_rules", return_value=[]) as load_rules, \
                 patch.object(scanner, "generate_recommendations", return_value=[]) as generate, \
                 patch.object(scanner.recommendations_repository, "save_recommendations", return_value={"items": []}):
                scanner.run_recommendations()

            ensure_rules.assert_not_called()
            load_rules.assert_called_once_with()
            generate.assert_called_once()
            self.assertFalse(recs_path.exists())

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
