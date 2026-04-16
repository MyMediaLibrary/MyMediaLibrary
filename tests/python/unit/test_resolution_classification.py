import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class ResolutionClassificationTests(unittest.TestCase):
    def test_standard_resolutions(self):
        self.assertEqual(scanner.classify_resolution(1920, 1080), "1080p")
        self.assertEqual(scanner.classify_resolution(1280, 720), "720p")
        self.assertEqual(scanner.classify_resolution(3840, 2160), "4K")

    def test_scope_4k_is_not_downgraded_to_1080p(self):
        self.assertEqual(scanner.classify_resolution(3828, 1592), "4K")

    def test_near_square_2k_sources_are_not_promoted_to_4k(self):
        self.assertEqual(scanner.classify_resolution(2100, 2100), "1080p")
        self.assertEqual(scanner.classify_resolution(2560, 2100), "1080p")

    def test_atypical_5_4_sources_are_not_promoted_to_1080p(self):
        self.assertEqual(scanner.classify_resolution(1280, 1024), "720p")
        self.assertEqual(scanner.classify_resolution(1360, 1024), "720p")

    def test_scope_1080p_keeps_1080p_when_long_edge_is_full_hd(self):
        self.assertEqual(scanner.classify_resolution(1920, 804), "1080p")

    def test_sub_720_square_sources_stay_sd(self):
        self.assertEqual(scanner.classify_resolution(700, 700), "SD")


if __name__ == "__main__":
    unittest.main()
