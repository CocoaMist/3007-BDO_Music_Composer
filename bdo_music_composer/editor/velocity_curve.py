"""Pure editor velocity-curve transforms shared by UI and tests."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


VELOCITY_CURVE_SHAPES = frozenset({"linear", "smooth", "ease_in", "ease_out"})


@dataclass(frozen=True, slots=True, order=True)
class VelocityEnvelopePoint:
    """One exact user-authored point in normalized time and MIDI velocity."""

    time: float
    velocity: float
    left_weight: float = 1.0 / 3.0
    right_weight: float = 1.0 / 3.0


def normalize_velocity_envelope_points(
    points: Iterable[VelocityEnvelopePoint],
) -> tuple[VelocityEnvelopePoint, ...]:
    """Clamp, sort and de-duplicate an arbitrary point envelope."""

    by_time: dict[float, VelocityEnvelopePoint] = {}
    for point in points:
        time = round(max(0.0, min(1.0, float(point.time))), 6)
        velocity = round(max(0.0, min(127.0, float(point.velocity))), 4)
        left_weight = max(0.02, min(0.95, float(point.left_weight)))
        right_weight = max(0.02, min(0.95, float(point.right_weight)))
        by_time[time] = VelocityEnvelopePoint(
            time,
            velocity,
            left_weight,
            right_weight,
        )
    if not by_time:
        by_time[0.0] = VelocityEnvelopePoint(0.0, 100.0)
        by_time[1.0] = VelocityEnvelopePoint(1.0, 100.0)
    elif len(by_time) == 1:
        only = next(iter(by_time.values()))
        by_time[0.0] = VelocityEnvelopePoint(0.0, only.velocity)
        by_time[1.0] = VelocityEnvelopePoint(1.0, only.velocity)
    else:
        ordered = sorted(by_time.values())
        by_time.setdefault(0.0, VelocityEnvelopePoint(0.0, ordered[0].velocity))
        by_time.setdefault(1.0, VelocityEnvelopePoint(1.0, ordered[-1].velocity))
    return tuple(sorted(by_time.values()))


def _shape_preserving_slopes(
    points: Sequence[VelocityEnvelopePoint],
) -> tuple[float, ...]:
    """Return PCHIP slopes that do not overshoot adjacent user points."""

    count = len(points)
    if count == 2:
        slope = (
            points[1].velocity - points[0].velocity
        ) / (points[1].time - points[0].time)
        return slope, slope
    widths = [points[index + 1].time - points[index].time for index in range(count - 1)]
    deltas = [
        (points[index + 1].velocity - points[index].velocity)
        / widths[index]
        for index in range(count - 1)
    ]
    slopes = [0.0] * count
    for index in range(1, count - 1):
        before, after = deltas[index - 1], deltas[index]
        if before == 0.0 or after == 0.0 or before * after <= 0.0:
            continue
        before_weight = 2.0 * widths[index] + widths[index - 1]
        after_weight = widths[index] + 2.0 * widths[index - 1]
        slopes[index] = (before_weight + after_weight) / (
            before_weight / before + after_weight / after
        )

    def endpoint_slope(width0: float, width1: float, delta0: float, delta1: float) -> float:
        slope = ((2.0 * width0 + width1) * delta0 - width0 * delta1) / (
            width0 + width1
        )
        if slope * delta0 <= 0.0:
            return 0.0
        if delta0 * delta1 < 0.0 and abs(slope) > abs(3.0 * delta0):
            return 3.0 * delta0
        return slope

    slopes[0] = endpoint_slope(widths[0], widths[1], deltas[0], deltas[1])
    slopes[-1] = endpoint_slope(
        widths[-1], widths[-2], deltas[-1], deltas[-2]
    )
    return tuple(slopes)


def velocity_envelope_value(
    position: float,
    points: Iterable[VelocityEnvelopePoint],
) -> float:
    """Evaluate an exact, shape-preserving point envelope without overshoot."""

    normalized = normalize_velocity_envelope_points(points)
    return _evaluate_normalized_velocity_envelope(
        position,
        normalized,
        _shape_preserving_slopes(normalized),
    )


def velocity_envelope_samples(
    points: Iterable[VelocityEnvelopePoint],
    count: int,
) -> tuple[float, ...]:
    """Sample one envelope with normalization and slopes computed once."""

    sample_count = max(2, int(count))
    normalized = normalize_velocity_envelope_points(points)
    slopes = _shape_preserving_slopes(normalized)
    return tuple(
        _evaluate_normalized_velocity_envelope(
            index / (sample_count - 1),
            normalized,
            slopes,
        )
        for index in range(sample_count)
    )


def _evaluate_normalized_velocity_envelope(
    position: float,
    normalized: Sequence[VelocityEnvelopePoint],
    slopes: Sequence[float],
) -> float:
    position = max(0.0, min(1.0, float(position)))
    if position <= normalized[0].time:
        return normalized[0].velocity
    if position >= normalized[-1].time:
        return normalized[-1].velocity
    upper = next(
        index
        for index in range(1, len(normalized))
        if position <= normalized[index].time
    )
    lower = upper - 1
    left, right = normalized[lower], normalized[upper]
    if position == right.time:
        return right.velocity
    width = right.time - left.time
    local = (position - left.time) / width
    local2, local3 = local * local, local * local * local
    delta = (right.velocity - left.velocity) / width
    left_slope = slopes[lower] * left.right_weight * 3.0
    right_slope = slopes[upper] * right.left_weight * 3.0
    if delta == 0.0:
        left_slope = right_slope = 0.0
    else:
        alpha = max(0.0, left_slope / delta)
        beta = max(0.0, right_slope / delta)
        magnitude = alpha * alpha + beta * beta
        if magnitude > 9.0:
            limiter = 3.0 / magnitude**0.5
            alpha *= limiter
            beta *= limiter
        left_slope = alpha * delta
        right_slope = beta * delta
    return (
        (2.0 * local3 - 3.0 * local2 + 1.0) * left.velocity
        + (local3 - 2.0 * local2 + local) * width * left_slope
        + (-2.0 * local3 + 3.0 * local2) * right.velocity
        + (local3 - local2) * width * right_slope
    )


def apply_velocity_level_envelope(
    notes: Sequence[Any],
    indices: Iterable[int],
    points: Iterable[VelocityEnvelopePoint],
    *,
    start_ms: float | None = None,
    end_ms: float | None = None,
) -> list[Any]:
    """Match onset-average MIDI velocity to an authored point envelope."""

    result = list(notes)
    chosen = sorted({int(index) for index in indices if 0 <= int(index) < len(result)})
    if not chosen:
        return result
    normalized = normalize_velocity_envelope_points(points)
    slopes = _shape_preserving_slopes(normalized)
    starts = [float(result[index].start) for index in chosen]
    first_start = min(starts) if start_ms is None else float(start_ms)
    last_start = max(starts) if end_ms is None else float(end_ms)
    if last_start < first_start:
        first_start, last_start = last_start, first_start
    span = last_start - first_start
    onset_groups: dict[float, list[int]] = {}
    for index in chosen:
        onset_groups.setdefault(round(float(result[index].start), 3), []).append(index)
    for onset_key, group_indices in onset_groups.items():
        onset = float(onset_key)
        position = 0.0 if span <= 0.0 else (onset - first_start) / span
        target = _evaluate_normalized_velocity_envelope(
            position,
            normalized,
            slopes,
        )
        baseline = sum(float(result[index].vel) for index in group_indices) / len(group_indices)
        for index in group_indices:
            velocity = (
                target
                if baseline <= 0.0
                else float(result[index].vel) * target / baseline
            )
            result[index] = result[index]._replace(
                vel=max(0, min(127, round(velocity)))
            )
    return result


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


def velocity_envelope_points_from_notes(
    notes: Sequence[Any],
    indices: Iterable[int],
    *,
    start_ms: float,
    end_ms: float,
    max_points: int = 64,
    tolerance: float = 1.5,
) -> tuple[VelocityEnvelopePoint, ...]:
    """Build a bounded, error-driven envelope from authoritative Note.vel."""

    grouped = velocity_time_points(notes, indices)
    if not grouped:
        return (
            VelocityEnvelopePoint(0.0, 100.0),
            VelocityEnvelopePoint(1.0, 100.0),
        )
    span = max(0.001, float(end_ms) - float(start_ms))
    candidates = [
        VelocityEnvelopePoint(
            max(0.0, min(1.0, (onset - float(start_ms)) / span)),
            average,
        )
        for onset, _point_indices, average in grouped
    ]
    normalized = list(normalize_velocity_envelope_points(candidates))
    if len(normalized) <= max(2, int(max_points)):
        return tuple(normalized)
    selected = {0, len(normalized) - 1}
    point_limit = max(2, int(max_points))
    while len(selected) < point_limit:
        ordered_selected = sorted(selected)
        best_index = -1
        best_error = float(tolerance)
        for left_index, right_index in zip(ordered_selected, ordered_selected[1:]):
            left, right = normalized[left_index], normalized[right_index]
            time_span = max(1e-9, right.time - left.time)
            for index in range(left_index + 1, right_index):
                point = normalized[index]
                progress = (point.time - left.time) / time_span
                estimated = left.velocity + (right.velocity - left.velocity) * progress
                error = abs(point.velocity - estimated)
                if error > best_error:
                    best_error = error
                    best_index = index
        if best_index < 0:
            break
        selected.add(best_index)
    return tuple(normalized[index] for index in sorted(selected))


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
        velocity = max(0, min(127, round(float(note.vel) + float(delta) * weight)))
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
        velocity = max(0, min(127, round(float(result[index].vel) * gain)))
        result[index] = result[index]._replace(vel=velocity)
    return result
