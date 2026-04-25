from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = 1
PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}
TYPE_RANK = {"data": 5, "quality": 4, "space": 3, "languages": 2, "series": 1}
UNKNOWN_VALUES = {"", "unknown", "inconnu", "none", "null", "n/a", "na", "?"}


def ensure_user_rules(default_rules_path: str | Path, user_rules_path: str | Path) -> bool:
    src = Path(default_rules_path)
    dst = Path(user_rules_path)
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copyfile(src, dst)
    else:
        dst.write_text('{"version":1,"rules":[]}\n', encoding="utf-8")
    return True


def load_rules(path: str | Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict) and r.get("enabled", True) is not False]


def write_recommendations(items: list[dict], output_path: str | Path, now: datetime | None = None) -> dict:
    ts = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    doc = {"generated_at": ts, "version": VERSION, "items": items}
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(out)
    return doc


def generate_recommendations(
    library_doc: dict,
    rules: list[dict],
    *,
    max_per_media: int = 3,
) -> list[dict]:
    media_items = library_doc.get("items") if isinstance(library_doc, dict) else []
    if not isinstance(media_items, list):
        return []
    recs: list[dict] = []
    for item in media_items:
        if not isinstance(item, dict):
            continue
        recs.extend(data_recommendations(item))
        recs.extend(series_recommendations(item))
        recs.extend(json_rule_recommendations(item, rules))
    deduped = dedupe_recommendations(recs)
    grouped = group_series_recommendations(deduped)
    return limit_noise(grouped, max_per_media=max_per_media)


def media_id(item: dict) -> str:
    raw = item.get("id")
    if raw not in (None, ""):
        return str(raw)
    typ = str(item.get("type") or "media")
    path = str(item.get("path") or item.get("title") or "unknown")
    return f"{typ}:{path}"


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number


def _score(item: dict) -> int | None:
    val = _get_field(item, "quality.score")
    number = _safe_float(val)
    return int(round(number)) if number is not None else None


def _size_gb(item: dict) -> float:
    number = _safe_float(item.get("size_gb"))
    if number is not None:
        return round(number, 1)
    size_b = _safe_float(item.get("size_b"))
    if size_b is None:
        return 0.0
    return round(size_b / (1024 ** 3), 1)


def _display(item: dict) -> dict:
    return {
        "title": item.get("title"),
        "year": item.get("year"),
        "score": _score(item),
        "size_gb": _size_gb(item),
        "resolution": item.get("resolution"),
    }


def make_rec(
    item: dict,
    *,
    rule_id: str,
    recommendation_type: str,
    priority: str,
    dedupe_group: str,
    severity: int,
    message: dict,
    suggested_action: dict,
    context: dict | None = None,
) -> dict:
    mid = media_id(item)
    return {
        "id": f"rec:{mid}:{rule_id}",
        "media_ref": {
            "id": mid,
            "type": item.get("type") or "media",
        },
        "display": _display(item),
        "recommendation_type": recommendation_type,
        "rule_id": rule_id,
        "priority": priority if priority in PRIORITY_RANK else "medium",
        "dedupe_group": dedupe_group,
        "severity": int(severity or 1),
        "context": context or {},
        "message": message,
        "suggested_action": suggested_action,
    }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in UNKNOWN_VALUES
    if isinstance(value, list):
        return len(value) == 0 or all(_is_missing(v) for v in value)
    return False


def _is_unknown(value: Any) -> bool:
    return _is_missing(value) or (isinstance(value, str) and value.strip().casefold() == "unknown")


def data_recommendations(item: dict) -> list[dict]:
    recs: list[dict] = []

    def add(rule_id, priority, severity, fr_msg, en_msg, fr_action, en_action, dedupe_group=None):
        recs.append(make_rec(
            item,
            rule_id=rule_id,
            recommendation_type="data",
            priority=priority,
            dedupe_group=dedupe_group or rule_id,
            severity=severity,
            message={"fr": fr_msg, "en": en_msg},
            suggested_action={"fr": fr_action, "en": en_action},
        ))

    if _is_unknown(item.get("resolution")):
        add("missing_resolution", "high", 2, "Résolution vidéo non détectée.", "Video resolution was not detected.", "Vérifier le fichier NFO ou relancer l’analyse du média.", "Check the NFO file or run the media scan again.")
    if _is_unknown(item.get("codec")):
        add("missing_video_codec", "high", 2, "Codec vidéo non détecté.", "Video codec was not detected.", "Vérifier les métadonnées vidéo du fichier.", "Check the video metadata of the file.")
    if _is_unknown(item.get("audio_codec")):
        add("missing_audio_codec", "medium", 1, "Codec audio non détecté.", "Audio codec was not detected.", "Vérifier les informations audio du fichier.", "Check the audio metadata of the file.")
    if _is_unknown(item.get("audio_channels")):
        add("missing_audio_channels", "medium", 1, "Nombre de canaux audio non détecté.", "Audio channel count was not detected.", "Vérifier les informations audio du fichier.", "Check the audio metadata of the file.")
    if not isinstance(item.get("audio_languages"), list) or _is_missing(item.get("audio_languages")):
        add("missing_audio_languages", "medium", 1, "Langues audio non détectées.", "Audio languages were not detected.", "Vérifier les pistes audio ou le fichier NFO.", "Check the audio tracks or the NFO file.")
    if _is_unknown(item.get("audio_languages_simple")):
        add("unknown_language", "medium", 1, "Langue audio impossible à classifier.", "Audio language could not be classified.", "Vérifier les métadonnées de langues audio.", "Check the audio language metadata.")
    if _is_unknown(item.get("audio_codec")) or _is_unknown(item.get("audio_channels")):
        add("unknown_audio_quality", "low", 1, "Qualité audio impossible à évaluer complètement.", "Audio quality could not be fully evaluated.", "Vérifier les métadonnées audio du média.", "Check the audio metadata of the media.", dedupe_group="unknown_audio_quality")
    if (_safe_float(item.get("size_b")) or 0) <= 0:
        add("missing_size", "high", 2, "Taille du fichier non détectée.", "File size was not detected.", "Vérifier l’accès au fichier et relancer un scan.", "Check file access and run a scan again.")
    if not isinstance(item.get("quality"), dict) or _score(item) is None:
        add("missing_score", "high", 2, "Score qualité absent.", "Quality score is missing.", "Relancer un scan avec le score qualité activé.", "Run a scan again with quality score enabled.")
    return recs


def _season_number(season: dict) -> int | None:
    for key in ("season", "season_number"):
        val = season.get(key)
        try:
            return int(val)
        except Exception:
            pass
    return None


def _dominant(values: list[Any]) -> Any:
    clean = [v for v in values if not _is_unknown(v)]
    if not clean:
        return None
    return Counter(clean).most_common(1)[0][0]


def _minority_seasons(seasons: list[dict], field: str) -> tuple[Any, list[dict]]:
    dominant = _dominant([s.get(field) for s in seasons if isinstance(s, dict)])
    if dominant is None:
        return None, []
    out = [s for s in seasons if isinstance(s, dict) and not _is_unknown(s.get(field)) and s.get(field) != dominant]
    return dominant, out


def _round_clean(value: float | int | None, digits: int = 1) -> float | int | None:
    if value is None:
        return None
    rounded = round(float(value), digits)
    return int(rounded) if rounded.is_integer() else rounded


def _fmt_value(value: Any, *, lang: str = "en") -> str:
    if value is None:
        return "?"
    numeric = isinstance(value, float)
    if isinstance(value, float):
        value = _round_clean(value)
    text = str(value)
    return text.replace(".", ",") if lang == "fr" and numeric else text


def _join_seasons_fr(seasons: list[int]) -> str:
    parts = [str(s) for s in seasons]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " et " + parts[-1]


def _join_seasons_en(seasons: list[int]) -> str:
    parts = [str(s) for s in seasons]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _series_msg(field_name: str, season: int | None, season_value: Any = None, dominant_value: Any = None) -> tuple[dict, dict]:
    s = season if season is not None else "?"
    messages = {
        "resolution": (
            f"La saison {s} est en {_fmt_value(season_value, lang='fr')} alors que la majorité de la série est en {_fmt_value(dominant_value, lang='fr')}.",
            f"Season {s} is in {_fmt_value(season_value)} while most of the series is in {_fmt_value(dominant_value)}.",
            f"Identifier la saison {s} et chercher une version alignée avec le reste de la série.",
            f"Review season {s} and look for a version aligned with the rest of the series.",
        ),
        "codec": (
            f"La saison {s} utilise le codec {_fmt_value(season_value, lang='fr')} alors que la majorité de la série utilise {_fmt_value(dominant_value, lang='fr')}.",
            f"Season {s} uses {_fmt_value(season_value)} while most of the series uses {_fmt_value(dominant_value)}.",
            f"Vérifier la saison {s}, surtout si elle utilise un codec ancien.",
            f"Review season {s}, especially if it uses an older codec.",
        ),
        "audio_channels": (
            f"La saison {s} est en audio {_fmt_value(season_value, lang='fr')} alors que la majorité de la série est en {_fmt_value(dominant_value, lang='fr')}.",
            f"Season {s} uses {_fmt_value(season_value)} audio while most of the series uses {_fmt_value(dominant_value)}.",
            f"Identifier la saison {s} avec un audio moins homogène.",
            f"Review season {s} for less consistent audio quality.",
        ),
        "audio_languages_simple": (
            f"La saison {s} est en {_fmt_value(season_value, lang='fr')} alors que la majorité de la série est en {_fmt_value(dominant_value, lang='fr')}.",
            f"Season {s} is {_fmt_value(season_value)} while most of the series is {_fmt_value(dominant_value)}.",
            f"Vérifier la saison {s}, notamment la présence du français.",
            f"Review season {s}, especially French audio availability.",
        ),
    }[field_name]
    return {"fr": messages[0], "en": messages[1]}, {"fr": messages[2], "en": messages[3]}


def series_recommendations(item: dict) -> list[dict]:
    if item.get("type") != "tv" or not isinstance(item.get("seasons"), list):
        return []
    seasons = [s for s in item.get("seasons") if isinstance(s, dict)]
    if len(seasons) < 2:
        return []
    recs: list[dict] = []
    field_rules = [
        ("resolution", "series_mixed_resolution", "season_resolution", "dominant_resolution"),
        ("codec", "series_mixed_video_codec", "season_video_codec", "dominant_video_codec"),
        ("audio_channels", "series_mixed_audio_channels", "season_audio_channels", "dominant_audio_channels"),
        ("audio_languages_simple", "series_mixed_languages", "season_audio_language_group", "dominant_audio_language_group"),
    ]
    for field, rule_id, season_key, dominant_key in field_rules:
        dominant, outliers = _minority_seasons(seasons, field)
        for season in outliers:
            sn = _season_number(season)
            msg, action = _series_msg(field, sn, season.get(field), dominant)
            recs.append(make_rec(
                item,
                rule_id=f"{rule_id}:s{sn}",
                recommendation_type="series",
                priority="medium",
                dedupe_group=f"{rule_id}:s{sn}",
                severity=1,
                message=msg,
                suggested_action=action,
                context={"season": sn, season_key: season.get(field), dominant_key: dominant},
            ))

    scored = [(s, _safe_float(_get_field(s, "quality.score"))) for s in seasons]
    scored = [(s, score) for s, score in scored if score is not None]
    for season, score in scored:
        others = [other_score for s, other_score in scored if s is not season]
        if not others:
            continue
        avg = sum(others) / len(others)
        delta = avg - score
        if delta >= 20:
            sn = _season_number(season)
            season_score = _round_clean(score)
            average_score = _round_clean(avg)
            delta_score = _round_clean(delta)
            recs.append(make_rec(
                item,
                rule_id=f"series_low_score_season:s{sn}",
                recommendation_type="series",
                priority="medium",
                dedupe_group=f"series_low_score_season:s{sn}",
                severity=2,
                message={
                    "fr": f"La saison {sn} a un score qualité de {_fmt_value(season_score, lang='fr')}, largement inférieur au score moyen de la série ({_fmt_value(average_score, lang='fr')}).",
                    "en": f"Season {sn} has a quality score of {_fmt_value(season_score)}, significantly lower than the series average score ({_fmt_value(average_score)}).",
                },
                suggested_action={"fr": f"Chercher une meilleure version de la saison {sn}.", "en": f"Look for a better version of season {sn}."},
                context={"season": sn, "season_score": season_score, "series_average_score": average_score, "delta": delta_score},
            ))

    sized = [(s, _safe_float(s.get("size_gb")) if s.get("size_gb") is not None else (_safe_float(s.get("size_b")) or 0) / (1024 ** 3)) for s in seasons]
    sized = [(s, size) for s, size in sized if size and size > 0]
    for season, size in sized:
        others = [other_size for s, other_size in sized if s is not season]
        if not others:
            continue
        avg = sum(others) / len(others)
        if avg > 0 and size >= avg * 2:
            sn = _season_number(season)
            season_size = _round_clean(size)
            average_size = _round_clean(avg)
            ratio = _round_clean(size / avg)
            recs.append(make_rec(
                item,
                rule_id=f"series_large_season:s{sn}",
                recommendation_type="series",
                priority="medium",
                dedupe_group=f"series_large_season:s{sn}",
                severity=1,
                message={
                    "fr": f"La saison {sn} pèse {_fmt_value(season_size, lang='fr')} Go, soit environ {_fmt_value(ratio, lang='fr')}x la taille moyenne des autres saisons ({_fmt_value(average_size, lang='fr')} Go).",
                    "en": f"Season {sn} is {_fmt_value(season_size)} GB, about {_fmt_value(ratio)}x the average size of the other seasons ({_fmt_value(average_size)} GB).",
                },
                suggested_action={"fr": f"Vérifier si la saison {sn} peut être optimisée.", "en": f"Check whether season {sn} can be optimized."},
                context={"season": sn, "season_size_gb": season_size, "average_other_seasons_size_gb": average_size, "ratio": ratio},
            ))
    return recs


def _flatten_rule_item(item: dict) -> dict:
    flat = dict(item)
    flat["score"] = _score(item)
    flat["size_gb"] = _size_gb(item)
    flat["video_codec"] = item.get("video_codec") or item.get("codec")
    flat["audio_language_group"] = item.get("audio_language_group") or item.get("audio_languages_simple")
    q = item.get("quality")
    if isinstance(q, dict):
        flat.setdefault("video_details", q.get("video_details"))
        flat.setdefault("audio_details", q.get("audio_details"))
    return flat


def _get_field(root: dict, dotted: str) -> Any:
    cur: Any = root
    for part in str(dotted).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur.get(part)
        else:
            return None
    return cur


def _contains(container: Any, value: Any) -> bool:
    if isinstance(container, list):
        return value in container
    if isinstance(container, str):
        return str(value).casefold() in container.casefold()
    return False


def condition_matches(item: dict, condition: dict) -> bool:
    field = condition.get("field")
    operator = condition.get("operator")
    expected = condition.get("value")
    value = _get_field(_flatten_rule_item(item), str(field))
    exists = value is not None
    missing = not exists or _is_missing(value)
    if operator == "exists":
        return exists and not missing
    if operator == "missing":
        return missing
    if missing:
        return False
    if operator == "=":
        return value == expected
    if operator == "!=":
        return value != expected
    if operator in {">", ">=", "<", "<="}:
        left = _safe_float(value)
        right = _safe_float(expected)
        if left is None or right is None:
            return False
        return {
            ">": left > right,
            ">=": left >= right,
            "<": left < right,
            "<=": left <= right,
        }[operator]
    if operator == "in":
        return isinstance(expected, list) and value in expected
    if operator == "not_in":
        return isinstance(expected, list) and value not in expected
    if operator == "contains":
        return _contains(value, expected)
    if operator == "not_contains":
        return not _contains(value, expected)
    return False


def json_rule_recommendations(item: dict, rules: list[dict]) -> list[dict]:
    recs = []
    for rule in rules:
        conditions = rule.get("conditions")
        if not isinstance(conditions, list):
            continue
        if not all(isinstance(c, dict) and condition_matches(item, c) for c in conditions):
            continue
        msg = rule.get("message")
        action = rule.get("suggested_action")
        if not (isinstance(msg, dict) and msg.get("fr") and msg.get("en") and isinstance(action, dict) and action.get("fr") and action.get("en")):
            continue
        recs.append(make_rec(
            item,
            rule_id=str(rule.get("id") or "json_rule"),
            recommendation_type=str(rule.get("type") or "quality"),
            priority=str(rule.get("priority") or "medium"),
            dedupe_group=str(rule.get("dedupe_group") or rule.get("id") or "json_rule"),
            severity=int(rule.get("severity") or 1),
            message={"fr": msg.get("fr"), "en": msg.get("en")},
            suggested_action={"fr": action.get("fr"), "en": action.get("en")},
        ))
    return recs


def _rec_sort_key(rec: dict) -> tuple[int, int, int]:
    return (
        PRIORITY_RANK.get(rec.get("priority"), 0),
        TYPE_RANK.get(rec.get("recommendation_type"), 0),
        int(rec.get("severity") or 0),
    )


def dedupe_recommendations(recs: list[dict]) -> list[dict]:
    by_rule: dict[tuple[str, str], dict] = {}
    for rec in recs:
        key = (rec.get("media_ref", {}).get("id"), rec.get("rule_id"))
        current = by_rule.get(key)
        if current is None or _rec_sort_key(rec) > _rec_sort_key(current):
            by_rule[key] = rec

    by_group: dict[tuple[str, str], dict] = {}
    for rec in by_rule.values():
        key = (rec.get("media_ref", {}).get("id"), rec.get("dedupe_group") or rec.get("rule_id"))
        current = by_group.get(key)
        if current is None or _rec_sort_key(rec) > _rec_sort_key(current):
            by_group[key] = rec
    return sorted(by_group.values(), key=lambda r: (str(r.get("media_ref", {}).get("id")), tuple(-v for v in _rec_sort_key(r)), str(r.get("rule_id"))))


SERIES_GROUP_FIELDS = {
    "series_mixed_resolution": ("season_resolution", "dominant_resolution"),
    "series_mixed_video_codec": ("season_video_codec", "dominant_video_codec"),
    "series_mixed_audio_channels": ("season_audio_channels", "dominant_audio_channels"),
    "series_mixed_languages": ("season_audio_language_group", "dominant_audio_language_group"),
}


def _base_series_rule_id(rule_id: str) -> str:
    return str(rule_id or "").split(":s", 1)[0]


def _series_group_key(rec: dict) -> tuple[str, str] | None:
    if rec.get("recommendation_type") != "series":
        return None
    base = _base_series_rule_id(str(rec.get("rule_id") or ""))
    if base not in SERIES_GROUP_FIELDS and base not in {"series_low_score_season", "series_large_season"}:
        return None
    media = rec.get("media_ref") or {}
    mid = media.get("id")
    if not mid:
        return None
    return str(mid), base


def _details_for_group(group: list[dict]) -> list[dict]:
    details = []
    for rec in group:
        ctx = rec.get("context") if isinstance(rec.get("context"), dict) else {}
        season = ctx.get("season")
        if season is None:
            continue
        detail = {"season": season}
        for key, value in ctx.items():
            if key != "season":
                detail[key] = value
        details.append(detail)
    return sorted(details, key=lambda d: (d.get("season") is None, d.get("season")))


def _same_context_value(details: list[dict], key: str) -> Any:
    values = [d.get(key) for d in details if d.get(key) is not None]
    if not values:
        return None
    first = values[0]
    return first if all(v == first for v in values) else None


def _grouped_series_message(base: str, seasons: list[int], details: list[dict]) -> tuple[dict, dict]:
    fr_seasons = _join_seasons_fr(seasons)
    en_seasons = _join_seasons_en(seasons)
    if base in SERIES_GROUP_FIELDS:
        season_key, dominant_key = SERIES_GROUP_FIELDS[base]
        season_value = _same_context_value(details, season_key)
        dominant_value = _same_context_value(details, dominant_key)
        if season_value is not None and dominant_value is not None:
            if base == "series_mixed_resolution":
                return {
                    "fr": f"Les saisons {fr_seasons} sont en {_fmt_value(season_value, lang='fr')} alors que la majorité de la série est en {_fmt_value(dominant_value, lang='fr')}.",
                    "en": f"Seasons {en_seasons} are in {_fmt_value(season_value)} while most of the series is in {_fmt_value(dominant_value)}.",
                }, {}
            if base == "series_mixed_video_codec":
                return {
                    "fr": f"Les saisons {fr_seasons} utilisent le codec {_fmt_value(season_value, lang='fr')} alors que la majorité de la série utilise {_fmt_value(dominant_value, lang='fr')}.",
                    "en": f"Seasons {en_seasons} use {_fmt_value(season_value)} while most of the series uses {_fmt_value(dominant_value)}.",
                }, {}
            if base == "series_mixed_audio_channels":
                return {
                    "fr": f"Les saisons {fr_seasons} sont en audio {_fmt_value(season_value, lang='fr')} alors que la majorité de la série est en {_fmt_value(dominant_value, lang='fr')}.",
                    "en": f"Seasons {en_seasons} use {_fmt_value(season_value)} audio while most of the series uses {_fmt_value(dominant_value)}.",
                }, {}
            if base == "series_mixed_languages":
                return {
                    "fr": f"Les saisons {fr_seasons} sont en {_fmt_value(season_value, lang='fr')} alors que la majorité de la série est en {_fmt_value(dominant_value, lang='fr')}.",
                    "en": f"Seasons {en_seasons} are {_fmt_value(season_value)} while most of the series is {_fmt_value(dominant_value)}.",
                }, {}
        return {
            "fr": f"Les saisons {fr_seasons} diffèrent du profil majoritaire de la série.",
            "en": f"Seasons {en_seasons} differ from the dominant series profile.",
        }, {}
    if base == "series_low_score_season":
        return {
            "fr": f"Les saisons {fr_seasons} ont un score qualité nettement inférieur au score moyen de la série.",
            "en": f"Seasons {en_seasons} have a quality score significantly lower than the series average.",
        }, {}
    if base == "series_large_season":
        return {
            "fr": f"Les saisons {fr_seasons} sont beaucoup plus lourdes que les autres saisons.",
            "en": f"Seasons {en_seasons} are much larger than the other seasons.",
        }, {}
    return {"fr": "", "en": ""}, {}


def _grouped_series_action(base: str, seasons: list[int]) -> dict:
    fr_seasons = _join_seasons_fr(seasons)
    en_seasons = _join_seasons_en(seasons)
    if base == "series_low_score_season":
        return {"fr": f"Chercher de meilleures versions des saisons {fr_seasons}.", "en": f"Look for better versions of seasons {en_seasons}."}
    if base == "series_large_season":
        return {"fr": f"Vérifier si les saisons {fr_seasons} peuvent être optimisées.", "en": f"Check whether seasons {en_seasons} can be optimized."}
    return {"fr": f"Vérifier les saisons {fr_seasons}.", "en": f"Review seasons {en_seasons}."}


def group_series_recommendations(recs: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    passthrough = []
    for rec in recs:
        key = _series_group_key(rec)
        if key is None:
            passthrough.append(rec)
        else:
            groups[key].append(rec)

    grouped = list(passthrough)
    for (_mid, base), group in groups.items():
        if len(group) == 1:
            grouped.extend(group)
            continue
        details = _details_for_group(group)
        seasons = [d.get("season") for d in details if d.get("season") is not None]
        if len(seasons) <= 1:
            grouped.extend(group)
            continue
        best = sorted(group, key=_rec_sort_key, reverse=True)[0]
        rec = dict(best)
        rec["rule_id"] = base
        rec["dedupe_group"] = base
        rec["severity"] = max(int(r.get("severity") or 0) for r in group)
        rec["priority"] = sorted(group, key=lambda r: PRIORITY_RANK.get(r.get("priority"), 0), reverse=True)[0].get("priority", best.get("priority"))
        msg, _ = _grouped_series_message(base, seasons, details)
        if msg.get("fr") and msg.get("en"):
            rec["message"] = msg
        rec["suggested_action"] = _grouped_series_action(base, seasons)
        rec["context"] = {"seasons": seasons, "details": details}
        grouped.append(rec)
    return sorted(grouped, key=lambda r: (str(r.get("media_ref", {}).get("id")), tuple(-v for v in _rec_sort_key(r)), str(r.get("rule_id"))))


def limit_noise(recs: list[dict], *, max_per_media: int = 3) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for rec in recs:
        grouped[str(rec.get("media_ref", {}).get("id"))].append(rec)
    kept = []
    for mid in sorted(grouped):
        ranked = sorted(grouped[mid], key=lambda r: tuple(-v for v in _rec_sort_key(r)))
        kept.extend(ranked[:max_per_media])
    return kept
