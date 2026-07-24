#!/usr/bin/env python3
"""Generate the game-capture A/B checklist for BDO real-time playback."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_midi import BDO_INSTRUMENT_NAMES  # noqa: E402
from pyside_bdo_gui import BDO_ARTICULATIONS  # noqa: E402
from project_paths import WWISE_MIDI_MAP_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=WWISE_MIDI_MAP_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "out" / "bdo_audio_validation_matrix.json")
    args = parser.parse_args()
    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    bank_by_id = {
        0x00: "midi_instrument_00_acousticguitar", 0x01: "midi_instrument_01_flute", 0x02: "midi_instrument_02_recorder",
        0x04: "midi_instrument_04_handdrum", 0x05: "midi_instrument_05_piatticymbals", 0x06: "midi_instrument_06_harp",
        0x07: "midi_instrument_07_piano", 0x08: "midi_instrument_08_violin", 0x0A: "midi_instrument_10_proguitar",
        0x0B: "midi_instrument_11_proflute", 0x0D: "midi_instrument_13_prodrumset", 0x0E: "midi_instrument_14_probasselectric",
        0x0F: "midi_instrument_15_probasscontra", 0x10: "midi_instrument_16_proharp", 0x11: "midi_instrument_17_propiano",
        0x12: "midi_instrument_18_proviolin", 0x13: "midi_instrument_19_propandrum", 0x24: "midi_instrument_24_proguitarelectricclean",
        0x25: "midi_instrument_25_proguitarelectricdrive", 0x26: "midi_instrument_26_proguitarelectricdist", 0x27: "midi_instrument_27_proclarinet",
        0x28: "midi_instrument_28_prohorn",
    }
    cells = []
    for instrument_id, name in sorted(BDO_INSTRUMENT_NAMES.items()):
        bank = bank_by_id.get(instrument_id)
        zones = mapping.get("banks", {}).get(bank, []) if bank else []
        types = [value for value, _label in BDO_ARTICULATIONS.get(instrument_id, [(0, "默认")])]
        for zone in zones:
            pitch = int(zone["root_note"])
            velocity = round((int(zone["velocity_min"]) + int(zone["velocity_max"])) / 2)
            for ntype in types:
                cells.append({
                    "instrument_id": instrument_id,
                    "instrument": name,
                    "bank": bank,
                    "source_id": zone["source_id"],
                    "pitch": pitch,
                    "velocity": velocity,
                    "ntype": ntype,
                    "capture_path": None,
                    "onset_frames": None,
                    "pitch_cents": None,
                    "loudness_lufs": None,
                    "spectral_distance": None,
                    "listener_pass": None,
                    "verification": "pending",
                })
        if not zones:
            cells.append({"instrument_id": instrument_id, "instrument": name, "verification": "unmapped"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"format": 1, "cells": cells}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved={args.output} cells={len(cells)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
