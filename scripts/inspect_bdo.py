#!/usr/bin/env python3
"""Inspect a BDO v9 score through the reusable snapshot reader."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOL_DIR))

from bdo_score import read_bdo_score  # noqa: E402
from midi2bdo import BDO_INSTRUMENT_NAMES  # noqa: E402


SETTING_NAMES = (
    "inst_reverb", "eff_reverb", "inst_delay", "eff_delay",
    "inst_chorus", "chorus_feedback", "chorus_lfo_depth", "chorus_lfo_freq",
)


def parse_bdo(path: Path, sample_notes: int = 5) -> dict:
    snapshot = read_bdo_score(path)
    result = {
        "path": str(path),
        "version": snapshot.version,
        "payload_size": snapshot.payload_size,
        "owner_id": snapshot.owner_id,
        "character_name_1": snapshot.character_name_1,
        "character_name_2": snapshot.character_name_2,
        "bpm": snapshot.bpm,
        "time_signature": snapshot.time_signature,
        "instrument_tag": snapshot.instrument_tag,
        "groups": [],
        "total_notes": snapshot.total_notes,
        "note_type_counts": {},
        "parsed_bytes": snapshot.parsed_bytes,
        "trailing_zero_bytes": snapshot.trailing_zero_bytes,
    }
    all_types: Counter[int] = Counter()
    for group_index in range(snapshot.instrument_count):
        group_tracks = [track for track in snapshot.tracks if track.group_index == group_index]
        group = {"index": group_index, "track_count": len(group_tracks), "tracks": []}
        for track in group_tracks:
            counts = Counter(note.ntype for note in track.notes)
            all_types.update(counts)
            pitches = [note.pitch for note in track.notes]
            end_ms = max((note.start_ms + note.duration_ms for note in track.notes), default=0.0)
            samples = [
                {
                    "index": index,
                    "pitch": note.pitch,
                    "ntype": note.ntype,
                    "velocity_a": note.velocity_a,
                    "velocity_b": note.velocity_b,
                    "start_ms": round(note.start_ms, 3),
                    "duration_ms": round(note.duration_ms, 3),
                }
                for index, note in enumerate(track.notes[:max(0, sample_notes)])
            ]
            group["tracks"].append({
                "index": track.track_index,
                "instrument_id": track.instrument_id,
                "instrument": BDO_INSTRUMENT_NAMES.get(track.instrument_id, f"0x{track.instrument_id:02x}"),
                "volume": track.volume,
                "data_size": track.data_size,
                "settings": dict(zip(SETTING_NAMES, track.settings)),
                "note_count": len(track.notes),
                "note_type_counts": dict(sorted(counts.items())),
                "pitch_min": min(pitches) if pitches else None,
                "pitch_max": max(pitches) if pitches else None,
                "end_ms": round(end_ms, 3),
                "sample_notes": samples,
            })
        result["groups"].append(group)
    result["note_type_counts"] = dict(sorted(all_types.items()))
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
    for group in report["groups"]:
        print(f"Group {group['index']} tracks={group['track_count']}")
        for track in group["tracks"]:
            print(
                f"  Track {track['index']}: inst=0x{track['instrument_id']:02x} "
                f"{track['instrument']} volume={track['volume']} notes={track['note_count']} "
                f"types={track['note_type_counts']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--sample-notes", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = parse_bdo(args.path, sample_notes=args.sample_notes)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else "", end="")
    if not args.json:
        print_text(report)


if __name__ == "__main__":
    main()
