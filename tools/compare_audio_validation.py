#!/usr/bin/env python3
"""Measure one game-capture/local-render pair for the validation matrix."""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"only 16-bit WAV is supported: {path}")
        rate = source.getframerate()
        channels = source.getnchannels()
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, rate


def resample(signal: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return signal
    positions = np.linspace(0, len(signal) - 1, max(1, round(len(signal) * target_rate / source_rate)))
    return np.interp(positions, np.arange(len(signal)), signal).astype(np.float32)


def onset(signal: np.ndarray, rate: int) -> int:
    threshold = max(0.002, float(np.max(np.abs(signal))) * 0.03)
    hits = np.flatnonzero(np.abs(signal) >= threshold)
    return int(hits[0]) if len(hits) else 0


def align(reference: np.ndarray, candidate: np.ndarray, rate: int) -> int:
    # Limit to the first 250 ms; long tracks do not need an expensive full correlate.
    width = min(len(reference), len(candidate), max(1, rate // 4))
    ref = reference[:width]
    cand = candidate[:width]
    correlation = np.correlate(cand, ref, mode="full")
    return int(np.argmax(correlation) - (len(ref) - 1))


def spectral_distance(reference: np.ndarray, candidate: np.ndarray) -> float:
    size = min(len(reference), len(candidate), 16384)
    if size < 128:
        return float("inf")
    window = np.hanning(size)
    a = np.abs(np.fft.rfft(reference[:size] * window)) + 1e-8
    b = np.abs(np.fft.rfft(candidate[:size] * window)) + 1e-8
    return float(np.mean(np.abs(20 * np.log10(a / b))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="game capture WAV")
    parser.add_argument("candidate", type=Path, help="local renderer WAV")
    parser.add_argument("--output", type=Path, help="write JSON report")
    args = parser.parse_args()
    reference, reference_rate = read_mono(args.reference)
    candidate, candidate_rate = read_mono(args.candidate)
    candidate = resample(candidate, candidate_rate, reference_rate)
    offset = align(reference, candidate, reference_rate)
    if offset > 0:
        candidate = candidate[offset:]
    elif offset < 0:
        reference = reference[-offset:]
    size = min(len(reference), len(candidate))
    reference, candidate = reference[:size], candidate[:size]
    ref_rms = float(np.sqrt(np.mean(reference**2)) + 1e-12)
    candidate_rms = float(np.sqrt(np.mean(candidate**2)) + 1e-12)
    report = {
        "format": 1,
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        "sample_rate": reference_rate,
        "alignment_frames": offset,
        "onset_delta_frames": onset(candidate, reference_rate) - onset(reference, reference_rate),
        "loudness_delta_db": 20 * np.log10(candidate_rms / ref_rms),
        "spectral_distance_db": spectral_distance(reference, candidate),
        "listener_pass": None,
        "verification": "pending_listener_review",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
