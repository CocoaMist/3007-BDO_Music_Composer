"""Pure clock policy for synchronizing reference and rendered preview audio.

The reference decoder and the BDO preview engine are independent transports.
Callers choose one project-time master and use this module to decide when the
reference transport must seek, play, or pause.  Keeping the policy Qt-free
makes the timing contract deterministic and directly regression-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


REFERENCE_CLOCK_SOFT_DRIFT_MS = 80.0
REFERENCE_CLOCK_HARD_DRIFT_MS = 250.0
REFERENCE_CLOCK_RESYNC_COOLDOWN_S = 0.35


@dataclass(frozen=True, slots=True)
class ReferenceClockDecision:
    inside_reference: bool
    drift_ms: float
    seek: bool
    play: bool
    pause: bool


def reference_clock_decision(
    *,
    master_project_ms: float,
    reference_project_ms: float,
    reference_audio_ms: float,
    reference_duration_ms: float,
    reference_is_playing: bool,
    want_playback: bool,
    force_seek: bool,
    now_seconds: float,
    last_resync_seconds: float,
) -> ReferenceClockDecision:
    """Return one bounded synchronization action for a project-time master."""

    values = (
        master_project_ms,
        reference_project_ms,
        reference_audio_ms,
        reference_duration_ms,
        now_seconds,
        last_resync_seconds,
    )
    if any(not math.isfinite(float(value)) for value in values):
        return ReferenceClockDecision(False, 0.0, False, False, bool(reference_is_playing))

    master = float(master_project_ms)
    reference = float(reference_project_ms)
    audio = float(reference_audio_ms)
    duration = max(0.0, float(reference_duration_ms))
    now = float(now_seconds)
    last_resync = float(last_resync_seconds)
    inside = audio >= 0.0 and (duration <= 0.0 or audio < duration)
    drift = reference - master
    absolute_drift = abs(drift)
    cooldown_elapsed = (
        now - last_resync >= REFERENCE_CLOCK_RESYNC_COOLDOWN_S
    )
    seek = bool(
        inside
        and (
            force_seek
            or absolute_drift >= REFERENCE_CLOCK_HARD_DRIFT_MS
            or (
                absolute_drift >= REFERENCE_CLOCK_SOFT_DRIFT_MS
                and cooldown_elapsed
            )
        )
    )
    should_play = bool(
        want_playback and inside and not reference_is_playing
    )
    should_pause = bool(
        reference_is_playing and (not want_playback or not inside)
    )
    return ReferenceClockDecision(
        inside,
        drift,
        seek,
        should_play,
        should_pause,
    )


__all__ = [
    "REFERENCE_CLOCK_HARD_DRIFT_MS",
    "REFERENCE_CLOCK_RESYNC_COOLDOWN_S",
    "REFERENCE_CLOCK_SOFT_DRIFT_MS",
    "ReferenceClockDecision",
    "reference_clock_decision",
]
