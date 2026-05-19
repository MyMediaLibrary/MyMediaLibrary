#!/usr/bin/env python3
"""
Media Library Scanner
Scans LIBRARY_PATH and persists runtime state to SQLite.

Runtime:
  The default scan is a dynamic pipeline. Phase 1 always runs; optional
  phases run only when their feature is enabled in SQLite config.
  --score-only Recompute quality scores from the SQLite media library.
  --reset    Reset legacy runtime output if present.

Phases:
  1. Filesystem + NFO scan — builds the media library, writes after each folder.
  2. Seerr enrichment — fetches streaming providers, writes after each folder.
  3. Scoring              — computes quality scores, writes after each folder.
  5. Recommendations      — replaces generated recommendations in SQLite.

Filters (combinable with any mode):
  --category <n>   Restrict scan to a single category name.
"""

import argparse
import base64
import contextlib
import copy
import fcntl
import hashlib
import hmac
import http.server
import json
import logging
from collections import Counter, defaultdict
from logging.handlers import RotatingFileHandler
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from backend import runtime_paths
except Exception:
    import runtime_paths  # type: ignore

try:
    from backend import db as sqlite_db
except Exception:
    try:
        import db as sqlite_db  # type: ignore
    except Exception:
        sqlite_db = None  # type: ignore

try:
    from backend.repositories import config_repository, media_repository, providers_repository, recommendations_repository
    from backend.repositories.scan_run_repository import ScanRunRecorder
except Exception:
    try:
        from repositories import config_repository, media_repository, providers_repository, recommendations_repository  # type: ignore
        from repositories.scan_run_repository import ScanRunRecorder  # type: ignore
    except Exception:
        config_repository = None  # type: ignore
        media_repository = None  # type: ignore
        providers_repository = None  # type: ignore
        recommendations_repository = None  # type: ignore
        ScanRunRecorder = None  # type: ignore


try:
    from backend.recommendations import (
        ensure_user_rules,
        generate_recommendations,
        load_rules as load_recommendation_rules,
        write_recommendations,
    )
except Exception:
    try:
        from recommendations import (
            ensure_user_rules,
            generate_recommendations,
            load_rules as load_recommendation_rules,
            write_recommendations,
        )
    except Exception as e:
        logging.getLogger("scanner").warning(
            "[SCAN] recommendations import failed (%s). Recommendations disabled; continuing non-blocking.",
            e,
        )

        def ensure_user_rules(default_rules_path, user_rules_path):
            return False

        def load_recommendation_rules(path):
            return []

        def generate_recommendations(library_doc, rules, *, max_per_media=3):
            return []

        def write_recommendations(items, output_path, now=None):
            return {"generated_at": None, "version": 1, "items": items}

try:
    from backend.media_probe import run_media_probe_document_if_enabled
except Exception:
    try:
        from media_probe import run_media_probe_document_if_enabled
    except Exception as e:
        logging.getLogger("scanner").warning(
            "[SCAN] [PHASE 2] [FFPROBE] media_probe import failed (%s). Technical scan disabled.",
            e,
        )

        def run_media_probe_document_if_enabled(*args, **kwargs):
            return None

def run_media_probe_pipeline_if_enabled(
    cfg: dict | None,
    *,
    library_document: dict | None = None,
    library_json_path: str | Path | None = None,
    output_path: str | Path | None = None,
    library_root: str | Path = runtime_paths.LIBRARY_DIR,
    timeout: float = 5.0,
    only_category: str | None = None,
):
    del output_path
    document = library_document
    if document is None and library_json_path is not None:
        document = load_library_document_non_blocking(str(library_json_path))
    if not isinstance(document, dict):
        return None
    return run_media_probe_document_if_enabled(
        cfg,
        library_document=document,
        library_root=library_root,
        timeout=timeout,
        only_category=only_category,
    )

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LIBRARY_PATH = str(runtime_paths.LIBRARY_DIR)
OUTPUT_PATH = str(runtime_paths.LIBRARY_JSON)
RECOMMENDATIONS_OUTPUT_PATH = str(runtime_paths.RECOMMENDATIONS_JSON)
RECOMMENDATIONS_RULES_PATH = str(runtime_paths.RECOMMENDATIONS_RULES_JSON)
CONFIG_PATH = str(runtime_paths.CONFIG_JSON)
SECRETS_PATH = str(runtime_paths.SECRETS_FILE)
SCAN_LOCK_PATH = str(runtime_paths.SCAN_LOCK)
PROVIDERS_MAPPING_RUNTIME_PATH = str(runtime_paths.PROVIDERS_MAPPING_JSON)
PROVIDERS_LOGO_PATH = str(runtime_paths.PROVIDERS_LOGO_JSON)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def _resolve_log_level(raw_level: str | None) -> int:
    return getattr(logging, str(raw_level or "INFO").upper(), logging.INFO)


def _set_global_log_level(raw_level: str | None) -> None:
    level = _resolve_log_level(raw_level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)


def _apply_configured_log_level() -> None:
    """Apply log_level from SQLite config after DB bootstrap."""
    try:
        cfg = load_config()
        _cfg_loglevel = cfg.get("system", {}).get("log_level", "INFO") if isinstance(cfg, dict) else "INFO"
        _set_global_log_level(_cfg_loglevel)
    except Exception as exc:
        logging.getLogger("scanner").debug("[config] Could not apply SQLite log level: %s", exc)


log = logging.getLogger("scanner")

try:
    from backend.scoring import build_quality_block, compute_quality, get_builtin_score_defaults
except Exception:
    try:
        from scoring import build_quality_block, compute_quality, get_builtin_score_defaults
    except Exception as e:
        logging.getLogger("scanner").warning(
            "[SCAN] scoring import failed (%s). Quality scoring disabled; continuing non-blocking.",
            e,
        )

        def compute_quality(item: dict) -> dict:
            return {
                "score": 0,
                "video": 0,
                "audio": 0,
                "languages": 0,
                "size": 0,
                "video_details": {
                    "resolution": 0,
                    "codec": 0,
                    "hdr": 0,
                },
                "audio_details": {
                    "codec": 0,
                    "channels": 0,
                },
            }

        def build_quality_block(
            *,
            video_resolution: int,
            video_codec: int,
            video_hdr: int,
            audio_codec: int,
            audio_channels: int,
            audio: int,
            languages: int,
            size: int,
            max_video_score: int,
            max_audio_score: int,
            max_languages_score: int,
            max_size_score: int,
            weights: dict | None = None,
        ) -> dict:
            video = int(video_resolution) + int(video_codec) + int(video_hdr)
            video_w = int(video)
            audio_w = int(audio)
            languages_w = int(languages)
            size_w = int(size)
            return {
                "score": video_w + audio_w + languages_w + size_w,
                "video": video,
                "video_w": video_w,
                "audio": int(audio),
                "audio_w": audio_w,
                "languages": int(languages),
                "languages_w": languages_w,
                "size": int(size),
                "size_w": size_w,
                "video_details": {
                    "resolution": int(video_resolution),
                    "codec": int(video_codec),
                    "hdr": int(video_hdr),
                },
                "audio_details": {
                    "codec": int(audio_codec),
                    "channels": int(audio_channels),
                },
            }

        def get_builtin_score_defaults() -> dict:
            return {
                "weights": {"video": 50, "audio": 20, "languages": 15, "size": 15},
            }

try:
    from backend.nfo import (
        classify_resolution, normalize_codec, normalize_audio_codec,
        parse_audio_languages, parse_subtitle_languages,
        parse_audio_channels, parse_video_bitrate,
        normalize_audio_channels, simplify_audio_languages,
        parse_movie_nfo, parse_tvshow_nfo, count_seasons_episodes,
        find_episode_nfo, find_movie_nfo, poster_rel_path,
        _nfo_stats, _parse_lang_raw, _parse_concatenated_lang_codes,
    )
except ImportError:
    from nfo import (
        classify_resolution, normalize_codec, normalize_audio_codec,
        parse_audio_languages, parse_subtitle_languages,
        parse_audio_channels, parse_video_bitrate,
        normalize_audio_channels, simplify_audio_languages,
        parse_movie_nfo, parse_tvshow_nfo, count_seasons_episodes,
        find_episode_nfo, find_movie_nfo, poster_rel_path,
        _nfo_stats, _parse_lang_raw, _parse_concatenated_lang_codes,
    )

# Rotating file log: 5MB max, keep 3 backups — in /data/ so it's accessible from host
_log_file = str(runtime_paths.SCANNER_LOG)
try:
    _fh = RotatingFileHandler(_log_file, maxBytes=5*1024*1024, backupCount=3)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_fh)
except Exception:
    pass  # log file not writable in some environments


# ---------------------------------------------------------------------------
# Seerr — providers only
# ---------------------------------------------------------------------------

_JSR_NOT_CONFIGURED = object()  # sentinel: Seerr not configured/disabled
_JSR_ERROR          = object()  # sentinel: HTTP/network error (transient — do not mark providers_fetched)
_JSR_NOT_FOUND      = object()  # sentinel: HTTP 500 "Unable to retrieve" — item not in Seerr


def _load_secrets() -> dict:
    """Load the Seerr secrets JSON file. Returns {} if missing or unreadable."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_secrets(data: dict) -> None:
    """Write secrets dict to SECRETS_PATH with mode 600."""
    output = Path(SECRETS_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try:
        os.chmod(output, 0o600)
    except OSError as e:
        log.warning(f"[secrets] Failed to set permissions on {SECRETS_PATH}: {e}")


def _save_secrets(data: dict) -> None:
    try:
        _write_secrets(data)
    except Exception as e:
        log.warning(f"[secrets] Could not write {SECRETS_PATH}: {e}")


_AUTH_PASSWORD_HASH_KEY = "auth_password_hash"
_AUTH_LEGACY_PASSWORD_KEYS = ("auth_password", "app_password", "password")
_AUTH_HASH_SCHEME = "pbkdf2_sha256"
_AUTH_HASH_ITERATIONS = 260_000
_AUTH_MIN_PASSWORD_LENGTH = 25
_AUTH_MIN_LOWERCASE = 2
_AUTH_MIN_UPPERCASE = 2
_AUTH_MIN_DIGITS = 2
_AUTH_MIN_SPECIAL = 2
_SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


def _auth_legacy_secret_paths() -> list[Path]:
    current_path = Path(SECRETS_PATH)
    return [
        current_path,
        current_path.with_name(".secret"),
        Path(runtime_paths.DATA_DIR) / ".secret",
        Path(getattr(runtime_paths, "LEGACY_SECRETS_FILE", Path("/conf/.secrets"))),
        Path(getattr(runtime_paths, "LEGACY_CONF_DIR", Path("/conf"))) / ".secret",
        Path(runtime_paths.APP_DIR) / ".secret",
    ]


def _auth_hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _AUTH_HASH_ITERATIONS,
    )
    return "$".join((
        _AUTH_HASH_SCHEME,
        str(_AUTH_HASH_ITERATIONS),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ))


def _auth_is_hash(value) -> bool:
    return isinstance(value, str) and value.startswith(f"{_AUTH_HASH_SCHEME}$")


def _auth_check_password_hash(stored_hash: str, password: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if scheme != _AUTH_HASH_SCHEME:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _auth_password_rule_status(password: str) -> dict[str, bool]:
    value = password if isinstance(password, str) else ""
    return {
        "length": len(value) >= _AUTH_MIN_PASSWORD_LENGTH,
        "lowercase": sum(1 for ch in value if ch.islower()) >= _AUTH_MIN_LOWERCASE,
        "uppercase": sum(1 for ch in value if ch.isupper()) >= _AUTH_MIN_UPPERCASE,
        "digits": sum(1 for ch in value if ch.isdigit()) >= _AUTH_MIN_DIGITS,
        "special": sum(1 for ch in value if not ch.isalnum() and not ch.isspace()) >= _AUTH_MIN_SPECIAL,
    }


def validate_auth_password(password: str, confirmation: str | None = None) -> tuple[bool, dict]:
    """Validate auth password creation/change rules without exposing secrets."""
    rules = _auth_password_rule_status(password)
    confirmation_matches = confirmation is None or password == confirmation
    ok = all(rules.values()) and confirmation_matches
    return ok, {
        "ok": ok,
        "rules": rules,
        "confirmation_matches": confirmation_matches,
        "min_length": _AUTH_MIN_PASSWORD_LENGTH,
    }


def _auth_legacy_plaintext_from_current_file() -> str | None:
    path = Path(SECRETS_PATH)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw or raw.startswith("{"):
        return None
    return raw


def _auth_plaintext_candidates(secrets_data: dict | None = None) -> list[tuple[str, Path | None, str | None]]:
    candidates: list[tuple[str, Path | None, str | None]] = []
    data = secrets_data if isinstance(secrets_data, dict) else _load_secrets()
    for key in _AUTH_LEGACY_PASSWORD_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            candidates.append((value, None, key))
    current_plaintext = _auth_legacy_plaintext_from_current_file()
    if current_plaintext:
        candidates.append((current_plaintext, Path(SECRETS_PATH), None))
    for path in _auth_legacy_secret_paths()[1:]:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if value:
            candidates.append((value, path, None))
    return candidates


def _auth_is_configured() -> bool:
    secrets_data = _load_secrets()
    if _auth_is_hash(secrets_data.get(_AUTH_PASSWORD_HASH_KEY)):
        return True
    return bool(_auth_plaintext_candidates(secrets_data))


def _auth_migrate_plaintext_password(password: str, *, legacy_path: Path | None = None, legacy_key: str | None = None) -> None:
    data = _load_secrets()
    data[_AUTH_PASSWORD_HASH_KEY] = _auth_hash_password(password)
    for key in _AUTH_LEGACY_PASSWORD_KEYS:
        data.pop(key, None)
    _write_secrets(data)
    _sync_auth_settings_to_db(data)
    if legacy_path and legacy_path != Path(SECRETS_PATH):
        with contextlib.suppress(Exception):
            legacy_path.unlink(missing_ok=True)
    log.info("[auth] Legacy plaintext password migrated to hash")


def _auth_verify_password(password: str) -> bool:
    if not isinstance(password, str) or not password:
        return False
    secrets_data = _load_secrets()
    stored_hash = secrets_data.get(_AUTH_PASSWORD_HASH_KEY)
    if _auth_is_hash(stored_hash):
        return _auth_check_password_hash(stored_hash, password)
    for legacy_password, legacy_path, legacy_key in _auth_plaintext_candidates(secrets_data):
        if hmac.compare_digest(legacy_password, password):
            _auth_migrate_plaintext_password(password, legacy_path=legacy_path, legacy_key=legacy_key)
            return True
    return False


def _apply_auth_secret_update(payload: dict, secrets_data: dict) -> str:
    auth_payload = payload.pop("auth", None)
    if not isinstance(auth_payload, dict):
        return "not modified"
    enabled = auth_payload.get("enabled") is True
    clear_requested = auth_payload.get("clear_password") is True
    if clear_requested or not enabled:
        secrets_data.pop(_AUTH_PASSWORD_HASH_KEY, None)
        for key in _AUTH_LEGACY_PASSWORD_KEYS:
            secrets_data.pop(key, None)
        return "disabled"
    password = auth_payload.get("password")
    confirm = auth_payload.get("password_confirm", auth_payload.get("confirm_password"))
    if not isinstance(password, str):
        raise ValueError("Password is required")
    valid, validation = validate_auth_password(password, confirm if isinstance(confirm, str) else None)
    if not validation["confirmation_matches"]:
        raise ValueError("Password confirmation does not match")
    if not valid:
        raise ValueError("Password does not meet security requirements")
    secrets_data[_AUTH_PASSWORD_HASH_KEY] = _auth_hash_password(password)
    for key in _AUTH_LEGACY_PASSWORD_KEYS:
        secrets_data.pop(key, None)
    return "updated"


def _sync_auth_settings_to_db(secrets_data: dict | None = None) -> None:
    if config_repository is None:
        return
    data = secrets_data if isinstance(secrets_data, dict) else _load_secrets()
    password_hash = data.get(_AUTH_PASSWORD_HASH_KEY)
    try:
        config_repository.save_auth_settings(
            auth_enabled=_auth_is_hash(password_hash),
            password_hash=password_hash if _auth_is_hash(password_hash) else None,
        )
    except Exception as e:
        log.debug("[auth] Could not sync auth settings to SQLite: %s", e)


def _redact_config_payload(payload: dict) -> dict:
    """Return a copy of payload with sensitive fields redacted for safe logging."""
    safe_payload = copy.deepcopy(payload)
    for key in ("seerr", "jellyseerr"):
        jsr = safe_payload.get(key)
        if isinstance(jsr, dict) and "apikey" in jsr:
            jsr["apikey"] = "***"
    auth = safe_payload.get("auth")
    if isinstance(auth, dict):
        for key in ("password", "password_confirm", "confirm_password"):
            if key in auth:
                auth[key] = "***"
    return safe_payload


_CONFIG_FLAT_GROUPS = frozenset({"system", "seerr", "ui", "recommendations", "media_probe"})
_CONFIG_SENSITIVE_TOKENS = ("api_key", "apikey", "token", "secret", "password")


def _config_flat_keys(d: dict) -> list[str]:
    """Return sorted flat key names (group.subkey or scalar) from a config dict.

    Omits auth/score/score_configuration/providers_visible and any key whose name
    contains a sensitive token — values are never included.
    """
    _SKIP = {"auth", "score", "score_configuration", "providers_visible"}
    keys: list[str] = []
    for k, v in d.items():
        if k in _SKIP:
            continue
        if k in _CONFIG_FLAT_GROUPS and isinstance(v, dict):
            for sk in v:
                flat = f"{k}.{sk}"
                if any(t in flat.casefold() for t in _CONFIG_SENSITIVE_TOKENS):
                    continue
                keys.append(flat)
        else:
            if not any(t in str(k).casefold() for t in _CONFIG_SENSITIVE_TOKENS):
                keys.append(str(k))
    return sorted(keys)


def _config_changed_keys(before: dict, after: dict) -> list[str]:
    """Return sorted flat key names whose values differ between before and after.

    providers_visible is excluded: it maps to providers.is_ignored (not app_config)
    and is never a loggable save key.
    """
    _SKIP = {"auth", "providers_visible"}
    changed: list[str] = []
    all_keys = set(before) | set(after)
    for k in all_keys:
        if k in _SKIP:
            continue
        v_b, v_a = before.get(k), after.get(k)
        if k == "score":
            b_en = v_b.get("enabled") if isinstance(v_b, dict) else None
            a_en = v_a.get("enabled") if isinstance(v_a, dict) else None
            if b_en != a_en:
                changed.append("score.enabled")
        elif k == "score_configuration":
            if v_b != v_a:
                changed.append("score_configuration")
        elif k in _CONFIG_FLAT_GROUPS:
            b = v_b if isinstance(v_b, dict) else {}
            a = v_a if isinstance(v_a, dict) else {}
            for sk in set(b) | set(a):
                if b.get(sk) != a.get(sk):
                    flat = f"{k}.{sk}"
                    if any(t in flat.casefold() for t in _CONFIG_SENSITIVE_TOKENS):
                        continue
                    changed.append(flat)
        else:
            if v_b != v_a and not any(t in str(k).casefold() for t in _CONFIG_SENSITIVE_TOKENS):
                changed.append(str(k))
    return sorted(changed)


def _fmt_config_val(v: object) -> str:
    """Format a config value for a single-line log entry (no secrets, no JSON quotes)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return f"[{len(v)} items]"
    return "(complex)"


def _config_changed_summary(before: dict, after: dict) -> str:
    """Return 'key : new_value, ...' for keys that changed, safe for INFO logging."""
    keys = _config_changed_keys(before, after)
    if not keys:
        return "(no change)"
    parts = []
    for flat_key in keys:
        if flat_key == "score_configuration":
            parts.append("score_configuration")
            continue
        if "." in flat_key:
            group, subkey = flat_key.split(".", 1)
            group_val = after.get(group)
            val = group_val.get(subkey) if isinstance(group_val, dict) else None
        else:
            val = after.get(flat_key)
        parts.append(f"{flat_key} : {_fmt_config_val(val)}")
    return ", ".join(parts)


def _patch_summary(written_keys: list[str], payload: dict) -> str:
    """Format written flat keys with their new values for INFO log output."""
    parts = []
    for flat_key in written_keys:
        if flat_key == "score_configuration":
            parts.append("score_configuration")
            continue
        if flat_key == "folders":
            parts.append(f"folders : [{len(payload.get('folders') or [])} items]")
            continue
        if "." in flat_key:
            group, subkey = flat_key.split(".", 1)
            val = (payload.get(group) or {}).get(subkey)
        else:
            val = payload.get(flat_key)
        if any(t in flat_key.casefold() for t in _CONFIG_SENSITIVE_TOKENS):
            continue
        parts.append(f"{flat_key} : {_fmt_config_val(val)}")
    return ", ".join(parts) if parts else "(no visible change)"


def _normalize_seerr_secret_keys(secrets: dict) -> tuple[dict, bool]:
    changed = False
    if not isinstance(secrets, dict):
        return {}, False
    if secrets.get("seerr_apikey") is None and secrets.get("jellyseerr_apikey"):
        secrets["seerr_apikey"] = secrets.get("jellyseerr_apikey")
        changed = True
    if "jellyseerr_apikey" in secrets:
        secrets.pop("jellyseerr_apikey", None)
        changed = True
    return secrets, changed


def normalize_seerr_config(cfg: dict) -> tuple[dict, bool]:
    changed = False
    legacy = cfg.get("jellyseerr") if isinstance(cfg.get("jellyseerr"), dict) else {}
    current = cfg.get("seerr") if isinstance(cfg.get("seerr"), dict) else {}
    merged = dict(legacy)
    merged.update(current)
    if cfg.get("seerr") != merged:
        cfg["seerr"] = merged
        changed = True
    if "jellyseerr" in cfg:
        cfg.pop("jellyseerr", None)
        changed = True
    return cfg, changed


def _apply_seerr_secret_update(payload: dict, secrets: dict) -> str:
    """
    Apply Seerr API key update policy from payload to secrets.

    Rules:
    - apikey missing        => not modified
    - apikey empty/whitespace/"***" => preserved (no overwrite)
    - apikey non-empty      => updated
    - clear_apikey=true     => explicit clear
    """
    jsr = payload.get("seerr")
    if not isinstance(jsr, dict):
        jsr = payload.get("jellyseerr")
    if not isinstance(jsr, dict):
        return "not modified"

    clear_requested = jsr.pop("clear_apikey", False) is True
    has_apikey_field = "apikey" in jsr
    raw_apikey = jsr.pop("apikey", None) if has_apikey_field else None

    if not jsr:
        payload.pop("seerr", None)
        payload.pop("jellyseerr", None)

    if clear_requested:
        secrets.pop("seerr_apikey", None)
        secrets.pop("jellyseerr_apikey", None)
        return "cleared"

    if not has_apikey_field:
        return "not modified"

    normalized = raw_apikey.strip() if isinstance(raw_apikey, str) else ""
    if not normalized or normalized == "***":
        return "preserved"

    secrets["seerr_apikey"] = normalized
    secrets.pop("jellyseerr_apikey", None)
    return "updated"


def _apply_jellyseerr_secret_update(payload: dict, secrets: dict) -> str:
    """Backward-compatible alias kept for legacy tests/callers."""
    return _apply_seerr_secret_update(payload, secrets)


def _jsr_cfg() -> dict:
    """Read Seerr settings. API key comes from the secrets file, rest from SQLite config."""
    cfg = load_config()
    jsr = cfg.get("seerr", {}) or cfg.get("jellyseerr", {})
    secrets = _load_secrets()
    secrets, secrets_changed = _normalize_seerr_secret_keys(secrets)
    if secrets_changed:
        _save_secrets(secrets)
    apikey = secrets.get("seerr_apikey") or secrets.get("jellyseerr_apikey") or ""
    return {
        "enabled": jsr.get("enabled", False),
        "url":     jsr.get("url", "").rstrip("/"),
        "apikey":  apikey,
    }


def _validate_seerr_url(url: str) -> None:
    """Raise ValueError if url uses a disallowed scheme or has no hostname."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Seerr URL must use http or https, got: {parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError("Seerr URL must include a hostname")


def _jsr_get(path: str, jsr: dict | None = None):
    """
    Returns:
      dict              — success (parsed JSON)
      _JSR_NOT_CONFIGURED — Seerr disabled or not configured
      _JSR_ERROR          — HTTP/network error (already logged as WARNING)
    """
    if jsr is None:
        jsr = _jsr_cfg()
    if not jsr["enabled"] or not jsr["url"] or not jsr["apikey"]:
        return _JSR_NOT_CONFIGURED
    try:
        _validate_seerr_url(jsr["url"])
    except ValueError as exc:
        log.warning("[seerr] URL rejected — %s", exc)
        return _JSR_ERROR
    url = f"{jsr['url']}/api/v1{path}"
    log.debug(f"Seerr GET: {url}")
    req = urllib.request.Request(url, headers={
        "X-Api-Key": jsr["apikey"].strip(),
        "Accept": "application/json",
        "User-Agent": "MyMediaLibraryScanner/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:300]
        if e.code in (404, 500) and "Unable to retrieve" in body:
            log.debug(f"[seerr] Item not found for {path} (not in Seerr/TMDB)")
            return _JSR_NOT_FOUND
        log.warning(f"Seerr HTTP {e.code} for {path}: {body}")
        return _JSR_ERROR
    except Exception as e:
        log.warning(f"Seerr request failed for {path}: {type(e).__name__}: {e}")
        return _JSR_ERROR


def _ensure_runtime_provider_mapping() -> None:
    """Warm provider mappings from SQLite without materializing bundled default JSON files."""
    if providers_repository is not None:
        try:
            providers_repository.load_provider_mappings(PROVIDERS_MAPPING_RUNTIME_PATH)
        except Exception as e:
            log.debug("[providers] Could not warm SQLite provider mappings: %s", e)


def _ensure_runtime_providers_logo() -> None:
    """Warm provider logos from SQLite without materializing bundled default JSON files."""
    if providers_repository is not None:
        try:
            providers_repository.load_provider_logos(PROVIDERS_LOGO_PATH)
        except Exception as e:
            log.debug("[providers] Could not warm SQLite provider logos: %s", e)


def _load_runtime_provider_mapping() -> dict:
    if providers_repository is not None:
        payload = providers_repository.load_provider_mappings(PROVIDERS_MAPPING_RUNTIME_PATH)
        if isinstance(payload, dict):
            return payload
    log.error("[providers] SQLite provider mappings repository unavailable")
    return {}


def _load_runtime_provider_logos() -> dict:
    if providers_repository is not None:
        payload = providers_repository.load_provider_logos(PROVIDERS_LOGO_PATH)
        if isinstance(payload, dict):
            return payload
    log.error("[providers] SQLite provider logos repository unavailable")
    return {}


def _save_runtime_provider_mapping(mapping: dict) -> None:
    if providers_repository is not None:
        providers_repository.save_provider_mappings(mapping, PROVIDERS_MAPPING_RUNTIME_PATH)
        return
    raise RuntimeError("SQLite provider mappings repository unavailable")


def _extract_raw_providers_from_item(item: dict) -> list[str]:
    providers = item.get("providers")
    if isinstance(providers, list):
        return _normalize_provider_entries(providers)
    if isinstance(providers, dict):
        merged = []
        for values in providers.values():
            if isinstance(values, list):
                merged.extend(values)
        return _normalize_provider_entries(merged)
    return []


def _upsert_runtime_provider_mapping(items: list[dict]) -> int:
    """Add missing raw providers to runtime mapping with null values; never overwrite existing keys."""
    mapping = _load_runtime_provider_mapping()
    if not isinstance(mapping, dict):
        mapping = {}
    added = 0
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        for raw_name in _extract_raw_providers_from_item(item):
            if raw_name not in mapping:
                mapping[raw_name] = None
                added += 1
    if added:
        _save_runtime_provider_mapping(mapping)
    return added


def _load_runtime_recommendation_rules() -> list[dict]:
    if recommendations_repository is not None:
        rules = recommendations_repository.load_recommendation_rules(RECOMMENDATIONS_RULES_PATH)
        if isinstance(rules, list):
            return rules
    log.error("[recommendations] SQLite recommendation rules repository unavailable")
    return []


_fetch_providers_sampled = False  # log raw response once per run

# Sentinel returned when Seerr call fails (vs [] = success with no FR providers)
_FETCH_ERROR    = object()
_ENRICH_WORKERS = 5  # ThreadPoolExecutor workers for Seerr enrichment
_SEERR_NOT_FOUND_TTL_DAYS = 30
_PROVIDER_TYPES = ("flatrate", "free", "ads", "buy", "rent")
_PROVIDER_ENRICH_GROUP = "flatrate"

def _normalize_lookup_title(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _resolve_ids_from_search(title: str | None, year: str | int | None, is_tv: bool, jsr: dict | None = None):
    """
    Resolve TMDB id via Seerr search when direct /tv/{id} fetch fails.
    Returns:
      dict        — {"tmdb_id": str|int|None, "tvdb_id": str|int|None}
      None        — nothing matched
      _FETCH_ERROR — Seerr request failure
    """
    if not isinstance(title, str) or not title.strip():
        return None
    query = urllib.parse.quote(title.strip())
    resp = _jsr_get(f"/search?query={query}", jsr)
    if resp in (_JSR_NOT_CONFIGURED, _JSR_NOT_FOUND):
        return None
    if resp is _JSR_ERROR:
        return _FETCH_ERROR

    results = resp.get("results") if isinstance(resp, dict) else None
    if not isinstance(results, list):
        return None

    target_media = "tv" if is_tv else "movie"
    expected_year = str(year).strip() if year is not None and str(year).strip() else None
    wanted_title = _normalize_lookup_title(title)

    scored: list[tuple[int, dict]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("mediaType") or item.get("media_type") or "").strip().lower()
        if media_type and media_type != target_media:
            continue
        tmdb_id = item.get("id") or item.get("tmdbId") or item.get("tmdb_id")
        tvdb_id = item.get("tvdbId") or item.get("tvdb_id")
        if tmdb_id in (None, "") and tvdb_id in (None, ""):
            continue
        candidate_title = (
            item.get("title")
            or item.get("name")
            or item.get("originalTitle")
            or item.get("originalName")
            or ""
        )
        candidate_norm = _normalize_lookup_title(candidate_title)
        candidate_date = item.get("releaseDate") or item.get("firstAirDate") or ""
        candidate_year = str(candidate_date)[:4] if isinstance(candidate_date, str) and len(candidate_date) >= 4 else None

        score = 0
        if candidate_norm == wanted_title:
            score += 4
        elif wanted_title and candidate_norm and (wanted_title in candidate_norm or candidate_norm in wanted_title):
            score += 2
        if expected_year and candidate_year == expected_year:
            score += 2
        if score > 0:
            scored.append((score, {"tmdb_id": tmdb_id, "tvdb_id": tvdb_id}))

    if not scored:
        return None
    scored.sort(key=lambda entry: entry[0], reverse=True)
    return scored[0][1]

def _extract_watch_provider_regions(watch_providers) -> list[tuple[str, dict]]:
    """
    Normalize Seerr/TMDB watch providers payload to a list of region payloads.

    Supported shapes:
      - {"FR": {...}, "US": {...}}
      - {"results": {"FR": {...}, "US": {...}}} (TMDB style)
      - [{"iso_3166_1": "FR", ...}, {"iso_3166_1": "US", ...}]
      - {"flatrate": [...], ...} (single region-like object)
    """
    regions: list[tuple[str, dict]] = []

    if isinstance(watch_providers, list):
        for entry in watch_providers:
            if not isinstance(entry, dict):
                continue
            region = str(entry.get("iso_3166_1") or "").strip().upper() or "UNKNOWN"
            regions.append((region, entry))
        return regions

    if not isinstance(watch_providers, dict):
        return regions

    # TMDB-compatible wrapper.
    nested_results = watch_providers.get("results")
    if isinstance(nested_results, dict):
        for region, payload in nested_results.items():
            if isinstance(payload, dict):
                regions.append((str(region).strip().upper() or "UNKNOWN", payload))
        return regions

    # Region map: {"FR": {...}, "US": {...}}
    has_region_map = any(
        isinstance(v, dict) and len(str(k)) in (2, 3)
        for k, v in watch_providers.items()
    )
    if has_region_map:
        for region, payload in watch_providers.items():
            if isinstance(payload, dict):
                regions.append((str(region).strip().upper() or "UNKNOWN", payload))
        return regions

    # Last resort: treat payload as a single region-like object.
    if any(k in watch_providers for k in _PROVIDER_TYPES):
        regions.append(("UNKNOWN", watch_providers))

    return regions

def fetch_providers(tmdb_id: str | int, is_tv: bool, jsr: dict | None = None):
    """
    Fetch FR streaming providers from Seerr.
    Returns:
      list[dict]   — success as flat raw provider entries
                     each dict entry: {raw_name, logo}
      _FETCH_ERROR — Seerr unreachable/error (caller should not set providers_fetched=True)
    """
    global _fetch_providers_sampled
    media_id = tmdb_id
    if not media_id:
        return []
    media = "tv" if is_tv else "movie"
    resp = _jsr_get(f"/{media}/{media_id}", jsr)

    if resp is _JSR_NOT_CONFIGURED:
        return []
    if resp is _JSR_NOT_FOUND:
        return _JSR_NOT_FOUND
    if resp is _JSR_ERROR:
        return _FETCH_ERROR

    data = resp

    # First successful call: dump structure so we can verify field names
    if not _fetch_providers_sampled:
        _fetch_providers_sampled = True
        top_keys = list(data.keys())
        log.debug(f"[providers] Seerr response keys for {media}/{media_id}: {top_keys}")
        wp_raw = data.get("watchProviders")
        log.debug(f"[providers] watchProviders sample: {json.dumps(wp_raw)[:600] if wp_raw is not None else 'KEY ABSENT'}")

    watch_providers = data.get("watchProviders")
    if watch_providers is None:
        watch_providers = data.get("watch_providers")
    regions = _extract_watch_provider_regions(watch_providers or {})

    providers_by_type_raw: dict[str, list[dict]] = {_PROVIDER_ENRICH_GROUP: []}
    for _, region_payload in regions:
        values = region_payload.get(_PROVIDER_ENRICH_GROUP)
        if isinstance(values, list):
            providers_by_type_raw[_PROVIDER_ENRICH_GROUP].extend(values)

    if not any(providers_by_type_raw.values()) and watch_providers:
        region_keys = [region for region, _ in regions] if regions else []
        log.debug(f"[providers] {media}/{media_id}: no providers extracted (regions: {region_keys or 'none'})")

    result: list[dict] = []
    seen_raw_names: set[str] = set()
    for group in (_PROVIDER_ENRICH_GROUP,):
        for p in providers_by_type_raw[group]:
            if not isinstance(p, dict):
                continue
            raw_name = p.get("name") or p.get("provider_name") or p.get("providerName") or ""
            if not raw_name:
                continue
            raw_name = str(raw_name)
            if raw_name in seen_raw_names:
                continue
            seen_raw_names.add(raw_name)
            log.debug(f"[providers_raw] {media}/{media_id} [{group}]: {raw_name!r}")
            # logoPath (camelCase Seerr) or logo_path (snake_case TMDB passthrough)
            raw_logo = p.get("logoPath") or p.get("logo_path") or p.get("logo")
            if raw_logo and raw_logo.startswith("http"):
                logo = None  # absolute URL — relative path unknown, not stored
            elif raw_logo:
                logo = raw_logo
            else:
                log.warning(f"[providers] No logo field for {raw_name!r} in {media}/{media_id}, raw={p}")
                logo = None
            result.append({"raw_name": raw_name, "logo": logo})
    return result


# ---------------------------------------------------------------------------
# Category / folder config
# ---------------------------------------------------------------------------

def build_categories_from_config(cfg: dict) -> list[dict]:
    """
    Returns list of {"name": str, "type": "movie"|"tv", "folder": str}
    from config.folders where type is 'movie' or 'tv' (not null or 'ignore').
    Respects enable_movies / enable_series flags.
    """
    enable_movies = cfg.get("enable_movies", True)
    enable_series = cfg.get("enable_series", True)
    cats = []
    for f in cfg.get("folders", []):
        ftype = f.get("type")
        if not ftype or ftype == "ignore":
            continue
        if not is_folder_enabled(f):
            continue
        if ftype == "movie" and not enable_movies:
            continue
        if ftype == "tv" and not enable_series:
            continue
        name = f["name"].replace("_", " ").replace("-", " ").title()
        cats.append({"name": name, "type": ftype, "folder": f["name"]})
    return cats


def is_folder_enabled(folder_cfg: dict | None) -> bool:
    """
    Compatibility resolver for folder active state.

    Priority:
    1) folder.enabled
    2) folder.visible (legacy)
    3) True (default)
    """
    if not isinstance(folder_cfg, dict):
        return True
    enabled = folder_cfg.get("enabled")
    if enabled is None:
        enabled = folder_cfg.get("visible", True)
    return enabled is not False


def sync_folders(root: Path, cfg: dict) -> bool:
    """
    Sync config['folders'] with filesystem subdirs of root:
    - New dirs  → add with type=null, enabled=false
    - Missing   → mark missing=True (preserved in config)
    - Existing  → preserve current config (type, enabled)
    Logs a WARNING for each folder with type=null.
    Returns True if cfg was modified (caller should save_config).
    """
    cfg_folders: dict[str, dict] = {f["name"]: dict(f) for f in cfg.get("folders", [])}

    try:
        fs_dirs = {
            d.name for d in root.iterdir()
            if d.is_dir() and not d.name.startswith((".", "@"))
        }
    except Exception as e:
        log.warning(f"[sync_folders] Cannot list {root}: {e}")
        return False

    changed = False

    # Mark missing / un-missing
    for name, folder in cfg_folders.items():
        was_missing = folder.get("missing", False)
        is_missing  = name not in fs_dirs
        if is_missing != was_missing:
            cfg_folders[name]["missing"] = is_missing
            changed = True

    # Add new dirs
    for name in sorted(fs_dirs):
        if name not in cfg_folders:
            cfg_folders[name] = {"name": name, "type": None, "enabled": False}
            changed = True

    cfg["folders"] = list(cfg_folders.values())

    # Single grouped INFO for unconfigured folders (replaces per-folder warnings)
    unconfigured = sorted(
        f["name"] for f in cfg_folders.values()
        if f.get("type") is None and not f.get("missing")
    )
    if unconfigured:
        log.info(f"[sync_folders] {len(unconfigured)} folder(s) skipped (no type configured): {', '.join(unconfigured)}")

    # Warn only when movies/series are enabled but no matching folder is configured
    enable_movies = cfg.get("enable_movies", True)
    enable_series = cfg.get("enable_series", True)
    configured_types = {f.get("type") for f in cfg_folders.values()}
    if enable_movies and "movie" not in configured_types:
        log.warning("[sync_folders] Movies enabled but no 'movie' folder configured")
    if enable_series and "tv" not in configured_types:
        log.warning("[sync_folders] Series enabled but no 'tv' folder configured")

    return changed


def migrate_env_to_config() -> None:
    """
    One-time migration: read legacy env vars (MOVIES_FOLDERS, SERIES_FOLDERS,
    SEERR_URL, etc.) and populate SQLite config if the corresponding fields
    are still at their defaults/empty. Idempotent — safe to call every startup.
    """
    cfg = load_config()
    changed = False
    env_migrated = False  # True only when actual env var values are consumed

    # Seerr bootstrap (supports both SEERR_* and legacy JELLYSEERR_* spellings)
    cfg, seerr_cfg_changed = normalize_seerr_config(cfg)
    changed = changed or seerr_cfg_changed

    raw_env_url = os.environ.get("SEERR_URL")
    if raw_env_url is None:
        raw_env_url = os.environ.get("JELLYSEERR_URL")
    if raw_env_url is None:
        raw_env_url = os.environ.get("JELLYSEER_URL")
    env_url = (raw_env_url or "").strip().rstrip("/")

    raw_env_apikey = os.environ.get("SEERR_API_KEY")
    if raw_env_apikey is None:
        raw_env_apikey = os.environ.get("SEERR_APIKEY")
    if raw_env_apikey is None:
        raw_env_apikey = os.environ.get("JELLYSEERR_APIKEY")
    if raw_env_apikey is None:
        raw_env_apikey = os.environ.get("JELLYSEER_APIKEY")
    env_apikey = (raw_env_apikey or "").strip()

    env_jsr_on = os.environ.get("ENABLE_SEERR", "")
    if not env_jsr_on:
        env_jsr_on = os.environ.get("ENABLE_JELLYSEERR", "")
    jsr = cfg.setdefault("seerr", {})
    if env_url and not jsr.get("url"):
        jsr["url"]     = env_url
        jsr["enabled"] = env_jsr_on.lower() == "true" if env_jsr_on else True
        changed = True
        env_migrated = True
    secrets = _load_secrets()
    secrets, secrets_changed = _normalize_seerr_secret_keys(secrets)
    if secrets_changed:
        _save_secrets(secrets)
    if env_apikey and not secrets.get("seerr_apikey") and not jsr.get("apikey"):
        secrets["seerr_apikey"] = env_apikey
        _save_secrets(secrets)
        log.info("[migrate] Seerr API key migrated to %s", SECRETS_PATH)
        env_migrated = True
    # Remove apikey from SQLite config if still present (migration cleanup)
    if jsr.pop("apikey", None):
        changed = True

    # enable_movies / enable_series
    if "enable_movies" not in cfg:
        env_em = os.environ.get("ENABLE_MOVIES", "")
        if env_em:
            cfg["enable_movies"] = env_em.lower() == "true"
            changed = True
            env_migrated = True
    if "enable_series" not in cfg:
        env_es = os.environ.get("ENABLE_SERIES", "")
        if env_es:
            cfg["enable_series"] = env_es.lower() == "true"
            changed = True
            env_migrated = True

    # Folders from MOVIES_FOLDERS / SERIES_FOLDERS
    env_movies = [f.strip() for f in os.environ.get("MOVIES_FOLDERS", "").split(",") if f.strip()]
    env_series = [f.strip() for f in os.environ.get("SERIES_FOLDERS", "").split(",") if f.strip()]
    if (env_movies or env_series) and not cfg.get("folders"):
        cfg["folders"] = []
        for fname in env_movies:
            cfg["folders"].append({"name": fname, "type": "movie", "enabled": True})
        for fname in env_series:
            cfg["folders"].append({"name": fname, "type": "tv",    "enabled": True})
        changed = True
        env_migrated = True

    # system block defaults
    sys_cfg = cfg.setdefault("system", {})
    if not sys_cfg.get("scan_cron"):
        sys_cfg["scan_cron"] = "0 3 * * *"
        changed = True
    if not sys_cfg.get("log_level"):
        sys_cfg["log_level"] = "INFO"
        changed = True
    ui_cfg = cfg.setdefault("ui", {})
    if "synopsis_on_hover" not in ui_cfg:
        ui_cfg["synopsis_on_hover"] = False
        changed = True

    cfg, score_changed, score_status = normalize_score_configuration_sections(cfg)
    changed = changed or score_changed
    cfg, rec_changed = normalize_recommendations_configuration(cfg)
    changed = changed or rec_changed
    if not score_status.get("weights_valid", False):
        log.warning(
            "[score] Weight total is %s (expected 100) in effective score config",
            score_status.get("weights_total"),
        )

    if changed:
        save_config(cfg)
        if env_migrated:
            log.info("[MIGRATION] Env vars migrated to SQLite config")
        else:
            log.debug("[MIGRATION] Config defaults applied to SQLite config")
    # Warm DB-backed provider metadata; bundled defaults are seeded during DB bootstrap.
    _ensure_runtime_provider_mapping()
    _ensure_runtime_providers_logo()


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v",
    ".ts", ".m2ts", ".mpg", ".mpeg", ".flv", ".webm",
}
IGNORED_EXTENSIONS = {
    ".nfo", ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".tbn", ".svg", ".srt", ".sub", ".ass",
    ".ssa", ".idx", ".txt", ".xml", ".json",
}


def get_dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_symlink() or entry.name.startswith((".', '@")):
                continue
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_dir_size(Path(entry.path))
    except PermissionError as e:
        log.warning(f"Permission denied: {e}")
    return total


def count_media_files(path: Path) -> int:
    count = 0
    try:
        for entry in os.scandir(path):
            if entry.is_symlink() or entry.name.startswith(('.', '@')):
                continue
            if entry.is_file(follow_symlinks=False):
                if Path(entry.name).suffix.lower() in MEDIA_EXTENSIONS:
                    count += 1
            elif entry.is_dir(follow_symlinks=False):
                count += count_media_files(Path(entry.path))
    except PermissionError as e:
        log.warning(f"Permission denied: {e}")
    return count


def _extract_filename_movie(media_dir: Path) -> str | None:
    """Return the name of the largest video file in a movie directory."""
    best: str | None = None
    best_size = -1
    try:
        for entry in media_dir.iterdir():
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            if size > best_size:
                best_size = size
                best = entry.name
    except PermissionError:
        pass
    return best


def _extract_filename_tv(series_dir: Path) -> dict | None:
    """Return {SNN: {ENN: filename}} for all detected video files in a TV series dir."""
    result: dict[str, dict[str, str]] = {}
    try:
        video_files = sorted(
            p for p in series_dir.rglob("*")
            if not p.is_symlink() and p.is_file()
            and p.suffix.lower() in MEDIA_EXTENSIONS
            and not p.name.startswith((".", "@"))
        )
    except PermissionError:
        return None
    for video in video_files:
        season_num, episode_num = _extract_season_episode_from_name(str(video))
        if season_num is None or episode_num is None:
            continue
        season_key = f"S{season_num:02d}"
        episode_key = f"E{episode_num:02d}"
        result.setdefault(season_key, {})[episode_key] = video.name
    return result or None


def format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


_TV_SKIP_NFO = {"tvshow.nfo", "season.nfo"}
_TV_SE_EP_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
_TV_X_SE_EP_RE = re.compile(r"\b(\d{1,2})x(\d{1,3})\b", re.IGNORECASE)
_TV_SEASON_HINT_RE = re.compile(r"(?:season|saison)[\s._-]*(\d{1,2})", re.IGNORECASE)
_TV_EP_TOKEN_RE = re.compile(r"(?:^|[\s._\-])(?:e|ep|episode)[\s._\-]*(\d{1,3})(?=$|[\s._\-])", re.IGNORECASE)
_TV_TRAILING_NUM_RE = re.compile(r"(?:^|[\s._\-])(\d{2,3})$")
_TV_COMMON_TECH_NUMBERS = {2160, 1080, 720, 576, 540, 480}


def _safe_int(value, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        return int(float(str(value).strip()))
    except Exception:
        return default


def _dominant_value(values: list):
    counter = Counter(v for v in values if v not in (None, "", []))
    if not counter:
        return None
    return sorted(counter.items(), key=lambda x: (-x[1], str(x[0])))[0][0]


def _extract_season_episode_from_name(path_like: str) -> tuple[int | None, int | None]:
    if not path_like:
        return None, None

    season_hint = _TV_SEASON_HINT_RE.search(path_like)
    hinted_season = _safe_int(season_hint.group(1), None) if season_hint else None

    match = _TV_SE_EP_RE.search(path_like)
    if match:
        return _safe_int(match.group(1)), _safe_int(match.group(2))
    match = _TV_X_SE_EP_RE.search(path_like)
    if match:
        return _safe_int(match.group(1)), _safe_int(match.group(2))

    # Episode extraction is based on basename to avoid unrelated parent folders.
    basename = Path(path_like).name
    stem = Path(basename).stem

    match = _TV_EP_TOKEN_RE.search(stem)
    if match:
        return hinted_season, _safe_int(match.group(1))

    # Anime-like names often use trailing numeric episodes: "Title.001", "Title - 01".
    # Keep this fallback conservative to avoid confusing quality markers (720/1080/2160).
    match = _TV_TRAILING_NUM_RE.search(stem)
    if match:
        ep_num = _safe_int(match.group(1))
        if isinstance(ep_num, int) and ep_num > 0 and ep_num not in _TV_COMMON_TECH_NUMBERS:
            return hinted_season, ep_num

    if hinted_season is not None:
        return hinted_season, None
    return None, None


def build_season_id(item_id: str, season) -> str | None:
    season_num = _safe_int(season, None)
    if not item_id or season_num is None or season_num < 0:
        return None
    return f"{item_id}:s{season_num:02d}"


def build_episode_id(item_id: str, season=None, episode=None) -> str | None:
    episode_num = _safe_int(episode, None)
    if not item_id or episode_num is None or episode_num <= 0:
        return None
    season_num = _safe_int(season, None)
    if season_num is not None and season_num >= 0:
        return f"{item_id}:s{season_num:02d}e{episode_num:02d}"
    return f"{item_id}:e{episode_num:03d}"


def _build_episode_dedupe_key(season_num: int | None, episode_num: int | None, fallback: str) -> str:
    if season_num is not None and episode_num is not None:
        return f"s{season_num:02d}e{episode_num:02d}"
    if season_num is None and episode_num is not None:
        return f"e{episode_num:03d}"
    return fallback.casefold()


def _episode_fallback_key(path: Path, series_dir: Path | None = None) -> str:
    try:
        base = path.relative_to(series_dir) if isinstance(series_dir, Path) else path
    except Exception:
        base = path
    no_suffix = base.with_suffix("")
    return str(no_suffix).replace("\\", "/").casefold()


def _episode_metadata_completeness(ep: dict) -> int:
    score = 0
    for key in (
        "resolution",
        "width",
        "height",
        "codec",
        "audio_codec_raw",
        "audio_codec",
        "audio_channels",
        "audio_languages",
        "subtitle_languages",
        "video_bitrate",
        "hdr_type",
        "runtime_min",
        "size_b",
    ):
        val = ep.get(key)
        if val not in (None, "", [], 0):
            score += 1
    return score


def _prefer_episode_metadata(current: dict | None, candidate: dict) -> dict:
    if current is None:
        return candidate
    cur_score = _episode_metadata_completeness(current)
    new_score = _episode_metadata_completeness(candidate)
    if new_score > cur_score:
        return candidate
    if new_score < cur_score:
        return current
    if int(candidate.get("size_b") or 0) > int(current.get("size_b") or 0):
        return candidate
    return current


def _parse_episode_nfo_metadata(nfo_path: Path, series_dir: Path | None = None, item_id: str | None = None) -> dict | None:
    try:
        root = ET.parse(nfo_path).getroot()
    except Exception:
        return None

    rel_hint = str(nfo_path)
    season_num = _safe_int((root.findtext("season") or "").strip(), None)
    episode_num = _safe_int((root.findtext("episode") or "").strip(), None)
    if season_num is None or episode_num is None:
        inferred_season, inferred_episode = _extract_season_episode_from_name(rel_hint)
        if season_num is None:
            season_num = inferred_season
        if episode_num is None:
            episode_num = inferred_episode
    video = root.find(".//fileinfo/streamdetails/video")
    audio = root.find(".//fileinfo/streamdetails/audio")

    width = _safe_int(video.findtext("width") if video is not None else None, None)
    height = _safe_int(video.findtext("height") if video is not None else None, None)
    resolution = classify_resolution(width, height) if width and height else None

    raw_codec = (video.findtext("codec") if video is not None else None)
    codec = normalize_codec(raw_codec)
    if _is_unknown_sentinel(codec):
        codec = None

    hdr_type = (video.findtext("hdrtype") if video is not None else None) or None
    if isinstance(hdr_type, str):
        hdr_type = hdr_type.strip() or None
    hdr = bool(hdr_type)

    runtime_min = _safe_int(
        (video.findtext("duration") if video is not None else None)
        or root.findtext("runtime")
        or root.findtext("durationinseconds"),
        None,
    )

    raw_audio = (audio.findtext("codec") if audio is not None else None) or root.findtext("audio_codec") or root.findtext("audiocodec")
    audio_norm = normalize_audio_codec(raw_audio)

    langs = parse_audio_languages(root)
    audio_languages_simple = simplify_audio_languages(langs)
    if _is_unknown_sentinel(audio_languages_simple):
        audio_languages_simple = None
    audio_channels = parse_audio_channels(root)
    subtitle_languages = parse_subtitle_languages(root) or None
    video_bitrate = parse_video_bitrate(root)

    size_b = 0
    for ext in MEDIA_EXTENSIONS:
        candidate = nfo_path.with_suffix(ext)
        if candidate.exists() and candidate.is_file():
            try:
                size_b = int(candidate.stat().st_size)
            except Exception:
                size_b = 0
            break

    dedupe_key = _build_episode_dedupe_key(
        season_num,
        episode_num,
        fallback=_episode_fallback_key(nfo_path, series_dir),
    )
    episode_id = build_episode_id(item_id, season=season_num, episode=episode_num)
    out = {
        "season": season_num,
        "episode": episode_num,
        "dedupe_key": dedupe_key,
        "size_b": max(0, int(size_b or 0)),
        "width": width,
        "height": height,
        "resolution": resolution,
        "codec": codec,
        "audio_codec_raw": audio_norm.get("raw"),
        "audio_codec": audio_norm.get("normalized"),
        "audio_channels": audio_channels,
        "audio_languages": langs,
        "audio_languages_simple": audio_languages_simple,
        "subtitle_languages": subtitle_languages,
        "video_bitrate": video_bitrate,
        "hdr": hdr,
        "hdr_type": hdr_type,
        "runtime_min": runtime_min,
    }
    if episode_id:
        out["episode_id"] = episode_id
    return out


def _parse_episode_files_without_nfo(series_dir: Path, existing_keys: set[str], item_id: str | None = None) -> list[dict]:
    parsed: list[dict] = []
    try:
        files = sorted(
            p for p in series_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS and not p.name.startswith("._")
        )
    except Exception:
        return parsed

    for video in files:
        if video.with_suffix(".nfo").exists():
            continue
        season_num, episode_num = _extract_season_episode_from_name(str(video))
        key = _build_episode_dedupe_key(
            season_num,
            episode_num,
            fallback=_episode_fallback_key(video, series_dir),
        )
        if key in existing_keys:
            continue
        try:
            size_b = int(video.stat().st_size)
        except Exception:
            size_b = 0
        episode_id = build_episode_id(item_id, season=season_num, episode=episode_num)
        ep = {
            "season": season_num,
            "episode": episode_num,
            "dedupe_key": key,
            "size_b": max(0, size_b),
            "width": None,
            "height": None,
            "resolution": None,
            "codec": None,
            "audio_codec_raw": None,
            "audio_codec": None,
            "audio_channels": None,
            "audio_languages": [],
            "audio_languages_simple": None,
            "subtitle_languages": None,
            "video_bitrate": None,
            "hdr": False,
            "hdr_type": None,
            "runtime_min": None,
        }
        if episode_id:
            ep["episode_id"] = episode_id
        parsed.append(ep)
    return parsed


def collect_series_episode_metadata(series_dir: Path, item_id: str | None = None) -> list[dict]:
    deduped: dict[str, dict] = {}
    try:
        nfo_candidates = sorted(
            p for p in series_dir.rglob("*.nfo")
            if p.is_file() and p.name.lower() not in _TV_SKIP_NFO and not p.name.startswith("._")
        )
    except Exception:
        nfo_candidates = []

    for nfo_path in nfo_candidates:
        ep = _parse_episode_nfo_metadata(nfo_path, series_dir=series_dir, item_id=item_id)
        if not isinstance(ep, dict):
            continue
        key = ep["dedupe_key"]
        deduped[key] = _prefer_episode_metadata(deduped.get(key), ep)

    for ep in _parse_episode_files_without_nfo(series_dir, set(deduped.keys()), item_id=item_id):
        key = ep["dedupe_key"]
        deduped[key] = _prefer_episode_metadata(deduped.get(key), ep)

    return list(deduped.values())


def _aggregate_audio_languages_from_episodes(episodes: list[dict]) -> list[str]:
    total = len(episodes)
    if total <= 0:
        return []
    threshold = 1 if total <= 2 else max(2, int(math.ceil(total * 0.20)))
    lang_counter: Counter = Counter()
    for ep in episodes:
        langs = ep.get("audio_languages") or []
        if not isinstance(langs, list):
            continue
        for lang in sorted(set(langs)):
            if lang:
                lang_counter[lang] += 1
    selected = [lang for lang, count in lang_counter.items() if count >= threshold]
    if not selected and lang_counter:
        selected = [lang for lang, _ in sorted(lang_counter.items(), key=lambda x: (-x[1], x[0]))[:2]]
    return sorted(selected)


_AUDIO_CHANNELS_PRIORITY: dict[str, int] = {
    "1.0": 1,
    "2.0": 2,
    "5.1": 3,
    "7.1": 4,
}


def _audio_channels_tie_break(value: str) -> tuple[int, int]:
    priority = _AUDIO_CHANNELS_PRIORITY.get(value, 0)
    base = 0
    if isinstance(value, str):
        try:
            base = int(float(value))
        except Exception:
            base = 0
    return priority, base


def _dominant_audio_channels(values: list) -> str | None:
    normalized_values: list[str] = []
    for value in values:
        normalized = normalize_audio_channels(value)
        if normalized:
            normalized_values.append(normalized)
    counter = Counter(normalized_values)
    if not counter:
        return None
    return sorted(
        counter.items(),
        key=lambda x: (-x[1], -_audio_channels_tie_break(x[0])[0], -_audio_channels_tie_break(x[0])[1], str(x[0])),
    )[0][0]


def _aggregate_subtitle_languages_from_episodes(episodes: list[dict]) -> list[str]:
    collected: set[str] = set()
    for ep in episodes:
        langs = ep.get("subtitle_languages")
        if not isinstance(langs, list):
            continue
        for lang in langs:
            if isinstance(lang, str) and lang.strip():
                collected.add(lang.strip())
    return sorted(collected)


def _average_video_bitrate_from_episodes(episodes: list[dict]) -> int | None:
    values = [
        int(ep.get("video_bitrate"))
        for ep in episodes
        if isinstance(ep.get("video_bitrate"), int) and int(ep.get("video_bitrate")) > 0
    ]
    if not values:
        return None
    return int(round(sum(values) / len(values)))


def _season_weight(season: dict) -> int:
    weight = _safe_int((season or {}).get("episodes_found"), 0) or 0
    return weight if weight > 0 else 1


def _dominant_value_from_seasons(seasons: list[dict], field: str):
    weighted: dict = defaultdict(int)
    for season in seasons:
        if not isinstance(season, dict):
            continue
        val = season.get(field)
        if val in (None, "", []):
            continue
        weighted[val] += _season_weight(season)
    if not weighted:
        return None
    return sorted(weighted.items(), key=lambda x: (-x[1], str(x[0])))[0][0]


def _dominant_series_value(seasons: list[dict], episodes: list[dict], field: str):
    value = _dominant_value_from_seasons(seasons, field)
    if value not in (None, "", []):
        return value
    return _dominant_value([e.get(field) for e in episodes])


def _aggregate_audio_languages_from_seasons(seasons: list[dict]) -> list[str]:
    total_weight = sum(_season_weight(s) for s in seasons if isinstance(s, dict))
    if total_weight <= 0:
        return []
    threshold = max(1, int(math.ceil(total_weight * 0.20)))
    lang_counter: Counter = Counter()
    for season in seasons:
        if not isinstance(season, dict):
            continue
        langs = season.get("audio_languages") or []
        if not isinstance(langs, list):
            continue
        w = _season_weight(season)
        for lang in sorted(set(langs)):
            if lang:
                lang_counter[lang] += w
    selected = [lang for lang, count in lang_counter.items() if count >= threshold]
    if not selected and lang_counter:
        selected = [lang for lang, _ in sorted(lang_counter.items(), key=lambda x: (-x[1], x[0]))[:2]]
    return sorted(selected)


def _aggregate_series_quality_from_seasons(
    seasons: list[dict],
    *,
    score_config: dict | None = None,
    fallback_item_for_score: dict | None = None,
) -> dict:
    weighted_total = 0
    acc: dict[str, float] = defaultdict(float)
    for season in seasons:
        if not isinstance(season, dict):
            continue
        q = season.get("quality")
        if not isinstance(q, dict):
            continue
        w = _season_weight(season)
        weighted_total += w
        for k in ("video", "audio", "languages", "size", "video_w", "audio_w", "languages_w", "size_w"):
            acc[k] += _as_number(q.get(k), 0.0) * w
        vd = q.get("video_details") if isinstance(q.get("video_details"), dict) else {}
        ad = q.get("audio_details") if isinstance(q.get("audio_details"), dict) else {}
        acc["vd_resolution"] += _as_number(vd.get("resolution"), 0.0) * w
        acc["vd_codec"] += _as_number(vd.get("codec"), 0.0) * w
        acc["vd_hdr"] += _as_number(vd.get("hdr"), 0.0) * w
        acc["ad_codec"] += _as_number(ad.get("codec"), 0.0) * w
        acc["ad_channels"] += _as_number(ad.get("channels"), 0.0) * w

    if weighted_total <= 0:
        if isinstance(fallback_item_for_score, dict):
            return compute_quality(fallback_item_for_score, score_config) if isinstance(score_config, dict) else compute_quality(fallback_item_for_score)
        return {}

    video_details = {
        "resolution": int(round(acc["vd_resolution"] / weighted_total)),
        "codec": int(round(acc["vd_codec"] / weighted_total)),
        "hdr": int(round(acc["vd_hdr"] / weighted_total)),
    }
    audio_details = {
        "codec": int(round(acc["ad_codec"] / weighted_total)),
        "channels": int(round(acc["ad_channels"] / weighted_total)),
    }
    quality = {
        "video_details": video_details,
        "audio_details": audio_details,
        "video": int(video_details["resolution"] + video_details["codec"] + video_details["hdr"]),
        "audio": int(round(acc["audio"] / weighted_total)),
        "languages": int(round(acc["languages"] / weighted_total)),
        "size": int(round(acc["size"] / weighted_total)),
        "video_w": round(acc["video_w"] / weighted_total, 4),
        "audio_w": round(acc["audio_w"] / weighted_total, 4),
        "languages_w": round(acc["languages_w"] / weighted_total, 4),
        "size_w": round(acc["size_w"] / weighted_total, 4),
    }
    quality["score"] = int(round(quality["video_w"] + quality["audio_w"] + quality["languages_w"] + quality["size_w"]))
    return quality


def aggregate_season_metadata(
    season_number: int,
    season_episodes: list[dict],
    *,
    item_id: str | None = None,
    episodes_expected: int | None = None,
    score_config: dict | None = None,
    include_quality: bool = True,
) -> dict:
    episodes_found = len(season_episodes)
    dominant_resolution = _dominant_value([e.get("resolution") for e in season_episodes])
    dominant_width = _dominant_value([e.get("width") for e in season_episodes])
    dominant_height = _dominant_value([e.get("height") for e in season_episodes])
    dominant_codec = _dominant_value([e.get("codec") for e in season_episodes])
    dominant_audio_raw = _dominant_value([e.get("audio_codec_raw") for e in season_episodes])
    dominant_audio = _dominant_value([e.get("audio_codec") for e in season_episodes])
    dominant_audio_channels = _dominant_audio_channels([e.get("audio_channels") for e in season_episodes])
    dominant_hdr_type = _dominant_value([e.get("hdr_type") for e in season_episodes])
    dominant_hdr = bool(dominant_hdr_type)
    if not dominant_hdr and any(bool(e.get("hdr")) for e in season_episodes):
        dominant_hdr = True

    known_runtimes = [int(e["runtime_min"]) for e in season_episodes if isinstance(e.get("runtime_min"), int) and e.get("runtime_min") > 0]
    runtime_min_total = int(sum(known_runtimes)) if known_runtimes else 0
    runtime_min_avg = int(round(runtime_min_total / len(known_runtimes))) if known_runtimes else None

    size_b = int(sum(int(e.get("size_b") or 0) for e in season_episodes))
    audio_languages = _aggregate_audio_languages_from_episodes(season_episodes)
    audio_languages_simple = simplify_audio_languages(audio_languages)
    subtitle_languages = _aggregate_subtitle_languages_from_episodes(season_episodes) or None
    video_bitrate = _average_video_bitrate_from_episodes(season_episodes)
    if _is_unknown_sentinel(audio_languages_simple):
        audio_languages_simple = None

    out = {
        "season": int(season_number),
        "episodes_found": int(episodes_found),
        "episodes_expected": int(episodes_expected) if isinstance(episodes_expected, int) and episodes_expected >= 0 else None,
        "resolution": dominant_resolution,
        "width": dominant_width,
        "height": dominant_height,
        "codec": dominant_codec,
        "audio_codec_raw": dominant_audio_raw,
        "audio_codec": dominant_audio,
        "audio_channels": dominant_audio_channels,
        "audio_languages": audio_languages,
        "audio_languages_simple": audio_languages_simple,
        "subtitle_languages": subtitle_languages,
        "video_bitrate": video_bitrate,
        "hdr": dominant_hdr,
        "hdr_type": dominant_hdr_type,
        "runtime_min_total": runtime_min_total,
        "runtime_min_avg": runtime_min_avg,
        "size_b": size_b,
        "size": format_size(size_b),
    }
    season_id = build_season_id(item_id or "", season_number)
    if season_id:
        out["season_id"] = season_id
    if include_quality:
        season_item_for_score = {
            "type": "tv",
            "resolution": dominant_resolution,
            "width": dominant_width,
            "height": dominant_height,
            "codec": dominant_codec,
            "audio_codec_raw": dominant_audio_raw,
            "audio_codec": dominant_audio,
            "audio_languages": audio_languages,
            "audio_languages_simple": audio_languages_simple,
            "hdr": dominant_hdr,
            "hdr_type": dominant_hdr_type,
            "size_b": size_b,
        }
        out["quality"] = compute_quality(season_item_for_score, score_config) if isinstance(score_config, dict) else compute_quality(season_item_for_score)
    return out


def aggregate_series_metadata(
    series_episodes: list[dict],
    *,
    item_id: str | None = None,
    score_config: dict | None = None,
    season_expected_counts: dict[int, int] | None = None,
    include_quality: bool = True,
) -> dict:
    by_season: dict[int, list[dict]] = defaultdict(list)
    seasonless_episodes: list[dict] = []
    for ep in series_episodes:
        season_num = _safe_int(ep.get("season"), None)
        if season_num is None:
            seasonless_episodes.append(ep)
        else:
            by_season[int(season_num)].append(ep)

    seasons: list[dict] = []
    expected = season_expected_counts or {}
    season_numbers = sorted(set(by_season.keys()) | set(expected.keys()))
    for season_num in season_numbers:
        season_eps = by_season.get(season_num, [])
        seasons.append(
            aggregate_season_metadata(
                season_num,
                season_eps,
                item_id=item_id,
                episodes_expected=expected.get(season_num),
                score_config=score_config,
                include_quality=include_quality,
            )
        )

    all_episodes = [*series_episodes]
    resolution = _dominant_series_value(seasons, all_episodes, "resolution")
    width = _dominant_series_value(seasons, all_episodes, "width")
    height = _dominant_series_value(seasons, all_episodes, "height")
    codec = _dominant_series_value(seasons, all_episodes, "codec")
    audio_codec_raw = _dominant_series_value(seasons, all_episodes, "audio_codec_raw")
    audio_codec = _dominant_series_value(seasons, all_episodes, "audio_codec")
    audio_channels = _dominant_audio_channels([e.get("audio_channels") for e in all_episodes])
    hdr_type = _dominant_series_value(seasons, all_episodes, "hdr_type")
    hdr = bool(hdr_type) or any(bool((s or {}).get("hdr")) for s in seasons if isinstance(s, dict)) or any(bool(e.get("hdr")) for e in all_episodes)

    season_runtime_totals = [
        _safe_int((s or {}).get("runtime_min_total"), 0) or 0
        for s in seasons
        if isinstance(s, dict)
    ]
    seasonless_runtimes = [
        _safe_int(e.get("runtime_min"), 0) or 0
        for e in seasonless_episodes
        if isinstance(e, dict)
    ]
    runtime_min = int(sum(season_runtime_totals) + sum(seasonless_runtimes)) if season_runtime_totals or seasonless_runtimes else 0
    episode_count = int(sum((_safe_int((s or {}).get("episodes_found"), 0) or 0) for s in seasons if isinstance(s, dict))) + len(seasonless_episodes)
    runtime_min_avg = int(round(runtime_min / episode_count)) if runtime_min > 0 and episode_count > 0 else None
    season_count = len(seasons)
    size_b = int(sum((_safe_int((s or {}).get("size_b"), 0) or 0) for s in seasons if isinstance(s, dict)) + sum((_safe_int((e or {}).get("size_b"), 0) or 0) for e in seasonless_episodes if isinstance(e, dict)))

    audio_languages = sorted(set(_aggregate_audio_languages_from_seasons(seasons)) | set(_aggregate_audio_languages_from_episodes(seasonless_episodes)))
    subtitle_languages = _aggregate_subtitle_languages_from_episodes(all_episodes) or None
    video_bitrate = _average_video_bitrate_from_episodes(all_episodes)
    audio_languages_simple = simplify_audio_languages(audio_languages)
    if _is_unknown_sentinel(audio_languages_simple):
        audio_languages_simple = None

    expected_values = [
        _safe_int((s or {}).get("episodes_expected"), None)
        for s in seasons
        if isinstance(s, dict)
    ]
    known_expected = [v for v in expected_values if isinstance(v, int) and v >= 0]
    episodes_expected = int(sum(known_expected)) if expected_values and len(known_expected) == len(expected_values) else None

    series_item_for_score = {
        "type": "tv",
        "resolution": resolution,
        "width": width,
        "height": height,
        "codec": codec,
        "audio_codec_raw": audio_codec_raw,
        "audio_codec": audio_codec,
        "audio_channels": audio_channels,
        "audio_languages": audio_languages,
        "audio_languages_simple": audio_languages_simple,
        "subtitle_languages": subtitle_languages,
        "video_bitrate": video_bitrate,
        "hdr": hdr,
        "hdr_type": hdr_type,
        "size_b": size_b,
    }
    out = {
        "seasons": seasons,
        "season_count": season_count,
        "episode_count": episode_count,
        "episodes_expected": episodes_expected,
        "size_b": size_b,
        "resolution": resolution,
        "width": width,
        "height": height,
        "runtime_min": runtime_min,
        "runtime_min_avg": runtime_min_avg,
        "codec": codec,
        "audio_codec_raw": audio_codec_raw,
        "audio_codec": audio_codec,
        "audio_channels": audio_channels,
        "audio_languages": audio_languages,
        "audio_languages_simple": audio_languages_simple,
        "subtitle_languages": subtitle_languages,
        "video_bitrate": video_bitrate,
        "hdr": hdr,
        "hdr_type": hdr_type,
    }
    if include_quality:
        out["quality"] = _aggregate_series_quality_from_seasons(
            seasons,
            score_config=score_config,
            fallback_item_for_score=series_item_for_score,
        )
    return out


def _extract_seerr_expected_counts(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    episodes_expected = _safe_int(
        payload.get("numberOfEpisodes")
        or payload.get("number_of_episodes")
        or payload.get("episodeCount")
        or payload.get("episode_count"),
        None,
    )
    season_count_expected = _safe_int(
        payload.get("numberOfSeasons")
        or payload.get("number_of_seasons")
        or payload.get("seasonCount")
        or payload.get("season_count"),
        None,
    )
    season_episode_counts: dict[int, int] = {}
    seasons = payload.get("seasons")
    if isinstance(seasons, list):
        for season in seasons:
            if not isinstance(season, dict):
                continue
            season_num = _safe_int(season.get("seasonNumber") or season.get("season_number"), None)
            if season_num is None:
                continue
            ep_expected = _safe_int(
                season.get("episodeCount")
                or season.get("episode_count")
                or season.get("episodes")
                or season.get("episodes_count"),
                None,
            )
            if isinstance(ep_expected, int) and ep_expected >= 0:
                season_episode_counts[int(season_num)] = int(ep_expected)
    if episodes_expected is None and season_episode_counts:
        episodes_expected = int(sum(season_episode_counts.values()))
    if season_count_expected is None and season_episode_counts:
        season_count_expected = len(season_episode_counts)
    if episodes_expected is None and season_count_expected is None and not season_episode_counts:
        return None
    return {
        "episodes_expected": episodes_expected,
        "season_count_expected": season_count_expected,
        "season_episode_counts": season_episode_counts,
    }


def _fetch_tv_expected_counts_from_seerr(
    *,
    tvdb_id: str | int | None,
    tmdb_id: str | int | None,
    title: str | None,
    year: str | int | None,
    jsr: dict | None,
) -> dict | None:
    if not isinstance(jsr, dict) or not jsr.get("enabled") or not jsr.get("url") or not jsr.get("apikey"):
        return None
    candidate_ids = []
    if tvdb_id not in (None, ""):
        candidate_ids.append(str(tvdb_id))
    if tmdb_id not in (None, "") and str(tmdb_id) not in candidate_ids:
        candidate_ids.append(str(tmdb_id))
    for candidate in candidate_ids:
        resp = _jsr_get(f"/tv/{candidate}", jsr)
        if resp in (_JSR_NOT_CONFIGURED, _JSR_NOT_FOUND, _JSR_ERROR):
            continue
        counts = _extract_seerr_expected_counts(resp)
        if counts:
            return counts

    resolved = _resolve_ids_from_search(title, year, is_tv=True, jsr=jsr)
    if resolved is _FETCH_ERROR or not isinstance(resolved, dict):
        return None
    resolved_tvdb = resolved.get("tvdb_id")
    resolved_tmdb = resolved.get("tmdb_id")
    for candidate in (resolved_tvdb, resolved_tmdb):
        if candidate in (None, ""):
            continue
        resp = _jsr_get(f"/tv/{candidate}", jsr)
        if resp in (_JSR_NOT_CONFIGURED, _JSR_NOT_FOUND, _JSR_ERROR):
            continue
        counts = _extract_seerr_expected_counts(resp)
        if counts:
            return counts
    return None


def merge_series_expected_counts_from_seerr(series_item: dict, expected_counts: dict | None) -> dict:
    if not isinstance(series_item, dict):
        return series_item
    if not isinstance(expected_counts, dict):
        series_item["episodes_expected"] = None
        return series_item

    episodes_expected = expected_counts.get("episodes_expected")
    if isinstance(episodes_expected, int) and episodes_expected >= 0:
        series_item["episodes_expected"] = episodes_expected
    else:
        series_item["episodes_expected"] = None

    season_expected = expected_counts.get("season_episode_counts")
    if isinstance(season_expected, dict):
        by_season = {
            int(s.get("season")): s
            for s in (series_item.get("seasons") or [])
            if isinstance(s, dict) and isinstance(s.get("season"), int)
        }
        for season_num, expected_ep in season_expected.items():
            if not isinstance(expected_ep, int) or expected_ep < 0:
                continue
            if season_num in by_season:
                by_season[season_num]["episodes_expected"] = expected_ep
                continue
            placeholder = aggregate_season_metadata(
                int(season_num),
                [],
                item_id=series_item.get("id"),
                episodes_expected=expected_ep,
                score_config=None,
            )
            by_season[season_num] = placeholder
        series_item["seasons"] = [by_season[k] for k in sorted(by_season.keys())]

    season_count_expected = expected_counts.get("season_count_expected")
    if isinstance(season_count_expected, int) and season_count_expected > 0:
        current = _safe_int(series_item.get("season_count"), 0) or 0
        series_item["season_count"] = max(current, int(season_count_expected))
    return series_item


def _inventory_item_id(media_type: str, category: str, folder_name: str) -> str:
    return f"{media_type}:{category}:{folder_name}"


def _list_video_files(path: Path) -> list[str]:
    files: list[str] = []
    try:
        for entry in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if (
                entry.is_file()
                and not entry.is_symlink()
                and entry.suffix.lower() in MEDIA_EXTENSIONS
            ):
                files.append(entry.name)
    except Exception:
        return []
    return files


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_existing(output_path: str) -> dict:
    # Use availability='all' so absent items (is_available=0) are included as prev data.
    # This preserves quality/enrichment even for items temporarily off-disk.
    data = load_library_document_non_blocking(output_path, availability="all")
    if not isinstance(data, dict):
        return {}
    try:
        return {item["path"]: item for item in data.get("items", []) if isinstance(item, dict) and item.get("path")}
    except Exception:
        return {}


def write_json(data: dict, output_path: str) -> None:
    if _is_library_output_path(output_path) and media_repository is not None:
        media_repository.save_library(data, output_path)
        log.debug("[library] Written to SQLite")
        return
    if not _is_canonical_runtime_json_path(output_path):
        _write_json_file_atomic(data, output_path)
        return
    raise RuntimeError(f"Runtime JSON writes are disabled: {output_path}")


def _is_library_output_path(output_path: str | Path) -> bool:
    return str(Path(output_path)) == str(Path(OUTPUT_PATH))


def _is_canonical_runtime_json_path(output_path: str | Path) -> bool:
    path = Path(output_path)
    return path in {
        runtime_paths.CONFIG_JSON,
        runtime_paths.PROVIDERS_MAPPING_JSON,
        runtime_paths.PROVIDERS_LOGO_JSON,
        runtime_paths.RECOMMENDATIONS_RULES_JSON,
        runtime_paths.LIBRARY_JSON,
        runtime_paths.RECOMMENDATIONS_JSON,
        runtime_paths.MEDIA_PROBE_CACHE_JSON,
        runtime_paths.LIBRARY_PROBE_JSON,
    }


def _write_json_file_atomic(data: dict, output_path: str | Path) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, output)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def load_library_document_non_blocking(path: str, availability: str = "available") -> dict | None:
    """Load library document from SQLite."""
    if media_repository is not None:
        document = media_repository.load_library(path, availability=availability)
        if isinstance(document, dict):
            items = document.get("items", [])
            if isinstance(items, list):
                return document
            raise ValueError("library.items must be an array")
        return None  # Empty or new library — not an error
    log.error("[library] SQLite media repository unavailable")
    return None


def library_document_exists(path: str | None = None) -> bool:
    target_path = path or OUTPUT_PATH
    document = load_library_document_non_blocking(target_path)
    return isinstance(document, dict) and isinstance(document.get("items"), list)


# ---------------------------------------------------------------------------
# Config helpers (SQLite)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict = {
    "system": {
        "scan_cron": "0 3 * * *",
        "log_level": "INFO",
        "needs_onboarding": True,
    },
    "folders": [],
    "enable_movies": True,
    "enable_series": True,
    "seerr": {
        "enabled": False,
        "url": "",
    },
    "ui": {
        "synopsis_on_hover": False,
        "default_view": "grid",
        "default_sort": "title-asc",
        "theme": "dark",
        "accent_color": "#7c6aff",
    },
    "score": {
        "enabled": False,
    },
    "recommendations": {
        "enabled": False,
    },
    "media_probe": {
        "enabled": False,
        "mode": "compare",
        "workers": 4,
        "cache_enabled": True,
    },
    "score_configuration": get_builtin_score_defaults(),
}


def _load_default_config() -> dict:
    return copy.deepcopy(_DEFAULT_CONFIG)


def load_config() -> dict:
    if config_repository is None:
        raise RuntimeError("SQLite config repository unavailable")
    try:
        cfg = config_repository.load_config(CONFIG_PATH)
    except Exception as e:
        log.error("[config] SQLite config unavailable: %s", e)
        raise
    if not isinstance(cfg, dict):
        raise RuntimeError("SQLite config is empty; run database bootstrap/seed before loading config")
    cfg, seerr_changed = normalize_seerr_config(cfg)
    cfg, changed, _ = normalize_score_configuration_sections(cfg)
    cfg, rec_changed = normalize_recommendations_configuration(cfg)
    cfg, probe_changed = normalize_media_probe_configuration(cfg)
    if seerr_changed or changed or rec_changed or probe_changed:
        try:
            save_config(cfg)
        except Exception as e:
            log.warning("[config] Could not normalize SQLite config: %s", e)
    return cfg


def _config_file_exists() -> bool:
    return Path(CONFIG_PATH).exists()


def _has_usable_config(cfg: dict) -> bool:
    folders = cfg.get("folders") or []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        ftype = folder.get("type")
        if ftype in ("movie", "tv") and not folder.get("missing", False):
            return True
    return False


def _derive_needs_onboarding(cfg: dict, config_exists: bool) -> bool:
    system = cfg.get("system") or {}
    if isinstance(system.get("needs_onboarding"), bool):
        return system["needs_onboarding"]
    if not config_exists:
        return True
    return not _has_usable_config(cfg)


def _ensure_needs_onboarding(cfg: dict, config_exists: bool | None = None) -> tuple[dict, bool]:
    if config_exists is None:
        config_exists = _config_file_exists()
    system = cfg.setdefault("system", {})
    changed = False
    if not isinstance(system.get("needs_onboarding"), bool):
        system["needs_onboarding"] = _derive_needs_onboarding(cfg, config_exists)
        changed = True
    return cfg, changed


def _finalize_needs_onboarding_after_config_update(cfg: dict) -> bool:
    """
    Keep onboarding deterministic after onboarding/settings saves.
    Once a usable media folder exists, onboarding is considered completed.
    """
    if not isinstance(cfg, dict):
        return False
    if not _has_usable_config(cfg):
        return False
    system = cfg.setdefault("system", {})
    if system.get("needs_onboarding") is False:
        return False
    system["needs_onboarding"] = False
    return True


def _is_score_enabled(cfg: dict | None) -> bool:
    score = (cfg or {}).get("score")
    if isinstance(score, dict) and isinstance(score.get("enabled"), bool):
        return score.get("enabled") is True
    system = (cfg or {}).get("system") or {}
    return system.get("enable_score") is True


def _is_recommendations_enabled(cfg: dict | None) -> bool:
    if not _is_score_enabled(cfg):
        return False
    rec = (cfg or {}).get("recommendations")
    return isinstance(rec, dict) and rec.get("enabled") is True


def normalize_media_probe_configuration(cfg: dict) -> tuple[dict, bool]:
    changed = False
    probe = cfg.get("media_probe")
    enabled = isinstance(probe, dict) and probe.get("enabled") is True
    mode = (probe or {}).get("mode") if isinstance(probe, dict) else None
    workers = _clamp_int(_as_int(probe.get("workers") if isinstance(probe, dict) else None, 4), 1, 8)
    cache_enabled = True if not isinstance(probe, dict) else probe.get("cache_enabled") is not False
    normalized = {
        "enabled": bool(enabled),
        "mode": "compare" if mode in (None, "", "compare") else str(mode),
        "workers": workers,
        "cache_enabled": bool(cache_enabled),
    }
    if probe != normalized:
        cfg["media_probe"] = normalized
        changed = True
    return cfg, changed


def normalize_recommendations_configuration(cfg: dict) -> tuple[dict, bool]:
    changed = False
    rec = cfg.get("recommendations")
    enabled = isinstance(rec, dict) and rec.get("enabled") is True
    normalized = {"enabled": bool(enabled and _is_score_enabled(cfg))}
    if rec != normalized:
        cfg["recommendations"] = normalized
        changed = True
    return cfg, changed


def normalize_folder_enabled_flags(cfg: dict, drop_visible: bool = False) -> bool:
    """
    Normalize folder active state to `enabled`.

    - If `enabled` is missing, derive it from legacy `visible` (default True)
    - Optionally drop `visible` once normalized
    """
    folders = cfg.get("folders")
    if not isinstance(folders, list):
        return False
    changed = False
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        if folder.get("enabled") is None:
            folder["enabled"] = is_folder_enabled(folder)
            changed = True
        if drop_visible and "visible" in folder:
            folder.pop("visible", None)
            changed = True
    return changed


def save_config(data: dict) -> None:
    if config_repository is not None:
        config_repository.save_config(data, CONFIG_PATH)
        return
    raise RuntimeError("SQLite config repository unavailable")


def deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge update into base, returning a new dict."""
    result = dict(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _extract_legacy_score_configuration(score_block: dict | None) -> dict:
    if not isinstance(score_block, dict):
        return {}
    return {k: v for k, v in score_block.items() if k != "enabled"}


def _migrate_score_enabled_flag(cfg: dict) -> tuple[dict, bool]:
    changed = False
    score_block = cfg.get("score")
    system = cfg.setdefault("system", {})

    enabled_value = None
    if isinstance(score_block, dict) and isinstance(score_block.get("enabled"), bool):
        enabled_value = score_block.get("enabled")
    elif isinstance(system.get("enable_score"), bool):
        enabled_value = system.get("enable_score")

    if enabled_value is None:
        enabled_value = False

    normalized_score = {"enabled": bool(enabled_value)}
    if score_block != normalized_score:
        cfg["score"] = normalized_score
        changed = True

    if "enable_score" in system:
        system.pop("enable_score", None)
        changed = True
    return cfg, changed


def normalize_score_configuration_sections(cfg: dict) -> tuple[dict, bool, dict]:
    defaults = load_score_defaults()
    changed = False

    legacy_score = cfg.get("score")
    legacy_details = _extract_legacy_score_configuration(legacy_score)

    cfg, flag_changed = _migrate_score_enabled_flag(cfg)
    changed = changed or flag_changed

    current_detailed = cfg.get("score_configuration")
    if legacy_details:
        merged_legacy = deep_merge(copy.deepcopy(legacy_details), current_detailed if isinstance(current_detailed, dict) else {})
        if current_detailed != merged_legacy:
            cfg["score_configuration"] = merged_legacy
            current_detailed = merged_legacy
            changed = True

    effective_score, status = validate_score_config(
        merge_score_config(defaults, current_detailed if isinstance(current_detailed, dict) else {}),
        defaults=defaults,
    )
    if (not isinstance(current_detailed, dict)) or current_detailed != effective_score:
        cfg["score_configuration"] = effective_score
        changed = True
    return cfg, changed, status


_SCORE_REQUIRED_DEFAULT_PATHS = (
    "video.resolution.default",
    "video.codec.default",
    "video.hdr.default",
    "audio.codec.default",
    "audio.channels.default",
    "languages.profile.default",
    "size.points.default",
    "size.profiles.movie.default.default.min_gb",
    "size.profiles.movie.default.default.max_gb",
    "size.profiles.series.default.default.min_gb",
    "size.profiles.series.default.default.max_gb",
)

_SCORE_NUMERIC_FIELDS = (
    "weights.video",
    "weights.audio",
    "weights.languages",
    "weights.size",
)


def _score_get_path(root: dict, path: str):
    cur = root
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _score_set_path(root: dict, path: str, value) -> None:
    cur = root
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _as_number(value, fallback=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _as_int(value, fallback=0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(fallback)


def _clamp_int(value, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _score_max_from_table(table: dict | None) -> int:
    if not isinstance(table, dict):
        return 0
    best = 0.0
    for value in table.values():
        if isinstance(value, (int, float)):
            best = max(best, _as_number(value, 0.0))
    return _as_int(best, 0)


def _compute_derived_max_score(score_config: dict) -> dict:
    if not isinstance(score_config, dict):
        return {
            "max_video": 0,
            "max_audio": 0,
            "max_languages": 0,
            "max_size": 0,
        }
    video = score_config.get("video") if isinstance(score_config.get("video"), dict) else {}
    audio = score_config.get("audio") if isinstance(score_config.get("audio"), dict) else {}
    languages = score_config.get("languages") if isinstance(score_config.get("languages"), dict) else {}
    size = score_config.get("size") if isinstance(score_config.get("size"), dict) else {}
    max_video = (
        _score_max_from_table(video.get("resolution") if isinstance(video.get("resolution"), dict) else {})
        + _score_max_from_table(video.get("codec") if isinstance(video.get("codec"), dict) else {})
        + _score_max_from_table(video.get("hdr") if isinstance(video.get("hdr"), dict) else {})
    )
    return {
        "max_video": _as_int(max_video, 0),
        "max_audio": _as_int(
            _score_max_from_table(audio.get("codec") if isinstance(audio.get("codec"), dict) else {})
            + _score_max_from_table(audio.get("channels") if isinstance(audio.get("channels"), dict) else {}),
            0,
        ),
        "max_languages": _score_max_from_table(languages.get("profile") if isinstance(languages.get("profile"), dict) else {}),
        "max_size": _score_max_from_table(size.get("points") if isinstance(size.get("points"), dict) else {}),
    }


def load_score_defaults() -> dict:
    return get_builtin_score_defaults()


def merge_score_config(defaults: dict, user_score: dict | None) -> dict:
    if not isinstance(defaults, dict):
        defaults = get_builtin_score_defaults()
    if not isinstance(user_score, dict):
        return copy.deepcopy(defaults)
    return deep_merge(copy.deepcopy(defaults), user_score)


def validate_score_config(score_config: dict, defaults: dict | None = None) -> tuple[dict, dict]:
    base_defaults = defaults if isinstance(defaults, dict) else get_builtin_score_defaults()
    cfg = merge_score_config(base_defaults, score_config)
    notes: list[dict] = []

    if "schema_version" in cfg:
        cfg.pop("schema_version", None)
        notes.append({"path": "schema_version", "reason": "removed_deprecated"})
    if "enabled" in cfg:
        cfg.pop("enabled", None)
        notes.append({"path": "enabled", "reason": "moved_to_score_flag"})
    if "penalties" in cfg:
        cfg.pop("penalties", None)
        notes.append({"path": "penalties", "reason": "removed_deprecated"})

    weights = cfg.setdefault("weights", {})
    for key in ("video", "audio", "languages", "size"):
        raw = weights.get(key)
        normalized = _clamp_int(_as_int(raw, _score_get_path(base_defaults, f"weights.{key}") or 0), 0, 100)
        if raw != normalized:
            notes.append({"path": f"weights.{key}", "reason": "clamped_or_defaulted"})
        weights[key] = normalized

    for path in _SCORE_REQUIRED_DEFAULT_PATHS:
        if _score_get_path(cfg, path) is None:
            fallback = _score_get_path(base_defaults, path)
            _score_set_path(cfg, path, fallback)
            notes.append({"path": path, "reason": "missing_default_restored"})

    derived_max_score = _compute_derived_max_score(cfg)
    if cfg.get("max_score") != derived_max_score:
        cfg["max_score"] = derived_max_score
        notes.append({"path": "max_score", "reason": "derived_refreshed"})

    status = compute_score_status(cfg)
    status["normalization_notes"] = notes
    return cfg, status


def validate_score_payload(payload: dict, defaults: dict, strict: bool = True) -> tuple[bool, dict]:
    if not isinstance(payload, dict):
        return False, {
            "ok": False,
            "error": {
                "code": "INVALID_SCORE_CONFIG",
                "message": "Payload must be a JSON object",
                "details": {"field": "payload"},
            },
        }

    score = payload.get("score")
    if not isinstance(score, dict):
        return False, {
            "ok": False,
            "error": {
                "code": "INVALID_SCORE_CONFIG",
                "message": "Missing score object in payload",
                "details": {"field": "score"},
            },
        }

    merged = merge_score_config(defaults, score)
    weights = merged.get("weights", {})
    for key in ("video", "audio", "languages", "size"):
        value = weights.get(key)
        if not isinstance(value, int):
            return False, {
                "ok": False,
                "error": {
                    "code": "INVALID_SCORE_CONFIG",
                    "message": "Weights must be integer values",
                    "details": {"field": f"weights.{key}", "value": value},
                },
            }
        if value < 0 or value > 100:
            return False, {
                "ok": False,
                "error": {
                    "code": "INVALID_SCORE_CONFIG",
                    "message": "Weights must be between 0 and 100",
                    "details": {"field": f"weights.{key}", "value": value},
                },
            }

    weights_total = sum(int(weights.get(k, 0)) for k in ("video", "audio", "languages", "size"))
    if strict and weights_total != 100:
        return False, {
            "ok": False,
            "error": {
                "code": "INVALID_SCORE_CONFIG",
                "message": "Weights total must equal 100",
                "details": {"weights_total": weights_total, "field": "weights"},
            },
        }

    for path in _SCORE_REQUIRED_DEFAULT_PATHS:
        if _score_get_path(merged, path) is None:
            return False, {
                "ok": False,
                "error": {
                    "code": "MISSING_DEFAULT_VALUE",
                    "message": f"Missing default fallback in {'.'.join(path.split('.')[:-1])}",
                    "details": {"path": f"score.{path}"},
                },
            }

    for path in _SCORE_NUMERIC_FIELDS:
        value = _score_get_path(merged, path)
        if not isinstance(value, (int, float)):
            return False, {
                "ok": False,
                "error": {
                    "code": "INVALID_SCORE_CONFIG",
                    "message": "Numeric field expected",
                    "details": {"field": path, "value": value},
                },
            }
    return True, {}


def compute_score_status(score_config: dict) -> dict:
    weights = score_config.get("weights", {}) if isinstance(score_config, dict) else {}
    total = sum(_as_int(weights.get(k), 0) for k in ("video", "audio", "languages", "size"))
    return {
        "weights_total": total,
        "weights_valid": total == 100,
    }


def get_effective_score_config(cfg: dict | None = None) -> tuple[dict, dict, dict]:
    defaults = load_score_defaults()
    base_cfg = cfg if isinstance(cfg, dict) else load_config()
    user_score = base_cfg.get("score_configuration") if isinstance(base_cfg, dict) else None
    effective, status = validate_score_config(merge_score_config(defaults, user_score), defaults=defaults)
    return defaults, effective, status


# ---------------------------------------------------------------------------
# QUICK SCAN
# ---------------------------------------------------------------------------

def _write_library_snapshot(items: list[dict], prev_data: dict, score_enabled: bool, output_path: str) -> None:
    """Persist current library state (used for incremental per-folder writes)."""
    clean_items = [_sanitize_item_for_library_json(item) for item in items]
    all_categories = sorted({i["category"] for i in clean_items})
    data = {
        "scanned_at":          datetime.now().isoformat(),
        "library_path":        LIBRARY_PATH,
        "total_items":         len(clean_items),
        "categories":          all_categories,
        "items":               clean_items,
    }
    write_json(data, output_path)


def _normalize_provider_entries(providers) -> list[str]:
    """Normalize one provider list to cleaned raw-name strings."""
    result = []
    seen = set()
    for p in (providers or []):
        if isinstance(p, str):
            raw_name = p
        elif isinstance(p, dict):
            raw_name = (
                p.get("raw_name")
                or p.get("name")
                or p.get("provider_name")
                or p.get("providerName")
            )
        else:
            raw_name = None
        cleaned = _clean_raw_provider_name(raw_name)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _normalize_providers(providers) -> list[str]:
    """Normalize providers payload to a flat cleaned raw-name list."""
    if isinstance(providers, list):
        return _normalize_provider_entries(providers)
    if not isinstance(providers, dict):
        return []

    ordered_entries = []
    for group in _PROVIDER_TYPES:
        values = providers.get(group)
        if isinstance(values, list):
            ordered_entries.extend(values)

    for key in sorted(k for k in providers.keys() if k not in _PROVIDER_TYPES):
        values = providers.get(key)
        if isinstance(values, list):
            ordered_entries.extend(values)

    return _normalize_provider_entries(ordered_entries)

def _strip_score_fields(item: dict) -> dict:
    """Remove score-related fields from one item (in place) for score-disabled runs."""
    if not isinstance(item, dict):
        return item
    item.pop("quality", None)
    # Legacy compatibility: some older datasets stored top-level score payloads
    item.pop("score", None)
    return item


def _sanitize_item_for_library_json(item: dict) -> dict:
    """Normalize one library item to the v0.3.1 schema."""
    if not isinstance(item, dict):
        return item
    clean = dict(item)
    clean.pop("_scan_tv_episodes_scanned", None)
    clean.pop("_scan_tv_series_scanned", None)
    clean.pop("_scan_tv_seerr_counts", None)
    clean.pop("runtime", None)
    clean.pop("audio_codec_display", None)
    clean.pop("complete", None)
    clean.pop("score", None)  # legacy top-level score field superseded by quality dict
    for field in ("audio_codec", "audio_languages_simple", "codec", "resolution"):
        if _is_unknown_sentinel(clean.get(field)):
            clean[field] = None
    clean["providers"] = _normalize_providers(clean.get("providers"))
    clean.pop("providers_by_type", None)
    quality = clean.get("quality")
    if isinstance(quality, dict):
        q = dict(quality)
        q.pop("level", None)
        q.pop("base_score", None)
        q.pop("score_details", None)
        video_details = q.get("video_details")
        if isinstance(video_details, dict):
            vd = {
                "resolution": _safe_int(video_details.get("resolution"), 0) or 0,
                "codec": _safe_int(video_details.get("codec"), 0) or 0,
                "hdr": _safe_int(video_details.get("hdr"), 0) or 0,
            }
        else:
            vd = {"resolution": 0, "codec": 0, "hdr": 0}
        audio_details = q.get("audio_details")
        if isinstance(audio_details, dict):
            ad = {
                "codec": _safe_int(audio_details.get("codec"), 0) or 0,
                "channels": _safe_int(audio_details.get("channels"), 0) or 0,
            }
        else:
            ad = {"codec": 0, "channels": 0}
        q_audio = _safe_int(q.get("audio"), 0) or 0
        q_languages = _safe_int(q.get("languages"), 0) or 0
        q_size = _safe_int(q.get("size"), 0) or 0
        q_video_w = _as_number(q.get("video_w"), _as_number(q.get("video"), 0.0))
        q_audio_w = _as_number(q.get("audio_w"), _as_number(q_audio, 0.0))
        q_languages_w = _as_number(q.get("languages_w"), _as_number(q_languages, 0.0))
        q_size_w = _as_number(q.get("size_w"), _as_number(q_size, 0.0))
        normalized_q = {
            "video_details": vd,
            "audio_details": ad,
            "video": int(vd["resolution"] + vd["codec"] + vd["hdr"]),
            "audio": q_audio,
            "languages": q_languages,
            "size": q_size,
            "video_w": round(q_video_w, 4),
            "audio_w": round(q_audio_w, 4),
            "languages_w": round(q_languages_w, 4),
            "size_w": round(q_size_w, 4),
        }
        normalized_q["score"] = int(round(normalized_q["video_w"] + normalized_q["audio_w"] + normalized_q["languages_w"] + normalized_q["size_w"]))
        if _safe_int(q.get("video"), normalized_q["video"]) != normalized_q["video"] or _safe_int(q.get("score"), normalized_q["score"]) != normalized_q["score"]:
            log.warning(
                "[score] Normalized inconsistent quality block for item %r (%s): score=%s video=%s",
                clean.get("title"),
                clean.get("path"),
                q.get("score"),
                q.get("video"),
            )
        clean["quality"] = normalized_q
    seasons = clean.get("seasons")
    if isinstance(seasons, list):
        sanitized_seasons = []
        for season in seasons:
            if not isinstance(season, dict):
                continue
            s = dict(season)
            for field in ("audio_codec", "audio_languages_simple", "codec", "resolution"):
                if _is_unknown_sentinel(s.get(field)):
                    s[field] = None
            sq = s.get("quality")
            if isinstance(sq, dict):
                sq2 = dict(sq)
                sq2.pop("level", None)
                sq2.pop("base_score", None)
                sq2.pop("score_details", None)
                video_details = sq2.get("video_details")
                if isinstance(video_details, dict):
                    vd2 = {
                        "resolution": _safe_int(video_details.get("resolution"), 0) or 0,
                        "codec": _safe_int(video_details.get("codec"), 0) or 0,
                        "hdr": _safe_int(video_details.get("hdr"), 0) or 0,
                    }
                else:
                    vd2 = {"resolution": 0, "codec": 0, "hdr": 0}
                audio_details = sq2.get("audio_details")
                if isinstance(audio_details, dict):
                    ad2 = {
                        "codec": _safe_int(audio_details.get("codec"), 0) or 0,
                        "channels": _safe_int(audio_details.get("channels"), 0) or 0,
                    }
                else:
                    ad2 = {"codec": 0, "channels": 0}
                sq_audio = _safe_int(sq2.get("audio"), 0) or 0
                sq_languages = _safe_int(sq2.get("languages"), 0) or 0
                sq_size = _safe_int(sq2.get("size"), 0) or 0
                sq_video_w = _as_number(sq2.get("video_w"), _as_number(sq2.get("video"), 0.0))
                sq_audio_w = _as_number(sq2.get("audio_w"), _as_number(sq_audio, 0.0))
                sq_languages_w = _as_number(sq2.get("languages_w"), _as_number(sq_languages, 0.0))
                sq_size_w = _as_number(sq2.get("size_w"), _as_number(sq_size, 0.0))
                normalized_sq = {
                    "video_details": vd2,
                    "audio_details": ad2,
                    "video": int(vd2["resolution"] + vd2["codec"] + vd2["hdr"]),
                    "audio": sq_audio,
                    "languages": sq_languages,
                    "size": sq_size,
                    "video_w": round(sq_video_w, 4),
                    "audio_w": round(sq_audio_w, 4),
                    "languages_w": round(sq_languages_w, 4),
                    "size_w": round(sq_size_w, 4),
                }
                normalized_sq["score"] = int(round(normalized_sq["video_w"] + normalized_sq["audio_w"] + normalized_sq["languages_w"] + normalized_sq["size_w"]))
                if _safe_int(sq2.get("video"), normalized_sq["video"]) != normalized_sq["video"] or _safe_int(sq2.get("score"), normalized_sq["score"]) != normalized_sq["score"]:
                    log.warning(
                        "[score] Normalized inconsistent season quality for item %r season=%s",
                        clean.get("title"),
                        s.get("season"),
                    )
                s["quality"] = normalized_sq
            sanitized_seasons.append(s)
        clean["seasons"] = sanitized_seasons
    return clean


def _sanitize_library_document(data: dict) -> dict:
    """Remove legacy root metadata and sanitize item payloads in-place."""
    if not isinstance(data, dict):
        return data
    data.pop("config", None)
    data.pop("meta", None)
    data.pop("providers_meta", None)
    data.pop("providers_raw", None)
    data.pop("providers_raw_meta", None)
    data.pop("enriched_at", None)
    items = data.get("items") or []
    if isinstance(items, list):
        for idx, item in enumerate(items):
            clean_item = _sanitize_item_for_library_json(item)
            if isinstance(item, dict) and isinstance(clean_item, dict):
                # Keep dict identity so existing references (e.g. enrich batches)
                # remain valid across per-folder writes.
                item.clear()
                item.update(clean_item)
            else:
                items[idx] = clean_item
    return data


def _is_unknown_sentinel(value) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().lower() == "unknown"


def _clean_raw_provider_name(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None
    cleaned = re.sub(r"\s+", " ", name.strip())
    # Keep raw names, only strip trailing separator noise.
    cleaned = re.sub(r"[\s\.,;:|/_-]+$", "", cleaned).strip()
    if not cleaned:
        return None
    if cleaned.casefold() == "autres":
        return None
    return cleaned

def scan_media_item(
    media_dir: Path,
    root: Path,
    cat: dict,
    prev: dict,
    enable_score: bool = True,
    score_config: dict | None = None,
    jsr_for_counts: dict | None = None,
) -> dict:
    """
    Build one item dict from filesystem + NFO.
    `prev` is the existing SQLite library item (may be empty dict).
    `id` is computed as `{media_type}:{category}:{folder_name}` — stable across
    rescans regardless of filename changes.
    """
    raw_name  = media_dir.name
    item_path = str(media_dir.relative_to(root))
    mtime     = media_dir.stat().st_mtime
    is_tv     = cat["type"] == "tv"
    media_type = "tv" if is_tv else "movie"
    lib_id     = _inventory_item_id(media_type, cat["name"], raw_name)

    # --- NFO metadata ---
    nfo_meta = {}
    series_agg: dict = {}
    expected_counts: dict | None = None
    if is_tv:
        tvshow_nfo = media_dir / "tvshow.nfo"
        if tvshow_nfo.exists():
            nfo_meta = parse_tvshow_nfo(tvshow_nfo)
        series_episodes = collect_series_episode_metadata(media_dir, item_id=lib_id)
        series_agg = aggregate_series_metadata(
            series_episodes,
            item_id=lib_id,
            score_config=score_config if isinstance(score_config, dict) else None,
            include_quality=bool(enable_score),
        )
        if isinstance(jsr_for_counts, dict) and jsr_for_counts.get("enabled"):
            expected_counts = _fetch_tv_expected_counts_from_seerr(
                tvdb_id=nfo_meta.get("tvdb_id") or prev.get("tvdb_id"),
                tmdb_id=nfo_meta.get("tmdb_id") or prev.get("tmdb_id"),
                title=nfo_meta.get("title") or prev.get("title") or _clean_title(raw_name),
                year=nfo_meta.get("year") or prev.get("year") or _extract_year(raw_name),
                jsr=jsr_for_counts,
            )
            if isinstance(expected_counts, dict):
                season_expected = expected_counts.get("season_episode_counts")
                if isinstance(season_expected, dict):
                    series_agg = aggregate_series_metadata(
                        series_episodes,
                        item_id=lib_id,
                        score_config=score_config if isinstance(score_config, dict) else None,
                        season_expected_counts=season_expected,
                        include_quality=bool(enable_score),
                    )
    else:
        nfo_file = find_movie_nfo(media_dir)
        if nfo_file:
            nfo_meta = parse_movie_nfo(nfo_file)

    # --- Title / year: NFO takes priority, fallback to folder name parsing ---
    title = nfo_meta.get("title") or _clean_title(raw_name)
    year  = nfo_meta.get("year")  or _extract_year(raw_name)

    # --- Local poster path ---
    poster_local = poster_rel_path(media_dir, root)

    # --- Poster: local file > NFO url > previous ---
    if poster_local:
        poster = f"/posters/{poster_local}"
    elif nfo_meta.get("poster_url"):
        poster = nfo_meta["poster_url"]
    else:
        poster = prev.get("poster")

    # --- IDs from NFO (always fresh). For TV, keep tmdb_id and tvdb_id separated. ---
    if is_tv:
        nfo_tmdb_id = nfo_meta.get("tmdb_id")
        nfo_tvdb_id = nfo_meta.get("tvdb_id")
        tmdb_id = nfo_tmdb_id or (prev.get("tmdb_id") if not nfo_tvdb_id else None)
        tvdb_id = nfo_tvdb_id or prev.get("tvdb_id")
        # Guard: never persist tvdb-style fallback into tmdb_id when tvdb_id is explicitly known.
        if tmdb_id and tvdb_id and str(tmdb_id).strip() == str(tvdb_id).strip():
            tmdb_id = None
    else:
        tmdb_id = nfo_meta.get("tmdb_id") or prev.get("tmdb_id")
        tvdb_id = None
    size_b = get_dir_size(media_dir)

    hdr_source = series_agg if is_tv else nfo_meta
    hdr_current = bool(hdr_source.get("hdr", False))
    hdr_type_current = (hdr_source.get("hdr_type") or "").strip() or None
    hdr_type_value = (hdr_type_current or prev.get("hdr_type")) if hdr_current else None

    item = {
        # id first — stable key shared across media, media_probe_cache, recommendations
        "id":                lib_id,
        "path":              item_path,
        "title":             title,
        "raw":               raw_name,
        "year":              year,
        "category":          cat["name"],
        "type":              cat["type"],
        "size_b":            size_b,
        "size":              format_size(size_b),
        "file_count":        count_media_files(media_dir),
        "added_at":          datetime.fromtimestamp(mtime).isoformat(),
        "added_ts":          int(mtime),
        "poster":            poster,
        "tmdb_id":           tmdb_id,
        "tvdb_id":           tvdb_id,
        "resolution":        (series_agg.get("resolution") if is_tv else nfo_meta.get("resolution")) or prev.get("resolution"),
        "width":             (series_agg.get("width") if is_tv else nfo_meta.get("width")) or prev.get("width"),
        "height":            (series_agg.get("height") if is_tv else nfo_meta.get("height")) or prev.get("height"),
        "plot":              nfo_meta.get("plot")        or prev.get("plot"),
        "genres":            nfo_meta.get("genres"),
        "runtime_min":       (series_agg.get("runtime_min") if is_tv else nfo_meta.get("runtime_min")) or prev.get("runtime_min"),
        "runtime_min_avg":   (series_agg.get("runtime_min_avg") if is_tv else nfo_meta.get("runtime_min_avg")) or prev.get("runtime_min_avg"),
        "season_count":      (series_agg.get("season_count") if is_tv else nfo_meta.get("season_count")) or prev.get("season_count"),
        "episode_count":     (series_agg.get("episode_count") if is_tv else nfo_meta.get("episode_count")) or prev.get("episode_count"),
        "codec":             (series_agg.get("codec") if is_tv else nfo_meta.get("codec")) or prev.get("codec"),
        "audio_codec_raw":   (series_agg.get("audio_codec_raw") if is_tv else nfo_meta.get("audio_codec_raw")) or prev.get("audio_codec_raw"),
        "audio_codec":       (series_agg.get("audio_codec") if is_tv else nfo_meta.get("audio_codec")) or prev.get("audio_codec"),
        "audio_channels":    (series_agg.get("audio_channels") if is_tv else nfo_meta.get("audio_channels")) or prev.get("audio_channels"),
        "audio_languages":   (series_agg.get("audio_languages") if is_tv else nfo_meta.get("audio_languages")) or prev.get("audio_languages") or [],
        "audio_languages_simple": (series_agg.get("audio_languages_simple") if is_tv else nfo_meta.get("audio_languages_simple")) or prev.get("audio_languages_simple") or simplify_audio_languages((series_agg.get("audio_languages") if is_tv else nfo_meta.get("audio_languages")) or prev.get("audio_languages") or []),
        "subtitle_languages": (series_agg.get("subtitle_languages") if is_tv else nfo_meta.get("subtitle_languages")) or prev.get("subtitle_languages"),
        "video_bitrate":     (series_agg.get("video_bitrate") if is_tv else nfo_meta.get("video_bitrate")) or prev.get("video_bitrate"),
        "hdr":               hdr_current,
        "hdr_type":          hdr_type_value,
        # Enriched fields preserved from previous SQLite library snapshot — overwritten by later enabled phases.
        "providers":              _normalize_providers(prev.get("providers")),
        "providers_fetched":      prev.get("providers_fetched", False),
        "seerr_last_fetched_at":  prev.get("seerr_last_fetched_at"),
        "seerr_status":           prev.get("seerr_status"),
    }
    if is_tv:
        item["size_b"] = int(series_agg.get("size_b") or size_b)
        item["size"] = format_size(item["size_b"])
        item["seasons"] = series_agg.get("seasons") or []
        item["episodes_expected"] = series_agg.get("episodes_expected")
        item = merge_series_expected_counts_from_seerr(item, expected_counts)
        item["_scan_tv_episodes_scanned"] = int(series_agg.get("episode_count") or 0)
        item["_scan_tv_series_scanned"] = 1
        item["_scan_tv_seerr_counts"] = bool(isinstance(expected_counts, dict))
    if enable_score:
        if is_tv and isinstance(series_agg.get("quality"), dict):
            q = dict(series_agg["quality"])
            q.pop("level", None)
            item["quality"] = q
        else:
            preserved_quality = prev.get("quality")
            if isinstance(preserved_quality, dict):
                q = dict(preserved_quality)
                q.pop("level", None)
                item["quality"] = q  # preserved during phase 1; overwritten by phase 3 when enabled
    else:
        # Phase 1 (score disabled): carry forward quality computed by a previous Phase 3 run
        preserved_quality = prev.get("quality")
        if isinstance(preserved_quality, dict):
            q = dict(preserved_quality)
            q.pop("level", None)
            item["quality"] = q
    if _is_unknown_sentinel(item.get("audio_codec")):
        item["audio_codec"] = None
    if _is_unknown_sentinel(item.get("audio_languages_simple")):
        item["audio_languages_simple"] = None
    # Filename map — never influences media_id, used for change tracking / probe cache
    if is_tv:
        item["filename"] = _extract_filename_tv(media_dir)
    else:
        item["filename"] = _extract_filename_movie(media_dir)
    return item



def run_quick(only_category: str | None = None) -> str:
    _t0 = time.monotonic()
    _nfo_stats["ok"] = 0
    _nfo_stats["failed"] = 0
    scope = f" [category: {only_category}]" if only_category else ""
    _log_phase_start("1", suffix=scope)

    root = Path(LIBRARY_PATH)
    if not root.exists():
        log.error(f"{_phase_prefix('1')} Library path not found: {LIBRARY_PATH}")
        return ""

    # One-time migration of legacy env vars → SQLite config
    migrate_env_to_config()

    # Sync folders with filesystem (adds new, marks missing)
    cfg = load_config()
    if sync_folders(root, cfg):
        save_config(cfg)
        cfg = load_config()
    if normalize_folder_enabled_flags(cfg, drop_visible=True):
        save_config(cfg)
        cfg = load_config()
    score_feature_enabled = _is_score_enabled(cfg)
    # v0.3.3 policy: final quality scoring is full-phase only (phase 3).
    # Phase 1 builds metadata/aggregations but does not persist final quality.
    score_enabled = False
    if score_feature_enabled:
        log.debug("%s Score disabled for phase 1; final quality is computed in phase 3", _phase_prefix("1"))
    _, effective_score_config, _ = get_effective_score_config(cfg)
    jsr_for_counts = _jsr_cfg()
    seerr_counts_active = bool(jsr_for_counts.get("enabled") and jsr_for_counts.get("url") and jsr_for_counts.get("apikey"))

    categories = build_categories_from_config(cfg)

    # Log folders that are skipped (no type configured)
    for folder in cfg.get("folders", []):
        fname = folder.get("name")
        if not fname or folder.get("missing"):
            continue
        ftype = folder.get("type")
        if not ftype or ftype == "ignore":
            log.debug(f"{_phase_prefix('1')} Folder [{fname}] skipped — no type configured")

    if not categories:
        all_typed_folders = [f for f in cfg.get("folders", []) if f.get("type") in {"movie", "tv"}]
        if not all_typed_folders:
            # No folders with a recognised type configured at all
            if not library_document_exists(OUTPUT_PATH):
                log.info("%s No folder configured yet — skipping phase", _phase_prefix("1"))
            else:
                log.warning("%s No folder configured with type 'movie' or 'tv'", _phase_prefix("1"))
        else:
            log.warning("%s All configured folders are disabled — skipping phase", _phase_prefix("1"))
        return ""

    log.info(f"{_phase_prefix('1')} {len(categories)} configured folder(s): {', '.join(c['name'] for c in categories)}")
    existing = load_existing(OUTPUT_PATH)

    # Preserve previous file content for backward-compatible partial scans
    prev_data: dict = load_library_document_non_blocking(OUTPUT_PATH) or {}

    # Single timestamp shared across all items in this scan run
    scan_time = datetime.now().isoformat()

    items = []
    scanned_ids: set[str] = set()
    scanned_paths = set()
    tv_series_scanned = 0
    tv_episodes_scanned = 0
    tv_series_with_seerr_counts = 0

    active_cats = [c for c in categories if not only_category or c["name"] == only_category]
    n_cats = len(active_cats)

    for cat_idx, cat in enumerate(active_cats, 1):
        cat_started_at = time.monotonic()
        log.info(f"{_phase_prefix('1')} Folder [{cat['folder']}] ({cat_idx}/{n_cats}) started — type={cat['type']}")
        cat_dir = root / cat["folder"]
        if not cat_dir.exists():
            log.warning(f"{_phase_prefix('1')} Folder [{cat['folder']}] skipped — not found: {cat_dir}")
            continue

        cat_items_before = len(items)
        for media_dir in sorted(cat_dir.iterdir()):
            if not media_dir.is_dir() or media_dir.name.startswith(('.', '@')):
                continue

            item_path = str(media_dir.relative_to(root))
            # Use the initial snapshot (loaded once before any writes) as source for prev
            prev = existing.get(item_path, {})

            # scan_media_item computes stable media_id via _inventory_item_id
            item = scan_media_item(
                media_dir,
                root,
                cat,
                prev,
                enable_score=score_enabled,
                score_config=effective_score_config,
                jsr_for_counts=jsr_for_counts if cat["type"] == "tv" and seerr_counts_active else None,
            )
            # Disk-state timestamps — COALESCE in upsert SQL preserves first_seen_at
            item["is_available"] = 1
            item["last_seen_at"] = scan_time
            item["last_scanned_at"] = scan_time
            item["first_seen_at"] = scan_time
            items.append(item)
            tv_series_scanned += int(item.get("_scan_tv_series_scanned") or 0)
            tv_episodes_scanned += int(item.get("_scan_tv_episodes_scanned") or 0)
            tv_series_with_seerr_counts += int(1 if item.get("_scan_tv_seerr_counts") else 0)
            scanned_paths.add(item_path)
            if item.get("id"):
                scanned_ids.add(item["id"])

        count = len(items) - cat_items_before
        log.info(f'{_phase_prefix("1")} Folder [{cat["folder"]}] completed in {time.monotonic() - cat_started_at:.1f}s — {count} item(s)')

    # When filtering by category, preserve items from other categories
    if only_category:
        # Preserve items from OTHER categories only — same-category absent items are
        # handled by mark_media_unavailable and must not be upserted with stale state.
        preserved = [i for i in existing.values() if i.get("category") != only_category]
        log.info(f"{_phase_prefix('1')} Preserving {len(preserved)} item(s) from other categories")
        for i in preserved:
            # Ensure preserved items use the string id format (may be an old integer id)
            i_media_type = "tv" if i.get("type") == "tv" else "movie"
            i_folder = Path(i.get("path", "")).name
            i["id"] = _inventory_item_id(i_media_type, i.get("category", ""), i_folder)
        items = items + preserved

    if media_repository is not None:
        marked = media_repository.mark_media_unavailable(OUTPUT_PATH, scanned_ids, only_category)
        if marked:
            log.info(f"{_phase_prefix('1')} Marked {marked} media entry(ies) unavailable")

    # Write snapshot once, after all folders and mark_unavailable.
    # For only_category: items already merged with preserved items from other categories above.
    _write_library_snapshot(items, prev_data, score_enabled, OUTPUT_PATH)

    size_mb = sum(int(item.get("size_b") or 0) for item in items) / (1024 * 1024)
    size_str = f"{size_mb:.1f} MB"
    try:
        mapping_added = _upsert_runtime_provider_mapping(items)
        if mapping_added:
            log.info(f"{_phase_prefix('1')} providers_mapping updated (+{mapping_added} raw provider(s))")
    except Exception as e:
        log.warning(f"{_phase_prefix('1')} providers_mapping update failed: {e}")

    elapsed = time.monotonic() - _t0
    if _nfo_stats["failed"] > 0:
        log.info(f"{_phase_prefix('1')} NFO parsing: {_nfo_stats['ok']} OK / {_nfo_stats['failed']} failed")
    else:
        log.debug(f"{_phase_prefix('1')} NFO parsing: {_nfo_stats['ok']} OK")

    # Audio codec stats
    audio_dist: dict = {}
    for item in items:
        ac = item.get("audio_codec") or "UNKNOWN"
        audio_dist[ac] = audio_dist.get(ac, 0) + 1
    audio_parts = [f"{k}×{v}" for k, v in sorted(audio_dist.items(), key=lambda x: -x[1])]
    log.debug(f"{_phase_prefix('1')} Audio codecs detected: {len(audio_dist)}")
    log.debug(f"{_phase_prefix('1')} Audio codecs detail: {' / '.join(audio_parts) if audio_parts else 'none'}")

    # Audio language stats
    lang_dist: dict = {}
    for item in items:
        for lang in (item.get("audio_languages") or []):
            lang_dist[lang] = lang_dist.get(lang, 0) + 1
    lang_parts = [f"{k}×{v}" for k, v in sorted(lang_dist.items(), key=lambda x: -x[1])]
    log.debug(f"{_phase_prefix('1')} Audio languages detected: {len(lang_dist)}")
    if lang_parts:
        log.debug(f"{_phase_prefix('1')} Audio languages detail: {' / '.join(lang_parts)}")

    # Video codec stats
    video_dist: dict = {}
    for item in items:
        vc = item.get("codec") or "unknown"
        video_dist[vc] = video_dist.get(vc, 0) + 1
    video_parts = [f"{k}×{v}" for k, v in sorted(video_dist.items(), key=lambda x: -x[1])]
    log.debug(f"{_phase_prefix('1')} Video codecs detected: {len(video_dist)}")
    log.debug(f"{_phase_prefix('1')} Video codecs detail: {' / '.join(video_parts) if video_parts else 'none'}")

    # Resolution stats
    res_dist: dict = {}
    for item in items:
        r = item.get("resolution") or "unknown"
        res_dist[r] = res_dist.get(r, 0) + 1
    res_parts = [f"{k}×{v}" for k, v in sorted(res_dist.items(), key=lambda x: -x[1])]
    log.debug(f"{_phase_prefix('1')} Resolutions detected: {len(res_dist)}")
    log.debug(f"{_phase_prefix('1')} Resolutions detail: {' / '.join(res_parts) if res_parts else 'none'}")
    movie_count = len([item for item in items if item.get("type") != "tv"])
    series_items = [item for item in items if item.get("type") == "tv"]
    series_count = len(series_items)
    series_episode_count = sum(int(item.get("episode_count") or 0) for item in series_items)
    if series_episode_count <= 0 and tv_episodes_scanned > 0:
        series_episode_count = tv_episodes_scanned
    log.info(f"{_phase_prefix('1')} Movies summary: {_count_label(movie_count, 'movie')} analyzed")
    log.info(
        f"{_phase_prefix('1')} Series summary: {_count_label(series_count, 'series', 'series')} analyzed / "
        f"{_count_label(series_episode_count, 'episode')} scanned"
    )
    if seerr_counts_active:
        log.debug(
            f"{_phase_prefix('1')} TV Seerr expected-count summary: {tv_series_with_seerr_counts}/{tv_series_scanned} series enriched"
        )

    summary1 = f"{_count_label(len(items), 'item')} total ({size_str})"
    _log_phase_complete("1", elapsed, summary1)
    return summary1


# ---------------------------------------------------------------------------
# ENRICH (providers via Seerr)
# ---------------------------------------------------------------------------

def run_enrich(force: bool = False, only_category: str | None = None) -> str:
    _t0 = time.monotonic()
    label = "force" if force else "missing only"
    scope = f" [category: {only_category}]" if only_category else ""
    _log_phase_start("3", suffix=f" ({label}){scope}")

    jsr = _jsr_cfg()
    if not jsr["enabled"]:
        log.warning("%s Disabled in SQLite config — skipping phase", _phase_prefix("3"))
        return ""
    if not jsr["url"] or not jsr["apikey"]:
        log.warning("%s URL or API key missing — skipping phase", _phase_prefix("3"))
        return ""

    data = load_library_document_non_blocking(OUTPUT_PATH)
    if not isinstance(data, dict):
        log.error(f"{_phase_prefix('3')} Cannot read {OUTPUT_PATH}")
        return ""

    items = data.get("items", [])

    def needs_enrich(item: dict) -> bool:
        if only_category and item.get("category") != only_category:
            return False
        # Enrichment can run from IDs or fallback search (requires title).
        # Keep this broad even in force mode to avoid skipping valid items.
        if not item.get("title") and not item.get("tmdb_id") and not item.get("tvdb_id"):
            return False
        if force:
            return True
        # Retry NOT_FOUND items after TTL — new titles appear in Seerr over time
        if item.get("seerr_status") == "not_found":
            last = item.get("seerr_last_fetched_at")
            if last:
                try:
                    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
                    return age_days >= _SEERR_NOT_FOUND_TTL_DAYS
                except Exception:
                    pass
            return False
        return not item.get("providers_fetched")

    to_enrich = [i for i in items if needs_enrich(i)]
    skipped   = len(items) - len(to_enrich)
    log.info(f"{_phase_prefix('3')} {len(to_enrich)} item(s) to process, {skipped} skipped ({_ENRICH_WORKERS} workers)")

    if not to_enrich:
        early_summary = f"0 enriched / {skipped} skipped" if skipped else "0 item(s)"
        _log_phase_complete("3", time.monotonic() - _t0, early_summary)
        return early_summary

    by_cat = defaultdict(list)
    for item in to_enrich:
        by_cat[item["category"]].append(item)

    enriched = 0

    # Build category display-name → raw folder name lookup for consistent log labels
    try:
        _enrich_cfg = load_config()
        _enrich_cats = build_categories_from_config(_enrich_cfg)
        _cat_folder_by_name = {c["name"]: c["folder"] for c in _enrich_cats}
    except Exception:
        _cat_folder_by_name = {}

    def _enrich_one(item):
        is_tv = item.get("type") == "tv"
        try:
            providers = _JSR_NOT_FOUND
            if is_tv:
                # Nominal path for TV: tvdb_id.
                tv_lookup_id = item.get("tvdb_id")
                if tv_lookup_id:
                    providers = fetch_providers(tv_lookup_id, True, jsr)
                # Compatibility fallback: some Seerr instances/media still resolve with TMDB tv id.
                if providers is _JSR_NOT_FOUND and item.get("tmdb_id"):
                    providers = fetch_providers(item["tmdb_id"], True, jsr)
                if providers is _JSR_NOT_FOUND:
                    resolved_ids = _resolve_ids_from_search(item.get("title"), item.get("year"), is_tv=True, jsr=jsr)
                    if resolved_ids is _FETCH_ERROR:
                        providers = _FETCH_ERROR
                    elif isinstance(resolved_ids, dict):
                        resolved_tvdb = resolved_ids.get("tvdb_id")
                        resolved_tmdb = resolved_ids.get("tmdb_id")
                        if resolved_tmdb not in (None, ""):
                            item["tmdb_id"] = str(resolved_tmdb)
                        if resolved_tvdb not in (None, ""):
                            log.debug(
                                f"{_phase_prefix('3')} Resolved TVDB id via search for {item.get('title')!r}: {item.get('tvdb_id')} -> {resolved_tvdb}"
                            )
                            item["tvdb_id"] = str(resolved_tvdb)
                            providers = fetch_providers(item["tvdb_id"], True, jsr)
                        if providers is _JSR_NOT_FOUND and item.get("tmdb_id"):
                            providers = fetch_providers(item["tmdb_id"], True, jsr)
            else:
                if item.get("tmdb_id"):
                    providers = fetch_providers(item["tmdb_id"], False, jsr)
                if providers is _JSR_NOT_FOUND:
                    resolved_ids = _resolve_ids_from_search(item.get("title"), item.get("year"), is_tv=False, jsr=jsr)
                    if resolved_ids is _FETCH_ERROR:
                        providers = _FETCH_ERROR
                    elif isinstance(resolved_ids, dict):
                        resolved_tmdb = resolved_ids.get("tmdb_id")
                        if resolved_tmdb not in (None, ""):
                            log.debug(
                                f"{_phase_prefix('3')} Resolved TMDB id via search for {item.get('title')!r}: {item.get('tmdb_id')} -> {resolved_tmdb}"
                            )
                            item["tmdb_id"] = str(resolved_tmdb)
                            providers = fetch_providers(item["tmdb_id"], False, jsr)
        except Exception as e:
            log.warning(
                f"{_phase_prefix('3')} Unexpected exception id={item.get('tvdb_id') if is_tv else item.get('tmdb_id')} "
                f"{item.get('title')!r}: {e}"
            )
            providers = _FETCH_ERROR
        time.sleep(0.05)
        return item, providers

    failed_count    = 0
    failed_ids      = []
    not_found_count = 0
    not_found_ids   = []
    sorted_by_cat = sorted(by_cat.items())
    n_enrich_cats = len(sorted_by_cat)
    for cat_idx, (cat_name, cat_items) in enumerate(sorted_by_cat, 1):
        cat_folder = _cat_folder_by_name.get(cat_name, cat_name)
        cat_started_at = time.monotonic()
        _now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        log.info(f"{_phase_prefix('3')} Folder [{cat_folder}] ({cat_idx}/{n_enrich_cats}) started — {len(cat_items)} item(s)")
        with ThreadPoolExecutor(max_workers=_ENRICH_WORKERS) as pool:
            futures = {pool.submit(_enrich_one, item): item for item in cat_items}
            for future in as_completed(futures):
                item, providers = future.result()
                if providers is _JSR_NOT_FOUND:
                    # Item not in Seerr — mark as fetched (no FR providers)
                    item["providers"]             = []
                    item["providers_fetched"]     = True
                    item["seerr_status"]          = "not_found"
                    item["seerr_last_fetched_at"] = _now_iso
                    not_found_count += 1
                    not_found_ids.append(item.get("tvdb_id", "?") if item.get("type") == "tv" else item.get("tmdb_id", "?"))
                    continue
                if providers is _FETCH_ERROR:
                    # Seerr unreachable — leave providers_fetched False, retry next run
                    # Transient error — do NOT update seerr_status/seerr_last_fetched_at
                    failed_count += 1
                    failed_ids.append(item.get("tvdb_id", "?") if item.get("type") == "tv" else item.get("tmdb_id", "?"))
                    continue
                # Store cleaned raw provider names from Seerr.
                item["providers"]             = _normalize_providers([p["raw_name"] for p in (providers or [])])
                item["providers_fetched"]     = True
                item["seerr_status"]          = "ok"
                item["seerr_last_fetched_at"] = _now_iso
                enriched += 1
                total_providers = len(providers or [])
                log.debug(f"{_phase_prefix('3')} {item['title']} — {total_providers} provider(s)")

        _sanitize_library_document(data)
        write_json(data, OUTPUT_PATH)
        log.info(f"{_phase_prefix('3')} Folder [{cat_folder}] completed in {time.monotonic() - cat_started_at:.1f}s — {len(cat_items)} item(s)")

    elapsed = time.monotonic() - _t0
    if not_found_count:
        ids_str = ", ".join(str(i) for i in not_found_ids[:20])
        suffix  = f" … (+{len(not_found_ids)-20} more)" if len(not_found_ids) > 20 else ""
        log.info(f"{_phase_prefix('3')} {not_found_count} item(s) not found — ids: {ids_str}{suffix}")
    if failed_count:
        ids_str = ", ".join(str(i) for i in failed_ids[:20])
        suffix  = f" … (+{len(failed_ids)-20} more)" if len(failed_ids) > 20 else ""
        log.warning(f"{_phase_prefix('3')} {failed_count} item(s) not enriched — ids: {ids_str}{suffix}")
    parts = [f"{enriched} enriched"]
    if not_found_count: parts.append(f"{not_found_count} not_found")
    if failed_count:    parts.append(_count_label(failed_count, "error"))
    if skipped:         parts.append(f"{skipped} skipped")
    summary3 = " / ".join(parts)
    _log_phase_complete("3", elapsed, summary3)
    return summary3


# ---------------------------------------------------------------------------
# SCORING PHASE
# ---------------------------------------------------------------------------

def recompute_scores_for_items(items: list[dict], score_config: dict) -> int:
    updated = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type")).lower() == "tv" and isinstance(item.get("seasons"), list):
            seasons = []
            for season in item.get("seasons") or []:
                if not isinstance(season, dict):
                    continue
                season_for_score = {
                    "type": "tv",
                    "resolution": season.get("resolution"),
                    "width": season.get("width"),
                    "height": season.get("height"),
                    "codec": season.get("codec"),
                    "audio_codec_raw": season.get("audio_codec_raw"),
                    "audio_codec": season.get("audio_codec"),
                    "audio_channels": season.get("audio_channels"),
                    "audio_languages": season.get("audio_languages") or [],
                    "audio_languages_simple": season.get("audio_languages_simple"),
                    "hdr": season.get("hdr"),
                    "hdr_type": season.get("hdr_type"),
                    "size_b": season.get("size_b"),
                }
                quality = compute_quality(season_for_score, score_config)
                season_copy = dict(season)
                season_copy["quality"] = quality
                seasons.append(season_copy)
            item["seasons"] = seasons
            item_for_score = {
                "type": "tv",
                "resolution": item.get("resolution"),
                "width": item.get("width"),
                "height": item.get("height"),
                "codec": item.get("codec"),
                "audio_codec_raw": item.get("audio_codec_raw"),
                "audio_codec": item.get("audio_codec"),
                "audio_channels": item.get("audio_channels"),
                "audio_languages": item.get("audio_languages") or [],
                "audio_languages_simple": item.get("audio_languages_simple"),
                "hdr": item.get("hdr"),
                "hdr_type": item.get("hdr_type"),
                "size_b": item.get("size_b"),
            }
            item["quality"] = _aggregate_series_quality_from_seasons(
                seasons,
                score_config=score_config,
                fallback_item_for_score=item_for_score,
            )
        else:
            item["quality"] = compute_quality(item, score_config)
        item.pop("score", None)
        updated += 1
    return updated


def recompute_scores_only(score_config: dict | None = None) -> int:
    data = load_library_document_non_blocking(OUTPUT_PATH)
    if not isinstance(data, dict):
        log.error(f"[score] Cannot read {OUTPUT_PATH}")
        return 0

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return 0

    if isinstance(score_config, dict):
        effective_score_config, _ = validate_score_config(score_config, defaults=load_score_defaults())
    else:
        _, effective_score_config, _ = get_effective_score_config()

    recalculated = recompute_scores_for_items(items, effective_score_config)
    write_json(data, OUTPUT_PATH)
    return recalculated


def run_scoring(only_category: str | None = None) -> str:
    _t0 = time.monotonic()
    cfg = load_config()
    if not _is_score_enabled(cfg):
        log.info("%s Disabled (score.enabled=false) — skipping phase", _phase_prefix("4"))
        return ""

    _log_phase_start("4")
    data = load_library_document_non_blocking(OUTPUT_PATH)
    if not isinstance(data, dict):
        log.error(f"{_phase_prefix('4')} Cannot read {OUTPUT_PATH}")
        return ""

    items = data.get("items", [])
    by_cat: dict = defaultdict(list)
    for item in items:
        cat_name = item.get("category")
        if not cat_name:
            continue
        if only_category and cat_name != only_category:
            continue
        by_cat[cat_name].append(item)

    if not by_cat:
        _log_phase_complete("4", time.monotonic() - _t0, _count_label(0, "item"))
        return "0 items scored"

    # Build category display-name → raw folder name lookup for consistent log labels
    cat_folder_by_name = {c["name"]: c["folder"] for c in build_categories_from_config(cfg)}

    _, effective_score_config, _ = get_effective_score_config(cfg)

    scored_total = 0
    sorted_score_cats = sorted(by_cat.items())
    n_score_cats = len(sorted_score_cats)
    for cat_idx, (cat_name, cat_items) in enumerate(sorted_score_cats, 1):
        cat_folder = cat_folder_by_name.get(cat_name, cat_name)
        cat_started_at = time.monotonic()
        log.info(f"{_phase_prefix('4')} Folder [{cat_folder}] ({cat_idx}/{n_score_cats}) started — {len(cat_items)} item(s)")
        scored_total += recompute_scores_for_items(cat_items, effective_score_config)
        _sanitize_library_document(data)
        write_json(data, OUTPUT_PATH)
        log.info(f"{_phase_prefix('4')} Folder [{cat_folder}] completed in {time.monotonic() - cat_started_at:.1f}s — {len(cat_items)} item(s)")

    elapsed = time.monotonic() - _t0
    summary4 = f"{_count_label(scored_total, 'item')} scored"
    _log_phase_complete("4", elapsed, summary4)
    return summary4


def run_score_only(trigger_type: str = "manual") -> int:
    recorder = _make_recorder(trigger_type, "score_only")
    with _scan_lock("score_only"):
        recorder.start()
        recorder.start_phase("score_only")
        _t0 = time.monotonic()
        log.info("[SCAN] %s", _SCAN_SEPARATOR)
        log.info("[SCAN] [SCORE-ONLY] Starting recompute")
        log.info("[SCAN] %s", _SCAN_SEPARATOR)
        try:
            defaults, effective_score_config, _ = get_effective_score_config()
            del defaults
            recalculated = recompute_scores_only(effective_score_config)
            elapsed = time.monotonic() - _t0
            log.info(f"[SCAN] [SCORE-ONLY] Completed in {elapsed:.1f}s — {_count_label(recalculated, 'item')} scored")
            recorder.finish_phase("score_only", elapsed, f"{_count_label(recalculated, 'item')} scored")
            recorder.complete()
            return recalculated
        except Exception as exc:
            recorder.fail(str(exc))
            raise


# ---------------------------------------------------------------------------
# RECOMMENDATIONS PHASE
# ---------------------------------------------------------------------------

def run_recommendations() -> str:
    _t0 = time.monotonic()
    cfg = load_config()
    if not _is_score_enabled(cfg):
        log.info("%s Disabled — score required", _phase_prefix("5"))
        return ""
    if not _is_recommendations_enabled(cfg):
        log.info("%s Disabled — skipping phase", _phase_prefix("5"))
        return ""

    _log_phase_start("5")
    lib_data = load_library_document_non_blocking(OUTPUT_PATH, availability="available")
    if not isinstance(lib_data, dict):
        log.error(f"{_phase_prefix('5')} Cannot read {OUTPUT_PATH}")
        save_recommendations_document_non_blocking([], RECOMMENDATIONS_OUTPUT_PATH)
        return ""

    rules = _load_runtime_recommendation_rules()
    recs = generate_recommendations(lib_data, rules)
    save_recommendations_document_non_blocking(recs, RECOMMENDATIONS_OUTPUT_PATH)
    summary5 = _count_label(len(recs), "recommendation")
    _log_phase_complete("5", time.monotonic() - _t0, summary5)
    return summary5


def load_recommendations_document_non_blocking(path: str) -> dict | None:
    """Load recommendations from SQLite."""
    if recommendations_repository is not None:
        payload = recommendations_repository.load_recommendations(path)
        if not isinstance(payload, dict):
            return None
        items = payload.get("items", [])
        if isinstance(items, list):
            return payload
        if items is not None:
            raise ValueError("recommendations.items must be an array")
    log.error("[recommendations] SQLite recommendations repository unavailable")
    return None


def save_recommendations_document_non_blocking(items: list[dict], path: str) -> dict:
    """Persist generated recommendations through SQLite."""
    if recommendations_repository is not None:
        return recommendations_repository.save_recommendations(items, path)
    raise RuntimeError("SQLite recommendations repository unavailable")


def _prepare_startup_configuration() -> dict:
    """Bootstrap config on startup without forcing a media scan."""
    migrate_env_to_config()
    cfg = load_config()
    changed = False
    cfg, onboarding_changed = _ensure_needs_onboarding(cfg)
    changed = changed or onboarding_changed
    if normalize_folder_enabled_flags(cfg, drop_visible=True):
        changed = True
    root = Path(LIBRARY_PATH)
    if root.exists():
        if sync_folders(root, cfg):
            changed = True
    if changed:
        save_config(cfg)
        cfg = load_config()
    return cfg


def _resolve_startup_phases(cfg: dict) -> list[int]:
    library_exists = library_document_exists(OUTPUT_PATH)
    if library_exists:
        return []
    if not _has_configured_media_folders(cfg):
        return []
    # Startup bootstrap: lightweight initial pass only.
    return [PHASE_SCAN]


def run_phases(
    phases: list[int],
    *,
    only_category: str | None = None,
    recorder: "ScanRunRecorder | None" = None,
) -> list[tuple[str, float, str]]:
    ordered = _normalize_phases(phases)
    if not ordered:
        log.info("[SCAN] No phase selected — nothing to run")
        return []
    _log_planned_phases(ordered)
    results: list[tuple[str, float, str]] = []
    _phase_fns = {
        PHASE_SCAN:            ("1", lambda: run_quick(only_category=only_category)),
        PHASE_PROBE:           ("2", lambda: run_probe(only_category=only_category)),
        PHASE_ENRICH:          ("3", lambda: run_enrich(force=True, only_category=only_category)),
        PHASE_SCORE:           ("4", lambda: run_scoring(only_category=only_category)),
        PHASE_RECOMMENDATIONS: ("5", lambda: run_recommendations()),
    }
    for phase in ordered:
        entry = _phase_fns.get(phase)
        if entry is None:
            continue
        phase_id, fn = entry
        if recorder:
            recorder.start_phase(phase_id)
        t = time.monotonic()
        summary = fn()
        elapsed = time.monotonic() - t
        if recorder:
            recorder.finish_phase(phase_id, elapsed, summary or "")
        results.append((phase_id, elapsed, summary or ""))
    return results


def run_probe(*, only_category: str | None = None) -> str:
    cfg = load_config()
    if not isinstance(cfg.get("media_probe"), dict) or cfg["media_probe"].get("enabled") is not True:
        return ""
    if cfg["media_probe"].get("mode", "compare") != "compare":
        log.warning("%s Unsupported mode %r — skipping", _phase_prefix("2"), cfg["media_probe"].get("mode"))
        return ""
    if not library_document_exists(OUTPUT_PATH):
        log.info("%s Skipping — media library is empty", _phase_prefix("2"))
        return ""
    try:
        document = load_library_document_non_blocking(OUTPUT_PATH)
        if not isinstance(document, dict):
            log.info("%s Skipping — media library is empty", _phase_prefix("2"))
            return ""
        result = run_media_probe_pipeline_if_enabled(
            cfg,
            library_document=document,
            library_json_path=OUTPUT_PATH,
            output_path=OUTPUT_PATH,
            library_root=LIBRARY_PATH,
            only_category=only_category,
        )
        if isinstance(result, tuple) and len(result) == 2:
            updated_document, _stats = result
            write_json(updated_document, OUTPUT_PATH)
            stats = _stats if isinstance(_stats, dict) else {}
            probed = stats.get("probed", 0)
            cached = stats.get("cache_hits", 0)
            return f"{probed} probed, {cached} cache hits" if (probed or cached) else "completed"
        elif result is not None:
            log.warning("%s Probe pipeline returned unexpected result — skipping library write", _phase_prefix("2"))
    except Exception as e:
        log.exception("%s Failed: %s", _phase_prefix("2"), e)
    return ""


# ---------------------------------------------------------------------------
# RESET
# ---------------------------------------------------------------------------

def run_reset() -> None:
    """Clear all library data from SQLite and remove any legacy JSON artifact."""
    if sqlite_db is not None:
        try:
            conn = sqlite_db.initialize_database()
            with conn:
                count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
                conn.execute("DELETE FROM media")
                conn.execute("DELETE FROM recommendations")
                conn.execute("DELETE FROM scan_runs")
            conn.close()
            log.info("[reset] Cleared %d items from SQLite (media, recommendations, scan_runs)", count)
        except Exception as exc:
            log.error("[reset] Failed to clear SQLite data: %s", exc)
    else:
        log.warning("[reset] SQLite unavailable — library data not cleared")
    output = Path(OUTPUT_PATH)
    if output.exists():
        output.unlink()
        log.info("[reset] Removed legacy %s", OUTPUT_PATH)


# ---------------------------------------------------------------------------
# Title helpers (fallback when no NFO)
# ---------------------------------------------------------------------------

YEAR_PATTERNS = [
    r'\((\d{4})\)',
    r'[.\s_\-](\d{4})[.\s_\-\[]',
    r'[.\s_\-](\d{4})$',
]


def _extract_year(name: str) -> str | None:
    for pattern in YEAR_PATTERNS:
        match = re.search(pattern, name)
        if match:
            year = int(match.group(1))
            if 1888 <= year <= datetime.now().year + 2:
                return str(year)
    return None


def _clean_title(name: str) -> str:
    title = name
    title = re.sub(r'\s*\(\d{4}\).*$', '', title)
    title = re.sub(r'[.\s_\-]\d{4}[.\s_\-\[].*$', '', title)
    title = re.sub(r'[.\s_\-]\d{4}$', '', title)
    title = re.sub(r'[._]', ' ', title)
    title = re.sub(
        r'\b(bluray|blu-ray|bdrip|brrip|webrip|web-dl|hdtv|dvdrip|'
        r'1080p|720p|480p|4k|uhd|hdr|hevc|x264|x265|h264|h265|aac|dts|'
        r'extended|theatrical|remastered|proper|multi|vf|vff|vostfr)\b',
        '', title, flags=re.IGNORECASE
    )
    title = re.sub(r'\s+', ' ', title).strip()
    return title.title() if title else name


# ---------------------------------------------------------------------------
# Inter-process scan lock (fcntl — works across startup, cron, and API scans)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _scan_lock(mode: str):
    """Acquire an exclusive inter-process lock for the duration of a scan.

    Uses fcntl.flock on SCAN_LOCK_PATH so any process (startup, cron, API
    subprocess) sees the same lock state.  Raises BlockingIOError immediately
    if another scan is already running.
    """
    lock_path = Path(SCAN_LOCK_PATH)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        raise
    try:
        fd.write(f"{os.getpid()} {mode}\n")
        fd.flush()
        log.info(f"[SCAN] Scan lock acquired — mode={mode}")
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fd.close()
        log.info("[SCAN] Scan lock released")


def _is_scan_locked() -> bool:
    """Non-blocking probe: return True if the scan lock is currently held by any process."""
    lock_path = Path(SCAN_LOCK_PATH)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as fd:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except Exception:
        return False  # Fail open — never block a scan due to a lock-check error


# ---------------------------------------------------------------------------
# HTTP server (--serve mode)
# ---------------------------------------------------------------------------

_srv_lock = threading.Lock()

# Routes that don't require authentication
_PUBLIC_GET  = {"/api/auth", "/health"}
_PUBLIC_POST = {"/api/auth", "/api/logout"}

# Rate limiting for /api/auth (brute force protection)
_auth_attempts: dict = {}   # ip → [timestamps]
_AUTH_MAX_ATTEMPTS = 10
_AUTH_WINDOW       = 60     # seconds


# ---------------------------------------------------------------------------
# Session management (SQLite-backed, survives restart)
# ---------------------------------------------------------------------------

def _session_add(token: str) -> None:
    try:
        conn = sqlite_db.open_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO active_sessions(token, expires_at) "
                    "VALUES (?, datetime('now', '+7 days'))",
                    (token,),
                )
        finally:
            conn.close()
    except Exception as exc:
        log.error("[session] Failed to persist session: %s", exc)


def _session_valid(token: str) -> bool:
    try:
        conn = sqlite_db.open_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM active_sessions WHERE token = ? AND expires_at > datetime('now')",
                (token,),
            ).fetchone()
            return bool(row)
        finally:
            conn.close()
    except Exception as exc:
        log.error("[session] Failed to validate session: %s", exc)
        return False


def _session_remove(token: str) -> None:
    try:
        conn = sqlite_db.open_connection()
        try:
            with conn:
                conn.execute("DELETE FROM active_sessions WHERE token = ?", (token,))
        finally:
            conn.close()
    except Exception as exc:
        log.warning("[session] Failed to remove session: %s", exc)


def _sessions_purge_expired() -> None:
    try:
        conn = sqlite_db.open_connection()
        try:
            with conn:
                conn.execute("DELETE FROM active_sessions WHERE expires_at <= datetime('now')")
        finally:
            conn.close()
    except Exception as exc:
        log.warning("[session] Failed to purge expired sessions: %s", exc)

_srv_state = {
    "status":     "idle",
    "mode":       None,
    "started_at": None,
    "ended_at":   None,
    "phase":      None,
    "completed_phases": [],
    "initial_library_ready": False,
    "log":        [],
}
_srv_proc = None
_cron_lock = threading.Lock()
_cron_thread = None
_cron_stop = threading.Event()
_cron_job = {
    "expr": None,
    "next_run": None,
    "tz": None,
}

PHASE_SCAN = 1
PHASE_PROBE = 2
PHASE_ENRICH = 3
PHASE_SCORE = 4
PHASE_RECOMMENDATIONS = 5
_PHASE_ORDER = [PHASE_SCAN, PHASE_PROBE, PHASE_ENRICH, PHASE_SCORE, PHASE_RECOMMENDATIONS]
VALID_MODES = {"quick", "full", "default", "score_only", "phased"}
_SCAN_SEPARATOR = "─" * 47
_SCAN_FINAL_SEPARATOR = "═" * 47
_PHASE_LABELS = {
    "1": ("FILESYSTEM+NFO", "Filesystem + NFO"),
    "2": ("FFPROBE", "FFprobe technical scan"),
    "3": ("SEERR", "Seerr enrichment"),
    "4": ("SCORING", "Scoring"),
    "5": ("RECOMMENDATIONS", "Recommendations"),
}
_PHASE_ID_BY_NUMBER = {
    PHASE_SCAN: "1",
    PHASE_PROBE: "2",
    PHASE_ENRICH: "3",
    PHASE_SCORE: "4",
    PHASE_RECOMMENDATIONS: "5",
}


def _phase_prefix(phase_id: str) -> str:
    name = _PHASE_LABELS.get(str(phase_id).upper(), (str(phase_id).upper(), ""))[0]
    return f"[SCAN] [PHASE {str(phase_id).upper()}] [{name}]"


def _phase_display_name(phase_id: str) -> str:
    return _PHASE_LABELS.get(str(phase_id).upper(), (str(phase_id).upper(), str(phase_id)))[1]


def _log_phase_start(phase_id: str, *, suffix: str = "") -> None:
    log.info("[SCAN] %s", _SCAN_SEPARATOR)
    log.info("%s Starting phase%s", _phase_prefix(phase_id), suffix)
    log.info("[SCAN] %s", _SCAN_SEPARATOR)


def _log_phase_complete(phase_id: str, duration: float, summary: str | None = None) -> None:
    if summary:
        log.info("%s Summary: %s", _phase_prefix(phase_id), summary)
    log.info("%s Completed in %.1fs", _phase_prefix(phase_id), duration)


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    plural = plural or f"{singular}s"
    return f"{count} {singular if count == 1 else plural}"


def _make_recorder(trigger_type: str, mode: str, phase_plan: str | None = None) -> "ScanRunRecorder":
    """Return a ScanRunRecorder, or a no-op stub if the repository is unavailable."""
    if ScanRunRecorder is None:
        class _Noop:
            def start(self): return self
            def record_phase(self, *a, **kw): pass
            def complete(self): pass
            def fail(self, *a, **kw): pass
        return _Noop()  # type: ignore
    return ScanRunRecorder(trigger_type=trigger_type, mode=mode, phase_plan=phase_plan)


def _log_planned_phases(ordered: list[int]) -> list[str]:
    expanded = []
    for phase in ordered:
        phase_id = _PHASE_ID_BY_NUMBER.get(phase)
        if not phase_id:
            continue
        expanded.append(phase_id)
    log.info("[SCAN] Planned phases:")
    for phase_id in expanded:
        log.info("[SCAN]   %-2s -> %s", phase_id, _phase_display_name(phase_id))
    return expanded


def _is_media_probe_enabled(cfg: dict | None) -> bool:
    probe = cfg.get("media_probe") if isinstance(cfg, dict) else None
    return isinstance(probe, dict) and probe.get("enabled") is True and probe.get("mode", "compare") == "compare"


def _is_media_probe_phase_enabled() -> bool:
    try:
        cfg = load_config()
    except Exception:
        return False
    return _is_media_probe_enabled(cfg)


def _phases_display_csv(phases: list[int]) -> str:
    expanded = []
    for phase in _normalize_phases(phases):
        phase_id = _PHASE_ID_BY_NUMBER.get(phase)
        if not phase_id:
            continue
        expanded.append(phase_id)
    return ",".join(expanded)


def _normalize_phases(phases: list[int] | tuple[int, ...] | set[int] | None) -> list[int]:
    if not phases:
        return []
    wanted: set[int] = set()
    for raw in phases:
        try:
            val = int(raw)
        except Exception:
            continue
        if val in _PHASE_ORDER:
            wanted.add(val)
    return [p for p in _PHASE_ORDER if p in wanted]


def _parse_phases_csv(value: str | None) -> list[int]:
    if not isinstance(value, str) or not value.strip():
        return []
    out: list[int] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except Exception:
            continue
    return _normalize_phases(out)


def _phases_to_csv(phases: list[int] | None) -> str:
    norm = _normalize_phases(phases or [])
    return ",".join(str(p) for p in norm)


def _configured_media_folder_count(cfg: dict | None) -> int:
    if not isinstance(cfg, dict):
        return 0
    count = 0
    for folder in cfg.get("folders") or []:
        if not isinstance(folder, dict):
            continue
        if folder.get("missing"):
            continue
        if not is_folder_enabled(folder):
            continue
        if folder.get("type") in {"movie", "tv"}:
            count += 1
    return count


def _has_configured_media_folders(cfg: dict | None) -> bool:
    return _configured_media_folder_count(cfg) > 0


def _seerr_runtime_state(cfg: dict | None, secrets: dict | None = None) -> dict:
    if not isinstance(cfg, dict):
        cfg = {}
    seerr = cfg.get("seerr")
    if not isinstance(seerr, dict):
        seerr = cfg.get("jellyseerr")
    if not isinstance(seerr, dict):
        seerr = {}
    sec = secrets if isinstance(secrets, dict) else _load_secrets()
    sec, _ = _normalize_seerr_secret_keys(sec)
    return {
        "enabled": bool(seerr.get("enabled")),
        "url": str(seerr.get("url") or "").strip(),
        "has_key": bool(sec.get("seerr_apikey") or sec.get("jellyseerr_apikey")),
    }


def _is_seerr_enrichment_active(cfg: dict | None, secrets: dict | None = None) -> bool:
    st = _seerr_runtime_state(cfg, secrets=secrets)
    return bool(st["enabled"] and st["url"] and st["has_key"])


def _phase_plan_from_config(
    cfg: dict | None,
    *,
    include_phase1: bool = True,
    secrets: dict | None = None,
) -> list[int]:
    phases: list[int] = []
    if include_phase1 and _has_configured_media_folders(cfg):
        phases.append(PHASE_SCAN)
    if _is_media_probe_enabled(cfg):
        phases.append(PHASE_PROBE)
    if _is_seerr_enrichment_active(cfg, secrets=secrets):
        phases.append(PHASE_ENRICH)
    if _is_score_enabled(cfg):
        phases.append(PHASE_SCORE)
    if _is_recommendations_enabled(cfg):
        phases.append(PHASE_RECOMMENDATIONS)
    return _normalize_phases(phases)


def _folder_scan_signature(folders: list | None) -> str:
    if not isinstance(folders, list):
        return "[]"
    normalized = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        normalized.append({
            "name": str(folder.get("name") or ""),
            "type": folder.get("type"),
            "enabled": bool(is_folder_enabled(folder)),
            "missing": bool(folder.get("missing")),
        })
    normalized.sort(key=lambda f: f["name"])
    return json.dumps(normalized, sort_keys=True)


def _compute_phases_for_config_change(
    previous_cfg: dict | None,
    next_cfg: dict | None,
    *,
    secrets_before: dict | None = None,
    secrets_after: dict | None = None,
) -> list[int]:
    prev_cfg = previous_cfg if isinstance(previous_cfg, dict) else {}
    new_cfg = next_cfg if isinstance(next_cfg, dict) else {}
    prev_secrets = secrets_before if isinstance(secrets_before, dict) else _load_secrets()
    next_secrets = secrets_after if isinstance(secrets_after, dict) else _load_secrets()

    folders_changed = _folder_scan_signature(prev_cfg.get("folders")) != _folder_scan_signature(new_cfg.get("folders"))
    probe_changed = _is_media_probe_enabled(prev_cfg) != _is_media_probe_enabled(new_cfg)
    seerr_changed = _seerr_runtime_state(prev_cfg, prev_secrets) != _seerr_runtime_state(new_cfg, next_secrets)
    score_changed = _is_score_enabled(prev_cfg) != _is_score_enabled(new_cfg)
    recommendations_changed = _is_recommendations_enabled(prev_cfg) != _is_recommendations_enabled(new_cfg)

    phases: list[int] = []
    if folders_changed:
        phases.extend(_phase_plan_from_config(new_cfg, include_phase1=True, secrets=next_secrets))
        # If folders changed but none are currently configured, still run phase 1
        # to refresh library outputs consistently.
        if PHASE_SCAN not in phases:
            phases.insert(0, PHASE_SCAN)
    else:
        if probe_changed and _is_media_probe_enabled(new_cfg):
            phases.append(PHASE_PROBE)
        if seerr_changed:
            phases.append(PHASE_ENRICH)
        if score_changed:
            phases.append(PHASE_SCORE)
        if recommendations_changed:
            if _is_score_enabled(new_cfg):
                phases.append(PHASE_SCORE)
            phases.append(PHASE_RECOMMENDATIONS)
    return _normalize_phases(phases)


def _scanner_cmd(mode: str, *, phases: list[int] | None = None, category: str | None = None, origin: str | None = None) -> list[str]:
    base = [sys.executable, __file__]
    norm_phases = _normalize_phases(phases or [])
    if norm_phases:
        base += ["--phases", _phases_to_csv(norm_phases)]
    elif mode == "quick":
        base += ["--quick"]
    elif mode == "score_only":
        base += ["--score-only"]
    elif mode == "full":
        base += ["--full"]
    if category:
        base += ["--category", str(category)]
    if origin:
        base += ["--origin", str(origin)]
    return base


def _valid_user_cron(expr: str) -> bool:
    return isinstance(expr, str) and len(expr.strip().split()) == 5


def _cron_tz() -> ZoneInfo:
    name = os.environ.get("TZ", "UTC") or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        log.warning("[CRON] Invalid timezone %r — falling back to UTC", name)
        return ZoneInfo("UTC")


def _cron_from_config(cfg: dict | None = None) -> str:
    current = cfg if isinstance(cfg, dict) else load_config()
    cron = (current.get("system", {}) or {}).get("scan_cron") or ""
    return str(cron).strip()


def _cron_field_matches(field: str, value: int, *, min_value: int, max_value: int) -> bool:
    if not field:
        return False
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, raw_step = part.split("/", 1)
            try:
                step = max(1, int(raw_step))
            except Exception:
                return False
        else:
            base = part
        if base == "*":
            start, end = min_value, max_value
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except Exception:
                return False
        else:
            try:
                start = end = int(base)
            except Exception:
                return False
        if min_value <= start <= value <= end <= max_value and (value - start) % step == 0:
            return True
    return False


def _cron_field_is_wildcard(field: str) -> bool:
    return str(field or "").strip() == "*"


def _cron_dow_matches(field: str, cron_dow: int) -> bool:
    return (
        _cron_field_matches(field, cron_dow, min_value=0, max_value=7)
        or (cron_dow == 0 and _cron_field_matches(field, 7, min_value=0, max_value=7))
    )


def _cron_matches(expr: str, when: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    # Cron uses Sunday as 0 or 7; Python weekday uses Monday=0.
    cron_dow = (when.weekday() + 1) % 7
    dom_match = _cron_field_matches(dom, when.day, min_value=1, max_value=31)
    dow_match = _cron_dow_matches(dow, cron_dow)
    if _cron_field_is_wildcard(dom) and _cron_field_is_wildcard(dow):
        day_match = True
    elif _cron_field_is_wildcard(dom):
        day_match = dow_match
    elif _cron_field_is_wildcard(dow):
        day_match = dom_match
    else:
        day_match = dom_match or dow_match
    return (
        _cron_field_matches(minute, when.minute, min_value=0, max_value=59)
        and _cron_field_matches(hour, when.hour, min_value=0, max_value=23)
        and _cron_field_matches(month, when.month, min_value=1, max_value=12)
        and day_match
    )


def _next_cron_run(expr: str, now: datetime | None = None) -> datetime | None:
    if not _valid_user_cron(expr):
        return None
    tz = _cron_tz()
    current = now.astimezone(tz) if now else datetime.now(tz)
    current = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = current + timedelta(days=366)
    while current <= deadline:
        if _cron_matches(expr, current):
            return current
        current += timedelta(minutes=1)
    return None


def _format_next_run(value: datetime | None) -> str:
    return value.isoformat(timespec="minutes") if value else "none"


def _start_scheduled_scan_from_cron() -> None:
    try:
        log.info("[SCAN] Scheduled scan triggered by user cron")
        with _srv_lock:
            running = _srv_state["status"] == "running"
        if running or _is_scan_locked():
            log.warning("[SCAN] Scheduled scan skipped (lock active)")
            return
        phases = _phase_plan_from_config(load_config(), include_phase1=True)
        if not phases:
            log.info("[SCAN] Scheduled scan skipped — no enabled scan phases")
            return
        threading.Thread(target=_run_scan_bg, args=("default", phases, None, "cron"), daemon=True).start()
    except Exception as e:
        log.exception("[CRON] Scheduled scan failed: %s", e)


def _cron_loop() -> None:
    last_run_key = None
    while not _cron_stop.is_set():
        try:
            with _cron_lock:
                expr = _cron_job.get("expr")
                next_run = _cron_job.get("next_run")
            if expr and next_run:
                now = datetime.now(_cron_tz()).replace(second=0, microsecond=0)
                if now >= next_run:
                    run_key = next_run.isoformat()
                    with _cron_lock:
                        _cron_job["next_run"] = _next_cron_run(expr, next_run)
                    if run_key != last_run_key:
                        last_run_key = run_key
                        _start_scheduled_scan_from_cron()
            _cron_stop.wait(1)
        except Exception as e:
            log.exception("[CRON] Scheduled scan failed: %s", e)
            _cron_stop.wait(5)


def start_user_scan_scheduler() -> None:
    global _cron_thread
    with _cron_lock:
        if _cron_thread and _cron_thread.is_alive():
            return
        _cron_stop.clear()
        _cron_thread = threading.Thread(target=_cron_loop, name="user-scan-cron", daemon=True)
        _cron_thread.start()
    log.info("[CRON] Scheduler started")
    sync_user_scan_cron(load_config(), reason="startup")


def sync_user_scan_cron(cfg: dict | None = None, *, reason: str = "config") -> bool:
    cron_expr = _cron_from_config(cfg)
    if not cron_expr:
        with _cron_lock:
            _cron_job.update(expr=None, next_run=None, tz=str(_cron_tz().key))
        log.info("[CRON] Scheduled scan disabled or not configured")
        return True
    if not _valid_user_cron(cron_expr):
        log.warning("[CRON] Invalid scheduled scan cron %r — keeping previous schedule", cron_expr)
        return False
    next_run = _next_cron_run(cron_expr)
    if next_run is None:
        log.warning("[CRON] Invalid scheduled scan cron %r — no next run could be calculated", cron_expr)
        return False
    tz_name = os.environ.get("TZ", "UTC") or "UTC"
    with _cron_lock:
        _cron_job.update(expr=cron_expr, next_run=next_run, tz=tz_name)
    log.info("[CRON] Scheduled scan configured: %s (tz=%s, next_run=%s)", cron_expr, tz_name, _format_next_run(next_run))
    return True


def _score_ui_schema() -> dict:
    return {
        "weights": {
            "field_type": "integer",
            "min": 0,
            "max": 100,
            "sum_must_equal": 100,
        },
        "numeric_default": {
            "field_type": "number",
        },
    }


def _score_settings_payload(cfg: dict | None = None) -> dict:
    current_cfg = cfg if isinstance(cfg, dict) else load_config()
    defaults, effective, status = get_effective_score_config(current_cfg)
    return {
        "enabled": _is_score_enabled(current_cfg),
        "defaults": defaults,
        "effective": effective,
        "ui_schema": _score_ui_schema(),
        "status": status,
    }


def _is_scan_running() -> bool:
    with _srv_lock:
        running = _srv_state["status"] == "running"
    return running or _is_scan_locked()


def _log_post_save_scan_skipped() -> None:
    log.info("[SETTINGS] Settings saved; post-save scan skipped because a scan is already running")


def _start_post_save_scan_if_idle(mode: str, phases: list[int]) -> bool:
    if _is_scan_running():
        _log_post_save_scan_skipped()
        return False
    threading.Thread(target=_run_scan_bg, args=(mode, phases, None, "manual"), daemon=True).start()
    return True


_SCAN_PHASE_STATE = {
    "1": "filesystem",
    "2": "ffprobe",
    "3": "seerr",
    "4": "scoring",
    "5": "recommendations",
}


def _update_scan_phase_state_from_log(line: str) -> None:
    match = re.search(r"\[PHASE\s+([0-9A-Z]+)\]", line or "")
    if not match:
        return
    phase_id = match.group(1).upper()
    phase_name = _SCAN_PHASE_STATE.get(phase_id)
    if not phase_name:
        return
    if "Starting phase" in line:
        _srv_state["phase"] = phase_name
    if re.search(r"\]\s+Completed in", line):
        completed = list(_srv_state.get("completed_phases") or [])
        if phase_name not in completed:
            completed.append(phase_name)
        _srv_state["completed_phases"] = completed
        if phase_name == "filesystem":
            _srv_state["initial_library_ready"] = True


def _empty_recommendations_payload(enabled: bool) -> dict:
    return {"enabled": bool(enabled), "generated_at": None, "version": 1, "items": []}


_recommendations_api_cache: dict[tuple, dict] = {}


def _recommendations_api_payload(cfg: dict | None = None) -> dict:
    cache_enabled = cfg is None and Path(OUTPUT_PATH) == runtime_paths.LIBRARY_JSON
    if cache_enabled:
        cache_key = (_runtime_db_signature(), "reco")
        cached = _recommendations_api_cache.get(cache_key)
        if cached is not None:
            return cached

    current_cfg = cfg if isinstance(cfg, dict) else load_config()
    enabled = _is_recommendations_enabled(current_cfg)
    if not enabled:
        payload = _empty_recommendations_payload(False)
    else:
        raw = load_recommendations_document_non_blocking(RECOMMENDATIONS_OUTPUT_PATH)
        if not isinstance(raw, dict):
            payload = _empty_recommendations_payload(True)
        else:
            raw["enabled"] = True
            raw.setdefault("generated_at", None)
            raw.setdefault("version", 1)
            if not isinstance(raw.get("items"), list):
                raw["items"] = []
            payload = raw

    if cache_enabled:
        _recommendations_api_cache[cache_key] = payload
    return payload


_library_api_cache: dict[tuple, dict] = {}


def _runtime_db_signature() -> tuple[tuple[str, int, int], ...]:
    if Path(OUTPUT_PATH) == runtime_paths.LIBRARY_JSON:
        db_path = sqlite_db.default_db_path() if sqlite_db is not None else runtime_paths.SQLITE_DB
    else:
        db_path = Path(OUTPUT_PATH).parent / "mymedialibrary.db"
    paths = [Path(db_path), Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")]
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
            signature.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            signature.append((str(path), -1, -1))
        except Exception:
            signature.append((str(path), -2, -2))
    return tuple(signature)


def _library_api_payload(availability: str = "available") -> dict:
    started = time.perf_counter()
    cache_enabled = Path(OUTPUT_PATH) == runtime_paths.LIBRARY_JSON
    signature = _runtime_db_signature()
    cache_key = (signature, availability)
    if cache_enabled and cache_key in _library_api_cache:
        payload = _library_api_cache[cache_key]
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        log.debug("[perf] /api/library cache=hit availability=%s items=%s duration_ms=%.1f", availability, len(items), (time.perf_counter() - started) * 1000)
        return payload

    load_started = time.perf_counter()
    payload = load_library_document_non_blocking(OUTPUT_PATH, availability=availability)
    load_ms = (time.perf_counter() - load_started) * 1000
    if not isinstance(payload, dict):
        payload = {"items": [], "categories": [], "total_items": 0}
        if cache_enabled:
            _library_api_cache[cache_key] = payload
        log.debug("[perf] /api/library cache=miss availability=%s sql_ms=%.1f items=0 duration_ms=%.1f", availability, load_ms, (time.perf_counter() - started) * 1000)
        return payload
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    categories = payload.get("categories")
    if not isinstance(categories, list):
        categories = sorted({
            item.get("category")
            for item in items
            if isinstance(item, dict) and item.get("category")
        })
    payload["items"] = items
    payload["categories"] = categories
    payload["total_items"] = len(items)
    if cache_enabled:
        _library_api_cache[cache_key] = payload
    log.debug(
        "[perf] /api/library cache=miss availability=%s sql_ms=%.1f items=%s categories=%s duration_ms=%.1f",
        availability,
        load_ms,
        len(items),
        len(categories),
        (time.perf_counter() - started) * 1000,
    )
    return payload


def _run_scan_bg(mode: str, phases: list[int] | None = None, category: str | None = None, origin: str = "manual"):
    global _srv_proc
    cmd = _scanner_cmd(mode, phases=phases, category=category, origin=origin)
    env = os.environ.copy()
    env["MML_SKIP_DB_STARTUP_TASKS"] = "1"

    with _srv_lock:
        _srv_state.update(status="running", mode=mode,
                          started_at=datetime.now(timezone.utc).isoformat(),
                          ended_at=None,
                          phase=None,
                          completed_phases=[],
                          initial_library_ready=False,
                          log=[f"[server] Starting: {' '.join(cmd)}"])
        if phases:
            _srv_state["phases"] = _normalize_phases(phases)
        else:
            _srv_state.pop("phases", None)

    try:
        proc = subprocess.Popen(cmd, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        with _srv_lock:
            _srv_proc = proc

        for line in proc.stdout:
            line = line.rstrip()
            with _srv_lock:
                _srv_state["log"].append(line)
                _update_scan_phase_state_from_log(line)
                if len(_srv_state["log"]) > 500:
                    _srv_state["log"] = _srv_state["log"][-500:]

        proc.wait()
        rc = proc.returncode
        if origin == "cron" and rc != 0:
            log.error("[CRON] Scheduled scan failed: scanner exited with code %s", rc)
        with _srv_lock:
            _srv_state["ended_at"] = datetime.now(timezone.utc).isoformat()
            _srv_state["status"]   = "done" if rc == 0 else "error"
            _srv_state["phase"] = None
            _srv_state["log"].append(f"[server] Done (code {rc})")
    except Exception as e:
        if origin == "cron":
            log.exception("[CRON] Scheduled scan failed: %s", e)
        with _srv_lock:
            _srv_state["status"]   = "error"
            _srv_state["ended_at"] = datetime.now(timezone.utc).isoformat()
            _srv_state["phase"] = None
            _srv_state["log"].append(f"[server] Exception : {e}")
    finally:
        with _srv_lock:
            _srv_proc = None


class _ScanHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, data, *, set_cookie=None):
        encode_started = time.perf_counter()
        body = json.dumps(data).encode()
        encode_ms = (time.perf_counter() - encode_started) * 1000
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)
        if getattr(self, "_request_path", "").startswith("/api/"):
            request_started = getattr(self, "_request_started", None)
            duration_ms = ((time.perf_counter() - request_started) * 1000) if request_started else 0.0
            log.debug(
                "[perf] endpoint=%s status=%s bytes=%s json_ms=%.1f duration_ms=%.1f",
                self._request_path,
                code,
                len(body),
                encode_ms,
                duration_ms,
            )

    def _check_auth(self) -> bool:
        """Return True if request carries a valid mml_session cookie."""
        if not _auth_is_configured():
            return True
        token = self._session_token()
        if token and _session_valid(token):
            return True
        return False

    def _session_token(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            name, _, val = part.strip().partition("=")
            if name == "mml_session" and val:
                return val
        return None

    def _make_session_cookie(self, token: str | None, *, expire: bool = False) -> str:
        """Build a Set-Cookie value; adds Secure flag when behind an HTTPS proxy."""
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
        if expire:
            return (
                f"mml_session=; HttpOnly; Path=/; SameSite=Lax{secure}; "
                "Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            )
        return f"mml_session={token}; HttpOnly; Path=/; SameSite=Lax{secure}; Max-Age={_SESSION_MAX_AGE}"

    def _is_rate_limited(self) -> bool:
        """Return True if the client IP has exceeded the auth attempt rate limit."""
        # Use X-Forwarded-For set by nginx (real client IP) to avoid all users
        # sharing one rate-limit bucket when the proxy sits on 127.0.0.1.
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        ip = forwarded if forwarded else self.client_address[0]
        now = time.time()
        ts  = _auth_attempts.get(ip, [])
        ts  = [t for t in ts if now - t < _AUTH_WINDOW]
        ts.append(now)
        _auth_attempts[ip] = ts
        return len(ts) > _AUTH_MAX_ATTEMPTS

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._request_started = time.perf_counter()
        path = self.path.split("?")[0]
        self._request_path = path
        if path not in _PUBLIC_GET and not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        if path == "/api/scan/status":
            with _srv_lock:
                self._json(200, dict(_srv_state))
        elif path == "/api/scan/log":
            try:
                with open(_log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                tail = "".join(lines[-500:])
            except Exception as e:
                tail = f"[Error reading log: {e}]"
            body = tail.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/auth/validate":
            # Used by nginx auth_request to gate static files.
            # Auth guard above already returns 401 if token invalid;
            # reaching here means the request is authenticated.
            self._json(200, {})
        elif path == "/api/auth":
            lang = load_config().get("system", {}).get("language") or "en"
            required = _auth_is_configured()
            self._json(200, {
                "required": required,
                "language": lang,
                "authenticated": (not required) or self._check_auth(),
            })
        elif path in ("/api/scan/test-jsr", "/api/seerr/test", "/api/jellyseerr/test"):
            # Test Seerr connectivity
            jsr = _jsr_cfg()
            if not jsr["enabled"] or not jsr["url"] or not jsr["apikey"]:
                self._json(200, {"ok": False, "error": "Seerr not configured (enable and set URL + API key)"})
                return
            resp = _jsr_get("/settings/main", jsr)
            if resp is _JSR_NOT_CONFIGURED:
                self._json(200, {"ok": False, "error": "Not configured"})
            elif resp is _JSR_ERROR:
                self._json(200, {"ok": False, "error": "Connection failed — check URL and API key"})
            else:
                version = resp.get("applicationVersion") or resp.get("version") or "?"
                self._json(200, {"ok": True, "version": version, "url": jsr["url"]})
        elif path == "/health":
            ok = library_document_exists(OUTPUT_PATH)
            self._json(200 if ok else 503, {"status": "ok" if ok else "degraded"})
        elif path == "/api/library":
            _avail_raw = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("availability", ["available"])[0]
            _availability = _avail_raw if _avail_raw in ("available", "absent", "all") else "available"
            self._json(200, _library_api_payload(availability=_availability))
        elif path == "/api/config":
            cfg = load_config()
            cfg, changed = _ensure_needs_onboarding(cfg)
            if normalize_folder_enabled_flags(cfg, drop_visible=True):
                changed = True
            # First-run: auto-detect folders if none configured yet
            if not cfg.get("folders"):
                root = Path(LIBRARY_PATH)
                if root.exists():
                    sync_folders(root, cfg)
                    changed = True
            # Self-heal stale onboarding flag if a usable config already exists
            # and a library snapshot is present.
            if (
                cfg.get("system", {}).get("needs_onboarding") is True
                and _has_usable_config(cfg)
                and library_document_exists(OUTPUT_PATH)
            ):
                cfg["system"]["needs_onboarding"] = False
                changed = True
            if changed:
                save_config(cfg)
                # cfg is already the normalized state that was just written — no reload needed.
            # Mask API key — never expose the real value to the frontend
            out = copy.deepcopy(cfg)
            out["needs_onboarding"] = _derive_needs_onboarding(cfg, config_exists=_config_file_exists())
            out["auth"] = {"enabled": _auth_is_configured()}
            out, seerr_changed = normalize_seerr_config(out)
            if seerr_changed:
                changed = True
            secrets = _load_secrets()
            secrets, _ = _normalize_seerr_secret_keys(secrets)
            if out.get("seerr", {}).get("apikey"):
                out["seerr"]["apikey"] = "***"
            elif secrets.get("seerr_apikey") or secrets.get("jellyseerr_apikey"):
                out.setdefault("seerr", {})["apikey"] = "***"
            self._json(200, out)
        elif path == "/api/settings/score":
            try:
                cfg = load_config()
                cfg, changed = _ensure_needs_onboarding(cfg)
                cfg, score_changed, _ = normalize_score_configuration_sections(cfg)
                changed = changed or score_changed
                if changed:
                    save_config(cfg)
                self._json(200, _score_settings_payload(cfg))
            except Exception as e:
                log.exception("[score] GET /api/settings/score failed: %s", e)
                self._json(500, {
                    "ok": False,
                    "error": {
                        "code": "SCORE_SETTINGS_LOAD_FAILED",
                        "message": "Failed to load score settings",
                        "details": {"path": "/api/settings/score"},
                    },
                })
        elif path == "/api/providers-map":
            self._json(200, _load_runtime_provider_mapping())
        elif path == "/api/providers-logo":
            self._json(200, _load_runtime_provider_logos())
        elif path == "/api/audio-languages":
            try:
                from backend.defaults.audio_language_defaults import DEFAULT_AUDIO_LANGUAGES
            except Exception:
                from defaults.audio_language_defaults import DEFAULT_AUDIO_LANGUAGES  # type: ignore
            self._json(200, DEFAULT_AUDIO_LANGUAGES)
        elif path == "/api/audiocodec-mapping":
            try:
                from backend.defaults.audio_codec_defaults import DEFAULT_AUDIO_CODEC_MAPPING
            except Exception:
                from defaults.audio_codec_defaults import DEFAULT_AUDIO_CODEC_MAPPING  # type: ignore
            self._json(200, DEFAULT_AUDIO_CODEC_MAPPING)
        elif path == "/api/recommendations":
            self._json(200, _recommendations_api_payload())
        elif path == "/api/scans/history":
            try:
                from repositories.scan_run_repository import get_recent_scan_runs  # type: ignore
            except Exception:
                try:
                    from backend.repositories.scan_run_repository import get_recent_scan_runs
                except Exception:
                    get_recent_scan_runs = None  # type: ignore
            if get_recent_scan_runs is None:
                self._json(503, {"error": "scan history unavailable"})
            else:
                self._json(200, {"items": get_recent_scan_runs(limit=50)})
        else:
            self._json(404, {"error": "not found"})

    def _scan_running_error_payload(self) -> dict:
        return {
            "ok": False,
            "error": {
                "code": "SCAN_RUNNING",
                "message": "A scan is currently running",
                "details": {},
            },
        }

    def _handle_score_settings_update(self, payload: dict) -> None:
        try:
            defaults = load_score_defaults()
            valid, err = validate_score_payload(payload, defaults, strict=True)
            if not valid:
                self._json(400, err)
                return

            # Load ONLY score tables + score.enabled — no folders, providers, seerr, etc.
            cfg = config_repository.load_score_config_only()
            score_config_before = cfg.get("score_configuration")
            merged = merge_score_config(defaults, payload.get("score"))
            effective, _ = validate_score_config(merged, defaults=defaults)
            cfg["score_configuration"] = effective
            cfg, score_changed, _ = normalize_score_configuration_sections(cfg)
            if score_changed:
                log.info("[score] Score configuration normalized during PUT /api/settings/score")
            score_config_changed = score_config_before != cfg.get("score_configuration")
            config_repository.save_score_configuration(
                cfg.get("score_configuration"),
                _is_score_enabled(cfg),
            )
            log.info("[config] Saved: %s", "score_configuration" if score_config_changed else "(no change)")

            recalculated = 0
            mode = "config_only"
            scan_skipped = None
            if _is_score_enabled(cfg) and score_config_changed:
                if _is_scan_running():
                    _log_post_save_scan_skipped()
                    mode = "scan_skipped"
                    scan_skipped = "running"
                else:
                    try:
                        recalculated = run_score_only(trigger_type="save_settings")
                        mode = "score_only"
                    except BlockingIOError:
                        _log_post_save_scan_skipped()
                        mode = "scan_skipped"
                        scan_skipped = "running"
            _, effective_after, status_after = get_effective_score_config(cfg)
            status_after = dict(status_after)
            status_after.update({
                "recalculated_items": recalculated,
                "mode": mode,
            })
            response = {
                "ok": True,
                "enabled": _is_score_enabled(cfg),
                "effective": effective_after,
                "status": status_after,
            }
            if scan_skipped:
                response["scan_skipped"] = scan_skipped
            self._json(200, response)
        except Exception as e:
            log.exception("[score] PUT /api/settings/score failed: %s", e)
            self._json(500, {
                "ok": False,
                "error": {
                    "code": "SCORE_SETTINGS_SAVE_FAILED",
                    "message": "Failed to save score settings",
                    "details": {"path": "/api/settings/score"},
                },
            })

    def _handle_score_settings_reset(self) -> None:
        try:
            defaults = load_score_defaults()
            cfg = config_repository.load_score_config_only()
            score_config_before = cfg.get("score_configuration")
            cfg["score_configuration"] = copy.deepcopy(defaults)
            cfg, score_changed, _ = normalize_score_configuration_sections(cfg)
            if score_changed:
                log.info("[score] Score configuration normalized during POST /api/settings/score/reset")
            score_config_changed = score_config_before != cfg.get("score_configuration")
            config_repository.save_score_configuration(
                cfg.get("score_configuration"),
                _is_score_enabled(cfg),
            )
            log.info("[config] Saved: %s", "score_configuration" if score_config_changed else "(no change)")

            recalculated = 0
            mode = "config_only"
            scan_skipped = None
            if _is_score_enabled(cfg):
                if _is_scan_running():
                    _log_post_save_scan_skipped()
                    mode = "scan_skipped"
                    scan_skipped = "running"
                else:
                    try:
                        recalculated = run_score_only(trigger_type="save_settings")
                        mode = "score_only"
                    except BlockingIOError:
                        _log_post_save_scan_skipped()
                        mode = "scan_skipped"
                        scan_skipped = "running"
            _, effective_after, status_after = get_effective_score_config(cfg)
            status_after = dict(status_after)
            status_after.update({
                "recalculated_items": recalculated,
                "mode": mode,
            })
            response = {
                "ok": True,
                "enabled": _is_score_enabled(cfg),
                "effective": effective_after,
                "status": status_after,
            }
            if scan_skipped:
                response["scan_skipped"] = scan_skipped
            self._json(200, response)
        except Exception as e:
            log.exception("[score] POST /api/settings/score/reset failed: %s", e)
            self._json(500, {
                "ok": False,
                "error": {
                    "code": "SCORE_SETTINGS_RESET_FAILED",
                    "message": "Failed to reset score settings",
                    "details": {"path": "/api/settings/score/reset"},
                },
            })

    def do_PUT(self):
        self._request_started = time.perf_counter()
        path = self.path.split("?")[0]
        self._request_path = path
        if path not in _PUBLIC_POST and not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/settings/score":
            self._handle_score_settings_update(payload)
            return

        self._json(404, {"error": "not found"})

    def do_POST(self):
        self._request_started = time.perf_counter()
        path = self.path.split("?")[0]
        self._request_path = path
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        if path == "/api/auth":
            if self._is_rate_limited():
                self._json(429, {"error": "too many attempts"})
                return
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            entered = payload.get("password", "")
            ok = _auth_verify_password(entered)
            if ok:
                token = secrets.token_hex(32)
                _session_add(token)
                self._json(200, {"ok": True}, set_cookie=self._make_session_cookie(token))
            else:
                self._json(200, {"ok": False})
            return
        if path == "/api/logout":
            token = self._session_token()
            if token:
                _session_remove(token)
            self._json(200, {"ok": True}, set_cookie=self._make_session_cookie(None, expire=True))
            return
        if path not in _PUBLIC_POST and not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        if path not in (
            "/api/scan/start",
            "/api/config",
            "/api/seerr/test",
            "/api/jellyseerr/test",
            "/api/providers-map",
            "/api/settings/score",
            "/api/settings/score/reset",
        ):
            self._json(404, {"error": "not found"})
            return
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/scan/start":
            mode = (payload.get("mode", "default") if isinstance(payload, dict) else "default").lower()
            if mode not in VALID_MODES:
                self._json(400, {"error": f"invalid mode: {mode}"}); return
            with _srv_lock:
                if _srv_state["status"] == "running":
                    log.info("[SCAN] Scan already running — refusing new scan request")
                    self._json(409, self._scan_running_error_payload()); return
            if _is_scan_locked():
                log.info("[SCAN] Scan already running — refusing new scan request")
                self._json(409, self._scan_running_error_payload()); return
            cfg = load_config()
            cfg, _ = _ensure_needs_onboarding(cfg)
            if cfg.get("system", {}).get("needs_onboarding") is True:
                cfg["system"]["needs_onboarding"] = False
                save_config(cfg)
            phases = []
            if isinstance(payload, dict) and payload.get("phases"):
                raw = payload.get("phases")
                if isinstance(raw, str):
                    phases = _parse_phases_csv(raw)
                elif isinstance(raw, list):
                    phases = _normalize_phases(raw)
            if not phases:
                if mode == "quick":
                    phases = [PHASE_SCAN]
                elif mode == "score_only":
                    phases = [PHASE_SCORE]
                else:
                    phases = _phase_plan_from_config(cfg, include_phase1=True)
            phases = _normalize_phases(phases)
            if not phases:
                self._json(200, {"ok": True, "mode": mode, "phases": [], "skipped": True})
                return
            threading.Thread(target=_run_scan_bg, args=(mode, phases, None, "manual"), daemon=True).start()
            self._json(200, {"ok": True, "mode": mode, "phases": phases})

        elif path == "/api/config":
            if not isinstance(payload, dict):
                self._json(400, {"error": "payload must be a JSON object"}); return

            # ── Translate legacy enable_score field ──────────────────────────
            system_payload = payload.get("system")
            if isinstance(system_payload, dict) and "enable_score" in system_payload:
                score_payload = payload.setdefault("score", {})
                if isinstance(score_payload, dict):
                    score_payload["enabled"] = system_payload.get("enable_score") is True
                system_payload.pop("enable_score", None)
                if not system_payload:
                    payload.pop("system", None)

            # ── Handle secrets (auth, seerr apikey) ──────────────────────────
            secrets_before = _load_secrets()
            secrets_after = dict(secrets_before)
            try:
                auth_action = _apply_auth_secret_update(payload, secrets_after)
            except ValueError as e:
                self._json(400, {"ok": False, "error": {"code": "INVALID_AUTH_CONFIG", "message": str(e)}})
                return
            jsr_key_action = _apply_seerr_secret_update(payload, secrets_after)

            # ── Track which top-level keys were sent ─────────────────────────
            original_keys = frozenset(payload)

            # ── Normalize payload keys in place ──────────────────────────────
            normalize_folder_enabled_flags(payload, drop_visible=True)
            payload.pop("jellyseerr", None)
            if "seerr" in original_keys:
                payload, _ = normalize_seerr_config(payload)
                if isinstance(payload.get("seerr"), dict):
                    payload["seerr"].pop("apikey", None)
                    payload["seerr"].pop("clear_apikey", None)
            if "score" in original_keys or "score_configuration" in original_keys:
                payload, _, _ = normalize_score_configuration_sections(payload)
            if "recommendations" in original_keys:
                payload, _ = normalize_recommendations_configuration(payload)
            if "folders" in original_keys or "system" in original_keys:
                _finalize_needs_onboarding_after_config_update(payload)

            # ── Build the dict to save (only keys from original payload) ─────
            to_save = {k: payload[k] for k in original_keys if k in payload}

            # ── Load phase-affecting config from DB (only what's needed) ─────
            _PHASE_KEYS = frozenset({"folders", "media_probe", "seerr", "score", "recommendations"})
            phase_keys_in_payload = _PHASE_KEYS & original_keys
            secrets_changed = secrets_before != secrets_after
            if phase_keys_in_payload or secrets_changed:
                cfg_before = config_repository.load_phase_affecting_config(phase_keys_in_payload)
            else:
                cfg_before = {}

            # ── Patch-based save ─────────────────────────────────────────────
            written_keys = config_repository.save_config_patch(to_save)

            if secrets_changed:
                try:
                    _write_secrets(secrets_after)
                    _sync_auth_settings_to_db(secrets_after)
                except Exception as e:
                    self._json(500, {"ok": False, "error": {"code": "SECRETS_WRITE_FAILED", "message": str(e)}})
                    return

            # ── Log ──────────────────────────────────────────────────────────
            if jsr_key_action == "updated":
                log.info("[config] Seerr API key updated")
            elif jsr_key_action == "preserved":
                log.info("[config] Seerr API key preserved")
            elif jsr_key_action == "cleared":
                log.info("[config] Seerr API key cleared (explicit request)")
            if auth_action == "updated":
                log.info("[config] Authentication password updated")
            elif auth_action == "disabled":
                log.info("[config] Authentication disabled")

            if written_keys:
                log.info("[config] Saved: %s", _patch_summary(written_keys, to_save))
            else:
                log.debug("[config] Saved: (no change)")

            # ── Immediate side-effects ───────────────────────────────────────
            new_level = (to_save.get("system") or {}).get("log_level") or to_save.get("log_level") or ""
            if new_level:
                _set_global_log_level(new_level)

            if isinstance(to_save.get("system"), dict) and "scan_cron" in to_save["system"]:
                sync_user_scan_cron(to_save, reason="config update")

            # ── Phase calculation (partial before/after) ─────────────────────
            cfg_after = dict(cfg_before)
            for k in phase_keys_in_payload:
                cfg_after[k] = to_save.get(k)
            phases = _compute_phases_for_config_change(
                cfg_before, cfg_after,
                secrets_before=secrets_before, secrets_after=secrets_after,
            )
            response = {"ok": True, "phases": phases}
            if phases:
                if not _start_post_save_scan_if_idle("phased", phases):
                    response["scan_skipped"] = "running"
                else:
                    log.info("[config] Triggering phased scan from config save: %s", phases)
            set_cookie = None
            if auth_action == "updated":
                token = secrets.token_hex(32)
                _session_add(token)
                set_cookie = self._make_session_cookie(token)
            elif auth_action == "disabled":
                set_cookie = self._make_session_cookie(None, expire=True)
            self._json(200, response, set_cookie=set_cookie)

        elif path == "/api/settings/score":
            self._handle_score_settings_update(payload)

        elif path == "/api/settings/score/reset":
            self._handle_score_settings_reset()

        elif path == "/api/providers-map":
            if not isinstance(payload, dict):
                self._json(400, {"error": "payload must be a JSON object"}); return
            try:
                current = _load_runtime_provider_mapping()
                # Replace full mapping payload (explicit save from editor UI)
                # while preserving JSON object shape.
                current = payload if isinstance(payload, dict) else {}
                _save_runtime_provider_mapping(current)
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"error": str(e)})

        else:
            self._json(404, {"error": "not found"})


def serve():
    _bootstrap_sqlite_runtime()
    _sessions_purge_expired()
    start_user_scan_scheduler()
    server = http.server.HTTPServer(("127.0.0.1", 8095), _ScanHandler)
    log.info("[server] Listening on 127.0.0.1:8095")
    server.serve_forever()


def _bootstrap_sqlite_runtime() -> bool:
    """Create and migrate the runtime SQLite DB early so production startup is observable."""
    if sqlite_db is None:
        raise RuntimeError("SQLite module import failed")
    bootstrapped = bool(sqlite_db.bootstrap_runtime_database(logger=log))
    _apply_configured_log_level()
    return bootstrapped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="scanner.py",
        description="Media Library Scanner",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--quick", action="store_true",
        help="Compatibility alias: run phase 1 only")
    mode_group.add_argument("--full",  action="store_true",
        help="Compatibility alias: run the dynamic phase pipeline")
    mode_group.add_argument("--phases", default=None, metavar="LIST",
        help="Explicit phases list, comma-separated (e.g. 1,2,3,4)")
    mode_group.add_argument("--score-only", action="store_true",
        help="Recompute score fields from the SQLite media library")
    mode_group.add_argument("--serve", action="store_true",
        help="Start HTTP API server on 127.0.0.1:8095")
    mode_group.add_argument("--reset", action="store_true",
        help="Remove legacy runtime output if present and exit")
    parser.add_argument("--category", default=None, metavar="NAME",
        help="Restrict scan to a single category name")
    parser.add_argument("--origin", default="manual",
        choices=["manual", "startup", "cron"],
        help="Scan origin for logging (manual/startup/cron)")
    args = parser.parse_args()

    if args.serve:
        serve()
        return

    _bootstrap_sqlite_runtime()

    if args.reset:
        run_reset()
        return

    if args.quick:
        lock_mode = "quick"
        mode_label = "--quick"
    elif args.score_only:
        lock_mode = "score_only"
        mode_label = "--score-only"
    elif args.phases:
        lock_mode = "phased"
        mode_label = f"--phases {_phases_display_csv(_parse_phases_csv(args.phases))}"
    else:
        lock_mode = "default"
        mode_label = "dynamic pipeline"

    _phase_plan_str = (
        "score_only" if args.score_only
        else _phases_display_csv(_parse_phases_csv(args.phases)) if args.phases
        else "1" if args.quick
        else None
    )
    recorder = _make_recorder(args.origin, lock_mode, phase_plan=_phase_plan_str)
    try:
        with _scan_lock(lock_mode):
            recorder.start()
            _t_main = time.monotonic()
            phase_durations: list[tuple[str, float, str]] = []
            if args.origin == "cron":
                log.info("[SCAN] Starting scheduled scan (dynamic pipeline)")
            log.info(f"[SCAN] {_SCAN_FINAL_SEPARATOR}")
            log.info(f"[SCAN] Starting scan {mode_label}")
            log.info(f"[SCAN] {_SCAN_FINAL_SEPARATOR}")

            if args.quick:
                phase_durations = run_phases([PHASE_SCAN], only_category=args.category, recorder=recorder)
            elif args.score_only:
                recorder.start_phase("score_only")
                t_so = time.monotonic()
                log.info("[SCAN] %s", _SCAN_SEPARATOR)
                log.info("[SCAN] [SCORE-ONLY] Starting recompute")
                log.info("[SCAN] %s", _SCAN_SEPARATOR)
                _defaults, _esc, _ = get_effective_score_config()
                del _defaults
                _n_scored = recompute_scores_only(_esc)
                _so_elapsed = time.monotonic() - t_so
                log.info(f"[SCAN] [SCORE-ONLY] Completed in {_so_elapsed:.1f}s — {_count_label(_n_scored, 'item')} scored")
                recorder.finish_phase("score_only", _so_elapsed, f"{_count_label(_n_scored, 'item')} scored")
            elif args.phases:
                phase_durations = run_phases(_parse_phases_csv(args.phases), only_category=args.category, recorder=recorder)
            else:
                cfg_for_plan = _prepare_startup_configuration() if args.origin == "startup" else load_config()
                if args.origin == "startup":
                    phases = _resolve_startup_phases(cfg_for_plan)
                    if not phases:
                        log.info("[SCAN] Startup: no media scan phase required")
                else:
                    phases = _phase_plan_from_config(cfg_for_plan, include_phase1=True)
                phase_durations = run_phases(phases, only_category=args.category, recorder=recorder)

            elapsed = time.monotonic() - _t_main
            log.info(f"[SCAN] {_SCAN_FINAL_SEPARATOR}")
            log.info(f"[SCAN] Scan completed in {elapsed:.1f}s")
            if phase_durations:
                log.info("[SCAN] Phase durations:")
                for phase_id, duration, _ in phase_durations:
                    log.info(
                        "[SCAN]   Phase %-2s (%s): %.1fs",
                        phase_id,
                        _phase_display_name(phase_id).replace(" + ", "+"),
                        duration,
                    )
            log.info(f"[SCAN] {_SCAN_FINAL_SEPARATOR}")
            recorder.complete()

    except BlockingIOError:
        if args.origin == "startup":
            log.warning("[SCAN] Startup scan skipped — another scan is already running")
        elif args.origin == "cron":
            log.warning("[SCAN] Scheduled scan skipped (lock active)")
        else:
            log.warning("[SCAN] Scan already running — refusing new scan request")
        sys.exit(1)
    except Exception as exc:
        recorder.fail(str(exc))
        raise


if __name__ == "__main__":
    main()
