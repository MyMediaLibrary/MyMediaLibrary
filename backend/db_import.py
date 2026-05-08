"""Non-destructive JSON to SQLite import helpers."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from backend import db, runtime_paths
except Exception:
    import db  # type: ignore
    import runtime_paths  # type: ignore


log = logging.getLogger(__name__)


@dataclass
class ImportReport:
    """Summary of a JSON to DB import pass."""

    imported: dict[str, int] = field(default_factory=dict)
    skipped_missing: list[str] = field(default_factory=list)
    invalid_json: list[str] = field(default_factory=list)

    def add(self, name: str, count: int) -> None:
        self.imported[name] = self.imported.get(name, 0) + int(count)


def import_runtime_json_files(
    db_path: str | Path | None = None,
    *,
    paths=runtime_paths,
) -> ImportReport:
    """Import all known runtime JSON files into SQLite without deleting them."""

    conn = db.initialize_database(db_path)
    try:
        report = ImportReport()
        import_providers_logo(conn, paths.PROVIDERS_LOGO_JSON, report)
        import_providers_mapping(conn, paths.PROVIDERS_MAPPING_JSON, report)
        import_recommendation_rules(conn, paths.RECOMMENDATIONS_RULES_JSON, report)
        import_config(conn, paths.CONFIG_JSON, report)
        import_media_probe_cache(conn, paths.MEDIA_PROBE_CACHE_JSON, report)
        import_library_inventory(conn, paths.INVENTORY_JSON, report)
        import_recommendations(conn, paths.RECOMMENDATIONS_JSON, report)
        import_library(conn, paths.LIBRARY_JSON, report)
        return report
    finally:
        conn.close()


def import_providers_logo(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "providers_logo", report)
    if not isinstance(payload, dict):
        return 0
    rows = 0
    with conn:
        for provider_name, logo in payload.items():
            if not isinstance(provider_name, str) or not provider_name:
                continue
            logo_path = logo if isinstance(logo, str) else None
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO provider_logos(provider_name, logo_path)
                VALUES (?, ?)
                """,
                (provider_name, logo_path),
            )
    _record(report, "providers_logo", rows)
    return rows


def import_providers_mapping(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "providers_mapping", report)
    if not isinstance(payload, dict):
        return 0
    rows = 0
    with conn:
        for raw_name, mapped_name in payload.items():
            if not isinstance(raw_name, str) or not raw_name:
                continue
            ignored = mapped_name is None
            mapped = mapped_name if isinstance(mapped_name, str) else None
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO provider_mappings(raw_name, mapped_name, is_ignored)
                VALUES (?, ?, ?)
                """,
                (raw_name, mapped, 1 if ignored else 0),
            )
    _record(report, "providers_mapping", rows)
    return rows


def import_recommendation_rules(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "recommendation_rules", report)
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        return 0
    rows = 0
    with conn:
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            rule_key = str(rule.get("id") or rule.get("rule_key") or f"rule_{index}")
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO recommendation_rules(rule_key, rule_json, enabled)
                VALUES (?, ?, ?)
                """,
                (rule_key, _to_json(rule), 0 if rule.get("enabled") is False else 1),
            )
    _record(report, "recommendation_rules", rows)
    return rows


def import_config(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "config", report)
    if not isinstance(payload, dict):
        return 0
    rows = 0
    with conn:
        for key, value in payload.items():
            if key == "auth":
                _import_auth_settings(conn, value)
                continue
            clean_value = _strip_sensitive_value(key, value)
            if clean_value is _SKIP_VALUE:
                continue
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO app_config(key, value_json)
                VALUES (?, ?)
                """,
                (str(key), _to_json(clean_value)),
            )
        if isinstance(payload.get("score"), dict) or isinstance(payload.get("score_configuration"), dict):
            score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO score_settings(id, enabled, configuration_json)
                VALUES (?, ?, ?)
                """,
                (
                    "default",
                    1 if score.get("enabled") is True else 0,
                    _to_json(payload.get("score_configuration") or {}),
                ),
            )
        if isinstance(payload.get("media_probe"), dict):
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO scan_settings(id, value_json)
                VALUES (?, ?)
                """,
                ("media_probe", _to_json(payload["media_probe"])),
            )
    _record(report, "config", rows)
    return rows


def import_media_probe_cache(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "media_probe_cache", report)
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict):
        return 0
    rows = 0
    with conn:
        for file_path, entry in files.items():
            if not isinstance(file_path, str) or not isinstance(entry, dict):
                continue
            probe = entry.get("probe") if isinstance(entry.get("probe"), dict) else {}
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO ffprobe_cache(file_path, size, mtime, status, normalized_json, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    file_path,
                    _as_int(entry.get("size_b")),
                    _as_float(entry.get("mtime")),
                    "ok" if probe.get("ok") else "error",
                    _to_json(probe),
                    probe.get("error") if isinstance(probe.get("error"), str) else None,
                ),
            )
    _record(report, "media_probe_cache", rows)
    return rows


def import_library_inventory(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "library_inventory", report)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return 0
    rows = 0
    with conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            inventory_id = str(item.get("id") or item.get("inventory_key") or item.get("path") or "")
            if not inventory_id:
                continue
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO inventory_items(
                    id, media_id, inventory_key, media_type, title, category, folder, path,
                    first_seen_at, last_seen_at, last_checked_at, missing_since, status, data_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inventory_id,
                    item.get("media_id"),
                    inventory_id,
                    item.get("media_type"),
                    item.get("title"),
                    item.get("category"),
                    item.get("root_folder_name") or item.get("folder"),
                    item.get("root_folder_path") or item.get("path"),
                    item.get("first_seen_at"),
                    item.get("last_seen_at"),
                    item.get("last_checked_at"),
                    item.get("missing_since"),
                    item.get("status"),
                    _to_json(item),
                ),
            )
    _record(report, "library_inventory", rows)
    return rows


def import_recommendations(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "recommendations", report)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return 0
    rows = 0
    with conn:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            rec_id = str(item.get("id") or f"recommendation:{index}")
            media_ref = item.get("media_ref") if isinstance(item.get("media_ref"), dict) else {}
            media_id = _existing_media_id(conn, media_ref.get("id"))
            display = item.get("display") if isinstance(item.get("display"), dict) else {}
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO recommendations(
                    id, media_id, recommendation_type, priority, title, reason, rule_id,
                    dedupe_group, severity, message_json, suggested_action_json, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec_id,
                    media_id,
                    item.get("recommendation_type") or "unknown",
                    item.get("priority"),
                    display.get("title") or item.get("title") or rec_id,
                    item.get("reason"),
                    item.get("rule_id"),
                    item.get("dedupe_group"),
                    _as_int(item.get("severity")),
                    _to_json(item.get("message") or {}),
                    _to_json(item.get("suggested_action") or {}),
                    _to_json(item),
                ),
            )
    _record(report, "recommendations", rows)
    return rows


def import_library(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "library", report)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return 0
    rows = 0
    with conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            rows += upsert_library_item(conn, item, overwrite=False)
    _record(report, "library", rows)
    return rows


def upsert_library_item(conn: sqlite3.Connection, item: dict[str, Any], *, overwrite: bool = True) -> int:
    """Write one scanner/library item to the DB.

    This is intentionally shape-compatible with current library.json items so
    scanner phases can call it later while JSON exports remain in place.
    """

    media_id = str(item.get("id") or item.get("path") or "")
    title = item.get("title")
    media_type = item.get("type") or item.get("media_type")
    if not media_id or not title or not media_type:
        return 0

    params = _media_params(media_id, item)
    if overwrite:
        conn.execute(_MEDIA_UPSERT_SQL, params)
        return 1
    return _insert_count(conn, _MEDIA_INSERT_IGNORE_SQL, params)


def _import_auth_settings(conn: sqlite3.Connection, value: Any) -> None:
    if not isinstance(value, dict):
        return
    password_hash = value.get("password_hash") if isinstance(value.get("password_hash"), str) else None
    conn.execute(
        """
        INSERT OR IGNORE INTO auth_settings(id, auth_enabled, password_hash)
        VALUES (1, ?, ?)
        """,
        (1 if value.get("enabled") is True else 0, password_hash),
    )


def _read_json(path: str | Path, name: str, report: ImportReport | None) -> Any:
    json_path = Path(path)
    if not json_path.exists():
        if report is not None:
            report.skipped_missing.append(name)
        log.info("[db-import] skip missing %s: %s", name, json_path)
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        if report is not None:
            report.invalid_json.append(name)
        log.warning("[db-import] invalid %s %s: %s", name, json_path, exc)
        return None


def _record(report: ImportReport | None, name: str, rows: int) -> None:
    if report is not None:
        report.add(name, rows)
    log.info("[db-import] %s imported rows=%s", name, rows)


def _insert_count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    before = conn.total_changes
    conn.execute(sql, params)
    return conn.total_changes - before


def _existing_media_id(conn: sqlite3.Connection, value: Any) -> str | None:
    if value in (None, ""):
        return None
    media_id = str(value)
    row = conn.execute("SELECT id FROM media WHERE id = ?", (media_id,)).fetchone()
    return media_id if row is not None else None


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


_SKIP_VALUE = object()


def _strip_sensitive_value(key: str, value: Any) -> Any:
    lowered = str(key).casefold()
    if any(token in lowered for token in ("apikey", "api_key", "token", "secret", "password")):
        return _SKIP_VALUE
    if isinstance(value, dict):
        clean = {}
        for child_key, child_value in value.items():
            stripped = _strip_sensitive_value(child_key, child_value)
            if stripped is not _SKIP_VALUE:
                clean[child_key] = stripped
        return clean
    if isinstance(value, list):
        clean_list = []
        for item in value:
            stripped = _strip_sensitive_value(key, item)
            if stripped is not _SKIP_VALUE:
                clean_list.append(stripped)
        return clean_list
    return value


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


def _media_params(media_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    return (
        media_id,
        item.get("type") or item.get("media_type"),
        item.get("title"),
        item.get("raw"),
        item.get("category"),
        item.get("year"),
        item.get("category"),
        item.get("path"),
        _as_int(item.get("tmdb_id")),
        _as_int(item.get("tvdb_id")),
        item.get("imdb_id"),
        item.get("plot") or item.get("overview"),
        item.get("poster") or item.get("poster_path"),
        _to_json(item.get("genres") or []),
        _as_int(item.get("file_count")),
        _as_int(item.get("size_b") or item.get("size_total")),
        _as_int(item.get("runtime_min")),
        _as_int(item.get("runtime_min_avg")),
        _as_float(quality.get("score") if isinstance(quality, dict) else item.get("quality_score")),
        _as_int(item.get("width")),
        _as_int(item.get("height")),
        item.get("resolution"),
        item.get("codec") or item.get("video_codec"),
        _as_int(item.get("video_bitrate")),
        item.get("audio_codec"),
        item.get("audio_codec_raw"),
        _as_int(item.get("audio_bitrate")),
        item.get("audio_channels"),
        _to_json(item.get("audio_languages") or []),
        item.get("audio_language_group") or item.get("audio_languages_simple"),
        _to_json(item.get("subtitle_languages") or []),
        _as_float(item.get("framerate")),
        item.get("container"),
        1 if item.get("hdr") is True else 0 if item.get("hdr") is False else None,
        item.get("hdr_type"),
        1 if item.get("dolby_vision") is True else 0 if item.get("dolby_vision") is False else None,
        _to_json(item.get("providers") or []),
        _to_json(quality or {}),
        _to_json(item),
        item.get("added_at"),
    )


_MEDIA_COLUMNS = """
id, media_type, title, raw_name, category, year, folder, path, tmdb_id, tvdb_id,
imdb_id, overview, poster_path, genres_json, file_count, size_total,
runtime_min, runtime_min_avg, quality_score, width, height, resolution,
video_codec, video_bitrate, audio_codec, audio_codec_raw, audio_bitrate,
audio_channels, audio_languages_json, audio_language_group,
subtitle_languages_json, framerate, container, hdr, hdr_type, dolby_vision,
providers_json, quality_json, data_json, last_seen_at
"""

_MEDIA_INSERT_IGNORE_SQL = f"""
INSERT OR IGNORE INTO media({_MEDIA_COLUMNS})
VALUES ({",".join(["?"] * 40)})
"""

_MEDIA_UPSERT_SQL = f"""
INSERT INTO media({_MEDIA_COLUMNS})
VALUES ({",".join(["?"] * 40)})
ON CONFLICT(id) DO UPDATE SET
    media_type = excluded.media_type,
    title = excluded.title,
    raw_name = excluded.raw_name,
    category = excluded.category,
    year = excluded.year,
    folder = excluded.folder,
    path = excluded.path,
    tmdb_id = excluded.tmdb_id,
    tvdb_id = excluded.tvdb_id,
    imdb_id = excluded.imdb_id,
    overview = excluded.overview,
    poster_path = excluded.poster_path,
    genres_json = excluded.genres_json,
    file_count = excluded.file_count,
    size_total = excluded.size_total,
    runtime_min = excluded.runtime_min,
    runtime_min_avg = excluded.runtime_min_avg,
    quality_score = excluded.quality_score,
    width = excluded.width,
    height = excluded.height,
    resolution = excluded.resolution,
    video_codec = excluded.video_codec,
    video_bitrate = excluded.video_bitrate,
    audio_codec = excluded.audio_codec,
    audio_codec_raw = excluded.audio_codec_raw,
    audio_bitrate = excluded.audio_bitrate,
    audio_channels = excluded.audio_channels,
    audio_languages_json = excluded.audio_languages_json,
    audio_language_group = excluded.audio_language_group,
    subtitle_languages_json = excluded.subtitle_languages_json,
    framerate = excluded.framerate,
    container = excluded.container,
    hdr = excluded.hdr,
    hdr_type = excluded.hdr_type,
    dolby_vision = excluded.dolby_vision,
    providers_json = excluded.providers_json,
    quality_json = excluded.quality_json,
    data_json = excluded.data_json,
    updated_at = CURRENT_TIMESTAMP,
    last_seen_at = excluded.last_seen_at
"""
