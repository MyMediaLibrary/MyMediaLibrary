"""SQLite-backed runtime configuration repository."""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

try:
    from backend import db, db_import, runtime_paths
except Exception:
    import db  # type: ignore
    import db_import  # type: ignore
    import runtime_paths  # type: ignore


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
    """Load configuration from SQLite only."""

    conn = db.initialize_database(_effective_db_path(json_path, db_path))
    try:
        if _config_tables_empty(conn):
            if not _is_canonical_json_path(json_path):
                db_import.import_config(conn, json_path)
                if _config_tables_empty(conn):
                    return None
            else:
                return None
        return _export_config(conn)
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
    """Persist sanitized config to SQLite."""

    sanitized = sanitize_config(config)
    conn = db.initialize_database(_effective_db_path(json_path, db_path))
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

    conn = db.initialize_database(db_path)
    try:
        with conn:
            _replace_auth_settings(conn, auth_enabled, password_hash)
    finally:
        conn.close()


def load_auth_settings(db_path: str | Path | None = None) -> dict[str, Any] | None:
    conn = db.initialize_database(db_path)
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


def _effective_db_path(json_path: str | Path, db_path: str | Path | None) -> str | Path | None:
    if db_path is not None:
        return db_path
    path = Path(json_path)
    if path == runtime_paths.CONFIG_JSON:
        return None
    root = path.parent.parent if path.parent.name == "conf" else path.parent
    return root / "data" / "mymedialibrary.db"


def _is_canonical_json_path(json_path: str | Path) -> bool:
    return Path(json_path) == runtime_paths.CONFIG_JSON


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


# Keys owned exclusively by save_config (user configuration).
# Runtime-internal keys like runtime_library_document must never appear here.
_APP_CONFIG_USER_KEYS = frozenset({
    "system",
    "scan",
    "recommendations",
    "seerr",
    "folders",
    "enable_movies",
    "enable_series",
    "providers_visible",
    "ui",
})


def _replace_app_config(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    structured_keys = {"auth", "score", "score_configuration", "media_probe"}
    # Wipe only user-config keys — never touch runtime keys (e.g. runtime_library_document).
    incoming_keys = {str(k) for k in config if k not in structured_keys}
    managed_keys = tuple(_APP_CONFIG_USER_KEYS | incoming_keys)
    if managed_keys:
        conn.execute(
            f"DELETE FROM app_config WHERE key IN ({','.join('?' * len(managed_keys))})",
            managed_keys,
        )
    for key, value in config.items():
        if key in structured_keys:
            continue
        sanitized = _sanitize_value(key, value)
        if sanitized is _SKIP:
            continue
        conn.execute(
            "INSERT INTO app_config(key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
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


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
