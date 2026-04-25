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
            runtime_paths.LegacyMigration(data / "config.json", conf / "config.json"),
            runtime_paths.LegacyMigration(data / "providers_mapping.json", conf / "providers_mapping.json"),
            runtime_paths.LegacyMigration(data / "providers_logo.json", conf / "providers_logo.json"),
            runtime_paths.LegacyMigration(data / "recommendations_rules.json", conf / "recommendations_rules.json"),
            runtime_paths.LegacyMigration(app / ".secrets", conf / ".secrets"),
        ),
    )


class StorageMigrationTest(unittest.TestCase):
    def test_simple_migration_moves_source_to_destination(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.DATA_DIR.mkdir()
            src = paths.DATA_DIR / "config.json"
            src.write_text('{"ok": true}', encoding="utf-8")

            storage_migration.run_storage_migration(paths)

            self.assertFalse(src.exists())
            self.assertEqual((paths.CONF_DIR / "config.json").read_text(encoding="utf-8"), '{"ok": true}')
            self.assertTrue(paths.TMP_DIR.is_dir())

    def test_already_migrated_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.CONF_DIR.mkdir()
            dst = paths.CONF_DIR / "config.json"
            dst.write_text('{"kept": true}', encoding="utf-8")

            storage_migration.run_storage_migration(paths)

            self.assertEqual(dst.read_text(encoding="utf-8"), '{"kept": true}')

    def test_identical_source_and_destination_removes_legacy_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.DATA_DIR.mkdir()
            paths.CONF_DIR.mkdir()
            src = paths.DATA_DIR / "providers_mapping.json"
            dst = paths.CONF_DIR / "providers_mapping.json"
            src.write_text('{"same": true}', encoding="utf-8")
            dst.write_text('{"same": true}', encoding="utf-8")

            storage_migration.run_storage_migration(paths)

            self.assertFalse(src.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"same": true}')

    def test_different_source_and_destination_blocks_migration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.DATA_DIR.mkdir()
            paths.CONF_DIR.mkdir()
            src = paths.DATA_DIR / "config.json"
            dst = paths.CONF_DIR / "config.json"
            src.write_text('{"legacy": true}', encoding="utf-8")
            dst.write_text('{"current": true}', encoding="utf-8")

            with self.assertRaises(storage_migration.StorageMigrationError):
                storage_migration.run_storage_migration(paths)

            self.assertEqual(src.read_text(encoding="utf-8"), '{"legacy": true}')
            self.assertEqual(dst.read_text(encoding="utf-8"), '{"current": true}')

    def test_conflict_preflight_does_not_cleanup_other_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = fake_paths(pathlib.Path(tmpdir))
            paths.DATA_DIR.mkdir()
            paths.CONF_DIR.mkdir()
            same_src = paths.DATA_DIR / "providers_mapping.json"
            same_dst = paths.CONF_DIR / "providers_mapping.json"
            conflict_src = paths.DATA_DIR / "config.json"
            conflict_dst = paths.CONF_DIR / "config.json"
            same_src.write_text('{"same": true}', encoding="utf-8")
            same_dst.write_text('{"same": true}', encoding="utf-8")
            conflict_src.write_text('{"legacy": true}', encoding="utf-8")
            conflict_dst.write_text('{"current": true}', encoding="utf-8")

            with self.assertRaises(storage_migration.StorageMigrationError):
                storage_migration.run_storage_migration(paths)

            self.assertTrue(same_src.exists())
            self.assertEqual(same_dst.read_text(encoding="utf-8"), '{"same": true}')
            self.assertTrue(conflict_src.exists())
            self.assertEqual(conflict_dst.read_text(encoding="utf-8"), '{"current": true}')

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
