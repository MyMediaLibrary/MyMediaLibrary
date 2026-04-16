#!/usr/bin/env python3
"""
Media Library Scanner
Scans LIBRARY_PATH and generates a library.json file.

Modes:
  --quick    Phase 1 only: filesystem + NFO scan. No scoring, no inventory.
  --full     All 4 phases: filesystem scan, Jellyseerr (force re-fetch), scoring, inventory.
  --reset    Delete library.json and exit.
  (default)  Same as --full.

Phases:
  1. Filesystem + NFO scan — builds library.json, writes after each folder.
  2. Jellyseerr enrichment — fetches streaming providers, writes after each folder.
  3. Scoring              — computes quality scores, writes after each folder.
  4. Inventory            — updates library_inventory.json, writes after each folder + final pass.

Filters (combinable with any mode):
  --category <n>   Restrict scan to a single category name.
"""

import argparse
import contextlib
import copy
import fcntl
import hmac
import http.server
import json
import logging
from collections import defaultdict
from logging.handlers import RotatingFileHandler
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

try:
    from backend.inventory_helpers import (
        apply_forced_missing_by_categories,
        cleanup_inventory_transient_fields,
        mark_disabled_inventory_items_missing,
        merge_inventory_documents,
        reconcile_inventory_missing_states,
    )
except Exception:
    try:
        from inventory_helpers import (
            apply_forced_missing_by_categories,
            cleanup_inventory_transient_fields,
            mark_disabled_inventory_items_missing,
            merge_inventory_documents,
            reconcile_inventory_missing_states,
        )
    except Exception as e:
        def merge_inventory_documents(existing_doc: dict, current_doc: dict) -> dict:
            return current_doc

        def reconcile_inventory_missing_states(document: dict) -> dict:
            return document

        def cleanup_inventory_transient_fields(document: dict) -> dict:
            return document

        def mark_disabled_inventory_items_missing(
            document: dict,
            disabled_folder_refs: set[tuple[str, str]] | list[tuple[str, str]] | None = None,
        ) -> dict:
            return document

        def apply_forced_missing_by_categories(document: dict, categories: set[str] | list[str] | None = None) -> dict:
            return document

        logging.getLogger("scanner").warning(
            "[SCAN] inventory_helpers import failed (%s). Inventory helpers disabled; continuing non-blocking.",
            e,
        )

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LIBRARY_PATH  = os.environ.get("LIBRARY_PATH",  "/mnt/media/library")
OUTPUT_PATH   = os.environ.get("OUTPUT_PATH",   "/data/library.json")
INVENTORY_OUTPUT_PATH = os.environ.get("INVENTORY_OUTPUT_PATH", "/data/library_inventory.json")
CONFIG_PATH   = os.environ.get("CONFIG_PATH",   "/data/config.json")
SECRETS_PATH  = os.environ.get("SECRETS_PATH",  "/app/.secrets")
SCAN_LOCK_PATH = os.environ.get("SCAN_LOCK_PATH", "/data/.scan.lock")
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
# Apply log_level from config.json if available (may be adjusted later via API too)
try:
    with open(os.environ.get("CONFIG_PATH", "/data/config.json"), encoding="utf-8") as _cfg_f:
        _cfg_loglevel = json.load(_cfg_f).get("system", {}).get("log_level", "INFO")
    _set_global_log_level(_cfg_loglevel)
except Exception:
    pass
log = logging.getLogger("scanner")

try:
    from backend.scoring import compute_quality
except Exception:
    try:
        from scoring import compute_quality
    except Exception as e:
        logging.getLogger("scanner").warning(
            "[SCAN] scoring import failed (%s). Quality scoring disabled; continuing non-blocking.",
            e,
        )

        def compute_quality(item: dict) -> dict:
            return {
                "score": 0,
                "level": 1,
                "base_score": 0,
                "penalty_total": 0,
                "video": 0,
                "audio": 0,
                "languages": 0,
                "size": 0,
                "penalties": [{"code": "scoring_unavailable", "value": 0}],
            }

try:
    from backend.nfo import (
        classify_resolution, normalize_codec, normalize_audio_codec,
        parse_audio_languages, simplify_audio_languages,
        parse_movie_nfo, parse_tvshow_nfo, count_seasons_episodes,
        find_episode_nfo, find_movie_nfo, poster_rel_path,
        _nfo_stats, _parse_lang_raw, _parse_concatenated_lang_codes,
    )
except ImportError:
    from nfo import (
        classify_resolution, normalize_codec, normalize_audio_codec,
        parse_audio_languages, simplify_audio_languages,
        parse_movie_nfo, parse_tvshow_nfo, count_seasons_episodes,
        find_episode_nfo, find_movie_nfo, poster_rel_path,
        _nfo_stats, _parse_lang_raw, _parse_concatenated_lang_codes,
    )

# Rotating file log: 5MB max, keep 3 backups — in /data/ so it's accessible from host
_log_file = os.environ.get("LOG_PATH", "/data/scanner.log")
try:
    _fh = RotatingFileHandler(_log_file, maxBytes=5*1024*1024, backupCount=3)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_fh)
except Exception:
    pass  # log file not writable in some environments


# ---------------------------------------------------------------------------
# Jellyseerr — providers only
# ---------------------------------------------------------------------------

_JSR_NOT_CONFIGURED = object()  # sentinel: Jellyseerr not configured/disabled
_JSR_ERROR          = object()  # sentinel: HTTP/network error (transient — do not mark providers_fetched)
_JSR_NOT_FOUND      = object()  # sentinel: HTTP 500 "Unable to retrieve" — item not in Jellyseerr


def _load_secrets() -> dict:
    """Load /app/.secrets (JSON). Returns {} if missing or unreadable."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_secrets(data: dict) -> None:
    """Write secrets dict to SECRETS_PATH with mode 600."""
    try:
        with open(SECRETS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        try:
            os.chmod(SECRETS_PATH, 0o600)
        except OSError as e:
            log.error(f"[secrets] Failed to set permissions on {SECRETS_PATH}: {e}")
    except Exception as e:
        log.warning(f"[secrets] Could not write {SECRETS_PATH}: {e}")


def _redact_config_payload(payload: dict) -> dict:
    """Return a copy of payload with sensitive fields redacted for safe logging."""
    safe_payload = copy.deepcopy(payload)
    jsr = safe_payload.get("jellyseerr")
    if isinstance(jsr, dict) and "apikey" in jsr:
        jsr["apikey"] = "***"
    return safe_payload


def _apply_jellyseerr_secret_update(payload: dict, secrets: dict) -> str:
    """
    Apply Jellyseerr API key update policy from payload to secrets.

    Rules:
    - apikey missing        => not modified
    - apikey empty/whitespace/"***" => preserved (no overwrite)
    - apikey non-empty      => updated
    - clear_apikey=true     => explicit clear
    """
    jsr = payload.get("jellyseerr")
    if not isinstance(jsr, dict):
        return "not modified"

    clear_requested = jsr.pop("clear_apikey", False) is True
    has_apikey_field = "apikey" in jsr
    raw_apikey = jsr.pop("apikey", None) if has_apikey_field else None

    if not jsr:
        payload.pop("jellyseerr", None)

    if clear_requested:
        secrets.pop("jellyseerr_apikey", None)
        return "cleared"

    if not has_apikey_field:
        return "not modified"

    normalized = raw_apikey.strip() if isinstance(raw_apikey, str) else ""
    if not normalized or normalized == "***":
        return "preserved"

    secrets["jellyseerr_apikey"] = normalized
    return "updated"


def _jsr_cfg() -> dict:
    """Read Jellyseerr settings. API key comes from /app/.secrets, rest from config.json."""
    cfg = load_config()
    jsr = cfg.get("jellyseerr", {})
    secrets = _load_secrets()
    # Prefer secrets file for apikey; fall back to config.json (legacy / migration)
    apikey = secrets.get("jellyseerr_apikey") or jsr.get("apikey", "")
    return {
        "enabled": jsr.get("enabled", False),
        "url":     jsr.get("url", "").rstrip("/"),
        "apikey":  apikey,
    }


def _jsr_get(path: str, jsr: dict | None = None):
    """
    Returns:
      dict              — success (parsed JSON)
      _JSR_NOT_CONFIGURED — Jellyseerr disabled or not configured
      _JSR_ERROR          — HTTP/network error (already logged as WARNING)
    """
    if jsr is None:
        jsr = _jsr_cfg()
    if not jsr["enabled"] or not jsr["url"] or not jsr["apikey"]:
        return _JSR_NOT_CONFIGURED
    url = f"{jsr['url']}/api/v1{path}"
    log.debug(f"Jellyseerr GET: {url}")
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
            log.debug(f"[jellyseerr] Item not found for {path} (not in Jellyseerr/TMDB)")
            return _JSR_NOT_FOUND
        log.warning(f"Jellyseerr HTTP {e.code} for {path}: {body}")
        return _JSR_ERROR
    except Exception as e:
        log.warning(f"Jellyseerr request failed for {path}: {type(e).__name__}: {e}")
        return _JSR_ERROR


PROVIDERS_JSON_PATH = "/usr/share/nginx/html/providers.json"


def load_provider_map() -> dict:
    if os.path.exists(PROVIDERS_JSON_PATH):
        with open(PROVIDERS_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("mapping", {}) if isinstance(data, dict) else {}
    log.warning("[providers] providers.json not found, no normalization applied")
    return {}


def clean_provider_name(name: str) -> str:
    """Defensive cleaning before provider map lookup."""
    s = name.strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*Amazon Channel$', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'\s*Apple TV Channel$', '', s, flags=re.IGNORECASE).strip()
    return s


def normalize_provider(name: str, provider_map: dict) -> str:
    """Return normalized name from map, or raw name if not found."""
    # Exact match
    if name in provider_map:
        return provider_map[name]
    # Defensive cleaning fallback (double spaces, trailing suffixes)
    cleaned = clean_provider_name(name)
    if cleaned != name:
        if cleaned in provider_map:
            return provider_map[cleaned]
        # Case-insensitive fallback
        cleaned_l = cleaned.lower()
        for k, v in provider_map.items():
            if k.lower() == cleaned_l:
                return v
    log.warning(f"[providers] Unmapped provider: {name!r}")
    return name


_fetch_providers_sampled = False  # log raw response once per run

# Sentinel returned when Jellyseerr call fails (vs [] = success with no FR providers)
_FETCH_ERROR    = object()
_ENRICH_WORKERS = 5  # ThreadPoolExecutor workers for Jellyseerr enrichment

def fetch_providers(tmdb_id: str | int, is_tv: bool, jsr: dict | None = None, provider_map: dict | None = None):
    """
    Fetch FR streaming providers from Jellyseerr.
    Returns:
      list[dict]   — success (may be empty if no FR providers)
                     each dict: {raw_name, name (normalized), logo, logo_url}
      _FETCH_ERROR — Jellyseerr unreachable/error (caller should not set providers_fetched=True)
    """
    global _fetch_providers_sampled
    if provider_map is None:
        provider_map = {}
    if not tmdb_id:
        return []
    media = "tv" if is_tv else "movie"
    resp = _jsr_get(f"/{media}/{tmdb_id}", jsr)

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
        log.debug(f"[providers] Jellyseerr response keys for {media}/{tmdb_id}: {top_keys}")
        wp_raw = data.get("watchProviders")
        log.debug(f"[providers] watchProviders sample: {json.dumps(wp_raw)[:600] if wp_raw is not None else 'KEY ABSENT'}")

    watch_providers = data.get("watchProviders") or []
    # Jellyseerr can return either a list [{iso_3166_1, flatrate}] or a dict {"FR": {...}}
    if isinstance(watch_providers, dict):
        fr = watch_providers.get("FR") or watch_providers.get("fr") or {}
    else:
        fr = next((p for p in watch_providers if p.get("iso_3166_1") == "FR"), {})

    flatrate = fr.get("flatrate") or []
    if not flatrate and watch_providers:
        log.debug(f"[providers] {media}/{tmdb_id}: no FR flatrate (fr keys: {list(fr.keys()) if fr else 'no FR entry'})")

    seen_canonical, result = set(), []
    for p in flatrate:
        raw_name = p.get("name") or p.get("provider_name") or ""
        if not raw_name:
            continue
        log.debug(f"[providers_raw] {media}/{tmdb_id}: {raw_name!r}")
        canonical = normalize_provider(raw_name, provider_map)
        if canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        log.debug(f"[providers] {media}/{tmdb_id}: {raw_name!r} → {canonical!r}")
        # logoPath (camelCase Jellyseerr) or logo_path (snake_case TMDB passthrough)
        raw_logo = p.get("logoPath") or p.get("logo_path") or p.get("logo")
        if raw_logo and raw_logo.startswith("http"):
            logo_url  = raw_logo
            logo      = None  # relative path unknown
        elif raw_logo:
            logo_url  = f"https://image.tmdb.org/t/p/w45{raw_logo}"
            logo      = raw_logo
        else:
            log.warning(f"[providers] No logo field for {canonical!r} in {media}/{tmdb_id}, raw={p}")
            logo_url = logo = None
        result.append({"raw_name": raw_name, "name": canonical, "logo": logo, "logo_url": logo_url})
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
    JELLYSEERR_URL, etc.) and populate config.json if the corresponding fields
    are still at their defaults/empty. Idempotent — safe to call every startup.
    """
    cfg = load_config()
    changed = False

    # Jellyseerr
    env_url    = os.environ.get("JELLYSEERR_URL",    "").rstrip("/")
    env_apikey = os.environ.get("JELLYSEERR_APIKEY", "")
    env_jsr_on = os.environ.get("ENABLE_JELLYSEERR", "")
    jsr = cfg.setdefault("jellyseerr", {})
    if env_url and not jsr.get("url"):
        jsr["url"]     = env_url
        jsr["enabled"] = env_jsr_on.lower() == "true" if env_jsr_on else True
        changed = True
    secrets = _load_secrets()
    if env_apikey and not secrets.get("jellyseerr_apikey") and not jsr.get("apikey"):
        secrets["jellyseerr_apikey"] = env_apikey
        _save_secrets(secrets)
        log.info("[migrate] Jellyseerr API key migrated to /app/.secrets")
    # Remove apikey from config.json if still present (migration cleanup)
    if jsr.pop("apikey", None):
        changed = True

    # enable_movies / enable_series
    if "enable_movies" not in cfg:
        env_em = os.environ.get("ENABLE_MOVIES", "")
        if env_em:
            cfg["enable_movies"] = env_em.lower() == "true"
            changed = True
    if "enable_series" not in cfg:
        env_es = os.environ.get("ENABLE_SERIES", "")
        if env_es:
            cfg["enable_series"] = env_es.lower() == "true"
            changed = True

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

    # system block defaults
    sys_cfg = cfg.setdefault("system", {})
    if not sys_cfg.get("scan_cron"):
        sys_cfg["scan_cron"] = "0 3 * * *"
        changed = True
    if not sys_cfg.get("log_level"):
        sys_cfg["log_level"] = "INFO"
        changed = True
    if "inventory_enabled" not in sys_cfg:
        sys_cfg["inventory_enabled"] = False
        changed = True
    if "enable_score" not in sys_cfg:
        sys_cfg["enable_score"] = False
        changed = True

    ui_cfg = cfg.setdefault("ui", {})
    if "synopsis_on_hover" not in ui_cfg:
        ui_cfg["synopsis_on_hover"] = False
        changed = True

    if changed:
        save_config(cfg)
        log.info("[MIGRATION] Env vars migrated to config.json")


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


def format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


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


def _make_inventory_video_file(name: str, now_utc: str) -> dict:
    return {
        "name": name,
        "status": "present",
        "first_seen_at": now_utc,
        "last_seen_at": now_utc,
        "last_checked_at": now_utc,
    }


def build_inventory_item(media_dir: Path, cat: dict, title: str, now_utc: str) -> dict:
    media_type = "tv" if cat["type"] == "tv" else "movie"
    item = {
        "id": _inventory_item_id(media_type, cat["name"], media_dir.name),
        "media_type": media_type,
        "category": cat["name"],
        "title": title,
        "root_folder_path": str(media_dir),
        "status": "present",
        "first_seen_at": now_utc,
        "last_seen_at": now_utc,
        "last_checked_at": now_utc,  # always after last_seen_at, before video_files
        "video_files": [_make_inventory_video_file(vf, now_utc) for vf in _list_video_files(media_dir)],
    }
    if media_type == "tv":
        subfolders: list[dict] = []
        try:
            for subdir in sorted(media_dir.iterdir(), key=lambda p: p.name.lower()):
                if not subdir.is_dir() or subdir.name.startswith((".", "@")):
                    continue
                sub_video_files = _list_video_files(subdir)
                if not sub_video_files:
                    continue
                subfolders.append({
                    "name": subdir.name,
                    "status": "present",
                    "first_seen_at": now_utc,
                    "last_seen_at": now_utc,
                    "last_checked_at": now_utc,  # always after last_seen_at, before video_files
                    "video_files": [_make_inventory_video_file(vf, now_utc) for vf in sub_video_files],
                })
        except Exception:
            subfolders = []
        item["subfolders"] = subfolders
    return item


def build_library_inventory(scanned_entries: list[dict], scan_mode: str, now: datetime | None = None) -> dict:
    now_dt = now or datetime.now(timezone.utc)
    now_utc = now_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    inventory_items = [
        build_inventory_item(entry["media_dir"], entry["cat"], entry["title"], now_utc)
        for entry in scanned_entries
    ]
    return {
        "version": 1,
        "generated_at": now_utc,
        "scan_mode": scan_mode,
        "missing_reconciliation": False,
        "items": inventory_items,
    }


def write_inventory_json_non_blocking(
    scanned_entries: list[dict],
    scan_mode: str,
    reconcile_missing: bool | None = None,
    forced_missing_folder_refs: set[tuple[str, str]] | list[tuple[str, str]] | None = None,
    forced_missing_categories: set[str] | list[str] | None = None,
) -> None:
    log.debug("[SCAN] Inventory write started")
    try:
        current_inventory = build_library_inventory(scanned_entries, scan_mode)
        existing_inventory = load_existing_inventory_document_non_blocking(INVENTORY_OUTPUT_PATH)
        inventory_to_write = current_inventory
        if existing_inventory is not None:
            try:
                inventory_to_write = merge_inventory_documents(existing_inventory, current_inventory)
            except Exception as e:
                log.warning(
                    f"[SCAN] Inventory merge failed: {e}. Falling back to current scan inventory."
                )
        should_reconcile_missing = (scan_mode == "full") if reconcile_missing is None else bool(reconcile_missing)
        if should_reconcile_missing:
            try:
                inventory_to_write = reconcile_inventory_missing_states(inventory_to_write)
                inventory_to_write["missing_reconciliation"] = True
            except Exception as e:
                inventory_to_write["missing_reconciliation"] = False
                log.warning(
                    f"[SCAN] Inventory missing reconciliation failed: {e}. Continuing with merged inventory."
                )
        else:
            inventory_to_write["missing_reconciliation"] = False
        if forced_missing_folder_refs:
            inventory_to_write = mark_disabled_inventory_items_missing(
                inventory_to_write,
                forced_missing_folder_refs,
            )
        elif forced_missing_categories:
            inventory_to_write = apply_forced_missing_by_categories(
                inventory_to_write,
                forced_missing_categories,
            )
        inventory_to_write = cleanup_inventory_transient_fields(inventory_to_write)
        write_json(inventory_to_write, INVENTORY_OUTPUT_PATH)
        log.debug(f"[SCAN] Inventory written successfully: {INVENTORY_OUTPUT_PATH}")
    except Exception as e:
        log.warning(f"[SCAN] Inventory write failed: {e}")


def load_existing_inventory_document_non_blocking(path: str) -> dict | None:
    """Load inventory JSON for merge; return None on missing/invalid/non-dict."""
    inventory_path = Path(path)
    if not inventory_path.exists():
        return None
    try:
        with open(inventory_path, encoding="utf-8") as f:
            document = json.load(f)
        if not isinstance(document, dict):
            raise ValueError("inventory root must be a JSON object")
        if not isinstance(document.get("items", []), list):
            raise ValueError("inventory.items must be an array")
        return document
    except Exception as e:
        log.warning(f"[SCAN] Failed to load existing inventory {path}: {e}. Falling back to current scan inventory.")
        return None


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_existing(output_path: str) -> dict:
    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        return {item["path"]: item for item in data.get("items", [])}
    except Exception:
        return {}


def write_json(data: dict, output_path: str) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.debug(f"Written: {output_path}")


# ---------------------------------------------------------------------------
# Config helpers (config.json)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict = {
    "system": {
        "scan_cron": "0 3 * * *",
        "log_level": "INFO",
        "needs_onboarding": True,
        "inventory_enabled": False,
        "enable_score": False,
    },
    "folders": [],
    "enable_movies": True,
    "enable_series": True,
    "jellyseerr": {
        "enabled": False,
        "url": "",
    },
    "providers_visible": [],
    "ui": {
        "synopsis_on_hover": False,
        "default_view": "grid",
        "default_sort": "title-asc",
        "theme": "dark",
        "accent_color": "#7c6aff",
    },
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_CONFIG)


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


def _is_inventory_enabled(cfg: dict | None) -> bool:
    system = (cfg or {}).get("system") or {}
    return system.get("inventory_enabled") is True


def _is_score_enabled(cfg: dict | None) -> bool:
    system = (cfg or {}).get("system") or {}
    return system.get("enable_score") is True


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
    output = Path(CONFIG_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge update into base, returning a new dict."""
    result = dict(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# QUICK SCAN
# ---------------------------------------------------------------------------

def _write_library_snapshot(items: list[dict], prev_data: dict, score_enabled: bool, output_path: str) -> None:
    """Write current library state to JSON (used for incremental per-folder writes)."""
    all_categories = sorted({i["category"] for i in items})
    data = {
        "scanned_at":          datetime.now().isoformat(),
        "library_path":        LIBRARY_PATH,
        "total_items":         len(items),
        "categories":          all_categories,
        "items":               items,
        "providers_meta":      prev_data.get("providers_meta") or {},
        "providers_raw_meta":  prev_data.get("providers_raw_meta") or {},
        "providers_raw":       prev_data.get("providers_raw") or [],
        "config": {
            "library_path": LIBRARY_PATH,
        },
        "meta": {
            "score_enabled": score_enabled,
        },
    }
    write_json(data, output_path)


def _normalize_providers(providers) -> list[str]:
    """Normalize providers to a list of canonical name strings (new format).
    Handles both legacy {name, logo} objects and already-normalized strings."""
    result = []
    for p in (providers or []):
        if isinstance(p, str) and p:
            result.append(p)
        elif isinstance(p, dict) and p.get("name"):
            result.append(p["name"])
    return result

def _strip_score_fields(item: dict) -> dict:
    """Remove score-related fields from one item (in place) for score-disabled runs."""
    if not isinstance(item, dict):
        return item
    item.pop("quality", None)
    # Legacy compatibility: some older datasets stored top-level score payloads
    item.pop("score", None)
    return item

def scan_media_item(media_dir: Path, root: Path, cat: dict, prev: dict, enable_score: bool = True) -> dict:
    """
    Build one item dict from filesystem + NFO.
    `prev` is the existing item from library.json (may be empty dict).
    `id` is computed using the same helper as library_inventory.json so both
    files share identical stable IDs.
    """
    raw_name  = media_dir.name
    item_path = str(media_dir.relative_to(root))
    mtime     = media_dir.stat().st_mtime
    is_tv     = cat["type"] == "tv"
    media_type = "tv" if is_tv else "movie"
    lib_id     = _inventory_item_id(media_type, cat["name"], raw_name)

    # --- NFO metadata ---
    nfo_meta = {}
    if is_tv:
        tvshow_nfo = media_dir / "tvshow.nfo"
        if tvshow_nfo.exists():
            nfo_meta = parse_tvshow_nfo(tvshow_nfo)
        res_meta = find_episode_nfo(media_dir)
        nfo_meta.update(res_meta)
        s_count, e_count = count_seasons_episodes(media_dir)
        nfo_meta["season_count"]  = s_count
        nfo_meta["episode_count"] = e_count
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

    # --- tmdb_id from NFO (always fresh) ---
    tmdb_id = nfo_meta.get("tmdb_id") or prev.get("tmdb_id")
    size_b = get_dir_size(media_dir)

    hdr_current = bool(nfo_meta.get("hdr", False))
    hdr_type_current = (nfo_meta.get("hdr_type") or "").strip() or None
    hdr_type_value = (hdr_type_current or prev.get("hdr_type")) if hdr_current else None

    item = {
        # id must be first — identical to library_inventory.json for cross-file matching
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
        "resolution":        nfo_meta.get("resolution") or prev.get("resolution"),
        "width":             nfo_meta.get("width")      or prev.get("width"),
        "height":            nfo_meta.get("height")     or prev.get("height"),
        "plot":              nfo_meta.get("plot")        or prev.get("plot"),
        "runtime":           nfo_meta.get("runtime")    or prev.get("runtime"),
        "runtime_min":       nfo_meta.get("runtime_min") or prev.get("runtime_min"),
        "season_count":      nfo_meta.get("season_count")  or prev.get("season_count"),
        "episode_count":     nfo_meta.get("episode_count") or prev.get("episode_count"),
        "codec":              nfo_meta.get("codec")              or prev.get("codec"),
        "audio_codec_raw":    nfo_meta.get("audio_codec_raw")    or prev.get("audio_codec_raw"),
        "audio_codec":        nfo_meta.get("audio_codec")        or prev.get("audio_codec")        or "UNKNOWN",
        "audio_codec_display": nfo_meta.get("audio_codec_display") or prev.get("audio_codec_display") or "Unknown",
        "audio_languages":    nfo_meta.get("audio_languages")    or prev.get("audio_languages")    or [],
        "audio_languages_simple": nfo_meta.get("audio_languages_simple") or prev.get("audio_languages_simple") or simplify_audio_languages(nfo_meta.get("audio_languages") or prev.get("audio_languages") or []),
        "hdr":               hdr_current,
        "hdr_type":          hdr_type_value,
        # Enriched fields preserved from previous library.json — overwritten by full scan phases
        "providers":         _normalize_providers(prev.get("providers", [])),
        "providers_fetched": prev.get("providers_fetched", False),
    }
    if enable_score:
        item["quality"] = prev.get("quality")  # preserved during quick scan; overwritten by phase 3
    return item



def run_quick(only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    _nfo_stats["ok"] = 0
    _nfo_stats["failed"] = 0
    scope = f" [category: {only_category}]" if only_category else ""
    log.info(f"[SCAN] ── Phase 1 : filesystem + NFO{scope} ──────────────")

    root = Path(LIBRARY_PATH)
    if not root.exists():
        log.error(f"[SCAN] Library path not found: {LIBRARY_PATH}")
        return

    # One-time migration of legacy env vars → config.json
    migrate_env_to_config()

    # Sync folders with filesystem (adds new, marks missing)
    cfg = load_config()
    if sync_folders(root, cfg):
        save_config(cfg)
        cfg = load_config()
    if normalize_folder_enabled_flags(cfg, drop_visible=True):
        save_config(cfg)
        cfg = load_config()
    score_enabled = _is_score_enabled(cfg)

    categories = build_categories_from_config(cfg)

    # Log folders that are skipped (no type configured)
    for folder in cfg.get("folders", []):
        fname = folder.get("name")
        if not fname or folder.get("missing"):
            continue
        ftype = folder.get("type")
        if not ftype or ftype == "ignore":
            log.debug(f"[SCAN] Skipping folder [{fname}] — no type configured")

    if not categories:
        all_typed_folders = [f for f in cfg.get("folders", []) if f.get("type") in {"movie", "tv"}]
        if not all_typed_folders:
            # No folders with a recognised type configured at all
            if not Path(OUTPUT_PATH).exists():
                log.info("[SCAN] No folder configured yet — skipping scan (configure folders via the web UI)")
            else:
                log.warning("[SCAN] No folder configured with type 'movie' or 'tv' in config.json")
        else:
            # Folders exist but all are disabled — update inventory to mark them missing
            log.warning("[SCAN] All configured folders are disabled — skipping filesystem scan")
            if _is_inventory_enabled(cfg):
                disabled_refs = {
                    ("tv" if f.get("type") == "tv" else "movie", f["name"].replace("_", " ").replace("-", " ").title())
                    for f in all_typed_folders
                    if not is_folder_enabled(f)
                }
                if disabled_refs:
                    try:
                        write_inventory_json_non_blocking(
                            [],
                            scan_mode="quick",
                            reconcile_missing=not bool(only_category),
                            forced_missing_folder_refs=disabled_refs,
                        )
                    except Exception as e:
                        log.warning(f"[SCAN] Inventory sidecar failed: {e}")
        return

    log.info(f"[SCAN] {len(categories)} configured folder(s): {', '.join(c['name'] for c in categories)}")
    existing = load_existing(OUTPUT_PATH)

    # Preserve providers_meta / enriched_at from previous run
    prev_data: dict = {}
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as _f:
            prev_data = json.load(_f)
    except Exception:
        pass

    items = []
    scanned_paths = set()

    active_cats = [c for c in categories if not only_category or c["name"] == only_category]
    n_cats = len(active_cats)

    for cat_idx, cat in enumerate(active_cats, 1):
        log.info(f"[SCAN] Processing folder [{cat['folder']}] ({cat_idx}/{n_cats}) — type={cat['type']}")
        cat_dir = root / cat["folder"]
        if not cat_dir.exists():
            log.warning(f"[SCAN] Folder not found on filesystem: {cat_dir}")
            continue

        cat_items_before = len(items)
        for media_dir in sorted(cat_dir.iterdir()):
            if not media_dir.is_dir() or media_dir.name.startswith(('.', '@')):
                continue

            item_path = str(media_dir.relative_to(root))
            # Use the initial snapshot (loaded once before any writes) as source for prev
            prev = existing.get(item_path, {})

            # scan_media_item computes id = _inventory_item_id(...) — same as library_inventory.json
            item = scan_media_item(media_dir, root, cat, prev, enable_score=score_enabled)
            items.append(item)
            scanned_paths.add(item_path)

        count = len(items) - cat_items_before
        # Incremental write after each folder
        _write_library_snapshot(items, prev_data, score_enabled, OUTPUT_PATH)
        log.info(f'[SCAN] Folder [{cat["folder"]}] done — {count} item(s) found')

    # When filtering by category, preserve items from other categories
    if only_category:
        preserved = [i for i in existing.values() if i.get("path") not in scanned_paths]
        log.info(f"  Preserving {len(preserved)} items from other categories")
        for i in preserved:
            if not score_enabled:
                _strip_score_fields(i)
            # Ensure preserved items use the string id format (may be an old integer id)
            i_media_type = "tv" if i.get("type") == "tv" else "movie"
            i_folder = Path(i.get("path", "")).name
            i["id"] = _inventory_item_id(i_media_type, i.get("category", ""), i_folder)
        items = items + preserved

    if not score_enabled:
        for item in items:
            _strip_score_fields(item)

    # Only_category: final write is required to include preserved items from other categories.
    # Normal full scan: the last per-folder incremental write already captured all items — skip.
    if only_category:
        _write_library_snapshot(items, prev_data, score_enabled, OUTPUT_PATH)

    try:
        size_mb = Path(OUTPUT_PATH).stat().st_size / (1024*1024)
        size_str = f"{size_mb:.1f} MB"
    except Exception:
        size_str = "?"
    elapsed = time.monotonic() - _t0
    if _nfo_stats["failed"] > 0:
        log.info(f"[SCAN] NFO parsing: {_nfo_stats['ok']} OK / {_nfo_stats['failed']} failed (see DEBUG logs for details)")
    else:
        log.debug(f"[SCAN] NFO parsing: {_nfo_stats['ok']} OK")

    # Audio codec stats
    audio_dist: dict = {}
    for item in items:
        ac = item.get("audio_codec") or "UNKNOWN"
        audio_dist[ac] = audio_dist.get(ac, 0) + 1
    audio_parts = [f"{k}×{v}" for k, v in sorted(audio_dist.items(), key=lambda x: -x[1])]
    log.info(f"[SCAN] Audio codecs detected: {len(audio_dist)}")
    log.debug(f"[SCAN] Audio codecs detail: {' / '.join(audio_parts) if audio_parts else 'none'}")

    # Audio language stats
    lang_dist: dict = {}
    for item in items:
        for lang in (item.get("audio_languages") or []):
            lang_dist[lang] = lang_dist.get(lang, 0) + 1
    lang_parts = [f"{k}×{v}" for k, v in sorted(lang_dist.items(), key=lambda x: -x[1])]
    log.info(f"[SCAN] Audio languages detected: {len(lang_dist)}")
    if lang_parts:
        log.debug(f"[SCAN] Audio languages detail: {' / '.join(lang_parts)}")

    # Video codec stats
    video_dist: dict = {}
    for item in items:
        vc = item.get("codec") or "unknown"
        video_dist[vc] = video_dist.get(vc, 0) + 1
    video_parts = [f"{k}×{v}" for k, v in sorted(video_dist.items(), key=lambda x: -x[1])]
    log.info(f"[SCAN] Video codecs detected: {len(video_dist)}")
    log.debug(f"[SCAN] Video codecs detail: {' / '.join(video_parts) if video_parts else 'none'}")

    # Resolution stats
    res_dist: dict = {}
    for item in items:
        r = item.get("resolution") or "unknown"
        res_dist[r] = res_dist.get(r, 0) + 1
    res_parts = [f"{k}×{v}" for k, v in sorted(res_dist.items(), key=lambda x: -x[1])]
    log.info(f"[SCAN] Resolutions detected: {len(res_dist)}")
    log.debug(f"[SCAN] Resolutions detail: {' / '.join(res_parts) if res_parts else 'none'}")

    log.info(f"[SCAN] Phase 1 completed in {elapsed:.1f}s — {len(items)} item(s) total ({size_str})")

    # Inventory sidecar — non-blocking
    if _is_inventory_enabled(cfg):
        inventory_entries = [
            {"media_dir": root / item["path"], "cat": {"name": item["category"], "type": item["type"]}, "title": item["title"]}
            for item in items
        ]
        disabled_refs = {
            ("tv" if folder.get("type") == "tv" else "movie", folder["name"].replace("_", " ").replace("-", " ").title())
            for folder in cfg.get("folders", [])
            if folder.get("type") in {"movie", "tv"} and not is_folder_enabled(folder)
        }
        try:
            write_inventory_json_non_blocking(
                inventory_entries,
                scan_mode="quick",
                reconcile_missing=not bool(only_category),
                forced_missing_folder_refs=disabled_refs,
            )
        except Exception as e:
            log.warning(f"[SCAN] Inventory sidecar failed: {e}")


# ---------------------------------------------------------------------------
# ENRICH (providers via Jellyseerr)
# ---------------------------------------------------------------------------

def run_enrich(force: bool = False, only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    label = "force" if force else "missing only"
    scope = f" [category: {only_category}]" if only_category else ""
    log.info(f"[SCAN] ── Phase 2 : Jellyseerr enrichment ({label}){scope} ──")

    jsr = _jsr_cfg()
    if not jsr["enabled"]:
        log.warning("[SCAN] Jellyseerr disabled in config.json — skipping enrichment")
        return
    if not jsr["url"] or not jsr["apikey"]:
        log.warning("[SCAN] Jellyseerr URL or apikey missing in config.json — skipping enrichment")
        return

    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"Cannot read {OUTPUT_PATH}: {e}")
        return

    items = data.get("items", [])

    def needs_enrich(item: dict) -> bool:
        if only_category and item.get("category") != only_category:
            return False
        if not item.get("tmdb_id"):
            return False  # no tmdb_id from NFO → can't fetch
        if force:
            return True
        return not item.get("providers_fetched")

    to_enrich = [i for i in items if needs_enrich(i)]
    skipped   = len(items) - len(to_enrich)
    log.info(f"[SCAN] Jellyseerr enrichment: {len(to_enrich)} items to process, {skipped} skipped ({_ENRICH_WORKERS} workers)")

    if not to_enrich:
        log.info("[SCAN] Nothing to enrich.")
        return

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

    # Load provider map (file-based normalization, reloaded each scan)
    provider_map = load_provider_map()
    log.debug(f"[providers] providers.json mapping loaded ({len(provider_map)} entries)")

    # providers_meta maps normalized name → {logo, logo_url} — stored at top level
    # Seed from existing data (migration: items may still have {name, logo} objects)
    providers_meta: dict = data.get("providers_meta") or {}
    for item in items:
        for p in (item.get("providers") or []):
            if isinstance(p, dict) and p.get("name") and p["name"] not in providers_meta:
                logo_url = p.get("logo")  # old format stored full URL in "logo"
                providers_meta[p["name"]] = {"logo": None, "logo_url": logo_url}

    # providers_raw_meta maps raw name → {logo, logo_url} — accumulated across scans
    providers_raw_meta: dict = data.get("providers_raw_meta") or {}

    def _enrich_one(item):
        is_tv = item.get("type") == "tv"
        try:
            providers = fetch_providers(item["tmdb_id"], is_tv, jsr, provider_map)
        except Exception as e:
            log.warning(f"[enrich] Unexpected exception tmdb_id={item.get('tmdb_id')} {item.get('title')!r}: {e}")
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
        log.info(f"[SCAN] Enriching folder [{cat_folder}] ({cat_idx}/{n_enrich_cats}) — {len(cat_items)} item(s)")
        with ThreadPoolExecutor(max_workers=_ENRICH_WORKERS) as pool:
            futures = {pool.submit(_enrich_one, item): item for item in cat_items}
            for future in as_completed(futures):
                item, providers = future.result()
                if providers is _JSR_NOT_FOUND:
                    # Item not in Jellyseerr — mark as fetched (no FR providers)
                    item["providers"]         = []
                    item["providers_fetched"] = True
                    not_found_count += 1
                    not_found_ids.append(item.get("tmdb_id", "?"))
                    continue
                if providers is _FETCH_ERROR:
                    # Jellyseerr unreachable — leave providers_fetched False, retry next run
                    failed_count += 1
                    failed_ids.append(item.get("tmdb_id", "?"))
                    continue
                for p in providers:
                    raw  = p["raw_name"]
                    name = p["name"]
                    logo_entry = {"logo": p.get("logo"), "logo_url": p.get("logo_url")}
                    # Accumulate raw providers (first logo seen wins)
                    if raw not in providers_raw_meta or (not providers_raw_meta[raw].get("logo_url") and p.get("logo_url")):
                        providers_raw_meta[raw] = logo_entry
                    # Update normalized providers_meta (first seen wins)
                    if name not in providers_meta or (not providers_meta[name].get("logo_url") and p.get("logo_url")):
                        providers_meta[name] = logo_entry
                # Store only normalized names in item (logos centralized in providers_meta)
                item["providers"]         = [p["name"] for p in providers]
                item["providers_fetched"] = True
                enriched += 1
                log.debug(f"  {item['title']} — {len(providers)} provider(s)")

        data["providers_meta"]     = providers_meta
        data["providers_raw_meta"] = providers_raw_meta
        data["providers_raw"]      = sorted(providers_raw_meta.keys())
        data["enriched_at"]        = datetime.now().isoformat()
        write_json(data, OUTPUT_PATH)
        log.info(f"[SCAN] Folder [{cat_folder}] done — {len(cat_items)} item(s) enriched")

    elapsed = time.monotonic() - _t0
    if not_found_count:
        ids_str = ", ".join(str(i) for i in not_found_ids[:20])
        suffix  = f" … (+{len(not_found_ids)-20} more)" if len(not_found_ids) > 20 else ""
        log.info(f"[SCAN] {not_found_count} item(s) not found in Jellyseerr — tmdb_ids: {ids_str}{suffix}")
    if failed_count:
        ids_str = ", ".join(str(i) for i in failed_ids[:20])
        suffix  = f" … (+{len(failed_ids)-20} more)" if len(failed_ids) > 20 else ""
        log.warning(f"[SCAN] {failed_count} item(s) not enriched (Jellyseerr error) — tmdb_ids: {ids_str}{suffix}")
    parts = [f"{enriched} OK"]
    if not_found_count: parts.append(f"{not_found_count} not found in Jellyseerr")
    if failed_count:    parts.append(f"{failed_count} errors")
    log.info(f"[SCAN] Phase 2 completed in {elapsed:.1f}s — {' / '.join(parts)}")


# ---------------------------------------------------------------------------
# SCORING PHASE
# ---------------------------------------------------------------------------

def run_scoring(only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    cfg = load_config()
    if not _is_score_enabled(cfg):
        log.info("[SCAN] Scoring disabled (system.enable_score=false) — skipping phase 3")
        return

    log.info("[SCAN] ── Phase 3 : scoring ──────────────────────────────")
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"[SCAN] Cannot read {OUTPUT_PATH}: {e}")
        return

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
        log.info("[SCAN] No items to score.")
        return

    # Build category display-name → raw folder name lookup for consistent log labels
    cat_folder_by_name = {c["name"]: c["folder"] for c in build_categories_from_config(cfg)}

    scored_total = 0
    sorted_score_cats = sorted(by_cat.items())
    n_score_cats = len(sorted_score_cats)
    for cat_idx, (cat_name, cat_items) in enumerate(sorted_score_cats, 1):
        cat_folder = cat_folder_by_name.get(cat_name, cat_name)
        log.info(f"[SCAN] Scoring folder [{cat_folder}] ({cat_idx}/{n_score_cats}) — {len(cat_items)} item(s)")
        for item in cat_items:
            item["quality"] = compute_quality(item)
            scored_total += 1
        write_json(data, OUTPUT_PATH)
        log.info(f"[SCAN] Folder [{cat_folder}] scored")

    elapsed = time.monotonic() - _t0
    log.info(f"[SCAN] Phase 3 completed — {scored_total} item(s) scored in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# INVENTORY PHASE
# ---------------------------------------------------------------------------

def _stamp_last_checked_at(doc: dict, now_utc: str) -> None:
    """Set last_checked_at = now_utc on all items, subfolders, and video_files in-place."""
    for item in doc.get("items", []):
        item["last_checked_at"] = now_utc
        for vf in item.get("video_files", []):
            vf["last_checked_at"] = now_utc
        for sf in item.get("subfolders", []):
            sf["last_checked_at"] = now_utc
            for vf in sf.get("video_files", []):
                vf["last_checked_at"] = now_utc


def run_inventory(scan_mode: str = "full", only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    cfg = load_config()
    if not _is_inventory_enabled(cfg):
        log.info("[SCAN] Inventory disabled (system.inventory_enabled=false) — skipping phase 4")
        return

    log.info("[SCAN] ── Phase 4 : inventory ─────────────────────────────")
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            lib_data = json.load(f)
    except Exception as e:
        log.error(f"[SCAN] Cannot read {OUTPUT_PATH}: {e}")
        return

    root = Path(LIBRARY_PATH)
    now_dt = datetime.now(timezone.utc)
    now_utc = now_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Snapshot existing inventory for merge (fixed reference throughout)
    existing_inventory = load_existing_inventory_document_non_blocking(INVENTORY_OUTPUT_PATH)

    # Disabled folder refs → mark their items missing
    force_missing_folder_refs = {
        ("tv" if folder.get("type") == "tv" else "movie", folder["name"].replace("_", " ").replace("-", " ").title())
        for folder in cfg.get("folders", [])
        if folder.get("type") in {"movie", "tv"} and not is_folder_enabled(folder)
    }

    categories = build_categories_from_config(cfg)

    # Path → library item lookup for title resolution
    items_by_path: dict[str, dict] = {
        item["path"]: item for item in lib_data.get("items", []) if item.get("path")
    }

    all_new_items: list[dict] = []

    active_inv_cats = [c for c in categories if not only_category or c["name"] == only_category]
    n_inv_cats = len(active_inv_cats)

    for cat_idx, cat in enumerate(active_inv_cats, 1):
        cat_dir = root / cat["folder"]
        if not cat_dir.exists():
            log.warning(f"[SCAN] Inventory: folder not found: {cat_dir}")
            continue

        log.info(f"[SCAN] Inventory: processing folder [{cat['folder']}] ({cat_idx}/{n_inv_cats}) — type={cat['type']}")
        cat_inv_items: list[dict] = []
        for media_dir in sorted(cat_dir.iterdir()):
            if not media_dir.is_dir() or media_dir.name.startswith(('.', '@')):
                continue
            item_path = str(media_dir.relative_to(root))
            lib_item = items_by_path.get(item_path, {})
            title = lib_item.get("title") or media_dir.name

            inv_item = build_inventory_item(media_dir, cat, title, now_utc)
            cat_inv_items.append(inv_item)

        all_new_items.extend(cat_inv_items)

        # Incremental write: merge scanned-so-far against snapshot
        partial_doc = {
            "version": 1,
            "generated_at": now_utc,
            "scan_mode": scan_mode,
            "missing_reconciliation": False,
            "items": list(all_new_items),
        }
        if existing_inventory is not None:
            merged = merge_inventory_documents(existing_inventory, partial_doc)
        else:
            merged = partial_doc
        merged = cleanup_inventory_transient_fields(merged)
        write_json(merged, INVENTORY_OUTPUT_PATH)
        log.info(f"[SCAN] Inventory: folder [{cat['folder']}] done — {len(cat_inv_items)} item(s)")

    # Final pass: full merge + optional missing reconciliation
    final_doc = {
        "version": 1,
        "generated_at": now_utc,
        "scan_mode": scan_mode,
        "missing_reconciliation": False,
        "items": list(all_new_items),
    }
    if existing_inventory is not None:
        final_merged = merge_inventory_documents(existing_inventory, final_doc)
    else:
        final_merged = final_doc

    if force_missing_folder_refs:
        final_merged = mark_disabled_inventory_items_missing(final_merged, force_missing_folder_refs)

    should_reconcile = scan_mode == "full" and not only_category
    if should_reconcile:
        try:
            final_merged = reconcile_inventory_missing_states(final_merged)
            final_merged["missing_reconciliation"] = True
        except Exception as e:
            final_merged["missing_reconciliation"] = False
            log.warning(f"[SCAN] Inventory missing reconciliation failed: {e}. Continuing.")
    else:
        final_merged["missing_reconciliation"] = False

    # Stamp last_checked_at = now for all items regardless of status
    _stamp_last_checked_at(final_merged, now_utc)
    final_merged = cleanup_inventory_transient_fields(final_merged)
    write_json(final_merged, INVENTORY_OUTPUT_PATH)

    # Missing summary
    missing_items = [i for i in final_merged.get("items", []) if i.get("status") == "missing"]
    if missing_items:
        names = [i.get("title") or i.get("id", "?") for i in missing_items[:20]]
        suffix = f" … (+{len(missing_items) - 20} more)" if len(missing_items) > 20 else ""
        log.info(f"[SCAN] Inventory: {len(missing_items)} missing item(s)")
        log.debug(f"[SCAN] Inventory missing: {', '.join(names)}{suffix}")
    else:
        log.info("[SCAN] Inventory: no missing items")

    elapsed = time.monotonic() - _t0
    log.info(
        f"[SCAN] Phase 4 completed in {elapsed:.1f}s — "
        f"{len(all_new_items)} present, {len(missing_items)} missing"
    )


# ---------------------------------------------------------------------------
# RESET
# ---------------------------------------------------------------------------

def run_reset() -> None:
    output = Path(OUTPUT_PATH)
    if output.exists():
        output.unlink()
        log.info(f"Deleted {OUTPUT_PATH}")
    else:
        log.info(f"Nothing to reset ({OUTPUT_PATH} does not exist)")


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

_srv_lock      = threading.Lock()
_valid_sessions: set = set()  # in-memory session tokens (cleared on restart)

# Routes that don't require authentication
_PUBLIC_GET  = {"/api/auth", "/health"}
_PUBLIC_POST = {"/api/auth"}

# Rate limiting for /api/auth (brute force protection)
_auth_attempts: dict = {}   # ip → [timestamps]
_AUTH_MAX_ATTEMPTS = 10
_AUTH_WINDOW       = 60     # seconds

_srv_state = {
    "status":     "idle",
    "mode":       None,
    "started_at": None,
    "ended_at":   None,
    "log":        [],
}
_srv_proc = None

VALID_MODES = {"quick", "full", "default"}


def _scanner_cmd(mode: str) -> list[str]:
    base = [sys.executable, __file__]
    if mode == "quick": return base + ["--quick"]
    if mode == "full":  return base + ["--full"]
    return base + ["--full"]  # default → full


def _run_scan_bg(mode: str):
    global _srv_proc
    cmd = _scanner_cmd(mode)
    env = os.environ.copy()

    with _srv_lock:
        _srv_state.update(status="running", mode=mode,
                          started_at=datetime.now(timezone.utc).isoformat(),
                          ended_at=None, log=[f"[server] Starting: {' '.join(cmd)}"])

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
                if len(_srv_state["log"]) > 500:
                    _srv_state["log"] = _srv_state["log"][-500:]

        proc.wait()
        rc = proc.returncode
        with _srv_lock:
            _srv_state["ended_at"] = datetime.now(timezone.utc).isoformat()
            _srv_state["status"]   = "done" if rc == 0 else "error"
            _srv_state["log"].append(f"[server] Done (code {rc})")
    except Exception as e:
        with _srv_lock:
            _srv_state["status"]   = "error"
            _srv_state["ended_at"] = datetime.now(timezone.utc).isoformat()
            _srv_state["log"].append(f"[server] Exception : {e}")
    finally:
        with _srv_lock:
            _srv_proc = None


class _ScanHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        """Return True if request is authenticated (or no password is configured)."""
        pw = os.environ.get("APP_PASSWORD", "")
        if not pw:
            return True
        token = self.headers.get("X-Auth-Token", "")
        return bool(token) and token in _valid_sessions

    def _is_rate_limited(self) -> bool:
        """Return True if the client IP has exceeded the auth attempt rate limit."""
        ip  = self.client_address[0]
        now = time.time()
        ts  = _auth_attempts.get(ip, [])
        ts  = [t for t in ts if now - t < _AUTH_WINDOW]
        ts.append(now)
        _auth_attempts[ip] = ts
        return len(ts) > _AUTH_MAX_ATTEMPTS

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
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
            pw = os.environ.get("APP_PASSWORD", "")
            lang = load_config().get("system", {}).get("language") or "en"
            self._json(200, {"required": bool(pw), "language": lang})
        elif path in ("/api/scan/test-jsr", "/api/jellyseerr/test"):
            # Test Jellyseerr connectivity
            jsr = _jsr_cfg()
            if not jsr["enabled"] or not jsr["url"] or not jsr["apikey"]:
                self._json(200, {"ok": False, "error": "Jellyseerr not configured (enable and set URL + API key)"})
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
            output = os.environ.get("OUTPUT_PATH", "/data/library.json")
            ok = os.path.exists(output)
            self._json(200 if ok else 503, {
                "status": "ok" if ok else "degraded",
                "library_json": ok,
                "scanner": "idle" if _srv_state["status"] != "running" else "running",
            })
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
            if changed:
                save_config(cfg)
                cfg = load_config()
                cfg, _ = _ensure_needs_onboarding(cfg)
            # Mask API key — never expose the real value to the frontend
            out = copy.deepcopy(cfg)
            out["needs_onboarding"] = _derive_needs_onboarding(cfg, config_exists=_config_file_exists())
            if out.get("jellyseerr", {}).get("apikey"):
                out["jellyseerr"]["apikey"] = "***"
            elif _load_secrets().get("jellyseerr_apikey"):
                out.setdefault("jellyseerr", {})["apikey"] = "***"
            self._json(200, out)
        elif path == "/api/providers-map":
            if os.path.exists(PROVIDERS_JSON_PATH):
                try:
                    with open(PROVIDERS_JSON_PATH, encoding="utf-8") as f:
                        data = json.load(f)
                        self._json(200, data.get("mapping", {}) if isinstance(data, dict) else {})
                except Exception as e:
                    self._json(500, {"error": str(e)})
            else:
                self._json(200, {})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
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
            pw      = os.environ.get("APP_PASSWORD", "")
            entered = payload.get("password", "")
            ok = (
                bool(pw)
                and isinstance(entered, str)
                and hmac.compare_digest(pw, entered)
            )
            if ok:
                token = secrets.token_hex(32)
                _valid_sessions.add(token)
                self._json(200, {"ok": True, "token": token})
            else:
                self._json(200, {"ok": False})
            return
        if path not in _PUBLIC_POST and not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        if path not in ("/api/scan/start", "/api/config", "/api/jellyseerr/test", "/api/providers-map"):
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
                    self._json(409, {"error": "scan already running"}); return
            if _is_scan_locked():
                log.info("[SCAN] Scan already running — refusing new scan request")
                self._json(409, {"error": "scan already running"}); return
            cfg = load_config()
            cfg, _ = _ensure_needs_onboarding(cfg)
            if cfg.get("system", {}).get("needs_onboarding") is True:
                cfg["system"]["needs_onboarding"] = False
                save_config(cfg)
            threading.Thread(target=_run_scan_bg, args=(mode,), daemon=True).start()
            self._json(200, {"ok": True, "mode": mode})

        elif path == "/api/config":
            if not isinstance(payload, dict):
                self._json(400, {"error": "payload must be a JSON object"}); return
            cfg = load_config()
            safe_payload = _redact_config_payload(payload)
            log.info("[config] Received: %s", json.dumps(safe_payload))

            secrets_before = _load_secrets()
            secrets_after = dict(secrets_before)
            jsr_key_action = _apply_jellyseerr_secret_update(payload, secrets_after)

            merged = deep_merge(cfg, payload)
            merged, _ = _ensure_needs_onboarding(merged, config_exists=True)
            normalize_folder_enabled_flags(merged, drop_visible=True)
            # Ensure apikey never persists in config.json
            if "jellyseerr" in merged:
                merged["jellyseerr"].pop("apikey", None)
                merged["jellyseerr"].pop("clear_apikey", None)
            save_config(merged)
            if secrets_after != secrets_before:
                _save_secrets(secrets_after)

            if jsr_key_action == "updated":
                log.info("[config] Jellyseerr API key updated")
            elif jsr_key_action == "preserved":
                log.info("[config] Jellyseerr API key preserved")
            elif jsr_key_action == "cleared":
                log.info("[config] Jellyseerr API key cleared (explicit request)")
            else:
                log.info("[config] Jellyseerr API key not modified")

            log.info("[config] Saved")
            # Apply log_level change immediately without restart
            new_level = merged.get("system", {}).get("log_level") or merged.get("log_level") or ""
            if new_level:
                _set_global_log_level(new_level)

            # Trigger a quick scan when folder configuration changed (type or enabled state)
            folders_changed = "folders" in payload
            if folders_changed and not _is_scan_locked():
                log.info("[config] Folder configuration changed — triggering quick scan")
                threading.Thread(target=_run_scan_bg, args=("quick",), daemon=True).start()
            elif folders_changed:
                log.info("[config] Folder configuration changed — scan already running, skipping auto quick scan")

            self._json(200, {"ok": True})

        elif path == "/api/providers-map":
            if not isinstance(payload, dict):
                self._json(400, {"error": "payload must be a JSON object"}); return
            try:
                data = {}
                if os.path.exists(PROVIDERS_JSON_PATH):
                    with open(PROVIDERS_JSON_PATH, encoding="utf-8") as f:
                        data = json.load(f)
                data["mapping"] = payload
                with open(PROVIDERS_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self._json(200, {"ok": True})
            except Exception as e:
                self._json(500, {"error": str(e)})

        else:
            self._json(404, {"error": "not found"})


def serve():
    server = http.server.HTTPServer(("127.0.0.1", 8095), _ScanHandler)
    log.info("[server] Listening on 127.0.0.1:8095")
    server.serve_forever()


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
        help="Phase 1 only: filesystem + NFO scan, no enrichment/scoring/inventory")
    mode_group.add_argument("--full",  action="store_true",
        help="All 4 phases: filesystem scan + Jellyseerr + scoring + inventory (default)")
    mode_group.add_argument("--serve", action="store_true",
        help="Start HTTP API server on 127.0.0.1:8095")
    mode_group.add_argument("--reset", action="store_true",
        help="Delete library.json and exit")
    parser.add_argument("--category", default=None, metavar="NAME",
        help="Restrict scan to a single category name")
    parser.add_argument("--origin", default="manual",
        choices=["manual", "startup", "cron"],
        help="Scan origin for logging (manual/startup/cron)")
    args = parser.parse_args()

    if args.serve:
        serve()
        return

    if args.reset:
        run_reset()
        return

    if args.quick:
        lock_mode = "quick"
        mode_label = "--quick"
    else:
        lock_mode = "full"
        mode_label = "--full"

    try:
        with _scan_lock(lock_mode):
            _t_main = time.monotonic()
            log.info(f"[SCAN] ═══════════════════════════════════")
            log.info(f"[SCAN] Starting scan {mode_label}")
            log.info(f"[SCAN] ═══════════════════════════════════")

            if args.quick:
                run_quick(only_category=args.category)
            else:
                # --full or default
                run_quick(only_category=args.category)
                run_enrich(force=True, only_category=args.category)
                run_scoring(only_category=args.category)
                run_inventory(scan_mode="full", only_category=args.category)

            elapsed = time.monotonic() - _t_main
            log.info(f"[SCAN] ═══════════════════════════════════")
            log.info(f"[SCAN] Scan completed in {elapsed:.1f}s")
            log.info(f"[SCAN] ═══════════════════════════════════")

    except BlockingIOError:
        if args.origin == "startup":
            log.warning("[SCAN] Startup scan skipped — another scan is already running")
        elif args.origin == "cron":
            log.warning("[SCAN] Cron scan skipped — another scan is already running")
        else:
            log.warning("[SCAN] Scan already running — refusing new scan request")
        sys.exit(1)


if __name__ == "__main__":
    main()
