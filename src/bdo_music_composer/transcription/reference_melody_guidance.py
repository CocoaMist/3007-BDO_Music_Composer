"""Weak, display-only melody guidance for reference timbre groups.

Editable notes may indicate which anonymous source the user is currently
following.  A hit is deliberately weak, deduplicated by time window and pitch,
and never changes recognition candidates, acoustic labels, or editor notes.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
from typing import Sequence


MIN_GUIDANCE_WINDOW_MS = 2_000.0
MAX_GUIDANCE_WINDOW_MS = 6_000.0
MAX_GUIDANCE_BOOST = 0.15
ESTABLISHED_WINDOW_COUNT = 2


@dataclass(frozen=True, slots=True)
class MelodyGuidanceGroup:
    group_id: str
    hit_count: int
    window_count: int
    distinct_pitch_count: int
    boost: float
    emphasis: float


@dataclass(frozen=True, slots=True)
class ReferenceMelodyGuidance:
    enabled: bool
    manual_note_count: int
    matched_note_count: int
    ambiguous_note_count: int
    window_ms: float
    groups: tuple[MelodyGuidanceGroup, ...] = ()
    focus_group_id: str = ""
    predicted_group_id: str = ""
    prediction_confidence: float = 0.0
    default_emphasis: float = 1.0
    target_instrument_id: int | None = None
    target_instrument_label: str = ""

    def group_emphasis(self, group_id: str) -> float:
        for group in self.groups:
            if group.group_id == group_id:
                return group.emphasis
        return self.default_emphasis

    def is_highest_priority_group(self, group_id: str) -> bool:
        return bool(
            self.focus_group_id
            and str(group_id) == self.focus_group_id
            and self.target_instrument_label
        )


def build_reference_melody_guidance(
    *,
    candidates: Sequence[object],
    groups: Sequence[object],
    notes: Sequence[object],
    beat_ms: float,
    audio_offset_ms: float = 0.0,
    enabled: bool = True,
    target_instrument_id: int | None = None,
    target_instrument_label: str = "",
) -> ReferenceMelodyGuidance:
    """Return conservative group emphasis derived from editable notes.

    The unit of evidence is one ``(group, window, pitch)`` tuple, not one
    recognition fragment.  This prevents a broken contour from earning extra
    influence merely because it was split into many candidates.
    """

    window_ms = max(
        MIN_GUIDANCE_WINDOW_MS,
        min(MAX_GUIDANCE_WINDOW_MS, _finite(beat_ms, 500.0) * 8.0),
    )
    valid_notes = tuple(note for note in notes if _valid_note(note))
    if not enabled:
        return ReferenceMelodyGuidance(
            False,
            len(valid_notes),
            0,
            0,
            window_ms,
            target_instrument_id=target_instrument_id,
            target_instrument_label=str(target_instrument_label),
        )

    group_by_candidate: dict[str, str] = {}
    for group in groups:
        group_id = str(getattr(group, "group_id", "") or "")
        if not group_id or group_id == "timbre-unknown":
            continue
        for candidate_id in getattr(group, "candidate_ids", ()):
            group_by_candidate[str(candidate_id)] = group_id

    by_pitch: dict[
        int,
        tuple[tuple[object, ...], tuple[float, ...], float],
    ] = {}
    candidates_by_pitch: dict[int, list[object]] = {}
    for candidate in candidates:
        candidate_id = str(getattr(candidate, "candidate_id", "") or "")
        if candidate_id not in group_by_candidate:
            continue
        candidates_by_pitch.setdefault(
            int(getattr(candidate, "pitch", -1)), []
        ).append(candidate)
    for pitch, values in candidates_by_pitch.items():
        values.sort(
            key=lambda item: (
                _finite(getattr(item, "start_ms", 0.0), 0.0),
                str(getattr(item, "candidate_id", "")),
            )
        )
        ordered = tuple(values)
        starts = tuple(
            _finite(getattr(item, "start_ms", 0.0), 0.0)
            for item in ordered
        )
        by_pitch[pitch] = (
            ordered,
            starts,
            max(
                (
                    max(
                        1.0,
                        _finite(
                            getattr(item, "duration_ms", 0.0),
                            1.0,
                        ),
                    )
                    for item in ordered
                ),
                default=1.0,
            ),
        )

    matched_hits: list[tuple[str, float, int, float]] = []
    matched_notes = 0
    ambiguous_notes = 0
    for note in valid_notes:
        pitch = int(getattr(note, "pitch", -1))
        start_ms = _finite(getattr(note, "start", 0.0), 0.0) - _finite(
            audio_offset_ms, 0.0
        )
        duration_ms = max(1.0, _finite(getattr(note, "dur", 0.0), 1.0))
        end_ms = start_ms + duration_ms
        if end_ms <= 0.0:
            continue
        group_scores: dict[str, float] = {}
        ordered, candidate_starts, max_candidate_duration = by_pitch.get(
            pitch,
            ((), (), 0.0),
        )
        first_candidate = bisect_left(
            candidate_starts,
            start_ms - max_candidate_duration - 120.0,
        )
        last_candidate = bisect_right(
            candidate_starts,
            end_ms + 120.0,
        )
        for candidate in ordered[first_candidate:last_candidate]:
            candidate_start = _finite(
                getattr(candidate, "start_ms", 0.0), 0.0
            )
            candidate_duration = max(
                1.0,
                _finite(getattr(candidate, "duration_ms", 0.0), 1.0),
            )
            candidate_end = candidate_start + candidate_duration
            overlap = max(
                0.0,
                min(end_ms, candidate_end) - max(start_ms, candidate_start),
            )
            overlap_ratio = overlap / max(
                1.0, min(duration_ms, candidate_duration)
            )
            onset_score = max(
                0.0, 1.0 - abs(start_ms - candidate_start) / 180.0
            )
            confidence = max(
                0.0,
                min(1.0, _finite(getattr(candidate, "confidence", 0.0), 0.0)),
            )
            score = confidence * (0.68 * overlap_ratio + 0.32 * onset_score)
            if score < 0.42:
                continue
            group_id = group_by_candidate[
                str(getattr(candidate, "candidate_id", ""))
            ]
            group_scores[group_id] = max(group_scores.get(group_id, 0.0), score)
        ranked = sorted(
            group_scores.items(), key=lambda item: (-item[1], item[0])
        )
        if not ranked:
            continue
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.12:
            ambiguous_notes += 1
            continue
        group_id, score = ranked[0]
        matched_hits.append((group_id, start_ms, pitch, score))
        matched_notes += 1

    # Anchor windows to each source's first matched note.  Absolute song-time
    # buckets can turn two adjacent notes on opposite sides of a 4-second
    # boundary into false evidence from two independent regions.
    group_anchors: dict[str, float] = {}
    for group_id, start_ms, _pitch, _score in matched_hits:
        group_anchors[group_id] = min(
            group_anchors.get(group_id, start_ms),
            start_ms,
        )
    deduplicated: dict[tuple[str, int, int], float] = {}
    for group_id, start_ms, pitch, score in matched_hits:
        window_index = math.floor(
            max(0.0, start_ms - group_anchors[group_id]) / window_ms
        )
        key = (group_id, window_index, pitch)
        deduplicated[key] = max(deduplicated.get(key, 0.0), score)

    grouped: dict[str, dict[int, list[tuple[int, float]]]] = {}
    for (group_id, window_index, pitch), score in deduplicated.items():
        grouped.setdefault(group_id, {}).setdefault(window_index, []).append(
            (pitch, score)
        )

    raw: list[tuple[str, int, int, int, float]] = []
    for group_id, windows in grouped.items():
        total = 0.0
        pitches: set[int] = set()
        hit_count = 0
        for hits in windows.values():
            strongest = sorted(hits, key=lambda item: (-item[1], item[0]))[:3]
            pitches.update(pitch for pitch, _score in strongest)
            hit_count += len(strongest)
            total += min(
                0.04,
                sum(0.004 + 0.008 * score for _pitch, score in strongest),
            )
        window_count = len(windows)
        reliability = min(1.0, window_count / ESTABLISHED_WINDOW_COUNT)
        boost = min(MAX_GUIDANCE_BOOST, total * reliability)
        raw.append(
            (group_id, hit_count, window_count, len(pitches), boost)
        )
    raw.sort(key=lambda item: (-item[4], -item[2], item[0]))

    focus_group_id = ""
    predicted_group_id = ""
    prediction_confidence = 0.0
    runner_up = raw[1][4] if len(raw) > 1 else 0.0
    if raw and raw[0][4] >= 0.004 and raw[0][4] - runner_up >= 0.004:
        predicted_group_id = raw[0][0]
        prediction_confidence = min(
            0.74,
            0.24
            + 0.34 * min(1.0, raw[0][2] / ESTABLISHED_WINDOW_COUNT)
            + 0.16
            * min(1.0, (raw[0][4] - runner_up) / 0.03),
        )
    established = bool(raw and raw[0][2] >= ESTABLISHED_WINDOW_COUNT)
    if established:
        if raw[0][4] >= 0.01 and raw[0][4] - runner_up >= 0.015:
            focus_group_id = raw[0][0]
            predicted_group_id = focus_group_id
            prediction_confidence = max(0.78, prediction_confidence)
    default_emphasis = (
        0.42
        if focus_group_id
        else 0.82
        if predicted_group_id
        else 0.72
        if raw
        else 1.0
    )
    results = tuple(
        MelodyGuidanceGroup(
            group_id,
            hit_count,
            window_count,
            pitch_count,
            boost,
            (
                1.35
                if group_id == focus_group_id
                else 1.10
                if group_id == predicted_group_id
                else min(
                    1.0,
                    0.78 + 0.42 * (boost / MAX_GUIDANCE_BOOST),
                )
            ),
        )
        for group_id, hit_count, window_count, pitch_count, boost in raw
    )
    return ReferenceMelodyGuidance(
        enabled=True,
        manual_note_count=len(valid_notes),
        matched_note_count=matched_notes,
        ambiguous_note_count=ambiguous_notes,
        window_ms=window_ms,
        groups=results,
        focus_group_id=focus_group_id,
        predicted_group_id=predicted_group_id,
        prediction_confidence=prediction_confidence,
        default_emphasis=default_emphasis,
        target_instrument_id=target_instrument_id,
        target_instrument_label=str(target_instrument_label),
    )


def _valid_note(note: object) -> bool:
    try:
        pitch = int(getattr(note, "pitch"))
        start = float(getattr(note, "start"))
        duration = float(getattr(note, "dur"))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return (
        0 <= pitch <= 127
        and math.isfinite(start)
        and math.isfinite(duration)
        and duration > 0.0
    )


def _finite(value: object, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return number if math.isfinite(number) else float(default)


__all__ = [
    "ESTABLISHED_WINDOW_COUNT",
    "MAX_GUIDANCE_BOOST",
    "MelodyGuidanceGroup",
    "ReferenceMelodyGuidance",
    "build_reference_melody_guidance",
]
