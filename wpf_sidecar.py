"""NDJSON JSON-RPC bridge for the WPF migration host.

This module intentionally has no Qt imports.  It accepts project schema-v2
snapshots and delegates import/validation/export to the established BDO core.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import traceback
from typing import Any

ROOT = Path(__file__).resolve().parent

from bdo_midi import (  # noqa: E402
    BDO_INSTRUMENT_NAMES,
    Note,
    gm_to_bdo_instrument,
    parse_midi,
)
from bdo_export import channel_groups_to_bdo  # noqa: E402
from bdo_profile import load_bdo_profile  # noqa: E402
from bdo_score import read_bdo_score  # noqa: E402
from bdo_validation import ValidationContext, validate_tracks  # noqa: E402
from bdo_articulation_profiles import PROFILES  # noqa: E402
from optimization import OptimizationIntensity, OptimizerConfig  # noqa: E402
from optimization.plugin_api import tracks_fingerprint  # noqa: E402
from optimization.plugin_host import analyse_with_algorithm, discover_host_algorithms  # noqa: E402
from project_schema import CURRENT_PROJECT_SCHEMA  # noqa: E402

@dataclass(slots=True)
class WorkerTrack:
    track_id: int
    notes: list[Any]
    gm_program: int
    is_percussion: bool
    display_name: str
    bdo_instrument_id: int
    muted: bool = False
    solo: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None
    marnian_synth_mode: str = "basic"
    color: str = "#d88c6f"
    effect_settings_placeholder: dict[str, Any] | None = None
    performance_controls: list[Any] | None = None
    notes_optimized: bool = False
    bdo_track_volume: int = 70
    bdo_track_settings: tuple[int, ...] = (0,) * 8
    bdo_source_group_index: int | None = None
    bdo_source_note_records: tuple[tuple, ...] = ()


def _settings(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("conversion_settings") or {})


def _project_from_midi(midi_path: str) -> dict[str, Any]:
    bpm, time_sig, groups, _tempo_changes = parse_midi(midi_path)
    tracks = []
    for index, (notes, program, percussion) in enumerate(groups, start=1):
        tracks.append({
            "track_id": index,
            "gm_program": int(program),
            "is_percussion": bool(percussion),
            "display_name": f"Track {index}",
            "bdo_instrument_id": int(gm_to_bdo_instrument(program, percussion)),
            "muted": False,
            "solo": False,
            "volume_scale": 1.0,
            "duration_scale": 1.0,
            "articulation_type": None,
            "marnian_synth_mode": "basic",
            "notes_optimized": False,
            "performance_controls": [],
            "bdo_track_volume": 70,
            "bdo_track_settings": [0] * 8,
            "bdo_source_group_index": None,
            "bdo_source_note_records": [],
            "notes": [[n.pitch, n.vel, round(n.start, 3), round(n.dur, 3), n.ntype] for n in notes],
        })
    source = str(Path(midi_path).resolve())
    return {
        "schema_version": CURRENT_PROJECT_SCHEMA,
        "original_midi_path": source,
        "source_midi_path": source,
        "output_name": Path(midi_path).stem,
        "owner_id": 0,
        "char_name": "MIDI",
        "bpm": int(bpm),
        "time_sig": int(time_sig),
        "tempo_changes": [],
        "lyric_events": [],
        "conversion_settings": {
            "transpose": 0, "velocity_mode": "preserve", "reverb": 0, "delay": 0,
            "chorus": None, "bpm_override": None, "vel_range": None, "vel_floor": None,
            "vel_step": None, "apply_sustain": True, "flatten_tempo": False,
        },
        "tracks": tracks,
        "research": {"profile_id": "bdo-global-v9-2026.07", "ab_experiments": []},
    }


def _project_from_bdo(score_path: str) -> dict[str, Any]:
    source_path = Path(score_path).resolve()
    # Game-created scores may append opaque editor metadata after the fully
    # parsed track payload. It is ignored only for read-only library import;
    # structural regression readers remain strict by default.
    snapshot = read_bdo_score(source_path, allow_trailing_data=True)
    grouped: dict[int, list[Any]] = {}
    for track in snapshot.tracks:
        grouped.setdefault(track.group_index, []).append(track)
    tracks = []
    for track_id, chunks in enumerate(grouped.values(), start=1):
        instrument_id = int(chunks[0].instrument_id)
        notes = [note for chunk in chunks for note in chunk.notes]
        notes.sort(key=lambda note: (note.start_ms, note.pitch, note.duration_ms))
        instrument_name = BDO_INSTRUMENT_NAMES.get(instrument_id, f"乐器 0x{instrument_id:02X}")
        tracks.append({
            "track_id": track_id,
            "gm_program": 0,
            "is_percussion": instrument_id == 0x0D,
            "display_name": str(instrument_name),
            "bdo_instrument_id": instrument_id,
            "muted": False,
            "solo": False,
            "volume_scale": 1.0,
            "duration_scale": 1.0,
            "articulation_type": None,
            "marnian_synth_mode": "basic",
            "notes_optimized": False,
            "performance_controls": [],
            "bdo_track_volume": int(chunks[0].volume),
            "bdo_track_settings": list(chunks[0].settings),
            "bdo_source_group_index": int(chunks[0].group_index),
            "bdo_source_note_records": [
                [note.pitch, note.velocity_a, note.start_ms, note.duration_ms, note.ntype, note.velocity_b]
                for chunk in chunks for note in chunk.notes
            ],
            "notes": [[note.pitch, note.velocity_a, round(note.start_ms, 3), round(note.duration_ms, 3), note.ntype] for note in notes],
        })
    return {
        "schema_version": CURRENT_PROJECT_SCHEMA,
        "original_midi_path": "",
        "source_midi_path": "",
        "source_bdo_path": str(source_path),
        "output_name": source_path.name,
        "owner_id": int(snapshot.owner_id),
        "char_name": snapshot.character_name_1 or snapshot.character_name_2 or "BDO",
        "bpm": int(snapshot.bpm),
        "time_sig": int(snapshot.time_signature),
        "tempo_changes": [],
        "lyric_events": [],
        "conversion_settings": {
            "transpose": 0, "velocity_mode": "preserve", "reverb": 0, "delay": 0,
            "chorus": None, "bpm_override": None, "vel_range": None, "vel_floor": None,
            "vel_step": None, "apply_sustain": True, "flatten_tempo": False,
        },
        "tracks": tracks,
        "research": {"profile_id": "bdo-global-v9-2026.07", "ab_experiments": []},
    }


def _tracks(payload: dict[str, Any]) -> list[WorkerTrack]:
    result: list[WorkerTrack] = []
    for raw in payload.get("tracks", []):
        if not isinstance(raw, dict):
            continue
        notes = []
        for value in raw.get("notes", []):
            if not isinstance(value, list) or len(value) < 5:
                continue
            notes.append(Note(int(value[0]), int(value[1]), float(value[2]), float(value[3]), int(value[4])))
        result.append(WorkerTrack(
            track_id=int(raw["track_id"]), notes=notes, gm_program=int(raw.get("gm_program", 0)),
            is_percussion=bool(raw.get("is_percussion", False)), display_name=str(raw.get("display_name", "Track")),
            bdo_instrument_id=int(raw.get("bdo_instrument_id", 0x0B)), muted=bool(raw.get("muted", False)),
            solo=bool(raw.get("solo", False)), volume_scale=float(raw.get("volume_scale", 1.0)),
            duration_scale=float(raw.get("duration_scale", 1.0)),
            articulation_type=int(raw["articulation_type"]) if raw.get("articulation_type") is not None else None,
            marnian_synth_mode=str(raw.get("marnian_synth_mode", "basic")), color=str(raw.get("color", "#d88c6f")),
            effect_settings_placeholder=dict(raw.get("effect_settings_placeholder") or {}),
            performance_controls=list(raw.get("performance_controls") or []), notes_optimized=bool(raw.get("notes_optimized", False)),
            bdo_track_volume=int(raw.get("bdo_track_volume", 70)),
            bdo_track_settings=tuple(int(value) for value in raw.get("bdo_track_settings", [0] * 8)),
            bdo_source_group_index=(int(raw["bdo_source_group_index"]) if raw.get("bdo_source_group_index") is not None else None),
            bdo_source_note_records=tuple(tuple(record) for record in raw.get("bdo_source_note_records", []) if isinstance(record, (list, tuple)) and len(record) >= 6),
        ))
    return result


def _active(tracks: list[WorkerTrack]) -> list[WorkerTrack]:
    solos = [track for track in tracks if track.solo]
    return solos if solos else [track for track in tracks if not track.muted]


def _issues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if int(payload.get("time_sig", 4)) < 1:
        issues.append({"code": "meter.invalid", "severity": "error", "message": "拍号无效"})
    if int(payload.get("time_sig", 4)) != 4:
        issues.append({"code": "meter.unsupported", "severity": "error", "message": "BDO v9 仅支持 /4 拍号"})
    if not int(payload.get("owner_id", 0)):
        issues.append({"code": "owner.missing", "severity": "error", "message": "缺少有效 Owner ID"})
    for track in _active(_tracks(payload)):
        if not 0 <= track.bdo_instrument_id <= 255:
            issues.append({"code": "instrument.invalid", "severity": "error", "message": "乐器 ID 无效", "track_id": track.track_id})
        for index, note in enumerate(track.notes):
            if not 0 <= note.pitch <= 127 or note.dur <= 0:
                issues.append({"code": "note.invalid", "severity": "error", "message": "音符音高或时值无效", "track_id": track.track_id, "note_indices": [index]})
    tracks = _active(_tracks(payload))
    profile = load_bdo_profile(ROOT / "data" / "profiles" / "bdo_global_v9.json")
    settings = _settings(payload)
    context = ValidationContext(
        transpose=int(settings.get("transpose", 0)), active_track_ids=frozenset(track.track_id for track in tracks),
        instrument_names=BDO_INSTRUMENT_NAMES, gm_drum_map={}, serialize_instrument=lambda track: track.bdo_instrument_id,
        velocity_mode=str(settings.get("velocity_mode", "preserve")),
        effects=(int(settings.get("reverb", 0)), int(settings.get("delay", 0)), settings.get("chorus")),
    )
    for issue in validate_tracks(tracks, profile, context):
        issues.append({"code": issue.code, "severity": issue.severity, "message": issue.message,
                       "track_id": issue.track_id, "note_indices": list(issue.note_indices),
                       "evidence": issue.evidence, "evidence_status": issue.evidence_status})
    return issues


def _export(payload: dict[str, Any], out_path: str) -> dict[str, Any]:
    issues = _issues(payload)
    if any(item["severity"] == "error" for item in issues):
        return {"exported": False, "issues": issues}
    tracks = _active(_tracks(payload))
    settings = _settings(payload)
    groups = [([note._replace(dur=max(1.0, note.dur * track.duration_scale)) for note in track.notes], track.gm_program, track.is_percussion) for track in tracks]
    instrument_map = {index: track.bdo_instrument_id for index, track in enumerate(tracks)}
    vel_scales = {index: track.volume_scale for index, track in enumerate(tracks) if track.volume_scale != 1.0}
    articulation_map = {index: track.articulation_type for index, track in enumerate(tracks) if track.articulation_type is not None}
    track_volumes = {index: track.bdo_track_volume for index, track in enumerate(tracks)}
    track_settings_map = {}
    for index, track in enumerate(tracks):
        values = list(track.bdo_track_settings if len(track.bdo_track_settings) == 8 else (0,) * 8)
        values[1] = int(settings.get("reverb", 0))
        values[3] = int(settings.get("delay", 0))
        chorus_values = settings.get("chorus") or (0, 0, 0)
        values[5:8] = [int(value) for value in chorus_values]
        track_settings_map[index] = tuple(values)
    velocity_b_maps = {index: track.bdo_source_note_records for index, track in enumerate(tracks) if track.bdo_source_note_records}
    data, summary = channel_groups_to_bdo(
        int(payload.get("bpm", 120)), int(payload.get("time_sig", 4)), groups,
        bpm_override=settings.get("bpm_override"), char_name=str(payload.get("char_name") or "MIDI"),
        vel_range=settings.get("vel_range") if settings.get("velocity_mode") == "rescale" else None,
        vel_floor=settings.get("vel_floor") if settings.get("velocity_mode") in {"floor", "stepped"} else None,
        vel_step=settings.get("vel_step") if settings.get("velocity_mode") == "stepped" else None,
        vel_layered=settings.get("velocity_mode") == "layered", transpose=int(settings.get("transpose", 0)),
        owner_id=int(payload.get("owner_id", 0)), instrument_map=instrument_map,
        reverb=int(settings.get("reverb", 0)), delay=int(settings.get("delay", 0)), chorus=settings.get("chorus"),
        vel_scales=vel_scales or None, articulation_map=articulation_map or None, preserve_note_types=True,
        track_volumes=track_volumes, track_settings_map=track_settings_map,
        velocity_b_maps=velocity_b_maps or None,
    )
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"exported": True, "path": str(target), "bytes": len(data), "summary": summary, "issues": issues}


def _algorithm_descriptors() -> tuple[list[dict[str, Any]], tuple[Any, ...]]:
    discovery = discover_host_algorithms()
    algorithms = [{
        "algorithm_id": item.algorithm_id,
        "display_name": item.display_name,
        "description": item.description,
        "scopes": list(item.scopes),
        "capabilities": list(item.capabilities),
    } for item in discovery.algorithms]
    return algorithms, discovery.algorithms


def _optimizer_maps() -> tuple[dict[int, frozenset[int]], dict[int, list[tuple[int, str]]], frozenset[int]]:
    profile = load_bdo_profile(ROOT / "data" / "profiles" / "bdo_global_v9.json")
    pitches: dict[int, frozenset[int]] = {}
    articulations: dict[int, list[tuple[int, str]]] = {}
    for instrument_id, rule in profile.instruments.items():
        if rule.allowed_pitches:
            pitches[instrument_id] = rule.allowed_pitches
        elif rule.pitch_min is not None and rule.pitch_max is not None:
            pitches[instrument_id] = frozenset(range(rule.pitch_min, rule.pitch_max + 1))
    for item in PROFILES:
        for instrument_id in item.instrument_ids:
            pair = (int(item.ntype), str(item.technique))
            if pair not in articulations.setdefault(int(instrument_id), []):
                articulations[int(instrument_id)].append(pair)
    articulations[profile.drum_instrument_id] = [(99, "打击乐")]
    return pitches, articulations, frozenset(profile.instruments)


def _materialize_project(payload: dict[str, Any], tracks: list[WorkerTrack], effect: Any) -> dict[str, Any]:
    result = deepcopy(payload)
    raw_by_id = {
        int(item.get("track_id", 0)): item
        for item in result.get("tracks", []) if isinstance(item, dict)
    }
    serialized = []
    for track in tracks:
        raw = deepcopy(raw_by_id.get(track.track_id, {}))
        raw.update({
            "track_id": track.track_id,
            "gm_program": track.gm_program,
            "is_percussion": track.is_percussion,
            "display_name": track.display_name,
            "bdo_instrument_id": track.bdo_instrument_id,
            "muted": track.muted,
            "solo": track.solo,
            "volume_scale": track.volume_scale,
            "duration_scale": track.duration_scale,
            "articulation_type": track.articulation_type,
            "marnian_synth_mode": track.marnian_synth_mode,
            "color": track.color,
            "effect_settings_placeholder": dict(track.effect_settings_placeholder or {}),
            "notes_optimized": True,
            "performance_controls": list(track.performance_controls or []),
            "bdo_track_volume": track.bdo_track_volume,
            "bdo_track_settings": list(track.bdo_track_settings),
            "bdo_source_group_index": track.bdo_source_group_index,
            "bdo_source_note_records": [list(record) for record in track.bdo_source_note_records],
            "notes": [[n.pitch, n.vel, round(n.start, 3), round(n.dur, 3), n.ntype] for n in track.notes],
        })
        serialized.append(raw)
    result["tracks"] = serialized
    if effect is not None:
        settings = result.setdefault("conversion_settings", {})
        settings["reverb"] = int(effect.reverb)
        settings["delay"] = int(effect.delay)
        settings["chorus"] = list(effect.chorus) if effect.chorus is not None else None
    return result


def _optimise_preview(params: dict[str, Any]) -> dict[str, Any]:
    payload = dict(params["project"])
    tracks = _tracks(payload)
    algorithms, descriptors = _algorithm_descriptors()
    requested_id = str(params.get("algorithm_id") or "bdo-safe")
    descriptor = next((item for item in descriptors if item.algorithm_id == requested_id), None)
    if descriptor is None:
        raise ValueError(f"未知优化算法：{requested_id}")
    scope = str(params.get("scope") or "global")
    requested_targets = frozenset(int(item) for item in params.get("target_track_ids", []))
    if scope == "single_track" and not requested_targets:
        raise ValueError("单轨优化必须指定目标轨道")
    target_ids = requested_targets or frozenset(track.track_id for track in tracks)
    pitches, articulations, valid_ids = _optimizer_maps()
    settings = _settings(payload)
    chorus = settings.get("chorus")
    config = OptimizerConfig(
        target_track_ids=target_ids,
        supported_pitches=pitches,
        lyric_events=list(payload.get("lyric_events") or []),
        current_reverb=int(settings.get("reverb", 0)),
        current_delay=int(settings.get("delay", 0)),
        current_chorus=tuple(int(value) for value in chorus) if chorus else None,
        allow_global_effect_write=scope == "global",
    )
    intensity = OptimizationIntensity(str(params.get("intensity") or "balanced"))
    session = analyse_with_algorithm(
        descriptor, tracks, int(payload.get("bpm", 120)), int(payload.get("time_sig", 4)),
        articulations, config, intensity, scope, valid_ids,
    )
    preview_tracks, effect = session.apply(tracks)
    preview_project = _materialize_project(payload, preview_tracks, effect)
    return {
        "source_fingerprint": session.original_fingerprint,
        "algorithm_id": descriptor.algorithm_id,
        "summary": session.preview.summary,
        "details": list(session.preview.details),
        "diagnostics": list(session.preview.diagnostics),
        "operation_count": len(session.preview.operations),
        "changed": bool(session.preview.operations),
        "preview_project": preview_project,
        "algorithms": algorithms,
    }


def _optimise_apply(params: dict[str, Any]) -> dict[str, Any]:
    payload = dict(params["project"])
    preview = dict(params["preview"])
    expected = str(preview.get("source_fingerprint") or "")
    current = tracks_fingerprint(_tracks(payload))
    if not expected or current != expected:
        raise ValueError("工程在分析后已变化，请重新运行优化分析")
    optimized = preview.get("preview_project")
    if not isinstance(optimized, dict):
        raise ValueError("优化预览缺少可应用的工程快照")
    return {"project": deepcopy(optimized), "applied": True}


def dispatch(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "handshake":
        algorithms, _descriptors = _algorithm_descriptors()
        return {"protocol": "ndjson", "capabilities": ["import_midi", "import_bdo", "validate_project", "export_bdo", "optimise_discover", "optimise_preview", "optimise_apply"], "algorithms": algorithms}
    if method == "import_midi":
        return {"project": _project_from_midi(str(params["midi_path"]))}
    if method == "import_bdo":
        return {"project": _project_from_bdo(str(params["score_path"]))}
    if method == "validate_project":
        return {"issues": _issues(dict(params["project"]))}
    if method == "export_bdo":
        return _export(dict(params["project"]), str(params["out_path"]))
    if method == "optimise_discover":
        algorithms, _descriptors = _algorithm_descriptors()
        discovery = discover_host_algorithms()
        return {"algorithms": algorithms, "diagnostics": list(discovery.diagnostics)}
    if method == "optimise_preview":
        return _optimise_preview(params)
    if method == "optimise_apply":
        return _optimise_apply(params)
    raise ValueError(f"unknown method: {method}")


def main() -> int:
    # Pipes are explicitly UTF-8 on both sides so the NDJSON contract does not
    # depend on the user's Windows legacy code page.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            request_id = request.get("id")
            result = dispatch(str(request["method"]), dict(request.get("params") or {}))
            response = {"id": request_id, "result": result}
        except Exception as exc:  # The host receives structured failures, never a broken stream.
            response = {"id": request.get("id") if "request" in locals() else None, "error": {"message": str(exc), "traceback": traceback.format_exc()}}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
