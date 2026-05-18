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
    from backend import db_migrations, db_schema, runtime_paths
except Exception:
    import db_migrations  # type: ignore
    import db_schema  # type: ignore
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

    # timeout=30: give concurrent writers (e.g. --serve + --origin startup) 30 s to
    # acquire the write lock rather than raising "database is locked" after 5 s.
    conn = sqlite3.connect(path, timeout=30)
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
        skip = os.environ.get("MML_SKIP_DB_STARTUP_TASKS") == "1"
        _log = active_logger.debug if skip else active_logger.info
        _log("[DB] SQLite initialized — path=%s", target)
        _log("[DB] Schema version: %s", version)
        _log("[DB] WAL enabled: %s", str(wal_mode).casefold() == "wal")
        _log("[DB] Foreign keys enabled: %s", bool(foreign_keys))
        if skip:
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


def _has_legacy_json_sources(active_logger: logging.Logger) -> bool:
    try:
        try:
            from backend import db_import
        except Exception:
            import db_import  # type: ignore
        detected = db_import.list_detected_legacy_json_files()
        if detected:
            active_logger.info("[DB] Legacy JSON scan path: %s", detected[0].parent)
            active_logger.info("[DB] Legacy JSON detected: %s", ", ".join(p.name for p in detected))
            return True
        return False
    except Exception as exc:
        active_logger.warning("[DB] Could not inspect legacy JSON files; running migration defensively: %s", exc)
        return True


def _seed_bundled_defaults(conn: sqlite3.Connection, active_logger: logging.Logger) -> None:
    try:
        try:
            from backend import db_seed
        except Exception:
            import db_seed  # type: ignore
        db_seed.seed_all(conn, logger=active_logger)
    except Exception as exc:
        active_logger.warning("[DB] Bundled default seed completed with warnings: %s", exc)


def is_database_bootstrapped(conn: sqlite3.Connection) -> bool:
    """Return True when the runtime DB has schema and minimum config seed data."""

    if get_schema_version(conn) < db_schema.SCHEMA_VERSION:
        return False
    expected_tables = {
        "app_config",
        "score_rules",
        "schema_migrations",
        "providers",
        "recommendation_rules",
    }
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({})".format(
            ",".join("?" for _ in expected_tables)
        ),
        tuple(expected_tables),
    ).fetchall()
    if {row["name"] for row in rows} != expected_tables:
        return False
    app_config_count = conn.execute("SELECT COUNT(*) FROM app_config").fetchone()[0]
    score_count = conn.execute("SELECT COUNT(*) FROM score_rules").fetchone()[0]
    rules_count = conn.execute("SELECT COUNT(*) FROM recommendation_rules").fetchone()[0]
    if app_config_count <= 0 or score_count <= 0 or rules_count <= 0:
        return False
    return True


def _run_startup_tasks_once(conn: sqlite3.Connection, db_path: Path, active_logger: logging.Logger) -> None:
    """Run JSON cleanup/seed once across cooperating startup processes."""

    lock_path, marker_path = _startup_task_paths(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            has_legacy_json = _has_legacy_json_sources(active_logger)
            bootstrapped = is_database_bootstrapped(conn)
            if bootstrapped:
                active_logger.info("[DB] Existing SQLite runtime detected")
            if not has_legacy_json and bootstrapped:
                active_logger.info("[DB] No legacy JSON files found — skipping migration")
                active_logger.info("[DB] Database already initialized — skipping bundled default seed")
                _write_startup_marker(marker_path)
                return
            if not has_legacy_json and _startup_marker_is_fresh(marker_path):
                active_logger.debug("[DB] Startup JSON migration/seed already completed for this boot")
                return
            if has_legacy_json:
                _migrate_runtime_json_sources(conn, active_logger)
            else:
                active_logger.info("[DB] No legacy JSON files found — skipping migration")
            if bootstrapped:
                active_logger.info("[DB] Database already initialized — skipping bundled default seed")
            else:
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


if __name__ == "__main__":
    import sys as _sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=_sys.stdout,
    )
    try:
        bootstrap_runtime_database()
    except Exception as _exc:
        logging.critical("[DB] Bootstrap failed: %s", _exc)
        _sys.exit(1)
