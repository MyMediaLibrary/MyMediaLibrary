"""SQLite to compatibility JSON export helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


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
        "SELECT rule_json FROM recommendation_rules ORDER BY id"
    ).fetchall()
    return {"version": 1, "rules": [_from_json(row["rule_json"], {}) for row in rows]}


def export_config(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT key, value_json FROM app_config ORDER BY key").fetchall()
    return {row["key"]: _from_json(row["value_json"], None) for row in rows}


def export_media_probe_cache(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT file_path, size, mtime, normalized_json
        FROM ffprobe_cache
        ORDER BY file_path
        """
    ).fetchall()
    return {
        "version": 1,
        "files": {
            row["file_path"]: {
                "path": row["file_path"],
                "size_b": row["size"],
                "mtime": row["mtime"],
                "probe": _from_json(row["normalized_json"], {}),
            }
            for row in rows
        },
    }


def export_recommendations(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT details_json FROM recommendations ORDER BY id").fetchall()
    return {"version": 1, "items": [_from_json(row["details_json"], {}) for row in rows]}


def export_library(conn: sqlite3.Connection, availability: str = "available") -> dict[str, Any]:
    if availability == "available":
        where = " WHERE is_available = 1"
    elif availability == "absent":
        where = " WHERE is_available = 0"
    else:
        where = ""
    rows = conn.execute(f"SELECT data_json, is_available FROM media{where} ORDER BY title, id").fetchall()
    items = []
    for row in rows:
        item = _from_json(row["data_json"], {})
        if isinstance(item, dict):
            item["is_available"] = bool(row["is_available"])
            items.append(item)
    return {"total_items": len(items), "items": items}


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
