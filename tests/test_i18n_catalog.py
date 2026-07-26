import ast
from pathlib import Path
import unittest

from bdo_transcription import (
    BACKEND_CHECK_FAILED_MESSAGE,
    BACKEND_MODULE_LOAD_FAILED_MESSAGE,
    FROZEN_BACKEND_UNAVAILABLE_MESSAGE,
    SOURCE_BACKEND_UNAVAILABLE_MESSAGE,
)
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

    def test_transcription_candidate_workflow_is_translated(self):
        required = {
            "扒谱模式",
            "开启参考音频分析与候选音符审阅",
            "分析参考音频",
            "识别结果仅作为候选，不会自动写入当前轨道",
            "写入当前轨草稿",
            "清除候选",
            "扒谱分析未改变任何正式音符",
            "仅播放参考音频",
        }
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] != source for source in required))
                rendered = catalog[
                    "已写入草稿 {accepted} 个 · 跳过重复 {duplicates} · 越界 {invalid}"
                ].format(accepted=3, duplicates=1, invalid=2)
                self.assertIn("3", rendered)
                self.assertIn("1", rendered)
                self.assertIn("2", rendered)

    def test_embedded_transcription_editor_is_translated(self):
        required = {
            "扒谱",
            "扒谱模式",
            "载入参考音频",
            "卸载参考音频",
            "分析整首",
            "重新分析区间",
            "置信度",
            "仅已拒绝",
            "证据轮廓",
            "清除 A–B",
            "音频位置对齐播放头",
            "将播放头设为第一拍",
            "审阅撤销",
            "审阅重做",
            "拒绝",
            "恢复",
            "写入当前轨草稿",
            "显式复制到…",
            "清除本次暂存",
            "存在未提交候选草稿",
            "当前仍有未提交候选草稿。请先应用，或撤销/清除本次暂存后再更换音频、调整偏移或重新分析。",
            "选择扒谱目标轨",
            "请选择一条旋律乐器轨后进入扒谱模式。",
            "当前没有可用的旋律乐器轨，请先新建乐器轨。",
            "循环区间",
            "循环播放 A–B 时间区间",
            "正在从缓存证据重新解码 A–B；不会再次运行模型。",
            "扒谱候选已作为一个工程操作写入；可整批撤销。",
            "区间重解码失败：{error}",
            FROZEN_BACKEND_UNAVAILABLE_MESSAGE,
            SOURCE_BACKEND_UNAVAILABLE_MESSAGE,
            BACKEND_CHECK_FAILED_MESSAGE,
            BACKEND_MODULE_LOAD_FAILED_MESSAGE,
        }
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] != source for source in required))
                routed = catalog[
                    "已路由 {count} 个 · 越界 {invalid} · 已满足 {duplicates}"
                ].format(count=4, invalid=1, duplicates=2)
                applied = catalog[
                    "已应用 {created} 个音符 · 已满足 {satisfied} · "
                    "保留失效 {invalid} · 孤立 {orphaned}"
                ].format(created=4, satisfied=2, invalid=1, orphaned=3)
                for number in ("4", "1", "2"):
                    self.assertIn(number, routed)
                for number in ("4", "2", "1", "3"):
                    self.assertIn(number, applied)
                interval_error = catalog[
                    "区间重解码失败：{error}"
                ].format(error="boom")
                self.assertIn("boom", interval_error)

    def test_every_chinese_transcription_widget_literal_is_catalogued(self):
        source_path = (
            Path(__file__).resolve().parents[1] / "transcription_editor_qt.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        source_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and any("\u4e00" <= character <= "\u9fff" for character in node.value)
        }
        self.assertTrue(source_literals)
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(source_literals.issubset(catalog))

    def test_every_localized_piano_roll_literal_is_catalogued(self):
        source_path = Path(__file__).resolve().parents[1] / "pyside_bdo_gui.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        source_literals = set()
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not node.args
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
            ):
                continue
            function = node.func
            function_name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            source = node.args[0].value
            if function_name in {"tr", "trf", "_tr"} and any(
                "\u4e00" <= character <= "\u9fff"
                for character in source
            ):
                source_literals.add(source)
        self.assertTrue(source_literals)
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(source_literals.issubset(catalog))

    def test_parameterized_text_formats_without_a_localizer(self):
        self.assertEqual(
            trf("已选 {selected} · 共 {total} 音符{position}{warning}",
                selected=2, total=8, position="", warning=""),
            "已选 2 · 共 8 音符",
        )


if __name__ == "__main__":
    unittest.main()
