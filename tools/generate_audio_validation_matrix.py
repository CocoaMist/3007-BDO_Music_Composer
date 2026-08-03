#!/usr/bin/env python3
"""Generate the game-capture A/B checklist for BDO real-time playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_midi import BDO_INSTRUMENT_NAMES  # noqa: E402
from bdo_music_composer.audio.bdo_audio_validation import (  # noqa: E402
    VALIDATION_MATRIX_FORMAT,
    validation_matrix_definition_sha256,
)
from bdo_music_composer.audio.bdo_instrument_samples import (  # noqa: E402
    banks_for_instrument,
    effective_sample_root_note,
    preview_route_ntype,
    select_zone_variants,
)
from bdo_music_composer.ui.main_window import BDO_ARTICULATIONS  # noqa: E402
from bdo_music_composer.core.project_paths import WWISE_MIDI_MAP_PATH  # noqa: E402


def _cell_id(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _selection_signature(
    rows: Sequence[dict],
    bank: str,
    pitch: int,
    velocity: int,
    route_ntype: int,
) -> tuple[object, ...] | None:
    variants = select_zone_variants(
        rows,
        pitch,
        velocity,
        route_ntype,
        bank=bank,
    )
    if not variants:
        return None
    first = variants[0]
    group_id = int(
        first.get("selection_group_id")
        or first.get("sound_id")
        or first["source_id"]
    )
    return (
        group_id,
        tuple(sorted(int(row["source_id"]) for row in variants)),
        tuple(sorted(int(row.get("sound_id", 0)) for row in variants)),
        tuple(sorted({int(row["root_note"]) for row in variants})),
        tuple(sorted({effective_sample_root_note(bank, row) for row in variants})),
        max(int(row["velocity_min"]) for row in variants),
        min(int(row["velocity_max"]) for row in variants),
        any(bool(row.get("unmodeled_pitch_rtpc", False)) for row in variants),
    )


def _selection_segments(
    rows: Sequence[dict],
    bank: str,
    velocity: int,
    route_ntype: int,
) -> list[tuple[int, int, tuple[object, ...]]]:
    result: list[tuple[int, int, tuple[object, ...]]] = []
    start = 0
    previous = _selection_signature(rows, bank, 0, velocity, route_ntype)
    for pitch in range(1, 128):
        current = _selection_signature(
            rows,
            bank,
            pitch,
            velocity,
            route_ntype,
        )
        if current == previous:
            continue
        if previous is not None:
            result.append((start, pitch - 1, previous))
        start = pitch
        previous = current
    if previous is not None:
        result.append((start, 127, previous))
    return result


def _probe_points(key_min: int, key_max: int) -> tuple[tuple[int, str], ...]:
    roles: dict[int, list[str]] = {}
    for pitch, role in (
        (key_min, "low"),
        ((key_min + key_max) // 2, "mid"),
        (key_max, "high"),
    ):
        roles.setdefault(pitch, []).append(role)
    return tuple(
        (pitch, "+".join(labels))
        for pitch, labels in sorted(roles.items())
    )


def build_validation_matrix(
    mapping: Mapping[str, object],
    instrument_names: Mapping[int, str],
    articulations: Mapping[int, Sequence[tuple[int, str]]],
) -> dict[str, object]:
    """Build probes from the source groups the runtime actually selects."""

    evidence_hash = str(mapping.get("evidence_sha256", ""))
    raw_banks = mapping.get("banks", {})
    banks = raw_banks if isinstance(raw_banks, Mapping) else {}
    cells: list[dict[str, object]] = []
    unmapped: list[dict[str, object]] = []

    for instrument_id, name in sorted(instrument_names.items()):
        definitions = articulations.get(instrument_id, ((0, "默认"),))
        instrument_banks = banks_for_instrument(instrument_id)
        if not instrument_banks:
            unmapped.append({
                "instrument_id": instrument_id,
                "instrument": name,
                "reason": "no_named_bank",
            })
            continue
        for bank in instrument_banks:
            rows = banks.get(bank, ())
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                rows = ()
            synth_mode = (
                bank.rsplit("_", 1)[-1]
                if "_synth_" in bank
                else "basic"
            )
            for requested_ntype, _label in definitions:
                route_ntype = preview_route_ntype(
                    instrument_id,
                    requested_ntype,
                )
                route_rows = [
                    row
                    for row in rows
                    if route_ntype
                    in {int(value) for value in row.get("route_ntypes", ())}
                ]
                if not route_rows:
                    unmapped.append({
                        "instrument_id": instrument_id,
                        "instrument": name,
                        "bank": bank,
                        "synth_mode": synth_mode,
                        "requested_ntype": requested_ntype,
                        "route_ntype": route_ntype,
                        "reason": "no_route_rows",
                    })
                    continue
                velocity_probes = sorted({
                    round(
                        (
                            int(row["velocity_min"])
                            + int(row["velocity_max"])
                        )
                        / 2
                    )
                    for row in route_rows
                })
                for velocity in velocity_probes:
                    for key_min, key_max, signature in _selection_segments(
                        rows,
                        bank,
                        velocity,
                        route_ntype,
                    ):
                        (
                            group_id,
                            source_ids,
                            sound_ids,
                            authored_roots,
                            effective_roots,
                            velocity_min,
                            velocity_max,
                            unmodeled_pitch_rtpc,
                        ) = signature
                        for pitch, probe_role in _probe_points(key_min, key_max):
                            identity = {
                                "mapping_evidence_sha256": evidence_hash,
                                "instrument_id": instrument_id,
                                "bank": bank,
                                "synth_mode": synth_mode,
                                "requested_ntype": int(requested_ntype),
                                "route_ntype": route_ntype,
                                "selection_group_id": group_id,
                                "source_ids": source_ids,
                                "key_min": key_min,
                                "key_max": key_max,
                                "velocity_min": velocity_min,
                                "velocity_max": velocity_max,
                                "pitch": pitch,
                            }
                            cells.append({
                                "cell_id": _cell_id(identity),
                                **identity,
                                "instrument": name,
                                "source_id": source_ids[0],
                                "sound_ids": list(sound_ids),
                                "authored_root_notes": list(authored_roots),
                                "effective_root_notes": list(effective_roots),
                                "unmodeled_pitch_rtpc": unmodeled_pitch_rtpc,
                                "velocity": velocity,
                                "ntype": int(requested_ntype),
                                "probe_role": probe_role,
                                "selection_valid": not unmodeled_pitch_rtpc,
                                "capture_path": None,
                                "onset_frames": None,
                                "pitch_cents": None,
                                "loudness_lufs": None,
                                "spectral_distance": None,
                                "listener_pass": None,
                                "verification": "pending",
                            })

    payload: dict[str, object] = {
        "format": VALIDATION_MATRIX_FORMAT,
        "mapping_evidence_sha256": evidence_hash,
        "selection_basis": "runtime_route_key_velocity_group",
        "required_probe_roles": ["low", "mid", "high"],
        "cells": cells,
        "unmapped": unmapped,
    }
    payload["matrix_definition_sha256"] = (
        validation_matrix_definition_sha256(payload)
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=WWISE_MIDI_MAP_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "out" / "bdo_audio_validation_matrix.json")
    args = parser.parse_args()
    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    payload = build_validation_matrix(
        mapping,
        BDO_INSTRUMENT_NAMES,
        BDO_ARTICULATIONS,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"saved={args.output} cells={len(payload['cells'])} "
        f"unmapped={len(payload['unmapped'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
