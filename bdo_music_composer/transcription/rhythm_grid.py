"""Immutable rhythm-grid contracts for transcription diagnostics.

Phase 1 accepts only a project grid that a caller explicitly enabled.  This
module never reads audio, runs a model, or mutates transcription candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Literal, Mapping, Sequence


RHYTHM_GRID_VERSION = "project-rhythm-grid-v1"

RhythmGridSource = Literal[
    "project",
    "onset_evidence",
    "benchmark_oracle",
]

_GRID_SOURCES = frozenset(
    {"project", "onset_evidence", "benchmark_oracle"}
)
_STRAIGHT_AND_TRIPLET_SUBDIVISIONS = tuple(
    sorted(
        {
            *(index / 16.0 for index in range(17)),
            *(index / 12.0 for index in range(13)),
        }
    )
)
_COMMON_DURATION_BEATS = (
    0.0625,
    1.0 / 12.0,
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


def _finite(value: object, field_name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be finite") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _candidate_value(
    candidate: object,
    field_name: str,
    default: object = "",
) -> object:
    if isinstance(candidate, Mapping):
        return candidate.get(field_name, default)
    return getattr(candidate, field_name, default)


@dataclass(frozen=True, slots=True)
class ProjectRhythmSettings:
    """Explicit caller intent plus the fixed project grid for Phase 1."""

    enabled: bool = False
    bpm: float = 120.0
    beat_origin_audio_ms: float = 0.0
    time_signature: int = 4

    def __post_init__(self) -> None:
        bpm = _finite(self.bpm, "bpm")
        origin = _finite(
            self.beat_origin_audio_ms,
            "beat_origin_audio_ms",
        )
        if bpm <= 0.0 or bpm > 1_000.0:
            raise ValueError("bpm must be in (0, 1000]")
        if isinstance(self.time_signature, bool):
            raise ValueError("time_signature must be a positive integer")
        meter = int(self.time_signature)
        if meter <= 0 or meter > 64:
            raise ValueError("time_signature must be in [1, 64]")
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "bpm", bpm)
        object.__setattr__(self, "beat_origin_audio_ms", origin)
        object.__setattr__(self, "time_signature", meter)


@dataclass(frozen=True, slots=True)
class RhythmTempoSegment:
    """One deterministic tempo span with an explicit beat coordinate."""

    start_ms: float
    end_ms: float | None
    bpm: float
    beat_at_start: float
    confidence: float

    def __post_init__(self) -> None:
        start = _finite(self.start_ms, "segment start_ms")
        end = (
            None
            if self.end_ms is None
            else _finite(self.end_ms, "segment end_ms")
        )
        bpm = _finite(self.bpm, "segment bpm")
        beat = _finite(self.beat_at_start, "segment beat_at_start")
        confidence = _finite(self.confidence, "segment confidence")
        if start < 0.0:
            raise ValueError("segment start_ms must be non-negative")
        if end is not None and end <= start:
            raise ValueError("segment end_ms must be greater than start_ms")
        if bpm <= 0.0 or bpm > 1_000.0:
            raise ValueError("segment bpm must be in (0, 1000]")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("segment confidence must be in [0, 1]")
        object.__setattr__(self, "start_ms", start)
        object.__setattr__(self, "end_ms", end)
        object.__setattr__(self, "bpm", bpm)
        object.__setattr__(self, "beat_at_start", beat)
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True, slots=True)
class RhythmGrid:
    """A versioned beat coordinate system; never authoritative note timing."""

    source: RhythmGridSource
    beat_origin_audio_ms: float
    time_signature: int
    tempo_segments: tuple[RhythmTempoSegment, ...]
    confidence: float
    version: str = RHYTHM_GRID_VERSION

    def __post_init__(self) -> None:
        source = str(self.source)
        origin = _finite(
            self.beat_origin_audio_ms,
            "beat_origin_audio_ms",
        )
        confidence = _finite(self.confidence, "grid confidence")
        if source not in _GRID_SOURCES:
            raise ValueError("unknown rhythm grid source")
        if isinstance(self.time_signature, bool):
            raise ValueError("time_signature must be a positive integer")
        meter = int(self.time_signature)
        if meter <= 0 or meter > 64:
            raise ValueError("time_signature must be in [1, 64]")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("grid confidence must be in [0, 1]")
        segments = tuple(self.tempo_segments)
        if not segments:
            raise ValueError("a rhythm grid requires at least one segment")
        previous_end: float | None = None
        for index, segment in enumerate(segments):
            if index and previous_end is None:
                raise ValueError("only the final tempo segment may be open")
            if previous_end is not None and segment.start_ms < previous_end:
                raise ValueError("tempo segments must be ordered and disjoint")
            previous_end = segment.end_ms
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "beat_origin_audio_ms", origin)
        object.__setattr__(self, "time_signature", meter)
        object.__setattr__(self, "tempo_segments", segments)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "version", str(self.version or ""))


@dataclass(frozen=True, slots=True)
class RhythmPosition:
    beat: float
    phase: float
    nearest_subdivision_distance_beats: float
    bpm: float


def build_project_rhythm_grid(
    settings: ProjectRhythmSettings,
) -> RhythmGrid | None:
    """Return a grid only after an explicit caller enablement."""

    if not settings.enabled:
        return None
    beat_ms = 60_000.0 / settings.bpm
    return RhythmGrid(
        source="project",
        beat_origin_audio_ms=settings.beat_origin_audio_ms,
        time_signature=settings.time_signature,
        tempo_segments=(
            RhythmTempoSegment(
                start_ms=0.0,
                end_ms=None,
                bpm=settings.bpm,
                beat_at_start=(
                    -settings.beat_origin_audio_ms / beat_ms
                ),
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )


def _segment_at(grid: RhythmGrid, time_ms: float) -> RhythmTempoSegment:
    selected = grid.tempo_segments[0]
    for segment in grid.tempo_segments:
        if time_ms < segment.start_ms:
            break
        selected = segment
        if segment.end_ms is None or time_ms < segment.end_ms:
            break
    return selected


def rhythm_position_at(grid: RhythmGrid, time_ms: float) -> RhythmPosition:
    """Project audio time into a beat phase without changing that time."""

    time_value = _finite(time_ms, "time_ms")
    segment = _segment_at(grid, time_value)
    beat = segment.beat_at_start + (
        (time_value - segment.start_ms) * segment.bpm / 60_000.0
    )
    phase = beat - math.floor(beat)
    distance = min(
        abs(phase - subdivision)
        for subdivision in _STRAIGHT_AND_TRIPLET_SUBDIVISIONS
    )
    return RhythmPosition(
        beat=beat,
        phase=phase,
        nearest_subdivision_distance_beats=distance,
        bpm=segment.bpm,
    )


def rhythmic_duration_fit(duration_ms: float, bpm: float) -> float:
    """Return a bounded proximity score to common straight/triplet values."""

    duration = _finite(duration_ms, "duration_ms")
    tempo = _finite(bpm, "bpm")
    if duration < 0.0 or tempo <= 0.0:
        raise ValueError("duration and bpm must be non-negative and positive")
    duration_beats = duration * tempo / 60_000.0
    nearest = min(
        abs(duration_beats - expected)
        for expected in _COMMON_DURATION_BEATS
    )
    scale = max(0.125, duration_beats * 0.25)
    return max(0.0, min(1.0, 1.0 - nearest / scale))


def transcription_candidate_revision(
    candidates: Sequence[object],
) -> str:
    """Return a stable revision without serializing audio or local paths."""

    digest = hashlib.sha256()
    for candidate in candidates:
        payload = (
            str(_candidate_value(candidate, "candidate_id")),
            int(_candidate_value(candidate, "pitch", 0)),
            round(float(_candidate_value(candidate, "start_ms", 0.0)), 6),
            round(float(_candidate_value(candidate, "duration_ms", 0.0)), 6),
            round(float(_candidate_value(candidate, "confidence", 0.0)), 6),
        )
        digest.update(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()[:24]


def rhythm_analysis_identity(
    *,
    evidence_cache_key: str,
    candidate_revision: str,
    grid: RhythmGrid,
    algorithm_version: str,
) -> str:
    """Bind a disposable result to exact evidence, candidates, and grid."""

    payload = {
        "algorithm_version": str(algorithm_version),
        "candidate_revision": str(candidate_revision),
        "evidence_cache_key": str(evidence_cache_key),
        "grid": {
            "beat_origin_audio_ms": round(grid.beat_origin_audio_ms, 6),
            "confidence": round(grid.confidence, 6),
            "source": grid.source,
            "time_signature": grid.time_signature,
            "version": grid.version,
            "tempo_segments": [
                {
                    "beat_at_start": round(segment.beat_at_start, 9),
                    "bpm": round(segment.bpm, 6),
                    "confidence": round(segment.confidence, 6),
                    "end_ms": (
                        None
                        if segment.end_ms is None
                        else round(segment.end_ms, 6)
                    ),
                    "start_ms": round(segment.start_ms, 6),
                }
                for segment in grid.tempo_segments
            ],
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


__all__ = [
    "ProjectRhythmSettings",
    "RHYTHM_GRID_VERSION",
    "RhythmGrid",
    "RhythmGridSource",
    "RhythmPosition",
    "RhythmTempoSegment",
    "build_project_rhythm_grid",
    "rhythm_analysis_identity",
    "rhythm_position_at",
    "rhythmic_duration_fit",
    "transcription_candidate_revision",
]
