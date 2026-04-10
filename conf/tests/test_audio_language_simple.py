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

    def test_unknown_for_empty_or_invalid_values(self):
        self.assertEqual(scanner.simplify_audio_languages([]), 'UNKNOWN')
        self.assertEqual(scanner.simplify_audio_languages(None), 'UNKNOWN')

    def test_vo_for_non_french_languages(self):
        self.assertEqual(scanner.simplify_audio_languages(['en', 'ja']), 'VO')


class ParseAudioLanguageRawTest(unittest.TestCase):
    def test_single_and_concat_codes(self):
        self.assertEqual(scanner._parse_lang_raw('fre'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('french'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('fr'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('ru'), ['rus'])
        self.assertEqual(scanner._parse_lang_raw('eng'), ['eng'])
        self.assertEqual(scanner._parse_lang_raw('freru'), ['fra', 'rus'])
        self.assertEqual(scanner._parse_lang_raw('engfre'), ['eng', 'fra'])
        self.assertEqual(scanner._parse_lang_raw('jpneng'), ['jpn', 'eng'])
        self.assertEqual(scanner._parse_lang_raw('freijo'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('freijoeng'), ['fra', 'eng'])
        self.assertEqual(scanner._parse_lang_raw('fregsw'), ['fra', 'gsw'])
        self.assertEqual(scanner._parse_lang_raw('frefrenob'), ['fra', 'fra', 'nob'])

    def test_empty_or_null_like_values(self):
        self.assertEqual(scanner._parse_lang_raw(''), [])
        self.assertEqual(scanner._parse_lang_raw('   '), [])
        self.assertEqual(scanner._parse_lang_raw(None), [])

    def test_release_aliases_and_separators(self):
        self.assertEqual(scanner._parse_lang_raw('vf'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('vff'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('truefrench'), ['fra'])
        self.assertEqual(scanner._parse_lang_raw('fr_en+ja|ita'), ['fra', 'eng', 'jpn', 'ita'])
        self.assertEqual(scanner._parse_lang_raw('vo'), [])
        self.assertEqual(scanner._parse_lang_raw('multi'), [])

    def test_long_repetitive_values_do_not_crash(self):
        self.assertEqual(scanner._parse_lang_raw('fre' * 500), ['fra'] * 500)

    def test_long_malformed_values_do_not_crash(self):
        self.assertEqual(scanner._parse_lang_raw('abcdef' * 400), [])

    def test_parse_audio_languages_deduplicates(self):
        import xml.etree.ElementTree as ET
        xml = ET.fromstring("<movie><audio><language>frefrenob</language></audio></movie>")
        self.assertEqual(scanner.parse_audio_languages(xml), ['fra', 'nob'])

    def test_parse_concatenated_keeps_unknown_chunks_and_recovers(self):
        recognized, unknown = scanner._parse_concatenated_lang_codes('freijoeng')
        self.assertEqual(recognized, ['fra', 'eng'])
        self.assertEqual(unknown, ['ijo'])

    def test_simplified_mapping_with_parsed_values(self):
        self.assertEqual(scanner.simplify_audio_languages(scanner._parse_lang_raw('fre')), 'VF')
        self.assertEqual(scanner.simplify_audio_languages(scanner._parse_lang_raw('ru')), 'VO')
        self.assertEqual(scanner.simplify_audio_languages(scanner._parse_lang_raw('freru')), 'MULTI')
        self.assertEqual(scanner.simplify_audio_languages(scanner._parse_lang_raw('engfre')), 'MULTI')
        self.assertEqual(scanner.simplify_audio_languages(scanner._parse_lang_raw('jpneng')), 'VO')
        self.assertEqual(scanner.simplify_audio_languages(scanner._parse_lang_raw('')), 'UNKNOWN')
        self.assertEqual(scanner.simplify_audio_languages(None), 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
