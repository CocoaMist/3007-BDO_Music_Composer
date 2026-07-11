import unittest

from i18n import LANGUAGES, LANGUAGE_CHOICES, TRANSLATIONS, detect_language_from_timezone, trf


class TranslationCatalogTests(unittest.TestCase):
    def test_supported_languages_are_declared(self):
        self.assertEqual([code for code, _label in LANGUAGES], ["zh_CN", "en_US", "ja_JP", "ko_KR"])
        self.assertEqual(LANGUAGE_CHOICES[0][0], "auto")

    def test_timezone_language_detection(self):
        cases = {
            ("China Standard Time", 480): "zh_CN",
            ("Asia/Shanghai", 480): "zh_CN",
            ("Tokyo Standard Time", 540): "ja_JP",
            ("Asia/Tokyo", 540): "ja_JP",
            ("Korea Standard Time", 540): "ko_KR",
            ("Asia/Seoul", 540): "ko_KR",
            ("Pacific Standard Time", -480): "en_US",
            ("Unknown UTC+9", 540): "en_US",
        }
        for (name, offset), expected in cases.items():
            with self.subTest(timezone=name):
                self.assertEqual(detect_language_from_timezone(name, offset), expected)

    def test_core_workflow_is_translated_in_every_catalog(self):
        required = {
            "导入 MIDI", "打开工程", "全局优化", "设置", "转换",
            "新建轨道", "删除轨道", "音符属性", "优化此轨", "界面语言",
        }
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] != source for source in required))

    def test_non_chinese_catalogs_have_identical_source_coverage(self):
        key_sets = {language: set(catalog) for language, catalog in TRANSLATIONS.items()}
        baseline = key_sets["en_US"]
        for language, keys in key_sets.items():
            with self.subTest(language=language):
                self.assertEqual(keys, baseline)

    def test_parameterized_text_formats_without_a_localizer(self):
        self.assertEqual(
            trf("已选 {selected} · 共 {total} 音符{position}{warning}",
                selected=2, total=8, position="", warning=""),
            "已选 2 · 共 8 音符",
        )


if __name__ == "__main__":
    unittest.main()
