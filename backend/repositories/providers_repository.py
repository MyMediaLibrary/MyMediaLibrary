"""SQLite runtime accessors for provider mappings and logos."""

from __future__ import annotations

import json
import logging
import sqlite3
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


def load_provider_mappings(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, str | None]:
    """Load provider mappings from SQLite only."""

    db_mapping = _load_from_db(
        db_path,
        json_path=json_path,
        canonical_path=runtime_paths.PROVIDERS_MAPPING_JSON,
        table_name="provider_mappings",
        exporter=db_export.export_providers_mapping,
        log_label="provider mappings",
    )
    if db_mapping is not None:
        return db_mapping
    return {}


def save_provider_mappings(
    mapping: dict[str, Any],
    json_path: str | Path,
    db_path: str | Path | None = None,
) -> None:
    """Persist provider mappings to SQLite."""

    normalized = _normalize_mapping(mapping)
    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.PROVIDERS_MAPPING_JSON))
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
        if not _is_canonical_json_path(json_path, runtime_paths.PROVIDERS_MAPPING_JSON):
            _write_json_object(json_path, normalized)
    finally:
        conn.close()


def load_provider_logos(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, str]:
    """Load provider logos from SQLite only."""

    db_logos = _load_from_db(
        db_path,
        json_path=json_path,
        canonical_path=runtime_paths.PROVIDERS_LOGO_JSON,
        table_name="provider_logos",
        exporter=db_export.export_providers_logo,
        log_label="provider logos",
    )
    if db_logos is not None:
        return db_logos
    return {}


def _load_from_db(
    db_path: str | Path | None,
    *,
    json_path: str | Path,
    canonical_path: Path,
    table_name: str,
    exporter,
    log_label: str,
):
    conn = db.initialize_database(_effective_db_path(json_path, db_path, canonical_path))
    try:
        if _table_is_empty(conn, table_name):
            if not _is_canonical_json_path(json_path, canonical_path):
                if table_name == "provider_mappings":
                    db_import.import_providers_mapping(conn, json_path)
                elif table_name == "provider_logos":
                    db_import.import_providers_logo(conn, json_path)
                if _table_is_empty(conn, table_name):
                    return None
            else:
                return None
        return exporter(conn)
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


def _write_json_object(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    return root / "data" / "mymedialibrary.db"


def _is_canonical_json_path(json_path: str | Path, canonical_path: Path) -> bool:
    return Path(json_path) == canonical_path
