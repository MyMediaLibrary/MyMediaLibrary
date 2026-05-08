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
    ffprobe_repository,
    inventory_repository,
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
                    "INSERT INTO scan_settings(id, value_json) VALUES (?, ?)",
                    ("media_probe", '{"enabled":true,"workers":2}'),
                )
                conn.commit()
            finally:
                conn.close()

            cfg = config_repository.load_config(json_path, db_path)

            self.assertEqual(cfg["system"]["log_level"], "DB")
            self.assertEqual(cfg["score"], {"enabled": True})
            self.assertEqual(cfg["score_configuration"], {"weights": {"video": 40}})
            self.assertEqual(cfg["media_probe"], {"enabled": True, "workers": 2})

    def test_config_imports_json_when_sqlite_empty(self):
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
            self.assertEqual(cfg["folders"], payload["folders"])
            self.assertEqual(cfg["score"], {"enabled": True})
            self.assertEqual(cfg["score_configuration"], payload["score_configuration"])
            self.assertEqual(cfg["media_probe"], payload["media_probe"])
            self.assertEqual(cfg_again, cfg)
            conn = db.initialize_database(db_path)
            try:
                app_count = conn.execute("SELECT COUNT(*) FROM app_config").fetchone()[0]
                score_count = conn.execute("SELECT COUNT(*) FROM score_settings").fetchone()[0]
                scan_count = conn.execute("SELECT COUNT(*) FROM scan_settings").fetchone()[0]
            finally:
                conn.close()
            self.assertGreaterEqual(app_count, 2)
            self.assertEqual(score_count, 1)
            self.assertEqual(scan_count, 1)

    def test_config_fallback_to_json_when_sqlite_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            json_path = root / "conf" / "config.json"
            json_path.parent.mkdir()
            json_path.write_text('{"system":{"log_level":"INFO"},"folders":[]}', encoding="utf-8")

            cfg = config_repository.load_config(json_path, blocked_parent / "mml.db")

            self.assertIsNone(cfg)

    def test_config_save_updates_sqlite_and_json_without_secrets(self):
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

            exported = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertNotIn("apikey", exported["seerr"])
            self.assertEqual(exported["seerr"], {"url": "https://seerr.test"})
            cfg = config_repository.load_config(json_path, db_path)
            self.assertNotIn("apikey", cfg["seerr"])
            self.assertEqual(cfg["score"], {"enabled": True})
            self.assertEqual(cfg["media_probe"], {"enabled": True, "workers": 2})

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

    def test_ffprobe_cache_hit_and_miss_by_file_signature(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            cache_json = root / "data" / "media_probe_cache.json"
            media_file = root / "library" / "movie.mkv"
            media_file.parent.mkdir()
            media_file.write_bytes(b"movie")
            stat = media_file.stat()
            repo = ffprobe_repository.open_cache(json_path=cache_json, db_path=db_path)
            try:
                repo.upsert_probe(
                    media_file,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    probe={"ok": True, "technical": {"resolution": "1080p"}},
                )
                hit = repo.get(media_file, size=stat.st_size, mtime=stat.st_mtime)
                miss = repo.get(media_file, size=stat.st_size + 1, mtime=stat.st_mtime)
            finally:
                repo.close()

            self.assertEqual(hit, {"ok": True, "technical": {"resolution": "1080p"}})
            self.assertIsNone(miss)

    def test_ffprobe_cache_upsert_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            cache_json = root / "data" / "media_probe_cache.json"
            media_file = root / "library" / "broken.mkv"
            media_file.parent.mkdir()
            media_file.write_bytes(b"broken")
            stat = media_file.stat()
            repo = ffprobe_repository.open_cache(json_path=cache_json, db_path=db_path)
            try:
                repo.upsert_error(media_file, size=stat.st_size, mtime=stat.st_mtime, error="broken file")
                cached = repo.get(media_file, size=stat.st_size, mtime=stat.st_mtime)
            finally:
                repo.close()

            self.assertEqual(cached, {"ok": False, "error": "broken file"})

    def test_ffprobe_cache_imports_json_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            cache_json = root / "data" / "media_probe_cache.json"
            cache_json.parent.mkdir()
            cache_json.write_text(
                json.dumps({
                    "version": 1,
                    "files": {
                        "/library/movie.mkv": {
                            "path": "/library/movie.mkv",
                            "size_b": 123,
                            "mtime": 42.5,
                            "probe": {"ok": True, "technical": {"codec": "H.265"}},
                        }
                    },
                }),
                encoding="utf-8",
            )

            first = ffprobe_repository.open_cache(json_path=cache_json, db_path=db_path)
            first.close()
            second = ffprobe_repository.open_cache(json_path=cache_json, db_path=db_path)
            try:
                cached = second.get("/library/movie.mkv", size=123, mtime=42.5)
                count = second.conn.execute("SELECT COUNT(*) FROM ffprobe_cache").fetchone()[0]
            finally:
                second.close()

            self.assertEqual(cached, {"ok": True, "technical": {"codec": "H.265"}})
            self.assertEqual(count, 1)

    def test_ffprobe_cache_tolerates_absent_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            missing_json = root / "data" / "missing.json"
            invalid_json = root / "data" / "invalid.json"
            invalid_json.parent.mkdir()
            invalid_json.write_text("{ invalid", encoding="utf-8")

            missing_repo = ffprobe_repository.open_cache(json_path=missing_json, db_path=db_path)
            missing_count = missing_repo.conn.execute("SELECT COUNT(*) FROM ffprobe_cache").fetchone()[0]
            missing_repo.close()
            invalid_repo = ffprobe_repository.open_cache(json_path=invalid_json, db_path=root / "data" / "other.db")
            invalid_count = invalid_repo.conn.execute("SELECT COUNT(*) FROM ffprobe_cache").fetchone()[0]
            invalid_repo.close()

            self.assertEqual(missing_count, 0)
            self.assertEqual(invalid_count, 0)

    def test_ffprobe_cache_fallback_when_sqlite_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")

            repo = ffprobe_repository.open_cache(json_path=root / "cache.json", db_path=blocked_parent / "db.sqlite")

            self.assertIsNone(repo)

    def test_inventory_loads_sqlite_before_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library_inventory.json"
            json_path.parent.mkdir()
            json_path.write_text(
                json.dumps({"version": 1, "items": [{"id": "movie:Films:Json", "title": "JSON"}]}),
                encoding="utf-8",
            )
            conn = db.initialize_database(db_path)
            try:
                inventory_repository.upsert_item(
                    conn,
                    {
                        "id": "movie:Films:Db",
                        "media_type": "movie",
                        "title": "DB",
                        "category": "Films",
                        "status": "present",
                    },
                )
                conn.commit()
            finally:
                conn.close()

            document = inventory_repository.load_inventory(json_path, db_path)

            self.assertEqual([item["title"] for item in document["items"]], ["DB"])

    def test_inventory_imports_json_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library_inventory.json"
            json_path.parent.mkdir()
            json_path.write_text(
                json.dumps({
                    "version": 1,
                    "items": [
                        {
                            "id": "movie:Films:Inception (2010)",
                            "media_type": "movie",
                            "title": "Inception",
                            "category": "Films",
                            "root_folder_path": "Films/Inception (2010)",
                            "status": "present",
                            "first_seen_at": "2026-04-01T00:00:00Z",
                            "last_seen_at": "2026-04-02T00:00:00Z",
                            "last_checked_at": "2026-04-02T00:00:00Z",
                        }
                    ],
                }),
                encoding="utf-8",
            )

            first = inventory_repository.load_inventory(json_path, db_path)
            second = inventory_repository.load_inventory(json_path, db_path)
            conn = db.initialize_database(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(first, second)
            self.assertEqual(count, 1)
            self.assertEqual(first["items"][0]["title"], "Inception")

    def test_inventory_tolerates_absent_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            missing_json = root / "data" / "missing_inventory.json"
            invalid_json = root / "data" / "invalid_inventory.json"
            invalid_json.parent.mkdir()
            invalid_json.write_text("{ invalid", encoding="utf-8")

            missing = inventory_repository.load_inventory(missing_json, root / "data" / "missing.db")
            invalid = inventory_repository.load_inventory(invalid_json, root / "data" / "invalid.db")

            self.assertIsNone(missing)
            self.assertIsNone(invalid)

    def test_inventory_fallback_when_sqlite_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            json_path = root / "library_inventory.json"

            document = inventory_repository.load_inventory(json_path, blocked_parent / "mml.db")

            self.assertIsNone(document)

    def test_inventory_save_updates_sqlite_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "data" / "library_inventory.json"
            document = {
                "version": 1,
                "generated_at": "2026-04-02T00:00:00Z",
                "items": [
                    {
                        "id": "movie:Films:Inception (2010)",
                        "media_type": "movie",
                        "title": "Inception",
                        "category": "Films",
                        "root_folder_path": "Films/Inception (2010)",
                        "status": "present",
                        "first_seen_at": "2026-04-01T00:00:00Z",
                        "last_seen_at": "2026-04-02T00:00:00Z",
                        "last_checked_at": "2026-04-02T00:00:00Z",
                    }
                ],
            }

            inventory_repository.save_inventory(document, json_path, db_path)

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["generated_at"], document["generated_at"])
            conn = db.initialize_database(db_path)
            try:
                row = conn.execute(
                    "SELECT inventory_key, title, status, path FROM inventory_items"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual((row["inventory_key"], row["title"], row["status"], row["path"]), (
                "movie:Films:Inception (2010)",
                "Inception",
                "present",
                "Films/Inception (2010)",
            ))

    def test_inventory_upsert_present_preserves_first_seen_and_updates_seen_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "data" / "mml.db"
            conn = db.initialize_database(db_path)
            try:
                inventory_repository.upsert_item(
                    conn,
                    {
                        "id": "movie:Films:Inception (2010)",
                        "title": "Inception",
                        "status": "present",
                        "first_seen_at": "2026-04-01T00:00:00Z",
                        "last_seen_at": "2026-04-01T00:00:00Z",
                        "last_checked_at": "2026-04-01T00:00:00Z",
                    },
                )
                inventory_repository.upsert_item(
                    conn,
                    {
                        "id": "movie:Films:Inception (2010)",
                        "title": "Inception",
                        "status": "present",
                        "first_seen_at": "2026-05-01T00:00:00Z",
                        "last_seen_at": "2026-05-01T00:00:00Z",
                        "last_checked_at": "2026-05-01T00:00:00Z",
                    },
                )
                row = conn.execute(
                    "SELECT first_seen_at, last_seen_at, last_checked_at, data_json FROM inventory_items"
                ).fetchone()
            finally:
                conn.close()

            data = json.loads(row["data_json"])
            self.assertEqual(row["first_seen_at"], "2026-04-01T00:00:00Z")
            self.assertEqual(data["first_seen_at"], "2026-04-01T00:00:00Z")
            self.assertEqual(row["last_seen_at"], "2026-05-01T00:00:00Z")
            self.assertEqual(row["last_checked_at"], "2026-05-01T00:00:00Z")

    def test_inventory_mark_missing_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = pathlib.Path(tmpdir) / "data" / "mml.db"
            conn = db.initialize_database(db_path)
            try:
                inventory_repository.mark_present(
                    conn,
                    "movie:Films:Inception (2010)",
                    seen_at="2026-04-01T00:00:00Z",
                    data={"title": "Inception", "category": "Films"},
                )
                inventory_repository.mark_missing(
                    conn,
                    "movie:Films:Inception (2010)",
                    checked_at="2026-05-01T00:00:00Z",
                )
                inventory_repository.mark_missing(
                    conn,
                    "movie:Films:Inception (2010)",
                    checked_at="2026-05-02T00:00:00Z",
                )
                row = conn.execute(
                    "SELECT status, first_seen_at, last_seen_at, last_checked_at, missing_since, data_json FROM inventory_items"
                ).fetchone()
            finally:
                conn.close()

            data = json.loads(row["data_json"])
            self.assertEqual(row["status"], "missing")
            self.assertEqual(row["first_seen_at"], "2026-04-01T00:00:00Z")
            self.assertEqual(row["last_seen_at"], "2026-04-01T00:00:00Z")
            self.assertEqual(row["last_checked_at"], "2026-05-02T00:00:00Z")
            self.assertEqual(row["missing_since"], "2026-05-01T00:00:00Z")
            self.assertEqual(data["missing_since"], "2026-05-01T00:00:00Z")

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

    def test_media_library_fallback_when_sqlite_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")

            loaded = media_repository.load_library(root / "library.json", blocked_parent / "mml.db")

            self.assertIsNone(loaded)

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

            exported = json.loads(json_path.read_text(encoding="utf-8"))
            conn = db.initialize_database(db_path)
            try:
                rows = conn.execute(
                    "SELECT id, media_type, quality_score, resolution, data_json FROM media ORDER BY id"
                ).fetchall()
                seasons = conn.execute("SELECT media_id, season_number, episodes_count, resolution FROM seasons").fetchall()
                providers = conn.execute("SELECT COUNT(*) FROM media_providers").fetchone()[0]
            finally:
                conn.close()

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

    def test_scanner_inventory_load_prefers_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library_inventory.json"
            json_path.write_text(
                json.dumps({"version": 1, "items": [{"id": "json", "title": "JSON"}]}),
                encoding="utf-8",
            )
            repo_document = {"version": 1, "items": [{"id": "db", "title": "DB"}]}

            with patch.object(scanner.inventory_repository, "load_inventory", return_value=repo_document):
                loaded = scanner.load_existing_inventory_document_non_blocking(str(json_path))

            self.assertEqual(loaded, repo_document)

    def test_scanner_inventory_save_uses_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = pathlib.Path(tmpdir) / "library_inventory.json"
            document = {"version": 1, "items": [{"id": "db", "title": "DB"}]}

            with patch.object(scanner.inventory_repository, "save_inventory") as save_inventory:
                scanner.save_inventory_document_non_blocking(document, str(json_path))

            save_inventory.assert_called_once_with(document, str(json_path))

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
                    "INSERT INTO provider_mappings(raw_name, mapped_name) VALUES (?, ?)",
                    ("Netflix", "db-value"),
                )
                conn.commit()
            finally:
                conn.close()

            mapping = providers_repository.load_provider_mappings(json_path, db_path)

            self.assertEqual(mapping, {"Netflix": "db-value"})

    def test_provider_mappings_import_json_when_sqlite_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "providers_mapping.json"
            json_path.parent.mkdir()
            json_path.write_text('{"Netflix":"Netflix","Ignored":null}', encoding="utf-8")

            mapping = providers_repository.load_provider_mappings(json_path, db_path)

            self.assertEqual(mapping, {"Ignored": None, "Netflix": "Netflix"})
            conn = db.initialize_database(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM provider_mappings").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 2)

    def test_provider_mappings_fallback_to_json_when_sqlite_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")
            json_path = root / "conf" / "providers_mapping.json"
            json_path.parent.mkdir()
            json_path.write_text('{"Netflix":"Netflix"}', encoding="utf-8")

            mapping = providers_repository.load_provider_mappings(json_path, blocked_parent / "mml.db")

            self.assertEqual(mapping, {"Netflix": "Netflix"})

    def test_provider_mapping_save_updates_sqlite_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "providers_mapping.json"

            providers_repository.save_provider_mappings({"Netflix": "Netflix", "Raw": None}, json_path, db_path)

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), {"Netflix": "Netflix", "Raw": None})
            conn = db.initialize_database(db_path)
            try:
                rows = conn.execute(
                    "SELECT raw_name, mapped_name, is_ignored FROM provider_mappings ORDER BY raw_name"
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
                    "INSERT INTO provider_logos(provider_name, logo_path) VALUES (?, ?)",
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

    def test_recommendations_fallback_when_sqlite_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("blocked", encoding="utf-8")

            payload = recommendations_repository.load_recommendations(
                root / "recommendations.json",
                blocked_parent / "mml.db",
            )

            self.assertIsNone(payload)

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

            exported = json.loads(json_path.read_text(encoding="utf-8"))
            conn = db.initialize_database(db_path)
            try:
                rows = conn.execute("SELECT id, media_id, priority, details_json FROM recommendations").fetchall()
            finally:
                conn.close()

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
                    "INSERT INTO recommendation_rules(rule_key, rule_json, enabled) VALUES (?, ?, ?)",
                    ("db-rule", '{"id":"db-rule","enabled":true}', 1),
                )
                conn.execute(
                    "INSERT INTO recommendation_rules(rule_key, rule_json, enabled) VALUES (?, ?, ?)",
                    ("disabled-rule", '{"id":"disabled-rule","enabled":false}', 0),
                )
                conn.commit()
            finally:
                conn.close()

            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)

            self.assertEqual([rule["id"] for rule in rules], ["db-rule"])

    def test_recommendation_rules_import_json_when_sqlite_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            db_path = root / "data" / "mml.db"
            json_path = root / "conf" / "recommendations_rules.json"
            json_path.parent.mkdir()
            json_path.write_text(
                '{"rules":[{"id":"json-rule","enabled":true},{"id":"off","enabled":false}]}',
                encoding="utf-8",
            )

            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)

            self.assertEqual([rule["id"] for rule in rules], ["json-rule"])
            conn = db.initialize_database(db_path)
            try:
                count = conn.execute("SELECT COUNT(*) FROM recommendation_rules").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 2)

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
                    "INSERT INTO recommendation_rules(rule_key, rule_json, enabled) VALUES (?, ?, ?)",
                    ("disabled-rule", '{"id":"disabled-rule","enabled":false}', 0),
                )
                conn.commit()
            finally:
                conn.close()

            rules = recommendations_repository.load_recommendation_rules(json_path, db_path)

            self.assertEqual(rules, [])

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
