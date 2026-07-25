#!/usr/bin/env python3
"""Create safe BDO game-test scores covering every instrument and MIDI pitch.

The game may impose an instrument-count limit on a single composition, so the
generator writes a numbered suite (eight instruments per score) rather than a
single potentially unopenable oversized file.  Every melodic instrument plays
MIDI 12..119 once; the drum kit plays its actual BDO keys 48..64 with type 99.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_midi import BDO_INSTRUMENT_NAMES, BDO_INSTRUMENTS, Note  # noqa: E402
from bdo_export import build_bdo_binary, encrypt_bdo, extract_owner_id  # noqa: E402


BPM = 120
NOTE_MS = 110.0
GAP_MS = 20.0
INSTRUMENTS_PER_FILE = 8
DRUM_SET_ID = BDO_INSTRUMENTS["drum_set"]


def notes_for(instrument_id: int) -> list[Note]:
    if instrument_id == DRUM_SET_ID:
        return [Note(pitch, 100, index * (NOTE_MS + GAP_MS), NOTE_MS, 99)
                for index, pitch in enumerate(range(48, 65))]
    return [Note(pitch, 100, index * (NOTE_MS + GAP_MS), NOTE_MS, 0)
            for index, pitch in enumerate(range(12, 120))]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output-prefix", default="BDO_All_Instruments_All_Notes")
    result.add_argument("--outdir", default=str(ROOT / "out" / "bdo"))
    result.add_argument("--owner-file", help="existing BDO file used to copy owner and character")
    result.add_argument("--owner-id", type=lambda value: int(value, 0),
                        help="owner ID in decimal or 0x... form; overrides --owner-file ID")
    result.add_argument("--name", default="AllNotesTest")
    result.add_argument("--install", action="store_true")
    result.add_argument("--game-dir", default=str(Path.home() / "Documents" / "Black Desert" / "Music"))
    return result


def main() -> None:
    args = parser().parse_args()
    owner_id, character = 0, args.name
    if args.owner_file:
        owner_id, inherited_name = extract_owner_id(args.owner_file)
        character = inherited_name or character
    if args.owner_id is not None:
        owner_id = args.owner_id

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(BDO_INSTRUMENTS.values()))
    manifest = ["BDO all-instruments / all-notes test suite", f"owner=0x{owner_id:08x}", ""]
    created: list[Path] = []
    for page, offset in enumerate(range(0, len(ids), INSTRUMENTS_PER_FILE), start=1):
        subset = ids[offset:offset + INSTRUMENTS_PER_FILE]
        groups = [(instrument_id, [notes_for(instrument_id)]) for instrument_id in subset]
        output = out_dir / f"{args.output_prefix}_{page:02d}"
        output.write_bytes(encrypt_bdo(build_bdo_binary(BPM, 4, groups, character, owner_id=owner_id)))
        created.append(output)
        manifest.append(f"{output.name}")
        for instrument_id in subset:
            pitches = notes_for(instrument_id)
            manifest.append(
                f"  0x{instrument_id:02x} {BDO_INSTRUMENT_NAMES[instrument_id]}: "
                f"{pitches[0].pitch}-{pitches[-1].pitch}, type {pitches[0].ntype}"
            )

    manifest_path = out_dir / f"{args.output_prefix}_manifest.txt"
    manifest_path.write_text("\n".join(manifest) + "\n", encoding="utf-8")
    if args.install:
        game_dir = Path(args.game_dir)
        game_dir.mkdir(parents=True, exist_ok=True)
        for output in created:
            shutil.copy2(output, game_dir / output.name)
    print("\n".join(f"saved={path}" for path in created))
    print(f"manifest={manifest_path}")


if __name__ == "__main__":
    main()
