"""Qt-free PCM preparation shared by real-time and offline preview."""

from __future__ import annotations

import math

import numpy as np


SAMPLE_PEAK_CEILING = 0.999


def _fill_progress(
    work: np.ndarray,
    age: np.ndarray,
    duration: int,
) -> None:
    np.divide(age, float(duration), out=work)
    np.clip(work, 0.0, 1.0, out=work)


def _fill_sine_phase(
    work: np.ndarray,
    age: np.ndarray,
    frequency: float,
    sample_rate: int,
) -> None:
    np.multiply(
        age,
        2.0 * np.pi * frequency / max(1.0, float(sample_rate)),
        out=work,
    )
    np.sin(work, out=work)


def articulation_preview_envelope(
    instrument_id: int,
    ntype: int,
    age_frames: np.ndarray,
    duration_frames: int,
    sample_rate: int,
    *,
    out: np.ndarray | None = None,
    scratch: np.ndarray | None = None,
) -> np.ndarray:
    """Build the shared approximate envelope for one BDO note type.

    Extracted maps identify native Event sample routes, but do not yet recover
    every parent Wwise modulator/filter.  This Qt-free approximation is used by
    both live playback and offline preview so the two paths cannot give the same
    score different articulation timing or colour.
    """

    age = np.asarray(age_frames, dtype=np.float32)
    duration = max(1, int(duration_frames) or int(sample_rate))
    if out is None or out.shape != age.shape or out.dtype != np.float32:
        envelope = np.empty_like(age, dtype=np.float32)
    else:
        envelope = out
    if (
        scratch is None
        or scratch.shape != age.shape
        or scratch.dtype != np.float32
        or np.shares_memory(scratch, age)
        or np.shares_memory(scratch, envelope)
    ):
        work = np.empty_like(age, dtype=np.float32)
    else:
        work = scratch
    envelope.fill(1.0)

    # Type 1 is a tag/basic colour, never a timing instruction. Keep a small
    # accent without truncating the formal note block.
    if ntype == 1 and instrument_id not in {0x1C, 0x20}:
        _fill_progress(work, age, duration)
        np.multiply(work, -0.06, out=envelope)
        envelope += 1.06
    elif ntype == 2:
        _fill_progress(work, age, duration)
        np.multiply(work, -0.18, out=envelope)
        envelope += 1.08
    elif ntype in {3, 23}:
        _fill_progress(work, age, duration)
        work *= 3.0
        np.minimum(work, 1.0, out=work)
        np.multiply(work, 0.52, out=envelope)
        envelope += 0.48
    elif ntype == 12:
        _fill_progress(work, age, duration)
        np.multiply(work, -0.42, out=envelope)
        envelope += 1.0
    elif ntype in {4, 5, 6, 7, 8, 17, 18, 19}:
        settings = {
            4: (5.0, 0.22),
            5: (6.0, 0.24),
            6: (5.5, 0.14),
            7: (7.0, 0.18),
            8: (8.0, 0.22),
            17: (9.0, 0.16),
            18: (6.5, 0.28),
            19: (11.0, 0.14),
        }
        frequency, depth = settings[ntype]
        _fill_sine_phase(work, age, frequency, sample_rate)
        np.multiply(work, depth * 0.5, out=envelope)
        envelope += 1.0 - depth * 0.5
    elif ntype == 13:
        _fill_progress(work, age, duration)
        work *= -3.0
        np.exp(work, out=envelope)
        envelope *= 0.58
    elif ntype == 14:
        envelope.fill(0.70)
    elif ntype == 15:
        _fill_progress(work, age, duration)
        work *= 3.0
        np.remainder(work, 1.0, out=work)
        np.subtract(0.84, work, out=envelope)
        envelope /= 0.12
        np.clip(envelope, 0.0, 1.0, out=envelope)
    elif ntype == 16:
        _fill_progress(work, age, duration)
        work *= np.pi
        np.sin(work, out=work)
        np.multiply(work, 0.45, out=envelope)
        envelope += 0.55
    elif ntype == 11:
        _fill_progress(work, age, duration)
        work *= 1.5
        np.minimum(work, 1.0, out=work)
        np.multiply(work, 0.10, out=envelope)
        envelope += 0.90
    elif ntype == 20:
        _fill_sine_phase(work, age, 1.3, sample_rate)
        np.multiply(work, 0.22, out=envelope)
        envelope += 0.68
    elif ntype == 21:
        _fill_sine_phase(work, age, 2.1, sample_rate)
        np.multiply(work, 0.18, out=envelope)
        envelope += 0.78
    elif ntype == 22:
        _fill_progress(work, age, duration)
        work *= -5.5
        np.exp(work, out=envelope)
        envelope *= 1.22
    elif ntype == 24:
        _fill_sine_phase(work, age, 38.0, sample_rate)
        np.sign(work, out=work)
        np.multiply(work, 0.45, out=envelope)
        envelope += 0.55
    elif ntype == 25:
        _fill_sine_phase(work, age, 13.0, sample_rate)
        np.multiply(work, 0.28, out=envelope)
        envelope += 0.72
    elif ntype == 26:
        envelope.fill(0.62)
    elif ntype == 27:
        envelope.fill(0.82)
    elif ntype == 28:
        envelope.fill(1.08)
    return envelope


def apply_articulation_preview_in_place(
    pcm: np.ndarray,
    instrument_id: int,
    ntype: int,
    age_frames: np.ndarray,
    duration_frames: int,
    sample_rate: int,
    *,
    native_articulation: bool = False,
    envelope_out: np.ndarray | None = None,
    scratch: np.ndarray | None = None,
) -> np.ndarray:
    """Apply shared fallback articulation DSP without allocating output PCM."""

    value = int(ntype)
    if native_articulation or value in {0, 9, 10, 99} or pcm.size == 0:
        return pcm
    envelope = articulation_preview_envelope(
        int(instrument_id),
        value,
        age_frames,
        int(duration_frames),
        int(sample_rate),
        out=envelope_out,
        scratch=scratch,
    )
    pcm *= envelope[:, None]
    # A gentle nonlinear colour distinguishes the brass/filter and slap
    # families without pretending to reproduce an unknown Wwise plug-in.
    if value in {21, 22}:
        pcm *= 1.35
        np.tanh(pcm, out=pcm)
    return pcm


def preview_chord_intervals(
    ntype: int,
    *,
    native_articulation: bool = False,
) -> tuple[int, ...]:
    """Return fallback chord layers not already present in a native Event."""

    if native_articulation:
        return ()
    if int(ntype) == 9:
        return (4, 7)
    if int(ntype) == 10:
        return (3, 7)
    return ()


def prepare_sample_pcm(pcm: np.ndarray) -> tuple[np.ndarray, float]:
    """Return finite contiguous PCM without erasing authored level ratios.

    Extracted Wwise media already carries part of the game's relative loudness;
    static HIRC Volume is applied later per event.  Per-file RMS matching would
    destroy both relationships, so preparation only attenuates malformed
    over-range PCM and never boosts a quiet source.
    """

    source = np.ascontiguousarray(pcm, dtype=np.float32)
    if source.size == 0:
        return source, 1.0
    if not np.isfinite(source).all():
        np.nan_to_num(
            source,
            copy=False,
            nan=0.0,
            posinf=SAMPLE_PEAK_CEILING,
            neginf=-SAMPLE_PEAK_CEILING,
        )
    peak = max(
        float(source.max(initial=0.0)),
        -float(source.min(initial=0.0)),
    )
    if not math.isfinite(peak) or peak <= SAMPLE_PEAK_CEILING:
        return source, 1.0
    gain = SAMPLE_PEAK_CEILING / peak
    source *= gain
    return source, gain


# Compatibility import retained for callers of the former real-time helper.
normalise_sample_loudness = prepare_sample_pcm


__all__ = [
    "SAMPLE_PEAK_CEILING",
    "apply_articulation_preview_in_place",
    "articulation_preview_envelope",
    "normalise_sample_loudness",
    "prepare_sample_pcm",
    "preview_chord_intervals",
]
