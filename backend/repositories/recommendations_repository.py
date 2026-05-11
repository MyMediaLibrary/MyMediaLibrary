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
        SELECT details_json, created_at, updated_at
        FROM recommendations
        ORDER BY priority, recommendation_type, id
        """
    ).fetchall()
    items = [_from_json(row["details_json"], {}) for row in rows]
    timestamps = [
        row["updated_at"] or row["created_at"]
        for row in rows
        if row["updated_at"] or row["created_at"]
    ]
    return {
        "generated_at": max(timestamps) if timestamps else None,
        "version": 1,
        "items": [item for item in items if isinstance(item, dict)],
    }


def replace_recommendations(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    """Replace the generated recommendation set atomically for a scan output."""

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
            id, media_id, recommendation_type, priority, title, reason, rule_id,
            dedupe_group, severity, message_json, suggested_action_json, details_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            media_id = excluded.media_id,
            recommendation_type = excluded.recommendation_type,
            priority = excluded.priority,
            title = excluded.title,
            reason = excluded.reason,
            rule_id = excluded.rule_id,
            dedupe_group = excluded.dedupe_group,
            severity = excluded.severity,
            message_json = excluded.message_json,
            suggested_action_json = excluded.suggested_action_json,
            details_json = excluded.details_json,
            updated_at = CURRENT_TIMESTAMP
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
    display = item.get("display") if isinstance(item.get("display"), dict) else {}
    return (
        rec_id,
        _existing_media_id(conn, media_ref.get("id")),
        str(item.get("recommendation_type") or "unknown"),
        item.get("priority"),
        display.get("title") or item.get("title") or rec_id,
        item.get("reason"),
        item.get("rule_id"),
        item.get("dedupe_group"),
        _as_int(item.get("severity")),
        _to_json(item.get("message") or {}),
        _to_json(item.get("suggested_action") or {}),
        _to_json(item),
    )


def _existing_media_id(conn: sqlite3.Connection, value: Any) -> str | None:
    if value in (None, ""):
        return None
    media_id = str(value)
    row = conn.execute("SELECT id FROM media WHERE id = ? LIMIT 1", (media_id,)).fetchone()
    return media_id if row else None


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output)


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


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
