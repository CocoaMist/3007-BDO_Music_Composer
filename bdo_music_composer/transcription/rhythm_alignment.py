"""Beat-aware, non-destructive timing projection for transcription candidates.

The Basic Pitch evidence timeline remains authoritative evidence.  This module
derives a disposable musical-time view which can be previewed or promoted by
the editor without rewriting cached evidence or the transcription session.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Sequence

import numpy as np

from bdo_music_composer.transcription.rhythm_grid import (
    ProjectRhythmSettings,
    RhythmGrid,
    RhythmTempoSegment,
    rhythm_position_at,
    transcription_candidate_revision,
)


RHYTHM_ALIGNMENT_VERSION = "rhythm-alignment-v2-source-clock"
RhythmAlignmentProfile = Literal["raw", "auto", "strict_1_64"]
CancelCallback = Callable[[], bool]

_AUTO_STEPS: tuple[tuple[float, int, bool], ...] = (
    (1.0, 1, False),
    (0.5, 2, False),
    (1.0 / 3.0, 3, True),
    (0.25, 4, False),
    (1.0 / 6.0, 6, True),
    (0.125, 8, False),
    (1.0 / 12.0, 12, True),
    (0.0625, 16, False),
)


class RhythmAlignmentCancelled(RuntimeError):
    pass


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
        raise RhythmAlignmentCancelled()


@dataclass(frozen=True, slots=True)
class RhythmAlignmentConfig:
    """Conservative user-facing projection policy."""

    profile: RhythmAlignmentProfile = "auto"
    maximum_local_shift_ms: float = 45.0
    chord_cluster_ms: float = 35.0
    onset_refine_radius_frames: int = 2
    minimum_onset_support: float = 0.35

    def __post_init__(self) -> None:
        profile = str(self.profile)
        if profile not in {"raw", "auto", "strict_1_64"}:
            raise ValueError("unknown rhythm alignment profile")
        maximum = _finite(
            self.maximum_local_shift_ms,
            "maximum_local_shift_ms",
        )
        cluster = _finite(self.chord_cluster_ms, "chord_cluster_ms")
        if maximum < 0.0 or maximum > 500.0:
            raise ValueError("maximum_local_shift_ms must be in [0, 500]")
        if cluster < 0.0 or cluster > 250.0:
            raise ValueError("chord_cluster_ms must be in [0, 250]")
        radius = int(self.onset_refine_radius_frames)
        if radius < 0 or radius > 8:
            raise ValueError("onset_refine_radius_frames must be in [0, 8]")
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "maximum_local_shift_ms", maximum)
        object.__setattr__(self, "chord_cluster_ms", cluster)
        object.__setattr__(self, "onset_refine_radius_frames", radius)
        object.__setattr__(
            self,
            "minimum_onset_support",
            _bounded(self.minimum_onset_support, "minimum_onset_support"),
        )


@dataclass(frozen=True, slots=True)
class RhythmGridEstimate:
    """One explainable source-audio beat grid proposal."""

    grid: RhythmGrid
    detected_bpm: float
    detected_origin_audio_ms: float
    confidence: float
    mean_beat_residual_ms: float
    p95_beat_residual_ms: float
    tempo_drift_ratio: float
    used_project_fallback: bool
    beat_count: int

    def __post_init__(self) -> None:
        bpm = _finite(self.detected_bpm, "detected_bpm")
        origin = _finite(
            self.detected_origin_audio_ms,
            "detected_origin_audio_ms",
        )
        if bpm <= 0.0:
            raise ValueError("detected_bpm must be positive")
        for field_name in (
            "mean_beat_residual_ms",
            "p95_beat_residual_ms",
            "tempo_drift_ratio",
        ):
            value = _finite(getattr(self, field_name), field_name)
            if value < 0.0:
                raise ValueError(f"{field_name} must be non-negative")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "detected_bpm", bpm)
        object.__setattr__(self, "detected_origin_audio_ms", origin)
        object.__setattr__(self, "confidence", _bounded(self.confidence, "confidence"))
        object.__setattr__(self, "used_project_fallback", bool(self.used_project_fallback))
        object.__setattr__(self, "beat_count", max(0, int(self.beat_count)))


@dataclass(frozen=True, slots=True)
class RhythmTimingProjection:
    candidate_id: str
    start_ms: float
    duration_ms: float
    raw_start_ms: float
    raw_duration_ms: float
    grid_divisor: int
    triplet: bool
    onset_support: float
    confidence: float
    shift_ms: float
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id or "")
        if not candidate_id:
            raise ValueError("a timing projection requires a candidate id")
        start = _finite(self.start_ms, "start_ms")
        duration = _finite(self.duration_ms, "duration_ms")
        raw_start = _finite(self.raw_start_ms, "raw_start_ms")
        raw_duration = _finite(self.raw_duration_ms, "raw_duration_ms")
        if start < 0.0 or raw_start < 0.0 or duration <= 0.0 or raw_duration <= 0.0:
            raise ValueError("timing projection contains invalid times")
        divisor = int(self.grid_divisor)
        if divisor not in {1, 2, 3, 4, 6, 8, 12, 16}:
            raise ValueError("unsupported timing projection divisor")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "start_ms", start)
        object.__setattr__(self, "duration_ms", duration)
        object.__setattr__(self, "raw_start_ms", raw_start)
        object.__setattr__(self, "raw_duration_ms", raw_duration)
        object.__setattr__(self, "grid_divisor", divisor)
        object.__setattr__(self, "triplet", bool(self.triplet))
        object.__setattr__(self, "onset_support", _bounded(self.onset_support, "onset_support"))
        object.__setattr__(self, "confidence", _bounded(self.confidence, "confidence"))
        object.__setattr__(self, "shift_ms", _finite(self.shift_ms, "shift_ms"))
        reasons = tuple(dict.fromkeys(str(value) for value in self.reason_codes if value))
        if not reasons:
            raise ValueError("a timing projection requires audit reasons")
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class RhythmAlignmentSidecar:
    identity: str
    evidence_cache_key: str
    candidate_revision: str
    estimate: RhythmGridEstimate
    config: RhythmAlignmentConfig
    projections: tuple[RhythmTimingProjection, ...]
    aligned_count: int
    mean_abs_shift_ms: float
    max_abs_shift_ms: float
    version: str = RHYTHM_ALIGNMENT_VERSION
    _projection_by_id: Mapping[str, RhythmTimingProjection] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        identity = str(self.identity or "")
        cache_key = str(self.evidence_cache_key or "")
        revision = str(self.candidate_revision or "")
        if not identity or not cache_key or not revision:
            raise ValueError("a rhythm alignment sidecar requires identities")
        projections = tuple(self.projections)
        ids = [item.candidate_id for item in projections]
        if len(ids) != len(set(ids)):
            raise ValueError("rhythm alignment candidate ids must be unique")
        expected = _alignment_identity(
            evidence_cache_key=cache_key,
            candidate_revision=revision,
            estimate=self.estimate,
            config=self.config,
        )
        if identity != expected:
            raise ValueError("rhythm alignment identity does not match lineage")
        aligned = sum(
            not math.isclose(item.start_ms, item.raw_start_ms, abs_tol=1e-6)
            or not math.isclose(item.duration_ms, item.raw_duration_ms, abs_tol=1e-6)
            for item in projections
        )
        if int(self.aligned_count) != aligned:
            raise ValueError("invalid aligned candidate count")
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "evidence_cache_key", cache_key)
        object.__setattr__(self, "candidate_revision", revision)
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "aligned_count", aligned)
        object.__setattr__(self, "mean_abs_shift_ms", max(0.0, _finite(self.mean_abs_shift_ms, "mean_abs_shift_ms")))
        object.__setattr__(self, "max_abs_shift_ms", max(0.0, _finite(self.max_abs_shift_ms, "max_abs_shift_ms")))
        object.__setattr__(self, "version", str(self.version or ""))
        object.__setattr__(
            self,
            "_projection_by_id",
            MappingProxyType({item.candidate_id: item for item in projections}),
        )

    def projection_for(self, candidate_id: str) -> RhythmTimingProjection | None:
        return self._projection_by_id.get(str(candidate_id))

    def apply_to(self, candidate: object) -> object:
        projection = self.projection_for(str(_value(candidate, "candidate_id", "")))
        if projection is None:
            return candidate
        try:
            return replace(
                candidate,
                start_ms=projection.start_ms,
                duration_ms=projection.duration_ms,
            )
        except TypeError:
            return candidate

    def is_current(self, *, evidence_cache_key: str, candidates: Sequence[object]) -> bool:
        return (
            self.evidence_cache_key == str(evidence_cache_key)
            and self.candidate_revision == transcription_candidate_revision(candidates)
            and self.identity
            == _alignment_identity(
                evidence_cache_key=str(evidence_cache_key),
                candidate_revision=transcription_candidate_revision(candidates),
                estimate=self.estimate,
                config=self.config,
            )
        )


def _alignment_identity(
    *,
    evidence_cache_key: str,
    candidate_revision: str,
    estimate: RhythmGridEstimate,
    config: RhythmAlignmentConfig,
) -> str:
    payload = {
        "cache": str(evidence_cache_key),
        "candidates": str(candidate_revision),
        "version": RHYTHM_ALIGNMENT_VERSION,
        "grid": {
            "bpm": round(estimate.detected_bpm, 6),
            "origin": round(estimate.detected_origin_audio_ms, 6),
            "confidence": round(estimate.confidence, 6),
            "fallback": estimate.used_project_fallback,
        },
        "config": {
            "profile": config.profile,
            "maximum_local_shift_ms": round(config.maximum_local_shift_ms, 6),
            "chord_cluster_ms": round(config.chord_cluster_ms, 6),
            "onset_refine_radius_frames": config.onset_refine_radius_frames,
            "minimum_onset_support": round(config.minimum_onset_support, 6),
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _fallback_estimate(settings: ProjectRhythmSettings) -> RhythmGridEstimate:
    beat_ms = 60_000.0 / settings.bpm
    grid = RhythmGrid(
        source="project",
        beat_origin_audio_ms=settings.beat_origin_audio_ms,
        time_signature=settings.time_signature,
        tempo_segments=(
            RhythmTempoSegment(
                start_ms=0.0,
                end_ms=None,
                bpm=settings.bpm,
                beat_at_start=-settings.beat_origin_audio_ms / beat_ms,
                confidence=0.35,
            ),
        ),
        confidence=0.35,
    )
    return RhythmGridEstimate(
        grid=grid,
        detected_bpm=settings.bpm,
        detected_origin_audio_ms=settings.beat_origin_audio_ms,
        confidence=0.35,
        mean_beat_residual_ms=0.0,
        p95_beat_residual_ms=0.0,
        tempo_drift_ratio=0.0,
        used_project_fallback=True,
        beat_count=0,
    )


def estimate_rhythm_grid_from_evidence(
    settings: ProjectRhythmSettings,
    *,
    frame_times_ms: np.ndarray,
    onset_evidence: np.ndarray,
    cancelled: CancelCallback | None = None,
) -> RhythmGridEstimate:
    """Estimate tempo/phase from cached onset evidence with a safe fallback."""

    _cancel_if_requested(cancelled)
    times = np.asarray(frame_times_ms, dtype=np.float64)
    onset = np.asarray(onset_evidence, dtype=np.float32)
    if times.ndim != 1 or onset.ndim != 2 or len(times) != onset.shape[0] or len(times) < 8:
        return _fallback_estimate(settings)
    deltas = np.diff(times)
    deltas = deltas[np.isfinite(deltas) & (deltas > 0.0)]
    if not len(deltas):
        return _fallback_estimate(settings)
    frame_ms = float(np.median(deltas))
    envelope = np.max(onset, axis=1).astype(np.float32, copy=False)
    if len(envelope) >= 3:
        envelope = np.convolve(envelope, np.asarray((0.25, 0.5, 0.25), dtype=np.float32), mode="same")
    floor = float(np.percentile(envelope, 55.0))
    envelope = np.maximum(0.0, envelope - floor)
    peak = float(np.max(envelope))
    if not math.isfinite(peak) or peak <= 1e-6:
        return _fallback_estimate(settings)
    envelope /= peak
    _cancel_if_requested(cancelled)

    # A small deterministic autocorrelation tracker is used instead of
    # importing librosa's numba-backed beat module here.  The packaged app can
    # therefore align cached evidence even when an optional JIT cache is
    # unavailable or corrupted.
    peak_indices = np.flatnonzero(
        (envelope >= 0.20)
        & (envelope >= np.r_[envelope[0], envelope[:-1]])
        & (envelope >= np.r_[envelope[1:], envelope[-1]])
    )
    if len(peak_indices) < 4:
        return _fallback_estimate(settings)
    minimum_lag = max(2, int(round(60_000.0 / (300.0 * frame_ms))))
    maximum_lag = min(
        len(envelope) // 2,
        int(round(60_000.0 / (30.0 * frame_ms))),
    )
    best_lag = 0
    best_score = -1.0
    for lag in range(minimum_lag, maximum_lag + 1):
        if lag % 32 == 0:
            _cancel_if_requested(cancelled)
        left = envelope[:-lag]
        right = envelope[lag:]
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 1e-9:
            continue
        correlation = float(np.dot(left, right) / denominator)
        bpm = 60_000.0 / (lag * frame_ms)
        prior_distance = abs(math.log2(bpm / settings.bpm))
        prior_fit = math.exp(-0.5 * (prior_distance / 0.35) ** 2)
        score = 0.88 * correlation + 0.12 * prior_fit
        if score > best_score + 1e-12:
            best_lag = lag
            best_score = score
    if best_lag <= 0 or best_score < 0.20:
        return _fallback_estimate(settings)

    phase_scores = np.zeros(best_lag, dtype=np.float64)
    for peak_index in peak_indices:
        phase_scores[int(peak_index) % best_lag] += float(envelope[peak_index])
    phase = int(np.argmax(phase_scores))
    expected = np.arange(phase, len(times), best_lag, dtype=np.int64)
    matched: list[int] = []
    residual_frames: list[int] = []
    radius = max(1, round(best_lag * 0.25))
    for target in expected:
        location = int(np.searchsorted(peak_indices, target, side="left"))
        choices = []
        if location < len(peak_indices):
            choices.append(int(peak_indices[location]))
        if location:
            choices.append(int(peak_indices[location - 1]))
        if not choices:
            continue
        selected = min(choices, key=lambda value: abs(value - int(target)))
        if abs(selected - int(target)) <= radius:
            matched.append(selected)
            residual_frames.append(abs(selected - int(target)))
    beat_indices = np.asarray(sorted(set(matched)), dtype=np.int64)
    if len(beat_indices) < 4:
        return _fallback_estimate(settings)
    detected_bpm = 60_000.0 / (best_lag * frame_ms)

    beat_times = times[beat_indices]
    intervals = np.diff(beat_times)
    median_interval = float(np.median(intervals))
    if median_interval <= 0.0:
        return _fallback_estimate(settings)
    detected_bpm = 60_000.0 / median_interval
    residuals = np.abs(intervals - median_interval)
    mean_residual = float(np.mean(residuals)) if len(residuals) else 0.0
    p95_residual = float(np.percentile(residuals, 95.0)) if len(residuals) else 0.0
    drift_ratio = p95_residual / max(1.0, median_interval)
    regularity = max(0.0, min(1.0, 1.0 - drift_ratio / 0.20))
    support = float(np.mean(envelope[beat_indices]))
    coverage = min(1.0, len(beat_indices) / max(1, len(expected)))
    prior_ratio = max(detected_bpm, settings.bpm) / min(detected_bpm, settings.bpm)
    prior_fit = max(0.0, min(1.0, 1.0 - abs(math.log2(prior_ratio)) / 1.0))
    confidence = max(
        0.0,
        min(
            1.0,
            0.40 * regularity
            + 0.25 * support
            + 0.20 * coverage
            + 0.10 * prior_fit
            + 0.05 * max(0.0, min(1.0, best_score)),
        ),
    )
    if confidence < 0.40:
        return _fallback_estimate(settings)

    anchor = float(beat_times[int(np.argmin(np.abs(beat_times - settings.beat_origin_audio_ms)))])
    beat_ms = 60_000.0 / detected_bpm
    anchor_index = round((anchor - settings.beat_origin_audio_ms) / beat_ms)
    origin = anchor - anchor_index * beat_ms
    grid = RhythmGrid(
        source="onset_evidence",
        beat_origin_audio_ms=origin,
        time_signature=settings.time_signature,
        tempo_segments=(
            RhythmTempoSegment(
                start_ms=0.0,
                end_ms=None,
                bpm=detected_bpm,
                beat_at_start=-origin / beat_ms,
                confidence=confidence,
            ),
        ),
        confidence=confidence,
    )
    return RhythmGridEstimate(
        grid=grid,
        detected_bpm=detected_bpm,
        detected_origin_audio_ms=origin,
        confidence=confidence,
        mean_beat_residual_ms=mean_residual,
        p95_beat_residual_ms=p95_residual,
        tempo_drift_ratio=drift_ratio,
        used_project_fallback=False,
        beat_count=len(beat_indices),
    )


def _refined_onset_ms(
    *,
    raw_start_ms: float,
    pitch: int,
    times: np.ndarray,
    onset: np.ndarray,
    midi_min: int,
    config: RhythmAlignmentConfig,
) -> tuple[float, float]:
    column = int(pitch) - int(midi_min)
    if column < 0 or column >= onset.shape[1] or not len(times):
        return raw_start_ms, 0.0
    centre = int(np.searchsorted(times, raw_start_ms, side="left"))
    centre = max(0, min(len(times) - 1, centre))
    radius = config.onset_refine_radius_frames
    lo = max(0, centre - radius)
    hi = min(len(times), centre + radius + 1)
    values = np.asarray(onset[lo:hi, column], dtype=np.float32)
    if not len(values):
        return raw_start_ms, 0.0
    local = int(np.argmax(values))
    support = float(values[local])
    candidate_ms = float(times[lo + local])
    if support < config.minimum_onset_support or abs(candidate_ms - raw_start_ms) > 30.0:
        return raw_start_ms, support
    return candidate_ms, support


def _choose_step(beat: float, beat_ms: float, config: RhythmAlignmentConfig) -> tuple[float, int, bool]:
    if config.profile == "strict_1_64":
        return 0.0625, 16, False
    if config.profile == "raw":
        return 0.0625, 16, False
    for step, divisor, triplet in _AUTO_STEPS:
        residual_ms = abs(beat - round(beat / step) * step) * beat_ms
        window = min(config.maximum_local_shift_ms, step * beat_ms * 0.35)
        if residual_ms <= window + 1e-9:
            return step, divisor, triplet
    return _AUTO_STEPS[-1]


def _segment_for_time(grid: RhythmGrid, time_ms: float) -> RhythmTempoSegment:
    selected = grid.tempo_segments[0]
    for segment in grid.tempo_segments:
        if time_ms < segment.start_ms:
            break
        selected = segment
        if segment.end_ms is None or time_ms < segment.end_ms:
            break
    return selected


def _audio_time_for_beat(
    grid: RhythmGrid,
    beat: float,
    *,
    near_time_ms: float,
) -> float:
    """Invert a local beat coordinate without changing the source clock."""

    segment = _segment_for_time(grid, near_time_ms)
    return segment.start_ms + (
        (float(beat) - segment.beat_at_start)
        * 60_000.0
        / segment.bpm
    )


def _bounded_boundary(
    projected_ms: float,
    raw_ms: float,
    maximum_shift_ms: float,
) -> float:
    maximum = max(0.0, float(maximum_shift_ms))
    return max(
        float(raw_ms) - maximum,
        min(float(raw_ms) + maximum, float(projected_ms)),
    )


def analyse_rhythm_alignment(
    *,
    evidence_cache_key: str,
    candidates: Sequence[object],
    settings: ProjectRhythmSettings,
    frame_times_ms: np.ndarray,
    onset_evidence: np.ndarray,
    frame_midi_min: int = 21,
    config: RhythmAlignmentConfig | None = None,
    cancelled: CancelCallback | None = None,
) -> RhythmAlignmentSidecar:
    """Build a deterministic exact-grid projection without mutating inputs."""

    config = config or RhythmAlignmentConfig()
    candidate_tuple = tuple(candidates)
    times = np.asarray(frame_times_ms, dtype=np.float64)
    onset = np.asarray(onset_evidence, dtype=np.float32)
    if times.ndim != 1 or onset.ndim != 2 or len(times) != onset.shape[0]:
        raise ValueError("alignment evidence does not share one time axis")
    estimate = estimate_rhythm_grid_from_evidence(
        settings,
        frame_times_ms=times,
        onset_evidence=onset,
        cancelled=cancelled,
    )
    source_beat_ms = 60_000.0 / estimate.detected_bpm
    projections: list[RhythmTimingProjection] = []
    candidate_pitch = {
        str(_value(candidate, "candidate_id", "")): int(_value(candidate, "pitch", 0))
        for candidate in candidate_tuple
    }

    for index, candidate in enumerate(candidate_tuple):
        if index % 256 == 0:
            _cancel_if_requested(cancelled)
        candidate_id = str(_value(candidate, "candidate_id", ""))
        raw_start = _finite(_value(candidate, "start_ms", 0.0), "candidate start_ms")
        raw_duration = _finite(_value(candidate, "duration_ms", 0.0), "candidate duration_ms")
        pitch = int(_value(candidate, "pitch", 0))
        confidence = _bounded(_value(candidate, "confidence", 0.0), "candidate confidence")
        if not candidate_id or raw_start < 0.0 or raw_duration <= 0.0:
            continue
        refined_start, onset_support = _refined_onset_ms(
            raw_start_ms=raw_start,
            pitch=pitch,
            times=times,
            onset=onset,
            midi_min=frame_midi_min,
            config=config,
        )
        start_beat = rhythm_position_at(estimate.grid, refined_start).beat
        end_beat = rhythm_position_at(estimate.grid, raw_start + raw_duration).beat
        step, divisor, triplet = _choose_step(start_beat, source_beat_ms, config)
        if config.profile == "raw":
            projected_start = raw_start
            projected_duration = raw_duration
            reasons = ("raw_timing",)
        else:
            snapped_start_beat = round(start_beat / step) * step
            snapped_end_beat = round(end_beat / step) * step
            if snapped_end_beat <= snapped_start_beat:
                snapped_end_beat = snapped_start_beat + step
            # Candidates, evidence, waveform samples and the reference player
            # all use decoded source-audio milliseconds.  Never convert the
            # detected beat number through the project BPM here: doing so
            # time-stretches the whole song and creates error that grows with
            # elapsed time.  A project-tempo fit must be a separate explicit
            # edit, not a display projection.
            projected_start = _audio_time_for_beat(
                estimate.grid,
                snapped_start_beat,
                near_time_ms=refined_start,
            )
            projected_end = _audio_time_for_beat(
                estimate.grid,
                snapped_end_beat,
                near_time_ms=raw_start + raw_duration,
            )
            projected_start = max(
                0.0,
                _bounded_boundary(
                    projected_start,
                    raw_start,
                    config.maximum_local_shift_ms,
                ),
            )
            projected_end = _bounded_boundary(
                projected_end,
                raw_start + raw_duration,
                config.maximum_local_shift_ms,
            )
            if projected_end <= projected_start:
                projected_start = raw_start
                projected_end = raw_start + raw_duration
            projected_duration = projected_end - projected_start
            reasons = (
                "onset_peak_refined" if not math.isclose(refined_start, raw_start, abs_tol=1e-6) else "raw_onset",
                "strict_1_64" if config.profile == "strict_1_64" else "adaptive_grid",
                "triplet_grid" if triplet else "straight_grid",
                "source_audio_grid",
            )
        projections.append(
            RhythmTimingProjection(
                candidate_id=candidate_id,
                start_ms=projected_start,
                duration_ms=projected_duration,
                raw_start_ms=raw_start,
                raw_duration_ms=raw_duration,
                grid_divisor=divisor,
                triplet=triplet,
                onset_support=onset_support,
                confidence=max(0.0, min(1.0, 0.55 * confidence + 0.45 * estimate.confidence)),
                shift_ms=projected_start - raw_start,
                reason_codes=tuple(reason for reason in reasons if reason),
            )
        )

    # Notes starting together must stay together after projection.  Use the
    # most confident member's exact target and keep every candidate identity.
    ordered = sorted(range(len(projections)), key=lambda i: projections[i].raw_start_ms)
    cluster_start = 0
    while cluster_start < len(ordered):
        cluster_end = cluster_start + 1
        first = projections[ordered[cluster_start]]
        while cluster_end < len(ordered):
            current = projections[ordered[cluster_end]]
            if current.raw_start_ms - first.raw_start_ms > config.chord_cluster_ms:
                break
            cluster_end += 1
        members = ordered[cluster_start:cluster_end]
        if len(members) > 1 and config.profile != "raw":
            anchor_index = max(members, key=lambda i: projections[i].confidence)
            anchor = projections[anchor_index]
            for member in members:
                item = projections[member]
                if (
                    member != anchor_index
                    and candidate_pitch.get(item.candidate_id)
                    == candidate_pitch.get(anchor.candidate_id)
                ):
                    continue
                if abs(anchor.start_ms - item.raw_start_ms) > (
                    config.maximum_local_shift_ms + 1e-9
                ):
                    continue
                projections[member] = replace(
                    item,
                    start_ms=anchor.start_ms,
                    shift_ms=anchor.start_ms - item.raw_start_ms,
                    reason_codes=tuple(dict.fromkeys((*item.reason_codes, "chord_cluster"))),
                )
        cluster_start = cluster_end

    # Prevent invisible same-pitch overlaps introduced by snapping.  The next
    # onset is already on-grid, so capping the previous duration remains exact.
    by_pitch: dict[int, list[int]] = {}
    for index, item in enumerate(projections):
        by_pitch.setdefault(candidate_pitch.get(item.candidate_id, -1), []).append(index)
    for pitch_indices in by_pitch.values():
        pitch_indices.sort(key=lambda i: projections[i].start_ms)
        for left, right in zip(pitch_indices, pitch_indices[1:]):
            previous = projections[left]
            following = projections[right]
            if config.profile == "raw":
                continue
            if following.start_ms <= previous.start_ms:
                local_bpm = rhythm_position_at(
                    estimate.grid,
                    following.raw_start_ms,
                ).bpm
                shifted_start = (
                    previous.start_ms + 60_000.0 / local_bpm / 16.0
                )
                if abs(shifted_start - following.raw_start_ms) <= (
                    config.maximum_local_shift_ms + 1e-9
                ):
                    following = replace(
                        following,
                        start_ms=shifted_start,
                        shift_ms=shifted_start - following.raw_start_ms,
                        reason_codes=tuple(
                            dict.fromkeys(
                                (*following.reason_codes, "same_pitch_collision_shifted")
                            )
                        ),
                    )
                    projections[right] = following
            maximum_duration = following.start_ms - previous.start_ms
            capped_end = previous.start_ms + maximum_duration
            raw_end = previous.raw_start_ms + previous.raw_duration_ms
            if (
                maximum_duration > 0.0
                and previous.duration_ms > maximum_duration
                and abs(capped_end - raw_end)
                <= config.maximum_local_shift_ms + 1e-9
            ):
                projections[left] = replace(
                    previous,
                    duration_ms=maximum_duration,
                    reason_codes=tuple(dict.fromkeys((*previous.reason_codes, "same_pitch_overlap_capped"))),
                )

    revision = transcription_candidate_revision(candidate_tuple)
    identity = _alignment_identity(
        evidence_cache_key=str(evidence_cache_key),
        candidate_revision=revision,
        estimate=estimate,
        config=config,
    )
    shifts = [
        boundary_shift
        for item in projections
        for boundary_shift in (
            abs(item.start_ms - item.raw_start_ms),
            abs(
                (item.start_ms + item.duration_ms)
                - (item.raw_start_ms + item.raw_duration_ms)
            ),
        )
    ]
    aligned_count = sum(
        not math.isclose(item.start_ms, item.raw_start_ms, abs_tol=1e-6)
        or not math.isclose(item.duration_ms, item.raw_duration_ms, abs_tol=1e-6)
        for item in projections
    )
    return RhythmAlignmentSidecar(
        identity=identity,
        evidence_cache_key=str(evidence_cache_key),
        candidate_revision=revision,
        estimate=estimate,
        config=config,
        projections=tuple(projections),
        aligned_count=aligned_count,
        mean_abs_shift_ms=float(np.mean(shifts)) if shifts else 0.0,
        max_abs_shift_ms=max(shifts, default=0.0),
    )


__all__ = [
    "RHYTHM_ALIGNMENT_VERSION",
    "RhythmAlignmentConfig",
    "RhythmAlignmentCancelled",
    "RhythmAlignmentProfile",
    "RhythmAlignmentSidecar",
    "RhythmGridEstimate",
    "RhythmTimingProjection",
    "analyse_rhythm_alignment",
    "estimate_rhythm_grid_from_evidence",
]
