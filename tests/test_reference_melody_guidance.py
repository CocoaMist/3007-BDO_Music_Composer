from __future__ import annotations

import unittest

from bdo_midi import Note
from bdo_music_composer.transcription.bdo_transcription import (
    TranscriptionCandidate,
)
from bdo_music_composer.transcription.reference_melody_guidance import (
    MAX_GUIDANCE_BOOST,
    build_reference_melody_guidance,
)
from bdo_music_composer.transcription.reference_timbre import (
    ReferenceTimbreGroup,
)


def _candidate(candidate_id: str, pitch: int, start_ms: float):
    return TranscriptionCandidate(
        pitch,
        80,
        start_ms,
        420.0,
        0.92,
        candidate_id=candidate_id,
    )


class ReferenceMelodyGuidanceTests(unittest.TestCase):
    def test_fragment_hits_are_deduplicated_by_window_and_pitch(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("a-fragment", 60, 25.0),
        )
        groups = (
            ReferenceTimbreGroup(
                "source-a",
                ("a", "a-fragment"),
                0.0,
                500.0,
                0.8,
                "#4AA3DF",
            ),
        )
        result = build_reference_melody_guidance(
            candidates=candidates,
            groups=groups,
            notes=(Note(60, 90, 0.0, 420.0, 0),),
            beat_ms=500.0,
        )

        self.assertEqual(result.matched_note_count, 1)
        self.assertEqual(result.groups[0].hit_count, 1)
        self.assertEqual(result.groups[0].window_count, 1)
        self.assertEqual(result.predicted_group_id, "source-a")
        self.assertEqual(result.focus_group_id, "")
        self.assertGreater(result.prediction_confidence, 0.0)
        self.assertEqual(result.groups[0].emphasis, 1.10)

    def test_focus_requires_repeated_distinct_time_windows(self) -> None:
        candidates = tuple(
            _candidate(f"a-{index}", 60 + index, index * 4_100.0)
            for index in range(2)
        )
        groups = (
            ReferenceTimbreGroup(
                "source-a",
                tuple(candidate.candidate_id for candidate in candidates),
                0.0,
                5_000.0,
                0.8,
                "#4AA3DF",
            ),
        )
        notes = tuple(
            Note(
                candidate.pitch,
                90,
                candidate.start_ms,
                candidate.duration_ms,
                0,
            )
            for candidate in candidates
        )
        result = build_reference_melody_guidance(
            candidates=candidates,
            groups=groups,
            notes=notes,
            beat_ms=500.0,
            target_instrument_id=0x0B,
            target_instrument_label="长笛",
        )

        self.assertEqual(result.focus_group_id, "source-a")
        self.assertEqual(result.target_instrument_id, 0x0B)
        self.assertEqual(result.target_instrument_label, "长笛")
        self.assertTrue(result.is_highest_priority_group("source-a"))
        self.assertFalse(result.is_highest_priority_group("source-b"))
        self.assertEqual(result.groups[0].window_count, 2)
        self.assertLessEqual(result.groups[0].boost, MAX_GUIDANCE_BOOST)
        self.assertEqual(result.groups[0].emphasis, 1.35)
        self.assertGreater(result.groups[0].emphasis, result.default_emphasis)
        self.assertGreaterEqual(result.default_emphasis, 0.35)

    def test_projected_candidate_time_is_the_focus_authority(self) -> None:
        raw_candidates = (
            _candidate("a-0", 60, 1_000.0),
            _candidate("a-1", 61, 5_100.0),
        )
        projected_candidates = (
            _candidate("a-0", 60, 0.0),
            _candidate("a-1", 61, 4_100.0),
        )
        groups = (
            ReferenceTimbreGroup(
                "source-a",
                ("a-0", "a-1"),
                0.0,
                6_000.0,
                0.8,
                "#4AA3DF",
            ),
        )
        notes = (
            Note(60, 90, 0.0, 420.0, 0),
            Note(61, 90, 4_100.0, 420.0, 0),
        )

        raw = build_reference_melody_guidance(
            candidates=raw_candidates,
            groups=groups,
            notes=notes,
            beat_ms=500.0,
        )
        projected = build_reference_melody_guidance(
            candidates=projected_candidates,
            groups=groups,
            notes=notes,
            beat_ms=500.0,
            target_instrument_id=0x0B,
            target_instrument_label="长笛",
        )

        self.assertEqual(raw.matched_note_count, 0)
        self.assertEqual(raw.focus_group_id, "")
        self.assertEqual(projected.matched_note_count, 2)
        self.assertEqual(projected.focus_group_id, "source-a")

    def test_adjacent_notes_across_absolute_boundary_are_one_window(self) -> None:
        candidates = (
            _candidate("a-0", 60, 3_900.0),
            _candidate("a-1", 61, 4_100.0),
        )
        groups = (
            ReferenceTimbreGroup(
                "source-a",
                ("a-0", "a-1"),
                0.0,
                5_000.0,
                0.8,
                "#4AA3DF",
            ),
        )
        notes = tuple(
            Note(
                candidate.pitch,
                90,
                candidate.start_ms,
                candidate.duration_ms,
                0,
            )
            for candidate in candidates
        )

        result = build_reference_melody_guidance(
            candidates=candidates,
            groups=groups,
            notes=notes,
            beat_ms=500.0,
        )

        self.assertEqual(result.groups[0].window_count, 1)
        self.assertEqual(result.focus_group_id, "")

    def test_ambiguous_source_hit_does_not_vote(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("b", 60, 5.0),
        )
        groups = (
            ReferenceTimbreGroup("source-a", ("a",), 0, 500, 0.8, "#f00"),
            ReferenceTimbreGroup("source-b", ("b",), 0, 500, 0.8, "#0f0"),
        )
        result = build_reference_melody_guidance(
            candidates=candidates,
            groups=groups,
            notes=(Note(60, 90, 0.0, 420.0, 0),),
            beat_ms=500.0,
        )

        self.assertEqual(result.ambiguous_note_count, 1)
        self.assertFalse(result.groups)
        self.assertEqual(result.default_emphasis, 1.0)

    def test_disabled_guidance_is_an_identity_projection(self) -> None:
        result = build_reference_melody_guidance(
            candidates=(),
            groups=(),
            notes=(Note(60, 90, 0.0, 420.0, 0),),
            beat_ms=500.0,
            enabled=False,
        )

        self.assertFalse(result.enabled)
        self.assertEqual(result.default_emphasis, 1.0)
        self.assertEqual(result.group_emphasis("anything"), 1.0)


if __name__ == "__main__":
    unittest.main()
