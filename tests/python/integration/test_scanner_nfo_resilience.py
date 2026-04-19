import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402
from nfo import _parse_nfo_xml  # noqa: E402


class NfoResilienceIntegrationTest(unittest.TestCase):
    def test_truncated_malformed_nfo_is_still_parsed(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "movie.nfo"
            path.write_text((FIXTURES / "nfo_malformed.nfo").read_text(encoding="utf-8"), encoding="utf-8")

            root = _parse_nfo_xml(path)
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

    def test_movie_nfo_prefers_tmdb_uniqueid(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>Inception</title>
  <id>99999</id>
  <uniqueid type="tmdb" default="true">27205</uniqueid>
</movie>
"""
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "movie.nfo"
            path.write_text(xml, encoding="utf-8")
            result = scanner.parse_movie_nfo(path)
            self.assertEqual(result.get("tmdb_id"), "27205")

    def test_tvshow_nfo_separates_tmdb_and_tvdb_ids(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<tvshow>
  <title>Andor</title>
  <id>83867</id>
  <uniqueid type="tvdb" default="true">83867</uniqueid>
  <uniqueid type="tmdb">228068</uniqueid>
</tvshow>
"""
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "tvshow.nfo"
            path.write_text(xml, encoding="utf-8")
            result = scanner.parse_tvshow_nfo(path)
            self.assertEqual(result.get("tmdb_id"), "228068")
            self.assertEqual(result.get("tvdb_id"), "83867")

    def test_tvshow_nfo_id_fallback_maps_to_tvdb_not_tmdb(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<tvshow>
  <title>La Casa de Papel</title>
  <id>311954</id>
</tvshow>
"""
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "tvshow.nfo"
            path.write_text(xml, encoding="utf-8")
            result = scanner.parse_tvshow_nfo(path)
            self.assertIsNone(result.get("tmdb_id"))
            self.assertEqual(result.get("tvdb_id"), "311954")


if __name__ == "__main__":
    unittest.main()
