"""Bounded, diagnostic-only rhythm context for transcription candidates."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
from typing import Callable, Literal, Mapping, Protocol, Sequence

import numpy as np

from bdo_music_composer.transcription.rhythm_grid import (
    RhythmGrid,
    rhythm_analysis_identity,
    rhythm_position_at,
    rhythmic_duration_fit,
    transcription_candidate_revision,
)
from bdo_music_composer.transcription.rhythm_decode import (
    RhythmBoundaryObservation,
    RhythmDecodeCancelled,
    decode_rhythm_boundaries,
)
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentSidecar,
)


RHYTHM_CLEANUP_VERSION = "rhythm-cleanup-diagnostic-v2"
RHYTHM_CANDIDATE_CHUNK_SIZE = 256
RHYTHM_EVIDENCE_CHUNK_FRAMES = 2_048
RHYTHM_MAX_FEATURE_WINDOW_FRAMES = 256

RhythmDecodeState = Literal[
    "KEEP_SINGLE",
    "MERGE_CONTINUATION",
    "KEEP_REATTACK",
    "EXTEND_OFFSET",
    "SUPPRESS_EXTRA",
]
RhythmProposalKind = Literal[
    "keep",
    "merge_same_pitch",
    "extend_offset",
    "suppress_extra",
    "propose_missing",
]

_DECODE_STATES = frozenset(
    {
        "KEEP_SINGLE",
        "MERGE_CONTINUATION",
        "KEEP_REATTACK",
        "EXTEND_OFFSET",
        "SUPPRESS_EXTRA",
    }
)
_PROPOSAL_KINDS = frozenset(
    {
        "keep",
        "merge_same_pitch",
        "extend_offset",
        "suppress_extra",
        "propose_missing",
    }
)


class RhythmDiagnosticCancelled(RuntimeError):
    pass


class CandidateLike(Protocol):
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float


CancelCallback = Callable[[], bool]


def _finite(value: object, field_name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be finite") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _bounded(value: object, field_name: str) -> float:
    numeric = _finite(value, field_name)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must be in [0, 1]")
    return numeric


def _value(item: object, field_name: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


def _cancel_if_requested(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise RhythmDiagnosticCancelled()


@dataclass(frozen=True, slots=True)
class RhythmCandidateFeatures:
    candidate_id: str
    beat_phase: float
    nearest_subdivision_distance_beats: float
    duration_beats: float
    duration_fit: float
    inter_onset_fit: float
    onset_support: float
    boundary_frame_continuity: float
    contour_stability: float
    chord_support: float
    voice_continuity: float

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id or "")
        if not candidate_id or len(candidate_id) > 256:
            raise ValueError("candidate features require a valid candidate id")
        phase = _finite(self.beat_phase, "beat_phase")
        distance = _finite(
            self.nearest_subdivision_distance_beats,
            "nearest_subdivision_distance_beats",
        )
        duration_beats = _finite(self.duration_beats, "duration_beats")
        if not 0.0 <= phase < 1.0:
            raise ValueError("beat_phase must be in [0, 1)")
        if distance < 0.0 or duration_beats < 0.0:
            raise ValueError("rhythm distances and durations must be non-negative")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "beat_phase", phase)
        object.__setattr__(
            self,
            "nearest_subdivision_distance_beats",
            distance,
        )
        object.__setattr__(self, "duration_beats", duration_beats)
        for field_name in (
            "duration_fit",
            "inter_onset_fit",
            "onset_support",
            "boundary_frame_continuity",
            "contour_stability",
            "chord_support",
            "voice_continuity",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class RhythmCleanupProposal:
    """One explainable review proposal; never an editor mutation."""

    kind: RhythmProposalKind
    decode_state: RhythmDecodeState
    source_candidate_ids: tuple[str, ...]
    confidence: float
    reason_codes: tuple[str, ...]
    target_start_ms: float | None = None
    target_duration_ms: float | None = None
    target_pitch: int | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind)
        state = str(self.decode_state)
        source_ids = tuple(dict.fromkeys(str(value) for value in self.source_candidate_ids))
        reasons = tuple(dict.fromkeys(str(value) for value in self.reason_codes if value))
        if kind not in _PROPOSAL_KINDS:
            raise ValueError("unknown rhythm proposal kind")
        if state not in _DECODE_STATES:
            raise ValueError("unknown rhythm decode state")
        if not source_ids or any(not value or len(value) > 256 for value in source_ids):
            raise ValueError("a rhythm proposal requires source candidate ids")
        if kind == "merge_same_pitch" and len(source_ids) < 2:
            raise ValueError("a merge proposal requires at least two sources")
        if not reasons:
            raise ValueError("a rhythm proposal requires audit reasons")
        confidence = _bounded(self.confidence, "proposal confidence")
        start = (
            None
            if self.target_start_ms is None
            else _finite(self.target_start_ms, "target_start_ms")
        )
        duration = (
            None
            if self.target_duration_ms is None
            else _finite(self.target_duration_ms, "target_duration_ms")
        )
        if start is not None and start < 0.0:
            raise ValueError("target_start_ms must be non-negative")
        if duration is not None and duration <= 0.0:
            raise ValueError("target_duration_ms must be positive")
        pitch = None if self.target_pitch is None else int(self.target_pitch)
        if pitch is not None and not 0 <= pitch <= 127:
            raise ValueError("target_pitch must be a MIDI pitch")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "decode_state", state)
        object.__setattr__(self, "source_candidate_ids", source_ids)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "target_start_ms", start)
        object.__setattr__(self, "target_duration_ms", duration)
        object.__setattr__(self, "target_pitch", pitch)

    @property
    def lineage_ids(self) -> tuple[str, ...]:
        return self.source_candidate_ids


@dataclass(frozen=True, slots=True)
class RhythmDiagnosticSidecar:
    """Disposable diagnostics bound to immutable evidence and candidates."""

    identity: str
    evidence_cache_key: str
    candidate_revision: str
    grid: RhythmGrid
    features: tuple[RhythmCandidateFeatures, ...]
    proposals: tuple[RhythmCleanupProposal, ...]
    processed_candidate_count: int
    evidence_window_read_count: int
    alignment: RhythmAlignmentSidecar | None = None
    version: str = RHYTHM_CLEANUP_VERSION
    automatic_actions_enabled: bool = False

    def __post_init__(self) -> None:
        identity = str(self.identity or "")
        cache_key = str(self.evidence_cache_key or "")
        revision = str(self.candidate_revision or "")
        if not identity or not cache_key or not revision:
            raise ValueError("a rhythm sidecar requires bound identities")
        version = str(self.version or "")
        if version != RHYTHM_CLEANUP_VERSION:
            raise ValueError("unsupported rhythm diagnostic version")
        expected_identity = rhythm_analysis_identity(
            evidence_cache_key=cache_key,
            candidate_revision=revision,
            grid=self.grid,
            algorithm_version=version,
        )
        if identity != expected_identity:
            raise ValueError("rhythm sidecar identity does not match lineage")
        features = tuple(self.features)
        proposals = tuple(self.proposals)
        feature_ids = {item.candidate_id for item in features}
        if len(feature_ids) != len(features):
            raise ValueError("rhythm feature candidate ids must be unique")
        for proposal in proposals:
            if not set(proposal.source_candidate_ids).issubset(feature_ids):
                raise ValueError("proposal lineage is outside the sidecar")
        processed = int(self.processed_candidate_count)
        reads = int(self.evidence_window_read_count)
        if processed < 0 or reads < 0 or processed != len(features):
            raise ValueError("invalid rhythm diagnostic counts")
        if bool(self.automatic_actions_enabled):
            raise ValueError("Phase 1 rhythm diagnostics cannot enable actions")
        alignment = self.alignment
        if alignment is not None and (
            alignment.evidence_cache_key != cache_key
            or alignment.candidate_revision != revision
        ):
            raise ValueError("rhythm alignment lineage is outside the sidecar")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "evidence_cache_key", cache_key)
        object.__setattr__(self, "candidate_revision", revision)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "proposals", proposals)
        object.__setattr__(self, "processed_candidate_count", processed)
        object.__setattr__(self, "evidence_window_read_count", reads)
        object.__setattr__(self, "alignment", alignment)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "automatic_actions_enabled", False)

    def is_current(
        self,
        *,
        evidence_cache_key: str,
        candidates: Sequence[object],
        grid: RhythmGrid,
    ) -> bool:
        revision = transcription_candidate_revision(candidates)
        identity = rhythm_analysis_identity(
            evidence_cache_key=str(evidence_cache_key),
            candidate_revision=revision,
            grid=grid,
            algorithm_version=self.version,
        )
        return (
            self.evidence_cache_key == str(evidence_cache_key)
            and self.candidate_revision == revision
            and self.identity == identity
        )


@dataclass(frozen=True, slots=True)
class _CandidateRecord:
    candidate: object
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float
    start_frame: int
    end_frame: int

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


def _validated_evidence(
    frame_times_ms: np.ndarray,
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    contour_evidence: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    times = np.asarray(frame_times_ms)
    frame = np.asarray(frame_evidence)
    onset = np.asarray(onset_evidence)
    contour = None if contour_evidence is None else np.asarray(contour_evidence)
    if times.ndim != 1 or not len(times):
        raise ValueError("frame times must be a non-empty vector")
    if frame.ndim != 2 or onset.shape != frame.shape:
        raise ValueError("frame and onset evidence must share one matrix shape")
    if frame.shape[0] != len(times):
        raise ValueError("evidence and exact frame times must share one axis")
    if contour is not None and (
        contour.ndim != 2 or contour.shape[0] != len(times)
    ):
        raise ValueError("contour evidence must share the exact time axis")
    return times, frame, onset, contour


def _records(
    candidates: Sequence[object],
    times: np.ndarray,
    cancelled: CancelCallback | None = None,
) -> tuple[_CandidateRecord, ...]:
    output: list[_CandidateRecord] = []
    for index, candidate in enumerate(candidates):
        if index % RHYTHM_CANDIDATE_CHUNK_SIZE == 0:
            _cancel_if_requested(cancelled)
        candidate_id = str(_value(candidate, "candidate_id", "") or "")
        pitch = int(_value(candidate, "pitch", -1))
        start = _finite(_value(candidate, "start_ms", 0.0), "candidate start_ms")
        duration = _finite(
            _value(candidate, "duration_ms", 0.0),
            "candidate duration_ms",
        )
        confidence = _bounded(
            _value(candidate, "confidence", 0.0),
            "candidate confidence",
        )
        if (
            not candidate_id
            or len(candidate_id) > 256
            or not 0 <= pitch <= 127
            or start < 0.0
            or duration <= 0.0
        ):
            raise ValueError("invalid transcription candidate")
        start_frame = min(
            len(times) - 1,
            max(0, int(np.searchsorted(times, start, side="left"))),
        )
        end_frame = min(
            len(times),
            max(
                start_frame + 1,
                int(
                    np.searchsorted(
                        times,
                        start + duration,
                        side="left",
                    )
                ),
            ),
        )
        output.append(
            _CandidateRecord(
                candidate,
                candidate_id,
                pitch,
                start,
                duration,
                confidence,
                start_frame,
                end_frame,
            )
        )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.start_ms,
                item.pitch,
                item.duration_ms,
                item.candidate_id,
            ),
        )
    )


def _window_bounds(start: int, end: int, frame_count: int) -> tuple[int, int]:
    lo = max(0, min(frame_count - 1, int(start)))
    hi = max(lo + 1, min(frame_count, int(end)))
    window_limit = min(
        RHYTHM_EVIDENCE_CHUNK_FRAMES,
        RHYTHM_MAX_FEATURE_WINDOW_FRAMES,
    )
    if hi - lo > window_limit:
        hi = lo + window_limit
    return lo, hi


def _safe_max(values: np.ndarray) -> float:
    if not values.size:
        return 0.0
    numeric = float(np.max(values))
    return max(0.0, min(1.0, numeric)) if math.isfinite(numeric) else 0.0


def _safe_mean(values: np.ndarray) -> float:
    if not values.size:
        return 0.0
    numeric = float(np.mean(values))
    return max(0.0, min(1.0, numeric)) if math.isfinite(numeric) else 0.0


def _ratio_fit(value_beats: float) -> float:
    if value_beats <= 0.0:
        return 0.0
    expected = (
        0.125,
        1.0 / 6.0,
        0.25,
        1.0 / 3.0,
        0.5,
        2.0 / 3.0,
        0.75,
        1.0,
        1.5,
        2.0,
        3.0,
        4.0,
    )
    distance = min(abs(value_beats - item) for item in expected)
    return max(0.0, min(1.0, 1.0 - distance / max(0.125, value_beats * 0.25)))


def _regular_repeat(
    previous_previous: _CandidateRecord | None,
    previous: _CandidateRecord,
    current: _CandidateRecord,
) -> bool:
    if previous_previous is None:
        return False
    left = previous.start_ms - previous_previous.start_ms
    right = current.start_ms - previous.start_ms
    return (
        left > 0.0
        and right > 0.0
        and abs(left - right) <= max(20.0, min(left, right) * 0.15)
    )


def _decode_pitch_proposals(
    pitch_records: Sequence[_CandidateRecord],
    feature_by_id: Mapping[str, RhythmCandidateFeatures],
    grid: RhythmGrid,
    cancelled: CancelCallback | None,
) -> tuple[RhythmCleanupProposal, ...]:
    """Decode and coalesce one pitch path into non-overlapping proposals."""

    observations: list[RhythmBoundaryObservation] = []
    for index, current in enumerate(pitch_records):
        if index % RHYTHM_CANDIDATE_CHUNK_SIZE == 0:
            _cancel_if_requested(cancelled)
        features = feature_by_id[current.candidate_id]
        previous = pitch_records[index - 1] if index else None
        position = rhythm_position_at(grid, current.start_ms)
        beat_ms = 60_000.0 / position.bpm
        observations.append(
            RhythmBoundaryObservation(
                candidate_id=current.candidate_id,
                previous_candidate_id=(
                    None if previous is None else previous.candidate_id
                ),
                candidate_confidence=current.confidence,
                duration_beats=features.duration_beats,
                grid_distance_beats=(
                    features.nearest_subdivision_distance_beats
                ),
                onset_support=features.onset_support,
                boundary_continuity=(
                    features.boundary_frame_continuity
                ),
                contour_stability=features.contour_stability,
                chord_support=features.chord_support,
                voice_continuity=features.voice_continuity,
                inter_onset_fit=features.inter_onset_fit,
                gap_beats=(
                    None
                    if previous is None
                    else (current.start_ms - previous.end_ms) / beat_ms
                ),
                regular_repeat=(
                    False
                    if previous is None
                    else _regular_repeat(
                        pitch_records[index - 2] if index >= 2 else None,
                        previous,
                        current,
                    )
                ),
            )
        )
    try:
        path = decode_rhythm_boundaries(
            observations,
            cancelled=cancelled,
        )
    except RhythmDecodeCancelled as exc:
        raise RhythmDiagnosticCancelled() from exc

    records_by_id = {item.candidate_id: item for item in pitch_records}
    output: list[RhythmCleanupProposal] = []
    merge_ids: list[str] = []
    merge_confidences: list[float] = []
    merge_reasons: list[str] = []

    def flush_merge() -> None:
        if len(merge_ids) < 2:
            merge_ids.clear()
            merge_confidences.clear()
            merge_reasons.clear()
            return
        records = [records_by_id[candidate_id] for candidate_id in merge_ids]
        first = records[0]
        output.append(
            RhythmCleanupProposal(
                kind="merge_same_pitch",
                decode_state="MERGE_CONTINUATION",
                source_candidate_ids=tuple(merge_ids),
                confidence=min(merge_confidences),
                reason_codes=tuple(dict.fromkeys(merge_reasons)),
                target_start_ms=first.start_ms,
                target_duration_ms=(
                    max(item.end_ms for item in records) - first.start_ms
                ),
                target_pitch=first.pitch,
            )
        )
        merge_ids.clear()
        merge_confidences.clear()
        merge_reasons.clear()

    for decision in path.decisions:
        if decision.state == "MERGE_CONTINUATION":
            previous_id = decision.previous_candidate_id
            if previous_id is None:
                raise ValueError("merge decision has no predecessor")
            if not merge_ids:
                merge_ids.append(previous_id)
            elif merge_ids[-1] != previous_id:
                flush_merge()
                merge_ids.append(previous_id)
            merge_ids.append(decision.candidate_id)
            merge_confidences.append(decision.confidence)
            merge_reasons.extend(decision.reason_codes)
            continue

        flush_merge()
        if decision.state == "SUPPRESS_EXTRA":
            output.append(
                RhythmCleanupProposal(
                    kind="suppress_extra",
                    decode_state="SUPPRESS_EXTRA",
                    source_candidate_ids=(decision.candidate_id,),
                    confidence=decision.confidence,
                    reason_codes=decision.reason_codes,
                )
            )
    flush_merge()
    return tuple(output)


def analyse_project_rhythm_diagnostics(
    *,
    evidence_cache_key: str,
    candidates: Sequence[object],
    grid: RhythmGrid,
    frame_times_ms: np.ndarray,
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    contour_evidence: np.ndarray | None = None,
    frame_midi_min: int = 21,
    contour_midi_min: int = 21,
    contour_bins_per_semitone: int = 3,
    cancelled: CancelCallback | None = None,
) -> RhythmDiagnosticSidecar:
    """Build a bounded review sidecar without returning changed candidates."""

    if grid.source != "project":
        raise ValueError("Phase 1 accepts only an explicit project grid")
    _cancel_if_requested(cancelled)
    times, frame, onset, contour = _validated_evidence(
        frame_times_ms,
        frame_evidence,
        onset_evidence,
        contour_evidence,
    )
    candidate_tuple = tuple(candidates)
    records = _records(candidate_tuple, times, cancelled)
    starts = [item.start_ms for item in records]
    feature_output: list[RhythmCandidateFeatures] = []
    feature_by_id: dict[str, RhythmCandidateFeatures] = {}
    previous_by_pitch: dict[int, _CandidateRecord] = {}
    recent_by_pitch: dict[int, _CandidateRecord] = {}
    evidence_reads = 0

    for chunk_start in range(0, len(records), RHYTHM_CANDIDATE_CHUNK_SIZE):
        _cancel_if_requested(cancelled)
        chunk = records[
            chunk_start : chunk_start + RHYTHM_CANDIDATE_CHUNK_SIZE
        ]
        for offset, record in enumerate(chunk):
            if offset % 256 == 0:
                _cancel_if_requested(cancelled)
            position = rhythm_position_at(grid, record.start_ms)
            frame_col = record.pitch - int(frame_midi_min)
            onset_support = 0.0
            frame_support = 0.0
            contour_stability = 0.0
            if 0 <= frame_col < frame.shape[1]:
                onset_lo = max(0, record.start_frame - 2)
                onset_hi = min(len(times), record.start_frame + 3)
                onset_support = _safe_max(
                    onset[onset_lo:onset_hi, frame_col]
                )
                evidence_reads += 1
                frame_lo, frame_hi = _window_bounds(
                    record.start_frame,
                    record.end_frame,
                    len(times),
                )
                frame_support = _safe_mean(
                    frame[frame_lo:frame_hi, frame_col]
                )
                evidence_reads += 1
                if contour is not None:
                    bins = max(1, int(contour_bins_per_semitone))
                    centre = (
                        record.pitch - int(contour_midi_min)
                    ) * bins
                    contour_lo = max(0, centre - bins // 2)
                    contour_hi = min(
                        contour.shape[1],
                        centre + bins // 2 + 1,
                    )
                    if contour_hi > contour_lo:
                        contour_stability = _safe_mean(
                            np.max(
                                contour[
                                    frame_lo:frame_hi,
                                    contour_lo:contour_hi,
                                ],
                                axis=1,
                            )
                        )
                        evidence_reads += 1

            previous = previous_by_pitch.get(record.pitch)
            boundary_continuity = frame_support
            inter_onset_fit = 0.0
            if previous is not None:
                beat_ms = 60_000.0 / position.bpm
                inter_onset_fit = _ratio_fit(
                    (record.start_ms - previous.start_ms) / beat_ms
                )
                if 0 <= frame_col < frame.shape[1]:
                    boundary_lo = max(0, previous.end_frame - 1)
                    boundary_hi = min(
                        len(times),
                        max(boundary_lo + 1, record.start_frame + 1),
                    )
                    if boundary_hi - boundary_lo <= 16:
                        boundary_continuity = _safe_mean(
                            frame[boundary_lo:boundary_hi, frame_col]
                        )
                        evidence_reads += 1

            lo = bisect_left(starts, record.start_ms - 40.0)
            hi = bisect_right(starts, record.start_ms + 40.0)
            simultaneous_pitches = {
                records[index].pitch
                for index in range(lo, hi)
                if records[index].candidate_id != record.candidate_id
            }
            chord_support = min(1.0, len(simultaneous_pitches) / 3.0)

            nearest_voice: _CandidateRecord | None = None
            for pitch in range(max(0, record.pitch - 12), min(127, record.pitch + 12) + 1):
                candidate = recent_by_pitch.get(pitch)
                if candidate is None or candidate.start_ms >= record.start_ms:
                    continue
                if nearest_voice is None or candidate.start_ms > nearest_voice.start_ms:
                    nearest_voice = candidate
            voice_continuity = 0.0
            if nearest_voice is not None:
                beat_ms = 60_000.0 / position.bpm
                gap = max(0.0, record.start_ms - nearest_voice.end_ms)
                pitch_distance = abs(record.pitch - nearest_voice.pitch)
                voice_continuity = max(
                    0.0,
                    min(
                        1.0,
                        (1.0 - min(1.0, gap / max(1.0, beat_ms)))
                        * (1.0 - min(1.0, pitch_distance / 12.0)),
                    ),
                )

            duration_beats = record.duration_ms * position.bpm / 60_000.0
            features = RhythmCandidateFeatures(
                candidate_id=record.candidate_id,
                beat_phase=position.phase,
                nearest_subdivision_distance_beats=(
                    position.nearest_subdivision_distance_beats
                ),
                duration_beats=duration_beats,
                duration_fit=rhythmic_duration_fit(
                    record.duration_ms,
                    position.bpm,
                ),
                inter_onset_fit=inter_onset_fit,
                onset_support=onset_support,
                boundary_frame_continuity=boundary_continuity,
                contour_stability=contour_stability,
                chord_support=chord_support,
                voice_continuity=voice_continuity,
            )
            feature_output.append(features)
            feature_by_id[record.candidate_id] = features
            previous_by_pitch[record.pitch] = record
            recent_by_pitch[record.pitch] = record

    _cancel_if_requested(cancelled)
    proposal_output: list[RhythmCleanupProposal] = []
    by_pitch: dict[int, list[_CandidateRecord]] = {}
    for record in records:
        by_pitch.setdefault(record.pitch, []).append(record)
    for pitch in sorted(by_pitch):
        _cancel_if_requested(cancelled)
        proposal_output.extend(
            _decode_pitch_proposals(
                by_pitch[pitch],
                feature_by_id,
                grid,
                cancelled,
            )
        )

    feature_tuple = tuple(
        sorted(feature_output, key=lambda item: item.candidate_id)
    )
    proposal_tuple = tuple(
        sorted(
            proposal_output,
            key=lambda item: (
                item.source_candidate_ids,
                item.kind,
                item.reason_codes,
            ),
        )
    )
    revision = transcription_candidate_revision(candidate_tuple)
    identity = rhythm_analysis_identity(
        evidence_cache_key=str(evidence_cache_key),
        candidate_revision=revision,
        grid=grid,
        algorithm_version=RHYTHM_CLEANUP_VERSION,
    )
    _cancel_if_requested(cancelled)
    return RhythmDiagnosticSidecar(
        identity=identity,
        evidence_cache_key=str(evidence_cache_key),
        candidate_revision=revision,
        grid=grid,
        features=feature_tuple,
        proposals=proposal_tuple,
        processed_candidate_count=len(feature_tuple),
        evidence_window_read_count=evidence_reads,
    )


__all__ = [
    "RHYTHM_CANDIDATE_CHUNK_SIZE",
    "RHYTHM_CLEANUP_VERSION",
    "RHYTHM_EVIDENCE_CHUNK_FRAMES",
    "RhythmCandidateFeatures",
    "RhythmCleanupProposal",
    "RhythmDecodeState",
    "RhythmDiagnosticCancelled",
    "RhythmDiagnosticSidecar",
    "analyse_project_rhythm_diagnostics",
]
