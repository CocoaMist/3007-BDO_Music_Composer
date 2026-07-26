from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field
import re
from types import SimpleNamespace
import unittest

from bdo_lyrics import LyricExpressionMode
from bdo_techniques import RealizationKind, TechniqueCandidate
from optimization import OptimizerConfig
from optimization.builtin import (
    ArticulationSuggestion,
    EffectSuggestion,
    EnsembleSuggestion,
    OptimizationResult,
    OptimizationTextSpec,
    TrackOptimizationReport,
)
from optimization.plugin_api import (
    OptimizationIntensity,
    OptimizationPreview,
    build_request,
)
from optimization.plugin_host import (
    BUILTIN_SAFE_ID,
    HostAlgorithmDescriptor,
    OptimizationSession,
    analyse_with_algorithm,
    discover_host_algorithms,
)


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))
_CJK = re.compile(r"[\u3400-\u9fff]")


@dataclass
class Track:
    track_id: int
    notes: list[Note]
    gm_program: int = 0
    is_percussion: bool = False
    display_name: str = "Track"
    bdo_instrument_id: int = 0x11
    muted: bool = False
    solo: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None
    marnian_synth_mode: str = "basic"
    color: str = "#ffffff"
    effect_settings_placeholder: dict = field(default_factory=dict)
    performance_controls: list = field(default_factory=list)
    notes_optimized: bool = False


ENGLISH = {
    "BDO 游戏安全优化": "BDO Game-Safe Optimization",
    "保持音符数量、音高集合、乐器映射和手动奏法的确定性安全优化。":
        "Deterministic safe optimization that preserves note count, pitch set, "
        "instrument mapping, and manual Musical Techniques.",
    "修复音块": "Repair Notes",
    "力度": "Velocity",
    "量化": "Quantize",
    "奏法": "Musical Technique",
    "轻微自然化": "Light Humanization",
    "声音效果": "Sound Effects",
    "全局": "Global",
    "单轨": "Single Track",
    "奏法 {articulations} 处 · 轻微自然化 {humanized} 个音符":
        "Musical Techniques: {articulations} · Light humanization: {humanized} notes",
    "效果：混响 {reverb_before}→{reverb_after} · 延迟 {delay_before}→{delay_after} · "
    "合唱 {chorus_before}→{chorus_after}":
        "Effects: Reverb {reverb_before}→{reverb_after} · Delay "
        "{delay_before}→{delay_after} · Chorus {chorus_before}→{chorus_after}",
    "注意：{message}": "Notice: {message}",
    "MIDI 优化报告": "MIDI Optimization Report",
    "总计：去重 {removed}，修重叠 {trimmed}，量化 {quantized}，力度润色 {velocity}，"
    "奏法 {articulations}，新增/拆分音 {added}":
        "Totals: deduplicated {removed}, overlap fixes {trimmed}, quantized "
        "{quantized}, velocity edits {velocity}, Musical Techniques "
        "{articulations}, added/split notes {added}",
    "{key_root} {key_mode} {confidence}": "{key_root} {key_mode} {confidence}",
    "全曲上下文：{tonal} · 风格 {styles}":
        "Song context: {tonal} · Style {styles}",
    "大调": "major",
    "小调": "minor",
    "调性不稳定": "Unstable tonality",
    "歌词：{tokens} 个音节/文本单元 · {alignments} 个对齐 · {mode} · 置信度 {confidence}":
        "Lyrics: {tokens} syllable/text units · {alignments} alignments · {mode} · "
        "Confidence {confidence}",
    "连贯": "Legato",
    "歌词与主旋律起点偏差较大": "Lyrics start far from the lead melody",
    "仅作为建议，不自动改写音高": "suggestion only; pitches are not rewritten",
    "歌词与主旋律起点偏差较大；仅作为建议，不自动改写音高":
        "Lyrics start far from the lead melody; this is a suggestion only and "
        "pitches are not rewritten",
    "游戏安全自然化：{count} 个音符": "Game-safe humanization: {count} notes",
    "游戏效果：Reverb {reverb_before}->{reverb_after} · Delay {delay_before}->{delay_after} · "
    "Chorus {chorus_before}->{chorus_after} · 置信度 {confidence}":
        "In-game effects: Reverb {reverb_before}->{reverb_after} · Delay "
        "{delay_before}->{delay_after} · Chorus {chorus_before}->{chorus_after} · "
        "Confidence {confidence}",
    "管弦配置使用适度空间感": "Use moderate space for orchestral instrumentation",
    "工程没有可分析音符": "The project has no notes to analyze",
    "声音效果优化已关闭": "Sound-effect optimization is disabled",
    "  - 配器建议：{message}": "  - Instrumentation: {message}",
    "{track_name} 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音":
        "{track_name} competes with the lead melody in rhythm and register; reduce "
        "activity or offset note onsets",
    "仅建议奏法 {count}（未写入工程）":
        "Suggested Musical Techniques: {count} (not written to the project)",
    "已优化": "Optimized",
    "无变化": "No changes",
    "修改": "Modified",
    "只读上下文": "Read-only context",
    "自动编曲新增": "Added by arrangement",
    "[{status}/{scope}] Track {track_id}: {track_name} · {before_notes}->{after_notes} notes":
        "[{status}/{scope}] Track {track_id}: {track_name} · "
        "{before_notes}->{after_notes} notes",
    "主旋律": "Lead Melody",
    "副旋律": "Secondary Melody",
    "和声": "Harmony",
    "低音": "Bass",
    "节奏": "Rhythm",
    "打击乐": "Percussion",
    "铺底": "Pad",
    "装饰声部": "Ornament",
    "音效": "FX",
    "旋律": "Melody",
    "和弦": "Chord",
    "低音动机": "Bass Riff",
    "  角色：{role}": "  Role: {role}",
    "  去重 {duplicates} · 重叠 {overlaps} · 短音 {short_notes} · 量化 {quantized} · "
    "力度 {velocities} · 奏法 {articulations}":
        "  Duplicates {duplicates} · Overlaps {overlaps} · Short notes {short_notes} · "
        "Quantized {quantized} · Velocity {velocities} · Musical Techniques {articulations}",
    "  奏法分布：{counts}": "  Musical Technique distribution: {counts}",
    "  仅建议 {suggestions} · 跳过候选 {skipped}":
        "  Suggestions {suggestions} · Skipped candidates {skipped}",
    "已加入预览": "Added to preview",
    "仅建议": "Suggestion only",
    "颤音": "Trill",
    "已验证映射": "Verified mapping",
    "长音含半音邻音往返": "A held note alternates with a semitone neighbor",
    "句尾保守降级": "Conservatively reduced at phrase end",
    "非和弦音降级": "Reduced for a non-chord tone",
    "旋律折返，滑音降级": "Slide reduced at a melodic turnback",
    "强拍": "Strong beat",
    "弱拍": "Weak beat",
    "{mode} 调性": "{mode} key",
    "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}":
        "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}",
    "乐理分析：{key_root} {key_mode} 调性置信度 {confidence}":
        "Music theory: {key_root} {key_mode}, confidence {confidence}",
    "{count} 个音超出目标乐器的游戏/采样键位，未自动夹音":
        "{count} notes are outside the target instrument's in-game/sample keys; "
        "pitches were not clamped",
    "检测到同拍多奏法": "Multiple Musical Techniques detected at one onset",
    "保留人工内容并要求导出前确认":
        "manual content is preserved and requires confirmation before export",
    "检测到同拍多奏法；保留人工内容并要求导出前确认":
        "Multiple Musical Techniques were detected at one onset; manual content is "
        "preserved and requires confirmation before export",
    "  - 配器：{issue}": "  - Instrumentation: {issue}",
    "BDO 原生": "Native BDO",
    "MIDI 近似": "MIDI approximation",
    "揉弦/气息颤音": "Vibrato",
    "Pitch Bend 曲线反复换向": "The Pitch Bend curve repeatedly changes direction",
    "  - 技法 {technique} · {confidence} · {state} · {reason}":
        "  - Technique {technique} · {confidence} · {state} · {reason}",
    "Track {track_id}（{role}）整体移调 {shift:+d} 半音，减少与主旋律的音区遮蔽":
        "Track {track_id} ({role}) transposed {shift:+d} semitones to reduce register "
        "masking with the lead melody",
    "[编配] {change}": "[Arrangement] {change}",
    "输入已有 {count} 个音符超出当前乐器映射；优化仅保留，不会新增，请在转换检查中处理。":
        "The input already has {count} notes outside the current instrument mapping. "
        "Optimization preserves but does not add them; resolve them in Conversion Check.",
    "输入已有 {count} 个鼓音尚未规范为 BDO 48–64/type 99；优化仅保留，请在转换检查中处理。":
        "The input already has {count} drum notes not normalized to BDO 48–64/type 99. "
        "Optimization preserves them; resolve them in Conversion Check.",
    "输入已有 {count} 个未验证奏法；优化会保护人工值，不会复制或新增。":
        "The input already has {count} unverified Musical Techniques. Optimization "
        "protects manual values and will not copy or add them.",
}


def tr(source: str) -> str:
    return ENGLISH.get(source, source)


def trf(source: str, **values: object) -> str:
    return tr(source).format(**values)


class OptimizerLocalizationTests(unittest.TestCase):
    def _rich_result(self, track_name: str = "Lead A") -> OptimizationResult:
        suggestion = ArticulationSuggestion(
            note_indices=(0,),
            ntype=4,
            technique="颤音",
            confidence=0.88,
            evidence="已验证映射",
            reason=(
                "长音含半音邻音往返；"
                "句尾保守降级，非和弦音降级，旋律折返，滑音降级"
            ),
            auto_applicable=True,
            applied=True,
            theory_context="melody · 强拍 · major 调性",
        )
        candidate = TechniqueCandidate(
            track_id=1,
            note_indices=(0,),
            technique_id="vibrato",
            confidence=0.94,
            reason="Pitch Bend 曲线反复换向",
            realization=RealizationKind.NATIVE_BDO,
        )
        report = TrackOptimizationReport(
            track_id=1,
            display_name=track_name,
            before_notes=4,
            after_notes=4,
            notes_quantized=2,
            articulations_added=1,
            articulation_counts={4: 1},
            suggestions=[suggestion],
            suggestions_only=1,
            articulation_candidates_skipped=2,
            warnings=[
                "乐理分析：0 major 调性置信度 80%",
                "3 个音超出目标乐器的游戏/采样键位，未自动夹音",
                "检测到同拍多奏法；保留人工内容并要求导出前确认",
            ],
            role="primary_melody",
            technique_candidates=[candidate],
            scope="修改",
        )
        song_context = SimpleNamespace(
            tonal=True,
            key_root=0,
            key_mode="major",
            tonal_confidence=0.8,
            styles=(SimpleNamespace(name="rock", confidence=0.9),),
        )
        lyric_context = SimpleNamespace(
            tokens=(1, 2),
            alignments=(1,),
            mode=LyricExpressionMode.LEGATO,
            confidence=0.75,
            warnings=(
                "歌词与主旋律起点偏差较大；仅作为建议，不自动改写音高",
            ),
        )
        effect = EffectSuggestion(
            1, 2, (3, 4, 5), 6, 7, (8, 9, 10), 0.85,
            ("管弦配置使用适度空间感",),
            True,
        )
        ensemble = EnsembleSuggestion(
            90,
            "Harmony A 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音",
            (1, 2),
        )
        return OptimizationResult(
            tracks=[],
            reports=[report],
            song_context=song_context,
            arrangement_changes=[
                "Track 1（harmony）整体移调 -12 半音，减少与主旋律的音区遮蔽",
            ],
            lyric_context=lyric_context,
            effect_suggestion=effect,
            ensemble_suggestions=[ensemble],
        )

    def test_builtin_summary_and_details_render_without_fixed_chinese(self) -> None:
        result = self._rich_result()

        simple = result.simple_summary_text(tr, format_translate=trf)
        details = result.summary_text(tr, format_translate=trf)

        self.assertIsNone(_CJK.search(simple), simple)
        self.assertIsNone(_CJK.search(details), details)
        self.assertIn("MIDI Optimization Report", details)
        self.assertIn("Lead Melody", details)
        self.assertIn("Vibrato", details)
        self.assertIn("Track 1 (Harmony) transposed -12 semitones", details)

    def test_production_english_catalog_covers_rich_builtin_report(self) -> None:
        from i18n import EN

        translate = lambda source: EN.get(source, source)
        format_translate = (
            lambda source, **values: translate(source).format(**values)
        )
        result = self._rich_result()
        rendered = result.simple_summary_text(
            translate,
            format_translate=format_translate,
        ) + "\n" + result.summary_text(
            translate,
            format_translate=format_translate,
        )

        self.assertIsNone(_CJK.search(rendered), rendered)

    def test_default_summary_remains_chinese_and_deterministic(self) -> None:
        result = self._rich_result()
        expected_simple = (
            "奏法 1 处 · 轻微自然化 0 个音符\n"
            "效果：混响 1→6 · 延迟 2→7 · 合唱 (3, 4, 5)→(8, 9, 10)\n"
            "注意：Harmony A 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音"
        )

        self.assertEqual(expected_simple, result.simple_summary_text())
        self.assertEqual(result.summary_text(), result.summary_text())
        self.assertIn("[已优化/修改] Track 1: Lead A · 4->4 notes", result.summary_text())
        self.assertIn("  角色：primary_melody", result.summary_text())

    def test_user_track_name_is_never_sent_to_translator(self) -> None:
        seen: list[str] = []

        def spy(source: str) -> str:
            seen.append(source)
            return ENGLISH.get(source, source)

        result = self._rich_result("用户私有轨 {A}")
        rendered = result.summary_text(spy)

        self.assertIn("用户私有轨 {A}", rendered)
        self.assertFalse(any("用户私有轨" in source for source in seen))

    def test_text_spec_validates_placeholders_and_falls_back_safely(self) -> None:
        with self.assertRaises(ValueError):
            OptimizationTextSpec.create("Count {count}")
        spec = OptimizationTextSpec.create("数量 {count}", {"count": 7})
        self.assertEqual("数量 7", spec.render(lambda _source: "Broken"))

        def broken_format(_source: str, **_values: object) -> str:
            raise KeyError("missing catalog key")

        self.assertEqual("数量 7", spec.render(format_translate=broken_format))

    def test_session_localizes_only_host_owned_preview_text(self) -> None:
        source = [Track(1, [], display_name="Lead", bdo_instrument_id=0x11)]
        descriptor = discover_host_algorithms().algorithms[0]
        session = analyse_with_algorithm(
            descriptor,
            source,
            120,
            4,
            {},
            OptimizerConfig(target_track_ids=frozenset({1})),
            OptimizationIntensity.CONSERVATIVE,
            "single_track",
            frozenset({0x11}),
        )

        localized = session.localized_preview(tr, format_translate=trf)

        self.assertIs(session.preview, session.localized_preview())
        self.assertEqual([], session.builtin_result.tracks)
        self.assertEqual(session.preview.source_fingerprint, localized.source_fingerprint)
        self.assertEqual(session.preview.operations, localized.operations)
        self.assertIsNot(session.preview, localized)
        self.assertIsNone(_CJK.search(localized.summary), localized.summary)
        self.assertIsNone(_CJK.search("\n".join(localized.details)), localized.details)
        applied, effects = session.apply(source)
        self.assertEqual(source, applied)
        self.assertIsNone(effects)

    def test_source_diagnostics_are_structured_and_localized(self) -> None:
        source = [
            Track(
                1,
                [Note(101, 80, 0, 100, 77)],
                display_name="Lead",
                bdo_instrument_id=0x0B,
            ),
            Track(
                2,
                [Note(36, 80, 0, 100, 0)],
                is_percussion=True,
                display_name="Drums",
                bdo_instrument_id=0x0D,
            ),
        ]
        descriptor = discover_host_algorithms().algorithms[0]
        session = analyse_with_algorithm(
            descriptor,
            source,
            120,
            4,
            {},
            OptimizerConfig(
                target_track_ids=frozenset({1, 2}),
                supported_pitches={
                    0x0B: frozenset(range(36, 97)),
                    0x0D: frozenset(range(48, 65)),
                },
                polish_velocity=False,
                humanize=False,
                apply_articulations=False,
            ),
            OptimizationIntensity.CONSERVATIVE,
            "global",
            frozenset({0x0B, 0x0D}),
        )

        localized = session.localized_preview(tr, format_translate=trf)

        self.assertEqual(3, len(session.host_diagnostic_specs))
        self.assertTrue(all("转换检查" in text for text in session.preview.diagnostics[:2]))
        self.assertTrue(all(_CJK.search(text) is None for text in localized.diagnostics))
        self.assertIn("{count}", session.host_diagnostic_specs[0].template)

    def test_external_plugin_identity_and_output_remain_verbatim(self) -> None:
        source = [Track(1, [], display_name="Lead", bdo_instrument_id=0x11)]
        request = build_request(
            source,
            120,
            4,
            frozenset({1}),
            {0x11: frozenset(range(12, 108))},
            {},
            OptimizationIntensity.BALANCED,
            "single_track",
            valid_instrument_ids=frozenset({0x11}),
        )
        descriptor = HostAlgorithmDescriptor(
            "third.party",
            "1",
            "第三方算法名",
            "第三方说明",
            ("single_track",),
            (),
            False,
        )
        preview = OptimizationPreview(
            request.source_fingerprint,
            descriptor.algorithm_id,
            descriptor.version,
            summary="第三方摘要",
            details=("第三方详情",),
            diagnostics=("第三方诊断",),
        )
        session = OptimizationSession(
            descriptor,
            request.source_fingerprint,
            source,
            request,
            preview,
        )

        localized = session.localized_preview(tr, format_translate=trf)

        self.assertIs(preview, localized)
        self.assertEqual("第三方算法名", descriptor.localized_display_name(tr))
        self.assertEqual("第三方说明", descriptor.localized_description(tr))
        self.assertEqual(("single_track",), descriptor.localized_scopes(tr))
        self.assertEqual((), descriptor.localized_capabilities(tr))
        self.assertEqual("第三方摘要", localized.summary)
        self.assertEqual(("第三方详情",), localized.details)
        self.assertEqual(("第三方诊断",), localized.diagnostics)

    def test_builtin_descriptor_is_localized_without_mutating_metadata(self) -> None:
        descriptor = discover_host_algorithms().algorithms[0]
        self.assertEqual(BUILTIN_SAFE_ID, descriptor.algorithm_id)
        self.assertEqual("BDO 游戏安全优化", descriptor.display_name)
        self.assertEqual("BDO Game-Safe Optimization", descriptor.localized_display_name(tr))
        self.assertNotIn("游戏", descriptor.localized_description(tr))
        self.assertEqual(
            ("Global", "Single Track"),
            descriptor.localized_scopes(tr),
        )
        self.assertEqual(
            (
                "Repair Notes",
                "Velocity",
                "Quantize",
                "Musical Technique",
                "Light Humanization",
                "Sound Effects",
            ),
            descriptor.localized_capabilities(tr),
        )
        self.assertEqual(("global", "single_track"), descriptor.scopes)
        self.assertEqual("note_cleanup", descriptor.capabilities[0])


if __name__ == "__main__":
    unittest.main()
