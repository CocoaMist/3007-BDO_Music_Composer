#!/usr/bin/env python3
"""Estimate root pitches and velocity layers for decoded BDO WAV samples."""

from __future__ import annotations

import argparse
import csv
import json
import math
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np


BANK_TO_BDO_ID = {
    "midi_instrument_00_acousticguitar": 0x00,
    "midi_instrument_01_flute": 0x01,
    "midi_instrument_02_recorder": 0x02,
    "midi_instrument_04_handdrum": 0x04,
    "midi_instrument_05_piatticymbals": 0x05,
    "midi_instrument_06_harp": 0x06,
    "midi_instrument_07_piano": 0x07,
    "midi_instrument_08_violin": 0x08,
    "midi_instrument_10_proguitar": 0x0A,
    "midi_instrument_11_proflute": 0x0B,
    "midi_instrument_13_prodrumset": 0x0D,
    "midi_instrument_14_probasselectric": 0x0E,
    "midi_instrument_15_probasscontra": 0x0F,
    "midi_instrument_16_proharp": 0x10,
    "midi_instrument_17_propiano": 0x11,
    "midi_instrument_18_proviolin": 0x12,
    "midi_instrument_19_propandrum": 0x13,
    "midi_instrument_24_proguitarelectricclean": 0x24,
    "midi_instrument_25_proguitarelectricdrive": 0x25,
    "midi_instrument_26_proguitarelectricdist": 0x26,
    "midi_instrument_27_proclarinet": 0x27,
    "midi_instrument_28_prohorn": 0x28,
}

PERCUSSION_BANKS = {
    "midi_instrument_03_snaredrum",
    "midi_instrument_04_handdrum",
    "midi_instrument_05_piatticymbals",
    "midi_instrument_13_prodrumset",
    "midi_instrument_19_propandrum",
}


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        sample_width = source.getsampwidth()
        raw = source.readframes(source.getnframes())
    if sample_width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM, got {sample_width * 8}-bit")
    values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        values = values.reshape(-1, channels).mean(axis=1)
    return values, sample_rate


def estimate_pitch(samples: np.ndarray, sample_rate: int) -> tuple[float | None, float]:
    """Return (Hz, confidence) using a bounded autocorrelation peak."""
    if len(samples) < sample_rate // 12:
        return None, 0.0
    start = min(len(samples) // 8, int(sample_rate * 0.08))
    window = samples[start:start + min(len(samples) - start, int(sample_rate * 1.2))]
    if len(window) < sample_rate // 12:
        window = samples[:min(len(samples), int(sample_rate * 1.2))]
    window = window - np.mean(window)
    if not np.any(window):
        return None, 0.0
    window *= np.hanning(len(window))
    spectrum = np.fft.rfft(window, n=1 << (len(window) * 2 - 1).bit_length())
    autocorrelation = np.fft.irfft(spectrum * np.conj(spectrum))[:len(window)]
    if autocorrelation[0] <= 0:
        return None, 0.0
    autocorrelation /= autocorrelation[0]
    min_lag = max(1, int(sample_rate / 4500.0))
    max_lag = min(len(autocorrelation) - 1, int(sample_rate / 28.0))
    if min_lag >= max_lag:
        return None, 0.0
    region = autocorrelation[min_lag:max_lag + 1]
    peak_offset = int(np.argmax(region))
    peak_lag = min_lag + peak_offset
    confidence = float(region[peak_offset])
    if confidence < 0.18:
        return None, confidence
    # Prefer a smaller lag if it is nearly as periodic: this reduces octave-down
    # errors on bright instruments whose second harmonic is strongest.
    threshold = confidence * 0.88
    local = np.flatnonzero(region >= threshold)
    if len(local):
        candidates = local + min_lag
        candidates = candidates[(candidates > min_lag) & (candidates < max_lag)]
        if len(candidates):
            peak_lag = int(candidates[0])
    return sample_rate / peak_lag, confidence


def midi_from_hz(frequency: float | None) -> int | None:
    if not frequency or frequency <= 0:
        return None
    midi = 69 + 12 * math.log2(frequency / 440.0)
    return int(round(midi)) if 12 <= midi <= 120 else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze decoded BDO instrument WAV files")
    parser.add_argument("input", type=Path, help="Root directory of instrument WAV folders")
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    grouped: dict[tuple[str, int | None], list[dict]] = defaultdict(list)
    for path in sorted(args.input.rglob("*.wav")):
        relative = path.relative_to(args.input)
        if len(relative.parts) < 2:
            continue
        bank = relative.parts[0]
        samples, sample_rate = read_mono(path)
        rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
        is_percussion = bank in PERCUSSION_BANKS
        frequency, confidence = (None, 0.0) if is_percussion else estimate_pitch(samples, sample_rate)
        root_midi = midi_from_hz(frequency)
        row = {
            "bank": bank,
            "bdo_instrument_id": BANK_TO_BDO_ID.get(bank),
            "wem_id": path.stem,
            "path": str(path),
            "sample_rate": sample_rate,
            "duration_seconds": round(len(samples) / sample_rate, 4),
            "rms": round(rms, 6),
            "root_hz": round(frequency, 3) if frequency else None,
            "root_midi": root_midi,
            "pitch_confidence": round(confidence, 4),
            "percussion": is_percussion,
        }
        rows.append(row)
        grouped[(bank, root_midi)].append(row)

    for samples in grouped.values():
        samples.sort(key=lambda row: row["rms"])
        for layer, row in enumerate(samples, start=1):
            row["velocity_layer"] = layer
            row["velocity_layers"] = len(samples)

    fields = [
        "bank", "bdo_instrument_id", "wem_id", "root_midi", "root_hz", "pitch_confidence",
        "velocity_layer", "velocity_layers", "rms", "duration_seconds", "sample_rate", "percussion", "path",
    ]
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    by_bank: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_bank[row["bank"]].append(row)
    payload = {
        "format": 1,
        "source_root": str(args.input),
        "banks": {
            bank: {
                "bdo_instrument_id": BANK_TO_BDO_ID.get(bank),
                "percussion": bank in PERCUSSION_BANKS,
                "samples": samples,
            }
            for bank, samples in sorted(by_bank.items())
        },
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Analyzed {len(rows)} samples in {len(by_bank)} banks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
