from __future__ import annotations

from collections import namedtuple
from types import SimpleNamespace
import unittest

from bdo_music_composer.editor.pitch_transform import (
    PITCH_OVERRIDE_MODE_SEMITONE,
    PITCH_OVERRIDE_PROVENANCE_AUTO,
    PitchTransformPlan,
    TrackPitchOverride,
    track_uses_percussion_pitch_semantics,
    transpose_notes,
)


Note = namedtuple("Note", "pitch vel start dur ntype")


class PitchTransformTests(unittest.TestCase):
    def test_global_and_track_octave_resolve_once_without_mutating_notes(self) -> None:
        source = [Note(60, 90, 0.0, 200.0, 0)]
        plan = PitchTransformPlan(-8).with_track_octave(7, 12)

        projected = transpose_notes(
            source,
            plan.effective_semitones(7),
        )

        self.assertEqual(plan.effective_semitones(7), 4)
        self.assertEqual(projected[0].pitch, 64)
        self.assertEqual(source[0].pitch, 60)
        self.assertEqual(projected[0]._fields, source[0]._fields)

    def test_drums_are_exempt_from_global_and_stale_track_overrides(self) -> None:
        plan = PitchTransformPlan(-8).with_track_octave(3, 24)

        resolved = plan.resolve(3, is_drum=True)

        self.assertTrue(resolved.drum_exempt)
        self.assertEqual(resolved.effective_semitones, 0)

    def test_bdo_drum_target_is_percussion_even_with_melodic_source_flag(self) -> None:
        track = SimpleNamespace(
            track_id=3,
            is_percussion=False,
            bdo_instrument_id=0x0D,
        )
        plan = PitchTransformPlan(-8).with_track_octave(3, 24)

        self.assertTrue(track_uses_percussion_pitch_semantics(track))
        self.assertEqual(plan.effective_track_semitones(track), 0)
        self.assertTrue(plan.is_neutral([track]))

    def test_octave_policy_rejects_non_octave_automatic_offsets(self) -> None:
        with self.assertRaises(ValueError):
            TrackPitchOverride(1, 7)
        explicit = TrackPitchOverride(
            1,
            7,
            mode=PITCH_OVERRIDE_MODE_SEMITONE,
        )
        self.assertEqual(explicit.semitones, 7)
        with self.assertRaises(ValueError):
            TrackPitchOverride(
                1,
                7,
                mode=PITCH_OVERRIDE_MODE_SEMITONE,
                provenance=PITCH_OVERRIDE_PROVENANCE_AUTO,
            )

    def test_payload_is_sorted_deterministic_and_prunable(self) -> None:
        plan = PitchTransformPlan.from_payload(
            {
                "global_semitones": -8,
                "track_overrides": [
                    {"track_id": 9, "semitones": -12},
                    {"track_id": 2, "semitones": 12},
                    {"track_id": "broken", "semitones": 12},
                ],
            }
        )

        self.assertEqual(
            [item["track_id"] for item in plan.to_payload()["track_overrides"]],
            [2, 9],
        )
        self.assertEqual(
            [item.track_id for item in plan.pruned({9}).track_overrides],
            [9],
        )

    def test_duplicate_payload_track_ids_use_first_valid_rule(self) -> None:
        plan = PitchTransformPlan.from_payload(
            {
                "track_overrides": [
                    {"track_id": 4, "semitones": 12},
                    {"track_id": 4, "semitones": -12},
                ]
            }
        )
        self.assertEqual(plan.effective_semitones(4), 12)


if __name__ == "__main__":
    unittest.main()
