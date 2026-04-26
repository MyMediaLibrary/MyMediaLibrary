import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import media_probe  # noqa: E402
import scanner  # noqa: E402


def ffprobe_payload(
    *,
    width=1920,
    height=1080,
    video_codec="h264",
    audio_codec="aac",
    channels=6,
    duration=3600,
    bitrate=8_000_000,
    audio_lang="fra",
    subtitle_lang="eng",
):
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": video_codec,
                "width": width,
                "height": height,
                "duration": str(duration),
                "bit_rate": str(bitrate),
                "color_transfer": "bt709",
            },
            {
                "codec_type": "audio",
                "codec_name": audio_codec,
                "channels": channels,
                "tags": {"language": audio_lang},
            },
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"language": subtitle_lang},
            },
        ],
        "format": {"duration": str(duration), "bit_rate": str(bitrate)},
    }


def completed(payload):
    return Mock(returncode=0, stdout=json.dumps(payload), stderr="")


class MediaProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.library_root = self.root / "library"
        self.data_dir = self.root / "data"
        self.library_root.mkdir()
        self.data_dir.mkdir()
        self.library_json = self.data_dir / "library.json"
        self.probe_json = self.data_dir / "library_probe.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_library(self, items):
        payload = {"scanned_at": "2026-04-26T10:00:00Z", "items": copy.deepcopy(items)}
        self.library_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def write_movie_fixture(self, item=None):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True, exist_ok=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        payload_item = {
            "id": "movie:Movies:Film",
            "path": "Movies/Film",
            "title": "Film",
            "category": "Movies",
            "type": "movie",
        }
        if item:
            payload_item.update(item)
        self.write_library([payload_item])
        return payload_item

    def generate_movie_probe(self, payload, item=None):
        self.write_movie_fixture(item)
        with patch.object(media_probe.subprocess, "run", return_value=completed(payload)):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )
        return json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]

    def test_disabled_does_not_write_or_call_ffprobe(self):
        self.write_library([])
        with patch.object(media_probe.subprocess, "run") as run:
            result = media_probe.run_media_probe_if_enabled(
                {"media_probe": {"enabled": False, "mode": "compare"}},
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        self.assertIsNone(result)
        run.assert_not_called()
        self.assertFalse(self.probe_json.exists())

    def test_enabled_compare_generates_probe_without_modifying_library_json(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "small.mkv").write_bytes(b"1")
        (movie_dir / "main.mkv").write_bytes(b"1" * 10)
        original = self.write_library([
            {
                "id": "movie:Movies:Film",
                "path": "Movies/Film",
                "title": "Film",
                "raw": "Film",
                "category": "Movies",
                "type": "movie",
                "resolution": "720p",
                "width": 1280,
                "height": 720,
                "codec": "H.265",
                "audio_codec": "DTS",
                "audio_languages": ["eng"],
                "audio_languages_simple": "VO",
                "size_b": 10,
                "size": "10 B",
                "file_count": 1,
                "providers": ["Netflix"],
                "providers_fetched": True,
            }
        ])

        with patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload())) as run:
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        self.assertEqual(stats, {"items": 1, "files_probed": 1, "errors": 0})
        self.assertIn("main.mkv", run.call_args.args[0][-1])
        self.assertEqual(json.loads(self.library_json.read_text(encoding="utf-8")), original)
        out = json.loads(self.probe_json.read_text(encoding="utf-8"))
        item = out["items"][0]
        self.assertEqual(item["title"], "Film")
        self.assertEqual(item["providers"], ["Netflix"])
        self.assertEqual(item["resolution"], "1080p")
        self.assertEqual(item["width"], 1920)
        self.assertEqual(item["height"], 1080)
        self.assertEqual(item["codec"], "H.264")
        self.assertEqual(item["audio_codec_raw"], "aac")
        self.assertEqual(item["audio_codec"], "AAC")
        self.assertEqual(item["audio_channels"], "5.1")
        self.assertEqual(item["audio_languages"], ["fra"])
        self.assertEqual(item["audio_languages_simple"], "VF")
        self.assertEqual(item["subtitle_languages"], ["eng"])
        self.assertEqual(item["video_bitrate"], 8_000_000)
        self.assertEqual(item["runtime_min"], 60)
        self.assertEqual(item["media_probe"]["status"], "ok")
        self.assertIn("resolution", item["media_probe"]["overwritten_fields"])

    def test_null_empty_unknown_probe_values_do_not_overwrite_existing_fields(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        self.write_library([
            {
                "id": "movie:Movies:Film",
                "path": "Movies/Film",
                "title": "Film",
                "category": "Movies",
                "type": "movie",
                "resolution": "1080p",
                "codec": "H.265",
                "audio_languages": ["fra"],
            }
        ])
        payload = ffprobe_payload(width=None, height=None, video_codec="unknown", audio_lang="und")
        payload["streams"][0].pop("width", None)
        payload["streams"][0].pop("height", None)

        with patch.object(media_probe.subprocess, "run", return_value=completed(payload)):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        item = json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["resolution"], "1080p")
        self.assertEqual(item["codec"], "H.265")
        self.assertEqual(item["audio_languages"], ["fra"])

    def test_video_bitrate_uses_stream_bit_rate(self):
        payload = ffprobe_payload(bitrate=5_108_632)

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["video_bitrate"], 5_108_632)

    def test_video_bitrate_uses_bps_tag(self):
        payload = ffprobe_payload()
        payload["streams"][0].pop("bit_rate", None)
        payload["streams"][0]["tags"] = {"BPS": "5108632"}

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["video_bitrate"], 5_108_632)

    def test_video_bitrate_uses_first_bps_dash_tag(self):
        payload = ffprobe_payload()
        payload["streams"][0].pop("bit_rate", None)
        payload["streams"][0]["tags"] = {"BPS-eng": "5108632"}

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["video_bitrate"], 5_108_632)

    def test_video_bitrate_ignores_format_bit_rate(self):
        payload = ffprobe_payload()
        payload["streams"][0].pop("bit_rate", None)
        payload["format"]["bit_rate"] = "9999999"

        item = self.generate_movie_probe(payload)

        self.assertNotIn("video_bitrate", item)
        self.assertNotIn("video_bitrate", item["media_probe"]["overwritten_fields"])

    def test_video_bitrate_existing_value_not_overwritten_when_probe_has_no_reliable_bitrate(self):
        payload = ffprobe_payload()
        payload["streams"][0].pop("bit_rate", None)
        payload["format"]["bit_rate"] = "9999999"

        item = self.generate_movie_probe(payload, {"video_bitrate": 1_234_567})

        self.assertEqual(item["video_bitrate"], 1_234_567)
        self.assertNotIn("video_bitrate", item["media_probe"]["overwritten_fields"])

    def test_video_bitrate_can_be_computed_from_byte_duration_tags(self):
        payload = ffprobe_payload()
        payload["streams"][0].pop("bit_rate", None)
        payload["streams"][0]["tags"] = {
            "NUMBER_OF_BYTES-eng": "600000000",
            "DURATION-eng": "00:20:00.000000000",
        }

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["video_bitrate"], 4_000_000)

    def test_ffprobe_codecs_are_normalized_to_display_labels(self):
        cases = [
            ("h264", "aac", "H.264", "AAC"),
            ("hevc", "eac3", "H.265", "Dolby Digital Plus"),
            ("avc1", "ac3", "H.264", "Dolby Digital"),
            ("mpeg2video", "dts", "MPEG-2", "DTS"),
            ("vc1", "truehd", "VC-1", "Dolby TrueHD"),
            ("av1", "flac", "AV1", "FLAC"),
            ("h265", "opus", "H.265", "Opus"),
        ]
        for video_codec, audio_codec, expected_video, expected_audio in cases:
            with self.subTest(video_codec=video_codec, audio_codec=audio_codec):
                item = self.generate_movie_probe(ffprobe_payload(video_codec=video_codec, audio_codec=audio_codec))
                self.assertEqual(item["codec"], expected_video)
                self.assertEqual(item["audio_codec"], expected_audio)

    def test_overwritten_fields_ignore_case_only_equivalent_values(self):
        item = self.generate_movie_probe(
            ffprobe_payload(video_codec="hevc", audio_codec="dts", audio_lang="FRA", subtitle_lang="ENG"),
            {
                "codec": "h265",
                "audio_codec": "dts",
                "audio_codec_raw": "DTS",
                "audio_languages": ["fra"],
                "subtitle_languages": ["eng"],
            },
        )

        overwritten = item["media_probe"]["overwritten_fields"]
        self.assertEqual(item["codec"], "H.265")
        self.assertEqual(item["audio_codec"], "DTS")
        self.assertNotIn("codec", overwritten)
        self.assertNotIn("audio_codec", overwritten)
        self.assertNotIn("audio_codec_raw", overwritten)
        self.assertNotIn("audio_languages", overwritten)
        self.assertNotIn("subtitle_languages", overwritten)

    def test_overwritten_fields_include_true_codec_difference(self):
        item = self.generate_movie_probe(
            ffprobe_payload(video_codec="hevc", audio_codec="eac3"),
            {"codec": "H.264", "audio_codec": "DTS"},
        )

        overwritten = item["media_probe"]["overwritten_fields"]
        self.assertIn("codec", overwritten)
        self.assertIn("audio_codec", overwritten)

    def test_score_enabled_recomputes_quality_and_diagnostics(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        original_quality = scanner.compute_quality({
            "type": "movie",
            "resolution": "720p",
            "codec": "H.264",
            "audio_codec": "AAC",
            "audio_languages_simple": "VO",
            "size_b": 1024,
        })
        self.write_library([
            {
                "id": "movie:Movies:Film",
                "path": "Movies/Film",
                "title": "Film",
                "category": "Movies",
                "type": "movie",
                "resolution": "720p",
                "codec": "H.264",
                "audio_codec": "AAC",
                "audio_languages_simple": "VO",
                "size_b": 1024,
                "quality": original_quality,
            }
        ])

        with patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload(width=3840, height=2160, video_codec="hevc", audio_codec="dts", channels=8, audio_lang="fra"))):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                score_enabled=True,
                score_config=scanner.get_effective_score_config({"score": {"enabled": True}})[1],
            )

        item = json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]
        self.assertIn("quality", item)
        self.assertEqual(item["media_probe"]["original_score"], original_quality["score"])
        self.assertEqual(item["media_probe"]["probe_score"], item["quality"]["score"])
        self.assertEqual(item["media_probe"]["score_delta"], item["quality"]["score"] - original_quality["score"])

    def test_score_disabled_does_not_create_quality(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        self.write_library([
            {"id": "movie:Movies:Film", "path": "Movies/Film", "title": "Film", "category": "Movies", "type": "movie"}
        ])

        with patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload())):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                score_enabled=False,
            )

        item = json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]
        self.assertNotIn("quality", item)
        self.assertIsNone(item["media_probe"]["probe_score"])

    def test_ffprobe_error_keeps_original_item_and_continues(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        original_item = {
            "id": "movie:Movies:Film",
            "path": "Movies/Film",
            "title": "Film",
            "category": "Movies",
            "type": "movie",
            "resolution": "720p",
            "quality": {"score": 12},
        }
        self.write_library([original_item])
        failed = Mock(returncode=1, stdout="", stderr="broken file")

        with patch.object(media_probe.subprocess, "run", return_value=failed):
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        item = json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(item["resolution"], "720p")
        self.assertEqual(item["quality"], {"score": 12})
        self.assertEqual(item["media_probe"]["status"], "error")
        self.assertIn("broken file", item["media_probe"]["error"])

    def test_ffprobe_missing_is_non_blocking(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        self.write_library([
            {"id": "movie:Movies:Film", "path": "Movies/Film", "title": "Film", "category": "Movies", "type": "movie"}
        ])

        with patch.object(media_probe.subprocess, "run", side_effect=FileNotFoundError("ffprobe")):
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        item = json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(item["media_probe"]["status"], "error")
        self.assertIn("ffprobe not found", item["media_probe"]["error"])

    def test_series_probes_episodes_and_aggregates_seasons_and_series(self):
        series_dir = self.library_root / "Series" / "Show"
        (series_dir / "Season 01").mkdir(parents=True)
        (series_dir / "Season 02").mkdir(parents=True)
        (series_dir / "Season 01" / "Show.S01E01.mkv").write_bytes(b"1")
        (series_dir / "Season 01" / "Show.S01E02.mkv").write_bytes(b"1")
        (series_dir / "Season 02" / "Show.S02E01.mkv").write_bytes(b"1")
        self.write_library([
            {
                "id": "tv:Series:Show",
                "path": "Series/Show",
                "title": "Show",
                "category": "Series",
                "type": "tv",
                "resolution": "720p",
                "seasons": [{"season": 1}, {"season": 2}],
            }
        ])

        def fake_run(cmd, **kwargs):
            path = cmd[-1]
            if "S02" in path:
                return completed(ffprobe_payload(width=3840, height=2160, video_codec="hevc", audio_codec="dts", channels=8, audio_lang="eng", subtitle_lang="fra"))
            return completed(ffprobe_payload(width=1920, height=1080, video_codec="h264", audio_codec="aac", channels=6, audio_lang="fra", subtitle_lang="eng"))

        with patch.object(media_probe.subprocess, "run", side_effect=fake_run):
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                score_enabled=True,
                score_config=scanner.get_effective_score_config({"score": {"enabled": True}})[1],
            )

        item = json.loads(self.probe_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(stats["files_probed"], 3)
        self.assertEqual(item["season_count"], 2)
        self.assertEqual(item["episode_count"], 3)
        self.assertEqual(item["runtime_min"], 180)
        self.assertEqual(item["runtime_min_avg"], 60)
        self.assertEqual(item["resolution"], "1080p")
        self.assertEqual(item["seasons"][0]["episodes_found"], 2)
        self.assertEqual(item["seasons"][0]["resolution"], "1080p")
        self.assertEqual(item["seasons"][1]["resolution"], "4K")
        self.assertIn("quality", item)
        self.assertEqual(item["media_probe"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
