#!/usr/bin/env python3
"""
Media Library Scanner
Scans LIBRARY_PATH and generates a library.json file.

Modes:
  --quick              Filesystem scan only (reads .nfo, resolution, local poster).
  --enrich             Filesystem scan + fetch streaming providers via Jellyseerr (default).
  --full               Filesystem scan + force re-fetch ALL providers from Jellyseerr.
  --reset              Delete library.json and exit.
  (default)            Same as --enrich.

Filters (combinable with any mode):
  --category <n>       Restrict scan to a single category name.
"""

import argparse
import copy
import http.server
import json
import logging
from collections import defaultdict
from logging.handlers import RotatingFileHandler
import os
import re
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

from inventory_helpers import merge_inventory_documents

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LIBRARY_PATH  = os.environ.get("LIBRARY_PATH",  "/mnt/media/library")
OUTPUT_PATH   = os.environ.get("OUTPUT_PATH",   "/data/library.json")
INVENTORY_OUTPUT_PATH = os.environ.get("INVENTORY_OUTPUT_PATH", "/data/library_inventory.json")
CONFIG_PATH   = os.environ.get("CONFIG_PATH",   "/data/config.json")
SECRETS_PATH  = os.environ.get("SECRETS_PATH",  "/app/.secrets")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
# Apply log_level from config.json if available (may be adjusted later via API too)
try:
    with open(os.environ.get("CONFIG_PATH", "/data/config.json"), encoding="utf-8") as _cfg_f:
        _cfg_loglevel = json.load(_cfg_f).get("system", {}).get("log_level", "INFO")
    logging.getLogger().setLevel(getattr(logging, _cfg_loglevel.upper(), logging.INFO))
except Exception:
    pass
log = logging.getLogger("scanner")

# Rotating file log: 5MB max, keep 3 backups — in /data/ so it's accessible from host
_log_file = os.environ.get("LOG_PATH", "/data/scanner.log")
try:
    _fh = RotatingFileHandler(_log_file, maxBytes=5*1024*1024, backupCount=3)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(_fh)
except Exception:
    pass  # log file not writable in some environments


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def classify_resolution(width: int, height: int) -> str:
    if width >= 3840 or height >= 2160:
        return "4K"
    if width >= 1280 or height >= 720:
        if height >= 1080 or width >= 1920:
            return "1080p"
        return "720p"
    return "SD"


# ---------------------------------------------------------------------------
# NFO parsing
# ---------------------------------------------------------------------------

CODEC_CANONICAL = {
    "hevc": "H.265", "h265": "H.265", "x265": "H.265",
    "h264": "H.264", "x264": "H.264", "avc":  "H.264",
    "av1":  "AV1",
    "mpeg2video": "MPEG-2", "mpeg2": "MPEG-2",
    "mpeg4": "MPEG-4",
    "vp9":  "VP9",
    "vc1":  "VC-1",
}

def normalize_codec(raw: str | None) -> str | None:
    if not raw:
        return None
    return CODEC_CANONICAL.get(raw.lower().strip()) or raw.upper().strip()


def _load_audiocodec_mapping() -> dict:
    """Load audiocodec_mapping.json from image path or dev-local fallback."""
    paths = [
        "/usr/share/nginx/html/audiocodec_mapping.json",
        os.path.join(os.path.dirname(__file__), "../app/audiocodec_mapping.json"),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                log.debug(f"[audiocodec] Mapping loaded from {p} ({len(data.get('priority', []))} entries)")
                return data
            except Exception as e:
                log.warning(f"[audiocodec] Failed to load {p}: {e}")
    log.warning("[audiocodec] audiocodec_mapping.json not found — all codecs will be UNKNOWN")
    return {"priority": [], "mapping": {}, "fallback": {"normalized": "UNKNOWN", "display": "Unknown"}}


AUDIOCODEC_MAPPING = _load_audiocodec_mapping()

# ---------------------------------------------------------------------------
# Audio language normalisation
# ---------------------------------------------------------------------------

ISO_639_1_TO_2: dict[str, str] = {
    'fr': 'fra', 'en': 'eng', 'de': 'deu', 'es': 'spa',
    'it': 'ita', 'ja': 'jpn', 'zh': 'zho', 'ko': 'kor',
    'pt': 'por', 'ru': 'rus', 'ar': 'ara', 'nl': 'nld',
    'pl': 'pol', 'sv': 'swe', 'da': 'dan', 'fi': 'fin',
    'nb': 'nob', 'tr': 'tur', 'cs': 'ces', 'hu': 'hun',
}

# Deprecated/bibliographic ISO 639-2 aliases → canonical terminiologic code
_ISO_639_2_ALIASES: dict[str, str] = {
    'fre': 'fra', 'ger': 'deu', 'chi': 'zho', 'cze': 'ces', 'dut': 'nld', 'rum': 'ron',
}

_KNOWN_ISO_639_2: frozenset[str] = frozenset({
    'fra', 'eng', 'deu', 'spa', 'ita', 'jpn', 'zho', 'kor', 'por', 'rus',
    'ara', 'nld', 'pol', 'swe', 'dan', 'fin', 'nor', 'nob', 'gsw', 'tur', 'ces', 'hun',
    'ron', 'bul', 'hrv', 'srp', 'ukr', 'heb', 'cat', 'lat', 'hin', 'ben',
    'vie', 'ind', 'may', 'tha', 'ell', 'slk', 'slv', 'est', 'lav', 'lit',
    'isl', 'mkd', 'aze', 'geo', 'arm',
})

LANGUAGE_NAME_ALIASES: dict[str, str] = {
    'french': 'fra', 'francais': 'fra', 'français': 'fra',
    'english': 'eng',
    'japanese': 'jpn',
    'german': 'deu',
    'spanish': 'spa',
    'italian': 'ita',
}

RELEASE_LANGUAGE_ALIASES: dict[str, str] = {
    'vf': 'fra', 'vff': 'fra', 'truefrench': 'fra',
    'jp': 'jpn',
}

SPECIAL_LANGUAGE_MARKERS: frozenset[str] = frozenset({'vo', 'multi'})

LANGUAGE_ALIASES_TO_CANONICAL: dict[str, str] = {
    **{k: v for k, v in ISO_639_1_TO_2.items()},
    **{k: v for k, v in _ISO_639_2_ALIASES.items()},
    **{k: _ISO_639_2_ALIASES.get(k, k) for k in _KNOWN_ISO_639_2},
    **LANGUAGE_NAME_ALIASES,
    **RELEASE_LANGUAGE_ALIASES,
}

_SEGMENTABLE_ALIASES: tuple[str, ...] = tuple(
    sorted((k for k in LANGUAGE_ALIASES_TO_CANONICAL.keys() if len(k) >= 3), key=len, reverse=True)
)
_SEGMENTABLE_LENGTHS: tuple[int, ...] = tuple(sorted({len(k) for k in _SEGMENTABLE_ALIASES}, reverse=True))
_ALIASES_BY_LENGTH: dict[int, dict[str, str]] = {}
for _alias in _SEGMENTABLE_ALIASES:
    _ALIASES_BY_LENGTH.setdefault(len(_alias), {})[_alias] = LANGUAGE_ALIASES_TO_CANONICAL[_alias]
_SEGMENTABLE_TWO_LETTER_ALIASES: dict[str, str] = {
    k: v for k, v in LANGUAGE_ALIASES_TO_CANONICAL.items() if len(k) == 2
}


def _normalize_lang_code(raw: str) -> str | None:
    """Normalize one language token to ISO 639-2 (3-letter code)."""
    code = raw.lower().strip()
    if code == 'und':
        # ISO 639-2 "und" = undetermined/unknown language
        return 'und'
    return LANGUAGE_ALIASES_TO_CANONICAL.get(code)


def _parse_concatenated_lang_codes(raw: str) -> tuple[list[str], list[str]]:
    """Iteratively parse separator-less values and keep recognized chunks.

    Returns:
      (recognized_iso_codes, unknown_chunks)
    """
    token = re.sub(r"\s+", "", (raw or "").lower())
    if not token:
        return ([], [])

    recognized: list[str] = []
    unknown_chunks: list[str] = []
    unknown_buf: list[str] = []

    idx = 0
    n = len(token)
    while idx < n:
        match_norm = None
        match_len = 0
        for alias_len in _SEGMENTABLE_LENGTHS:
            end = idx + alias_len
            if end > n:
                continue
            candidate = token[idx:end]
            norm = _ALIASES_BY_LENGTH[alias_len].get(candidate)
            if norm:
                match_norm = norm
                match_len = alias_len
                break

        # 2-letter chunks are accepted only when we are on a clean boundary
        # (no unknown chars accumulated). This keeps support for sequences like
        # "freru" while avoiding noisy matches inside random garbage.
        if match_norm is None and not unknown_buf and idx + 2 <= n:
            candidate2 = token[idx:idx + 2]
            norm2 = _SEGMENTABLE_TWO_LETTER_ALIASES.get(candidate2)
            if norm2:
                match_norm = norm2
                match_len = 2

        if match_norm is None:
            unknown_buf.append(token[idx])
            idx += 1
            continue

        if unknown_buf:
            unknown_chunks.append(''.join(unknown_buf))
            unknown_buf = []

        recognized.append(match_norm)
        idx += match_len

    if unknown_buf:
        unknown_chunks.append(''.join(unknown_buf))

    return recognized, unknown_chunks


def _parse_lang_token(token: str, item_title: str = '') -> list[str]:
    """Parse one language token (single alias or concatenated aliases)."""
    single = re.sub(r"\s+", "", token.lower().strip())
    if not single:
        return []

    if single in SPECIAL_LANGUAGE_MARKERS:
        log.info(f"[SCAN] Audio language marker detected (no direct ISO code): {single!r} in item {item_title!r}")
        return []

    norm = _normalize_lang_code(single)
    if norm:
        return [norm]

    parsed, unknown_chunks = _parse_concatenated_lang_codes(single)
    if parsed:
        if unknown_chunks:
            rec_preview = parsed[:8]
            ignored_preview = unknown_chunks[:5]
            suffix = ""
            if len(parsed) > len(rec_preview) or len(unknown_chunks) > len(ignored_preview):
                suffix = f" (truncated: recognized={len(parsed)}, ignored={len(unknown_chunks)})"
            log.info(
                f"[SCAN] Partially parsed audio language value: {single!r} in item {item_title!r} "
                f"-> recognized={rec_preview}, ignored={ignored_preview}{suffix}"
            )
        return parsed

    log.warning(f"[SCAN] Unrecognized audio language value: {single!r} in item {item_title!r} — skipped")
    return []


def _parse_lang_raw(raw: str | None, item_title: str = '') -> list[str]:
    """Parse a raw language string (possibly concatenated, e.g. 'freeng') into ISO 639-2 codes."""
    if raw is None:
        return []
    raw = raw.strip().lower()
    if not raw:
        return []

    # Step 1 — split on explicit separators
    parts = [p.strip() for p in re.split(r'[\s,/|;_+\-]+', raw) if p.strip()]
    if len(parts) > 1:
        result = []
        for p in parts:
            result.extend(_parse_lang_token(p, item_title))
        return result

    return _parse_lang_token(parts[0] if parts else raw, item_title)



def parse_audio_languages(root: ET.Element, item_title: str = '') -> list[str]:
    """Collect all audio language codes from an NFO root element. Returns sorted ISO 639-2 list."""
    langs: list[str] = []

    # Primary: <fileinfo><streamdetails><audio>*<language>
    for audio_el in root.findall(".//fileinfo/streamdetails/audio"):
        raw = _xml_text(audio_el, "language")
        if raw:
            langs.extend(_parse_lang_raw(raw, item_title))

    # Fallback: <audio>*<language> at root level
    for audio_el in root.findall("audio"):
        raw = _xml_text(audio_el, "language")
        if raw:
            langs.extend(_parse_lang_raw(raw, item_title))

    # Last resort: <languages> at root
    raw_langs = _xml_text(root, "languages")
    if raw_langs:
        langs.extend(_parse_lang_raw(raw_langs, item_title))

    # Deduplicate (preserve order), sort, exclude 'und'
    seen: set[str] = set()
    result = []
    for l in langs:
        if l not in seen and l != 'und':
            seen.add(l)
            result.append(l)
    return sorted(result)


def simplify_audio_languages(codes: list[str] | None) -> str:
    """Map detailed audio language codes to VF / VO / MULTI / UNKNOWN.

    Rules:
      - no language detected -> UNKNOWN
      - only French -> VF
      - French + at least 1 other language -> MULTI
      - without French (but with at least one language) -> VO
    """
    if not isinstance(codes, list):
        return 'UNKNOWN'

    normalized: set[str] = set()
    for code in codes:
        if not isinstance(code, str):
            continue
        norm = _normalize_lang_code(code)
        if norm and norm != 'und':
            normalized.add(norm)

    if not normalized:
        return 'UNKNOWN'
    if normalized == {'fra'}:
        return 'VF'
    if 'fra' in normalized and len(normalized) > 1:
        return 'MULTI'
    return 'VO'


# Pre-compute normalized keys for fast lookup: strip dashes/spaces/uppercase
_AC_NORM = re.compile(r"[-\s]")
def _ac_key(s: str) -> str:
    return _AC_NORM.sub("", s.upper())

_AC_LOOKUP: list[tuple[str, dict]] = [
    (_ac_key(k), AUDIOCODEC_MAPPING["mapping"][k])
    for k in AUDIOCODEC_MAPPING.get("priority", [])
    if k in AUDIOCODEC_MAPPING.get("mapping", {})
]


def normalize_audio_codec(raw: str | None) -> dict:
    """
    Normalize an audio codec string to three levels:
      'raw'        — original value as-is (for debug)
      'normalized' — canonical constant used for filters/stats (e.g. 'ATMOS', 'EAC3')
      'display'    — human-readable label used in the UI (e.g. 'Dolby Atmos')

    Matching follows the priority order in audiocodec_mapping.json.
    Tolerance: case-insensitive, dashes and spaces ignored (EAC-3 == EAC3).
    """
    fb = AUDIOCODEC_MAPPING.get("fallback", {"normalized": "UNKNOWN", "display": "Unknown"})
    if not raw or not raw.strip():
        return {"raw": raw, "normalized": fb["normalized"], "display": fb["display"]}

    value_key = _ac_key(raw.strip())
    for entry_key, entry in _AC_LOOKUP:
        if value_key == entry_key:
            return {"raw": raw, "normalized": entry["normalized"], "display": entry["display"]}

    return {"raw": raw, "normalized": fb["normalized"], "display": fb["display"]}


# NFO parse stats — reset at each run_quick() call, reported as grouped summary
_nfo_stats: dict = {"ok": 0, "failed": 0}


def _parse_nfo_xml(nfo_path: Path) -> ET.Element | None:
    """
    Parse a NFO file tolerantly:
    1. Try standard ElementTree.parse().
    2. On "junk after document element", read raw bytes, find the root close tag,
       truncate there, and retry — handles NFO files with extra content after </root>.
    3. Log non-._* failures as DEBUG (summary reported at end of scan).
    """
    try:
        root = ET.parse(nfo_path).getroot()
        _nfo_stats["ok"] += 1
        return root
    except ET.ParseError as e:
        err = str(e)
        # Strategy: read raw content and truncate at first root closing tag
        try:
            raw = nfo_path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
            # Find root tag name from opening tag
            m = re.match(r"\s*<(\w+)", text)
            if m:
                root_tag = m.group(1)
                close = f"</{root_tag}>"
                idx = text.find(close)
                if idx != -1:
                    truncated = text[:idx + len(close)]
                    root = ET.fromstring(truncated)
                    log.debug(f"NFO truncated-parse OK ({nfo_path.name}): {err}")
                    _nfo_stats["ok"] += 1
                    return root
        except Exception:
            pass
        if not nfo_path.name.startswith("._"):
            _nfo_stats["failed"] += 1
            log.debug(f"NFO parse failed ({nfo_path}): {err}")
        return None
    except Exception as e:
        if not nfo_path.name.startswith("._"):
            _nfo_stats["failed"] += 1
            log.debug(f"NFO read error ({nfo_path}): {e}")
        return None


def _xml_text(root: ET.Element, *tags) -> str | None:
    """Return the text of the first matching tag, trying each in order."""
    for tag in tags:
        el = root.find(tag)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return None


def parse_movie_nfo(nfo_path: Path) -> dict:
    """Parse a Kodi/Jellyfin movie .nfo file. Returns a dict of metadata."""
    result = {}
    root = _parse_nfo_xml(nfo_path)
    if root is None:
        return result

    result["title"]   = _xml_text(root, "title")
    result["year"]    = _xml_text(root, "year")
    result["plot"]    = _xml_text(root, "plot")
    result["runtime"] = _xml_text(root, "runtime")

    # tmdb_id — prefer <uniqueid type="tmdb">, fallback to <id>
    for uid in root.findall("uniqueid"):
        if uid.get("type") == "tmdb" and uid.text:
            result["tmdb_id"] = uid.text.strip()
            break
    if "tmdb_id" not in result:
        result["tmdb_id"] = _xml_text(root, "id")

    # Poster URL from <thumb aspect="poster">
    for thumb in root.findall("thumb"):
        if thumb.get("aspect") == "poster" and thumb.text:
            result["poster_url"] = thumb.text.strip()
            break

    # Resolution + codec + HDR from <fileinfo><streamdetails><video>
    video = root.find(".//fileinfo/streamdetails/video")
    if video is not None:
        try:
            w = int(_xml_text(video, "width")  or 0)
            h = int(_xml_text(video, "height") or 0)
            if w and h:
                result["width"]      = w
                result["height"]     = h
                result["resolution"] = classify_resolution(w, h)
            raw_codec = _xml_text(video, "codec")
            if raw_codec:
                result["codec"] = normalize_codec(raw_codec)
            hdr = _xml_text(video, "hdrtype")
            result["hdr"] = bool(hdr and hdr.strip())
            rt = _xml_text(video, "duration") or _xml_text(root, "runtime")
            if rt:
                try:
                    result["runtime_min"] = int(float(rt))
                except (ValueError, TypeError):
                    pass
        except (ValueError, TypeError):
            pass

    # Audio codec from <fileinfo><streamdetails><audio><codec>
    # fallback to <audio_codec> / <audiocodec> at root level
    audio = root.find(".//fileinfo/streamdetails/audio")
    raw_audio = (_xml_text(audio, "codec") if audio is not None else None) \
                or _xml_text(root, "audio_codec", "audiocodec")
    if raw_audio:
        ac = normalize_audio_codec(raw_audio)
        result["audio_codec_raw"]     = ac["raw"]
        result["audio_codec"]         = ac["normalized"]
        result["audio_codec_display"] = ac["display"]

    result["audio_languages"] = parse_audio_languages(root, result.get("title") or "")
    result["audio_languages_simple"] = simplify_audio_languages(result["audio_languages"])

    return result


def parse_tvshow_nfo(nfo_path: Path) -> dict:
    """Parse a tvshow.nfo file (series-level metadata)."""
    result = {}
    root = _parse_nfo_xml(nfo_path)
    if root is None:
        return result

    result["title"] = _xml_text(root, "title")
    result["year"]  = _xml_text(root, "year")
    result["plot"]  = _xml_text(root, "plot")

    for uid in root.findall("uniqueid"):
        if uid.get("type") == "tmdb" and uid.text:
            result["tmdb_id"] = uid.text.strip()
            break
    if "tmdb_id" not in result:
        result["tmdb_id"] = _xml_text(root, "id")

    for thumb in root.findall("thumb"):
        if thumb.get("aspect") == "poster" and thumb.text:
            result["poster_url"] = thumb.text.strip()
            break

    return result


def count_seasons_episodes(series_dir: Path) -> tuple[int, int]:
    """
    Count episodes and deduce season count for a series.

    Supports:
    - Sub-folder layout : Serie/Season 1/S01E01.nfo
    - Flat layout       : Serie/S01E01.nfo
    - Mixed             : some seasons in sub-folders, others flat
    """
    SKIP = {"tvshow.nfo", "season.nfo"}
    _season_re = re.compile(r"[Ss](\d{1,2})[Ee]\d", re.IGNORECASE)

    episode_nfos: list[Path] = []
    try:
        for entry in series_dir.rglob("*.nfo"):
            if (entry.is_file() and entry.name.lower() not in SKIP
                    and not entry.name.startswith("._")):
                episode_nfos.append(entry)
    except Exception:
        pass

    episode_count = len(episode_nfos)

    # If no .nfo files, fall back to counting video files
    if episode_count == 0:
        _VIDEO_EXT = {'.mkv', '.mp4', '.avi', '.m2ts', '.ts', '.mov', '.wmv', '.flv', '.m4v'}
        video_files: list[Path] = []
        try:
            for entry in series_dir.rglob('*'):
                if entry.is_file() and entry.suffix.lower() in _VIDEO_EXT:
                    video_files.append(entry)
        except Exception:
            pass
        episode_count = len(video_files)
        if episode_count == 0:
            # Last resort: count season sub-folders and their children
            try:
                sub_dirs = [d for d in series_dir.iterdir() if d.is_dir() and not d.name.startswith(('.', '@'))]
                if sub_dirs:
                    return len(sub_dirs), sum(
                        len([f for f in d.iterdir() if f.is_file()]) for d in sub_dirs
                    )
            except Exception:
                pass
            return 0, 0
        # Deduce seasons from video filenames
        season_numbers_v: set[int] = set()
        for vf in video_files:
            m = _season_re.search(vf.stem)
            if m:
                season_numbers_v.add(int(m.group(1)))
        return (len(season_numbers_v) if season_numbers_v else 1), episode_count

    # Deduce seasons from SxxExx patterns in .nfo filenames
    season_numbers: set[int] = set()
    for nfo in episode_nfos:
        m = _season_re.search(nfo.stem)
        if m:
            season_numbers.add(int(m.group(1)))

    season_count = len(season_numbers) if season_numbers else 1
    return season_count, episode_count


def find_episode_nfo(series_dir: Path) -> dict:
    """
    Find the first episode .nfo anywhere in the series tree and extract
    video metadata (resolution, codec, HDR, runtime).

    Supports flat layout (no season sub-folders), sub-folder layout, and mixed.
    Stops at the first .nfo that contains valid video stream details.
    """
    SKIP = {"tvshow.nfo", "season.nfo"}

    # Collect all candidate episode .nfo files recursively, sorted for
    # reproducibility (season 1 / episode 1 comes first alphabetically).
    try:
        candidates = sorted(
            f for f in series_dir.rglob("*.nfo")
            if f.is_file() and f.name.lower() not in SKIP
            and not f.name.startswith("._")
        )
    except Exception:
        return {}

    for nfo_file in candidates:
        root = _parse_nfo_xml(nfo_file)
        if root is None:
            continue
        try:
            video = root.find(".//fileinfo/streamdetails/video")
            if video is not None:
                w = int(_xml_text(video, "width")  or 0)
                h = int(_xml_text(video, "height") or 0)
                if w and h:
                    raw_codec = _xml_text(video, "codec")
                    hdr_raw   = _xml_text(video, "hdrtype")
                    ep_rt     = _xml_text(video, "duration")
                    runtime_min = None
                    if ep_rt:
                        try: runtime_min = int(float(ep_rt))
                        except (ValueError, TypeError): pass
                    audio_el = root.find(".//fileinfo/streamdetails/audio")
                    raw_audio = (_xml_text(audio_el, "codec") if audio_el is not None else None) \
                                or _xml_text(root, "audio_codec", "audiocodec")
                    ac = normalize_audio_codec(raw_audio)
                    langs = parse_audio_languages(root)
                    return {
                        "width":              w,
                        "height":             h,
                        "resolution":         classify_resolution(w, h),
                        "codec":              normalize_codec(raw_codec),
                        "hdr":                bool(hdr_raw and hdr_raw.strip()),
                        "runtime_min":        runtime_min,
                        "audio_codec_raw":    ac["raw"],
                        "audio_codec":        ac["normalized"],
                        "audio_codec_display": ac["display"],
                        "audio_languages":    langs,
                        "audio_languages_simple": simplify_audio_languages(langs),
                    }
        except Exception as e:
            log.debug(f"Episode NFO extract error ({nfo_file}): {e}")
            continue

    return {}


def find_movie_nfo(movie_dir: Path) -> Path | None:
    """Find the .nfo file for a movie directory (any .nfo that isn't season/tvshow)."""
    SKIP = {"tvshow.nfo", "season.nfo"}
    for f in sorted(movie_dir.iterdir()):
        if (f.is_file() and f.suffix.lower() == ".nfo"
                and f.name.lower() not in SKIP
                and not f.name.startswith("._")):  # skip macOS AppleDouble metadata
            return f
    return None


def poster_rel_path(media_dir: Path, root: Path) -> str | None:
    """Return the URL-encoded relative path to poster image if it exists, else None."""
    for ext in ("poster.jpg", "poster.png", "poster.jpeg"):
        poster = media_dir / ext
        if poster.exists():
            rel = str(media_dir.relative_to(root) / ext)
            encoded = "/".join(urllib.parse.quote(part, safe="") for part in rel.replace("\\", "/").split("/"))
            return encoded
    return None


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
        os.chmod(SECRETS_PATH, 0o600)
    except Exception as e:
        log.warning(f"[secrets] Could not write {SECRETS_PATH}: {e}")


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
            log.info(f"[jellyseerr] Item not found for {path} (not in Jellyseerr/TMDB)")
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
        if ftype == "movie" and not enable_movies:
            continue
        if ftype == "tv" and not enable_series:
            continue
        name = f["name"].replace("_", " ").replace("-", " ").title()
        cats.append({"name": name, "type": ftype, "folder": f["name"]})
    return cats


def sync_folders(root: Path, cfg: dict) -> bool:
    """
    Sync config['folders'] with filesystem subdirs of root:
    - New dirs  → add with type=null, visible=false
    - Missing   → mark missing=True (preserved in config)
    - Existing  → preserve current config (type, visible)
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
            cfg_folders[name] = {"name": name, "type": None, "visible": False}
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
            cfg["folders"].append({"name": fname, "type": "movie", "visible": True})
        for fname in env_series:
            cfg["folders"].append({"name": fname, "type": "tv",    "visible": True})
        changed = True

    # system block defaults
    sys_cfg = cfg.setdefault("system", {})
    if not sys_cfg.get("scan_cron"):
        sys_cfg["scan_cron"] = "0 3 * * *"
        changed = True
    if not sys_cfg.get("log_level"):
        sys_cfg["log_level"] = "INFO"
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


def write_inventory_json_non_blocking(scanned_entries: list[dict], scan_mode: str) -> None:
    log.info("[SCAN] Inventory write started")
    try:
        current_inventory = build_library_inventory(scanned_entries, scan_mode)
        existing_inventory = load_existing_inventory_document_non_blocking(INVENTORY_OUTPUT_PATH)
        merged_inventory = (
            merge_inventory_documents(existing_inventory, current_inventory)
            if existing_inventory is not None
            else current_inventory
        )
        write_json(merged_inventory, INVENTORY_OUTPUT_PATH)
        log.info(f"[SCAN] Inventory written successfully: {INVENTORY_OUTPUT_PATH}")
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
    log.info(f"Written: {output_path}")


# ---------------------------------------------------------------------------
# Config helpers (config.json)
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

def scan_media_item(media_dir: Path, root: Path, cat: dict, prev: dict) -> dict:
    """
    Build one item dict from filesystem + NFO.
    `prev` is the existing item from library.json (may be empty dict).
    """
    raw_name  = media_dir.name
    item_path = str(media_dir.relative_to(root))
    mtime     = media_dir.stat().st_mtime
    is_tv     = cat["type"] == "tv"

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

    return {
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
        "hdr":               nfo_meta.get("hdr", False),
        "providers":         _normalize_providers(prev.get("providers", [])),
        "providers_fetched": prev.get("providers_fetched", False),
    }


def run_quick(only_category: str | None = None, scan_mode: str = "full") -> None:
    _t0 = time.monotonic()
    _nfo_stats["ok"] = 0
    _nfo_stats["failed"] = 0
    scope = f" [category: {only_category}]" if only_category else ""
    log.info(f"[SCAN] Starting filesystem+NFO scan{scope}")

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

    categories = build_categories_from_config(cfg)
    if not categories:
        is_first_scan = not Path(OUTPUT_PATH).exists()
        if is_first_scan:
            log.info("[SCAN] No folder configured yet — skipping scan (configure folders via the web UI)")
        else:
            log.warning("[SCAN] No folder configured with type 'movie' or 'tv' in config.json")
        return

    log.info(f"[SCAN] {len(categories)} configured folder(s): {', '.join(c['name'] for c in categories)}")
    existing = load_existing(OUTPUT_PATH)

    items = []
    inventory_entries: list[dict] = []
    item_id = 0
    scanned_paths = set()
    cat_counts = {}

    for cat in categories:
        if only_category and cat["name"] != only_category:
            continue

        cat_dir = root / cat["folder"]
        if not cat_dir.exists():
            log.warning(f"[SCAN] Category folder not found: {cat_dir}")
            continue

        cat_items_before = len(items)
        for media_dir in sorted(cat_dir.iterdir()):
            if not media_dir.is_dir() or media_dir.name.startswith(('.', '@')):
                continue

            item_path = str(media_dir.relative_to(root))
            prev = existing.get(item_path, {})

            item = scan_media_item(media_dir, root, cat, prev)
            item["id"] = item_id
            items.append(item)
            inventory_entries.append({
                "media_dir": media_dir,
                "cat": cat,
                "title": item.get("title") or media_dir.name,
            })
            scanned_paths.add(item_path)
            item_id += 1

        count = len(items) - cat_items_before
        cat_counts[cat["name"]] = count
        log.info(f'[SCAN] Category "{cat["name"]}": {count} items found')

    # When filtering, preserve items from other categories
    if only_category:
        preserved = [i for i in existing.values() if i.get("path") not in scanned_paths]
        log.info(f"  Preserving {len(preserved)} items from other categories")
        for i in preserved:
            i["id"] = item_id
            item_id += 1
        items = items + preserved

    all_categories = sorted({i["category"] for i in items})

    # Preserve providers_meta from previous run (enrich writes it; quick must not lose it)
    prev_data: dict = {}
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as _f:
            prev_data = json.load(_f)
    except Exception:
        pass

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
    }
    output_path = Path(OUTPUT_PATH)
    write_json(data, OUTPUT_PATH)
    write_inventory_json_non_blocking(inventory_entries, scan_mode)
    try:
        size_mb = output_path.stat().st_size / (1024*1024)
        size_str = f"{size_mb:.1f} MB"
    except Exception:
        size_str = "?"
    elapsed = time.monotonic() - _t0
    log.info(f"[SCAN] Filesystem scan done — {len(items)} items total")
    log.info(f"[SCAN] Writing library.json — {len(items)} items ({size_str})")
    if _nfo_stats["failed"] > 0:
        log.info(f"[SCAN] NFO parsing: {_nfo_stats['ok']} OK / {_nfo_stats['failed']} failed (see DEBUG logs for details)")
    else:
        log.debug(f"[SCAN] NFO parsing: {_nfo_stats['ok']} OK")
    audio_dist: dict = {}
    for item in items:
        ac = item.get("audio_codec") or "UNKNOWN"
        audio_dist[ac] = audio_dist.get(ac, 0) + 1
    parts = [f"{k}×{v}" for k, v in sorted(audio_dist.items(), key=lambda x: -x[1])]
    log.info(f"[SCAN] Audio codecs: {' / '.join(parts) if parts else 'none'}")
    lang_dist: dict = {}
    for item in items:
        for l in (item.get("audio_languages") or []):
            lang_dist[l] = lang_dist.get(l, 0) + 1
    if lang_dist:
        lparts = [f"{k}×{v}" for k, v in sorted(lang_dist.items(), key=lambda x: -x[1])]
        log.info(f"[SCAN] Audio languages: {' / '.join(lparts)}")
    log.info(f"[SCAN] Filesystem scan completed in {elapsed:.1f}s")



# ---------------------------------------------------------------------------
# ENRICH (providers via Jellyseerr)
# ---------------------------------------------------------------------------

def run_enrich(force: bool = False, only_category: str | None = None) -> None:
    _t0 = time.monotonic()
    label = "force" if force else "missing only"
    scope = f" [category: {only_category}]" if only_category else ""
    log.info(f"[SCAN] Starting Jellyseerr enrichment ({label}){scope}")

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

    # Load provider map (file-based normalization, reloaded each scan)
    provider_map = load_provider_map()
    log.info(f"[providers] providers.json mapping loaded ({len(provider_map)} entries)")

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
    for cat_name, cat_items in sorted(by_cat.items()):
        log.info(f"  Enriching: {cat_name} ({len(cat_items)} items)")
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
        log.info(f"[SCAN]   {cat_name} — {enriched} enriched so far")

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
    log.info(f"[SCAN] Enrichment completed in {elapsed:.1f}s — {' / '.join(parts)}")


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
# HTTP server (--serve mode)
# ---------------------------------------------------------------------------

_srv_lock  = threading.Lock()
_srv_state = {
    "status":     "idle",
    "mode":       None,
    "started_at": None,
    "ended_at":   None,
    "log":        [],
}
_srv_proc = None

VALID_MODES = {"quick", "enrich", "full", "default"}


def _scanner_cmd(mode: str) -> list[str]:
    base = [sys.executable, __file__]
    if mode == "quick":  return base + ["--quick"]
    if mode == "enrich": return base + ["--enrich"]
    if mode == "full":   return base + ["--full"]
    return base


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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
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
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/auth":
            pw = os.environ.get("APP_PASSWORD", "")
            self._json(200, {"required": bool(pw)})
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
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
            pw = os.environ.get("APP_PASSWORD", "")
            entered = payload.get("password", "")
            ok = bool(pw) and entered == pw
            self._json(200, {"ok": ok})
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
            log.info(f"[config] Received: {json.dumps(payload)}")
            # Extract apikey before merging — store in secrets, not config.json
            new_apikey = None
            if isinstance(payload.get("jellyseerr"), dict) and "apikey" in payload["jellyseerr"]:
                new_apikey = payload["jellyseerr"].pop("apikey")
                if not payload["jellyseerr"]:
                    payload.pop("jellyseerr", None)
            merged = deep_merge(cfg, payload)
            merged, _ = _ensure_needs_onboarding(merged, config_exists=True)
            # Ensure apikey never persists in config.json
            if "jellyseerr" in merged:
                merged["jellyseerr"].pop("apikey", None)
            save_config(merged)
            if new_apikey is not None and new_apikey != "***":
                secrets = _load_secrets()
                secrets["jellyseerr_apikey"] = new_apikey
                _save_secrets(secrets)
                log.info("[config] Jellyseerr API key saved to secrets")
            log.info(f"[config] Saved")
            # Apply log_level change immediately without restart
            new_level = merged.get("system", {}).get("log_level") or merged.get("log_level") or ""
            if new_level:
                logging.getLogger().setLevel(getattr(logging, new_level.upper(), logging.INFO))
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
    mode_group.add_argument("--quick",  action="store_true",
        help="Filesystem + NFO scan only, no provider enrichment")
    mode_group.add_argument("--enrich", action="store_true",
        help="Filesystem + NFO scan + fetch missing providers (default)")
    mode_group.add_argument("--full",   action="store_true",
        help="Filesystem + NFO scan + force re-fetch ALL providers")
    mode_group.add_argument("--serve",  action="store_true",
        help="Start HTTP API server on 127.0.0.1:8095")
    mode_group.add_argument("--reset",  action="store_true",
        help="Delete library.json and exit")
    parser.add_argument("--category", default=None, metavar="NAME",
        help="Restrict scan to a single category name")
    args = parser.parse_args()

    if args.serve:
        serve()
        return

    if args.reset:
        run_reset()
        return

    _t_main = time.monotonic()

    if args.quick:
        mode_label = "--quick"
    elif args.full:
        mode_label = "--full"
    else:
        mode_label = "--enrich (default)"
    log.info(f"[SCAN] ═══════════════════════════════════")
    log.info(f"[SCAN] Starting scan {mode_label}")
    log.info(f"[SCAN] ═══════════════════════════════════")

    if args.quick:
        run_quick(only_category=args.category, scan_mode="quick")
    elif args.full:
        run_quick(only_category=args.category, scan_mode="full")
        run_enrich(force=True, only_category=args.category)
    else:
        # --enrich or default
        run_quick(only_category=args.category, scan_mode="full")
        run_enrich(force=False, only_category=args.category)

    elapsed = time.monotonic() - _t_main
    log.info(f"[SCAN] ═══════════════════════════════════")
    log.info(f"[SCAN] Full scan completed in {elapsed:.1f}s")
    log.info(f"[SCAN] ═══════════════════════════════════")


if __name__ == "__main__":
    main()
