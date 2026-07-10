"""Offline preview renderer backed by extracted BDO Wwise samples."""

from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np


SAMPLE_RATE = 36000

BDO_BANK_BY_ID = {
    0x00: "midi_instrument_00_acousticguitar",
    0x01: "midi_instrument_01_flute",
    0x02: "midi_instrument_02_recorder",
    0x04: "midi_instrument_04_handdrum",
    0x05: "midi_instrument_05_piatticymbals",
    0x06: "midi_instrument_06_harp",
    0x07: "midi_instrument_07_piano",
    0x08: "midi_instrument_08_violin",
    0x0A: "midi_instrument_10_proguitar",
    0x0B: "midi_instrument_11_proflute",
    0x0D: "midi_instrument_13_prodrumset",
    0x0E: "midi_instrument_14_probasselectric",
    0x0F: "midi_instrument_15_probasscontra",
    0x10: "midi_instrument_16_proharp",
    0x11: "midi_instrument_17_propiano",
    0x12: "midi_instrument_18_proviolin",
    0x13: "midi_instrument_19_propandrum",
    0x24: "midi_instrument_24_proguitarelectricclean",
    0x25: "midi_instrument_25_proguitarelectricdrive",
    0x26: "midi_instrument_26_proguitarelectricdist",
    0x27: "midi_instrument_27_proclarinet",
    0x28: "midi_instrument_28_prohorn",
}

GM_TO_BDO_DRUM = {
    35: 48, 36: 48, 37: 49, 38: 50, 39: 50, 40: 50, 41: 51,
    42: 54, 43: 53, 44: 56, 45: 55, 46: 58, 47: 57, 48: 59,
    49: 61, 50: 60, 51: 62, 52: 61, 53: 62, 54: 62, 55: 61,
    56: 62, 57: 61, 58: 62, 59: 62, 60: 60, 61: 61, 62: 61,
    63: 63, 64: 64,
}


@dataclass(frozen=True)
class RenderResult:
    duration_ms: float
    notes_rendered: int
    missing_instruments: tuple[int, ...]


@lru_cache(maxsize=128)
def _read_wav(path_string: str) -> np.ndarray:
    path = Path(path_string)
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"Unsupported sample width: {path}")
        data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        channels = source.getnchannels()
        rate = source.getframerate()
    if channels == 1:
        data = np.column_stack((data, data))
    else:
        data = data.reshape(-1, channels)[:, :2]
        if data.shape[1] == 1:
            data = np.column_stack((data[:, 0], data[:, 0]))
    if rate != SAMPLE_RATE:
        length = max(1, round(len(data) * SAMPLE_RATE / rate))
        positions = np.linspace(0, len(data) - 1, length)
        data = np.column_stack((
            np.interp(positions, np.arange(len(data)), data[:, 0]),
            np.interp(positions, np.arange(len(data)), data[:, 1]),
        )).astype(np.float32)
    return data.astype(np.float32, copy=False)


class BdoSampleMap:
    def __init__(self, map_path: str | Path) -> None:
        payload = json.loads(Path(map_path).read_text(encoding="utf-8"))
        self.by_bank = {
            bank: [row for row in rows if row.get("wav_exists")]
            for bank, rows in payload.get("banks", {}).items()
        }

    def has_instrument(self, instrument_id: int) -> bool:
        bank = BDO_BANK_BY_ID.get(instrument_id)
        return bool(bank and self.by_bank.get(bank))

    def supported_pitches(self, instrument_id: int) -> frozenset[int]:
        bank = BDO_BANK_BY_ID.get(instrument_id)
        return frozenset(
            pitch
            for row in self.by_bank.get(bank or "", [])
            for pitch in range(int(row["key_min"]), int(row["key_max"]) + 1)
        )

    def choose(self, instrument_id: int, pitch: int, velocity: int) -> dict | None:
        bank = BDO_BANK_BY_ID.get(instrument_id)
        rows = self.by_bank.get(bank or "", [])
        if not rows:
            return None
        if instrument_id == 0x0D:
            pitch = GM_TO_BDO_DRUM.get(pitch, pitch)
        matches = [
            row for row in rows
            if int(row["key_min"]) <= pitch <= int(row["key_max"])
            and int(row["velocity_min"]) <= velocity <= int(row["velocity_max"])
        ]
        if not matches:
            return None
        return min(
            matches,
            key=lambda row: (
                abs(pitch - int(row["root_note"])),
                abs(velocity - (int(row["velocity_min"]) + int(row["velocity_max"])) / 2),
                int(row["source_id"]),
            ),
        )


@lru_cache(maxsize=4)
def _cached_sample_map(map_path: str) -> BdoSampleMap:
    return BdoSampleMap(map_path)


def sample_map_covers(map_path: str | Path, instrument_ids: tuple[int, ...] | list[int]) -> bool:
    sample_map = _cached_sample_map(str(map_path))
    return all(sample_map.has_instrument(instrument_id) for instrument_id in instrument_ids)


def sample_map_supported_pitches(map_path: str | Path, instrument_id: int) -> frozenset[int]:
    """Return the exact MIDI keys with a Wwise source zone for an instrument."""
    return _cached_sample_map(str(map_path)).supported_pitches(instrument_id)


def sample_map_supports_note(
    map_path: str | Path, instrument_id: int, pitch: int, velocity: int
) -> bool:
    """Whether Wwise has an exact key-and-velocity zone for this note."""
    return _cached_sample_map(str(map_path)).choose(instrument_id, pitch, velocity) is not None


def _resample_for_note(sample: np.ndarray, root_note: int, target_note: int, max_frames: int) -> np.ndarray:
    ratio = 2.0 ** ((target_note - root_note) / 12.0)
    output_frames = min(max_frames, max(1, int(len(sample) / ratio)))
    positions = np.arange(output_frames, dtype=np.float32) * ratio
    return np.column_stack((
        np.interp(positions, np.arange(len(sample)), sample[:, 0]),
        np.interp(positions, np.arange(len(sample)), sample[:, 1]),
    )).astype(np.float32)


def render_preview(tracks: list, map_path: str | Path, output_path: str | Path, start_ms: float = 0.0) -> RenderResult:
    sample_map = BdoSampleMap(map_path)
    end_ms = max((note.start + note.dur * track.duration_scale for track in tracks for note in track.notes), default=start_ms)
    frames = max(1, int(math.ceil(max(0.0, end_ms - start_ms) * SAMPLE_RATE / 1000.0)) + SAMPLE_RATE // 8)
    mix = np.zeros((frames, 2), dtype=np.float32)
    missing: set[int] = set()
    rendered = 0

    for track in tracks:
        if not sample_map.has_instrument(track.bdo_instrument_id):
            missing.add(track.bdo_instrument_id)
            continue
        for note in track.notes:
            if note.start + note.dur * track.duration_scale <= start_ms:
                continue
            velocity = max(1, min(127, round(note.vel * track.volume_scale)))
            selected = sample_map.choose(track.bdo_instrument_id, note.pitch, velocity)
            if selected is None:
                missing.add(track.bdo_instrument_id)
                continue
            start_frame = max(0, round((note.start - start_ms) * SAMPLE_RATE / 1000.0))
            if start_frame >= len(mix):
                continue
            note_frames = max(1, round(note.dur * track.duration_scale * SAMPLE_RATE / 1000.0))
            sample = _read_wav(selected["wav_path"])
            target_pitch = GM_TO_BDO_DRUM.get(note.pitch, note.pitch) if track.bdo_instrument_id == 0x0D else note.pitch
            rendered_sample = _resample_for_note(sample, int(selected["root_note"]), target_pitch, note_frames)
            end_frame = min(len(mix), start_frame + len(rendered_sample))
            rendered_sample = rendered_sample[:end_frame - start_frame]
            fade = min(len(rendered_sample), max(16, int(SAMPLE_RATE * 0.012)))
            if fade:
                rendered_sample[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)[:, None]
            mix[start_frame:end_frame] += rendered_sample * (velocity / 127.0) * 0.72
            rendered += 1

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.98:
        mix *= 0.98 / peak
    pcm = np.clip(mix * 32767.0, -32768, 32767).astype("<i2")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(pcm.tobytes())
    return RenderResult((len(mix) / SAMPLE_RATE) * 1000.0, rendered, tuple(sorted(missing)))
