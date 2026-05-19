"""Runtime accessors for recommendation rules and generated recommendations."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from backend import db, db_export, db_import, runtime_paths
except Exception:
    import db  # type: ignore
    import db_export  # type: ignore
    import db_import  # type: ignore
    import runtime_paths  # type: ignore


log = logging.getLogger(__name__)


def load_recommendation_rules(json_path: str | Path, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load enabled recommendation rules from SQLite only."""

    db_rules = _load_rules_from_db(json_path, db_path)
    if db_rules is not None:
        return db_rules
    return []


def load_recommendations(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Load generated recommendations from SQLite only."""

    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.RECOMMENDATIONS_JSON))
    try:
        if _table_is_empty(conn, "recommendations"):
            if not _is_canonical_json_path(json_path, runtime_paths.RECOMMENDATIONS_JSON):
                db_import.import_recommendations(conn, json_path)
                if _table_is_empty(conn, "recommendations"):
                    return None
                return export_recommendations(conn)
            return None
        return export_recommendations(conn)
    finally:
        conn.close()


def save_recommendations(
    items: list[dict[str, Any]],
    json_path: str | Path,
    db_path: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace generated recommendations in SQLite."""

    ts = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {"generated_at": ts, "version": 1, "items": [item for item in items if isinstance(item, dict)]}
    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.RECOMMENDATIONS_JSON))
    try:
        replace_recommendations(conn, payload["items"])
        if not _is_canonical_json_path(json_path, runtime_paths.RECOMMENDATIONS_JSON):
            _write_json(json_path, payload)
        return payload
    finally:
        conn.close()


def export_recommendations(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT r.id, r.media_id, r.recommendation_type, r.priority, r.rule_id,
               r.message_fr, r.message_en, r.suggested_action_fr, r.suggested_action_en,
               r.created_at, r.updated_at,
               m.title AS media_title, m.year AS media_year, m.media_type
        FROM recommendations r
        LEFT JOIN media m ON m.id = r.media_id
        ORDER BY r.priority, r.recommendation_type, r.id
        """
    ).fetchall()
    items = []
    timestamps = []
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
        ts = row["updated_at"] or row["created_at"]
        if ts:
            timestamps.append(ts)
    return {
        "generated_at": max(timestamps) if timestamps else None,
        "version": 1,
        "items": items,
    }


def replace_recommendations(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    """Replace the generated recommendation set atomically for a scan output.

    Recommendations whose media was deleted between scans have media_id=NULL
    (ON DELETE SET NULL) and are invisible in the UI; they are purged here on
    the next scan. This is intentional, not a leak.
    """

    with conn:
        conn.execute("DELETE FROM recommendations")
        for index, item in enumerate(items):
            if isinstance(item, dict):
                upsert_recommendation(conn, item, index=index)


def upsert_recommendation(conn: sqlite3.Connection, item: dict[str, Any], *, index: int = 0) -> None:
    if not isinstance(item, dict):
        return
    rec_id = str(item.get("id") or f"recommendation:{index}")
    conn.execute(
        """
        INSERT INTO recommendations(
            id, media_id, recommendation_type, priority, rule_id,
            message_fr, message_en, suggested_action_fr, suggested_action_en
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            media_id            = excluded.media_id,
            recommendation_type = excluded.recommendation_type,
            priority            = excluded.priority,
            rule_id             = excluded.rule_id,
            message_fr          = excluded.message_fr,
            message_en          = excluded.message_en,
            suggested_action_fr = excluded.suggested_action_fr,
            suggested_action_en = excluded.suggested_action_en,
            updated_at          = CURRENT_TIMESTAMP
        """,
        _recommendation_params(conn, rec_id, item),
    )


def _load_rules_from_db(json_path: str | Path, db_path: str | Path | None) -> list[dict[str, Any]] | None:
    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.RECOMMENDATIONS_RULES_JSON))
    try:
        payload = db_export.export_recommendation_rules(conn)
    finally:
        conn.close()
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        return None
    return [rule for rule in rules if isinstance(rule, dict) and rule.get("enabled") is not False]


def _table_is_empty(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
    return row is None


def _recommendation_params(conn: sqlite3.Connection, rec_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    media_ref = item.get("media_ref") if isinstance(item.get("media_ref"), dict) else {}
    msg = item.get("message") or {}
    action = item.get("suggested_action") or {}
    return (
        rec_id,
        _existing_media_id(conn, media_ref.get("id")),
        str(item.get("recommendation_type") or "unknown"),
        item.get("priority"),
        item.get("rule_id"),
        msg.get("fr") or None,
        msg.get("en") or None,
        action.get("fr") or None,
        action.get("en") or None,
    )


def _existing_media_id(conn: sqlite3.Connection, value: Any) -> str | None:
    if value in (None, ""):
        return None
    media_id = str(value)
    row = conn.execute("SELECT id FROM media WHERE id = ? LIMIT 1", (media_id,)).fetchone()
    return media_id if row else None


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output)




def _effective_db_path(
    json_path: str | Path,
    db_path: str | Path | None,
    canonical_path: Path,
) -> str | Path | None:
    if db_path is not None:
        return db_path
    path = Path(json_path)
    if path == canonical_path:
        return None
    root = path.parent.parent if path.parent.name == "conf" else path.parent
    return root / "mymedialibrary.db"


def _is_canonical_json_path(json_path: str | Path, canonical_path: Path) -> bool:
    return Path(json_path) == canonical_path
