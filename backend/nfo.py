"""
NFO parsing, codec normalisation and audio language helpers.

All functions are pure or depend only on static data and the local filesystem
(audiocodec_mapping.json, poster files). They have no dependency on scanner
runtime state (config, library.json, Jellyseerr, etc.) and can be tested in
isolation.

Imported by scanner.py at runtime.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger("scanner")


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def classify_resolution(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "SD"
    long_edge = max(width, height)
    short_edge = min(width, height)
    # 4K:
    # - Keep UHD content (>=2160 on one axis),
    # - Keep scope/cropped 4K encodes (~3840x1600) via long-edge tolerance,
    # - Avoid promoting near-square ~2K sources (e.g. 2100x2100, 2560x2100).
    if short_edge >= 2160 or (long_edge >= 3800 and short_edge >= 1500):
        return "4K"
    # 1080p: require a near-FHD long edge and enough vertical pixels for cropped scope encodes.
    # This avoids promoting 5:4 sources such as 1280x1024 to 1080p.
    if long_edge >= 1880 and short_edge >= 800:
        return "1080p"
    # 720p:
    # - Require a near-1280 long edge,
    # - Accept cropped encodes with lower short edge,
    # - Avoid promoting small near-square sources (e.g. 700x700).
    if long_edge >= 1240 and short_edge >= 520:
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
        log.debug(f"[SCAN] Audio language marker detected (no direct ISO code): {single!r} in item {item_title!r}")
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
            log.debug(
                f"[SCAN] Partially parsed audio language value: {single!r} in item {item_title!r} "
                f"-> recognized={rec_preview}, ignored={ignored_preview}{suffix}"
            )
        return parsed

    log.debug(f"[SCAN] Unrecognized audio language value: {single!r} in item {item_title!r} — skipped")
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

    # IDs — prefer explicit uniqueid tags, then dedicated root tags, then legacy <id>.
    for uid in root.findall("uniqueid"):
        uid_type = (uid.get("type") or "").strip().lower()
        uid_val = (uid.text or "").strip()
        if not uid_val:
            continue
        if uid_type in {"tmdb", "themoviedb"}:
            result["tmdb_id"] = uid_val
            break
    if "tmdb_id" not in result:
        tmdb_fallback = _xml_text(root, "tmdbid", "tmdb_id", "id")
        if tmdb_fallback:
            result["tmdb_id"] = tmdb_fallback

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
            result["hdr_type"] = hdr
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
        uid_type = (uid.get("type") or "").strip().lower()
        uid_val = (uid.text or "").strip()
        if not uid_val:
            continue
        if uid_type in {"tmdb", "themoviedb"} and "tmdb_id" not in result:
            result["tmdb_id"] = uid_val
        if uid_type in {"tvdb", "thetvdb"} and "tvdb_id" not in result:
            result["tvdb_id"] = uid_val

    if "tmdb_id" not in result:
        tmdb_fallback = _xml_text(root, "tmdbid", "tmdb_id")
        if tmdb_fallback:
            result["tmdb_id"] = tmdb_fallback
    if "tvdb_id" not in result:
        tvdb_fallback = _xml_text(root, "tvdbid", "tvdb_id")
        if tvdb_fallback:
            result["tvdb_id"] = tvdb_fallback
    # Legacy fallback for tvshow.nfo: <id> is often TVDB, never coerce into tmdb_id.
    if "tvdb_id" not in result:
        tvdb_legacy = _xml_text(root, "id")
        if tvdb_legacy:
            result["tvdb_id"] = tvdb_legacy

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
                        "hdr_type":           hdr_raw,
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
