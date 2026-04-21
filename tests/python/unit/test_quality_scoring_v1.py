import pathlib
import sys
import unittest
import copy

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scoring  # noqa: E402


def _gb(value: float) -> int:
    return int(value * (1024 ** 3))


class QualityScoringV1Test(unittest.TestCase):
    def test_max_helpers_from_active_config(self):
        cfg = scoring.get_builtin_score_defaults()
        self.assertEqual(scoring.get_max_video_score(cfg), 50)
        self.assertEqual(scoring.get_max_audio_score(cfg), 20)
        self.assertEqual(scoring.get_max_languages_score(cfg), 15)
        self.assertEqual(scoring.get_max_size_score(cfg), 15)

    def test_max_helpers_prefer_precomputed_max_score_block(self):
        cfg = scoring.get_builtin_score_defaults()
        cfg["max_score"] = {
            "max_video": 77,
            "max_audio": 31,
            "max_languages": 22,
            "max_size": 11,
        }
        self.assertEqual(scoring.get_max_video_score(cfg), 77)
        self.assertEqual(scoring.get_max_audio_score(cfg), 31)
        self.assertEqual(scoring.get_max_languages_score(cfg), 22)
        self.assertEqual(scoring.get_max_size_score(cfg), 11)

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

        expected_keys = {
            "score",
            "video",
            "audio",
            "languages",
            "size",
            "video_details",
        }
        self.assertTrue(expected_keys.issubset(set(quality.keys())))
        self.assertNotIn("level", quality)
        self.assertNotIn("base_score", quality)
        self.assertNotIn("score_details", quality)
        self.assertEqual(
            quality["video"],
            int(quality["video_details"]["resolution"])
            + int(quality["video_details"]["codec"])
            + int(quality["video_details"]["hdr"]),
        )

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

    def test_weights_change_score_when_only_weights_change(self):
        item = {
            "resolution": "1080p",
            "codec": "H.264",
            "hdr": False,
            "audio_codec": "Dolby Digital",
            "audio_languages_simple": "VF",
            "size_b": _gb(8),
        }
        defaults = scoring.get_builtin_score_defaults()
        baseline = scoring.compute_quality(item, defaults)["score"]

        reweighted = copy.deepcopy(defaults)
        reweighted["weights"] = {
            "video": 10,
            "audio": 10,
            "languages": 10,
            "size": 70,
        }
        shifted = scoring.compute_quality(item, reweighted)["score"]

        self.assertNotEqual(baseline, shifted)

    def test_score_formula_is_deterministic_even_with_invalid_weight_values(self):
        item = {
            "resolution": "2160p",
            "codec": "H.265",
            "hdr_type": "Dolby Vision",
            "audio_codec_raw": "TRUEHD ATMOS",
            "audio_languages_simple": "MULTI",
            "size_b": _gb(20),
        }
        cfg = scoring.get_builtin_score_defaults()
        cfg["weights"] = {
            "video": 200,
            "audio": 200,
            "languages": 200,
            "size": 200,
        }
        quality = scoring.compute_quality(item, cfg)
        self.assertEqual(
            quality["score"],
            quality["video_w"] + quality["audio_w"] + quality["languages_w"] + quality["size_w"],
        )
        self.assertEqual(
            quality["video"],
            quality["video_details"]["resolution"] + quality["video_details"]["codec"] + quality["video_details"]["hdr"],
        )


if __name__ == "__main__":
    unittest.main()
