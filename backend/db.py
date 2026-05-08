"""SQLite connection and initialization layer for MyMediaLibrary."""

from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

try:
    from backend import db_migrations, runtime_paths
except Exception:
    import db_migrations  # type: ignore
    import runtime_paths  # type: ignore


DEFAULT_DB_PATH = runtime_paths.SQLITE_DB

log = logging.getLogger(__name__)


def open_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with MyMediaLibrary runtime pragmas."""

    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
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

    target = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    active_logger = logger or log
    try:
        conn = initialize_database(target)
    except Exception as exc:
        active_logger.warning("[DB] SQLite unavailable — falling back to JSON: %s", exc)
        return False
    try:
        version = get_schema_version(conn)
        wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        active_logger.info("[DB] SQLite initialized — path=%s", target)
        active_logger.info("[DB] Schema version: %s", version)
        active_logger.info("[DB] WAL enabled: %s", str(wal_mode).casefold() == "wal")
        active_logger.info("[DB] Foreign keys enabled: %s", bool(foreign_keys))
        _migrate_runtime_json_sources(conn, active_logger)
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
