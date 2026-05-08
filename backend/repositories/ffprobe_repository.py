"""SQLite-backed ffprobe cache repository."""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

try:
    from backend import db, db_import
except Exception:
    import db  # type: ignore
    import db_import  # type: ignore


log = logging.getLogger(__name__)


class FfprobeCacheRepository:
    """Reusable SQLite connection for a media probe pass."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def close(self) -> None:
        try:
            self.conn.commit()
        except Exception:
            pass
        self.conn.close()

    def get(self, path: str | Path, *, size: int, mtime: float) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT status, normalized_json, error
            FROM ffprobe_cache
            WHERE file_path = ? AND size = ? AND mtime = ?
            LIMIT 1
            """,
            (str(path), int(size), float(mtime)),
        ).fetchone()
        if row is None:
            return None
        probe = _from_json(row["normalized_json"], {})
        if not isinstance(probe, dict):
            probe = {}
        if row["status"] == "ok":
            probe.setdefault("ok", True)
            return copy.deepcopy(probe)
        error = row["error"] if isinstance(row["error"], str) and row["error"] else probe.get("error")
        return {"ok": False, "error": error or "ffprobe failed"}

    def upsert_probe(self, path: str | Path, *, size: int, mtime: float, probe: dict[str, Any]) -> None:
        status = "ok" if isinstance(probe, dict) and probe.get("ok") is True else "error"
        error = probe.get("error") if isinstance(probe, dict) and isinstance(probe.get("error"), str) else None
        self.conn.execute(
            """
            INSERT INTO ffprobe_cache(file_path, size, mtime, probed_at, status, normalized_json, error)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            ON CONFLICT(file_path, size, mtime) DO UPDATE SET
                probed_at = CURRENT_TIMESTAMP,
                status = excluded.status,
                normalized_json = excluded.normalized_json,
                error = excluded.error
            """,
            (str(path), int(size), float(mtime), status, _to_json(probe if isinstance(probe, dict) else {}), error),
        )

    def upsert_error(self, path: str | Path, *, size: int, mtime: float, error: str) -> None:
        self.upsert_probe(path, size=size, mtime=mtime, probe={"ok": False, "error": str(error or "ffprobe failed")})

    def delete_stale(self, file_paths: list[str | Path]) -> int:
        keep = {str(path) for path in file_paths}
        if not keep:
            return 0
        rows = self.conn.execute("SELECT id, file_path FROM ffprobe_cache").fetchall()
        stale_ids = [row["id"] for row in rows if row["file_path"] not in keep]
        if not stale_ids:
            return 0
        placeholders = ",".join("?" for _ in stale_ids)
        with self.conn:
            self.conn.execute(f"DELETE FROM ffprobe_cache WHERE id IN ({placeholders})", stale_ids)
        return len(stale_ids)


def open_cache(
    *,
    json_path: str | Path,
    db_path: str | Path | None = None,
) -> FfprobeCacheRepository | None:
    """Open the SQLite cache, importing JSON once when the table is empty."""

    try:
        conn = db.initialize_database(db_path)
    except Exception as exc:
        log.debug("[ffprobe] SQLite cache unavailable, falling back to JSON: %s", exc)
        return None
    try:
        if _table_is_empty(conn):
            db_import.import_media_probe_cache(conn, json_path)
        return FfprobeCacheRepository(conn)
    except Exception as exc:
        log.warning("[ffprobe] Could not initialize SQLite cache: %s", exc)
        conn.close()
        return None


def _table_is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM ffprobe_cache LIMIT 1").fetchone() is None


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
