#!/usr/bin/env python3
"""Recover Wwise MIDI note/velocity ranges from a wwiser text dump."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    node_id: int
    node_type: str
    parent_id: int | None
    source_id: int | None
    props: dict[str, int] = field(default_factory=dict)
    avoid_repeat: int = 0
    selection_mode: str = "single"
    target_id: int | None = None
    action_ids: tuple[int, ...] = ()
    pitch_cents: float = 0.0
    pitch_random_min_cents: float = 0.0
    pitch_random_max_cents: float = 0.0
    volume_db: float = 0.0
    makeup_gain_db: float = 0.0
    playlist_ids: tuple[int, ...] = ()
    playlist_weights: tuple[int, ...] = ()
    container_loop_count: int | None = None
    continuous: bool = False
    global_scope: bool = False
    reset_playlist_each_play: bool = False
    max_instances: int | None = None
    kill_newest: bool = False
    ignore_parent_max_instances: bool = False
    instance_limit_global: bool = False
    use_virtual_behavior: bool = False
    sound_loop_count: int | None = None
    midi_break_loop_on_note_off: bool = False
    volume_envelope_modulator_ids: tuple[int, ...] = ()
    envelope_release_ms: float | None = None


@dataclass(frozen=True)
class EventRoute:
    event_id: int
    target_id: int
    ntype: int


@dataclass(frozen=True)
class SampleLoop:
    """One standard RIFF ``smpl`` loop, with an exclusive end frame."""

    start_frame: int
    end_frame: int
    play_count: int


BANK_START = re.compile(
    r"^\s*bank v(?P<version>\d+)\s+"
    r"(?P<bank>midi_instrument_[^\s]+\.bnk)\s*$",
    re.MULTILINE,
)
SUPPORTED_BANK_VERSIONS = frozenset({145})
OBJECT = re.compile(
    r"^\s+obj\s+(?P<type>CAk\w+)\[\d+\](?P<body>.*?)(?=^\s+obj\s+CAk\w+\[\d+\]|\Z)",
    re.MULTILINE | re.DOTALL,
)
VALUE = re.compile(
    r"\[(?P<name>MidiTrackingRootNote|MidiKeyRangeMin|MidiKeyRangeMax|MidiVelocityRangeMin|MidiVelocityRangeMax)\]"
    r"\s*\n.*?pValue = (?P<value>-?\d+)",
    re.DOTALL,
)
RANGED_PITCH = re.compile(
    r"\bpID = [^\n]*\[Pitch\]\s*\n"
    r"[^\n]*\bmin = (?P<min>-?\d+(?:\.\d+)?)\s*\n"
    r"[^\n]*\bmax = (?P<max>-?\d+(?:\.\d+)?)"
)
RTPC_OBJECT = re.compile(
    r"^\s+obj\s+RTPC\[\d+\](?P<body>.*?)"
    r"(?=^\s+obj\s+RTPC\[\d+\]|^\s+obj\s+Children\b|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _static_property(body: str, name: str) -> float | None:
    match = re.search(
        rf"\bpID = [^\n]*\[{re.escape(name)}\]\s*\n"
        r"[^\n]*\bpValue = (?P<value>-?\d+(?:\.\d+)?)",
        body,
    )
    return float(match.group("value")) if match else None


def _bool_field(body: str, name: str) -> bool:
    match = re.search(rf"\b{re.escape(name)} = ([01])\b", body)
    return bool(int(match.group(1))) if match else False


def _volume_envelope_modulator_ids(body: str) -> tuple[int, ...]:
    result: list[int] = []
    for match in RTPC_OBJECT.finditer(body):
        rtpc_body = match.group("body")
        if not re.search(r"\brtpcType = [^\n]*\[Modulator\]", rtpc_body):
            continue
        if not re.search(r"\bParamID = [^\n]*\[Volume\]", rtpc_body):
            continue
        id_match = re.search(r"\bRTPCID = (\d+)", rtpc_body)
        if id_match:
            result.append(int(id_match.group(1)))
    return tuple(dict.fromkeys(result))


def _advanced_settings_bits(body: str) -> int:
    settings = re.search(
        r"\bobj\s+AdvSettingsParams\b(?P<body>.*?)"
        r"(?=^\s+obj\s+StateChunk\b|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if not settings:
        return 0
    bits = re.search(
        r"\bbyBitVector = 0x(?P<value>[0-9A-Fa-f]+)",
        settings.group("body"),
    )
    return int(bits.group("value"), 16) if bits else 0


def parse_nodes(section: str) -> dict[int, Node]:
    nodes: dict[int, Node] = {}
    for match in OBJECT.finditer(section):
        body = match.group("body")
        id_match = re.search(r"\bulID = (\d+)", body)
        if not id_match:
            continue
        source_match = re.search(r"\bsourceID = (\d+)", body)
        parent_match = re.search(r"\bDirectParentID = (\d+)", body)
        avoid_repeat_match = re.search(r"\bwAvoidRepeatCount = (\d+)", body)
        selection_mode_match = re.search(
            r"\beMode = [^\n]*\[(Random|Sequence)\]",
            body,
        )
        target_match = re.search(r"\bidExt = (\d+)", body)
        pitch_value = _static_property(body, "Pitch")
        volume_value = _static_property(body, "Volume")
        makeup_gain_value = _static_property(body, "MakeUpGain")
        sound_loop_value = _static_property(body, "Loop")
        envelope_release = _static_property(body, "Envelope_ReleaseTime")
        ranged_pitch_match = RANGED_PITCH.search(body)
        container_loop_match = re.search(r"\bsLoopCount = (\d+)", body)
        max_instances_match = re.search(r"\bu16MaxNumInstance = (\d+)", body)
        playlist_ids = tuple(
            int(value)
            for value in re.findall(r"\bulPlayID = (\d+)", body)
        )
        playlist_weights = tuple(
            int(value)
            for value in re.findall(r"\bweight = (-?\d+)", body)
        )
        advanced_settings_bits = _advanced_settings_bits(body)
        node = Node(
            node_id=int(id_match.group(1)),
            node_type=match.group("type"),
            parent_id=int(parent_match.group(1)) if parent_match and parent_match.group(1) != "0" else None,
            source_id=int(source_match.group(1)) if source_match else None,
            props={item.group("name"): int(item.group("value")) for item in VALUE.finditer(body)},
            avoid_repeat=(
                int(avoid_repeat_match.group(1))
                if avoid_repeat_match
                else 0
            ),
            selection_mode=(
                selection_mode_match.group(1).lower()
                if selection_mode_match
                else "single"
            ),
            target_id=int(target_match.group(1)) if target_match else None,
            action_ids=tuple(
                int(value)
                for value in re.findall(r"\bulActionID = (\d+)", body)
            ),
            pitch_cents=(
                pitch_value if pitch_value is not None else 0.0
            ),
            volume_db=(
                volume_value if volume_value is not None else 0.0
            ),
            makeup_gain_db=(
                makeup_gain_value
                if makeup_gain_value is not None
                else 0.0
            ),
            pitch_random_min_cents=(
                float(ranged_pitch_match.group("min"))
                if ranged_pitch_match
                else 0.0
            ),
            pitch_random_max_cents=(
                float(ranged_pitch_match.group("max"))
                if ranged_pitch_match
                else 0.0
            ),
            playlist_ids=playlist_ids,
            playlist_weights=playlist_weights,
            container_loop_count=(
                int(container_loop_match.group(1))
                if container_loop_match
                else None
            ),
            continuous=_bool_field(body, "bIsContinuous"),
            global_scope=_bool_field(body, "bIsGlobal"),
            reset_playlist_each_play=_bool_field(
                body,
                "bResetPlayListAtEachPlay",
            ),
            max_instances=(
                int(max_instances_match.group(1))
                if max_instances_match
                else None
            ),
            kill_newest=_bool_field(body, "bKillNewest"),
            ignore_parent_max_instances=_bool_field(
                body,
                "bIgnoreParentMaxNumInst",
            ),
            # v90+ packs the former bIsGlobalLimit into bit 2.  wwiser
            # leaves that bit unnamed in its text view.
            instance_limit_global=bool(advanced_settings_bits & 0x04),
            use_virtual_behavior=bool(advanced_settings_bits & 0x02),
            sound_loop_count=(
                int(sound_loop_value)
                if sound_loop_value is not None
                and sound_loop_value.is_integer()
                else None
            ),
            midi_break_loop_on_note_off=_bool_field(
                body,
                "bIsMidiBreakLoopOnNoteOff",
            ),
            volume_envelope_modulator_ids=(
                _volume_envelope_modulator_ids(body)
            ),
            envelope_release_ms=(
                envelope_release * 1000.0
                if match.group("type") == "CAkEnvelopeModulator"
                and envelope_release is not None
                else None
            ),
        )
        nodes[node.node_id] = node
    return nodes


def effective_props(node: Node, nodes: dict[int, Node]) -> dict[str, int | None]:
    root_note: int | None = None
    key_min = 0
    key_max = 127
    velocity_min = 0
    velocity_max = 127
    seen: set[int] = set()
    current: Node | None = node
    while current and current.node_id not in seen:
        seen.add(current.node_id)
        if root_note is None and "MidiTrackingRootNote" in current.props:
            root_note = current.props["MidiTrackingRootNote"]
        if "MidiKeyRangeMin" in current.props:
            key_min = max(key_min, current.props["MidiKeyRangeMin"])
        if "MidiKeyRangeMax" in current.props:
            key_max = min(key_max, current.props["MidiKeyRangeMax"])
        if "MidiVelocityRangeMin" in current.props:
            velocity_min = max(
                velocity_min,
                current.props["MidiVelocityRangeMin"],
            )
        if "MidiVelocityRangeMax" in current.props:
            velocity_max = min(
                velocity_max,
                current.props["MidiVelocityRangeMax"],
            )
        current = nodes.get(current.parent_id) if current.parent_id else None
    if key_min > key_max or velocity_min > velocity_max:
        raise ValueError(
            f"empty inherited MIDI range for HIRC node {node.node_id}"
        )
    if root_note is None:
        root_note = (key_min + key_max) // 2
    return {
        "MidiTrackingRootNote": root_note,
        "MidiKeyRangeMin": key_min,
        "MidiKeyRangeMax": key_max,
        "MidiVelocityRangeMin": velocity_min,
        "MidiVelocityRangeMax": velocity_max,
    }


def ancestors(node: Node, nodes: dict[int, Node]) -> tuple[Node, ...]:
    result: list[Node] = []
    seen: set[int] = set()
    current: Node | None = node
    while current and current.node_id not in seen:
        seen.add(current.node_id)
        result.append(current)
        current = nodes.get(current.parent_id) if current.parent_id else None
    return tuple(result)


def wwise_fnv1(name: str) -> int:
    """Return the case-insensitive Wwise short ID for an object name."""

    value = 2166136261
    for byte in name.lower().encode("utf-8"):
        value = ((value * 16777619) & 0xFFFFFFFF) ^ byte
    return value


def _event_name(bank: str, ntype: int) -> str:
    suffix = f"{ntype:02d}" if ntype < 10 else str(ntype)
    return f"{bank}_{suffix}"


def recover_event_routes(
    bank: str,
    nodes: dict[int, Node],
    *,
    max_ntype: int = 99,
) -> tuple[EventRoute, ...]:
    """Recover articulation routes from hashed Event names and play Actions.

    The event short ID is evidence carried by the bank itself.  Recomputing it
    avoids a second hand-maintained table that can swap articulations or omit
    newly added banks.
    """

    routes: list[EventRoute] = []
    seen_event_ids: dict[int, int] = {}
    for ntype in range(max_ntype + 1):
        event_id = wwise_fnv1(_event_name(bank, ntype))
        previous = seen_event_ids.setdefault(event_id, ntype)
        if previous != ntype:
            raise ValueError(
                f"Wwise event hash collision for ntypes {previous} and {ntype}"
            )
        event = nodes.get(event_id)
        if event is None:
            continue
        if event.node_type != "CAkEvent":
            raise ValueError(
                f"{bank}: expected event {event_id}, found {event.node_type}"
            )
        targets: set[int] = set()
        for action_id in event.action_ids:
            action = nodes.get(action_id)
            if (
                action is not None
                and action.node_type == "CAkActionPlay"
                and action.target_id is not None
            ):
                targets.add(action.target_id)
        if not targets:
            raise ValueError(
                f"{bank}: event {event_id} ({_event_name(bank, ntype)}) "
                "has no ActionPlay target"
            )
        missing_targets = sorted(targets - set(nodes))
        if missing_targets:
            raise ValueError(
                f"{bank}: event {event_id} targets missing HIRC nodes "
                f"{missing_targets}"
            )
        routes.extend(
            EventRoute(event_id, target_id, ntype)
            for target_id in sorted(targets)
        )
    return tuple(
        sorted(
            set(routes),
            key=lambda route: (
                route.target_id,
                route.ntype,
                route.event_id,
            ),
        )
    )


def lineage_volume_db(lineage: tuple[Node, ...]) -> float:
    """Combine static Volume and MakeUpGain along the inherited parent path."""

    return sum(
        item.volume_db + item.makeup_gain_db
        for item in lineage
    )


def lineage_release_ms(
    lineage: tuple[Node, ...],
    nodes: dict[int, Node],
) -> float | None:
    """Resolve an unambiguous Volume Envelope Modulator note-off release.

    Multiple different releases cannot be represented faithfully by one row,
    so the mapper deliberately leaves that case unknown instead of guessing.
    """

    modulator_ids = tuple(
        dict.fromkeys(
            modulator_id
            for item in lineage
            for modulator_id in item.volume_envelope_modulator_ids
        )
    )
    if not modulator_ids:
        return None
    releases: list[float] = []
    for modulator_id in modulator_ids:
        modulator = nodes.get(modulator_id)
        if (
            modulator is None
            or modulator.node_type != "CAkEnvelopeModulator"
            or modulator.envelope_release_ms is None
        ):
            return None
        releases.append(modulator.envelope_release_ms)
    first = releases[0]
    if any(abs(value - first) > 1e-6 for value in releases[1:]):
        return None
    return first


def selection_metadata(
    lineage: tuple[Node, ...],
) -> dict[str, object]:
    selection_group = next(
        (
            item
            for item in lineage
            if item.node_type == "CAkRanSeqCntr"
        ),
        None,
    )
    if selection_group is None:
        return {
            "selection_group_id": lineage[0].node_id,
            "selection_mode": "single",
            "avoid_repeat": 0,
            "playlist_index": None,
            "playlist_order": [],
            "playlist_weight": None,
            "container_loop_count": None,
            "selection_continuous": False,
            "selection_global": False,
            "selection_reset_playlist": False,
            "selection_max_instances": None,
            "selection_kill_newest": False,
        }

    container_index = lineage.index(selection_group)
    direct_child_id = (
        lineage[container_index - 1].node_id
        if container_index > 0
        else None
    )
    try:
        playlist_index = selection_group.playlist_ids.index(
            direct_child_id
        )
    except ValueError:
        playlist_index = None
    playlist_weight = (
        selection_group.playlist_weights[playlist_index]
        if playlist_index is not None
        and playlist_index < len(selection_group.playlist_weights)
        else None
    )
    return {
        "selection_group_id": selection_group.node_id,
        "selection_mode": selection_group.selection_mode,
        "avoid_repeat": selection_group.avoid_repeat,
        "playlist_index": playlist_index,
        "playlist_order": list(selection_group.playlist_ids),
        "playlist_weight": playlist_weight,
        "container_loop_count": selection_group.container_loop_count,
        "selection_continuous": selection_group.continuous,
        "selection_global": selection_group.global_scope,
        "selection_reset_playlist": (
            selection_group.reset_playlist_each_play
        ),
        "selection_max_instances": selection_group.max_instances,
        "selection_kill_newest": selection_group.kill_newest,
    }


def instance_limit_metadata(
    lineage: tuple[Node, ...],
) -> dict[str, object]:
    """Resolve node-level Wwise instance limits on one Sound lineage.

    A node with ``bIgnoreParentMaxNumInst`` cuts off limits above it.  The
    current instrument banks have at most one surviving limit per Sound.  If a
    future bank carries nested limits, keep the full evidence but leave the
    scalar runtime fields disabled rather than pretending one limit represents
    both groups.
    """

    limiting_nodes: list[Node] = []
    for item in lineage:
        if item.max_instances is not None and item.max_instances > 0:
            limiting_nodes.append(item)
        if item.ignore_parent_max_instances:
            break
    limits = [
        {
            "group_id": item.node_id,
            "max_instances": item.max_instances,
            "kill_newest": item.kill_newest,
            "global_scope": item.instance_limit_global,
            "use_virtual_behavior": item.use_virtual_behavior,
        }
        for item in limiting_nodes
    ]
    resolved = limiting_nodes[0] if len(limiting_nodes) == 1 else None
    return {
        "instance_group_id": (
            resolved.node_id if resolved is not None else None
        ),
        "max_instances": (
            resolved.max_instances if resolved is not None else 0
        ),
        "kill_newest": (
            resolved.kill_newest if resolved is not None else False
        ),
        "instance_limit_global": (
            resolved.instance_limit_global
            if resolved is not None
            else False
        ),
        "instance_use_virtual_behavior": (
            resolved.use_virtual_behavior
            if resolved is not None
            else False
        ),
        "instance_limits": limits,
    }


def read_wem_sample_loops(path: Path) -> tuple[SampleLoop, ...]:
    """Read standard RIFF ``smpl`` loop metadata without decoding audio."""

    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[8:12] != b"WAVE":
            raise ValueError(f"{path}: not a RIFF WAVE file")
        if header[:4] == b"RIFF":
            endian = "<"
        elif header[:4] == b"RIFX":
            endian = ">"
        else:
            raise ValueError(f"{path}: unsupported RIFF signature")

        while True:
            chunk_header = stream.read(8)
            if not chunk_header:
                return ()
            if len(chunk_header) != 8:
                raise ValueError(f"{path}: truncated RIFF chunk header")
            chunk_id = chunk_header[:4]
            chunk_size = struct.unpack(
                f"{endian}I",
                chunk_header[4:],
            )[0]
            if chunk_id != b"smpl":
                stream.seek(chunk_size + (chunk_size & 1), 1)
                continue
            payload = stream.read(chunk_size)
            if len(payload) != chunk_size or chunk_size < 36:
                raise ValueError(f"{path}: truncated smpl chunk")
            sample_loop_count = struct.unpack_from(
                f"{endian}I",
                payload,
                28,
            )[0]
            required_size = 36 + sample_loop_count * 24
            if required_size > len(payload):
                raise ValueError(f"{path}: truncated smpl loop table")
            loops: list[SampleLoop] = []
            for index in range(sample_loop_count):
                offset = 36 + index * 24
                _, _, start, inclusive_end, _, play_count = (
                    struct.unpack_from(
                        f"{endian}6I",
                        payload,
                        offset,
                    )
                )
                if inclusive_end < start:
                    raise ValueError(
                        f"{path}: invalid smpl loop {index}"
                    )
                loops.append(
                    SampleLoop(
                        start_frame=start,
                        end_frame=inclusive_end + 1,
                        play_count=play_count,
                    )
                )
            return tuple(loops)


def portable_media_path(bank: str, source_id: int, suffix: str) -> str:
    return f"{bank}/{source_id}.{suffix}"


def atomic_write_text(path: Path, text: str) -> None:
    """Replace one generated artifact only after a complete durable write."""

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
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def mapping_document(
    by_bank: dict[str, list[dict[str, object]]],
    *,
    bank_versions: set[int] | frozenset[int] | tuple[int, ...] = (),
    dump_sha256: str | None = None,
    evidence_sha256: str | None = None,
) -> dict[str, object]:
    """Build the additive v2 document consumed by existing sample loaders."""

    versions = sorted({int(value) for value in bank_versions})
    return {
        "format": 2,
        "wwise_bank_version": versions[0] if len(versions) == 1 else None,
        "wwise_bank_versions": versions,
        "source_dump_sha256": dump_sha256,
        "evidence_sha256": evidence_sha256,
        "selection_order": [
            "event_route",
            "key_velocity_zone",
            "random_sequence_container",
        ],
        "loop_end_frame_semantics": "exclusive",
        "banks": by_bank,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Map Wwise MIDI tracking data to extracted WEM files")
    parser.add_argument("dump", type=Path, help="wwiser combined text dump")
    parser.add_argument("wem_root", type=Path, help="Root directory containing <bank>/<source_id>.wem")
    parser.add_argument("--wav-root", type=Path, help="Optional root directory containing decoded WAV files")
    parser.add_argument(
        "--portable-paths",
        dest="portable_paths",
        action="store_true",
        default=True,
        help="Write bank-relative media paths while checking files under the supplied roots",
    )
    parser.add_argument(
        "--absolute-paths",
        dest="portable_paths",
        action="store_false",
        help="Development-only: write machine-local absolute media paths.",
    )
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    dump_bytes = args.dump.read_bytes()
    text = dump_bytes.decode("utf-8")
    starts = list(BANK_START.finditer(text))
    rows = []
    mapping_errors: list[str] = []
    if not starts:
        mapping_errors.append("no midi_instrument bank sections found")
    bank_versions = {
        int(start.group("version")) for start in starts
    }
    unsupported_versions = sorted(
        bank_versions - SUPPORTED_BANK_VERSIONS
    )
    if unsupported_versions:
        mapping_errors.append(
            "unsupported Wwise bank versions: "
            f"{unsupported_versions}; supported={sorted(SUPPORTED_BANK_VERSIONS)}"
        )
    seen_banks: set[str] = set()
    loop_cache: dict[Path, tuple[SampleLoop, ...]] = {}
    for index, start in enumerate(starts):
        bank_filename = start.group("bank")
        bank = Path(bank_filename).stem
        if bank in seen_banks:
            mapping_errors.append(f"duplicate bank section: {bank}")
            continue
        seen_banks.add(bank)
        section = text[start.end():starts[index + 1].start() if index + 1 < len(starts) else len(text)]
        nodes = parse_nodes(section)
        try:
            routes = recover_event_routes(bank, nodes)
        except ValueError as error:
            mapping_errors.append(str(error))
            routes = ()
        if not routes:
            mapping_errors.append(f"{bank}: no hashed articulation events found")
        route_by_target: dict[int, list[EventRoute]] = {}
        for route in routes:
            route_by_target.setdefault(route.target_id, []).append(route)
        for node in nodes.values():
            if node.node_type != "CAkSound" or node.source_id is None:
                continue
            try:
                props = effective_props(node, nodes)
            except ValueError as error:
                mapping_errors.append(f"{bank}: {error}")
                continue
            wem_path = args.wem_root / bank / f"{node.source_id}.wem"
            wav_path = args.wav_root / bank / f"{node.source_id}.wav" if args.wav_root else None
            lineage = ancestors(node, nodes)
            route_target = next(
                (
                    ancestor
                    for ancestor in lineage
                    if ancestor.node_id in route_by_target
                ),
                None,
            )
            node_routes = (
                route_by_target[route_target.node_id]
                if route_target is not None
                else []
            )
            if route_target is None:
                mapping_errors.append(
                    f"{bank}: sound {node.node_id} has no Event route"
                )
            selection = selection_metadata(lineage)
            instance_limit = instance_limit_metadata(lineage)
            if len(instance_limit["instance_limits"]) > 1:
                mapping_errors.append(
                    f"{bank}: sound {node.node_id} has nested instance "
                    "limits that cannot use the scalar runtime fields"
                )
            pitch_cents = sum(ancestor.pitch_cents for ancestor in lineage)
            pitch_random_min = sum(
                ancestor.pitch_random_min_cents for ancestor in lineage
            )
            pitch_random_max = sum(
                ancestor.pitch_random_max_cents for ancestor in lineage
            )
            makeup_gain_db = sum(
                ancestor.makeup_gain_db for ancestor in lineage
            )
            sample_loops: tuple[SampleLoop, ...] = ()
            if wem_path.is_file():
                if wem_path not in loop_cache:
                    try:
                        loop_cache[wem_path] = read_wem_sample_loops(
                            wem_path
                        )
                    except (OSError, ValueError) as error:
                        mapping_errors.append(str(error))
                        loop_cache[wem_path] = ()
                sample_loops = loop_cache[wem_path]
            if node.sound_loop_count == 0 and not sample_loops:
                mapping_errors.append(
                    f"{bank}: looping sound {node.node_id} / "
                    f"{node.source_id}.wem has no smpl loop"
                )
            scalar_loop = sample_loops[0] if len(sample_loops) == 1 else None
            row = {
                "bank": bank,
                "sound_id": node.node_id,
                "source_id": node.source_id,
                "root_note": props["MidiTrackingRootNote"],
                "key_min": props["MidiKeyRangeMin"],
                "key_max": props["MidiKeyRangeMax"],
                "velocity_min": props["MidiVelocityRangeMin"],
                "velocity_max": props["MidiVelocityRangeMax"],
                "route_ntypes": [
                    route.ntype for route in node_routes
                ],
                "route_event_ids": [
                    route.event_id for route in node_routes
                ],
                "route_target_id": (
                    route_target.node_id
                    if route_target is not None
                    else None
                ),
                "pitch_cents": pitch_cents,
                "pitch_random_min_cents": pitch_random_min,
                "pitch_random_max_cents": pitch_random_max,
                "makeup_gain_db": makeup_gain_db,
                "volume_db": lineage_volume_db(lineage),
                "release_ms": lineage_release_ms(lineage, nodes),
                "sound_loop_count": node.sound_loop_count,
                "midi_break_loop_on_note_off": (
                    node.midi_break_loop_on_note_off
                ),
                "sample_loops": len(sample_loops),
                "loop_start_frame": (
                    scalar_loop.start_frame
                    if scalar_loop is not None
                    else None
                ),
                "loop_end_frame": (
                    scalar_loop.end_frame
                    if scalar_loop is not None
                    else None
                ),
                "loop_play_count": (
                    scalar_loop.play_count
                    if scalar_loop is not None
                    else None
                ),
                "sample_loop_regions": [
                    {
                        "start_frame": loop.start_frame,
                        "end_frame": loop.end_frame,
                        "play_count": loop.play_count,
                    }
                    for loop in sample_loops
                ],
                "wem_path": (
                    portable_media_path(bank, node.source_id, "wem")
                    if args.portable_paths
                    else str(wem_path)
                ),
                "wem_exists": wem_path.is_file(),
                "wav_path": (
                    portable_media_path(bank, node.source_id, "wav")
                    if wav_path and args.portable_paths
                    else str(wav_path) if wav_path else ""
                ),
                "wav_exists": wav_path.is_file() if wav_path else False,
            }
            row.update(selection)
            row.update(instance_limit)
            rows.append(row)

    rows.sort(key=lambda row: (row["bank"], row["key_min"], row["velocity_min"], row["source_id"]))
    found_wem = sum(row["wem_exists"] for row in rows)
    found_wav = sum(row["wav_exists"] for row in rows) if args.wav_root else 0
    print(f"Mapped {len(rows)} sound nodes; WEM {found_wem}/{len(rows)}; WAV {found_wav}/{len(rows)}")
    if found_wem != len(rows):
        mapping_errors.append(
            f"missing {len(rows) - found_wem} mapped WEM files"
        )
    if args.wav_root and found_wav != len(rows):
        mapping_errors.append(
            f"missing {len(rows) - found_wav} mapped WAV files"
        )
    if args.tsv.resolve() == args.json.resolve():
        mapping_errors.append("TSV and JSON outputs must be different files")
    for warning in mapping_errors:
        print(f"Mapping evidence error: {warning}")
    if mapping_errors:
        return 1

    semantic_rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"wem_path", "wav_path"}
        }
        for row in rows
    ]
    evidence_sha256 = hashlib.sha256(
        json.dumps(
            {
                "bank_versions": sorted(bank_versions),
                "rows": semantic_rows,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    for row in rows:
        row["evidence_sha256"] = evidence_sha256

    fields = [
        "evidence_sha256",
        "bank", "sound_id", "source_id", "root_note", "key_min", "key_max",
        "velocity_min", "velocity_max", "route_ntypes", "route_event_ids",
        "route_target_id", "selection_group_id", "selection_mode",
        "avoid_repeat", "playlist_index", "playlist_order",
        "playlist_weight", "container_loop_count",
        "selection_continuous", "selection_global",
        "selection_reset_playlist", "selection_max_instances",
        "selection_kill_newest",
        "instance_group_id", "max_instances", "kill_newest",
        "instance_limit_global", "instance_use_virtual_behavior",
        "instance_limits",
        "pitch_cents", "pitch_random_min_cents",
        "pitch_random_max_cents", "makeup_gain_db", "volume_db",
        "release_ms", "sound_loop_count",
        "midi_break_loop_on_note_off", "sample_loops",
        "loop_start_frame", "loop_end_frame", "loop_play_count",
        "sample_loop_regions",
        "wem_exists", "wav_exists", "wem_path", "wav_path",
    ]
    by_bank: dict[str, list[dict]] = {}
    for row in rows:
        by_bank.setdefault(row["bank"], []).append(row)

    tsv_output = io.StringIO(newline="")
    writer = csv.DictWriter(
        tsv_output,
        fieldnames=fields,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    json_output = json.dumps(
        mapping_document(
            by_bank,
            bank_versions=bank_versions,
            dump_sha256=hashlib.sha256(dump_bytes).hexdigest(),
            evidence_sha256=evidence_sha256,
        ),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    atomic_write_text(args.json, json_output)
    atomic_write_text(args.tsv, tsv_output.getvalue())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
