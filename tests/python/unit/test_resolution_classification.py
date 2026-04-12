import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "conf"))

import scanner  # noqa: E402


class ResolutionClassificationTests(unittest.TestCase):
    def test_standard_resolutions(self):
        self.assertEqual(scanner.classify_resolution(1920, 1080), "1080p")
        self.assertEqual(scanner.classify_resolution(1280, 720), "720p")
        self.assertEqual(scanner.classify_resolution(3840, 2160), "4K")

    def test_scope_4k_is_not_downgraded_to_1080p(self):
        self.assertEqual(scanner.classify_resolution(3828, 1592), "4K")


if __name__ == "__main__":
    unittest.main()
