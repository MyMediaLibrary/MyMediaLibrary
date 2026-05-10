"""SQLite-backed probe cache repository keyed by (media_id, filename)."""

from __future__ import annotations

import copy
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
        """Return cached probe if (media_id, filename) hit and file unchanged."""
        try:
            stat = path.stat()
            file_size = int(stat.st_size)
            modified_at = float(stat.st_mtime)
        except Exception:
            return None

        row = self.conn.execute(
            """
            SELECT probe_data FROM media_probe_cache
            WHERE media_id = ? AND filename = ? AND file_size = ? AND modified_at = ?
            LIMIT 1
            """,
            (media_id, filename, file_size, modified_at),
        ).fetchone()

        if row is None:
            return None
        probe = _from_json(row["probe_data"], None)
        if not isinstance(probe, dict):
            return None
        return copy.deepcopy(probe)

    def upsert(self, media_id: str, filename: str, path: Path, probe: dict) -> None:
        """Store probe result keyed by (media_id, filename)."""
        try:
            stat = path.stat()
            file_size = int(stat.st_size)
            modified_at = float(stat.st_mtime)
        except Exception:
            return
        try:
            self.conn.execute(
                """
                INSERT INTO media_probe_cache(media_id, filename, file_path, file_size, modified_at, probe_data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_id, filename) DO UPDATE SET
                    file_path = excluded.file_path,
                    file_size = excluded.file_size,
                    modified_at = excluded.modified_at,
                    probed_at = CURRENT_TIMESTAMP,
                    probe_data = excluded.probe_data
                """,
                (media_id, filename, str(path), file_size, modified_at, _to_json(probe)),
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
