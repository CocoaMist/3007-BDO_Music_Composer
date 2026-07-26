"""Qt-free policy for projecting transcription candidates into editor notes.

Candidates always retain their original audio-relative timing.  This module is
the single boundary that applies the reference-audio offset when comparing or
creating authoritative editor ``Note`` values.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Collection, Protocol

from bdo_midi import BDO_NOTE_MAX, BDO_NOTE_MIN, Note


BDO_PERCUSSION_INSTRUMENT_ID = 0x0D


class CandidateLike(Protocol):
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float


class NoteLike(Protocol):
    pitch: int
    start: float
    dur: float


@dataclass(frozen=True, slots=True)
class ProjectedCandidateNote:
    """Candidate timing after the audio-to-project offset is applied once."""

    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float


@dataclass(frozen=True, slots=True)
class CandidateNotePolicy:
    """Deterministic candidate matching and editor-note creation rules."""

    onset_tolerance_ms: float = 40.0
    duration_relative_tolerance: float = 0.18
    minimum_duration_ms: float = 1.0

    @staticmethod
    def project_start_ms(
        candidate: CandidateLike,
        reference_audio_offset_ms: float = 0.0,
    ) -> float:
        return (
            float(candidate.start_ms)
            + float(reference_audio_offset_ms)
        )

    def note_duration_ms(self, candidate: CandidateLike) -> float:
        return max(
            float(self.minimum_duration_ms),
            float(candidate.duration_ms),
        )

    def project_timing_is_valid(
        self,
        candidate: CandidateLike,
        reference_audio_offset_ms: float = 0.0,
    ) -> bool:
        """Return whether a candidate can exist on the project timeline."""

        project_start = self.project_start_ms(
            candidate,
            reference_audio_offset_ms,
        )
        duration_ms = float(candidate.duration_ms)
        return (
            math.isfinite(project_start)
            and project_start >= 0.0
            and math.isfinite(duration_ms)
            and duration_ms >= 0.0
        )

    def project(
        self,
        candidate: CandidateLike,
        reference_audio_offset_ms: float = 0.0,
    ) -> ProjectedCandidateNote:
        return ProjectedCandidateNote(
            pitch=int(candidate.pitch),
            velocity=max(1, min(127, int(candidate.velocity))),
            start_ms=self.project_start_ms(
                candidate,
                reference_audio_offset_ms,
            ),
            duration_ms=self.note_duration_ms(candidate),
        )

    def match_window(
        self,
        candidate: CandidateLike,
        reference_audio_offset_ms: float = 0.0,
    ) -> tuple[float, float]:
        project_start = self.project_start_ms(
            candidate,
            reference_audio_offset_ms,
        )
        return (
            project_start - float(self.onset_tolerance_ms),
            project_start + float(self.onset_tolerance_ms),
        )

    def duration_tolerance_ms(
        self,
        candidate: CandidateLike,
    ) -> float:
        duration_ms = self.note_duration_ms(candidate)
        return max(
            float(self.onset_tolerance_ms),
            duration_ms * float(self.duration_relative_tolerance),
        )

    def matches_note(
        self,
        candidate: CandidateLike,
        note: NoteLike,
        reference_audio_offset_ms: float = 0.0,
    ) -> bool:
        project_start = self.project_start_ms(
            candidate,
            reference_audio_offset_ms,
        )
        duration_ms = self.note_duration_ms(candidate)
        values = (
            project_start,
            duration_ms,
            float(note.start),
            float(note.dur),
        )
        if not all(math.isfinite(value) for value in values):
            return False
        return (
            int(candidate.pitch) == int(note.pitch)
            and abs(project_start - float(note.start))
            <= float(self.onset_tolerance_ms)
            and abs(duration_ms - float(note.dur))
            <= max(
                float(self.onset_tolerance_ms),
                duration_ms * float(self.duration_relative_tolerance),
            )
        )

    def to_note(
        self,
        candidate: CandidateLike,
        reference_audio_offset_ms: float = 0.0,
    ) -> Note:
        if not self.project_timing_is_valid(
            candidate,
            reference_audio_offset_ms,
        ):
            raise ValueError(
                "candidate projects outside the non-negative project timeline"
            )
        projected = self.project(candidate, reference_audio_offset_ms)
        return Note(
            max(0, min(127, projected.pitch)),
            projected.velocity,
            projected.start_ms,
            projected.duration_ms,
            0,
        )

    @staticmethod
    def pitch_is_valid_for_melodic_track(
        candidate_pitch: int,
        *,
        is_percussion: bool,
        instrument_id: int,
        transpose: int = 0,
        supported_pitches: Collection[int] | None = None,
    ) -> bool:
        """Fail closed for percussion, then validate the exported pitch."""

        if (
            bool(is_percussion)
            or int(instrument_id) == BDO_PERCUSSION_INSTRUMENT_ID
        ):
            return False
        converted_pitch = int(candidate_pitch) + int(transpose)
        if supported_pitches is not None:
            return converted_pitch in supported_pitches
        return BDO_NOTE_MIN <= converted_pitch <= BDO_NOTE_MAX


CANDIDATE_NOTE_POLICY = CandidateNotePolicy()


__all__ = [
    "BDO_PERCUSSION_INSTRUMENT_ID",
    "CANDIDATE_NOTE_POLICY",
    "CandidateLike",
    "CandidateNotePolicy",
    "NoteLike",
    "ProjectedCandidateNote",
]
