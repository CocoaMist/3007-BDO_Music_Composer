from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import unittest

import numpy as np

from bdo_transcription_harmony import (
    ChordSegment,
    HarmonyAnalysisCancelled,
    HarmonyAnalysis,
    KeyEstimate,
    analyse_harmony,
    apply_harmony_overrides,
    apply_locked_harmony,
    harmony_cache_key,
)


MIDI_MIN = 21


def frame_fixture(
    regions: list[tuple[float, float, tuple[int, ...]]],
    *,
    duration_ms: float = 1_000.0,
    frame_period_ms: float = 25.0,
) -> tuple[np.ndarray, np.ndarray]:
    times = np.arange(0.0, duration_ms, frame_period_ms, dtype=np.float64)
    frames = np.zeros((len(times), 88), dtype=np.float32)
    for start, end, pitches in regions:
        rows = (times >= start) & (times < end)
        for pitch in pitches:
            frames[rows, pitch - MIDI_MIN] = 0.9
    return frames, times


def symbolic_chord(
    pitches: tuple[int, ...],
    *,
    start_ms: float = 0.0,
    duration_ms: float = 500.0,
) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(
            pitch=pitch,
            velocity=104,
            start_ms=start_ms,
            duration_ms=duration_ms,
            confidence=0.95,
        )
        for pitch in pitches
    )


class HarmonyChordTests(unittest.TestCase):
    def test_supported_chord_qualities_and_inversions(self) -> None:
        patterns = {
            "major": (0, 4, 7),
            "minor": (0, 3, 7),
            "dim": (0, 3, 6),
            "sus2": (0, 2, 7),
            "sus4": (0, 5, 7),
            "maj7": (0, 4, 7, 11),
            "7": (0, 4, 7, 10),
            "min7": (0, 3, 7, 10),
            "half_diminished7": (0, 3, 6, 10),
        }
        for expected_quality, intervals in patterns.items():
            with self.subTest(quality=expected_quality):
                pitches = tuple(48 + interval for interval in intervals)
                frames, times = frame_fixture(
                    [(0.0, 500.0, pitches)],
                    duration_ms=500.0,
                )
                result = analyse_harmony(
                    frames,
                    times,
                    cache_key=f"quality-{expected_quality}",
                    bpm=120,
                    duration_ms=500.0,
                )
                segment = result.chord_segments[0]
                self.assertEqual(segment.root_pc, 0)
                self.assertEqual(segment.quality, expected_quality)
                self.assertEqual(segment.bass_pc, 0)
                self.assertGreaterEqual(segment.confidence, 0.8)

        # The root stays C while the explicit bass records first inversion.
        frames, times = frame_fixture(
            [(0.0, 500.0, (52, 55, 60))],
            duration_ms=500.0,
        )
        inversion = analyse_harmony(
            frames,
            times,
            cache_key="inversion",
            bpm=120,
            duration_ms=500.0,
        ).chord_segments[0]
        self.assertEqual((inversion.root_pc, inversion.quality), (0, "major"))
        self.assertEqual(inversion.bass_pc, 4)

    def test_single_note_and_dyad_fail_closed_to_no_chord(self) -> None:
        for pitches in ((60,), (60, 61), (60, 67)):
            with self.subTest(pitches=pitches):
                frames, times = frame_fixture(
                    [(0.0, 500.0, pitches)],
                    duration_ms=500.0,
                )
                segment = analyse_harmony(
                    frames,
                    times,
                    cache_key=f"sparse-{pitches}",
                    bpm=120,
                    duration_ms=500.0,
                ).chord_segments[0]
                self.assertEqual(segment.quality, "N")
                self.assertIsNone(segment.root_pc)
                self.assertIsNone(segment.bass_pc)

    def test_viterbi_never_turns_fail_closed_dyad_into_previous_chord(
        self,
    ) -> None:
        frames, times = frame_fixture(
            [
                (0.0, 500.0, (48, 52, 55)),
                (500.0, 1000.0, (48, 55)),
            ],
            duration_ms=1000.0,
        )
        segments = analyse_harmony(
            frames,
            times,
            cache_key="strict-n-after-chord",
            bpm=120,
            duration_ms=1000.0,
        ).chord_segments
        self.assertEqual(
            [
                (segment.start_audio_ms, segment.end_audio_ms, segment.quality)
                for segment in segments
            ],
            [(0.0, 500.0, "major"), (500.0, 1000.0, "N")],
        )

    def test_exact_frame_times_and_first_beat_anchor_define_windows(self) -> None:
        frames, times = frame_fixture(
            [
                (0.0, 250.0, (48, 52, 55)),
                (250.0, 750.0, (50, 53, 57)),
                (750.0, 1_000.0, (55, 59, 62)),
            ]
        )
        result = analyse_harmony(
            frames,
            times,
            cache_key="anchored",
            bpm=120,
            beat_origin_audio_ms=250.0,
            duration_ms=1_000.0,
        )
        self.assertEqual(
            [
                (segment.start_audio_ms, segment.end_audio_ms)
                for segment in result.chord_segments
            ],
            [(0.0, 250.0), (250.0, 750.0), (750.0, 1_000.0)],
        )
        self.assertEqual(
            [(segment.root_pc, segment.quality) for segment in result.chord_segments],
            [(0, "major"), (2, "minor"), (7, "major")],
        )

    def test_stable_ids_and_deterministic_smoothing_merge_equal_beats(self) -> None:
        frames, times = frame_fixture(
            [(0.0, 1_000.0, (48, 52, 55))]
        )
        first = analyse_harmony(
            frames,
            times,
            cache_key="stable",
            bpm=120,
            duration_ms=1_000.0,
        )
        second = analyse_harmony(
            frames.copy(),
            times.copy(),
            cache_key="stable",
            bpm=120,
            duration_ms=1_000.0,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first.chord_segments), 1)
        self.assertEqual(
            (
                first.chord_segments[0].start_audio_ms,
                first.chord_segments[0].end_audio_ms,
            ),
            (0.0, 1_000.0),
        )
        changed_identity = analyse_harmony(
            frames,
            times,
            cache_key="different-cache",
            bpm=120,
            duration_ms=1_000.0,
        )
        self.assertNotEqual(
            first.chord_segments[0].segment_id,
            changed_identity.chord_segments[0].segment_id,
        )

    def test_symbolic_candidates_and_notes_are_scored_separately(self) -> None:
        frames, times = frame_fixture([], duration_ms=500.0)
        from_candidates = analyse_harmony(
            frames,
            times,
            cache_key="candidate-only",
            bpm=120,
            duration_ms=500.0,
            symbolic_candidates=symbolic_chord((48, 52, 55)),
        ).chord_segments[0]
        self.assertEqual(from_candidates.source, "candidates")
        self.assertEqual((from_candidates.root_pc, from_candidates.quality), (0, "major"))
        self.assertGreater(from_candidates.alternatives[0].candidate_score, 0.9)
        self.assertEqual(from_candidates.alternatives[0].audio_score, 0.0)
        self.assertEqual(from_candidates.alternatives[0].note_score, 0.0)

        note_events = tuple(
            SimpleNamespace(pitch=pitch, vel=96, start=0.0, dur=500.0)
            for pitch in (45, 48, 52)
        )
        from_notes = analyse_harmony(
            frames,
            times,
            cache_key="note-only",
            bpm=120,
            duration_ms=500.0,
            symbolic_notes=note_events,
        ).chord_segments[0]
        self.assertEqual(from_notes.source, "notes")
        self.assertEqual((from_notes.root_pc, from_notes.quality), (9, "minor"))
        self.assertGreater(from_notes.alternatives[0].note_score, 0.9)
        self.assertEqual(from_notes.alternatives[0].candidate_score, 0.0)

    def test_audio_symbolic_disagreement_preserves_explainable_top_two(self) -> None:
        frames, times = frame_fixture(
            [(0.0, 500.0, (48, 52, 55))],
            duration_ms=500.0,
        )
        result = analyse_harmony(
            frames,
            times,
            cache_key="conflict",
            bpm=120,
            duration_ms=500.0,
            symbolic_candidates=symbolic_chord((50, 53, 57)),
        )
        self.assertIn(
            "audio_symbolic",
            {conflict.kind for conflict in result.conflicts},
        )
        alternatives = result.chord_segments[0].alternatives
        self.assertEqual(
            {(item.root_pc, item.quality) for item in alternatives},
            {(0, "major"), (2, "minor")},
        )
        c_major = next(item for item in alternatives if item.root_pc == 0)
        d_minor = next(item for item in alternatives if item.root_pc == 2)
        self.assertGreater(c_major.audio_score, c_major.candidate_score)
        self.assertGreater(d_minor.candidate_score, d_minor.audio_score)


class HarmonyKeyAndOverrideTests(unittest.TestCase):
    def test_global_key_has_top_three_and_is_conservative(self) -> None:
        pitches = (
            48,
            52,
            55,
            60,
            62,
            64,
            65,
            67,
            69,
            71,
            72,
            72,
            67,
            60,
            60,
        )
        duration = float(len(pitches) * 100)
        times = np.arange(0.0, duration, 25.0, dtype=np.float64)
        frames = np.zeros((len(times), 88), dtype=np.float32)
        for row, time_ms in enumerate(times):
            frames[row, pitches[int(time_ms // 100.0)] - MIDI_MIN] = 0.9
        estimate = analyse_harmony(
            frames,
            times,
            cache_key="key-c-major",
            bpm=120,
            duration_ms=duration,
        ).global_key
        self.assertEqual((estimate.root_pc, estimate.mode), (0, "major"))
        self.assertGreater(estimate.confidence, 0.8)
        self.assertEqual(len(estimate.alternatives), 3)
        self.assertEqual(
            (estimate.alternatives[0].root_pc, estimate.alternatives[0].mode),
            (0, "major"),
        )

        sparse_frames, sparse_times = frame_fixture(
            [(0.0, 500.0, (60,))],
            duration_ms=500.0,
        )
        sparse = analyse_harmony(
            sparse_frames,
            sparse_times,
            cache_key="key-sparse",
            bpm=120,
            duration_ms=500.0,
        ).global_key
        self.assertIsNone(sparse.root_pc)
        self.assertIsNone(sparse.mode)

    def test_manual_overrides_split_auto_segments_and_survive_reanalysis(self) -> None:
        frames, times = frame_fixture(
            [(0.0, 1_000.0, (48, 52, 55))]
        )
        automatic = analyse_harmony(
            frames,
            times,
            cache_key="override-cache",
            bpm=120,
            duration_ms=1_000.0,
        )
        manual_key = KeyEstimate(9, "minor", 0.2, (), "audio")
        manual_chord = ChordSegment(
            "",
            250.0,
            750.0,
            2,
            "minor",
            2,
            0.2,
        )
        overridden = apply_harmony_overrides(
            automatic,
            key_override=manual_key,
            chord_overrides=(manual_chord,),
        )
        self.assertEqual(
            [
                (item.start_audio_ms, item.end_audio_ms, item.root_pc, item.quality)
                for item in overridden.chord_segments
            ],
            [
                (0.0, 250.0, 0, "major"),
                (250.0, 750.0, 2, "minor"),
                (750.0, 1_000.0, 0, "major"),
            ],
        )
        locked = overridden.chord_segments[1]
        self.assertFalse(locked.locked)
        self.assertEqual(locked.source, "manual")
        self.assertEqual(locked.confidence, 1.0)
        self.assertEqual(overridden.global_key.source, "manual")
        self.assertEqual(overridden.global_key.confidence, 1.0)

        new_frames, new_times = frame_fixture(
            [(0.0, 1_000.0, (55, 59, 62))]
        )
        reanalysed = analyse_harmony(
            new_frames,
            new_times,
            cache_key="override-cache",
            bpm=120,
            duration_ms=1_000.0,
        )
        restored = apply_locked_harmony(reanalysed, overridden)
        restored_locked = next(
            item
            for item in restored.chord_segments
            if item.source == "manual"
        )
        self.assertEqual(
            (
                restored_locked.start_audio_ms,
                restored_locked.end_audio_ms,
                restored_locked.root_pc,
                restored_locked.quality,
            ),
            (250.0, 750.0, 2, "minor"),
        )
        self.assertEqual(
            (restored.global_key.root_pc, restored.global_key.mode),
            (9, "minor"),
        )
        self.assertEqual(restored.global_key.source, "manual")

    def test_overlapping_manual_overrides_fail_closed(self) -> None:
        base = HarmonyAnalysis(
            "manual-validation",
            KeyEstimate(None, None, 0.0),
            (),
        )
        first = ChordSegment("", 0.0, 500.0, 0, "major", 0, 1.0)
        second = ChordSegment("", 400.0, 800.0, 7, "7", 7, 1.0)
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            apply_harmony_overrides(
                base,
                chord_overrides=(first, second),
            )

    def test_cache_key_contains_timing_and_revision_identity(self) -> None:
        base = harmony_cache_key(
            "basic-pitch-cache",
            bpm=120,
            time_signature=4,
            beat_origin_audio_ms=0.0,
            candidate_revision="c1",
            note_revision="n1",
        )
        self.assertEqual(
            base,
            harmony_cache_key(
                "basic-pitch-cache",
                bpm=120,
                time_signature=4,
                beat_origin_audio_ms=0.0,
                candidate_revision="c1",
                note_revision="n1",
            ),
        )
        changed = harmony_cache_key(
            "basic-pitch-cache",
            bpm=120,
            time_signature=4,
            beat_origin_audio_ms=1.0,
            candidate_revision="c1",
            note_revision="n1",
        )
        self.assertNotEqual(base, changed)
        changed_bpm = harmony_cache_key(
            "basic-pitch-cache",
            bpm=90,
            time_signature=4,
            beat_origin_audio_ms=0.0,
            candidate_revision="c1",
            note_revision="n1",
        )
        self.assertNotEqual(base, changed_bpm)

    def test_public_results_are_immutable(self) -> None:
        estimate = KeyEstimate(0, "major", 0.9)
        with self.assertRaises(FrozenInstanceError):
            estimate.confidence = 0.1  # type: ignore[misc]


class HarmonyValidationTests(unittest.TestCase):
    def test_invalid_matrix_times_and_bpm_are_rejected(self) -> None:
        frames, times = frame_fixture(
            [(0.0, 500.0, (48, 52, 55))],
            duration_ms=500.0,
        )
        with self.assertRaisesRegex(ValueError, "match"):
            analyse_harmony(
                frames,
                times[:-1],
                cache_key="invalid",
                bpm=120,
            )
        invalid_times = times.copy()
        invalid_times[2] = invalid_times[1]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            analyse_harmony(
                frames,
                invalid_times,
                cache_key="invalid",
                bpm=120,
            )
        invalid_frames = frames.copy()
        invalid_frames[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite non-negative"):
            analyse_harmony(
                invalid_frames,
                times,
                cache_key="invalid",
                bpm=120,
            )
        with self.assertRaisesRegex(ValueError, "positive"):
            analyse_harmony(
                frames,
                times,
                cache_key="invalid",
                bpm=0,
            )

    def test_analysis_can_be_cancelled_before_work_starts(self) -> None:
        frames, times = frame_fixture(
            [(0.0, 500.0, (48, 52, 55))],
            duration_ms=500.0,
        )
        with self.assertRaisesRegex(
            HarmonyAnalysisCancelled,
            "cancelled",
        ) as caught:
            analyse_harmony(
                frames,
                times,
                cache_key="cancel-immediate",
                bpm=120,
                cancelled=lambda: True,
            )
        self.assertIsInstance(caught.exception, RuntimeError)

    def test_analysis_cooperatively_cancels_during_symbolic_indexing(
        self,
    ) -> None:
        frames, times = frame_fixture(
            [(0.0, 500.0, (48, 52, 55))],
            duration_ms=500.0,
        )
        events = tuple(
            SimpleNamespace(
                pitch=48 + index % 24,
                velocity=96,
                start_ms=float(index % 400),
                duration_ms=80.0,
                confidence=0.9,
            )
            for index in range(4_096)
        )
        calls = 0

        def cancelled() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 8

        with self.assertRaises(HarmonyAnalysisCancelled):
            analyse_harmony(
                frames,
                times,
                cache_key="cancel-symbolic",
                bpm=120,
                duration_ms=500.0,
                symbolic_candidates=events,
                cancelled=cancelled,
            )
        self.assertGreaterEqual(calls, 8)


if __name__ == "__main__":
    unittest.main()
