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
        CONF_DIR=conf,
        TMP_DIR=tmp,
        SECRETS_FILE=conf / ".secrets",
        LEGACY_MIGRATIONS=(
            runtime_paths.LegacyMigration(app / ".secrets", conf / ".secrets"),
        ),
    )


class StorageMigrationTest(unittest.TestCase):
    def test_creates_runtime_directories_without_moving_json_config_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            paths = fake_paths(root)
            paths.DATA_DIR.mkdir()
            paths.CONF_DIR.mkdir()
            data_config = paths.DATA_DIR / "config.json"
            conf_config = paths.CONF_DIR / "config.json"
            data_config.write_text('{"legacy": true}', encoding="utf-8")
            conf_config.write_text('{"current": true}', encoding="utf-8")

            storage_migration.run_storage_migration(paths)

            self.assertTrue(paths.TMP_DIR.is_dir())
            self.assertEqual(data_config.read_text(encoding="utf-8"), '{"legacy": true}')
            self.assertEqual(conf_config.read_text(encoding="utf-8"), '{"current": true}')

    def test_secrets_are_migrated_and_chmod_600(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            app = pathlib.Path(tmpdir) / "app"
            app.mkdir()
            src = app / ".secrets"
            src.write_text('{"apikey": "secret"}', encoding="utf-8")
            os.chmod(src, 0o644)

            storage_migration.run_storage_migration(paths)

            dst = paths.CONF_DIR / ".secrets"
            self.assertFalse(src.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"apikey": "secret"}')
            self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
