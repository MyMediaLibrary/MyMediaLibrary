"""Tests for run_phases() dispatch: each phase calls the right function, once."""

import pathlib
import sys
import unittest
from unittest.mock import call, patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class PhaseDispatchTest(unittest.TestCase):
    """run_phases() must call exactly one function per phase, in order."""

    def _run(self, phases, *, probe_enabled=False):
        """Helper: run run_phases with all run_* patched, return call log."""
        calls = []
        probe_cfg = {"enabled": probe_enabled, "mode": "compare"}
        with patch.object(scanner, "run_quick",         side_effect=lambda **_: calls.append("scan")),    \
             patch.object(scanner, "run_probe",         side_effect=lambda **_: calls.append("probe")),   \
             patch.object(scanner, "run_enrich",        side_effect=lambda **_: calls.append("enrich")),  \
             patch.object(scanner, "run_scoring",       side_effect=lambda **_: calls.append("score")),   \
             patch.object(scanner, "run_recommendations", side_effect=lambda: calls.append("recs")):
            scanner.run_phases(phases)
        return calls

    def test_full_pipeline_1_2_3_4_5_calls_each_function_once(self):
        calls = self._run([
            scanner.PHASE_SCAN,
            scanner.PHASE_PROBE,
            scanner.PHASE_ENRICH,
            scanner.PHASE_SCORE,
            scanner.PHASE_RECOMMENDATIONS,
        ])
        self.assertEqual(calls, ["scan", "probe", "enrich", "score", "recs"])

    def test_each_function_called_exactly_once(self):
        calls = self._run([
            scanner.PHASE_SCAN,
            scanner.PHASE_PROBE,
            scanner.PHASE_ENRICH,
            scanner.PHASE_SCORE,
            scanner.PHASE_RECOMMENDATIONS,
        ])
        self.assertEqual(calls.count("scan"),   1)
        self.assertEqual(calls.count("probe"),  1)
        self.assertEqual(calls.count("enrich"), 1)
        self.assertEqual(calls.count("score"),  1)
        self.assertEqual(calls.count("recs"),   1)

    def test_phase_2_calls_run_probe_not_run_enrich(self):
        calls = self._run([scanner.PHASE_PROBE])
        self.assertIn("probe", calls)
        self.assertNotIn("enrich", calls)
        self.assertNotIn("scan", calls)

    def test_phase_3_calls_run_enrich_not_run_probe(self):
        calls = self._run([scanner.PHASE_ENRICH])
        self.assertIn("enrich", calls)
        self.assertNotIn("probe", calls)
        self.assertNotIn("score", calls)

    def test_phase_4_calls_run_scoring_not_run_enrich(self):
        calls = self._run([scanner.PHASE_SCORE])
        self.assertIn("score", calls)
        self.assertNotIn("enrich", calls)
        self.assertNotIn("probe", calls)

    def test_phase_5_calls_run_recommendations_only(self):
        calls = self._run([scanner.PHASE_RECOMMENDATIONS])
        self.assertIn("recs", calls)
        self.assertNotIn("score", calls)
        self.assertNotIn("enrich", calls)

    def test_probe_not_triggered_by_phase_scan_alone(self):
        """Phase 1 must not auto-trigger probe anymore (1B pattern removed)."""
        calls = self._run([scanner.PHASE_SCAN])
        self.assertEqual(calls, ["scan"])
        self.assertNotIn("probe", calls)

    def test_order_preserved(self):
        calls = self._run([
            scanner.PHASE_SCAN,
            scanner.PHASE_PROBE,
            scanner.PHASE_ENRICH,
        ])
        self.assertEqual(calls.index("scan"),  0)
        self.assertEqual(calls.index("probe"), 1)
        self.assertEqual(calls.index("enrich"), 2)

    def test_durations_returned_with_correct_phase_ids(self):
        with patch.object(scanner, "run_quick"),      \
             patch.object(scanner, "run_probe"),      \
             patch.object(scanner, "run_enrich"),     \
             patch.object(scanner, "run_scoring"),    \
             patch.object(scanner, "run_recommendations"):
            durations = scanner.run_phases([
                scanner.PHASE_SCAN,
                scanner.PHASE_PROBE,
                scanner.PHASE_ENRICH,
                scanner.PHASE_SCORE,
                scanner.PHASE_RECOMMENDATIONS,
            ])
        ids = [d[0] for d in durations]
        self.assertEqual(ids, ["1", "2", "3", "4", "5"])


class PhaseLabelConsistencyTest(unittest.TestCase):
    """Phase labels must match the functions that execute them."""

    def test_phase_2_label_is_ffprobe(self):
        label, _ = scanner._PHASE_LABELS["2"]
        self.assertEqual(label, "FFPROBE")

    def test_phase_3_label_is_seerr(self):
        label, _ = scanner._PHASE_LABELS["3"]
        self.assertEqual(label, "SEERR")

    def test_phase_4_label_is_scoring(self):
        label, _ = scanner._PHASE_LABELS["4"]
        self.assertEqual(label, "SCORING")

    def test_run_enrich_logs_phase_3(self):
        with patch.object(scanner, "load_config", return_value={"seerr": {"enabled": False}}), \
             self.assertLogs("scanner", level="WARNING") as logs:
            scanner.run_enrich()
        joined = "\n".join(logs.output)
        self.assertIn("[PHASE 3] [SEERR]", joined)
        self.assertNotIn("[PHASE 2]", joined)

    def test_run_scoring_logs_phase_4(self):
        with patch.object(scanner, "load_config", return_value={"score": {"enabled": False}}), \
             self.assertLogs("scanner", level="INFO") as logs:
            scanner.run_scoring()
        joined = "\n".join(logs.output)
        self.assertIn("[PHASE 4] [SCORING]", joined)
        self.assertNotIn("[PHASE 3]", joined)

    def test_run_probe_logs_phase_2(self):
        # probe enabled but library empty → logs "Skipping" under [PHASE 2]
        with patch.object(scanner, "load_config", return_value={"media_probe": {"enabled": True, "mode": "compare"}}), \
             patch.object(scanner, "library_document_exists", return_value=False), \
             self.assertLogs("scanner", level="INFO") as logs:
            scanner.run_probe()
        joined = "\n".join(logs.output)
        self.assertIn("[PHASE 2] [FFPROBE]", joined)
        self.assertNotIn("[PHASE 1B]", joined)

    def test_no_phase_id_mismatch_in_enrich_or_scoring(self):
        """Ensure run_enrich never emits [PHASE 2] and run_scoring never emits [PHASE 3]."""
        # run_enrich: seerr disabled → fast exit, check log has no [PHASE 2]
        with patch.object(scanner, "load_config", return_value={"seerr": {"enabled": False}}), \
             self.assertLogs("scanner", level="WARNING") as logs:
            scanner.run_enrich()
        self.assertNotIn("[PHASE 2]", "\n".join(logs.output))

        # run_scoring: score disabled → fast exit, check log has no [PHASE 3]
        with patch.object(scanner, "load_config", return_value={"score": {"enabled": False}}), \
             self.assertLogs("scanner", level="INFO") as logs:
            scanner.run_scoring()
        self.assertNotIn("[PHASE 3]", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
