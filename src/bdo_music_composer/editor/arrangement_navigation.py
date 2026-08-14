"""Pure timeline navigation and viewport calculations.

The Qt canvas owns focus and painting; this module keeps DAW-style keyboard
movement deterministic and independently testable.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True, slots=True)
class TimelineViewport:
    zoom_factor: float
    start_ms: float


def timeline_grid_step_ms(
    bpm: int,
    *,
    coarse: bool = False,
    fine: bool = False,
) -> float:
    """Return one keyboard movement step without depending on paint density."""

    beat_ms = 60_000.0 / max(1, int(bpm))
    if coarse:
        return beat_ms
    if fine:
        return beat_ms / 16.0
    return beat_ms / 4.0


def normalized_boundaries(values: Iterable[float]) -> tuple[float, ...]:
    """Return finite, non-negative, de-duplicated timeline boundaries."""

    return tuple(sorted({
        round(float(value), 6)
        for value in values
        if math.isfinite(float(value)) and float(value) >= 0.0
    }))


def neighboring_boundary(
    boundaries: tuple[float, ...],
    current_ms: float,
    direction: int,
) -> float:
    """Move to the previous/next exact boundary, clamping at either end."""

    if not boundaries:
        return max(0.0, float(current_ms))
    current = max(0.0, float(current_ms))
    if direction < 0:
        index = bisect_left(boundaries, current - 1e-6) - 1
        return boundaries[max(0, index)]
    index = bisect_right(boundaries, current + 1e-6)
    return boundaries[min(len(boundaries) - 1, index)]


def viewport_for_range(
    timeline_end_ms: float,
    start_ms: float,
    end_ms: float,
    *,
    margin_ratio: float = 0.08,
) -> TimelineViewport:
    """Fit a time range into the viewport with a small context margin."""

    timeline_end = max(1.0, float(timeline_end_ms))
    start = max(0.0, min(float(start_ms), timeline_end))
    end = max(start, min(float(end_ms), timeline_end))
    span = max(1.0, end - start)
    padded_span = min(timeline_end, span * (1.0 + 2.0 * margin_ratio))
    zoom = max(0.25, min(32.0, timeline_end / padded_span))
    visible = timeline_end / zoom
    center = (start + end) / 2.0
    max_start = max(0.0, timeline_end - visible)
    view_start = max(0.0, min(center - visible / 2.0, max_start))
    return TimelineViewport(zoom, view_start)


__all__ = [
    "TimelineViewport",
    "neighboring_boundary",
    "normalized_boundaries",
    "timeline_grid_step_ms",
    "viewport_for_range",
]
