"""SQLite runtime accessors for the unified providers table."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

try:
    from backend import db, db_export, runtime_paths
except Exception:
    import db  # type: ignore
    import db_export  # type: ignore
    import runtime_paths  # type: ignore


log = logging.getLogger(__name__)


def load_provider_mappings(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, str | None]:
    """Return {raw_name: mapped_name|None} from the unified providers table."""

    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.PROVIDERS_MAPPING_JSON))
    try:
        return db_export.export_providers_mapping(conn)
    finally:
        conn.close()


def save_provider_mappings(
    mapping: dict[str, Any],
    json_path: str | Path,
    db_path: str | Path | None = None,
) -> None:
    """Persist provider mappings into the unified providers table."""

    normalized = _normalize_mapping(mapping)
    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.PROVIDERS_MAPPING_JSON))
    try:
        with conn:
            for raw_name, mapped_name in normalized.items():
                conn.execute(
                    """
                    INSERT INTO providers(raw_name, mapped_name, is_ignored)
                    VALUES (?, ?, ?)
                    ON CONFLICT(raw_name) DO UPDATE SET
                        mapped_name = excluded.mapped_name,
                        is_ignored  = excluded.is_ignored,
                        updated_at  = CURRENT_TIMESTAMP
                    """,
                    (raw_name, mapped_name, 1 if mapped_name is None else 0),
                )
    finally:
        conn.close()


def load_provider_logos(json_path: str | Path, db_path: str | Path | None = None) -> dict[str, str]:
    """Return {display_name: logo_path} from the unified providers table."""

    conn = db.initialize_database(_effective_db_path(json_path, db_path, runtime_paths.PROVIDERS_LOGO_JSON))
    try:
        return db_export.export_providers_logo(conn)
    finally:
        conn.close()


def _normalize_mapping(mapping: dict[str, Any]) -> dict[str, str | None]:
    normalized: dict[str, str | None] = {}
    for raw_name, mapped_name in (mapping or {}).items():
        if not isinstance(raw_name, str) or not raw_name:
            continue
        normalized[raw_name] = mapped_name if isinstance(mapped_name, str) else None
    return normalized


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


