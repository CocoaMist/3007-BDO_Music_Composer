"""Immutable autosave snapshots and background-safe project serialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import uuid

from atomic_io import atomic_copy_file, atomic_write_json


PROJECT_INDEX_NAME = "project.index.json"
_PROJECT_ID_NAMESPACE = uuid.UUID("f6b6ffb5-c43f-4d7f-a4cc-1fc0f460be98")


def normalize_project_id(value: object) -> str:
    """Return one canonical UUID string or an empty value for invalid input."""

    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        return ""


def new_project_id() -> str:
    return str(uuid.uuid4())


def project_id_for_path(project_dir: Path) -> str:
    """Create a stable legacy identity until the next save persists a UUID."""

    try:
        identity_path = str(Path(project_dir).resolve()).casefold()
    except OSError:
        identity_path = str(Path(project_dir).absolute()).casefold()
    return str(uuid.uuid5(_PROJECT_ID_NAMESPACE, identity_path))


@dataclass(frozen=True, slots=True)
class ProjectTrackSnapshot:
    values: Mapping[str, Any]
    notes: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class AutosaveRequest:
    project_dir: Path
    metadata: Mapping[str, Any]
    tracks: tuple[ProjectTrackSnapshot, ...]
    saved_at: str
    reason: str
    source_path: Path | None = None
    source_copy: Path | None = None


def freeze_project_tracks(
    tracks: Sequence[object],
) -> tuple[ProjectTrackSnapshot, ...]:
    return tuple(
        ProjectTrackSnapshot(
            values={
                "track_id": int(getattr(track, "track_id")),
                "gm_program": int(getattr(track, "gm_program")),
                "is_percussion": bool(getattr(track, "is_percussion")),
                "display_name": str(getattr(track, "display_name")),
                "bdo_instrument_id": int(getattr(track, "bdo_instrument_id")),
                "muted": bool(getattr(track, "muted", False)),
                "solo": bool(getattr(track, "solo", False)),
                "volume_scale": float(getattr(track, "volume_scale", 1.0)),
                "duration_scale": float(getattr(track, "duration_scale", 1.0)),
                "bdo_track_volume": int(getattr(track, "bdo_track_volume", 70)),
                "bdo_track_settings": tuple(
                    int(value)
                    for value in getattr(track, "bdo_track_settings", (0,) * 8)
                ),
                "bdo_source_group_index": getattr(
                    track, "bdo_source_group_index", None
                ),
                "bdo_source_note_records": tuple(
                    tuple(record)
                    for record in getattr(track, "bdo_source_note_records", ())
                ),
                "articulation_type": getattr(track, "articulation_type", None),
                "marnian_synth_mode": str(
                    getattr(track, "marnian_synth_mode", "basic") or "basic"
                ),
                "notes_optimized": bool(
                    getattr(track, "notes_optimized", False)
                ),
                "performance_controls": tuple(
                    dict(control)
                    for control in getattr(track, "performance_controls", ())
                ),
            },
            notes=tuple(getattr(track, "notes", ())),
        )
        for track in tracks
    )


def _track_payload(track: ProjectTrackSnapshot) -> dict[str, Any]:
    payload = dict(track.values)
    payload["bdo_track_settings"] = list(payload["bdo_track_settings"])
    payload["bdo_source_note_records"] = [
        list(record) for record in payload["bdo_source_note_records"]
    ]
    payload["performance_controls"] = [
        dict(control) for control in payload["performance_controls"]
    ]
    payload["notes"] = [
        [
            int(note.pitch),
            int(note.vel),
            float(note.start),
            float(note.dur),
            int(getattr(note, "ntype", 0)),
        ]
        for note in track.notes
    ]
    return payload


def _safe_instrument_ids(values: Sequence[object]) -> list[int]:
    instrument_ids: list[int] = []
    seen: set[int] = set()
    for value in values:
        source = value.values if isinstance(value, ProjectTrackSnapshot) else value
        if not isinstance(source, Mapping):
            continue
        try:
            instrument_id = int(source.get("bdo_instrument_id"))
        except (TypeError, ValueError):
            continue
        if 0 <= instrument_id <= 0xFF and instrument_id not in seen:
            seen.add(instrument_id)
            instrument_ids.append(instrument_id)
    return instrument_ids


def write_autosave(request: AutosaveRequest) -> Path:
    request.project_dir.mkdir(parents=True, exist_ok=True)
    if request.source_path is not None and request.source_copy is not None:
        if not request.source_copy.is_file():
            atomic_copy_file(request.source_path, request.source_copy)

    payload = dict(request.metadata)
    payload["project_id"] = (
        normalize_project_id(payload.get("project_id"))
        or project_id_for_path(request.project_dir)
    )
    payload["tracks"] = [_track_payload(track) for track in request.tracks]
    project_path = request.project_dir / "project.json"
    atomic_write_json(project_path, payload)
    atomic_write_json(
        request.project_dir / PROJECT_INDEX_NAME,
        {
            "schema": "bdo-project-index/v1",
            "project_id": payload["project_id"],
            "output_name": str(payload.get("output_name") or ""),
            "saved_at": request.saved_at,
            "instrument_ids": _safe_instrument_ids(request.tracks),
        },
    )
    with (request.project_dir / "autosave.log").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write(f"[{request.saved_at}] {request.reason}\n")
    return project_path


def rename_project(project_path: Path, output_name: str) -> str:
    """Atomically change an inactive project's display name and safe index."""

    project_path = Path(project_path)
    clean_name = str(output_name).strip()
    if not clean_name:
        raise ValueError("project name must not be empty")
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("project root must be an object")
    payload["output_name"] = clean_name
    payload["project_id"] = (
        normalize_project_id(payload.get("project_id"))
        or project_id_for_path(project_path.parent)
    )
    atomic_write_json(project_path, payload)

    saved_at = str(payload.get("saved_at") or "")
    raw_tracks = payload.get("tracks")
    tracks = raw_tracks if isinstance(raw_tracks, list) else []
    atomic_write_json(
        project_path.parent / PROJECT_INDEX_NAME,
        {
            "schema": "bdo-project-index/v1",
            "project_id": payload["project_id"],
            "output_name": clean_name,
            "saved_at": saved_at,
            "instrument_ids": _safe_instrument_ids(tracks),
        },
    )
    return payload["project_id"]


__all__ = [
    "AutosaveRequest",
    "PROJECT_INDEX_NAME",
    "ProjectTrackSnapshot",
    "freeze_project_tracks",
    "new_project_id",
    "normalize_project_id",
    "project_id_for_path",
    "rename_project",
    "write_autosave",
]
