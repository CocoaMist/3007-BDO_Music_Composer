#!/usr/bin/env python3
"""Temporary, standalone lossless BDO-v9-to-MIDI converter.

The ordinary MIDI events make the score playable in MIDI software.  A MIDI
sequencer cannot natively express BDO ``ntype``, its second velocity byte, or
arbitrary floating-point millisecond positions.  Therefore every physical BDO
track also receives a ``sequencer_specific`` event containing an exact copy of
its public note records and track settings.  This tool is deliberately not
imported by the desktop application.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import sys
from typing import Iterable


# Allow ``python tools/bdo_to_midi.py`` from any current directory without
# installing the repository.  Only the independent codec package is imported.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

import mido
from bdo_codec import BdoDocument, BdoTrack, read_score


TICKS_PER_BEAT = 960
_METADATA_MAGIC = b"BDOM"
_METADATA_VERSION = 1
_TRACK_HEADER = struct.Struct("<4sBHHHB8sI")
_NOTE_RECORD = struct.Struct("<BBBBdd")

# This is only a listening-friendly General MIDI suggestion.  The exact BDO
# instrument ID is retained in the lossless metadata block.
_PROGRAM_BY_BDO_INSTRUMENT = {
    0x00: 24, 0x01: 73, 0x02: 74, 0x04: 115, 0x05: 49, 0x06: 46,
    0x07: 0, 0x08: 40, 0x0A: 24, 0x0B: 73, 0x0E: 33, 0x0F: 43,
    0x10: 46, 0x11: 0, 0x12: 40, 0x13: 112, 0x24: 27, 0x25: 29,
    0x26: 30, 0x27: 71, 0x28: 60,
}


def _tempo_from_bpm(bpm: int) -> int:
    return mido.bpm2tempo(max(1, min(999, int(bpm))))


def _milliseconds_to_ticks(milliseconds: float, tempo: int) -> int:
    return max(0, round(mido.second2tick(milliseconds / 1000.0, TICKS_PER_BEAT, tempo)))


def encode_lossless_track_metadata(group_index: int, track_index: int, track: BdoTrack) -> bytes:
    """Encode BDO fields MIDI cannot represent, without private header data."""

    payload = bytearray(_TRACK_HEADER.pack(
        _METADATA_MAGIC,
        _METADATA_VERSION,
        group_index,
        track_index,
        int(track.instrument_id),
        int(track.volume),
        track.settings.to_bytes(),
        len(track.notes),
    ))
    for note in track.notes:
        payload.extend(_NOTE_RECORD.pack(
            int(note.pitch), int(note.ntype), int(note.velocity_a), int(note.velocity_b),
            float(note.start_ms), float(note.duration_ms),
        ))
    return bytes(payload)


def decode_lossless_track_metadata(payload: bytes) -> dict[str, object] | None:
    """Decode one BDOM metadata payload; return ``None`` for unrelated MIDI data."""

    if len(payload) < _TRACK_HEADER.size or payload[:4] != _METADATA_MAGIC:
        return None
    magic, version, group, physical, instrument, volume, settings, count = _TRACK_HEADER.unpack_from(payload)
    if magic != _METADATA_MAGIC or version != _METADATA_VERSION:
        raise ValueError("unsupported BDOM lossless metadata version")
    expected_size = _TRACK_HEADER.size + count * _NOTE_RECORD.size
    if len(payload) != expected_size:
        raise ValueError("invalid BDOM lossless metadata length")
    notes = [
        _NOTE_RECORD.unpack_from(payload, _TRACK_HEADER.size + index * _NOTE_RECORD.size)
        for index in range(count)
    ]
    return {
        "group_index": group,
        "track_index": physical,
        "instrument_id": instrument,
        "volume": volume,
        "settings": tuple(settings),
        "notes": notes,
    }


def lossless_metadata_from_midi(midi_path: Path) -> list[dict[str, object]]:
    """Extract BDOM metadata blocks, used by ``--verify`` and automated checks."""

    result: list[dict[str, object]] = []
    for midi_track in mido.MidiFile(midi_path).tracks:
        for message in midi_track:
            if message.type == "sequencer_specific":
                decoded = decode_lossless_track_metadata(bytes(message.data))
                if decoded is not None:
                    result.append(decoded)
    return result


def _midi_track_for_bdo_track(
    group_index: int,
    track_index: int,
    track: BdoTrack,
    *,
    tempo: int,
    channel: int,
) -> mido.MidiTrack:
    events: list[tuple[int, int, mido.Message]] = []
    if track.instrument_id != 0x0D:
        events.append((0, 0, mido.Message(
            "program_change", channel=channel,
            program=_PROGRAM_BY_BDO_INSTRUMENT.get(int(track.instrument_id), 0),
        )))
    for note in track.notes:
        start = _milliseconds_to_ticks(note.start_ms, tempo)
        # MIDI note-off must not precede note-on even for malformed/zero BDO durations.
        end = max(start, _milliseconds_to_ticks(note.start_ms + note.duration_ms, tempo))
        events.append((start, 1, mido.Message(
            "note_on", channel=channel, note=note.pitch, velocity=max(1, note.velocity_a),
        )))
        events.append((end, 0, mido.Message(
            "note_off", channel=channel, note=note.pitch, velocity=0,
        )))
    events.sort(key=lambda item: (item[0], item[1]))  # note-off first at a shared tick
    output = mido.MidiTrack()
    output.append(mido.MetaMessage(
        "track_name", name=f"BDO {group_index + 1}.{track_index + 1} instrument 0x{track.instrument_id:02X}", time=0,
    ))
    output.append(mido.MetaMessage(
        "sequencer_specific", data=encode_lossless_track_metadata(group_index, track_index, track), time=0,
    ))
    last_tick = 0
    for tick, _order, message in events:
        message.time = tick - last_tick
        output.append(message)
        last_tick = tick
    output.append(mido.MetaMessage("end_of_track", time=0))
    return output


def convert_bdo_to_midi(document: BdoDocument, output_path: Path) -> None:
    """Write a Type-1 MIDI projection plus exact BDOM note metadata."""

    tempo = _tempo_from_bpm(document.header.bpm)
    midi = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    meta.append(mido.MetaMessage(
        "time_signature", numerator=max(1, int(document.header.time_signature)), denominator=4, time=0,
    ))
    meta.append(mido.MetaMessage("end_of_track", time=0))
    midi.tracks.append(meta)
    non_drum_channel = 0
    for group_index, group in enumerate(document.groups):
        for track_index, track in enumerate(group.tracks):
            if track.instrument_id == 0x0D:
                channel = 9
            else:
                channel = non_drum_channel
                non_drum_channel = (non_drum_channel + 1) % 16
                if non_drum_channel == 9:
                    non_drum_channel = (non_drum_channel + 1) % 16
            midi.tracks.append(_midi_track_for_bdo_track(
                group_index, track_index, track, tempo=tempo, channel=channel,
            ))
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    try:
        midi.save(temporary)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _document_metadata(document: BdoDocument) -> list[dict[str, object]]:
    return [
        {
            "group_index": group_index,
            "track_index": track_index,
            "instrument_id": track.instrument_id,
            "volume": track.volume,
            "settings": tuple(track.settings),
            "notes": [note.values() for note in track.notes],
        }
        for group_index, group in enumerate(document.groups)
        for track_index, track in enumerate(group.tracks)
    ]


def verify_lossless_metadata(document: BdoDocument, midi_path: Path) -> None:
    """Raise when the embedded exact BDO note/track records differ from source."""

    expected = _document_metadata(document)
    actual = lossless_metadata_from_midi(midi_path)
    if actual != expected:
        raise ValueError("lossless BDOM metadata verification failed")


def _parse_args(arguments: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Temporary lossless BDO v9 to MIDI converter.")
    parser.add_argument("input", type=Path, help="source BDO v9 score")
    parser.add_argument("output", type=Path, nargs="?", help="output .mid (default: input name with .mid)")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    parser.add_argument("--verify", action="store_true", help="read the MIDI back and verify exact BDO metadata")
    return parser.parse_args(arguments)


def main(arguments: Iterable[str] | None = None) -> int:
    args = _parse_args(arguments)
    source = args.input.expanduser()
    output = (args.output or source.with_suffix(".mid")).expanduser()
    if not source.is_file():
        print(f"error: input BDO file does not exist: {source}", file=sys.stderr)
        return 2
    if output.exists() and not args.force:
        print(f"error: output already exists (use --force): {output}", file=sys.stderr)
        return 2
    try:
        document = read_score(source)
        convert_bdo_to_midi(document, output)
        if args.verify:
            verify_lossless_metadata(document, output)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"converted {document.total_notes} BDO notes to {output}")
    if args.verify:
        print("verified: exact BDO note fields and physical track metadata are embedded in MIDI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
