"""Non-destructive JSON to SQLite import helpers."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from backend import db, runtime_paths
    from backend.scoring import (
        flatten_score_to_rules,
        flatten_score_to_size_profiles,
        reconstruct_score_config_from_rows,
    )
except Exception:
    import db  # type: ignore
    import runtime_paths  # type: ignore
    from scoring import (  # type: ignore
        flatten_score_to_rules,
        flatten_score_to_size_profiles,
        reconstruct_score_config_from_rows,
    )


log = logging.getLogger(__name__)

_CONFIG_FLAT_GROUPS = ("system", "seerr", "ui", "recommendations", "media_probe")
# folders and providers_visible go to dedicated tables / providers.is_ignored
_CONFIG_STRUCTURED_KEYS = {"auth", "score", "score_configuration", "folders", "providers_visible"} | set(_CONFIG_FLAT_GROUPS)
_CONFIG_IMPORTABLE_KEYS = {
    "system",
    "scan",
    "auth",
    "score",
    "score_configuration",
    "recommendations",
    "seerr",
    "folders",
    "enable_movies",
    "enable_series",
    "providers_visible",
    "ui",
    "media_probe",
}
_CONFIG_NON_CONFIG_KEYS = {
    "runtime_library_document",
    "library",
    "items",
    "categories",
    "media",
    ".secrets",
    "secrets",
}
_CONFIG_DIFF_LIMIT = 50
_SENSITIVE_TOKENS = ("apikey", "api_key", "token", "secret", "password", "access_token", "refresh_token", "hash")


@dataclass
class ImportReport:
    """Summary of a JSON to DB import pass."""

    imported: dict[str, int] = field(default_factory=dict)
    skipped_missing: list[str] = field(default_factory=list)
    invalid_json: list[str] = field(default_factory=list)

    def add(self, name: str, count: int) -> None:
        self.imported[name] = self.imported.get(name, 0) + int(count)


@dataclass
class StartupJsonMigrationResult:
    """Result for one startup JSON import/validation/cleanup step."""

    name: str
    path: Path
    status: str
    source_count: int | None = None
    source_total_count: int | None = None
    db_count: int | None = None
    removed: bool = False
    warning: str | None = None


def import_runtime_json_files(
    db_path: str | Path | None = None,
    *,
    paths=runtime_paths,
) -> ImportReport:
    """Import all known runtime JSON files into SQLite without deleting them."""

    conn = db.initialize_database(db_path)
    try:
        report = ImportReport()
        import_providers_logo(conn, paths.PROVIDERS_LOGO_JSON, report)
        import_providers_mapping(conn, paths.PROVIDERS_MAPPING_JSON, report, overwrite=True)
        import_recommendation_rules(conn, paths.RECOMMENDATIONS_RULES_JSON, report)
        import_config(conn, paths.CONFIG_JSON, report)
        import_recommendations(conn, paths.RECOMMENDATIONS_JSON, report)
        import_library(conn, paths.LIBRARY_JSON, report)
        return report
    finally:
        conn.close()


def migrate_runtime_json_files_at_startup(
    conn: sqlite3.Connection,
    *,
    paths=runtime_paths,
    logger: logging.Logger | None = None,
    remove_validated: bool = True,
) -> list[StartupJsonMigrationResult]:
    """Import runtime JSON files, validate row counts, and remove validated sources."""

    active_logger = logger or log
    specs = _startup_json_specs(paths)
    results: list[StartupJsonMigrationResult] = []
    warnings = False

    active_logger.info("[DB] JSON migration starting")
    data_dir = Path(paths.CONFIG_JSON).parent
    active_logger.info("[DB] Legacy JSON scan path: %s", data_dir)
    _remove_obsolete_runtime_files(paths, active_logger)
    for spec in specs:
        result = _migrate_one_startup_json(conn, spec, active_logger, remove_validated=remove_validated)
        results.append(result)
        if result.status not in ("ok", "skipped"):
            warnings = True

    active_logger.info("[DB] JSON migration cleanup summary:")
    for result in results:
        suffix = ""
        if result.status == "ok" and result.removed:
            suffix = " removed"
        elif result.status == "warning":
            suffix = " kept"
        active_logger.info("[DB]   %s: %s%s", result.path.name, result.status.upper(), suffix)
    if warnings:
        active_logger.warning("[DB] JSON migration completed with warnings — source files kept for review")
    else:
        active_logger.info("[DB] JSON migration completed successfully")
    return results


def seed_bundled_defaults(
    conn: sqlite3.Connection,
    *,
    logger: logging.Logger | None = None,
) -> dict[str, int]:
    """Seed defaults from Python constants into SQLite (idempotent, INSERT OR IGNORE)."""
    try:
        from backend import db_seed
    except Exception:
        import db_seed  # type: ignore
    return db_seed.seed_all(conn, logger=logger)


def legacy_json_paths(*, paths=runtime_paths) -> list[Path]:
    """Return legacy JSON sources that may be imported once into SQLite."""

    return [
        Path(paths.CONFIG_JSON),
        Path(paths.PROVIDERS_MAPPING_JSON),
        Path(paths.PROVIDERS_LOGO_JSON),
        Path(paths.RECOMMENDATIONS_RULES_JSON),
        Path(paths.MEDIA_PROBE_CACHE_JSON),
        Path(paths.LIBRARY_JSON),
        Path(paths.RECOMMENDATIONS_JSON),
    ]


def list_detected_legacy_json_files(*, paths=runtime_paths) -> list[Path]:
    """Return legacy JSON sources that currently exist on disk."""
    return [path for path in legacy_json_paths(paths=paths) if path.exists()]


def has_legacy_json_files(*, paths=runtime_paths) -> bool:
    """Return True when at least one legacy runtime JSON source still exists."""

    return bool(list_detected_legacy_json_files(paths=paths))


def _startup_json_specs(paths) -> list[dict[str, Any]]:
    return [
        {
            "name": "config",
            "path": Path(paths.CONFIG_JSON),
            "source_total_count": _count_config_total_source,
            "source_count": _count_config_source,
            "db_count": _count_config_db,
            "import": lambda conn, path: import_config(conn, path, overwrite=True),
        },
        {
            "name": "providers_mapping",
            "path": Path(paths.PROVIDERS_MAPPING_JSON),
            "source_count": _count_mapping_source,
            "db_count": lambda conn: conn.execute(
                "SELECT COUNT(*) FROM providers WHERE mapped_name IS NOT NULL OR is_ignored = 1"
            ).fetchone()[0],
            "import": lambda conn, path: import_providers_mapping(conn, path, overwrite=True),
            # DB may have more entries from Python seed than user's legacy JSON — that's fine
            "valid_when": lambda source_count, db_count: db_count >= source_count,
        },
        {
            "name": "providers_logo",
            "path": Path(paths.PROVIDERS_LOGO_JSON),
            "source_count": _count_mapping_source,
            "db_count": lambda conn: conn.execute(
                "SELECT COUNT(*) FROM providers WHERE logo_path IS NOT NULL"
            ).fetchone()[0],
            "import": import_providers_logo,
            "valid_when": lambda source_count, db_count: db_count >= source_count,
        },
        {
            "name": "recommendation_rules",
            "path": Path(paths.RECOMMENDATIONS_RULES_JSON),
            "source_count": _count_rules_source,
            "db_count": lambda conn: _table_count(conn, "recommendation_rules"),
            "import": import_recommendation_rules,
            # DB may have more default rules than user's legacy JSON — that's fine
            "valid_when": lambda source_count, db_count: db_count >= source_count,
        },
        {
            "name": "library",
            "path": Path(paths.LIBRARY_JSON),
            "source_count": _count_items_source,
            "db_count": lambda conn: _table_count(conn, "media"),
            "import": import_library,
        },
        {
            "name": "recommendations",
            "path": Path(paths.RECOMMENDATIONS_JSON),
            "source_count": _count_items_source,
            "db_count": lambda conn: _table_count(conn, "recommendations"),
            "import": import_recommendations,
        },
    ]


def _migrate_one_startup_json(
    conn: sqlite3.Connection,
    spec: dict[str, Any],
    active_logger: logging.Logger,
    *,
    remove_validated: bool,
) -> StartupJsonMigrationResult:
    name = spec["name"]
    path = Path(spec["path"])
    if not path.exists():
        active_logger.info("[DB] Import skipped — %s not found", path.name)
        return StartupJsonMigrationResult(name=name, path=path, status="skipped")

    payload = _read_json(path, name, None)
    if payload is None:
        active_logger.warning("[DB] Import check failed for %s — invalid JSON — keeping source file for review", path.name)
        return StartupJsonMigrationResult(name=name, path=path, status="warning", warning="invalid_json")

    source_count = spec["source_count"](payload)
    source_total_count = (spec.get("source_total_count") or spec["source_count"])(payload)
    spec["import"](conn, path)
    db_count = spec["db_count"](conn)
    if name == "config":
        validation = _validate_config_import(conn, payload)
        if validation["valid"]:
            active_logger.info("[DB] Import check passed for %s — removing migrated source file", path.name)
            removed = _remove_validated_source(path, active_logger) if remove_validated else False
            return StartupJsonMigrationResult(
                name=name,
                path=path,
                status="ok",
                source_count=source_count,
                source_total_count=source_total_count,
                db_count=db_count,
                removed=removed,
            )
        active_logger.warning("[DB] Import check failed for %s — keeping source file for review", path.name)
        _log_config_import_diff(validation["differences"], active_logger)
        return StartupJsonMigrationResult(
            name=name,
            path=path,
            status="warning",
            source_count=source_count,
            source_total_count=source_total_count,
            db_count=db_count,
            warning="config_diff",
        )

    valid_when = spec.get("valid_when") or (lambda source_count, db_count: source_count == db_count)
    if valid_when(source_count, db_count):
        removed = False
        if source_total_count != source_count:
            active_logger.info(
                "[DB] Import check %s — json=%s importable=%s db=%s — OK",
                path.name,
                source_total_count,
                source_count,
                db_count,
            )
        else:
            active_logger.info("[DB] Import check %s — json=%s db=%s — OK", path.name, source_count, db_count)
        if remove_validated:
            try:
                removed = _remove_validated_source(path, active_logger)
            except Exception as exc:
                return StartupJsonMigrationResult(
                    name=name,
                    path=path,
                    status="warning",
                    source_count=source_count,
                    db_count=db_count,
                    warning=str(exc),
                )
        return StartupJsonMigrationResult(
            name=name,
            path=path,
            status="ok",
            source_count=source_count,
            source_total_count=source_total_count,
            db_count=db_count,
            removed=removed,
        )

    if source_total_count != source_count:
        active_logger.warning(
            "[DB] Import check failed for %s — json=%s importable=%s db=%s — keeping source file for review",
            path.name,
            source_total_count,
            source_count,
            db_count,
        )
    else:
        active_logger.warning(
            "[DB] Import check failed for %s — json=%s db=%s — keeping source file for review",
            path.name,
            source_count,
            db_count,
        )
    return StartupJsonMigrationResult(
        name=name,
        path=path,
        status="warning",
        source_count=source_count,
        source_total_count=source_total_count,
        db_count=db_count,
        warning="count_mismatch",
    )


def _remove_validated_source(path: Path, active_logger: logging.Logger) -> bool:
    try:
        path.unlink()
        active_logger.info("[DB] Removed migrated file %s", path)
        return True
    except FileNotFoundError:
        return True
    except Exception as exc:
        active_logger.warning("[DB] Could not remove migrated file %s: %s", path, exc)
        raise


def _remove_obsolete_runtime_files(paths, active_logger: logging.Logger) -> None:
    for attr in ("LIBRARY_PROBE_JSON",):
        obsolete = getattr(paths, attr, None)
        if obsolete is None:
            continue
        path = Path(obsolete)
        if not path.exists():
            continue
        try:
            path.unlink()
            active_logger.info("[DB] Removed obsolete file %s", path)
        except Exception as exc:
            active_logger.warning("[DB] Could not remove obsolete file %s: %s", path, exc)


def import_providers_logo(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    """Import {display_name: logo_path} into the unified providers table.

    Logo key is matched to mapped_name first, then to raw_name as fallback.
    If no match exists, a new provider row is created with raw_name = key.
    """
    payload = _read_json(path, "providers_logo", report)
    if not isinstance(payload, dict):
        return 0
    rows = 0
    with conn:
        for provider_name, logo in payload.items():
            if not isinstance(provider_name, str) or not provider_name:
                continue
            logo_path = logo if isinstance(logo, str) else None
            if not logo_path:
                continue
            # 1. Update by mapped_name (only when logo actually changes)
            updated = conn.execute(
                "UPDATE providers SET logo_path = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE mapped_name = ? AND logo_path IS NOT ?",
                (logo_path, provider_name, logo_path),
            ).rowcount
            if updated > 0:
                rows += updated
                continue
            if conn.execute("SELECT 1 FROM providers WHERE mapped_name = ?", (provider_name,)).fetchone():
                continue
            # 2. Update by raw_name (only when logo actually changes)
            updated = conn.execute(
                "UPDATE providers SET logo_path = ?, updated_at = CURRENT_TIMESTAMP"
                " WHERE raw_name = ? AND logo_path IS NOT ?",
                (logo_path, provider_name, logo_path),
            ).rowcount
            if updated > 0:
                rows += updated
                continue
            if conn.execute("SELECT 1 FROM providers WHERE raw_name = ?", (provider_name,)).fetchone():
                continue
            # 3. Insert new provider with just raw_name + logo
            rows += _insert_count(
                conn,
                "INSERT OR IGNORE INTO providers(raw_name, logo_path) VALUES (?, ?)",
                (provider_name, logo_path),
            )
    _record(report, "providers_logo", rows)
    return rows


def import_providers_mapping(
    conn: sqlite3.Connection,
    path: str | Path,
    report: ImportReport | None = None,
    *,
    overwrite: bool = False,
) -> int:
    """Import {raw_name: mapped_name|null} into the unified providers table.

    When overwrite=False (default, used by seed), existing rows are preserved.
    When overwrite=True (used by user-facing save), existing mappings are updated.
    """
    payload = _read_json(path, "providers_mapping", report)
    if not isinstance(payload, dict):
        return 0
    rows = 0
    with conn:
        for raw_name, mapped_name in payload.items():
            if not isinstance(raw_name, str) or not raw_name:
                continue
            ignored = mapped_name is None
            mapped = mapped_name if isinstance(mapped_name, str) else None
            if overwrite:
                rows += conn.execute(
                    """
                    INSERT INTO providers(raw_name, mapped_name, is_ignored)
                    VALUES (?, ?, ?)
                    ON CONFLICT(raw_name) DO UPDATE SET
                        mapped_name = excluded.mapped_name,
                        is_ignored  = excluded.is_ignored,
                        updated_at  = CURRENT_TIMESTAMP
                    """,
                    (raw_name, mapped, 1 if ignored else 0),
                ).rowcount
            else:
                rows += _insert_count(
                    conn,
                    "INSERT OR IGNORE INTO providers(raw_name, mapped_name, is_ignored) VALUES (?, ?, ?)",
                    (raw_name, mapped, 1 if ignored else 0),
                )
    _record(report, "providers_mapping", rows)
    return rows


def import_recommendation_rules(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "recommendation_rules", report)
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        return 0
    rows = 0
    with conn:
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            rule_key = str(rule.get("id") or rule.get("rule_key") or f"rule_{index}")
            conditions = rule.get("conditions")
            msg = rule.get("message") or {}
            action = rule.get("suggested_action") or {}
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO recommendation_rules
                    (rule_key, rule_type, priority, enabled, dedupe_group, severity,
                     conditions_json, message_fr, message_en, suggested_action_fr, suggested_action_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_key,
                    str(rule.get("type") or "") or None,
                    str(rule.get("priority") or "") or None,
                    0 if rule.get("enabled") is False else 1,
                    str(rule.get("dedupe_group") or "") or None,
                    rule.get("severity"),
                    _to_json(conditions) if isinstance(conditions, list) else None,
                    msg.get("fr") or None,
                    msg.get("en") or None,
                    action.get("fr") or None,
                    action.get("en") or None,
                ),
            )
    _record(report, "recommendation_rules", rows)
    return rows


def import_config(
    conn: sqlite3.Connection,
    path: str | Path,
    report: ImportReport | None = None,
    *,
    overwrite: bool = False,
) -> int:
    raw_payload = _read_json(path, "config", report)
    if not isinstance(raw_payload, dict):
        return 0
    payload = sanitize_importable_config(raw_payload)
    rows = 0
    app_config_sql = (
        """
        INSERT INTO app_config(key, value_json)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = CURRENT_TIMESTAMP
        """
        if overwrite
        else """
        INSERT OR IGNORE INTO app_config(key, value_json)
        VALUES (?, ?)
        """
    )
    score_enabled_sql = (
        """
        INSERT INTO app_config(key, value_json)
        VALUES ('score.enabled', ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = CURRENT_TIMESTAMP
        """
        if overwrite
        else """
        INSERT OR IGNORE INTO app_config(key, value_json)
        VALUES ('score.enabled', ?)
        """
    )
    with conn:
        for key, value in payload.items():
            if key == "auth":
                _import_auth_settings(conn, value, overwrite=overwrite)
                continue
            if key in _CONFIG_STRUCTURED_KEYS:
                continue
            clean_value = _strip_sensitive_value(key, value)
            if clean_value is _SKIP_VALUE:
                continue
            rows += _insert_count(conn, app_config_sql, (str(key), _to_json(clean_value)))
        if isinstance(payload.get("score"), dict) or isinstance(payload.get("score_configuration"), dict):
            score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
            score_configuration = payload.get("score_configuration") if isinstance(payload.get("score_configuration"), dict) else {}
            legacy_score_configuration = {
                key: value
                for key, value in score.items()
                if key in {"weights", "video", "audio", "languages", "size"}
            }
            if legacy_score_configuration:
                score_configuration = _deep_merge(legacy_score_configuration, score_configuration)
            rows += _insert_count(
                conn,
                score_enabled_sql,
                (_to_json(score.get("enabled") is True),),
            )
            if overwrite:
                conn.execute("DELETE FROM score_rules")
                conn.execute("DELETE FROM score_size_profiles")
            for (category, group_key, value_key, score_value) in flatten_score_to_rules(score_configuration):
                rows += _insert_count(
                    conn,
                    "INSERT OR IGNORE INTO score_rules(category, group_key, value_key, score_value)"
                    " VALUES (?, ?, ?, ?)",
                    (category, group_key, value_key, score_value),
                )
            for (media_type, res_key, codec_key, min_gb, max_gb) in flatten_score_to_size_profiles(score_configuration):
                rows += _insert_count(
                    conn,
                    "INSERT OR IGNORE INTO score_size_profiles"
                    "(media_type, resolution_key, codec_key, min_gb, max_gb) VALUES (?, ?, ?, ?, ?)",
                    (media_type, res_key, codec_key, min_gb, max_gb),
                )
        # Import folders into dedicated table
        if isinstance(payload.get("folders"), list):
            if overwrite:
                conn.execute("DELETE FROM folders")
            for folder in payload["folders"]:
                if not isinstance(folder, dict):
                    continue
                name = folder.get("name") or folder.get("path") or ""
                if not isinstance(name, str) or not name.strip():
                    continue
                enabled_raw = folder.get("enabled")
                if enabled_raw is None:
                    enabled_raw = folder.get("visible", True)
                rows += _insert_count(
                    conn,
                    "INSERT OR IGNORE INTO folders(name, media_type, enabled) VALUES (?, ?, ?)",
                    (name.strip(), folder.get("type"), 1 if enabled_raw else 0),
                )
        # Import providers_visible → providers.is_ignored (non-empty list only)
        pv = payload.get("providers_visible")
        if isinstance(pv, list) and pv:
            visible_names = {str(n) for n in pv if isinstance(n, str) and n}
            if visible_names:
                placeholders = ",".join("?" * len(visible_names))
                conn.execute(
                    f"UPDATE providers SET is_ignored = 0, updated_at = CURRENT_TIMESTAMP"
                    f" WHERE mapped_name IS NOT NULL AND mapped_name IN ({placeholders})",
                    tuple(visible_names),
                )
                conn.execute(
                    f"UPDATE providers SET is_ignored = 1, updated_at = CURRENT_TIMESTAMP"
                    f" WHERE mapped_name IS NOT NULL AND mapped_name NOT IN ({placeholders})",
                    tuple(visible_names),
                )
        for group in _CONFIG_FLAT_GROUPS:
            if isinstance(payload.get(group), dict):
                for subkey, subval in payload[group].items():
                    clean = _strip_sensitive_value(subkey, subval)
                    if clean is _SKIP_VALUE:
                        continue
                    rows += _insert_count(
                        conn,
                        app_config_sql,
                        (f"{group}.{subkey}", _to_json(clean)),
                    )
    _record(report, "config", rows)
    return rows


def sanitize_importable_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return only real, non-secret configuration keys that belong in SQLite."""

    if not isinstance(config, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in config.items():
        key_str = str(key)
        if key_str in _CONFIG_NON_CONFIG_KEYS or key_str not in _CONFIG_IMPORTABLE_KEYS:
            continue
        cleaned = _strip_sensitive_value(key_str, value)
        if cleaned is _SKIP_VALUE:
            continue
        sanitized[key_str] = cleaned
    return sanitized


def sanitize_config_for_db(config: dict[str, Any]) -> dict[str, Any]:
    """Remove runtime/cache payloads and secrets from a legacy config document."""

    return sanitize_importable_config(config)


def import_recommendations(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "recommendations", report)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return 0
    rows = 0
    with conn:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            rec_id = str(item.get("id") or f"recommendation:{index}")
            media_ref = item.get("media_ref") if isinstance(item.get("media_ref"), dict) else {}
            media_id = _existing_media_id(conn, media_ref.get("id"))
            msg = item.get("message") or {}
            action = item.get("suggested_action") or {}
            rows += _insert_count(
                conn,
                """
                INSERT OR IGNORE INTO recommendations(
                    id, media_id, recommendation_type, priority, rule_id,
                    message_fr, message_en, suggested_action_fr, suggested_action_en
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec_id,
                    media_id,
                    item.get("recommendation_type") or "unknown",
                    item.get("priority"),
                    item.get("rule_id"),
                    msg.get("fr") or None,
                    msg.get("en") or None,
                    action.get("fr") or None,
                    action.get("en") or None,
                ),
            )
    _record(report, "recommendations", rows)
    return rows


def import_library(conn: sqlite3.Connection, path: str | Path, report: ImportReport | None = None) -> int:
    payload = _read_json(path, "library", report)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return 0
    rows = 0
    with conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            rows += upsert_library_item(conn, item, overwrite=False)
    _record(report, "library", rows)
    return rows


def upsert_library_item(conn: sqlite3.Connection, item: dict[str, Any], *, overwrite: bool = True) -> int:
    """Write one scanner/library item to the DB.

    This is intentionally shape-compatible with current library.json items so
    scanner phases can call it later while JSON exports remain in place.
    """

    media_id = str(item.get("id") or item.get("path") or "")
    title = item.get("title")
    media_type = item.get("type") or item.get("media_type")
    if not media_id or not title or not media_type:
        return 0

    params = _media_params(media_id, item)
    if overwrite:
        conn.execute(_MEDIA_UPSERT_SQL, params)
        _upsert_media_providers(conn, media_id, item.get("providers"))
        return 1
    written = _insert_count(conn, _MEDIA_INSERT_IGNORE_SQL, params)
    if written:
        _upsert_media_providers(conn, media_id, item.get("providers"))
    return written


def _upsert_media_providers(conn: sqlite3.Connection, media_id: str, providers: Any) -> None:
    """Sync item.providers list into media_providers + providers tables."""
    if not media_id:
        return
    names: list[str] = []
    seen: set[str] = set()
    for provider in providers or []:
        name = provider if isinstance(provider, str) else None
        if isinstance(provider, dict):
            name = provider.get("name") or provider.get("raw_name") or provider.get("provider_name")
        if not isinstance(name, str) or not name.strip():
            continue
        cleaned = name.strip()
        if cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        names.append(cleaned)
    conn.execute("DELETE FROM media_providers WHERE media_id = ?", (media_id,))
    for name in names:
        conn.execute("INSERT OR IGNORE INTO providers(raw_name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM providers WHERE raw_name = ?", (name,)).fetchone()
        if row is not None:
            conn.execute(
                "INSERT OR IGNORE INTO media_providers(media_id, provider_id) VALUES (?, ?)",
                (media_id, row[0]),
            )


def _import_auth_settings(conn: sqlite3.Connection, value: Any, *, overwrite: bool = False) -> None:
    if not isinstance(value, dict):
        return
    password_hash = value.get("password_hash") if isinstance(value.get("password_hash"), str) else None
    sql = (
        """
        INSERT INTO auth_settings(id, auth_enabled, password_hash)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            auth_enabled = excluded.auth_enabled,
            password_hash = excluded.password_hash,
            updated_at = CURRENT_TIMESTAMP
        """
        if overwrite
        else """
        INSERT OR IGNORE INTO auth_settings(id, auth_enabled, password_hash)
        VALUES (1, ?, ?)
        """
    )
    conn.execute(
        sql,
        (1 if value.get("enabled") is True else 0, password_hash),
    )


def _read_json(path: str | Path, name: str, report: ImportReport | None) -> Any:
    json_path = Path(path)
    if not json_path.exists():
        if report is not None:
            report.skipped_missing.append(name)
        log.info("[db-import] skip missing %s: %s", name, json_path)
        return None
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        if report is not None:
            report.invalid_json.append(name)
        log.warning("[db-import] invalid %s %s: %s", name, json_path, exc)
        return None


def _count_mapping_source(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    return sum(1 for key in payload if isinstance(key, str) and key)


def _count_rules_source(payload: Any) -> int:
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        return 0
    return sum(1 for rule in rules if isinstance(rule, dict))


def _count_files_source(payload: Any) -> int:
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict):
        return 0
    return sum(1 for file_path, entry in files.items() if isinstance(file_path, str) and isinstance(entry, dict))


def _count_items_source(payload: Any) -> int:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict))


def _count_config_source(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    payload = sanitize_importable_config(payload)
    count = 0
    for key, value in payload.items():
        if key == "auth":
            if isinstance(value, dict):
                count += 1
            continue
        if key in _CONFIG_STRUCTURED_KEYS:
            continue
        if _strip_sensitive_value(key, value) is not _SKIP_VALUE:
            count += 1
    if isinstance(payload.get("score"), dict) or isinstance(payload.get("score_configuration"), dict):
        count += 1
    # folders / providers_visible go to dedicated tables — count only when non-empty
    folders_val = payload.get("folders")
    if isinstance(folders_val, list) and folders_val:
        count += 1
    pv_val = payload.get("providers_visible")
    if isinstance(pv_val, list) and pv_val:
        count += 1
    for group in _CONFIG_FLAT_GROUPS:
        if isinstance(payload.get(group), dict):
            count += 1
    return count


def _count_config_total_source(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    payload = sanitize_importable_config(payload)
    count = len(payload)
    if isinstance(payload.get("score"), dict) or isinstance(payload.get("score_configuration"), dict):
        count += 1
    if isinstance(payload.get("media_probe"), dict):
        count += 1
    return count


def _count_config_db(conn: sqlite3.Connection) -> int:
    # Exclude runtime key, flat group prefix keys, and score.* from raw count.
    # folders and providers_visible are in dedicated tables, not in app_config.
    group_excludes = " AND ".join(f"key NOT LIKE '{g}.%'" for g in _CONFIG_FLAT_GROUPS)
    app_config = conn.execute(
        f"SELECT COUNT(*) FROM app_config WHERE key != ? AND key NOT LIKE 'score.%' AND {group_excludes}",
        (_LIBRARY_DOCUMENT_KEY,),
    ).fetchone()[0]
    # Score (score.enabled in app_config + score_rules/score_size_profiles) counts as 1 unit.
    score = 1 if (
        conn.execute("SELECT 1 FROM score_rules LIMIT 1").fetchone()
        or conn.execute("SELECT 1 FROM app_config WHERE key = 'score.enabled' LIMIT 1").fetchone()
    ) else 0
    # Folders table counts as 1 unit if it has rows.
    folders = 1 if conn.execute("SELECT 1 FROM folders LIMIT 1").fetchone() else 0
    # providers_visible counts as 1 unit if any provider is explicitly hidden.
    providers_visible = 1 if conn.execute(
        "SELECT 1 FROM providers WHERE mapped_name IS NOT NULL AND is_ignored = 1 LIMIT 1"
    ).fetchone() else 0
    auth = conn.execute("SELECT COUNT(*) FROM auth_settings").fetchone()[0]
    # Count each flat group as 1 logical unit regardless of how many subkeys it has.
    group_count = sum(
        1 for g in _CONFIG_FLAT_GROUPS
        if conn.execute(
            "SELECT 1 FROM app_config WHERE key LIKE ? LIMIT 1", (f"{g}.%",)
        ).fetchone()
    )
    return int(app_config) + int(score) + int(folders) + int(providers_visible) + int(auth) + group_count


def _validate_config_import(conn: sqlite3.Connection, payload: Any) -> dict[str, Any]:
    expected = _config_source_document(payload)
    actual = _config_db_document(conn)
    expected_flat = _flatten_config_document(expected)
    actual_flat = _flatten_config_document(actual)
    differences: list[tuple[str, str, Any, Any]] = []

    for path in sorted(expected_flat):
        if path not in actual_flat:
            differences.append(("missing", path, expected_flat[path], None))
            continue
        expected_value = expected_flat[path]
        actual_value = actual_flat[path]
        if type(expected_value) is not type(actual_value):
            differences.append(("type", path, expected_value, actual_value))
        elif expected_value != actual_value:
            differences.append(("value", path, expected_value, actual_value))
    return {"valid": not differences, "differences": differences}


def _log_config_import_diff(
    differences: list[tuple[str, str, Any, Any]],
    active_logger: logging.Logger,
) -> None:
    for kind, path, expected_value, actual_value in differences[:_CONFIG_DIFF_LIMIT]:
        if kind == "missing":
            active_logger.warning("[DB] config import diff: missing in DB: %s", path)
        elif kind == "type":
            active_logger.warning(
                "[DB] config import diff: type mismatch: %s json=%s db=%s",
                path,
                type(expected_value).__name__,
                type(actual_value).__name__,
            )
        else:
            active_logger.warning(
                "[DB] config import diff: value mismatch: %s json=%s db=%s",
                path,
                _diagnostic_json(path, expected_value),
                _diagnostic_json(path, actual_value),
            )
    remaining = len(differences) - _CONFIG_DIFF_LIMIT
    if remaining > 0:
        active_logger.warning("[DB] config import diff: %s additional difference(s) omitted", remaining)


def _config_source_document(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    payload = sanitize_importable_config(payload)
    document: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "auth":
            if isinstance(value, dict):
                document["auth"] = {"enabled": value.get("enabled") is True}
            continue
        if key in _CONFIG_STRUCTURED_KEYS:
            continue
        clean_value = _strip_sensitive_value(key, value)
        if clean_value is not _SKIP_VALUE:
            document[str(key)] = clean_value
    if isinstance(payload.get("score"), dict):
        score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
        document["score"] = {"enabled": score.get("enabled") is True}
    score = payload.get("score") if isinstance(payload.get("score"), dict) else {}
    legacy_score_configuration = {
        key: value
        for key, value in score.items()
        if key in {"weights", "video", "audio", "languages", "size"}
    }
    if isinstance(payload.get("score_configuration"), dict) or legacy_score_configuration:
        score_configuration = (
            payload.get("score_configuration")
            if isinstance(payload.get("score_configuration"), dict)
            else {}
        )
        document["score_configuration"] = _deep_merge(legacy_score_configuration, score_configuration)
    # folders is now in its own table — include normalized form only when non-empty
    if isinstance(payload.get("folders"), list):
        normalized_folders = []
        for f in payload["folders"]:
            if not isinstance(f, dict):
                continue
            name = f.get("name") or f.get("path") or ""
            if not name:
                continue
            enabled_raw = f.get("enabled")
            if enabled_raw is None:
                enabled_raw = f.get("visible", True)
            normalized_folders.append({"name": str(name), "type": f.get("type"), "enabled": bool(enabled_raw)})
        if normalized_folders:
            document["folders"] = normalized_folders
    for group in _CONFIG_FLAT_GROUPS:
        if isinstance(payload.get(group), dict):
            document[group] = payload[group]
    return document


def _config_db_document(conn: sqlite3.Connection) -> dict[str, Any]:
    document: dict[str, Any] = {}
    rows = conn.execute(
        "SELECT key, value_json FROM app_config WHERE key != ? ORDER BY key",
        (_LIBRARY_DOCUMENT_KEY,),
    ).fetchall()
    for row in rows:
        key = row["key"]
        if key.startswith("score."):
            continue  # handled below as part of score block
        prefix, sep, _ = key.partition(".")
        if sep and prefix in set(_CONFIG_FLAT_GROUPS):
            continue  # handled below
        document[key] = _from_json(row["value_json"], None)

    score_enabled_row = conn.execute(
        "SELECT value_json FROM app_config WHERE key = 'score.enabled'"
    ).fetchone()
    if score_enabled_row is not None:
        document["score"] = {"enabled": bool(_from_json(score_enabled_row["value_json"], False))}
    rule_rows = conn.execute(
        "SELECT category, group_key, value_key, score_value FROM score_rules ORDER BY id"
    ).fetchall()
    profile_rows = conn.execute(
        "SELECT media_type, resolution_key, codec_key, min_gb, max_gb FROM score_size_profiles ORDER BY id"
    ).fetchall()
    document["score_configuration"] = reconstruct_score_config_from_rows(rule_rows, profile_rows)

    # Reconstruct folders from dedicated table — only include when non-empty
    folder_rows = conn.execute("SELECT name, media_type, enabled FROM folders ORDER BY id").fetchall()
    if folder_rows:
        document["folders"] = [
            {"name": r["name"], "type": r["media_type"], "enabled": bool(r["enabled"])}
            for r in folder_rows
        ]

    for group in _CONFIG_FLAT_GROUPS:
        group_rows = conn.execute(
            "SELECT key, value_json FROM app_config WHERE key LIKE ? ORDER BY key",
            (f"{group}.%",),
        ).fetchall()
        if group_rows:
            prefix_len = len(group) + 1
            document[group] = {
                row["key"][prefix_len:]: _from_json(row["value_json"], None)
                for row in group_rows
            }

    auth_row = conn.execute("SELECT auth_enabled FROM auth_settings WHERE id = 1").fetchone()
    if auth_row is not None:
        document["auth"] = {"enabled": bool(auth_row["auth_enabled"])}
    return document


def _flatten_config_document(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        if not value and prefix:
            return {prefix: {}}
        flattened: dict[str, Any] = {}
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_config_document(value[key], path))
        return flattened
    if isinstance(value, list):
        if not value and prefix:
            return {prefix: []}
        flattened = {}
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            flattened.update(_flatten_config_document(item, path))
        return flattened
    return {prefix: value} if prefix else {"<root>": value}


def _diagnostic_json(path: str, value: Any) -> str:
    if _is_sensitive_path(path):
        return "<redacted>"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_sensitive_path(path: str) -> bool:
    lowered = path.casefold()
    return any(token in lowered for token in _SENSITIVE_TOKENS)


def _table_count(conn: sqlite3.Connection, table_name: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


_LIBRARY_DOCUMENT_KEY = "runtime_library_document"


def _store_library_document_snapshot(conn: sqlite3.Connection, document: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO app_config(key, value_json, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (_LIBRARY_DOCUMENT_KEY, _to_json(document)),
    )


def _record(report: ImportReport | None, name: str, rows: int) -> None:
    if report is not None:
        report.add(name, rows)
    log.info("[db-import] %s imported rows=%s", name, rows)


def _insert_count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    before = conn.total_changes
    conn.execute(sql, params)
    return conn.total_changes - before


def _existing_media_id(conn: sqlite3.Connection, value: Any) -> str | None:
    if value in (None, ""):
        return None
    media_id = str(value)
    row = conn.execute("SELECT id FROM media WHERE id = ?", (media_id,)).fetchone()
    return media_id if row is not None else None


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in update.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _from_json(value: str | None, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


_SKIP_VALUE = object()


def _strip_sensitive_value(key: str, value: Any) -> Any:
    lowered = str(key).casefold()
    if any(token in lowered for token in _SENSITIVE_TOKENS):
        return _SKIP_VALUE
    if isinstance(value, dict):
        clean = {}
        for child_key, child_value in value.items():
            stripped = _strip_sensitive_value(child_key, child_value)
            if stripped is not _SKIP_VALUE:
                clean[child_key] = stripped
        return clean if clean or not value else _SKIP_VALUE
    if isinstance(value, list):
        clean_list = []
        for item in value:
            stripped = _strip_sensitive_value(key, item)
            if stripped is not _SKIP_VALUE:
                clean_list.append(stripped)
        return clean_list if clean_list or not value else _SKIP_VALUE
    return value


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _media_params(media_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    return (
        media_id,
        item.get("type") or item.get("media_type"),
        item.get("title"),
        item.get("raw"),
        item.get("category"),
        item.get("year"),
        item.get("category"),
        item.get("path"),
        _as_int(item.get("tmdb_id")),
        _as_int(item.get("tvdb_id")),
        item.get("imdb_id"),
        item.get("plot") or item.get("overview"),
        item.get("poster") or item.get("poster_path"),
        _to_json(item.get("genres") or []),
        _as_int(item.get("file_count")),
        _as_int(item.get("size_b") or item.get("size_total")),
        _as_int(item.get("runtime_min")),
        _as_int(item.get("runtime_min_avg")),
        _as_float(quality.get("score") if isinstance(quality, dict) else item.get("quality_score")),
        _as_int(item.get("width")),
        _as_int(item.get("height")),
        item.get("resolution"),
        item.get("codec") or item.get("video_codec"),
        _as_int(item.get("video_bitrate")),
        item.get("audio_codec"),
        item.get("audio_codec_raw"),
        _as_int(item.get("audio_bitrate")),
        item.get("audio_channels"),
        _to_json(item.get("audio_languages") or []),
        item.get("audio_language_group") or item.get("audio_languages_simple"),
        _to_json(item.get("subtitle_languages") or []),
        _as_float(item.get("framerate")),
        item.get("container"),
        1 if item.get("hdr") is True else 0 if item.get("hdr") is False else None,
        item.get("hdr_type"),
        1 if item.get("dolby_vision") is True else 0 if item.get("dolby_vision") is False else None,
        1 if item.get("providers_fetched") else 0,
        _to_json(quality) if quality else None,
        item.get("last_seen_at") or item.get("added_at"),
        1 if item.get("is_available", True) else 0,
        item.get("first_seen_at"),
        item.get("last_scanned_at"),
        _to_json(item["filename"]) if item.get("filename") is not None else None,
        item.get("seerr_last_fetched_at"),
        item.get("seerr_status"),
    )


_MEDIA_COLUMNS = """
id, media_type, title, raw_name, category, year, folder, path, tmdb_id, tvdb_id,
imdb_id, overview, poster_path, genres_json, file_count, size_total,
runtime_min, runtime_min_avg, quality_score, width, height, resolution,
video_codec, video_bitrate, audio_codec, audio_codec_raw, audio_bitrate,
audio_channels, audio_languages_json, audio_language_group,
subtitle_languages_json, framerate, container, hdr, hdr_type, dolby_vision,
providers_fetched, quality_json, last_seen_at,
is_available, first_seen_at, last_scanned_at, filename,
seerr_last_fetched_at, seerr_status
"""

_MEDIA_INSERT_IGNORE_SQL = f"""
INSERT OR IGNORE INTO media({_MEDIA_COLUMNS})
VALUES ({",".join(["?"] * 45)})
"""

_MEDIA_UPSERT_SQL = f"""
INSERT INTO media({_MEDIA_COLUMNS})
VALUES ({",".join(["?"] * 45)})
ON CONFLICT(id) DO UPDATE SET
    media_type = excluded.media_type,
    title = excluded.title,
    raw_name = excluded.raw_name,
    category = excluded.category,
    year = excluded.year,
    folder = excluded.folder,
    path = excluded.path,
    tmdb_id = excluded.tmdb_id,
    tvdb_id = excluded.tvdb_id,
    imdb_id = excluded.imdb_id,
    overview = excluded.overview,
    poster_path = excluded.poster_path,
    genres_json = excluded.genres_json,
    file_count = excluded.file_count,
    size_total = excluded.size_total,
    runtime_min = excluded.runtime_min,
    runtime_min_avg = excluded.runtime_min_avg,
    quality_score = excluded.quality_score,
    width = excluded.width,
    height = excluded.height,
    resolution = excluded.resolution,
    video_codec = excluded.video_codec,
    video_bitrate = excluded.video_bitrate,
    audio_codec = excluded.audio_codec,
    audio_codec_raw = excluded.audio_codec_raw,
    audio_bitrate = excluded.audio_bitrate,
    audio_channels = excluded.audio_channels,
    audio_languages_json = excluded.audio_languages_json,
    audio_language_group = excluded.audio_language_group,
    subtitle_languages_json = excluded.subtitle_languages_json,
    framerate = excluded.framerate,
    container = excluded.container,
    hdr = excluded.hdr,
    hdr_type = excluded.hdr_type,
    dolby_vision = excluded.dolby_vision,
    providers_fetched = excluded.providers_fetched,
    quality_json = excluded.quality_json,
    updated_at = CURRENT_TIMESTAMP,
    last_seen_at = excluded.last_seen_at,
    is_available = excluded.is_available,
    first_seen_at = COALESCE(first_seen_at, excluded.first_seen_at),
    last_scanned_at = excluded.last_scanned_at,
    filename = excluded.filename,
    seerr_last_fetched_at = COALESCE(excluded.seerr_last_fetched_at, seerr_last_fetched_at),
    seerr_status = COALESCE(excluded.seerr_status, seerr_status)
"""
