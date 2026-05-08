"""Schema migration helpers for the SQLite database."""

from __future__ import annotations

import sqlite3

try:
    from backend import db_schema
except Exception:
    import db_schema  # type: ignore


class DatabaseMigrationError(RuntimeError):
    """Raised when the database schema is newer than this application."""


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current SQLite user_version for the database."""

    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending schema migrations.

    Version 1 is the initial schema. Future versions should be added as small,
    ordered steps after this first creation pass.
    """

    current_version = get_schema_version(conn)
    if current_version > db_schema.SCHEMA_VERSION:
        raise DatabaseMigrationError(
            f"Database schema version {current_version} is newer than supported "
            f"version {db_schema.SCHEMA_VERSION}"
        )
    if current_version == db_schema.SCHEMA_VERSION:
        return

    with conn:
        if current_version < 1:
            _apply_initial_schema(conn)
            current_version = 1
        if current_version < 2:
            _apply_v2_ffprobe_lookup_index(conn)
            current_version = 2
        if current_version < 3:
            _apply_v3_inventory_indexes(conn)
            current_version = 3

        conn.execute(f"PRAGMA user_version = {current_version}")


def _apply_initial_schema(conn: sqlite3.Connection) -> None:
    for statement in db_schema.CREATE_TABLES_SQL:
        conn.execute(statement)
    for statement in db_schema.CREATE_INDEXES_SQL:
        conn.execute(statement)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (1,),
    )


def _apply_v2_ffprobe_lookup_index(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ffprobe_cache_lookup ON ffprobe_cache(file_path, size, mtime)")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (2,),
    )


def _apply_v3_inventory_indexes(conn: sqlite3.Connection) -> None:
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_inventory_key ON inventory_items(inventory_key)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_folder ON inventory_items(folder)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_media_type ON inventory_items(media_type)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_last_seen_at ON inventory_items(last_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_missing_since ON inventory_items(missing_since)",
    ):
        conn.execute(statement)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (3,),
    )
