"""Bounded, Qt-free spectral transforms for the transcription piano roll.

The UI renders five-second image tiles, but the transform itself deliberately
has no file or Qt dependencies.  Callers provide only the small PCM slice for
one tile.  This keeps FFT work outside paint/audio callbacks and makes the
time/pitch projection straightforward to test.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np


DEFAULT_FLOOR_DB = -72.0
DEFAULT_FRAME_PERIOD_MS = 20.0
MIN_FFT_SIZE = 512
MAX_FFT_SIZE = 4_096
FFT_BLOCK_COLUMNS = 32


class SpectrogramCancelled(RuntimeError):
    """Raised when a tile transform is no longer part of the viewport."""


def choose_fft_size(sample_rate: float) -> int:
    """Choose a bounded window of roughly 46 ms for musical pitch display."""

    rate = max(1.0, float(sample_rate))
    target = max(MIN_FFT_SIZE, min(MAX_FFT_SIZE, rate * 0.046))
    exponent = round(math.log2(target))
    return max(MIN_FFT_SIZE, min(MAX_FFT_SIZE, 1 << exponent))


def spectrogram_column_count(
    duration_ms: float,
    pixels_per_ms: float,
    *,
    frame_period_ms: float = DEFAULT_FRAME_PERIOD_MS,
    maximum_columns: int = 4_096,
) -> int:
    """Return enough columns for the source and viewport, never more.

    A zoomed-out view should not calculate hundreds of FFTs only to collapse
    them into a handful of pixels.  Conversely, zooming in does not invent
    spectral resolution beyond the fixed analysis period.
    """

    duration = max(0.0, float(duration_ms))
    source_columns = max(
        1,
        math.ceil(duration / max(1e-6, float(frame_period_ms))),
    )
    pixel_columns = max(1, math.ceil(duration * max(1e-7, float(pixels_per_ms))))
    return min(max(1, int(maximum_columns)), source_columns, pixel_columns)


def _mono_float32(samples: np.ndarray) -> np.ndarray:
    values = np.asarray(samples)
    if values.ndim == 2:
        values = np.mean(values, axis=1, dtype=np.float32)
    elif values.ndim != 1:
        raise ValueError("spectrogram PCM must be mono or frames x channels")
    return np.nan_to_num(
        np.asarray(values, dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
        copy=True,
    )


def midi_spectrogram(
    samples: np.ndarray,
    sample_rate: float,
    *,
    pitch_min: int,
    pitch_max: int,
    output_columns: int,
    floor_db: float = DEFAULT_FLOOR_DB,
    tile_frame_count: int | None = None,
    leading_padding_frames: int = 0,
    cancel_requested: Callable[[], bool] | None = None,
) -> np.ndarray:
    """Create a ``time x MIDI-semitone`` intensity matrix for one tile.

    ``tile_frame_count`` and ``leading_padding_frames`` let a decoder provide
    real audio around tile boundaries.  With their defaults, this function
    pads an exact tile with silence and is convenient for tests and non-stream
    callers.  Returned values are absolute full-scale dB intensities in
    ``[0, 1]``; there is no per-tile normalization, so adjacent tiles do not
    pulse merely because their local peak levels differ.
    """

    rate = float(sample_rate)
    if not math.isfinite(rate) or rate <= 0.0:
        raise ValueError("sample_rate must be positive")
    low_pitch = max(0, min(127, int(pitch_min)))
    high_pitch = max(low_pitch, min(127, int(pitch_max)))
    columns = max(1, int(output_columns))
    values = _mono_float32(samples)
    fft_size = choose_fft_size(rate)
    half_window = fft_size // 2

    if tile_frame_count is None:
        tile_frames = int(values.size)
        values = np.pad(values, (half_window, half_window))
        leading = half_window
    else:
        tile_frames = max(0, int(tile_frame_count))
        leading = max(0, int(leading_padding_frames))
    if tile_frames <= 0:
        return np.zeros((columns, high_pitch - low_pitch + 1), dtype=np.float32)
    required = leading + tile_frames + half_window
    if values.size < required:
        values = np.pad(values, (0, required - int(values.size)))

    if cancel_requested is not None and cancel_requested():
        raise SpectrogramCancelled()

    centers = (
        leading
        + (np.arange(columns, dtype=np.float64) + 0.5)
        * tile_frames
        / columns
    )
    starts = np.rint(centers - half_window).astype(np.int64)
    starts = np.clip(starts, 0, max(0, values.size - fft_size))
    window = np.hanning(fft_size).astype(np.float32)
    coherent_gain = max(1e-12, float(np.sum(window)) / 2.0)
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / rate)

    band_bounds: list[tuple[int, int]] = []
    for pitch in range(low_pitch, high_pitch + 1):
        low_hz = 440.0 * (2.0 ** ((pitch - 69.5) / 12.0))
        high_hz = 440.0 * (2.0 ** ((pitch - 68.5) / 12.0))
        first = int(np.searchsorted(frequencies, low_hz, side="left"))
        last = int(np.searchsorted(frequencies, high_hz, side="left"))
        first = max(1, min(frequencies.size - 1, first))
        last = max(first + 1, min(frequencies.size, last))
        band_bounds.append((first, last))

    floor = float(floor_db)
    if not math.isfinite(floor) or floor >= -1e-6:
        raise ValueError("floor_db must be negative")
    output = np.zeros((columns, len(band_bounds)), dtype=np.float32)
    offsets = np.arange(fft_size, dtype=np.int64)
    for block_start in range(0, columns, FFT_BLOCK_COLUMNS):
        if cancel_requested is not None and cancel_requested():
            raise SpectrogramCancelled()
        block_end = min(columns, block_start + FFT_BLOCK_COLUMNS)
        indices = starts[block_start:block_end, None] + offsets[None, :]
        frames = values[indices] * window[None, :]
        magnitude = np.abs(np.fft.rfft(frames, axis=1)) / coherent_gain
        for band_index, (first, last) in enumerate(band_bounds):
            output[block_start:block_end, band_index] = np.max(
                magnitude[:, first:last],
                axis=1,
            )

    db = 20.0 * np.log10(np.maximum(output, np.float32(1e-8)))
    np.subtract(db, floor, out=db)
    np.divide(db, -floor, out=db)
    return np.clip(db, 0.0, 1.0).astype(np.float32, copy=False)


__all__ = [
    "DEFAULT_FLOOR_DB",
    "DEFAULT_FRAME_PERIOD_MS",
    "FFT_BLOCK_COLUMNS",
    "MAX_FFT_SIZE",
    "MIN_FFT_SIZE",
    "SpectrogramCancelled",
    "choose_fft_size",
    "midi_spectrogram",
    "spectrogram_column_count",
]
