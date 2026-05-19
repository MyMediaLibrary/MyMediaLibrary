"""SQLite to compatibility JSON export helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

try:
    from backend.repositories import media_repository as _media_repository
except Exception:
    try:
        from repositories import media_repository as _media_repository  # type: ignore
    except Exception:
        _media_repository = None  # type: ignore


def export_providers_logo(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {display_name: logo_path} keyed by mapped_name (or raw_name if no mapping)."""
    rows = conn.execute(
        """
        SELECT COALESCE(mapped_name, raw_name) AS display_name, logo_path
        FROM providers
        WHERE logo_path IS NOT NULL
        ORDER BY display_name
        """
    ).fetchall()
    return {row["display_name"]: row["logo_path"] for row in rows}


def export_providers_mapping(conn: sqlite3.Connection) -> dict[str, str | None]:
    """Return {raw_name: mapped_name|None} for explicitly mapped/ignored providers only."""
    rows = conn.execute(
        """
        SELECT raw_name, mapped_name, is_ignored FROM providers
        WHERE mapped_name IS NOT NULL OR is_ignored = 1
        ORDER BY raw_name
        """
    ).fetchall()
    return {
        row["raw_name"]: None if row["is_ignored"] else row["mapped_name"]
        for row in rows
    }


def export_recommendation_rules(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT rule_key, enabled, rule_type, priority, dedupe_group, severity,
               conditions_json, message_fr, message_en, suggested_action_fr, suggested_action_en
        FROM recommendation_rules
        ORDER BY id
        """
    ).fetchall()
    rules = []
    for row in rows:
        rules.append({
            "id": row["rule_key"],
            "enabled": bool(row["enabled"]),
            "type": row["rule_type"],
            "priority": row["priority"],
            "dedupe_group": row["dedupe_group"],
            "severity": row["severity"],
            "conditions": _from_json(row["conditions_json"], []),
            "message": {"fr": row["message_fr"], "en": row["message_en"]},
            "suggested_action": {"fr": row["suggested_action_fr"], "en": row["suggested_action_en"]},
        })
    return {"version": 1, "rules": rules}


_EXPORT_FLAT_GROUPS = frozenset({"system", "seerr", "ui", "recommendations", "media_probe", "score"})
_EXPORT_SKIP_KEYS = frozenset({"runtime_library_document", "folders", "providers_visible"})


def export_config(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT key, value_json FROM app_config ORDER BY key").fetchall()
    result: dict[str, Any] = {}
    for row in rows:
        key = row["key"]
        if key in _EXPORT_SKIP_KEYS:
            continue
        prefix, sep, subkey = key.partition(".")
        if sep and prefix in _EXPORT_FLAT_GROUPS:
            result.setdefault(prefix, {})[subkey] = _from_json(row["value_json"], None)
        else:
            result[key] = _from_json(row["value_json"], None)

    # Reconstruct folders from dedicated table
    folder_rows = conn.execute("SELECT name, media_type, enabled FROM folders ORDER BY id").fetchall()
    result["folders"] = [
        {"name": r["name"], "type": r["media_type"], "enabled": bool(r["enabled"])}
        for r in folder_rows
    ]

    # Reconstruct providers_visible from providers.is_ignored
    has_hidden = conn.execute(
        "SELECT 1 FROM providers WHERE mapped_name IS NOT NULL AND is_ignored = 1 LIMIT 1"
    ).fetchone() is not None
    if has_hidden:
        visible_rows = conn.execute(
            "SELECT mapped_name FROM providers WHERE is_ignored = 0 AND mapped_name IS NOT NULL ORDER BY mapped_name"
        ).fetchall()
        result["providers_visible"] = [r["mapped_name"] for r in visible_rows]
    else:
        result["providers_visible"] = []

    return result


def export_recommendations(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT r.id, r.media_id, r.recommendation_type, r.priority, r.rule_id,
               r.message_fr, r.message_en, r.suggested_action_fr, r.suggested_action_en,
               m.title AS media_title, m.year AS media_year, m.media_type
        FROM recommendations r
        LEFT JOIN media m ON m.id = r.media_id
        ORDER BY r.priority, r.recommendation_type, r.id
        """
    ).fetchall()
    items = []
    for row in rows:
        item: dict[str, Any] = {
            "id": row["id"],
            "recommendation_type": row["recommendation_type"],
            "priority": row["priority"],
            "rule_id": row["rule_id"],
            "message": {"fr": row["message_fr"], "en": row["message_en"]},
            "suggested_action": {"fr": row["suggested_action_fr"], "en": row["suggested_action_en"]},
        }
        if row["media_id"]:
            item["media_ref"] = {
                "id": row["media_id"],
                "type": row["media_type"] or "media",
            }
            if row["media_title"] or row["media_year"] is not None:
                item["display"] = {
                    "title": row["media_title"],
                    "year": row["media_year"],
                }
        items.append(item)
    return {"version": 1, "items": items}


def export_library(conn: sqlite3.Connection, availability: str = "available") -> dict[str, Any]:
    if _media_repository is not None:
        doc = _media_repository.export_library(conn, availability=availability)
        return {"total_items": doc["total_items"], "items": doc["items"]}
    # Fallback: minimal column-based reconstruction (no seasons/providers)
    if availability == "available":
        where = " WHERE is_available = 1"
    elif availability == "absent":
        where = " WHERE is_available = 0"
    else:
        where = ""
    rows = conn.execute(f"SELECT id, is_available FROM media{where} ORDER BY title, id").fetchall()
    items = [{"id": row["id"], "is_available": bool(row["is_available"])} for row in rows]
    return {"total_items": len(items), "items": items}


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
