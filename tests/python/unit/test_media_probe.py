import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch


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
    audio_bitrate=640_000,
    framerate="24000/1001",
    container="matroska,webm",
    size=123456,
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
                "avg_frame_rate": framerate,
                "color_transfer": "bt709",
            },
            {
                "codec_type": "audio",
                "codec_name": audio_codec,
                "channels": channels,
                "bit_rate": str(audio_bitrate),
                "tags": {"language": audio_lang},
            },
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"language": subtitle_lang},
            },
        ],
        "format": {"duration": str(duration), "bit_rate": str(bitrate), "format_name": container, "size": str(size)},
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
        self.cache_json = self.data_dir / "media_probe_cache.json"

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

    def generate_movie_probe(self, payload, item=None, **kwargs):
        self.write_movie_fixture(item)
        with patch.object(media_probe.subprocess, "run", return_value=completed(payload)):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                **kwargs,
            )
        return json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]

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

    def test_enabled_compare_enriches_library_json_without_parallel_output(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "small.mkv").write_bytes(b"1")
        (movie_dir / "main.mkv").write_bytes(b"1" * 10)
        self.write_library([
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

        self.assertEqual(stats, {"items": 1, "files_total": 1, "files_probed": 1, "files_cached": 0, "errors": 0})
        self.assertIn("main.mkv", run.call_args.args[0][-1])
        self.assertFalse(self.probe_json.exists())
        out = json.loads(self.library_json.read_text(encoding="utf-8"))
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
        self.assertEqual(item["audio_bitrate"], 640_000)
        self.assertEqual(item["framerate"], 23.976)
        self.assertEqual(item["container"], "MKV")
        self.assertEqual(item["size_b"], 123456)
        self.assertEqual(item["runtime_min"], 60)
        self.assertEqual(item["media_probe"]["status"], "ok")
        self.assertIn("resolution", item["media_probe"]["overwritten_fields"])

    def test_ffprobe_dolby_vision_sets_hdr_type_and_flag(self):
        payload = ffprobe_payload()
        payload["streams"][0]["profile"] = "dvhe.05.06"

        item = self.generate_movie_probe(payload)

        self.assertTrue(item["dolby_vision"])
        self.assertTrue(item["hdr"])
        self.assertEqual(item["hdr_type"], "Dolby Vision")

    def test_pipeline_probe_applies_technical_fields_to_library_without_diagnostics(self):
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
                "resolution": "720p",
                "codec": "H.265",
            }
        ])

        cfg = {"media_probe": {"enabled": True, "mode": "compare", "workers": 2, "cache_enabled": True}}
        with patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload(width=3840, height=2160, video_codec="hevc"))):
            stats = media_probe.run_media_probe_pipeline_if_enabled(
                cfg,
                library_json_path=self.library_json,
                library_root=self.library_root,
            )

        self.assertEqual(stats["items"], 1)
        library_item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(library_item["resolution"], "4K")
        self.assertEqual(library_item["codec"], "H.265")
        self.assertNotIn("media_probe", library_item)
        self.assertFalse(self.probe_json.exists())

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

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["resolution"], "1080p")
        self.assertEqual(item["codec"], "H.265")
        self.assertEqual(item["audio_languages"], ["fra"])

    def test_video_bitrate_uses_stream_bit_rate(self):
        payload = ffprobe_payload(bitrate=5_108_632)

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["video_bitrate"], 5_108_632)

    def test_cache_hit_skips_ffprobe(self):
        """media_probe_cache hit prevents ffprobe from running."""
        self.write_movie_fixture()
        cached_probe = {"ok": True, "technical": media_probe._technical_from_ffprobe(ffprobe_payload(video_codec="hevc"))}

        mock_repo = MagicMock()
        mock_repo.get.return_value = cached_probe

        with patch.object(media_probe, "_open_media_probe_cache_repo", return_value=mock_repo), \
             patch.object(media_probe.subprocess, "run") as run_mock:
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                library_root=self.library_root,
            )

        run_mock.assert_not_called()
        self.assertEqual(stats["files_cached"], 1)
        self.assertEqual(stats["files_probed"], 0)
        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["codec"], "H.265")

    def test_cache_reprobes_when_size_or_mtime_changes(self):
        """Cache is invalidated when file size or mtime changes; hit prevents ffprobe."""
        import db as _db
        from repositories import media_probe_cache_repository

        self.write_movie_fixture()
        movie_path = self.library_root / "Movies" / "Film" / "main.mkv"
        db_path = self.data_dir / "mpc.db"
        media_id = "movie:Movies:Film"
        filename = "main.mkv"

        # Create the DB schema and insert the media FK row required by the cache table.
        conn = _db.initialize_database(db_path)
        with conn:
            conn.execute(
                "INSERT INTO media(id, media_type, title) VALUES (?, ?, ?)",
                (media_id, "movie", "Film"),
            )
        conn.close()

        # Seed cache with the current file's probe result
        cached_probe = {"ok": True, "technical": media_probe._technical_from_ffprobe(ffprobe_payload(video_codec="hevc"))}
        repo = media_probe_cache_repository.open_cache(db_path=db_path)
        repo.upsert(media_id, filename, movie_path, cached_probe)
        repo.close()

        def open_repo():
            return media_probe_cache_repository.open_cache(db_path=db_path)

        # Cache hit: file unchanged → ffprobe not called
        with patch.object(media_probe, "_open_media_probe_cache_repo", side_effect=open_repo), \
             patch.object(media_probe.subprocess, "run") as run_mock:
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                library_root=self.library_root,
            )

        run_mock.assert_not_called()
        self.assertEqual(stats["files_cached"], 1)
        self.assertEqual(stats["files_probed"], 0)
        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["codec"], "H.265")

        # Invalidate: file content changes (different size + new mtime)
        movie_path.write_bytes(b"changed content - different size triggers cache miss")

        # Cache miss: file changed → ffprobe called, result stored in cache
        with patch.object(media_probe, "_open_media_probe_cache_repo", side_effect=open_repo), \
             patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload(video_codec="h264"))) as run_mock:
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                library_root=self.library_root,
            )

        run_mock.assert_called_once()
        self.assertEqual(stats["files_probed"], 1)
        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["codec"], "H.264")

    def test_cache_disabled_always_calls_ffprobe(self):
        self.write_movie_fixture()

        with patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload(video_codec="h264"))) as run:
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                cache_enabled=False,
            )

        run.assert_called_once()
        self.assertEqual(stats["files_cached"], 0)
        self.assertEqual(stats["files_probed"], 1)
        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["codec"], "H.264")

    def test_workers_are_bounded_for_thread_pool(self):
        self.write_movie_fixture()
        with patch.object(media_probe, "ThreadPoolExecutor", wraps=media_probe.ThreadPoolExecutor) as executor, \
             patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload())):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                workers=99,
                cache_enabled=False,
            )

        self.assertEqual(executor.call_args.kwargs["max_workers"], 8)
        self.assertEqual(media_probe._normalize_workers(0), 1)
        self.assertEqual(media_probe._normalize_workers("bad"), 4)

    def test_ffprobe_error_in_worker_continues(self):
        self.write_movie_fixture()
        failed = Mock(returncode=1, stdout="", stderr="broken file")

        with patch.object(media_probe.subprocess, "run", return_value=failed):
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        self.assertEqual(stats["errors"], 1)
        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["media_probe"]["status"], "error")

    def test_summary_log_includes_cache_counts_and_duration(self):
        self.write_movie_fixture()

        with self.assertLogs("scanner", level="INFO") as logs, \
             patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload())):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                cache_enabled=False,
            )

        joined = "\n".join(logs.output)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Starting phase — workers=4, cache=disabled", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Folder [Movies] (1/1) started", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Folder [Movies] completed in", joined)
        self.assertIn("1 item / 1 file / 0 errors", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Summary:", joined)
        self.assertIn("1 item / 1 file probed / 0 errors", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Completed in", joined)

    def test_category_progress_logs_include_cache_counts_and_duration(self):
        movie_dir = self.library_root / "Movies" / "Film"
        movie_dir.mkdir(parents=True)
        (movie_dir / "main.mkv").write_bytes(b"1")
        series_dir = self.library_root / "Series" / "Show"
        series_dir.mkdir(parents=True)
        (series_dir / "Show.S01E01.mkv").write_bytes(b"1")
        self.write_library([
            {"id": "movie:Movies:Film", "path": "Movies/Film", "title": "Film", "category": "Movies", "type": "movie"},
            {"id": "tv:Series:Show", "path": "Series/Show", "title": "Show", "category": "Series", "type": "tv"},
        ])

        with self.assertLogs("scanner", level="INFO") as logs, \
             patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload())):
            stats = media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
                cache_enabled=True,
            )

        self.assertEqual(stats, {"items": 2, "files_total": 2, "files_probed": 2, "files_cached": 0, "errors": 0})
        joined = "\n".join(logs.output)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Starting phase", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Folder [Movies] (1/2) started", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Folder [Series] (2/2) started", joined)
        self.assertIn("Folder [Movies] completed in", joined)
        self.assertIn("1 item / 1 file / 1 probed / 0 cached / 0 errors", joined)
        self.assertIn("Folder [Series] completed in", joined)
        self.assertIn("[SCAN] [PHASE 2] [FFPROBE] Summary:", joined)
        self.assertIn("2 items / 2 files total / 2 probed / 0 cached / 0 errors", joined)
        self.assertIn("Completed in", joined)

    def test_disabled_probe_does_not_emit_media_probe_logs(self):
        self.write_library([])
        with patch.object(media_probe.log, "info") as info, \
             patch.object(media_probe.subprocess, "run") as run:
            result = media_probe.run_media_probe_if_enabled(
                {"media_probe": {"enabled": False, "mode": "compare"}},
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        self.assertIsNone(result)
        info.assert_not_called()
        run.assert_not_called()

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

    def test_audio_language_tags_are_case_insensitive_and_normalized(self):
        payload = ffprobe_payload(audio_lang="fre")
        payload["streams"].append({
            "codec_type": "audio",
            "codec_name": "dts",
            "channels": 6,
            "tags": {"LANGUAGE": "en"},
        })

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["audio_languages"], ["eng", "fra"])
        self.assertEqual(item["audio_languages_simple"], "MULTI")

    def test_audio_language_title_case_tag_is_normalized(self):
        payload = ffprobe_payload(audio_lang="und")
        payload["streams"][1]["tags"] = {"Language": "spa"}

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["audio_languages"], ["spa"])
        self.assertEqual(item["audio_languages_simple"], "VO")

    def test_audio_language_short_french_code_is_normalized(self):
        item = self.generate_movie_probe(ffprobe_payload(audio_lang="fr"))

        self.assertEqual(item["audio_languages"], ["fra"])
        self.assertEqual(item["audio_languages_simple"], "VF")

    def test_subtitle_languages_are_case_insensitive_and_normalized(self):
        payload = ffprobe_payload(subtitle_lang="fre")
        payload["streams"][-1]["tags"] = {"Language": "fre"}

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["subtitle_languages"], ["fra"])

    def test_und_and_unknown_languages_are_ignored(self):
        payload = ffprobe_payload(audio_lang="und", subtitle_lang="unknown")
        payload["streams"].append({
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "tags": {"LANGUAGE": "english"},
        })
        payload["streams"].append({
            "codec_type": "subtitle",
            "codec_name": "subrip",
            "tags": {"language": ""},
        })

        item = self.generate_movie_probe(payload)

        self.assertEqual(item["audio_languages"], ["eng"])
        self.assertNotIn("subtitle_languages", item)

    def test_language_list_order_only_difference_is_not_overwritten(self):
        payload = ffprobe_payload(audio_lang="fra", subtitle_lang="fra")
        payload["streams"].append({
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "tags": {"language": "eng"},
        })
        payload["streams"].append({
            "codec_type": "subtitle",
            "codec_name": "subrip",
            "tags": {"language": "eng"},
        })

        item = self.generate_movie_probe(
            payload,
            {
                "audio_languages": ["fra", "eng"],
                "subtitle_languages": ["fra", "eng"],
            },
        )

        overwritten = item["media_probe"]["overwritten_fields"]
        self.assertEqual(item["audio_languages"], ["eng", "fra"])
        self.assertEqual(item["subtitle_languages"], ["eng", "fra"])
        self.assertNotIn("audio_languages", overwritten)
        self.assertNotIn("subtitle_languages", overwritten)

    def test_runtime_micro_differences_are_not_reported_as_overwritten(self):
        item = self.generate_movie_probe(
            ffprobe_payload(duration=62 * 60),
            {"runtime_min": 60, "runtime_min_avg": 60},
        )

        self.assertEqual(item["runtime_min"], 62)
        self.assertEqual(item["runtime_min_avg"], 62)
        self.assertNotIn("runtime_min", item["media_probe"]["overwritten_fields"])
        self.assertNotIn("runtime_min_avg", item["media_probe"]["overwritten_fields"])

    def test_runtime_large_differences_are_reported_as_overwritten(self):
        item = self.generate_movie_probe(
            ffprobe_payload(duration=63 * 60),
            {"runtime_min": 60, "runtime_min_avg": 60},
        )

        self.assertIn("runtime_min", item["media_probe"]["overwritten_fields"])
        self.assertIn("runtime_min_avg", item["media_probe"]["overwritten_fields"])

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

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
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

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
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

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
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

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
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

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(stats["files_probed"], 3)
        self.assertEqual(item["season_count"], 2)
        self.assertEqual(item["episode_count"], 3)
        self.assertEqual(item["runtime_min"], 180)
        self.assertEqual(item["runtime_min_avg"], 60)
        self.assertEqual(item["resolution"], "1080p")
        self.assertEqual(item["seasons"][0]["season_id"], "tv:Series:Show:s01")
        self.assertEqual(item["seasons"][1]["season_id"], "tv:Series:Show:s02")
        self.assertEqual(item["seasons"][0]["episodes_found"], 2)
        self.assertEqual(item["seasons"][0]["resolution"], "1080p")
        self.assertEqual(item["seasons"][1]["resolution"], "4K")
        self.assertIn("quality", item)
        self.assertEqual(item["media_probe"]["status"], "ok")

    def test_series_probe_keeps_seasonless_anime_without_artificial_season(self):
        series_dir = self.library_root / "Anime" / "One Piece"
        series_dir.mkdir(parents=True)
        (series_dir / "One Piece.E123.mkv").write_bytes(b"1")
        self.write_library([
            {
                "id": "tv:Anime:One.Piece",
                "path": "Anime/One Piece",
                "title": "One Piece",
                "category": "Anime",
                "type": "tv",
            }
        ])

        with patch.object(media_probe.subprocess, "run", return_value=completed(ffprobe_payload())):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["episode_count"], 1)
        self.assertEqual(item["season_count"], 0)
        self.assertEqual(item["seasons"], [])

    def test_series_language_and_subtitle_aggregation_uses_episode_unions(self):
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
            }
        ])

        def fake_run(cmd, **kwargs):
            path = cmd[-1]
            if "S01E01" in path:
                return completed(ffprobe_payload(audio_lang="fre", subtitle_lang="eng"))
            if "S01E02" in path:
                payload = ffprobe_payload(audio_lang="en", subtitle_lang="fre")
                payload["streams"][1]["tags"] = {"LANGUAGE": "en"}
                payload["streams"][2]["tags"] = {"Language": "fre"}
                return completed(payload)
            return completed(ffprobe_payload(audio_lang="es", subtitle_lang="japanese"))

        with patch.object(media_probe.subprocess, "run", side_effect=fake_run):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["seasons"][0]["audio_languages"], ["eng", "fra"])
        self.assertEqual(item["seasons"][0]["audio_languages_simple"], "MULTI")
        self.assertEqual(item["seasons"][0]["subtitle_languages"], ["eng", "fra"])
        self.assertEqual(item["seasons"][1]["audio_languages"], ["spa"])
        self.assertEqual(item["seasons"][1]["audio_languages_simple"], "VO")
        self.assertEqual(item["seasons"][1]["subtitle_languages"], ["jpn"])
        self.assertEqual(item["audio_languages"], ["eng", "fra", "spa"])
        self.assertEqual(item["audio_languages_simple"], "MULTI")
        self.assertEqual(item["subtitle_languages"], ["eng", "fra", "jpn"])

    def test_series_without_detected_languages_preserves_existing_language_fields(self):
        series_dir = self.library_root / "Series" / "Show"
        (series_dir / "Season 01").mkdir(parents=True)
        (series_dir / "Season 02").mkdir(parents=True)
        (series_dir / "Season 01" / "Show.S01E01.mkv").write_bytes(b"1")
        (series_dir / "Season 02" / "Show.S02E01.mkv").write_bytes(b"1")
        self.write_library([
            {
                "id": "tv:Series:Show",
                "path": "Series/Show",
                "title": "Show",
                "category": "Series",
                "type": "tv",
                "audio_languages": ["fra"],
                "audio_languages_simple": "VF",
                "subtitle_languages": ["eng"],
                "seasons": [
                    {
                        "season": 1,
                        "audio_languages": ["fra"],
                        "audio_languages_simple": "VF",
                        "subtitle_languages": ["eng"],
                    },
                    {
                        "season": 2,
                        "audio_languages": ["spa"],
                        "audio_languages_simple": "VO",
                        "subtitle_languages": ["fra"],
                    },
                ],
            }
        ])

        def fake_run(cmd, **kwargs):
            if "S02" in cmd[-1]:
                return completed(ffprobe_payload(audio_lang="eng", subtitle_lang="spa"))
            payload = ffprobe_payload(audio_lang="und", subtitle_lang="unknown")
            payload["streams"][1]["tags"] = {"language": "und"}
            payload["streams"][2]["tags"] = {"language": "unknown"}
            return completed(payload)

        with patch.object(media_probe.subprocess, "run", side_effect=fake_run):
            media_probe.generate_library_probe(
                library_json_path=self.library_json,
                output_path=self.probe_json,
                library_root=self.library_root,
            )

        item = json.loads(self.library_json.read_text(encoding="utf-8"))["items"][0]
        self.assertEqual(item["audio_languages"], ["eng", "fra"])
        self.assertEqual(item["audio_languages_simple"], "MULTI")
        self.assertEqual(item["subtitle_languages"], ["eng", "spa"])
        self.assertEqual(item["seasons"][0]["audio_languages"], ["fra"])
        self.assertEqual(item["seasons"][0]["audio_languages_simple"], "VF")
        self.assertEqual(item["seasons"][0]["subtitle_languages"], ["eng"])
        self.assertEqual(item["seasons"][1]["audio_languages"], ["eng"])
        self.assertEqual(item["seasons"][1]["audio_languages_simple"], "VO")
        self.assertEqual(item["seasons"][1]["subtitle_languages"], ["spa"])


class MediaProbeCacheRepositoryTest(unittest.TestCase):
    """Unit tests for media_probe_cache_repository without probe_data JSON."""

    def _make_db(self, db_path: pathlib.Path, media_id: str) -> None:
        import db as _db
        from repositories import media_probe_cache_repository as mpcr
        conn = _db.initialize_database(db_path)
        with conn:
            conn.execute(
                "INSERT INTO media(id, media_type, title) VALUES (?, 'movie', 'Film')", (media_id,)
            )
        conn.close()

    def _make_probe(self, codec: str = "H.265", audio_lang: list | None = None) -> dict:
        return {
            "ok": True,
            "technical": {
                "width": 1920, "height": 1080, "resolution": "1080p",
                "codec": codec, "hdr": False, "hdr_type": None,
                "runtime_min": 90, "runtime_min_avg": 90, "video_bitrate": 4000000,
                "audio_codec": "DTS-HD MA", "audio_codec_raw": "dts",
                "audio_channels": "5.1",
                "audio_languages": audio_lang or ["fr"],
                "subtitle_languages": ["fr", "en"],
                "audio_bitrate": 1200000, "audio_languages_simple": "VF",
                "framerate": 23.976, "container": "MKV",
                "dolby_vision": False, "size_b": 5368709120,
            },
        }

    def test_upsert_and_get_round_trip(self):
        """upsert() + get() returns the same probe dict (no JSON blob involved)."""
        import db as _db
        from repositories import media_probe_cache_repository as mpcr
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            media_id = "m:test"
            movie_file = pathlib.Path(tmp) / "movie.mkv"
            movie_file.write_bytes(b"fake content")
            self._make_db(db_path, media_id)
            probe_in = self._make_probe()
            repo = mpcr.open_cache(db_path=db_path)
            repo.upsert(media_id, movie_file.name, movie_file, probe_in)
            probe_out = repo.get(media_id, movie_file.name, movie_file)
            repo.close()
            self.assertIsNotNone(probe_out)
            self.assertIs(probe_out["ok"], True)
            tech = probe_out["technical"]
            self.assertEqual(tech["width"], 1920)
            self.assertEqual(tech["codec"], "H.265")
            self.assertEqual(tech["audio_languages"], ["fr"])
            self.assertEqual(tech["subtitle_languages"], ["fr", "en"])
            self.assertIs(tech["hdr"], False)
            self.assertIs(tech["dolby_vision"], False)
            self.assertEqual(tech["framerate"], 23.976)
            self.assertEqual(tech["container"], "MKV")

    def test_cache_miss_when_size_changes(self):
        """get() returns None after file size changes (cache invalidation)."""
        import db as _db
        from repositories import media_probe_cache_repository as mpcr
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            media_id = "m:inval"
            movie_file = pathlib.Path(tmp) / "movie.mkv"
            movie_file.write_bytes(b"v1")
            self._make_db(db_path, media_id)
            repo = mpcr.open_cache(db_path=db_path)
            repo.upsert(media_id, movie_file.name, movie_file, self._make_probe())
            repo.close()
            movie_file.write_bytes(b"v2 different size")
            repo = mpcr.open_cache(db_path=db_path)
            result = repo.get(media_id, movie_file.name, movie_file)
            repo.close()
            self.assertIsNone(result)

    def test_no_probe_data_column_in_schema(self):
        """After v21, media_probe_cache must not have a probe_data column."""
        import db as _db
        with tempfile.TemporaryDirectory() as tmp:
            conn = _db.initialize_database(pathlib.Path(tmp) / "mml.db")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(media_probe_cache)").fetchall()}
            conn.close()
            self.assertNotIn("probe_data", cols)
            self.assertIn("probe_ok", cols)
            self.assertIn("audio_languages_json", cols)

    def test_audio_languages_json_stored_as_list(self):
        """audio_languages must be stored as a JSON array and retrieved as a list."""
        import db as _db
        from repositories import media_probe_cache_repository as mpcr
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            media_id = "m:lang"
            movie_file = pathlib.Path(tmp) / "movie.mkv"
            movie_file.write_bytes(b"content")
            self._make_db(db_path, media_id)
            probe_in = self._make_probe(audio_lang=["fr", "en", "de"])
            repo = mpcr.open_cache(db_path=db_path)
            repo.upsert(media_id, movie_file.name, movie_file, probe_in)
            probe_out = repo.get(media_id, movie_file.name, movie_file)
            repo.close()
            self.assertEqual(probe_out["technical"]["audio_languages"], ["fr", "en", "de"])

    def test_ok_false_probe_stored_and_retrieved(self):
        """Probes with ok=False must also be cached correctly."""
        import db as _db
        from repositories import media_probe_cache_repository as mpcr
        with tempfile.TemporaryDirectory() as tmp:
            db_path = pathlib.Path(tmp) / "mml.db"
            media_id = "m:err"
            movie_file = pathlib.Path(tmp) / "movie.mkv"
            movie_file.write_bytes(b"bad")
            self._make_db(db_path, media_id)
            probe_in = {"ok": False, "technical": {}}
            repo = mpcr.open_cache(db_path=db_path)
            repo.upsert(media_id, movie_file.name, movie_file, probe_in)
            probe_out = repo.get(media_id, movie_file.name, movie_file)
            repo.close()
            self.assertIsNotNone(probe_out)
            self.assertIs(probe_out["ok"], False)


if __name__ == "__main__":
    unittest.main()
