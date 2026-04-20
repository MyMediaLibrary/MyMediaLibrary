from __future__ import annotations

import copy
from typing import Any


UNKNOWN_LANGUAGE_LABELS = {"UNKNOWN", "INCONNU", "INCONNUE", "UNK"}
LEGACY_VIDEO_CODECS = {"MPEG-2", "MPEG-4", "VC-1", "XVID", "DIVX"}
MODERN_VIDEO_CODECS = {"AV1", "H.265", "HEVC", "X265"}
AVC_VIDEO_CODECS = {"H.264", "AVC", "X264"}


DEFAULT_SCORE_CONFIG: dict[str, Any] = {
    "enabled": True,
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
    "penalties": {
        "max_total": 20,
        "rules": {
            "video_excellent_audio_low": {
                "strong": -10,
                "medium": -5,
            },
            "high_resolution_legacy_codec": {
                "strong": -8,
                "medium": -4,
            },
            "good_video_few_languages": -5,
            "size_incoherent": -5,
        },
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


def _resolve_penalty_value(rule_config: Any, severity: str | None = None) -> int:
    value = 0.0
    if isinstance(rule_config, dict):
        if severity and severity in rule_config:
            value = _as_float(rule_config.get(severity), 0.0)
        elif "default" in rule_config:
            value = _as_float(rule_config.get("default"), 0.0)
    elif isinstance(rule_config, (int, float)):
        value = float(rule_config)
    return abs(_as_int(value, 0))


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


def compute_quality_penalties(item: dict, partial_scores: dict, score_config: dict[str, Any] | None = None) -> list[dict]:
    del item  # reserved for future rules requiring raw item context

    cfg = _resolve_score_config(score_config)
    penalties_cfg = cfg.get("penalties") if isinstance(cfg.get("penalties"), dict) else {}
    rules = penalties_cfg.get("rules") if isinstance(penalties_cfg.get("rules"), dict) else {}

    penalties: list[dict[str, int | str]] = []

    video_score = int(partial_scores.get("video", 0))
    audio_score = int(partial_scores.get("audio", 0))
    language_score = int(partial_scores.get("languages", 0))
    size_status = str(partial_scores.get("size_status") or "")
    size_score = int(partial_scores.get("size", 0))
    resolution_score = int(partial_scores.get("video_details", {}).get("resolution_score", 0))
    video_codec_family = str(partial_scores.get("video_details", {}).get("video_codec_family") or "")

    r = rules.get("video_excellent_audio_low")
    if video_score >= 40 and audio_score <= 6:
        v = _resolve_penalty_value(r, "strong")
        if v:
            penalties.append({"code": "video_excellent_audio_low", "value": v})
    elif video_score >= 35 and audio_score < 10:
        v = _resolve_penalty_value(r, "medium")
        if v:
            penalties.append({"code": "video_excellent_audio_low", "value": v})

    r = rules.get("high_resolution_legacy_codec")
    if resolution_score >= 20 and video_codec_family == "legacy":
        v = _resolve_penalty_value(r, "strong")
        if v:
            penalties.append({"code": "high_resolution_legacy_codec", "value": v})
    elif resolution_score == 10 and video_codec_family == "legacy":
        v = _resolve_penalty_value(r, "medium")
        if v:
            penalties.append({"code": "high_resolution_legacy_codec", "value": v})

    if video_score >= 40 and language_score <= 5:
        v = _resolve_penalty_value(rules.get("good_video_few_languages"), None)
        if v:
            penalties.append({"code": "good_video_few_languages", "value": v})

    if (size_status in {"too_small", "too_large"} or (not size_status and size_score <= 5)) and video_score >= 35:
        v = _resolve_penalty_value(rules.get("size_incoherent"), None)
        if v:
            penalties.append({"code": "size_incoherent", "value": v})

    return penalties


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
    video_score = int(video_details["score"])
    audio_score = int(compute_audio_quality_score(item, cfg))
    language_score = int(compute_language_quality_score(item, cfg))
    size_details = _compute_size_quality_details(item, cfg)
    size_score = int(size_details.get("score", 0))

    base_score = video_score + audio_score + language_score + size_score

    partial_scores = {
        "video": video_score,
        "audio": audio_score,
        "languages": language_score,
        "size": size_score,
        "size_status": size_details.get("status"),
        "video_details": video_details,
    }
    penalties = compute_quality_penalties(item, partial_scores, cfg)

    penalties_cfg = cfg.get("penalties") if isinstance(cfg.get("penalties"), dict) else {}
    max_total = abs(_as_int(penalties_cfg.get("max_total"), 20))
    penalty_total = min(sum(abs(_as_int(p.get("value"), 0)) for p in penalties), max_total)

    final_score = _as_int(base_score - penalty_total, 0)
    final_score = max(0, min(100, final_score))

    return {
        "score": final_score,
        "base_score": _as_int(base_score, 0),
        "penalty_total": _as_int(penalty_total, 0),
        "video": _as_int(video_score, 0),
        "audio": _as_int(audio_score, 0),
        "languages": _as_int(language_score, 0),
        "size": _as_int(size_score, 0),
        "penalties": penalties,
        "score_details": {
            "video": _as_int(video_score, 0),
            "audio": _as_int(audio_score, 0),
            "languages": _as_int(language_score, 0),
            "size": _as_int(size_score, 0),
        },
    }
