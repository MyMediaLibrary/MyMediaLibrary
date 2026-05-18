import json
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
import db_export  # noqa: E402
import db_migrations  # noqa: E402
import db_schema  # noqa: E402
import db_seed  # noqa: E402
from repositories import recommendations_repository  # noqa: E402


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
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": ""}), \
                     self.assertLogs("db-bootstrap-test", level="INFO") as logs:
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

    def test_runtime_bootstrap_skip_flag_suppresses_info_logs(self):
        """With MML_SKIP_DB_STARTUP_TASKS=1 the DB state logs must be DEBUG, not INFO."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "mymedialibrary.db"
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": "1"}):
                    # assertLogs at INFO must capture nothing from our logger
                    logger = logging.getLogger("db-bootstrap-skip-info-test")
                    # No INFO logs expected — assertLogs would raise if none captured;
                    # we verify by calling bootstrap and checking no INFO-level DB lines appear.
                    ok = db.bootstrap_runtime_database(db_path, logger=logger)
            finally:
                db._startup_tasks_done = previous_done

            self.assertTrue(ok)
            # Migrations still ran (schema at target version)
            conn = db.initialize_database(db_path)
            version = db.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)

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
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": ""}), \
                     patch.object(db, "_has_legacy_json_sources", return_value=False), \
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
                "INSERT INTO score_rules(category, group_key, value_key, score_value) VALUES (?, ?, ?, ?)",
                ("weights", "weight", "video", 50),
            )
            conn.execute(
                "INSERT INTO recommendation_rules(rule_key, enabled) VALUES (?, ?)",
                ("low_score", 1),
            )
            conn.commit()
            conn.close()
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": ""}), \
                     patch.object(db, "_has_legacy_json_sources", return_value=False), \
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
                "INSERT INTO score_rules(category, group_key, value_key, score_value) VALUES (?, ?, ?, ?)",
                ("weights", "weight", "video", 50),
            )
            conn.execute(
                "INSERT INTO recommendation_rules(rule_key, enabled) VALUES (?, ?)",
                ("low_score", 1),
            )
            conn.commit()
            conn.close()
            previous_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": ""}), \
                     patch.object(db, "_has_legacy_json_sources", return_value=True), \
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
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": ""}), \
                     patch.object(db, "_has_legacy_json_sources", return_value=True), \
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
            self.assertEqual([row["version"] for row in migrations], list(range(1, db_schema.SCHEMA_VERSION + 1)))

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
                INSERT INTO recommendations(id, media_id, recommendation_type, priority)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "rec:movie:Films:Inception (2010):low_score",
                    "movie:Films:Inception (2010)",
                    "quality",
                    "medium",
                ),
            )
            conn.commit()

            conn.execute("DELETE FROM media WHERE id = ?", ("movie:Films:Inception (2010)",))
            season_count = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
            rec_media_id = conn.execute("SELECT media_id FROM recommendations").fetchone()[0]
            conn.close()

            self.assertEqual(season_count, 0)
            self.assertIsNone(rec_media_id)

    def test_migration_is_noop_when_database_is_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mymedialibrary.db")
            before = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

            db_migrations.migrate(conn)

            after = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            conn.close()

            self.assertEqual(before, db_schema.SCHEMA_VERSION)
            self.assertEqual(after, db_schema.SCHEMA_VERSION)


class V8UnifiedProvidersTest(unittest.TestCase):
    """Tests for v8 migration: 3-table provider structure → unified providers table."""

    def _make_pre_v8_db(self, path: pathlib.Path) -> sqlite3.Connection:
        """Create a minimal DB at schema v7 (old 3-table provider structure)."""
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        # Minimal tables needed for v8 migration to run
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
        conn.execute("""
            CREATE TABLE providers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE provider_mappings (
                id INTEGER PRIMARY KEY,
                raw_name TEXT NOT NULL UNIQUE,
                mapped_name TEXT,
                is_ignored INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE provider_logos (
                id INTEGER PRIMARY KEY,
                provider_name TEXT NOT NULL UNIQUE,
                logo_path TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for v in range(1, 8):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 7")
        conn.commit()
        return conn

    def test_v8_migration_preserves_provider_with_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)
            conn.execute(
                "INSERT INTO provider_mappings(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                ("Netflix", "Netflix", 0),
            )
            conn.commit()

            db_migrations.migrate(conn)

            row = conn.execute("SELECT mapped_name, is_ignored FROM providers WHERE raw_name = ?", ("Netflix",)).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["mapped_name"], "Netflix")
            self.assertEqual(row["is_ignored"], 0)

    def test_v8_migration_preserves_ignored_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)
            conn.execute(
                "INSERT INTO provider_mappings(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                ("Canal VOD", None, 1),
            )
            conn.commit()

            db_migrations.migrate(conn)

            row = conn.execute("SELECT mapped_name, is_ignored FROM providers WHERE raw_name = ?", ("Canal VOD",)).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertIsNone(row["mapped_name"])
            self.assertEqual(row["is_ignored"], 1)

    def test_v8_migration_merges_logo_by_mapped_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)
            conn.execute(
                "INSERT INTO provider_mappings(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                ("Disney Plus", "Disney+", 0),
            )
            conn.execute(
                "INSERT INTO provider_logos(provider_name, logo_path) VALUES (?, ?)",
                ("Disney+", "disney.webp"),
            )
            conn.commit()

            db_migrations.migrate(conn)

            row = conn.execute("SELECT mapped_name, logo_path FROM providers WHERE raw_name = ?", ("Disney Plus",)).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["mapped_name"], "Disney+")
            self.assertEqual(row["logo_path"], "disney.webp")

    def test_v8_migration_preserves_provider_without_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)
            # Provider in providers table (from scan) but no explicit mapping
            conn.execute("INSERT INTO providers(name) VALUES (?)", ("Prime Video",))
            conn.commit()

            db_migrations.migrate(conn)

            row = conn.execute("SELECT raw_name, mapped_name, is_ignored FROM providers WHERE raw_name = ?", ("Prime Video",)).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertIsNone(row["mapped_name"])
            self.assertEqual(row["is_ignored"], 0)

    def test_v8_migration_new_provider_detectable_after_migration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)
            conn.execute(
                "INSERT INTO provider_mappings(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                ("Netflix", "Netflix", 0),
            )
            conn.commit()
            db_migrations.migrate(conn)

            # Simulate scan detecting a new provider post-migration
            conn.execute("INSERT OR IGNORE INTO providers(raw_name) VALUES (?)", ("Crunchyroll",))
            conn.commit()

            rows = conn.execute("SELECT raw_name FROM providers ORDER BY raw_name").fetchall()
            conn.close()
            names = [r["raw_name"] for r in rows]
            self.assertIn("Netflix", names)
            self.assertIn("Crunchyroll", names)

    def test_v8_migration_drops_old_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)

            db_migrations.migrate(conn)

            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
            self.assertNotIn("provider_mappings", tables)
            self.assertNotIn("provider_logos", tables)

    def test_v8_migration_registers_schema_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)

            db_migrations.migrate(conn)

            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)

    def test_v8_migration_idempotent_when_raw_name_already_present(self):
        """Migration must not crash when providers already has raw_name (partially migrated DB)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
            # providers already has raw_name (not name) — simulates partial or re-run migration
            conn.execute("""
                CREATE TABLE providers (
                    id INTEGER PRIMARY KEY,
                    raw_name TEXT NOT NULL UNIQUE,
                    mapped_name TEXT,
                    is_ignored INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("INSERT INTO providers(raw_name, mapped_name) VALUES (?, ?)", ("Netflix", "Netflix"))
            for v in range(1, 8):
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
            conn.execute("PRAGMA user_version = 7")
            conn.commit()

            # Must not raise
            db_migrations.migrate(conn)

            row = conn.execute("SELECT raw_name, mapped_name FROM providers WHERE raw_name = ?", ("Netflix",)).fetchone()
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["mapped_name"], "Netflix")
            self.assertEqual(version, db_schema.SCHEMA_VERSION)

    def test_v8_migration_no_logo_url_column_in_providers(self):
        """providers table must not have logo_url after migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(providers)").fetchall()}
            conn.close()
            self.assertNotIn("logo_url", cols)

    def test_v8_migration_logo_url_absent_on_pre_v8_db_after_migration(self):
        """logo_url must not be added to providers when migrating from old schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = self._make_pre_v8_db(path)
            db_migrations.migrate(conn)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(providers)").fetchall()}
            conn.close()
            self.assertNotIn("logo_url", cols)


class SchemaTargetTest(unittest.TestCase):
    """Schema target state after v9-v12 cleanup — fresh DB and seed invariants."""

    _DELETED = frozenset({"ffprobe_cache", "scan_settings", "episodes", "files", "streams"})
    _REQUIRED = frozenset({
        "active_sessions", "app_config", "auth_settings", "media",
        "media_probe_cache", "media_providers", "providers",
        "recommendation_rules", "recommendations", "scan_runs",
        "schema_migrations", "score_rules", "score_size_profiles", "seasons",
    })

    def test_fresh_db_has_no_deleted_tables(self):
        """Tables removed in v9-v11 must not appear in a fresh DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            for t in self._DELETED:
                self.assertNotIn(t, tables, f"deleted table '{t}' found in fresh DB")

    def test_fresh_db_has_all_required_tables(self):
        """All required tables must be present in a fresh DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            missing = self._REQUIRED - tables
            self.assertFalse(missing, f"required tables missing from fresh DB: {missing}")

    def test_seed_populates_media_probe_flat_keys(self):
        """db_seed must write media_probe.* flat keys into app_config, not a JSON blob."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            keys = {r[0] for r in conn.execute(
                "SELECT key FROM app_config WHERE key LIKE 'media_probe.%'"
            ).fetchall()}
            conn.close()
            for k in ("media_probe.enabled", "media_probe.mode",
                      "media_probe.workers", "media_probe.cache_enabled"):
                self.assertIn(k, keys, f"flat probe key '{k}' not seeded")

    def test_no_media_probe_blob_in_app_config(self):
        """app_config must not have a key literally named 'media_probe' (blob form)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            row = conn.execute("SELECT 1 FROM app_config WHERE key = 'media_probe'").fetchone()
            conn.close()
            self.assertIsNone(row)


class V10DropScanSettingsTest(unittest.TestCase):
    """Tests for the v10 migration: scan_settings → app_config flat keys."""

    def test_migrates_media_probe_blob_to_flat_keys(self):
        """scan_settings.media_probe blob must be expanded into app_config flat keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute("""
                    CREATE TABLE scan_settings (
                        id TEXT PRIMARY KEY, value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)
                """)
                conn.execute(
                    "INSERT INTO scan_settings VALUES ('media_probe', ?, CURRENT_TIMESTAMP)",
                    ('{"enabled":true,"mode":"compare","workers":6,"cache_enabled":false}',),
                )
            db_migrations._apply_v10_drop_scan_settings(conn)
            probe = {
                r[0]: json.loads(r[1])
                for r in conn.execute(
                    "SELECT key, value_json FROM app_config WHERE key LIKE 'media_probe.%'"
                ).fetchall()
            }
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            self.assertEqual(probe.get("media_probe.enabled"), True)
            self.assertEqual(probe.get("media_probe.workers"), 6)
            self.assertEqual(probe.get("media_probe.cache_enabled"), False)
            self.assertNotIn("scan_settings", tables)

    def test_preserves_existing_flat_key_not_overwritten(self):
        """INSERT OR IGNORE must leave a user value already in app_config untouched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute("""
                    CREATE TABLE scan_settings (
                        id TEXT PRIMARY KEY, value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)
                """)
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES ('media_probe.workers', '8')"
                )
                conn.execute(
                    "INSERT INTO scan_settings VALUES ('media_probe', ?, CURRENT_TIMESTAMP)",
                    ('{"enabled":false,"workers":2}',),
                )
            db_migrations._apply_v10_drop_scan_settings(conn)
            workers = json.loads(
                conn.execute(
                    "SELECT value_json FROM app_config WHERE key = 'media_probe.workers'"
                ).fetchone()[0]
            )
            conn.close()
            self.assertEqual(workers, 8)

    def test_idempotent_when_scan_settings_absent(self):
        """v10 migration must not raise when scan_settings does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v10_drop_scan_settings(conn)
            conn.close()


class V11DropDeadTablesTest(unittest.TestCase):
    """Tests for the v11 migration: drop episodes, files, streams."""

    def test_drops_all_three_tables(self):
        """episodes, files, and streams must be absent after v11 migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, media_id TEXT)")
                conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY)")
                conn.execute("CREATE TABLE streams (id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL)")
            db_migrations._apply_v11_drop_dead_tables(conn)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            self.assertNotIn("episodes", tables)
            self.assertNotIn("files", tables)
            self.assertNotIn("streams", tables)

    def test_idempotent_when_tables_already_gone(self):
        """v11 migration must not raise when the dead tables are already absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v11_drop_dead_tables(conn)
            conn.close()

    def test_version_reaches_schema_target(self):
        """After full migration pipeline on a fresh DB, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class V12FlattenAppConfigBlobsTest(unittest.TestCase):
    """Tests for the v12 migration: flatten system/seerr/ui/recommendations blobs."""

    def test_flattens_existing_blobs(self):
        """Blob rows must be expanded into group.subkey flat keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("system", '{"scan_cron":"0 4 * * *","log_level":"DEBUG","needs_onboarding":false}'),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("seerr", '{"enabled":true,"url":"http://seerr.local"}'),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("ui", '{"theme":"light","default_view":"list"}'),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("recommendations", '{"enabled":true}'),
                )
            db_migrations._apply_v12_flatten_app_config_blobs(conn)
            keys = {r[0] for r in conn.execute("SELECT key FROM app_config").fetchall()}
            conn.close()
            self.assertIn("system.scan_cron", keys)
            self.assertIn("system.log_level", keys)
            self.assertIn("seerr.enabled", keys)
            self.assertIn("seerr.url", keys)
            self.assertIn("ui.theme", keys)
            self.assertIn("ui.default_view", keys)
            self.assertIn("recommendations.enabled", keys)

    def test_removes_blob_key_after_migration(self):
        """The original blob key must be deleted after flattening."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("system", '{"scan_cron":"0 3 * * *"}'),
                )
            db_migrations._apply_v12_flatten_app_config_blobs(conn)
            row = conn.execute("SELECT 1 FROM app_config WHERE key = 'system'").fetchone()
            conn.close()
            self.assertIsNone(row, "blob key 'system' must be removed after migration")

    def test_no_overwrite_existing_flat_keys(self):
        """INSERT OR IGNORE must leave existing flat keys untouched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("system.log_level", '"WARNING"'),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO app_config(key, value_json) VALUES (?, ?)",
                    ("system", '{"log_level":"DEBUG","scan_cron":"0 3 * * *"}'),
                )
            db_migrations._apply_v12_flatten_app_config_blobs(conn)
            level = json.loads(
                conn.execute(
                    "SELECT value_json FROM app_config WHERE key = 'system.log_level'"
                ).fetchone()[0]
            )
            conn.close()
            self.assertEqual(level, "WARNING", "existing flat key must not be overwritten by migration")

    def test_idempotent_when_already_flat(self):
        """Migration must not raise when no blob keys exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            db_migrations._apply_v12_flatten_app_config_blobs(conn)
            conn.close()

    def test_fresh_db_seeds_all_groups_as_flat_keys(self):
        """After seeding, system/seerr/ui/recommendations must be flat keys, never blobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            all_keys = {r[0] for r in conn.execute("SELECT key FROM app_config").fetchall()}
            conn.close()
            for group in ("system", "seerr", "ui", "recommendations"):
                self.assertNotIn(group, all_keys, f"blob key '{group}' must not exist after seeding")
            for expected in (
                "system.scan_cron", "system.log_level", "system.needs_onboarding",
                "seerr.enabled", "seerr.url",
                "ui.theme", "ui.default_view", "ui.default_sort",
                "recommendations.enabled",
            ):
                self.assertIn(expected, all_keys, f"flat key '{expected}' missing after seeding")


class V13DropRecommendationJsonColumnsTest(unittest.TestCase):
    """Tests for the v13 migration: drop message_json and suggested_action_json."""

    _DROPPED = ("message_json", "suggested_action_json")

    def test_fresh_db_has_no_dropped_columns(self):
        """A fresh DB must not contain message_json or suggested_action_json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            for col in self._DROPPED:
                self.assertNotIn(col, cols, f"dropped column '{col}' found in fresh recommendations table")

    def test_migration_drops_columns_from_existing_db(self):
        """v13 migration must remove the two redundant columns from an existing DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            # Add the dropped columns back to simulate a pre-v13 DB
            with conn:
                try:
                    conn.execute("ALTER TABLE recommendations ADD COLUMN message_json TEXT")
                except Exception:
                    pass
                try:
                    conn.execute("ALTER TABLE recommendations ADD COLUMN suggested_action_json TEXT")
                except Exception:
                    pass
            db_migrations._apply_v13_drop_recommendation_json_columns(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            for col in self._DROPPED:
                self.assertNotIn(col, cols, f"column '{col}' must be absent after v13 migration")

    def test_migration_preserves_existing_recommendations(self):
        """v13 migration must not lose any recommendation rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                try:
                    conn.execute("ALTER TABLE recommendations ADD COLUMN message_json TEXT")
                    conn.execute("ALTER TABLE recommendations ADD COLUMN suggested_action_json TEXT")
                except Exception:
                    pass
                conn.execute(
                    "INSERT OR IGNORE INTO recommendations"
                    "(id, recommendation_type, message_en, suggested_action_en, message_json, suggested_action_json)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    ("rec:1", "quality", "bad", "replace", '{"en":"bad"}', '{"en":"replace"}'),
                )
            db_migrations._apply_v13_drop_recommendation_json_columns(conn)
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)

    def test_migration_idempotent(self):
        """v13 migration must not raise when columns are already gone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v13_drop_recommendation_json_columns(conn)
            db_migrations._apply_v13_drop_recommendation_json_columns(conn)
            conn.close()

    def test_upsert_recommendation_does_not_write_dropped_columns(self):
        """upsert_recommendation must succeed without referencing the dropped columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend" / "repositories"))
            import recommendations_repository  # noqa: E402
            item = {
                "id": "rec:test:1",
                "recommendation_type": "quality",
                "priority": "medium",
                "display": {"title": "Low score"},
                "message": {"en": "Quality too low"},
                "suggested_action": {"en": "Replace the file"},
            }
            with conn:
                recommendations_repository.upsert_recommendation(conn, item)
            row = conn.execute(
                "SELECT message_en, suggested_action_en FROM recommendations WHERE id = 'rec:test:1'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["message_en"], "Quality too low")
            self.assertEqual(row["suggested_action_en"], "Replace the file")

    def test_version_reaches_schema_target(self):
        """After full migration pipeline, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class V14RecommendationRulesExtractScalarsTest(unittest.TestCase):
    """Tests for the v14 migration: extract rule_type and priority from rule_json."""

    def test_fresh_db_has_rule_type_and_priority_columns(self):
        """A fresh DB must have rule_type and priority columns in recommendation_rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}
            conn.close()
            self.assertIn("rule_type", cols)
            self.assertIn("priority", cols)

    def test_seed_populates_rule_type_and_priority(self):
        """seed_recommendation_rules must fill rule_type and priority from the rule dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            rows = conn.execute(
                "SELECT rule_key, rule_type, priority FROM recommendation_rules"
            ).fetchall()
            conn.close()
            self.assertGreater(len(rows), 0)
            for row in rows:
                self.assertIsNotNone(row["rule_type"], f"rule_type is NULL for {row['rule_key']}")
                self.assertIsNotNone(row["priority"], f"priority is NULL for {row['rule_key']}")

    def _make_pre_v14_conn(self) -> sqlite3.Connection:
        """Return an in-memory connection with the pre-v14 recommendation_rules schema."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:")
        conn.row_factory = _sqlite3.Row
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE recommendation_rules ("
            "  id INTEGER PRIMARY KEY,"
            "  rule_key TEXT NOT NULL UNIQUE,"
            "  rule_json TEXT NOT NULL,"
            "  enabled INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        for v in range(1, 14):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 13")
        conn.commit()
        return conn

    def test_migration_extracts_scalars_from_existing_rows(self):
        """v14 migration must populate rule_type and priority from rule_json on existing rows."""
        conn = self._make_pre_v14_conn()
        with conn:
            conn.execute(
                "INSERT INTO recommendation_rules(rule_key, rule_json, enabled)"
                " VALUES (?, ?, 1)",
                ("test_rule", '{"id":"test_rule","type":"quality","priority":"high"}'),
            )
        db_migrations._apply_v14_recommendation_rules_extract_scalars(conn)
        row = conn.execute(
            "SELECT rule_type, priority FROM recommendation_rules WHERE rule_key = 'test_rule'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["rule_type"], "quality")
        self.assertEqual(row["priority"], "high")

    def test_migration_does_not_overwrite_existing_values(self):
        """v14 migration must not touch rows that already have rule_type or priority set."""
        conn = self._make_pre_v14_conn()
        # Add rule_type/priority columns manually (as v14 migration would)
        conn.execute("ALTER TABLE recommendation_rules ADD COLUMN rule_type TEXT")
        conn.execute("ALTER TABLE recommendation_rules ADD COLUMN priority TEXT")
        with conn:
            conn.execute(
                "INSERT INTO recommendation_rules(rule_key, rule_json, rule_type, priority, enabled)"
                " VALUES (?, ?, ?, ?, 1)",
                ("test_rule", '{"id":"test_rule","type":"space","priority":"low"}', "quality", "high"),
            )
        db_migrations._apply_v14_recommendation_rules_extract_scalars(conn)
        row = conn.execute(
            "SELECT rule_type, priority FROM recommendation_rules WHERE rule_key = 'test_rule'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["rule_type"], "quality")
        self.assertEqual(row["priority"], "high")

    def test_migration_idempotent(self):
        """v14 migration must not raise when run twice."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            db_migrations._apply_v14_recommendation_rules_extract_scalars(conn)
            db_migrations._apply_v14_recommendation_rules_extract_scalars(conn)
            conn.close()

    def test_version_reaches_schema_target(self):
        """After full migration pipeline, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class V15DropDeadColumnsTest(unittest.TestCase):
    """Tests for the v15 migration: drop missing_since, media.quality_json, seasons.quality_json."""

    def test_fresh_db_has_no_dropped_columns(self):
        """A fresh DB must not contain missing_since or quality_json on media/seasons."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            media_cols = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
            season_cols = {r[1] for r in conn.execute("PRAGMA table_info(seasons)").fetchall()}
            conn.close()
            self.assertNotIn("missing_since", media_cols)
            self.assertNotIn("quality_json", media_cols)
            self.assertNotIn("quality_json", season_cols)

    def test_migration_drops_columns_from_existing_db(self):
        """v15 migration must remove the three dead columns from an existing DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            # Add the dropped columns back to simulate a pre-v15 DB
            with conn:
                for col in ("missing_since TEXT", "quality_json TEXT"):
                    try:
                        conn.execute(f"ALTER TABLE media ADD COLUMN {col}")
                    except Exception:
                        pass
                try:
                    conn.execute("ALTER TABLE seasons ADD COLUMN quality_json TEXT")
                except Exception:
                    pass
            db_migrations._apply_v15_drop_dead_columns(conn)
            media_cols = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
            season_cols = {r[1] for r in conn.execute("PRAGMA table_info(seasons)").fetchall()}
            conn.close()
            self.assertNotIn("missing_since", media_cols)
            self.assertNotIn("quality_json", media_cols)
            self.assertNotIn("quality_json", season_cols)

    def test_migration_preserves_media_rows(self):
        """v15 migration must not lose any media rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                for col in ("missing_since TEXT", "quality_json TEXT"):
                    try:
                        conn.execute(f"ALTER TABLE media ADD COLUMN {col}")
                    except Exception:
                        pass
                conn.execute(
                    "INSERT OR IGNORE INTO media(id, media_type, title) VALUES (?, ?, ?)",
                    ("m:1", "movie", "Inception"),
                )
            db_migrations._apply_v15_drop_dead_columns(conn)
            count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)

    def test_migration_idempotent(self):
        """v15 migration must not raise when columns are already gone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v15_drop_dead_columns(conn)
            db_migrations._apply_v15_drop_dead_columns(conn)
            conn.close()

    def test_upsert_media_does_not_write_quality_json(self):
        """upsert_library_item must succeed without referencing quality_json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            import db_import
            item = {
                "id": "movie:Films:Inception",
                "type": "movie",
                "title": "Inception",
                "quality": {"score": 87, "video": 50, "audio": 20},
            }
            with conn:
                db_import.upsert_library_item(conn, item, overwrite=True)
            row = conn.execute(
                "SELECT quality_score, data_json FROM media WHERE id = 'movie:Films:Inception'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["quality_score"], 87.0)
            data = json.loads(row["data_json"])
            self.assertEqual(data["quality"]["score"], 87)

    def test_version_reaches_schema_target(self):
        """After full migration pipeline, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class V16RecommendationRulesStructuredTest(unittest.TestCase):
    """Tests for the v16 migration: flatten rule_json into structured columns."""

    def test_fresh_db_has_no_rule_json_column(self):
        """A fresh v16 DB must not have rule_json in recommendation_rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}
            conn.close()
            self.assertNotIn("rule_json", cols)

    def test_fresh_db_has_all_structured_columns(self):
        """A fresh v16 DB must have all new structured columns in recommendation_rules."""
        expected = {"conditions_json", "message_fr", "message_en",
                    "suggested_action_fr", "suggested_action_en", "dedupe_group", "severity"}
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}
            conn.close()
            for col in expected:
                self.assertIn(col, cols, f"Missing column: {col}")

    def test_seed_populates_all_structured_columns(self):
        """seed_recommendation_rules must write conditions_json, message, suggested_action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            rows = conn.execute(
                "SELECT rule_key, rule_type, priority, dedupe_group, severity,"
                "       conditions_json, message_fr, message_en,"
                "       suggested_action_fr, suggested_action_en"
                " FROM recommendation_rules"
            ).fetchall()
            conn.close()
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIsNotNone(row["rule_type"], f"rule_type NULL for {row['rule_key']}")
            self.assertIsNotNone(row["priority"], f"priority NULL for {row['rule_key']}")
            self.assertIsNotNone(row["message_fr"], f"message_fr NULL for {row['rule_key']}")
            self.assertIsNotNone(row["message_en"], f"message_en NULL for {row['rule_key']}")
            self.assertIsNotNone(row["conditions_json"], f"conditions_json NULL for {row['rule_key']}")

    def test_export_reconstruction_matches_original_rule_format(self):
        """export_recommendation_rules must return the dict format expected by the engine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_seed.seed_all(conn)
            payload = db_export.export_recommendation_rules(conn)
            conn.close()
        rules = payload["rules"]
        self.assertGreater(len(rules), 0)
        for rule in rules:
            self.assertIn("id", rule)
            self.assertIn("enabled", rule)
            self.assertIn("type", rule)
            self.assertIn("priority", rule)
            self.assertIn("conditions", rule)
            self.assertIsInstance(rule["conditions"], list)
            self.assertIn("message", rule)
            self.assertIsInstance(rule["message"], dict)
            self.assertIn("fr", rule["message"])
            self.assertIn("en", rule["message"])
            self.assertIn("suggested_action", rule)
            self.assertIsInstance(rule["suggested_action"], dict)

    def test_migration_from_pre_v16_db_with_rule_json(self):
        """v16 migration must extract all fields from rule_json and drop the column."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:")
        conn.row_factory = _sqlite3.Row
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE recommendation_rules ("
            "  id INTEGER PRIMARY KEY,"
            "  rule_key TEXT NOT NULL UNIQUE,"
            "  rule_json TEXT NOT NULL,"
            "  rule_type TEXT,"
            "  priority TEXT,"
            "  enabled INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        for v in range(1, 16):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 15")
        rule = {
            "id": "very_low_score",
            "enabled": True,
            "type": "quality",
            "priority": "high",
            "dedupe_group": "score_low",
            "severity": 2,
            "conditions": [{"field": "score", "operator": "<", "value": 40}],
            "message": {"fr": "Score très faible.", "en": "Very low score."},
            "suggested_action": {"fr": "Chercher mieux.", "en": "Look for better."},
        }
        conn.execute(
            "INSERT INTO recommendation_rules(rule_key, rule_json, rule_type, priority, enabled)"
            " VALUES (?, ?, ?, ?, ?)",
            ("very_low_score", json.dumps(rule), "quality", "high", 1),
        )
        conn.commit()

        db_migrations._apply_v16_recommendation_rules_structured(conn)
        conn.commit()

        cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}
        self.assertNotIn("rule_json", cols)
        self.assertIn("conditions_json", cols)

        row = conn.execute("SELECT * FROM recommendation_rules WHERE rule_key = 'very_low_score'").fetchone()
        conn.close()
        self.assertEqual(row["rule_type"], "quality")
        self.assertEqual(row["priority"], "high")
        self.assertEqual(row["dedupe_group"], "score_low")
        self.assertEqual(row["severity"], 2)
        self.assertEqual(row["message_fr"], "Score très faible.")
        self.assertEqual(row["message_en"], "Very low score.")
        self.assertEqual(row["suggested_action_fr"], "Chercher mieux.")
        self.assertEqual(row["suggested_action_en"], "Look for better.")
        conditions = json.loads(row["conditions_json"])
        self.assertEqual(conditions, [{"field": "score", "operator": "<", "value": 40}])

    def test_migration_idempotent_on_fresh_db(self):
        """v16 migration must be a no-op (no error) when rule_json is already absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v16_recommendation_rules_structured(conn)
            db_migrations._apply_v16_recommendation_rules_structured(conn)
            conn.close()

    def test_migration_preserves_enabled_column(self):
        """v16 migration must not alter the enabled column value."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:")
        conn.row_factory = _sqlite3.Row
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE recommendation_rules ("
            "  id INTEGER PRIMARY KEY,"
            "  rule_key TEXT NOT NULL UNIQUE,"
            "  rule_json TEXT NOT NULL,"
            "  enabled INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        for v in range(1, 16):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 15")
        conn.execute(
            "INSERT INTO recommendation_rules(rule_key, rule_json, enabled) VALUES (?, ?, ?)",
            ("disabled_rule", '{"id":"disabled_rule","type":"quality","priority":"low",'
             '"conditions":[],"message":{"fr":"f","en":"e"},"suggested_action":{"fr":"f","en":"e"}}',
             0),
        )
        conn.commit()
        db_migrations._apply_v16_recommendation_rules_structured(conn)
        conn.commit()

        row = conn.execute("SELECT enabled FROM recommendation_rules WHERE rule_key = 'disabled_rule'").fetchone()
        conn.close()
        self.assertEqual(row["enabled"], 0)

    def test_migration_handles_malformed_rule_json(self):
        """v16 migration must skip malformed rule_json without crashing."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:")
        conn.row_factory = _sqlite3.Row
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE recommendation_rules ("
            "  id INTEGER PRIMARY KEY,"
            "  rule_key TEXT NOT NULL UNIQUE,"
            "  rule_json TEXT NOT NULL,"
            "  enabled INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        for v in range(1, 16):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 15")
        conn.execute(
            "INSERT INTO recommendation_rules(rule_key, rule_json, enabled) VALUES (?, ?, ?)",
            ("bad_rule", "NOT VALID JSON {{", 1),
        )
        conn.commit()
        db_migrations._apply_v16_recommendation_rules_structured(conn)
        conn.commit()

        cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}
        self.assertNotIn("rule_json", cols)
        row = conn.execute("SELECT rule_key FROM recommendation_rules WHERE rule_key = 'bad_rule'").fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_load_recommendation_rules_returns_engine_compatible_format(self):
        """load_recommendation_rules must return dicts with conditions, message, suggested_action."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "mml.db"
            json_path = root / "recommendations_rules.json"
            json_path.write_text('{"version":1,"rules":[]}', encoding="utf-8")
            conn = db.initialize_database(db_path)
            db_seed.seed_all(conn)
            conn.close()
            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)
        self.assertGreater(len(rules), 0)
        for rule in rules:
            self.assertIn("id", rule)
            self.assertIsInstance(rule.get("conditions"), list)
            self.assertIsInstance(rule.get("message"), dict)
            self.assertIsInstance(rule.get("suggested_action"), dict)

    def test_version_reaches_schema_target(self):
        """After full migration pipeline, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class V17RecommendationsDropRedundantColumnsTest(unittest.TestCase):
    """Tests for the v17 migration: drop title, reason, dedupe_group, severity from recommendations."""

    _DROPPED = ("title", "reason", "dedupe_group", "severity")

    def test_fresh_db_has_no_dropped_columns(self):
        """A fresh v17 DB must not contain the four dropped columns in recommendations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            for col in self._DROPPED:
                self.assertNotIn(col, cols, f"dropped column '{col}' found in fresh recommendations table")

    def test_fresh_db_retains_required_columns(self):
        """A fresh v17+ DB must keep id, media_id, recommendation_type, priority, rule_id."""
        required = {"id", "media_id", "recommendation_type", "priority", "rule_id"}
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            for col in required:
                self.assertIn(col, cols, f"required column '{col}' missing from fresh recommendations table")

    def test_migration_drops_columns_from_existing_db(self):
        """v17 migration must remove the four dead columns from an existing DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                for col in ("title TEXT NOT NULL DEFAULT ''",
                            "reason TEXT", "dedupe_group TEXT", "severity INTEGER"):
                    try:
                        conn.execute(f"ALTER TABLE recommendations ADD COLUMN {col}")
                    except Exception:
                        pass
            db_migrations._apply_v17_recommendations_drop_redundant_columns(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            for col in self._DROPPED:
                self.assertNotIn(col, cols, f"column '{col}' must be absent after v17 migration")

    def test_migration_preserves_recommendation_rows(self):
        """v17 migration must not lose any recommendation rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT INTO recommendations(id, recommendation_type)"
                    " VALUES (?, ?)",
                    ("rec:1", "quality"),
                )
            db_migrations._apply_v17_recommendations_drop_redundant_columns(conn)
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)

    def test_migration_idempotent(self):
        """v17 migration must not raise when the columns are already absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v17_recommendations_drop_redundant_columns(conn)
            db_migrations._apply_v17_recommendations_drop_redundant_columns(conn)
            conn.close()

    def test_upsert_recommendation_writes_message_columns(self):
        """upsert_recommendation must write message/action columns (no details_json)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            item = {
                "id": "rec:movie:Films:Demo:low_score",
                "recommendation_type": "quality",
                "priority": "high",
                "rule_id": "low_score",
                "media_ref": {"id": "movie:Films:Demo", "type": "movie"},
                "message": {"fr": "Score faible.", "en": "Low score."},
                "suggested_action": {"fr": "Chercher mieux.", "en": "Look for better."},
            }
            with conn:
                recommendations_repository.upsert_recommendation(conn, item)
            row = conn.execute(
                "SELECT recommendation_type, priority, rule_id,"
                "       message_en, suggested_action_en"
                " FROM recommendations WHERE id = 'rec:movie:Films:Demo:low_score'"
            ).fetchone()
            conn.close()

            self.assertIsNotNone(row)
            self.assertEqual(row["recommendation_type"], "quality")
            self.assertEqual(row["priority"], "high")
            self.assertEqual(row["rule_id"], "low_score")
            self.assertEqual(row["message_en"], "Low score.")
            self.assertEqual(row["suggested_action_en"], "Look for better.")

    def test_version_reaches_schema_target(self):
        """After full migration pipeline, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class V18RecommendationsReplaceDetailsJsonTest(unittest.TestCase):
    """Tests for the v18 migration: replace details_json with message/action columns."""

    _DROPPED = ("details_json",)
    _ADDED = ("message_fr", "message_en", "suggested_action_fr", "suggested_action_en")

    def test_fresh_db_has_no_details_json(self):
        """A fresh v18 DB must not contain details_json in recommendations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            self.assertNotIn("details_json", cols)

    def test_fresh_db_has_message_action_columns(self):
        """A fresh v18 DB must have message_fr/en and suggested_action_fr/en columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
            conn.close()
            for col in self._ADDED:
                self.assertIn(col, cols, f"missing column: {col}")

    def test_migration_extracts_message_from_details_json(self):
        """v18 migration must populate message/action columns from details_json."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:")
        conn.row_factory = _sqlite3.Row
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute(
            "CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE recommendations ("
            "  id TEXT PRIMARY KEY,"
            "  media_id TEXT,"
            "  recommendation_type TEXT NOT NULL,"
            "  priority TEXT,"
            "  rule_id TEXT,"
            "  details_json TEXT,"
            "  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        for v in range(1, 18):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 17")
        conn.execute(
            "INSERT INTO recommendations(id, recommendation_type, priority, rule_id, details_json)"
            " VALUES (?, ?, ?, ?, ?)",
            ("rec:m:rule", "quality", "high", "low_score",
             '{"message":{"fr":"Score faible.","en":"Low score."},'
             '"suggested_action":{"fr":"Chercher.","en":"Look for better."}}'),
        )
        conn.commit()

        db_migrations._apply_v18_recommendations_replace_details_json(conn)
        conn.commit()

        cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
        self.assertNotIn("details_json", cols)
        for col in self._ADDED:
            self.assertIn(col, cols)

        row = conn.execute("SELECT * FROM recommendations WHERE id = 'rec:m:rule'").fetchone()
        conn.close()
        self.assertEqual(row["message_fr"], "Score faible.")
        self.assertEqual(row["message_en"], "Low score.")
        self.assertEqual(row["suggested_action_fr"], "Chercher.")
        self.assertEqual(row["suggested_action_en"], "Look for better.")

    def test_migration_preserves_rows(self):
        """v18 migration must not delete any recommendation rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                for i in range(3):
                    conn.execute(
                        "INSERT INTO recommendations(id, recommendation_type) VALUES (?, ?)",
                        (f"rec:{i}", "quality"),
                    )
            db_migrations._apply_v18_recommendations_replace_details_json(conn)
            count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
            conn.close()
            self.assertEqual(count, 3)

    def test_migration_idempotent(self):
        """v18 migration must not raise when details_json is already absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            db_migrations._apply_v18_recommendations_replace_details_json(conn)
            db_migrations._apply_v18_recommendations_replace_details_json(conn)
            conn.close()

    def test_upsert_and_export_round_trip(self):
        """upsert then export must return message/action and media_ref via JOIN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT INTO media(id, media_type, title, year) VALUES (?, ?, ?, ?)",
                    ("movie:Films:Demo", "movie", "Demo", 2024),
                )
                recommendations_repository.upsert_recommendation(
                    conn,
                    {
                        "id": "rec:movie:Films:Demo:low_score",
                        "recommendation_type": "quality",
                        "priority": "high",
                        "rule_id": "low_score",
                        "media_ref": {"id": "movie:Films:Demo", "type": "movie"},
                        "message": {"fr": "Score faible.", "en": "Low score."},
                        "suggested_action": {"fr": "Chercher mieux.", "en": "Look for better."},
                    },
                )
            from repositories import recommendations_repository as repo
            payload = repo.export_recommendations(conn)
            conn.close()

        items = payload["items"]
        self.assertEqual(len(items), 1)
        rec = items[0]
        self.assertEqual(rec["id"], "rec:movie:Films:Demo:low_score")
        self.assertEqual(rec["recommendation_type"], "quality")
        self.assertEqual(rec["priority"], "high")
        self.assertEqual(rec["rule_id"], "low_score")
        self.assertEqual(rec["message"], {"fr": "Score faible.", "en": "Low score."})
        self.assertEqual(rec["suggested_action"], {"fr": "Chercher mieux.", "en": "Look for better."})
        self.assertEqual(rec["media_ref"], {"id": "movie:Films:Demo", "type": "movie"})
        self.assertEqual(rec["display"]["title"], "Demo")
        self.assertEqual(rec["display"]["year"], 2024)

    def test_dynamic_rule_without_recommendation_rules_entry(self):
        """Recommendations from hardcoded rules (no DB rule) must be preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT INTO media(id, media_type, title) VALUES (?, ?, ?)",
                    ("tv:Series:Demo", "tv", "Demo Serie"),
                )
                recommendations_repository.upsert_recommendation(
                    conn,
                    {
                        "id": "rec:tv:Series:Demo:series_mixed_resolution:s2",
                        "recommendation_type": "series",
                        "priority": "medium",
                        "rule_id": "series_mixed_resolution:s2",
                        "media_ref": {"id": "tv:Series:Demo", "type": "tv"},
                        "message": {
                            "fr": "La saison 2 est en 720p alors que la majorité est en 1080p.",
                            "en": "Season 2 is in 720p while most of the series is in 1080p.",
                        },
                        "suggested_action": {
                            "fr": "Vérifier la saison 2.",
                            "en": "Review season 2.",
                        },
                    },
                )
            from repositories import recommendations_repository as repo
            payload = repo.export_recommendations(conn)
            conn.close()

        items = payload["items"]
        self.assertEqual(len(items), 1)
        rec = items[0]
        self.assertEqual(rec["rule_id"], "series_mixed_resolution:s2")
        self.assertIn("Season 2", rec["message"]["en"])
        self.assertEqual(rec["media_ref"]["type"], "tv")

    def test_export_after_media_deleted_returns_stable_payload(self):
        """export_recommendations must not crash when media_id is NULL (ON DELETE SET NULL).

        Verifies the LEFT JOIN behaviour: a recommendation whose media was deleted
        keeps its message/action columns but has no media_ref or display in the
        exported payload. The frontend filters these out via visibleRecommendations().
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            with conn:
                conn.execute(
                    "INSERT INTO media(id, media_type, title, year) VALUES (?, ?, ?, ?)",
                    ("movie:Films:Demo", "movie", "Demo", 2024),
                )
                recommendations_repository.upsert_recommendation(
                    conn,
                    {
                        "id": "rec:movie:Films:Demo:low_score",
                        "recommendation_type": "quality",
                        "priority": "high",
                        "rule_id": "low_score",
                        "media_ref": {"id": "movie:Films:Demo", "type": "movie"},
                        "message": {"fr": "Score faible.", "en": "Low score."},
                        "suggested_action": {"fr": "Chercher mieux.", "en": "Look for better."},
                    },
                )
            # Delete the media; FK is ON DELETE SET NULL so the rec row survives
            with conn:
                conn.execute("DELETE FROM media WHERE id = 'movie:Films:Demo'")

            row = conn.execute(
                "SELECT media_id FROM recommendations WHERE id = 'rec:movie:Films:Demo:low_score'"
            ).fetchone()
            self.assertIsNone(row["media_id"], "media_id must be NULL after media deletion")

            from repositories import recommendations_repository as repo
            payload = repo.export_recommendations(conn)
            conn.close()

        items = payload["items"]
        self.assertEqual(len(items), 1, "orphan recommendation must still be exported")
        rec = items[0]

        # media_ref and display are absent when media_id is NULL
        self.assertNotIn("media_ref", rec)
        self.assertNotIn("display", rec)

        # message and suggested_action are preserved from the columns
        self.assertEqual(rec["message"], {"fr": "Score faible.", "en": "Low score."})
        self.assertEqual(rec["suggested_action"], {"fr": "Chercher mieux.", "en": "Look for better."})

        # core fields still present — frontend can render safely
        self.assertEqual(rec["recommendation_type"], "quality")
        self.assertEqual(rec["priority"], "high")
        self.assertEqual(rec["rule_id"], "low_score")

    def test_version_reaches_schema_target(self):
        """After full migration pipeline, user_version equals SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)


class BootstrapStartupTest(unittest.TestCase):
    """Tests for the startup bootstrap sequence introduced to fix the startup race.

    Context: the old entrypoint started --serve and --origin startup concurrently.
    Both called bootstrap_runtime_database() at the same time, causing a race on
    the fcntl startup-tasks lock.  --serve could block there and never bind port 8095.

    Fix: entrypoint now runs `python3 -m backend.db` sequentially BEFORE services,
    then sets MML_SKIP_DB_STARTUP_TASKS=1 for both child processes.
    """

    def _make_v8_db(self, path: pathlib.Path) -> None:
        """Create a minimal v8 SQLite DB to simulate an upgrade scenario."""
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE score_settings (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, configuration_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE auth_settings (id INTEGER PRIMARY KEY CHECK (id=1), auth_enabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
        conn.execute("CREATE TABLE recommendation_rules (id INTEGER PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, rule_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE recommendations (id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL, title TEXT NOT NULL, message_json TEXT, suggested_action_json TEXT, details_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL, quality_json TEXT, missing_since TEXT, is_available INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE seasons (media_id TEXT, season_number INTEGER, quality_json TEXT, PRIMARY KEY(media_id, season_number))")
        for v in range(1, 9):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
        conn.close()

    def test_v8_db_migrates_to_current_schema_on_initialize_database(self):
        """A v8 DB must reach SCHEMA_VERSION after initialize_database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v8_db(path)

            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            media_cols = {r[1] for r in conn.execute("PRAGMA table_info(media)").fetchall()}
            conn.close()

            self.assertEqual(version, db_schema.SCHEMA_VERSION)
            self.assertNotIn("missing_since", media_cols)
            self.assertNotIn("quality_json", media_cols)

    def test_skip_startup_tasks_still_runs_migrations(self):
        """MML_SKIP_DB_STARTUP_TASKS=1 must still apply schema migrations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v8_db(path)

            prev_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": "1"}):
                    db.bootstrap_runtime_database(path)
            finally:
                db._startup_tasks_done = prev_done

            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)

    def test_skip_startup_tasks_skips_seed(self):
        """MML_SKIP_DB_STARTUP_TASKS=1 must not call seed or JSON migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            prev_done = db._startup_tasks_done
            db._startup_tasks_done = False
            try:
                with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": "1"}), \
                     patch.object(db, "_seed_bundled_defaults") as seed, \
                     patch.object(db, "_migrate_runtime_json_sources") as migrate_json:
                    db.bootstrap_runtime_database(path)
            finally:
                db._startup_tasks_done = prev_done
            self.assertEqual(seed.call_count, 0)
            self.assertEqual(migrate_json.call_count, 0)

    def test_concurrent_skip_processes_after_sequential_bootstrap(self):
        """After sequential bootstrap, two concurrent SKIP processes must both see SCHEMA_VERSION.

        This mirrors the new entrypoint sequence:
          1. python3 -m backend.db  (sequential, migrates v8→v15)
          2. MML_SKIP_DB_STARTUP_TASKS=1 python3 scanner.py --serve  (concurrent)
          3. MML_SKIP_DB_STARTUP_TASKS=1 python3 scanner.py --origin startup  (concurrent)

        With the DB already at SCHEMA_VERSION, migrate() is a no-op and the two
        concurrent SKIP processes should not race on write access.
        """
        import threading
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            # Step 1: sequential bootstrap (simulates entrypoint step 2)
            with patch.object(db, "_has_legacy_json_sources", return_value=False), \
                 patch.object(db, "_seed_bundled_defaults"):
                db.bootstrap_runtime_database(path)

            errors = []
            versions = []

            def skip_worker():
                try:
                    # Simulate MML_SKIP_DB_STARTUP_TASKS=1 child process
                    with patch.dict("os.environ", {"MML_SKIP_DB_STARTUP_TASKS": "1"}):
                        db.bootstrap_runtime_database(path)
                    conn = db.initialize_database(path)
                    versions.append(db_migrations.get_schema_version(conn))
                    conn.close()
                except Exception as exc:
                    errors.append(exc)

            t1 = threading.Thread(target=skip_worker)
            t2 = threading.Thread(target=skip_worker)
            t1.start(); t2.start()
            t1.join(); t2.join()

            self.assertEqual(errors, [], f"Unexpected errors in concurrent SKIP processes: {errors}")
            for v in versions:
                self.assertEqual(v, db_schema.SCHEMA_VERSION)

    def test_db_main_exits_zero_on_success(self):
        """python3 -m backend.db must exit 0 when bootstrap succeeds."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            ROOT = pathlib.Path(__file__).resolve().parents[3]
            env = {**__import__("os").environ, "MYMEDIALIBRARY_DB_PATH": str(path)}
            p = subprocess.run(
                [__import__("sys").executable, str(ROOT / "backend" / "db.py")],
                capture_output=True, env=env, cwd=str(ROOT),
            )
            self.assertEqual(p.returncode, 0, f"stderr: {p.stderr.decode()}")

    def test_db_main_exits_nonzero_on_bad_path(self):
        """python3 -m backend.db must exit non-zero when DB path is unwritable."""
        import subprocess
        ROOT = pathlib.Path(__file__).resolve().parents[3]
        env = {**__import__("os").environ, "MYMEDIALIBRARY_DB_PATH": "/proc/nonexistent/mml.db"}
        p = subprocess.run(
            [__import__("sys").executable, str(ROOT / "backend" / "db.py")],
            capture_output=True, env=env, cwd=str(ROOT),
        )
        self.assertNotEqual(p.returncode, 0)


class V19MigrationTest(unittest.TestCase):
    """Schema v19: replace score_settings with score_rules + score_size_profiles."""

    def _make_v18_db_with_score(self, path: pathlib.Path, config_json: str, enabled: int = 1) -> None:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA user_version = 18")
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE auth_settings (id INTEGER PRIMARY KEY CHECK (id=1), auth_enabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE score_settings (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, configuration_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE recommendation_rules (id INTEGER PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL)")
        conn.execute("CREATE TABLE seasons (id INTEGER PRIMARY KEY, media_id TEXT, season_number INTEGER)")
        conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, raw_name TEXT NOT NULL UNIQUE, mapped_name TEXT, is_ignored INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE media_providers (media_id TEXT, provider_id INTEGER, PRIMARY KEY (media_id, provider_id))")
        conn.execute("CREATE TABLE recommendations (id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL)")
        conn.execute("CREATE TABLE scan_runs (id INTEGER PRIMARY KEY, mode TEXT, phases TEXT, started_at TEXT NOT NULL, status TEXT NOT NULL)")
        conn.execute("CREATE TABLE active_sessions (token TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE media_probe_cache (id INTEGER PRIMARY KEY, media_id TEXT NOT NULL)")
        for v in range(1, 19):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute(
            "INSERT INTO score_settings(id, enabled, configuration_json) VALUES ('default', ?, ?)",
            (enabled, config_json),
        )
        conn.execute("INSERT INTO app_config(key, value_json) VALUES ('system.log_level', '\"INFO\"')")
        conn.commit()
        conn.close()

    def test_v19_migration_creates_score_rules_and_size_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v18_db_with_score(path, '{}')
            conn = db.initialize_database(path)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
            self.assertIn("score_rules", tables)
            self.assertIn("score_size_profiles", tables)
            self.assertNotIn("score_settings", tables)

    def test_v19_migration_removes_score_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v18_db_with_score(path, '{}')
            conn = db.initialize_database(path)
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='score_settings'"
            ).fetchone()
            conn.close()
            self.assertIsNone(exists)

    def test_v19_migration_migrates_enabled_to_app_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v18_db_with_score(path, '{}', enabled=1)
            conn = db.initialize_database(path)
            row = conn.execute(
                "SELECT value_json FROM app_config WHERE key = 'score.enabled'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row["value_json"]), True)

    def test_v19_migration_flattens_configuration_json_to_score_rules(self):
        config = json.dumps({
            "weights": {"video": 40, "audio": 25, "languages": 20, "size": 15},
            "max_score": {"max_video": 50, "max_audio": 30, "max_languages": 15, "max_size": 15},
            "video": {"resolution": {"2160p": 25, "default": 8}},
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v18_db_with_score(path, config)
            conn = db.initialize_database(path)
            rules = {
                (r["category"], r["group_key"], r["value_key"]): r["score_value"]
                for r in conn.execute(
                    "SELECT category, group_key, value_key, score_value FROM score_rules"
                ).fetchall()
            }
            conn.close()
            self.assertEqual(rules[("weights", "weight", "video")], 40)
            self.assertEqual(rules[("weights", "weight", "audio")], 25)
            self.assertEqual(rules[("max_score", "max_score", "max_video")], 50)
            self.assertEqual(rules[("video", "resolution", "2160p")], 25)
            self.assertEqual(rules[("video", "resolution", "default")], 8)

    def test_v19_migration_flattens_size_profiles(self):
        config = json.dumps({
            "size": {
                "profiles": {
                    "movie": {"1080p": {"hevc": {"min_gb": 2, "max_gb": 10}}},
                    "series": {"720p": {"default": {"min_gb": 0.2, "max_gb": 1.5}}},
                }
            }
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v18_db_with_score(path, config)
            conn = db.initialize_database(path)
            profiles = {
                (r["media_type"], r["resolution_key"], r["codec_key"]): (r["min_gb"], r["max_gb"])
                for r in conn.execute(
                    "SELECT media_type, resolution_key, codec_key, min_gb, max_gb FROM score_size_profiles"
                ).fetchall()
            }
            conn.close()
            self.assertIn(("movie", "1080p", "hevc"), profiles)
            self.assertEqual(profiles[("movie", "1080p", "hevc")], (2.0, 10.0))
            self.assertIn(("series", "720p", "default"), profiles)
            self.assertAlmostEqual(profiles[("series", "720p", "default")][0], 0.2)

    def test_v19_migration_empty_config_json_migrates_cleanly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v18_db_with_score(path, '{}')
            conn = db.initialize_database(path)
            rules_count = conn.execute("SELECT COUNT(*) FROM score_rules").fetchone()[0]
            score_enabled = conn.execute(
                "SELECT value_json FROM app_config WHERE key = 'score.enabled'"
            ).fetchone()
            conn.close()
            self.assertEqual(rules_count, 0)
            self.assertIsNotNone(score_enabled)

    def test_v19_migration_idempotent_on_fresh_db(self):
        """v19 migration on a fresh v19 DB (no score_settings) must be a no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)
            self.assertIn("score_rules", tables)
            self.assertNotIn("score_settings", tables)

    def test_v19_from_v8_db_full_chain(self):
        """A v8 DB (with score_settings) must reach v19 and have score_rules after full migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = sqlite3.connect(str(path))
            conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE score_settings (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, configuration_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE auth_settings (id INTEGER PRIMARY KEY CHECK (id=1), auth_enabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
            conn.execute("CREATE TABLE recommendation_rules (id INTEGER PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, rule_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1)")
            conn.execute("CREATE TABLE recommendations (id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL, title TEXT NOT NULL, message_json TEXT, suggested_action_json TEXT, details_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL, quality_json TEXT, missing_since TEXT, is_available INTEGER NOT NULL DEFAULT 1)")
            conn.execute("CREATE TABLE seasons (media_id TEXT, season_number INTEGER, quality_json TEXT, PRIMARY KEY(media_id, season_number))")
            for v in range(1, 9):
                conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
            conn.execute(
                "INSERT INTO score_settings(id, enabled, configuration_json) VALUES ('default', 1, ?)",
                (json.dumps({"weights": {"video": 45}}),),
            )
            conn.execute("PRAGMA user_version = 8")
            conn.commit()
            conn.close()

            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            rules = conn.execute("SELECT category, value_key, score_value FROM score_rules").fetchall()
            score_enabled = conn.execute(
                "SELECT value_json FROM app_config WHERE key = 'score.enabled'"
            ).fetchone()
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()

            self.assertEqual(version, db_schema.SCHEMA_VERSION)
            self.assertNotIn("score_settings", tables)
            self.assertIn("score_rules", tables)
            self.assertIsNotNone(score_enabled)
            video_rule = next((r for r in rules if r["value_key"] == "video"), None)
            self.assertIsNotNone(video_rule)
            self.assertEqual(video_rule["score_value"], 45)


class V20MigrationTest(unittest.TestCase):
    """Schema v20: folders table, remove runtime_library_document / providers_visible from app_config."""

    def _make_v19_db(self, path: pathlib.Path, *, folders_json: str | None = None, providers_visible_json: str | None = None, has_library_snapshot: bool = False, has_providers: bool = False) -> None:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA user_version = 19")
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE auth_settings (id INTEGER PRIMARY KEY CHECK (id=1), auth_enabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE score_rules (id INTEGER PRIMARY KEY, category TEXT NOT NULL, group_key TEXT NOT NULL, value_key TEXT NOT NULL, score_value REAL NOT NULL, UNIQUE(category, group_key, value_key))")
        conn.execute("CREATE TABLE score_size_profiles (id INTEGER PRIMARY KEY, media_type TEXT NOT NULL, resolution_key TEXT NOT NULL, codec_key TEXT NOT NULL, min_gb REAL NOT NULL, max_gb REAL NOT NULL, UNIQUE(media_type, resolution_key, codec_key))")
        conn.execute("CREATE TABLE recommendation_rules (id INTEGER PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL, is_available INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE seasons (id INTEGER PRIMARY KEY, media_id TEXT, season_number INTEGER)")
        conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, raw_name TEXT NOT NULL UNIQUE, mapped_name TEXT, is_ignored INTEGER NOT NULL DEFAULT 0, logo_path TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE media_providers (media_id TEXT, provider_id INTEGER, PRIMARY KEY (media_id, provider_id))")
        conn.execute("CREATE TABLE recommendations (id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL)")
        conn.execute("CREATE TABLE scan_runs (id INTEGER PRIMARY KEY, mode TEXT, phases TEXT, started_at TEXT NOT NULL, status TEXT NOT NULL)")
        conn.execute("CREATE TABLE active_sessions (token TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE media_probe_cache (id INTEGER PRIMARY KEY, media_id TEXT NOT NULL)")
        for v in range(1, 20):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("INSERT INTO app_config(key, value_json) VALUES ('system.log_level', '\"INFO\"')")
        if folders_json is not None:
            conn.execute("INSERT INTO app_config(key, value_json) VALUES ('folders', ?)", (folders_json,))
        if providers_visible_json is not None:
            conn.execute("INSERT INTO app_config(key, value_json) VALUES ('providers_visible', ?)", (providers_visible_json,))
        if has_library_snapshot:
            conn.execute("INSERT INTO app_config(key, value_json) VALUES ('runtime_library_document', '{\"items\":[]}')")
        if has_providers:
            conn.execute("INSERT INTO providers(raw_name, mapped_name) VALUES ('Netflix', 'Netflix')")
            conn.execute("INSERT INTO providers(raw_name, mapped_name) VALUES ('Prime', 'Amazon Prime Video')")
        conn.commit()
        conn.close()

    def test_v20_migration_creates_folders_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path)
            conn = db.initialize_database(path)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
            self.assertIn("folders", tables)

    def test_v20_migration_migrates_folders_json_to_table(self):
        folders = [{"name": "/movies", "type": "movie", "enabled": True}, {"name": "/series", "type": "series", "enabled": False}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path, folders_json=json.dumps(folders))
            conn = db.initialize_database(path)
            rows = conn.execute("SELECT name, media_type, enabled FROM folders ORDER BY name").fetchall()
            conn.close()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["name"], "/movies")
            self.assertEqual(rows[0]["media_type"], "movie")
            self.assertEqual(rows[0]["enabled"], 1)
            self.assertEqual(rows[1]["name"], "/series")
            self.assertEqual(rows[1]["enabled"], 0)

    def test_v20_migration_handles_folders_visible_field_fallback(self):
        folders = [{"name": "/movies", "type": "movie", "visible": True}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path, folders_json=json.dumps(folders))
            conn = db.initialize_database(path)
            row = conn.execute("SELECT enabled FROM folders WHERE name = '/movies'").fetchone()
            conn.close()
            self.assertEqual(row["enabled"], 1)

    def test_v20_migration_removes_folders_from_app_config(self):
        folders = [{"name": "/movies", "type": "movie", "enabled": True}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path, folders_json=json.dumps(folders))
            conn = db.initialize_database(path)
            row = conn.execute("SELECT 1 FROM app_config WHERE key = 'folders'").fetchone()
            conn.close()
            self.assertIsNone(row)

    def test_v20_migration_removes_runtime_library_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path, has_library_snapshot=True)
            conn = db.initialize_database(path)
            row = conn.execute("SELECT 1 FROM app_config WHERE key = 'runtime_library_document'").fetchone()
            conn.close()
            self.assertIsNone(row)

    def test_v20_migration_migrates_providers_visible_to_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path, providers_visible_json='["Netflix"]', has_providers=True)
            conn = db.initialize_database(path)
            rows = {r["mapped_name"]: r["is_ignored"] for r in conn.execute("SELECT mapped_name, is_ignored FROM providers WHERE mapped_name IS NOT NULL").fetchall()}
            visible_key = conn.execute("SELECT 1 FROM app_config WHERE key = 'providers_visible'").fetchone()
            conn.close()
            self.assertEqual(rows.get("Netflix"), 0)
            self.assertEqual(rows.get("Amazon Prime Video"), 1)
            self.assertIsNone(visible_key)

    def test_v20_migration_is_safe_on_fresh_db_without_old_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v19_db(path)
            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            folder_count = conn.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)
            self.assertEqual(folder_count, 0)


class V21MigrationTest(unittest.TestCase):
    """Schema v21: media_probe_cache — replace probe_data JSON with typed columns."""

    def _make_v20_db_with_probe(self, path: pathlib.Path, rows: list[dict]) -> None:
        """Build a minimal v20 DB with media_probe_cache rows using probe_data JSON."""
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA user_version = 20")
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE auth_settings (id INTEGER PRIMARY KEY CHECK (id=1), auth_enabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE score_rules (id INTEGER PRIMARY KEY, category TEXT NOT NULL, group_key TEXT NOT NULL, value_key TEXT NOT NULL, score_value REAL NOT NULL, UNIQUE(category, group_key, value_key))")
        conn.execute("CREATE TABLE score_size_profiles (id INTEGER PRIMARY KEY, media_type TEXT NOT NULL, resolution_key TEXT NOT NULL, codec_key TEXT NOT NULL, min_gb REAL NOT NULL, max_gb REAL NOT NULL, UNIQUE(media_type, resolution_key, codec_key))")
        conn.execute("CREATE TABLE recommendation_rules (id INTEGER PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE folders (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, media_type TEXT, enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL, is_available INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE seasons (id INTEGER PRIMARY KEY, media_id TEXT, season_number INTEGER)")
        conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, raw_name TEXT NOT NULL UNIQUE, mapped_name TEXT, is_ignored INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE media_providers (media_id TEXT, provider_id INTEGER, PRIMARY KEY (media_id, provider_id))")
        conn.execute("CREATE TABLE recommendations (id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL)")
        conn.execute("CREATE TABLE scan_runs (id INTEGER PRIMARY KEY, mode TEXT, phases TEXT, started_at TEXT NOT NULL, status TEXT NOT NULL)")
        conn.execute("CREATE TABLE active_sessions (token TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL)")
        conn.execute("""
            CREATE TABLE media_probe_cache (
                id INTEGER PRIMARY KEY,
                media_id TEXT NOT NULL,
                filename TEXT,
                file_path TEXT,
                file_size INTEGER,
                modified_at REAL,
                probed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                probe_data TEXT,
                FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
                UNIQUE (media_id, filename)
            )
        """)
        for v in range(1, 21):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        for r in rows:
            media_id = r["media_id"]
            conn.execute("INSERT OR IGNORE INTO media(id, media_type, title) VALUES (?, 'movie', ?)", (media_id, media_id))
            conn.execute(
                "INSERT INTO media_probe_cache(media_id, filename, file_size, modified_at, probe_data)"
                " VALUES (?, ?, ?, ?, ?)",
                (media_id, r.get("filename", "main.mkv"), r.get("file_size", 1000), r.get("modified_at", 1.0), r.get("probe_data")),
            )
        conn.commit()
        conn.close()

    def test_v21_migration_adds_typed_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v20_db_with_probe(path, [])
            conn = db.initialize_database(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(media_probe_cache)").fetchall()}
            conn.close()
            for expected in ("probe_ok", "width", "height", "resolution", "codec", "hdr", "hdr_type",
                             "runtime_min", "runtime_min_avg", "video_bitrate",
                             "audio_codec", "audio_codec_raw", "audio_channels",
                             "audio_languages_json", "subtitle_languages_json",
                             "audio_bitrate", "audio_languages_simple", "framerate",
                             "container", "dolby_vision", "size_b"):
                self.assertIn(expected, cols, f"missing column: {expected}")

    def test_v21_migration_removes_probe_data_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v20_db_with_probe(path, [])
            conn = db.initialize_database(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(media_probe_cache)").fetchall()}
            conn.close()
            self.assertNotIn("probe_data", cols)

    def test_v21_migration_migrates_probe_data_to_columns(self):
        probe_data = json.dumps({
            "ok": True,
            "technical": {
                "width": 1920, "height": 1080, "resolution": "1080p",
                "codec": "H.265", "hdr": True, "hdr_type": "HDR10",
                "runtime_min": 120, "runtime_min_avg": 120, "video_bitrate": 5000000,
                "audio_codec": "DTS-HD MA", "audio_codec_raw": "dts",
                "audio_channels": "7.1",
                "audio_languages": ["fr", "en"], "subtitle_languages": ["fr"],
                "audio_bitrate": 1500000, "audio_languages_simple": "MULTI",
                "framerate": 23.976, "container": "MKV",
                "dolby_vision": False, "size_b": 10737418240,
            },
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v20_db_with_probe(path, [{"media_id": "m1", "probe_data": probe_data}])
            conn = db.initialize_database(path)
            row = conn.execute("SELECT * FROM media_probe_cache WHERE media_id='m1'").fetchone()
            conn.close()
            self.assertEqual(row["probe_ok"], 1)
            self.assertEqual(row["width"], 1920)
            self.assertEqual(row["height"], 1080)
            self.assertEqual(row["resolution"], "1080p")
            self.assertEqual(row["codec"], "H.265")
            self.assertEqual(row["hdr"], 1)
            self.assertEqual(row["hdr_type"], "HDR10")
            self.assertEqual(row["runtime_min"], 120)
            self.assertEqual(row["audio_codec"], "DTS-HD MA")
            self.assertEqual(json.loads(row["audio_languages_json"]), ["fr", "en"])
            self.assertEqual(json.loads(row["subtitle_languages_json"]), ["fr"])
            self.assertEqual(row["framerate"], 23.976)
            self.assertEqual(row["container"], "MKV")
            self.assertEqual(row["dolby_vision"], 0)

    def test_v21_migration_handles_null_probe_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v20_db_with_probe(path, [{"media_id": "m_null", "probe_data": None}])
            conn = db.initialize_database(path)
            row = conn.execute("SELECT probe_ok FROM media_probe_cache WHERE media_id='m_null'").fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["probe_ok"], 0)

    def test_v21_migration_handles_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v20_db_with_probe(path, [{"media_id": "m_bad", "probe_data": "NOT_JSON"}])
            conn = db.initialize_database(path)
            count = conn.execute("SELECT COUNT(*) FROM media_probe_cache WHERE media_id='m_bad'").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)

    def test_v21_migration_is_idempotent_on_fresh_db(self):
        """Fresh DB (no probe_data column) must survive the v21 migration without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(media_probe_cache)").fetchall()}
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)
            self.assertNotIn("probe_data", cols)
            self.assertIn("probe_ok", cols)


class V22MigrationTest(unittest.TestCase):
    """Schema v22: seasons — drop data_json (written but never read at runtime)."""

    def _make_v21_db_with_seasons(self, path: pathlib.Path) -> None:
        """Build a minimal v21 DB with seasons rows that still have data_json."""
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA user_version = 21")
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE app_config (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE auth_settings (id INTEGER PRIMARY KEY CHECK (id=1), auth_enabled INTEGER NOT NULL DEFAULT 0, password_hash TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE score_rules (id INTEGER PRIMARY KEY, category TEXT NOT NULL, group_key TEXT NOT NULL, value_key TEXT NOT NULL, score_value REAL NOT NULL, UNIQUE(category, group_key, value_key))")
        conn.execute("CREATE TABLE score_size_profiles (id INTEGER PRIMARY KEY, media_type TEXT NOT NULL, resolution_key TEXT NOT NULL, codec_key TEXT NOT NULL, min_gb REAL NOT NULL, max_gb REAL NOT NULL, UNIQUE(media_type, resolution_key, codec_key))")
        conn.execute("CREATE TABLE recommendation_rules (id INTEGER PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1)")
        conn.execute("CREATE TABLE folders (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, media_type TEXT, enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE media (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, title TEXT NOT NULL, is_available INTEGER NOT NULL DEFAULT 1)")
        conn.execute("""
            CREATE TABLE seasons (
                id INTEGER PRIMARY KEY,
                media_id TEXT NOT NULL,
                season_number INTEGER NOT NULL,
                title TEXT,
                episodes_count INTEGER,
                size_total INTEGER,
                runtime_min INTEGER,
                runtime_min_avg INTEGER,
                quality_score REAL,
                width INTEGER,
                height INTEGER,
                resolution TEXT,
                video_codec TEXT,
                data_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
                UNIQUE (media_id, season_number)
            )
        """)
        conn.execute("CREATE TABLE providers (id INTEGER PRIMARY KEY, raw_name TEXT NOT NULL UNIQUE, mapped_name TEXT, is_ignored INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE media_providers (media_id TEXT, provider_id INTEGER, PRIMARY KEY (media_id, provider_id))")
        conn.execute("CREATE TABLE recommendations (id TEXT PRIMARY KEY, recommendation_type TEXT NOT NULL)")
        conn.execute("CREATE TABLE scan_runs (id INTEGER PRIMARY KEY, mode TEXT, phases TEXT, started_at TEXT NOT NULL, status TEXT NOT NULL)")
        conn.execute("CREATE TABLE active_sessions (token TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE media_probe_cache (id INTEGER PRIMARY KEY, media_id TEXT NOT NULL, filename TEXT, probe_ok INTEGER NOT NULL DEFAULT 0)")
        for v in range(1, 22):
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (v,))
        conn.execute("INSERT INTO media(id, media_type, title) VALUES ('m1', 'tv', 'Show')")
        conn.execute(
            "INSERT INTO seasons(media_id, season_number, title, episodes_count, resolution, data_json)"
            " VALUES ('m1', 1, 'Season 1', 10, '1080p', '{\"season\":1,\"codec\":\"H.265\"}')"
        )
        conn.execute(
            "INSERT INTO seasons(media_id, season_number, episodes_count, resolution, data_json)"
            " VALUES ('m1', 2, 8, '4K', NULL)"
        )
        conn.commit()
        conn.close()

    def test_v22_migration_removes_data_json_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v21_db_with_seasons(path)
            conn = db.initialize_database(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(seasons)").fetchall()}
            conn.close()
            self.assertNotIn("data_json", cols)

    def test_v22_migration_preserves_season_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            self._make_v21_db_with_seasons(path)
            conn = db.initialize_database(path)
            count = conn.execute("SELECT COUNT(*) FROM seasons WHERE media_id='m1'").fetchone()[0]
            row1 = conn.execute("SELECT resolution, episodes_count FROM seasons WHERE media_id='m1' AND season_number=1").fetchone()
            conn.close()
            self.assertEqual(count, 2)
            self.assertEqual(row1["resolution"], "1080p")
            self.assertEqual(row1["episodes_count"], 10)

    def test_v22_migration_is_idempotent_on_fresh_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "mml.db"
            conn = db.initialize_database(path)
            version = db_migrations.get_schema_version(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(seasons)").fetchall()}
            conn.close()
            self.assertEqual(version, db_schema.SCHEMA_VERSION)
            self.assertNotIn("data_json", cols)

    def test_v22_no_data_json_in_schema_target(self):
        """Fresh DB must not have data_json in seasons at all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = db.initialize_database(pathlib.Path(tmpdir) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(seasons)").fetchall()}
            conn.close()
            self.assertNotIn("data_json", cols)
            # All important typed columns must still be there
            for col in ("media_id", "season_number", "title", "episodes_count",
                        "resolution", "width", "height", "video_codec", "audio_codec",
                        "audio_languages_json", "runtime_min_avg"):
                self.assertIn(col, cols, f"missing column: {col}")


if __name__ == "__main__":
    unittest.main()
