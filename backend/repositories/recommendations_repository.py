"""Runtime accessors for recommendation rules."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

try:
    from backend import db, db_export, db_import
except Exception:
    import db  # type: ignore
    import db_export  # type: ignore
    import db_import  # type: ignore


log = logging.getLogger(__name__)


def load_recommendation_rules(json_path: str | Path, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load enabled recommendation rules from SQLite first, with JSON fallback."""

    db_rules = _load_rules_from_db(json_path, db_path)
    if db_rules is not None:
        return db_rules
    return _load_enabled_json_rules(json_path)


def _load_rules_from_db(json_path: str | Path, db_path: str | Path | None) -> list[dict[str, Any]] | None:
    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[recommendations] SQLite unavailable for rules, falling back to JSON: %s", exc)
        return None
    try:
        if _table_is_empty(conn, "recommendation_rules"):
            imported = db_import.import_recommendation_rules(conn, json_path)
            if not imported and _table_is_empty(conn, "recommendation_rules"):
                return None
        payload = db_export.export_recommendation_rules(conn)
    except Exception as exc:
        log.warning("[recommendations] Could not load rules from SQLite: %s", exc)
        return None
    finally:
        conn.close()
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        return None
    return [rule for rule in rules if isinstance(rule, dict) and rule.get("enabled") is not False]


def _table_is_empty(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
    return row is None


def _load_enabled_json_rules(path: str | Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[recommendations] Could not read rules JSON fallback %s: %s", path, exc)
        return []
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict) and rule.get("enabled") is not False]
