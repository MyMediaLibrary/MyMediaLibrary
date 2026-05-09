"""SQLite connection and initialization layer for MyMediaLibrary."""

from __future__ import annotations

import sqlite3
import contextlib
import fcntl
import logging
import os
import threading
import time
from pathlib import Path

try:
    from backend import db_migrations, runtime_paths
except Exception:
    import db_migrations  # type: ignore
    import runtime_paths  # type: ignore


DEFAULT_DB_PATH = runtime_paths.SQLITE_DB
DB_PATH_ENV = "MYMEDIALIBRARY_DB_PATH"


def default_db_path() -> Path:
    configured = os.environ.get(DB_PATH_ENV)
    return Path(configured) if configured else DEFAULT_DB_PATH

log = logging.getLogger(__name__)
_startup_tasks_lock = threading.Lock()
_startup_tasks_done = False
_STARTUP_TASKS_MARKER_TTL_SECONDS = 300


def open_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with MyMediaLibrary runtime pragmas."""

    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_database(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create or migrate the database and return an open connection."""

    conn = open_connection(db_path)
    try:
        db_migrations.migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


def bootstrap_runtime_database(
    db_path: str | Path | None = None,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    """Initialize the runtime database once at process startup and log its state."""

    global _startup_tasks_done
    target = Path(db_path) if db_path is not None else default_db_path()
    active_logger = logger or log
    try:
        conn = initialize_database(target)
    except Exception as exc:
        active_logger.error("[DB] SQLite unavailable — runtime storage unavailable: %s", exc)
        raise
    try:
        version = get_schema_version(conn)
        wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        active_logger.info("[DB] SQLite initialized — path=%s", target)
        active_logger.info("[DB] Schema version: %s", version)
        active_logger.info("[DB] WAL enabled: %s", str(wal_mode).casefold() == "wal")
        active_logger.info("[DB] Foreign keys enabled: %s", bool(foreign_keys))
        if os.environ.get("MML_SKIP_DB_STARTUP_TASKS") == "1":
            active_logger.debug("[DB] Startup JSON migration/seed skipped for child process")
            return True
        with _startup_tasks_lock:
            if not _startup_tasks_done:
                _run_startup_tasks_once(conn, target, active_logger)
                _startup_tasks_done = True
        return True
    finally:
        conn.close()


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Expose schema version lookup from the migration layer."""

    return db_migrations.get_schema_version(conn)


def _migrate_runtime_json_sources(conn: sqlite3.Connection, active_logger: logging.Logger) -> None:
    try:
        try:
            from backend import db_import
        except Exception:
            import db_import  # type: ignore
        db_import.migrate_runtime_json_files_at_startup(conn, logger=active_logger)
    except Exception as exc:
        active_logger.warning("[DB] JSON migration completed with warnings — source files kept for review: %s", exc)


def _seed_bundled_defaults(conn: sqlite3.Connection, active_logger: logging.Logger) -> None:
    try:
        try:
            from backend import db_import
        except Exception:
            import db_import  # type: ignore
        db_import.seed_bundled_defaults(conn, logger=active_logger)
    except Exception as exc:
        active_logger.warning("[DB] Bundled default seed completed with warnings: %s", exc)


def _run_startup_tasks_once(conn: sqlite3.Connection, db_path: Path, active_logger: logging.Logger) -> None:
    """Run JSON cleanup/seed once across cooperating startup processes."""

    lock_path, marker_path = _startup_task_paths(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if _startup_marker_is_fresh(marker_path):
                active_logger.debug("[DB] Startup JSON migration/seed already completed for this boot")
                return
            _migrate_runtime_json_sources(conn, active_logger)
            _seed_bundled_defaults(conn, active_logger)
            _write_startup_marker(marker_path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _startup_task_paths(db_path: Path) -> tuple[Path, Path]:
    if db_path == DEFAULT_DB_PATH:
        base = runtime_paths.TMP_DIR
    else:
        base = db_path.parent
    return base / "mml_sqlite_startup_tasks.lock", base / "mml_sqlite_startup_tasks.done"


def _startup_marker_is_fresh(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    except Exception:
        return False
    return 0 <= age <= _STARTUP_TASKS_MARKER_TTL_SECONDS


def _write_startup_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        path.write_text(str(time.time()), encoding="utf-8")
