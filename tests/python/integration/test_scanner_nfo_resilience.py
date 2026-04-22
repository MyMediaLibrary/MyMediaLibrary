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
            self.assertIsNone(result.get("audio_channels"))
            self.assertIsNone(result.get("subtitle_languages"))
            self.assertIsNone(result.get("video_bitrate"))
            self.assertIsNone(result.get("genres"))

    def test_movie_streamdetails_extracts_new_fields(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>Demo</title>
  <fileinfo>
    <streamdetails>
      <video>
        <width>1920</width>
        <height>1080</height>
        <bitrate>7500000</bitrate>
      </video>
      <audio>
        <codec>eac3</codec>
        <channels>6</channels>
        <language>fre</language>
      </audio>
      <subtitle><language>eng</language></subtitle>
      <subtitle><language>fra</language></subtitle>
    </streamdetails>
  </fileinfo>
</movie>
"""
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "movie.nfo"
            path.write_text(xml, encoding="utf-8")
            result = scanner.parse_movie_nfo(path)
            self.assertEqual(result.get("audio_channels"), "5.1")
            self.assertEqual(result.get("subtitle_languages"), ["eng", "fra"])
            self.assertEqual(result.get("video_bitrate"), 7500000)

    def test_movie_nfo_parses_genres_ordered_deduplicated(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>Demo</title>
  <genre> Action </genre>
  <genre>Science Fiction</genre>
  <genre>Action</genre>
</movie>
"""
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "movie.nfo"
            path.write_text(xml, encoding="utf-8")
            result = scanner.parse_movie_nfo(path)
            self.assertEqual(result.get("genres"), ["Action", "Science Fiction"])

    def test_tvshow_nfo_parses_genres_or_null_when_absent(self):
        xml_with = """<?xml version="1.0" encoding="UTF-8"?>
<tvshow>
  <title>Show</title>
  <genre>Drama</genre>
  <genre> Thriller </genre>
  <genre>Drama</genre>
</tvshow>
"""
        xml_without = """<?xml version="1.0" encoding="UTF-8"?>
<tvshow>
  <title>Show</title>
</tvshow>
"""
        with tempfile.TemporaryDirectory() as td:
            path_with = pathlib.Path(td) / "tvshow-with.nfo"
            path_without = pathlib.Path(td) / "tvshow-without.nfo"
            path_with.write_text(xml_with, encoding="utf-8")
            path_without.write_text(xml_without, encoding="utf-8")
            result_with = scanner.parse_tvshow_nfo(path_with)
            result_without = scanner.parse_tvshow_nfo(path_without)
            self.assertEqual(result_with.get("genres"), ["Drama", "Thriller"])
            self.assertIsNone(result_without.get("genres"))

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
