"""SQLite schema definition for the future MyMediaLibrary database."""

from __future__ import annotations


SCHEMA_VERSION = 1


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
    CREATE TABLE IF NOT EXISTS scan_settings (
        id TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS score_settings (
        id TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        configuration_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_rules (
        id INTEGER PRIMARY KEY,
        rule_key TEXT NOT NULL UNIQUE,
        rule_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_mappings (
        id INTEGER PRIMARY KEY,
        raw_name TEXT NOT NULL UNIQUE,
        mapped_name TEXT,
        is_ignored INTEGER NOT NULL DEFAULT 0 CHECK (is_ignored IN (0, 1)),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_logos (
        id INTEGER PRIMARY KEY,
        provider_name TEXT NOT NULL UNIQUE,
        logo_path TEXT,
        logo_url TEXT,
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
        quality_json TEXT,
        data_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT,
        missing_since TEXT
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
        quality_json TEXT,
        data_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
        UNIQUE (media_id, season_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY,
        media_id TEXT NOT NULL,
        season_id INTEGER,
        season_number INTEGER,
        episode_number INTEGER,
        title TEXT,
        overview TEXT,
        air_date TEXT,
        path TEXT,
        size INTEGER,
        duration REAL,
        quality_json TEXT,
        data_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
        FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE SET NULL,
        UNIQUE (media_id, season_number, episode_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        media_id TEXT,
        season_id INTEGER,
        episode_id INTEGER,
        path TEXT NOT NULL,
        relative_path TEXT,
        file_name TEXT,
        size INTEGER,
        mtime REAL,
        duration REAL,
        container TEXT,
        data_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT,
        missing_since TEXT,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE,
        FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE SET NULL,
        FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE SET NULL,
        UNIQUE (path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS streams (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        stream_type TEXT NOT NULL,
        stream_index INTEGER,
        codec TEXT,
        language TEXT,
        channels INTEGER,
        bitrate INTEGER,
        width INTEGER,
        height INTEGER,
        resolution TEXT,
        hdr INTEGER CHECK (hdr IN (0, 1)),
        dolby_vision INTEGER CHECK (dolby_vision IN (0, 1)),
        framerate REAL,
        profile TEXT,
        bit_depth INTEGER,
        extra_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
        UNIQUE (file_id, stream_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS providers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
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
        title TEXT NOT NULL,
        reason TEXT,
        rule_id TEXT,
        dedupe_group TEXT,
        severity INTEGER,
        message_json TEXT,
        suggested_action_json TEXT,
        details_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory_items (
        id TEXT PRIMARY KEY,
        media_id TEXT,
        inventory_key TEXT NOT NULL UNIQUE,
        media_type TEXT,
        title TEXT,
        category TEXT,
        folder TEXT,
        path TEXT,
        first_seen_at TEXT,
        last_seen_at TEXT,
        last_checked_at TEXT,
        missing_since TEXT,
        status TEXT,
        data_json TEXT,
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
    CREATE TABLE IF NOT EXISTS ffprobe_cache (
        id INTEGER PRIMARY KEY,
        file_path TEXT NOT NULL,
        size INTEGER,
        mtime REAL,
        probed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL,
        normalized_json TEXT,
        error TEXT,
        UNIQUE (file_path, size, mtime)
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
    "CREATE INDEX IF NOT EXISTS idx_episodes_media_id ON episodes(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_media_season_episode ON episodes(media_id, season_number, episode_number)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_season_id ON episodes(season_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_media_id ON files(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_season_id ON files(season_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_episode_id ON files(episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)",
    "CREATE INDEX IF NOT EXISTS idx_providers_name ON providers(name)",
    "CREATE INDEX IF NOT EXISTS idx_streams_file_id ON streams(file_id)",
    "CREATE INDEX IF NOT EXISTS idx_streams_file_type ON streams(file_id, stream_type)",
    "CREATE INDEX IF NOT EXISTS idx_media_providers_media_id ON media_providers(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_providers_provider_id ON media_providers(provider_id)",
    "CREATE INDEX IF NOT EXISTS idx_recommendations_media_id ON recommendations(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_recommendations_type_priority ON recommendations(recommendation_type, priority)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_items_media_id ON inventory_items(media_id)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_items_path ON inventory_items(path)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_items_status ON inventory_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_ffprobe_cache_file_path ON ffprobe_cache(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_ffprobe_cache_file_signature ON ffprobe_cache(file_path, size, mtime)",
)


EXPECTED_TABLES = frozenset(
    {
        "schema_migrations",
        "app_config",
        "auth_settings",
        "scan_settings",
        "score_settings",
        "recommendation_rules",
        "provider_mappings",
        "provider_logos",
        "media",
        "seasons",
        "episodes",
        "files",
        "streams",
        "providers",
        "media_providers",
        "recommendations",
        "inventory_items",
        "scan_runs",
        "ffprobe_cache",
    }
)


EXPECTED_INDEXES = frozenset(
    sql.split()[5] for sql in CREATE_INDEXES_SQL
)
