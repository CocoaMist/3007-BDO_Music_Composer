from __future__ import annotations

import unittest

from bdo_midi import BDO_NOTE_MAX, BDO_NOTE_MIN, Note
from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
from bdo_music_composer.transcription.bdo_transcription_policy import (
    BDO_PERCUSSION_INSTRUMENT_ID,
    CANDIDATE_NOTE_POLICY,
)


class CandidateNotePolicyTests(unittest.TestCase):
    def candidate(
        self,
        *,
        pitch: int = 60,
        start_ms: float = 100.0,
        duration_ms: float = 500.0,
    ) -> TranscriptionCandidate:
        return TranscriptionCandidate(
            pitch,
            96,
            start_ms,
            duration_ms,
            0.9,
            candidate_id="stable-id",
        )

    def test_projection_applies_audio_offset_once_without_mutating_candidate(
        self,
    ) -> None:
        candidate = self.candidate(start_ms=100.0)
        projected = CANDIDATE_NOTE_POLICY.project(candidate, 150.0)
        note = CANDIDATE_NOTE_POLICY.to_note(candidate, 150.0)

        self.assertEqual(projected.start_ms, 250.0)
        self.assertEqual(note, Note(60, 96, 250.0, 500.0, 0))
        self.assertTrue(
            CANDIDATE_NOTE_POLICY.matches_note(candidate, note, 150.0)
        )
        self.assertFalse(
            CANDIDATE_NOTE_POLICY.matches_note(candidate, note, 300.0)
        )
        self.assertEqual(candidate.start_ms, 100.0)
        self.assertEqual(candidate.candidate_id, "stable-id")

    def test_fixed_onset_boundary_is_deterministic(self) -> None:
        candidate = self.candidate()
        at_boundary = Note(60, 80, 140.0, 500.0, 0)
        outside_boundary = Note(60, 80, 140.001, 500.0, 0)

        self.assertTrue(
            CANDIDATE_NOTE_POLICY.matches_note(candidate, at_boundary)
        )
        self.assertFalse(
            CANDIDATE_NOTE_POLICY.matches_note(candidate, outside_boundary)
        )
        self.assertEqual(
            CANDIDATE_NOTE_POLICY.match_window(candidate),
            (60.0, 140.0),
        )

    def test_duration_uses_one_relative_or_absolute_rule(self) -> None:
        candidate = self.candidate(duration_ms=500.0)

        self.assertTrue(
            CANDIDATE_NOTE_POLICY.matches_note(
                candidate,
                Note(60, 80, 100.0, 590.0, 0),
            )
        )
        self.assertFalse(
            CANDIDATE_NOTE_POLICY.matches_note(
                candidate,
                Note(60, 80, 100.0, 590.001, 0),
            )
        )

        short = self.candidate(duration_ms=100.0)
        self.assertTrue(
            CANDIDATE_NOTE_POLICY.matches_note(
                short,
                Note(60, 80, 100.0, 140.0, 0),
            )
        )
        self.assertFalse(
            CANDIDATE_NOTE_POLICY.matches_note(
                short,
                Note(60, 80, 100.0, 140.001, 0),
            )
        )

    def test_minimum_duration_is_shared_by_matching_and_note_creation(
        self,
    ) -> None:
        candidate = self.candidate(duration_ms=0.0)
        note = CANDIDATE_NOTE_POLICY.to_note(candidate)

        self.assertEqual(note.dur, 1.0)
        self.assertTrue(CANDIDATE_NOTE_POLICY.matches_note(candidate, note))

    def test_negative_project_time_is_rejected_instead_of_clamped(self) -> None:
        candidate = self.candidate(start_ms=100.0)

        self.assertFalse(
            CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                candidate,
                -101.0,
            )
        )
        with self.assertRaisesRegex(ValueError, "project timeline"):
            CANDIDATE_NOTE_POLICY.to_note(candidate, -101.0)
        self.assertEqual(candidate.start_ms, 100.0)

    def test_melodic_pitch_validation_is_fail_closed_for_percussion(
        self,
    ) -> None:
        valid = CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track

        self.assertFalse(
            valid(
                60,
                is_percussion=True,
                instrument_id=1,
            )
        )
        self.assertFalse(
            valid(
                60,
                is_percussion=False,
                instrument_id=BDO_PERCUSSION_INSTRUMENT_ID,
            )
        )
        self.assertTrue(
            valid(
                60,
                is_percussion=False,
                instrument_id=1,
                transpose=2,
                supported_pitches={62},
            )
        )
        self.assertFalse(
            valid(
                60,
                is_percussion=False,
                instrument_id=1,
                transpose=1,
                supported_pitches={62},
            )
        )
        self.assertTrue(
            valid(
                BDO_NOTE_MIN,
                is_percussion=False,
                instrument_id=1,
            )
        )
        self.assertTrue(
            valid(
                BDO_NOTE_MAX,
                is_percussion=False,
                instrument_id=1,
            )
        )
        self.assertFalse(
            valid(
                BDO_NOTE_MAX + 1,
                is_percussion=False,
                instrument_id=1,
            )
        )


if __name__ == "__main__":
    unittest.main()
