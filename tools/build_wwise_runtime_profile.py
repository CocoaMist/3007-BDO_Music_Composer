#!/usr/bin/env python3
"""Create a portable, conservative runtime-evidence profile from wwiser.

The profile is intentionally an audit artifact.  It records exact HIRC facts
without claiming that game-supplied RTPC values, spatial routing, or Wwise DSP
have been reproduced by the Python preview engine.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterator, TextIO


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from project_paths import WWISE_MIDI_MAP_PATH
from tools.map_wwise_midi_tracking import OBJECT, RTPC_OBJECT


BANK_START = re.compile(
    r"^\s*bank v(?P<version>\d+)\s+"
    r"(?P<bank>midi_instrument_[^\s]+\.bnk)\s*$",
    re.MULTILINE,
)
PLUGIN = re.compile(
    r"ulPluginID\s+=\s+(0x[0-9a-fA-F]+)(?:\s+\[([^]]+)\])?"
)
AUX = re.compile(r"\bauxID\s+=\s+(\d+)")
BUS = re.compile(r"\b(?:OverrideBusId|reflectionsAuxBus)\s+=\s+(\d+)")
NUMBER = r"-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?"
PROPERTY_VALUE = re.compile(
    rf"\bpID = [^\n]*\[([^]]+)\]\s*\n"
    rf"[^\n]*\bpValue = (?P<value>{NUMBER})"
)
GRAPH_POINT = re.compile(
    rf"\bFrom = (?P<from>{NUMBER})\s*\n"
    rf"[^\n]*\bTo = (?P<to>{NUMBER})\s*\n"
    r"[^\n]*\bInterp = [^\n]*\[([^]]+)\]"
)
MODULATOR_TYPES = {
    "CAkEnvelopeModulator": "envelope",
    "CAkLFOModulator": "lfo",
    "CAkTimeModulator": "time",
}


def parse_bank_dump(text: str) -> tuple[dict[str, str], dict[str, int]]:
    starts = list(BANK_START.finditer(text))
    sections: dict[str, str] = {}
    versions: dict[str, int] = {}
    for index, match in enumerate(starts):
        name = Path(match.group("bank")).stem
        if name in sections:
            raise ValueError(f"duplicate bank section: {name}")
        end = (
            starts[index + 1].start()
            if index + 1 < len(starts)
            else len(text)
        )
        sections[name] = text[match.end():end]
        versions[name] = int(match.group("version"))
    return sections, versions


def bank_sections(text: str) -> dict[str, str]:
    return parse_bank_dump(text)[0]


@contextmanager
def atomic_text_output(path: Path) -> Iterator[TextIO]:
    """Replace a generated profile only after successful serialization."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary as output:
            yield output
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _number(value: str) -> int | float:
    parsed = float(value)
    if parsed.is_integer() and "e" not in value.lower() and "." not in value:
        return int(parsed)
    return parsed


def _field(body: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)} = [^\n]*\[([^]]+)\]", body)
    return match.group(1) if match else None


def _integer_field(body: str, name: str) -> int | None:
    match = re.search(rf"\b{re.escape(name)} = (\d+)", body)
    return int(match.group(1)) if match else None


def parse_rtpc_bindings(section: str) -> list[dict[str, object]]:
    """Return object-owned RTPC curves without interpreting their scaling."""

    result: list[dict[str, object]] = []
    for object_match in OBJECT.finditer(section):
        body = object_match.group("body")
        owner_id = _integer_field(body, "ulID")
        if owner_id is None:
            continue
        for rtpc_match in RTPC_OBJECT.finditer(body):
            rtpc_body = rtpc_match.group("body")
            rtpc_type = _field(rtpc_body, "rtpcType")
            parameter = _field(rtpc_body, "ParamID")
            if not rtpc_type or not parameter:
                continue
            result.append({
                "owner_id": owner_id,
                "owner_type": object_match.group("type"),
                "rtpc_id": _integer_field(rtpc_body, "RTPCID"),
                "rtpc_type": rtpc_type,
                "parameter": parameter,
                "accumulation": _field(rtpc_body, "rtpcAccum") or "unknown",
                "scaling": _field(rtpc_body, "eScaling") or "unknown",
                "curve_id": _integer_field(rtpc_body, "rtpcCurveID"),
                "points": [
                    {
                        "x": _number(point.group("from")),
                        "y": _number(point.group("to")),
                        "interpolation": point.group(3),
                    }
                    for point in GRAPH_POINT.finditer(rtpc_body)
                ],
            })
    return sorted(
        result,
        key=lambda item: (
            int(item["owner_id"]),
            str(item["rtpc_type"]),
            str(item["parameter"]),
            int(item["rtpc_id"] or -1),
        ),
    )


def parse_modulators(section: str) -> list[dict[str, object]]:
    """Return exact modulator settings; no DSP behavior is inferred."""

    result: list[dict[str, object]] = []
    for object_match in OBJECT.finditer(section):
        kind = MODULATOR_TYPES.get(object_match.group("type"))
        if kind is None:
            continue
        body = object_match.group("body")
        node_id = _integer_field(body, "ulID")
        if node_id is None:
            continue
        result.append({
            "id": node_id,
            "type": kind,
            "properties": {
                match.group(1): _number(match.group("value"))
                for match in PROPERTY_VALUE.finditer(body)
            },
        })
    return sorted(result, key=lambda item: (str(item["type"]), int(item["id"])))


def _route_summary(zones: list[dict]) -> list[dict[str, object]]:
    grouped: dict[int, list[dict]] = {}
    for row in zones:
        values = row.get("route_ntypes", ())
        if isinstance(values, (int, str)):
            values = (values,)
        for value in values or ():
            try:
                grouped.setdefault(int(value), []).append(row)
            except (TypeError, ValueError):
                continue
    return [
        {
            "ntype": ntype,
            "rows": len(rows),
            "key_min": min(int(row["key_min"]) for row in rows),
            "key_max": max(int(row["key_max"]) for row in rows),
            "velocity_min": min(int(row["velocity_min"]) for row in rows),
            "velocity_max": max(int(row["velocity_max"]) for row in rows),
        }
        for ntype, rows in sorted(grouped.items())
    ]


def _finite_values(zones: list[dict], key: str) -> list[float]:
    result: list[float] = []
    for row in zones:
        value = row.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed):
            result.append(parsed)
    return result


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _consistent_groups(
    zones: list[dict],
    *,
    id_key: str,
    fields: tuple[tuple[str, str, object], ...],
) -> dict[int, dict[str, object]]:
    """Collect repeated row metadata and reject contradictory evidence."""

    result: dict[int, dict[str, object]] = {}
    for row in zones:
        raw_id = row.get(id_key)
        if raw_id is None:
            continue
        group_id = int(raw_id)
        record: dict[str, object] = {"id": group_id}
        for output_key, row_key, default in fields:
            value = row.get(row_key, default)
            if isinstance(default, bool):
                value = _truthy(value)
            elif isinstance(default, int):
                value = int(value or 0)
            elif isinstance(default, str):
                value = str(value)
            record[output_key] = value
        previous = result.get(group_id)
        if previous is not None and previous != record:
            raise ValueError(
                f"conflicting {id_key} metadata for group {group_id}: "
                f"{previous!r} != {record!r}"
            )
        result[group_id] = record
    return result


def build_bank_profile(
    bank: str,
    zones: list[dict],
    section: str,
) -> dict[str, object]:
    """Combine portable map facts with non-emulated HIRC evidence."""

    node_counts = Counter(
        match.group("type")
        for match in OBJECT.finditer(section)
    )
    rtpc_bindings = parse_rtpc_bindings(section)
    modulators = parse_modulators(section)
    releases = _finite_values(zones, "release_ms")
    selection_groups = _consistent_groups(
        zones,
        id_key="selection_group_id",
        fields=(
            ("mode", "selection_mode", "single"),
            ("avoid_repeat", "avoid_repeat", 0),
            ("continuous", "selection_continuous", False),
            ("global_scope", "selection_global", False),
            ("reset_playlist", "selection_reset_playlist", False),
        ),
    )
    instance_groups = _consistent_groups(
        [
            row for row in zones
            if row.get("instance_group_id") is not None
            and int(row.get("max_instances", 0) or 0) > 0
        ],
        id_key="instance_group_id",
        fields=(
            ("max_instances", "max_instances", 0),
            ("kill_newest", "kill_newest", False),
            ("global_scope", "instance_limit_global", False),
            (
                "use_virtual_behavior",
                "instance_use_virtual_behavior",
                False,
            ),
        ),
    )
    plugin_counts = Counter(
        (plugin_id.lower(), name or "unknown")
        for plugin_id, name in PLUGIN.findall(section)
    )
    rtpc_counts = Counter(
        (str(item["rtpc_type"]), str(item["parameter"]))
        for item in rtpc_bindings
    )

    return {
        "bank": bank,
        "zone_rows": len(zones),
        "source_ids": len({int(row["source_id"]) for row in zones}),
        "key_ranges": sorted({
            (int(row["key_min"]), int(row["key_max"]))
            for row in zones
        }),
        "velocity_ranges": sorted({
            (int(row["velocity_min"]), int(row["velocity_max"]))
            for row in zones
        }),
        "articulation_routes": _route_summary(zones),
        "sample_loop_rows": sum(
            1 for row in zones if int(row.get("sample_loops", 0) or 0) > 0
        ),
        "release_ms": {
            "known_rows": len(releases),
            "min": min(releases) if releases else None,
            "max": max(releases) if releases else None,
        },
        "selection_groups": [
            selection_groups[key] for key in sorted(selection_groups)
        ],
        "instance_groups": [
            instance_groups[key] for key in sorted(instance_groups)
        ],
        "hirc": {
            "node_counts": dict(sorted(node_counts.items())),
            "plugins": [
                {"id": plugin_id, "name": name, "references": count}
                for (plugin_id, name), count in sorted(plugin_counts.items())
            ],
            "aux_send_ids": sorted({
                int(value) for value in AUX.findall(section) if int(value)
            }),
            "bus_ids": sorted({
                int(value) for value in BUS.findall(section) if int(value)
            }),
            "modulators": modulators,
            "rtpc_binding_counts": [
                {
                    "type": rtpc_type,
                    "parameter": parameter,
                    "count": count,
                }
                for (rtpc_type, parameter), count in sorted(rtpc_counts.items())
            ],
            "rtpc_bindings": rtpc_bindings,
        },
    }


def runtime_profile_document(
    mapping: dict,
    sections: dict[str, str],
    *,
    dump_name: str,
    bank_versions: dict[str, int] | None = None,
    dump_sha256: str | None = None,
) -> dict[str, object]:
    banks = {
        bank: build_bank_profile(bank, zones, sections.get(bank, ""))
        for bank, zones in sorted(mapping.get("banks", {}).items())
    }
    return {
        "format": 2,
        # A basename is enough to identify the local evidence without leaking
        # the user's private machine path into a report or bug attachment.
        "source_dump_name": Path(dump_name).name,
        "source_dump_sha256": dump_sha256,
        "wwise_bank_versions": sorted(set((bank_versions or {}).values())),
        "banks": banks,
        "evidence_classes": {
            "runtime_safe": [
                "event_articulation_routes",
                "key_velocity_zones",
                "static_pitch_and_gain",
                "sample_loop_regions",
                "note_off_release_time",
                "container_playlist_and_instance_limits",
            ],
            "audit_only_until_scaling_is_implemented": [
                "rtpc_graphs",
                "envelope_and_lfo_modulators",
                "attenuation_curves",
            ],
            "requires_game_ab_or_additional_tables": [
                "game_parameter_runtime_values",
                "aux_bus_and_spatial_mix",
                "localized_instrument_and_articulation_names",
                "game_editor_unlock_and_range_constraints",
                "exact_synth_filter_lfo_envelope_sound",
            ],
        },
        "unknown_policy": (
            "Do not emulate audit-only fields or label them verified without "
            "their scaling, runtime inputs, and game A/B evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="Combined wwiser text dump")
    parser.add_argument("--map", type=Path, default=WWISE_MIDI_MAP_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("wwise_runtime_profile.json"),
    )
    args = parser.parse_args()

    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    if int(mapping.get("format", 0)) not in {1, 2}:
        raise ValueError(
            f"unsupported Wwise MIDI map format: {mapping.get('format')!r}"
        )
    dump_bytes = args.dump.read_bytes()
    sections, bank_versions = parse_bank_dump(
        dump_bytes.decode("utf-8", errors="replace")
    )
    mapping_banks = set(mapping.get("banks", {}))
    dump_banks = set(sections)
    if mapping_banks != dump_banks:
        raise ValueError(
            "mapping/dump bank mismatch: "
            f"missing_in_dump={sorted(mapping_banks - dump_banks)} "
            f"missing_in_map={sorted(dump_banks - mapping_banks)}"
        )
    empty_banks = sorted(
        bank for bank, section in sections.items() if not section.strip()
    )
    if empty_banks:
        raise ValueError(f"empty bank sections: {empty_banks}")
    payload = runtime_profile_document(
        mapping,
        sections,
        dump_name=args.dump.name,
        bank_versions=bank_versions,
        dump_sha256=hashlib.sha256(dump_bytes).hexdigest(),
    )
    with atomic_text_output(args.output) as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        f"saved={args.output} banks={len(payload['banks'])} "
        f"parsed_dump_banks={len(sections)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
