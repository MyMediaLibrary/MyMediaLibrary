import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "conf"))

import scanner  # noqa: E402


class NfoResilienceIntegrationTest(unittest.TestCase):
    def test_truncated_malformed_nfo_is_still_parsed(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "movie.nfo"
            path.write_text((FIXTURES / "nfo_malformed.nfo").read_text(encoding="utf-8"), encoding="utf-8")

            root = scanner._parse_nfo_xml(path)
            self.assertIsNotNone(root)
            result = scanner.parse_movie_nfo(path)

            self.assertEqual(result["resolution"], "4K")
            self.assertEqual(result["codec"], "H.265")
            self.assertEqual(result["audio_languages"], ["fra", "rus"])
            self.assertEqual(result["audio_languages_simple"], "MULTI")

    def test_missing_audio_fields_returns_unknown_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "movie.nfo"
            path.write_text((FIXTURES / "nfo_missing_audio.nfo").read_text(encoding="utf-8"), encoding="utf-8")

            result = scanner.parse_movie_nfo(path)
            self.assertEqual(result["resolution"], "1080p")
            self.assertEqual(result["audio_languages"], [])
            self.assertEqual(result["audio_languages_simple"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
