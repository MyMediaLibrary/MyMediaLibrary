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
except Exception:
    from defaults.config_defaults import DEFAULT_CONFIG  # type: ignore
    from defaults.provider_defaults import DEFAULT_PROVIDERS, DEFAULT_PROVIDER_LOGOS  # type: ignore
    from defaults.recommendation_defaults import DEFAULT_RECOMMENDATION_RULES  # type: ignore


log = logging.getLogger(__name__)

_CONFIG_FLAT_GROUPS = ("system", "seerr", "ui", "recommendations", "media_probe")
_CONFIG_SKIP_KEYS = frozenset({"score", "score_configuration", "auth"} | set(_CONFIG_FLAT_GROUPS))


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
        score = DEFAULT_CONFIG.get("score", {})
        rows += _insert_count(
            conn,
            "INSERT OR IGNORE INTO score_settings(id, enabled, configuration_json) VALUES (?, ?, ?)",
            ("default", 1 if score.get("enabled") else 0, "{}"),
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
