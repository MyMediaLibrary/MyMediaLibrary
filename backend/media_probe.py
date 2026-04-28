"""Generate a ffprobe-based comparison snapshot for MyMediaLibrary.

The probe output is intentionally separate from library.json. It keeps the
regular scan output untouched and writes a comparison document to
library_probe.json when explicitly enabled.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time
from typing import Any

try:
    from backend import runtime_paths
except Exception:
    import runtime_paths  # type: ignore

try:
    from backend.nfo import (
        classify_resolution,
        normalize_audio_channels,
        normalize_audio_codec,
        normalize_codec,
        _parse_lang_raw,
        simplify_audio_languages,
    )
except Exception:
    from nfo import (  # type: ignore
        classify_resolution,
        normalize_audio_channels,
        normalize_audio_codec,
        normalize_codec,
        _parse_lang_raw,
        simplify_audio_languages,
    )

try:
    from backend.scoring import compute_quality
except Exception:
    from scoring import compute_quality  # type: ignore


log = logging.getLogger("scanner")

LIBRARY_PATH = str(runtime_paths.LIBRARY_DIR)
LIBRARY_PROBE_OUTPUT_PATH = str(runtime_paths.LIBRARY_PROBE_JSON)
MEDIA_PROBE_CACHE_PATH = str(runtime_paths.MEDIA_PROBE_CACHE_JSON)

MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v",
    ".ts", ".m2ts", ".mpg", ".mpeg", ".flv", ".webm",
}

TECHNICAL_FIELDS = (
    "resolution",
    "width",
    "height",
    "runtime_min",
    "runtime_min_avg",
    "codec",
    "audio_codec_raw",
    "audio_codec",
    "audio_channels",
    "audio_languages",
    "audio_languages_simple",
    "subtitle_languages",
    "video_bitrate",
    "hdr",
    "hdr_type",
    "quality",
)

_TV_SE_EP_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})")
_TV_X_SE_EP_RE = re.compile(r"\b(\d{1,2})x(\d{1,3})\b", re.IGNORECASE)
_TV_SEASON_HINT_RE = re.compile(r"(?:season|saison)[\s._-]*(\d{1,2})", re.IGNORECASE)
_TV_EP_TOKEN_RE = re.compile(r"(?:^|[\s._\-])(?:e|ep|episode)[\s._\-]*(\d{1,3})(?=$|[\s._\-])", re.IGNORECASE)
_TV_TRAILING_NUM_RE = re.compile(r"(?:^|[\s._\-])(\d{2,3})$")
_TV_COMMON_TECH_NUMBERS = {2160, 1080, 720, 576, 540, 480}
_RUNTIME_DIFF_TOLERANCE_MIN = 2


def is_enabled(cfg: dict | None) -> bool:
    probe = (cfg or {}).get("media_probe")
    return isinstance(probe, dict) and probe.get("enabled") is True and probe.get("mode", "compare") == "compare"


def run_media_probe_if_enabled(
    cfg: dict | None,
    *,
    library_json_path: str | Path,
    output_path: str | Path = LIBRARY_PROBE_OUTPUT_PATH,
    library_root: str | Path = LIBRARY_PATH,
    score_enabled: bool = False,
    score_config: dict | None = None,
    timeout: float = 5.0,
) -> dict[str, int] | None:
    if not is_enabled(cfg):
        return None
    return generate_library_probe(
        library_json_path=library_json_path,
        output_path=output_path,
        library_root=library_root,
        score_enabled=score_enabled,
        score_config=score_config,
        timeout=timeout,
        workers=_media_probe_workers(cfg),
        cache_enabled=_media_probe_cache_enabled(cfg),
    )


def generate_library_probe(
    *,
    library_json_path: str | Path,
    output_path: str | Path = LIBRARY_PROBE_OUTPUT_PATH,
    library_root: str | Path = LIBRARY_PATH,
    score_enabled: bool = False,
    score_config: dict | None = None,
    timeout: float = 5.0,
    workers: int = 4,
    cache_enabled: bool = True,
    cache_path: str | Path = MEDIA_PROBE_CACHE_PATH,
) -> dict[str, int]:
    started_at = time.monotonic()
    source_path = Path(library_json_path)
    out_path = Path(output_path)
    root = Path(library_root)
    workers = _normalize_workers(workers)
    stats = {"items": 0, "files_total": 0, "files_probed": 0, "files_cached": 0, "errors": 0}

    log.info(
        "[MEDIA_PROBE] Starting compare probe: workers=%s, cache=%s",
        workers,
        "enabled" if cache_enabled else "disabled",
    )

    with open(source_path, encoding="utf-8") as f:
        original_doc = json.load(f)

    probe_doc = copy.deepcopy(original_doc)
    items = probe_doc.get("items")
    if not isinstance(items, list):
        items = []
        probe_doc["items"] = items

    plans = []
    files_to_resolve: list[Path] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        stats["items"] += 1
        try:
            plan = _plan_item_probe(item, root)
            plans.append(plan)
            files_to_resolve.extend(plan.get("files") or [])
        except Exception as exc:
            _set_error_diagnostic(item, str(exc))
            stats["errors"] += 1
            log.debug("[MEDIA_PROBE] Item planning failed for %s: %s", item.get("path"), exc)

    stats["files_total"] = len(files_to_resolve)
    probe_results, probe_stats = _resolve_probe_results(
        files_to_resolve,
        cache_path=cache_path,
        cache_enabled=cache_enabled,
        workers=workers,
        timeout=timeout,
    )
    stats["files_probed"] = probe_stats["files_probed"]
    stats["files_cached"] = probe_stats["files_cached"]

    for plan in plans:
        item = plan["item"]
        try:
            item_stats = _apply_item_probe(plan, probe_results, score_enabled=score_enabled, score_config=score_config)
            stats["errors"] += item_stats.get("errors", 0)
            if item.get("media_probe", {}).get("status") == "error" and item_stats.get("errors", 0) == 0:
                stats["errors"] += 1
        except Exception as exc:
            _set_error_diagnostic(item, str(exc))
            stats["errors"] += 1
            log.debug("[MEDIA_PROBE] Item probe failed for %s: %s", item.get("path"), exc)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(probe_doc, f, ensure_ascii=False, indent=2)

    duration = time.monotonic() - started_at
    log.info(
        "[MEDIA_PROBE] Generated library_probe.json: %s items, %s files total, %s probed, %s cached, %s errors (duration: %.1fs)",
        stats["items"],
        stats["files_total"],
        stats["files_probed"],
        stats["files_cached"],
        stats["errors"],
        duration,
    )
    return stats


def _plan_item_probe(item: dict, library_root: Path) -> dict:
    media_dir = library_root / str(item.get("path") or "")
    if not media_dir.exists():
        return {"item": item, "kind": "missing", "media_dir": media_dir, "files": [], "error": f"media path not found: {media_dir}"}

    if item.get("type") == "tv":
        files = _video_files_recursive(media_dir)
        if not files:
            return {"item": item, "kind": "skipped", "media_dir": media_dir, "files": [], "error": "no video file found"}
        return {"item": item, "kind": "tv", "media_dir": media_dir, "files": files}

    video_path = _select_main_video_file(media_dir)
    if not video_path:
        return {"item": item, "kind": "skipped", "media_dir": media_dir, "files": [], "error": "no video file found"}
    return {"item": item, "kind": "movie", "media_dir": media_dir, "files": [video_path]}


def _apply_item_probe(
    plan: dict,
    probe_results: dict[str, dict],
    *,
    score_enabled: bool,
    score_config: dict | None,
) -> dict[str, int]:
    item = plan["item"]
    original = copy.deepcopy(item)
    original_score = _score_value(original)
    kind = plan.get("kind")
    if kind == "missing":
        _set_error_diagnostic(item, str(plan.get("error") or "media path not found"))
        return {"errors": 1}
    if kind == "skipped":
        _set_skipped_diagnostic(item, str(plan.get("error") or "no video file found"))
        return {"errors": 0}

    if kind == "tv":
        media_dir = plan["media_dir"]
        episodes = []
        errors = []
        for video_path in plan.get("files") or []:
            probe = probe_results.get(str(video_path)) or {"ok": False, "error": "missing probe result"}
            if probe.get("ok"):
                ep = dict(probe.get("technical") or {})
                season, episode = _extract_season_episode_from_name(str(video_path.relative_to(media_dir)))
                ep["season"] = season
                ep["episode"] = episode
                episode_id = build_episode_id(
                    str(item.get("id") or ""),
                    season=season,
                    episode=episode,
                )
                if episode_id:
                    ep["episode_id"] = episode_id
                ep["_item_id"] = str(item.get("id") or "")
                ep["size_b"] = _file_size(video_path)
                episodes.append(ep)
            else:
                errors.append(str(probe.get("error") or "ffprobe failed"))
        if not episodes:
            _set_error_diagnostic(item, "; ".join(errors[:3]) or "no probe data")
            return {"errors": len(errors) or 1}
        agg = _aggregate_series_metadata(episodes, score_enabled=score_enabled, score_config=score_config)
        overwritten = _merge_technical_fields(item, agg)
        if score_enabled:
            _recompute_item_quality(item, score_config)
            overwritten = _append_field(overwritten, "quality")
        _set_ok_diagnostic(item, overwritten, original_score, _score_value(item), errors[0] if errors else None)
        return {"errors": len(errors)}

    video_path = (plan.get("files") or [None])[0]
    probe = probe_results.get(str(video_path)) if video_path else None
    if not probe:
        probe = {"ok": False, "error": "missing probe result"}
    if not probe.get("ok"):
        _set_error_diagnostic(item, str(probe.get("error") or "ffprobe failed"))
        return {"errors": 1}

    tech = dict(probe.get("technical") or {})
    overwritten = _merge_technical_fields(item, tech)
    if score_enabled:
        _recompute_item_quality(item, score_config)
        overwritten = _append_field(overwritten, "quality")
    _set_ok_diagnostic(item, overwritten, original_score, _score_value(item), None)
    return {"errors": 0}


def _probe_video_file(path: Path, *, timeout: float) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,duration,bit_rate,channels,channel_layout,tags,disposition,color_transfer,color_primaries,color_space,pix_fmt,profile",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        return {"ok": False, "error": f"ffprobe not found: {exc}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffprobe timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if completed.returncode != 0:
        return {"ok": False, "error": (completed.stderr or "ffprobe failed").strip()}
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception as exc:
        return {"ok": False, "error": f"invalid ffprobe json: {exc}"}
    return {"ok": True, "technical": _technical_from_ffprobe(payload)}


def _resolve_probe_results(
    files: list[Path],
    *,
    cache_path: str | Path,
    cache_enabled: bool,
    workers: int,
    timeout: float,
) -> tuple[dict[str, dict], dict[str, int]]:
    unique_files = sorted({Path(path) for path in files}, key=lambda p: str(p))
    stats = {"files_probed": 0, "files_cached": 0}
    results: dict[str, dict] = {}
    disk_cache = _load_probe_cache(cache_path) if cache_enabled else {}
    next_cache: dict[str, dict] = {}
    to_probe: list[Path] = []

    for path in unique_files:
        key = str(path)
        entry = disk_cache.get(key) if cache_enabled else None
        if entry and _cache_entry_matches(path, entry):
            probe = entry.get("probe")
            if isinstance(probe, dict):
                results[key] = copy.deepcopy(probe)
                next_cache[key] = _cache_entry_for(path, probe)
                stats["files_cached"] += 1
                log.debug("[MEDIA_PROBE] Cache hit: %s", path)
                continue
        if cache_enabled:
            log.debug("[MEDIA_PROBE] Cache miss: %s", path)
        to_probe.append(path)

    if to_probe:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_probe_video_file, path, timeout=timeout): path for path in to_probe}
            for future in as_completed(futures):
                path = futures[future]
                key = str(path)
                try:
                    probe = future.result()
                except Exception as exc:
                    probe = {"ok": False, "error": str(exc)}
                results[key] = probe
                stats["files_probed"] += 1
                if probe.get("ok") and cache_enabled:
                    next_cache[key] = _cache_entry_for(path, probe)
                elif not probe.get("ok"):
                    log.debug("[MEDIA_PROBE] ffprobe failed for %s: %s", path, probe.get("error"))

    if cache_enabled:
        _write_probe_cache(cache_path, next_cache)
    return results, stats


def _load_probe_cache(cache_path: str | Path) -> dict[str, dict]:
    path = Path(cache_path)
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    files = payload.get("files") if isinstance(payload, dict) else None
    return files if isinstance(files, dict) else {}


def _write_probe_cache(cache_path: str | Path, files: dict[str, dict]) -> None:
    path = Path(cache_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "files": files}, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as exc:
        log.warning("[MEDIA_PROBE] Could not write cache %s: %s", path, exc)


def _cache_entry_matches(path: Path, entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        stat = path.stat()
    except Exception:
        return False
    return (
        entry.get("path") == str(path)
        and int(entry.get("size_b") or -1) == int(stat.st_size)
        and abs(float(entry.get("mtime") or -1) - float(stat.st_mtime)) < 0.000001
    )


def _cache_entry_for(path: Path, probe: dict) -> dict:
    try:
        stat = path.stat()
        size_b = int(stat.st_size)
        mtime = float(stat.st_mtime)
    except Exception:
        size_b = 0
        mtime = 0.0
    return {
        "path": str(path),
        "size_b": size_b,
        "mtime": mtime,
        "probe": copy.deepcopy(probe),
    }


def _normalize_workers(value) -> int:
    try:
        workers = int(value)
    except Exception:
        workers = 4
    return max(1, min(8, workers))


def _media_probe_workers(cfg: dict | None) -> int:
    probe = (cfg or {}).get("media_probe")
    return _normalize_workers(probe.get("workers") if isinstance(probe, dict) else 4)


def _media_probe_cache_enabled(cfg: dict | None) -> bool:
    probe = (cfg or {}).get("media_probe")
    return not (isinstance(probe, dict) and probe.get("cache_enabled") is False)


def _technical_from_ffprobe(payload: dict) -> dict:
    streams = payload.get("streams") if isinstance(payload, dict) else []
    if not isinstance(streams, list):
        streams = []
    video = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), {})
    audio_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "subtitle"]
    audio = audio_streams[0] if audio_streams else {}

    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    raw_codec = _clean_str(video.get("codec_name"))
    codec = normalize_codec(raw_codec)
    if _is_unknown(codec):
        codec = None
    audio_norm = _normalize_ffprobe_audio_codec(_clean_str(audio.get("codec_name")))
    audio_codec = audio_norm.get("normalized")
    if _is_unknown(audio_codec):
        audio_codec = None

    audio_languages = _languages_from_streams(audio_streams)
    subtitle_languages = _languages_from_streams(subtitle_streams)
    runtime_min = _runtime_minutes(video.get("duration")) or _runtime_minutes((payload.get("format") or {}).get("duration") if isinstance(payload.get("format"), dict) else None)
    video_bitrate = _video_bitrate_from_stream(video)
    hdr_type = _detect_hdr_type(video)
    tech = {
        "width": width,
        "height": height,
        "resolution": classify_resolution(width, height) if width and height else None,
        "runtime_min": runtime_min,
        "runtime_min_avg": runtime_min,
        "codec": codec,
        "audio_codec_raw": audio_norm.get("raw"),
        "audio_codec": audio_codec,
        "audio_channels": _audio_channels_from_stream(audio),
        "audio_languages": audio_languages,
        "audio_languages_simple": simplify_audio_languages(audio_languages),
        "subtitle_languages": subtitle_languages or None,
        "video_bitrate": video_bitrate,
        "hdr": bool(hdr_type),
        "hdr_type": hdr_type,
    }
    if _is_unknown(tech["audio_languages_simple"]):
        tech["audio_languages_simple"] = None
    return tech


def _detect_hdr_type(video: dict) -> str | None:
    text = " ".join(
        str(video.get(k) or "")
        for k in ("color_transfer", "color_primaries", "color_space", "pix_fmt", "profile")
    ).upper()
    if "ARIB-STD-B67" in text or "HLG" in text:
        return "HLG"
    if "SMPTE2084" in text or "PQ" in text:
        return "HDR10"
    if "BT2020" in text:
        return "HDR"
    return None


def _aggregate_series_metadata(episodes: list[dict], *, score_enabled: bool, score_config: dict | None) -> dict:
    by_season: dict[int, list[dict]] = defaultdict(list)
    seasonless_episodes: list[dict] = []
    for ep in episodes:
        season = _positive_int(ep.get("season"))
        if season is None:
            seasonless_episodes.append(ep)
        else:
            by_season[season].append(ep)

    seasons = [
        _aggregate_season_metadata(
            season,
            by_season[season],
            item_id=episodes[0].get("_item_id") if episodes else None,
            score_enabled=score_enabled,
            score_config=score_config,
        )
        for season in sorted(by_season)
    ]
    runtime_min = sum(int(s.get("runtime_min_total") or 0) for s in seasons) + sum(
        int(ep.get("runtime_min") or 0)
        for ep in seasonless_episodes
    )
    episode_count = sum(int(s.get("episodes_found") or 0) for s in seasons) + len(seasonless_episodes)
    audio_languages = sorted(
        set(_aggregate_audio_languages_from_groups(seasons))
        | set(_aggregate_audio_languages_from_groups(seasonless_episodes))
    )
    all_groups = [*episodes]
    agg = {
        "seasons": seasons,
        "season_count": len(seasons),
        "episode_count": episode_count,
        "resolution": _dominant_from_groups(seasons, "resolution") or _dominant_from_groups(all_groups, "resolution"),
        "width": _dominant_from_groups(seasons, "width") or _dominant_from_groups(all_groups, "width"),
        "height": _dominant_from_groups(seasons, "height") or _dominant_from_groups(all_groups, "height"),
        "codec": _dominant_from_groups(seasons, "codec") or _dominant_from_groups(all_groups, "codec"),
        "audio_codec_raw": _dominant_from_groups(seasons, "audio_codec_raw") or _dominant_from_groups(all_groups, "audio_codec_raw"),
        "audio_codec": _dominant_from_groups(seasons, "audio_codec") or _dominant_from_groups(all_groups, "audio_codec"),
        "audio_channels": _dominant_audio_channels([s.get("audio_channels") for s in all_groups]),
        "audio_languages": audio_languages,
        "audio_languages_simple": simplify_audio_languages(audio_languages),
        "subtitle_languages": _aggregate_subtitle_languages(all_groups) or None,
        "video_bitrate": _average_positive_int([ep.get("video_bitrate") for ep in episodes]),
        "hdr_type": _dominant_from_groups(seasons, "hdr_type") or _dominant_from_groups(all_groups, "hdr_type"),
        "runtime_min": runtime_min,
        "runtime_min_avg": int(round(runtime_min / episode_count)) if runtime_min > 0 and episode_count > 0 else None,
    }
    agg["hdr"] = bool(agg["hdr_type"]) or any(bool(s.get("hdr")) for s in seasons) or any(bool(ep.get("hdr")) for ep in all_groups)
    if _is_unknown(agg["audio_languages_simple"]):
        agg["audio_languages_simple"] = None
    return agg


def _aggregate_season_metadata(season: int, episodes: list[dict], *, item_id: str | None = None, score_enabled: bool, score_config: dict | None) -> dict:
    runtime_total = sum(int(ep.get("runtime_min") or 0) for ep in episodes)
    known_runtime_count = len([ep for ep in episodes if int(ep.get("runtime_min") or 0) > 0])
    audio_languages = _aggregate_audio_languages_from_groups(episodes)
    out = {
        "season": int(season),
        "episodes_found": len(episodes),
        "resolution": _dominant_from_groups(episodes, "resolution"),
        "width": _dominant_from_groups(episodes, "width"),
        "height": _dominant_from_groups(episodes, "height"),
        "codec": _dominant_from_groups(episodes, "codec"),
        "audio_codec_raw": _dominant_from_groups(episodes, "audio_codec_raw"),
        "audio_codec": _dominant_from_groups(episodes, "audio_codec"),
        "audio_channels": _dominant_audio_channels([ep.get("audio_channels") for ep in episodes]),
        "audio_languages": audio_languages,
        "audio_languages_simple": simplify_audio_languages(audio_languages),
        "subtitle_languages": _aggregate_subtitle_languages(episodes) or None,
        "video_bitrate": _average_positive_int([ep.get("video_bitrate") for ep in episodes]),
        "hdr_type": _dominant_from_groups(episodes, "hdr_type"),
        "runtime_min_total": runtime_total,
        "runtime_min_avg": int(round(runtime_total / known_runtime_count)) if runtime_total > 0 and known_runtime_count > 0 else None,
        "size_b": sum(int(ep.get("size_b") or 0) for ep in episodes),
    }
    season_id = build_season_id(item_id or "", season)
    if season_id:
        out["season_id"] = season_id
    out["hdr"] = bool(out["hdr_type"]) or any(bool(ep.get("hdr")) for ep in episodes)
    if _is_unknown(out["audio_languages_simple"]):
        out["audio_languages_simple"] = None
    if score_enabled:
        out["quality"] = compute_quality({"type": "tv", **out}, score_config)
    return out


def _merge_technical_fields(target: dict, source: dict) -> list[str]:
    overwritten = []
    for field in TECHNICAL_FIELDS:
        if field == "quality":
            continue
        val = source.get(field)
        if _valid_probe_value(val):
            if _field_value_changed(field, target.get(field), val):
                overwritten.append(field)
            target[field] = val
    if isinstance(source.get("seasons"), list):
        target["seasons"] = source["seasons"]
        overwritten.append("seasons")
        for field in ("season_count", "episode_count"):
            val = source.get(field)
            if _valid_probe_value(val):
                if _field_value_changed(field, target.get(field), val):
                    overwritten.append(field)
                target[field] = val
    return sorted(set(overwritten))


def _recompute_item_quality(item: dict, score_config: dict | None) -> None:
    if item.get("type") == "tv" and isinstance(item.get("seasons"), list):
        seasons = []
        for season in item.get("seasons") or []:
            if not isinstance(season, dict):
                continue
            season_copy = dict(season)
            season_copy["quality"] = compute_quality({"type": "tv", **season_copy}, score_config)
            seasons.append(season_copy)
        item["seasons"] = seasons
        item["quality"] = _aggregate_quality_from_seasons(seasons, item, score_config)
    else:
        item["quality"] = compute_quality(item, score_config)


def _aggregate_quality_from_seasons(seasons: list[dict], item: dict, score_config: dict | None) -> dict:
    weighted_total = 0
    acc: dict[str, float] = defaultdict(float)
    for season in seasons:
        q = season.get("quality") if isinstance(season, dict) else None
        if not isinstance(q, dict):
            continue
        weight = int(season.get("episodes_found") or 1)
        weighted_total += max(1, weight)
        for key in ("video", "audio", "languages", "size", "video_w", "audio_w", "languages_w", "size_w"):
            acc[key] += _number(q.get(key)) * max(1, weight)
        vd = q.get("video_details") if isinstance(q.get("video_details"), dict) else {}
        ad = q.get("audio_details") if isinstance(q.get("audio_details"), dict) else {}
        for key in ("resolution", "codec", "hdr"):
            acc[f"vd_{key}"] += _number(vd.get(key)) * max(1, weight)
        for key in ("codec", "channels"):
            acc[f"ad_{key}"] += _number(ad.get(key)) * max(1, weight)
    if weighted_total <= 0:
        return compute_quality(item, score_config)
    quality = {
        "video_details": {
            "resolution": int(round(acc["vd_resolution"] / weighted_total)),
            "codec": int(round(acc["vd_codec"] / weighted_total)),
            "hdr": int(round(acc["vd_hdr"] / weighted_total)),
        },
        "audio_details": {
            "codec": int(round(acc["ad_codec"] / weighted_total)),
            "channels": int(round(acc["ad_channels"] / weighted_total)),
        },
        "audio": int(round(acc["audio"] / weighted_total)),
        "languages": int(round(acc["languages"] / weighted_total)),
        "size": int(round(acc["size"] / weighted_total)),
        "video_w": round(acc["video_w"] / weighted_total, 4),
        "audio_w": round(acc["audio_w"] / weighted_total, 4),
        "languages_w": round(acc["languages_w"] / weighted_total, 4),
        "size_w": round(acc["size_w"] / weighted_total, 4),
    }
    quality["video"] = int(sum(quality["video_details"].values()))
    quality["score"] = int(round(quality["video_w"] + quality["audio_w"] + quality["languages_w"] + quality["size_w"]))
    return quality


def _set_ok_diagnostic(item: dict, fields: list[str], original_score: int | None, probe_score: int | None, warning: str | None) -> None:
    item["media_probe"] = {
        "status": "ok",
        "source": "ffprobe",
        "overwritten_fields": fields,
        "original_score": original_score,
        "probe_score": probe_score,
        "score_delta": (probe_score - original_score) if isinstance(original_score, int) and isinstance(probe_score, int) else None,
        "error": warning,
    }


def _set_error_diagnostic(item: dict, error: str) -> None:
    original_score = _score_value(item)
    item["media_probe"] = {
        "status": "error",
        "source": "ffprobe",
        "overwritten_fields": [],
        "original_score": original_score,
        "probe_score": original_score,
        "score_delta": 0 if isinstance(original_score, int) else None,
        "error": error,
    }


def _set_skipped_diagnostic(item: dict, reason: str) -> None:
    original_score = _score_value(item)
    item["media_probe"] = {
        "status": "skipped",
        "source": "ffprobe",
        "overwritten_fields": [],
        "original_score": original_score,
        "probe_score": original_score,
        "score_delta": 0 if isinstance(original_score, int) else None,
        "error": reason,
    }


def _select_main_video_file(media_dir: Path) -> Path | None:
    files = _video_files_direct(media_dir)
    if not files:
        files = _video_files_recursive(media_dir)
    if not files:
        return None
    return sorted(files, key=lambda p: (_file_size(p), str(p)), reverse=True)[0]


def _video_files_direct(media_dir: Path) -> list[Path]:
    try:
        return sorted(p for p in media_dir.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS and not p.name.startswith("._"))
    except Exception:
        return []


def _video_files_recursive(media_dir: Path) -> list[Path]:
    try:
        return sorted(p for p in media_dir.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS and not p.name.startswith("._"))
    except Exception:
        return []


def _extract_season_episode_from_name(path_like: str) -> tuple[int | None, int | None]:
    if not path_like:
        return None, None
    season_hint = _TV_SEASON_HINT_RE.search(path_like)
    hinted_season = _positive_int(season_hint.group(1)) if season_hint else None
    match = _TV_SE_EP_RE.search(path_like)
    if match:
        return _positive_int(match.group(1)), _positive_int(match.group(2))
    match = _TV_X_SE_EP_RE.search(path_like)
    if match:
        return _positive_int(match.group(1)), _positive_int(match.group(2))
    stem = Path(Path(path_like).name).stem
    match = _TV_EP_TOKEN_RE.search(stem)
    if match:
        return hinted_season, _positive_int(match.group(1))
    match = _TV_TRAILING_NUM_RE.search(stem)
    if match:
        ep_num = _positive_int(match.group(1))
        if isinstance(ep_num, int) and ep_num not in _TV_COMMON_TECH_NUMBERS:
            return hinted_season, ep_num
    return hinted_season, None


def build_season_id(item_id: str, season) -> str | None:
    season_num = _positive_int(season)
    if not item_id or season_num is None:
        return None
    return f"{item_id}:s{season_num:02d}"


def build_episode_id(item_id: str, season=None, episode=None) -> str | None:
    episode_num = _positive_int(episode)
    if not item_id or episode_num is None:
        return None
    season_num = _positive_int(season)
    if season_num is not None:
        return f"{item_id}:s{season_num:02d}e{episode_num:02d}"
    return f"{item_id}:e{episode_num:03d}"


def _aggregate_audio_languages_from_groups(groups: list[dict]) -> list[str]:
    values = set()
    for group in groups:
        for lang in group.get("audio_languages") or []:
            if isinstance(lang, str) and lang.strip():
                values.add(lang.strip())
    return sorted(values)


def _aggregate_subtitle_languages(groups: list[dict]) -> list[str]:
    values = set()
    for group in groups:
        for lang in group.get("subtitle_languages") or []:
            if isinstance(lang, str) and lang.strip():
                values.add(lang.strip())
    return sorted(values)


def _dominant_from_groups(groups: list[dict], field: str):
    weighted: dict[Any, int] = defaultdict(int)
    for group in groups:
        value = group.get(field)
        if value in (None, "", []):
            continue
        weighted[value] += int(group.get("episodes_found") or 1)
    if not weighted:
        return None
    return sorted(weighted.items(), key=lambda entry: (-entry[1], str(entry[0])))[0][0]


def _dominant_audio_channels(values: list) -> str | None:
    normalized = [normalize_audio_channels(v) for v in values]
    counter = Counter(v for v in normalized if v)
    if not counter:
        return None
    priority = {"1.0": 1, "2.0": 2, "5.1": 3, "7.1": 4}
    return sorted(counter.items(), key=lambda entry: (-entry[1], -priority.get(entry[0], 0), str(entry[0])))[0][0]


def _languages_from_streams(streams: list[dict]) -> list[str]:
    values = set()
    for stream in streams:
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        for raw in _language_tag_values(tags):
            for lang in _parse_probe_language(raw):
                values.add(lang)
    return sorted(values)


def _language_tag_values(tags: dict) -> list:
    values = []
    for key, value in tags.items():
        if not isinstance(key, str):
            continue
        normalized_key = key.strip().casefold()
        if normalized_key == "language" or normalized_key.endswith(".language") or normalized_key.endswith(":language"):
            values.append(value)
    return values


def _parse_probe_language(value) -> list[str]:
    cleaned = _clean_str(str(value)) if value is not None else None
    if not cleaned or cleaned.casefold() in {"und", "unknown"}:
        return []
    try:
        parsed = _parse_lang_raw(cleaned)
    except Exception:
        parsed = []
    return [lang for lang in parsed if isinstance(lang, str) and lang.strip() and lang.casefold() not in {"und", "unknown"}]


def _video_bitrate_from_stream(video: dict) -> int | None:
    bitrate = _positive_int(video.get("bit_rate"))
    if bitrate:
        return bitrate
    tags = video.get("tags") if isinstance(video.get("tags"), dict) else {}
    bitrate = _positive_int(tags.get("BPS"))
    if bitrate:
        return bitrate
    for key, value in tags.items():
        if isinstance(key, str) and key.upper().startswith("BPS-"):
            bitrate = _positive_int(value)
            if bitrate:
                return bitrate
    return _video_bitrate_from_byte_duration_tags(tags)


def _video_bitrate_from_byte_duration_tags(tags: dict) -> int | None:
    byte_tags = [
        (str(key), _positive_int(value))
        for key, value in tags.items()
        if isinstance(key, str) and key.upper().startswith("NUMBER_OF_BYTES-")
    ]
    for byte_key, bytes_count in byte_tags:
        if not bytes_count:
            continue
        suffix = byte_key[len("NUMBER_OF_BYTES-"):]
        duration = _duration_seconds_from_tag(tags.get(f"DURATION-{suffix}"))
        if duration:
            return int(round(bytes_count * 8 / duration))
    return None


def _duration_seconds_from_tag(value) -> float | None:
    cleaned = _clean_str(value)
    if not cleaned:
        return None
    try:
        seconds = float(cleaned)
        return seconds if seconds > 0 else None
    except Exception:
        pass
    match = re.match(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$", cleaned)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


_FFPROBE_AUDIO_CODEC_LABELS = {
    "aac": "AAC",
    "ac3": "Dolby Digital",
    "eac3": "Dolby Digital Plus",
    "eac-3": "Dolby Digital Plus",
    "dts": "DTS",
    "truehd": "Dolby TrueHD",
    "flac": "FLAC",
    "mp3": "MP3",
    "opus": "Opus",
}


def _normalize_ffprobe_audio_codec(raw: str | None) -> dict:
    norm = normalize_audio_codec(raw)
    key = _audio_codec_key(raw)
    label = _FFPROBE_AUDIO_CODEC_LABELS.get(key)
    if label:
        return {"raw": raw, "normalized": label, "display": label}
    return norm


def _audio_codec_key(value) -> str:
    cleaned = _clean_str(str(value)) if value is not None else None
    if not cleaned:
        return ""
    return re.sub(r"[\s_]", "", cleaned.lower())


def _field_value_changed(field: str, current, candidate) -> bool:
    if not _valid_probe_value(current):
        return True
    if field in {"runtime_min", "runtime_min_avg", "runtime_min_total"}:
        return _runtime_value_changed(current, candidate)
    if field == "codec":
        return _casefold(normalize_codec(str(current))) != _casefold(normalize_codec(str(candidate)))
    if field in {"audio_codec", "audio_codec_raw"}:
        return _audio_equivalence_key(current) != _audio_equivalence_key(candidate)
    if field in {"audio_languages", "subtitle_languages"}:
        return _language_list_key(current) != _language_list_key(candidate)
    if isinstance(current, str) and isinstance(candidate, str):
        return _casefold(current) != _casefold(candidate)
    return current != candidate


def _audio_equivalence_key(value) -> str:
    raw_key = _audio_codec_key(value)
    if raw_key in _FFPROBE_AUDIO_CODEC_LABELS:
        return _casefold(_FFPROBE_AUDIO_CODEC_LABELS[raw_key])
    norm = normalize_audio_codec(str(value) if value is not None else None)
    label = norm.get("normalized") if isinstance(norm, dict) else None
    if _valid_probe_value(label):
        return _casefold(label)
    return _casefold(str(value) if value is not None else "")


def _language_list_key(value) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(sorted(_casefold(v) for v in value if isinstance(v, str) and v.strip()))
    if isinstance(value, str) and value.strip():
        return (_casefold(value),)
    return tuple()


def _runtime_value_changed(current, candidate) -> bool:
    current_num = _positive_int(current)
    candidate_num = _positive_int(candidate)
    if current_num is None or candidate_num is None:
        return current != candidate
    return abs(current_num - candidate_num) > _RUNTIME_DIFF_TOLERANCE_MIN


def _casefold(value) -> str:
    return str(value or "").strip().casefold()


def _average_positive_int(values: list) -> int | None:
    positive = [int(v) for v in values if isinstance(v, int) and v > 0]
    if not positive:
        return None
    return int(round(sum(positive) / len(positive)))


def _audio_channels_from_stream(stream: dict) -> str | None:
    channels = _positive_int(stream.get("channels"))
    layout = _clean_str(stream.get("channel_layout"))
    if channels == 8:
        return "7.1"
    if channels == 6:
        return "5.1"
    if channels == 2:
        return "2.0"
    if channels == 1:
        return "1.0"
    return normalize_audio_channels(layout)


def _runtime_minutes(value) -> int | None:
    try:
        seconds = float(value)
    except Exception:
        return None
    if seconds <= 0:
        return None
    return int(round(seconds / 60.0))


def _positive_int(value) -> int | None:
    try:
        num = int(float(str(value).strip()))
    except Exception:
        return None
    return num if num > 0 else None


def _number(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _clean_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _valid_probe_value(value) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if value == []:
        return False
    if isinstance(value, str) and _is_unknown(value):
        return False
    return True


def _is_unknown(value) -> bool:
    return isinstance(value, str) and value.strip().lower() == "unknown"


def _score_value(item: dict) -> int | None:
    q = item.get("quality")
    if not isinstance(q, dict):
        return None
    try:
        return int(round(float(q.get("score"))))
    except Exception:
        return None


def _append_field(fields: list[str], field: str) -> list[str]:
    return sorted(set([*fields, field]))
