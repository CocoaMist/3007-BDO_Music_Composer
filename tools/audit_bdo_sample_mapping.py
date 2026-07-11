#!/usr/bin/env python3
"""Audit GUI BDO instrument IDs against Wwise maps and saved game scores."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "midi-to-bdo"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from midi2bdo import BDO_INSTRUMENT_NAMES, BDO_INSTRUMENTS  # noqa: E402
from bdo_sample_renderer import BDO_BANK_BY_ID  # noqa: E402
from bdo_realtime_audio import marnian_synth_matrix  # noqa: E402
from inspect_bdo import parse_bdo  # noqa: E402
from pyside_bdo_gui import BDO_ARTICULATIONS  # noqa: E402
from project_paths import WWISE_MIDI_MAP_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=WWISE_MIDI_MAP_PATH)
    parser.add_argument("--music-dir", type=Path, help="Optional Black Desert Music directory")
    args = parser.parse_args()

    active_ids = set(BDO_INSTRUMENTS.values())
    mapped_ids = set(BDO_BANK_BY_ID)
    payload = json.loads(args.map.read_text(encoding="utf-8"))
    by_bank = payload.get("banks", {})
    synth_matrix = marnian_synth_matrix()
    synth_missing = [
        (instrument_id, mode, bank)
        for instrument_id, modes in synth_matrix.items()
        for mode, bank in modes.items()
        if not bank or not any(row.get("wav_exists") for row in by_bank.get(bank, []))
    ]
    duplicate_banks = [bank for bank, count in Counter(BDO_BANK_BY_ID.values()).items() if count > 1]
    missing_banks = [bank for bank in BDO_BANK_BY_ID.values() if bank not in by_bank]
    missing_wav = [
        (bank, row["source_id"])
        for bank, rows in by_bank.items()
        for row in rows
        if not row.get("wav_exists")
    ]

    direct_ids = active_ids & mapped_ids
    synth_ids = set(synth_matrix)
    print(f"GUI IDs: {len(active_ids)}")
    print(f"Direct named-BNK IDs: {len(direct_ids)}")
    print(f"Marnian synth-routed IDs: {len(synth_ids)}")
    print(f"Preview-routable IDs: {len(direct_ids | synth_ids)}")
    print("Marnian 4x4 source matrix:")
    for instrument_id, modes in sorted(synth_matrix.items()):
        values = ", ".join(
            f"{mode}={'ok' if (instrument_id, mode, bank) not in synth_missing else 'missing'}"
            for mode, bank in modes.items()
        )
        print(f"  0x{instrument_id:02x} {BDO_INSTRUMENT_NAMES[instrument_id]}: {values}")
    print("Unroutable GUI IDs:")
    for instrument_id in sorted(active_ids - direct_ids - synth_ids):
        print(f"  0x{instrument_id:02x} {BDO_INSTRUMENT_NAMES[instrument_id]}")
    print(f"Duplicate bank mappings: {duplicate_banks or 'none'}")
    print(f"Mapped banks absent from HIRC JSON: {missing_banks or 'none'}")
    print(f"HIRC rows with missing WAV: {len(missing_wav)}")
    print(f"Marnian synth cells with missing WAV: {len(synth_missing)}")

    if args.music_dir:
        used_ids: Counter[int] = Counter()
        observed_fx: dict[int, set[int]] = {}
        non_fx_types: dict[int, set[int]] = {}
        failures = []
        for path in args.music_dir.iterdir():
            if not path.is_file():
                continue
            try:
                report = parse_bdo(path, sample_notes=0)
            except Exception as exc:
                failures.append(f"{path.name}: {exc}")
                continue
            for group in report["groups"]:
                for track in group["tracks"]:
                    instrument_id = track["instrument_id"]
                    used_ids[instrument_id] += 1
                    observed_types = set(track["note_type_counts"])
                    if instrument_id in BDO_ARTICULATIONS:
                        observed_fx.setdefault(instrument_id, set()).update(observed_types)
                    else:
                        non_fx_types.setdefault(instrument_id, set()).update(observed_types)
        print(f"Parsed game scores: {sum(used_ids.values())} tracks; failures: {len(failures)}")
        print("Game-only IDs:", sorted(f"0x{i:02x}" for i in set(used_ids) - active_ids) or "none")
        print("GUI IDs not observed in supplied scores:", sorted(f"0x{i:02x}" for i in active_ids - set(used_ids)) or "none")
        if failures:
            print("Parse failures:")
            for failure in failures:
                print(f"  {failure}")

        # FX tables are serialized as game ntype values.  Only instruments with
        # an explicit FX table are checked strictly; 0 and 99 on other tracks
        # are normal/basic and percussion storage values respectively.
        unknown_fx = {}
        missing_fx = {}
        print("Articulation audit (explicit FX instruments):")
        for instrument_id, definitions in sorted(BDO_ARTICULATIONS.items()):
            expected = {ntype for ntype, _label in definitions}
            observed = observed_fx.get(instrument_id, set())
            unknown = observed - expected
            missing = expected - observed
            if unknown:
                unknown_fx[instrument_id] = unknown
            if missing:
                missing_fx[instrument_id] = missing
            print(
                f"  0x{instrument_id:02x} "
                f"expected={sorted(expected)} observed={sorted(observed)} "
                f"unknown={sorted(unknown)} missing={sorted(missing)}"
            )
        print("Non-FX track ntypes (informational):")
        for instrument_id, ntypes in sorted(non_fx_types.items()):
            print(f"  0x{instrument_id:02x} {BDO_INSTRUMENT_NAMES.get(instrument_id, 'unknown')}: {sorted(ntypes)}")
        if unknown_fx:
            print("Unknown articulation ntypes:", unknown_fx)
        if missing_fx:
            print("Unobserved declared FX ntypes (coverage only):", missing_fx)

    problems = duplicate_banks or missing_banks or missing_wav or synth_missing
    if args.music_dir:
        problems = problems or bool(unknown_fx)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
