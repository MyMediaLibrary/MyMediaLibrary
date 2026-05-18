"""SQLite schema definition for the future MyMediaLibrary database."""

from __future__ import annotations


SCHEMA_VERSION = 22


CREATE_TABLES_SQL = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_config (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        auth_enabled INTEGER NOT NULL DEFAULT 0 CHECK (auth_enabled IN (0, 1)),
        password_hash TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        media_type TEXT,
        enabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
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
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_rules (
        id INTEGER PRIMARY KEY,
        rule_key TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        rule_type TEXT,
        priority TEXT,
        dedupe_group TEXT,
        severity INTEGER,
        conditions_json TEXT,
        message_fr TEXT,
        message_en TEXT,
        suggested_action_fr TEXT,
        suggested_action_en TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media (
        id TEXT PRIMARY KEY,
        media_type TEXT NOT NULL,
        title TEXT NOT NULL,
        raw_name TEXT,
        category TEXT,
        original_title TEXT,
        year INTEGER,
        folder TEXT,
        root_path TEXT,
        path TEXT,
        tmdb_id INTEGER,
        tvdb_id INTEGER,
        imdb_id TEXT,
        overview TEXT,
        poster_path TEXT,
        genres_json TEXT,
        file_count INTEGER,
        size_total INTEGER,
        runtime_min INTEGER,
        runtime_min_avg INTEGER,
        quality_score REAL,
        width INTEGER,
        height INTEGER,
        resolution TEXT,
        video_codec TEXT,
        video_bitrate INTEGER,
        audio_codec TEXT,
        audio_codec_raw TEXT,
        audio_bitrate INTEGER,
        audio_channels TEXT,
        audio_languages_json TEXT,
        audio_language_group TEXT,
        subtitle_languages_json TEXT,
        framerate REAL,
        container TEXT,
        hdr INTEGER CHECK (hdr IN (0, 1)),
        hdr_type TEXT,
        dolby_vision INTEGER CHECK (dolby_vision IN (0, 1)),
        providers_json TEXT,
        data_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT,
        is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1)),
        first_seen_at TEXT,
        last_scanned_at TEXT,
        filename TEXT,
        filename_history TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seasons (
        id INTEGER PRIMARY KEY,
        media_id TEXT NOT NULL,
        season_number INTEGER NOT NULL,
        title TEXT,
        episodes_count INTEGER,
        size_total INTEGER,
        runtime_min INTEGER,
        runtime_min_avg INTEGER,
        quality_score REAL,
        width INTEGER,
        height INTEGER,
        resolution TEXT,
        video_codec TEXT,
        video_bitrate INTEGER,
        audio_codec TEXT,
        audio_codec_raw TEXT,
        audio_bitrate INTEGER,
        audio_channels TEXT,
        audio_languages_json TEXT,
        audio_language_group TEXT,
        subtitle_languages_json TEXT,
        framerate REAL,
        container TEXT,
        hdr INTEGER CHECK (hdr IN (0, 1)),
        hdr_type TEXT,
        dolby_vision INTEGER CHECK (dolby_vision IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
        UNIQUE (media_id, season_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS providers (
        id INTEGER PRIMARY KEY,
        raw_name TEXT NOT NULL UNIQUE,
        mapped_name TEXT,
        is_ignored INTEGER NOT NULL DEFAULT 0,
        logo_path TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media_providers (
        media_id TEXT NOT NULL,
        provider_id INTEGER NOT NULL,
        PRIMARY KEY (media_id, provider_id),
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
        FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendations (
        id TEXT PRIMARY KEY,
        media_id TEXT,
        recommendation_type TEXT NOT NULL,
        priority TEXT,
        rule_id TEXT,
        message_fr TEXT,
        message_en TEXT,
        suggested_action_fr TEXT,
        suggested_action_en TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_runs (
        id INTEGER PRIMARY KEY,
        mode TEXT,
        phases TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        duration_seconds REAL,
        status TEXT NOT NULL,
        summary_json TEXT,
        error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_sessions (
        token TEXT PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media_probe_cache (
        id INTEGER PRIMARY KEY,
        media_id TEXT NOT NULL,
        filename TEXT,
        file_path TEXT,
        file_size INTEGER,
        modified_at REAL,
        probed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        probe_ok INTEGER NOT NULL DEFAULT 0,
        width INTEGER,
        height INTEGER,
        resolution TEXT,
        codec TEXT,
        hdr INTEGER NOT NULL DEFAULT 0,
        hdr_type TEXT,
        runtime_min INTEGER,
        runtime_min_avg INTEGER,
        video_bitrate INTEGER,
        audio_codec TEXT,
        audio_codec_raw TEXT,
        audio_channels TEXT,
        audio_languages_json TEXT,
        subtitle_languages_json TEXT,
        audio_bitrate INTEGER,
        audio_languages_simple TEXT,
        framerate REAL,
        container TEXT,
        dolby_vision INTEGER NOT NULL DEFAULT 0,
        size_b INTEGER,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
        UNIQUE (media_id, filename)
    )
    """,
)


CREATE_INDEXES_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_media_media_type ON media(media_type)",
    "CREATE INDEX IF NOT EXISTS idx_media_title ON media(title)",
    "CREATE INDEX IF NOT EXISTS idx_media_category ON media(category)",
    "CREATE INDEX IF NOT EXISTS idx_media_folder ON media(folder)",
    "CREATE INDEX IF NOT EXISTS idx_media_tmdb_id ON media(tmdb_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_tvdb_id ON media(tvdb_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_imdb_id ON media(imdb_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_quality_score ON media(quality_score)",
    "CREATE INDEX IF NOT EXISTS idx_media_resolution ON media(resolution)",
    "CREATE INDEX IF NOT EXISTS idx_seasons_media_id ON seasons(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_providers_raw_name ON providers(raw_name)",
    "CREATE INDEX IF NOT EXISTS idx_media_providers_media_id ON media_providers(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_providers_provider_id ON media_providers(provider_id)",
    "CREATE INDEX IF NOT EXISTS idx_recommendations_media_id ON recommendations(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_recommendations_type_priority ON recommendations(recommendation_type, priority)",
    "CREATE INDEX IF NOT EXISTS idx_recommendations_priority ON recommendations(priority)",
    "CREATE INDEX IF NOT EXISTS idx_recommendations_created_at ON recommendations(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_active_sessions_expires_at ON active_sessions(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_media_is_available ON media(is_available)",
    "CREATE INDEX IF NOT EXISTS idx_media_first_seen_at ON media(first_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_media_probe_cache_media_id ON media_probe_cache(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_probe_cache_lookup ON media_probe_cache(media_id, filename)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_rules_rule_type ON recommendation_rules(rule_type)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_rules_priority ON recommendation_rules(priority)",
    "CREATE INDEX IF NOT EXISTS idx_recommendation_rules_enabled ON recommendation_rules(enabled)",
    "CREATE INDEX IF NOT EXISTS idx_score_rules_category ON score_rules(category)",
    "CREATE INDEX IF NOT EXISTS idx_score_rules_lookup ON score_rules(category, group_key, value_key)",
)


EXPECTED_TABLES = frozenset(
    {
        "schema_migrations",
        "app_config",
        "auth_settings",
        "folders",
        "score_rules",
        "score_size_profiles",
        "recommendation_rules",
        "media",
        "seasons",
        "providers",
        "media_providers",
        "recommendations",
        "scan_runs",
        "active_sessions",
        "media_probe_cache",
    }
)


EXPECTED_INDEXES = frozenset(
    sql.split()[5] for sql in CREATE_INDEXES_SQL
)
