from __future__ import annotations

from dataclasses import dataclass
import unittest

import numpy as np

from bdo_music_composer.transcription.bdo_transcription import (
    _recover_dense_short_frame_events,
)
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentConfig,
    analyse_rhythm_alignment,
    estimate_rhythm_grid_from_evidence,
)
from bdo_music_composer.transcription.rhythm_grid import (
    ProjectRhythmSettings,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float


def _regular_evidence() -> tuple[np.ndarray, np.ndarray]:
    times = np.arange(0.0, 8_000.0, 10.0, dtype=np.float64)
    onset = np.zeros((len(times), 88), dtype=np.float32)
    for value in range(0, 8_000, 500):
        onset[value // 10, 60 - 21] = 1.0
    return times, onset


class RhythmAlignmentTests(unittest.TestCase):
    def test_estimator_recovers_regular_tempo_without_optional_jit(self) -> None:
        times, onset = _regular_evidence()
        estimate = estimate_rhythm_grid_from_evidence(
            ProjectRhythmSettings(enabled=True, bpm=120.0),
            frame_times_ms=times,
            onset_evidence=onset,
        )
        self.assertFalse(estimate.used_project_fallback)
        self.assertAlmostEqual(estimate.detected_bpm, 120.0, places=4)
        self.assertGreater(estimate.confidence, 0.8)
        self.assertEqual(estimate.beat_count, 16)

    def test_auto_projection_is_exact_and_keeps_chords_together(self) -> None:
        times, onset = _regular_evidence()
        candidates = (
            _Candidate("a", 60, 497.0, 248.0, 0.9),
            _Candidate("b", 64, 512.0, 250.0, 0.8),
            _Candidate("c", 60, 751.0, 240.0, 0.85),
        )
        sidecar = analyse_rhythm_alignment(
            evidence_cache_key="a" * 24,
            candidates=candidates,
            settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
            frame_times_ms=times,
            onset_evidence=onset,
        )
        first = sidecar.projection_for("a")
        chord = sidecar.projection_for("b")
        following = sidecar.projection_for("c")
        assert first is not None and chord is not None and following is not None
        self.assertEqual(first.start_ms, chord.start_ms)
        for item in (first, chord, following):
            units = item.start_ms / (500.0 / 16.0)
            self.assertAlmostEqual(units, round(units), places=8)
        self.assertLessEqual(first.duration_ms, following.start_ms - first.start_ms)
        self.assertTrue(
            sidecar.is_current(
                evidence_cache_key="a" * 24,
                candidates=candidates,
            )
        )

    def test_raw_profile_is_non_mutating(self) -> None:
        times, onset = _regular_evidence()
        candidate = _Candidate("a", 60, 497.0, 248.0, 0.9)
        sidecar = analyse_rhythm_alignment(
            evidence_cache_key="b" * 24,
            candidates=(candidate,),
            settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
            frame_times_ms=times,
            onset_evidence=onset,
            config=RhythmAlignmentConfig(profile="raw"),
        )
        projected = sidecar.projection_for("a")
        assert projected is not None
        self.assertEqual(projected.start_ms, candidate.start_ms)
        self.assertEqual(projected.duration_ms, candidate.duration_ms)
        self.assertEqual(sidecar.aligned_count, 0)

    def test_project_bpm_mismatch_never_time_stretches_source_audio(self) -> None:
        times = np.arange(0.0, 30_000.0, 10.0, dtype=np.float64)
        onset = np.zeros((len(times), 88), dtype=np.float32)
        for value in range(0, 30_000, 600):
            onset[value // 10, 60 - 21] = 1.0
        candidates = (
            _Candidate("near", 60, 6_000.0, 300.0, 0.9),
            _Candidate("late", 64, 24_000.0, 300.0, 0.9),
        )
        config = RhythmAlignmentConfig(
            profile="auto",
            maximum_local_shift_ms=45.0,
        )
        sidecar = analyse_rhythm_alignment(
            evidence_cache_key="d" * 24,
            candidates=candidates,
            settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
            frame_times_ms=times,
            onset_evidence=onset,
            config=config,
        )

        self.assertAlmostEqual(sidecar.estimate.detected_bpm, 100.0)
        self.assertFalse(sidecar.estimate.used_project_fallback)
        for candidate in candidates:
            projected = sidecar.projection_for(candidate.candidate_id)
            assert projected is not None
            self.assertLessEqual(
                abs(projected.start_ms - candidate.start_ms),
                config.maximum_local_shift_ms,
            )
            self.assertLessEqual(
                abs(
                    projected.start_ms
                    + projected.duration_ms
                    - candidate.start_ms
                    - candidate.duration_ms
                ),
                config.maximum_local_shift_ms,
            )
        self.assertLessEqual(
            sidecar.max_abs_shift_ms,
            config.maximum_local_shift_ms,
        )

    def test_raw_profile_preserves_colliding_notes_exactly(self) -> None:
        times, onset = _regular_evidence()
        candidates = (
            _Candidate("a", 60, 500.0, 80.0, 0.9),
            _Candidate("b", 60, 500.0, 80.0, 0.8),
        )
        sidecar = analyse_rhythm_alignment(
            evidence_cache_key="e" * 24,
            candidates=candidates,
            settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
            frame_times_ms=times,
            onset_evidence=onset,
            config=RhythmAlignmentConfig(profile="raw"),
        )
        self.assertEqual(
            tuple(
                (item.start_ms, item.duration_ms)
                for item in sidecar.projections
            ),
            ((500.0, 80.0), (500.0, 80.0)),
        )
        self.assertEqual(sidecar.aligned_count, 0)

    def test_same_pitch_collisions_are_shifted_to_the_next_1_64_slot(self) -> None:
        times, onset = _regular_evidence()
        candidates = (
            _Candidate("a", 60, 500.0, 80.0, 0.9),
            _Candidate("b", 60, 510.0, 80.0, 0.9),
        )
        sidecar = analyse_rhythm_alignment(
            evidence_cache_key="c" * 24,
            candidates=candidates,
            settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
            frame_times_ms=times,
            onset_evidence=onset,
            config=RhythmAlignmentConfig(profile="strict_1_64"),
        )
        first = sidecar.projection_for("a")
        second = sidecar.projection_for("b")
        assert first is not None and second is not None
        self.assertAlmostEqual(second.start_ms - first.start_ms, 31.25)
        self.assertLessEqual(
            abs(
                first.start_ms
                + first.duration_ms
                - candidates[0].start_ms
                - candidates[0].duration_ms
            ),
            45.0,
        )


class DenseShortRecoveryTests(unittest.TestCase):
    def test_only_regular_strong_short_sequence_is_recovered(self) -> None:
        frame = np.zeros((32, 88), dtype=np.float32)
        onset = np.zeros_like(frame)
        column = 60 - 21
        for start in (5, 9, 13):
            onset[start, column] = 0.9
            frame[start : start + 3, column] = 0.7
        recovered = _recover_dense_short_frame_events(
            frame,
            onset,
            [],
            onset_threshold=0.5,
            frame_threshold=0.3,
            min_note_len=5,
        )
        self.assertEqual(
            tuple((item.start_frame, item.end_frame, item.pitch) for item in recovered),
            ((5, 8, 60), (9, 12, 60), (13, 16, 60)),
        )

    def test_isolated_short_peak_is_not_recovered(self) -> None:
        frame = np.zeros((24, 88), dtype=np.float32)
        onset = np.zeros_like(frame)
        column = 60 - 21
        onset[8, column] = 0.95
        frame[8:11, column] = 0.8
        self.assertEqual(
            _recover_dense_short_frame_events(
                frame,
                onset,
                [],
                onset_threshold=0.5,
                frame_threshold=0.3,
                min_note_len=5,
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
