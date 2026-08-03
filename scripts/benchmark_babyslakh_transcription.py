"""Tune and validate mixed-audio transcription on BabySlakh.

BabySlakh is a development-only CC BY 4.0 dataset. This script downloads it
to the user's writable cache, never to the repository or application bundle.
The generated JSON contains public track IDs and aggregate metrics only.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request, urlopen
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_music_composer.core.project_paths import USER_DATA_DIR  # noqa: E402
from bdo_music_composer.transcription.bdo_transcription import (  # noqa: E402
    HPSS_BLOCK_SECONDS,
    HPSS_HOP_LENGTH,
    HPSS_KERNEL_SIZE,
    HPSS_MARGIN,
    HPSS_N_FFT,
    HPSS_OVERLAP_SECONDS,
    HPSS_POWER,
    MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT,
    STANDARD_ANALYSIS_MODE,
    MIXED_ENHANCED_ANALYSIS_MODE,
    TRANSCRIPTION_FUSION_VERSION,
    TRANSCRIPTION_EVIDENCE_DTYPE,
    TRANSCRIPTION_NOTE_BINS,
    TRANSCRIPTION_TIME_DTYPE,
    TranscriptionResult,
    _candidates_from_basic_pitch,
    _close_memmap,
    _fast_harmonic_separator,
    _import_basic_pitch,
    _import_basic_pitch_note_creation,
    _onnx_model,
    _predict_basic_pitch_windows,
    _run_streamed_analysis,
    _signal_audio_input,
    _transcription_workspace,
    _write_cached_result,
    basic_pitch_frame_times_ms,
    blockwise_harmonic_signal,
    transcription_audio_fingerprint,
    transcription_cache_key,
)
from bdo_music_composer.transcription.bdo_transcription_postprocess import (  # noqa: E402
    BALANCED_CLEANUP_PROFILE,
    CLEAN_CLEANUP_PROFILE,
    FragmentCleanupParams,
    FrameNoteEvent,
    POSTPROCESS_VERSION,
    PRESERVE_CLEANUP_PROFILE,
    V1_PARAMS,
    postprocess_frame_events,
)


BABYSLAKH_RECORD = "https://zenodo.org/records/4603844"
BABYSLAKH_DOWNLOAD_URL = (
    "https://zenodo.org/api/records/4603844/files/"
    "babyslakh_16k.zip/content"
)
BABYSLAKH_ARCHIVE_NAME = "babyslakh_16k.zip"
BABYSLAKH_ARCHIVE_BYTES = 882_883_087
BABYSLAKH_ARCHIVE_MD5 = "ea1797fc57689a0e33c759c17a2292f5"
BABYSLAKH_LICENSE = "CC BY 4.0"
TUNING_TRACKS = tuple(f"Track{index:05d}" for index in range(1, 13))
HOLDOUT_TRACKS = tuple(f"Track{index:05d}" for index in range(13, 21))

FRAGMENT_ONSET_TOLERANCE_FRAMES = 4
FRAGMENT_OFFSET_MIN_TOLERANCE_FRAMES = 4
FRAGMENT_OFFSET_TOLERANCE_RATIO = 0.20
FRAGMENT_SEVERE_MAX_FRAMES = 6
FRAGMENT_REVIEW_MAX_FRAMES = 8
FRAGMENT_DENSITY_MIN_FRAMES = 9
FRAGMENT_DENSITY_MAX_FRAMES = 11
CLEANUP_CHECKPOINT_SCHEMA_VERSION = 1
CLEANUP_CHECKPOINT_DIRECTORY = "cleanup-evidence-v1"


@dataclass(frozen=True, order=True)
class SearchConfig:
    frame_harmonic_weight: float
    onset_harmonic_weight: float
    onset_threshold: float
    frame_threshold: float
    min_note_len_frames: int


FROZEN_MIXED_ENHANCED_V2_CONFIG = SearchConfig(
    frame_harmonic_weight=0.55,
    onset_harmonic_weight=0.25,
    onset_threshold=0.55,
    frame_threshold=0.25,
    min_note_len_frames=5,
)


@dataclass(frozen=True, order=True)
class FragmentCleanupSearchConfig:
    """One member of the closed fragment-cleanup parameter grid."""

    max_merge_gap_frames: int
    nms_min_overlap_ratio: float
    nms_onset_distance_frames: int
    max_weak_onset_prominence: float
    clean_max_confidence: float

    def params(self) -> FragmentCleanupParams:
        return replace(
            V1_PARAMS,
            max_merge_gap_frames=self.max_merge_gap_frames,
            nms_min_overlap_ratio=self.nms_min_overlap_ratio,
            nms_onset_distance_frames=self.nms_onset_distance_frames,
            max_weak_onset_prominence=(
                self.max_weak_onset_prominence
            ),
            clean_max_confidence=self.clean_max_confidence,
        )


FROZEN_V1_CLEANUP_CONFIG = FragmentCleanupSearchConfig(
    max_merge_gap_frames=V1_PARAMS.max_merge_gap_frames,
    nms_min_overlap_ratio=V1_PARAMS.nms_min_overlap_ratio,
    nms_onset_distance_frames=V1_PARAMS.nms_onset_distance_frames,
    max_weak_onset_prominence=V1_PARAMS.max_weak_onset_prominence,
    clean_max_confidence=V1_PARAMS.clean_max_confidence,
)


@dataclass(frozen=True, order=True)
class EvaluationFrameNote:
    """Minimal, confidence-free note used by deterministic frame metrics."""

    start_frame: int
    end_frame: int
    pitch: int
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_frame, bool)
            or isinstance(self.end_frame, bool)
            or isinstance(self.pitch, bool)
            or not isinstance(self.start_frame, int)
            or not isinstance(self.end_frame, int)
            or not isinstance(self.pitch, int)
            or self.start_frame < 0
            or self.end_frame <= self.start_frame
            or not 0 <= self.pitch <= 127
        ):
            raise ValueError("invalid evaluation frame note")
        object.__setattr__(
            self,
            "lineage",
            tuple(sorted({str(value) for value in self.lineage if value})),
        )

    @property
    def span_frames(self) -> int:
        return self.end_frame - self.start_frame


@dataclass(frozen=True)
class FragmentTrackEvaluation:
    """Raw and balanced events for one held-out song."""

    track_id: str
    reference: tuple[EvaluationFrameNote, ...]
    raw: tuple[EvaluationFrameNote, ...]
    processed: tuple[EvaluationFrameNote, ...]
    duration_seconds: float
    total_decode_seconds: float
    postprocess_seconds: float
    clean_processed: tuple[EvaluationFrameNote, ...] | None = None
    clean_total_decode_seconds: float | None = None
    clean_postprocess_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.track_id:
            raise ValueError("track_id is required")
        for name in (
            "duration_seconds",
            "total_decode_seconds",
            "postprocess_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        clean_times = (
            self.clean_total_decode_seconds,
            self.clean_postprocess_seconds,
        )
        if self.clean_processed is None:
            if any(value is not None for value in clean_times):
                raise ValueError(
                    "clean timing requires clean processed notes"
                )
        elif any(value is None for value in clean_times):
            raise ValueError(
                "clean processed notes require clean timing"
            )
        else:
            for name, value in zip(
                (
                    "clean_total_decode_seconds",
                    "clean_postprocess_seconds",
                ),
                clean_times,
            ):
                numeric = float(value)
                if not math.isfinite(numeric) or numeric < 0.0:
                    raise ValueError(
                        f"{name} must be finite and non-negative"
                    )


@dataclass(frozen=True)
class FragmentCleanupEvidenceCase:
    """Evidence-backed case used to evaluate every closed-grid member."""

    track_id: str
    reference: tuple[EvaluationFrameNote, ...]
    raw_events: tuple[FrameNoteEvent, ...]
    frame_evidence: np.ndarray
    onset_evidence: np.ndarray
    duration_seconds: float
    total_decode_seconds: float
    onset_threshold: float
    frame_threshold: float
    midi_min: int = 21


@dataclass(frozen=True)
class CleanupEvidenceData:
    frame: np.ndarray
    onset: np.ndarray
    times_ms: np.ndarray
    duration_seconds: float
    frame_count: int


@dataclass
class MetricAccumulator:
    note_precision: float = 0.0
    note_recall: float = 0.0
    onset_f1: float = 0.0
    onset_offset_f1: float = 0.0
    tracks: int = 0

    def add(self, values: dict[str, float]) -> None:
        self.note_precision += values["note_precision"]
        self.note_recall += values["note_recall"]
        self.onset_f1 += values["onset_f1"]
        self.onset_offset_f1 += values["onset_offset_f1"]
        self.tracks += 1

    def means(self) -> dict[str, float]:
        count = max(1, self.tracks)
        return {
            "note_precision": self.note_precision / count,
            "note_recall": self.note_recall / count,
            "onset_f1": self.onset_f1 / count,
            "onset_offset_f1": self.onset_offset_f1 / count,
        }


class WorkingSetSampler:
    """Sample current resident memory during one pre-warmed measurement."""

    def __init__(self) -> None:
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def current_bytes() -> int:
        if sys.platform != "win32":
            try:
                import resource

                peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                return peak * (1 if sys.platform == "darwin" else 1024)
            except (ImportError, OSError):
                return 0
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCountersEx),
            wintypes.DWORD,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        handle = kernel32.GetCurrentProcess()
        if not kernel32.K32GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        ):
            return 0
        return int(counters.WorkingSetSize)

    def __enter__(self) -> "WorkingSetSampler":
        self.peak_bytes = self.current_bytes()

        def sample() -> None:
            while not self._stop.wait(0.05):
                self.peak_bytes = max(
                    self.peak_bytes,
                    self.current_bytes(),
                )

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.peak_bytes = max(self.peak_bytes, self.current_bytes())


def search_grid() -> tuple[SearchConfig, ...]:
    return tuple(
        SearchConfig(*values)
        for values in itertools.product(
            (0.55, 0.70, 0.85),
            (0.25, 0.40, 0.55),
            (0.45, 0.50, 0.55),
            (0.25, 0.30, 0.35),
            (5, 8, 11),
        )
    )


def fragment_cleanup_grid() -> tuple[FragmentCleanupSearchConfig, ...]:
    """Return the complete 108-member grid in its fixed tie-break order."""

    return tuple(
        FragmentCleanupSearchConfig(*values)
        for values in itertools.product(
            (0, 1, 2),
            (0.80, 0.85, 0.90),
            (1, 2),
            (0.05, 0.10, 0.15),
            (0.25, 0.30),
        )
    )


def evaluation_note_from_event(
    event: FrameNoteEvent,
) -> EvaluationFrameNote:
    return EvaluationFrameNote(
        int(event.start_frame),
        int(event.end_frame),
        int(event.pitch),
        tuple(event.lineage),
    )


def _frame_match_pairs(
    reference: tuple[EvaluationFrameNote, ...],
    estimated: tuple[EvaluationFrameNote, ...],
    *,
    include_offset: bool,
    onset_tolerance_frames: int = FRAGMENT_ONSET_TOLERANCE_FRAMES,
) -> tuple[tuple[int, int], ...]:
    """Match exact-pitch notes with mir_eval's deterministic assignment."""

    if not reference or not estimated:
        return ()
    import mir_eval.transcription

    matches: list[tuple[int, int]] = []
    reference_by_pitch: dict[int, list[int]] = {}
    estimated_by_pitch: dict[int, list[int]] = {}
    for index, note in enumerate(reference):
        reference_by_pitch.setdefault(note.pitch, []).append(index)
    for index, note in enumerate(estimated):
        estimated_by_pitch.setdefault(note.pitch, []).append(index)
    for pitch in sorted(set(reference_by_pitch) & set(estimated_by_pitch)):
        ref_indexes = reference_by_pitch[pitch]
        est_indexes = estimated_by_pitch[pitch]
        ref_intervals = np.asarray(
            [
                (
                    reference[index].start_frame,
                    reference[index].end_frame,
                )
                for index in ref_indexes
            ],
            dtype=np.float64,
        )
        est_intervals = np.asarray(
            [
                (
                    estimated[index].start_frame,
                    estimated[index].end_frame,
                )
                for index in est_indexes
            ],
            dtype=np.float64,
        )
        frequency = 440.0 * 2.0 ** ((float(pitch) - 69.0) / 12.0)
        ref_pitches = np.full(len(ref_indexes), frequency, dtype=np.float64)
        est_pitches = np.full(len(est_indexes), frequency, dtype=np.float64)
        pitch_matches = mir_eval.transcription.match_notes(
            ref_intervals,
            ref_pitches,
            est_intervals,
            est_pitches,
            onset_tolerance=float(onset_tolerance_frames),
            offset_ratio=(
                FRAGMENT_OFFSET_TOLERANCE_RATIO
                if include_offset
                else None
            ),
            offset_min_tolerance=float(
                FRAGMENT_OFFSET_MIN_TOLERANCE_FRAMES
            ),
        )
        matches.extend(
            (ref_indexes[int(ref_index)], est_indexes[int(est_index)])
            for ref_index, est_index in pitch_matches
        )
    return tuple(sorted(matches))


def _precision_recall_f1(
    matched: int,
    estimated_count: int,
    reference_count: int,
) -> tuple[float, float, float]:
    precision = float(matched) / max(1, int(estimated_count))
    recall = float(matched) / max(1, int(reference_count))
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return precision, recall, f1


def _short_bucket_metrics(
    reference: tuple[EvaluationFrameNote, ...],
    estimated: tuple[EvaluationFrameNote, ...],
    matches: tuple[tuple[int, int], ...],
) -> dict[str, float | int]:
    buckets = {
        "short_le_6": (
            lambda note: note.span_frames <= FRAGMENT_SEVERE_MAX_FRAMES
        ),
        "short_le_8": (
            lambda note: note.span_frames <= FRAGMENT_REVIEW_MAX_FRAMES
        ),
        "short_9_11": (
            lambda note: (
                FRAGMENT_DENSITY_MIN_FRAMES
                <= note.span_frames
                <= FRAGMENT_DENSITY_MAX_FRAMES
            )
        ),
    }
    output: dict[str, float | int] = {}
    for name, predicate in buckets.items():
        ref_indexes = {
            index
            for index, note in enumerate(reference)
            if predicate(note)
        }
        est_indexes = {
            index
            for index, note in enumerate(estimated)
            if predicate(note)
        }
        matched_ref = sum(
            ref_index in ref_indexes
            for ref_index, _est_index in matches
        )
        matched_est = sum(
            est_index in est_indexes
            for _ref_index, est_index in matches
        )
        output[f"{name}_reference_count"] = len(ref_indexes)
        output[f"{name}_estimated_count"] = len(est_indexes)
        output[f"{name}_matched_reference_count"] = matched_ref
        output[f"{name}_matched_estimated_count"] = matched_est
        output[f"{name}_precision"] = (
            float(matched_est) / max(1, len(est_indexes))
        )
        output[f"{name}_recall"] = (
            float(matched_ref) / max(1, len(ref_indexes))
        )
    return output


def frame_note_metrics(
    reference: tuple[EvaluationFrameNote, ...],
    estimated: tuple[EvaluationFrameNote, ...],
) -> dict[str, float | int]:
    """Return note metrics and the three fixed short-note strata."""

    onset_matches = _frame_match_pairs(
        reference,
        estimated,
        include_offset=False,
    )
    onset_offset_matches = _frame_match_pairs(
        reference,
        estimated,
        include_offset=True,
    )
    note_precision, note_recall, onset_offset_f1 = (
        _precision_recall_f1(
            len(onset_offset_matches),
            len(estimated),
            len(reference),
        )
    )
    _onset_precision, _onset_recall, onset_f1 = (
        _precision_recall_f1(
            len(onset_matches),
            len(estimated),
            len(reference),
        )
    )
    return {
        "reference_count": len(reference),
        "candidate_count": len(estimated),
        "onset_match_count": len(onset_matches),
        "onset_offset_match_count": len(onset_offset_matches),
        "note_precision": note_precision,
        "note_recall": note_recall,
        "onset_f1": onset_f1,
        "onset_offset_f1": onset_offset_f1,
        **_short_bucket_metrics(
            reference,
            estimated,
            onset_offset_matches,
        ),
    }


def _interval_gap(
    left: EvaluationFrameNote,
    right: EvaluationFrameNote,
) -> int:
    if left.end_frame <= right.start_frame:
        return right.start_frame - left.end_frame
    if right.end_frame <= left.start_frame:
        return left.start_frame - right.end_frame
    return 0


def _fragment_assignments(
    reference: tuple[EvaluationFrameNote, ...],
    estimated: tuple[EvaluationFrameNote, ...],
) -> dict[int, tuple[int, ...]]:
    assigned: dict[int, list[int]] = {}
    for estimated_index, candidate in enumerate(estimated):
        choices: list[tuple[int, int, int]] = []
        for reference_index, truth in enumerate(reference):
            if truth.pitch != candidate.pitch:
                continue
            overlap = max(
                0,
                min(truth.end_frame, candidate.end_frame)
                - max(truth.start_frame, candidate.start_frame),
            )
            if overlap <= 0:
                continue
            choices.append(
                (
                    -overlap,
                    abs(candidate.start_frame - truth.start_frame),
                    reference_index,
                )
            )
        if choices:
            reference_index = min(choices)[2]
            assigned.setdefault(reference_index, []).append(estimated_index)
    return {
        reference_index: tuple(
            sorted(
                indexes,
                key=lambda index: (
                    estimated[index].start_frame,
                    estimated[index].end_frame,
                    estimated[index].pitch,
                    index,
                ),
            )
        )
        for reference_index, indexes in assigned.items()
    }


def _pitch_flicker_count(
    estimated: tuple[EvaluationFrameNote, ...],
) -> int:
    count = 0
    for candidate in estimated:
        if candidate.span_frames > FRAGMENT_REVIEW_MAX_FRAMES:
            continue
        if any(
            other is not candidate
            and 1 <= abs(other.pitch - candidate.pitch) <= 2
            and other.span_frames >= candidate.span_frames + 2
            and _interval_gap(candidate, other) <= 1
            for other in estimated
        ):
            count += 1
    return count


def _fragment_shape_metrics(
    reference: tuple[EvaluationFrameNote, ...],
    estimated: tuple[EvaluationFrameNote, ...],
    *,
    duration_seconds: float,
) -> dict[str, float | int]:
    assignments = _fragment_assignments(reference, estimated)
    split_reference_count = sum(
        len(indexes) >= 2 for indexes in assignments.values()
    )
    fragment_count = sum(
        max(0, len(indexes) - 1) for indexes in assignments.values()
    )
    truth_onsets = {
        (note.pitch, note.start_frame) for note in reference
    }
    unsupported_boundaries: set[tuple[int, int]] = set()
    for indexes in assignments.values():
        for estimated_index in indexes[1:]:
            candidate = estimated[estimated_index]
            if not any(
                pitch == candidate.pitch
                and abs(onset - candidate.start_frame)
                <= FRAGMENT_ONSET_TOLERANCE_FRAMES
                for pitch, onset in truth_onsets
            ):
                unsupported_boundaries.add(
                    (candidate.pitch, candidate.start_frame)
                )
    reference_count = len(reference)
    candidate_count = len(estimated)
    pitch_flicker_count = _pitch_flicker_count(estimated)
    duration_minutes = float(duration_seconds) / 60.0
    return {
        "fragment_count": fragment_count,
        "split_reference_count": split_reference_count,
        "fragmentation_rate": (
            float(fragment_count) / max(1, reference_count)
        ),
        "split_rate": (
            float(split_reference_count) / max(1, reference_count)
        ),
        "unsupported_fragment_boundary_count": len(
            unsupported_boundaries
        ),
        "unsupported_fragment_boundaries_per_minute": (
            float(len(unsupported_boundaries))
            / max(duration_minutes, 1e-9)
        ),
        "pitch_flicker_count": pitch_flicker_count,
        "pitch_flicker_rate": (
            float(pitch_flicker_count) / max(1, candidate_count)
        ),
        "candidate_inflation_ratio": (
            float(candidate_count) / max(1, reference_count)
        ),
        "candidate_excess_rate": (
            float(candidate_count - reference_count)
            / max(1, reference_count)
        ),
    }


def _false_merge_count(
    reference: tuple[EvaluationFrameNote, ...],
    raw: tuple[EvaluationFrameNote, ...],
    processed: tuple[EvaluationFrameNote, ...],
) -> int:
    raw_supported_reference = {
        ref_index
        for ref_index, _raw_index in _frame_match_pairs(
            reference,
            raw,
            include_offset=False,
        )
    }
    false_merges = 0
    for candidate in processed:
        if len(candidate.lineage) < 2:
            continue
        supported_truths = {
            ref_index
            for ref_index in raw_supported_reference
            if reference[ref_index].pitch == candidate.pitch
            and (
                candidate.start_frame
                - FRAGMENT_ONSET_TOLERANCE_FRAMES
                <= reference[ref_index].start_frame
                <= candidate.end_frame
                + FRAGMENT_ONSET_TOLERANCE_FRAMES
            )
        }
        false_merges += max(0, len(supported_truths) - 1)
    return false_merges


def fragment_track_metrics(
    evaluation: FragmentTrackEvaluation,
) -> dict[str, object]:
    """Evaluate one song before and after fragment cleanup."""

    reference = tuple(sorted(evaluation.reference))
    raw = tuple(sorted(evaluation.raw))
    processed = tuple(sorted(evaluation.processed))
    baseline = {
        **frame_note_metrics(reference, raw),
        **_fragment_shape_metrics(
            reference,
            raw,
            duration_seconds=evaluation.duration_seconds,
        ),
    }
    false_merge_count = _false_merge_count(reference, raw, processed)
    balanced = {
        **frame_note_metrics(reference, processed),
        **_fragment_shape_metrics(
            reference,
            processed,
            duration_seconds=evaluation.duration_seconds,
        ),
        "false_merge_count": false_merge_count,
        "false_merge_rate": (
            float(false_merge_count) / max(1, len(reference))
        ),
    }
    accuracy_keys = (
        "note_precision",
        "note_recall",
        "onset_f1",
        "onset_offset_f1",
        "short_le_8_recall",
    )
    before_fragments = int(baseline["fragment_count"])
    after_fragments = int(balanced["fragment_count"])
    deltas = {
        f"{key}_delta": float(balanced[key]) - float(baseline[key])
        for key in accuracy_keys
    }
    deltas["fragmentation_reduction"] = (
        float(before_fragments - after_fragments) / before_fragments
        if before_fragments
        else 0.0
    )
    deltas["candidate_count_change_rate"] = (
        float(
            int(balanced["candidate_count"])
            - int(baseline["candidate_count"])
        )
        / max(1, int(baseline["candidate_count"]))
    )
    result: dict[str, object] = {
        "track_id": evaluation.track_id,
        "duration_seconds": float(evaluation.duration_seconds),
        "baseline": baseline,
        "balanced": balanced,
        "deltas": deltas,
        "timing": {
            "total_decode_seconds": float(
                evaluation.total_decode_seconds
            ),
            "postprocess_seconds": float(
                evaluation.postprocess_seconds
            ),
            "postprocess_share": (
                float(evaluation.postprocess_seconds)
                / max(float(evaluation.total_decode_seconds), 1e-9)
            ),
        },
    }
    if evaluation.clean_processed is not None:
        clean_processed = tuple(sorted(evaluation.clean_processed))
        clean_false_merge_count = _false_merge_count(
            reference,
            raw,
            clean_processed,
        )
        clean = {
            **frame_note_metrics(reference, clean_processed),
            **_fragment_shape_metrics(
                reference,
                clean_processed,
                duration_seconds=evaluation.duration_seconds,
            ),
            "false_merge_count": clean_false_merge_count,
            "false_merge_rate": (
                float(clean_false_merge_count)
                / max(1, len(reference))
            ),
        }
        clean_deltas = {
            f"{key}_delta": (
                float(clean[key]) - float(baseline[key])
            )
            for key in accuracy_keys
        }
        clean_after_fragments = int(clean["fragment_count"])
        clean_deltas["fragmentation_reduction"] = (
            float(before_fragments - clean_after_fragments)
            / before_fragments
            if before_fragments
            else 0.0
        )
        clean_deltas["candidate_count_change_rate"] = (
            float(
                int(clean["candidate_count"])
                - int(baseline["candidate_count"])
            )
            / max(1, int(baseline["candidate_count"]))
        )
        assert evaluation.clean_total_decode_seconds is not None
        assert evaluation.clean_postprocess_seconds is not None
        result.update(
            {
                "clean": clean,
                "clean_deltas": clean_deltas,
                "clean_timing": {
                    "total_decode_seconds": float(
                        evaluation.clean_total_decode_seconds
                    ),
                    "postprocess_seconds": float(
                        evaluation.clean_postprocess_seconds
                    ),
                    "postprocess_share": (
                        float(evaluation.clean_postprocess_seconds)
                        / max(
                            float(
                                evaluation.clean_total_decode_seconds
                            ),
                            1e-9,
                        )
                    ),
                },
            }
        )
    return result


def fragment_evaluation_result_signature(
    evaluation: FragmentTrackEvaluation,
) -> str:
    """Hash only musical inputs, excluding config-specific timing."""

    def notes_payload(
        notes: tuple[EvaluationFrameNote, ...],
    ) -> list[list[object]]:
        return [
            [
                note.start_frame,
                note.end_frame,
                note.pitch,
                list(note.lineage),
            ]
            for note in sorted(notes)
        ]

    payload = {
        "version": "fragment-evaluation-result-v1",
        "track_id": evaluation.track_id,
        "duration_seconds": float(
            evaluation.duration_seconds
        ).hex(),
        "reference": notes_payload(evaluation.reference),
        "raw": notes_payload(evaluation.raw),
        "processed": notes_payload(evaluation.processed),
        "clean_processed": (
            None
            if evaluation.clean_processed is None
            else notes_payload(evaluation.clean_processed)
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _fragment_evaluation_timing(
    evaluation: FragmentTrackEvaluation,
) -> dict[str, float]:
    return {
        "total_decode_seconds": float(evaluation.total_decode_seconds),
        "postprocess_seconds": float(evaluation.postprocess_seconds),
        "postprocess_share": (
            float(evaluation.postprocess_seconds)
            / max(float(evaluation.total_decode_seconds), 1e-9)
        ),
    }


def _clean_evaluation_timing(
    evaluation: FragmentTrackEvaluation,
) -> dict[str, float] | None:
    if (
        evaluation.clean_total_decode_seconds is None
        or evaluation.clean_postprocess_seconds is None
    ):
        return None
    return {
        "total_decode_seconds": float(
            evaluation.clean_total_decode_seconds
        ),
        "postprocess_seconds": float(
            evaluation.clean_postprocess_seconds
        ),
        "postprocess_share": (
            float(evaluation.clean_postprocess_seconds)
            / max(
                float(evaluation.clean_total_decode_seconds),
                1e-9,
            )
        ),
    }


def evaluate_balanced_profile_gate(
    baseline: dict[str, float | int],
    balanced: dict[str, float | int],
    *,
    fragmentation_reduction: float,
    false_merge_count: int,
    reference_note_count: int,
    worst_song_onset_f1_delta: float,
    postprocess_share: float,
) -> dict[str, object]:
    """Apply the frozen balanced-profile release thresholds."""

    tolerance = 1e-12

    def at_least(value: float, threshold: float) -> bool:
        return float(value) + tolerance >= float(threshold)

    def at_most(value: float, threshold: float) -> bool:
        return float(value) <= float(threshold) + tolerance

    precision_gain = (
        float(balanced["note_precision"])
        - float(baseline["note_precision"])
    )
    onset_f1_delta = (
        float(balanced["onset_f1"])
        - float(baseline["onset_f1"])
    )
    onset_offset_f1_delta = (
        float(balanced["onset_offset_f1"])
        - float(baseline["onset_offset_f1"])
    )
    recall_delta = (
        float(balanced["note_recall"])
        - float(baseline["note_recall"])
    )
    short_recall_delta = (
        float(balanced["short_le_8_recall"])
        - float(baseline["short_le_8_recall"])
    )
    false_merge_rate = (
        float(false_merge_count) / max(1, int(reference_note_count))
    )
    checks = {
        "fragmentation_reduction_at_least_0_20": (
            at_least(fragmentation_reduction, 0.20)
        ),
        "note_precision_gain_at_least_0_005": at_least(
            precision_gain,
            0.005,
        ),
        "onset_f1_drop_at_most_0_003": at_least(
            onset_f1_delta,
            -0.003,
        ),
        "onset_offset_f1_drop_at_most_0_002": (
            at_least(onset_offset_f1_delta, -0.002)
        ),
        "note_recall_drop_at_most_0_005": at_least(
            recall_delta,
            -0.005,
        ),
        "short_le_8_recall_drop_at_most_0_01": (
            at_least(short_recall_delta, -0.01)
        ),
        "false_merge_rate_at_most_0_005": at_most(
            false_merge_rate,
            0.005,
        ),
        "worst_song_onset_f1_drop_at_most_0_02": (
            at_least(worst_song_onset_f1_delta, -0.02)
        ),
        "postprocess_share_below_0_05": float(postprocess_share) < 0.05,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "values": {
            "fragmentation_reduction": float(
                fragmentation_reduction
            ),
            "note_precision_gain": precision_gain,
            "onset_f1_delta": onset_f1_delta,
            "onset_offset_f1_delta": onset_offset_f1_delta,
            "note_recall_delta": recall_delta,
            "short_le_8_recall_delta": short_recall_delta,
            "false_merge_rate": false_merge_rate,
            "worst_song_onset_f1_delta": float(
                worst_song_onset_f1_delta
            ),
            "postprocess_share": float(postprocess_share),
        },
    }


def evaluate_clean_profile_safety_gate(
    baseline: dict[str, float | int],
    balanced: dict[str, float | int],
    clean: dict[str, float | int],
    *,
    false_merge_count: int,
    reference_note_count: int,
    worst_song_onset_f1_delta: float,
    postprocess_share: float,
) -> dict[str, object]:
    """Keep clean-profile safety constraints no weaker than balanced."""

    tolerance = 1e-12

    def at_least(value: float, threshold: float) -> bool:
        return float(value) + tolerance >= float(threshold)

    def at_most(value: float, threshold: float) -> bool:
        return float(value) <= float(threshold) + tolerance

    onset_f1_delta = (
        float(clean["onset_f1"]) - float(baseline["onset_f1"])
    )
    onset_offset_f1_delta = (
        float(clean["onset_offset_f1"])
        - float(baseline["onset_offset_f1"])
    )
    recall_delta = (
        float(clean["note_recall"]) - float(baseline["note_recall"])
    )
    short_recall_delta = (
        float(clean["short_le_8_recall"])
        - float(baseline["short_le_8_recall"])
    )
    false_merge_rate = (
        float(false_merge_count) / max(1, int(reference_note_count))
    )
    checks = {
        "onset_f1_drop_at_most_0_003": at_least(
            onset_f1_delta,
            -0.003,
        ),
        "onset_offset_f1_drop_at_most_0_002": at_least(
            onset_offset_f1_delta,
            -0.002,
        ),
        "note_recall_drop_at_most_0_005": at_least(
            recall_delta,
            -0.005,
        ),
        "short_le_8_recall_drop_at_most_0_01": at_least(
            short_recall_delta,
            -0.01,
        ),
        "false_merge_rate_at_most_0_005": at_most(
            false_merge_rate,
            0.005,
        ),
        "worst_song_onset_f1_drop_at_most_0_02": at_least(
            worst_song_onset_f1_delta,
            -0.02,
        ),
        "candidate_count_not_above_balanced": (
            int(clean["candidate_count"])
            <= int(balanced["candidate_count"])
        ),
        "postprocess_share_below_0_05": (
            float(postprocess_share) < 0.05
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "values": {
            "onset_f1_delta": onset_f1_delta,
            "onset_offset_f1_delta": onset_offset_f1_delta,
            "note_recall_delta": recall_delta,
            "short_le_8_recall_delta": short_recall_delta,
            "false_merge_rate": false_merge_rate,
            "worst_song_onset_f1_delta": float(
                worst_song_onset_f1_delta
            ),
            "candidate_count_delta_from_balanced": (
                int(clean["candidate_count"])
                - int(balanced["candidate_count"])
            ),
            "postprocess_share": float(postprocess_share),
        },
    }


def _aggregate_fragment_side(
    track_results: tuple[dict[str, object], ...],
    side: str,
) -> dict[str, float | int]:
    metrics = [dict(result[side]) for result in track_results]
    macro_keys = (
        "note_precision",
        "note_recall",
        "onset_f1",
        "onset_offset_f1",
    )
    output: dict[str, float | int] = {
        key: (
            sum(float(item[key]) for item in metrics) / len(metrics)
            if metrics
            else 0.0
        )
        for key in macro_keys
    }
    count_keys = (
        "reference_count",
        "candidate_count",
        "onset_match_count",
        "onset_offset_match_count",
        "fragment_count",
        "split_reference_count",
        "unsupported_fragment_boundary_count",
        "pitch_flicker_count",
    )
    for key in count_keys:
        output[key] = sum(int(item[key]) for item in metrics)
    for bucket in ("short_le_6", "short_le_8", "short_9_11"):
        for suffix in (
            "reference_count",
            "estimated_count",
            "matched_reference_count",
            "matched_estimated_count",
        ):
            key = f"{bucket}_{suffix}"
            output[key] = sum(int(item[key]) for item in metrics)
        output[f"{bucket}_precision"] = (
            float(output[f"{bucket}_matched_estimated_count"])
            / max(1, int(output[f"{bucket}_estimated_count"]))
        )
        output[f"{bucket}_recall"] = (
            float(output[f"{bucket}_matched_reference_count"])
            / max(1, int(output[f"{bucket}_reference_count"]))
        )
    reference_count = int(output["reference_count"])
    candidate_count = int(output["candidate_count"])
    total_duration_seconds = sum(
        float(result["duration_seconds"]) for result in track_results
    )
    output.update(
        {
            "fragmentation_rate": (
                float(output["fragment_count"])
                / max(1, reference_count)
            ),
            "split_rate": (
                float(output["split_reference_count"])
                / max(1, reference_count)
            ),
            "unsupported_fragment_boundaries_per_minute": (
                float(output["unsupported_fragment_boundary_count"])
                / max(total_duration_seconds / 60.0, 1e-9)
            ),
            "pitch_flicker_rate": (
                float(output["pitch_flicker_count"])
                / max(1, candidate_count)
            ),
            "candidate_inflation_ratio": (
                float(candidate_count) / max(1, reference_count)
            ),
            "candidate_excess_rate": (
                float(candidate_count - reference_count)
                / max(1, reference_count)
            ),
        }
    )
    if side in {"balanced", "clean"}:
        output["false_merge_count"] = sum(
            int(item["false_merge_count"]) for item in metrics
        )
        output["false_merge_rate"] = (
            float(output["false_merge_count"])
            / max(1, reference_count)
        )
    return output


def summarize_fragment_cleanup_tracks(
    evaluations: tuple[FragmentTrackEvaluation, ...],
) -> dict[str, object]:
    """Compute track metrics, aggregate them, and evaluate release gates."""

    return summarize_fragment_cleanup_results(
        tuple(fragment_track_metrics(item) for item in evaluations)
    )


def summarize_fragment_cleanup_results(
    track_results: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Aggregate precomputed track metrics and evaluate release gates."""

    ordered = tuple(
        sorted(
            track_results,
            key=lambda item: str(item["track_id"]),
        )
    )
    baseline = _aggregate_fragment_side(ordered, "baseline")
    balanced = _aggregate_fragment_side(ordered, "balanced")
    before_fragments = int(baseline["fragment_count"])
    after_fragments = int(balanced["fragment_count"])
    fragmentation_reduction = (
        float(before_fragments - after_fragments) / before_fragments
        if before_fragments
        else 0.0
    )
    total_decode_seconds = sum(
        float(dict(item["timing"])["total_decode_seconds"])
        for item in ordered
    )
    postprocess_seconds = sum(
        float(dict(item["timing"])["postprocess_seconds"])
        for item in ordered
    )
    postprocess_share = (
        postprocess_seconds / max(total_decode_seconds, 1e-9)
    )
    worst_item = (
        min(
            ordered,
            key=lambda item: (
                float(dict(item["deltas"])["onset_f1_delta"]),
                str(item["track_id"]),
            ),
        )
        if ordered
        else None
    )
    worst_delta = (
        float(dict(worst_item["deltas"])["onset_f1_delta"])
        if worst_item is not None
        else 0.0
    )
    worst_by_metric: dict[str, dict[str, str | float | None]] = {}
    for delta_key in (
        "note_precision_delta",
        "note_recall_delta",
        "onset_f1_delta",
        "onset_offset_f1_delta",
        "short_le_8_recall_delta",
    ):
        item = (
            min(
                ordered,
                key=lambda result: (
                    float(dict(result["deltas"])[delta_key]),
                    str(result["track_id"]),
                ),
            )
            if ordered
            else None
        )
        worst_by_metric[delta_key] = {
            "track_id": (
                str(item["track_id"]) if item is not None else None
            ),
            "delta": (
                float(dict(item["deltas"])[delta_key])
                if item is not None
                else 0.0
            ),
        }
    gate = evaluate_balanced_profile_gate(
        baseline,
        balanced,
        fragmentation_reduction=fragmentation_reduction,
        false_merge_count=int(balanced["false_merge_count"]),
        reference_note_count=int(balanced["reference_count"]),
        worst_song_onset_f1_delta=worst_delta,
        postprocess_share=postprocess_share,
    )
    result: dict[str, object] = {
        "metric_version": "fragment-cleanup-metrics-v2",
        "track_count": len(ordered),
        "baseline": baseline,
        "balanced": balanced,
        "deltas": {
            "fragmentation_reduction": fragmentation_reduction,
            "note_precision_delta": (
                float(balanced["note_precision"])
                - float(baseline["note_precision"])
            ),
            "note_recall_delta": (
                float(balanced["note_recall"])
                - float(baseline["note_recall"])
            ),
            "onset_f1_delta": (
                float(balanced["onset_f1"])
                - float(baseline["onset_f1"])
            ),
            "onset_offset_f1_delta": (
                float(balanced["onset_offset_f1"])
                - float(baseline["onset_offset_f1"])
            ),
            "short_le_8_recall_delta": (
                float(balanced["short_le_8_recall"])
                - float(baseline["short_le_8_recall"])
            ),
            "candidate_inflation_ratio_delta": (
                float(balanced["candidate_inflation_ratio"])
                - float(baseline["candidate_inflation_ratio"])
            ),
            "candidate_count_change_rate": (
                float(
                    int(balanced["candidate_count"])
                    - int(baseline["candidate_count"])
                )
                / max(1, int(baseline["candidate_count"]))
            ),
        },
        "per_song_worst": {
            "track_id": (
                str(worst_item["track_id"])
                if worst_item is not None
                else None
            ),
            "onset_f1_delta": worst_delta,
            "metrics": worst_by_metric,
        },
        "timing": {
            "total_decode_seconds": total_decode_seconds,
            "postprocess_seconds": postprocess_seconds,
            "postprocess_share": postprocess_share,
        },
        "quality_gate": gate,
        "tracks": list(ordered),
    }
    has_clean = bool(ordered) and all(
        "clean" in item
        and "clean_deltas" in item
        and "clean_timing" in item
        for item in ordered
    )
    clean_gate: dict[str, object] | None = None
    if has_clean:
        clean = _aggregate_fragment_side(ordered, "clean")
        clean_before_fragments = int(baseline["fragment_count"])
        clean_after_fragments = int(clean["fragment_count"])
        clean_fragmentation_reduction = (
            float(clean_before_fragments - clean_after_fragments)
            / clean_before_fragments
            if clean_before_fragments
            else 0.0
        )
        clean_total_decode_seconds = sum(
            float(dict(item["clean_timing"])["total_decode_seconds"])
            for item in ordered
        )
        clean_postprocess_seconds = sum(
            float(dict(item["clean_timing"])["postprocess_seconds"])
            for item in ordered
        )
        clean_postprocess_share = (
            clean_postprocess_seconds
            / max(clean_total_decode_seconds, 1e-9)
        )
        clean_worst_item = min(
            ordered,
            key=lambda item: (
                float(
                    dict(item["clean_deltas"])["onset_f1_delta"]
                ),
                str(item["track_id"]),
            ),
        )
        clean_worst_delta = float(
            dict(clean_worst_item["clean_deltas"])["onset_f1_delta"]
        )
        clean_gate = evaluate_clean_profile_safety_gate(
            baseline,
            balanced,
            clean,
            false_merge_count=int(clean["false_merge_count"]),
            reference_note_count=int(clean["reference_count"]),
            worst_song_onset_f1_delta=clean_worst_delta,
            postprocess_share=clean_postprocess_share,
        )
        result.update(
            {
                "clean": clean,
                "clean_deltas": {
                    "fragmentation_reduction": (
                        clean_fragmentation_reduction
                    ),
                    "note_precision_delta": (
                        float(clean["note_precision"])
                        - float(baseline["note_precision"])
                    ),
                    "note_recall_delta": (
                        float(clean["note_recall"])
                        - float(baseline["note_recall"])
                    ),
                    "onset_f1_delta": (
                        float(clean["onset_f1"])
                        - float(baseline["onset_f1"])
                    ),
                    "onset_offset_f1_delta": (
                        float(clean["onset_offset_f1"])
                        - float(baseline["onset_offset_f1"])
                    ),
                    "short_le_8_recall_delta": (
                        float(clean["short_le_8_recall"])
                        - float(baseline["short_le_8_recall"])
                    ),
                    "candidate_inflation_ratio_delta": (
                        float(clean["candidate_inflation_ratio"])
                        - float(baseline["candidate_inflation_ratio"])
                    ),
                    "candidate_count_change_rate": (
                        float(
                            int(clean["candidate_count"])
                            - int(baseline["candidate_count"])
                        )
                        / max(1, int(baseline["candidate_count"]))
                    ),
                },
                "clean_per_song_worst": {
                    "track_id": str(clean_worst_item["track_id"]),
                    "onset_f1_delta": clean_worst_delta,
                },
                "clean_timing": {
                    "total_decode_seconds": (
                        clean_total_decode_seconds
                    ),
                    "postprocess_seconds": clean_postprocess_seconds,
                    "postprocess_share": clean_postprocess_share,
                },
                "clean_safety_gate": clean_gate,
            }
        )
    result["selection_gate"] = {
        "passed": bool(gate["passed"])
        and clean_gate is not None
        and bool(clean_gate["passed"]),
        "balanced_quality_passed": bool(gate["passed"]),
        "clean_safety_evaluated": clean_gate is not None,
        "clean_safety_passed": (
            None if clean_gate is None else bool(clean_gate["passed"])
        ),
    }
    return result


def summarize_cleanup_grid_with_metric_reuse(
    evaluations_by_config: dict[
        FragmentCleanupSearchConfig,
        list[FragmentTrackEvaluation],
    ],
) -> tuple[
    dict[FragmentCleanupSearchConfig, dict[str, object]],
    dict[str, int],
]:
    """Reuse mir_eval/fragment metrics for identical musical results."""

    metric_cache: dict[str, dict[str, object]] = {}
    reports: dict[FragmentCleanupSearchConfig, dict[str, object]] = {}
    evaluation_count = 0
    for config, evaluations in evaluations_by_config.items():
        track_results: list[dict[str, object]] = []
        for evaluation in evaluations:
            evaluation_count += 1
            signature = fragment_evaluation_result_signature(evaluation)
            cached = metric_cache.get(signature)
            if cached is None:
                cached = fragment_track_metrics(evaluation)
                metric_cache[signature] = cached
            result = {
                **cached,
                "timing": _fragment_evaluation_timing(evaluation),
            }
            clean_timing = _clean_evaluation_timing(evaluation)
            if clean_timing is not None:
                result["clean_timing"] = clean_timing
            track_results.append(result)
        reports[config] = summarize_fragment_cleanup_results(
            tuple(track_results)
        )
    unique_count = len(metric_cache)
    return reports, {
        "grid_track_evaluation_count": evaluation_count,
        "unique_result_signature_count": unique_count,
        "reused_metric_evaluation_count": (
            evaluation_count - unique_count
        ),
    }


def select_fragment_cleanup_config(
    reports: dict[FragmentCleanupSearchConfig, dict[str, object]],
) -> FragmentCleanupSearchConfig | None:
    """Choose one passing config by the frozen ranking and grid order."""

    order = {
        config: index
        for index, config in enumerate(fragment_cleanup_grid())
    }
    unknown = set(reports) - set(order)
    if unknown:
        raise ValueError("fragment cleanup report contains off-grid config")
    passing = [
        config
        for config, report in reports.items()
        if (
            bool(dict(report["selection_gate"])["passed"])
            if "selection_gate" in report
            else (
                bool(dict(report["quality_gate"])["passed"])
                and "clean_safety_gate" in report
                and bool(
                    dict(report["clean_safety_gate"])["passed"]
                )
            )
        )
    ]
    if not passing:
        return None
    return min(
        passing,
        key=lambda config: (
            -float(
                dict(reports[config]["deltas"])[
                    "fragmentation_reduction"
                ]
            ),
            -float(dict(reports[config]["balanced"])["note_precision"]),
            -float(
                dict(reports[config]["balanced"])["onset_offset_f1"]
            ),
            -float(
                dict(
                    reports[config].get(
                        "clean",
                        reports[config]["balanced"],
                    )
                )["note_precision"]
            ),
            -float(
                dict(
                    reports[config].get(
                        "clean",
                        reports[config]["balanced"],
                    )
                )["onset_offset_f1"]
            ),
            order[config],
        ),
    )


def evaluate_fragment_cleanup_grid(
    cases: tuple[FragmentCleanupEvidenceCase, ...],
    *,
    configs: tuple[FragmentCleanupSearchConfig, ...] | None = None,
) -> dict[FragmentCleanupSearchConfig, dict[str, object]]:
    """Evaluate selected closed-grid members against shared raw evidence."""

    selected_configs = (
        fragment_cleanup_grid() if configs is None else tuple(configs)
    )
    official = set(fragment_cleanup_grid())
    if len(set(selected_configs)) != len(selected_configs):
        raise ValueError("fragment cleanup grid contains duplicates")
    if set(selected_configs) - official:
        raise ValueError("fragment cleanup grid contains off-grid config")
    evaluations_by_config = {
        config: [] for config in selected_configs
    }
    for case in sorted(cases, key=lambda item: item.track_id):
        for config, evaluation in _evaluate_fragment_cleanup_case(
            case,
            selected_configs,
        ).items():
            evaluations_by_config[config].append(evaluation)
    reports, _reuse = summarize_cleanup_grid_with_metric_reuse(
        evaluations_by_config
    )
    return reports


def _evaluate_fragment_cleanup_case(
    case: FragmentCleanupEvidenceCase,
    configs: tuple[FragmentCleanupSearchConfig, ...],
    *,
    progress_label: str | None = None,
) -> dict[FragmentCleanupSearchConfig, FragmentTrackEvaluation]:
    """Evaluate one evidence map immediately so its workspace may close."""

    preserved = postprocess_frame_events(
        case.raw_events,
        case.frame_evidence,
        case.onset_evidence,
        profile=PRESERVE_CLEANUP_PROFILE,
        onset_threshold=case.onset_threshold,
        frame_threshold=case.frame_threshold,
        midi_min=case.midi_min,
    )
    raw = tuple(
        evaluation_note_from_event(event) for event in preserved.events
    )
    output: dict[
        FragmentCleanupSearchConfig,
        FragmentTrackEvaluation,
    ] = {}
    for config_index, config in enumerate(configs, start=1):
        started = time.perf_counter()
        processed = postprocess_frame_events(
            case.raw_events,
            case.frame_evidence,
            case.onset_evidence,
            profile=BALANCED_CLEANUP_PROFILE,
            onset_threshold=case.onset_threshold,
            frame_threshold=case.frame_threshold,
            midi_min=case.midi_min,
            params=config.params(),
        )
        postprocess_seconds = time.perf_counter() - started
        clean_started = time.perf_counter()
        clean_processed = postprocess_frame_events(
            case.raw_events,
            case.frame_evidence,
            case.onset_evidence,
            profile=CLEAN_CLEANUP_PROFILE,
            onset_threshold=case.onset_threshold,
            frame_threshold=case.frame_threshold,
            midi_min=case.midi_min,
            params=config.params(),
        )
        clean_postprocess_seconds = (
            time.perf_counter() - clean_started
        )
        output[config] = FragmentTrackEvaluation(
            track_id=case.track_id,
            reference=case.reference,
            raw=raw,
            processed=tuple(
                evaluation_note_from_event(event)
                for event in processed.events
            ),
            duration_seconds=case.duration_seconds,
            total_decode_seconds=(
                case.total_decode_seconds + postprocess_seconds
            ),
            postprocess_seconds=postprocess_seconds,
            clean_processed=tuple(
                evaluation_note_from_event(event)
                for event in clean_processed.events
            ),
            clean_total_decode_seconds=(
                case.total_decode_seconds + clean_postprocess_seconds
            ),
            clean_postprocess_seconds=clean_postprocess_seconds,
        )
        if progress_label is not None and (
            config_index % 12 == 0 or config_index == len(configs)
        ):
            _progress(
                (
                    f"{progress_label}: cleanup grid "
                    f"{config_index}/{len(configs)}"
                )
            )
    return output


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cleanup_checkpoint_folder(
    checkpoint_root: Path,
    track_id: str,
) -> Path:
    if track_id not in HOLDOUT_TRACKS:
        raise ValueError("cleanup checkpoint track is outside holdout")
    return Path(checkpoint_root) / track_id


def _remove_cleanup_checkpoint(
    folder: Path,
    checkpoint_root: Path,
) -> bool:
    try:
        root = Path(checkpoint_root).resolve()
        target = Path(folder)
        if (
            target.is_symlink()
            or target.name not in HOLDOUT_TRACKS
            or target.parent.resolve() != root
        ):
            return False
        if target.is_file():
            target.unlink()
            return True
        if not target.is_dir() or target.resolve().parent != root:
            return False
        shutil.rmtree(target)
        return True
    except OSError:
        return False


def _cleanup_checkpoint_file_descriptor(
    path: Path,
    *,
    filename: str,
    shape: tuple[int, ...],
    dtype: np.dtype,
) -> dict[str, object]:
    return {
        "filename": filename,
        "shape": list(shape),
        "dtype": np.dtype(dtype).str,
        "file_size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _valid_cleanup_evidence_values(array: np.ndarray) -> bool:
    rows = int(array.shape[0])
    for start in range(0, rows, 4096):
        values = np.asarray(array[start : start + 4096])
        if (
            not np.all(np.isfinite(values))
            or np.any(values < 0.0)
            or np.any(values > 1.0)
        ):
            return False
    return True


def _publish_cleanup_evidence_checkpoint(
    checkpoint_root: Path,
    track_id: str,
    *,
    frame_source: Path,
    onset_source: Path,
    times_ms: np.ndarray,
    duration_seconds: float,
    audio_fingerprint: str,
    evidence_cache_key: str,
) -> None:
    """Publish frame evidence atomically with a path-free manifest."""

    root = Path(checkpoint_root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise RuntimeError("cleanup checkpoint root must not be a symlink")
    target = _cleanup_checkpoint_folder(root, track_id)
    frame = np.load(frame_source, mmap_mode="r", allow_pickle=False)
    onset = np.load(onset_source, mmap_mode="r", allow_pickle=False)
    try:
        if (
            frame.ndim != 2
            or frame.shape[1] != TRANSCRIPTION_NOTE_BINS
            or frame.dtype != TRANSCRIPTION_EVIDENCE_DTYPE
            or onset.shape != frame.shape
            or onset.dtype != TRANSCRIPTION_EVIDENCE_DTYPE
            or not _valid_cleanup_evidence_values(frame)
            or not _valid_cleanup_evidence_values(onset)
        ):
            raise RuntimeError("cleanup checkpoint evidence is invalid")
        frame_count = int(frame.shape[0])
    finally:
        _close_memmap(frame)
        _close_memmap(onset)
    times = np.asarray(times_ms, dtype=TRANSCRIPTION_TIME_DTYPE)
    duration_seconds = float(duration_seconds)
    if (
        times.shape != (frame_count,)
        or not np.all(np.isfinite(times))
        or (len(times) > 1 and not np.all(np.diff(times) > 0.0))
        or not math.isfinite(duration_seconds)
        or duration_seconds <= 0.0
        or len(audio_fingerprint) != 64
        or any(value not in "0123456789abcdef" for value in audio_fingerprint)
        or len(evidence_cache_key) != 24
        or any(value not in "0123456789abcdef" for value in evidence_cache_key)
    ):
        raise RuntimeError("cleanup checkpoint metadata is invalid")

    staging = Path(
        tempfile.mkdtemp(prefix=".checkpoint-tmp-", dir=root)
    )
    try:
        frame_path = staging / "frame.npy"
        onset_path = staging / "onset.npy"
        times_path = staging / "times_ms.npy"
        shutil.copyfile(frame_source, frame_path)
        shutil.copyfile(onset_source, onset_path)
        with times_path.open("wb") as stream:
            np.save(stream, times, allow_pickle=False)
        manifest = {
            "schema_version": CLEANUP_CHECKPOINT_SCHEMA_VERSION,
            "track_id": track_id,
            "dataset_archive_md5": BABYSLAKH_ARCHIVE_MD5,
            "analysis_mode": MIXED_ENHANCED_ANALYSIS_MODE,
            "fusion_version": TRANSCRIPTION_FUSION_VERSION,
            "frozen_v2_config": asdict(
                FROZEN_MIXED_ENHANCED_V2_CONFIG
            ),
            "audio_fingerprint": audio_fingerprint,
            "evidence_cache_key": evidence_cache_key,
            "duration_seconds": duration_seconds,
            "frame_count": frame_count,
            "files": {
                "frame": _cleanup_checkpoint_file_descriptor(
                    frame_path,
                    filename="frame.npy",
                    shape=(frame_count, TRANSCRIPTION_NOTE_BINS),
                    dtype=TRANSCRIPTION_EVIDENCE_DTYPE,
                ),
                "onset": _cleanup_checkpoint_file_descriptor(
                    onset_path,
                    filename="onset.npy",
                    shape=(frame_count, TRANSCRIPTION_NOTE_BINS),
                    dtype=TRANSCRIPTION_EVIDENCE_DTYPE,
                ),
                "times_ms": _cleanup_checkpoint_file_descriptor(
                    times_path,
                    filename="times_ms.npy",
                    shape=(frame_count,),
                    dtype=TRANSCRIPTION_TIME_DTYPE,
                ),
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(
                manifest,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        if target.exists() and not _remove_cleanup_checkpoint(
            target,
            root,
        ):
            raise RuntimeError(
                "invalid cleanup checkpoint could not be replaced"
            )
        staging.replace(target)
    finally:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)


def _load_cleanup_evidence_checkpoint(
    checkpoint_root: Path,
    track_id: str,
    *,
    audio_fingerprint: str,
    evidence_cache_key: str,
) -> CleanupEvidenceData | None:
    """Load a complete checkpoint or fail closed without partial reuse."""

    root = Path(checkpoint_root)
    folder = _cleanup_checkpoint_folder(root, track_id)
    arrays: list[np.ndarray] = []
    valid_data: CleanupEvidenceData | None = None
    try:
        if (
            root.is_symlink()
            or folder.is_symlink()
            or not folder.is_dir()
            or folder.parent.resolve() != root.resolve()
        ):
            return None
        manifest_path = folder / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frame_count = manifest["frame_count"]
        duration_seconds = float(manifest["duration_seconds"])
        if (
            manifest["schema_version"]
            != CLEANUP_CHECKPOINT_SCHEMA_VERSION
            or manifest["track_id"] != track_id
            or manifest["dataset_archive_md5"]
            != BABYSLAKH_ARCHIVE_MD5
            or manifest["analysis_mode"]
            != MIXED_ENHANCED_ANALYSIS_MODE
            or manifest["fusion_version"] != TRANSCRIPTION_FUSION_VERSION
            or manifest["frozen_v2_config"]
            != asdict(FROZEN_MIXED_ENHANCED_V2_CONFIG)
            or manifest["audio_fingerprint"] != audio_fingerprint
            or manifest["evidence_cache_key"] != evidence_cache_key
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or frame_count <= 0
            or not math.isfinite(duration_seconds)
            or duration_seconds <= 0.0
        ):
            return None
        files = manifest["files"]
        specifications = (
            (
                "frame",
                "frame.npy",
                (frame_count, TRANSCRIPTION_NOTE_BINS),
                TRANSCRIPTION_EVIDENCE_DTYPE,
            ),
            (
                "onset",
                "onset.npy",
                (frame_count, TRANSCRIPTION_NOTE_BINS),
                TRANSCRIPTION_EVIDENCE_DTYPE,
            ),
            (
                "times_ms",
                "times_ms.npy",
                (frame_count,),
                TRANSCRIPTION_TIME_DTYPE,
            ),
        )
        loaded: dict[str, np.ndarray] = {}
        for key, filename, shape, dtype in specifications:
            descriptor = files[key]
            path = folder / filename
            if (
                descriptor["filename"] != filename
                or descriptor["shape"] != list(shape)
                or descriptor["dtype"] != np.dtype(dtype).str
                or path.is_symlink()
                or not path.is_file()
                or descriptor["file_size"] != path.stat().st_size
                or descriptor["sha256"] != _sha256_file(path)
            ):
                return None
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            arrays.append(array)
            if array.shape != shape or array.dtype != np.dtype(dtype):
                return None
            if key != "times_ms" and not _valid_cleanup_evidence_values(
                array
            ):
                return None
            loaded[key] = array
        times = loaded["times_ms"]
        if (
            not np.all(np.isfinite(times))
            or (len(times) > 1 and not np.all(np.diff(times) > 0.0))
        ):
            return None
        valid_data = CleanupEvidenceData(
            frame=loaded["frame"],
            onset=loaded["onset"],
            times_ms=times,
            duration_seconds=duration_seconds,
            frame_count=frame_count,
        )
        return valid_data
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        EOFError,
        json.JSONDecodeError,
    ):
        return None
    finally:
        # Ownership transfers only when all three arrays form a valid result.
        if valid_data is None:
            for array in arrays:
                _close_memmap(array)


def _close_cleanup_evidence(data: CleanupEvidenceData) -> None:
    _close_memmap(data.frame)
    _close_memmap(data.onset)
    _close_memmap(data.times_ms)


@contextmanager
def _checkpointed_cleanup_evidence(
    audio_path: Path,
    track_id: str,
    *,
    model_provider,
    inference,
    note_creation,
    work_root: Path,
):
    """Yield reusable evidence and whether ONNX was skipped."""

    fingerprint_started = time.perf_counter()
    audio_fingerprint = transcription_audio_fingerprint(audio_path)
    fingerprint_seconds = time.perf_counter() - fingerprint_started
    evidence_cache_key = transcription_cache_key(
        audio_path,
        analysis_mode=MIXED_ENHANCED_ANALYSIS_MODE,
        audio_fingerprint=audio_fingerprint,
    )
    checkpoint_root = Path(work_root) / CLEANUP_CHECKPOINT_DIRECTORY
    data = _load_cleanup_evidence_checkpoint(
        checkpoint_root,
        track_id,
        audio_fingerprint=audio_fingerprint,
        evidence_cache_key=evidence_cache_key,
    )
    source = "checkpoint"
    evidence_seconds = 0.0
    checkpoint_write_seconds = 0.0
    if data is None:
        source = "onnx"
        with _transcription_workspace(
            Path(work_root) / "inference-work"
        ) as workspace:
            model_output: dict[str, np.ndarray] = {}
            try:
                evidence_started = time.perf_counter()
                model_output, original_length = _run_streamed_analysis(
                    audio_path,
                    model_provider(),
                    inference,
                    workspace,
                    analysis_mode=MIXED_ENHANCED_ANALYSIS_MODE,
                    frame_harmonic_weight=(
                        FROZEN_MIXED_ENHANCED_V2_CONFIG
                        .frame_harmonic_weight
                    ),
                    onset_harmonic_weight=(
                        FROZEN_MIXED_ENHANCED_V2_CONFIG
                        .onset_harmonic_weight
                    ),
                    contour_harmonic_weight=(
                        MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT
                    ),
                )
                evidence_seconds = (
                    time.perf_counter() - evidence_started
                )
                frame_count = int(model_output["note"].shape[0])
                frame_times_ms = basic_pitch_frame_times_ms(
                    frame_count,
                    note_creation=note_creation,
                )
                duration_seconds = (
                    float(original_length)
                    / float(inference.AUDIO_SAMPLE_RATE)
                )
            finally:
                for array in model_output.values():
                    _close_memmap(array)
            checkpoint_started = time.perf_counter()
            _publish_cleanup_evidence_checkpoint(
                checkpoint_root,
                track_id,
                frame_source=workspace / "evidence-note.npy",
                onset_source=workspace / "evidence-onset.npy",
                times_ms=frame_times_ms,
                duration_seconds=duration_seconds,
                audio_fingerprint=audio_fingerprint,
                evidence_cache_key=evidence_cache_key,
            )
            checkpoint_write_seconds = (
                time.perf_counter() - checkpoint_started
            )
        data = _load_cleanup_evidence_checkpoint(
            checkpoint_root,
            track_id,
            audio_fingerprint=audio_fingerprint,
            evidence_cache_key=evidence_cache_key,
        )
        if data is None:
            raise RuntimeError(
                "cleanup evidence checkpoint failed validation"
            )
    try:
        yield data, {
            "evidence_source": source,
            "fingerprint_seconds": fingerprint_seconds,
            "evidence_seconds": evidence_seconds,
            "checkpoint_write_seconds": checkpoint_write_seconds,
        }
    finally:
        _close_cleanup_evidence(data)


def download_dataset(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / BABYSLAKH_ARCHIVE_NAME
    if (
        not archive.is_file()
        or archive.stat().st_size != BABYSLAKH_ARCHIVE_BYTES
        or _md5(archive) != BABYSLAKH_ARCHIVE_MD5
    ):
        temporary = archive.with_suffix(".zip.part")
        request = Request(
            BABYSLAKH_DOWNLOAD_URL,
            headers={"User-Agent": "BDO-Music-Composer-Benchmark/1"},
        )
        with urlopen(request, timeout=60) as response, temporary.open(
            "wb"
        ) as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if (
            temporary.stat().st_size != BABYSLAKH_ARCHIVE_BYTES
            or _md5(temporary) != BABYSLAKH_ARCHIVE_MD5
        ):
            temporary.unlink(missing_ok=True)
            raise RuntimeError("BabySlakh archive checksum mismatch")
        temporary.replace(archive)

    dataset_dir = cache_dir / "babyslakh_16k"
    sentinel = dataset_dir / ".verified-ea1797fc"
    if sentinel.is_file():
        return dataset_dir
    dataset_dir.mkdir(parents=True, exist_ok=True)
    root = dataset_dir.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (dataset_dir / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(
                    "BabySlakh archive contains an unsafe path"
                ) from exc
        bundle.extractall(dataset_dir)
    sentinel.write_text(
        (
            f"Source: {BABYSLAKH_RECORD}\n"
            f"License: {BABYSLAKH_LICENSE}\n"
            f"MD5: {BABYSLAKH_ARCHIVE_MD5}\n"
        ),
        encoding="utf-8",
    )
    return dataset_dir


def _track_dir(dataset_dir: Path, track_id: str) -> Path:
    matches = tuple(
        path
        for path in dataset_dir.rglob(track_id)
        if (
            path.is_dir()
            and "__MACOSX" not in path.parts
            and (path / "all_src.mid").is_file()
            and (
                (path / "mix.flac").is_file()
                or (path / "mix.wav").is_file()
            )
        )
    )
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one directory for {track_id}"
        )
    return matches[0]


def _track_inputs(
    dataset_dir: Path,
    track_id: str,
) -> tuple[Path, Path]:
    folder = _track_dir(dataset_dir, track_id)
    audio = next(
        (
            path
            for name in ("mix.flac", "mix.wav")
            if (path := folder / name).is_file()
        ),
        None,
    )
    midi = folder / "all_src.mid"
    if audio is None or not midi.is_file():
        raise FileNotFoundError(f"incomplete BabySlakh track: {track_id}")
    return audio, midi


def _reference_notes(midi_path: Path) -> tuple[np.ndarray, np.ndarray]:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(midi_path))
    notes = sorted(
        (
            note
            for instrument in midi.instruments
            if not instrument.is_drum
            for note in instrument.notes
            if note.end > note.start
        ),
        key=lambda note: (note.start, note.pitch, note.end),
    )
    intervals = np.asarray(
        [(note.start, note.end) for note in notes],
        dtype=np.float64,
    ).reshape((-1, 2))
    pitches = np.asarray(
        [pretty_midi.note_number_to_hz(note.pitch) for note in notes],
        dtype=np.float64,
    )
    return intervals, pitches


def _reference_frame_notes(
    midi_path: Path,
    frame_times_ms: np.ndarray,
) -> tuple[EvaluationFrameNote, ...]:
    """Project public MIDI truth onto the exact Basic Pitch frame axis."""

    import pretty_midi

    times = np.asarray(frame_times_ms, dtype=np.float64)
    if times.ndim != 1 or not times.size:
        raise ValueError("frame_times_ms must be a non-empty vector")
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    output: list[EvaluationFrameNote] = []
    for instrument in midi.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            if note.end <= note.start:
                continue
            start = int(
                np.searchsorted(
                    times,
                    float(note.start) * 1000.0,
                    side="left",
                )
            )
            if start >= len(times):
                continue
            end = int(
                np.searchsorted(
                    times,
                    float(note.end) * 1000.0,
                    side="left",
                )
            )
            end = min(len(times), max(start + 1, end))
            output.append(
                EvaluationFrameNote(
                    start,
                    end,
                    int(note.pitch),
                )
            )
    return tuple(sorted(output))


def _raw_frame_events(
    model_output: dict[str, np.ndarray],
    note_creation,
    config: SearchConfig,
) -> tuple[FrameNoteEvent, ...]:
    """Decode raw frame events once, before any cleanup profile."""

    frame = np.asarray(model_output["note"], dtype=np.float32)
    onset = np.asarray(model_output["onset"], dtype=np.float32)
    events = note_creation.output_to_notes_polyphonic(
        frame,
        onset,
        onset_thresh=config.onset_threshold,
        frame_thresh=config.frame_threshold,
        infer_onsets=True,
        min_note_len=config.min_note_len_frames,
        min_freq=None,
        max_freq=None,
        melodia_trick=True,
    )
    parsed: list[tuple[int, int, int, float]] = []
    for item in events:
        if len(item) < 4:
            continue
        try:
            start = int(item[0])
            end = int(item[1])
            pitch = int(item[2])
            confidence = float(item[3])
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            start < 0
            or end <= start
            or end > frame.shape[0]
            or not 0 <= pitch <= 127
            or not math.isfinite(confidence)
        ):
            continue
        parsed.append(
            (
                start,
                end,
                pitch,
                max(0.0, min(1.0, confidence)),
            )
        )
    parsed.sort(key=lambda item: (item[0], item[2], item[1], -item[3]))
    occurrences: dict[tuple[int, int, int, float], int] = {}
    output: list[FrameNoteEvent] = []
    for start, end, pitch, confidence in parsed:
        key = (start, end, pitch, confidence)
        ordinal = occurrences.get(key, 0)
        occurrences[key] = ordinal + 1
        output.append(
            FrameNoteEvent(
                start,
                end,
                pitch,
                confidence,
                (
                    "raw:"
                    f"{start}:{end}:{pitch}:{confidence.hex()}:{ordinal}",
                ),
            )
        )
    return tuple(output)


def _estimated_notes(
    model_output: dict[str, np.ndarray],
    note_creation,
    config: SearchConfig,
) -> tuple[np.ndarray, np.ndarray]:
    import pretty_midi

    events = note_creation.output_to_notes_polyphonic(
        np.asarray(model_output["note"], dtype=np.float32),
        np.asarray(model_output["onset"], dtype=np.float32),
        onset_thresh=config.onset_threshold,
        frame_thresh=config.frame_threshold,
        infer_onsets=True,
        min_note_len=config.min_note_len_frames,
        min_freq=None,
        max_freq=None,
        melodia_trick=True,
    )
    times = basic_pitch_frame_times_ms(
        int(model_output["note"].shape[0]),
        note_creation=note_creation,
    ) / 1000.0
    intervals: list[tuple[float, float]] = []
    pitches: list[float] = []
    for start, end, pitch, _confidence in events:
        if 0 <= int(start) < int(end) < times.size:
            intervals.append((times[int(start)], times[int(end)]))
            pitches.append(pretty_midi.note_number_to_hz(int(pitch)))
    return (
        np.asarray(intervals, dtype=np.float64).reshape((-1, 2)),
        np.asarray(pitches, dtype=np.float64),
    )


def _metrics(
    reference: tuple[np.ndarray, np.ndarray],
    estimated: tuple[np.ndarray, np.ndarray],
) -> dict[str, float]:
    import mir_eval.transcription
    import mir_eval.util

    ref_intervals, ref_pitches = reference
    est_intervals, est_pitches = estimated
    mir_eval.transcription.validate(
        ref_intervals,
        ref_pitches,
        est_intervals,
        est_pitches,
    )
    if not ref_pitches.size or not est_pitches.size:
        return {
            "note_precision": 0.0,
            "note_recall": 0.0,
            "onset_f1": 0.0,
            "onset_offset_f1": 0.0,
        }
    # Both sides originate from MIDI notes. With mir_eval's fixed 50-cent
    # tolerance, different integer MIDI pitches can never match. Partitioning
    # the exact same matcher by pitch therefore preserves the maximum matching
    # while avoiding a whole-track ref×estimate distance matrix for every one
    # of the 243 search configurations.
    ref_midi = np.rint(
        69.0 + 12.0 * np.log2(ref_pitches / 440.0)
    ).astype(np.int16)
    est_midi = np.rint(
        69.0 + 12.0 * np.log2(est_pitches / 440.0)
    ).astype(np.int16)
    onset_offset_matches = 0
    onset_matches = 0
    for pitch in np.intersect1d(ref_midi, est_midi):
        ref_mask = ref_midi == pitch
        est_mask = est_midi == pitch
        onset_offset_matches += len(
            mir_eval.transcription.match_notes(
                ref_intervals[ref_mask],
                ref_pitches[ref_mask],
                est_intervals[est_mask],
                est_pitches[est_mask],
            )
        )
        onset_matches += len(
            mir_eval.transcription.match_notes(
                ref_intervals[ref_mask],
                ref_pitches[ref_mask],
                est_intervals[est_mask],
                est_pitches[est_mask],
                offset_ratio=None,
            )
        )
    precision = float(onset_offset_matches) / len(est_pitches)
    recall = float(onset_offset_matches) / len(ref_pitches)
    onset_precision = float(onset_matches) / len(est_pitches)
    onset_recall = float(onset_matches) / len(ref_pitches)
    return {
        "note_precision": float(precision),
        "note_recall": float(recall),
        "onset_f1": float(
            mir_eval.util.f_measure(onset_precision, onset_recall)
        ),
        "onset_offset_f1": float(
            mir_eval.util.f_measure(precision, recall)
        ),
    }


def _write_tuning_evidence(
    folder: Path,
    group_index: int,
    original: dict[str, np.ndarray],
    harmonic: dict[str, np.ndarray],
    *,
    frame_weight: float,
    onset_weight: float,
) -> tuple[Path, Path]:
    """Publish one frame/onset pair for process-parallel grid decoding."""

    paths: list[Path] = []
    for key, weight in (
        ("note", float(frame_weight)),
        ("onset", float(onset_weight)),
    ):
        raw = np.asarray(original[key], dtype=np.float32)
        separated = np.asarray(harmonic[key], dtype=np.float32)
        if raw.shape != separated.shape or raw.ndim != 2:
            raise RuntimeError("tuning evidence timelines do not align")
        path = folder / f"group-{group_index}-{key}.npy"
        output = np.lib.format.open_memmap(
            path,
            mode="w+",
            dtype=np.dtype("<f2"),
            shape=raw.shape,
        )
        try:
            rows_per_chunk = max(1, 1_048_576 // raw.shape[1])
            for start in range(0, int(raw.shape[0]), rows_per_chunk):
                stop = min(int(raw.shape[0]), start + rows_per_chunk)
                values = (
                    raw[start:stop] * (1.0 - weight)
                    + separated[start:stop] * weight
                )
                output[start:stop] = np.clip(values, 0.0, 1.0)
            output.flush()
        finally:
            _close_memmap(output)
        paths.append(path)
    return paths[0], paths[1]


def _evaluate_tuning_group(
    reference: tuple[np.ndarray, np.ndarray],
    note_path: Path,
    onset_path: Path,
    configs: tuple[SearchConfig, ...],
) -> tuple[tuple[SearchConfig, dict[str, float]], ...]:
    """Worker entry: decode all thresholds for one fusion-weight pair."""

    note_creation = _import_basic_pitch_note_creation()
    note = np.load(note_path, mmap_mode="r", allow_pickle=False)
    onset = np.load(onset_path, mmap_mode="r", allow_pickle=False)
    try:
        evidence = {"note": note, "onset": onset}
        return tuple(
            (
                config,
                _metrics(
                    reference,
                    _estimated_notes(evidence, note_creation, config),
                ),
            )
            for config in configs
        )
    finally:
        _close_memmap(note)
        _close_memmap(onset)


def _inference_pair(audio_path: Path, model, inference):
    overlapping_frames = 30
    overlap_len = overlapping_frames * inference.FFT_HOP
    hop_size = inference.AUDIO_N_SAMPLES - overlap_len
    audio, _ = inference.librosa.load(
        str(audio_path),
        sr=inference.AUDIO_SAMPLE_RATE,
        mono=True,
    )
    audio = np.asarray(audio, dtype=np.float32)
    harmonic = blockwise_harmonic_signal(
        audio,
        inference.AUDIO_SAMPLE_RATE,
        block_seconds=HPSS_BLOCK_SECONDS,
        overlap_seconds=HPSS_OVERLAP_SECONDS,
        harmonic_separator=lambda block: _fast_harmonic_separator(
            inference.librosa,
            block,
        ),
    )
    original, original_length = _predict_basic_pitch_windows(
        _signal_audio_input(audio, inference, overlap_len, hop_size),
        model,
        inference,
        overlapping_frames=overlapping_frames,
        overlap_len=overlap_len,
        hop_size=hop_size,
    )
    separated, harmonic_length = _predict_basic_pitch_windows(
        _signal_audio_input(harmonic, inference, overlap_len, hop_size),
        model,
        inference,
        overlapping_frames=overlapping_frames,
        overlap_len=overlap_len,
        hop_size=hop_size,
    )
    if harmonic_length != original_length:
        raise RuntimeError("HPSS inference timeline changed")
    return original, separated


def _select_config(
    accumulators: dict[SearchConfig, MetricAccumulator],
) -> SearchConfig:
    # The config itself is the final deterministic tie-breaker.
    return max(
        sorted(accumulators),
        key=lambda config: (
            accumulators[config].means()["onset_offset_f1"],
            accumulators[config].means()["onset_f1"],
            accumulators[config].means()["note_precision"],
        ),
    )


def _progress(message: str) -> None:
    try:
        print(message, flush=True)
    except BrokenPipeError:
        # A detached development run must keep evaluating and writing its
        # report even if the launching terminal closes.
        pass


def _write_tuning_checkpoint(
    path: Path,
    completed_track_ids: list[str],
    accumulators: dict[SearchConfig, MetricAccumulator],
) -> None:
    payload = {
        "algorithm_version": TRANSCRIPTION_FUSION_VERSION,
        "completed_track_ids": list(completed_track_ids),
        "metrics": [
            {
                "config": asdict(config),
                "accumulator": asdict(accumulators[config]),
            }
            for config in sorted(accumulators)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_tuning_checkpoint(
    path: Path,
    configs: tuple[SearchConfig, ...],
) -> tuple[list[str], dict[SearchConfig, MetricAccumulator]]:
    empty = {config: MetricAccumulator() for config in configs}
    if not path.is_file():
        return [], empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        completed = [str(value) for value in payload["completed_track_ids"]]
        if (
            payload["algorithm_version"] != TRANSCRIPTION_FUSION_VERSION
            or completed != list(TUNING_TRACKS[: len(completed)])
        ):
            return [], empty
        restored: dict[SearchConfig, MetricAccumulator] = {}
        for item in payload["metrics"]:
            config = SearchConfig(**item["config"])
            restored[config] = MetricAccumulator(**item["accumulator"])
        if set(restored) != set(configs):
            return [], empty
        return completed, restored
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return [], empty


def _candidate_estimates(
    candidates,
) -> tuple[np.ndarray, np.ndarray]:
    import pretty_midi

    return (
        np.asarray(
            [
                (
                    float(candidate.start_ms) / 1000.0,
                    (
                        float(candidate.start_ms)
                        + float(candidate.duration_ms)
                    )
                    / 1000.0,
                )
                for candidate in candidates
            ],
            dtype=np.float64,
        ).reshape((-1, 2)),
        np.asarray(
            [
                pretty_midi.note_number_to_hz(int(candidate.pitch))
                for candidate in candidates
            ],
            dtype=np.float64,
        ),
    )


def _measure_product_pipeline(
    audio_path: Path,
    model,
    inference,
    note_creation,
    config: SearchConfig,
    *,
    analysis_mode: str,
    work_root: Path,
) -> tuple[tuple[np.ndarray, np.ndarray], float]:
    """Measure the same decode/infer/fuse/decode/publish path as the app."""

    model_output: dict[str, np.ndarray] = {}
    started = time.perf_counter()
    fingerprint = transcription_audio_fingerprint(audio_path)
    with _transcription_workspace(work_root) as workspace:
        try:
            model_output, original_length = _run_streamed_analysis(
                audio_path,
                model,
                inference,
                workspace,
                analysis_mode=analysis_mode,
                frame_harmonic_weight=config.frame_harmonic_weight,
                onset_harmonic_weight=config.onset_harmonic_weight,
                contour_harmonic_weight=(
                    MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT
                ),
            )
            midi_data, note_events = note_creation.model_output_to_notes(
                model_output,
                onset_thresh=config.onset_threshold,
                frame_thresh=config.frame_threshold,
                min_note_len=config.min_note_len_frames,
                min_freq=None,
                max_freq=None,
                include_pitch_bends=False,
                multiple_pitch_bends=False,
                melodia_trick=True,
                midi_tempo=120,
            )
            if transcription_audio_fingerprint(audio_path) != fingerprint:
                raise RuntimeError(
                    "BabySlakh audio changed during measurement"
                )
            cache_key = transcription_cache_key(
                audio_path,
                analysis_mode=analysis_mode,
                audio_fingerprint=fingerprint,
            )
            candidates = _candidates_from_basic_pitch(
                midi_data,
                note_events,
            )
            result = TranscriptionResult(
                candidates,
                cache_key,
                ("frame", "onset", "contour"),
            )
            frame_count = int(model_output["note"].shape[0])
            _write_cached_result(
                result,
                model_output,
                workspace / "published-cache",
                frame_times_ms=basic_pitch_frame_times_ms(
                    frame_count,
                    note_creation=note_creation,
                ),
                duration_ms=(
                    float(original_length)
                    / float(inference.AUDIO_SAMPLE_RATE)
                    * 1000.0
                ),
                audio_fingerprint=fingerprint,
                analysis_mode=analysis_mode,
                sensitivity="balanced",
            )
            elapsed = time.perf_counter() - started
            return _candidate_estimates(candidates), elapsed
        finally:
            for array in model_output.values():
                _close_memmap(array)


def _measure_holdout_in_fresh_runtime(
    dataset_dir: Path,
    selected: SearchConfig,
    *,
    work_root: Path,
) -> dict[str, object]:
    """Run all holdout analyses after loading and pre-warming one model."""

    basic_pitch, inference, note_creation, onnxruntime = _import_basic_pitch()
    model = _onnx_model(basic_pitch, inference, onnxruntime)
    model.predict(
        np.zeros(
            (1, int(inference.AUDIO_N_SAMPLES), 1),
            dtype=np.float32,
        )
    )
    baseline_config = SearchConfig(0.0, 0.0, 0.50, 0.30, 11)
    standard_seconds = 0.0
    enhanced_seconds = 0.0
    estimates: list[
        tuple[
            str,
            tuple[np.ndarray, np.ndarray],
            tuple[np.ndarray, np.ndarray],
        ]
    ] = []
    work_root.mkdir(parents=True, exist_ok=True)
    with WorkingSetSampler() as memory:
        for track_number, track_id in enumerate(HOLDOUT_TRACKS, start=1):
            _progress(
                (
                    f"Runtime holdout {track_id} "
                    f"({track_number}/{len(HOLDOUT_TRACKS)})"
                )
            )
            audio, _midi = _track_inputs(dataset_dir, track_id)
            standard_estimate, elapsed = _measure_product_pipeline(
                audio,
                model,
                inference,
                note_creation,
                baseline_config,
                analysis_mode=STANDARD_ANALYSIS_MODE,
                work_root=work_root,
            )
            standard_seconds += elapsed
            enhanced_estimate, elapsed = _measure_product_pipeline(
                audio,
                model,
                inference,
                note_creation,
                selected,
                analysis_mode=MIXED_ENHANCED_ANALYSIS_MODE,
                work_root=work_root,
            )
            enhanced_seconds += elapsed
            estimates.append(
                (track_id, standard_estimate, enhanced_estimate)
            )

    baseline = MetricAccumulator()
    enhanced = MetricAccumulator()
    for track_id, standard_estimate, enhanced_estimate in estimates:
        _audio, midi = _track_inputs(dataset_dir, track_id)
        reference = _reference_notes(midi)
        baseline.add(_metrics(reference, standard_estimate))
        enhanced.add(_metrics(reference, enhanced_estimate))
    return {
        "standard": baseline.means(),
        "mixed_enhanced": enhanced.means(),
        "standard_seconds": standard_seconds,
        "mixed_enhanced_seconds": enhanced_seconds,
        "runtime_ratio": (
            enhanced_seconds / max(standard_seconds, 1e-9)
        ),
        "peak_working_set_mib": memory.peak_bytes / 1024**2,
    }


def _launch_holdout_runtime(
    dataset_dir: Path,
    selected: SearchConfig,
    *,
    work_root: Path,
) -> dict[str, object]:
    """Measure in an independent process so tuning cannot pollute memory."""

    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="runtime-probe-",
        dir=work_root,
    ) as temporary_name:
        temporary = Path(temporary_name)
        config_path = temporary / "config.json"
        output_path = temporary / "result.json"
        config_path.write_text(
            json.dumps(asdict(selected)),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--runtime-worker",
                "--dataset-dir",
                str(dataset_dir),
                "--runtime-config",
                str(config_path),
                "--runtime-output",
                str(output_path),
                "--cache-dir",
                str(work_root),
            ],
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            raise RuntimeError(
                "independent BabySlakh runtime probe failed"
            )
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(
                "independent BabySlakh runtime probe returned invalid data"
            )
        return payload


def run_benchmark(
    dataset_dir: Path,
    *,
    tuning_checkpoint: Path | None = None,
    runtime_subprocess: bool = False,
    runtime_work_root: Path | None = None,
) -> dict[str, object]:
    basic_pitch, inference, _note_creation, onnxruntime = _import_basic_pitch()
    model = _onnx_model(basic_pitch, inference, onnxruntime)
    configs = search_grid()
    completed_tuning, tuning = (
        _load_tuning_checkpoint(tuning_checkpoint, configs)
        if tuning_checkpoint is not None
        else ([], {config: MetricAccumulator() for config in configs})
    )
    configs_by_weights: dict[
        tuple[float, float],
        list[SearchConfig],
    ] = {}
    for config in configs:
        configs_by_weights.setdefault(
            (
                config.frame_harmonic_weight,
                config.onset_harmonic_weight,
            ),
            [],
        ).append(config)

    tuning_work_root = (
        tuning_checkpoint.parent
        if tuning_checkpoint is not None
        else USER_DATA_DIR / "benchmarks" / "BabySlakh"
    )
    tuning_work_root.mkdir(parents=True, exist_ok=True)
    metric_workers = min(
        9,
        max(1, (os.cpu_count() or 2) // 2),
    )
    with ProcessPoolExecutor(max_workers=metric_workers) as metric_pool:
        for track_number, track_id in enumerate(TUNING_TRACKS, start=1):
            if track_id in completed_tuning:
                _progress(
                    (
                        f"Tuning {track_id} "
                        f"({track_number}/{len(TUNING_TRACKS)}) cached"
                    )
                )
                continue
            _progress(
                (
                    f"Tuning {track_id} "
                    f"({track_number}/{len(TUNING_TRACKS)})"
                )
            )
            audio, midi = _track_inputs(dataset_dir, track_id)
            reference = _reference_notes(midi)
            original, harmonic = _inference_pair(audio, model, inference)
            with tempfile.TemporaryDirectory(
                prefix=f"{track_id}-",
                dir=tuning_work_root,
            ) as temporary_name:
                tasks = []
                for group_index, (
                    (frame_weight, onset_weight),
                    grouped_configs,
                ) in enumerate(configs_by_weights.items()):
                    note_path, onset_path = _write_tuning_evidence(
                        Path(temporary_name),
                        group_index,
                        original,
                        harmonic,
                        frame_weight=frame_weight,
                        onset_weight=onset_weight,
                    )
                    for config_start in range(
                        0,
                        len(grouped_configs),
                        3,
                    ):
                        tasks.append(
                            metric_pool.submit(
                                _evaluate_tuning_group,
                                reference,
                                note_path,
                                onset_path,
                                tuple(
                                    grouped_configs[
                                        config_start : config_start + 3
                                    ]
                                ),
                            )
                        )
                del original, harmonic
                for task in tasks:
                    for config, values in task.result():
                        tuning[config].add(values)
            completed_tuning.append(track_id)
            if tuning_checkpoint is not None:
                _write_tuning_checkpoint(
                    tuning_checkpoint,
                    completed_tuning,
                    tuning,
                )
    selected = _select_config(tuning)
    measurement_root = (
        Path(runtime_work_root)
        if runtime_work_root is not None
        else USER_DATA_DIR / "benchmarks" / "BabySlakh" / "runtime"
    )
    holdout = (
        _launch_holdout_runtime(
            dataset_dir,
            selected,
            work_root=measurement_root,
        )
        if runtime_subprocess
        else _measure_holdout_in_fresh_runtime(
            dataset_dir,
            selected,
            work_root=measurement_root,
        )
    )
    baseline_metrics = dict(holdout["standard"])
    enhanced_metrics = dict(holdout["mixed_enhanced"])
    timing_ratio = float(holdout["runtime_ratio"])
    peak_working_set_mib = float(holdout["peak_working_set_mib"])
    gate_checks = {
        "onset_offset_f1_gain_at_least_0_02": (
            enhanced_metrics["onset_offset_f1"]
            - baseline_metrics["onset_offset_f1"]
            >= 0.02
        ),
        "onset_f1_drop_at_most_0_01": (
            enhanced_metrics["onset_f1"]
            >= baseline_metrics["onset_f1"] - 0.01
        ),
        "precision_drop_at_most_0_01": (
            enhanced_metrics["note_precision"]
            >= baseline_metrics["note_precision"] - 0.01
        ),
        "runtime_ratio_at_most_2_2": timing_ratio <= 2.2,
        "working_set_at_most_512_mib": (
            peak_working_set_mib <= 512.0
        ),
    }
    return {
        "dataset": {
            "record": BABYSLAKH_RECORD,
            "license": BABYSLAKH_LICENSE,
            "archive_md5": BABYSLAKH_ARCHIVE_MD5,
        },
        "algorithm_version": TRANSCRIPTION_FUSION_VERSION,
        "algorithm_parameters": {
            "block_seconds": HPSS_BLOCK_SECONDS,
            "overlap_seconds": HPSS_OVERLAP_SECONDS,
            "n_fft": HPSS_N_FFT,
            "hop_length": HPSS_HOP_LENGTH,
            "kernel_size": HPSS_KERNEL_SIZE,
            "power": HPSS_POWER,
            "margin": HPSS_MARGIN,
            "evidence_dtype": "<f2",
        },
        "tuning_track_ids": list(TUNING_TRACKS),
        "holdout_track_ids": list(HOLDOUT_TRACKS),
        "selected_config": asdict(selected),
        "tuning_metrics": tuning[selected].means(),
        "holdout": {
            "standard": baseline_metrics,
            "mixed_enhanced": enhanced_metrics,
            "runtime_ratio": timing_ratio,
            "standard_seconds": float(holdout["standard_seconds"]),
            "mixed_enhanced_seconds": float(
                holdout["mixed_enhanced_seconds"]
            ),
            "peak_working_set_mib": peak_working_set_mib,
            "timing_scope": (
                "fingerprint, streaming decode/resample, HPSS, ONNX, "
                "fusion, note decode, evidence validation/hash/publish"
            ),
            "memory_scope": (
                "independent pre-warmed process during full analyses"
            ),
        },
        "quality_gate": {
            "passed": all(gate_checks.values()),
            "checks": gate_checks,
        },
    }


def cleanup_holdout_report(
    reports: dict[FragmentCleanupSearchConfig, dict[str, object]],
    *,
    runtime: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the path-free v4 cleanup report from evaluated grid results."""

    selected = select_fragment_cleanup_config(reports)
    ordered_configs = [
        config
        for config in fragment_cleanup_grid()
        if config in reports
    ]
    passing_count = sum(
        bool(
            dict(
                reports[config].get(
                    "selection_gate",
                    reports[config]["quality_gate"],
                )
            )["passed"]
        )
        for config in ordered_configs
    )
    balanced_passing_count = sum(
        bool(dict(reports[config]["quality_gate"])["passed"])
        for config in ordered_configs
    )
    clean_passing_count = sum(
        bool(
            dict(
                reports[config].get(
                    "clean_safety_gate",
                    {"passed": False},
                )
            )["passed"]
        )
        for config in ordered_configs
    )

    def compact(
        config: FragmentCleanupSearchConfig,
    ) -> dict[str, object]:
        summary = reports[config]
        return {
            "config": asdict(config),
            "quality_gate": summary["quality_gate"],
            "deltas": summary["deltas"],
            "balanced": summary["balanced"],
            "clean": summary.get("clean"),
            "clean_deltas": summary.get("clean_deltas"),
            "per_song_worst": summary["per_song_worst"],
            "clean_per_song_worst": summary.get(
                "clean_per_song_worst"
            ),
            "timing": summary["timing"],
            "clean_timing": summary.get("clean_timing"),
            "clean_safety_gate": summary.get("clean_safety_gate"),
            "selection_gate": summary.get("selection_gate"),
        }

    selected_metrics = reports.get(selected) if selected is not None else None
    fixed_v1_metrics = reports.get(FROZEN_V1_CLEANUP_CONFIG)
    return {
        "report_schema_version": 4,
        "report_kind": "babyslakh-fragment-cleanup-holdout",
        "dataset": {
            "record": BABYSLAKH_RECORD,
            "license": BABYSLAKH_LICENSE,
            "archive_md5": BABYSLAKH_ARCHIVE_MD5,
        },
        "evidence": {
            "analysis_mode": MIXED_ENHANCED_ANALYSIS_MODE,
            "fusion_version": TRANSCRIPTION_FUSION_VERSION,
            "frozen_v2_config": asdict(
                FROZEN_MIXED_ENHANCED_V2_CONFIG
            ),
            "evidence_dtype": "<f2",
        },
        "postprocess_version": POSTPROCESS_VERSION,
        "production_release_mode": "explicit_opt_in_experimental",
        "automatic_actions_evaluated": True,
        "execution_policy": {
            "safe_default_profile": PRESERVE_CLEANUP_PROFILE,
            "experimental_profiles": [
                BALANCED_CLEANUP_PROFILE,
                CLEAN_CLEANUP_PROFILE,
            ],
            "requires_explicit_user_opt_in": True,
            "automatic_actions_enabled_for_experimental_profiles": True,
            "holdout_release_gate_passed": selected is not None,
        },
        "holdout_track_ids": list(HOLDOUT_TRACKS),
        "closed_grid": {
            "configuration_count": len(fragment_cleanup_grid()),
            "evaluated_count": len(ordered_configs),
            "parameter_order": [
                "max_merge_gap_frames",
                "nms_min_overlap_ratio",
                "nms_onset_distance_frames",
                "max_weak_onset_prominence",
                "clean_max_confidence",
            ],
            "values": {
                "max_merge_gap_frames": [0, 1, 2],
                "nms_min_overlap_ratio": [0.80, 0.85, 0.90],
                "nms_onset_distance_frames": [1, 2],
                "max_weak_onset_prominence": [0.05, 0.10, 0.15],
                "clean_max_confidence": [0.25, 0.30],
            },
        },
        "balanced_passing_config_count": balanced_passing_count,
        "clean_safety_passing_config_count": clean_passing_count,
        "passing_config_count": passing_count,
        "selected_config": (
            asdict(selected) if selected is not None else None
        ),
        "annotation_only": False,
        "grid_recommendation_only": True,
        "active_experimental_config": asdict(
            FROZEN_V1_CLEANUP_CONFIG
        ),
        "selected_metrics": selected_metrics,
        "fixed_v1_config": asdict(FROZEN_V1_CLEANUP_CONFIG),
        "fixed_v1_metrics": fixed_v1_metrics,
        "grid_results": [
            compact(config) for config in ordered_configs
        ],
        "runtime": runtime or {},
    }


def run_cleanup_holdout(
    dataset_dir: Path,
    *,
    work_root: Path,
) -> dict[str, object]:
    """Run cleanup-only holdout evaluation without the 243 fusion search."""

    dataset_dir = Path(dataset_dir).resolve()
    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    configs = fragment_cleanup_grid()
    evaluations_by_config: dict[
        FragmentCleanupSearchConfig,
        list[FragmentTrackEvaluation],
    ] = {config: [] for config in configs}
    runtime_tracks: list[dict[str, object]] = []

    backend_started = time.perf_counter()
    basic_pitch, inference, note_creation, onnxruntime = _import_basic_pitch()
    backend_import_seconds = time.perf_counter() - backend_started
    model_holder: dict[str, object] = {}
    model_load_and_prewarm_seconds = 0.0

    def model_provider():
        nonlocal model_load_and_prewarm_seconds
        model = model_holder.get("model")
        if model is None:
            started = time.perf_counter()
            model = _onnx_model(basic_pitch, inference, onnxruntime)
            model.predict(
                np.zeros(
                    (1, int(inference.AUDIO_N_SAMPLES), 1),
                    dtype=np.float32,
                )
            )
            model_load_and_prewarm_seconds += (
                time.perf_counter() - started
            )
            model_holder["model"] = model
        return model

    checkpoint_reused_count = 0
    onnx_generated_count = 0
    for track_number, track_id in enumerate(HOLDOUT_TRACKS, start=1):
        _progress(
            (
                f"Cleanup holdout {track_id} "
                f"({track_number}/{len(HOLDOUT_TRACKS)})"
            )
        )
        audio_path, midi_path = _track_inputs(dataset_dir, track_id)
        with _checkpointed_cleanup_evidence(
            audio_path,
            track_id,
            model_provider=model_provider,
            inference=inference,
            note_creation=note_creation,
            work_root=work_root,
        ) as (evidence, evidence_runtime):
            raw_decode_started = time.perf_counter()
            raw_events = _raw_frame_events(
                {
                    "note": evidence.frame,
                    "onset": evidence.onset,
                },
                note_creation,
                FROZEN_MIXED_ENHANCED_V2_CONFIG,
            )
            raw_decode_seconds = (
                time.perf_counter() - raw_decode_started
            )
            reference = _reference_frame_notes(
                midi_path,
                evidence.times_ms,
            )
            case = FragmentCleanupEvidenceCase(
                track_id=track_id,
                reference=reference,
                raw_events=raw_events,
                frame_evidence=evidence.frame,
                onset_evidence=evidence.onset,
                duration_seconds=evidence.duration_seconds,
                total_decode_seconds=raw_decode_seconds,
                onset_threshold=(
                    FROZEN_MIXED_ENHANCED_V2_CONFIG.onset_threshold
                ),
                frame_threshold=(
                    FROZEN_MIXED_ENHANCED_V2_CONFIG.frame_threshold
                ),
            )
            evaluated = _evaluate_fragment_cleanup_case(
                case,
                configs,
                progress_label=track_id,
            )
            for config, evaluation in evaluated.items():
                evaluations_by_config[config].append(evaluation)
            source = str(evidence_runtime["evidence_source"])
            checkpoint_reused_count += int(source == "checkpoint")
            onnx_generated_count += int(source == "onnx")
            runtime_tracks.append(
                {
                    "track_id": track_id,
                    "duration_seconds": evidence.duration_seconds,
                    **evidence_runtime,
                    "raw_decode_seconds": raw_decode_seconds,
                    "reference_note_count": len(reference),
                    "raw_candidate_count": len(raw_events),
                }
            )

    reports, metric_reuse = summarize_cleanup_grid_with_metric_reuse(
        evaluations_by_config
    )
    return cleanup_holdout_report(
        reports,
        runtime={
            "backend_import_seconds": backend_import_seconds,
            "model_load_and_prewarm_seconds": (
                model_load_and_prewarm_seconds
            ),
            "checkpoint_schema_version": (
                CLEANUP_CHECKPOINT_SCHEMA_VERSION
            ),
            "checkpoint_reused_track_count": checkpoint_reused_count,
            "onnx_generated_track_count": onnx_generated_count,
            "metric_reuse": metric_reuse,
            "tracks": runtime_tracks,
            "timing_scope": {
                "evidence_seconds": (
                    "stream decode/resample, HPSS, and ONNX evidence"
                ),
                "raw_decode_seconds": (
                    "one shared output_to_notes_polyphonic decode"
                ),
                "postprocess_share": (
                    "postprocess / (raw decode + postprocess)"
                ),
            },
        },
    )


def write_cleanup_holdout_report(
    path: Path,
    report: dict[str, object],
) -> None:
    """Atomically write an explicitly requested cleanup report."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output)


def _parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=USER_DATA_DIR / "benchmarks" / "BabySlakh",
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        help="Use an existing extracted BabySlakh directory.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
    )
    parser.add_argument(
        "--cleanup-holdout",
        action="store_true",
        help=(
            "Run only the 108-config fragment-cleanup holdout using "
            "the frozen v2 mixed-enhanced evidence configuration."
        ),
    )
    parser.add_argument(
        "--cleanup-output",
        type=Path,
        help=(
            "Explicit output path required with --cleanup-holdout."
        ),
    )
    parser.add_argument(
        "--runtime-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--runtime-config",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--runtime-output",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=USER_DATA_DIR
        / "benchmarks"
        / "BabySlakh"
        / "transcription_report.json",
    )
    parser.add_argument(
        "--tuning-checkpoint",
        type=Path,
        default=USER_DATA_DIR
        / "benchmarks"
        / "BabySlakh"
        / "tuning_checkpoint.json",
    )
    args = parser.parse_args(argv)
    if args.cleanup_holdout and args.cleanup_output is None:
        parser.error(
            "--cleanup-holdout requires an explicit --cleanup-output"
        )
    if args.cleanup_output is not None and not args.cleanup_holdout:
        parser.error(
            "--cleanup-output is only valid with --cleanup-holdout"
        )
    if args.cleanup_holdout and (
        args.download_only or args.runtime_worker
    ):
        parser.error(
            "--cleanup-holdout cannot be combined with another mode"
        )
    return args


def main() -> int:
    args = _parse_args()
    if args.runtime_worker:
        if (
            args.dataset_dir is None
            or args.runtime_config is None
            or args.runtime_output is None
        ):
            raise SystemExit(
                "runtime worker requires dataset, config, and output"
            )
        selected = SearchConfig(
            **json.loads(
                args.runtime_config.read_text(encoding="utf-8")
            )
        )
        measurement = _measure_holdout_in_fresh_runtime(
            args.dataset_dir.resolve(),
            selected,
            work_root=args.cache_dir.resolve() / "runtime-work",
        )
        args.runtime_output.write_text(
            json.dumps(measurement, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    dataset_dir = (
        args.dataset_dir.resolve()
        if args.dataset_dir is not None
        else download_dataset(args.cache_dir.resolve())
    )
    if args.download_only:
        print(
            f"BabySlakh verified ({BABYSLAKH_LICENSE}); "
            f"source: {BABYSLAKH_RECORD}"
        )
        return 0
    if args.cleanup_holdout:
        report = run_cleanup_holdout(
            dataset_dir,
            work_root=args.cache_dir.resolve() / "cleanup-runtime",
        )
        assert args.cleanup_output is not None
        write_cleanup_holdout_report(
            args.cleanup_output.resolve(),
            report,
        )
        selected = report["selected_config"]
        _progress(
            (
                "Cleanup holdout complete: "
                f"selected_config={selected!r}, "
                f"annotation_only={report['annotation_only']!r}, "
                f"output={args.cleanup_output.resolve()}"
            )
        )
        return 0
    report = run_benchmark(
        dataset_dir,
        tuning_checkpoint=args.tuning_checkpoint,
        runtime_subprocess=True,
        runtime_work_root=args.cache_dir.resolve() / "runtime-probe",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _progress(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["quality_gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
