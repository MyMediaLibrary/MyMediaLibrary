import logging
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import db_migrations  # noqa: E402
import db_schema  # noqa: E402


class DatabaseSchemaTest(unittest.TestCase):
    def test_creates_empty_database_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "nested" / "mymedialibrary.db"

            conn = db.initialize_database(db_path)
            conn.close()

            self.assertTrue(db_path.is_file())

    def test_default_database_path_can_be_overridden_for_tests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "data" / "mymedialibrary.db"

            with patch.dict("os.environ", {db.DB_PATH_ENV: str(db_path)}):
                conn = db.initialize_database()
                conn.close()

            self.assertTrue(db_path.is_file())

    def test_runtime_bootstrap_creates_database_and_logs_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "nested" / "mymedialibrary.db"
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False

            try:
                with self.assertLogs("db-bootstrap-test", level="INFO") as logs:
                    ok = db.bootstrap_runtime_database(
                        db_path,
                        logger=logging.getLogger("db-bootstrap-test"),
                    )
            finally:
                db._startup_tasks_done = previous_done

            self.assertTrue(ok)
            self.assertTrue(db_path.is_file())
            output = "\n".join(logs.output)
            self.assertIn("[DB] SQLite initialized", output)
            self.assertIn(f"path={db_path}", output)
            self.assertIn(f"[DB] Schema version: {db_schema.SCHEMA_VERSION}", output)
            self.assertIn("[DB] WAL enabled: True", output)

    def test_runtime_bootstrap_raises_when_sqlite_unavailable(self):
        with self.assertLogs("db-bootstrap-fallback-test", level="ERROR") as logs, \
             patch.object(db, "initialize_database", side_effect=OSError("read-only")):
            with self.assertRaises(OSError):
                db.bootstrap_runtime_database(
                    pathlib.Path("/blocked/mymedialibrary.db"),
                    logger=logging.getLogger("db-bootstrap-fallback-test"),
                )

        self.assertIn("[DB] SQLite unavailable — runtime storage unavailable", "\n".join(logs.output))

    def test_runtime_bootstrap_runs_startup_tasks_once_across_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.object(db, "_has_legacy_json_sources", return_value=False), \
                     patch.object(db, "_migrate_runtime_json_sources") as migrate, \
                     patch.object(db, "_seed_bundled_defaults") as seed:
                    self.assertTrue(db.bootstrap_runtime_database(db_path))
                    db._startup_tasks_done = False
                    self.assertTrue(db.bootstrap_runtime_database(db_path))
            finally:
                db._startup_tasks_done = previous_done

            self.assertEqual(migrate.call_count, 0)
            self.assertEqual(seed.call_count, 1)

    def test_runtime_bootstrap_skips_migration_and_seed_when_already_initialized_without_legacy_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            conn = db.initialize_database(db_path)
            conn.execute("INSERT INTO app_config(key, value_json) VALUES (?, ?)", ("system", '{"log_level":"INFO"}'))
            conn.execute(
                "INSERT INTO score_settings(id, enabled, configuration_json) VALUES (?, ?, ?)",
                ("default", 1, '{"weights":{"video":50,"audio":20,"languages":15,"size":15}}'),
            )
            conn.commit()
            conn.close()
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.object(db, "_has_legacy_json_sources", return_value=False), \
                     patch.object(db, "_migrate_runtime_json_sources") as migrate, \
                     patch.object(db, "_seed_bundled_defaults") as seed, \
                     self.assertLogs("db-bootstrap-skip-test", level="INFO") as logs:
                    self.assertTrue(db.bootstrap_runtime_database(
                        db_path,
                        logger=logging.getLogger("db-bootstrap-skip-test"),
                    ))
            finally:
                db._startup_tasks_done = previous_done

            self.assertEqual(migrate.call_count, 0)
            self.assertEqual(seed.call_count, 0)
            output = "\n".join(logs.output)
            self.assertIn("[DB] Existing SQLite runtime detected", output)
            self.assertIn("[DB] No legacy JSON files found — skipping migration", output)
            self.assertIn("[DB] Database already initialized — skipping bundled default seed", output)
            self.assertNotIn("Import skipped", output)
            self.assertNotIn("rows=0", output)

    def test_runtime_bootstrap_runs_migration_only_when_legacy_json_exists_on_initialized_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            conn = db.initialize_database(db_path)
            conn.execute("INSERT INTO app_config(key, value_json) VALUES (?, ?)", ("system", '{"log_level":"INFO"}'))
            conn.execute(
                "INSERT INTO score_settings(id, enabled, configuration_json) VALUES (?, ?, ?)",
                ("default", 1, "{}"),
            )
            conn.commit()
            conn.close()
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.object(db, "_has_legacy_json_sources", return_value=True), \
                     patch.object(db, "_migrate_runtime_json_sources") as migrate, \
                     patch.object(db, "_seed_bundled_defaults") as seed:
                    self.assertTrue(db.bootstrap_runtime_database(db_path))
            finally:
                db._startup_tasks_done = previous_done

            self.assertEqual(migrate.call_count, 1)
            self.assertEqual(seed.call_count, 0)

    def test_runtime_bootstrap_runs_migration_and_seed_on_first_install_with_legacy_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.object(db, "_has_legacy_json_sources", return_value=True), \
                     patch.object(db, "_migrate_runtime_json_sources") as migrate, \
                     patch.object(db, "_seed_bundled_defaults") as seed:
                    self.assertTrue(db.bootstrap_runtime_database(db_path))
            finally:
                db._startup_tasks_done = previous_done

            self.assertEqual(migrate.call_count, 1)
            self.assertEqual(seed.call_count, 1)

    def test_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"

            first = db.initialize_database(db_path)
            first.execute("INSERT INTO app_config(key, value_json) VALUES (?, ?)", ("theme", '"dark"'))
            first.commit()
            first.close()

            second = db.initialize_database(db_path)
            rows = second.execute("SELECT key, value_json FROM app_config").fetchall()
            migrations = second.execute("SELECT version FROM schema_migrations").fetchall()
            second.close()

            self.assertEqual([(row["key"], row["value_json"]) for row in rows], [("theme", '"dark"')])
            self.assertEqual([row["version"] for row in migrations], [1, 2, 3, db_schema.SCHEMA_VERSION])

    def test_expected_tables_are_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")

            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            conn.close()

            self.assertEqual({row["name"] for row in rows}, db_schema.EXPECTED_TABLES)

    def test_schema_version_is_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")
            version = db.get_schema_version(conn)
            conn.close()

            self.assertEqual(version, db_schema.SCHEMA_VERSION)

    def test_foreign_keys_are_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")
            enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]

            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO seasons(media_id, season_number)
                    VALUES (?, ?)
                    """,
                    (999, 1),
                )

            conn.close()
            self.assertEqual(enabled, 1)

    def test_main_indexes_are_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")

            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            conn.close()

            self.assertTrue(db_schema.EXPECTED_INDEXES.issubset({row["name"] for row in rows}))

    def test_media_uses_stable_text_ids_for_json_compatibility(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")

            media_columns = {
                row["name"]: row["type"]
                for row in conn.execute("PRAGMA table_info(media)").fetchall()
            }
            season_columns = {
                row["name"]: row["type"]
                for row in conn.execute("PRAGMA table_info(seasons)").fetchall()
            }
            recommendation_columns = {
                row["name"]: row["type"]
                for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()
            }

            conn.close()

            self.assertEqual(media_columns["id"], "TEXT")
            self.assertEqual(season_columns["media_id"], "TEXT")
            self.assertEqual(recommendation_columns["id"], "TEXT")
            self.assertEqual(recommendation_columns["media_id"], "TEXT")

    def test_stable_media_ids_work_with_foreign_keys_and_cascade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")

            conn.execute(
                "INSERT INTO media(id, media_type, title) VALUES (?, ?, ?)",
                ("movie:Films:Inception (2010)", "movie", "Inception"),
            )
            conn.execute(
                "INSERT INTO seasons(media_id, season_number, title) VALUES (?, ?, ?)",
                ("movie:Films:Inception (2010)", 1, "Season 1"),
            )
            conn.execute(
                """
                INSERT INTO recommendations(id, media_id, recommendation_type, priority, title)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "rec:movie:Films:Inception (2010):low_score",
                    "movie:Films:Inception (2010)",
                    "quality",
                    "medium",
                    "Low score",
                ),
            )
            conn.commit()

            conn.execute("DELETE FROM media WHERE id = ?", ("movie:Films:Inception (2010)",))
            season_count = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
            rec_media_id = conn.execute("SELECT media_id FROM recommendations").fetchone()[0]
            conn.close()

            self.assertEqual(season_count, 0)
            self.assertIsNone(rec_media_id)

    def test_episode_numbering_is_nullable_for_non_classic_series_layouts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")
            episode_columns = {
                row["name"]: row["notnull"]
                for row in conn.execute("PRAGMA table_info(episodes)").fetchall()
            }
            conn.close()

            self.assertEqual(episode_columns["season_number"], 0)
            self.assertEqual(episode_columns["episode_number"], 0)

    def test_migration_is_noop_when_database_is_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")
            before = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

            db_migrations.migrate(conn)

            after = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            conn.close()

            self.assertEqual(before, db_schema.SCHEMA_VERSION)
            self.assertEqual(after, db_schema.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
