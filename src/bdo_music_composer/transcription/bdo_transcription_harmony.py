"""Qt-free, conservative harmony analysis for transcription evidence.

The analyser consumes Basic Pitch's frame-aligned note matrix and optional
symbolic events.  It never edits editor notes and deliberately returns ``N``
when the evidence cannot support at least a triad.  All times use the original
reference-audio timeline; project offsets belong at the UI/session boundary.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Callable, Iterable, Literal, Sequence

import numpy as np


HARMONY_ALGORITHM_VERSION = "bdo-harmony-v1"
ChordQuality = Literal[
    "major",
    "minor",
    "dim",
    "sus2",
    "sus4",
    "maj7",
    "7",
    "min7",
    "half_diminished7",
    "N",
]
KeyMode = Literal["major", "minor"]
HarmonySource = Literal[
    "audio",
    "candidates",
    "notes",
    "combined",
    "manual",
    "none",
]

_CHORD_TEMPLATES: tuple[tuple[ChordQuality, tuple[int, ...]], ...] = (
    ("major", (0, 4, 7)),
    ("minor", (0, 3, 7)),
    ("dim", (0, 3, 6)),
    ("sus2", (0, 2, 7)),
    ("sus4", (0, 5, 7)),
    ("maj7", (0, 4, 7, 11)),
    ("7", (0, 4, 7, 10)),
    ("min7", (0, 3, 7, 10)),
    ("half_diminished7", (0, 3, 6, 10)),
)
_QUALITY_ORDER = {
    quality: index for index, (quality, _intervals) in enumerate(_CHORD_TEMPLATES)
}
_CHORD_INTERVALS = dict(_CHORD_TEMPLATES)
_CHORD_STATES: tuple[tuple[int, ChordQuality], ...] = tuple(
    (root, quality)
    for root in range(12)
    for quality, _intervals in _CHORD_TEMPLATES
)
_VITERBI_STATES: tuple[tuple[int | None, ChordQuality], ...] = (
    (None, "N"),
    *_CHORD_STATES,
)
_CHORD_STATE_ROOTS = np.asarray(
    [root for root, _quality in _CHORD_STATES],
    dtype=np.int8,
)
_CHORD_STATE_MASKS = np.zeros(
    (len(_CHORD_STATES), 12),
    dtype=np.float64,
)
_CHORD_STATE_LENGTHS = np.empty(len(_CHORD_STATES), dtype=np.float64)
_CHORD_STATE_COMPLEXITY = np.empty(len(_CHORD_STATES), dtype=np.float64)
for _state_index, (_root, _quality) in enumerate(_CHORD_STATES):
    _intervals = _CHORD_INTERVALS[_quality]
    _CHORD_STATE_MASKS[
        _state_index,
        [(int(_root) + interval) % 12 for interval in _intervals],
    ] = 1.0
    _CHORD_STATE_LENGTHS[_state_index] = len(_intervals)
    _CHORD_STATE_COMPLEXITY[_state_index] = (
        0.018 if len(_intervals) == 4 else 0.0
    )
for _constant_array in (
    _CHORD_STATE_ROOTS,
    _CHORD_STATE_MASKS,
    _CHORD_STATE_LENGTHS,
    _CHORD_STATE_COMPLEXITY,
):
    _constant_array.setflags(write=False)
_MAJOR_SCALE = frozenset((0, 2, 4, 5, 7, 9, 11))
_MINOR_SCALE = frozenset((0, 2, 3, 5, 7, 8, 10))
_SOURCE_WEIGHTS = {
    "audio": 0.55,
    "candidates": 0.20,
    "notes": 0.25,
}
_ACTIVE_RELATIVE_THRESHOLD = 0.18
_MIN_CHORD_SCORE = 0.60
_MIN_CHORD_MARGIN = 0.035
_CONFLICT_MARGIN = 0.08
_SWITCH_PENALTY = 0.11
_EPSILON = 1e-9
_CANCEL_CHECK_INTERVAL = 64


class HarmonyAnalysisCancelled(RuntimeError):
    """Raised when a caller cooperatively cancels harmony analysis."""


CancellationCallback = Callable[[], bool]


@dataclass(frozen=True)
class KeyAlternative:
    root_pc: int
    mode: KeyMode
    confidence: float


@dataclass(frozen=True)
class KeyEstimate:
    root_pc: int | None
    mode: KeyMode | None
    confidence: float
    alternatives: tuple[KeyAlternative, ...] = ()
    source: HarmonySource = "none"


@dataclass(frozen=True)
class ChordAlternative:
    root_pc: int
    quality: ChordQuality
    bass_pc: int | None
    confidence: float
    audio_score: float = 0.0
    candidate_score: float = 0.0
    note_score: float = 0.0


@dataclass(frozen=True)
class ChordSegment:
    segment_id: str
    start_audio_ms: float
    end_audio_ms: float
    root_pc: int | None
    quality: ChordQuality
    bass_pc: int | None
    confidence: float
    alternatives: tuple[ChordAlternative, ...] = ()
    source: HarmonySource = "none"
    locked: bool = False


@dataclass(frozen=True)
class HarmonyConflict:
    segment_id: str
    kind: Literal["audio_symbolic", "low_margin"]
    alternatives: tuple[ChordAlternative, ...]


@dataclass(frozen=True)
class HarmonyAnalysis:
    cache_key: str
    global_key: KeyEstimate
    chord_segments: tuple[ChordSegment, ...]
    conflicts: tuple[HarmonyConflict, ...] = ()


@dataclass(frozen=True)
class _BeatWindow:
    start_ms: float
    end_ms: float


@dataclass(frozen=True)
class _SourceEvidence:
    chroma: np.ndarray
    bass_pc: int | None
    scores: dict[tuple[int, ChordQuality], float]
    informative: bool


@dataclass(frozen=True)
class _BeatDecision:
    window: _BeatWindow
    state: tuple[int | None, ChordQuality]
    bass_pc: int | None
    confidence: float
    alternatives: tuple[ChordAlternative, ...]
    source: HarmonySource
    emissions: tuple[float, ...]
    conflict_kinds: tuple[Literal["audio_symbolic", "low_margin"], ...]


def harmony_cache_key(
    audio_cache_key: str,
    *,
    bpm: float,
    time_signature: int,
    beat_origin_audio_ms: float,
    candidate_revision: str = "",
    note_revision: str = "",
) -> str:
    """Return the deterministic identity for derived harmony analysis."""

    if not isinstance(audio_cache_key, str) or not audio_cache_key:
        raise ValueError("audio_cache_key must not be empty")
    _validate_positive_number(bpm, "bpm")
    if isinstance(time_signature, bool) or int(time_signature) <= 0:
        raise ValueError("time_signature must be positive")
    if not math.isfinite(float(beat_origin_audio_ms)):
        raise ValueError("beat_origin_audio_ms must be finite")
    payload = {
        "algorithm": HARMONY_ALGORITHM_VERSION,
        "audio_cache_key": audio_cache_key,
        "beat_origin_us": int(round(float(beat_origin_audio_ms) * 1000.0)),
        "bpm_milli": int(round(float(bpm) * 1000.0)),
        "candidate_revision": str(candidate_revision),
        "note_revision": str(note_revision),
        "time_signature": int(time_signature),
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def analyse_harmony(
    frame_matrix: np.ndarray,
    frame_times_ms: np.ndarray,
    *,
    cache_key: str,
    bpm: float,
    beat_origin_audio_ms: float = 0.0,
    midi_min: int = 21,
    duration_ms: float | None = None,
    symbolic_candidates: Sequence[object] = (),
    symbolic_notes: Sequence[object] = (),
    cancelled: CancellationCallback | None = None,
) -> HarmonyAnalysis:
    """Analyse key and beat-aligned chords without reading files or using Qt.

    ``symbolic_candidates`` and ``symbolic_notes`` must already use audio time.
    The function intentionally has no reference-offset argument, preventing an
    offset from being applied a second time in this domain layer.
    """

    _raise_if_cancelled(cancelled)
    matrix, times = _validated_frame_input(
        frame_matrix,
        frame_times_ms,
        cancelled=cancelled,
    )
    _validate_positive_number(bpm, "bpm")
    if not isinstance(cache_key, str) or not cache_key:
        raise ValueError("cache_key must not be empty")
    if isinstance(midi_min, bool):
        raise ValueError("midi_min must be an integer")
    midi_min = int(midi_min)
    if not math.isfinite(float(beat_origin_audio_ms)):
        raise ValueError("beat_origin_audio_ms must be finite")
    duration = _analysis_duration(times, duration_ms)
    beat_ms = 60_000.0 / float(bpm)
    windows = _beat_windows(
        duration, beat_ms, float(beat_origin_audio_ms)
    )
    audio = _aggregate_frame_evidence(
        matrix,
        times,
        windows,
        midi_min,
        cancelled=cancelled,
    )
    candidates = _aggregate_symbolic_evidence(
        symbolic_candidates,
        windows,
        cancelled=cancelled,
    )
    notes = _aggregate_symbolic_evidence(
        symbolic_notes,
        windows,
        cancelled=cancelled,
    )

    decisions_list: list[_BeatDecision] = []
    for index, window in enumerate(windows):
        if index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        decisions_list.append(
            _decide_beat(
                window,
                audio[index],
                candidates[index],
                notes[index],
            )
        )
    decisions = tuple(decisions_list)
    smoothed_states = _viterbi_states(decisions, cancelled=cancelled)
    resolved_decisions: list[_BeatDecision] = []
    for index, (decision, state) in enumerate(
        zip(decisions, smoothed_states)
    ):
        if index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        resolved_decisions.append(_decision_with_state(decision, state))
    decisions = tuple(resolved_decisions)
    segments, conflicts = _segments_from_beats(
        cache_key,
        decisions,
        cancelled=cancelled,
    )
    global_key = _estimate_key(
        audio,
        candidates,
        notes,
        cancelled=cancelled,
    )
    _raise_if_cancelled(cancelled)
    return HarmonyAnalysis(cache_key, global_key, segments, conflicts)


def apply_harmony_overrides(
    analysis: HarmonyAnalysis,
    *,
    key_override: KeyEstimate | None = None,
    chord_overrides: Iterable[ChordSegment] = (),
) -> HarmonyAnalysis:
    """Overlay manual, locked decisions while retaining unaffected analysis.

    Overrides may split automatic segments.  Their IDs and split-fragment IDs
    are regenerated deterministically from the analysis cache identity.
    """

    overrides = tuple(
        _normalise_chord_override(analysis.cache_key, segment)
        for segment in chord_overrides
    )
    overrides = tuple(
        sorted(
            overrides,
            key=lambda item: (
                item.start_audio_ms,
                item.end_audio_ms,
                item.segment_id,
            ),
        )
    )
    for left, right in zip(overrides, overrides[1:]):
        if right.start_audio_ms < left.end_audio_ms - _EPSILON:
            raise ValueError("manual chord overrides must not overlap")

    conflicts_by_id: dict[str, tuple[HarmonyConflict, ...]] = {}
    for conflict in analysis.conflicts:
        conflicts_by_id.setdefault(conflict.segment_id, ())
        conflicts_by_id[conflict.segment_id] += (conflict,)

    current: list[tuple[ChordSegment, tuple[HarmonyConflict, ...]]] = [
        (segment, conflicts_by_id.get(segment.segment_id, ()))
        for segment in analysis.chord_segments
    ]
    for override in overrides:
        next_items: list[tuple[ChordSegment, tuple[HarmonyConflict, ...]]] = []
        for segment, segment_conflicts in current:
            if (
                segment.end_audio_ms <= override.start_audio_ms + _EPSILON
                or segment.start_audio_ms >= override.end_audio_ms - _EPSILON
            ):
                next_items.append((segment, segment_conflicts))
                continue
            if segment.start_audio_ms < override.start_audio_ms - _EPSILON:
                left = _segment_fragment(
                    analysis.cache_key,
                    segment,
                    segment.start_audio_ms,
                    override.start_audio_ms,
                )
                next_items.append(
                    (left, _retarget_conflicts(segment_conflicts, left.segment_id))
                )
            if segment.end_audio_ms > override.end_audio_ms + _EPSILON:
                right = _segment_fragment(
                    analysis.cache_key,
                    segment,
                    override.end_audio_ms,
                    segment.end_audio_ms,
                )
                next_items.append(
                    (right, _retarget_conflicts(segment_conflicts, right.segment_id))
                )
        next_items.append((override, ()))
        current = next_items

    current.sort(
        key=lambda item: (
            item[0].start_audio_ms,
            item[0].end_audio_ms,
            item[0].segment_id,
        )
    )
    segments = tuple(item[0] for item in current)
    conflicts = tuple(
        conflict
        for _segment, item_conflicts in current
        for conflict in item_conflicts
    )
    global_key = (
        _normalise_key_override(key_override)
        if key_override is not None
        else analysis.global_key
    )
    return HarmonyAnalysis(
        analysis.cache_key,
        global_key,
        segments,
        tuple(
            sorted(
                conflicts,
                key=lambda item: (item.segment_id, item.kind),
            )
        ),
    )


def apply_locked_harmony(
    new_analysis: HarmonyAnalysis,
    previous_analysis: HarmonyAnalysis,
) -> HarmonyAnalysis:
    """Reapply only manual key and locked chord decisions after reanalysis."""

    key_override = (
        previous_analysis.global_key
        if previous_analysis.global_key.source == "manual"
        else None
    )
    locked = tuple(
        segment
        for segment in previous_analysis.chord_segments
        if segment.locked or segment.source == "manual"
    )
    return apply_harmony_overrides(
        new_analysis,
        key_override=key_override,
        chord_overrides=locked,
    )


def _validated_frame_input(
    frame_matrix: np.ndarray,
    frame_times_ms: np.ndarray,
    *,
    cancelled: CancellationCallback | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    _raise_if_cancelled(cancelled)
    matrix = np.asarray(frame_matrix)
    times = np.asarray(frame_times_ms)
    if matrix.ndim != 2 or matrix.shape[0] <= 0 or matrix.shape[1] <= 0:
        raise ValueError("frame_matrix must be a non-empty 2D matrix")
    if times.ndim != 1 or times.shape[0] != matrix.shape[0]:
        raise ValueError("frame_times_ms must match frame_matrix rows")
    if not np.issubdtype(matrix.dtype, np.number):
        raise ValueError("frame_matrix must be numeric")
    if not np.issubdtype(times.dtype, np.number):
        raise ValueError("frame_times_ms must be numeric")
    # Preserve float16/float32 memmaps.  Per-beat percentile work promotes the
    # visible slice as needed, avoiding an eager full-song float64 copy.
    matrix = np.asarray(matrix)
    times = np.asarray(times, dtype=np.float64)
    if not np.all(np.isfinite(matrix)) or np.any(matrix < 0.0):
        raise ValueError("frame_matrix must contain finite non-negative values")
    _raise_if_cancelled(cancelled)
    if not np.all(np.isfinite(times)) or np.any(times < 0.0):
        raise ValueError("frame_times_ms must contain finite non-negative values")
    if times.shape[0] > 1 and np.any(np.diff(times) <= 0.0):
        raise ValueError("frame_times_ms must be strictly increasing")
    return matrix, times


def _validate_positive_number(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{name} must be a finite positive number")


def _analysis_duration(times: np.ndarray, duration_ms: float | None) -> float:
    if duration_ms is not None:
        _validate_positive_number(duration_ms, "duration_ms")
        duration = float(duration_ms)
        if duration + _EPSILON < float(times[-1]):
            raise ValueError("duration_ms must include the final frame time")
        return duration
    if times.shape[0] == 1:
        return max(1.0, float(times[0]) + 10.0)
    frame_period = float(np.median(np.diff(times)))
    return max(1.0, float(times[-1]) + frame_period)


def _beat_windows(
    duration_ms: float,
    beat_ms: float,
    origin_ms: float,
) -> tuple[_BeatWindow, ...]:
    first_index = math.floor((0.0 - origin_ms) / beat_ms)
    last_index = math.ceil((duration_ms - origin_ms) / beat_ms)
    windows: list[_BeatWindow] = []
    for index in range(first_index, last_index):
        start = max(0.0, origin_ms + index * beat_ms)
        end = min(duration_ms, origin_ms + (index + 1) * beat_ms)
        if end > start + _EPSILON:
            windows.append(_BeatWindow(start, end))
    if not windows:
        windows.append(_BeatWindow(0.0, duration_ms))
    return tuple(windows)


def _aggregate_frame_evidence(
    matrix: np.ndarray,
    times: np.ndarray,
    windows: Sequence[_BeatWindow],
    midi_min: int,
    *,
    cancelled: CancellationCallback | None = None,
) -> tuple[_SourceEvidence, ...]:
    result = []
    for index, window in enumerate(windows):
        if index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        left = int(np.searchsorted(times, window.start_ms, side="left"))
        right = int(np.searchsorted(times, window.end_ms, side="left"))
        if right <= left:
            chroma = np.zeros(12, dtype=np.float64)
            bass_pc = None
        else:
            # A percentile preserves short attacks better than a mean without
            # letting a single noisy frame dominate an entire beat.
            per_pitch = np.percentile(matrix[left:right], 90.0, axis=0)
            chroma = np.zeros(12, dtype=np.float64)
            for bin_index, value in enumerate(per_pitch):
                chroma[(midi_min + bin_index) % 12] += float(value)
            bass_pc = _lowest_active_pitch_class(per_pitch, midi_min)
        result.append(_build_source_evidence(chroma, bass_pc))
    return tuple(result)


def _aggregate_symbolic_evidence(
    events: Sequence[object],
    windows: Sequence[_BeatWindow],
    *,
    cancelled: CancellationCallback | None = None,
) -> tuple[_SourceEvidence, ...]:
    """Aggregate events by visiting only beat windows they overlap.

    The previous implementation visited every event for every beat, making a
    ten-minute song with 20,000 candidates quadratic in practical input size.
    This event-oriented interval index preserves event insertion order (and
    therefore deterministic floating-point accumulation) while reducing work
    to the number of actual event/window overlaps.
    """

    _raise_if_cancelled(cancelled)
    parsed: list[tuple[int, float, float, float]] = []
    for index, event in enumerate(events):
        if index % 256 == 0:
            _raise_if_cancelled(cancelled)
        values = _event_values(event)
        if values is not None:
            parsed.append(values)

    window_count = len(windows)
    if window_count == 0:
        return ()
    starts = tuple(window.start_ms for window in windows)
    ends = tuple(window.end_ms for window in windows)
    durations = tuple(
        max(window.end_ms - window.start_ms, _EPSILON)
        for window in windows
    )
    chromas = np.zeros((window_count, 12), dtype=np.float64)
    bass_pitches = np.full(window_count, 128, dtype=np.int16)
    had_overlap = np.zeros(window_count, dtype=np.bool_)

    for index, (pitch, start, end, strength) in enumerate(parsed):
        if index % 256 == 0:
            _raise_if_cancelled(cancelled)
        # Strict inequalities match the old ``overlap <= 0`` boundary rule.
        first = bisect_right(ends, start)
        stop = bisect_left(starts, end)
        if first >= stop or stop <= 0 or first >= window_count:
            continue
        first = max(0, first)
        stop = min(window_count, stop)
        # Events are processed in their original sequence, preserving the old
        # deterministic addition order within each pitch-class/window cell.
        pitch_class = pitch % 12
        for window_index in range(first, stop):
            if (
                window_index - first
            ) % 256 == 0 and window_index != first:
                _raise_if_cancelled(cancelled)
            overlap = min(end, ends[window_index]) - max(
                start,
                starts[window_index],
            )
            if overlap <= 0.0:
                continue
            weight = strength * min(
                1.0,
                overlap / durations[window_index],
            )
            chromas[window_index, pitch_class] += weight
            had_overlap[window_index] = True
            if (
                weight > _EPSILON
                and pitch < int(bass_pitches[window_index])
            ):
                bass_pitches[window_index] = pitch

    result: list[_SourceEvidence] = []
    for index in range(window_count):
        if index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        if not bool(had_overlap[index]):
            bass_pc = None
        elif int(bass_pitches[index]) < 128:
            bass_pc = int(bass_pitches[index]) % 12
        else:
            # Preserve the legacy zero-strength-event behaviour.
            bass_pc = 0
        result.append(_build_source_evidence(chromas[index], bass_pc))
    return tuple(result)


def _event_values(
    event: object,
) -> tuple[int, float, float, float] | None:
    try:
        pitch = int(getattr(event, "pitch"))
        start_value = getattr(event, "start_ms", None)
        if start_value is None:
            start_value = getattr(event, "start")
        duration_value = getattr(event, "duration_ms", None)
        if duration_value is None:
            duration_value = getattr(event, "dur")
        start = float(start_value)
        duration = float(duration_value)
        velocity = float(
            getattr(event, "velocity", getattr(event, "vel", 100.0))
        )
        confidence = float(getattr(event, "confidence", 1.0))
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        not 0 <= pitch <= 127
        or not math.isfinite(start)
        or not math.isfinite(duration)
        or not math.isfinite(velocity)
        or not math.isfinite(confidence)
        or duration <= 0.0
    ):
        return None
    strength = (
        max(0.0, min(1.0, confidence))
        * (0.35 + 0.65 * max(0.0, min(127.0, velocity)) / 127.0)
    )
    return pitch, start, start + duration, strength


def _lowest_active_pitch_class(
    per_pitch: np.ndarray,
    midi_min: int,
) -> int | None:
    maximum = float(np.max(per_pitch, initial=0.0))
    if maximum <= _EPSILON:
        return None
    threshold = maximum * _ACTIVE_RELATIVE_THRESHOLD
    active = np.flatnonzero(per_pitch >= threshold)
    return int((midi_min + int(active[0])) % 12) if active.size else None


def _normalised_chroma(chroma: np.ndarray) -> np.ndarray:
    values = np.maximum(np.asarray(chroma, dtype=np.float64), 0.0)
    maximum = float(np.max(values, initial=0.0))
    return values / maximum if maximum > _EPSILON else values


def _build_source_evidence(
    chroma: np.ndarray,
    bass_pc: int | None,
) -> _SourceEvidence:
    normalised = _normalised_chroma(chroma)
    active_count = int(
        np.count_nonzero(normalised >= _ACTIVE_RELATIVE_THRESHOLD)
    )
    informative = active_count >= 3
    scores = (
        _score_chord_states(normalised, bass_pc)
        if informative
        else {}
    )
    return _SourceEvidence(normalised, bass_pc, scores, informative)


def _score_chord_states(
    chroma: np.ndarray,
    bass_pc: int | None,
) -> dict[tuple[int, ChordQuality], float]:
    total = float(np.sum(chroma))
    maximum = float(np.max(chroma, initial=0.0))
    if total <= _EPSILON or maximum <= _EPSILON:
        return {}
    active = np.asarray(
        chroma >= maximum * _ACTIVE_RELATIVE_THRESHOLD,
        dtype=np.float64,
    )
    active_count = max(1.0, float(np.sum(active)))
    intersections = _CHORD_STATE_MASKS @ active
    coverage = (_CHORD_STATE_MASKS @ chroma) / total
    completeness = intersections / _CHORD_STATE_LENGTHS
    root_strength = chroma[_CHORD_STATE_ROOTS] / maximum
    extra_ratio = (active_count - intersections) / active_count
    bass_score = np.zeros(len(_CHORD_STATES), dtype=np.float64)
    if bass_pc is not None:
        bass_score[_CHORD_STATE_MASKS[:, bass_pc] > 0.0] = 0.42
        bass_score[_CHORD_STATE_ROOTS == bass_pc] = 1.0
    scores = (
        0.52 * coverage
        + 0.28 * completeness
        + 0.12 * root_strength
        + 0.08 * bass_score
        - 0.10 * extra_ratio
        - _CHORD_STATE_COMPLEXITY
    )
    scores[completeness < 0.74] = np.minimum(
        scores[completeness < 0.74],
        0.56,
    )
    scores = np.clip(scores, 0.0, 1.0)
    return {
        state: float(scores[index])
        for index, state in enumerate(_CHORD_STATES)
    }


def _decide_beat(
    window: _BeatWindow,
    audio: _SourceEvidence,
    candidates: _SourceEvidence,
    notes: _SourceEvidence,
) -> _BeatDecision:
    sources = {
        "audio": audio,
        "candidates": candidates,
        "notes": notes,
    }
    informative = {
        name: evidence
        for name, evidence in sources.items()
        if evidence.informative
    }
    if not informative:
        emissions = tuple(
            1.0 if state == (None, "N") else 0.0
            for state in _VITERBI_STATES
        )
        return _BeatDecision(
            window,
            (None, "N"),
            None,
            1.0,
            (),
            "none",
            emissions,
            (),
        )

    weight_total = sum(_SOURCE_WEIGHTS[name] for name in informative)
    combined_scores = {
        state: sum(
            _SOURCE_WEIGHTS[name] * evidence.scores[state]
            for name, evidence in informative.items()
        )
        / weight_total
        for state in _CHORD_STATES
    }
    ranked = _rank_states(combined_scores)
    best_state, best_score = ranked[0]
    _second_state, second_score = ranked[1]
    margin = best_score - second_score
    bass_pc = _combined_bass(informative)
    source_best = {
        name: _rank_states(evidence.scores)[0]
        for name, evidence in informative.items()
    }
    symbolic_ranked = sorted(
        (
            (state, score, name)
            for name, (state, score) in source_best.items()
            if name in {"candidates", "notes"} and score >= _MIN_CHORD_SCORE
        ),
        key=lambda item: (
            -item[1],
            item[0][0],
            _QUALITY_ORDER[item[0][1]],
            item[2],
        ),
    )
    source_mismatch = bool(
        "audio" in source_best
        and source_best["audio"][1] >= _MIN_CHORD_SCORE
        and symbolic_ranked
        and source_best["audio"][0]
        != symbolic_ranked[0][0]
    )
    if source_mismatch:
        alternative_states = (
            source_best["audio"][0],
            symbolic_ranked[0][0],
        )
    else:
        alternative_states = tuple(state for state, _score in ranked[:2])
    alternatives = tuple(
        _chord_alternative(
            state,
            bass_pc,
            combined_scores[state],
            audio,
            candidates,
            notes,
        )
        for state in alternative_states
    )

    conflict_kinds: list[
        Literal["audio_symbolic", "low_margin"]
    ] = []
    if source_mismatch:
        conflict_kinds.append("audio_symbolic")
    if margin < _CONFLICT_MARGIN:
        conflict_kinds.append("low_margin")

    fail_closed = best_score < _MIN_CHORD_SCORE or margin < _MIN_CHORD_MARGIN
    state: tuple[int | None, ChordQuality] = (
        (None, "N") if fail_closed else best_state
    )
    confidence = (
        _clamp01(max(0.55, 1.0 - margin))
        if fail_closed
        else _clamp01(best_score * (0.72 + min(0.28, margin * 2.5)))
    )
    n_emission = (
        max(0.72, best_score + 0.06)
        if fail_closed
        else 0.12
    )
    emissions = (
        (n_emission,)
        + tuple(-1_000_000_000.0 for _state in _CHORD_STATES)
        if fail_closed
        else tuple(
            n_emission
            if candidate_state == (None, "N")
            else combined_scores[candidate_state]  # type: ignore[index]
            for candidate_state in _VITERBI_STATES
        )
    )
    return _BeatDecision(
        window,
        state,
        None if fail_closed else bass_pc,
        confidence,
        alternatives,
        _source_label(tuple(informative)),
        emissions,
        tuple(conflict_kinds),
    )


def _rank_states(
    scores: dict[tuple[int, ChordQuality], float],
) -> list[tuple[tuple[int, ChordQuality], float]]:
    return sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            _QUALITY_ORDER[item[0][1]],
        ),
    )


def _chord_alternative(
    state: tuple[int, ChordQuality],
    bass_pc: int | None,
    score: float,
    audio: _SourceEvidence,
    candidates: _SourceEvidence,
    notes: _SourceEvidence,
) -> ChordAlternative:
    return ChordAlternative(
        state[0],
        state[1],
        bass_pc,
        _clamp01(score),
        _clamp01(audio.scores.get(state, 0.0)),
        _clamp01(candidates.scores.get(state, 0.0)),
        _clamp01(notes.scores.get(state, 0.0)),
    )


def _combined_bass(
    sources: dict[str, _SourceEvidence],
) -> int | None:
    votes = np.zeros(12, dtype=np.float64)
    for name, evidence in sources.items():
        if evidence.bass_pc is not None:
            votes[evidence.bass_pc] += _SOURCE_WEIGHTS[name]
    if float(np.max(votes, initial=0.0)) <= _EPSILON:
        return None
    return int(np.flatnonzero(votes == np.max(votes))[0])


def _source_label(names: Sequence[str]) -> HarmonySource:
    name_set = frozenset(names)
    if not name_set:
        return "none"
    if len(name_set) > 1:
        return "combined"
    return next(iter(name_set))  # type: ignore[return-value]


def _viterbi_states(
    decisions: Sequence[_BeatDecision],
    *,
    cancelled: CancellationCallback | None = None,
) -> tuple[tuple[int | None, ChordQuality], ...]:
    _raise_if_cancelled(cancelled)
    if not decisions:
        return ()
    state_count = len(_VITERBI_STATES)
    previous = np.asarray(decisions[0].emissions, dtype=np.float64)
    back = np.zeros((len(decisions), state_count), dtype=np.int16)
    for beat_index in range(1, len(decisions)):
        if beat_index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        global_best = int(np.argmax(previous))
        current = np.empty(state_count, dtype=np.float64)
        emissions = decisions[beat_index].emissions
        for state_index in range(state_count):
            stay_score = float(previous[state_index])
            switch_score = float(previous[global_best]) - _SWITCH_PENALTY
            if stay_score >= switch_score:
                predecessor = state_index
                path_score = stay_score
            else:
                predecessor = global_best
                path_score = switch_score
            back[beat_index, state_index] = predecessor
            current[state_index] = path_score + emissions[state_index]
        previous = current
    state_index = int(np.argmax(previous))
    path = [state_index]
    for beat_index in range(len(decisions) - 1, 0, -1):
        if beat_index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        state_index = int(back[beat_index, state_index])
        path.append(state_index)
    path.reverse()
    return tuple(_VITERBI_STATES[index] for index in path)


def _decision_with_state(
    decision: _BeatDecision,
    state: tuple[int | None, ChordQuality],
) -> _BeatDecision:
    if state == decision.state:
        return decision
    if state == (None, "N"):
        return replace(
            decision,
            state=state,
            bass_pc=None,
            confidence=_clamp01(decision.emissions[0]),
        )
    state_index = _VITERBI_STATES.index(state)
    matching = next(
        (
            alternative
            for alternative in decision.alternatives
            if (alternative.root_pc, alternative.quality) == state
        ),
        None,
    )
    alternatives = (
        (matching,)
        + tuple(
            item for item in decision.alternatives if item is not matching
        )[:1]
        if matching is not None
        else decision.alternatives
    )
    return replace(
        decision,
        state=state,
        confidence=_clamp01(decision.emissions[state_index]),
        alternatives=alternatives,
    )


def _segments_from_beats(
    cache_key: str,
    decisions: Sequence[_BeatDecision],
    *,
    cancelled: CancellationCallback | None = None,
) -> tuple[tuple[ChordSegment, ...], tuple[HarmonyConflict, ...]]:
    _raise_if_cancelled(cancelled)
    if not decisions:
        return (), ()
    groups: list[list[_BeatDecision]] = []
    for index, decision in enumerate(decisions):
        if index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        if (
            groups
            and groups[-1][-1].state == decision.state
            and groups[-1][-1].bass_pc == decision.bass_pc
            and abs(
                groups[-1][-1].window.end_ms
                - decision.window.start_ms
            )
            <= 0.001
        ):
            groups[-1].append(decision)
        else:
            groups.append([decision])

    segments = []
    conflicts = []
    for index, group in enumerate(groups):
        if index % _CANCEL_CHECK_INTERVAL == 0:
            _raise_if_cancelled(cancelled)
        first, last = group[0], group[-1]
        root_pc, quality = first.state
        start_ms, end_ms = first.window.start_ms, last.window.end_ms
        source = _merged_source(tuple(item.source for item in group))
        alternatives = _merge_alternatives(group)
        segment_id = _stable_segment_id(
            cache_key,
            start_ms,
            end_ms,
            root_pc,
            quality,
            first.bass_pc,
            source,
        )
        segment = ChordSegment(
            segment_id,
            start_ms,
            end_ms,
            root_pc,
            quality,
            first.bass_pc,
            _clamp01(
                sum(item.confidence for item in group) / len(group)
            ),
            alternatives,
            source,
            False,
        )
        segments.append(segment)
        kinds = sorted(
            {
                kind
                for item in group
                for kind in item.conflict_kinds
            }
        )
        conflicts.extend(
            HarmonyConflict(segment_id, kind, alternatives)
            for kind in kinds
        )
    return tuple(segments), tuple(conflicts)


def _merge_alternatives(
    decisions: Sequence[_BeatDecision],
) -> tuple[ChordAlternative, ...]:
    totals: dict[
        tuple[int, ChordQuality, int | None],
        list[float],
    ] = {}
    for decision in decisions:
        for alternative in decision.alternatives:
            key = (
                alternative.root_pc,
                alternative.quality,
                alternative.bass_pc,
            )
            values = totals.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
            values[0] += alternative.confidence
            values[1] += alternative.audio_score
            values[2] += alternative.candidate_score
            values[3] += alternative.note_score
            values[4] += 1.0
    merged = [
        ChordAlternative(
            key[0],
            key[1],
            key[2],
            values[0] / values[4],
            values[1] / values[4],
            values[2] / values[4],
            values[3] / values[4],
        )
        for key, values in totals.items()
    ]
    merged.sort(
        key=lambda item: (
            -item.confidence,
            item.root_pc,
            _QUALITY_ORDER[item.quality],
        )
    )
    return tuple(merged[:2])


def _merged_source(sources: Sequence[HarmonySource]) -> HarmonySource:
    unique = frozenset(source for source in sources if source != "none")
    if not unique:
        return "none"
    if len(unique) == 1:
        return next(iter(unique))
    return "combined"


def _estimate_key(
    audio: Sequence[_SourceEvidence],
    candidates: Sequence[_SourceEvidence],
    notes: Sequence[_SourceEvidence],
    *,
    cancelled: CancellationCallback | None = None,
) -> KeyEstimate:
    _raise_if_cancelled(cancelled)
    source_groups = {
        "audio": audio,
        "candidates": candidates,
        "notes": notes,
    }
    chromas: dict[str, np.ndarray] = {}
    for name, evidence in source_groups.items():
        _raise_if_cancelled(cancelled)
        combined = np.sum(
            np.asarray([item.chroma for item in evidence]),
            axis=0,
        )
        normalised = _normalised_chroma(combined)
        if (
            int(
                np.count_nonzero(
                    normalised >= _ACTIVE_RELATIVE_THRESHOLD
                )
            )
            >= 5
        ):
            chromas[name] = normalised
    if not chromas:
        return KeyEstimate(None, None, 0.0, (), "none")
    weight_total = sum(_SOURCE_WEIGHTS[name] for name in chromas)
    chroma = sum(
        _SOURCE_WEIGHTS[name] * values
        for name, values in chromas.items()
    ) / weight_total
    maximum = float(np.max(chroma, initial=0.0))
    total = float(np.sum(chroma))
    scored: list[tuple[float, int, KeyMode]] = []
    for root in range(12):
        _raise_if_cancelled(cancelled)
        for mode, scale in (
            ("major", _MAJOR_SCALE),
            ("minor", _MINOR_SCALE),
        ):
            scale_pcs = {(root + interval) % 12 for interval in scale}
            coverage = (
                sum(float(chroma[pc]) for pc in scale_pcs) / total
                if total > _EPSILON
                else 0.0
            )
            third = (root + (4 if mode == "major" else 3)) % 12
            score = (
                0.62 * coverage
                + 0.18 * float(chroma[root]) / max(maximum, _EPSILON)
                + 0.12
                * float(chroma[(root + 7) % 12])
                / max(maximum, _EPSILON)
                + 0.08 * float(chroma[third]) / max(maximum, _EPSILON)
            )
            scored.append((_clamp01(score), root, mode))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    best, second = scored[0], scored[1]
    margin = best[0] - second[0]
    alternatives = tuple(
        KeyAlternative(root, mode, score)
        for score, root, mode in scored[:3]
    )
    confidence = _clamp01(
        best[0] * (0.75 + min(0.25, margin * 3.0))
    )
    if best[0] < 0.62 or margin < 0.015:
        return KeyEstimate(
            None,
            None,
            confidence,
            alternatives,
            _source_label(tuple(chromas)),
        )
    return KeyEstimate(
        best[1],
        best[2],
        confidence,
        alternatives,
        _source_label(tuple(chromas)),
    )


def _stable_segment_id(
    cache_key: str,
    start_ms: float,
    end_ms: float,
    root_pc: int | None,
    quality: ChordQuality,
    bass_pc: int | None,
    source: HarmonySource,
) -> str:
    payload = "|".join(
        (
            cache_key,
            str(int(round(start_ms * 1000.0))),
            str(int(round(end_ms * 1000.0))),
            "N" if root_pc is None else str(root_pc),
            quality,
            "N" if bass_pc is None else str(bass_pc),
            source,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _normalise_key_override(override: KeyEstimate) -> KeyEstimate:
    if override.root_pc is None or override.mode not in {"major", "minor"}:
        raise ValueError("manual key override requires a root and mode")
    if not 0 <= int(override.root_pc) <= 11:
        raise ValueError("key root_pc must be between 0 and 11")
    return KeyEstimate(
        int(override.root_pc),
        override.mode,
        1.0,
        override.alternatives,
        "manual",
    )


def _normalise_chord_override(
    cache_key: str,
    override: ChordSegment,
) -> ChordSegment:
    start = float(override.start_audio_ms)
    end = float(override.end_audio_ms)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0.0 or end <= start:
        raise ValueError("manual chord override requires a valid audio-time range")
    quality = override.quality
    if quality != "N" and quality not in _CHORD_INTERVALS:
        raise ValueError("unsupported chord quality")
    if quality == "N":
        root_pc = None
        bass_pc = None
    else:
        if override.root_pc is None or not 0 <= int(override.root_pc) <= 11:
            raise ValueError("manual chord override requires root_pc 0..11")
        root_pc = int(override.root_pc)
        bass_pc = (
            None
            if override.bass_pc is None
            else int(override.bass_pc)
        )
        if bass_pc is not None and not 0 <= bass_pc <= 11:
            raise ValueError("bass_pc must be between 0 and 11")
    source: HarmonySource = "manual"
    segment_id = _stable_segment_id(
        cache_key,
        start,
        end,
        root_pc,
        quality,
        bass_pc,
        source,
    )
    return ChordSegment(
        segment_id,
        start,
        end,
        root_pc,
        quality,
        bass_pc,
        1.0,
        override.alternatives,
        source,
        bool(override.locked),
    )


def _segment_fragment(
    cache_key: str,
    segment: ChordSegment,
    start_ms: float,
    end_ms: float,
) -> ChordSegment:
    return replace(
        segment,
        segment_id=_stable_segment_id(
            cache_key,
            start_ms,
            end_ms,
            segment.root_pc,
            segment.quality,
            segment.bass_pc,
            segment.source,
        ),
        start_audio_ms=start_ms,
        end_audio_ms=end_ms,
    )


def _retarget_conflicts(
    conflicts: Sequence[HarmonyConflict],
    segment_id: str,
) -> tuple[HarmonyConflict, ...]:
    return tuple(
        replace(conflict, segment_id=segment_id)
        for conflict in conflicts
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _raise_if_cancelled(
    cancelled: CancellationCallback | None,
) -> None:
    if cancelled is not None and cancelled():
        raise HarmonyAnalysisCancelled("harmony analysis cancelled")
