import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class TvAggregationV033Test(unittest.TestCase):
    def test_aggregate_series_metadata_uses_dominant_values(self):
        episodes = []
        for _ in range(7):
            episodes.append(
                {
                    "season": 1,
                    "episode": None,
                    "resolution": "1080p",
                    "width": 1920,
                    "height": 1080,
                    "codec": "H.265",
                    "audio_codec_raw": "eac3",
                    "audio_codec": "Dolby Digital Plus",
                    "audio_languages": ["fra", "eng"],
                    "hdr": False,
                    "hdr_type": None,
                    "runtime_min": 48,
                    "size_b": 5 * 1024**3,
                }
            )
        for _ in range(3):
            episodes.append(
                {
                    "season": 1,
                    "episode": None,
                    "resolution": "720p",
                    "width": 1280,
                    "height": 720,
                    "codec": "H.264",
                    "audio_codec_raw": "aac",
                    "audio_codec": "AAC",
                    "audio_languages": ["eng"],
                    "hdr": False,
                    "hdr_type": None,
                    "runtime_min": 46,
                    "size_b": 2 * 1024**3,
                }
            )
        agg = scanner.aggregate_series_metadata(episodes)
        self.assertEqual(agg["resolution"], "1080p")
        self.assertEqual(agg["width"], 1920)
        self.assertEqual(agg["height"], 1080)
        self.assertEqual(agg["episode_count"], 10)
        self.assertEqual(agg["runtime_min"], 47)

    def test_aggregate_season_runtime_handles_missing_values(self):
        season = scanner.aggregate_season_metadata(
            2,
            [
                {"runtime_min": 52, "size_b": 10, "audio_languages": [], "hdr": False},
                {"runtime_min": None, "size_b": 20, "audio_languages": [], "hdr": False},
                {"runtime_min": 48, "size_b": 30, "audio_languages": [], "hdr": False},
            ],
        )
        self.assertEqual(season["runtime_min_total"], 100)
        self.assertEqual(season["runtime_min_avg"], 50)
        self.assertEqual(season["size_b"], 60)

    def test_recompute_scores_for_items_updates_tv_seasons(self):
        items = [
            {
                "type": "tv",
                "resolution": "1080p",
                "codec": "H.265",
                "audio_codec_raw": "eac3",
                "audio_codec": "Dolby Digital Plus",
                "audio_languages": ["fra", "eng"],
                "audio_languages_simple": "MULTI",
                "hdr": False,
                "hdr_type": None,
                "size_b": 30 * 1024**3,
                "seasons": [
                    {
                        "season": 1,
                        "episodes_found": 10,
                        "resolution": "720p",
                        "codec": "H.264",
                        "audio_codec_raw": "aac",
                        "audio_codec": "AAC",
                        "audio_languages": ["fra", "eng"],
                        "audio_languages_simple": "MULTI",
                        "hdr": False,
                        "hdr_type": None,
                        "size_b": 10 * 1024**3,
                    },
                    {
                        "season": 2,
                        "episodes_found": 8,
                        "resolution": "1080p",
                        "codec": "H.265",
                        "audio_codec_raw": "eac3",
                        "audio_codec": "Dolby Digital Plus",
                        "audio_languages": ["fra", "eng"],
                        "audio_languages_simple": "MULTI",
                        "hdr": False,
                        "hdr_type": None,
                        "size_b": 20 * 1024**3,
                    },
                ],
            }
        ]
        updated = scanner.recompute_scores_for_items(items, scanner.get_builtin_score_defaults())
        self.assertEqual(updated, 1)
        self.assertIn("quality", items[0]["seasons"][0])
        self.assertIn("quality", items[0]["seasons"][1])
        self.assertIn("quality", items[0])

    def test_merge_series_expected_counts_adds_missing_expected_season(self):
        item = {
            "episode_count": 10,
            "season_count": 1,
            "seasons": [{"season": 1, "episodes_found": 10}],
        }
        merged = scanner.merge_series_expected_counts_from_seerr(
            item,
            {
                "episodes_expected": 20,
                "season_count_expected": 2,
                "season_episode_counts": {1: 10, 2: 10},
            },
        )
        self.assertEqual(merged["season_count"], 2)
        self.assertEqual(len(merged["seasons"]), 2)
        season2 = [s for s in merged["seasons"] if s["season"] == 2][0]
        self.assertEqual(season2["episodes_found"], 0)
        self.assertEqual(season2["episodes_expected"], 10)


if __name__ == "__main__":
    unittest.main()
