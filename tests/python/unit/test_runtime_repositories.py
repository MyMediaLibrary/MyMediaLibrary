import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import db  # noqa: E402
import scanner  # noqa: E402
from repositories import (  # noqa: E402
    config_repository,
    media_repository,
    providers_repository,
    recommendations_repository,
)


class RuntimeRepositoriesTest(unittest.TestCase):
    def test_config_read_sqlite_before_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "config.json"
            json_path.parent.mkdir()
            json_path.write_text('{"system":{"log_level":"JSON"},"folders":[]}', encoding="utf-8")

            conn = db.initialize_database(db_path)
            try:
                conn.execute(
                    "INSERT INTO app_config(key, value_json) VALUES (?, ?)",
                    ("system", '{"log_level":"DB","scan_cron":"0 3 * * *"}'),
                )
                conn.execute(
                    "INSERT INTO score_settings(id, enabled, configuration_json) VALUES (?, ?, ?)",
                    ("default", 1, '{"weights":{"video":40}}'),
                )
                conn.execute(
                    "INSERT INTO app_config(key, value_json) VALUES (?, ?)",
                    ("media_probe.enabled", "true"),
                )
                conn.execute(
                    "INSERT INTO app_config(key, value_json) VALUES (?, ?)",
                    ("media_probe.workers", "2"),
                )
                conn.commit()
            finally:
                conn.close()

            cfg = config_repository.load_config(json_path, db_path)

            self.assertEqual(cfg["system"]["log_level"], "DB")
            self.assertEqual(cfg["score"], {"enabled": True})
            self.assertEqual(cfg["score_configuration"], {"weights": {"video": 40}})
            self.assertEqual(cfg["media_probe"], {"enabled": True, "workers": 2})

    def test_config_imports_noncanonical_json_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "config.json"
            json_path.parent.mkdir()
            payload = {
                "system": {"log_level": "DEBUG", "scan_cron": "*/5 * * * *"},
                "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
                "score": {"enabled": True},
                "score_configuration": {"weights": {"video": 40}},
                "media_probe": {"enabled": True, "workers": 3},
            }
            json_path.write_text(json.dumps(payload), encoding="utf-8")

            cfg = config_repository.load_config(json_path, db_path)
            cfg_again = config_repository.load_config(json_path, db_path)

            self.assertEqual(cfg["system"]["log_level"], "DEBUG")
            self.assertEqual(cfg_again, cfg)
            conn = db.initialize_database(db_path)
            try:
                app_count = conn.execute("SELECT COUNT(*) FROM app_config").fetchone()[0]
                score_count = conn.execute("SELECT COUNT(*) FROM score_settings").fetchone()[0]
                probe_count = conn.execute(
                    "SELECT COUNT(*) FROM app_config WHERE key LIKE 'media_probe.%'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertGreater(app_count, 0)
            self.assertEqual(score_count, 1)
            self.assertGreater(probe_count, 0)

    def test_config_requires_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            json_path = root / "conf" / "config.json"
            json_path.parent.mkdir()
            json_path.write_text('{"system":{"log_level":"INFO"},"folders":[]}', encoding="utf-8")

            with self.assertRaises(Exception):
                config_repository.load_config(json_path, blocked_parent / "mml.db")

    def test_config_save_updates_sqlite_without_json_or_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "config.json"
            payload = {
                "system": {"log_level": "DEBUG", "scan_cron": "0 3 * * *"},
                "seerr": {"url": "https://seerr.test", "apikey": "clear-secret"},
                "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
                "score": {"enabled": True},
                "score_configuration": {"weights": {"video": 40}},
                "media_probe": {"enabled": True, "workers": 2},
            }

            config_repository.save_config(payload, json_path, db_path)

            self.assertFalse(json_path.exists())
            cfg = config_repository.load_config(json_path, db_path)
            self.assertNotIn("apikey", cfg["seerr"])
            self.assertEqual(cfg["score"], {"enabled": True})
            self.assertEqual(cfg["media_probe"], {"enabled": True, "workers": 2})

    def test_save_config_full_writes_only_flat_keys_no_blobs(self):
        """save_config must write group.*  flat keys and never recreate group-name blobs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "config.json"
            payload = {
                "system": {"scan_cron": "0 4 * * *", "log_level": "DEBUG",
                           "needs_onboarding": False, "inventory_enabled": False},
                "seerr": {"enabled": True, "url": "http://seerr.local"},
                "ui": {"theme": "light", "default_view": "list", "default_sort": "title-asc",
                       "synopsis_on_hover": True, "accent_color": "#000"},
                "recommendations": {"enabled": True},
                "media_probe": {"enabled": True, "mode": "compare", "workers": 2, "cache_enabled": False},
                "folders": ["/movies"],
                "enable_movies": True,
            }

            config_repository.save_config(payload, json_path, db_path)

            conn = db.initialize_database(db_path)
            try:
                all_keys = {r["key"] for r in conn.execute("SELECT key FROM app_config").fetchall()}
            finally:
                conn.close()
            for group in ("system", "seerr", "ui", "recommendations", "media_probe"):
                self.assertNotIn(group, all_keys, f"blob key '{group}' must not exist after save_config")
            for expected in ("system.scan_cron", "system.log_level", "seerr.enabled",
                             "ui.theme", "recommendations.enabled", "media_probe.enabled"):
                self.assertIn(expected, all_keys, f"flat key '{expected}' missing after save_config")

    def test_save_config_partial_preserves_other_groups(self):
        """save_config with a partial payload must not wipe flat keys of absent groups."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "config.json"
            # Seed a full config first
            config_repository.save_config({
                "folders": [], "enable_movies": True,
                "system": {"scan_cron": "0 3 * * *", "log_level": "INFO",
                           "needs_onboarding": True, "inventory_enabled": False},
                "seerr": {"enabled": False, "url": ""},
                "ui": {"theme": "dark", "default_view": "grid", "default_sort": "title-asc",
                       "synopsis_on_hover": False, "accent_color": "#7c6aff"},
                "recommendations": {"enabled": False},
                "media_probe": {"enabled": False, "mode": "compare", "workers": 4, "cache_enabled": True},
            }, json_path, db_path)

            # Partial save: only scalar keys — no groups
            config_repository.save_config({"folders": ["/movies"], "enable_movies": False},
                                          json_path, db_path)

            cfg = config_repository.load_config(json_path, db_path)
            self.assertIsNotNone(cfg.get("system"), "system group must survive partial save")
            self.assertIsNotNone(cfg.get("seerr"), "seerr group must survive partial save")
            self.assertIsNotNone(cfg.get("ui"), "ui group must survive partial save")
            self.assertIsNotNone(cfg.get("recommendations"), "recommendations group must survive partial save")
            self.assertIsNotNone(cfg.get("media_probe"), "media_probe group must survive partial save")

    def test_config_sanitizes_sensitive_keys_recursively(self):
        payload = {
            "api_key": "top",
            "nested": {
                "access_token": "token",
                "refresh_token": "refresh",
                "safe": "ok",
                "items": [{"password": "pw", "name": "kept"}],
            },
        }

        sanitized = config_repository.sanitize_config(payload)

        self.assertEqual(sanitized, {"nested": {"safe": "ok", "items": [{"name": "kept"}]}})

    def test_auth_settings_store_hash_and_disabled_clears_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "data" / "mml.db"

            config_repository.save_auth_settings(
                auth_enabled=True,
                password_hash="pbkdf2_sha256$260000$salt$digest",
                db_path=db_path,
            )
            enabled = config_repository.load_auth_settings(db_path)
            config_repository.save_auth_settings(auth_enabled=False, password_hash=None, db_path=db_path)
            disabled = config_repository.load_auth_settings(db_path)

            self.assertEqual(enabled["auth_enabled"], True)
            self.assertEqual(enabled["password_hash"], "pbkdf2_sha256$260000$salt$digest")
            self.assertEqual(disabled["auth_enabled"], False)
            self.assertIsNone(disabled["password_hash"])

    def test_media_library_loads_sqlite_before_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library.json"
            json_path.parent.mkdir()
            json_path.write_text(
                json.dumps({"items": [{"id": "json", "path": "Films/Json", "title": "JSON", "type": "movie"}]}),
                encoding="utf-8",
            )
            db_doc = {
                "scanned_at": "2026-05-01T00:00:00",
                "library_path": "/library",
                "items": [{"id": "db", "path": "Films/Db", "title": "DB", "type": "movie", "category": "Films"}],
            }
            conn = db.initialize_database(db_path)
            try:
                media_repository.replace_library(conn, db_doc)
            finally:
                conn.close()

            loaded = media_repository.load_library(json_path, db_path)

            self.assertEqual([item["id"] for item in loaded["items"]], ["db"])

    def test_media_library_imports_json_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library.json"
            json_path.parent.mkdir()
            item = {
                "id": "movie:Films:Inception (2010)",
                "path": "Films/Inception (2010)",
                "title": "Inception",
                "raw": "Inception (2010)",
                "category": "Films",
                "type": "movie",
                "year": 2010,
                "quality": {"score": 87},
                "providers": ["Netflix"],
            }
            json_path.write_text(json.dumps({"version": 1, "items": [item]}), encoding="utf-8")

            first = media_repository.load_library(json_path, db_path)
            second = media_repository.load_library(json_path, db_path)
            conn = db.initialize_database(db_path)
            try:
                media_count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
                provider_count = conn.execute("SELECT COUNT(*) FROM media_providers").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(first["items"], second["items"])
            self.assertEqual(media_count, 1)
            self.assertEqual(provider_count, 1)
            self.assertEqual(first["items"][0]["quality"]["score"], 87)

    def test_media_library_tolerates_absent_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            missing_json = root / "data" / "missing_library.json"
            invalid_json = root / "data" / "invalid_library.json"
            invalid_json.parent.mkdir()
            invalid_json.write_text("{ invalid", encoding="utf-8")

            missing = media_repository.load_library(missing_json, root / "data" / "missing.db")
            invalid = media_repository.load_library(invalid_json, root / "data" / "invalid.db")

            self.assertIsNone(missing)
            self.assertIsNone(invalid)

    def test_media_library_loads_empty_snapshot_after_json_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library.json"
            conn = db.initialize_database(db_path)
            try:
                media_repository.replace_library(conn, {"version": 1, "items": []})
            finally:
                conn.close()

            loaded = media_repository.load_library(json_path, db_path)

            self.assertEqual(loaded["items"], [])
            self.assertEqual(loaded["total_items"], 0)

    def test_media_library_requires_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")

            with self.assertRaises(Exception):
                media_repository.load_library(root / "library.json", blocked_parent / "mml.db")

    def test_media_library_save_updates_sqlite_and_exports_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library.json"
            movie = {
                "id": "movie:Films:Inception (2010)",
                "path": "Films/Inception (2010)",
                "title": "Inception",
                "category": "Films",
                "type": "movie",
                "resolution": "1080p",
                "codec": "h264",
                "audio_languages": ["eng", "fra"],
                "subtitle_languages": ["fra"],
                "providers": ["Netflix"],
                "quality": {"score": 91},
            }
            series = {
                "id": "tv:Series:Dark",
                "path": "Series/Dark",
                "title": "Dark",
                "category": "Series",
                "type": "tv",
                "seasons": [{"season": 1, "episodes_found": 2, "resolution": "4K"}],
            }
            document = {"scanned_at": "2026-05-01T00:00:00", "library_path": "/library", "items": [movie, series]}

            media_repository.save_library(document, json_path, db_path)

            conn = db.initialize_database(db_path)
            try:
                rows = conn.execute(
                    "SELECT id, media_type, quality_score, resolution, data_json FROM media ORDER BY id"
                ).fetchall()
                seasons = conn.execute("SELECT media_id, season_number, episodes_count, resolution FROM seasons").fetchall()
                providers = conn.execute("SELECT COUNT(*) FROM media_providers").fetchone()[0]
            finally:
                conn.close()

            exported = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in exported["items"]], [movie["id"], series["id"]])
            self.assertEqual([row["id"] for row in rows], [movie["id"], series["id"]])
            self.assertEqual(rows[0]["quality_score"], 91)
            self.assertEqual(rows[0]["resolution"], "1080p")
            self.assertEqual(json.loads(rows[0]["data_json"])["audio_languages"], ["eng", "fra"])
            self.assertEqual(seasons[0]["media_id"], series["id"])
            self.assertEqual(seasons[0]["episodes_count"], 2)
            self.assertEqual(providers, 1)

    def test_scanner_library_write_uses_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = pathlib.Path(tmpdir) / "library.json"
            document = {"items": [{"id": "db", "path": "Films/Db", "title": "DB", "type": "movie"}]}
            repo_payload = dict(document, total_items=1)

            with patch.object(scanner, "OUTPUT_PATH", str(output_path)), \
                 patch.object(scanner.media_repository, "save_library", return_value=repo_payload) as save:
                scanner.write_json(document, str(output_path))

            save.assert_called_once_with(document, str(output_path))

    def test_scanner_library_load_prefers_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = pathlib.Path(tmpdir) / "library.json"
            output_path.write_text(
                json.dumps({"items": [{"id": "json", "path": "Films/Json", "title": "JSON"}]}),
                encoding="utf-8",
            )
            repo_payload = {"items": [{"id": "db", "path": "Films/Db", "title": "DB"}]}

            with patch.object(scanner.media_repository, "load_library", return_value=repo_payload):
                loaded = scanner.load_library_document_non_blocking(str(output_path))
                existing = scanner.load_existing(str(output_path))

            self.assertEqual([item["id"] for item in loaded["items"]], ["db"])
            self.assertEqual(existing["Films/Db"]["title"], "DB")

    def test_provider_mappings_read_sqlite_before_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "providers_mapping.json"
            json_path.parent.mkdir()
            json_path.write_text('{"Netflix":"json-value"}', encoding="utf-8")

            conn = db.initialize_database(db_path)
            try:
                conn.execute(
                    "INSERT INTO providers(raw_name, mapped_name) VALUES (?, ?)",
                    ("Netflix", "db-value"),
                )
                conn.commit()
            finally:
                conn.close()

            mapping = providers_repository.load_provider_mappings(json_path, db_path)

            self.assertEqual(mapping, {"Netflix": "db-value"})

    def test_provider_mappings_returns_empty_when_sqlite_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "providers_mapping.json"
            json_path.parent.mkdir()
            json_path.write_text('{"Netflix":"Netflix","Ignored":null}', encoding="utf-8")

            # No JSON fallback: empty DB → empty result (seed runs at bootstrap, not here)
            mapping = providers_repository.load_provider_mappings(json_path, db_path)

            self.assertEqual(mapping, {})

    def test_provider_mappings_require_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            json_path = root / "conf" / "providers_mapping.json"
            json_path.parent.mkdir()
            json_path.write_text('{"Netflix":"Netflix"}', encoding="utf-8")

            with self.assertRaises(Exception):
                providers_repository.load_provider_mappings(json_path, blocked_parent / "mml.db")

    def test_provider_mapping_save_updates_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "providers_mapping.json"

            providers_repository.save_provider_mappings({"Netflix": "Netflix", "Raw": None}, json_path, db_path)

            conn = db.initialize_database(db_path)
            try:
                rows = conn.execute(
                    "SELECT raw_name, mapped_name, is_ignored FROM providers ORDER BY raw_name"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(
                [(row["raw_name"], row["mapped_name"], row["is_ignored"]) for row in rows],
                [("Netflix", "Netflix", 0), ("Raw", None, 1)],
            )

    def test_provider_logos_read_sqlite_before_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "providers_logo.json"
            json_path.parent.mkdir()
            json_path.write_text('{"Netflix":"json.webp"}', encoding="utf-8")

            conn = db.initialize_database(db_path)
            try:
                conn.execute(
                    "INSERT INTO providers(raw_name, logo_path) VALUES (?, ?)",
                    ("Netflix", "db.webp"),
                )
                conn.commit()
            finally:
                conn.close()

            logos = providers_repository.load_provider_logos(json_path, db_path)

            self.assertEqual(logos, {"Netflix": "db.webp"})

    def test_recommendations_loads_sqlite_before_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "recommendations.json"
            json_path.parent.mkdir()
            json_path.write_text(
                json.dumps({"version": 1, "items": [{"id": "json-rec", "display": {"title": "JSON"}}]}),
                encoding="utf-8",
            )
            conn = db.initialize_database(db_path)
            try:
                recommendations_repository.upsert_recommendation(
                    conn,
                    {
                        "id": "db-rec",
                        "display": {"title": "DB"},
                        "recommendation_type": "quality",
                        "priority": "medium",
                        "message": {"en": "DB"},
                        "suggested_action": {"en": "Fix"},
                    },
                )
                conn.commit()
            finally:
                conn.close()

            payload = recommendations_repository.load_recommendations(json_path, db_path)

            self.assertEqual([item["id"] for item in payload["items"]], ["db-rec"])

    def test_recommendations_imports_json_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "recommendations.json"
            json_path.parent.mkdir()
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
            json_path.write_text(json.dumps({"version": 1, "items": [rec]}), encoding="utf-8")

            first = recommendations_repository.load_recommendations(json_path, db_path)
            second = recommendations_repository.load_recommendations(json_path, db_path)
            conn = db.initialize_database(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(first["items"], second["items"])
            self.assertEqual(count, 1)
            self.assertEqual(first["items"][0]["rule_id"], "low_score")

    def test_recommendations_tolerates_absent_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            missing_json = root / "data" / "missing_recommendations.json"
            invalid_json = root / "data" / "invalid_recommendations.json"
            invalid_json.parent.mkdir()
            invalid_json.write_text("{ invalid", encoding="utf-8")

            missing = recommendations_repository.load_recommendations(missing_json, root / "data" / "missing.db")
            invalid = recommendations_repository.load_recommendations(invalid_json, root / "data" / "invalid.db")

            self.assertIsNone(missing)
            self.assertIsNone(invalid)

    def test_recommendations_require_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")

            with self.assertRaises(Exception):
                recommendations_repository.load_recommendations(
                    root / "recommendations.json",
                    blocked_parent / "mml.db",
                )

    def test_recommendations_save_replaces_sqlite_and_exports_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "recommendations.json"
            old_rec = {
                "id": "old-rec",
                "display": {"title": "Old"},
                "recommendation_type": "quality",
                "priority": "low",
            }
            new_rec = {
                "id": "new-rec",
                "media_ref": {"id": "movie:Films:Inception (2010)", "type": "movie"},
                "display": {"title": "Inception"},
                "recommendation_type": "quality",
                "priority": "high",
                "rule_id": "low_score",
                "message": {"en": "Low score"},
                "suggested_action": {"en": "Replace"},
            }

            recommendations_repository.save_recommendations([old_rec], json_path, db_path)
            recommendations_repository.save_recommendations([new_rec], json_path, db_path)

            conn = db.initialize_database(db_path)
            try:
                rows = conn.execute("SELECT id, media_id, priority, details_json FROM recommendations").fetchall()
            finally:
                conn.close()

            exported = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in exported["items"]], ["new-rec"])
            self.assertEqual([row["id"] for row in rows], ["new-rec"])
            self.assertIsNone(rows[0]["media_id"])
            self.assertEqual(rows[0]["priority"], "high")
            self.assertEqual(json.loads(rows[0]["details_json"])["media_ref"]["id"], "movie:Films:Inception (2010)")

    def test_recommendations_upsert_keeps_existing_media_id_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "data" / "mml.db"
            conn = db.initialize_database(db_path)
            try:
                conn.execute(
                    "INSERT INTO media(id, media_type, title) VALUES (?, ?, ?)",
                    ("movie:Films:Inception (2010)", "movie", "Inception"),
                )
                recommendations_repository.upsert_recommendation(
                    conn,
                    {
                        "id": "rec:movie:Films:Inception (2010):low_score",
                        "media_ref": {"id": "movie:Films:Inception (2010)", "type": "movie"},
                        "display": {"title": "Inception"},
                        "recommendation_type": "quality",
                        "priority": "medium",
                    },
                )
                row = conn.execute("SELECT media_id FROM recommendations").fetchone()
            finally:
                conn.close()

            self.assertEqual(row["media_id"], "movie:Films:Inception (2010)")

    def test_scanner_recommendations_api_prefers_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recs_path = pathlib.Path(tmpdir) / "recommendations.json"
            recs_path.write_text(
                json.dumps({"version": 1, "items": [{"id": "json-rec"}]}),
                encoding="utf-8",
            )
            db_payload = {"version": 1, "generated_at": "2026-05-01T00:00:00Z", "items": [{"id": "db-rec"}]}

            with patch.object(scanner, "RECOMMENDATIONS_OUTPUT_PATH", str(recs_path)), \
                 patch.object(scanner.recommendations_repository, "load_recommendations", return_value=db_payload):
                payload = scanner._recommendations_api_payload({"score": {"enabled": True}, "recommendations": {"enabled": True}})

            self.assertTrue(payload["enabled"])
            self.assertEqual([item["id"] for item in payload["items"]], ["db-rec"])

    def test_scanner_recommendations_save_uses_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recs_path = pathlib.Path(tmpdir) / "recommendations.json"
            items = [{"id": "rec", "display": {"title": "Title"}}]
            repo_payload = {"version": 1, "generated_at": "2026-05-01T00:00:00Z", "items": items}

            with patch.object(scanner.recommendations_repository, "save_recommendations", return_value=repo_payload) as save:
                payload = scanner.save_recommendations_document_non_blocking(items, str(recs_path))

            save.assert_called_once_with(items, str(recs_path))
            self.assertEqual(payload, repo_payload)

    def test_recommendation_rules_read_sqlite_before_json_and_filter_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "recommendations_rules.json"
            json_path.parent.mkdir()
            json_path.write_text(
                '{"rules":[{"id":"json-rule","enabled":true}]}',
                encoding="utf-8",
            )

            conn = db.initialize_database(db_path)
            try:
                conn.execute(
                    "INSERT INTO recommendation_rules(rule_key, enabled) VALUES (?, ?)",
                    ("db-rule", 1),
                )
                conn.execute(
                    "INSERT INTO recommendation_rules(rule_key, enabled) VALUES (?, ?)",
                    ("disabled-rule", 0),
                )
                conn.commit()
            finally:
                conn.close()

            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)

            self.assertEqual([rule["id"] for rule in rules], ["db-rule"])

    def test_recommendation_rules_returns_empty_when_sqlite_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "recommendations_rules.json"
            json_path.parent.mkdir()
            json_path.write_text(
                '{"rules":[{"id":"json-rule","enabled":true},{"id":"off","enabled":false}]}',
                encoding="utf-8",
            )

            # No JSON fallback: empty DB → empty result (seed runs at bootstrap, not here)
            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)

            self.assertEqual(rules, [])

    def test_recommendation_rules_do_not_fallback_when_sqlite_rules_are_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "recommendations_rules.json"
            json_path.parent.mkdir()
            json_path.write_text(
                '{"rules":[{"id":"json-rule","enabled":true}]}',
                encoding="utf-8",
            )

            conn = db.initialize_database(db_path)
            try:
                conn.execute(
                    "INSERT INTO recommendation_rules(rule_key, enabled) VALUES (?, ?)",
                    ("disabled-rule", 0),
                )
                conn.commit()
            finally:
                conn.close()

            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)

            self.assertEqual(rules, [])

    def test_save_config_preserves_runtime_library_snapshot(self):
        """Bug fix: save_config must not wipe runtime_library_document from app_config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library.json"
            cfg_path = root / "data" / "config.json"

            # Write a library snapshot into app_config
            conn = db.initialize_database(db_path)
            try:
                media_repository.replace_library(conn, {"items": [{"id": "m1", "title": "Test", "path": "/t", "type": "movie"}]})
                snapshot_before = conn.execute(
                    "SELECT value_json FROM app_config WHERE key = 'runtime_library_document'"
                ).fetchone()
                self.assertIsNotNone(snapshot_before)
            finally:
                conn.close()

            # Save user config — must NOT touch runtime_library_document
            config_repository.save_config(
                {"system": {"log_level": "DEBUG"}, "folders": [], "score": {"enabled": False}},
                cfg_path,
                db_path,
            )

            # Snapshot must still be present and unchanged
            conn = db.initialize_database(db_path)
            try:
                snapshot_after = conn.execute(
                    "SELECT value_json FROM app_config WHERE key = 'runtime_library_document'"
                ).fetchone()
                self.assertIsNotNone(snapshot_after)
                self.assertEqual(snapshot_before["value_json"], snapshot_after["value_json"])
            finally:
                conn.close()

            # load_library must still return the snapshot
            loaded = media_repository.load_library(json_path, db_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(len(loaded["items"]), 1)
            self.assertEqual(loaded["items"][0]["id"], "m1")

    def test_reset_clears_runtime_library_snapshot(self):
        """Bug fix: run_reset must delete runtime_library_document so /api/library returns empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library.json"

            conn = db.initialize_database(db_path)
            try:
                media_repository.replace_library(conn, {"items": [{"id": "m1", "title": "T", "path": "/t", "type": "movie"}]})
                # Verify snapshot is present
                row = conn.execute("SELECT 1 FROM app_config WHERE key = 'runtime_library_document'").fetchone()
                self.assertIsNotNone(row)
                # Simulate reset
                with conn:
                    conn.execute("DELETE FROM media")
                    conn.execute("DELETE FROM recommendations")
                    conn.execute("DELETE FROM scan_runs")
                    media_repository.clear_library_snapshot(conn)
            finally:
                conn.close()

            # Snapshot must be gone
            conn = db.initialize_database(db_path)
            try:
                row = conn.execute("SELECT 1 FROM app_config WHERE key = 'runtime_library_document'").fetchone()
                self.assertIsNone(row)
            finally:
                conn.close()

            # load_library must return None (empty library)
            loaded = media_repository.load_library(json_path, db_path)
            self.assertIsNone(loaded)

    def test_scanner_provider_mapping_uses_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mapping_path = pathlib.Path(tmpdir) / "providers_mapping.json"
            mapping_path.write_text("{}", encoding="utf-8")
            with patch.object(scanner, "PROVIDERS_MAPPING_RUNTIME_PATH", str(mapping_path)), \
                 patch.object(scanner.providers_repository, "load_provider_mappings", return_value={"DB": "value"}) as load:
                mapping = scanner._load_runtime_provider_mapping()

            load.assert_called_once_with(str(mapping_path))
            self.assertEqual(mapping, {"DB": "value"})

    def test_scanner_recommendation_rules_uses_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_path = pathlib.Path(tmpdir) / "recommendations_rules.json"
            rules_path.write_text('{"rules":[]}', encoding="utf-8")
            with patch.object(scanner, "RECOMMENDATIONS_RULES_PATH", str(rules_path)), \
                 patch.object(scanner.recommendations_repository, "load_recommendation_rules", return_value=[{"id": "db"}]) as load:
                rules = scanner._load_runtime_recommendation_rules()

            load.assert_called_once_with(str(rules_path))
            self.assertEqual(rules, [{"id": "db"}])


if __name__ == "__main__":
    unittest.main()
