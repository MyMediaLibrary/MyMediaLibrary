"""Scan-run history repository — one row per scan, no JSON blobs."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

try:
    from backend import db as _db
except Exception:
    import db as _db  # type: ignore

log = logging.getLogger(__name__)

_PHASE_COLS = {
    "1": "phase1",
    "2": "phase2",
    "3": "phase3",
    "4": "phase4",
    "5": "phase5",
    "score_only": "score_only",
}

_VALID_TRIGGER_TYPES = frozenset({"manual", "cron", "startup", "save_settings", "api", "unknown"})
_VALID_STATUSES = frozenset({"running", "completed", "failed"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_scan_run(
    *,
    trigger_type: str,
    mode: str,
    phase_plan: str | None = None,
    db_path: Any = None,
) -> int:
    """INSERT a new scan_run row and return its id (0 on failure)."""
    if trigger_type not in _VALID_TRIGGER_TYPES:
        trigger_type = "unknown"
    try:
        conn = _db.open_connection(db_path)
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO scan_runs(trigger_type, mode, phase_plan, status, started_at)
                    VALUES (?, ?, ?, 'running', ?)
                    """,
                    (trigger_type, mode, phase_plan, _now_iso()),
                )
                return cur.lastrowid or 0
        finally:
            conn.close()
    except Exception as exc:
        log.error("[scan_run] create_scan_run failed: %s", exc)
        return 0


def mark_phase_enabled(run_id: int, phase_id: str, *, db_path: Any = None) -> None:
    """Mark a phase as planned/enabled for this scan run."""
    col = _PHASE_COLS.get(phase_id)
    if not col or not run_id:
        return
    try:
        conn = _db.open_connection(db_path)
        try:
            with conn:
                conn.execute(
                    f"UPDATE scan_runs SET {col}_enabled = 1, updated_at = ? WHERE id = ?",
                    (_now_iso(), run_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        log.error("[scan_run] mark_phase_enabled(%s, %s) failed: %s", run_id, phase_id, exc)


def mark_phase_completed(
    run_id: int,
    phase_id: str,
    *,
    duration_sec: float,
    summary: str = "",
    db_path: Any = None,
) -> None:
    """Record a phase's duration and summary on the scan_run row."""
    col = _PHASE_COLS.get(phase_id)
    if not col or not run_id:
        return
    try:
        conn = _db.open_connection(db_path)
        try:
            with conn:
                conn.execute(
                    f"""
                    UPDATE scan_runs
                    SET {col}_enabled = 1,
                        {col}_duration_sec = ?,
                        {col}_summary = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (round(duration_sec, 3), summary or None, _now_iso(), run_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        log.error("[scan_run] mark_phase_completed(%s, %s) failed: %s", run_id, phase_id, exc)


def mark_completed(run_id: int, *, total_duration_sec: float, db_path: Any = None) -> None:
    """Mark the scan_run as completed."""
    if not run_id:
        return
    try:
        conn = _db.open_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE scan_runs
                    SET status = 'completed',
                        completed_at = ?,
                        total_duration_sec = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (_now_iso(), round(total_duration_sec, 3), _now_iso(), run_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        log.error("[scan_run] mark_completed(%s) failed: %s", run_id, exc)


def mark_failed(run_id: int, *, error: str, total_duration_sec: float = 0.0, db_path: Any = None) -> None:
    """Mark the scan_run as failed with an error message."""
    if not run_id:
        return
    try:
        conn = _db.open_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE scan_runs
                    SET status = 'failed',
                        completed_at = ?,
                        total_duration_sec = ?,
                        error = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (_now_iso(), round(total_duration_sec, 3), str(error)[:2000], _now_iso(), run_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        log.error("[scan_run] mark_failed(%s) failed: %s", run_id, exc)


def get_recent_scan_runs(limit: int = 50, *, db_path: Any = None) -> list[dict[str, Any]]:
    """Return the most recent scan_run rows as plain dicts, newest first."""
    try:
        conn = _db.open_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception as exc:
        log.error("[scan_run] get_recent_scan_runs failed: %s", exc)
        return []


class ScanRunRecorder:
    """Lightweight helper that writes one row per scan to scan_runs.

    All DB operations are wrapped in try/except — a DB failure never
    interrupts the scan itself.
    """

    def __init__(
        self,
        trigger_type: str,
        mode: str,
        phase_plan: str | None = None,
        db_path: Any = None,
    ) -> None:
        self._trigger_type = trigger_type
        self._mode = mode
        self._phase_plan = phase_plan
        self._db_path = db_path
        self._run_id: int = 0
        self._t0: float = 0.0

    def start(self) -> "ScanRunRecorder":
        self._t0 = time.monotonic()
        self._run_id = create_scan_run(
            trigger_type=self._trigger_type,
            mode=self._mode,
            phase_plan=self._phase_plan,
            db_path=self._db_path,
        )
        return self

    def record_phase(self, phase_id: str, duration_sec: float, summary: str = "") -> None:
        mark_phase_completed(
            self._run_id,
            phase_id,
            duration_sec=duration_sec,
            summary=summary,
            db_path=self._db_path,
        )

    def complete(self) -> None:
        mark_completed(
            self._run_id,
            total_duration_sec=time.monotonic() - self._t0,
            db_path=self._db_path,
        )

    def fail(self, error: str) -> None:
        mark_failed(
            self._run_id,
            error=error,
            total_duration_sec=time.monotonic() - self._t0,
            db_path=self._db_path,
        )
