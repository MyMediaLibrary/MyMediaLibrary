"""SQLite-backed runtime configuration repository."""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

try:
    from backend import db, db_import
except Exception:
    import db  # type: ignore
    import db_import  # type: ignore


log = logging.getLogger(__name__)

SENSITIVE_KEY_TOKENS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "access_token",
    "refresh_token",
)

_SKIP = object()


def load_config(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Load configuration from SQLite, importing JSON first when DB is empty."""

    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[config] SQLite unavailable for config, falling back to JSON: %s", exc)
        return None
    try:
        if _config_tables_empty(conn):
            imported = db_import.import_config(conn, json_path)
            if not imported and _config_tables_empty(conn):
                return None
        return _export_config(conn)
    except Exception as exc:
        log.warning("[config] Could not load config from SQLite: %s", exc)
        return None
    finally:
        conn.close()


def save_config(
    config: dict[str, Any],
    json_path: str | Path,
    db_path: str | Path | None = None,
    *,
    auth_enabled: bool | None = None,
    password_hash: str | None = None,
) -> None:
    """Persist sanitized config to SQLite and JSON compatibility output."""

    sanitized = sanitize_config(config)
    _write_json(json_path, sanitized)
    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.warning("[config] Could not open SQLite config store: %s", exc)
        return
    try:
        with conn:
            _replace_app_config(conn, sanitized)
            _replace_score_settings(conn, sanitized)
            _replace_scan_settings(conn, sanitized)
            if auth_enabled is not None or password_hash is not None:
                _replace_auth_settings(conn, bool(auth_enabled), password_hash)
    finally:
        conn.close()


def save_auth_settings(
    *,
    auth_enabled: bool,
    password_hash: str | None,
    db_path: str | Path | None = None,
) -> None:
    """Persist hash-only auth state to SQLite without touching .secrets."""

    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[config] SQLite unavailable for auth settings: %s", exc)
        return
    try:
        with conn:
            _replace_auth_settings(conn, auth_enabled, password_hash)
    finally:
        conn.close()


def load_auth_settings(db_path: str | Path | None = None) -> dict[str, Any] | None:
    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[config] SQLite unavailable for auth settings: %s", exc)
        return None
    try:
        row = conn.execute(
            "SELECT auth_enabled, password_hash, updated_at FROM auth_settings WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "auth_enabled": bool(row["auth_enabled"]),
        "password_hash": row["password_hash"],
        "updated_at": row["updated_at"],
    }


def sanitize_config(value: Any) -> Any:
    """Return a copy without API keys, tokens, secrets, or passwords."""

    cleaned = _sanitize_value("", value)
    return cleaned if isinstance(cleaned, dict) else {}


def _config_tables_empty(conn: sqlite3.Connection) -> bool:
    for table in ("app_config", "scan_settings", "score_settings", "auth_settings"):
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
            return False
    return True


def _export_config(conn: sqlite3.Connection) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    rows = conn.execute("SELECT key, value_json FROM app_config ORDER BY key").fetchall()
    for row in rows:
        cfg[row["key"]] = _from_json(row["value_json"], None)

    score_row = conn.execute(
        "SELECT enabled, configuration_json FROM score_settings WHERE id = 'default'"
    ).fetchone()
    if score_row is not None:
        cfg["score"] = {"enabled": bool(score_row["enabled"])}
        cfg["score_configuration"] = _from_json(score_row["configuration_json"], {})

    scan_rows = conn.execute("SELECT id, value_json FROM scan_settings ORDER BY id").fetchall()
    for row in scan_rows:
        cfg[row["id"]] = _from_json(row["value_json"], {})

    return sanitize_config(cfg)


def _replace_app_config(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    structured_keys = {"auth", "score", "score_configuration", "media_probe"}
    conn.execute("DELETE FROM app_config")
    for key, value in config.items():
        if key in structured_keys:
            continue
        sanitized = _sanitize_value(key, value)
        if sanitized is _SKIP:
            continue
        conn.execute(
            """
            INSERT INTO app_config(key, value_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (str(key), _to_json(sanitized)),
        )


def _replace_score_settings(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    score = config.get("score") if isinstance(config.get("score"), dict) else {}
    score_config = config.get("score_configuration") if isinstance(config.get("score_configuration"), dict) else {}
    conn.execute("DELETE FROM score_settings")
    conn.execute(
        """
        INSERT INTO score_settings(id, enabled, configuration_json, updated_at)
        VALUES ('default', ?, ?, CURRENT_TIMESTAMP)
        """,
        (1 if score.get("enabled") is True else 0, _to_json(score_config)),
    )


def _replace_scan_settings(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    conn.execute("DELETE FROM scan_settings")
    for key in ("media_probe",):
        value = config.get(key)
        if isinstance(value, dict):
            conn.execute(
                """
                INSERT INTO scan_settings(id, value_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (key, _to_json(value)),
            )


def _replace_auth_settings(conn: sqlite3.Connection, auth_enabled: bool, password_hash: str | None) -> None:
    conn.execute(
        """
        INSERT INTO auth_settings(id, auth_enabled, password_hash, updated_at)
        VALUES (1, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            auth_enabled = excluded.auth_enabled,
            password_hash = excluded.password_hash,
            updated_at = CURRENT_TIMESTAMP
        """,
        (1 if auth_enabled and password_hash else 0, password_hash if auth_enabled else None),
    )


def _sanitize_value(key: str, value: Any) -> Any:
    lowered = str(key).casefold()
    if any(token in lowered for token in SENSITIVE_KEY_TOKENS):
        return _SKIP
    if isinstance(value, dict):
        cleaned = {}
        for child_key, child_value in value.items():
            sanitized = _sanitize_value(child_key, child_value)
            if sanitized is not _SKIP:
                cleaned[child_key] = sanitized
        return cleaned
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            sanitized = _sanitize_value(key, item)
            if sanitized is not _SKIP:
                cleaned_list.append(sanitized)
        return cleaned_list
    return copy.deepcopy(value)


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
