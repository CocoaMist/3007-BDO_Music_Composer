"""Sample-zone coverage and privacy-safe audio A/B measurements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import wave

import numpy as np

from bdo_realtime_audio import bank_for_instrument
from bdo_sample_renderer import BdoSampleMap, GM_TO_BDO_DRUM


@dataclass(frozen=True, slots=True)
class InstrumentCoverage:
    instrument_id: int
    total_notes: int
    covered_notes: int
    missing_note_indices: tuple[int, ...]
    status: str


@dataclass(frozen=True, slots=True)
class AudioAlignmentReport:
    sample_rate: int
    alignment_frames: int
    onset_delta_frames: int
    loudness_delta_db: float
    spectral_distance_db: float


def sample_coverage_for_tracks(tracks: list[object], map_path: Path) -> tuple[InstrumentCoverage, ...]:
    sample_map = BdoSampleMap(map_path)
    result = []
    for track in tracks:
        missing = []
        instrument_id = int(track.bdo_instrument_id)
        bank = bank_for_instrument(instrument_id, str(getattr(track, "marnian_synth_mode", "basic")))
        for index, note in enumerate(track.notes):
            velocity = max(1, min(127, round(note.vel * float(getattr(track, "volume_scale", 1.0)))))
            pitch = GM_TO_BDO_DRUM.get(int(note.pitch), int(note.pitch)) if instrument_id == 0x0D and int(note.ntype) != 99 else int(note.pitch)
            if sample_map.choose_bank(bank, pitch, velocity) is None:
                missing.append(index)
        total = len(track.notes)
        covered = total - len(missing)
        status = "verified_zone" if total and covered == total else ("partial" if covered else "unmapped")
        result.append(InstrumentCoverage(
            instrument_id, total, covered, tuple(missing), status
        ))
    return tuple(result)


def _read_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"only 16-bit WAV is supported: {path}")
        rate = source.getframerate()
        channels = source.getnchannels()
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, rate


def _resample(signal: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return signal
    positions = np.linspace(0, len(signal) - 1, max(1, round(len(signal) * target_rate / source_rate)))
    return np.interp(positions, np.arange(len(signal)), signal).astype(np.float32)


def _onset(signal: np.ndarray) -> int:
    threshold = max(0.002, float(np.max(np.abs(signal), initial=0.0)) * 0.03)
    hits = np.flatnonzero(np.abs(signal) >= threshold)
    return int(hits[0]) if len(hits) else 0


def _spectral_distance(reference: np.ndarray, candidate: np.ndarray) -> float:
    size = min(len(reference), len(candidate), 16384)
    if size < 128:
        return float("inf")
    window = np.hanning(size)
    left = np.abs(np.fft.rfft(reference[:size] * window)) + 1e-8
    right = np.abs(np.fft.rfft(candidate[:size] * window)) + 1e-8
    return float(np.mean(np.abs(20 * np.log10(left / right))))


def compare_audio(reference_path: Path, candidate_path: Path) -> AudioAlignmentReport:
    reference, rate = _read_mono(reference_path)
    candidate, candidate_rate = _read_mono(candidate_path)
    candidate = _resample(candidate, candidate_rate, rate)
    width = min(len(reference), len(candidate), max(1, rate // 4))
    correlation = np.correlate(candidate[:width], reference[:width], mode="full")
    offset = int(np.argmax(correlation) - (width - 1)) if width else 0
    if offset > 0:
        candidate = candidate[offset:]
    elif offset < 0:
        reference = reference[-offset:]
    size = min(len(reference), len(candidate))
    reference, candidate = reference[:size], candidate[:size]
    reference_rms = float(np.sqrt(np.mean(reference**2)) + 1e-12)
    candidate_rms = float(np.sqrt(np.mean(candidate**2)) + 1e-12)
    return AudioAlignmentReport(
        rate,
        offset,
        _onset(candidate) - _onset(reference),
        float(20 * np.log10(candidate_rms / reference_rms)),
        _spectral_distance(reference, candidate),
    )


__all__ = [
    "AudioAlignmentReport", "InstrumentCoverage", "compare_audio",
    "sample_coverage_for_tracks",
]
