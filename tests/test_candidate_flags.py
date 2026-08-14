"""Focused tests for candidate invalid/duplicate flag classification."""

from __future__ import annotations

from dataclasses import dataclass
import unittest

from bdo_midi import Note

from bdo_music_composer.transcription.bdo_transcription_policy import (
    candidate_duplicate_flags,
    candidate_is_invalid_for_track,
)


@dataclass(frozen=True, slots=True)
class Candidate:
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float


def _candidate(*, start_ms: float = 100.0, pitch: int = 60, duration_ms: float = 80.0) -> Candidate:
    return Candidate(pitch, 90, start_ms, duration_ms)


class CandidateIsInvalidForTrackTests(unittest.TestCase):
    def test_rejects_negative_timing(self) -> None:
        self.assertTrue(
            candidate_is_invalid_for_track(
                _candidate(start_ms=-50.0),
                reference_audio_offset_ms=0.0,
                is_percussion=False,
                instrument_id=0x0B,
            )
        )

    def test_rejects_percussion_track(self) -> None:
        self.assertTrue(
            candidate_is_invalid_for_track(
                _candidate(),
                reference_audio_offset_ms=0.0,
                is_percussion=True,
                instrument_id=0x0B,
            )
        )

    def test_rejects_out_of_range_pitch(self) -> None:
        self.assertTrue(
            candidate_is_invalid_for_track(
                _candidate(pitch=200),
                reference_audio_offset_ms=0.0,
                is_percussion=False,
                instrument_id=0x0B,
                supported_pitches={60, 64},
            )
        )

    def test_accepts_valid_candidate(self) -> None:
        self.assertFalse(
            candidate_is_invalid_for_track(
                _candidate(pitch=60),
                reference_audio_offset_ms=0.0,
                is_percussion=False,
                instrument_id=0x0B,
                supported_pitches={60, 64},
            )
        )


class CandidateDuplicateFlagsTests(unittest.TestCase):
    def test_marks_exact_duplicate(self) -> None:
        notes = [Note(60, 90, 100.0, 80.0, 0)]
        candidates = [_candidate(start_ms=100.0, pitch=60, duration_ms=80.0)]
        invalid_ids, duplicate_ids = candidate_duplicate_flags(
            notes,
            candidates,
            reference_audio_offset_ms=0.0,
            candidate_id_of=lambda c: "c0",
            is_invalid=lambda c: False,
        )
        self.assertEqual(invalid_ids, frozenset())
        self.assertEqual(duplicate_ids, {"c0"})

    def test_marks_invalid_and_skips_duplicate_check(self) -> None:
        notes = [Note(60, 90, 100.0, 80.0, 0)]
        candidates = [_candidate(start_ms=-50.0, pitch=60)]
        invalid_ids, duplicate_ids = candidate_duplicate_flags(
            notes,
            candidates,
            reference_audio_offset_ms=0.0,
            candidate_id_of=lambda c: "c0",
            is_invalid=lambda c: True,
        )
        self.assertEqual(invalid_ids, {"c0"})
        self.assertEqual(duplicate_ids, frozenset())

    def test_ignores_different_pitch(self) -> None:
        notes = [Note(60, 90, 100.0, 80.0, 0)]
        candidates = [_candidate(start_ms=100.0, pitch=61)]
        invalid_ids, duplicate_ids = candidate_duplicate_flags(
            notes,
            candidates,
            reference_audio_offset_ms=0.0,
            candidate_id_of=lambda c: "c0",
            is_invalid=lambda c: False,
        )
        self.assertEqual(invalid_ids, frozenset())
        self.assertEqual(duplicate_ids, frozenset())

    def test_empty_notes_yield_no_duplicates(self) -> None:
        candidates = [_candidate()]
        invalid_ids, duplicate_ids = candidate_duplicate_flags(
            [],
            candidates,
            reference_audio_offset_ms=0.0,
            candidate_id_of=lambda c: "c0",
            is_invalid=lambda c: False,
        )
        self.assertEqual(invalid_ids, frozenset())
        self.assertEqual(duplicate_ids, frozenset())


if __name__ == "__main__":
    unittest.main()
