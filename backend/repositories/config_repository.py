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
    from backend.scoring import (
        flatten_score_to_rules,
        flatten_score_to_size_profiles,
        reconstruct_score_config_from_rows,
    )
except Exception:
    import db  # type: ignore
    import db_import  # type: ignore
    import runtime_paths  # type: ignore
    from scoring import (  # type: ignore
        flatten_score_to_rules,
        flatten_score_to_size_profiles,
        reconstruct_score_config_from_rows,
    )


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
    """Persist config to SQLite.

    Sensitive subkeys (apikey, token, password, …) are filtered during write by
    _replace_app_config — no upfront deepcopy needed here.
    """
    conn = db.initialize_database(_effective_db_path(json_path, db_path))
    try:
        with conn:
            _replace_app_config(conn, config)
            _replace_folders(conn, config)
            _replace_providers_visibility(conn, config)
            _replace_score_data(conn, config)
            if auth_enabled is not None or password_hash is not None:
                _replace_auth_settings(conn, bool(auth_enabled), password_hash)
    finally:
        conn.close()


def save_score_configuration(
    score_configuration: dict[str, Any] | None,
    score_enabled: bool | None,
    db_path: str | Path | None = None,
) -> None:
    """Persist ONLY score_rules / score_size_profiles / score.enabled — no other table touched.

    Used by the score-settings PUT/POST/reset handlers so they don't trigger a
    full config rewrite (folders, app_config scalars, providers, …).
    """
    conn = db.initialize_database(db_path)
    try:
        with conn:
            _replace_score_data(conn, {"score_configuration": score_configuration or {}})
            if score_enabled is not None:
                conn.execute(
                    "INSERT INTO app_config(key, value_json, updated_at)"
                    " VALUES ('score.enabled', ?, CURRENT_TIMESTAMP)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    "   value_json = excluded.value_json,"
                    "   updated_at = CURRENT_TIMESTAMP",
                    (_to_json(bool(score_enabled)),),
                )
    finally:
        conn.close()


def load_score_config_only(db_path: str | Path | None = None) -> dict[str, Any]:
    """Load ONLY score.enabled + score_configuration from DB.

    Returns {"score": {"enabled": bool}, "score_configuration": {...}}.
    Does NOT read folders, providers, seerr, system, ui, or any other table.
    Used by score settings handlers that don't need the full config.
    """
    conn = db.initialize_database(db_path)
    try:
        score_row = conn.execute(
            "SELECT value_json FROM app_config WHERE key = 'score.enabled'"
        ).fetchone()
        score_enabled = _from_json(score_row["value_json"], False) if score_row else False

        rule_rows = conn.execute(
            "SELECT category, group_key, value_key, score_value FROM score_rules ORDER BY id"
        ).fetchall()
        profile_rows = conn.execute(
            "SELECT media_type, resolution_key, codec_key, min_gb, max_gb FROM score_size_profiles ORDER BY id"
        ).fetchall()
        return {
            "score": {"enabled": bool(score_enabled)},
            "score_configuration": reconstruct_score_config_from_rows(rule_rows, profile_rows),
        }
    finally:
        conn.close()


def load_phase_affecting_config(
    phase_keys: frozenset[str],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load ONLY the config fields needed to detect scan-phase changes.

    phase_keys is the subset of {"folders", "media_probe", "seerr", "score",
    "recommendations"} that are present in the incoming payload.  Only those
    groups are read from the DB so the caller can compare before/after.
    """
    if not phase_keys:
        return {}
    conn = db.initialize_database(db_path)
    try:
        cfg: dict[str, Any] = {}

        if "folders" in phase_keys:
            rows = conn.execute(
                "SELECT name, media_type, enabled FROM folders ORDER BY id"
            ).fetchall()
            cfg["folders"] = [
                {"name": r["name"], "type": r["media_type"], "enabled": bool(r["enabled"])}
                for r in rows
            ]

        # score.enabled is needed both for "score" and "recommendations" checks
        if "score" in phase_keys or "recommendations" in phase_keys:
            row = conn.execute(
                "SELECT value_json FROM app_config WHERE key = 'score.enabled'"
            ).fetchone()
            cfg["score"] = {"enabled": bool(_from_json(row["value_json"], False) if row else False)}

        if "recommendations" in phase_keys:
            row = conn.execute(
                "SELECT value_json FROM app_config WHERE key = 'recommendations.enabled'"
            ).fetchone()
            cfg["recommendations"] = {"enabled": bool(_from_json(row["value_json"], False) if row else False)}

        if "media_probe" in phase_keys:
            for subkey in ("enabled", "mode"):
                row = conn.execute(
                    "SELECT value_json FROM app_config WHERE key = ?",
                    (f"media_probe.{subkey}",),
                ).fetchone()
                if row:
                    cfg.setdefault("media_probe", {})[subkey] = _from_json(row["value_json"], None)

        if "seerr" in phase_keys:
            for subkey in ("enabled", "url"):
                row = conn.execute(
                    "SELECT value_json FROM app_config WHERE key = ?",
                    (f"seerr.{subkey}",),
                ).fetchone()
                if row:
                    cfg.setdefault("seerr", {})[subkey] = _from_json(row["value_json"], None)

        return cfg
    finally:
        conn.close()


def save_config_patch(
    payload: dict[str, Any],
    db_path: str | Path | None = None,
) -> list[str]:
    """Write ONLY the keys present in payload to their respective tables.

    This is the patch-based alternative to save_config().  Only rows that
    correspond to keys in payload are written; everything else is untouched.

    Returns a sorted list of flat key names that were actually written
    (e.g. ["score_configuration", "ui.theme"]).
    """
    written: list[str] = []
    conn = db.initialize_database(db_path)
    try:
        with conn:
            # Scalar user keys (enable_movies, enable_series, scan, …)
            for key in _APP_CONFIG_USER_KEYS:
                if key in payload:
                    sanitized = _sanitize_value(key, payload[key])
                    if sanitized is not _SKIP:
                        _upsert_app_config(conn, key, sanitized)
                        written.append(key)

            # Flat groups: system, seerr, ui, recommendations, media_probe, score
            for group in _FLAT_CONFIG_GROUPS:
                if group not in payload or not isinstance(payload[group], dict):
                    continue
                group_val = payload[group]
                for subkey, subval in group_val.items():
                    sanitized = _sanitize_value(subkey, subval)
                    if sanitized is _SKIP:
                        continue
                    _upsert_app_config(conn, f"{group}.{subkey}", sanitized)
                    written.append(f"{group}.{subkey}")

            # score_configuration → score tables (separate from "score" flat group)
            if "score_configuration" in payload:
                _replace_score_data(conn, {"score_configuration": payload["score_configuration"]})
                written.append("score_configuration")

            # folders → folders table
            if "folders" in payload:
                _replace_folders(conn, payload)
                written.append("folders")

            # providers_visible → providers.is_ignored
            if "providers_visible" in payload:
                _replace_providers_visibility(conn, payload)
                # Not added to written (excluded from log output per provider_visible fix)

    finally:
        conn.close()

    return sorted(written)


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
    for table in ("app_config", "score_rules", "auth_settings"):
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


_FLAT_CONFIG_GROUPS = frozenset({"system", "seerr", "ui", "recommendations", "media_probe", "score"})


def _export_config(conn: sqlite3.Connection) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    group_flat: dict[str, dict[str, Any]] = {}
    rows = conn.execute("SELECT key, value_json FROM app_config ORDER BY key").fetchall()
    for row in rows:
        key = row["key"]
        prefix, sep, subkey = key.partition(".")
        if sep and prefix in _FLAT_CONFIG_GROUPS:
            group_flat.setdefault(prefix, {})[subkey] = _from_json(row["value_json"], None)
        else:
            cfg[key] = _from_json(row["value_json"], None)
    for group, subkeys in group_flat.items():
        cfg[group] = subkeys

    # Reconstruct folders from dedicated table
    folder_rows = conn.execute(
        "SELECT name, media_type, enabled FROM folders ORDER BY id"
    ).fetchall()
    cfg["folders"] = [
        {"name": r["name"], "type": r["media_type"], "enabled": bool(r["enabled"])}
        for r in folder_rows
    ]

    # Reconstruct providers_visible from providers.is_ignored
    # If any mapped provider is explicitly hidden → return whitelist of visible ones
    # If none are hidden → return None (frontend shows all providers)
    has_hidden = conn.execute(
        "SELECT 1 FROM providers WHERE mapped_name IS NOT NULL AND is_ignored = 1 LIMIT 1"
    ).fetchone() is not None
    if has_hidden:
        visible_rows = conn.execute(
            "SELECT mapped_name FROM providers WHERE is_ignored = 0 AND mapped_name IS NOT NULL ORDER BY mapped_name"
        ).fetchall()
        cfg["providers_visible"] = [r["mapped_name"] for r in visible_rows]
    else:
        cfg["providers_visible"] = None

    rule_rows = conn.execute(
        "SELECT category, group_key, value_key, score_value FROM score_rules ORDER BY id"
    ).fetchall()
    profile_rows = conn.execute(
        "SELECT media_type, resolution_key, codec_key, min_gb, max_gb FROM score_size_profiles ORDER BY id"
    ).fetchall()
    cfg["score_configuration"] = reconstruct_score_config_from_rows(rule_rows, profile_rows)

    # Data came from DB which was already sanitized on write — no deepcopy needed.
    return cfg


# Scalar user-config keys stored directly in app_config (no flat group prefix, no dedicated table).
# runtime_library_document, folders, providers_visible must never appear here.
_APP_CONFIG_USER_KEYS = frozenset({
    "scan",
    "enable_movies",
    "enable_series",
})


def _upsert_app_config(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Insert or update a single app_config row."""
    conn.execute(
        "INSERT INTO app_config(key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)"
        " ON CONFLICT(key) DO UPDATE SET"
        "   value_json = excluded.value_json, updated_at = CURRENT_TIMESTAMP",
        (key, _to_json(value)),
    )


def _replace_app_config(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    # folders and providers_visible go to dedicated tables; score_configuration to score tables.
    _SKIP_KEYS = {"auth", "score_configuration", "folders", "providers_visible"}
    # Wipe only scalar user-config keys — never touch runtime keys (e.g. runtime_library_document).
    incoming_keys = {str(k) for k in config if k not in _SKIP_KEYS and k not in _FLAT_CONFIG_GROUPS}
    managed_keys = tuple(_APP_CONFIG_USER_KEYS | incoming_keys)
    if managed_keys:
        conn.execute(
            f"DELETE FROM app_config WHERE key IN ({','.join('?' * len(managed_keys))})",
            managed_keys,
        )
    # For each flat group present in the incoming config, wipe both any residual blob key
    # and all flat subkeys so the write is always a clean replace.
    for group in _FLAT_CONFIG_GROUPS:
        if group in config:
            conn.execute(
                "DELETE FROM app_config WHERE key = ? OR key LIKE ?",
                (group, f"{group}.%"),
            )
    for key, value in config.items():
        if key in _SKIP_KEYS:
            continue
        if key in _FLAT_CONFIG_GROUPS:
            if isinstance(value, dict):
                for subkey, subval in value.items():
                    sanitized = _sanitize_value(subkey, subval)
                    if sanitized is _SKIP:
                        continue
                    conn.execute(
                        "INSERT INTO app_config(key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                        (f"{key}.{subkey}", _to_json(sanitized)),
                    )
            continue
        sanitized = _sanitize_value(key, value)
        if sanitized is _SKIP:
            continue
        conn.execute(
            "INSERT INTO app_config(key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (str(key), _to_json(sanitized)),
        )


def _replace_folders(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    if "folders" not in config:
        return
    folders = config["folders"]
    if not isinstance(folders, list):
        return
    conn.execute("DELETE FROM folders")
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        name = folder.get("name") or folder.get("path") or ""
        if not isinstance(name, str) or not name.strip():
            continue
        # Support legacy "visible" as fallback for "enabled"; default is enabled.
        enabled_raw = folder.get("enabled")
        if enabled_raw is None:
            enabled_raw = folder.get("visible", True)
        conn.execute(
            "INSERT OR IGNORE INTO folders(name, media_type, enabled) VALUES (?, ?, ?)",
            (name.strip(), folder.get("type"), 1 if enabled_raw else 0),
        )


def _replace_providers_visibility(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    """Update providers.is_ignored based on providers_visible list.

    - Key absent from config → no change (partial save)
    - None or empty list → no change (conservative: treat as "no preference")
    - Non-empty list → set visible providers is_ignored=0, hidden is_ignored=1
    """
    if "providers_visible" not in config:
        return
    pv = config["providers_visible"]
    if not isinstance(pv, list) or not pv:
        return
    visible_names = {str(n) for n in pv if isinstance(n, str) and n}
    if not visible_names:
        return
    placeholders = ",".join("?" * len(visible_names))
    conn.execute(
        f"UPDATE providers SET is_ignored = 0, updated_at = CURRENT_TIMESTAMP"
        f" WHERE mapped_name IS NOT NULL AND mapped_name IN ({placeholders})",
        tuple(visible_names),
    )
    conn.execute(
        f"UPDATE providers SET is_ignored = 1, updated_at = CURRENT_TIMESTAMP"
        f" WHERE mapped_name IS NOT NULL AND mapped_name NOT IN ({placeholders})",
        tuple(visible_names),
    )


def _replace_score_data(conn: sqlite3.Connection, config: dict[str, Any]) -> None:
    score_config = config.get("score_configuration") if isinstance(config.get("score_configuration"), dict) else {}
    conn.execute("DELETE FROM score_rules")
    conn.execute("DELETE FROM score_size_profiles")
    for (category, group_key, value_key, score_value) in flatten_score_to_rules(score_config):
        conn.execute(
            "INSERT INTO score_rules(category, group_key, value_key, score_value) VALUES (?, ?, ?, ?)",
            (category, group_key, value_key, score_value),
        )
    for (media_type, res_key, codec_key, min_gb, max_gb) in flatten_score_to_size_profiles(score_config):
        conn.execute(
            "INSERT INTO score_size_profiles(media_type, resolution_key, codec_key, min_gb, max_gb)"
            " VALUES (?, ?, ?, ?, ?)",
            (media_type, res_key, codec_key, min_gb, max_gb),
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
