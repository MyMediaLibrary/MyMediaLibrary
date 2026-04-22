import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class TvAggregationV033Test(unittest.TestCase):
    def test_extract_episode_from_anime_like_names(self):
        self.assertEqual(scanner._extract_season_episode_from_name("Boruto.E01.mkv"), (None, 1))
        self.assertEqual(scanner._extract_season_episode_from_name("Boruto - E002.mkv"), (None, 2))
        self.assertEqual(scanner._extract_season_episode_from_name("OnePiece.001.mkv"), (None, 1))
        self.assertEqual(scanner._extract_season_episode_from_name("Show.1x03.mkv"), (1, 3))
        self.assertEqual(scanner._extract_season_episode_from_name("Show.1080p.mkv"), (None, None))

    def test_collect_series_episode_metadata_dedupes_nfo_and_video_for_episode_token_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            series_dir = pathlib.Path(tmpdir) / "Boruto"
            series_dir.mkdir(parents=True)
            video = series_dir / "Boruto.E01.mkv"
            video.write_bytes(b"0123456789")
            (series_dir / "Boruto.E01.nfo").write_text(
                "<episodedetails><title>Boruto</title></episodedetails>",
                encoding="utf-8",
            )

            episodes = scanner.collect_series_episode_metadata(series_dir)
            self.assertEqual(len(episodes), 1)
            self.assertEqual(episodes[0]["season"], 1)
            self.assertEqual(episodes[0]["episode"], 1)
            self.assertEqual(episodes[0]["size_b"], 10)

            agg = scanner.aggregate_series_metadata(episodes)
            self.assertEqual(agg["episode_count"], 1)
            self.assertEqual(agg["season_count"], 1)
            self.assertEqual(agg["size_b"], 10)
            self.assertEqual(agg["seasons"][0]["size_b"], 10)

    def test_collect_series_episode_metadata_without_nfo_parses_anime_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            series_dir = pathlib.Path(tmpdir) / "Anime"
            series_dir.mkdir(parents=True)
            (series_dir / "Anime.001.mkv").write_bytes(b"a" * 3)
            (series_dir / "Anime.002.mkv").write_bytes(b"b" * 5)

            episodes = sorted(
                scanner.collect_series_episode_metadata(series_dir),
                key=lambda e: int(e.get("episode") or 0),
            )
            self.assertEqual(len(episodes), 2)
            self.assertEqual([e.get("episode") for e in episodes], [1, 2])
            self.assertEqual(sum(int(e.get("size_b") or 0) for e in episodes), 8)

    def test_parse_episode_nfo_metadata_extracts_new_streamdetails_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nfo = pathlib.Path(tmpdir) / "Show.S01E01.nfo"
            nfo.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<episodedetails>
  <season>1</season>
  <episode>1</episode>
  <fileinfo>
    <streamdetails>
      <video>
        <width>1920</width>
        <height>1080</height>
        <bitrate>4500000</bitrate>
      </video>
      <audio>
        <channels>8</channels>
        <language>eng</language>
      </audio>
      <subtitle><language>fra</language></subtitle>
      <subtitle><language>eng</language></subtitle>
    </streamdetails>
  </fileinfo>
</episodedetails>
""",
                encoding="utf-8",
            )
            parsed = scanner._parse_episode_nfo_metadata(nfo)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["audio_channels"], "7.1")
            self.assertEqual(parsed["subtitle_languages"], ["eng", "fra"])
            self.assertEqual(parsed["video_bitrate"], 4500000)

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
        self.assertEqual(agg["runtime_min"], 474)
        self.assertEqual(agg["runtime_min_avg"], 47)
        self.assertIn("quality", agg)
        self.assertNotIn("base_score", agg["quality"])
        self.assertNotIn("score_details", agg["quality"])
        self.assertEqual(
            agg["quality"]["video"],
            agg["quality"]["video_details"]["resolution"]
            + agg["quality"]["video_details"]["codec"]
            + agg["quality"]["video_details"]["hdr"],
        )
        self.assertEqual(
            agg["quality"]["audio"],
            agg["quality"]["audio_details"]["codec"] + agg["quality"]["audio_details"]["channels"],
        )

    def test_aggregate_series_metadata_uses_season_sums_for_runtime_and_size(self):
        seasons = [
            {
                "season": 1,
                "episodes_found": 10,
                "episodes_expected": 10,
                "resolution": "720p",
                "width": 1280,
                "height": 720,
                "codec": "H.264",
                "audio_codec_raw": "aac",
                "audio_codec": "AAC",
                "audio_languages": ["eng", "fra"],
                "audio_languages_simple": "MULTI",
                "hdr": False,
                "hdr_type": None,
                "runtime_min_total": 460,
                "size_b": 30 * 1024**3,
                "quality": scanner.compute_quality({"type": "tv", "resolution": "720p", "codec": "H.264", "size_b": 30 * 1024**3}),
            },
            {
                "season": 2,
                "episodes_found": 8,
                "episodes_expected": 10,
                "resolution": "1080p",
                "width": 1920,
                "height": 1080,
                "codec": "H.265",
                "audio_codec_raw": "eac3",
                "audio_codec": "Dolby Digital Plus",
                "audio_languages": ["eng", "fra"],
                "audio_languages_simple": "MULTI",
                "hdr": False,
                "hdr_type": None,
                "runtime_min_total": 392,
                "size_b": 57 * 1024**3,
                "quality": scanner.compute_quality({"type": "tv", "resolution": "1080p", "codec": "H.265", "size_b": 57 * 1024**3}),
            },
        ]
        with patch.object(scanner, "aggregate_season_metadata", side_effect=seasons):
            agg = scanner.aggregate_series_metadata([{"season": 1}, {"season": 2}])

        self.assertEqual(agg["episode_count"], 18)
        self.assertEqual(agg["episodes_expected"], 20)
        self.assertEqual(agg["runtime_min"], 852)
        self.assertEqual(agg["runtime_min_avg"], 47)
        self.assertEqual(agg["size_b"], (30 + 57) * 1024**3)

    def test_aggregate_series_metadata_expected_is_none_when_partial(self):
        seasons = [
            {
                "season": 1,
                "episodes_found": 10,
                "episodes_expected": 10,
                "runtime_min_total": 460,
                "size_b": 1,
                "quality": {
                    "score": 1,
                    "video": 1,
                    "audio": 0,
                    "languages": 0,
                    "size": 0,
                    "video_w": 1.0,
                    "audio_w": 0.0,
                    "languages_w": 0.0,
                    "size_w": 0.0,
                    "video_details": {"resolution": 1, "codec": 0, "hdr": 0},
                },
            },
            {
                "season": 2,
                "episodes_found": 8,
                "episodes_expected": None,
                "runtime_min_total": 392,
                "size_b": 1,
                "quality": {
                    "score": 1,
                    "video": 1,
                    "audio": 0,
                    "languages": 0,
                    "size": 0,
                    "video_w": 1.0,
                    "audio_w": 0.0,
                    "languages_w": 0.0,
                    "size_w": 0.0,
                    "video_details": {"resolution": 1, "codec": 0, "hdr": 0},
                },
            },
        ]
        with patch.object(scanner, "aggregate_season_metadata", side_effect=seasons):
            agg = scanner.aggregate_series_metadata([{"season": 1}, {"season": 2}])
        self.assertIsNone(agg["episodes_expected"])

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
        self.assertNotIn("base_score", season["quality"])
        self.assertNotIn("score_details", season["quality"])
        self.assertEqual(
            season["quality"]["video"],
            season["quality"]["video_details"]["resolution"]
            + season["quality"]["video_details"]["codec"]
            + season["quality"]["video_details"]["hdr"],
        )
        self.assertEqual(
            season["quality"]["audio"],
            season["quality"]["audio_details"]["codec"] + season["quality"]["audio_details"]["channels"],
        )

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
        for quality in (items[0]["quality"], items[0]["seasons"][0]["quality"], items[0]["seasons"][1]["quality"]):
            self.assertNotIn("base_score", quality)
            self.assertNotIn("score_details", quality)
            self.assertEqual(
                quality["video"],
                quality["video_details"]["resolution"]
                + quality["video_details"]["codec"]
                + quality["video_details"]["hdr"],
            )
            self.assertEqual(
                quality["audio"],
                quality["audio_details"]["codec"] + quality["audio_details"]["channels"],
            )

    def test_aggregate_season_metadata_adds_channels_subtitles_and_bitrate(self):
        season = scanner.aggregate_season_metadata(
            1,
            [
                {"audio_channels": "5.1", "subtitle_languages": ["fra", "eng"], "video_bitrate": 4000, "size_b": 1, "audio_languages": [], "hdr": False},
                {"audio_channels": "5.1", "subtitle_languages": ["eng"], "video_bitrate": 0, "size_b": 1, "audio_languages": [], "hdr": False},
                {"audio_channels": "7.1", "subtitle_languages": None, "video_bitrate": None, "size_b": 1, "audio_languages": [], "hdr": False},
                {"audio_channels": "7.1", "subtitle_languages": ["jpn"], "video_bitrate": 6000, "size_b": 1, "audio_languages": [], "hdr": False},
            ],
        )
        self.assertEqual(season["audio_channels"], "7.1")
        self.assertEqual(season["subtitle_languages"], ["eng", "fra", "jpn"])
        self.assertEqual(season["video_bitrate"], 5000)

    def test_aggregate_series_metadata_uses_episode_level_for_new_fields(self):
        episodes = [
            {"season": 1, "audio_channels": "7.1", "subtitle_languages": ["eng"], "video_bitrate": 1000, "size_b": 1, "audio_languages": [], "hdr": False},
            {"season": 1, "audio_channels": "7.1", "subtitle_languages": ["fra"], "video_bitrate": 3000, "size_b": 1, "audio_languages": [], "hdr": False},
            {"season": 2, "audio_channels": "5.1", "subtitle_languages": ["jpn"], "video_bitrate": 0, "size_b": 1, "audio_languages": [], "hdr": False},
            {"season": 2, "audio_channels": "5.1", "subtitle_languages": None, "video_bitrate": None, "size_b": 1, "audio_languages": [], "hdr": False},
        ]
        agg = scanner.aggregate_series_metadata(episodes)
        self.assertEqual(agg["audio_channels"], "7.1")
        self.assertEqual(agg["subtitle_languages"], ["eng", "fra", "jpn"])
        self.assertEqual(agg["video_bitrate"], 2000)

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
