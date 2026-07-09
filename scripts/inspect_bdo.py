#!/usr/bin/env python3
"""Inspect decrypted BDO music files for format research."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"
sys.path.insert(0, str(TOOL_DIR))

import _ice  # noqa: E402
from midi2bdo import (  # noqa: E402
    BDO_INSTRUMENT_NAMES,
    BDO_VERSION,
    HEADER_SIZE,
    NAME_FIELD_SIZE,
    NOTE_SIZE,
)


TRACK_HEADER = struct.Struct("<HH8sH")
NOTE = struct.Struct("<BBBBdd")


def decode_name(data: bytes) -> str:
    return data.decode("utf-16-le", errors="replace").rstrip("\x00")


def decode_settings(settings: bytes) -> dict[str, int]:
    values = list(settings)
    return {
        "inst_reverb": values[0],
        "eff_reverb": values[1],
        "inst_delay": values[2],
        "eff_delay": values[3],
        "inst_chorus": values[4],
        "chorus_feedback": values[5],
        "chorus_lfo_depth": values[6],
        "chorus_lfo_freq": values[7],
    }


def decrypt_payload(path: Path) -> tuple[int, bytes]:
    data = path.read_bytes()
    if len(data) < 4:
        raise ValueError("file is too small")
    version = struct.unpack_from("<I", data, 0)[0]
    return version, _ice.decrypt(data[4:])


def parse_bdo(path: Path, sample_notes: int = 5) -> dict:
    version, plaintext = decrypt_payload(path)
    if version != BDO_VERSION:
        raise ValueError(f"unsupported BDO version {version}; expected {BDO_VERSION}")
    if len(plaintext) < HEADER_SIZE:
        raise ValueError("decrypted payload is shorter than the fixed header")

    owner_id = struct.unpack_from("<I", plaintext, 0)[0]
    name_a_start = 8
    name_b_start = name_a_start + NAME_FIELD_SIZE
    bpm_offset = name_b_start + NAME_FIELD_SIZE
    bpm, time_sig = struct.unpack_from("<HH", plaintext, bpm_offset)
    inst_tag_start = bpm_offset + 4
    inst_tag = plaintext[inst_tag_start:HEADER_SIZE].split(b"\x00", 1)[0].decode(
        "ascii", errors="replace"
    )

    result = {
        "path": str(path),
        "version": version,
        "payload_size": len(plaintext),
        "owner_id": owner_id,
        "character_name_1": decode_name(plaintext[name_a_start:name_b_start]),
        "character_name_2": decode_name(plaintext[name_b_start:bpm_offset]),
        "bpm": bpm,
        "time_signature": time_sig,
        "instrument_tag": inst_tag,
        "groups": [],
        "total_notes": 0,
        "note_type_counts": {},
    }

    offset = HEADER_SIZE
    all_note_types: Counter[int] = Counter()
    if offset >= len(plaintext) or plaintext[offset] != 0:
        raise ValueError(f"unexpected group marker at 0x{offset:x}")

    offset += 1
    num_instruments = struct.unpack_from("<H", plaintext, offset)[0]
    offset += 2

    for group_index in range(num_instruments):
        if group_index == 0:
            track_count = struct.unpack_from("<H", plaintext, offset)[0]
            offset += 2
        else:
            track_count = struct.unpack_from("<H", plaintext, offset)[0]
            offset += 2

        group = {"index": group_index, "track_count": track_count, "tracks": []}
        for track_index in range(track_count):
            if offset + TRACK_HEADER.size > len(plaintext):
                raise ValueError(f"track header exceeds payload at 0x{offset:x}")

            track_start = offset
            data_size, track_marker, settings, note_count = TRACK_HEADER.unpack_from(
                plaintext, offset
            )
            offset += TRACK_HEADER.size

            inst_id = track_marker & 0xFF
            volume = (track_marker >> 8) & 0xFF
            expected_note_bytes = note_count * NOTE_SIZE
            if offset + expected_note_bytes > len(plaintext):
                raise ValueError(f"notes exceed payload at 0x{offset:x}")

            note_type_counts: Counter[int] = Counter()
            samples = []
            pitch_min = None
            pitch_max = None
            end_ms = 0.0
            for note_index in range(note_count):
                pitch, ntype, vel_a, vel_b, start_ms, dur_ms = NOTE.unpack_from(
                    plaintext, offset
                )
                offset += NOTE.size
                note_type_counts[ntype] += 1
                all_note_types[ntype] += 1
                pitch_min = pitch if pitch_min is None else min(pitch_min, pitch)
                pitch_max = pitch if pitch_max is None else max(pitch_max, pitch)
                end_ms = max(end_ms, start_ms + dur_ms)
                if len(samples) < sample_notes:
                    samples.append(
                        {
                            "index": note_index,
                            "pitch": pitch,
                            "ntype": ntype,
                            "velocity_a": vel_a,
                            "velocity_b": vel_b,
                            "start_ms": round(start_ms, 3),
                            "duration_ms": round(dur_ms, 3),
                        }
                    )

            consumed = offset - track_start - 2
            if consumed < data_size:
                offset += data_size - consumed
            elif consumed > data_size:
                raise ValueError(
                    f"track consumed {consumed} bytes, larger than data_size {data_size}"
                )

            track = {
                "index": track_index,
                "instrument_id": inst_id,
                "instrument": BDO_INSTRUMENT_NAMES.get(inst_id, f"0x{inst_id:02x}"),
                "volume": volume,
                "data_size": data_size,
                "settings": decode_settings(settings),
                "note_count": note_count,
                "note_type_counts": dict(sorted(note_type_counts.items())),
                "pitch_min": pitch_min,
                "pitch_max": pitch_max,
                "end_ms": round(end_ms, 3),
                "sample_notes": samples,
            }
            group["tracks"].append(track)
            result["total_notes"] += note_count

        result["groups"].append(group)

    result["note_type_counts"] = dict(sorted(all_note_types.items()))
    result["parsed_bytes"] = offset
    result["trailing_zero_bytes"] = len(plaintext) - offset
    return result


def print_text(report: dict) -> None:
    print(f"File: {report['path']}")
    print(f"Version: {report['version']}  Payload: {report['payload_size']} bytes")
    print(f"Owner ID: 0x{report['owner_id']:08x}")
    print(f"Character: {report['character_name_1']!r}")
    print(f"BPM: {report['bpm']}  Time: {report['time_signature']}/4")
    print(f"Instrument tag: {report['instrument_tag']}")
    print(f"Total notes: {report['total_notes']}")
    print(f"Note types: {report['note_type_counts']}")
    print()
    for group in report["groups"]:
        print(f"Group {group['index']} tracks={group['track_count']}")
        for track in group["tracks"]:
            print(
                "  "
                f"Track {track['index']}: inst=0x{track['instrument_id']:02x} "
                f"{track['instrument']} volume={track['volume']} "
                f"notes={track['note_count']} types={track['note_type_counts']}"
            )
            print(f"    settings={track['settings']}")
            if track["sample_notes"]:
                print(f"    samples={track['sample_notes']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--sample-notes", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = parse_bdo(args.path, sample_notes=args.sample_notes)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text(report)


if __name__ == "__main__":
    main()
