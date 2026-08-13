"""Deterministic bounded magnetic alignment for arrangement Clips."""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
import math
from typing import Iterable


MAX_SNAP_TARGETS = 8192


@dataclass(frozen=True, slots=True)
class ArrangementSnapTarget:
    time_ms: float
    kind: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class ArrangementSnapResult:
    start_ms: float
    target_ms: float | None = None
    kind: str = ""
    label: str = ""


@dataclass(frozen=True, slots=True)
class ArrangementSnapIndex:
    """Immutable drag-lifetime index; neighbor lookup avoids frame-time scans."""

    targets: tuple[ArrangementSnapTarget, ...]
    times: tuple[float, ...]
    marker_targets: tuple[ArrangementSnapTarget, ...] = ()
    marker_times: tuple[float, ...] = ()
    clip_targets: tuple[ArrangementSnapTarget, ...] = ()
    clip_times: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class OccupiedClipIndex:
    intervals: tuple[tuple[float, float], ...]
    starts: tuple[float, ...]


def normalize_snap_targets(
    targets: Iterable[ArrangementSnapTarget],
) -> tuple[ArrangementSnapTarget, ...]:
    priority = {"marker": 0, "clip": 1, "grid": 2}
    buckets: dict[int, list[ArrangementSnapTarget]] = {
        0: [], 1: [], 2: [], 3: [],
    }
    seen: dict[int, set[tuple[float, str]]] = {
        0: set(), 1: set(), 2: set(), 3: set(),
    }
    for target in targets:
        try:
            value = float(target.time_ms)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(value) or value < 0.0:
            continue
        kind = str(target.kind)
        bucket_id = priority.get(kind, 3)
        bucket = buckets[bucket_id]
        if len(bucket) >= MAX_SNAP_TARGETS:
            continue
        key = (round(value, 6), kind)
        if key in seen[bucket_id]:
            continue
        seen[bucket_id].add(key)
        bucket.append(ArrangementSnapTarget(value, kind, str(target.label)[:80]))
    # High-priority semantic targets cannot be starved by a large number of
    # lower-priority Clip edges supplied earlier in the input stream.
    result: list[ArrangementSnapTarget] = []
    for bucket_id in range(4):
        remaining = MAX_SNAP_TARGETS - len(result)
        if remaining <= 0:
            break
        result.extend(buckets[bucket_id][:remaining])
    return tuple(result)


def build_snap_index(
    targets: Iterable[ArrangementSnapTarget],
) -> ArrangementSnapIndex:
    priority = {"marker": 0, "clip": 1, "grid": 2}
    normalized = sorted(
        normalize_snap_targets(targets),
        key=lambda target: (
            target.time_ms,
            priority.get(target.kind, 3),
            target.label,
        ),
    )
    # Only the highest-priority semantic target at an exact time can win.
    # Collapsing here also makes each pointer-move query strictly bounded.
    collapsed: list[ArrangementSnapTarget] = []
    previous_time: float | None = None
    for target in normalized:
        rounded_time = round(target.time_ms, 6)
        if previous_time == rounded_time:
            continue
        collapsed.append(target)
        previous_time = rounded_time
    result = tuple(collapsed)
    markers = tuple(item for item in result if item.kind == "marker")
    clips = tuple(item for item in result if item.kind == "clip")
    return ArrangementSnapIndex(
        result,
        tuple(item.time_ms for item in result),
        markers,
        tuple(item.time_ms for item in markers),
        clips,
        tuple(item.time_ms for item in clips),
    )


def _neighbor_targets(
    targets: tuple[ArrangementSnapTarget, ...],
    times: tuple[float, ...],
    time_ms: float,
) -> tuple[ArrangementSnapTarget, ...]:
    position = bisect_left(times, time_ms)
    return tuple(
        targets[item]
        for item in (position - 1, position)
        if 0 <= item < len(targets)
    )


def build_occupied_clip_index(
    intervals: Iterable[tuple[float, float]],
) -> OccupiedClipIndex:
    normalized = sorted(
        (max(0.0, float(start)), float(end))
        for start, end in intervals
        if math.isfinite(float(start))
        and math.isfinite(float(end))
        and float(end) > max(0.0, float(start))
    )
    result = tuple(normalized)
    return OccupiedClipIndex(result, tuple(start for start, _end in result))


def align_overlapping_clip(
    proposed_start_ms: float,
    duration_ms: float,
    occupied: OccupiedClipIndex,
) -> ArrangementSnapResult:
    """Move an overlapping Clip to the nearest free adjacent boundary."""

    start = max(0.0, float(proposed_start_ms))
    duration = max(0.0, float(duration_ms))
    end = start + duration
    if not occupied.intervals or duration <= 0.0:
        return ArrangementSnapResult(start)
    position = bisect_left(occupied.starts, end)
    overlap_index = next(
        (
            index
            for index in (position - 1, position)
            if 0 <= index < len(occupied.intervals)
            and occupied.intervals[index][0] < end
            and start < occupied.intervals[index][1]
        ),
        None,
    )
    if overlap_index is None:
        return ArrangementSnapResult(start)

    left = occupied.intervals[overlap_index][0] - duration
    left_index = overlap_index - 1
    while left >= 0.0 and left_index >= 0:
        previous = occupied.intervals[left_index]
        if previous[1] <= left:
            break
        left = previous[0] - duration
        left_index -= 1

    right = occupied.intervals[overlap_index][1]
    right_index = overlap_index + 1
    while right_index < len(occupied.intervals):
        following = occupied.intervals[right_index]
        if right + duration <= following[0]:
            break
        right = following[1]
        right_index += 1

    candidates = [(abs(right - start), right)]
    if left >= 0.0:
        candidates.append((abs(left - start), left))
    _distance, aligned = min(candidates)
    target_ms = aligned if aligned >= start else aligned + duration
    return ArrangementSnapResult(aligned, target_ms, "clip", "")


def snap_clip_start(
    proposed_start_ms: float,
    duration_ms: float,
    targets: Iterable[ArrangementSnapTarget] | ArrangementSnapIndex,
    *,
    tolerance_ms: float,
    grid_ms: float | None = None,
    grid_origin_ms: float = 0.0,
) -> ArrangementSnapResult:
    """Snap either Clip edge to the closest target without changing duration."""

    start = max(0.0, float(proposed_start_ms))
    duration = max(0.0, float(duration_ms))
    tolerance = max(0.0, float(tolerance_ms))
    candidates: list[tuple[int, float, float, float, str, str]] = []
    priority = {"marker": 0, "clip": 1, "grid": 2}
    edges = (start, start + duration)
    index = targets if isinstance(targets, ArrangementSnapIndex) else build_snap_index(targets)
    for edge in edges:
        for kind_targets, kind_times in (
            (index.marker_targets, index.marker_times),
            (index.clip_targets, index.clip_times),
        ):
            for target in _neighbor_targets(kind_targets, kind_times, edge):
                delta = float(target.time_ms) - edge
                if abs(delta) <= tolerance:
                    candidates.append((
                        priority.get(target.kind, 3), abs(delta), delta,
                        float(target.time_ms), target.kind, target.label,
                    ))
    if grid_ms is not None and math.isfinite(float(grid_ms)) and float(grid_ms) > 0.0:
        grid = float(grid_ms)
        origin = float(grid_origin_ms)
        for edge in edges:
            target = origin + round((edge - origin) / grid) * grid
            delta = target - edge
            if abs(delta) <= tolerance:
                candidates.append((2, abs(delta), delta, target, "grid", ""))
    if not candidates:
        return ArrangementSnapResult(start)
    _priority, _distance, delta, target_ms, kind, label = min(candidates)
    snapped = max(0.0, start + delta)
    return ArrangementSnapResult(snapped, target_ms, kind, label)


__all__ = [
    "ArrangementSnapResult",
    "ArrangementSnapIndex",
    "ArrangementSnapTarget",
    "OccupiedClipIndex",
    "MAX_SNAP_TARGETS",
    "align_overlapping_clip",
    "build_occupied_clip_index",
    "build_snap_index",
    "normalize_snap_targets",
    "snap_clip_start",
]
