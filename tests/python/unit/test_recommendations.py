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
            ({"field": "unknown_field", "operator": "not_contains", "value": "fr"}, False),
            ({"field": "unknown_field", "operator": "!=", "value": "VO"}, False),
            ({"field": "empty_list", "operator": "exists"}, False),
            ({"field": "empty_list", "operator": "missing"}, True),
        ]
        sample["unknown_field"] = "UNKNOWN"
        sample["empty_list"] = []
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

    def test_series_low_score_message_includes_compared_scores(self):
        tv = item(
            id="tv:Series:Demo",
            type="tv",
            seasons=[
                {"season": 1, "quality": {"score": 70}, "size_gb": 10},
                {"season": 6, "quality": {"score": 35}, "size_gb": 10},
                {"season": 7, "quality": {"score": 70}, "size_gb": 10},
            ],
        )
        rec = next(r for r in recommendations.series_recommendations(tv) if r["rule_id"].startswith("series_low_score_season:s6"))
        self.assertEqual(rec["priority"], "medium")
        self.assertEqual(rec["context"], {"season": 6, "season_score": 35, "series_average_score": 70, "delta": 35})
        self.assertIn("score qualité de 35", rec["message"]["fr"])
        self.assertIn("(70)", rec["message"]["fr"])
        self.assertIn("quality score of 35", rec["message"]["en"])
        self.assertIn("average score (70)", rec["message"]["en"])

    def test_series_large_season_message_uses_season_size_not_series_size(self):
        tv = item(
            id="tv:Series:Demo",
            type="tv",
            size_gb=400,
            seasons=[
                {"season": 1, "size_gb": 35, "quality": {"score": 80}},
                {"season": 5, "size_gb": 84, "quality": {"score": 80}},
                {"season": 6, "size_gb": 35, "quality": {"score": 80}},
            ],
        )
        rec = next(r for r in recommendations.series_recommendations(tv) if r["rule_id"].startswith("series_large_season:s5"))
        self.assertEqual(rec["context"], {
            "season": 5,
            "season_size_gb": 84,
            "average_other_seasons_size_gb": 35,
            "ratio": 2.4,
        })
        self.assertIn("84 Go", rec["message"]["fr"])
        self.assertNotIn("400", rec["message"]["fr"])
        self.assertIn("2,4x", rec["message"]["fr"])
        self.assertIn("84 GB", rec["message"]["en"])
        self.assertIn("2.4x", rec["message"]["en"])

    def test_series_mixed_messages_include_compared_values(self):
        tv = item(
            id="tv:Series:Demo",
            type="tv",
            seasons=[
                {"season": 1, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 2, "resolution": "720p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 3, "resolution": "1080p", "codec": "Xvid", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 4, "resolution": "1080p", "codec": "HEVC", "audio_channels": "2.0", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 5, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "VO", "size_gb": 10, "quality": {"score": 80}},
                {"season": 6, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
            ],
        )
        recs = recommendations.series_recommendations(tv)

        resolution = next(r for r in recs if r["rule_id"].startswith("series_mixed_resolution:s2"))
        self.assertEqual(resolution["context"]["season_resolution"], "720p")
        self.assertEqual(resolution["context"]["dominant_resolution"], "1080p")
        self.assertIn("720p", resolution["message"]["fr"])
        self.assertIn("1080p", resolution["message"]["en"])

        codec = next(r for r in recs if r["rule_id"].startswith("series_mixed_video_codec:s3"))
        self.assertEqual(codec["context"]["season_video_codec"], "Xvid")
        self.assertEqual(codec["context"]["dominant_video_codec"], "HEVC")
        self.assertIn("Xvid", codec["message"]["fr"])
        self.assertIn("HEVC", codec["message"]["en"])

        channels = next(r for r in recs if r["rule_id"].startswith("series_mixed_audio_channels:s4"))
        self.assertEqual(channels["context"]["season_audio_channels"], "2.0")
        self.assertEqual(channels["context"]["dominant_audio_channels"], "5.1")
        self.assertIn("2.0", channels["message"]["fr"])
        self.assertIn("5.1", channels["message"]["en"])

        languages = next(r for r in recs if r["rule_id"].startswith("series_mixed_languages:s5"))
        self.assertEqual(languages["context"]["season_audio_language_group"], "VO")
        self.assertEqual(languages["context"]["dominant_audio_language_group"], "MULTI")
        self.assertIn("VO", languages["message"]["fr"])
        self.assertIn("MULTI", languages["message"]["en"])

    def test_series_recommendations_group_same_rule_before_noise_limit(self):
        tv = item(
            id="tv:Series:Grouped",
            type="tv",
            resolution="1080p",
            codec="HEVC",
            audio_channels="5.1",
            audio_languages_simple="MULTI",
            size_gb=10,
            quality={"score": 80},
            seasons=[
                {"season": 1, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 2, "resolution": "720p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 3, "resolution": "720p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 4, "resolution": "720p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 5, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 6, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
                {"season": 7, "resolution": "1080p", "codec": "HEVC", "audio_channels": "5.1", "audio_languages_simple": "MULTI", "size_gb": 10, "quality": {"score": 80}},
            ],
        )
        recs = recommendations.generate_recommendations({"items": [tv]}, [], max_per_media=3)
        resolution = next(r for r in recs if r["rule_id"] == "series_mixed_resolution")
        self.assertEqual(resolution["context"]["seasons"], [2, 3, 4])
        self.assertEqual([d["season"] for d in resolution["context"]["details"]], [2, 3, 4])
        self.assertIn("Les saisons 2, 3 et 4", resolution["message"]["fr"])
        self.assertIn("Seasons 2, 3 and 4", resolution["message"]["en"])
        self.assertLessEqual(len(recs), 3)

    def test_series_low_score_and_large_seasons_group_plural_messages(self):
        tv = item(
            id="tv:Series:GroupedScores",
            type="tv",
            seasons=[
                {"season": 1, "size_gb": 10, "quality": {"score": 80}},
                {"season": 2, "size_gb": 10, "quality": {"score": 80}},
                {"season": 4, "size_gb": 10, "quality": {"score": 40}},
                {"season": 5, "size_gb": 35, "quality": {"score": 80}},
                {"season": 6, "size_gb": 10, "quality": {"score": 40}},
                {"season": 7, "size_gb": 35, "quality": {"score": 80}},
            ],
        )
        grouped = recommendations.group_series_recommendations(recommendations.dedupe_recommendations(recommendations.series_recommendations(tv)))
        low = next(r for r in grouped if r["rule_id"] == "series_low_score_season")
        large = next(r for r in grouped if r["rule_id"] == "series_large_season")
        self.assertEqual(low["context"]["seasons"], [4, 6])
        self.assertIn("Les saisons 4 et 6", low["message"]["fr"])
        self.assertIn("Seasons 4 and 6", low["message"]["en"])
        self.assertEqual(large["context"]["seasons"], [5, 7])
        self.assertIn("beaucoup plus lourdes", large["message"]["fr"])
        self.assertIn("much larger", large["message"]["en"])

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

    def test_low_score_default_rule_is_medium(self):
        rules = recommendations.load_rules(ROOT / "backend" / "recommendations_rules.json")
        rec = next(r for r in recommendations.json_rule_recommendations(item(quality={"score": 50}), rules) if r["rule_id"] == "low_score")
        self.assertEqual(rec["priority"], "medium")

    def test_language_rules_require_reliable_audio_languages(self):
        rules = recommendations.load_rules(ROOT / "backend" / "recommendations_rules.json")
        no_languages = item(audio_languages=None, audio_languages_simple="VF")
        known_without_french = item(audio_languages=["eng"], audio_languages_simple="VO")

        missing_recs = recommendations.json_rule_recommendations(no_languages, rules)
        known_recs = recommendations.json_rule_recommendations(known_without_french, rules)

        self.assertFalse(any(r["rule_id"] == "missing_french_audio" for r in missing_recs))
        self.assertTrue(any(r["rule_id"] == "missing_french_audio" for r in known_recs))

    def test_vo_only_requires_known_language_group(self):
        rules = recommendations.load_rules(ROOT / "backend" / "recommendations_rules.json")
        unknown_group = item(audio_language_group=None, audio_languages_simple="UNKNOWN")
        vo_group = item(audio_language_group="VO", audio_languages_simple="VF")

        unknown_recs = recommendations.json_rule_recommendations(unknown_group, rules)
        vo_recs = recommendations.json_rule_recommendations(vo_group, rules)

        self.assertFalse(any(r["rule_id"] == "vo_only" for r in unknown_recs))
        self.assertTrue(any(r["rule_id"] == "vo_only" for r in vo_recs))

    def test_missing_french_subtitles_requires_known_subtitles(self):
        rules = recommendations.load_rules(ROOT / "backend" / "recommendations_rules.json")
        unknown_subtitles = item(audio_language_group="VO", subtitle_languages=[])
        known_without_french = item(audio_language_group="VO", subtitle_languages=["eng"])

        unknown_recs = recommendations.json_rule_recommendations(unknown_subtitles, rules)
        known_recs = recommendations.json_rule_recommendations(known_without_french, rules)

        self.assertFalse(any(r["rule_id"] == "missing_french_subtitles_for_vo" for r in unknown_recs))
        self.assertTrue(any(r["rule_id"] == "missing_french_subtitles_for_vo" for r in known_recs))

    def test_unknown_language_is_data(self):
        recs = recommendations.data_recommendations(item(audio_languages_simple="UNKNOWN"))
        rec = next(r for r in recs if r["rule_id"] == "unknown_language")
        self.assertEqual(rec["recommendation_type"], "data")


if __name__ == "__main__":
    unittest.main()
