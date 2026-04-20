import json
import pathlib
import sys
import tempfile
import unittest
import copy
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class ScoreConfigBackendTest(unittest.TestCase):
    def test_validate_score_config_restores_required_default_paths(self):
        defaults = scanner.load_score_defaults()
        broken = scanner.merge_score_config(defaults, {})
        del broken["video"]["codec"]["default"]
        del broken["size"]["profiles"]["movie"]["default"]["default"]["min_gb"]

        effective, status = scanner.validate_score_config(broken, defaults=defaults)

        self.assertIn("default", effective["video"]["codec"])
        self.assertIn("min_gb", effective["size"]["profiles"]["movie"]["default"]["default"])
        self.assertEqual(status["weights_total"], 100)
        self.assertTrue(status["weights_valid"])

    def test_validate_score_payload_rejects_invalid_weight_sum(self):
        defaults = scanner.load_score_defaults()
        cfg = scanner.merge_score_config(defaults, {})
        cfg["weights"]["video"] = 49

        ok, err = scanner.validate_score_payload({"score": cfg}, defaults=defaults, strict=True)
        self.assertFalse(ok)
        self.assertEqual(err["error"]["code"], "INVALID_SCORE_CONFIG")

    def test_get_effective_score_config_merges_partial_score_config(self):
        cfg = {"score_configuration": {"weights": {"video": 49, "audio": 21, "languages": 15, "size": 15}}}
        defaults, effective, status = scanner.get_effective_score_config(cfg)
        self.assertNotIn("schema_version", defaults)
        self.assertNotIn("schema_version", effective)
        self.assertEqual(effective["weights"]["video"], 49)
        self.assertEqual(status["weights_total"], 100)
        self.assertTrue(status["weights_valid"])

    def test_validate_score_config_removes_legacy_penalties_block(self):
        defaults = scanner.load_score_defaults()
        cfg = scanner.merge_score_config(defaults, {})
        cfg["penalties"] = {"max_total": 20, "rules": {"size_incoherent": -5}}

        effective, status = scanner.validate_score_config(cfg, defaults=defaults)

        self.assertNotIn("penalties", effective)
        reasons = [note.get("reason") for note in status.get("normalization_notes", [])]
        self.assertIn("removed_deprecated", reasons)

    def test_recompute_scores_only_updates_library_quality_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = pathlib.Path(tmp) / "library.json"
            output_path.write_text(json.dumps({
                "items": [{
                    "title": "Movie",
                    "type": "movie",
                    "resolution": "1080p",
                    "codec": "H.265",
                    "audio_codec": "DTS-HD MA",
                    "audio_languages_simple": "MULTI",
                    "size_b": int(6 * (1024 ** 3)),
                    "quality": {"score": 1},
                    "custom": "keep",
                }]
            }), encoding="utf-8")

            with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                count = scanner.recompute_scores_only()

            self.assertEqual(count, 1)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["items"][0]["custom"], "keep")
            self.assertIn("quality", payload["items"][0])
            self.assertGreaterEqual(payload["items"][0]["quality"]["score"], 0)
            self.assertLessEqual(payload["items"][0]["quality"]["score"], 100)

    def test_recompute_scores_only_applies_weight_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = pathlib.Path(tmp) / "library.json"
            output_path.write_text(json.dumps({
                "items": [{
                    "title": "Movie",
                    "type": "movie",
                    "resolution": "1080p",
                    "codec": "H.264",
                    "audio_codec": "Dolby Digital",
                    "audio_languages_simple": "VF",
                    "size_b": int(8 * (1024 ** 3)),
                }]
            }), encoding="utf-8")

            defaults = scanner.load_score_defaults()
            score_cfg = copy.deepcopy(defaults)
            score_cfg["weights"] = {
                "video": 10,
                "audio": 10,
                "languages": 10,
                "size": 70,
            }

            with patch.object(scanner, "OUTPUT_PATH", str(output_path)):
                scanner.recompute_scores_only(defaults)
                baseline_payload = json.loads(output_path.read_text(encoding="utf-8"))
                baseline_score = baseline_payload["items"][0]["quality"]["score"]

                scanner.recompute_scores_only(score_cfg)
                shifted_payload = json.loads(output_path.read_text(encoding="utf-8"))
                shifted_score = shifted_payload["items"][0]["quality"]["score"]

            self.assertNotEqual(baseline_score, shifted_score)

    def test_run_score_only_does_not_trigger_scan_phases(self):
        with patch("scanner.run_quick") as run_quick, \
             patch("scanner.run_enrich") as run_enrich, \
             patch("scanner.run_scoring") as run_scoring, \
             patch("scanner.run_inventory") as run_inventory, \
             patch("scanner.recompute_scores_only", return_value=0), \
             patch("scanner._scan_lock"), \
             patch("scanner.get_effective_score_config", return_value=({}, scanner.load_score_defaults(), {})):
            scanner.run_score_only()

        run_quick.assert_not_called()
        run_enrich.assert_not_called()
        run_scoring.assert_not_called()
        run_inventory.assert_not_called()
