"""SQLite-backed runtime inventory repository."""

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


def load_inventory(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Load inventory from SQLite, importing JSON once when the table is empty."""

    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[inventory] SQLite unavailable, falling back to JSON: %s", exc)
        return None
    try:
        if _table_is_empty(conn):
            imported = db_import.import_library_inventory(conn, json_path)
            if not imported and _table_is_empty(conn):
                return None
        return export_inventory(conn)
    except Exception as exc:
        log.warning("[inventory] Could not load inventory from SQLite: %s", exc)
        return None
    finally:
        conn.close()


def save_inventory(document: dict[str, Any], json_path: str | Path, db_path: str | Path | None = None) -> None:
    """Persist inventory to SQLite and JSON compatibility output."""

    payload = document if isinstance(document, dict) else {"version": 1, "items": []}
    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.warning("[inventory] Could not open SQLite inventory store: %s", exc)
        _write_json(json_path, payload)
        return
    try:
        with conn:
            for item in (payload.get("items") if isinstance(payload, dict) else []) or []:
                if isinstance(item, dict):
                    upsert_item(conn, item)
        _write_json(json_path, payload)
    finally:
        conn.close()


def export_inventory(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT data_json FROM inventory_items ORDER BY title, id").fetchall()
    items = [_from_json(row["data_json"], {}) for row in rows]
    return {"version": 1, "items": [item for item in items if isinstance(item, dict)]}


def upsert_item(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    inventory_id = _item_id(item)
    if not inventory_id:
        return
    existing = conn.execute(
        "SELECT first_seen_at FROM inventory_items WHERE id = ? OR inventory_key = ? LIMIT 1",
        (inventory_id, inventory_id),
    ).fetchone()
    item_copy = copy.deepcopy(item)
    if existing and existing["first_seen_at"]:
        item_copy["first_seen_at"] = existing["first_seen_at"]
    conn.execute(
        """
        INSERT INTO inventory_items(
            id, media_id, inventory_key, media_type, title, category, folder, path,
            first_seen_at, last_seen_at, last_checked_at, missing_since, status, data_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            media_id = excluded.media_id,
            inventory_key = excluded.inventory_key,
            media_type = excluded.media_type,
            title = excluded.title,
            category = excluded.category,
            folder = excluded.folder,
            path = excluded.path,
            first_seen_at = COALESCE(inventory_items.first_seen_at, excluded.first_seen_at),
            last_seen_at = excluded.last_seen_at,
            last_checked_at = excluded.last_checked_at,
            missing_since = excluded.missing_since,
            status = excluded.status,
            data_json = excluded.data_json
        """,
        _item_params(inventory_id, item_copy),
    )


def mark_present(conn: sqlite3.Connection, inventory_key: str, *, seen_at: str, data: dict[str, Any] | None = None) -> None:
    item = copy.deepcopy(data or {})
    item["id"] = inventory_key
    item["status"] = "present"
    item.setdefault("first_seen_at", seen_at)
    item["last_seen_at"] = seen_at
    item["last_checked_at"] = seen_at
    item["missing_since"] = None
    upsert_item(conn, item)


def mark_missing(conn: sqlite3.Connection, inventory_key: str, *, checked_at: str) -> None:
    row = conn.execute("SELECT data_json, missing_since FROM inventory_items WHERE inventory_key = ?", (inventory_key,)).fetchone()
    item = _from_json(row["data_json"], {}) if row else {"id": inventory_key}
    if not isinstance(item, dict):
        item = {"id": inventory_key}
    item["status"] = "missing"
    item["last_checked_at"] = checked_at
    item["missing_since"] = row["missing_since"] if row and row["missing_since"] else checked_at
    upsert_item(conn, item)


def _table_is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM inventory_items LIMIT 1").fetchone() is None


def _item_id(item: dict[str, Any]) -> str:
    value = item.get("id") or item.get("inventory_key") or item.get("path") or item.get("root_folder_path")
    return str(value) if value else ""


def _item_params(inventory_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        inventory_id,
        item.get("media_id"),
        inventory_id,
        item.get("media_type"),
        item.get("title"),
        item.get("category"),
        item.get("root_folder_name") or item.get("folder") or _folder_from_id(inventory_id),
        item.get("root_folder_path") or item.get("path"),
        item.get("first_seen_at"),
        item.get("last_seen_at"),
        item.get("last_checked_at"),
        item.get("missing_since"),
        item.get("status"),
        _to_json(item),
    )


def _folder_from_id(inventory_id: str) -> str | None:
    parts = inventory_id.split(":", 2)
    return parts[2] if len(parts) == 3 else None


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
