import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "conf"))

import scoring  # noqa: E402


def _gb(value: float) -> int:
    return int(value * (1024 ** 3))


class QualityScoringV1Test(unittest.TestCase):
    def test_video_scores(self):
        self.assertEqual(
            scoring.compute_video_quality_score({"resolution": "4K", "codec": "H.265", "hdr_type": "Dolby Vision"})["score"],
            50,
        )
        self.assertEqual(
            scoring.compute_video_quality_score({"resolution": "1080p", "codec": "H.264", "hdr": False})["score"],
            30,
        )
        self.assertEqual(
            scoring.compute_video_quality_score({"resolution": "SD", "codec": "DivX", "hdr": False})["score"],
            8,
        )
        self.assertEqual(scoring.compute_video_quality_score({})["score"], 14)

    def test_audio_scores(self):
        self.assertEqual(scoring.compute_audio_quality_score({"audio_codec_raw": "TRUEHD ATMOS"}), 20)
        self.assertEqual(scoring.compute_audio_quality_score({"audio_codec_raw": "DTS-HD MA"}), 18)
        self.assertEqual(scoring.compute_audio_quality_score({"audio_codec": "AAC"}), 6)
        self.assertEqual(scoring.compute_audio_quality_score({}), 8)

    def test_language_scores(self):
        self.assertEqual(scoring.compute_language_quality_score({"audio_languages_simple": "MULTI"}), 15)
        self.assertEqual(scoring.compute_language_quality_score({"audio_languages_simple": "VF"}), 10)
        self.assertEqual(scoring.compute_language_quality_score({"audio_languages_simple": "VO"}), 5)
        self.assertEqual(scoring.compute_language_quality_score({}), 3)

    def test_size_scores(self):
        self.assertEqual(
            scoring.compute_size_quality_score({"resolution": "1080p", "codec": "H.265", "size_b": _gb(5)}),
            15,
        )
        self.assertEqual(
            scoring.compute_size_quality_score({"resolution": "1080p", "codec": "H.264", "size_b": _gb(20)}),
            8,
        )
        self.assertEqual(
            scoring.compute_size_quality_score({"resolution": "4K", "codec": "H.265", "size_b": _gb(5)}),
            5,
        )
        self.assertEqual(scoring.compute_size_quality_score({}), 5)

    def test_penalties_and_cap(self):
        penalties = scoring.compute_quality_penalties(
            {},
            {
                "video": 45,
                "audio": 6,
                "languages": 5,
                "size": 5,
                "video_details": {"resolution_score": 20, "video_codec_family": "legacy"},
            },
        )
        self.assertEqual(sum(p["value"] for p in penalties), 28)

        quality = scoring.compute_quality(
            {
                "resolution": "4K",
                "codec": "H.264",
                "hdr_type": "Dolby Vision",
                "audio_codec": "AAC",
                "audio_languages_simple": "VO",
                "size_b": _gb(4),
            }
        )
        self.assertEqual(quality["penalty_total"], 20)

    def test_quality_level_boundaries(self):
        self.assertEqual(scoring.get_quality_level(0), 1)
        self.assertEqual(scoring.get_quality_level(20), 1)
        self.assertEqual(scoring.get_quality_level(21), 2)
        self.assertEqual(scoring.get_quality_level(40), 2)
        self.assertEqual(scoring.get_quality_level(41), 3)
        self.assertEqual(scoring.get_quality_level(60), 3)
        self.assertEqual(scoring.get_quality_level(61), 4)
        self.assertEqual(scoring.get_quality_level(80), 4)
        self.assertEqual(scoring.get_quality_level(81), 5)
        self.assertEqual(scoring.get_quality_level(100), 5)

    def test_final_score_level_and_shape(self):
        quality = scoring.compute_quality(
            {
                "resolution": "1080p",
                "codec": "H.264",
                "hdr": False,
                "audio_codec": "Dolby Digital",
                "audio_languages_simple": "VF",
                "size_b": _gb(8),
            }
        )
        self.assertEqual(quality["score"], 65)
        self.assertEqual(quality["level"], 4)

        expected_keys = {
            "score",
            "level",
            "base_score",
            "penalty_total",
            "video",
            "audio",
            "languages",
            "size",
            "penalties",
        }
        self.assertTrue(expected_keys.issubset(set(quality.keys())))

        low_quality = scoring.compute_quality(
            {
                "resolution": "4K",
                "codec": "MPEG-2",
                "hdr_type": "Dolby Vision",
                "audio_codec": "MP3",
                "audio_languages_simple": "VO",
                "size_b": _gb(2),
            }
        )
        self.assertGreaterEqual(low_quality["score"], 0)
        self.assertLessEqual(low_quality["score"], 100)


if __name__ == "__main__":
    unittest.main()
