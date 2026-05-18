"""Idempotent database seeding from Python defaults.

All seed functions use INSERT OR IGNORE so they never overwrite user data.
Call seed_all() from bootstrap_runtime_database() on every startup.
"""

from __future__ import annotations

import json
import logging
import sqlite3

try:
    from backend.defaults.config_defaults import DEFAULT_CONFIG
    from backend.defaults.provider_defaults import DEFAULT_PROVIDERS, DEFAULT_PROVIDER_LOGOS
    from backend.defaults.recommendation_defaults import DEFAULT_RECOMMENDATION_RULES
    from backend.scoring import (
        DEFAULT_SCORE_CONFIG,
        flatten_score_to_rules,
        flatten_score_to_size_profiles,
    )
except Exception:
    from defaults.config_defaults import DEFAULT_CONFIG  # type: ignore
    from defaults.provider_defaults import DEFAULT_PROVIDERS, DEFAULT_PROVIDER_LOGOS  # type: ignore
    from defaults.recommendation_defaults import DEFAULT_RECOMMENDATION_RULES  # type: ignore
    from scoring import (  # type: ignore
        DEFAULT_SCORE_CONFIG,
        flatten_score_to_rules,
        flatten_score_to_size_profiles,
    )


log = logging.getLogger(__name__)

_CONFIG_FLAT_GROUPS = ("system", "seerr", "ui", "recommendations", "media_probe", "score")
# folders and providers_visible are stored in dedicated tables, not in app_config
_CONFIG_SKIP_KEYS = frozenset({"score_configuration", "auth", "folders", "providers_visible"} | set(_CONFIG_FLAT_GROUPS))


def seed_config(conn: sqlite3.Connection) -> int:
    """Seed default app config keys. INSERT OR IGNORE — never overwrites existing values."""
    rows = 0
    with conn:
        for key, value in DEFAULT_CONFIG.items():
            if key in _CONFIG_SKIP_KEYS:
                continue
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO app_config(key, value_json) VALUES (?, ?)",
                (key, _to_json(value)),
            )
        for group in _CONFIG_FLAT_GROUPS:
            blob = DEFAULT_CONFIG.get(group)
            if isinstance(blob, dict):
                for subkey, subval in blob.items():
                    rows += _insert_count(
                        conn,
                        "INSERT OR IGNORE INTO app_config(key, value_json) VALUES (?, ?)",
                        (f"{group}.{subkey}", _to_json(subval)),
                    )
    return rows


def seed_folders(conn: sqlite3.Connection) -> int:
    """Seed default folders from DEFAULT_CONFIG. INSERT OR IGNORE — never overwrites existing rows."""
    rows = 0
    default_folders = DEFAULT_CONFIG.get("folders", [])
    if not isinstance(default_folders, list):
        return 0
    with conn:
        for folder in default_folders:
            if not isinstance(folder, dict):
                continue
            name = folder.get("name") or folder.get("path") or ""
            if not isinstance(name, str) or not name.strip():
                continue
            enabled_raw = folder.get("enabled")
            if enabled_raw is None:
                enabled_raw = folder.get("visible", True)
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO folders(name, media_type, enabled) VALUES (?, ?, ?)",
                (name.strip(), folder.get("type"), 1 if enabled_raw else 0),
            )
    return rows


def seed_score_data(conn: sqlite3.Connection) -> int:
    """Seed default score rules and size profiles. INSERT OR IGNORE — never overwrites user data."""
    rows = 0
    with conn:
        for (category, group_key, value_key, score_value) in flatten_score_to_rules(DEFAULT_SCORE_CONFIG):
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO score_rules(category, group_key, value_key, score_value)"
                " VALUES (?, ?, ?, ?)",
                (category, group_key, value_key, score_value),
            )
        for (media_type, res_key, codec_key, min_gb, max_gb) in flatten_score_to_size_profiles(DEFAULT_SCORE_CONFIG):
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO score_size_profiles"
                "(media_type, resolution_key, codec_key, min_gb, max_gb) VALUES (?, ?, ?, ?, ?)",
                (media_type, res_key, codec_key, min_gb, max_gb),
            )
    return rows


def seed_providers(conn: sqlite3.Connection) -> int:
    """Seed default provider mappings and logos. INSERT OR IGNORE — never overwrites user customisations."""
    rows = 0
    with conn:
        for raw_name, mapped_name in DEFAULT_PROVIDERS.items():
            is_ignored = 1 if mapped_name is None else 0
            mapped = mapped_name if isinstance(mapped_name, str) else None
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO providers(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                (raw_name, mapped, is_ignored),
            )
        for display_name, logo_path in DEFAULT_PROVIDER_LOGOS.items():
            updated = conn.execute(
                "UPDATE providers SET logo_path = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE mapped_name = ? AND logo_path IS NULL",
                (logo_path, display_name),
            ).rowcount
            if updated > 0:
                rows += updated
                continue
            if conn.execute("SELECT 1 FROM providers WHERE mapped_name = ?", (display_name,)).fetchone():
                continue
            updated = conn.execute(
                "UPDATE providers SET logo_path = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE raw_name = ? AND logo_path IS NULL",
                (logo_path, display_name),
            ).rowcount
            if updated > 0:
                rows += updated
                continue
            if conn.execute("SELECT 1 FROM providers WHERE raw_name = ?", (display_name,)).fetchone():
                continue
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO providers(raw_name, logo_path) VALUES (?, ?)",
                (display_name, logo_path),
            )
    return rows


def seed_recommendation_rules(conn: sqlite3.Connection) -> int:
    """Seed default recommendation rules. INSERT OR IGNORE — never overwrites existing rules."""
    rows = 0
    with conn:
        for rule in DEFAULT_RECOMMENDATION_RULES:
            rule_key = str(rule.get("id") or rule.get("rule_key") or "")
            if not rule_key:
                continue
            conditions = rule.get("conditions")
            msg = rule.get("message") or {}
            action = rule.get("suggested_action") or {}
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO recommendation_rules"
                " (rule_key, rule_type, priority, enabled, dedupe_group, severity,"
                "  conditions_json, message_fr, message_en, suggested_action_fr, suggested_action_en)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule_key,
                    str(rule.get("type") or "") or None,
                    str(rule.get("priority") or "") or None,
                    0 if rule.get("enabled") is False else 1,
                    str(rule.get("dedupe_group") or "") or None,
                    rule.get("severity"),
                    _to_json(conditions) if isinstance(conditions, list) else None,
                    msg.get("fr") or None,
                    msg.get("en") or None,
                    action.get("fr") or None,
                    action.get("en") or None,
                ),
            )
    return rows


def seed_all(conn: sqlite3.Connection, logger: logging.Logger | None = None) -> dict[str, int]:
    """Run all seed functions and return per-category row counts."""
    active_logger = logger or log
    results: dict[str, int] = {}

    n = seed_config(conn)
    results["config"] = n
    active_logger.info("[DB] Seeded config defaults — rows=%s", n)

    n = seed_folders(conn)
    results["folders"] = n
    active_logger.info("[DB] Seeded folders defaults — rows=%s", n)

    n = seed_score_data(conn)
    results["score_data"] = n
    active_logger.info("[DB] Seeded score defaults — rows=%s", n)

    n = seed_providers(conn)
    results["providers"] = n
    active_logger.info("[DB] Seeded provider defaults — rows=%s", n)

    n = seed_recommendation_rules(conn)
    results["recommendation_rules"] = n
    active_logger.info("[DB] Seeded recommendation rules — rows=%s", n)

    return results


def _insert_count(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    before = conn.total_changes
    conn.execute(sql, params)
    return conn.total_changes - before


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
