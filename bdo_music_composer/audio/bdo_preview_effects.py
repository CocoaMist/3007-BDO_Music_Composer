"""Bounded local preview for the BDO composer effect topology.

The game resources verify three per-track Aux sends and five shared authoring
controls, but they do not expose the Wwise plug-in chain or the 0..100 to native
DSP conversion.  This module therefore implements a deliberately conservative
preview, not a game-accurate emulator.  It performs no I/O and allocates only
while configured, before playback enters the audio callback.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


PREVIEW_DELAY_SECONDS = 0.25
PREVIEW_DELAY_MIN_REPEATS = 2
PREVIEW_DELAY_MAX_REPEATS = 20
PREVIEW_DELAY_WET_GAIN = 0.42
PREVIEW_DELAY_AUDIBLE_GAIN = 0.01
PREVIEW_REVERB_MIN_SECONDS = 0.2
PREVIEW_REVERB_MAX_SECONDS = 8.0
PREVIEW_CHORUS_MIN_FREQUENCY_HZ = 0.03
PREVIEW_CHORUS_MAX_FREQUENCY_HZ = 0.30
MAX_EFFECT_TAIL_SECONDS = 8.0
PREVIEW_EFFECT_VECTOR_FRAMES = 4_096


def _authoring_fraction(value: int | float) -> float:
    """Map an imported byte to the documented authoring range for preview."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return max(0.0, min(100.0, numeric)) / 100.0


@dataclass(frozen=True, slots=True)
class PreviewEffectSettings:
    """Shared composer controls retained as authoring values."""

    reverb_time: int = 0
    delay_feedback: int = 0
    chorus_feedback: int = 0
    chorus_lfo_depth: int = 0
    chorus_lfo_frequency: int = 0

    @classmethod
    def from_legacy(
        cls,
        reverb: int,
        delay: int,
        chorus: tuple[int, int, int] | None,
    ) -> "PreviewEffectSettings":
        feedback, depth, frequency = chorus or (0, 0, 0)
        return cls(
            int(reverb),
            int(delay),
            int(feedback),
            int(depth),
            int(frequency),
        )


def preview_send_gain(value: int | float) -> float:
    """Return the local linear Aux-send approximation for one authoring value."""

    return _authoring_fraction(value)


def preview_delay_repeat_count(value: int | float) -> int:
    """Map Delay Feedback to the game's documented approximate echo count."""

    fraction = _authoring_fraction(value)
    return round(
        PREVIEW_DELAY_MIN_REPEATS
        + (PREVIEW_DELAY_MAX_REPEATS - PREVIEW_DELAY_MIN_REPEATS) * fraction
    )


def preview_delay_feedback_gain(value: int | float) -> float:
    """Return a stable feedback gain whose audible tail matches the guide.

    The official authoring guide documents about two delayed sounds at 0 and
    about twenty at 100, but does not publish the native Wwise taper.  Anchor
    the local approximation to those endpoints using a conservative -40 dB
    audibility boundary instead of the previous arbitrary linear coefficient.
    """

    repeats = preview_delay_repeat_count(value)
    return (
        PREVIEW_DELAY_AUDIBLE_GAIN / PREVIEW_DELAY_WET_GAIN
    ) ** (1.0 / max(1, repeats - 1))


def preview_chorus_frequency_hz(value: int | float) -> float:
    """Map authoring frequency to a slow-but-moving 0 and bank-bounded 100."""

    fraction = _authoring_fraction(value)
    return PREVIEW_CHORUS_MIN_FREQUENCY_HZ + (
        PREVIEW_CHORUS_MAX_FREQUENCY_HZ
        - PREVIEW_CHORUS_MIN_FREQUENCY_HZ
    ) * fraction


class PreviewEffectProcessor:
    """Allocation-free streaming reverb, delay and chorus approximation."""

    def __init__(self, sample_rate: int = 48_000) -> None:
        self.sample_rate = max(8_000, int(sample_rate))
        self.settings = PreviewEffectSettings()
        self.reverb_enabled = False
        self.delay_enabled = False
        self.chorus_enabled = False
        # Reverb is a four-line scalar recurrence. NumPy scalar indexing inside
        # its per-frame loop costs substantially more than the arithmetic, so
        # keep these small, bounded rings as preallocated native-float lists.
        # Delay/chorus remain arrays because their access pattern is different.
        self._reverb_buffer_left: list[list[float]] = []
        self._reverb_buffer_right: list[list[float]] = []
        self._reverb_lengths: tuple[int, ...] = ()
        self._reverb_positions: list[int] = []
        self._reverb_damping_left: list[float] = []
        self._reverb_damping_right: list[float] = []
        self._reverb_feedback: tuple[float, ...] = ()
        self._delay_buffer = np.empty((0, 2), dtype=np.float32)
        self._delay_scratch = np.empty((0, 2), dtype=np.float32)
        self._delay_position = 0
        self._delay_feedback = 0.0
        self._chorus_buffer = np.empty((0, 2), dtype=np.float32)
        self._chorus_position = 0
        self._chorus_phase = 0.0
        self._chorus_phase_step = 0.0
        self._chorus_frame_cursor = 0
        self._chorus_base_frames = 0.0
        self._chorus_depth_frames = 0.0
        self._chorus_feedback = 0.0
        self._chorus_offsets = np.empty(0, dtype=np.float64)
        self._chorus_phase_values = np.empty(0, dtype=np.float64)
        self._chorus_read_left = np.empty(0, dtype=np.float64)
        self._chorus_read_right = np.empty(0, dtype=np.float64)
        self._chorus_indices_left = np.empty(0, dtype=np.intp)
        self._chorus_indices_right = np.empty(0, dtype=np.intp)
        self._chorus_next_left = np.empty(0, dtype=np.intp)
        self._chorus_next_right = np.empty(0, dtype=np.intp)
        self._chorus_fractions = np.empty((0, 2), dtype=np.float32)
        self._chorus_a = np.empty((0, 2), dtype=np.float32)
        self._chorus_b = np.empty((0, 2), dtype=np.float32)
        self._chorus_wet = np.empty((0, 2), dtype=np.float32)

    @property
    def active(self) -> bool:
        return self.reverb_enabled or self.delay_enabled or self.chorus_enabled

    def configure(
        self,
        settings: PreviewEffectSettings,
        *,
        reverb_send: bool,
        delay_send: bool,
        chorus_send: bool,
    ) -> None:
        """Prepare fixed state before playback; no callback calls this method."""

        self.settings = settings
        self.reverb_enabled = bool(reverb_send)
        self.delay_enabled = bool(delay_send)
        self.chorus_enabled = bool(chorus_send)

        reverb_fraction = _authoring_fraction(settings.reverb_time)
        # A zero authoring value is treated as the smallest useful preset when
        # a track explicitly sends to the bus.  The exact game curve is not
        # present in the inspected resources.
        # The shared v145 init bank contains RoomVerb curves spanning 0.2 to
        # 8/10 seconds. It does not prove the composer binding; use the lower
        # bounded span only as the shape of this explicitly approximate curve.
        decay_seconds = PREVIEW_REVERB_MIN_SECONDS + (
            PREVIEW_REVERB_MAX_SECONDS - PREVIEW_REVERB_MIN_SECONDS
        ) * reverb_fraction * reverb_fraction
        base_lengths = (0.0297, 0.0331, 0.0371, 0.0411)
        lengths = tuple(
            max(2, round(self.sample_rate * value))
            for value in base_lengths
        )
        if self.reverb_enabled:
            self._reverb_lengths = lengths
            self._reverb_positions = [0] * len(lengths)
            self._reverb_buffer_left = [[0.0] * length for length in lengths]
            self._reverb_buffer_right = [[0.0] * length for length in lengths]
            self._reverb_damping_left = [0.0] * len(lengths)
            self._reverb_damping_right = [0.0] * len(lengths)
            self._reverb_feedback = tuple(
                10.0
                ** (-3.0 * (float(length) / self.sample_rate) / decay_seconds)
                for length in lengths
            )
        else:
            self._reverb_lengths = ()
            self._reverb_positions = []
            self._reverb_buffer_left = []
            self._reverb_buffer_right = []
            self._reverb_damping_left = []
            self._reverb_damping_right = []
            self._reverb_feedback = ()

        if self.delay_enabled:
            delay_frames = max(2, round(self.sample_rate * PREVIEW_DELAY_SECONDS))
            self._delay_buffer = np.zeros((delay_frames, 2), dtype=np.float32)
            self._delay_scratch = np.empty(
                (PREVIEW_EFFECT_VECTOR_FRAMES, 2),
                dtype=np.float32,
            )
            self._delay_feedback = preview_delay_feedback_gain(
                settings.delay_feedback
            )
        else:
            self._delay_buffer = np.empty((0, 2), dtype=np.float32)
            self._delay_scratch = np.empty((0, 2), dtype=np.float32)
            self._delay_feedback = 0.0
        self._delay_position = 0

        if self.chorus_enabled:
            max_delay_frames = max(4, round(self.sample_rate * 0.026))
            self._chorus_buffer = np.zeros(
                (max_delay_frames + 2, 2),
                dtype=np.float32,
            )
            self._chorus_offsets = np.arange(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.float64,
            )
            self._chorus_phase_values = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.float64,
            )
            self._chorus_read_left = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.float64,
            )
            self._chorus_read_right = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.float64,
            )
            self._chorus_indices_left = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.intp,
            )
            self._chorus_indices_right = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.intp,
            )
            self._chorus_next_left = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.intp,
            )
            self._chorus_next_right = np.empty(
                PREVIEW_EFFECT_VECTOR_FRAMES,
                dtype=np.intp,
            )
            self._chorus_fractions = np.empty(
                (PREVIEW_EFFECT_VECTOR_FRAMES, 2),
                dtype=np.float32,
            )
            self._chorus_a = np.empty(
                (PREVIEW_EFFECT_VECTOR_FRAMES, 2),
                dtype=np.float32,
            )
            self._chorus_b = np.empty(
                (PREVIEW_EFFECT_VECTOR_FRAMES, 2),
                dtype=np.float32,
            )
            self._chorus_wet = np.empty(
                (PREVIEW_EFFECT_VECTOR_FRAMES, 2),
                dtype=np.float32,
            )
            depth = _authoring_fraction(settings.chorus_lfo_depth)
            self._chorus_base_frames = self.sample_rate * 0.010
            # All 40 instrument banks point at the same init-bank Flanger
            # AuxBus: its RTPCs expose 30..100% depth, 0..0.3 Hz frequency and
            # -1..+1 feedback.  Clamp feedback slightly inside unity because
            # this lightweight delay does not reproduce Wwise's safeguards.
            self._chorus_depth_frames = (
                self._chorus_base_frames * (0.30 + 0.70 * depth)
            )
            # The official game guide describes value 0 as slow movement, not
            # a stopped oscillator.  Keep a conservative non-zero floor while
            # retaining the inspected bank's 0.3 Hz upper bound.
            frequency_hz = preview_chorus_frequency_hz(
                settings.chorus_lfo_frequency
            )
            self._chorus_phase_step = (
                2.0 * math.pi * frequency_hz / self.sample_rate
            )
            self._chorus_feedback = max(
                -0.85,
                min(
                    0.85,
                    2.0 * _authoring_fraction(settings.chorus_feedback) - 1.0,
                ),
            )
        else:
            self._chorus_buffer = np.empty((0, 2), dtype=np.float32)
            self._chorus_base_frames = 0.0
            self._chorus_depth_frames = 0.0
            self._chorus_phase_step = 0.0
            self._chorus_feedback = 0.0
            self._chorus_offsets = np.empty(0, dtype=np.float64)
            self._chorus_phase_values = np.empty(0, dtype=np.float64)
            self._chorus_read_left = np.empty(0, dtype=np.float64)
            self._chorus_read_right = np.empty(0, dtype=np.float64)
            self._chorus_indices_left = np.empty(0, dtype=np.intp)
            self._chorus_indices_right = np.empty(0, dtype=np.intp)
            self._chorus_next_left = np.empty(0, dtype=np.intp)
            self._chorus_next_right = np.empty(0, dtype=np.intp)
            self._chorus_fractions = np.empty((0, 2), dtype=np.float32)
            self._chorus_a = np.empty((0, 2), dtype=np.float32)
            self._chorus_b = np.empty((0, 2), dtype=np.float32)
            self._chorus_wet = np.empty((0, 2), dtype=np.float32)
        self._chorus_position = 0
        self._chorus_phase = 0.0
        self._chorus_frame_cursor = 0

    def reset(self) -> None:
        """Clear tails after Stop/Seek without reallocating callback state."""

        for line in range(len(self._reverb_lengths)):
            left = self._reverb_buffer_left[line]
            right = self._reverb_buffer_right[line]
            for index in range(len(left)):
                left[index] = 0.0
                right[index] = 0.0
            self._reverb_positions[line] = 0
            self._reverb_damping_left[line] = 0.0
            self._reverb_damping_right[line] = 0.0
        if self._delay_buffer.size:
            self._delay_buffer.fill(0.0)
        if self._chorus_buffer.size:
            self._chorus_buffer.fill(0.0)
        self._delay_position = 0
        self._chorus_position = 0
        self._chorus_phase = 0.0
        self._chorus_frame_cursor = 0

    def tail_frames(self) -> int:
        """Return a bounded transport tail for the configured approximation."""

        tails = [0.0]
        if self.reverb_enabled:
            fraction = _authoring_fraction(self.settings.reverb_time)
            tails.append(
                PREVIEW_REVERB_MIN_SECONDS
                + (PREVIEW_REVERB_MAX_SECONDS - PREVIEW_REVERB_MIN_SECONDS)
                * fraction
                * fraction
            )
        if self.delay_enabled:
            repeats = preview_delay_repeat_count(
                self.settings.delay_feedback
            )
            tails.append(PREVIEW_DELAY_SECONDS * repeats)
        if self.chorus_enabled:
            tails.append(0.25 + 0.75 * abs(self._chorus_feedback))
        seconds = min(MAX_EFFECT_TAIL_SECONDS, max(tails))
        return max(0, round(seconds * self.sample_rate))

    def process(
        self,
        output: np.ndarray,
        reverb_input: np.ndarray,
        delay_input: np.ndarray,
        chorus_input: np.ndarray,
        frames: int,
    ) -> None:
        """Add wet buses to ``output`` in place without temporary arrays."""

        count = min(
            max(0, int(frames)),
            len(output),
            len(reverb_input),
            len(delay_input),
            len(chorus_input),
        )
        if count <= 0:
            return
        if self.reverb_enabled:
            self._process_reverb(output, reverb_input, count)
        if self.delay_enabled:
            self._process_delay(output, delay_input, count)
        if self.chorus_enabled:
            self._process_chorus(output, chorus_input, count)

    def _process_reverb(
        self,
        output: np.ndarray,
        source: np.ndarray,
        frames: int,
    ) -> None:
        line_count = len(self._reverb_lengths)
        positions = self._reverb_positions
        lengths = self._reverb_lengths
        buffers_left = self._reverb_buffer_left
        buffers_right = self._reverb_buffer_right
        damping_left = self._reverb_damping_left
        damping_right = self._reverb_damping_right
        feedback_values = self._reverb_feedback
        for frame in range(frames):
            input_left = float(source[frame, 0])
            input_right = float(source[frame, 1])
            wet_left = 0.0
            wet_right = 0.0
            for line in range(line_count):
                position = positions[line]
                buffer_left = buffers_left[line]
                buffer_right = buffers_right[line]
                delayed_left = buffer_left[position]
                delayed_right = buffer_right[position]
                damped_left = 0.72 * delayed_left + 0.28 * damping_left[line]
                damped_right = 0.72 * delayed_right + 0.28 * damping_right[line]
                damping_left[line] = damped_left
                damping_right[line] = damped_right
                feedback = feedback_values[line]
                buffer_left[position] = (
                    input_left * 0.28 + damped_left * feedback
                )
                buffer_right[position] = (
                    input_right * 0.28 + damped_right * feedback
                )
                wet_left += delayed_left
                wet_right += delayed_right
                position += 1
                if position >= lengths[line]:
                    position = 0
                positions[line] = position
            output[frame, 0] += wet_left * 0.10
            output[frame, 1] += wet_right * 0.10

    def _process_delay(
        self,
        output: np.ndarray,
        source: np.ndarray,
        frames: int,
    ) -> None:
        length = len(self._delay_buffer)
        position = self._delay_position
        feedback = self._delay_feedback
        offset = 0
        scratch_capacity = len(self._delay_scratch)
        while offset < frames:
            count = min(
                frames - offset,
                length - position,
                scratch_capacity,
            )
            delayed = self._delay_buffer[position:position + count]
            scratch = self._delay_scratch[:count]
            output_slice = output[offset:offset + count]
            source_slice = source[offset:offset + count]
            np.multiply(delayed, PREVIEW_DELAY_WET_GAIN, out=scratch)
            np.add(output_slice, scratch, out=output_slice)
            np.multiply(delayed, feedback, out=scratch)
            np.add(source_slice, scratch, out=delayed)
            position += count
            if position >= length:
                position = 0
            offset += count
        self._delay_position = position

    def _process_chorus(
        self,
        output: np.ndarray,
        source: np.ndarray,
        frames: int,
    ) -> None:
        length = len(self._chorus_buffer)
        position = self._chorus_position
        cursor = self._chorus_frame_cursor
        offset = 0
        # A vector chunk never exceeds the minimum modulated delay. All reads
        # are therefore captured before this chunk writes its contiguous ring
        # segment, preserving the scalar feedback order across wraparounds.
        safe_chunk = max(1, int(self._chorus_base_frames))
        while offset < frames:
            count = min(
                frames - offset,
                length - position,
                safe_chunk,
                PREVIEW_EFFECT_VECTOR_FRAMES,
            )
            offsets = self._chorus_offsets[:count]
            phase_values = self._chorus_phase_values[:count]
            left_read = self._chorus_read_left[:count]
            right_read = self._chorus_read_right[:count]
            left_indices = self._chorus_indices_left[:count]
            right_indices = self._chorus_indices_right[:count]
            left_next = self._chorus_next_left[:count]
            right_next = self._chorus_next_right[:count]
            fractions = self._chorus_fractions[:count]
            first = self._chorus_a[:count]
            second = self._chorus_b[:count]
            wet = self._chorus_wet[:count]

            np.add(offsets, cursor, out=phase_values)
            np.multiply(
                phase_values,
                self._chorus_phase_step,
                out=phase_values,
            )
            np.remainder(phase_values, 2.0 * math.pi, out=phase_values)

            np.sin(phase_values, out=left_read)
            np.multiply(
                left_read,
                self._chorus_depth_frames * 0.5,
                out=left_read,
            )
            left_read += self._chorus_base_frames + (
                self._chorus_depth_frames * 0.5
            )
            np.subtract(offsets, left_read, out=left_read)
            left_read += position
            np.remainder(left_read, length, out=left_read)

            np.add(phase_values, math.pi, out=right_read)
            np.sin(right_read, out=right_read)
            np.multiply(
                right_read,
                self._chorus_depth_frames * 0.5,
                out=right_read,
            )
            right_read += self._chorus_base_frames + (
                self._chorus_depth_frames * 0.5
            )
            np.subtract(offsets, right_read, out=right_read)
            right_read += position
            np.remainder(right_read, length, out=right_read)

            np.copyto(left_indices, left_read, casting="unsafe")
            np.copyto(right_indices, right_read, casting="unsafe")
            np.add(left_indices, 1, out=left_next)
            np.add(right_indices, 1, out=right_next)
            np.remainder(left_next, length, out=left_next)
            np.remainder(right_next, length, out=right_next)
            np.subtract(left_read, left_indices, out=left_read)
            np.subtract(right_read, right_indices, out=right_read)
            np.copyto(fractions[:, 0], left_read, casting="unsafe")
            np.copyto(fractions[:, 1], right_read, casting="unsafe")

            np.take(
                self._chorus_buffer[:, 0],
                left_indices,
                out=first[:, 0],
            )
            np.take(
                self._chorus_buffer[:, 1],
                right_indices,
                out=first[:, 1],
            )
            np.take(
                self._chorus_buffer[:, 0],
                left_next,
                out=second[:, 0],
            )
            np.take(
                self._chorus_buffer[:, 1],
                right_next,
                out=second[:, 1],
            )
            np.subtract(second, first, out=wet)
            np.multiply(wet, fractions, out=wet)
            np.add(wet, first, out=wet)

            output_slice = output[offset:offset + count]
            buffer_slice = self._chorus_buffer[position:position + count]
            np.multiply(wet, 0.34, out=second)
            np.add(output_slice, second, out=output_slice)
            np.multiply(wet, self._chorus_feedback, out=second)
            np.add(source[offset:offset + count], second, out=buffer_slice)

            position += count
            if position >= length:
                position = 0
            offset += count
            cursor += count
        self._chorus_position = position
        self._chorus_frame_cursor = cursor
        self._chorus_phase = math.fmod(
            cursor * self._chorus_phase_step,
            2.0 * math.pi,
        )


__all__ = [
    "MAX_EFFECT_TAIL_SECONDS",
    "PREVIEW_CHORUS_MAX_FREQUENCY_HZ",
    "PREVIEW_CHORUS_MIN_FREQUENCY_HZ",
    "PREVIEW_DELAY_AUDIBLE_GAIN",
    "PREVIEW_DELAY_MAX_REPEATS",
    "PREVIEW_DELAY_MIN_REPEATS",
    "PREVIEW_DELAY_SECONDS",
    "PREVIEW_DELAY_WET_GAIN",
    "PREVIEW_REVERB_MAX_SECONDS",
    "PREVIEW_REVERB_MIN_SECONDS",
    "PreviewEffectProcessor",
    "PreviewEffectSettings",
    "preview_chorus_frequency_hz",
    "preview_delay_feedback_gain",
    "preview_delay_repeat_count",
    "preview_send_gain",
]
