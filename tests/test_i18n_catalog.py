import ast
import inspect
import os
from pathlib import Path
from string import Formatter
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSpinBox,
    QTabWidget,
    QWidget,
)

import i18n
from bdo_articulation_profiles import EvidenceLevel, PROFILES as ARTICULATION_PROFILES
from bdo_instrument_adaptation import articulation_pairs_by_instrument
from bdo_midi.instruments import BDO_INSTRUMENT_NAMES
from bdo_techniques import TECHNIQUE_PROFILES
from bdo_transcription import (
    BACKEND_CHECK_FAILED_MESSAGE,
    BACKEND_MODULE_LOAD_FAILED_MESSAGE,
    FROZEN_BACKEND_UNAVAILABLE_MESSAGE,
    SOURCE_BACKEND_UNAVAILABLE_MESSAGE,
)
from i18n import (
    LANGUAGES,
    LANGUAGE_CHOICES,
    Localizer,
    TRANSLATIONS,
    defer_tr,
    detect_language_from_timezone,
    install_localizer,
    tr,
    trf,
    trfv,
    tr_joinv,
    trv,
)
from optimization import builtin as optimizer_builtin


def _format_signature(template: str) -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted(
        (
            (field_name, format_spec, conversion)
            for _literal, field_name, format_spec, conversion in Formatter().parse(template)
            if field_name is not None
        ),
        key=repr,
    ))


SCORE_COMPARISON_SOURCES = {
    "谱面结构与音符一致（时间容差 {tolerance:g} ms）。",
    "发现 {count} 项差异：",
    "- {path}: {message} ({expected!r} -> {actual!r})",
    "时间差超过 {tolerance:g} ms",
    "字段不同",
    "私有字段不同",
    "轨道数量不同",
    "乐器轨道顺序不同",
    "轨道缺失",
    "轨道字段不同",
    "音符数量不同",
    "音符字段不同",
}

VALIDATION_SOURCES = {
    "当前轨道因 Mute/Solo 状态不参与导出。",
    "轨道游戏音量不是有效的 v9 字节。",
    "轨道音量 {volume} 超过当前游戏编辑范围 0–100；未编辑时会原样保留。",
    "轨道效果设置不是有效的 8 字节 v9 数据。",
    "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。",
    "未知 BDO 乐器 ID 0x{instrument_id:02X}。",
    "{count} 个 GM 打击乐音符没有 BDO 映射：{pitches}。",
    "导出会把 {count} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。",
    "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。",
    "{count} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。",
    "当前乐器缺少经过验证的完整游戏音域。",
    "{count} 个音符不在当前乐器的已知游戏音域内。",
    "导出会将此轨道全部音符移调 {transpose:+d} 半音。",
    "导出会将此轨道音符时值乘以 {duration_scale:.3g}。",
    "导出会将此轨道力度乘以 {volume_scale:.3g}。",
    "FX type {articulation} 不属于当前乐器。",
    "导出会把此轨道全部音符设为 FX type {articulation}。",
    "该乐器当前只有样本键位证据，完整音域仍待游戏验证。",
    "导出会把 {track_count} 条轨道按乐器 0x{instrument_id:02X} 合并：{track_names}。",
    "同一游戏乐器的 {track_count} 条轨道使用了不同音量；游戏只保存一个乐器音量，请先统一。",
    "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；游戏只保存一组发送量，请先统一。",
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过已验证上限 {limit}。",
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过工具保守审阅阈值 {limit}；"
    "导出器不会因此截断，但游戏实际 noteCount 由账号能力运行时下发，请在游戏内确认。",
    "导出会使用 {velocity_mode} 力度处理模式修改活动音符。",
    "导出会写入全局效果：reverb={reverb}, delay={delay}, chorus={chorus}。",
    "主效果包含无效的 v9 字节。",
    "主效果含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。",
    "需处理",
    "需人工确认",
    "变化说明",
    "轨道 {track_id}",
    "全局",
    "{count} 个音符",
    "已验证",
    "推断",
    "近似",
    "  证据（{status}）：{evidence}",
}


class TranslationCatalogTests(unittest.TestCase):
    def test_supported_languages_are_declared(self):
        self.assertEqual(
            [code for code, _label in LANGUAGES],
            ["zh_CN", "zh_TW", "en_US", "ja_JP", "ko_KR"],
        )
        self.assertEqual(LANGUAGE_CHOICES[0][0], "auto")
        self.assertEqual(LANGUAGE_CHOICES[0][1], "自动（跟随系统）")

    def test_localizer_defaults_to_the_system_language_policy(self):
        self.assertEqual(
            inspect.signature(Localizer).parameters["language"].default,
            "auto",
        )
        self.assertEqual(
            inspect.signature(install_localizer).parameters["language"].default,
            "auto",
        )

    def test_timezone_language_detection(self):
        cases = {
            ("China Standard Time", 480): "zh_CN",
            ("Asia/Shanghai", 480): "zh_CN",
            ("Taipei Standard Time", 480): "zh_TW",
            ("Asia/Taipei", 480): "zh_TW",
            ("Hong Kong Standard Time", 480): "zh_TW",
            ("Asia/Hong_Kong", 480): "zh_TW",
            ("Tokyo Standard Time", 540): "ja_JP",
            ("Asia/Tokyo", 540): "ja_JP",
            ("Korea Standard Time", 540): "ko_KR",
            ("Asia/Seoul", 540): "ko_KR",
            ("Pacific Standard Time", -480): "en_US",
            ("Unknown UTC+9", 540): "en_US",
            ("Unknown UTC+8", 480): "en_US",
            ("Singapore Standard Time", 480): "en_US",
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
                if language == "zh_TW":
                    self.assertTrue(all(catalog[source] for source in required))
                else:
                    self.assertTrue(all(catalog[source] != source for source in required))

    def test_traditional_chinese_uses_taiwan_desktop_terms(self):
        catalog = TRANSLATIONS["zh_TW"]
        expected = {
            "导入 MIDI": "匯入 MIDI",
            "打开工程": "開啟專案",
            "界面语言": "介面語言",
            "设置": "設定",
            "游戏曲谱": "遊戲樂譜",
            "轨道 FX 设置每轨发送；此页设置共享主效果。": (
                "音軌 FX 設定每軌發送；此頁設定共享主效果。"
            ),
            "游戏参数 · 本地 FX 试听为未校准近似": (
                "遊戲參數 · 本機 FX 試聽為未校準近似"
            ),
            "延迟反馈：控制回声返回延迟线的比例；越高，重复越多。本地试听固定约 250 ms。": (
                "延遲回授：控制回聲返回延遲線的比例；越高，重複越多。本機試聽固定約 250 ms。"
            ),
            "合唱反馈：控制调制延迟的反馈强度；越高，梳状与旋动感越明显。": (
                "合唱回授：控制調變延遲的回授強度；越高，梳狀與旋動感越明顯。"
            ),
        }
        for source, translated in expected.items():
            with self.subTest(source=source):
                self.assertEqual(catalog[source], translated)

    def test_translated_catalogs_have_identical_source_coverage(self):
        key_sets = {language: set(catalog) for language, catalog in TRANSLATIONS.items()}
        baseline = key_sets["en_US"]
        for language, keys in key_sets.items():
            with self.subTest(language=language):
                self.assertEqual(keys, baseline)

    def test_duplicate_renderings_are_cross_locale_equivalent(self):
        """Every reversible collision must mean the same thing everywhere."""

        for language, catalog in TRANSLATIONS.items():
            rendered_sources: dict[str, list[str]] = {}
            for source, rendered in catalog.items():
                rendered_sources.setdefault(rendered, []).append(source)
            for rendered, sources in rendered_sources.items():
                if len(sources) < 2:
                    continue
                vectors = {
                    tuple(
                        regional.get(source, source)
                        for regional in TRANSLATIONS.values()
                    )
                    for source in sources
                }
                with self.subTest(language=language, rendered=rendered):
                    self.assertEqual(1, len(vectors), sources)

    def test_every_translation_preserves_the_complete_format_signature(self):
        for language, catalog in TRANSLATIONS.items():
            for source, translated in catalog.items():
                with self.subTest(language=language, source=source):
                    self.assertEqual(
                        _format_signature(source),
                        _format_signature(translated),
                    )

    def test_catalog_source_keys_are_not_redeclared(self):
        source_path = Path(__file__).resolve().parents[1] / "i18n.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        occurrences = {name: [] for name in ("EN", "JA", "KO")}

        def record(name: str, dictionary: ast.Dict) -> None:
            for key in dictionary.keys:
                if key is None:
                    continue
                value = ast.literal_eval(key)
                if isinstance(value, str):
                    occurrences[name].append(value)

        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in occurrences:
                        record(target.id, node.value)
            elif (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and node.value.args
                and isinstance(node.value.args[0], ast.Dict)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "update"
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id in occurrences
            ):
                record(node.value.func.value.id, node.value.args[0])

        for language, keys in occurrences.items():
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            with self.subTest(language=language):
                self.assertEqual([], duplicates)

    def test_validation_and_score_reports_are_fully_catalogued(self):
        required = VALIDATION_SOURCES | SCORE_COMPARISON_SOURCES
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] for source in required))

    def test_all_fixed_articulation_labels_and_usage_hints_are_catalogued(self):
        labels = {
            label
            for pairs in articulation_pairs_by_instrument().values()
            for _ntype, label in pairs
        }
        source_path = Path(__file__).resolve().parents[1] / "pyside_bdo_gui.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        hints = set()
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "BDO_ARTICULATION_USAGE_HINTS"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Dict)
            ):
                hints = {
                    ast.literal_eval(value)
                    for value in node.value.values
                    if value is not None
                }
                break
        self.assertTrue(labels)
        self.assertTrue(hints)
        required = labels | hints
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] for source in required))

    def test_builtin_optimizer_nested_runtime_text_is_catalogued(self):
        source_path = (
            Path(__file__).resolve().parents[1] / "optimization" / "builtin.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        parent = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        required = set()
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Constant)
                or not isinstance(node.value, str)
                or not any("\u3400" <= character <= "\u9fff" for character in node.value)
            ):
                continue
            source = node.value
            if (
                isinstance(parent.get(node), ast.JoinedStr)
                or source.startswith("^")
                or source in {" 调性", " · 自动八度加倍"}
            ):
                continue
            required.add(source.removeprefix("；"))
        required.update(
            template
            for _pattern, template, _fields in optimizer_builtin._DYNAMIC_BUILTIN_TEXT
        )
        required.update(optimizer_builtin._REASON_SUFFIXES)
        required.update(optimizer_builtin._ROLE_LABELS.values())
        required.update(optimizer_builtin._KEY_MODE_LABELS.values())
        required.update(optimizer_builtin._LYRIC_MODE_LABELS.values())
        required.add("{track_name} · 自动八度加倍")
        required.update(
            profile.name
            for profile in TECHNIQUE_PROFILES.values()
            if any("\u3400" <= character <= "\u9fff" for character in profile.name)
        )
        required.update(
            profile.technique
            for profile in ARTICULATION_PROFILES
            if any("\u3400" <= character <= "\u9fff" for character in profile.technique)
        )
        required.update(level.value for level in EvidenceLevel)

        self.assertTrue(required)
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                self.assertTrue(required.issubset(catalog))
                self.assertTrue(all(catalog[source] for source in required))

    def test_official_instrument_names_match_each_region(self):
        official = {
            0x00: ("Beginner Guitar", "初心者用ギター", "초보자용 기타"),
            0x01: ("Beginner Flute", "初心者用フルート", "초보자용 플룻"),
            0x02: ("Beginner Recorder", "初心者用リコーダー", "초보자용 리코더"),
            0x04: ("Beginner Hand Drum", "初心者用ハンドドラム", "초보자용 핸드드럼"),
            0x05: ("Beginner Cymbals", "初心者用シンバル", "초보자용 심벌즈"),
            0x06: ("Beginner Harp", "初心者用ハープ", "초보자용 하프"),
            0x07: ("Beginner Piano", "初心者用ピアノ", "초보자용 피아노"),
            0x08: ("Beginner Violin", "初心者用バイオリン", "초보자용 바이올린"),
            0x0A: ("Florchestra Acoustic Guitar", "フローケストラアコースティックギター", "플로케스트라 어쿠스틱 기타"),
            0x0B: ("Florchestra Flute", "フローケストラフルート", "플로케스트라 플룻"),
            0x0D: ("Florchestra Drum Set", "フローケストラドラムセット", "플로케스트라 드럼 세트"),
            0x0E: ("Marnibass", "マルニバス", "마르니베이스"),
            0x0F: ("Florchestra Contrabass", "フローケストラコントラバス", "플로케스트라 콘트라베이스"),
            0x10: ("Florchestra Harp", "フローケストラハープ", "플로케스트라 하프"),
            0x11: ("Florchestra Piano", "フローケストラピアノ", "플로케스트라 피아노"),
            0x12: ("Florchestra Violin", "フローケストラバイオリン", "플로케스트라 바이올린"),
            0x13: ("Florchestra Handpan", "フローケストラタンドラム", "플로케스트라 팬드럼"),
            0x14: ("Marnian: Wavy Planet", "マルニアン：波の惑星", "마르니언 : 물결행성"),
            0x18: ("Marnian: Illusion Tree", "マルニアン：幻想ツリー", "마르니언 : 환상트리"),
            0x1C: ("Marnian: Secret Note", "マルニアン：秘密のノート", "마르니언 : 비밀노트"),
            0x20: ("Marnian: Sandwich", "マルニアン：サンドイッチ", "마르니언 : 샌드위치"),
            0x24: ("Marni Electric Guitar: Silver Wave", "マルニエレキギター：銀色の波", "마르니 일렉기타 : 은빛물결"),
            0x25: ("Marni Electric Guitar: Highway", "マルニエレキギター：ハイウェイ", "마르니 일렉기타 : 하이웨이"),
            0x26: ("Marni Electric Guitar: Hexe Glam", "マルニエレキギター：ヘクセグラム", "마르니 일렉기타 : 헥세글램"),
            0x27: ("Florchestra Clarinet", "フローケストラクラリネット", "플로케스트라 클라리넷"),
            0x28: ("Florchestra Horn", "フローケストラホルン", "플로케스트라 호른"),
        }
        self.assertEqual(set(BDO_INSTRUMENT_NAMES), set(official))
        for instrument_id, source in BDO_INSTRUMENT_NAMES.items():
            expected = official[instrument_id]
            with self.subTest(instrument_id=instrument_id):
                self.assertEqual(TRANSLATIONS["en_US"][source], expected[0])
                self.assertEqual(TRANSLATIONS["ja_JP"][source], expected[1])
                self.assertEqual(TRANSLATIONS["ko_KR"][source], expected[2])

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
                if language == "zh_TW":
                    self.assertTrue(all(catalog[source] for source in required))
                else:
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
                if language == "zh_TW":
                    self.assertTrue(all(catalog[source] for source in required))
                else:
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

    def test_fixed_chinese_ui_sink_literals_are_explicitly_translated(self):
        """Prevent newly added visible copy from bypassing tr()/trf()."""

        sink_names = {
            "QCheckBox", "QGroupBox", "QLabel", "QMenu", "QPushButton",
            "PillButton", "addAction", "addItem", "addMenu", "addRow",
            "critical", "drawText", "information", "question", "setAccessibleDescription",
            "setAccessibleName", "setPlaceholderText", "setPrefix", "setSpecialValueText",
            "setStatusTip", "setSuffix", "setText", "setToolTip", "setWhatsThis",
            "setWindowTitle", "show_global_toast", "warning",
        }
        translation_names = {"_tr", "tr", "trf"}
        failures: list[str] = []
        for filename in ("pyside_bdo_gui.py", "transcription_editor_qt.py"):
            path = Path(__file__).resolve().parents[1] / filename
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            parents: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parents[child] = parent
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                function = call.func
                function_name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                if function_name not in sink_names:
                    continue
                for literal in (
                    node
                    for argument in call.args
                    for node in ast.walk(argument)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and any("\u4e00" <= character <= "\u9fff" for character in node.value)
                ):
                    cursor = parents.get(literal)
                    translated = False
                    while cursor is not None and cursor is not call:
                        if isinstance(cursor, ast.Call):
                            nested = cursor.func
                            nested_name = (
                                nested.id
                                if isinstance(nested, ast.Name)
                                else nested.attr
                                if isinstance(nested, ast.Attribute)
                                else ""
                            )
                            if nested_name in translation_names:
                                translated = True
                                break
                        cursor = parents.get(cursor)
                    if not translated:
                        failures.append(
                            f"{filename}:{literal.lineno}: {literal.value!r}"
                        )
        self.assertEqual([], failures)

    def test_live_widget_tree_switches_all_fixed_properties_and_trf_values(self):
        if os.environ.get("BDO_I18N_QT_CHILD") != "1":
            environment = os.environ.copy()
            environment["BDO_I18N_QT_CHILD"] = "1"
            environment["QT_QPA_PLATFORM"] = "offscreen"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    (
                        "tests.test_i18n_catalog.TranslationCatalogTests."
                        "test_live_widget_tree_switches_all_fixed_properties_and_trf_values"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            return

        app = QApplication.instance() or QApplication([])
        invalid_localizer = Localizer(app, "unsupported-locale")
        self.assertEqual(invalid_localizer.requested_language, "auto")
        self.assertIn(invalid_localizer.language, {code for code, _label in LANGUAGES})
        app.removeEventFilter(invalid_localizer)
        invalid_localizer.deleteLater()
        previous_localizer = i18n._localizer
        localizer = install_localizer(app, "en_US")
        root = QWidget()
        root.setWindowTitle("设置")
        root.setToolTip("播放")
        root.setStatusTip("暂停")
        root.setWhatsThis("继续")
        root.setAccessibleName("设置")
        root.setAccessibleDescription("停止")

        class CallbackDialog(QDialog):
            def __init__(self, parent):
                super().__init__(parent)
                self.retranslation_count = 0

            def retranslate_dynamic_content(self):
                self.retranslation_count += 1

        callback_dialog = CallbackDialog(root)

        fixed_label = QLabel(tr("播放"), root)
        dynamic_state = QLabel(tr("播放"), root)
        formatted_label = QLabel(
            trf("{project} · 空白项目", project="Aurora"),
            root,
        )
        nested_label = QLabel(
            trf("{label}: {value}", label=trv("播放"), value="Aurora"),
            root,
        )
        nested_format_label = QLabel(
            trf(
                "{label}: {value}",
                label=trfv("轨道 {track_id}", track_id=7),
                value="Aurora",
            ),
            root,
        )
        nested_joined_label = QLabel(
            trf(
                "{label}: {value}",
                label=tr_joinv((trv("播放"), trv("暂停"))),
                value="Aurora",
            ),
            root,
        )
        cached_status = defer_tr(trf("已拒绝 {count} 个候选", count=3))
        cached_label = QLabel(str(cached_status), root)
        unknown_dynamic = QLabel("User · Aurora", root)

        skip_text = QLabel("Play", root)
        skip_text.setProperty("i18nSkipText", True)
        skip_text.setToolTip("播放")
        skip_all = QLabel("Play", root)
        skip_all.setProperty("i18nSkip", True)
        skip_all.setToolTip("播放")
        dynamic_tooltip = QLabel("Reference", root)
        dynamic_tooltip.setProperty("i18nSkipToolTip", True)
        dynamic_tooltip.setToolTip("Play")

        mixed_combo = QComboBox(root)
        mixed_combo.addItem(tr("详细信息 ▸"))
        mixed_combo.addItem("Play")
        mixed_combo.setProperty("i18nSkipItemIndexes", (1,))

        line_edit = QLineEdit(root)
        line_edit.setPlaceholderText(tr("设置"))
        spin = QSpinBox(root)
        spin.setPrefix(tr("播放"))
        spin.setSuffix(tr(" 半音"))
        spin.setSpecialValueText(tr("默认"))

        menu = QMenu(tr("设置"), root)
        action = QAction(tr("播放"), root)
        action.setToolTip(tr("暂停"))
        action.setStatusTip(tr("继续"))
        action.setWhatsThis(tr("停止"))
        root.addAction(action)

        tabs = QTabWidget(root)
        tabs.addTab(QWidget(), tr("设置"))
        tabs.setTabToolTip(0, tr("播放"))
        tabs.setTabWhatsThis(0, tr("暂停"))

        items = QListWidget(root)
        items.setProperty("i18nTranslateItems", True)
        item = QListWidgetItem(tr("播放"))
        item.setToolTip(tr("暂停"))
        item.setStatusTip(tr("继续"))
        item.setWhatsThis(tr("停止"))
        items.addItem(item)

        try:
            root.show()
            callback_dialog.show()
            app.processEvents()
            callback_baseline = callback_dialog.retranslation_count
            self.assertEqual(0, callback_baseline)
            self.assertEqual(root.windowTitle(), "Settings")
            self.assertEqual(root.toolTip(), "Play")

            # Plugin/analysis results arrive after the fixed widget tree has
            # registered its sources. Two identity templates can still render
            # the same opaque value and must not make it translatable.
            ambiguous_plugin_text = trf("{summary}", summary="Play")
            trf("{details}", details="Play")
            ambiguous_label = QLabel(ambiguous_plugin_text, root)
            ambiguous_cached = defer_tr(ambiguous_plugin_text)
            ambiguous_chinese_plugin_text = trf(
                "{summary}",
                summary="播放",
            )
            trf("{details}", details="播放")
            ambiguous_chinese_label = QLabel(
                ambiguous_chinese_plugin_text,
                root,
            )
            ambiguous_chinese_cached = defer_tr(
                ambiguous_chinese_plugin_text
            )
            ambiguous_label.show()
            ambiguous_chinese_label.show()
            app.processEvents()
            dynamic_state.setText(tr("暂停"))

            localizer.set_language("ja_JP")
            self.assertEqual(
                callback_baseline + 1,
                callback_dialog.retranslation_count,
            )
            self.assertEqual(fixed_label.text(), "再生")
            self.assertEqual(dynamic_state.text(), "一時停止")
            self.assertEqual(formatted_label.text(), "Aurora · 空のプロジェクト")
            self.assertEqual(nested_label.text(), "再生: Aurora")
            self.assertEqual(nested_format_label.text(), "トラック 7: Aurora")
            self.assertEqual(nested_joined_label.text(), "再生、一時停止: Aurora")
            cached_label.setText(str(cached_status))
            self.assertEqual(cached_label.text(), "候補を3件拒否しました")
            self.assertEqual(ambiguous_label.text(), "Play")
            self.assertEqual(str(ambiguous_cached), "Play")
            self.assertEqual(ambiguous_chinese_label.text(), "播放")
            self.assertEqual(str(ambiguous_chinese_cached), "播放")
            self.assertEqual(unknown_dynamic.text(), "User · Aurora")
            self.assertEqual(root.windowTitle(), "設定")
            self.assertEqual(root.toolTip(), "再生")
            self.assertEqual(root.statusTip(), "一時停止")
            self.assertEqual(root.whatsThis(), "再開")
            self.assertEqual(root.accessibleName(), "設定")
            self.assertEqual(root.accessibleDescription(), "停止")
            self.assertEqual(line_edit.placeholderText(), "設定")
            self.assertEqual(spin.prefix(), "再生")
            self.assertEqual(spin.suffix(), " 半音")
            self.assertEqual(spin.specialValueText(), "デフォルト")
            self.assertEqual(menu.title(), "設定")
            self.assertEqual(action.text(), "再生")
            self.assertEqual(action.toolTip(), "一時停止")
            self.assertEqual(action.statusTip(), "再開")
            self.assertEqual(action.whatsThis(), "停止")
            self.assertEqual(tabs.tabText(0), "設定")
            self.assertEqual(tabs.tabToolTip(0), "再生")
            self.assertEqual(tabs.tabWhatsThis(0), "一時停止")
            self.assertEqual(item.text(), "再生")
            self.assertEqual(item.toolTip(), "一時停止")
            self.assertEqual(item.statusTip(), "再開")
            self.assertEqual(item.whatsThis(), "停止")
            self.assertEqual(skip_text.text(), "Play")
            self.assertEqual(skip_text.toolTip(), "再生")
            self.assertEqual(skip_all.text(), "Play")
            self.assertEqual(skip_all.toolTip(), "播放")
            self.assertEqual(dynamic_tooltip.toolTip(), "Play")
            self.assertEqual(mixed_combo.itemText(0), "詳細 ▸")
            self.assertEqual(mixed_combo.itemText(1), "Play")

            localizer.set_language("ko_KR")
            self.assertEqual(fixed_label.text(), "재생")
            self.assertEqual(dynamic_state.text(), "일시정지")
            self.assertEqual(formatted_label.text(), "Aurora · 빈 프로젝트")
            self.assertEqual(nested_label.text(), "재생: Aurora")
            self.assertEqual(nested_format_label.text(), "트랙 7: Aurora")
            self.assertEqual(nested_joined_label.text(), "재생, 일시정지: Aurora")
            cached_label.setText(str(cached_status))
            self.assertEqual(cached_label.text(), "후보 3개 거부")
            self.assertEqual(ambiguous_label.text(), "Play")
            self.assertEqual(str(ambiguous_cached), "Play")
            self.assertEqual(ambiguous_chinese_label.text(), "播放")
            self.assertEqual(str(ambiguous_chinese_cached), "播放")
            self.assertEqual(unknown_dynamic.text(), "User · Aurora")
            self.assertEqual(root.windowTitle(), "설정")
            self.assertEqual(menu.title(), "설정")
            self.assertEqual(action.text(), "재생")
            self.assertEqual(tabs.tabText(0), "설정")
            self.assertEqual(item.text(), "재생")
            self.assertEqual(skip_text.text(), "Play")
            self.assertEqual(skip_text.toolTip(), "재생")
            self.assertEqual(skip_all.toolTip(), "播放")
            self.assertEqual(dynamic_tooltip.toolTip(), "Play")
            self.assertEqual(mixed_combo.itemText(0), "세부 정보 ▸")
            self.assertEqual(mixed_combo.itemText(1), "Play")

            localizer.set_language("zh_CN")
            self.assertEqual(fixed_label.text(), "播放")
            self.assertEqual(dynamic_state.text(), "暂停")
            self.assertEqual(formatted_label.text(), "Aurora · 空白项目")
            self.assertEqual(nested_label.text(), "播放: Aurora")
            self.assertEqual(nested_format_label.text(), "轨道 7: Aurora")
            self.assertEqual(nested_joined_label.text(), "播放、暂停: Aurora")
            cached_label.setText(str(cached_status))
            self.assertEqual(cached_label.text(), "已拒绝 3 个候选")
            self.assertEqual(ambiguous_label.text(), "Play")
            self.assertEqual(str(ambiguous_cached), "Play")
            self.assertEqual(ambiguous_chinese_label.text(), "播放")
            self.assertEqual(str(ambiguous_chinese_cached), "播放")
            self.assertEqual(unknown_dynamic.text(), "User · Aurora")
            self.assertEqual(dynamic_tooltip.toolTip(), "Play")

            # Opaque collision records must survive a source-locale cycle.
            # Otherwise a project/plugin value equal to the Chinese UI key
            # would become the translated fixed action label on the next
            # switch.
            localizer.set_language("en_US")
            self.assertEqual(ambiguous_label.text(), "Play")
            self.assertEqual(ambiguous_chinese_label.text(), "播放")
            localizer.set_language("ja_JP")
            self.assertEqual(ambiguous_label.text(), "Play")
            self.assertEqual(ambiguous_chinese_label.text(), "播放")
        finally:
            root.close()
            callback_dialog.close()
            menu.close()
            app.removeEventFilter(localizer)
            i18n._localizer = previous_localizer
            localizer.deleteLater()
            app.processEvents()

    def test_parameterized_text_formats_without_a_localizer(self):
        self.assertEqual(
            trf("已选 {selected} · 共 {total} 音符{position}{warning}",
                selected=2, total=8, position="", warning=""),
            "已选 2 · 共 8 音符",
        )


if __name__ == "__main__":
    unittest.main()
