"""Bounded reference-audio tempo estimation for project defaults."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable


REFERENCE_TEMPO_ANALYSIS_SECONDS = 180.0


class ReferenceTempoError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReferenceTempoEstimate:
    detected_bpm: float
    confidence: float
    beat_count: int
    tempo_drift_ratio: float
    analysed_seconds: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.detected_bpm) or self.detected_bpm <= 0.0:
            raise ValueError("detected_bpm must be positive and finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.beat_count < 0:
            raise ValueError("beat_count cannot be negative")
        if not math.isfinite(self.tempo_drift_ratio) or self.tempo_drift_ratio < 0.0:
            raise ValueError("tempo_drift_ratio must be finite and non-negative")


def estimate_reference_tempo(
    path: str | Path,
    *,
    prior_bpm: float = 120.0,
    cancelled: Callable[[], bool] | None = None,
) -> ReferenceTempoEstimate:
    """Estimate one steady tempo without decoding more than three minutes."""

    import librosa  # type: ignore[import-not-found]
    import numpy as np

    if cancelled is not None and cancelled():
        raise ReferenceTempoError("reference tempo analysis cancelled")
    try:
        signal, sample_rate = librosa.load(
            str(Path(path)),
            sr=22_050,
            mono=True,
            duration=REFERENCE_TEMPO_ANALYSIS_SECONDS,
            dtype=np.float32,
        )
    except Exception as exc:
        raise ReferenceTempoError("unable to decode reference tempo") from exc
    if cancelled is not None and cancelled():
        raise ReferenceTempoError("reference tempo analysis cancelled")
    audio = np.asarray(signal, dtype=np.float32)
    if audio.ndim != 1 or audio.size < sample_rate or not np.all(np.isfinite(audio)):
        raise ReferenceTempoError("reference audio is too short for tempo analysis")

    hop_length = 512
    onset = librosa.onset.onset_strength(
        y=audio,
        sr=sample_rate,
        hop_length=hop_length,
    )
    if cancelled is not None and cancelled():
        raise ReferenceTempoError("reference tempo analysis cancelled")
    if onset.size < 16 or float(np.max(onset)) <= 1e-8:
        raise ReferenceTempoError("reference audio has no usable onsets")
    envelope = np.asarray(onset, dtype=np.float32)
    floor = float(np.percentile(envelope, 55.0))
    envelope = np.maximum(0.0, envelope - floor)
    peak = float(np.max(envelope))
    if peak <= 1e-8:
        raise ReferenceTempoError("reference audio has no usable onsets")
    envelope /= peak
    peak_frames = np.flatnonzero(
        (envelope >= 0.20)
        & (envelope >= np.r_[envelope[0], envelope[:-1]])
        & (envelope >= np.r_[envelope[1:], envelope[-1]])
    )
    frame_seconds = hop_length / float(sample_rate)
    minimum_lag = max(2, round(60.0 / (300.0 * frame_seconds)))
    maximum_lag = min(
        envelope.size // 2,
        round(60.0 / (30.0 * frame_seconds)),
    )
    best_lag = 0
    best_score = -1.0
    for lag in range(minimum_lag, maximum_lag + 1):
        if lag % 32 == 0 and cancelled is not None and cancelled():
            raise ReferenceTempoError("reference tempo analysis cancelled")
        left = envelope[:-lag]
        right = envelope[lag:]
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 1e-9:
            continue
        correlation = float(np.dot(left, right) / denominator)
        candidate_bpm = 60.0 / (lag * frame_seconds)
        prior_distance = abs(math.log2(candidate_bpm / max(1.0, prior_bpm)))
        prior_fit = math.exp(-0.5 * (prior_distance / 0.35) ** 2)
        # Autocorrelation often rates the half-tempo lag slightly higher.
        # A bounded project-tempo prior resolves that musical octave ambiguity
        # without overriding a clearly stronger unrelated pulse.
        score = 0.75 * correlation + 0.25 * prior_fit
        if score > best_score + 1e-12:
            best_lag = lag
            best_score = score
    if best_lag <= 0 or best_score < 0.20 or peak_frames.size < 4:
        raise ReferenceTempoError("reference tempo could not be estimated")

    phase_scores = np.zeros(best_lag, dtype=np.float64)
    for frame in peak_frames:
        phase_scores[int(frame) % best_lag] += float(envelope[frame])
    phase = int(np.argmax(phase_scores))
    expected = np.arange(phase, envelope.size, best_lag, dtype=np.int64)
    radius = max(1, round(best_lag * 0.25))
    matched: list[int] = []
    for target in expected:
        location = int(np.searchsorted(peak_frames, target, side="left"))
        choices = []
        if location < peak_frames.size:
            choices.append(int(peak_frames[location]))
        if location:
            choices.append(int(peak_frames[location - 1]))
        if choices:
            selected = min(choices, key=lambda value: abs(value - int(target)))
            if abs(selected - int(target)) <= radius:
                matched.append(selected)
    beats = np.asarray(sorted(set(matched)), dtype=np.int64)
    if beats.size < 4:
        raise ReferenceTempoError("reference tempo has too few stable beats")
    bpm = 60.0 / (best_lag * frame_seconds)
    beat_times = beats.astype(np.float64) * frame_seconds
    intervals = np.diff(beat_times)
    median_interval = float(np.median(intervals)) if intervals.size else 0.0
    if median_interval <= 0.0:
        raise ReferenceTempoError("reference beat intervals are invalid")
    residuals = np.abs(intervals - median_interval)
    drift_ratio = float(np.percentile(residuals, 95.0)) / median_interval
    regularity = max(0.0, min(1.0, 1.0 - drift_ratio / 0.18))
    onset_scale = max(1e-8, float(np.percentile(onset, 90.0)))
    support = max(
        0.0,
        min(1.0, float(np.median(onset[beats])) / onset_scale),
    )
    coverage = min(1.0, beats.size / 32.0)
    confidence = max(
        0.0,
        min(
            1.0,
            0.45 * regularity
            + 0.25 * support
            + 0.20 * coverage
            + 0.10 * max(0.0, min(1.0, best_score)),
        ),
    )
    analysed_seconds = audio.size / float(sample_rate)
    return ReferenceTempoEstimate(
        detected_bpm=bpm,
        confidence=confidence,
        beat_count=int(beats.size),
        tempo_drift_ratio=drift_ratio,
        analysed_seconds=analysed_seconds,
    )


__all__ = [
    "REFERENCE_TEMPO_ANALYSIS_SECONDS",
    "ReferenceTempoError",
    "ReferenceTempoEstimate",
    "estimate_reference_tempo",
]
