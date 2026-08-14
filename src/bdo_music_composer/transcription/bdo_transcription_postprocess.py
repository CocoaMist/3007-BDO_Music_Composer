"""Deterministic fragment-note detection and conservative cleanup.

The Basic Pitch decoder emits frame-index events.  This module operates on
those events before they are converted to editor candidates, so every decode
entry point can share the same behaviour.  It is deliberately independent
from Qt, project state, and the authoritative editor ``Note`` model.

Automatic cleanup is evidence-gated.  Duration alone is only a review signal:
short ornaments, repeated attacks, and chord notes are retained unless the
evidence also establishes a narrow same-pitch duplicate or false split.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
import math
import operator
from typing import Iterable, Literal, Sequence, TypeAlias

import numpy as np


POSTPROCESS_VERSION = "fragment-cleanup-v4-display-continuity"

PRESERVE_CLEANUP_PROFILE = "preserve"
BALANCED_CLEANUP_PROFILE = "balanced"
CLEAN_CLEANUP_PROFILE = "clean"

CleanupProfile = Literal["preserve", "balanced", "clean"]
AuditAction = Literal["kept", "merged", "suppressed", "deduplicated"]
FragmentFlag = Literal[
    "auto_merged",
    "chord_supported",
    "cleanup_candidate",
    "clean_suppressed",
    "exact_duplicate",
    "nms_duplicate",
    "nms_survivor",
    "pitch_flicker",
    "regular_repeat",
    "review_fragment",
    "sequence_supported",
    "severe_fragment",
    "short_density",
]


@dataclass(frozen=True)
class FragmentCleanupParams:
    """Fixed v1 parameters selected for conservative, explainable behaviour."""

    version: str = POSTPROCESS_VERSION
    nms_onset_distance_frames: int = 2
    nms_min_overlap_ratio: float = 0.85
    max_merge_gap_frames: int = 2
    frame_continuity_ratio: float = 0.80
    frame_continuity_floor: float = 0.18
    onset_peak_radius_frames: int = 1
    onset_context_radius_frames: int = 3
    max_weak_onset_prominence: float = 0.10
    min_strong_reonset_ratio: float = 1.00
    max_weak_frame_attack_prominence: float = 0.10
    chord_onset_radius_frames: int = 2
    repeat_period_tolerance_ratio: float = 0.20
    repeat_period_min_tolerance_frames: int = 1
    severe_fragment_max_frames: int = 6
    review_fragment_max_frames: int = 8
    density_fragment_max_frames: int = 11
    clean_max_confidence: float = 0.30
    clean_max_frame_support: float = 0.35
    sequence_max_gap_frames: int = 8
    sequence_max_pitch_distance: int = 12
    flicker_max_pitch_distance: int = 2
    flicker_max_gap_frames: int = 1


V1_PARAMS = FragmentCleanupParams()
_AUDIT_ACTION_ORDER = {
    "deduplicated": 0,
    "suppressed": 1,
    "merged": 2,
    "kept": 3,
}


def _strict_int(value: object, name: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be an integer")
    try:
        return int(operator.index(value))
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _source_token(
    start_frame: int,
    end_frame: int,
    pitch: int,
    confidence: float,
) -> str:
    return (
        f"frame:{start_frame}:{end_frame}:{pitch}:"
        f"{float(confidence).hex()}"
    )


@dataclass(frozen=True)
class FrameNoteEvent:
    """One decoded note in evidence-frame coordinates.

    ``end_frame`` is exclusive. ``lineage`` contains stable raw-event IDs and
    is unioned when NMS or a conservative merge combines events.
    """

    start_frame: int
    end_frame: int
    pitch: int
    confidence: float
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        start = _strict_int(self.start_frame, "start_frame")
        end = _strict_int(self.end_frame, "end_frame")
        pitch = _strict_int(self.pitch, "pitch")
        confidence = float(self.confidence)
        if start < 0 or end <= start:
            raise ValueError("event frames must satisfy 0 <= start < end")
        if not 0 <= pitch <= 127:
            raise ValueError("pitch must be in MIDI range 0..127")
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be finite and in range 0..1")
        lineage = tuple(
            sorted(
                {
                    str(item)
                    for item in self.lineage
                    if str(item)
                }
            )
        )
        if not lineage:
            lineage = (_source_token(start, end, pitch, confidence),)
        object.__setattr__(self, "start_frame", start)
        object.__setattr__(self, "end_frame", end)
        object.__setattr__(self, "pitch", pitch)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "lineage", lineage)

    @property
    def span_frames(self) -> int:
        return self.end_frame - self.start_frame


FrameEventInput: TypeAlias = (
    FrameNoteEvent
    | tuple[int, int, int, float]
    | tuple[int, int, int, float, str]
    | tuple[int, int, int, float, Sequence[str]]
)


@dataclass(frozen=True)
class FragmentAudit:
    """One explainable output or removal decision."""

    event: FrameNoteEvent
    action: AuditAction
    flags: frozenset[FragmentFlag] = frozenset()
    reason: str = ""


@dataclass(frozen=True)
class FragmentPostprocessStats:
    input_count: int
    output_count: int
    exact_duplicate_count: int
    nms_removed_count: int
    automatic_merge_count: int
    suspected_fragment_count: int
    severe_fragment_count: int
    density_short_count: int
    pitch_flicker_count: int
    suppressed_count: int


@dataclass(frozen=True)
class FragmentPostprocessResult:
    """Kept events plus reversible hidden events and a complete audit trail."""

    events: tuple[FrameNoteEvent, ...]
    suppressed: tuple[FrameNoteEvent, ...]
    audit: tuple[FragmentAudit, ...]
    stats: FragmentPostprocessStats
    profile: CleanupProfile
    version: str = POSTPROCESS_VERSION
    automatic_actions_enabled: bool = False

    @property
    def kept(self) -> tuple[FrameNoteEvent, ...]:
        return self.events


@dataclass
class _WorkingEvent:
    event: FrameNoteEvent
    attack_frames: tuple[int, ...]
    merge_count: int = 0
    nms_absorbed: int = 0


def _event_sort_key(event: FrameNoteEvent) -> tuple:
    return (
        event.start_frame,
        event.pitch,
        event.end_frame,
        -event.confidence,
        event.lineage,
    )


def _audit_sort_key(item: FragmentAudit) -> tuple:
    return (
        item.event.start_frame,
        item.event.pitch,
        item.event.end_frame,
        _AUDIT_ACTION_ORDER[item.action],
        item.reason,
        item.event.lineage,
    )


def _coerce_event(item: FrameEventInput) -> FrameNoteEvent:
    if isinstance(item, FrameNoteEvent):
        return item
    if not isinstance(item, (tuple, list)):
        raise TypeError("events must contain FrameNoteEvent or 4/5-item tuples")
    if len(item) == 4:
        return FrameNoteEvent(item[0], item[1], item[2], item[3])
    if len(item) != 5:
        raise ValueError("event tuples must contain four or five items")
    raw_lineage = item[4]
    if isinstance(raw_lineage, str):
        lineage = (raw_lineage,)
    else:
        lineage = tuple(str(value) for value in raw_lineage)
    return FrameNoteEvent(item[0], item[1], item[2], item[3], lineage)


def _validate_evidence(
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    frame = np.asarray(frame_evidence)
    onset = np.asarray(onset_evidence)
    if frame.ndim != 2 or onset.ndim != 2:
        raise ValueError("frame and onset evidence must be two-dimensional")
    if frame.shape != onset.shape:
        raise ValueError("frame and onset evidence shapes must match")
    return frame, onset


def _combine_lineage(*events: FrameNoteEvent) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                source_id
                for event in events
                for source_id in event.lineage
            }
        )
    )


def _deduplicate_exact(
    events: Sequence[FrameNoteEvent],
) -> tuple[list[_WorkingEvent], list[FragmentAudit], int]:
    grouped: dict[
        tuple[int, int, int, float],
        list[FrameNoteEvent],
    ] = {}
    for event in events:
        key = (
            event.start_frame,
            event.end_frame,
            event.pitch,
            event.confidence,
        )
        grouped.setdefault(key, []).append(event)

    working: list[_WorkingEvent] = []
    audit: list[FragmentAudit] = []
    duplicate_count = 0
    for group in grouped.values():
        if len(group) == 1:
            # Decoder output overwhelmingly consists of unique events.  Keep
            # the already-normalised immutable object instead of rebuilding
            # it through dataclasses.replace (and __post_init__) on every run.
            representative = group[0]
            ordered = group
        else:
            ordered = sorted(group, key=_event_sort_key)
            lineage = _combine_lineage(*ordered)
            representative = (
                ordered[0]
                if ordered[0].lineage == lineage
                else replace(ordered[0], lineage=lineage)
            )
        working.append(
            _WorkingEvent(
                representative,
                (representative.start_frame,),
            )
        )
        for duplicate in ordered[1:]:
            duplicate_count += 1
            audit.append(
                FragmentAudit(
                    duplicate,
                    "deduplicated",
                    frozenset({"exact_duplicate"}),
                    "exact_duplicate",
                )
            )
    working.sort(key=lambda item: _event_sort_key(item.event))
    return working, audit, duplicate_count


def _overlap_ratio(left: FrameNoteEvent, right: FrameNoteEvent) -> float:
    overlap = max(
        0,
        min(left.end_frame, right.end_frame)
        - max(left.start_frame, right.start_frame),
    )
    return overlap / max(left.span_frames, right.span_frames)


def _nms_priority(item: _WorkingEvent) -> tuple:
    event = item.event
    return (
        -event.confidence,
        -event.span_frames,
        event.start_frame,
        event.end_frame,
        event.lineage,
    )


def _same_pitch_nms(
    working: Sequence[_WorkingEvent],
    params: FragmentCleanupParams,
) -> tuple[list[_WorkingEvent], list[FragmentAudit], int]:
    by_pitch: dict[int, list[_WorkingEvent]] = {}
    for item in working:
        by_pitch.setdefault(item.event.pitch, []).append(item)

    output: list[_WorkingEvent] = []
    audit: list[FragmentAudit] = []
    removed_count = 0
    for pitch in sorted(by_pitch):
        kept: list[_WorkingEvent] = []
        # Greedy NMS is priority ordered.  Only survivors whose starts are in
        # the fixed onset-radius can overlap a candidate, so retain that exact
        # ordering in tiny per-frame buckets rather than rescanning the whole
        # pitch history for every event.
        kept_by_start: dict[int, list[tuple[int, _WorkingEvent]]] = {}
        for candidate in sorted(by_pitch[pitch], key=_nms_priority):
            duplicate_of: _WorkingEvent | None = None
            first_start = (
                candidate.event.start_frame
                - params.nms_onset_distance_frames
            )
            last_start = (
                candidate.event.start_frame
                + params.nms_onset_distance_frames
            )
            duplicate_priority = len(kept)
            for start in range(first_start, last_start + 1):
                for priority_index, survivor in kept_by_start.get(start, ()):
                    if priority_index >= duplicate_priority:
                        continue
                    if (
                        _overlap_ratio(candidate.event, survivor.event)
                        >= params.nms_min_overlap_ratio
                    ):
                        duplicate_priority = priority_index
                        duplicate_of = survivor
            if duplicate_of is None:
                priority_index = len(kept)
                kept.append(candidate)
                kept_by_start.setdefault(
                    candidate.event.start_frame,
                    [],
                ).append((priority_index, candidate))
                continue

            removed_count += 1
            audit.append(
                FragmentAudit(
                    candidate.event,
                    "deduplicated",
                    frozenset({"nms_duplicate"}),
                    "same_pitch_nms",
                )
            )
            duplicate_of.event = replace(
                duplicate_of.event,
                lineage=_combine_lineage(
                    duplicate_of.event,
                    candidate.event,
                ),
            )
            # NMS establishes that both detections describe one attack.  Keep
            # the survivor's timing for repeat-pattern guards; treating the
            # discarded near-duplicate as another attack would invent a rapid
            # repetition and make later cleanup depend on decoder duplication.
            duplicate_of.nms_absorbed += 1 + candidate.nms_absorbed
        output.extend(kept)
    output.sort(key=lambda item: _event_sort_key(item.event))
    return output, audit, removed_count


def _pitch_column(
    matrix: np.ndarray,
    pitch: int,
    midi_min: int,
) -> np.ndarray | None:
    column = pitch - midi_min
    if column < 0 or column >= matrix.shape[1]:
        return None
    return matrix[:, column]


def _finite_window(
    series: np.ndarray,
    start: int,
    stop: int,
) -> list[float]:
    """Read a fixed, normally single-digit evidence window without arrays."""

    values: list[float] = []
    for index in range(max(0, start), min(len(series), stop)):
        value = float(series[index])
        if math.isfinite(value):
            values.append(value)
    return values


def _median(values: list[float]) -> float:
    values.sort()
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2.0


def _onset_features(
    event: FrameNoteEvent,
    onset: np.ndarray,
    midi_min: int,
    params: FragmentCleanupParams,
) -> tuple[float, float]:
    series = _pitch_column(onset, event.pitch, midi_min)
    if series is None or not series.size:
        # Unsupported pitches fail closed: never use absent evidence to alter.
        return 1.0, 1.0
    center = event.start_frame
    peak_lo = max(0, center - params.onset_peak_radius_frames)
    peak_hi = min(
        len(series),
        center + params.onset_peak_radius_frames + 1,
    )
    peak_values = _finite_window(series, peak_lo, peak_hi)
    if not peak_values:
        return 1.0, 1.0
    peak = max(peak_values)

    context_lo = max(0, center - params.onset_context_radius_frames)
    context_hi = min(
        len(series),
        center + params.onset_context_radius_frames + 1,
    )
    background_values = _finite_window(series, context_lo, peak_lo)
    background_values.extend(
        _finite_window(series, peak_hi, context_hi)
    )
    background = (
        _median(background_values)
        if background_values
        else 0.0
    )
    return peak, max(0.0, peak - background)


def _frame_support(
    event: FrameNoteEvent,
    frame: np.ndarray,
    midi_min: int,
) -> float:
    series = _pitch_column(frame, event.pitch, midi_min)
    if series is None:
        return 1.0
    values = _finite_window(
        series,
        event.start_frame,
        event.end_frame,
    )
    return sum(values) / len(values) if values else 1.0


def _frame_attack_prominence(
    event: FrameNoteEvent,
    frame: np.ndarray,
    midi_min: int,
    params: FragmentCleanupParams,
) -> float:
    """Approximate Basic Pitch's frame-derived onset at an event boundary."""

    series = _pitch_column(frame, event.pitch, midi_min)
    if series is None or not series.size:
        return 1.0
    center = event.start_frame
    attack_values = _finite_window(series, center, center + 2)
    if not attack_values:
        return 1.0
    context_lo = max(0, center - params.onset_context_radius_frames)
    baseline_values = _finite_window(series, context_lo, center)
    baseline = (
        _median(baseline_values)
        if baseline_values
        else 0.0
    )
    return max(0.0, max(attack_values) - baseline)


def _has_continuous_boundary(
    left: FrameNoteEvent,
    right: FrameNoteEvent,
    frame: np.ndarray,
    midi_min: int,
    frame_threshold: float,
    params: FragmentCleanupParams,
) -> bool:
    series = _pitch_column(frame, left.pitch, midi_min)
    if series is None:
        return False
    lo = max(0, left.end_frame - 1)
    hi = min(len(series), right.start_frame + 2)
    values = _finite_window(series, lo, hi)
    if not values:
        return False
    required = max(
        params.frame_continuity_floor,
        float(frame_threshold) * params.frame_continuity_ratio,
    )
    return min(values) >= required


def _chord_supported_event_ids(
    all_events: Sequence[FrameNoteEvent],
    params: FragmentCleanupParams,
) -> frozenset[int]:
    """Return identities with a different-pitch onset in the fixed window."""

    pitches_by_start: dict[int, set[int]] = {}
    for event in all_events:
        pitches_by_start.setdefault(event.start_frame, set()).add(
            event.pitch
        )
    supported: set[int] = set()
    radius = params.chord_onset_radius_frames
    for event in all_events:
        for start in range(
            event.start_frame - radius,
            event.start_frame + radius + 1,
        ):
            pitches = pitches_by_start.get(start)
            if pitches and (
                len(pitches) > 1 or event.pitch not in pitches
            ):
                supported.add(id(event))
                break
    return frozenset(supported)


def _interval_is_regular(
    left_attack: int,
    right_attack: int,
    same_pitch_attacks: Sequence[int],
    params: FragmentCleanupParams,
    attack_indexes: dict[int, int] | None = None,
) -> bool:
    interval = right_attack - left_attack
    if interval <= 0:
        return False
    attacks = (
        tuple(sorted(set(same_pitch_attacks)))
        if attack_indexes is None
        else tuple(same_pitch_attacks)
    )
    indexes = (
        {attack: index for index, attack in enumerate(attacks)}
        if attack_indexes is None
        else attack_indexes
    )
    left_index = indexes.get(left_attack)
    right_index = indexes.get(right_attack)
    if left_index is None or right_index is None:
        return False
    neighbours: list[int] = []
    if left_index > 0:
        neighbours.append(left_attack - attacks[left_index - 1])
    if right_index + 1 < len(attacks):
        neighbours.append(attacks[right_index + 1] - right_attack)
    tolerance = max(
        params.repeat_period_min_tolerance_frames,
        int(round(interval * params.repeat_period_tolerance_ratio)),
    )
    return any(
        neighbour > 0 and abs(neighbour - interval) <= tolerance
        for neighbour in neighbours
    )


def _can_merge_boundary(
    left: _WorkingEvent,
    right: _WorkingEvent,
    *,
    frame: np.ndarray,
    onset: np.ndarray,
    midi_min: int,
    frame_threshold: float,
    chord_supported_event_ids: frozenset[int],
    flicker_boundary_index: dict[
        int,
        tuple[tuple[int, ...], tuple[int, ...]],
    ],
    same_pitch_attacks: Sequence[int],
    attack_indexes: dict[int, int],
    params: FragmentCleanupParams,
) -> bool:
    if left.event.pitch != right.event.pitch:
        return False
    gap = right.event.start_frame - left.event.end_frame
    if gap < 0 or gap > params.max_merge_gap_frames:
        return False
    flicker_intervals = flicker_boundary_index.get(left.event.pitch)
    if flicker_intervals is not None:
        starts, prefix_ends = flicker_intervals
        hi = bisect_right(
            starts,
            right.event.start_frame + params.flicker_max_gap_frames,
        )
        if (
            hi
            and prefix_ends[hi - 1]
            >= left.event.end_frame - params.flicker_max_gap_frames
        ):
            return False
    if not _has_continuous_boundary(
        left.event,
        right.event,
        frame,
        midi_min,
        frame_threshold,
        params,
    ):
        return False
    left_onset_peak, _left_onset_prominence = _onset_features(
        left.event,
        onset,
        midi_min,
        params,
    )
    right_onset_peak, right_onset_prominence = _onset_features(
        right.event,
        onset,
        midi_min,
        params,
    )
    # The decoder creates the right-hand note because its onset crossed the
    # decode threshold, so applying that same absolute threshold here would
    # make every split impossible to merge. Judge the boundary independently:
    # a locally prominent reattack is protected, as is a second peak at least
    # as strong as the first. A weaker threshold-crossing plateau can still be
    # merged when frame evidence remains continuous.
    if right_onset_prominence >= params.max_weak_onset_prominence:
        return False
    if right_onset_peak > 0.0 and (
        left_onset_peak <= 0.0
        or right_onset_peak
        >= left_onset_peak * params.min_strong_reonset_ratio
    ):
        return False
    if (
        _frame_attack_prominence(
            right.event,
            frame,
            midi_min,
            params,
        )
        >= params.max_weak_frame_attack_prominence
    ):
        return False
    if id(right.event) in chord_supported_event_ids:
        return False
    left_attack = max(left.attack_frames)
    right_attack = min(right.attack_frames)
    if _interval_is_regular(
        left_attack,
        right_attack,
        same_pitch_attacks,
        params,
        attack_indexes,
    ):
        return False
    return True


def _merge_same_pitch_gaps(
    working: Sequence[_WorkingEvent],
    *,
    frame: np.ndarray,
    onset: np.ndarray,
    midi_min: int,
    frame_threshold: float,
    params: FragmentCleanupParams,
    chord_supported_event_ids: frozenset[int] | None = None,
    pitch_flicker_event_ids: frozenset[int] | None = None,
) -> tuple[list[_WorkingEvent], int]:
    context_events = tuple(item.event for item in working)
    chord_supported_event_ids = (
        _chord_supported_event_ids(context_events, params)
        if chord_supported_event_ids is None
        else chord_supported_event_ids
    )
    pitch_flicker_event_ids = (
        _pitch_flicker_event_ids(context_events, params)
        if pitch_flicker_event_ids is None
        else pitch_flicker_event_ids
    )
    flickers_by_base_pitch: dict[int, list[FrameNoteEvent]] = {}
    for event in context_events:
        if id(event) not in pitch_flicker_event_ids:
            continue
        for delta in range(1, params.flicker_max_pitch_distance + 1):
            for base_pitch in (event.pitch - delta, event.pitch + delta):
                if 0 <= base_pitch <= 127:
                    flickers_by_base_pitch.setdefault(
                        base_pitch,
                        [],
                    ).append(event)
    flicker_boundary_index: dict[
        int,
        tuple[tuple[int, ...], tuple[int, ...]],
    ] = {}
    for pitch, events in flickers_by_base_pitch.items():
        ordered = sorted(events, key=_event_sort_key)
        running_end = -1
        prefix_ends: list[int] = []
        for event in ordered:
            running_end = max(running_end, event.end_frame)
            prefix_ends.append(running_end)
        flicker_boundary_index[pitch] = (
            tuple(event.start_frame for event in ordered),
            tuple(prefix_ends),
        )
    by_pitch: dict[int, list[_WorkingEvent]] = {}
    for item in working:
        by_pitch.setdefault(item.event.pitch, []).append(item)

    merged_output: list[_WorkingEvent] = []
    merge_count = 0
    for pitch in sorted(by_pitch):
        group = sorted(
            by_pitch[pitch],
            key=lambda item: _event_sort_key(item.event),
        )
        same_pitch_attacks = tuple(
            sorted(
                {
                    attack
                    for item in group
                    for attack in item.attack_frames
                }
            )
        )
        attack_indexes = {
            attack: index
            for index, attack in enumerate(same_pitch_attacks)
        }
        current = group[0]
        for following in group[1:]:
            if _can_merge_boundary(
                current,
                following,
                frame=frame,
                onset=onset,
                midi_min=midi_min,
                frame_threshold=frame_threshold,
                chord_supported_event_ids=chord_supported_event_ids,
                flicker_boundary_index=flicker_boundary_index,
                same_pitch_attacks=same_pitch_attacks,
                attack_indexes=attack_indexes,
                params=params,
            ):
                current = _WorkingEvent(
                    FrameNoteEvent(
                        current.event.start_frame,
                        max(
                            current.event.end_frame,
                            following.event.end_frame,
                        ),
                        pitch,
                        max(
                            current.event.confidence,
                            following.event.confidence,
                        ),
                        _combine_lineage(
                            current.event,
                            following.event,
                        ),
                    ),
                    tuple(
                        sorted(
                            set(current.attack_frames)
                            | set(following.attack_frames)
                        )
                    ),
                    current.merge_count + following.merge_count + 1,
                    current.nms_absorbed + following.nms_absorbed,
                )
                merge_count += 1
            else:
                merged_output.append(current)
                current = following
        merged_output.append(current)
    merged_output.sort(key=lambda item: _event_sort_key(item.event))
    return merged_output, merge_count


def _interval_gap(left: FrameNoteEvent, right: FrameNoteEvent) -> int:
    if left.end_frame <= right.start_frame:
        return right.start_frame - left.end_frame
    if right.end_frame <= left.start_frame:
        return left.start_frame - right.end_frame
    return 0


def _sequence_supported_event_ids(
    all_events: Sequence[FrameNoteEvent],
    params: FragmentCleanupParams,
) -> frozenset[int]:
    """Find exact expanded-interval neighbours with an offline sweep."""

    gap = params.sequence_max_gap_frames
    pitch_distance = params.sequence_max_pitch_distance
    candidates = tuple(enumerate(all_events))
    queries = sorted(
        enumerate(all_events),
        key=lambda item: (
            item[1].end_frame + gap,
            _event_sort_key(item[1]),
            item[0],
        ),
    )
    # Two best ending candidates per pitch are enough to exclude the query
    # event itself while still answering whether any other interval overlaps.
    best_by_pitch: list[list[tuple[int, int]]] = [
        [(-1, -1), (-1, -1)] for _ in range(128)
    ]
    supported: set[int] = set()
    candidate_index = 0
    for index, event in queries:
        upper_start = event.end_frame + gap
        while (
            candidate_index < len(candidates)
            and candidates[candidate_index][1].start_frame <= upper_start
        ):
            added_index, added = candidates[candidate_index]
            pair = (added.end_frame, added_index)
            best = best_by_pitch[added.pitch]
            if (
                pair[0] > best[0][0]
                or (pair[0] == best[0][0] and pair[1] < best[0][1])
            ):
                best[1] = best[0]
                best[0] = pair
            elif (
                pair[0] > best[1][0]
                or (pair[0] == best[1][0] and pair[1] < best[1][1])
            ):
                best[1] = pair
            candidate_index += 1

        lower_end = event.start_frame - gap
        for pitch in range(
            max(0, event.pitch - pitch_distance),
            min(127, event.pitch + pitch_distance) + 1,
        ):
            first, second = best_by_pitch[pitch]
            match = second if first[1] == index else first
            if match[1] >= 0 and match[0] >= lower_end:
                supported.add(id(event))
                break
    return frozenset(supported)


def _pitch_flicker_event_ids(
    all_events: Sequence[FrameNoteEvent],
    params: FragmentCleanupParams,
) -> frozenset[int]:
    """Label short ±1/±2-semitone excursions without modifying pitch."""

    gap = params.flicker_max_gap_frames
    queries_by_minimum_span: dict[
        int,
        list[tuple[int, FrameNoteEvent]],
    ] = {}
    for index, event in enumerate(all_events):
        if event.span_frames <= params.review_fragment_max_frames:
            queries_by_minimum_span.setdefault(
                event.span_frames + 2,
                [],
            ).append((index, event))

    supported: set[int] = set()
    for minimum_span, queries in queries_by_minimum_span.items():
        candidates = tuple(
            (index, event)
            for index, event in enumerate(all_events)
            if event.span_frames >= minimum_span
        )
        ordered_queries = sorted(
            queries,
            key=lambda item: (
                item[1].end_frame + gap,
                _event_sort_key(item[1]),
                item[0],
            ),
        )
        best_end_by_pitch = [-1] * 128
        candidate_index = 0
        for _index, event in ordered_queries:
            upper_start = event.end_frame + gap
            while (
                candidate_index < len(candidates)
                and candidates[candidate_index][1].start_frame
                <= upper_start
            ):
                added = candidates[candidate_index][1]
                best_end_by_pitch[added.pitch] = max(
                    best_end_by_pitch[added.pitch],
                    added.end_frame,
                )
                candidate_index += 1
            lower_end = event.start_frame - gap
            found = False
            for pitch_delta in range(
                1,
                params.flicker_max_pitch_distance + 1,
            ):
                for pitch in (
                    event.pitch - pitch_delta,
                    event.pitch + pitch_delta,
                ):
                    if (
                        0 <= pitch <= 127
                        and best_end_by_pitch[pitch] >= 0
                        and best_end_by_pitch[pitch] >= lower_end
                    ):
                        supported.add(id(event))
                        found = True
                        break
                if found:
                    break
    return frozenset(supported)


def _regular_repeat_event_ids(
    all_events: Sequence[FrameNoteEvent],
    params: FragmentCleanupParams,
) -> frozenset[int]:
    by_pitch_and_start: dict[
        int,
        dict[int, list[FrameNoteEvent]],
    ] = {}
    for event in all_events:
        by_pitch_and_start.setdefault(event.pitch, {}).setdefault(
            event.start_frame,
            [],
        ).append(event)
    supported: set[int] = set()
    for by_start in by_pitch_and_start.values():
        starts = sorted(by_start)
        for index in range(1, len(starts) - 1):
            previous = starts[index - 1]
            current = starts[index]
            interval = current - previous
            tolerance = max(
                params.repeat_period_min_tolerance_frames,
                int(
                    round(
                        interval
                        * params.repeat_period_tolerance_ratio
                    )
                ),
            )
            neighbours = [starts[index + 1] - current]
            if index > 1:
                neighbours.append(previous - starts[index - 2])
            if any(
                neighbour > 0
                and abs(neighbour - interval) <= tolerance
                for neighbour in neighbours
            ):
                supported.update(id(event) for event in by_start[current])
    return frozenset(supported)


@dataclass(frozen=True)
class _FragmentContext:
    chord_supported: frozenset[int]
    sequence_supported: frozenset[int]
    pitch_flicker: frozenset[int]
    regular_repeat: frozenset[int]


def _fragment_context(
    all_events: Sequence[FrameNoteEvent],
    params: FragmentCleanupParams,
    *,
    chord_supported: frozenset[int] | None = None,
    pitch_flicker: frozenset[int] | None = None,
) -> _FragmentContext:
    return _FragmentContext(
        _chord_supported_event_ids(all_events, params)
        if chord_supported is None
        else chord_supported,
        _sequence_supported_event_ids(all_events, params),
        _pitch_flicker_event_ids(all_events, params)
        if pitch_flicker is None
        else pitch_flicker,
        _regular_repeat_event_ids(all_events, params),
    )


def _flags_for_event(
    item: _WorkingEvent,
    context: _FragmentContext,
    params: FragmentCleanupParams,
) -> frozenset[FragmentFlag]:
    event = item.event
    event_id = id(event)
    flags: set[FragmentFlag] = set()
    if item.merge_count:
        flags.add("auto_merged")
    if item.nms_absorbed:
        flags.add("nms_survivor")
    if event.span_frames <= params.severe_fragment_max_frames:
        flags.add("severe_fragment")
    if event.span_frames <= params.review_fragment_max_frames:
        flags.add("review_fragment")
    if event.span_frames <= params.density_fragment_max_frames:
        flags.add("short_density")
    if event_id in context.pitch_flicker:
        flags.add("pitch_flicker")
    if event_id in context.chord_supported:
        flags.add("chord_supported")
    if event_id in context.sequence_supported:
        flags.add("sequence_supported")
    if event_id in context.regular_repeat:
        flags.add("regular_repeat")
    return frozenset(flags)


def _should_clean_suppress(
    event: FrameNoteEvent,
    flags: frozenset[FragmentFlag],
    *,
    frame: np.ndarray,
    onset: np.ndarray,
    midi_min: int,
    onset_threshold: float,
    params: FragmentCleanupParams,
) -> bool:
    if event.span_frames > params.severe_fragment_max_frames:
        return False
    if event.confidence >= params.clean_max_confidence:
        return False
    if {
        "auto_merged",
        "chord_supported",
        "pitch_flicker",
        "regular_repeat",
        "sequence_supported",
    } & flags:
        return False
    onset_peak, onset_prominence = _onset_features(
        event,
        onset,
        midi_min,
        params,
    )
    if (
        onset_peak >= onset_threshold
        or onset_prominence >= params.max_weak_onset_prominence
    ):
        return False
    return _frame_support(event, frame, midi_min) < (
        params.clean_max_frame_support
    )


def _preview_automatic_action_lineage(
    working: Sequence[_WorkingEvent],
    *,
    profile: CleanupProfile,
    frame: np.ndarray,
    onset: np.ndarray,
    midi_min: int,
    onset_threshold: float,
    frame_threshold: float,
    params: FragmentCleanupParams,
) -> tuple[frozenset[str], _FragmentContext | None]:
    """Dry-run unverified actions and return every implicated raw lineage."""

    if profile == PRESERVE_CLEANUP_PROFILE or not working:
        return frozenset(), None
    preview = [
        _WorkingEvent(
            item.event,
            item.attack_frames,
            item.merge_count,
            item.nms_absorbed,
        )
        for item in working
    ]
    candidate_lineage: set[str] = set()
    preview, nms_audit, nms_count = _same_pitch_nms(preview, params)
    for audit in nms_audit:
        candidate_lineage.update(audit.event.lineage)
    for item in preview:
        if item.nms_absorbed:
            candidate_lineage.update(item.event.lineage)

    premerge_events = tuple(item.event for item in preview)
    premerge_chord_support = _chord_supported_event_ids(
        premerge_events,
        params,
    )
    premerge_pitch_flicker = _pitch_flicker_event_ids(
        premerge_events,
        params,
    )
    preview, merge_count = _merge_same_pitch_gaps(
        preview,
        frame=frame,
        onset=onset,
        midi_min=midi_min,
        frame_threshold=frame_threshold,
        params=params,
        chord_supported_event_ids=premerge_chord_support,
        pitch_flicker_event_ids=premerge_pitch_flicker,
    )
    for item in preview:
        if item.merge_count:
            candidate_lineage.update(item.event.lineage)

    reusable_context: _FragmentContext | None = None
    preview_context: _FragmentContext | None = None
    if profile == CLEAN_CLEANUP_PROFILE or (
        nms_count == 0 and merge_count == 0
    ):
        preview_context = _fragment_context(
            tuple(item.event for item in preview),
            params,
            chord_supported=(
                premerge_chord_support if merge_count == 0 else None
            ),
            pitch_flicker=(
                premerge_pitch_flicker if merge_count == 0 else None
            ),
        )
    if nms_count == 0 and merge_count == 0:
        reusable_context = preview_context
    if profile == CLEAN_CLEANUP_PROFILE:
        assert preview_context is not None
        for item in preview:
            flags = _flags_for_event(item, preview_context, params)
            if _should_clean_suppress(
                item.event,
                flags,
                frame=frame,
                onset=onset,
                midi_min=midi_min,
                onset_threshold=onset_threshold,
                params=params,
            ):
                candidate_lineage.update(item.event.lineage)
    return frozenset(candidate_lineage), reusable_context


def _run_frame_event_postprocess(
    events: Iterable[FrameEventInput],
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    *,
    profile: CleanupProfile,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    midi_min: int = 21,
    params: FragmentCleanupParams = V1_PARAMS,
    apply_automatic_actions: bool,
) -> FragmentPostprocessResult:
    if profile not in {
        PRESERVE_CLEANUP_PROFILE,
        BALANCED_CLEANUP_PROFILE,
        CLEAN_CLEANUP_PROFILE,
    }:
        raise ValueError(f"unsupported cleanup profile: {profile!r}")
    onset_threshold = float(onset_threshold)
    frame_threshold = float(frame_threshold)
    if (
        not math.isfinite(onset_threshold)
        or not 0.0 <= onset_threshold <= 1.0
        or not math.isfinite(frame_threshold)
        or not 0.0 <= frame_threshold <= 1.0
    ):
        raise ValueError("evidence thresholds must be finite and in range 0..1")
    midi_min = _strict_int(midi_min, "midi_min")
    automatic_actions_enabled = bool(
        apply_automatic_actions
        and profile != PRESERVE_CLEANUP_PROFILE
    )
    frame, onset = _validate_evidence(frame_evidence, onset_evidence)

    normalised = sorted(
        (_coerce_event(item) for item in events),
        key=_event_sort_key,
    )
    if normalised and max(item.end_frame for item in normalised) > frame.shape[0]:
        raise ValueError("event frames exceed the evidence timeline")

    working, removal_audit, exact_duplicate_count = _deduplicate_exact(
        normalised
    )
    nms_removed_count = 0
    automatic_merge_count = 0
    cleanup_candidate_lineage: frozenset[str] = frozenset()
    annotation_context: _FragmentContext | None = None
    reusable_chord_support: frozenset[int] | None = None
    reusable_pitch_flicker: frozenset[int] | None = None
    if (
        automatic_actions_enabled
        and profile != PRESERVE_CLEANUP_PROFILE
        and working
    ):
        working, nms_audit, nms_removed_count = _same_pitch_nms(
            working,
            params,
        )
        removal_audit.extend(nms_audit)
        premerge_events = tuple(item.event for item in working)
        premerge_chord_support = _chord_supported_event_ids(
            premerge_events,
            params,
        )
        premerge_pitch_flicker = _pitch_flicker_event_ids(
            premerge_events,
            params,
        )
        working, automatic_merge_count = _merge_same_pitch_gaps(
            working,
            frame=frame,
            onset=onset,
            midi_min=midi_min,
            frame_threshold=frame_threshold,
            params=params,
            chord_supported_event_ids=premerge_chord_support,
            pitch_flicker_event_ids=premerge_pitch_flicker,
        )
        if automatic_merge_count == 0:
            reusable_chord_support = premerge_chord_support
            reusable_pitch_flicker = premerge_pitch_flicker
    elif working:
        # Preserve remains non-mutating, but the UI still benefits from the
        # exact same evidence gate as the balanced profile.  Mark only the
        # lineage that balanced would merge/deduplicate so presentation can
        # connect false-split fragments without changing candidate identity.
        preview_profile = (
            BALANCED_CLEANUP_PROFILE
            if profile == PRESERVE_CLEANUP_PROFILE
            else profile
        )
        (
            cleanup_candidate_lineage,
            annotation_context,
        ) = _preview_automatic_action_lineage(
            working,
            profile=preview_profile,
            frame=frame,
            onset=onset,
            midi_min=midi_min,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            params=params,
        )

    context = (
        annotation_context
        if annotation_context is not None
        else _fragment_context(
            tuple(item.event for item in working),
            params,
            chord_supported=reusable_chord_support,
            pitch_flicker=reusable_pitch_flicker,
        )
    )
    kept: list[FrameNoteEvent] = []
    suppressed: list[FrameNoteEvent] = []
    output_audit: list[FragmentAudit] = []
    suspected_fragment_count = 0
    severe_fragment_count = 0
    density_short_count = 0
    pitch_flicker_count = 0
    for item in working:
        flags = _flags_for_event(item, context, params)
        cleanup_candidate = bool(
            cleanup_candidate_lineage.intersection(item.event.lineage)
        )
        if cleanup_candidate:
            flags = frozenset(
                set(flags) | {"cleanup_candidate", "review_fragment"}
            )
        suspected_fragment_count += "review_fragment" in flags
        severe_fragment_count += "severe_fragment" in flags
        density_short_count += "short_density" in flags
        pitch_flicker_count += "pitch_flicker" in flags
        if (
            automatic_actions_enabled
            and profile == CLEAN_CLEANUP_PROFILE
            and _should_clean_suppress(
                item.event,
                flags,
                frame=frame,
                onset=onset,
                midi_min=midi_min,
                onset_threshold=onset_threshold,
                params=params,
            )
        ):
            suppressed.append(item.event)
            output_audit.append(
                FragmentAudit(
                    item.event,
                    "suppressed",
                    frozenset(set(flags) | {"clean_suppressed"}),
                    "isolated_weak_severe_fragment",
                )
            )
            continue
        kept.append(item.event)
        output_audit.append(
            FragmentAudit(
                item.event,
                "merged" if item.merge_count else "kept",
                flags,
                (
                    "weak_same_pitch_split"
                    if item.merge_count
                    else "automatic_cleanup_preview"
                    if cleanup_candidate
                    else ""
                ),
            )
        )

    all_audit = tuple(
        sorted(removal_audit + output_audit, key=_audit_sort_key)
    )
    stats = FragmentPostprocessStats(
        input_count=len(normalised),
        output_count=len(kept),
        exact_duplicate_count=exact_duplicate_count,
        nms_removed_count=nms_removed_count,
        automatic_merge_count=automatic_merge_count,
        suspected_fragment_count=suspected_fragment_count,
        severe_fragment_count=severe_fragment_count,
        density_short_count=density_short_count,
        pitch_flicker_count=pitch_flicker_count,
        suppressed_count=len(suppressed),
    )
    return FragmentPostprocessResult(
        tuple(kept),
        tuple(suppressed),
        all_audit,
        stats,
        profile,
        params.version,
        automatic_actions_enabled,
    )


def postprocess_frame_events(
    events: Iterable[FrameEventInput],
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    *,
    profile: CleanupProfile = PRESERVE_CLEANUP_PROFILE,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    midi_min: int = 21,
    params: FragmentCleanupParams = V1_PARAMS,
) -> FragmentPostprocessResult:
    """Apply the cleanup profile selected by the caller.

    ``preserve`` only sorts and removes exact duplicates. ``balanced`` applies
    deterministic same-pitch NMS and evidence-gated false-split merging.
    ``clean`` applies the balanced actions and additionally hides isolated,
    weak, severe fragments in the reversible ``suppressed`` sidecar.

    Selecting a profile is the opt-in: there is no separate production gate
    or action switch that can silently turn ``balanced`` or ``clean`` into
    ``preserve``. Use :func:`preview_frame_event_cleanup` for an explicit dry
    run.
    """

    return _run_frame_event_postprocess(
        events,
        frame_evidence,
        onset_evidence,
        profile=profile,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        midi_min=midi_min,
        params=params,
        apply_automatic_actions=True,
    )


def preview_frame_event_cleanup(
    events: Iterable[FrameEventInput],
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    *,
    profile: CleanupProfile = PRESERVE_CLEANUP_PROFILE,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    midi_min: int = 21,
    params: FragmentCleanupParams = V1_PARAMS,
) -> FragmentPostprocessResult:
    """Preview automatic actions without merging or suppressing candidates.

    Exact duplicates are still removed because that operation is part of all
    three profiles. Potential NMS, merge, and clean suppression decisions are
    exposed through ``cleanup_candidate`` flags and the audit lineage.
    """

    return _run_frame_event_postprocess(
        events,
        frame_evidence,
        onset_evidence,
        profile=profile,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        midi_min=midi_min,
        params=params,
        apply_automatic_actions=False,
    )


__all__ = [
    "BALANCED_CLEANUP_PROFILE",
    "CLEAN_CLEANUP_PROFILE",
    "CleanupProfile",
    "FragmentAudit",
    "FragmentCleanupParams",
    "FragmentFlag",
    "FragmentPostprocessResult",
    "FragmentPostprocessStats",
    "FrameNoteEvent",
    "POSTPROCESS_VERSION",
    "PRESERVE_CLEANUP_PROFILE",
    "V1_PARAMS",
    "postprocess_frame_events",
    "preview_frame_event_cleanup",
]
