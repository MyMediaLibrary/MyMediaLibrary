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
        if current_version < 4:
            _apply_v4_recommendations_indexes(conn)
            current_version = 4
        if current_version < 5:
            _apply_v5_active_sessions(conn)
            current_version = 5
        if current_version < 6:
            _apply_v6_media_availability(conn)
            current_version = 6
        if current_version < 7:
            _apply_v7_drop_inventory(conn)
            current_version = 7
        if current_version < 8:
            _apply_v8_unified_providers(conn)
            current_version = 8

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
    # inventory_items no longer exists on fresh installs (dropped in v7).
    # Skip index creation silently; v7 will drop the table on existing DBs.
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory_items'"
    ).fetchone()
    if table_exists:
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


def _apply_v4_recommendations_indexes(conn: sqlite3.Connection) -> None:
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_recommendations_priority ON recommendations(priority)",
        "CREATE INDEX IF NOT EXISTS idx_recommendations_created_at ON recommendations(created_at)",
    ):
        conn.execute(statement)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (4,),
    )


def _apply_v7_drop_inventory(conn: sqlite3.Connection) -> None:
    """Remove the inventory_items table — superseded by media.is_available tracking."""
    conn.execute("DROP TABLE IF EXISTS inventory_items")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (7,),
    )


def _apply_v8_unified_providers(conn: sqlite3.Connection) -> None:
    """Consolidate provider_mappings + provider_logos into the unified providers table."""

    # Step 1: rename providers.name → providers.raw_name on existing DBs (idempotent)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(providers)").fetchall()}
    if "name" in cols and "raw_name" not in cols:
        conn.execute("ALTER TABLE providers RENAME COLUMN name TO raw_name")
    elif "raw_name" not in cols and "name" not in cols:
        raise sqlite3.OperationalError(
            "providers table has neither 'name' nor 'raw_name' column — cannot apply v8 migration"
        )
    # If raw_name already exists (partially or fully migrated DB): skip rename.

    # Step 2: add missing columns (idempotent — existing columns raise OperationalError, ignored)
    for sql in (
        "ALTER TABLE providers ADD COLUMN mapped_name TEXT",
        "ALTER TABLE providers ADD COLUMN is_ignored INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE providers ADD COLUMN logo_path TEXT",
        "ALTER TABLE providers ADD COLUMN created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE providers ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists

    # Step 3: rebuild index under the new column name
    conn.execute("DROP INDEX IF EXISTS idx_providers_name")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_providers_raw_name ON providers(raw_name)")

    # Step 4: merge provider_mappings into providers (if old table still exists)
    pm_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_mappings'"
    ).fetchone()
    if pm_exists:
        conn.execute("""
            INSERT OR IGNORE INTO providers(raw_name, mapped_name, is_ignored)
            SELECT raw_name, mapped_name, is_ignored FROM provider_mappings
        """)
        conn.execute("""
            UPDATE providers
            SET mapped_name = (
                    SELECT mapped_name FROM provider_mappings WHERE raw_name = providers.raw_name
                ),
                is_ignored  = (
                    SELECT is_ignored  FROM provider_mappings WHERE raw_name = providers.raw_name
                ),
                updated_at  = CURRENT_TIMESTAMP
            WHERE EXISTS (
                SELECT 1 FROM provider_mappings WHERE raw_name = providers.raw_name
            )
        """)
        conn.execute("DROP TABLE IF EXISTS provider_mappings")

    # Step 5: merge logo_path from provider_logos into providers (if old table still exists)
    pl_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_logos'"
    ).fetchone()
    if pl_exists:
        # Primary match: logo provider_name == providers.mapped_name
        conn.execute("""
            UPDATE providers
            SET logo_path  = (
                    SELECT logo_path FROM provider_logos WHERE provider_name = providers.mapped_name
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE providers.mapped_name IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM provider_logos WHERE provider_name = providers.mapped_name
              )
        """)
        # Fallback: logo provider_name == providers.raw_name (no mapped_name)
        conn.execute("""
            UPDATE providers
            SET logo_path  = (
                    SELECT logo_path FROM provider_logos WHERE provider_name = providers.raw_name
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE providers.logo_path IS NULL
              AND EXISTS (
                  SELECT 1 FROM provider_logos WHERE provider_name = providers.raw_name
              )
        """)
        conn.execute("DROP TABLE IF EXISTS provider_logos")

    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (8,),
    )


def _apply_v6_media_availability(conn: sqlite3.Connection) -> None:
    """Add disk-state tracking columns to media and create media_probe_cache."""
    # ALTER TABLE is idempotent: ignore "duplicate column name" on fresh DBs
    # where the initial schema already includes these columns.
    for sql in (
        "ALTER TABLE media ADD COLUMN is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1))",
        "ALTER TABLE media ADD COLUMN first_seen_at TEXT",
        "ALTER TABLE media ADD COLUMN last_scanned_at TEXT",
        "ALTER TABLE media ADD COLUMN filename TEXT",
        "ALTER TABLE media ADD COLUMN filename_history TEXT",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists (fresh DB created from current schema)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_probe_cache (
            id INTEGER PRIMARY KEY,
            media_id TEXT NOT NULL,
            filename TEXT,
            file_path TEXT,
            file_size INTEGER,
            modified_at REAL,
            probed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            probe_data TEXT,
            FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
            UNIQUE (media_id, filename)
        )
        """
    )
    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_media_is_available ON media(is_available)",
        "CREATE INDEX IF NOT EXISTS idx_media_first_seen_at ON media(first_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_media_probe_cache_media_id ON media_probe_cache(media_id)",
        "CREATE INDEX IF NOT EXISTS idx_media_probe_cache_lookup ON media_probe_cache(media_id, filename)",
    ):
        conn.execute(sql)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (6,),
    )


def _apply_v5_active_sessions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS active_sessions (
            token TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_sessions_expires_at ON active_sessions(expires_at)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
        (5,),
    )
