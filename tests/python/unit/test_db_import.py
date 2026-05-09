import json
import pathlib
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import db_export  # noqa: E402
import db_import  # noqa: E402


class DatabaseImportTest(unittest.TestCase):
    def make_paths(self, root: pathlib.Path):
        conf = root / "conf"
        data = root / "data"
        defaults = root / "defaults" / "conf"
        conf.mkdir()
        data.mkdir()
        defaults.mkdir(parents=True)
        return types.SimpleNamespace(
            PROVIDERS_LOGO_JSON=conf / "providers_logo.json",
            PROVIDERS_MAPPING_JSON=conf / "providers_mapping.json",
            RECOMMENDATIONS_RULES_JSON=conf / "recommendations_rules.json",
            CONFIG_JSON=conf / "config.json",
            MEDIA_PROBE_CACHE_JSON=data / "media_probe_cache.json",
            LIBRARY_PROBE_JSON=data / "library_probe.json",
            INVENTORY_JSON=data / "library_inventory.json",
            RECOMMENDATIONS_JSON=data / "recommendations.json",
            LIBRARY_JSON=data / "library.json",
            SECRETS_FILE=conf / ".secrets",
            DEFAULT_CONFIG_JSON=defaults / "config.json",
            DEFAULT_PROVIDERS_MAPPING_JSON=defaults / "providers_mapping.json",
            DEFAULT_PROVIDERS_LOGO_JSON=defaults / "providers_logo.json",
            DEFAULT_RECOMMENDATIONS_RULES_JSON=defaults / "recommendations_rules.json",
        )

    def write_json(self, path: pathlib.Path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_import_providers_logo_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "providers_logo.json"
            self.write_json(path, {"Netflix": "netflix.webp"})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_providers_logo(conn, path)

            self.assertEqual(inserted, 1)
            self.assertEqual(db_export.export_providers_logo(conn), {"Netflix": "netflix.webp"})
            conn.close()

    def test_import_providers_mapping_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "providers_mapping.json"
            self.write_json(path, {"Amazon Prime Video": "Prime Video", "Unknown": None})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_providers_mapping(conn, path)
            rows = conn.execute(
                "SELECT raw_name, mapped_name, is_ignored FROM provider_mappings ORDER BY raw_name"
            ).fetchall()
            conn.close()

            self.assertEqual(inserted, 2)
            self.assertEqual(
                [(row["raw_name"], row["mapped_name"], row["is_ignored"]) for row in rows],
                [("Amazon Prime Video", "Prime Video", 0), ("Unknown", None, 1)],
            )

    def test_import_recommendations_rules_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "recommendations_rules.json"
            rule = {"id": "low_score", "enabled": True, "conditions": []}
            self.write_json(path, {"version": 1, "rules": [rule]})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_recommendation_rules(conn, path)

            self.assertEqual(inserted, 1)
            self.assertEqual(db_export.export_recommendation_rules(conn)["rules"], [rule])
            conn.close()

    def test_import_config_json_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            self.write_json(
                path,
                {
                    "folders": [{"name": "Films", "type": "movie"}],
                    "seerr": {"enabled": True, "url": "https://example.test", "apikey": "secret"},
                    "score": {"enabled": True},
                    "score_configuration": {"weights": {"video": 40}},
                    "media_probe": {"enabled": True, "workers": 2},
                },
            )
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_config(conn, path)
            exported = db_export.export_config(conn)
            score = conn.execute("SELECT enabled, configuration_json FROM score_settings WHERE id = 'default'").fetchone()
            probe = conn.execute("SELECT value_json FROM scan_settings WHERE id = 'media_probe'").fetchone()
            conn.close()

            self.assertGreaterEqual(inserted, 4)
            self.assertIn("folders", exported)
            self.assertEqual(exported["seerr"], {"enabled": True, "url": "https://example.test"})
            self.assertEqual(score["enabled"], 1)
            self.assertEqual(json.loads(probe["value_json"])["workers"], 2)

    def test_import_media_probe_cache_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "media_probe_cache.json"
            self.write_json(
                path,
                {
                    "version": 1,
                    "files": {
                        "/library/movie.mkv": {
                            "path": "/library/movie.mkv",
                            "size_b": 123,
                            "mtime": 42.5,
                            "probe": {"ok": True, "technical": {"resolution": "1080p"}},
                        }
                    },
                },
            )
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_media_probe_cache(conn, path)
            exported = db_export.export_media_probe_cache(conn)
            conn.close()

            self.assertEqual(inserted, 1)
            self.assertEqual(exported["files"]["/library/movie.mkv"]["size_b"], 123)
            self.assertTrue(exported["files"]["/library/movie.mkv"]["probe"]["ok"])

    def test_import_library_inventory_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "library_inventory.json"
            item = {
                "id": "movie:Films:Inception (2010)",
                "media_type": "movie",
                "category": "Films",
                "title": "Inception",
                "root_folder_path": "/library/Films/Inception (2010)",
                "status": "present",
            }
            self.write_json(path, {"version": 1, "items": [item]})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_library_inventory(conn, path)
            rows = conn.execute("SELECT id, status, data_json FROM inventory_items").fetchall()
            conn.close()

            self.assertEqual(inserted, 1)
            self.assertEqual(rows[0]["id"], item["id"])
            self.assertEqual(rows[0]["status"], "present")
            self.assertEqual(json.loads(rows[0]["data_json"])["title"], "Inception")

    def test_import_recommendations_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "recommendations.json"
            rec = {
                "id": "rec:movie:Films:Inception (2010):low_score",
                "media_ref": {"id": "movie:Films:Inception (2010)", "type": "movie"},
                "display": {"title": "Inception"},
                "recommendation_type": "quality",
                "priority": "medium",
                "rule_id": "low_score",
                "message": {"en": "Low score"},
                "suggested_action": {"en": "Replace"},
            }
            self.write_json(path, {"version": 1, "items": [rec]})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_recommendations(conn, path)
            rows = conn.execute("SELECT id, media_id, priority, details_json FROM recommendations").fetchall()
            conn.close()

            self.assertEqual(inserted, 1)
            self.assertEqual(rows[0]["id"], rec["id"])
            self.assertIsNone(rows[0]["media_id"])
            self.assertEqual(rows[0]["priority"], "medium")
            self.assertEqual(json.loads(rows[0]["details_json"])["media_ref"]["id"], "movie:Films:Inception (2010)")
            self.assertEqual(json.loads(rows[0]["details_json"])["rule_id"], "low_score")

    def test_import_library_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "library.json"
            item = {
                "id": "movie:Films:Inception (2010)",
                "path": "Films/Inception (2010)",
                "title": "Inception",
                "raw": "Inception (2010)",
                "category": "Films",
                "type": "movie",
                "year": 2010,
                "size_b": 123,
                "quality": {"score": 87},
                "providers": ["Netflix"],
            }
            self.write_json(path, {"version": 1, "items": [item]})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            inserted = db_import.import_library(conn, path)
            rows = conn.execute("SELECT id, media_type, quality_score, data_json FROM media").fetchall()
            conn.close()

            self.assertEqual(inserted, 1)
            self.assertEqual(rows[0]["id"], item["id"])
            self.assertEqual(rows[0]["media_type"], "movie")
            self.assertEqual(rows[0]["quality_score"], 87)
            self.assertEqual(json.loads(rows[0]["data_json"])["providers"], ["Netflix"])

    def test_import_is_idempotent_when_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "providers_logo.json"
            self.write_json(path, {"Netflix": "netflix.webp"})
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")

            first = db_import.import_providers_logo(conn, path)
            second = db_import.import_providers_logo(conn, path)
            count = conn.execute("SELECT COUNT(*) FROM provider_logos").fetchone()[0]
            conn.close()

            self.assertEqual(first, 1)
            self.assertEqual(second, 0)
            self.assertEqual(count, 1)

    def test_missing_json_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")
            report = db_import.ImportReport()

            inserted = db_import.import_providers_logo(conn, pathlib.Path(tmp) / "missing.json", report)
            conn.close()

            self.assertEqual(inserted, 0)
            self.assertEqual(report.skipped_missing, ["providers_logo"])

    def test_invalid_json_is_reported_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "providers_logo.json"
            path.write_text("{ invalid", encoding="utf-8")
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")
            report = db_import.ImportReport()

            inserted = db_import.import_providers_logo(conn, path, report)
            conn.close()

            self.assertEqual(inserted, 0)
            self.assertEqual(report.invalid_json, ["providers_logo"])

    def test_runtime_import_handles_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(paths.PROVIDERS_LOGO_JSON, {"Netflix": "netflix.webp"})
            self.write_json(paths.PROVIDERS_MAPPING_JSON, {"Amazon Prime Video": "Prime Video"})
            self.write_json(paths.RECOMMENDATIONS_RULES_JSON, {"version": 1, "rules": [{"id": "low"}]})
            self.write_json(paths.CONFIG_JSON, {"folders": [], "score": {"enabled": False}})
            self.write_json(paths.MEDIA_PROBE_CACHE_JSON, {"version": 1, "files": {}})
            self.write_json(paths.INVENTORY_JSON, {"version": 1, "items": []})
            self.write_json(paths.RECOMMENDATIONS_JSON, {"version": 1, "items": []})
            self.write_json(paths.LIBRARY_JSON, {"version": 1, "items": []})

            report = db_import.import_runtime_json_files(root / "data" / "mymedialibrary.db", paths=paths)

            self.assertEqual(report.invalid_json, [])
            self.assertEqual(report.skipped_missing, [])
            self.assertEqual(report.imported["providers_logo"], 1)

    def test_startup_migration_removes_validated_json_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(paths.PROVIDERS_LOGO_JSON, {"Netflix": "netflix.webp"})
            self.write_json(paths.PROVIDERS_MAPPING_JSON, {"Prime": "Prime Video"})
            self.write_json(paths.RECOMMENDATIONS_RULES_JSON, {"version": 1, "rules": [{"id": "low"}]})
            self.write_json(paths.CONFIG_JSON, {"folders": [], "score": {"enabled": False}})
            self.write_json(
                paths.MEDIA_PROBE_CACHE_JSON,
                {"version": 1, "files": {"/movie.mkv": {"size_b": 1, "mtime": 2.0, "probe": {"ok": True}}}},
            )
            self.write_json(paths.INVENTORY_JSON, {"version": 1, "items": [{"id": "inv-1", "status": "present"}]})
            self.write_json(paths.LIBRARY_JSON, {"version": 1, "items": [{"id": "m-1", "type": "movie", "title": "M", "path": "/m"}]})
            self.write_json(paths.RECOMMENDATIONS_JSON, {"version": 1, "items": [{"id": "r-1", "title": "R"}]})
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")

            results = db_import.migrate_runtime_json_files_at_startup(conn, paths=paths)

            self.assertTrue(all(result.status == "ok" for result in results))
            self.assertFalse(paths.LIBRARY_JSON.exists())
            self.assertFalse(paths.RECOMMENDATIONS_JSON.exists())
            self.assertFalse(paths.INVENTORY_JSON.exists())
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM media").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0], 1)
            conn.close()

    def test_startup_migration_removes_config_when_only_sensitive_keys_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(
                paths.CONFIG_JSON,
                {
                    "folders": [],
                    "system": {"log_level": "INFO"},
                    "seerr": {"api_key": "secret"},
                    "score": {"enabled": False},
                },
            )
            paths.SECRETS_FILE.write_text('{"seerr_apikey":"secret"}', encoding="utf-8")
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")

            with self.assertLogs("db-import", level="INFO") as logs:
                results = db_import.migrate_runtime_json_files_at_startup(
                    conn,
                    paths=paths,
                    logger=__import__("logging").getLogger("db-import"),
                )

            config_result = next(result for result in results if result.name == "config")
            self.assertEqual(config_result.status, "ok")
            self.assertEqual(config_result.source_total_count, 5)
            self.assertEqual(config_result.source_count, config_result.db_count)
            self.assertFalse(paths.CONFIG_JSON.exists())
            self.assertTrue(paths.SECRETS_FILE.exists())
            self.assertIn("json=5 importable=4 db=4", "\n".join(logs.output))
            conn.close()

    def test_startup_migration_removes_obsolete_library_probe_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            paths.LIBRARY_PROBE_JSON.write_text('{"items":[]}', encoding="utf-8")
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")

            db_import.migrate_runtime_json_files_at_startup(conn, paths=paths)

            self.assertFalse(paths.LIBRARY_PROBE_JSON.exists())
            conn.close()

    def test_startup_migration_keeps_json_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(paths.PROVIDERS_LOGO_JSON, {"Netflix": "netflix.webp"})
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")
            conn.execute(
                "INSERT INTO provider_logos(provider_name, logo_path) VALUES (?, ?)",
                ("Disney+", "disney.webp"),
            )
            conn.commit()

            results = db_import.migrate_runtime_json_files_at_startup(conn, paths=paths)

            logo_result = next(result for result in results if result.name == "providers_logo")
            self.assertEqual(logo_result.status, "warning")
            self.assertTrue(paths.PROVIDERS_LOGO_JSON.exists())
            self.assertEqual(logo_result.source_count, 1)
            self.assertEqual(logo_result.db_count, 2)
            conn.close()

    def test_startup_migration_keeps_invalid_json_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            paths.PROVIDERS_MAPPING_JSON.write_text("{ invalid", encoding="utf-8")
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")

            results = db_import.migrate_runtime_json_files_at_startup(conn, paths=paths)

            mapping = next(result for result in results if result.name == "providers_mapping")
            logo = next(result for result in results if result.name == "providers_logo")
            self.assertEqual(mapping.status, "warning")
            self.assertEqual(mapping.warning, "invalid_json")
            self.assertTrue(paths.PROVIDERS_MAPPING_JSON.exists())
            self.assertEqual(logo.status, "skipped")
            conn.close()

    def test_startup_migration_is_idempotent_after_cleanup_and_never_removes_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(paths.PROVIDERS_LOGO_JSON, {"Netflix": "netflix.webp"})
            paths.SECRETS_FILE.write_text('{"seerr_apikey":"secret"}', encoding="utf-8")
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")

            first = db_import.migrate_runtime_json_files_at_startup(conn, paths=paths)
            second = db_import.migrate_runtime_json_files_at_startup(conn, paths=paths)

            self.assertEqual(next(result for result in first if result.name == "providers_logo").status, "ok")
            self.assertEqual(next(result for result in second if result.name == "providers_logo").status, "skipped")
            self.assertFalse(paths.PROVIDERS_LOGO_JSON.exists())
            self.assertTrue(paths.SECRETS_FILE.exists())
            self.assertEqual(json.loads(paths.SECRETS_FILE.read_text(encoding="utf-8"))["seerr_apikey"], "secret")
            conn.close()

    def test_seed_bundled_defaults_imports_without_writing_conf_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(paths.DEFAULT_CONFIG_JSON, {"folders": [], "score": {"enabled": False}})
            self.write_json(paths.DEFAULT_PROVIDERS_MAPPING_JSON, {"Netflix": "Netflix"})
            self.write_json(paths.DEFAULT_PROVIDERS_LOGO_JSON, {"Netflix": "netflix.webp"})
            self.write_json(paths.DEFAULT_RECOMMENDATIONS_RULES_JSON, {"version": 1, "rules": [{"id": "low"}]})
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")

            rows = db_import.seed_bundled_defaults(conn, paths=paths)

            self.assertGreaterEqual(rows["config"], 1)
            self.assertEqual(rows["provider_mappings"], 1)
            self.assertEqual(rows["provider_logos"], 1)
            self.assertEqual(rows["recommendation_rules"], 1)
            self.assertFalse(paths.CONFIG_JSON.exists())
            self.assertFalse(paths.PROVIDERS_MAPPING_JSON.exists())
            self.assertFalse(paths.PROVIDERS_LOGO_JSON.exists())
            self.assertFalse(paths.RECOMMENDATIONS_RULES_JSON.exists())
            conn.close()

    def test_seed_bundled_defaults_is_idempotent_and_preserves_user_customizations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = self.make_paths(root)
            self.write_json(paths.DEFAULT_PROVIDERS_MAPPING_JSON, {"Netflix": "Netflix", "Disney+": "Disney+"})
            conn = db.initialize_database(root / "data" / "mymedialibrary.db")
            conn.execute(
                "INSERT INTO provider_mappings(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                ("Netflix", "NFX-custom", 0),
            )
            conn.commit()

            first = db_import.seed_bundled_defaults(conn, paths=paths)
            second = db_import.seed_bundled_defaults(conn, paths=paths)
            rows = conn.execute(
                "SELECT raw_name, mapped_name FROM provider_mappings ORDER BY raw_name"
            ).fetchall()

            self.assertEqual(first["provider_mappings"], 1)
            self.assertEqual(second["provider_mappings"], 0)
            self.assertEqual(
                [(row["raw_name"], row["mapped_name"]) for row in rows],
                [("Disney+", "Disney+"), ("Netflix", "NFX-custom")],
            )
            conn.close()

    def test_upsert_library_item_prepares_scanner_db_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.initialize_database(pathlib.Path(tmp) / "db.sqlite")
            item = {
                "id": "movie:Films:Inception (2010)",
                "type": "movie",
                "title": "Inception",
                "path": "Films/Inception (2010)",
                "quality": {"score": 50},
            }

            first = db_import.upsert_library_item(conn, item)
            item["quality"] = {"score": 75}
            second = db_import.upsert_library_item(conn, item)
            score = conn.execute("SELECT quality_score FROM media WHERE id = ?", (item["id"],)).fetchone()[0]
            conn.close()

            self.assertEqual(first, 1)
            self.assertEqual(second, 1)
            self.assertEqual(score, 75)


if __name__ == "__main__":
    unittest.main()
