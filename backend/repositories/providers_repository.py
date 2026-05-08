"""Runtime accessors for provider mappings and logos.

The transition is intentionally conservative: SQLite is preferred when it has
data, JSON remains the compatibility format, and database failures fall back to
the existing files.
"""

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


def load_provider_mappings(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, str | None]:
    """Load provider mappings from SQLite first, importing JSON if DB is empty."""

    db_mapping = _load_from_db(
        db_path,
        table_name="provider_mappings",
        importer=lambda conn: db_import.import_providers_mapping(conn, json_path),
        exporter=db_export.export_providers_mapping,
        log_label="provider mappings",
    )
    if db_mapping is not None:
        return db_mapping
    return _read_json_object(json_path)


def save_provider_mappings(
    mapping: dict[str, Any],
    json_path: str | Path,
    db_path: str | Path | None = None,
) -> None:
    """Persist provider mappings to JSON compatibility output and SQLite."""

    normalized = _normalize_mapping(mapping)
    _write_json_object(json_path, normalized)
    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.warning("[providers] Could not open SQLite provider mappings store: %s", exc)
        return
    try:
        with conn:
            for raw_name, mapped_name in normalized.items():
                conn.execute(
                    """
                    INSERT INTO provider_mappings(raw_name, mapped_name, is_ignored, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(raw_name) DO UPDATE SET
                        mapped_name = excluded.mapped_name,
                        is_ignored = excluded.is_ignored,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (raw_name, mapped_name, 1 if mapped_name is None else 0),
                )
    finally:
        conn.close()


def load_provider_logos(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, str]:
    """Load provider logos from SQLite first, importing JSON if DB is empty."""

    db_logos = _load_from_db(
        db_path,
        table_name="provider_logos",
        importer=lambda conn: db_import.import_providers_logo(conn, json_path),
        exporter=db_export.export_providers_logo,
        log_label="provider logos",
    )
    if db_logos is not None:
        return db_logos
    return {key: value for key, value in _read_json_object(json_path).items() if isinstance(value, str)}


def _load_from_db(
    db_path: str | Path | None,
    *,
    table_name: str,
    importer,
    exporter,
    log_label: str,
):
    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[providers] SQLite unavailable for %s, falling back to JSON: %s", log_label, exc)
        return None
    try:
        if _table_is_empty(conn, table_name):
            imported = importer(conn)
            if not imported and _table_is_empty(conn, table_name):
                return None
        return exporter(conn)
    except Exception as exc:
        log.warning("[providers] Could not load %s from SQLite: %s", log_label, exc)
        return None
    finally:
        conn.close()


def _table_is_empty(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
    return row is None


def _normalize_mapping(mapping: dict[str, Any]) -> dict[str, str | None]:
    normalized: dict[str, str | None] = {}
    for raw_name, mapped_name in (mapping or {}).items():
        if not isinstance(raw_name, str) or not raw_name:
            continue
        normalized[raw_name] = mapped_name if isinstance(mapped_name, str) else None
    return normalized


def _read_json_object(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[providers] Could not read JSON fallback %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_object(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
