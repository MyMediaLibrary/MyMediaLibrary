from __future__ import annotations

import copy
from typing import Any


UNKNOWN_LANGUAGE_LABELS = {"UNKNOWN", "INCONNU", "INCONNUE", "UNK"}
LEGACY_VIDEO_CODECS = {"MPEG-2", "MPEG-4", "VC-1", "XVID", "DIVX"}
MODERN_VIDEO_CODECS = {"AV1", "H.265", "HEVC", "X265"}
AVC_VIDEO_CODECS = {"H.264", "AVC", "X264"}


DEFAULT_SCORE_CONFIG: dict[str, Any] = {
    "weights": {
        "video": 50,
        "audio": 20,
        "languages": 15,
        "size": 15,
    },
    "video": {
        "resolution": {
            "2160p": 25,
            "1080p": 20,
            "720p": 10,
            "sd": 5,
            "unknown": 8,
            "default": 8,
        },
        "codec": {
            "av1": 15,
            "hevc": 15,
            "h265": 15,
            "h264": 10,
            "avc": 10,
            "mpeg2": 3,
            "vc1": 3,
            "xvid": 3,
            "divx": 3,
            "unknown": 6,
            "default": 6,
        },
        "hdr": {
            "dolby_vision": 10,
            "hdr10plus": 8,
            "hdr10": 5,
            "hlg": 5,
            "sdr": 0,
            "unknown": 0,
            "default": 0,
        },
    },
    "audio": {
        "codec": {
            "truehd_atmos": 20,
            "dts_hd": 18,
            "dts": 15,
            "eac3": 12,
            "ac3": 10,
            "aac": 6,
            "mp3_mp2": 3,
            "unknown": 8,
            "default": 8,
        }
    },
    "languages": {
        "profile": {
            "multi": 15,
            "french_only": 10,
            "vo": 5,
            "unknown": 3,
            "default": 3,
        }
    },
    "size": {
        "points": {
            "coherent": 15,
            "too_large": 8,
            "too_small": 5,
            "unknown": 5,
            "default": 5,
        },
        "profiles": {
            "movie": {
                "2160p": {
                    "hevc": {"min_gb": 8, "max_gb": 25},
                    "default": {"min_gb": 8, "max_gb": 25},
                },
                "1080p": {
                    "hevc": {"min_gb": 2, "max_gb": 10},
                    "h264": {"min_gb": 4, "max_gb": 15},
                    "default": {"min_gb": 2, "max_gb": 15},
                },
                "720p": {
                    "default": {"min_gb": 2, "max_gb": 6},
                },
                "sd": {
                    "default": {"min_gb": 0.5, "max_gb": 2},
                },
                "unknown": {
                    "default": {"min_gb": 0.5, "max_gb": 15},
                },
                "default": {
                    "default": {"min_gb": 1, "max_gb": 15},
                },
            },
            "series": {
                "2160p": {
                    "hevc": {"min_gb": 2, "max_gb": 8},
                    "default": {"min_gb": 2, "max_gb": 8},
                },
                "1080p": {
                    "hevc": {"min_gb": 0.35, "max_gb": 3},
                    "h264": {"min_gb": 0.5, "max_gb": 4},
                    "default": {"min_gb": 0.35, "max_gb": 4},
                },
                "720p": {
                    "default": {"min_gb": 0.2, "max_gb": 1.5},
                },
                "sd": {
                    "default": {"min_gb": 0.15, "max_gb": 1},
                },
                "unknown": {
                    "default": {"min_gb": 0.15, "max_gb": 4},
                },
                "default": {
                    "default": {"min_gb": 0.15, "max_gb": 4},
                },
            },
        },
    },
    "max_score": {
        "max_video": 50,
        "max_audio": 20,
        "max_languages": 15,
        "max_size": 15,
    },
}


def get_builtin_score_defaults() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_SCORE_CONFIG)


def _resolve_score_config(score_config: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(score_config, dict):
        return score_config
    return DEFAULT_SCORE_CONFIG


def _as_upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return fallback


def _size_gb(item: dict) -> float | None:
    size_b = item.get("size_b")
    if isinstance(size_b, (int, float)) and size_b > 0:
        return float(size_b) / (1024 ** 3)
    return None


def _resolution_bucket(item: dict) -> str:
    resolution = _as_upper(item.get("resolution"))
    if resolution in {"4K", "2160P", "UHD"}:
        return "2160p"
    if resolution == "1080P":
        return "1080p"
    if resolution == "720P":
        return "720p"
    if resolution in {"SD", "480P", "576P"}:
        return "sd"
    if not resolution or resolution == "UNKNOWN":
        return "unknown"
    return resolution.lower()


def _video_codec_key(item: dict) -> str:
    codec = _as_upper(item.get("codec"))
    if codec == "AV1":
        return "av1"
    if codec in {"HEVC", "H.265", "X265"}:
        return "hevc"
    if codec in {"H265"}:
        return "h265"
    if codec in {"H.264", "X264"}:
        return "h264"
    if codec == "AVC":
        return "avc"
    if codec in {"MPEG-2", "MPEG2"}:
        return "mpeg2"
    if codec in {"VC-1", "VC1"}:
        return "vc1"
    if codec == "XVID":
        return "xvid"
    if codec == "DIVX":
        return "divx"
    if not codec or codec == "UNKNOWN":
        return "unknown"
    return codec.lower().replace(" ", "_")


def _video_codec_family_from_key(codec_key: str) -> str:
    if codec_key in {"av1", "hevc", "h265"}:
        return "modern"
    if codec_key in {"h264", "avc"}:
        return "avc"
    if codec_key in {"mpeg2", "vc1", "xvid", "divx"}:
        return "legacy"
    return "unknown"


def _audio_codec_key(item: dict) -> str:
    raw = _as_upper(item.get("audio_codec_raw"))
    normalized = _as_upper(item.get("audio_codec"))
    display = _as_upper(item.get("audio_codec_display"))
    audio_ref = " ".join([raw, normalized, display])

    if "ATMOS" in audio_ref or "TRUEHD" in audio_ref:
        return "truehd_atmos"
    if "DTS-HD" in audio_ref:
        return "dts_hd"
    if "DTS" in audio_ref:
        return "dts"
    if "DOLBY DIGITAL PLUS" in audio_ref or "EAC3" in audio_ref or "E-AC-3" in audio_ref:
        return "eac3"
    if "DOLBY DIGITAL" in audio_ref or "AC3" in audio_ref or "AC-3" in audio_ref:
        return "ac3"
    if "AAC" in audio_ref:
        return "aac"
    if "MP3" in audio_ref or "MP2" in audio_ref:
        return "mp3_mp2"
    if not audio_ref.strip() or "UNKNOWN" in audio_ref:
        return "unknown"
    return "unknown"


def _language_profile_key(item: dict) -> str:
    simple = _as_upper(item.get("audio_languages_simple"))
    if simple == "MULTI":
        return "multi"
    if simple == "VF":
        return "french_only"
    if simple == "VO":
        return "vo"
    if simple in UNKNOWN_LANGUAGE_LABELS or not simple:
        return "unknown"
    return "unknown"


def _hdr_key(item: dict) -> str:
    hdr_type = _as_upper(item.get("hdr_type"))
    hdr_flag = bool(item.get("hdr"))

    if "DOLBY" in hdr_type or hdr_type == "DV":
        return "dolby_vision"
    if "HDR10+" in hdr_type:
        return "hdr10plus"
    if "HDR10" in hdr_type:
        return "hdr10"
    if "HLG" in hdr_type:
        return "hlg"
    if hdr_flag:
        return "hdr10"
    if hdr_type and hdr_type not in {"SDR"}:
        return "unknown"
    return "sdr"


def _lookup_number(table: Any, key: str, *, fallback: float = 0.0) -> float:
    if not isinstance(table, dict):
        return fallback
    if key in table:
        return _as_float(table.get(key), fallback)
    if "default" in table:
        return _as_float(table.get("default"), fallback)
    return fallback


def _max_table_value(table: Any, *, fallback: float = 0.0) -> float:
    if not isinstance(table, dict):
        return fallback
    best = None
    for value in table.values():
        if isinstance(value, (int, float)):
            numeric = _as_float(value, fallback)
            if best is None or numeric > best:
                best = numeric
    if best is None:
        return fallback
    return best


def _score_component_maxima(score_config: dict[str, Any]) -> dict[str, float]:
    video_cfg = score_config.get("video") if isinstance(score_config.get("video"), dict) else {}
    audio_cfg = score_config.get("audio") if isinstance(score_config.get("audio"), dict) else {}
    langs_cfg = score_config.get("languages") if isinstance(score_config.get("languages"), dict) else {}
    size_cfg = score_config.get("size") if isinstance(score_config.get("size"), dict) else {}

    video_max = (
        _max_table_value(video_cfg.get("resolution"), fallback=0.0)
        + _max_table_value(video_cfg.get("codec"), fallback=0.0)
        + _max_table_value(video_cfg.get("hdr"), fallback=0.0)
    )
    return {
        "video": max(0.0, video_max),
        "audio": max(0.0, _max_table_value(audio_cfg.get("codec"), fallback=0.0)),
        "languages": max(0.0, _max_table_value(langs_cfg.get("profile"), fallback=0.0)),
        "size": max(0.0, _max_table_value(size_cfg.get("points"), fallback=0.0)),
    }


def _size_profile_type_key(item: dict) -> str:
    return "series" if str(item.get("type") or "").strip().lower() == "tv" else "movie"


def _size_profile_codec_key(video_codec_key: str) -> str:
    if video_codec_key in {"hevc", "h265", "av1"}:
        return "hevc"
    if video_codec_key in {"h264", "avc"}:
        return "h264"
    return "default"


def _resolve_size_threshold(size_profiles: Any, content_type: str, resolution_key: str, codec_key: str) -> dict[str, float] | None:
    if not isinstance(size_profiles, dict):
        return None

    type_table = size_profiles.get(content_type)
    if not isinstance(type_table, dict):
        type_table = size_profiles.get("default")
    if not isinstance(type_table, dict):
        return None

    res_table = type_table.get(resolution_key)
    if not isinstance(res_table, dict):
        res_table = type_table.get("default")
    if not isinstance(res_table, dict):
        return None

    threshold = res_table.get(codec_key)
    if not isinstance(threshold, dict):
        threshold = res_table.get("default")
    if not isinstance(threshold, dict):
        return None

    min_gb = _as_float(threshold.get("min_gb"), 0.0)
    max_gb = _as_float(threshold.get("max_gb"), min_gb)
    if max_gb < min_gb:
        max_gb = min_gb
    return {"min_gb": min_gb, "max_gb": max_gb}


def _compute_size_quality_details(item: dict, score_config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _resolve_score_config(score_config)
    size_cfg = cfg.get("size") if isinstance(cfg.get("size"), dict) else {}
    points = size_cfg.get("points") if isinstance(size_cfg.get("points"), dict) else {}

    size_gb = _size_gb(item)
    if size_gb is None:
        score = _as_int(_lookup_number(points, "unknown", fallback=0), 0)
        return {"score": score, "status": "unknown", "size_gb": None}

    resolution_key = _resolution_bucket(item)
    video_codec_key = _video_codec_key(item)
    content_type = _size_profile_type_key(item)
    profile_codec_key = _size_profile_codec_key(video_codec_key)
    threshold = _resolve_size_threshold(size_cfg.get("profiles"), content_type, resolution_key, profile_codec_key)

    if not threshold:
        score = _as_int(_lookup_number(points, "unknown", fallback=0), 0)
        return {"score": score, "status": "unknown", "size_gb": size_gb}

    min_gb = threshold["min_gb"]
    max_gb = threshold["max_gb"]
    if size_gb < min_gb:
        status = "too_small"
    elif size_gb <= max_gb:
        status = "coherent"
    else:
        status = "too_large"

    score = _as_int(_lookup_number(points, status, fallback=0), 0)
    return {
        "score": score,
        "status": status,
        "size_gb": size_gb,
        "min_gb": min_gb,
        "max_gb": max_gb,
    }


def compute_video_quality_score(item: dict, score_config: dict[str, Any] | None = None) -> dict:
    cfg = _resolve_score_config(score_config)
    video_cfg = cfg.get("video") if isinstance(cfg.get("video"), dict) else {}

    resolution_key = _resolution_bucket(item)
    codec_key = _video_codec_key(item)
    hdr_key = _hdr_key(item)

    resolution_score = _as_int(_lookup_number(video_cfg.get("resolution"), resolution_key, fallback=0), 0)
    codec_score = _as_int(_lookup_number(video_cfg.get("codec"), codec_key, fallback=0), 0)
    hdr_score = _as_int(_lookup_number(video_cfg.get("hdr"), hdr_key, fallback=0), 0)

    total = resolution_score + codec_score + hdr_score

    return {
        "score": total,
        "resolution": resolution_score,
        "codec": codec_score,
        "hdr": hdr_score,
        "resolution_score": resolution_score,
        "video_codec_family": _video_codec_family_from_key(codec_key),
    }


def compute_audio_quality_score(item: dict, score_config: dict[str, Any] | None = None) -> int:
    cfg = _resolve_score_config(score_config)
    audio_cfg = cfg.get("audio") if isinstance(cfg.get("audio"), dict) else {}
    key = _audio_codec_key(item)
    return _as_int(_lookup_number(audio_cfg.get("codec"), key, fallback=0), 0)


def compute_language_quality_score(item: dict, score_config: dict[str, Any] | None = None) -> int:
    cfg = _resolve_score_config(score_config)
    langs_cfg = cfg.get("languages") if isinstance(cfg.get("languages"), dict) else {}
    key = _language_profile_key(item)
    return _as_int(_lookup_number(langs_cfg.get("profile"), key, fallback=0), 0)


def compute_size_quality_score(item: dict, score_config: dict[str, Any] | None = None) -> int:
    return int(_compute_size_quality_details(item, score_config).get("score", 0))


def get_max_video_score(score_config: dict[str, Any] | None = None) -> int:
    cfg = _resolve_score_config(score_config)
    max_score = cfg.get("max_score") if isinstance(cfg.get("max_score"), dict) else {}
    if isinstance(max_score.get("max_video"), (int, float)):
        return _as_int(max_score.get("max_video"), 0)
    # Backward-compatible fallback for legacy configs without max_score.
    maxima = _score_component_maxima(cfg)
    return _as_int(maxima.get("video"), 0)


def get_max_audio_score(score_config: dict[str, Any] | None = None) -> int:
    cfg = _resolve_score_config(score_config)
    max_score = cfg.get("max_score") if isinstance(cfg.get("max_score"), dict) else {}
    if isinstance(max_score.get("max_audio"), (int, float)):
        return _as_int(max_score.get("max_audio"), 0)
    # Backward-compatible fallback for legacy configs without max_score.
    maxima = _score_component_maxima(cfg)
    return _as_int(maxima.get("audio"), 0)


def get_max_languages_score(score_config: dict[str, Any] | None = None) -> int:
    cfg = _resolve_score_config(score_config)
    max_score = cfg.get("max_score") if isinstance(cfg.get("max_score"), dict) else {}
    if isinstance(max_score.get("max_languages"), (int, float)):
        return _as_int(max_score.get("max_languages"), 0)
    # Backward-compatible fallback for legacy configs without max_score.
    maxima = _score_component_maxima(cfg)
    return _as_int(maxima.get("languages"), 0)


def get_max_size_score(score_config: dict[str, Any] | None = None) -> int:
    cfg = _resolve_score_config(score_config)
    max_score = cfg.get("max_score") if isinstance(cfg.get("max_score"), dict) else {}
    if isinstance(max_score.get("max_size"), (int, float)):
        return _as_int(max_score.get("max_size"), 0)
    # Backward-compatible fallback for legacy configs without max_score.
    maxima = _score_component_maxima(cfg)
    return _as_int(maxima.get("size"), 0)


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
    weights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    v_resolution = _as_int(video_resolution, 0)
    v_codec = _as_int(video_codec, 0)
    v_hdr = _as_int(video_hdr, 0)
    weights = weights if isinstance(weights, dict) else {}
    w_video = _as_float(weights.get("video"), 0.0)
    w_audio = _as_float(weights.get("audio"), 0.0)
    w_languages = _as_float(weights.get("languages"), 0.0)
    w_size = _as_float(weights.get("size"), 0.0)

    max_video = max(0.0, _as_float(max_video_score, 0.0))
    max_audio = max(0.0, _as_float(max_audio_score, 0.0))
    max_languages = max(0.0, _as_float(max_languages_score, 0.0))
    max_size = max(0.0, _as_float(max_size_score, 0.0))

    video = int(v_resolution + v_codec + v_hdr)
    a_score = _as_int(audio, 0)
    l_score = _as_int(languages, 0)
    s_score = _as_int(size, 0)

    video_w = float((video / max_video) * w_video) if max_video > 0 else 0.0
    audio_w = float((a_score / max_audio) * w_audio) if max_audio > 0 else 0.0
    languages_w = float((l_score / max_languages) * w_languages) if max_languages > 0 else 0.0
    size_w = float((s_score / max_size) * w_size) if max_size > 0 else 0.0
    score = int(round(video_w + audio_w + languages_w + size_w))

    return {
        "score": score,
        "video": video,
        "video_w": round(video_w, 4),
        "audio": a_score,
        "audio_w": round(audio_w, 4),
        "languages": l_score,
        "languages_w": round(languages_w, 4),
        "size": s_score,
        "size_w": round(size_w, 4),
        "video_details": {
            "resolution": v_resolution,
            "codec": v_codec,
            "hdr": v_hdr,
        },
    }


def get_quality_level(score: int) -> int:
    if score <= 20:
        return 1
    if score <= 40:
        return 2
    if score <= 60:
        return 3
    if score <= 80:
        return 4
    return 5


def compute_quality(item: dict, score_config: dict[str, Any] | None = None) -> dict:
    cfg = _resolve_score_config(score_config)

    video_details = compute_video_quality_score(item, cfg)
    audio_score = int(compute_audio_quality_score(item, cfg))
    language_score = int(compute_language_quality_score(item, cfg))
    size_details = _compute_size_quality_details(item, cfg)
    size_score = int(size_details.get("score", 0))

    video_resolution = _as_int(video_details.get("resolution"), 0)
    video_codec = _as_int(video_details.get("codec"), 0)
    video_hdr = _as_int(video_details.get("hdr"), 0)
    weights = cfg.get("weights") if isinstance(cfg.get("weights"), dict) else {}
    return build_quality_block(
        video_resolution=video_resolution,
        video_codec=video_codec,
        video_hdr=video_hdr,
        audio=audio_score,
        languages=language_score,
        size=size_score,
        max_video_score=get_max_video_score(cfg),
        max_audio_score=get_max_audio_score(cfg),
        max_languages_score=get_max_languages_score(cfg),
        max_size_score=get_max_size_score(cfg),
        weights=weights,
    )
