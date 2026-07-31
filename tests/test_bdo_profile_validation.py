from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, replace
from pathlib import Path
import unittest

from bdo_codec import MAX_NOTES_PER_TRACK
from bdo_profile import Evidence, LimitPolicy, load_bdo_profile
from bdo_validation import ValidationContext, validate_tracks
from optimization.plugin_api import OptimizationLimits
from project_paths import PROFILES_DIR
from pitch_transform import PitchTransformPlan


Note = namedtuple("Note", "pitch vel start dur ntype")


@dataclass
class Track:
    track_id: int
    notes: list
    bdo_instrument_id: int
    display_name: str = "track"
    is_percussion: bool = False
    muted: bool = False
    solo: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None
    bdo_track_volume: int = 70
    bdo_track_settings: tuple[int, ...] = (0,) * 8


class BdoProfileValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_bdo_profile(PROFILES_DIR / "bdo_global_v9.json")

    def context(self, tracks) -> ValidationContext:
        return ValidationContext(
            0,
            frozenset(track.track_id for track in tracks),
            {},
            {36: 48, 37: 49},
            lambda track: track.bdo_instrument_id,
        )

    def test_profile_loads_versioned_limits_and_evidence(self) -> None:
        self.assertEqual(self.profile.format_version, 9)
        self.assertEqual(self.profile.note_limit_per_track, 730)
        self.assertEqual(
            self.profile.note_limit_per_track,
            MAX_NOTES_PER_TRACK,
        )
        self.assertEqual(
            OptimizationLimits().export_track_note_limit,
            MAX_NOTES_PER_TRACK,
        )
        track_limit = self.profile.limit_policy("notes_per_track")
        instrument_limit = self.profile.limit_policy("notes_per_instrument")
        self.assertEqual("wire_hard", track_limit.kind)
        self.assertTrue(track_limit.is_hard)
        self.assertEqual("verified", track_limit.evidence.status)
        self.assertEqual(10000, instrument_limit.value)
        self.assertEqual("tool_soft_guardrail", instrument_limit.kind)
        self.assertFalse(instrument_limit.is_hard)
        self.assertEqual("inferred", instrument_limit.evidence.status)
        self.assertIn("runtime", instrument_limit.evidence.source)
        self.assertEqual(self.profile.drum_instrument_id, 13)
        self.assertEqual(self.profile.instruments[11].evidence.status, "verified")

    def test_game_ui_sparse_percussion_lanes_are_verified(self) -> None:
        hand_drum = self.profile.instruments[0x04]
        cymbals = self.profile.instruments[0x05]
        self.assertEqual("verified", hand_drum.evidence.status)
        self.assertEqual(
            frozenset({60, 65, 66, 67, 72, 73, 74, 77, 78, 79}),
            hand_drum.allowed_pitches,
        )
        self.assertEqual(frozenset({60, 65, 71}), cymbals.allowed_pitches)
        self.assertTrue(hand_drum.supports_pitch(60))
        self.assertFalse(hand_drum.supports_pitch(61))

    def test_validator_rejects_disabled_game_ui_percussion_lane(self) -> None:
        track = Track(5, [Note(61, 90, 0, 100, 0)], 0x04)
        issues = validate_tracks([track], self.profile, self.context([track]))
        invalid = next(
            item for item in issues
            if item.code == "pitch.instrument_unsupported"
        )
        self.assertEqual((0,), invalid.note_indices)
        self.assertEqual("verified", invalid.evidence_status)

    def test_validator_locates_unsupported_notes_and_describes_export_changes(self) -> None:
        track = Track(
            4,
            [Note(47, 90, 0, 200, 0), Note(60, 90, 300, 200, 0)],
            11,
            volume_scale=0.8,
        )
        issues = validate_tracks([track], self.profile, self.context([track]))
        pitch_issue = next(item for item in issues if item.code == "pitch.instrument_unsupported")
        self.assertEqual(pitch_issue.track_id, 4)
        self.assertEqual(pitch_issue.note_indices, (0,))
        self.assertTrue(any(item.code == "export.velocity_scale" for item in issues))

    def test_validator_uses_same_track_pitch_plan_as_export(self) -> None:
        first = Track(4, [Note(47, 90, 0, 200, 0)], 11)
        second = Track(5, [Note(60, 90, 0, 200, 0)], 11)
        base = self.context([first, second])
        plan = PitchTransformPlan(0).with_track_octave(4, 12)
        context = ValidationContext(
            base.transpose,
            base.active_track_ids,
            base.instrument_names,
            base.gm_drum_map,
            base.serialize_instrument,
            pitch_plan=plan,
        )

        issues = validate_tracks([first, second], self.profile, context)

        self.assertFalse(any(
            item.code == "pitch.instrument_unsupported"
            and item.track_id == 4
            for item in issues
        ))
        transpose = next(
            item for item in issues
            if item.code == "export.transpose" and item.track_id == 4
        )
        self.assertEqual(dict(transpose.message_values)["transpose"], 12)
        self.assertFalse(any(
            item.code == "export.transpose" and item.track_id == 5
            for item in issues
        ))

    def test_bdo_drum_target_is_exempt_when_source_flag_is_melodic(self) -> None:
        track = Track(
            8,
            [Note(48, 90, 0, 200, 99)],
            0x0D,
            is_percussion=False,
        )
        base = self.context([track])
        context = ValidationContext(
            -8,
            base.active_track_ids,
            base.instrument_names,
            base.gm_drum_map,
            base.serialize_instrument,
            pitch_plan=PitchTransformPlan(-8),
        )

        issues = validate_tracks([track], self.profile, context)

        self.assertFalse(any(
            item.code == "export.transpose" for item in issues
        ))
        self.assertFalse(any(item.severity == "error" for item in issues))

    def test_approximate_instrument_range_warns_without_hard_rejection(self) -> None:
        track = Track(
            6,
            [Note(44, 90, 0, 200, 0), Note(89, 90, 300, 200, 0)],
            0x13,
        )

        issues = validate_tracks([track], self.profile, self.context([track]))

        range_issue = next(
            item for item in issues if item.code == "pitch.range_unverified"
        )
        self.assertEqual("warning", range_issue.severity)
        self.assertEqual("approximate", range_issue.evidence_status)
        self.assertFalse(any(
            item.code == "pitch.instrument_unsupported" for item in issues
        ))

    def test_validator_blocks_unmapped_drums_and_capacity_loss(self) -> None:
        drums = Track(1, [Note(99, 90, 0, 100, 0)], 13, is_percussion=True)
        issues = validate_tracks([drums], self.profile, self.context([drums]))
        self.assertTrue(any(item.code == "drum.unmapped" and item.severity == "error" for item in issues))

    def test_instrument_10000_threshold_is_a_soft_review_not_export_loss(self) -> None:
        note = Note(60, 90, 0, 100, 0)
        track = Track(9, [note] * 10001, 17)

        issues = validate_tracks([track], self.profile, self.context([track]))

        capacity = next(item for item in issues if item.code == "capacity.instrument")
        self.assertEqual("warning", capacity.severity)
        self.assertEqual("inferred", capacity.evidence_status)
        self.assertEqual((9,), capacity.related_track_ids)
        self.assertIn("工具保守审阅阈值 10000", capacity.message)
        self.assertIn("导出器不会因此截断", capacity.message)
        self.assertIn("游戏内确认", capacity.message)
        self.assertNotIn("丢弃尾部", capacity.message)

    def test_same_game_instrument_rejects_volume_and_aux_send_conflicts(self) -> None:
        first = Track(
            1,
            [Note(60, 90, 0, 100, 0)],
            0x11,
            bdo_track_volume=70,
            bdo_track_settings=(10, 1, 20, 2, 30, 3, 4, 5),
        )
        second = Track(
            2,
            [Note(64, 90, 100, 100, 0)],
            0x11,
            bdo_track_volume=80,
            bdo_track_settings=(11, 1, 20, 2, 30, 3, 4, 5),
        )

        issues = validate_tracks(
            [first, second],
            self.profile,
            self.context([first, second]),
        )

        by_code = {issue.code: issue for issue in issues}
        self.assertEqual("error", by_code["tracks.volume_conflict"].severity)
        self.assertEqual("error", by_code["tracks.effects_conflict"].severity)
        self.assertEqual((1, 2), by_code["tracks.merge"].related_track_ids)
        self.assertEqual(
            (1, 2),
            by_code["tracks.volume_conflict"].related_track_ids,
        )
        self.assertEqual(
            (1, 2),
            by_code["tracks.effects_conflict"].related_track_ids,
        )

    def test_legacy_wire_values_are_preserved_but_warned(self) -> None:
        track = Track(
            3,
            [Note(60, 90, 0, 100, 0)],
            0x11,
            bdo_track_volume=118,
            bdo_track_settings=(140, 0, 0, 0, 0, 0, 0, 0),
        )
        context = self.context([track])
        context = ValidationContext(
            context.transpose,
            context.active_track_ids,
            context.instrument_names,
            context.gm_drum_map,
            context.serialize_instrument,
            effects=(0, 0, (0, 0, 150)),
        )

        issues = validate_tracks([track], self.profile, context)

        codes = {issue.code for issue in issues}
        self.assertIn("track.volume_legacy_range", codes)
        self.assertIn("track.effects_legacy_range", codes)
        self.assertIn("export.global_effects_legacy_range", codes)

    def test_issue_codes_keep_track_group_and_score_order(self) -> None:
        note = Note(60, 90, 0, 100, 0)
        excluded = Track(1, [note], 0x11)
        malformed = Track(
            2,
            [Note(0, 90, 0, 100, 0)],
            0x99,
            duration_scale=0.5,
            volume_scale=0.75,
            articulation_type=7,
            bdo_track_volume="invalid",  # type: ignore[arg-type]
            bdo_track_settings=(1, 2),
        )
        first = Track(
            3,
            [note],
            0x11,
            display_name="Lead A",
            bdo_track_volume=60,
            bdo_track_settings=(10, 0, 0, 0, 0, 0, 0, 0),
        )
        second = Track(
            4,
            [Note(64, 90, 100, 100, 0)],
            0x11,
            display_name="Lead B",
            bdo_track_volume=70,
            bdo_track_settings=(20, 0, 0, 0, 0, 0, 0, 0),
        )
        capacity_policy = LimitPolicy(
            1,
            "wire_hard",
            Evidence("verified", "ordered fixture"),
        )
        profile = replace(
            self.profile,
            note_limit_per_instrument=1,
            limit_policies={
                **self.profile.limit_policies,
                "notes_per_instrument": capacity_policy,
            },
        )
        tracks = [excluded, malformed, first, second]
        context = ValidationContext(
            0,
            frozenset({2, 3, 4}),
            {},
            {36: 48, 37: 49},
            lambda track: track.bdo_instrument_id,
            sample_only_percussion_ids=frozenset({0x99}),
            velocity_mode="normalize",
            effects=(101, 0, (0, 0, 0)),
        )

        issues = validate_tracks(tracks, profile, context)

        self.assertEqual(
            [
                "track.excluded",
                "track.volume_wire_range",
                "track.effects_wire_shape",
                "instrument.unknown",
                "pitch.wire_clamp",
                "pitch.range_unverified",
                "export.duration_scale",
                "export.velocity_scale",
                "articulation.unsupported",
                "percussion.sample_only",
                "tracks.merge",
                "tracks.volume_conflict",
                "tracks.effects_conflict",
                "capacity.instrument",
                "export.velocity_mode",
                "export.global_effects",
                "export.global_effects_legacy_range",
            ],
            [issue.code for issue in issues],
        )


if __name__ == "__main__":
    unittest.main()
