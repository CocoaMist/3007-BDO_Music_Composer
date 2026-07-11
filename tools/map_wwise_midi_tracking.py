#!/usr/bin/env python3
"""Recover Wwise MIDI note/velocity ranges from a wwiser text dump."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    node_id: int
    node_type: str
    parent_id: int | None
    source_id: int | None
    props: dict[str, int] = field(default_factory=dict)


BANK_START = re.compile(r"^\s*bank v\d+\s+(?P<bank>midi_instrument_[^\s]+\.bnk)\s*$", re.MULTILINE)
OBJECT = re.compile(
    r"^\s+obj\s+(?P<type>CAk\w+)\[\d+\](?P<body>.*?)(?=^\s+obj\s+CAk\w+\[\d+\]|\Z)",
    re.MULTILINE | re.DOTALL,
)
VALUE = re.compile(
    r"\[(?P<name>MidiTrackingRootNote|MidiKeyRangeMin|MidiKeyRangeMax|MidiVelocityRangeMin|MidiVelocityRangeMax)\]"
    r"\s*\n.*?pValue = (?P<value>-?\d+)",
    re.DOTALL,
)


def parse_nodes(section: str) -> dict[int, Node]:
    nodes: dict[int, Node] = {}
    for match in OBJECT.finditer(section):
        body = match.group("body")
        id_match = re.search(r"\bulID = (\d+)", body)
        if not id_match:
            continue
        source_match = re.search(r"\bsourceID = (\d+)", body)
        parent_match = re.search(r"\bDirectParentID = (\d+)", body)
        node = Node(
            node_id=int(id_match.group(1)),
            node_type=match.group("type"),
            parent_id=int(parent_match.group(1)) if parent_match and parent_match.group(1) != "0" else None,
            source_id=int(source_match.group(1)) if source_match else None,
            props={item.group("name"): int(item.group("value")) for item in VALUE.finditer(body)},
        )
        nodes[node.node_id] = node
    return nodes


def effective_props(node: Node, nodes: dict[int, Node]) -> dict[str, int | None]:
    values: dict[str, int | None] = {
        "MidiTrackingRootNote": None,
        "MidiKeyRangeMin": None,
        "MidiKeyRangeMax": None,
        "MidiVelocityRangeMin": None,
        "MidiVelocityRangeMax": None,
    }
    seen: set[int] = set()
    current: Node | None = node
    while current and current.node_id not in seen:
        seen.add(current.node_id)
        for name in values:
            if values[name] is None and name in current.props:
                values[name] = current.props[name]
        current = nodes.get(current.parent_id) if current.parent_id else None
    values["MidiKeyRangeMin"] = 0 if values["MidiKeyRangeMin"] is None else values["MidiKeyRangeMin"]
    values["MidiKeyRangeMax"] = 127 if values["MidiKeyRangeMax"] is None else values["MidiKeyRangeMax"]
    values["MidiVelocityRangeMin"] = 0 if values["MidiVelocityRangeMin"] is None else values["MidiVelocityRangeMin"]
    values["MidiVelocityRangeMax"] = 127 if values["MidiVelocityRangeMax"] is None else values["MidiVelocityRangeMax"]
    if values["MidiTrackingRootNote"] is None:
        values["MidiTrackingRootNote"] = (values["MidiKeyRangeMin"] + values["MidiKeyRangeMax"]) // 2
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Map Wwise MIDI tracking data to extracted WEM files")
    parser.add_argument("dump", type=Path, help="wwiser combined text dump")
    parser.add_argument("wem_root", type=Path, help="Root directory containing <bank>/<source_id>.wem")
    parser.add_argument("--wav-root", type=Path, help="Optional root directory containing decoded WAV files")
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    text = args.dump.read_text(encoding="utf-8")
    starts = list(BANK_START.finditer(text))
    rows = []
    for index, start in enumerate(starts):
        bank_filename = start.group("bank")
        bank = Path(bank_filename).stem
        section = text[start.end():starts[index + 1].start() if index + 1 < len(starts) else len(text)]
        nodes = parse_nodes(section)
        for node in nodes.values():
            if node.node_type != "CAkSound" or node.source_id is None:
                continue
            props = effective_props(node, nodes)
            wem_path = args.wem_root / bank / f"{node.source_id}.wem"
            wav_path = args.wav_root / bank / f"{node.source_id}.wav" if args.wav_root else None
            rows.append({
                "bank": bank,
                "sound_id": node.node_id,
                "source_id": node.source_id,
                "root_note": props["MidiTrackingRootNote"],
                "key_min": props["MidiKeyRangeMin"],
                "key_max": props["MidiKeyRangeMax"],
                "velocity_min": props["MidiVelocityRangeMin"],
                "velocity_max": props["MidiVelocityRangeMax"],
                "wem_path": str(wem_path),
                "wem_exists": wem_path.is_file(),
                "wav_path": str(wav_path) if wav_path else "",
                "wav_exists": wav_path.is_file() if wav_path else False,
            })

    rows.sort(key=lambda row: (row["bank"], row["key_min"], row["velocity_min"], row["source_id"]))
    fields = ["bank", "sound_id", "source_id", "root_note", "key_min", "key_max", "velocity_min", "velocity_max", "wem_exists", "wav_exists", "wem_path", "wav_path"]
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    by_bank: dict[str, list[dict]] = {}
    for row in rows:
        by_bank.setdefault(row["bank"], []).append(row)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({"format": 1, "banks": by_bank}, ensure_ascii=False, indent=2), encoding="utf-8")
    found_wem = sum(row["wem_exists"] for row in rows)
    found_wav = sum(row["wav_exists"] for row in rows) if args.wav_root else 0
    print(f"Mapped {len(rows)} sound nodes; WEM {found_wem}/{len(rows)}; WAV {found_wav}/{len(rows)}")
    return 0 if found_wem == len(rows) and (not args.wav_root or found_wav == len(rows)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
