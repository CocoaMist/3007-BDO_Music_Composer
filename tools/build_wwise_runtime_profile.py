#!/usr/bin/env python3
"""Create a conservative runtime profile from wwiser dumps and MIDI zones.

The profile deliberately preserves unresolved values as ``unknown``.  It is a
machine-readable audit input for the real-time player, not a claim that an
unidentified Wwise plug-in has been reimplemented.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from project_paths import WWISE_MIDI_MAP_PATH


BANK_START = re.compile(r"^\s*bank v\d+\s+(midi_instrument_[^\s]+\.bnk)\s*$", re.MULTILINE)
PLUGIN = re.compile(r"ulPluginID\s+=\s+(0x[0-9a-fA-F]+)(?:\s+\[([^]]+)\])?")
AUX = re.compile(r"\bauxID\s+=\s+(\d+)")
BUS = re.compile(r"\b(?:OverrideBusId|reflectionsAuxBus)\s+=\s+(\d+)")
RTPC = re.compile(r"\b(?:RTPC|pRTPCMgr|InitialRTPC)\b")


def bank_sections(text: str) -> dict[str, str]:
    starts = list(BANK_START.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(starts):
        name = Path(match.group(1)).stem
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        sections[name] = text[match.end():end]
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="Combined wwiser text dump")
    parser.add_argument("--map", type=Path, default=WWISE_MIDI_MAP_PATH)
    parser.add_argument("--output", type=Path, default=Path("wwise_runtime_profile.json"))
    args = parser.parse_args()

    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    sections = bank_sections(args.dump.read_text(encoding="utf-8", errors="replace"))
    banks = {}
    for bank, zones in mapping.get("banks", {}).items():
        section = sections.get(f"{bank}.bnk", sections.get(bank, ""))
        plugins = [
            {"id": plugin_id, "name": name}
            for plugin_id, name in sorted({(plugin_id.lower(), name or "unknown") for plugin_id, name in PLUGIN.findall(section)})
        ]
        banks[bank] = {
            "midi_zones": [{
                key: row.get(key)
                for key in ("sound_id", "source_id", "root_note", "key_min", "key_max", "velocity_min", "velocity_max")
            } for row in zones],
            "plugins": plugins,
            "aux_sends": sorted({int(value) for value in AUX.findall(section)}),
            "bus_ids": sorted({int(value) for value in BUS.findall(section) if int(value)}),
            "has_rtpc": bool(RTPC.search(section)),
            "loop": "unknown",
            "note_type_routing": "unknown",
        }
    payload = {
        "format": 1,
        "source_dump": str(args.dump),
        "banks": banks,
        "unknown_policy": "Do not emulate fields marked unknown or mark them verified.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved={args.output} banks={len(banks)} parsed_dump_banks={len(sections)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
