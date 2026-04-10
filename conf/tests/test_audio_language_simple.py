import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import scanner  # noqa: E402


class SimplifyAudioLanguagesTest(unittest.TestCase):
    def test_vf_only_french(self):
        self.assertEqual(scanner.simplify_audio_languages(['fra']), 'VF')
        self.assertEqual(scanner.simplify_audio_languages(['fr']), 'VF')
        self.assertEqual(scanner.simplify_audio_languages(['FRE']), 'VF')

    def test_multi_requires_french_and_another_language(self):
        self.assertEqual(scanner.simplify_audio_languages(['fra', 'eng']), 'MULTI')
        self.assertEqual(scanner.simplify_audio_languages(['FR', 'ja']), 'MULTI')

    def test_vo_without_french_even_with_multiple_languages(self):
        self.assertEqual(scanner.simplify_audio_languages(['eng', 'jpn']), 'VO')
        self.assertEqual(scanner.simplify_audio_languages(['en', 'ja']), 'VO')

    def test_vo_for_empty_or_invalid_values(self):
        self.assertEqual(scanner.simplify_audio_languages([]), 'VO')
        self.assertEqual(scanner.simplify_audio_languages(None), 'VO')
        self.assertEqual(scanner.simplify_audio_languages(['unknown']), 'VO')


if __name__ == '__main__':
    unittest.main()
