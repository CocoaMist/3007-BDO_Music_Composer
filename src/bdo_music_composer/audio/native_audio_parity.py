"""Fail-closed semantic parity gate for the optional native audio core."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


PARITY_MAX_ABSOLUTE_ERROR = 1e-6
PARITY_MAX_RMS_ERROR = 1e-7


@dataclass(frozen=True, slots=True)
class NativeAudioParityResult:
    frames: int
    max_absolute_error: float
    rms_error: float
    finite: bool
    passed: bool
    reason: str


def compare_audio_blocks(
    reference: np.ndarray,
    candidate: np.ndarray,
    *,
    max_absolute_error: float = PARITY_MAX_ABSOLUTE_ERROR,
    max_rms_error: float = PARITY_MAX_RMS_ERROR,
) -> NativeAudioParityResult:
    """Compare exact-shape stereo blocks without accepting NaN/Inf."""

    left = np.asarray(reference, dtype=np.float32)
    right = np.asarray(candidate, dtype=np.float32)
    if left.shape != right.shape or left.ndim != 2 or left.shape[1] != 2:
        return NativeAudioParityResult(0, float("inf"), float("inf"), False, False, "shape-mismatch")
    finite = bool(np.isfinite(left).all() and np.isfinite(right).all())
    if not finite:
        return NativeAudioParityResult(len(left), float("inf"), float("inf"), False, False, "non-finite")
    delta = np.asarray(right - left, dtype=np.float64)
    maximum = float(np.max(np.abs(delta), initial=0.0))
    rms = float(np.sqrt(np.mean(delta * delta))) if delta.size else 0.0
    passed = maximum <= max_absolute_error and rms <= max_rms_error
    return NativeAudioParityResult(
        len(left), maximum, rms, True, passed, "passed" if passed else "audio-mismatch"
    )


__all__ = [
    "NativeAudioParityResult",
    "PARITY_MAX_ABSOLUTE_ERROR",
    "PARITY_MAX_RMS_ERROR",
    "compare_audio_blocks",
]
