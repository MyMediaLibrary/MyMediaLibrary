"""Tests for the Phase 2 (ffprobe) pipeline promotion and phase renumbering."""

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class PipelineConstantsTest(unittest.TestCase):
    def test_phase_numbers(self):
        self.assertEqual(scanner.PHASE_SCAN, 1)
        self.assertEqual(scanner.PHASE_PROBE, 2)
        self.assertEqual(scanner.PHASE_ENRICH, 3)
        self.assertEqual(scanner.PHASE_SCORE, 4)
        self.assertEqual(scanner.PHASE_RECOMMENDATIONS, 5)

    def test_phase_order_is_sequential(self):
        self.assertEqual(
            scanner._PHASE_ORDER,
            [
                scanner.PHASE_SCAN,
                scanner.PHASE_PROBE,
                scanner.PHASE_ENRICH,
                scanner.PHASE_SCORE,
                scanner.PHASE_RECOMMENDATIONS,
            ],
        )

    def test_phase_labels_cover_all_phases(self):
        for phase_num, phase_id in scanner._PHASE_ID_BY_NUMBER.items():
            self.assertIn(phase_id, scanner._PHASE_LABELS, f"Phase {phase_num} has no label")

    def test_phase_labels_have_no_1b(self):
        self.assertNotIn("1B", scanner._PHASE_LABELS)
        self.assertNotIn("1b", scanner._PHASE_LABELS)

    def test_phase_id_by_number_has_no_1b(self):
        for phase_id in scanner._PHASE_ID_BY_NUMBER.values():
            self.assertNotEqual(phase_id.upper(), "1B")

    def test_scan_phase_state_has_no_1b(self):
        self.assertNotIn("1B", scanner._SCAN_PHASE_STATE)
        self.assertNotIn("1b", scanner._SCAN_PHASE_STATE)
        self.assertIn("2", scanner._SCAN_PHASE_STATE)
        self.assertEqual(scanner._SCAN_PHASE_STATE["2"], "ffprobe")

    def test_phase_2_label_is_ffprobe(self):
        label, description = scanner._PHASE_LABELS["2"]
        self.assertEqual(label, "FFPROBE")
        self.assertIn("FFprobe", description)

    def test_phase_3_label_is_seerr(self):
        label, _ = scanner._PHASE_LABELS["3"]
        self.assertEqual(label, "SEERR")

    def test_phase_4_label_is_scoring(self):
        label, _ = scanner._PHASE_LABELS["4"]
        self.assertEqual(label, "SCORING")


class PhasePlanFromConfigTest(unittest.TestCase):
    def test_probe_included_when_enabled(self):
        cfg = {
            "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
            "media_probe": {"enabled": True, "mode": "compare"},
        }
        phases = scanner._phase_plan_from_config(cfg)
        self.assertIn(scanner.PHASE_PROBE, phases)

    def test_probe_excluded_when_disabled(self):
        cfg = {
            "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
            "media_probe": {"enabled": False, "mode": "compare"},
        }
        phases = scanner._phase_plan_from_config(cfg)
        self.assertNotIn(scanner.PHASE_PROBE, phases)

    def test_probe_excluded_when_absent_from_config(self):
        cfg = {
            "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
        }
        phases = scanner._phase_plan_from_config(cfg)
        self.assertNotIn(scanner.PHASE_PROBE, phases)

    def test_probe_comes_after_scan(self):
        cfg = {
            "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
            "media_probe": {"enabled": True, "mode": "compare"},
        }
        phases = scanner._phase_plan_from_config(cfg)
        scan_idx = phases.index(scanner.PHASE_SCAN)
        probe_idx = phases.index(scanner.PHASE_PROBE)
        self.assertLess(scan_idx, probe_idx)

    def test_probe_comes_before_enrich(self):
        cfg = {
            "folders": [{"name": "Movies", "type": "movie", "enabled": True}],
            "media_probe": {"enabled": True, "mode": "compare"},
            "seerr": {"enabled": True, "url": "http://seerr"},
        }
        with patch.object(scanner, "_is_seerr_enrichment_active", return_value=True):
            phases = scanner._phase_plan_from_config(cfg)
        self.assertIn(scanner.PHASE_PROBE, phases)
        self.assertIn(scanner.PHASE_ENRICH, phases)
        probe_idx = phases.index(scanner.PHASE_PROBE)
        enrich_idx = phases.index(scanner.PHASE_ENRICH)
        self.assertLess(probe_idx, enrich_idx)


class RunProbeFunctionTest(unittest.TestCase):
    def test_run_probe_is_public_function(self):
        self.assertTrue(callable(scanner.run_probe))
        self.assertFalse(scanner.run_probe.__name__.startswith("_"))

    def test_run_probe_skips_when_disabled(self):
        with patch.object(scanner, "load_config", return_value={"media_probe": {"enabled": False}}), \
             patch.object(scanner, "run_media_probe_pipeline_if_enabled") as mock_pipeline:
            scanner.run_probe()
        mock_pipeline.assert_not_called()

    def test_run_probe_skips_when_library_missing(self):
        with patch.object(scanner, "load_config", return_value={"media_probe": {"enabled": True, "mode": "compare"}}), \
             patch.object(scanner, "library_document_exists", return_value=False), \
             patch.object(scanner, "run_media_probe_pipeline_if_enabled") as mock_pipeline:
            scanner.run_probe()
        mock_pipeline.assert_not_called()

    def test_run_probe_logs_phase_2_prefix(self):
        with patch.object(scanner, "load_config", return_value={"media_probe": {"enabled": True, "mode": "compare"}}), \
             patch.object(scanner, "library_document_exists", return_value=False), \
             self.assertLogs("scanner", level="INFO") as logs:
            scanner.run_probe()
        joined = "\n".join(logs.output)
        self.assertIn("[PHASE 2] [FFPROBE]", joined)
        self.assertNotIn("[PHASE 1B]", joined)


class MediaProbeCacheTest(unittest.TestCase):
    def test_cache_hit_prevents_reprobing(self):
        """When media_probe_cache has a valid entry, ffprobe is not re-run."""
        import media_probe as mp

        media_id = "movie:movies:TestMovie"
        filename = "TestMovie.2023.mkv"
        probe_data = {"ok": True, "technical": {"resolution": "1080p"}}

        mock_repo = MagicMock()
        mock_repo.get.return_value = probe_data

        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "movies" / "TestMovie"
            media_dir.mkdir(parents=True)
            video_file = media_dir / filename
            video_file.write_bytes(b"\x00" * 1024)

            doc = {
                "items": [{
                    "id": media_id,
                    "type": "movie",
                    "category": "movies",
                    "path": "movies/TestMovie",
                }]
            }

            with patch.object(mp, "_open_media_probe_cache_repo", return_value=mock_repo), \
                 patch.object(mp, "_open_probe_cache_repository", return_value=None), \
                 patch.object(mp, "_probe_video_file") as mock_ffprobe:
                result_doc, stats = mp._generate_probe_document(
                    doc,
                    library_root=root,
                    score_enabled=False,
                    score_config=None,
                    timeout=5.0,
                    workers=1,
                    cache_enabled=True,
                    cache_path="/tmp/unused.json",
                    only_category=None,
                    include_diagnostics=False,
                )

        mock_ffprobe.assert_not_called()
        mock_repo.get.assert_called_once()

    def test_cache_miss_triggers_ffprobe_and_writes_to_cache(self):
        """When media_probe_cache has no entry, ffprobe runs and result is cached."""
        import media_probe as mp

        media_id = "movie:movies:TestMovie"
        filename = "TestMovie.2023.mkv"
        probe_data = {"ok": True, "technical": {"resolution": "1080p"}}

        mock_repo = MagicMock()
        mock_repo.get.return_value = None  # cache miss

        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "movies" / "TestMovie"
            media_dir.mkdir(parents=True)
            video_file = media_dir / filename
            video_file.write_bytes(b"\x00" * 1024)

            doc = {
                "items": [{
                    "id": media_id,
                    "type": "movie",
                    "category": "movies",
                    "path": "movies/TestMovie",
                }]
            }

            with patch.object(mp, "_open_media_probe_cache_repo", return_value=mock_repo), \
                 patch.object(mp, "_open_probe_cache_repository", return_value=None), \
                 patch.object(mp, "_probe_video_file", return_value=probe_data) as mock_ffprobe:
                mp._generate_probe_document(
                    doc,
                    library_root=root,
                    score_enabled=False,
                    score_config=None,
                    timeout=5.0,
                    workers=1,
                    cache_enabled=True,
                    cache_path="/tmp/unused.json",
                    only_category=None,
                    include_diagnostics=False,
                )

        mock_ffprobe.assert_called_once()
        mock_repo.upsert.assert_called_once()
        call_kwargs = mock_repo.upsert.call_args
        self.assertEqual(call_kwargs.args[0], media_id)
        self.assertEqual(call_kwargs.args[1], filename)

    def test_filename_change_invalidates_cache(self):
        """Cache miss when filename changes (even same media_id)."""
        import media_probe as mp

        media_id = "movie:movies:TestMovie"
        old_filename = "TestMovie.2023.1080p.mkv"
        new_filename = "TestMovie.2023.2160p.mkv"
        probe_data = {"ok": True, "technical": {"resolution": "4K"}}

        # Cache returns None for new filename (miss)
        def cache_get(mid, fname, path):
            if fname == old_filename:
                return {"ok": True, "technical": {"resolution": "1080p"}}
            return None  # new filename → cache miss

        mock_repo = MagicMock()
        mock_repo.get.side_effect = cache_get

        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            media_dir = root / "movies" / "TestMovie"
            media_dir.mkdir(parents=True)
            # New 4K file on disk
            video_file = media_dir / new_filename
            video_file.write_bytes(b"\x00" * 4096)

            doc = {
                "items": [{
                    "id": media_id,
                    "type": "movie",
                    "category": "movies",
                    "path": "movies/TestMovie",
                }]
            }

            with patch.object(mp, "_open_media_probe_cache_repo", return_value=mock_repo), \
                 patch.object(mp, "_open_probe_cache_repository", return_value=None), \
                 patch.object(mp, "_probe_video_file", return_value=probe_data) as mock_ffprobe:
                mp._generate_probe_document(
                    doc,
                    library_root=root,
                    score_enabled=False,
                    score_config=None,
                    timeout=5.0,
                    workers=1,
                    cache_enabled=True,
                    cache_path="/tmp/unused.json",
                    only_category=None,
                    include_diagnostics=False,
                )

        # ffprobe should have been called (cache miss for new filename)
        mock_ffprobe.assert_called_once()
        mock_repo.upsert.assert_called_once()
        upsert_args = mock_repo.upsert.call_args.args
        self.assertEqual(upsert_args[1], new_filename)


if __name__ == "__main__":
    unittest.main()
