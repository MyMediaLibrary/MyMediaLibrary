#!/usr/bin/env python3
"""
Media Library Scanner
Scans LIBRARY_PATH and generates a library.json file.

Modes:
  --quick    Phase 1 only: filesystem + NFO scan. No scoring, no inventory.
  --full     All 4 phases: filesystem scan, Seerr (force re-fetch), scoring, inventory.
  --score-only Recompute quality scores from existing library.json only.
  --reset    Delete library.json and exit.
  (default)  Same as --full.

Phases:
  1. Filesystem + NFO scan — builds library.json, writes after each folder.
  2. Seerr enrichment — fetches streaming providers, writes after each folder.
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
from collections import Counter, defaultdict
from logging.handlers import RotatingFileHandler
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
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
SCORE_DEFAULTS_PATH = os.environ.get("SCORE_DEFAULTS_PATH", "/app/score_defaults.json")
SECRETS_PATH  = os.environ.get("SECRETS_PATH",  "/app/.secrets")
SCAN_LOCK_PATH = os.environ.get("SCAN_LOCK_PATH", "/data/.scan.lock")
PROVIDERS_MAPPING_SOURCE_PATH = os.environ.get("PROVIDERS_MAPPING_SOURCE_PATH", "/usr/share/nginx/html/providers_mapping.json")
PROVIDERS_MAPPING_RUNTIME_PATH = os.environ.get("PROVIDERS_MAPPING_RUNTIME_PATH", "/data/providers_mapping.json")
PROVIDERS_LOGO_PATH = os.environ.get("PROVIDERS_LOGO_PATH", "/usr/share/nginx/html/providers_logo.json")
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
            }

        def build_quality_block(
            *,
            video_resolution: int,
            video_codec: int,
            video_hdr: int,
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
            }

        def get_builtin_score_defaults() -> dict:
            return {
                "weights": {"video": 50, "audio": 20, "languages": 15, "size": 15},
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
# Seerr — providers only
# ---------------------------------------------------------------------------

_JSR_NOT_CONFIGURED = object()  # sentinel: Seerr not configured/disabled
_JSR_ERROR          = object()  # sentinel: HTTP/network error (transient — do not mark providers_fetched)
_JSR_NOT_FOUND      = object()  # sentinel: HTTP 500 "Unable to retrieve" — item not in Seerr


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
    for key in ("seerr", "jellyseerr"):
        jsr = safe_payload.get(key)
        if isinstance(jsr, dict) and "apikey" in jsr:
            jsr["apikey"] = "***"
    return safe_payload


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
    """Read Seerr settings. API key comes from /app/.secrets, rest from config.json."""
    cfg = load_config()
    jsr = cfg.get("seerr", {}) or cfg.get("jellyseerr", {})
    secrets = _load_secrets()
    secrets, secrets_changed = _normalize_seerr_secret_keys(secrets)
    if secrets_changed:
        _save_secrets(secrets)
    # Prefer secrets file for apikey; fall back to config.json (legacy / migration)
    apikey = secrets.get("seerr_apikey") or secrets.get("jellyseerr_apikey") or jsr.get("apikey", "")
    return {
        "enabled": jsr.get("enabled", False),
        "url":     jsr.get("url", "").rstrip("/"),
        "apikey":  apikey,
    }


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
    """Bootstrap /data providers mapping once: copy bundled file only if runtime file is absent."""
    runtime_path = Path(PROVIDERS_MAPPING_RUNTIME_PATH)
    if runtime_path.exists():
        return
    try:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        source_path = Path(PROVIDERS_MAPPING_SOURCE_PATH)
        if source_path.exists():
            shutil.copyfile(source_path, runtime_path)
        else:
            runtime_path.write_text("{}", encoding="utf-8")
    except Exception as e:
        log.warning(f"[providers] Could not bootstrap runtime mapping file: {e}")


def _load_runtime_provider_mapping() -> dict:
    _ensure_runtime_provider_mapping()
    try:
        with open(PROVIDERS_MAPPING_RUNTIME_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception as e:
        log.warning(f"[providers] Could not read runtime mapping file: {e}")
    return {}


def _save_runtime_provider_mapping(mapping: dict) -> None:
    try:
        path = Path(PROVIDERS_MAPPING_RUNTIME_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"[providers] Could not write runtime mapping file: {e}")


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


_fetch_providers_sampled = False  # log raw response once per run

# Sentinel returned when Seerr call fails (vs [] = success with no FR providers)
_FETCH_ERROR    = object()
_ENRICH_WORKERS = 5  # ThreadPoolExecutor workers for Seerr enrichment
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
                     each dict entry: {raw_name, logo, logo_url}
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
                logo_url  = raw_logo
                logo      = None  # relative path unknown
            elif raw_logo:
                logo_url  = f"https://image.tmdb.org/t/p/w45{raw_logo}"
                logo      = raw_logo
            else:
                log.warning(f"[providers] No logo field for {raw_name!r} in {media}/{media_id}, raw={p}")
                logo_url = logo = None
            result.append({"raw_name": raw_name, "logo": logo, "logo_url": logo_url})
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
    SEERR_URL, etc.) and populate config.json if the corresponding fields
    are still at their defaults/empty. Idempotent — safe to call every startup.
    """
    cfg = load_config()
    changed = False

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
    secrets = _load_secrets()
    secrets, secrets_changed = _normalize_seerr_secret_keys(secrets)
    if secrets_changed:
        _save_secrets(secrets)
    if env_apikey and not secrets.get("seerr_apikey") and not jsr.get("apikey"):
        secrets["seerr_apikey"] = env_apikey
        _save_secrets(secrets)
        log.info("[migrate] Seerr API key migrated to /app/.secrets")
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

    ui_cfg = cfg.setdefault("ui", {})
    if "synopsis_on_hover" not in ui_cfg:
        ui_cfg["synopsis_on_hover"] = False
        changed = True

    cfg, score_changed, score_status = normalize_score_configuration_sections(cfg)
    changed = changed or score_changed
    if not score_status.get("weights_valid", False):
        log.warning(
            "[score] Weight total is %s (expected 100) in effective score config",
            score_status.get("weights_total"),
        )

    if changed:
        save_config(cfg)
        log.info("[MIGRATION] Env vars migrated to config.json")
    # Bootstrap runtime providers mapping once (non-destructive).
    _ensure_runtime_provider_mapping()


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


_TV_SKIP_NFO = {"tvshow.nfo", "season.nfo"}
_TV_SE_EP_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
_TV_SEASON_HINT_RE = re.compile(r"(?:season|saison)[\s._-]*(\d{1,2})", re.IGNORECASE)


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
    match = _TV_SE_EP_RE.search(path_like)
    if match:
        return _safe_int(match.group(1)), _safe_int(match.group(2))
    season_hint = _TV_SEASON_HINT_RE.search(path_like)
    if season_hint:
        return _safe_int(season_hint.group(1)), None
    return None, None


def _build_episode_dedupe_key(season_num: int | None, episode_num: int | None, fallback: str) -> str:
    if season_num is not None and episode_num is not None:
        return f"s{season_num:02d}e{episode_num:03d}"
    return fallback.casefold()


def _episode_metadata_completeness(ep: dict) -> int:
    score = 0
    for key in (
        "resolution",
        "width",
        "height",
        "codec",
        "audio_codec_raw",
        "audio_codec",
        "audio_languages",
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


def _parse_episode_nfo_metadata(nfo_path: Path) -> dict | None:
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
    if season_num is None:
        season_num = 1

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
        fallback=str(nfo_path.name),
    )
    return {
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
        "audio_languages": langs,
        "audio_languages_simple": audio_languages_simple,
        "hdr": hdr,
        "hdr_type": hdr_type,
        "runtime_min": runtime_min,
    }


def _parse_episode_files_without_nfo(series_dir: Path, existing_keys: set[str]) -> list[dict]:
    parsed: list[dict] = []
    try:
        files = sorted(
            p for p in series_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS and not p.name.startswith("._")
        )
    except Exception:
        return parsed

    for video in files:
        season_num, episode_num = _extract_season_episode_from_name(str(video))
        if season_num is None:
            season_num = 1
        key = _build_episode_dedupe_key(
            season_num,
            episode_num,
            fallback=str(video.relative_to(series_dir)),
        )
        if key in existing_keys:
            continue
        try:
            size_b = int(video.stat().st_size)
        except Exception:
            size_b = 0
        parsed.append({
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
            "audio_languages": [],
            "audio_languages_simple": None,
            "hdr": False,
            "hdr_type": None,
            "runtime_min": None,
        })
    return parsed


def collect_series_episode_metadata(series_dir: Path) -> list[dict]:
    deduped: dict[str, dict] = {}
    try:
        nfo_candidates = sorted(
            p for p in series_dir.rglob("*.nfo")
            if p.is_file() and p.name.lower() not in _TV_SKIP_NFO and not p.name.startswith("._")
        )
    except Exception:
        nfo_candidates = []

    for nfo_path in nfo_candidates:
        ep = _parse_episode_nfo_metadata(nfo_path)
        if not isinstance(ep, dict):
            continue
        key = ep["dedupe_key"]
        deduped[key] = _prefer_episode_metadata(deduped.get(key), ep)

    for ep in _parse_episode_files_without_nfo(series_dir, set(deduped.keys())):
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


def aggregate_season_metadata(
    season_number: int,
    season_episodes: list[dict],
    *,
    episodes_expected: int | None = None,
    score_config: dict | None = None,
) -> dict:
    episodes_found = len(season_episodes)
    dominant_resolution = _dominant_value([e.get("resolution") for e in season_episodes])
    dominant_width = _dominant_value([e.get("width") for e in season_episodes])
    dominant_height = _dominant_value([e.get("height") for e in season_episodes])
    dominant_codec = _dominant_value([e.get("codec") for e in season_episodes])
    dominant_audio_raw = _dominant_value([e.get("audio_codec_raw") for e in season_episodes])
    dominant_audio = _dominant_value([e.get("audio_codec") for e in season_episodes])
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
    if _is_unknown_sentinel(audio_languages_simple):
        audio_languages_simple = None

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
    quality = compute_quality(season_item_for_score, score_config) if isinstance(score_config, dict) else compute_quality(season_item_for_score)

    return {
        "season": int(season_number),
        "episodes_found": int(episodes_found),
        "episodes_expected": int(episodes_expected) if isinstance(episodes_expected, int) and episodes_expected >= 0 else None,
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
        "runtime_min_total": runtime_min_total,
        "runtime_min_avg": runtime_min_avg,
        "size_b": size_b,
        "size": format_size(size_b),
        "quality": quality,
    }


def aggregate_series_metadata(
    series_episodes: list[dict],
    *,
    score_config: dict | None = None,
    season_expected_counts: dict[int, int] | None = None,
) -> dict:
    by_season: dict[int, list[dict]] = defaultdict(list)
    for ep in series_episodes:
        season_num = _safe_int(ep.get("season"), 1)
        if season_num is None:
            season_num = 1
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
                episodes_expected=expected.get(season_num),
                score_config=score_config,
            )
        )

    all_resolution = [e.get("resolution") for e in series_episodes]
    all_width = [e.get("width") for e in series_episodes]
    all_height = [e.get("height") for e in series_episodes]
    all_codec = [e.get("codec") for e in series_episodes]
    all_audio_raw = [e.get("audio_codec_raw") for e in series_episodes]
    all_audio = [e.get("audio_codec") for e in series_episodes]
    all_hdr_type = [e.get("hdr_type") for e in series_episodes]
    known_runtimes = [int(e["runtime_min"]) for e in series_episodes if isinstance(e.get("runtime_min"), int) and e.get("runtime_min") > 0]

    resolution = _dominant_value(all_resolution)
    width = _dominant_value(all_width)
    height = _dominant_value(all_height)
    codec = _dominant_value(all_codec)
    audio_codec_raw = _dominant_value(all_audio_raw)
    audio_codec = _dominant_value(all_audio)
    hdr_type = _dominant_value(all_hdr_type)
    hdr = bool(hdr_type) or any(bool(e.get("hdr")) for e in series_episodes)

    runtime_min = int(round(sum(known_runtimes) / len(known_runtimes))) if known_runtimes else None
    episode_count = len(series_episodes)
    season_count = len(seasons)
    size_b = int(sum(int(e.get("size_b") or 0) for e in series_episodes))

    audio_languages = _aggregate_audio_languages_from_episodes(series_episodes)
    audio_languages_simple = simplify_audio_languages(audio_languages)
    if _is_unknown_sentinel(audio_languages_simple):
        audio_languages_simple = None

    series_item_for_score = {
        "type": "tv",
        "resolution": resolution,
        "width": width,
        "height": height,
        "codec": codec,
        "audio_codec_raw": audio_codec_raw,
        "audio_codec": audio_codec,
        "audio_languages": audio_languages,
        "audio_languages_simple": audio_languages_simple,
        "hdr": hdr,
        "hdr_type": hdr_type,
        "size_b": size_b,
    }
    quality = compute_quality(series_item_for_score, score_config) if isinstance(score_config, dict) else compute_quality(series_item_for_score)

    return {
        "seasons": seasons,
        "season_count": season_count,
        "episode_count": episode_count,
        "size_b": size_b,
        "resolution": resolution,
        "width": width,
        "height": height,
        "runtime_min": runtime_min,
        "codec": codec,
        "audio_codec_raw": audio_codec_raw,
        "audio_codec": audio_codec,
        "audio_languages": audio_languages,
        "audio_languages_simple": audio_languages_simple,
        "hdr": hdr,
        "hdr_type": hdr_type,
        "quality": quality,
    }


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
        series_item["complete"] = None
        return series_item

    episodes_expected = expected_counts.get("episodes_expected")
    if isinstance(episodes_expected, int) and episodes_expected >= 0:
        series_item["episodes_expected"] = episodes_expected
    else:
        series_item["episodes_expected"] = None

    if isinstance(series_item.get("episode_count"), int) and isinstance(series_item.get("episodes_expected"), int):
        series_item["complete"] = bool(series_item["episode_count"] == series_item["episodes_expected"])
    else:
        series_item["complete"] = None

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
    },
    "folders": [],
    "enable_movies": True,
    "enable_series": True,
    "seerr": {
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
    "score": {
        "enabled": False,
    },
    "score_configuration": get_builtin_score_defaults(),
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = copy.deepcopy(_DEFAULT_CONFIG)
    if isinstance(cfg, dict):
        cfg, seerr_changed = normalize_seerr_config(cfg)
        cfg, changed, _ = normalize_score_configuration_sections(cfg)
        if seerr_changed or changed:
            save_config(cfg)
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


def _is_inventory_enabled(cfg: dict | None) -> bool:
    system = (cfg or {}).get("system") or {}
    return system.get("inventory_enabled") is True


def _is_score_enabled(cfg: dict | None) -> bool:
    score = (cfg or {}).get("score")
    if isinstance(score, dict) and isinstance(score.get("enabled"), bool):
        return score.get("enabled") is True
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


def load_score_defaults() -> dict:
    try:
        with open(SCORE_DEFAULTS_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception as e:
        log.warning(f"[score] Could not load score defaults from {SCORE_DEFAULTS_PATH}: {e}")
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
    """Write current library state to JSON (used for incremental per-folder writes)."""
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
        q_audio = _safe_int(q.get("audio"), 0) or 0
        q_languages = _safe_int(q.get("languages"), 0) or 0
        q_size = _safe_int(q.get("size"), 0) or 0
        normalized_q = {
            "video_details": vd,
            "video": int(vd["resolution"] + vd["codec"] + vd["hdr"]),
            "audio": q_audio,
            "languages": q_languages,
            "size": q_size,
            "video_w": _safe_int(q.get("video_w"), _safe_int(q.get("video"), 0) or 0) or 0,
            "audio_w": _safe_int(q.get("audio_w"), q_audio) or 0,
            "languages_w": _safe_int(q.get("languages_w"), q_languages) or 0,
            "size_w": _safe_int(q.get("size_w"), q_size) or 0,
        }
        normalized_q["score"] = int(
            normalized_q["video_w"] + normalized_q["audio_w"] + normalized_q["languages_w"] + normalized_q["size_w"]
        )
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
                sq_audio = _safe_int(sq2.get("audio"), 0) or 0
                sq_languages = _safe_int(sq2.get("languages"), 0) or 0
                sq_size = _safe_int(sq2.get("size"), 0) or 0
                normalized_sq = {
                    "video_details": vd2,
                    "video": int(vd2["resolution"] + vd2["codec"] + vd2["hdr"]),
                    "audio": sq_audio,
                    "languages": sq_languages,
                    "size": sq_size,
                    "video_w": _safe_int(sq2.get("video_w"), _safe_int(sq2.get("video"), 0) or 0) or 0,
                    "audio_w": _safe_int(sq2.get("audio_w"), sq_audio) or 0,
                    "languages_w": _safe_int(sq2.get("languages_w"), sq_languages) or 0,
                    "size_w": _safe_int(sq2.get("size_w"), sq_size) or 0,
                }
                normalized_sq["score"] = int(
                    normalized_sq["video_w"] + normalized_sq["audio_w"] + normalized_sq["languages_w"] + normalized_sq["size_w"]
                )
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
    series_agg: dict = {}
    expected_counts: dict | None = None
    if is_tv:
        tvshow_nfo = media_dir / "tvshow.nfo"
        if tvshow_nfo.exists():
            nfo_meta = parse_tvshow_nfo(tvshow_nfo)
        series_episodes = collect_series_episode_metadata(media_dir)
        series_agg = aggregate_series_metadata(
            series_episodes,
            score_config=score_config if isinstance(score_config, dict) else None,
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
                        score_config=score_config if isinstance(score_config, dict) else None,
                        season_expected_counts=season_expected,
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
        "tvdb_id":           tvdb_id,
        "resolution":        (series_agg.get("resolution") if is_tv else nfo_meta.get("resolution")) or prev.get("resolution"),
        "width":             (series_agg.get("width") if is_tv else nfo_meta.get("width")) or prev.get("width"),
        "height":            (series_agg.get("height") if is_tv else nfo_meta.get("height")) or prev.get("height"),
        "plot":              nfo_meta.get("plot")        or prev.get("plot"),
        "runtime_min":       (series_agg.get("runtime_min") if is_tv else nfo_meta.get("runtime_min")) or prev.get("runtime_min"),
        "season_count":      (series_agg.get("season_count") if is_tv else nfo_meta.get("season_count")) or prev.get("season_count"),
        "episode_count":     (series_agg.get("episode_count") if is_tv else nfo_meta.get("episode_count")) or prev.get("episode_count"),
        "codec":             (series_agg.get("codec") if is_tv else nfo_meta.get("codec")) or prev.get("codec"),
        "audio_codec_raw":   (series_agg.get("audio_codec_raw") if is_tv else nfo_meta.get("audio_codec_raw")) or prev.get("audio_codec_raw"),
        "audio_codec":       (series_agg.get("audio_codec") if is_tv else nfo_meta.get("audio_codec")) or prev.get("audio_codec"),
        "audio_languages":   (series_agg.get("audio_languages") if is_tv else nfo_meta.get("audio_languages")) or prev.get("audio_languages") or [],
        "audio_languages_simple": (series_agg.get("audio_languages_simple") if is_tv else nfo_meta.get("audio_languages_simple")) or prev.get("audio_languages_simple") or simplify_audio_languages((series_agg.get("audio_languages") if is_tv else nfo_meta.get("audio_languages")) or prev.get("audio_languages") or []),
        "hdr":               hdr_current,
        "hdr_type":          hdr_type_value,
        # Enriched fields preserved from previous library.json — overwritten by full scan phases
        "providers":         _normalize_providers(prev.get("providers")),
        "providers_fetched": prev.get("providers_fetched", False),
    }
    if is_tv:
        item["size_b"] = int(series_agg.get("size_b") or size_b)
        item["size"] = format_size(item["size_b"])
        item["seasons"] = series_agg.get("seasons") or []
        item["episodes_expected"] = None
        item["complete"] = None
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
                item["quality"] = q  # preserved during quick scan; overwritten by phase 3
    if _is_unknown_sentinel(item.get("audio_codec")):
        item["audio_codec"] = None
    if _is_unknown_sentinel(item.get("audio_languages_simple")):
        item["audio_languages_simple"] = None
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

    # Preserve previous file content for backward-compatible partial scans
    prev_data: dict = {}
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as _f:
            prev_data = json.load(_f)
    except Exception:
        pass

    items = []
    scanned_paths = set()
    tv_series_scanned = 0
    tv_episodes_scanned = 0
    tv_series_with_seerr_counts = 0

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
            item = scan_media_item(
                media_dir,
                root,
                cat,
                prev,
                enable_score=score_enabled,
                score_config=effective_score_config,
                jsr_for_counts=jsr_for_counts if cat["type"] == "tv" and seerr_counts_active else None,
            )
            items.append(item)
            tv_series_scanned += int(item.get("_scan_tv_series_scanned") or 0)
            tv_episodes_scanned += int(item.get("_scan_tv_episodes_scanned") or 0)
            tv_series_with_seerr_counts += int(1 if item.get("_scan_tv_seerr_counts") else 0)
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
    try:
        mapping_added = _upsert_runtime_provider_mapping(items)
        if mapping_added:
            log.info(f"[SCAN] providers_mapping updated (+{mapping_added} raw provider(s))")
    except Exception as e:
        log.warning(f"[SCAN] providers_mapping update failed: {e}")

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
    log.info(
        f"[SCAN] TV scan summary: {tv_series_scanned} series analyzed / {tv_episodes_scanned} episodes scanned"
    )
    if seerr_counts_active:
        log.info(
            f"[SCAN] TV Seerr expected-count summary: {tv_series_with_seerr_counts}/{tv_series_scanned} series enriched"
        )

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
# ENRICH (providers via Seerr)
# ---------------------------------------------------------------------------

def run_enrich(force: bool = False, only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    label = "force" if force else "missing only"
    scope = f" [category: {only_category}]" if only_category else ""
    log.info(f"[SCAN] ── Phase 2 : Seerr enrichment ({label}){scope} ──")

    jsr = _jsr_cfg()
    if not jsr["enabled"]:
        log.warning("[SCAN] Seerr disabled in config.json — skipping enrichment")
        return
    if not jsr["url"] or not jsr["apikey"]:
        log.warning("[SCAN] Seerr URL or apikey missing in config.json — skipping enrichment")
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
        # Enrichment can run from IDs or fallback search (requires title).
        # Keep this broad even in force mode to avoid skipping valid items.
        if not item.get("title") and not item.get("tmdb_id") and not item.get("tvdb_id"):
            return False
        if force:
            return True
        return not item.get("providers_fetched")

    to_enrich = [i for i in items if needs_enrich(i)]
    skipped   = len(items) - len(to_enrich)
    log.info(f"[SCAN] Seerr enrichment: {len(to_enrich)} items to process, {skipped} skipped ({_ENRICH_WORKERS} workers)")

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
                            log.info(
                                f"[enrich-tv] Resolved TVDB id via search for {item.get('title')!r}: {item.get('tvdb_id')} -> {resolved_tvdb}"
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
                            log.info(
                                f"[enrich-movie] Resolved TMDB id via search for {item.get('title')!r}: {item.get('tmdb_id')} -> {resolved_tmdb}"
                            )
                            item["tmdb_id"] = str(resolved_tmdb)
                            providers = fetch_providers(item["tmdb_id"], False, jsr)
        except Exception as e:
            log.warning(
                f"[enrich] Unexpected exception id={item.get('tvdb_id') if is_tv else item.get('tmdb_id')} "
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
        log.info(f"[SCAN] Enriching folder [{cat_folder}] ({cat_idx}/{n_enrich_cats}) — {len(cat_items)} item(s)")
        with ThreadPoolExecutor(max_workers=_ENRICH_WORKERS) as pool:
            futures = {pool.submit(_enrich_one, item): item for item in cat_items}
            for future in as_completed(futures):
                item, providers = future.result()
                if providers is _JSR_NOT_FOUND:
                    # Item not in Seerr — mark as fetched (no FR providers)
                    item["providers"]         = []
                    item["providers_fetched"] = True
                    not_found_count += 1
                    not_found_ids.append(item.get("tvdb_id", "?") if item.get("type") == "tv" else item.get("tmdb_id", "?"))
                    continue
                if providers is _FETCH_ERROR:
                    # Seerr unreachable — leave providers_fetched False, retry next run
                    failed_count += 1
                    failed_ids.append(item.get("tvdb_id", "?") if item.get("type") == "tv" else item.get("tmdb_id", "?"))
                    continue
                # Store cleaned raw provider names from Seerr.
                item["providers"] = _normalize_providers([p["raw_name"] for p in (providers or [])])
                item["providers_fetched"] = True
                enriched += 1
                total_providers = len(providers or [])
                log.debug(f"  {item['title']} — {total_providers} provider(s)")

        _sanitize_library_document(data)
        write_json(data, OUTPUT_PATH)
        log.info(f"[SCAN] Folder [{cat_folder}] done — {len(cat_items)} item(s) enriched")

    elapsed = time.monotonic() - _t0
    if not_found_count:
        ids_str = ", ".join(str(i) for i in not_found_ids[:20])
        suffix  = f" … (+{len(not_found_ids)-20} more)" if len(not_found_ids) > 20 else ""
        log.info(f"[SCAN] {not_found_count} item(s) not found in Seerr — ids: {ids_str}{suffix}")
    if failed_count:
        ids_str = ", ".join(str(i) for i in failed_ids[:20])
        suffix  = f" … (+{len(failed_ids)-20} more)" if len(failed_ids) > 20 else ""
        log.warning(f"[SCAN] {failed_count} item(s) not enriched (Seerr error) — ids: {ids_str}{suffix}")
    parts = [f"{enriched} OK"]
    if not_found_count: parts.append(f"{not_found_count} not found in Seerr")
    if failed_count:    parts.append(f"{failed_count} errors")
    log.info(f"[SCAN] Phase 2 completed in {elapsed:.1f}s — {' / '.join(parts)}")


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
                "audio_languages": item.get("audio_languages") or [],
                "audio_languages_simple": item.get("audio_languages_simple"),
                "hdr": item.get("hdr"),
                "hdr_type": item.get("hdr_type"),
                "size_b": item.get("size_b"),
            }
            item["quality"] = compute_quality(item_for_score, score_config)
        else:
            item["quality"] = compute_quality(item, score_config)
        item.pop("score", None)
        updated += 1
    return updated


def recompute_scores_only(score_config: dict | None = None) -> int:
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.error(f"[score] Cannot read {OUTPUT_PATH}: {e}")
        return 0

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return 0

    _, effective_score_config, _ = get_effective_score_config()
    if isinstance(score_config, dict):
        effective_score_config, _ = validate_score_config(score_config, defaults=load_score_defaults())

    recalculated = recompute_scores_for_items(items, effective_score_config)
    write_json(data, OUTPUT_PATH)
    return recalculated


def run_scoring(only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    cfg = load_config()
    if not _is_score_enabled(cfg):
        log.info("[SCAN] Scoring disabled (score.enabled=false) — skipping phase 3")
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

    _, effective_score_config, _ = get_effective_score_config(cfg)

    scored_total = 0
    sorted_score_cats = sorted(by_cat.items())
    n_score_cats = len(sorted_score_cats)
    for cat_idx, (cat_name, cat_items) in enumerate(sorted_score_cats, 1):
        cat_folder = cat_folder_by_name.get(cat_name, cat_name)
        log.info(f"[SCAN] Scoring folder [{cat_folder}] ({cat_idx}/{n_score_cats}) — {len(cat_items)} item(s)")
        scored_total += recompute_scores_for_items(cat_items, effective_score_config)
        _sanitize_library_document(data)
        write_json(data, OUTPUT_PATH)
        log.info(f"[SCAN] Folder [{cat_folder}] scored")

    elapsed = time.monotonic() - _t0
    log.info(f"[SCAN] Phase 3 completed — {scored_total} item(s) scored in {elapsed:.1f}s")


def run_score_only() -> int:
    with _scan_lock("score_only"):
        _t0 = time.monotonic()
        log.info("[SCAN] ── Score-only recompute ───────────────────────────")
        defaults, effective_score_config, _ = get_effective_score_config()
        del defaults  # only used for lazy bootstrap and validation side-effects
        recalculated = recompute_scores_only(effective_score_config)
        elapsed = time.monotonic() - _t0
        log.info(f"[SCAN] Score-only completed — {recalculated} item(s) scored in {elapsed:.1f}s")
        return recalculated


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
_PUBLIC_POST = {"/api/auth", "/api/logout"}

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

VALID_MODES = {"quick", "full", "default", "score_only"}


def _scanner_cmd(mode: str) -> list[str]:
    base = [sys.executable, __file__]
    if mode == "quick": return base + ["--quick"]
    if mode == "full":  return base + ["--full"]
    if mode == "score_only": return base + ["--score-only"]
    return base + ["--full"]  # default → full


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

    def _json(self, code, data, *, set_cookie=None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        """Return True if request carries a valid mml_session cookie."""
        pw = os.environ.get("APP_PASSWORD", "")
        if not pw:
            return True
        token = self._session_token()
        if token and token in _valid_sessions:
            return True
        return False

    def _session_token(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            name, _, val = part.strip().partition("=")
            if name == "mml_session" and val:
                return val
        return None

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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
            required = bool(pw)
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
            if _is_scan_locked():
                self._json(409, self._scan_running_error_payload())
                return

            defaults = load_score_defaults()
            valid, err = validate_score_payload(payload, defaults, strict=True)
            if not valid:
                self._json(400, err)
                return

            cfg = load_config()
            merged = merge_score_config(defaults, payload.get("score"))
            effective, _ = validate_score_config(merged, defaults=defaults)
            cfg["score_configuration"] = effective
            cfg, score_changed, _ = normalize_score_configuration_sections(cfg)
            if score_changed:
                log.info("[score] Score configuration normalized during PUT /api/settings/score")
            save_config(cfg)

            recalculated = 0
            mode = "config_only"
            if _is_score_enabled(cfg):
                try:
                    recalculated = run_score_only()
                    mode = "score_only"
                except BlockingIOError:
                    self._json(409, self._scan_running_error_payload())
                    return
            _, effective_after, status_after = get_effective_score_config(cfg)
            status_after = dict(status_after)
            status_after.update({
                "recalculated_items": recalculated,
                "mode": mode,
            })
            self._json(200, {
                "ok": True,
                "enabled": _is_score_enabled(cfg),
                "effective": effective_after,
                "status": status_after,
            })
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
            if _is_scan_locked():
                self._json(409, self._scan_running_error_payload())
                return

            defaults = load_score_defaults()
            cfg = load_config()
            cfg["score_configuration"] = copy.deepcopy(defaults)
            cfg, score_changed, _ = normalize_score_configuration_sections(cfg)
            if score_changed:
                log.info("[score] Score configuration normalized during POST /api/settings/score/reset")
            save_config(cfg)

            recalculated = 0
            mode = "config_only"
            if _is_score_enabled(cfg):
                try:
                    recalculated = run_score_only()
                    mode = "score_only"
                except BlockingIOError:
                    self._json(409, self._scan_running_error_payload())
                    return
            _, effective_after, status_after = get_effective_score_config(cfg)
            status_after = dict(status_after)
            status_after.update({
                "recalculated_items": recalculated,
                "mode": mode,
            })
            self._json(200, {
                "ok": True,
                "enabled": _is_score_enabled(cfg),
                "effective": effective_after,
                "status": status_after,
            })
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
        path = self.path.split("?")[0]
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
                cookie = f"mml_session={token}; HttpOnly; Path=/; SameSite=Lax"
                self._json(200, {"ok": True}, set_cookie=cookie)
            else:
                self._json(200, {"ok": False})
            return
        if path == "/api/logout":
            token = self._session_token()
            if token:
                _valid_sessions.discard(token)
            expired = "mml_session=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self._json(200, {"ok": True}, set_cookie=expired)
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
            system_payload = payload.get("system")
            if isinstance(system_payload, dict) and "enable_score" in system_payload:
                score_payload = payload.setdefault("score", {})
                if isinstance(score_payload, dict):
                    score_payload["enabled"] = system_payload.get("enable_score") is True
                system_payload.pop("enable_score", None)
                if not system_payload:
                    payload.pop("system", None)
            cfg = load_config()
            safe_payload = _redact_config_payload(payload)
            log.info("[config] Received: %s", json.dumps(safe_payload))

            secrets_before = _load_secrets()
            secrets_after = dict(secrets_before)
            jsr_key_action = _apply_seerr_secret_update(payload, secrets_after)

            merged = deep_merge(cfg, payload)
            merged, _ = _ensure_needs_onboarding(merged, config_exists=True)
            normalize_folder_enabled_flags(merged, drop_visible=True)
            merged, _ = normalize_seerr_config(merged)
            merged, _, _ = normalize_score_configuration_sections(merged)
            # Ensure apikey never persists in config.json
            if "seerr" in merged:
                merged["seerr"].pop("apikey", None)
                merged["seerr"].pop("clear_apikey", None)
            merged.pop("jellyseerr", None)
            save_config(merged)
            if secrets_after != secrets_before:
                _save_secrets(secrets_after)

            if jsr_key_action == "updated":
                log.info("[config] Seerr API key updated")
            elif jsr_key_action == "preserved":
                log.info("[config] Seerr API key preserved")
            elif jsr_key_action == "cleared":
                log.info("[config] Seerr API key cleared (explicit request)")
            else:
                log.info("[config] Seerr API key not modified")

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
        help="All 4 phases: filesystem scan + Seerr + scoring + inventory (default)")
    mode_group.add_argument("--score-only", action="store_true",
        help="Recompute score fields from existing library.json only")
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
    elif args.score_only:
        lock_mode = "score_only"
        mode_label = "--score-only"
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
            elif args.score_only:
                run_score_only()
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
