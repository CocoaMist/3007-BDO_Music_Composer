from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, replace
import re
import unittest

from bdo_profile import Evidence, LimitPolicy, load_bdo_profile
from bdo_validation import (
    ValidationContext,
    ValidationIssue,
    evidence_status_source,
    issues_report,
    localized_evidence_status,
    localized_validation_message,
    validate_tracks,
)
from project_paths import PROFILES_DIR


Note = namedtuple("Note", "pitch vel start dur ntype")
_CJK = re.compile(r"[\u3400-\u9fff]")


@dataclass
class Track:
    track_id: int
    notes: list[Note]
    bdo_instrument_id: int
    display_name: str = "Track"
    is_percussion: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None
    bdo_track_volume: object = 70
    bdo_track_settings: tuple[int, ...] = (0,) * 8


ENGLISH = {
    "当前轨道因 Mute/Solo 状态不参与导出。":
        "This track is excluded from export because of its Mute/Solo state.",
    "轨道游戏音量不是有效的 v9 字节。":
        "The track's in-game volume is not a valid v9 byte.",
    "轨道音量 {volume} 超过当前游戏编辑范围 0–100；未编辑时会原样保留。":
        "Track volume {volume} exceeds the current in-game edit range of 0–100; "
        "the imported value is preserved unless edited.",
    "轨道效果设置不是有效的 8 字节 v9 数据。":
        "The track effect settings are not valid 8-byte v9 data.",
    "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。":
        "The track effect sends contain an imported value above the current in-game "
        "edit range of 0–100; unedited values are preserved.",
    "未知 BDO 乐器 ID 0x{instrument_id:02X}。":
        "Unknown BDO instrument ID 0x{instrument_id:02X}.",
    "{count} 个 GM 打击乐音符没有 BDO 映射：{pitches}。":
        "GM percussion notes without a BDO mapping: {count}; pitches: {pitches}.",
    "导出会把 {count} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。":
        "Export will convert {count} GM percussion notes to BDO 48–64 / ntype 99.",
    "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。":
        "This percussion instrument has no complete per-note GM mapping; verify the "
        "result in game.",
    "{count} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。":
        "{count} notes are outside the BDO C0–B8 range; the exporter will clamp "
        "their pitches.",
    "当前乐器缺少经过验证的完整游戏音域。":
        "A complete verified in-game range is not available for this instrument.",
    "{count} 个音符不在当前乐器的已知游戏音域内。":
        "{count} notes are outside this instrument's known in-game range.",
    "导出会将此轨道全部音符移调 {transpose:+d} 半音。":
        "Export will transpose every note on this track by {transpose:+d} semitones.",
    "导出会将此轨道音符时值乘以 {duration_scale:.3g}。":
        "Export will multiply note durations on this track by {duration_scale:.3g}.",
    "导出会将此轨道力度乘以 {volume_scale:.3g}。":
        "Export will multiply note velocities on this track by {volume_scale:.3g}.",
    "FX type {articulation} 不属于当前乐器。":
        "FX type {articulation} is not available for this instrument.",
    "导出会把此轨道全部音符设为 FX type {articulation}。":
        "Export will set every note on this track to FX type {articulation}.",
    "该乐器当前只有样本键位证据，完整音域仍待游戏验证。":
        "Only sample-key evidence is available for this instrument; its complete "
        "range still requires in-game verification.",
    "导出会把 {track_count} 条轨道按乐器 0x{instrument_id:02X} 合并：{track_names}。":
        "Export will merge {track_count} tracks for instrument 0x{instrument_id:02X}: "
        "{track_names}.",
    "同一游戏乐器的 {track_count} 条轨道使用了不同音量；游戏只保存一个乐器音量，请先统一。":
        "{track_count} tracks for the same in-game instrument use different volumes; "
        "the game stores one instrument volume, so make them consistent first.",
    "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；游戏只保存一组发送量，请先统一。":
        "{track_count} tracks for the same in-game instrument use different effect "
        "send levels; the game stores one set, so make them consistent first.",
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过已验证上限 {limit}。":
        "Instrument 0x{instrument_id:02X} has {count} notes after merging, exceeding "
        "the verified limit of {limit}.",
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过工具保守审阅阈值 {limit}；"
    "导出器不会因此截断，但游戏实际 noteCount 由账号能力运行时下发，请在游戏内确认。":
        "Instrument 0x{instrument_id:02X} has {count} notes after merging, exceeding "
        "the tool's conservative review threshold of {limit}. The exporter will not "
        "truncate them, but the game's actual noteCount is supplied at runtime for "
        "the account; verify it in game.",
    "导出会使用 {velocity_mode} 力度处理模式修改活动音符。":
        "Export will modify active notes using the {velocity_mode} velocity mode.",
    "导出会写入全局效果：reverb={reverb}, delay={delay}, chorus={chorus}。":
        "Export will write global effects: reverb={reverb}, delay={delay}, "
        "chorus={chorus}.",
    "主效果包含无效的 v9 字节。":
        "The master effects contain an invalid v9 byte.",
    "主效果含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。":
        "The master effects contain an imported value above the current in-game edit "
        "range of 0–100; unedited values are preserved.",
    "需处理": "Action required",
    "需人工确认": "Manual confirmation",
    "变化说明": "Change summary",
    "轨道 {track_id}": "Track {track_id}",
    "全局": "Global",
    "{count} 个音符": "{count} notes",
    "已验证": "Verified",
    "推断": "Inferred",
    "近似": "Approximate",
    "  证据（{status}）：{evidence}": "  Evidence ({status}): {evidence}",
}


class ValidationLocalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_bdo_profile(PROFILES_DIR / "bdo_global_v9.json")

    def _context(
        self,
        tracks: list[Track],
        *,
        active: frozenset[int] | None = None,
        transpose: int = 0,
        sample_only: frozenset[int] = frozenset(),
        velocity_mode: str = "preserve",
        effects: tuple[int, int, tuple[int, int, int] | None] = (0, 0, None),
    ) -> ValidationContext:
        return ValidationContext(
            transpose,
            active if active is not None else frozenset(track.track_id for track in tracks),
            {},
            {36: 48, 37: 49},
            lambda track: track.bdo_instrument_id,
            sample_only,
            velocity_mode,
            effects,
        )

    def _validate(self, tracks: list[Track], **context_values: object) -> list[ValidationIssue]:
        return list(validate_tracks(
            tracks,
            self.profile,
            self._context(tracks, **context_values),
        ))

    def _all_branch_issues(self) -> list[ValidationIssue]:
        note = Note(60, 90, 0, 100, 0)
        issues: list[ValidationIssue] = []

        excluded = Track(1, [note], 0x11)
        issues += self._validate([excluded], active=frozenset())

        malformed = Track(
            2,
            [Note(0, 90, 0, 100, 0)],
            0x99,
            duration_scale=0.5,
            volume_scale=0.75,
            articulation_type=7,
            bdo_track_volume="invalid",
            bdo_track_settings=(1, 2),
        )
        issues += self._validate(
            [malformed],
            transpose=1,
            sample_only=frozenset({0x99}),
            velocity_mode="normalize",
            effects=(300, 0, (0, 0, 0)),
        )

        legacy = Track(
            3,
            [note],
            0x11,
            articulation_type=0,
            bdo_track_volume=118,
            bdo_track_settings=(140, 0, 0, 0, 0, 0, 0, 0),
        )
        issues += self._validate([legacy], effects=(101, 0, (0, 0, 0)))

        drums = Track(
            4,
            [Note(99, 90, 0, 100, 0), Note(36, 90, 100, 100, 0)],
            self.profile.drum_instrument_id,
            is_percussion=True,
        )
        issues += self._validate([drums])

        percussion = Track(5, [note], 0x04, is_percussion=True)
        issues += self._validate([percussion])

        unsupported = Track(6, [Note(110, 90, 0, 100, 0)], 0x11)
        issues += self._validate([unsupported])

        unverified_rule = replace(
            self.profile.instruments[0x11],
            pitch_min=None,
            pitch_max=None,
            allowed_pitches=frozenset(),
        )
        unverified_profile = replace(
            self.profile,
            instruments={**self.profile.instruments, 0x11: unverified_rule},
        )
        unverified = Track(7, [note], 0x11)
        issues += list(validate_tracks(
            [unverified],
            unverified_profile,
            self._context([unverified]),
        ))

        first = Track(
            8,
            [note],
            0x11,
            display_name="Lead A",
            bdo_track_volume=60,
            bdo_track_settings=(10, 0, 0, 0, 0, 0, 0, 0),
        )
        second = Track(
            9,
            [note],
            0x11,
            display_name="Lead B",
            bdo_track_volume=70,
            bdo_track_settings=(20, 0, 0, 0, 0, 0, 0, 0),
        )
        issues += self._validate([first, second])

        soft_capacity = Track(10, [note] * 10001, 0x11)
        issues += self._validate([soft_capacity])

        hard_policy = LimitPolicy(1, "wire_hard", Evidence("verified", "hard limit"))
        hard_profile = replace(
            self.profile,
            note_limit_per_instrument=1,
            limit_policies={
                **self.profile.limit_policies,
                "notes_per_instrument": hard_policy,
            },
        )
        hard_capacity = Track(11, [note, note], 0x11)
        issues += list(validate_tracks(
            [hard_capacity],
            hard_profile,
            self._context([hard_capacity]),
        ))
        return issues

    def test_all_validation_branches_have_translatable_structured_messages(self) -> None:
        issues = self._all_branch_issues()
        expected_codes = {
            "articulation.note_unsupported",
            "articulation.unsupported",
            "capacity.instrument",
            "drum.remap",
            "drum.unmapped",
            "export.duration_scale",
            "export.global_effects",
            "export.global_effects_legacy_range",
            "export.global_effects_wire_range",
            "export.track_articulation",
            "export.transpose",
            "export.velocity_mode",
            "export.velocity_scale",
            "instrument.unknown",
            "percussion.sample_only",
            "percussion.unverified_mapping",
            "pitch.instrument_unsupported",
            "pitch.range_unverified",
            "pitch.wire_clamp",
            "track.effects_legacy_range",
            "track.effects_wire_shape",
            "track.excluded",
            "track.volume_legacy_range",
            "track.volume_wire_range",
            "tracks.effects_conflict",
            "tracks.merge",
            "tracks.volume_conflict",
        }
        self.assertEqual(expected_codes, {issue.code for issue in issues})
        self.assertTrue(all(issue.message_template for issue in issues))
        self.assertTrue(all(issue.message_template in ENGLISH for issue in issues))
        for issue in issues:
            localized = localized_validation_message(issue, lambda text: ENGLISH[text])
            self.assertIsNone(_CJK.search(localized), (issue.code, localized))

        capacity = [issue for issue in issues if issue.code == "capacity.instrument"]
        self.assertEqual({"error", "warning"}, {issue.severity for issue in capacity})

    def test_default_message_is_chinese_and_dynamic_values_are_preserved(self) -> None:
        tracks = [
            Track(1, [Note(60, 90, 0, 100, 0)], 0x11, display_name="旋律 {A}"),
            Track(2, [Note(64, 90, 100, 100, 0)], 0x11, display_name="Bass 100%"),
        ]
        merge = next(
            issue for issue in self._validate(tracks)
            if issue.code == "tracks.merge"
        )

        self.assertIn("导出会把 2 条轨道", merge.message)
        self.assertIn("旋律 {A}, Bass 100%", merge.message)
        localized = localized_validation_message(merge, lambda text: ENGLISH[text])
        self.assertIn("merge 2 tracks", localized)
        self.assertIn("旋律 {A}, Bass 100%", localized)

    def test_unsupported_per_note_articulation_points_to_exact_notes(self) -> None:
        track = Track(
            1,
            [
                Note(60, 90, 0, 100, 0),
                Note(64, 90, 100, 100, 255),
                Note(67, 90, 200, 100, 255),
            ],
            0x11,
        )
        issue = next(
            item for item in self._validate([track])
            if item.code == "articulation.note_unsupported"
        )
        self.assertEqual((1, 2), issue.note_indices)
        self.assertIn("type 255", issue.message)

    def test_placeholder_mismatch_falls_back_without_losing_values(self) -> None:
        track = Track(1, [Note(60, 90, 0, 100, 0)], 0x11, bdo_track_volume=118)
        issue = next(
            item for item in self._validate([track])
            if item.code == "track.volume_legacy_range"
        )
        rendered = localized_validation_message(issue, lambda _text: "Broken translation")
        self.assertEqual(issue.message, rendered)
        self.assertIn("118", rendered)

    def test_legacy_issue_constructor_and_default_report_remain_compatible(self) -> None:
        issue = ValidationIssue(
            "legacy", "warning", "旧消息", 4, (1, 2), "raw", "inferred", "legacy_fix"
        )
        self.assertEqual("旧消息", localized_validation_message(issue))
        self.assertEqual("legacy_fix", issue.fix_id)
        report = issues_report([issue])
        self.assertEqual(
            "[需人工确认] Track 4 · 2 notes · 旧消息\n  证据(inferred): raw",
            report,
        )

    def test_localized_report_translates_labels_but_not_evidence(self) -> None:
        track = Track(3, [Note(60, 90, 0, 100, 0)], 0x11, bdo_track_volume=118)
        issue = next(
            item for item in self._validate([track])
            if item.code == "track.volume_legacy_range"
        )
        issue = replace(issue, evidence="用户证据/raw-source")

        report = issues_report([issue], translate=lambda text: ENGLISH[text])

        self.assertIn("[Manual confirmation] Track 3", report)
        self.assertIn("Track volume 118", report)
        self.assertIn("Evidence (Verified): 用户证据/raw-source", report)

    def test_evidence_status_localizes_only_known_host_enums(self) -> None:
        self.assertEqual("已验证", evidence_status_source("verified"))
        self.assertIsNone(evidence_status_source("vendor-status"))
        self.assertEqual("已验证", localized_evidence_status("verified"))
        self.assertEqual(
            "Verified",
            localized_evidence_status("verified", lambda text: ENGLISH[text]),
        )
        self.assertEqual(
            "vendor-status",
            localized_evidence_status("vendor-status", lambda _text: "translated"),
        )

    def test_format_translate_api_matches_i18n_trf_shape(self) -> None:
        track = Track(8, [Note(60, 90, 0, 100, 0)], 0x11, bdo_track_volume=118)
        issue = next(
            item for item in self._validate([track])
            if item.code == "track.volume_legacy_range"
        )

        def translate_format(template: str, **values: object) -> str:
            return ENGLISH[template].format(**values)

        self.assertIn(
            "Track volume 118",
            localized_validation_message(issue, format_translate=translate_format),
        )
        self.assertIn(
            "Manual confirmation",
            issues_report([issue], format_translate=translate_format),
        )


if __name__ == "__main__":
    unittest.main()
