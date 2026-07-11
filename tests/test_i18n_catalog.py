import unittest

from i18n import LANGUAGES, TRANSLATIONS


class TranslationCatalogTests(unittest.TestCase):
    def test_supported_languages_are_declared(self):
        self.assertEqual([code for code, _label in LANGUAGES], ["zh_CN", "en_US", "ja_JP", "ko_KR"])

    def test_core_workflow_is_translated_in_every_catalog(self):
        required = {
            "导入 MIDI", "打开工程", "全局优化", "设置", "转换",
            "新建轨道", "删除轨道", "音符属性", "优化此轨", "界面语言",
        }
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] != source for source in required))


if __name__ == "__main__":
    unittest.main()
