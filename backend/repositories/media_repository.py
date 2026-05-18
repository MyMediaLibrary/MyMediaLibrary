"""SQLite-backed runtime media library repository."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from backend import db, db_import, runtime_paths
except Exception:
    import db  # type: ignore
    import db_import  # type: ignore
    import runtime_paths  # type: ignore


log = logging.getLogger(__name__)

_LIBRARY_DOCUMENT_KEY = "runtime_library_document"


def load_library(json_path: str | Path, db_path: str | Path | None = None, availability: str = "available") -> dict[str, Any] | None:
    """Load the media library from SQLite only.

    Returns None when media table is empty and no valid JSON import source is available.
    This signals "no library yet" (fresh install or after full reset).
    """

    conn = db.initialize_database(_effective_db_path(json_path, db_path))
    try:
        if _table_is_empty(conn, "media"):
            if _is_canonical_json_path(json_path):
                return None
            payload = _read_library_json(json_path)
            if payload is None:
                return None
            _save_library_payload(conn, payload, replace=False)
        return export_library(conn, availability=availability)
    finally:
        conn.close()


def save_library(
    document: dict[str, Any],
    json_path: str | Path,
    db_path: str | Path | None = None,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Persist the current library document to SQLite."""

    payload = _normalize_library_document(document)
    conn = db.initialize_database(_effective_db_path(json_path, db_path))
    try:
        _save_library_payload(conn, payload, replace=replace)
        if not _is_canonical_json_path(json_path):
            _write_json(json_path, payload)
        return payload
    finally:
        conn.close()


def import_library_if_empty(json_path: str | Path, db_path: str | Path | None = None) -> int:
    try:
        conn = db.initialize_database(_effective_db_path(json_path, db_path))
    except Exception as exc:
        log.debug("[library] SQLite unavailable for import: %s", exc)
        return 0
    try:
        if not _table_is_empty(conn, "media"):
            return 0
        payload = _read_library_json(json_path)
        if payload is None:
            return db_import.import_library(conn, json_path)
        _save_library_payload(conn, payload, replace=False)
        return len(payload.get("items") or [])
    finally:
        conn.close()


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
    return _normalize_library_document({
        "scanned_at": None,
        "library_path": None,
        "total_items": len(items),
        "categories": sorted({item.get("category") for item in items if item.get("category")}),
        "items": items,
    })


def replace_library(conn: sqlite3.Connection, document: dict[str, Any]) -> None:
    _save_library_payload(conn, _normalize_library_document(document), replace=True)


def clear_library_snapshot(conn: sqlite3.Connection) -> None:
    """Remove the runtime library snapshot from app_config (called during full reset)."""
    conn.execute("DELETE FROM app_config WHERE key = ?", (_LIBRARY_DOCUMENT_KEY,))


def mark_media_unavailable(
    json_path: str | Path,
    scanned_ids: set[str],
    category: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Mark media absent from scanned_ids as unavailable (is_available=0).

    Returns the number of rows updated.  When scanned_ids is empty and no category
    is given, does nothing as a safety guard against marking everything unavailable
    on scan errors.  last_seen_at is intentionally NOT updated — it preserves the
    timestamp of the last time the media was actually found on disk.
    """
    if not scanned_ids and category is None:
        return 0
    now = datetime.now().isoformat()
    conn = db.initialize_database(_effective_db_path(json_path, db_path))
    try:
        with conn:
            return _mark_media_unavailable(conn, scanned_ids, category, now)
    finally:
        conn.close()


def _mark_media_unavailable(
    conn: sqlite3.Connection,
    scanned_ids: set[str],
    category: str | None,
    now: str,
) -> int:
    ids = list(scanned_ids)
    if category is not None:
        if ids:
            placeholders = ",".join("?" * len(ids))
            sql = (
                f"UPDATE media SET is_available = 0, last_scanned_at = ?"
                f" WHERE category = ? AND id NOT IN ({placeholders}) AND is_available = 1"
            )
            params: list = [now, category] + ids
        else:
            sql = "UPDATE media SET is_available = 0, last_scanned_at = ? WHERE category = ? AND is_available = 1"
            params = [now, category]
    else:
        placeholders = ",".join("?" * len(ids))
        sql = (
            f"UPDATE media SET is_available = 0, last_scanned_at = ?"
            f" WHERE id NOT IN ({placeholders}) AND is_available = 1"
        )
        params = [now] + ids
    cursor = conn.execute(sql, params)
    return cursor.rowcount


def upsert_media_item(conn: sqlite3.Connection, item: dict[str, Any]) -> int:
    if not isinstance(item, dict):
        return 0
    media_id = str(item.get("id") or item.get("path") or "")
    new_filename = _to_json(item["filename"]) if item.get("filename") is not None else None
    # Read existing filename before upsert so we can track history on change
    prev_filename: str | None = None
    if new_filename is not None and media_id:
        row = conn.execute("SELECT filename FROM media WHERE id = ?", (media_id,)).fetchone()
        if row:
            prev_filename = row["filename"]
    written = db_import.upsert_library_item(conn, item, overwrite=True)
    if written:
        _sync_media_providers(conn, media_id, item.get("providers"))
        _sync_media_children(conn, media_id, item)
        if prev_filename is not None and prev_filename != new_filename:
            _append_to_filename_history(conn, media_id, prev_filename)
    return written


def _append_to_filename_history(conn: sqlite3.Connection, media_id: str, old_filename_json: str) -> None:
    row = conn.execute("SELECT filename_history FROM media WHERE id = ?", (media_id,)).fetchone()
    if not row:
        return
    history = _from_json(row["filename_history"], [])
    if not isinstance(history, list):
        history = []
    if old_filename_json not in history:
        history.append(old_filename_json)
    conn.execute("UPDATE media SET filename_history = ? WHERE id = ?", (_to_json(history), media_id))


def _save_library_payload(conn: sqlite3.Connection, document: dict[str, Any], *, replace: bool) -> None:
    items = document.get("items") if isinstance(document.get("items"), list) else []
    with conn:
        if replace:
            conn.execute("DELETE FROM media")
        for item in items:
            if isinstance(item, dict):
                upsert_media_item(conn, item)


def _sync_media_providers(conn: sqlite3.Connection, media_id: str, providers: Any) -> None:
    if not media_id:
        return
    names = []
    seen = set()
    for provider in providers or []:
        name = provider if isinstance(provider, str) else None
        if isinstance(provider, dict):
            name = provider.get("name") or provider.get("raw_name") or provider.get("provider_name")
        if not isinstance(name, str) or not name.strip():
            continue
        cleaned = name.strip()
        if cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        names.append(cleaned)
    conn.execute("DELETE FROM media_providers WHERE media_id = ?", (media_id,))
    for name in names:
        conn.execute(
            "INSERT OR IGNORE INTO providers(raw_name) VALUES (?)",
            (name,),
        )
        provider_id = conn.execute("SELECT id FROM providers WHERE raw_name = ?", (name,)).fetchone()
        if provider_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO media_providers(media_id, provider_id) VALUES (?, ?)",
                (media_id, provider_id["id"]),
            )


def _sync_media_children(conn: sqlite3.Connection, media_id: str, item: dict[str, Any]) -> None:
    if not media_id:
        return
    seasons = item.get("seasons") if isinstance(item.get("seasons"), list) else []
    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_number = _as_int(season.get("season") or season.get("season_number"))
        if season_number is None:
            continue
        conn.execute(
            """
            INSERT INTO seasons(
                media_id, season_number, title, episodes_count, size_total, runtime_min,
                runtime_min_avg, quality_score, width, height, resolution, video_codec,
                audio_codec, audio_channels, audio_languages_json, audio_language_group,
                subtitle_languages_json, container
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_id, season_number) DO UPDATE SET
                title = excluded.title,
                episodes_count = excluded.episodes_count,
                size_total = excluded.size_total,
                runtime_min = excluded.runtime_min,
                runtime_min_avg = excluded.runtime_min_avg,
                quality_score = excluded.quality_score,
                width = excluded.width,
                height = excluded.height,
                resolution = excluded.resolution,
                video_codec = excluded.video_codec,
                audio_codec = excluded.audio_codec,
                audio_channels = excluded.audio_channels,
                audio_languages_json = excluded.audio_languages_json,
                audio_language_group = excluded.audio_language_group,
                subtitle_languages_json = excluded.subtitle_languages_json,
                container = excluded.container,
                updated_at = CURRENT_TIMESTAMP
            """,
            _season_params(media_id, season_number, season),
        )


def _season_params(media_id: str, season_number: int, season: dict[str, Any]) -> tuple[Any, ...]:
    quality = season.get("quality") if isinstance(season.get("quality"), dict) else {}
    return (
        media_id,
        season_number,
        season.get("title") or season.get("name"),
        _as_int(season.get("episodes_found") or season.get("episodes_count")),
        _as_int(season.get("size_b") or season.get("size_total")),
        _as_int(season.get("runtime_min")),
        _as_int(season.get("runtime_min_avg")),
        _as_float(quality.get("score") if isinstance(quality, dict) else season.get("quality_score")),
        _as_int(season.get("width")),
        _as_int(season.get("height")),
        season.get("resolution"),
        season.get("codec") or season.get("video_codec"),
        season.get("audio_codec"),
        season.get("audio_channels"),
        _to_json(season.get("audio_languages") or []),
        season.get("audio_language_group") or season.get("audio_languages_simple"),
        _to_json(season.get("subtitle_languages") or []),
        season.get("container"),
    )


def _load_document_snapshot(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT value_json FROM app_config WHERE key = ?", (_LIBRARY_DOCUMENT_KEY,)).fetchone()
    payload = _from_json(row["value_json"], None) if row else None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("items"), list):
        return None
    return payload


def _store_document_snapshot(conn: sqlite3.Connection, document: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO app_config(key, value_json, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (_LIBRARY_DOCUMENT_KEY, _to_json(document)),
    )


def _normalize_library_document(document: dict[str, Any]) -> dict[str, Any]:
    payload = dict(document) if isinstance(document, dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    payload["items"] = [item for item in items if isinstance(item, dict)]
    payload["total_items"] = len(payload["items"])
    payload.setdefault("categories", sorted({item.get("category") for item in payload["items"] if item.get("category")}))
    payload.setdefault("scanned_at", datetime.now().isoformat())
    return payload


def _read_library_json(path: str | Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        log.info("[library] Could not read JSON import source %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("items"), list):
        return None
    return _normalize_library_document(payload)


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _table_is_empty(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone() is None


def _effective_db_path(json_path: str | Path, db_path: str | Path | None) -> str | Path | None:
    if db_path is not None:
        return db_path
    path = Path(json_path)
    if path == runtime_paths.LIBRARY_JSON:
        return None
    return path.parent / "mymedialibrary.db"


def _is_canonical_json_path(json_path: str | Path) -> bool:
    return Path(json_path) == runtime_paths.LIBRARY_JSON


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None
