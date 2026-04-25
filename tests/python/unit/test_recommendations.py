import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import recommendations  # noqa: E402


def item(**overrides):
    base = {
        "id": "movie:Films:Demo",
        "type": "movie",
        "title": "Demo",
        "year": 2024,
        "resolution": "1080p",
        "codec": "H.264",
        "audio_codec": "Dolby Digital",
        "audio_channels": "5.1",
        "audio_languages": ["fra"],
        "audio_languages_simple": "VF",
        "subtitle_languages": ["fra"],
        "video_bitrate": 12000000,
        "size_b": 10 * 1024 ** 3,
        "quality": {"score": 70, "video_details": {"codec": 10}, "audio_details": {"channels": 8}},
    }
    base.update(overrides)
    return base


class RecommendationsTest(unittest.TestCase):
    def test_ensure_user_rules_copies_default_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            src = root / "default.json"
            dst = root / "data" / "rules.json"
            src.write_text('{"version":1,"rules":[{"id":"a"}]}', encoding="utf-8")
            self.assertTrue(recommendations.ensure_user_rules(src, dst))
            self.assertEqual(json.loads(dst.read_text(encoding="utf-8"))["rules"][0]["id"], "a")
            dst.write_text('{"version":1,"rules":[{"id":"user"}]}', encoding="utf-8")
            self.assertFalse(recommendations.ensure_user_rules(src, dst))
            self.assertEqual(json.loads(dst.read_text(encoding="utf-8"))["rules"][0]["id"], "user")

    def test_json_rule_operators_and_nested_fields(self):
        sample = item(tags=["a", "b"], nested={"value": 5}, quality={"score": 50, "video_details": {"codec": 3}})
        cases = [
            ({"field": "resolution", "operator": "=", "value": "1080p"}, True),
            ({"field": "resolution", "operator": "!=", "value": "720p"}, True),
            ({"field": "nested.value", "operator": ">", "value": 4}, True),
            ({"field": "nested.value", "operator": ">=", "value": 5}, True),
            ({"field": "nested.value", "operator": "<", "value": 6}, True),
            ({"field": "nested.value", "operator": "<=", "value": 5}, True),
            ({"field": "resolution", "operator": "in", "value": ["720p", "1080p"]}, True),
            ({"field": "resolution", "operator": "not_in", "value": ["4K"]}, True),
            ({"field": "tags", "operator": "contains", "value": "a"}, True),
            ({"field": "tags", "operator": "not_contains", "value": "z"}, True),
            ({"field": "quality.video_details.codec", "operator": "exists"}, True),
            ({"field": "missing.field", "operator": "missing"}, True),
            ({"field": "missing.field", "operator": "=", "value": 1}, False),
        ]
        for condition, expected in cases:
            with self.subTest(condition=condition):
                self.assertEqual(recommendations.condition_matches(sample, condition), expected)

    def test_json_rules_generate_recommendation(self):
        rules = [{
            "id": "large",
            "enabled": True,
            "type": "space",
            "priority": "high",
            "dedupe_group": "large",
            "severity": 2,
            "conditions": [{"field": "size_gb", "operator": ">", "value": 8}],
            "message": {"fr": "Lourd.", "en": "Large."},
            "suggested_action": {"fr": "Optimiser.", "en": "Optimize."},
        }]
        recs = recommendations.json_rule_recommendations(item(), rules)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["recommendation_type"], "space")

    def test_data_rules_detect_missing_values(self):
        recs = recommendations.data_recommendations(item(
            resolution="UNKNOWN",
            codec=None,
            audio_codec="UNKNOWN",
            audio_channels=None,
            audio_languages=[],
            audio_languages_simple="UNKNOWN",
            size_b=0,
            quality=None,
        ))
        rule_ids = {r["rule_id"] for r in recs}
        self.assertTrue({
            "missing_resolution",
            "missing_video_codec",
            "missing_audio_codec",
            "missing_audio_channels",
            "missing_audio_languages",
            "unknown_language",
            "unknown_audio_quality",
            "missing_size",
            "missing_score",
        }.issubset(rule_ids))

    def test_series_rules_include_season_context(self):
        tv = item(
            id="tv:Series:Demo",
            type="tv",
            seasons=[
                {"season": 1, "resolution": "1080p", "codec": "H.264", "audio_channels": "5.1", "audio_languages_simple": "VF", "size_b": 5 * 1024 ** 3, "quality": {"score": 80}},
                {"season": 2, "resolution": "720p", "codec": "Xvid", "audio_channels": "2.0", "audio_languages_simple": "VO", "size_b": 12 * 1024 ** 3, "quality": {"score": 45}},
                {"season": 3, "resolution": "1080p", "codec": "H.264", "audio_channels": "5.1", "audio_languages_simple": "VF", "size_b": 5 * 1024 ** 3, "quality": {"score": 82}},
            ],
        )
        recs = recommendations.series_recommendations(tv)
        self.assertTrue(any(r["context"].get("season") == 2 for r in recs))
        self.assertTrue(any(r["rule_id"].startswith("series_low_score_season") for r in recs))

    def test_dedupe_and_limit_noise(self):
        sample = item()
        recs = [
            recommendations.make_rec(sample, rule_id="large", recommendation_type="space", priority="medium", dedupe_group="size", severity=1, message={"fr": "a", "en": "a"}, suggested_action={"fr": "a", "en": "a"}),
            recommendations.make_rec(sample, rule_id="very_large", recommendation_type="space", priority="high", dedupe_group="size", severity=2, message={"fr": "b", "en": "b"}, suggested_action={"fr": "b", "en": "b"}),
            recommendations.make_rec(sample, rule_id="data", recommendation_type="data", priority="high", dedupe_group="data", severity=1, message={"fr": "c", "en": "c"}, suggested_action={"fr": "c", "en": "c"}),
            recommendations.make_rec(sample, rule_id="quality", recommendation_type="quality", priority="medium", dedupe_group="quality", severity=1, message={"fr": "d", "en": "d"}, suggested_action={"fr": "d", "en": "d"}),
            recommendations.make_rec(sample, rule_id="lang", recommendation_type="languages", priority="low", dedupe_group="lang", severity=1, message={"fr": "e", "en": "e"}, suggested_action={"fr": "e", "en": "e"}),
        ]
        deduped = recommendations.dedupe_recommendations(recs)
        self.assertFalse(any(r["rule_id"] == "large" for r in deduped))
        limited = recommendations.limit_noise(deduped, max_per_media=3)
        self.assertEqual(len(limited), 3)
        self.assertEqual(limited[0]["recommendation_type"], "data")

    def test_write_recommendations_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "recommendations.json"
            doc = recommendations.write_recommendations([], out)
            self.assertEqual(doc["version"], 1)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["items"], [])


if __name__ == "__main__":
    unittest.main()
