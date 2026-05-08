"""SQLite to compatibility JSON export helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def export_providers_logo(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT provider_name, logo_path FROM provider_logos ORDER BY provider_name"
    ).fetchall()
    return {row["provider_name"]: row["logo_path"] for row in rows if row["logo_path"] is not None}


def export_providers_mapping(conn: sqlite3.Connection) -> dict[str, str | None]:
    rows = conn.execute(
        "SELECT raw_name, mapped_name, is_ignored FROM provider_mappings ORDER BY raw_name"
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


def export_library_inventory(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT data_json FROM inventory_items ORDER BY id").fetchall()
    return {"version": 1, "items": [_from_json(row["data_json"], {}) for row in rows]}


def export_recommendations(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT details_json FROM recommendations ORDER BY id").fetchall()
    return {"version": 1, "items": [_from_json(row["details_json"], {}) for row in rows]}


def export_library(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT data_json FROM media ORDER BY title, id").fetchall()
    items = [_from_json(row["data_json"], {}) for row in rows]
    return {"total_items": len(items), "items": items}


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
