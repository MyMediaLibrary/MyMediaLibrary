import os
import pathlib
import stat
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import runtime_paths  # noqa: E402
import storage_migration  # noqa: E402


def fake_paths(root: pathlib.Path):
    data = root / "data"
    conf = root / "conf"
    tmp = root / "tmp"
    app = root / "app"
    return types.SimpleNamespace(
        DATA_DIR=data,
        LEGACY_CONF_DIR=conf,
        TMP_DIR=tmp,
        SECRETS_FILE=data / ".secrets",
        LEGACY_MIGRATIONS=(
            runtime_paths.LegacyMigration(app / ".secrets", data / ".secrets"),
            runtime_paths.LegacyMigration(conf / ".secrets", data / ".secrets"),
        ),
    )


class StorageMigrationTest(unittest.TestCase):
    def test_creates_runtime_directories_without_creating_conf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            paths = fake_paths(root)

            storage_migration.run_storage_migration(paths)

            self.assertTrue(paths.DATA_DIR.is_dir())
            self.assertTrue(paths.TMP_DIR.is_dir())
            self.assertFalse(paths.LEGACY_CONF_DIR.exists())

    def test_app_legacy_secrets_are_migrated_and_chmod_600(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            app = pathlib.Path(tmpdir) / "app"
            app.mkdir()
            src = app / ".secrets"
            src.write_text('{"apikey": "secret"}', encoding="utf-8")
            os.chmod(src, 0o644)

            storage_migration.run_storage_migration(paths)

            dst = paths.DATA_DIR / ".secrets"
            self.assertFalse(src.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"apikey": "secret"}')
            self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o600)

    def test_conf_legacy_secrets_are_migrated_to_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.LEGACY_CONF_DIR.mkdir()
            src = paths.LEGACY_CONF_DIR / ".secrets"
            src.write_text('{"seerr_apikey": "secret"}', encoding="utf-8")

            storage_migration.run_storage_migration(paths)

            dst = paths.DATA_DIR / ".secrets"
            self.assertFalse(src.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"seerr_apikey": "secret"}')
            self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o600)

    def test_data_secrets_win_over_legacy_conf_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.DATA_DIR.mkdir()
            paths.LEGACY_CONF_DIR.mkdir()
            current = paths.DATA_DIR / ".secrets"
            legacy = paths.LEGACY_CONF_DIR / ".secrets"
            current.write_text('{"seerr_apikey": "current"}', encoding="utf-8")
            legacy.write_text('{"seerr_apikey": "legacy"}', encoding="utf-8")

            storage_migration.run_storage_migration(paths)

            self.assertEqual(current.read_text(encoding="utf-8"), '{"seerr_apikey": "current"}')
            self.assertFalse(legacy.exists())


if __name__ == "__main__":
    unittest.main()
