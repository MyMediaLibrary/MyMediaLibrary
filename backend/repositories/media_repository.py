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
        where = " WHERE m.is_available = 1"
    elif availability == "absent":
        where = " WHERE m.is_available = 0"
    else:
        where = ""
    media_rows = conn.execute(
        f"SELECT * FROM media m{where} ORDER BY m.title, m.id"
    ).fetchall()
    if not media_rows:
        return _normalize_library_document({"scanned_at": None, "library_path": None, "total_items": 0, "categories": [], "items": []})

    media_ids = [r["id"] for r in media_rows]
    seasons_by_media = _batch_seasons(conn, media_ids)
    providers_by_media = _batch_providers(conn, media_ids)

    items = [_reconstruct_item(row, seasons_by_media, providers_by_media) for row in media_rows]
    return _normalize_library_document({
        "scanned_at": None,
        "library_path": None,
        "total_items": len(items),
        "categories": sorted({item.get("category") for item in items if item.get("category")}),
        "items": items,
    })


def _batch_seasons(conn: sqlite3.Connection, media_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not media_ids:
        return {}
    placeholders = ",".join("?" * len(media_ids))
    rows = conn.execute(
        f"SELECT * FROM seasons WHERE media_id IN ({placeholders}) ORDER BY media_id, season_number",
        media_ids,
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        mid = row["media_id"]
        result.setdefault(mid, []).append(_reconstruct_season(row))
    return result


def _batch_providers(conn: sqlite3.Connection, media_ids: list[str]) -> dict[str, list[str]]:
    if not media_ids:
        return {}
    placeholders = ",".join("?" * len(media_ids))
    rows = conn.execute(
        f"""
        SELECT mp.media_id, COALESCE(p.mapped_name, p.raw_name) AS display_name
        FROM media_providers mp
        JOIN providers p ON p.id = mp.provider_id
        WHERE mp.media_id IN ({placeholders}) AND (p.is_ignored IS NULL OR p.is_ignored = 0)
        ORDER BY mp.media_id, p.id
        """,
        media_ids,
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["media_id"], []).append(row["display_name"])
    return result


def _reconstruct_item(
    row: Any,
    seasons_by_media: dict[str, list[dict[str, Any]]],
    providers_by_media: dict[str, list[str]],
) -> dict[str, Any]:
    media_id = row["id"]
    seasons = seasons_by_media.get(media_id, [])
    providers = providers_by_media.get(media_id, [])
    quality = _from_json(row["quality_json"], None)
    audio_languages = _from_json(row["audio_languages_json"], [])
    subtitle_languages = _from_json(row["subtitle_languages_json"], [])
    genres = _from_json(row["genres_json"], [])
    filename = _from_json(row["filename"], None)
    filename_history = _from_json(row["filename_history"], [])
    item: dict[str, Any] = {
        "id": media_id,
        "type": row["media_type"],
        "media_type": row["media_type"],
        "title": row["title"],
        "raw": row["raw_name"],
        "category": row["category"],
        "year": row["year"],
        "folder": row["folder"],
        "root_path": row["root_path"],
        "path": row["path"],
        "tmdb_id": str(row["tmdb_id"]) if row["tmdb_id"] is not None else None,
        "tvdb_id": str(row["tvdb_id"]) if row["tvdb_id"] is not None else None,
        "imdb_id": row["imdb_id"],
        "plot": row["overview"],
        "overview": row["overview"],
        "poster": row["poster_path"],
        "poster_path": row["poster_path"],
        "genres": genres,
        "file_count": row["file_count"],
        "size_b": row["size_total"],
        "size_total": row["size_total"],
        "runtime_min": row["runtime_min"],
        "runtime_min_avg": row["runtime_min_avg"],
        "quality": quality,
        "quality_score": row["quality_score"],
        "width": row["width"],
        "height": row["height"],
        "resolution": row["resolution"],
        "codec": row["video_codec"],
        "video_codec": row["video_codec"],
        "video_bitrate": row["video_bitrate"],
        "audio_codec": row["audio_codec"],
        "audio_codec_raw": row["audio_codec_raw"],
        "audio_bitrate": row["audio_bitrate"],
        "audio_channels": row["audio_channels"],
        "audio_languages": audio_languages,
        "audio_languages_simple": row["audio_language_group"],
        "audio_language_group": row["audio_language_group"],
        "subtitle_languages": subtitle_languages,
        "framerate": row["framerate"],
        "container": row["container"],
        "hdr": bool(row["hdr"]) if row["hdr"] is not None else None,
        "hdr_type": row["hdr_type"],
        "dolby_vision": bool(row["dolby_vision"]) if row["dolby_vision"] is not None else None,
        "providers_fetched": bool(row["providers_fetched"]),
        "providers": providers,
        "is_available": bool(row["is_available"]),
        "last_seen_at": row["last_seen_at"],
        "added_at": row["first_seen_at"],
        "first_seen_at": row["first_seen_at"],
        "last_scanned_at": row["last_scanned_at"],
        "filename": filename,
        "filename_history": filename_history if isinstance(filename_history, list) else [],
    }
    if seasons:
        item["seasons"] = seasons
        item["season_count"] = len(seasons)
        item["episode_count"] = sum(s.get("episodes_count") or 0 for s in seasons)
    return item


def _reconstruct_season(row: Any) -> dict[str, Any]:
    audio_languages = _from_json(row["audio_languages_json"], [])
    subtitle_languages = _from_json(row["subtitle_languages_json"], [])
    quality_score = row["quality_score"]
    return {
        "season": row["season_number"],
        "season_number": row["season_number"],
        "title": row["title"],
        "episodes_count": row["episodes_count"],
        "size_b": row["size_total"],
        "size_total": row["size_total"],
        "runtime_min": row["runtime_min"],
        "runtime_min_avg": row["runtime_min_avg"],
        "quality": {"score": quality_score} if quality_score is not None else None,
        "quality_score": quality_score,
        "width": row["width"],
        "height": row["height"],
        "resolution": row["resolution"],
        "codec": row["video_codec"],
        "video_codec": row["video_codec"],
        "audio_codec": row["audio_codec"],
        "audio_channels": row["audio_channels"],
        "audio_languages": audio_languages,
        "audio_languages_simple": row["audio_language_group"],
        "subtitle_languages": subtitle_languages,
        "container": row["container"],
        "hdr": bool(row["hdr"]) if row["hdr"] is not None else None,
        "hdr_type": row["hdr_type"],
        "dolby_vision": bool(row["dolby_vision"]) if row["dolby_vision"] is not None else None,
    }


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
