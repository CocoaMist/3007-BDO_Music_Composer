"""Score-wide BDO velocity base and optional normalization helpers."""

from __future__ import annotations

from collections.abc import Iterable
from math import floor


BDO_VELOCITY_MIN = 0
BDO_VELOCITY_MAX = 127


def _round_half_up(value: float) -> int:
    return int(floor(float(value) + 0.5))


def base_velocity_map(
    velocities: Iterable[int],
    base: int,
    reference_base: int,
    *,
    equalize: bool,
) -> dict[int, int]:
    """Add a free base, then optionally normalize the whole set as one group."""

    levels = sorted({int(value) for value in velocities})
    delta = int(base) - int(reference_base)
    raw = {level: level + delta for level in levels}
    if not raw:
        return {0: 0}

    if not equalize:
        mapped = {
            level: max(BDO_VELOCITY_MIN, min(BDO_VELOCITY_MAX, value))
            for level, value in raw.items()
        }
    else:
        low, high = min(raw.values()), max(raw.values())
        if BDO_VELOCITY_MIN <= low and high <= BDO_VELOCITY_MAX:
            mapped = dict(raw)
        elif low >= BDO_VELOCITY_MIN:
            # User-selected B mapping: scale the entire positive group from
            # zero, so the largest adjusted value becomes 127.
            scale = BDO_VELOCITY_MAX / high
            mapped = {
                level: _round_half_up(value * scale)
                for level, value in raw.items()
            }
        elif high <= BDO_VELOCITY_MAX:
            # Symmetric lower-bound case: scale all distances from 127 so the
            # smallest adjusted value becomes zero.
            scale = BDO_VELOCITY_MAX / (BDO_VELOCITY_MAX - low)
            mapped = {
                level: _round_half_up(
                    BDO_VELOCITY_MAX
                    - (BDO_VELOCITY_MAX - value) * scale
                )
                for level, value in raw.items()
            }
        else:
            scale = BDO_VELOCITY_MAX / (high - low)
            mapped = {
                level: _round_half_up((value - low) * scale)
                for level, value in raw.items()
            }
    return mapped
