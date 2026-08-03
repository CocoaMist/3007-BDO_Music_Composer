from __future__ import annotations

import copy
from contextlib import redirect_stderr
from dataclasses import replace
import io
import json
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

import numpy as np

from scripts.benchmark_babyslakh_transcription import (
    BABYSLAKH_ARCHIVE_BYTES,
    BABYSLAKH_ARCHIVE_MD5,
    CLEANUP_CHECKPOINT_DIRECTORY,
    EvaluationFrameNote,
    FROZEN_MIXED_ENHANCED_V2_CONFIG,
    FROZEN_V1_CLEANUP_CONFIG,
    FragmentCleanupEvidenceCase,
    FragmentCleanupSearchConfig,
    FragmentTrackEvaluation,
    HOLDOUT_TRACKS,
    MetricAccumulator,
    TUNING_TRACKS,
    WorkingSetSampler,
    _checkpointed_cleanup_evidence,
    _close_cleanup_evidence,
    _false_merge_count,
    _load_cleanup_evidence_checkpoint,
    _load_tuning_checkpoint,
    _metrics,
    _parse_args,
    _publish_cleanup_evidence_checkpoint,
    _raw_frame_events,
    _reference_frame_notes,
    _write_tuning_checkpoint,
    cleanup_holdout_report,
    evaluate_balanced_profile_gate,
    evaluate_fragment_cleanup_grid,
    fragment_cleanup_grid,
    fragment_evaluation_result_signature,
    fragment_track_metrics,
    frame_note_metrics,
    main as benchmark_main,
    search_grid,
    select_fragment_cleanup_config,
    summarize_cleanup_grid_with_metric_reuse,
    summarize_fragment_cleanup_tracks,
    write_cleanup_holdout_report,
)
from bdo_music_composer.transcription.bdo_transcription_postprocess import (
    FrameNoteEvent,
    V1_PARAMS,
    postprocess_frame_events,
)


class BabySlakhBenchmarkTests(unittest.TestCase):
    def test_dataset_identity_and_split_are_fixed(self) -> None:
        self.assertEqual(BABYSLAKH_ARCHIVE_BYTES, 882_883_087)
        self.assertEqual(
            BABYSLAKH_ARCHIVE_MD5,
            "ea1797fc57689a0e33c759c17a2292f5",
        )
        self.assertEqual(
            TUNING_TRACKS,
            tuple(f"Track{index:05d}" for index in range(1, 13)),
        )
        self.assertEqual(
            HOLDOUT_TRACKS,
            tuple(f"Track{index:05d}" for index in range(13, 21)),
        )
        self.assertTrue(set(TUNING_TRACKS).isdisjoint(HOLDOUT_TRACKS))

    def test_search_grid_is_complete_and_deterministic(self) -> None:
        first = search_grid()
        second = search_grid()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3**5)
        self.assertEqual(
            {config.frame_harmonic_weight for config in first},
            {0.55, 0.70, 0.85},
        )
        self.assertEqual(
            {config.onset_harmonic_weight for config in first},
            {0.25, 0.40, 0.55},
        )
        self.assertEqual(
            {config.onset_threshold for config in first},
            {0.45, 0.50, 0.55},
        )
        self.assertEqual(
            {config.frame_threshold for config in first},
            {0.25, 0.30, 0.35},
        )
        self.assertEqual(
            {config.min_note_len_frames for config in first},
            {5, 8, 11},
        )

    def test_fragment_cleanup_grid_is_closed_and_deterministic(self) -> None:
        first = fragment_cleanup_grid()
        self.assertEqual(first, fragment_cleanup_grid())
        self.assertEqual(len(first), 3 * 3 * 2 * 3 * 2)
        self.assertEqual(
            {config.max_merge_gap_frames for config in first},
            {0, 1, 2},
        )
        self.assertEqual(
            {config.nms_min_overlap_ratio for config in first},
            {0.80, 0.85, 0.90},
        )
        self.assertEqual(
            {config.nms_onset_distance_frames for config in first},
            {1, 2},
        )
        self.assertEqual(
            {config.max_weak_onset_prominence for config in first},
            {0.05, 0.10, 0.15},
        )
        self.assertEqual(
            {config.clean_max_confidence for config in first},
            {0.25, 0.30},
        )
        fixed = FragmentCleanupSearchConfig(
            max_merge_gap_frames=2,
            nms_min_overlap_ratio=0.85,
            nms_onset_distance_frames=2,
            max_weak_onset_prominence=0.10,
            clean_max_confidence=0.30,
        )
        self.assertIn(fixed, first)
        self.assertEqual(fixed.params(), V1_PARAMS)
        self.assertEqual(fixed, FROZEN_V1_CLEANUP_CONFIG)

    def test_cleanup_evidence_config_matches_published_v2(self) -> None:
        report_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "benchmarks"
            / "babyslakh_transcription_v2.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(
            report["selected_config"],
            {
                "frame_harmonic_weight": (
                    FROZEN_MIXED_ENHANCED_V2_CONFIG
                    .frame_harmonic_weight
                ),
                "onset_harmonic_weight": (
                    FROZEN_MIXED_ENHANCED_V2_CONFIG
                    .onset_harmonic_weight
                ),
                "onset_threshold": (
                    FROZEN_MIXED_ENHANCED_V2_CONFIG.onset_threshold
                ),
                "frame_threshold": (
                    FROZEN_MIXED_ENHANCED_V2_CONFIG.frame_threshold
                ),
                "min_note_len_frames": (
                    FROZEN_MIXED_ENHANCED_V2_CONFIG
                    .min_note_len_frames
                ),
            },
        )

    def test_tuning_checkpoint_round_trips_without_paths(self) -> None:
        configs = search_grid()
        accumulators = {
            config: MetricAccumulator(tracks=1)
            for config in configs
        }
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            _write_tuning_checkpoint(
                checkpoint,
                [TUNING_TRACKS[0]],
                accumulators,
            )
            completed, restored = _load_tuning_checkpoint(
                checkpoint,
                configs,
            )
            self.assertEqual(completed, [TUNING_TRACKS[0]])
            self.assertEqual(restored, accumulators)
            text = checkpoint.read_text(encoding="utf-8")
            self.assertNotIn(str(Path(directory)), text)

    def test_working_set_sampler_reports_process_memory(self) -> None:
        self.assertGreater(WorkingSetSampler.current_bytes(), 0)

    def test_pitch_partitioned_metrics_match_public_mir_eval(self) -> None:
        import mir_eval.transcription
        import pretty_midi

        reference_intervals = np.asarray(
            (
                (0.00, 0.50),
                (0.04, 0.62),
                (0.80, 1.20),
                (1.30, 1.75),
                (1.90, 2.20),
            ),
            dtype=np.float64,
        )
        reference_pitches = np.asarray(
            [
                pretty_midi.note_number_to_hz(pitch)
                for pitch in (60, 60, 64, 67, 72)
            ],
            dtype=np.float64,
        )
        estimated_intervals = np.asarray(
            (
                (0.02, 0.51),
                (0.07, 0.90),
                (0.79, 1.22),
                (1.36, 1.74),
                (1.88, 2.80),
                (2.50, 2.80),
            ),
            dtype=np.float64,
        )
        estimated_pitches = np.asarray(
            [
                pretty_midi.note_number_to_hz(pitch)
                for pitch in (60, 60, 64, 67, 72, 75)
            ],
            dtype=np.float64,
        )
        precision, recall, onset_offset_f1, _overlap = (
            mir_eval.transcription.precision_recall_f1_overlap(
                reference_intervals,
                reference_pitches,
                estimated_intervals,
                estimated_pitches,
            )
        )
        _onset_precision, _onset_recall, onset_f1, _overlap = (
            mir_eval.transcription.precision_recall_f1_overlap(
                reference_intervals,
                reference_pitches,
                estimated_intervals,
                estimated_pitches,
                offset_ratio=None,
            )
        )

        actual = _metrics(
            (reference_intervals, reference_pitches),
            (estimated_intervals, estimated_pitches),
        )

        self.assertAlmostEqual(actual["note_precision"], precision)
        self.assertAlmostEqual(actual["note_recall"], recall)
        self.assertAlmostEqual(actual["onset_f1"], onset_f1)
        self.assertAlmostEqual(
            actual["onset_offset_f1"],
            onset_offset_f1,
        )

    @staticmethod
    def _fragment_fixture() -> FragmentTrackEvaluation:
        reference = (
            EvaluationFrameNote(0, 20, 60),
            EvaluationFrameNote(30, 36, 62),
            EvaluationFrameNote(45, 53, 64),
            EvaluationFrameNote(60, 70, 65),
        )
        raw = (
            EvaluationFrameNote(0, 9, 60, ("a",)),
            EvaluationFrameNote(9, 20, 60, ("b",)),
            EvaluationFrameNote(30, 36, 62, ("c",)),
            EvaluationFrameNote(45, 53, 64, ("d",)),
            EvaluationFrameNote(60, 70, 65, ("e",)),
            EvaluationFrameNote(4, 8, 61, ("flicker",)),
        )
        processed = (
            EvaluationFrameNote(0, 20, 60, ("a", "b")),
            EvaluationFrameNote(30, 36, 62, ("c",)),
            EvaluationFrameNote(45, 53, 64, ("d",)),
            EvaluationFrameNote(60, 70, 65, ("e",)),
            EvaluationFrameNote(4, 8, 61, ("flicker",)),
        )
        return FragmentTrackEvaluation(
            track_id="TrackSynthetic",
            reference=reference,
            raw=raw,
            processed=processed,
            duration_seconds=60.0,
            total_decode_seconds=10.0,
            postprocess_seconds=0.1,
            clean_processed=processed,
            clean_total_decode_seconds=10.0,
            clean_postprocess_seconds=0.1,
        )

    def test_frame_metrics_report_fixed_short_note_strata(self) -> None:
        fixture = self._fragment_fixture()
        metrics = frame_note_metrics(fixture.reference, fixture.raw)
        self.assertEqual(metrics["short_le_6_reference_count"], 1)
        self.assertEqual(metrics["short_le_8_reference_count"], 2)
        self.assertEqual(metrics["short_9_11_reference_count"], 1)
        self.assertEqual(metrics["short_le_6_estimated_count"], 2)
        self.assertEqual(metrics["short_le_8_estimated_count"], 3)
        self.assertEqual(metrics["short_9_11_estimated_count"], 3)
        self.assertAlmostEqual(metrics["short_le_6_precision"], 0.5)
        self.assertAlmostEqual(metrics["short_le_8_recall"], 1.0)
        self.assertAlmostEqual(metrics["short_9_11_recall"], 1.0)

    def test_fragment_metrics_cover_boundaries_flicker_and_inflation(
        self,
    ) -> None:
        result = fragment_track_metrics(self._fragment_fixture())
        baseline = result["baseline"]
        balanced = result["balanced"]
        self.assertEqual(baseline["fragment_count"], 1)
        self.assertEqual(baseline["split_reference_count"], 1)
        self.assertEqual(
            baseline["unsupported_fragment_boundary_count"],
            1,
        )
        self.assertEqual(baseline["pitch_flicker_count"], 1)
        self.assertAlmostEqual(
            baseline["candidate_inflation_ratio"],
            1.5,
        )
        self.assertEqual(balanced["fragment_count"], 0)
        self.assertEqual(balanced["false_merge_count"], 0)
        self.assertAlmostEqual(
            result["deltas"]["fragmentation_reduction"],
            1.0,
        )
        self.assertAlmostEqual(
            result["deltas"]["candidate_count_change_rate"],
            -1.0 / 6.0,
        )

    def test_false_merge_requires_two_supported_true_onsets(self) -> None:
        reference = (
            EvaluationFrameNote(0, 6, 60),
            EvaluationFrameNote(8, 14, 60),
        )
        raw = (
            EvaluationFrameNote(0, 6, 60, ("left",)),
            EvaluationFrameNote(8, 14, 60, ("right",)),
        )
        merged = (
            EvaluationFrameNote(0, 14, 60, ("left", "right")),
        )
        self.assertEqual(_false_merge_count(reference, raw, merged), 1)
        self.assertEqual(
            _false_merge_count(
                reference[:1],
                raw[:1],
                (
                    EvaluationFrameNote(
                        0,
                        6,
                        60,
                        ("left", "duplicate"),
                    ),
                ),
            ),
            0,
        )

    def test_balanced_gate_uses_every_frozen_threshold(self) -> None:
        baseline = {
            "note_precision": 0.20,
            "note_recall": 0.30,
            "onset_f1": 0.40,
            "onset_offset_f1": 0.25,
            "short_le_8_recall": 0.50,
        }
        balanced = {
            "note_precision": 0.205,
            "note_recall": 0.295,
            "onset_f1": 0.397,
            "onset_offset_f1": 0.248,
            "short_le_8_recall": 0.49,
        }
        passing = evaluate_balanced_profile_gate(
            baseline,
            balanced,
            fragmentation_reduction=0.20,
            false_merge_count=5,
            reference_note_count=1000,
            worst_song_onset_f1_delta=-0.02,
            postprocess_share=0.049,
        )
        self.assertTrue(passing["passed"])
        failing = evaluate_balanced_profile_gate(
            baseline,
            balanced,
            fragmentation_reduction=0.20,
            false_merge_count=5,
            reference_note_count=1000,
            worst_song_onset_f1_delta=-0.02,
            postprocess_share=0.05,
        )
        self.assertFalse(failing["passed"])
        self.assertFalse(
            failing["checks"]["postprocess_share_below_0_05"]
        )

    def test_holdout_summary_tracks_worst_song_and_timing(self) -> None:
        fixture = self._fragment_fixture()
        summary = summarize_fragment_cleanup_tracks((fixture,))
        self.assertEqual(
            summary["per_song_worst"]["track_id"],
            "TrackSynthetic",
        )
        self.assertAlmostEqual(
            summary["timing"]["postprocess_share"],
            0.01,
        )
        self.assertEqual(
            summary["per_song_worst"]["metrics"][
                "note_precision_delta"
            ]["track_id"],
            "TrackSynthetic",
        )
        self.assertTrue(summary["quality_gate"]["passed"])

    def test_metric_results_are_reused_by_musical_signature(self) -> None:
        first, second = fragment_cleanup_grid()[:2]
        evaluation = self._fragment_fixture()
        slower = replace(
            evaluation,
            total_decode_seconds=20.0,
            postprocess_seconds=0.2,
        )
        self.assertEqual(
            fragment_evaluation_result_signature(evaluation),
            fragment_evaluation_result_signature(slower),
        )
        changed = replace(
            evaluation,
            processed=evaluation.processed[:-1],
        )
        self.assertNotEqual(
            fragment_evaluation_result_signature(evaluation),
            fragment_evaluation_result_signature(changed),
        )
        with patch(
            "scripts.benchmark_babyslakh_transcription."
            "fragment_track_metrics",
            wraps=fragment_track_metrics,
        ) as metrics:
            reports, reuse = summarize_cleanup_grid_with_metric_reuse(
                {
                    first: [evaluation],
                    second: [slower],
                }
            )
        self.assertEqual(metrics.call_count, 1)
        self.assertEqual(
            reuse,
            {
                "grid_track_evaluation_count": 2,
                "unique_result_signature_count": 1,
                "reused_metric_evaluation_count": 1,
            },
        )
        self.assertAlmostEqual(
            reports[first]["timing"]["postprocess_share"],
            0.01,
        )
        self.assertAlmostEqual(
            reports[second]["timing"]["postprocess_share"],
            0.01,
        )

    def test_grid_selection_uses_frozen_metric_priority(self) -> None:
        first, second = fragment_cleanup_grid()[:2]

        def report(
            config: FragmentCleanupSearchConfig,
            *,
            reduction: float,
            precision: float,
            onset_offset_f1: float,
            passed: bool = True,
        ) -> tuple[FragmentCleanupSearchConfig, dict[str, object]]:
            return config, {
                "deltas": {
                    "fragmentation_reduction": reduction,
                },
                "balanced": {
                    "note_precision": precision,
                    "onset_offset_f1": onset_offset_f1,
                },
                "clean": {
                    "note_precision": precision,
                    "onset_offset_f1": onset_offset_f1,
                },
                "quality_gate": {"passed": passed},
                "clean_safety_gate": {"passed": passed},
            }

        reports = dict(
            (
                report(
                    first,
                    reduction=0.30,
                    precision=0.30,
                    onset_offset_f1=0.30,
                ),
                report(
                    second,
                    reduction=0.40,
                    precision=0.20,
                    onset_offset_f1=0.20,
                ),
            )
        )
        self.assertEqual(
            select_fragment_cleanup_config(reports),
            second,
        )
        reports[first]["deltas"]["fragmentation_reduction"] = 0.40
        reports[first]["balanced"]["note_precision"] = 0.21
        self.assertEqual(
            select_fragment_cleanup_config(reports),
            first,
        )
        reports[first]["balanced"]["note_precision"] = 0.20
        reports[first]["balanced"]["onset_offset_f1"] = 0.20
        self.assertEqual(
            select_fragment_cleanup_config(reports),
            first,
        )
        reports[first]["quality_gate"]["passed"] = False
        reports[second]["quality_gate"]["passed"] = False
        self.assertIsNone(select_fragment_cleanup_config(reports))

    def test_grid_evaluation_runs_postprocessor_on_shared_evidence(
        self,
    ) -> None:
        frame = np.zeros((24, 88), dtype=np.float32)
        onset = np.zeros_like(frame)
        column = 60 - 21
        frame[:20, column] = 0.8
        onset[0, column] = 0.8
        case = FragmentCleanupEvidenceCase(
            track_id="TrackGrid",
            reference=(EvaluationFrameNote(0, 20, 60),),
            raw_events=(
                FrameNoteEvent(0, 8, 60, 0.8, ("left",)),
                FrameNoteEvent(8, 20, 60, 0.7, ("right",)),
            ),
            frame_evidence=frame,
            onset_evidence=onset,
            duration_seconds=1.0,
            total_decode_seconds=100.0,
            onset_threshold=0.5,
            frame_threshold=0.3,
        )
        config = fragment_cleanup_grid()[0]
        with patch(
            (
                "scripts.benchmark_babyslakh_transcription."
                "postprocess_frame_events"
            ),
            wraps=postprocess_frame_events,
        ) as mocked_postprocess:
            reports = evaluate_fragment_cleanup_grid(
                (case,),
                configs=(config,),
            )
        self.assertEqual(set(reports), {config})
        self.assertEqual(len(mocked_postprocess.call_args_list), 3)
        self.assertEqual(
            reports[config]["balanced"]["fragment_count"],
            0,
        )
        self.assertEqual(
            select_fragment_cleanup_config(reports),
            config,
        )

    def test_clean_confidence_dimension_changes_clean_not_balanced(
        self,
    ) -> None:
        low, high = fragment_cleanup_grid()[:2]
        self.assertEqual(low.clean_max_confidence, 0.25)
        self.assertEqual(high.clean_max_confidence, 0.30)
        frame = np.zeros((12, 88), dtype=np.float32)
        onset = np.zeros_like(frame)
        column = 60 - 21
        frame[2:6, column] = 0.10
        onset[2, column] = 0.01
        case = FragmentCleanupEvidenceCase(
            track_id="TrackCleanThreshold",
            reference=(EvaluationFrameNote(2, 6, 60),),
            raw_events=(
                FrameNoteEvent(2, 6, 60, 0.27, ("weak",)),
            ),
            frame_evidence=frame,
            onset_evidence=onset,
            duration_seconds=1.0,
            total_decode_seconds=100.0,
            onset_threshold=0.5,
            frame_threshold=0.3,
        )
        reports = evaluate_fragment_cleanup_grid(
            (case,),
            configs=(low, high),
        )
        self.assertEqual(
            reports[low]["balanced"]["candidate_count"],
            reports[high]["balanced"]["candidate_count"],
        )
        self.assertEqual(reports[low]["clean"]["candidate_count"], 1)
        self.assertEqual(reports[high]["clean"]["candidate_count"], 0)
        self.assertTrue(
            reports[low]["clean_safety_gate"]["passed"]
        )
        self.assertFalse(
            reports[high]["clean_safety_gate"]["passed"]
        )
        self.assertFalse(
            reports[high]["selection_gate"]["clean_safety_passed"]
        )

    def test_clean_metrics_break_balanced_selection_ties(self) -> None:
        low, high = fragment_cleanup_grid()[:2]

        def report(clean_precision: float) -> dict[str, object]:
            return {
                "deltas": {"fragmentation_reduction": 0.30},
                "balanced": {
                    "note_precision": 0.30,
                    "onset_offset_f1": 0.25,
                },
                "clean": {
                    "note_precision": clean_precision,
                    "onset_offset_f1": 0.24,
                },
                "quality_gate": {"passed": True},
                "clean_safety_gate": {"passed": True},
                "selection_gate": {"passed": True},
            }

        self.assertEqual(
            select_fragment_cleanup_config(
                {
                    low: report(0.31),
                    high: report(0.32),
                }
            ),
            high,
        )

    def test_raw_frame_decode_is_stable_and_keeps_duplicate_lineage(
        self,
    ) -> None:
        class NoteCreation:
            @staticmethod
            def output_to_notes_polyphonic(
                frame,
                onset,
                **kwargs,
            ):
                self.assertEqual(frame.dtype, np.float32)
                self.assertEqual(onset.dtype, np.float32)
                self.assertEqual(kwargs["onset_thresh"], 0.55)
                return (
                    (1, 5, 60, 0.4),
                    (1, 5, 60, 0.4),
                )

        evidence = {
            "note": np.zeros((8, 88), dtype=np.float16),
            "onset": np.zeros((8, 88), dtype=np.float16),
        }
        events = _raw_frame_events(
            evidence,
            NoteCreation(),
            FROZEN_MIXED_ENHANCED_V2_CONFIG,
        )
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0].lineage, events[1].lineage)
        self.assertEqual(
            events,
            _raw_frame_events(
                evidence,
                NoteCreation(),
                FROZEN_MIXED_ENHANCED_V2_CONFIG,
            ),
        )

    def test_reference_midi_uses_supplied_frame_axis(self) -> None:
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(initial_tempo=120)
        instrument = pretty_midi.Instrument(program=0)
        instrument.notes.append(
            pretty_midi.Note(
                velocity=100,
                pitch=60,
                start=0.020,
                end=0.080,
            )
        )
        midi.instruments.append(instrument)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truth.mid"
            midi.write(str(path))
            notes = _reference_frame_notes(
                path,
                np.asarray((0.0, 25.0, 50.0, 75.0, 100.0)),
            )
        self.assertEqual(
            notes,
            (EvaluationFrameNote(1, 4, 60),),
        )

    def test_cleanup_report_is_path_free_and_explicitly_experimental(
        self,
    ) -> None:
        config = fragment_cleanup_grid()[0]
        summary = summarize_fragment_cleanup_tracks(
            (self._fragment_fixture(),)
        )
        passing = cleanup_holdout_report({config: summary})
        self.assertEqual(passing["report_schema_version"], 4)
        self.assertEqual(
            passing["production_release_mode"],
            "explicit_opt_in_experimental",
        )
        self.assertTrue(passing["automatic_actions_evaluated"])
        self.assertEqual(
            passing["execution_policy"],
            {
                "safe_default_profile": "preserve",
                "experimental_profiles": ["balanced", "clean"],
                "requires_explicit_user_opt_in": True,
                (
                    "automatic_actions_enabled_for_"
                    "experimental_profiles"
                ): True,
                "holdout_release_gate_passed": True,
            },
        )
        self.assertEqual(passing["selected_config"], {
            "max_merge_gap_frames": config.max_merge_gap_frames,
            "nms_min_overlap_ratio": config.nms_min_overlap_ratio,
            "nms_onset_distance_frames": (
                config.nms_onset_distance_frames
            ),
            "max_weak_onset_prominence": (
                config.max_weak_onset_prominence
            ),
            "clean_max_confidence": config.clean_max_confidence,
        })
        self.assertFalse(passing["annotation_only"])
        self.assertTrue(passing["grid_recommendation_only"])
        self.assertNotIn("recommendation_only", passing)
        self.assertEqual(
            passing["active_experimental_config"],
            passing["fixed_v1_config"],
        )
        self.assertIsNotNone(
            passing["grid_results"][0]["clean"]
        )
        self.assertTrue(
            passing["grid_results"][0]["clean_safety_gate"]["passed"]
        )
        self.assertTrue(
            passing["grid_results"][0]["selection_gate"]["passed"]
        )
        failing_summary = copy.deepcopy(summary)
        failing_summary["quality_gate"]["passed"] = False
        failing_summary["selection_gate"]["passed"] = False
        failing_summary["selection_gate"][
            "balanced_quality_passed"
        ] = False
        failing = cleanup_holdout_report(
            {config: failing_summary},
        )
        self.assertIsNone(failing["selected_config"])
        self.assertFalse(failing["annotation_only"])
        self.assertFalse(
            failing["execution_policy"]["holdout_release_gate_passed"]
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cleanup-v4.json"
            write_cleanup_holdout_report(output, failing)
            text = output.read_text(encoding="utf-8")
            restored = json.loads(text)
            self.assertNotIn(str(Path(directory)), text)
            self.assertEqual(restored, failing)

    def test_cleanup_evidence_checkpoint_round_trips_without_paths(
        self,
    ) -> None:
        track_id = HOLDOUT_TRACKS[0]
        fingerprint = "a" * 64
        cache_key = "b" * 24
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            frame_path = source / "evidence-note.npy"
            onset_path = source / "evidence-onset.npy"
            frame = np.lib.format.open_memmap(
                frame_path,
                mode="w+",
                dtype=np.dtype("<f2"),
                shape=(4, 88),
            )
            onset = np.lib.format.open_memmap(
                onset_path,
                mode="w+",
                dtype=np.dtype("<f2"),
                shape=(4, 88),
            )
            frame[:] = 0.25
            onset[:] = 0.5
            frame.flush()
            onset.flush()
            del frame, onset
            checkpoint_root = root / CLEANUP_CHECKPOINT_DIRECTORY
            _publish_cleanup_evidence_checkpoint(
                checkpoint_root,
                track_id,
                frame_source=frame_path,
                onset_source=onset_path,
                times_ms=np.asarray(
                    (0.0, 10.0, 20.0, 30.0),
                    dtype=np.float64,
                ),
                duration_seconds=0.04,
                audio_fingerprint=fingerprint,
                evidence_cache_key=cache_key,
            )
            manifest_path = (
                checkpoint_root / track_id / "manifest.json"
            )
            manifest_text = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn(str(root), manifest_text)
            loaded = _load_cleanup_evidence_checkpoint(
                checkpoint_root,
                track_id,
                audio_fingerprint=fingerprint,
                evidence_cache_key=cache_key,
            )
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.frame.shape, (4, 88))
            self.assertTrue(np.allclose(loaded.onset, 0.5))
            _close_cleanup_evidence(loaded)

            with (checkpoint_root / track_id / "frame.npy").open(
                "r+b"
            ) as stream:
                stream.seek(-1, 2)
                byte = stream.read(1)
                stream.seek(-1, 2)
                stream.write(bytes((byte[0] ^ 0x01,)))
            self.assertIsNone(
                _load_cleanup_evidence_checkpoint(
                    checkpoint_root,
                    track_id,
                    audio_fingerprint=fingerprint,
                    evidence_cache_key=cache_key,
                )
            )

    def test_completed_checkpoint_skips_model_and_onnx_track_run(
        self,
    ) -> None:
        track_id = HOLDOUT_TRACKS[0]
        fingerprint = "c" * 64
        cache_key = "d" * 24
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            frame_path = source / "evidence-note.npy"
            onset_path = source / "evidence-onset.npy"
            for path in (frame_path, onset_path):
                array = np.lib.format.open_memmap(
                    path,
                    mode="w+",
                    dtype=np.dtype("<f2"),
                    shape=(3, 88),
                )
                array[:] = 0.1
                array.flush()
                del array
            _publish_cleanup_evidence_checkpoint(
                root / CLEANUP_CHECKPOINT_DIRECTORY,
                track_id,
                frame_source=frame_path,
                onset_source=onset_path,
                times_ms=np.asarray((0.0, 10.0, 20.0)),
                duration_seconds=0.03,
                audio_fingerprint=fingerprint,
                evidence_cache_key=cache_key,
            )
            with (
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "transcription_audio_fingerprint",
                    return_value=fingerprint,
                ),
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "transcription_cache_key",
                    return_value=cache_key,
                ),
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "_run_streamed_analysis"
                ) as inference_run,
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "_onnx_model"
                ) as model_run,
            ):
                with _checkpointed_cleanup_evidence(
                    root / "audio.flac",
                    track_id,
                    model_provider=model_run,
                    inference=object(),
                    note_creation=object(),
                    work_root=root,
                ) as (evidence, runtime):
                    self.assertEqual(
                        runtime["evidence_source"],
                        "checkpoint",
                    )
                    self.assertEqual(evidence.frame_count, 3)
            inference_run.assert_not_called()
            model_run.assert_not_called()

    def test_cleanup_cli_requires_explicit_mode_and_output(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                _parse_args(["--cleanup-holdout"])
            with self.assertRaises(SystemExit):
                _parse_args(["--cleanup-output", "report.json"])
        args = _parse_args(
            [
                "--cleanup-holdout",
                "--cleanup-output",
                "report.json",
            ]
        )
        self.assertTrue(args.cleanup_holdout)
        self.assertEqual(args.cleanup_output, Path("report.json"))

    def test_cleanup_cli_dispatches_without_running_fusion_search(
        self,
    ) -> None:
        config = fragment_cleanup_grid()[0]
        summary = summarize_fragment_cleanup_tracks(
            (self._fragment_fixture(),)
        )
        report = cleanup_holdout_report({config: summary})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "cleanup-v3.json"
            with (
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "download_dataset",
                    return_value=root / "dataset",
                ),
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "run_cleanup_holdout",
                    return_value=report,
                ) as cleanup_run,
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "run_benchmark"
                ) as fusion_run,
                patch(
                    "scripts.benchmark_babyslakh_transcription."
                    "_progress"
                ),
                patch(
                    "sys.argv",
                    [
                        "benchmark",
                        "--cleanup-holdout",
                        "--cleanup-output",
                        str(output),
                    ],
                ),
            ):
                self.assertEqual(benchmark_main(), 0)
            cleanup_run.assert_called_once()
            fusion_run.assert_not_called()
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                report,
            )


if __name__ == "__main__":
    unittest.main()
