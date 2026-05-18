"""SQLite-backed probe cache repository keyed by (media_id, filename).

Probe results are stored as individual typed columns — no probe_data JSON blob.
The returned dict format {"ok": bool, "technical": {...}} is preserved for callers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

try:
    from backend import db
except Exception:
    import db  # type: ignore

log = logging.getLogger(__name__)

# Columns from the technical dict that map 1-to-1 to DB columns (scalars only).
_TECH_SCALAR_COLS = (
    "width", "height", "resolution", "codec", "hdr_type",
    "runtime_min", "runtime_min_avg", "video_bitrate",
    "audio_codec", "audio_codec_raw", "audio_channels",
    "audio_bitrate", "audio_languages_simple", "framerate", "container",
)

_SELECT_COLS = (
    "probe_ok",
    "width", "height", "resolution", "codec",
    "hdr", "hdr_type",
    "runtime_min", "runtime_min_avg", "video_bitrate",
    "audio_codec", "audio_codec_raw", "audio_channels",
    "audio_languages_json", "subtitle_languages_json",
    "audio_bitrate", "audio_languages_simple", "framerate", "container",
    "dolby_vision", "size_b",
)

_SELECT_SQL = (
    "SELECT " + ", ".join(_SELECT_COLS) + " FROM media_probe_cache"
    " WHERE media_id = ? AND filename = ? AND file_size = ? AND modified_at = ?"
    " LIMIT 1"
)

_INSERT_SQL = """
    INSERT INTO media_probe_cache(
        media_id, filename, file_path, file_size, modified_at,
        probe_ok,
        width, height, resolution, codec,
        hdr, hdr_type,
        runtime_min, runtime_min_avg, video_bitrate,
        audio_codec, audio_codec_raw, audio_channels,
        audio_languages_json, subtitle_languages_json,
        audio_bitrate, audio_languages_simple, framerate, container,
        dolby_vision, size_b
    ) VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?,?,?)
    ON CONFLICT(media_id, filename) DO UPDATE SET
        file_path             = excluded.file_path,
        file_size             = excluded.file_size,
        modified_at           = excluded.modified_at,
        probed_at             = CURRENT_TIMESTAMP,
        probe_ok              = excluded.probe_ok,
        width                 = excluded.width,
        height                = excluded.height,
        resolution            = excluded.resolution,
        codec                 = excluded.codec,
        hdr                   = excluded.hdr,
        hdr_type              = excluded.hdr_type,
        runtime_min           = excluded.runtime_min,
        runtime_min_avg       = excluded.runtime_min_avg,
        video_bitrate         = excluded.video_bitrate,
        audio_codec           = excluded.audio_codec,
        audio_codec_raw       = excluded.audio_codec_raw,
        audio_channels        = excluded.audio_channels,
        audio_languages_json  = excluded.audio_languages_json,
        subtitle_languages_json = excluded.subtitle_languages_json,
        audio_bitrate         = excluded.audio_bitrate,
        audio_languages_simple = excluded.audio_languages_simple,
        framerate             = excluded.framerate,
        container             = excluded.container,
        dolby_vision          = excluded.dolby_vision,
        size_b                = excluded.size_b
"""


class MediaProbeCacheRepository:
    """Per-file probe cache keyed by (media_id, filename)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def close(self) -> None:
        try:
            self.conn.commit()
        except Exception:
            pass
        self.conn.close()

    def get(self, media_id: str, filename: str, path: Path) -> dict | None:
        """Return cached probe if (media_id, filename) hit and file unchanged.

        Returns {"ok": bool, "technical": {...}} or None on miss/invalid.
        """
        try:
            stat = path.stat()
            file_size = int(stat.st_size)
            modified_at = float(stat.st_mtime)
        except Exception:
            return None

        row = self.conn.execute(
            _SELECT_SQL, (media_id, filename, file_size, modified_at)
        ).fetchone()
        if row is None:
            return None

        tech: dict[str, Any] = {}
        for col in _TECH_SCALAR_COLS:
            tech[col] = row[col]
        tech["hdr"] = bool(row["hdr"])
        tech["dolby_vision"] = bool(row["dolby_vision"])
        tech["audio_languages"] = _from_json(row["audio_languages_json"], [])
        tech["subtitle_languages"] = _from_json(row["subtitle_languages_json"], None)

        return {"ok": bool(row["probe_ok"]), "technical": tech}

    def upsert(self, media_id: str, filename: str, path: Path, probe: dict) -> None:
        """Store probe result keyed by (media_id, filename)."""
        try:
            stat = path.stat()
            file_size = int(stat.st_size)
            modified_at = float(stat.st_mtime)
        except Exception:
            return
        ok = 1 if probe.get("ok") else 0
        tech = probe.get("technical")
        tech = tech if isinstance(tech, dict) else {}
        al = tech.get("audio_languages")
        sl = tech.get("subtitle_languages")
        try:
            self.conn.execute(
                _INSERT_SQL,
                (
                    media_id, filename, str(path), file_size, modified_at,
                    ok,
                    tech.get("width"), tech.get("height"),
                    tech.get("resolution"), tech.get("codec"),
                    1 if tech.get("hdr") else 0, tech.get("hdr_type"),
                    tech.get("runtime_min"), tech.get("runtime_min_avg"),
                    tech.get("video_bitrate"),
                    tech.get("audio_codec"), tech.get("audio_codec_raw"), tech.get("audio_channels"),
                    _to_json(al) if isinstance(al, list) else None,
                    _to_json(sl) if isinstance(sl, list) else None,
                    tech.get("audio_bitrate"), tech.get("audio_languages_simple"),
                    tech.get("framerate"), tech.get("container"),
                    1 if tech.get("dolby_vision") else 0,
                    tech.get("size_b"),
                ),
            )
        except Exception as exc:
            log.debug("[media_probe_cache] upsert failed for %s/%s: %s", media_id, filename, exc)


def open_cache(*, db_path: str | Path | None = None) -> MediaProbeCacheRepository:
    conn = db.initialize_database(db_path)
    return MediaProbeCacheRepository(conn)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
