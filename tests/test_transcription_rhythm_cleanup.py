from __future__ import annotations

from dataclasses import dataclass, replace
import unittest

import numpy as np

from bdo_music_composer.transcription.rhythm_cleanup import (
    RHYTHM_CANDIDATE_CHUNK_SIZE,
    RhythmCleanupProposal,
    RhythmDiagnosticCancelled,
    RhythmDiagnosticSidecar,
    analyse_project_rhythm_diagnostics,
)
from bdo_music_composer.transcription.rhythm_decode import (
    RhythmBoundaryObservation,
    RhythmDecodeCancelled,
    decode_rhythm_boundaries,
)
from bdo_music_composer.transcription.rhythm_grid import (
    ProjectRhythmSettings,
    build_project_rhythm_grid,
    rhythm_position_at,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float


def _evidence() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    times = np.arange(0.0, 410.0, 10.0, dtype=np.float64)
    frame = np.zeros((len(times), 88), dtype=np.float32)
    onset = np.zeros_like(frame)
    contour = np.zeros((len(times), 88 * 3), dtype=np.float32)
    frame[:, 60 - 21] = 0.8
    onset[0, 60 - 21] = 0.9
    onset[11, 60 - 21] = 0.2
    contour[:, (60 - 21) * 3] = 0.7
    return times, frame, onset, contour


class RhythmGridTests(unittest.TestCase):
    def test_project_grid_requires_explicit_enablement(self) -> None:
        self.assertIsNone(
            build_project_rhythm_grid(
                ProjectRhythmSettings(
                    enabled=False,
                    bpm=120.0,
                    beat_origin_audio_ms=0.0,
                    time_signature=4,
                )
            )
        )

    def test_project_grid_preserves_audio_time_and_projects_phase(self) -> None:
        grid = build_project_rhythm_grid(
            ProjectRhythmSettings(
                enabled=True,
                bpm=120.0,
                beat_origin_audio_ms=100.0,
                time_signature=4,
            )
        )
        self.assertIsNotNone(grid)
        assert grid is not None
        origin = rhythm_position_at(grid, 100.0)
        quarter = rhythm_position_at(grid, 225.0)
        self.assertAlmostEqual(origin.beat, 0.0)
        self.assertAlmostEqual(origin.phase, 0.0)
        self.assertAlmostEqual(quarter.beat, 0.25)
        self.assertAlmostEqual(quarter.phase, 0.25)


class RhythmDiagnosticTests(unittest.TestCase):
    def _sidecar(self) -> tuple[RhythmDiagnosticSidecar, tuple[_Candidate, ...]]:
        candidates = (
            _Candidate("a", 60, 0.0, 100.0, 0.8),
            _Candidate("b", 60, 110.0, 100.0, 0.3),
        )
        times, frame, onset, contour = _evidence()
        grid = build_project_rhythm_grid(
            ProjectRhythmSettings(enabled=True, bpm=120.0)
        )
        assert grid is not None
        sidecar = analyse_project_rhythm_diagnostics(
            evidence_cache_key="a" * 64,
            candidates=candidates,
            grid=grid,
            frame_times_ms=times,
            frame_evidence=frame,
            onset_evidence=onset,
            contour_evidence=contour,
        )
        return sidecar, candidates

    def test_diagnostic_is_sidecar_only_and_preserves_merge_lineage(self) -> None:
        sidecar, candidates = self._sidecar()
        self.assertFalse(sidecar.automatic_actions_enabled)
        self.assertEqual(sidecar.processed_candidate_count, 2)
        self.assertEqual(
            candidates,
            (
                _Candidate("a", 60, 0.0, 100.0, 0.8),
                _Candidate("b", 60, 110.0, 100.0, 0.3),
            ),
        )
        merge = next(
            item
            for item in sidecar.proposals
            if item.kind == "merge_same_pitch"
        )
        self.assertEqual(merge.decode_state, "MERGE_CONTINUATION")
        self.assertEqual(merge.lineage_ids, ("a", "b"))

    def test_sidecar_rejects_changed_candidate_revision_or_grid(self) -> None:
        sidecar, candidates = self._sidecar()
        self.assertTrue(
            sidecar.is_current(
                evidence_cache_key="a" * 64,
                candidates=candidates,
                grid=sidecar.grid,
            )
        )
        changed = (candidates[0], replace(candidates[1], duration_ms=120.0))
        self.assertFalse(
            sidecar.is_current(
                evidence_cache_key="a" * 64,
                candidates=changed,
                grid=sidecar.grid,
            )
        )
        different_grid = build_project_rhythm_grid(
            ProjectRhythmSettings(enabled=True, bpm=121.0)
        )
        assert different_grid is not None
        self.assertFalse(
            sidecar.is_current(
                evidence_cache_key="a" * 64,
                candidates=candidates,
                grid=different_grid,
            )
        )

    def test_cancellation_happens_before_evidence_work(self) -> None:
        candidates = (_Candidate("a", 60, 0.0, 100.0, 0.8),)
        times, frame, onset, contour = _evidence()
        grid = build_project_rhythm_grid(
            ProjectRhythmSettings(enabled=True, bpm=120.0)
        )
        assert grid is not None
        with self.assertRaises(RhythmDiagnosticCancelled):
            analyse_project_rhythm_diagnostics(
                evidence_cache_key="a" * 64,
                candidates=candidates,
                grid=grid,
                frame_times_ms=times,
                frame_evidence=frame,
                onset_evidence=onset,
                contour_evidence=contour,
                cancelled=lambda: True,
            )

    def test_proposal_and_sidecar_reject_unknown_lineage(self) -> None:
        sidecar, _candidates = self._sidecar()
        invalid = RhythmCleanupProposal(
            kind="suppress_extra",
            decode_state="SUPPRESS_EXTRA",
            source_candidate_ids=("missing",),
            confidence=0.9,
            reason_codes=("diagnostic",),
        )
        with self.assertRaises(ValueError):
            RhythmDiagnosticSidecar(
                identity=sidecar.identity,
                evidence_cache_key=sidecar.evidence_cache_key,
                candidate_revision=sidecar.candidate_revision,
                grid=sidecar.grid,
                features=sidecar.features,
                proposals=(invalid,),
                processed_candidate_count=len(sidecar.features),
                evidence_window_read_count=0,
            )

    def test_sidecar_rejects_tampered_identity(self) -> None:
        sidecar, _candidates = self._sidecar()
        with self.assertRaises(ValueError):
            replace(sidecar, identity="tampered")

    def test_chunk_size_is_fixed_and_small(self) -> None:
        self.assertEqual(RHYTHM_CANDIDATE_CHUNK_SIZE, 256)

    def test_continuation_chain_is_one_non_overlapping_proposal(self) -> None:
        times = np.arange(0.0, 610.0, 10.0, dtype=np.float64)
        frame = np.zeros((len(times), 88), dtype=np.float32)
        onset = np.zeros_like(frame)
        contour = np.zeros((len(times), 88 * 3), dtype=np.float32)
        frame[:, 60 - 21] = 0.8
        onset[0, 60 - 21] = 0.9
        onset[11, 60 - 21] = 0.2
        onset[25, 60 - 21] = 0.2
        contour[:, (60 - 21) * 3] = 0.7
        candidates = (
            _Candidate("a", 60, 0.0, 100.0, 0.8),
            _Candidate("b", 60, 110.0, 100.0, 0.3),
            _Candidate("c", 60, 245.0, 100.0, 0.3),
        )
        grid = build_project_rhythm_grid(
            ProjectRhythmSettings(enabled=True, bpm=120.0)
        )
        assert grid is not None
        sidecar = analyse_project_rhythm_diagnostics(
            evidence_cache_key="b" * 64,
            candidates=candidates,
            grid=grid,
            frame_times_ms=times,
            frame_evidence=frame,
            onset_evidence=onset,
            contour_evidence=contour,
        )
        merges = [
            proposal
            for proposal in sidecar.proposals
            if proposal.kind == "merge_same_pitch"
        ]
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0].lineage_ids, ("a", "b", "c"))
        self.assertAlmostEqual(merges[0].target_duration_ms or 0.0, 345.0)


class RhythmDecodeTests(unittest.TestCase):
    @staticmethod
    def _observation(
        candidate_id: str,
        previous_candidate_id: str | None,
        **changes: object,
    ) -> RhythmBoundaryObservation:
        values: dict[str, object] = {
            "candidate_id": candidate_id,
            "previous_candidate_id": previous_candidate_id,
            "candidate_confidence": 0.3,
            "duration_beats": 0.2,
            "grid_distance_beats": 0.0,
            "onset_support": 0.15,
            "boundary_continuity": 0.85,
            "contour_stability": 0.8,
            "chord_support": 0.0,
            "voice_continuity": 0.8,
            "inter_onset_fit": 0.8 if previous_candidate_id else 0.0,
            "gap_beats": 0.02 if previous_candidate_id else None,
            "regular_repeat": False,
        }
        values.update(changes)
        return RhythmBoundaryObservation(**values)  # type: ignore[arg-type]

    def test_decoder_selects_a_deterministic_continuation_path(self) -> None:
        observations = (
            self._observation(
                "a",
                None,
                candidate_confidence=0.8,
                onset_support=0.9,
            ),
            self._observation("b", "a"),
            self._observation("c", "b"),
        )
        first = decode_rhythm_boundaries(observations)
        second = decode_rhythm_boundaries(observations)
        self.assertEqual(first, second)
        self.assertEqual(
            tuple(decision.state for decision in first.decisions),
            ("KEEP_SINGLE", "MERGE_CONTINUATION", "MERGE_CONTINUATION"),
        )

    def test_strong_onset_protects_a_true_reattack(self) -> None:
        path = decode_rhythm_boundaries(
            (
                self._observation("a", None, onset_support=0.9),
                self._observation("b", "a", onset_support=0.9),
            )
        )
        self.assertEqual(path.decisions[-1].state, "KEEP_REATTACK")

    def test_chord_and_regular_repeat_context_block_merging(self) -> None:
        for protection in (
            {"chord_support": 1.0 / 3.0},
            {"regular_repeat": True},
        ):
            with self.subTest(protection=protection):
                path = decode_rhythm_boundaries(
                    (
                        self._observation("a", None, onset_support=0.9),
                        self._observation("b", "a", **protection),
                    )
                )
                self.assertEqual(
                    path.decisions[-1].state,
                    "KEEP_REATTACK",
                )

    def test_only_weak_short_off_grid_candidate_can_be_suppressed(self) -> None:
        path = decode_rhythm_boundaries(
            (
                self._observation(
                    "weak",
                    None,
                    candidate_confidence=0.1,
                    duration_beats=0.04,
                    grid_distance_beats=0.12,
                    onset_support=0.05,
                    boundary_continuity=0.1,
                    contour_stability=0.05,
                    voice_continuity=0.0,
                ),
            )
        )
        self.assertEqual(path.decisions[0].state, "SUPPRESS_EXTRA")

    def test_decoder_cancellation_is_bounded(self) -> None:
        with self.assertRaises(RhythmDecodeCancelled):
            decode_rhythm_boundaries(
                (self._observation("a", None),),
                cancelled=lambda: True,
            )


if __name__ == "__main__":
    unittest.main()
