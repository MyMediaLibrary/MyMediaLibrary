from __future__ import annotations

from typing import Any


UNKNOWN_LANGUAGE_LABELS = {"UNKNOWN", "INCONNU", "INCONNUE", "UNK"}
LEGACY_VIDEO_CODECS = {"MPEG-2", "MPEG-4", "VC-1", "XVID", "DIVX"}
MODERN_VIDEO_CODECS = {"AV1", "H.265", "HEVC", "X265"}
AVC_VIDEO_CODECS = {"H.264", "AVC", "X264"}


def _as_upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _size_gb(item: dict) -> float | None:
    size_b = item.get("size_b")
    if isinstance(size_b, (int, float)) and size_b > 0:
        return float(size_b) / (1024 ** 3)
    return None


def _video_codec_family(item: dict) -> str:
    codec = _as_upper(item.get("codec"))
    if codec in MODERN_VIDEO_CODECS:
        return "modern"
    if codec in AVC_VIDEO_CODECS:
        return "avc"
    if codec in LEGACY_VIDEO_CODECS:
        return "legacy"
    return "unknown"


def _resolution_score_and_bucket(item: dict) -> tuple[int, str]:
    resolution = _as_upper(item.get("resolution"))
    if resolution in {"4K", "2160P", "UHD"}:
        return 25, "4k"
    if resolution == "1080P":
        return 20, "1080p"
    if resolution == "720P":
        return 10, "720p"
    if resolution in {"SD", "480P", "576P"}:
        return 5, "sd"
    return 8, "unknown"


def _hdr_score(item: dict) -> int:
    hdr_type = _as_upper(item.get("hdr_type"))
    hdr_flag = bool(item.get("hdr"))

    if "DOLBY" in hdr_type or "DV" == hdr_type:
        return 10
    if "HDR10+" in hdr_type:
        return 8
    if "HDR10" in hdr_type or "HLG" in hdr_type:
        return 5
    if hdr_flag:
        return 5
    return 0


def compute_video_quality_score(item: dict) -> dict:
    resolution_score, _ = _resolution_score_and_bucket(item)

    family = _video_codec_family(item)
    if family == "modern":
        codec_score = 15
    elif family == "avc":
        codec_score = 10
    elif family == "legacy":
        codec_score = 3
    else:
        codec_score = 6

    hdr_score = _hdr_score(item)
    total = resolution_score + codec_score + hdr_score

    return {
        "score": total,
        "resolution": resolution_score,
        "codec": codec_score,
        "hdr": hdr_score,
        "resolution_score": resolution_score,
        "video_codec_family": family,
    }


def compute_audio_quality_score(item: dict) -> int:
    raw = _as_upper(item.get("audio_codec_raw"))
    normalized = _as_upper(item.get("audio_codec"))
    display = _as_upper(item.get("audio_codec_display"))
    audio_ref = " ".join([raw, normalized, display])

    if "ATMOS" in audio_ref or "TRUEHD" in audio_ref:
        return 20
    if "DTS-HD" in audio_ref:
        return 18
    if "DTS" in audio_ref:
        return 15
    if "DOLBY DIGITAL PLUS" in audio_ref or "EAC3" in audio_ref or "E-AC-3" in audio_ref:
        return 12
    if "DOLBY DIGITAL" in audio_ref or "AC3" in audio_ref or "AC-3" in audio_ref:
        return 10
    if "AAC" in audio_ref:
        return 6
    if "MP3" in audio_ref or "MP2" in audio_ref:
        return 3
    return 8


def compute_language_quality_score(item: dict) -> int:
    simple = _as_upper(item.get("audio_languages_simple"))
    if simple == "MULTI":
        return 15
    if simple == "VF":
        return 10
    if simple == "VO":
        return 5
    if simple in UNKNOWN_LANGUAGE_LABELS or not simple:
        return 3
    return 3


def compute_size_quality_score(item: dict) -> int:
    size_gb = _size_gb(item)
    if size_gb is None:
        return 5

    resolution_score, bucket = _resolution_score_and_bucket(item)
    codec_family = _video_codec_family(item)

    if bucket == "1080p":
        if codec_family == "modern":
            if size_gb < 2:
                return 5
            if size_gb <= 10:
                return 15
            return 8
        if codec_family == "avc":
            if size_gb < 4:
                return 5
            if size_gb <= 15:
                return 15
            return 8
        if codec_family == "legacy":
            return 5
        return 5

    if bucket == "4k":
        if codec_family == "modern":
            if size_gb < 8:
                return 5
            if size_gb <= 25:
                return 15
            return 8
        if codec_family == "avc":
            if size_gb < 15:
                return 5
            if size_gb <= 30:
                return 15
            return 8
        return 5

    if bucket == "720p":
        if size_gb < 2:
            return 5
        if size_gb <= 6:
            return 15
        return 8

    if bucket == "sd":
        if size_gb < (500 / 1024):
            return 5
        if size_gb <= 2:
            return 15
        return 8

    if resolution_score == 8:
        return 5

    return 5


def compute_quality_penalties(item: dict, partial_scores: dict) -> list[dict]:
    penalties: list[dict] = []

    video_score = int(partial_scores.get("video", 0))
    audio_score = int(partial_scores.get("audio", 0))
    language_score = int(partial_scores.get("languages", 0))
    size_score = int(partial_scores.get("size", 0))
    resolution_score = int(partial_scores.get("video_details", {}).get("resolution_score", 0))
    video_codec_family = partial_scores.get("video_details", {}).get("video_codec_family")

    if video_score >= 40 and audio_score <= 6:
        penalties.append({"code": "audio_video_mismatch", "value": 10})
    elif video_score >= 35 and audio_score < 10:
        penalties.append({"code": "audio_video_imbalance", "value": 5})

    if resolution_score >= 20 and video_codec_family == "legacy":
        penalties.append({"code": "legacy_codec_high_res", "value": 8})
    elif resolution_score == 10 and video_codec_family == "legacy":
        penalties.append({"code": "legacy_codec_mid_res", "value": 4})

    if video_score >= 40 and language_score <= 5:
        penalties.append({"code": "premium_video_weak_languages", "value": 5})

    if size_score == 5 and video_score >= 35:
        penalties.append({"code": "size_video_mismatch", "value": 5})

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


def compute_quality(item: dict) -> dict:
    video_details = compute_video_quality_score(item)
    video_score = int(video_details["score"])
    audio_score = int(compute_audio_quality_score(item))
    language_score = int(compute_language_quality_score(item))
    size_score = int(compute_size_quality_score(item))

    base_score = video_score + audio_score + language_score + size_score

    partial_scores = {
        "video": video_score,
        "audio": audio_score,
        "languages": language_score,
        "size": size_score,
        "video_details": video_details,
    }
    penalties = compute_quality_penalties(item, partial_scores)
    penalty_total = min(sum(int(p.get("value", 0)) for p in penalties), 20)
    final_score = max(0, min(100, base_score - penalty_total))

    return {
        "score": final_score,
        "level": get_quality_level(final_score),
        "base_score": base_score,
        "penalty_total": penalty_total,
        "video": video_score,
        "audio": audio_score,
        "languages": language_score,
        "size": size_score,
        "penalties": penalties,
    }
