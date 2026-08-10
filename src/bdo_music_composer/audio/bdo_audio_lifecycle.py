"""Shared, Qt-free audible-lifetime policy for BDO sample preview.

The score model stores the formal note-block duration.  Preview additionally
needs a bounded audible tail for naturally decaying instruments.  Keep that
decision here so real-time playback, seeking, key audition, and offline
rendering cannot drift into separate timing rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


GUITAR_IDS = frozenset({0x00, 0x0A, 0x24, 0x25, 0x26})
HARP_IDS = frozenset({0x06, 0x10})
PIANO_IDS = frozenset({0x07, 0x11})
SHORT_ARTICULATION_TYPES = frozenset({2, 13, 22, 24})

_TAIL_MS_BY_INSTRUMENT = {
    **{instrument_id: 800.0 for instrument_id in GUITAR_IDS | HARP_IDS},
    **{instrument_id: 1_200.0 for instrument_id in PIANO_IDS},
    0x04: 600.0,   # hand drum
    0x05: 2_500.0, # cymbals
    0x0D: 600.0,   # drum set
    0x13: 1_200.0, # handpan
}

BOUNDARY_FADE_MS = 12.0
INSTANCE_LIMIT_RELEASE_MS = 4.0
MAX_RELEASE_MS = 60_000.0
ACTIVE_SIGNAL_RELATIVE_FLOOR = 10.0 ** (-60.0 / 20.0)
ACTIVE_SIGNAL_ABSOLUTE_FLOOR = 1.0e-5
ACTIVE_SIGNAL_QUIET_HOLD_MS = 20.0


@dataclass(frozen=True)
class VoiceLifecycle:
    """Formal and audible timing for one already pitch-shifted voice."""

    note_frames: int
    audible_frames: int
    fade_out_frames: int

    @property
    def tail_frames(self) -> int:
        return max(0, self.audible_frames - self.note_frames)


@dataclass(frozen=True)
class InstanceLimitDecision:
    """Pure Wwise same-priority instance-limit result.

    Victim indices address the caller-provided active-instance sequence.  That
    sequence is insertion ordered, so equal start frames deterministically
    discard the instance that was started first.
    """

    accept_new: bool
    victim_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class InstanceTimelineItem:
    """One predecoded event presented to the shared instance-limit planner."""

    start_frame: int
    audible_frames: int
    group_id: int = -1
    scope_id: int = -1
    max_instances: int = 0
    kill_newest: bool = False


@dataclass(frozen=True)
class InstanceTimelinePlan:
    accepted: tuple[bool, ...]
    audible_frames: tuple[int, ...]
    forced_release: tuple[bool, ...]


def decide_instance_limit(
    active_start_frames: tuple[int, ...] | list[int],
    max_instances: int,
    kill_newest: bool,
) -> InstanceLimitDecision:
    """Resolve Wwise ``Discard oldest/newest`` without playback dependencies."""

    limit = max(0, int(max_instances))
    if limit <= 0 or len(active_start_frames) < limit:
        return InstanceLimitDecision(True)
    if bool(kill_newest):
        return InstanceLimitDecision(False)
    victims_needed = len(active_start_frames) - limit + 1
    ordered = sorted(
        range(len(active_start_frames)),
        key=lambda index: (int(active_start_frames[index]), index),
    )
    return InstanceLimitDecision(
        True,
        tuple(ordered[:victims_needed]),
    )


def plan_instance_timeline(
    items: tuple[InstanceTimelineItem, ...] | list[InstanceTimelineItem],
    release_frames: int,
) -> InstanceTimelinePlan:
    """Plan per-object Wwise limits for a chronologically ordered event list.

    A discarded-oldest instance leaves capacity immediately while its PCM gets
    a bounded release.  This distinction prevents dense simultaneous hits from
    exceeding the recovered limit merely because an older voice is still in
    its click-suppression fade.
    """

    count = len(items)
    accepted = [True] * count
    starts = [int(item.start_frame) for item in items]
    natural_ends = [
        starts[index] + max(0, int(item.audible_frames))
        for index, item in enumerate(items)
    ]
    effective_ends = list(natural_ends)
    forced = [False] * count
    active_by_scope: dict[tuple[int, int], list[int]] = {}
    release = max(1, int(release_frames))

    for index, item in enumerate(items):
        group_id = int(item.group_id)
        limit = max(0, int(item.max_instances))
        if group_id < 0 or limit <= 0:
            continue
        key = (group_id, int(item.scope_id))
        start = starts[index]
        active = [
            active_index
            for active_index in active_by_scope.get(key, ())
            if effective_ends[active_index] > start
        ]
        decision = decide_instance_limit(
            [starts[active_index] for active_index in active],
            limit,
            bool(item.kill_newest),
        )
        if not decision.accept_new:
            accepted[index] = False
            effective_ends[index] = start
            active_by_scope[key] = active
            continue
        victim_set = {
            active[victim_index]
            for victim_index in decision.victim_indices
        }
        for victim in victim_set:
            shortened_end = min(effective_ends[victim], start + release)
            if shortened_end < effective_ends[victim]:
                effective_ends[victim] = shortened_end
                forced[victim] = True
        active_by_scope[key] = [
            active_index
            for active_index in active
            if active_index not in victim_set
        ] + [index]

    audible = tuple(
        max(0, effective_ends[index] - starts[index])
        if accepted[index]
        else 0
        for index in range(count)
    )
    return InstanceTimelinePlan(
        tuple(accepted),
        audible,
        tuple(forced),
    )


def milliseconds_to_frames(milliseconds: float, sample_rate: int) -> int:
    return max(0, round(float(milliseconds) * max(1, int(sample_rate)) / 1000.0))


def detect_active_signal_frames(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    quiet_hold_ms: float = ACTIVE_SIGNAL_QUIET_HOLD_MS,
) -> int:
    """Return the decoded-frame endpoint of meaningful sample signal.

    This is intentionally a preload/offline operation.  The threshold is
    relative to each sample's own peak, with a small absolute noise floor.
    A bounded quiet hold avoids cutting immediately after the final crossing.
    """

    source = np.asarray(pcm)
    if source.size == 0 or source.ndim == 0:
        return 0
    if source.ndim == 1:
        frame_level = np.abs(source)
    else:
        frame_level = np.max(np.abs(source), axis=1)
    if frame_level.size == 0:
        return 0
    finite_level = np.where(np.isfinite(frame_level), frame_level, 0.0)
    peak = float(np.max(finite_level, initial=0.0))
    if peak <= ACTIVE_SIGNAL_ABSOLUTE_FLOOR:
        return min(1, len(finite_level))
    threshold = max(
        ACTIVE_SIGNAL_ABSOLUTE_FLOOR,
        peak * ACTIVE_SIGNAL_RELATIVE_FLOOR,
    )
    active_indices = np.flatnonzero(finite_level >= threshold)
    if active_indices.size == 0:
        return min(1, len(finite_level))
    hold_frames = milliseconds_to_frames(quiet_hold_ms, sample_rate)
    return min(len(finite_level), int(active_indices[-1]) + 1 + hold_frames)


def sample_output_frames(sample_frames: int, playback_ratio: float) -> int:
    """Convert decoded source frames to output-timeline frames."""

    ratio = float(playback_ratio)
    if sample_frames <= 0 or not math.isfinite(ratio) or ratio <= 0.0:
        return 0
    return max(1, math.ceil(int(sample_frames) / ratio))


def _short_articulation_frames(
    ntype: int,
    note_frames: int,
    sample_rate: int,
) -> int | None:
    if ntype == 2:
        desired = max(
            milliseconds_to_frames(40.0, sample_rate),
            min(
                round(note_frames * 0.35),
                milliseconds_to_frames(180.0, sample_rate),
            ),
        )
    elif ntype == 13:
        desired = max(
            milliseconds_to_frames(60.0, sample_rate),
            min(
                round(note_frames * 0.55),
                milliseconds_to_frames(260.0, sample_rate),
            ),
        )
    elif ntype == 22:
        desired = milliseconds_to_frames(220.0, sample_rate)
    elif ntype == 24:
        desired = milliseconds_to_frames(100.0, sample_rate)
    else:
        return None
    return max(1, min(note_frames, desired))


def voice_lifecycle(
    instrument_id: int,
    ntype: int,
    note_frames: int,
    sample_signal_output_frames: int,
    sample_rate: int,
    *,
    native_articulation: bool = False,
    sample_loops: bool = False,
    release_ms: float | None = None,
) -> VoiceLifecycle:
    """Resolve one deterministic audible boundary.

    Gated families stop at the formal note block.  Piano, plucked strings, and
    percussion receive bounded natural tails.  Short articulations override
    family tails, and every legacy result is capped by the decoded sample's
    meaningful signal endpoint.

    Recovered native Wwise routes are authoritative: their note-off release
    replaces legacy articulation/family guesses.  One-shot sources are capped
    by their meaningful endpoint; looping sources repeat the decoded region,
    so the file length does not cap that timeline.
    """

    rate = max(1, int(sample_rate))
    note_length = max(1, int(note_frames))
    signal_length = max(0, int(sample_signal_output_frames))
    if sample_loops:
        try:
            source_release_ms = float(
                BOUNDARY_FADE_MS if release_ms is None else release_ms
            )
        except (TypeError, ValueError, OverflowError):
            source_release_ms = BOUNDARY_FADE_MS
        if not math.isfinite(source_release_ms):
            source_release_ms = BOUNDARY_FADE_MS
        source_release_ms = max(
            0.0,
            min(MAX_RELEASE_MS, source_release_ms),
        )
        release_frames = milliseconds_to_frames(source_release_ms, rate)
        audible = note_length + release_frames if signal_length > 0 else 0
        if audible <= 0:
            return VoiceLifecycle(note_length, 0, 0)
        fade = (
            min(audible, release_frames)
            if release_frames > 0
            else min(
                audible,
                milliseconds_to_frames(BOUNDARY_FADE_MS, rate),
            )
        )
        return VoiceLifecycle(note_length, audible, fade)

    if native_articulation:
        try:
            source_release_ms = float(
                BOUNDARY_FADE_MS if release_ms is None else release_ms
            )
        except (TypeError, ValueError, OverflowError):
            source_release_ms = BOUNDARY_FADE_MS
        if not math.isfinite(source_release_ms):
            source_release_ms = BOUNDARY_FADE_MS
        source_release_ms = max(
            0.0,
            min(MAX_RELEASE_MS, source_release_ms),
        )
        release_frames = milliseconds_to_frames(source_release_ms, rate)
        desired = note_length + release_frames
        audible = min(desired, signal_length) if signal_length > 0 else 0
        if audible <= 0:
            return VoiceLifecycle(note_length, 0, 0)
        fade = (
            min(audible, release_frames)
            if release_frames > 0
            else min(
                audible,
                milliseconds_to_frames(BOUNDARY_FADE_MS, rate),
            )
        )
        return VoiceLifecycle(note_length, audible, fade)

    short_length = _short_articulation_frames(int(ntype), note_length, rate)
    if short_length is not None:
        desired = short_length
    else:
        tail_ms = _TAIL_MS_BY_INSTRUMENT.get(int(instrument_id), 0.0)
        if int(instrument_id) in PIANO_IDS and int(ntype) == 11:
            tail_ms = 2_500.0
        desired = note_length + milliseconds_to_frames(tail_ms, rate)

    audible = min(desired, signal_length) if signal_length > 0 else 0
    if audible <= 0:
        return VoiceLifecycle(note_length, 0, 0)
    fade = min(
        audible,
        milliseconds_to_frames(BOUNDARY_FADE_MS, rate),
    )
    return VoiceLifecycle(note_length, audible, fade)


__all__ = [
    "BOUNDARY_FADE_MS",
    "GUITAR_IDS",
    "HARP_IDS",
    "INSTANCE_LIMIT_RELEASE_MS",
    "InstanceLimitDecision",
    "InstanceTimelineItem",
    "InstanceTimelinePlan",
    "MAX_RELEASE_MS",
    "PIANO_IDS",
    "SHORT_ARTICULATION_TYPES",
    "VoiceLifecycle",
    "detect_active_signal_frames",
    "decide_instance_limit",
    "milliseconds_to_frames",
    "plan_instance_timeline",
    "sample_output_frames",
    "voice_lifecycle",
]
