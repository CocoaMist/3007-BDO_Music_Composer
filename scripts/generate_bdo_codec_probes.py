#!/usr/bin/env python3
"""Generate private one-variable BDO v9 probes for controlled in-game validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT,):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from bdo_midi import Note  # noqa: E402
from bdo_export import channel_groups_to_bdo, extract_owner_id  # noqa: E402
from pyside_bdo_gui import (  # noqa: E402
    BDO_ARTICULATIONS, BDO_EDITOR_PITCH_RANGES, BDO_INSTRUMENT_NAMES,
    MARNIAN_SYNTH_INSTRUMENT_IDS, MARNIAN_SYNTH_MODE_OFFSETS,
)


def _safe_pitch(instrument_id: int) -> int:
    allowed = BDO_EDITOR_PITCH_RANGES.get(instrument_id, range(48, 73))
    if not allowed:
        return 60
    return (int(allowed.start) + int(allowed.stop) - 1) // 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner_score", type=Path, help="private score saved by your own account")
    parser.add_argument("output", type=Path, help="private output directory; keep it outside Git")
    args = parser.parse_args()
    owner_id, character_name = extract_owner_id(str(args.owner_score))
    if not owner_id:
        raise SystemExit("owner score does not contain a valid Owner ID")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    def write_probe(name: str, instrument_id: int, notes: list[Note], **options) -> None:
        variables = options.pop("manifest_variables", {})
        data, summary = channel_groups_to_bdo(
            120, 4, [(notes, 0, instrument_id == 0x0D)],
            char_name=character_name, owner_id=owner_id,
            instrument_map={0: instrument_id}, preserve_note_types=True,
            **options,
        )
        target = args.output / name
        target.write_bytes(data)
        manifest.append({
            "file": name,
            "instrument_id": instrument_id,
            "notes": len(notes),
            "variables": variables,
            "bytes": len(data),
            "summary_notes": summary["total_notes"],
        })

    for instrument_id in sorted(BDO_INSTRUMENT_NAMES):
        write_probe(
            f"instrument-i{instrument_id:02x}-baseline",
            instrument_id,
            [Note(_safe_pitch(instrument_id), 96, 0.0, 1000.0, 0)],
            manifest_variables={"instrument_baseline": True},
        )

    for instrument_id, definitions in sorted(BDO_ARTICULATIONS.items()):
        pitch = _safe_pitch(instrument_id)
        for ntype, _label in definitions:
            write_probe(
                f"articulation-i{instrument_id:02x}-t{ntype:03d}",
                instrument_id,
                [Note(pitch, 96, 0.0, 1000.0, ntype)],
                manifest_variables={"ntype": ntype},
            )

    for volume in (0, 1, 70, 100, 127):
        write_probe(
            f"track-volume-{volume:03d}", 0x11,
            [Note(_safe_pitch(0x11), 96, 0.0, 1000.0, 0)],
            track_volumes={0: volume}, manifest_variables={"track_volume": volume},
        )

    for setting_index in range(8):
        values = [0] * 8
        values[setting_index] = 64
        write_probe(
            f"track-setting-{setting_index}-064", 0x11,
            [Note(_safe_pitch(0x11), 96, 0.0, 1000.0, 0)],
            track_settings_map={0: values},
            manifest_variables={"settings_index": setting_index, "value": 64},
        )

    for base_id in sorted(MARNIAN_SYNTH_INSTRUMENT_IDS):
        for mode, offset in MARNIAN_SYNTH_MODE_OFFSETS.items():
            serialized_id = base_id + offset
            write_probe(
                f"marnian-i{base_id:02x}-{mode}", serialized_id,
                [Note(_safe_pitch(base_id), 96, 0.0, 1000.0, 0)],
                manifest_variables={"base_instrument_id": base_id, "mode": mode, "offset": offset},
            )

    write_probe(
        "drum-canonical-48-64", 0x0D,
        [Note(pitch, 96, (pitch - 48) * 250.0, 100.0, 99) for pitch in range(48, 65)],
        manifest_variables={"pitch_range": [48, 64], "ntype": 99},
    )
    for instrument_id in (0x24, 0x25, 0x26):
        write_probe(
            f"electric-fx-i{instrument_id:02x}-36-43", instrument_id,
            [Note(pitch, 96, (pitch - 36) * 500.0, 300.0, 25) for pitch in range(36, 44)],
            manifest_variables={"pitch_range": [36, 43], "ntype": 25},
        )

    (args.output / "manifest.json").write_text(
        json.dumps({
            "schema": "bdo-codec-private-probes/v1",
            "contains_private_identity": True,
            "probe_count": len(manifest),
            "probes": manifest,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(manifest)} private probes in {args.output}")
    print("Do not commit or share this directory; score files contain your Owner ID and character name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
