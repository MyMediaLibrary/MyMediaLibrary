"""Schema migration helpers for the SQLite database."""

from __future__ import annotations

import json as _json
import logging
import os
import sqlite3

try:
    from backend import db_schema
except Exception:
    import db_schema  # type: ignore

log = logging.getLogger(__name__)


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
        if current_version < 9:
            _apply_v9_drop_ffprobe_cache(conn)
            current_version = 9
        if current_version < 10:
            _apply_v10_drop_scan_settings(conn)
            current_version = 10
        if current_version < 11:
            _apply_v11_drop_dead_tables(conn)
            current_version = 11
        if current_version < 12:
            _apply_v12_flatten_app_config_blobs(conn)
            current_version = 12
        if current_version < 13:
            _apply_v13_drop_recommendation_json_columns(conn)
            current_version = 13
        if current_version < 14:
            _apply_v14_recommendation_rules_extract_scalars(conn)
            current_version = 14
        if current_version < 15:
            _apply_v15_drop_dead_columns(conn)
            current_version = 15
        if current_version < 16:
            _apply_v16_recommendation_rules_structured(conn)
            current_version = 16
        if current_version < 17:
            _apply_v17_recommendations_drop_redundant_columns(conn)
            current_version = 17
        if current_version < 18:
            _apply_v18_recommendations_replace_details_json(conn)
            current_version = 18
        if current_version < 19:
            _apply_v19_replace_score_settings(conn)
            current_version = 19

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
    # ffprobe_cache is dropped in v9; skip index creation on fresh installs where the table never existed.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ffprobe_cache'"
    ).fetchone():
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


def _apply_v9_drop_ffprobe_cache(conn: sqlite3.Connection) -> None:
    """Migrate ffprobe_cache data into media_probe_cache, then drop ffprobe_cache.

    Matching strategy: extract the filename (basename) from ffprobe_cache.file_path and
    look up the media row whose filename column equals it (direct match for movies) or
    contains it as a JSON string value (series). Rows that cannot be matched to a
    media_id are logged as orphaned and skipped — they cannot be imported into
    media_probe_cache because that table requires a media_id FK.

    The migration is idempotent: INSERT OR IGNORE skips existing (media_id, filename)
    pairs and DROP TABLE IF EXISTS is a no-op when the table is already gone.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ffprobe_cache'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (9,))
        return

    rows = conn.execute(
        "SELECT file_path, size, mtime, probed_at, normalized_json FROM ffprobe_cache"
    ).fetchall()

    migrated = 0
    skipped = 0
    orphaned = 0

    for row in rows:
        file_path = row[0] or ""
        filename = os.path.basename(file_path)
        probe_data = row[4]

        if not filename or probe_data is None:
            orphaned += 1
            continue

        # Try exact filename match (movies store a plain string in media.filename).
        media = conn.execute(
            "SELECT id FROM media WHERE filename = ? LIMIT 1", (filename,)
        ).fetchone()

        # Fallback: JSON containment match (series store a nested JSON object).
        if media is None:
            media = conn.execute(
                'SELECT id FROM media WHERE filename LIKE ? LIMIT 1',
                (f'%"{filename}"%',),
            ).fetchone()

        if media is None:
            orphaned += 1
            continue

        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO media_probe_cache
                    (media_id, filename, file_path, file_size, modified_at, probed_at, probe_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (media[0], filename, file_path, row[1], row[2], row[3], probe_data),
            )
            if cursor.rowcount > 0:
                migrated += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    conn.execute("DROP TABLE IF EXISTS ffprobe_cache")
    log.info(
        "[DB] v9: ffprobe_cache → media_probe_cache — migrated=%d skipped=%d orphaned=%d",
        migrated,
        skipped,
        orphaned,
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (9,))


def _apply_v10_drop_scan_settings(conn: sqlite3.Connection) -> None:
    """Migrate scan_settings.media_probe blob into flat app_config keys, then drop scan_settings.

    The media_probe JSON dict (e.g. {"enabled":false,"mode":"compare","workers":4,"cache_enabled":true})
    is expanded into individual app_config rows keyed as media_probe.<subkey>.

    The migration is idempotent:
    - INSERT OR IGNORE skips flat keys that already exist in app_config.
    - DROP TABLE IF EXISTS is a no-op when scan_settings is already gone.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scan_settings'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (10,))
        return

    row = conn.execute(
        "SELECT value_json FROM scan_settings WHERE id = 'media_probe'"
    ).fetchone()

    migrated = 0
    skipped = 0
    missing = 0

    if row is not None:
        try:
            probe = _json.loads(row[0] or "{}")
            if isinstance(probe, dict):
                for subkey, subval in probe.items():
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO app_config(key, value_json) VALUES (?, ?)",
                        (
                            f"media_probe.{subkey}",
                            _json.dumps(subval, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                    if cursor.rowcount > 0:
                        migrated += 1
                    else:
                        skipped += 1
        except Exception:
            missing += 1
    else:
        missing += 1

    conn.execute("DROP TABLE IF EXISTS scan_settings")
    log.info(
        "[DB] v10: scan_settings → app_config (media_probe.*) — migrated=%d skipped=%d missing=%d",
        migrated,
        skipped,
        missing,
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (10,))


def _apply_v15_drop_dead_columns(conn: sqlite3.Connection) -> None:
    """Drop columns that are written but never read back, or never written at all.

    media.missing_since  — never written in v0.5.x; superseded by is_available + last_seen_at.
    media.quality_json   — written as a duplicate of data_json.quality; never SELECTed.
    seasons.quality_json — same rationale as media.quality_json.

    All three DROPs are idempotent via PRAGMA table_info checks.
    SQLite 3.35+ DROP COLUMN is used throughout.
    """
    drops = [
        ("media",   "missing_since"),
        ("media",   "quality_json"),
        ("seasons", "quality_json"),
    ]
    for table, col in drops:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col in cols:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    log.info("[DB] v15: dropped media.missing_since, media.quality_json, seasons.quality_json")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (15,))


def _apply_v14_recommendation_rules_extract_scalars(conn: sqlite3.Connection) -> None:
    """Add rule_type and priority columns to recommendation_rules, populated from rule_json.

    Both columns are added via ALTER TABLE (idempotent — existing columns are skipped).
    Rows already having non-NULL values in either column are not updated (preserves user edits).
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recommendation_rules'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (14,))
        return

    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}
    for col in ("rule_type", "priority"):
        if col not in cols:
            conn.execute(f"ALTER TABLE recommendation_rules ADD COLUMN {col} TEXT")

    if "rule_json" not in cols:
        log.info("[DB] v14: recommendation_rules — rule_json absent, skipped")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (14,))
        return

    rows = conn.execute(
        "SELECT id, rule_json, rule_type, priority FROM recommendation_rules"
        " WHERE rule_type IS NULL OR priority IS NULL"
    ).fetchall()

    migrated = 0
    skipped = 0
    malformed = 0

    for row in rows:
        try:
            rule = _json.loads(row[1] or "{}")
        except Exception:
            malformed += 1
            continue
        if not isinstance(rule, dict):
            malformed += 1
            continue
        new_type = row[2] or str(rule.get("type") or "") or None
        new_priority = row[3] or str(rule.get("priority") or "") or None
        if new_type is None and new_priority is None:
            skipped += 1
            continue
        conn.execute(
            "UPDATE recommendation_rules SET rule_type = ?, priority = ? WHERE id = ?",
            (new_type, new_priority, row[0]),
        )
        migrated += 1

    log.info(
        "[DB] v14: recommendation_rules extract scalars — migrated=%d skipped=%d malformed=%d",
        migrated,
        skipped,
        malformed,
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (14,))


def _apply_v19_replace_score_settings(conn: sqlite3.Connection) -> None:
    """Replace score_settings with score_rules + score_size_profiles, and score.enabled in app_config.

    Idempotent: if score_settings no longer exists (already migrated or fresh v19 install),
    the function simply ensures the new tables exist and marks the version.
    """
    try:
        from backend.scoring import flatten_score_to_rules, flatten_score_to_size_profiles
    except Exception:
        from scoring import flatten_score_to_rules, flatten_score_to_size_profiles  # type: ignore

    conn.execute("""
        CREATE TABLE IF NOT EXISTS score_rules (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            group_key TEXT NOT NULL,
            value_key TEXT NOT NULL,
            score_value REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, group_key, value_key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS score_size_profiles (
            id INTEGER PRIMARY KEY,
            media_type TEXT NOT NULL,
            resolution_key TEXT NOT NULL,
            codec_key TEXT NOT NULL,
            min_gb REAL NOT NULL,
            max_gb REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(media_type, resolution_key, codec_key)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_score_rules_category ON score_rules(category)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_score_rules_lookup ON score_rules(category, group_key, value_key)"
    )

    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='score_settings'"
    ).fetchone():
        log.info("[DB] v19: score_settings absent — new tables created, skipped data migration")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (19,))
        return

    row = conn.execute(
        "SELECT enabled, configuration_json FROM score_settings WHERE id = 'default'"
    ).fetchone()

    if row is not None:
        enabled = bool(row[0])
        try:
            score_config = _json.loads(row[1] or "{}")
        except Exception:
            score_config = {}
            log.warning("[DB] v19: malformed configuration_json in score_settings — treating as empty")
        if not isinstance(score_config, dict):
            score_config = {}

        conn.execute(
            "INSERT OR IGNORE INTO app_config(key, value_json) VALUES ('score.enabled', ?)",
            (_json.dumps(enabled),),
        )
        rules = flatten_score_to_rules(score_config)
        profiles = flatten_score_to_size_profiles(score_config)
        for (category, group_key, value_key, score_value) in rules:
            conn.execute(
                "INSERT OR IGNORE INTO score_rules(category, group_key, value_key, score_value)"
                " VALUES (?, ?, ?, ?)",
                (category, group_key, value_key, score_value),
            )
        for (media_type, res_key, codec_key, min_gb, max_gb) in profiles:
            conn.execute(
                "INSERT OR IGNORE INTO score_size_profiles"
                "(media_type, resolution_key, codec_key, min_gb, max_gb) VALUES (?, ?, ?, ?, ?)",
                (media_type, res_key, codec_key, min_gb, max_gb),
            )
        log.info(
            "[DB] v19: score_settings migrated — enabled=%s rules=%d profiles=%d",
            enabled, len(rules), len(profiles),
        )

    conn.execute("DROP TABLE IF EXISTS score_settings")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (19,))


def _apply_v18_recommendations_replace_details_json(conn: sqlite3.Connection) -> None:
    """Replace recommendations.details_json with message_fr/en and suggested_action_fr/en columns.

    Adds the four message/action columns, migrates values from details_json,
    then drops details_json. Idempotent: safe to call when details_json is
    already absent (fresh v18 DB).
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recommendations'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (18,))
        return

    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()}

    for col in ("message_fr", "message_en", "suggested_action_fr", "suggested_action_en"):
        if col not in cols:
            conn.execute(f"ALTER TABLE recommendations ADD COLUMN {col} TEXT")

    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()}

    if "details_json" not in cols:
        log.info("[DB] v18: recommendations — details_json already absent, skipped")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (18,))
        return

    rows = conn.execute("SELECT id, details_json FROM recommendations").fetchall()
    migrated = malformed = 0

    for row in rows:
        try:
            item = _json.loads(row[1] or "{}")
        except Exception:
            malformed += 1
            log.warning("[DB] v18: malformed details_json for recommendation id=%s", row[0])
            continue
        if not isinstance(item, dict):
            malformed += 1
            continue

        msg = item.get("message") or {}
        action = item.get("suggested_action") or {}
        conn.execute(
            """
            UPDATE recommendations SET
                message_fr          = COALESCE(message_fr, ?),
                message_en          = COALESCE(message_en, ?),
                suggested_action_fr = COALESCE(suggested_action_fr, ?),
                suggested_action_en = COALESCE(suggested_action_en, ?)
            WHERE id = ?
            """,
            (
                msg.get("fr") or None,
                msg.get("en") or None,
                action.get("fr") or None,
                action.get("en") or None,
                row[0],
            ),
        )
        migrated += 1

    conn.execute("ALTER TABLE recommendations DROP COLUMN details_json")

    log.info(
        "[DB] v18: recommendations replace details_json — migrated=%d malformed=%d",
        migrated,
        malformed,
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (18,))


def _apply_v17_recommendations_drop_redundant_columns(conn: sqlite3.Connection) -> None:
    """Drop title, reason, dedupe_group, severity from recommendations.

    These columns were denormalised redundancies; v18 then replaced details_json
    with explicit message_fr/en and suggested_action_fr/en columns.
    Uses ALTER TABLE DROP COLUMN (SQLite 3.35+, idempotent via PRAGMA table_info).
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recommendations'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (17,))
        return

    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
    for col in ("title", "reason", "dedupe_group", "severity"):
        if col in cols:
            conn.execute(f"ALTER TABLE recommendations DROP COLUMN {col}")

    log.info("[DB] v17: recommendations — dropped title, reason, dedupe_group, severity")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (17,))


def _apply_v16_recommendation_rules_structured(conn: sqlite3.Connection) -> None:
    """Flatten recommendation_rules.rule_json into structured columns.

    Adds dedupe_group, severity, conditions_json, message_fr/en, suggested_action_fr/en
    and created_at columns (idempotent — existing columns are skipped).
    Migrates data from rule_json into the new columns, then drops rule_json.
    Safe to call when rule_json is already absent (fresh v16 DB).
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recommendation_rules'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (16,))
        return

    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}

    new_cols = {
        "dedupe_group": "TEXT",
        "severity": "INTEGER",
        "conditions_json": "TEXT",
        "message_fr": "TEXT",
        "message_en": "TEXT",
        "suggested_action_fr": "TEXT",
        "suggested_action_en": "TEXT",
        "created_at": "TEXT",
    }
    for col, col_type in new_cols.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE recommendation_rules ADD COLUMN {col} {col_type}")
    conn.execute(
        "UPDATE recommendation_rules SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )

    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendation_rules)").fetchall()}

    if "rule_json" not in cols:
        log.info("[DB] v16: recommendation_rules structured — rule_json already absent, skipped")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (16,))
        return

    rows = conn.execute("SELECT id, rule_key, rule_json FROM recommendation_rules").fetchall()
    migrated = 0
    skipped = 0
    malformed = 0

    for row in rows:
        try:
            rule = _json.loads(row[2] or "{}")
        except Exception:
            malformed += 1
            log.warning("[DB] v16: malformed rule_json for rule_key=%s", row[1])
            continue
        if not isinstance(rule, dict):
            malformed += 1
            continue

        msg = rule.get("message") or {}
        action = rule.get("suggested_action") or {}
        conditions = rule.get("conditions")
        conditions_json = (
            _json.dumps(conditions, ensure_ascii=False, separators=(",", ":"))
            if isinstance(conditions, list)
            else None
        )

        conn.execute(
            """
            UPDATE recommendation_rules SET
                dedupe_group      = COALESCE(dedupe_group, ?),
                severity          = COALESCE(severity, ?),
                conditions_json   = COALESCE(conditions_json, ?),
                message_fr        = COALESCE(message_fr, ?),
                message_en        = COALESCE(message_en, ?),
                suggested_action_fr = COALESCE(suggested_action_fr, ?),
                suggested_action_en = COALESCE(suggested_action_en, ?)
            WHERE id = ?
            """,
            (
                str(rule.get("dedupe_group") or "") or None,
                rule.get("severity"),
                conditions_json,
                msg.get("fr") or None,
                msg.get("en") or None,
                action.get("fr") or None,
                action.get("en") or None,
                row[0],
            ),
        )
        migrated += 1

    conn.execute("ALTER TABLE recommendation_rules DROP COLUMN rule_json")

    log.info(
        "[DB] v16: recommendation_rules structured — migrated=%d skipped=%d malformed=%d",
        migrated,
        skipped,
        malformed,
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (16,))


def _apply_v13_drop_recommendation_json_columns(conn: sqlite3.Connection) -> None:
    """Drop the redundant message_json and suggested_action_json columns from recommendations.

    details_json is the canonical source for both fields. The two dedicated columns
    were a write-through cache that could drift; dropping them removes the redundancy.
    SQLite 3.35+ DROP COLUMN is used (idempotent via PRAGMA table_info check).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()}
    for col in ("message_json", "suggested_action_json"):
        if col in cols:
            conn.execute(f"ALTER TABLE recommendations DROP COLUMN {col}")
    log.info("[DB] v13: dropped recommendations.message_json and suggested_action_json")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (13,))


def _apply_v12_flatten_app_config_blobs(conn: sqlite3.Connection) -> None:
    """Expand system/seerr/ui/recommendations blobs into flat app_config keys.

    Blobs stored under the group name are expanded into group.subkey rows.
    INSERT OR IGNORE preserves any existing flat keys (never overwrites user data).
    The blob key itself is then removed so only flat keys remain.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_config'"
    ).fetchone():
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (12,))
        return

    _GROUPS = ("system", "seerr", "ui", "recommendations")
    migrated = 0
    skipped = 0
    for group in _GROUPS:
        row = conn.execute(
            "SELECT value_json FROM app_config WHERE key = ?", (group,)
        ).fetchone()
        if row is None:
            continue
        try:
            blob = _json.loads(row[0] or "{}")
        except Exception:
            blob = {}
        if isinstance(blob, dict):
            for subkey, subval in blob.items():
                try:
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO app_config(key, value_json) VALUES (?, ?)",
                        (f"{group}.{subkey}", _json.dumps(subval, ensure_ascii=False, separators=(",", ":"))),
                    )
                    if cursor.rowcount > 0:
                        migrated += 1
                    else:
                        skipped += 1
                except Exception:
                    skipped += 1
        conn.execute("DELETE FROM app_config WHERE key = ?", (group,))
    log.info("[DB] v12: flatten app_config blobs — migrated=%d skipped=%d", migrated, skipped)
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (12,))


def _apply_v11_drop_dead_tables(conn: sqlite3.Connection) -> None:
    """Drop the episodes, files, and streams tables — never populated, superseded by media.data_json.

    Drop order respects FK constraints: streams → files → episodes.
    All three DROPs are IF EXISTS so the migration is idempotent.
    """
    conn.execute("DROP TABLE IF EXISTS streams")
    conn.execute("DROP TABLE IF EXISTS files")
    conn.execute("DROP TABLE IF EXISTS episodes")
    log.info("[DB] v11: dropped dead tables — streams, files, episodes")
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (11,))
