"""SQLite connection and initialization layer for MyMediaLibrary."""

from __future__ import annotations

import sqlite3
from pathlib import Path

try:
    from backend import db_migrations, runtime_paths
except Exception:
    import db_migrations  # type: ignore
    import runtime_paths  # type: ignore


DEFAULT_DB_PATH = runtime_paths.SQLITE_DB


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


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Expose schema version lookup from the migration layer."""

    return db_migrations.get_schema_version(conn)
