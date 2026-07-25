"""Pure velocity-curve transforms shared by editor UI and tests."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


VELOCITY_CURVE_SHAPES = frozenset({"linear", "smooth", "ease_in", "ease_out"})


def velocity_neighbor_weight(distance_ms: float, radius_ms: float) -> float:
    """Smooth compact falloff for a dragged curve point and its neighbours."""
    radius = max(0.001, float(radius_ms))
    normalized = abs(float(distance_ms)) / radius
    if normalized >= 1.0:
        return 0.0
    # Quartic falloff: full influence at the point, soft near the edge, and
    # exactly zero outside the selected time neighbourhood.
    return (1.0 - normalized * normalized) ** 2


def velocity_time_points(
    notes: Sequence[Any],
    indices: Iterable[int] | None = None,
) -> list[tuple[float, tuple[int, ...], float]]:
    """Group simultaneous notes into one editable curve point per onset."""
    chosen = (
        range(len(notes))
        if indices is None
        else sorted({int(index) for index in indices if 0 <= int(index) < len(notes)})
    )
    groups: dict[float, list[int]] = {}
    for index in chosen:
        onset = round(float(notes[index].start), 3)
        groups.setdefault(onset, []).append(index)
    return [
        (
            onset,
            tuple(point_indices),
            sum(float(notes[index].vel) for index in point_indices) / len(point_indices),
        )
        for onset, point_indices in sorted(groups.items())
    ]


def apply_weighted_velocity_delta(
    notes: Sequence[Any],
    center_ms: float,
    delta: float,
    radius_ms: float,
) -> list[Any]:
    """Move one time point while smoothly influencing neighbouring points."""
    result = list(notes)
    for index, note in enumerate(notes):
        weight = velocity_neighbor_weight(float(note.start) - center_ms, radius_ms)
        if weight <= 0.0:
            continue
        velocity = max(1, min(127, round(float(note.vel) + float(delta) * weight)))
        result[index] = note._replace(vel=velocity)
    return result


def velocity_curve_progress(position: float, shape: str = "linear") -> float:
    """Map normalized time to a stable 0..1 curve position."""
    position = max(0.0, min(1.0, float(position)))
    if shape == "smooth":
        return position * position * (3.0 - 2.0 * position)
    if shape == "ease_in":
        return position * position
    if shape == "ease_out":
        return 1.0 - (1.0 - position) ** 2
    if shape != "linear":
        raise ValueError(f"unknown velocity curve shape: {shape}")
    return position


def apply_velocity_curve(
    notes: Sequence[Any],
    indices: Iterable[int],
    start_percent: int,
    end_percent: int,
    shape: str = "linear",
) -> list[Any]:
    """Scale selected velocities over musical time while preserving dynamics.

    Percentages are gain values rather than absolute velocities, so accents and
    the relative balance between notes survive the global crescendo/decrescendo.
    """
    result = list(notes)
    chosen = sorted({int(index) for index in indices if 0 <= int(index) < len(result)})
    if not chosen:
        return result
    starts = [float(result[index].start) for index in chosen]
    first_start, last_start = min(starts), max(starts)
    span = last_start - first_start
    start_gain = max(1, min(300, int(start_percent))) / 100.0
    end_gain = max(1, min(300, int(end_percent))) / 100.0
    for index in chosen:
        position = 0.0 if span <= 0.0 else (float(result[index].start) - first_start) / span
        curved = velocity_curve_progress(position, shape)
        gain = start_gain + (end_gain - start_gain) * curved
        velocity = max(1, min(127, round(float(result[index].vel) * gain)))
        result[index] = result[index]._replace(vel=velocity)
    return result
