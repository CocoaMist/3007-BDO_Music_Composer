"""Immutable packaged snapshots and background-safe project serialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import math
import uuid

from bdo_common.atomic_io import atomic_copy_file, atomic_write_json
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME


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
class FrozenJsonObject:
    items: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class FrozenJsonArray:
    items: tuple[object, ...] = ()


def freeze_json_value(value: object, *, path: str = "$") -> object:
    """Recursively detach JSON-compatible values from mutable UI state."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            items.append((
                key,
                freeze_json_value(item, path=f"{path}.{key}"),
            ))
        return FrozenJsonObject(tuple(items))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return FrozenJsonArray(tuple(
            freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ))
    raise TypeError(f"{path} is not JSON-compatible")


def thaw_json_value(value: object) -> object:
    if isinstance(value, FrozenJsonObject):
        return {
            key: thaw_json_value(item)
            for key, item in value.items
        }
    if isinstance(value, FrozenJsonArray):
        return [thaw_json_value(item) for item in value.items]
    return value


def _frozen_object(value: object, *, path: str) -> FrozenJsonObject:
    frozen = freeze_json_value(value, path=path)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError(f"{path} must be an object")
    return frozen


def _frozen_array(value: object, *, path: str) -> FrozenJsonArray:
    frozen = freeze_json_value(value, path=path)
    if not isinstance(frozen, FrozenJsonArray):
        raise TypeError(f"{path} must be an array")
    return frozen


@dataclass(frozen=True, slots=True)
class ProjectNoteSnapshot:
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float
    note_type: int

    @classmethod
    def capture(cls, note: object, *, path: str) -> "ProjectNoteSnapshot":
        try:
            start_ms = float(getattr(note, "start"))
            duration_ms = float(getattr(note, "dur"))
            if not math.isfinite(start_ms) or not math.isfinite(duration_ms):
                raise ValueError("note timing must be finite")
            return cls(
                pitch=int(getattr(note, "pitch")),
                velocity=int(getattr(note, "vel")),
                start_ms=start_ms,
                duration_ms=duration_ms,
                note_type=int(getattr(note, "ntype", 0)),
            )
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{path} is not a valid note") from exc

    def to_payload(self) -> list[int | float]:
        return [
            self.pitch,
            self.velocity,
            self.start_ms,
            self.duration_ms,
            self.note_type,
        ]


@dataclass(frozen=True, slots=True)
class ProjectTrackSnapshot:
    """Detached track state consumed only by the autosave writer."""

    track_id: int
    gm_program: int
    is_percussion: bool
    display_name: str
    bdo_instrument_id: int
    muted: bool
    solo: bool
    duration_scale: float
    bdo_track_volume: int
    bdo_track_settings: tuple[int, ...]
    bdo_source_group_index: int | None
    bdo_source_note_records: FrozenJsonArray
    articulation_type: int | None
    marnian_synth_mode: str
    notes_optimized: bool
    performance_controls: FrozenJsonArray
    notes: tuple[ProjectNoteSnapshot, ...]

    @classmethod
    def capture(cls, track: object, *, path: str) -> "ProjectTrackSnapshot":
        legacy_scale = float(getattr(track, "volume_scale", 1.0))
        if not math.isclose(legacy_scale, 1.0, abs_tol=1e-12):
            raise ValueError(
                f"{path}.volume_scale must be baked into note velocities"
            )
        duration_scale = float(getattr(track, "duration_scale", 1.0))
        if not math.isfinite(duration_scale):
            raise ValueError(f"{path}.duration_scale must be finite")
        raw_group_index = getattr(track, "bdo_source_group_index", None)
        raw_articulation = getattr(track, "articulation_type", None)
        raw_notes = tuple(getattr(track, "notes", ()))
        return cls(
            track_id=int(getattr(track, "track_id")),
            gm_program=int(getattr(track, "gm_program")),
            is_percussion=bool(getattr(track, "is_percussion")),
            display_name=str(getattr(track, "display_name")),
            bdo_instrument_id=int(getattr(track, "bdo_instrument_id")),
            muted=bool(getattr(track, "muted", False)),
            solo=bool(getattr(track, "solo", False)),
            duration_scale=duration_scale,
            bdo_track_volume=int(
                getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
            ),
            bdo_track_settings=tuple(
                int(value)
                for value in getattr(track, "bdo_track_settings", (0,) * 8)
            ),
            bdo_source_group_index=(
                None if raw_group_index is None else int(raw_group_index)
            ),
            bdo_source_note_records=_frozen_array(
                getattr(track, "bdo_source_note_records", ()),
                path=f"{path}.bdo_source_note_records",
            ),
            articulation_type=(
                None if raw_articulation is None else int(raw_articulation)
            ),
            marnian_synth_mode=str(
                getattr(track, "marnian_synth_mode", "basic") or "basic"
            ),
            notes_optimized=bool(getattr(track, "notes_optimized", False)),
            performance_controls=_frozen_array(
                getattr(track, "performance_controls", ()),
                path=f"{path}.performance_controls",
            ),
            notes=tuple(
                ProjectNoteSnapshot.capture(
                    note,
                    path=f"{path}.notes[{index}]",
                )
                for index, note in enumerate(raw_notes)
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "gm_program": self.gm_program,
            "is_percussion": self.is_percussion,
            "display_name": self.display_name,
            "bdo_instrument_id": self.bdo_instrument_id,
            "muted": self.muted,
            "solo": self.solo,
            "volume_scale": 1.0,
            "duration_scale": self.duration_scale,
            "bdo_track_volume": self.bdo_track_volume,
            "bdo_track_settings": list(self.bdo_track_settings),
            "bdo_source_group_index": self.bdo_source_group_index,
            "bdo_source_note_records": thaw_json_value(
                self.bdo_source_note_records
            ),
            "articulation_type": self.articulation_type,
            "marnian_synth_mode": self.marnian_synth_mode,
            "notes_optimized": self.notes_optimized,
            "performance_controls": thaw_json_value(
                self.performance_controls
            ),
            "notes": [note.to_payload() for note in self.notes],
        }


@dataclass(frozen=True, slots=True)
class ProjectMetadataSnapshot:
    """Typed, recursively detached project metadata for one writer request."""

    schema_version: int
    project_id: str
    saved_at: str
    reason: str
    source_format: str
    source_reference: str
    output_name: str
    owner_id: int
    character_name: str
    bpm: int
    time_signature: int
    time_signature_denominator: int | None
    tempo_changes: int
    lyric_events: FrozenJsonArray
    reference_audio_attached: bool
    reference_audio_volume: int
    reference_audio_offset_ms: float
    beat_origin_ms: float
    transcription_review: FrozenJsonObject
    transcription_assist_review: FrozenJsonObject
    reference_layers: FrozenJsonObject
    conversion_settings: FrozenJsonObject
    pitch_transform: FrozenJsonObject
    research: FrozenJsonObject

    @classmethod
    def capture(
        cls,
        *,
        schema_version: int,
        project_id: object = "",
        saved_at: object = "",
        reason: object = "autosave",
        source_format: object = "project",
        source_reference: object = "",
        output_name: object = "",
        owner_id: object = 0,
        character_name: object = "",
        bpm: object = 120,
        time_signature: object = 4,
        time_signature_denominator: object = 4,
        tempo_changes: object = 1,
        lyric_events: object = (),
        reference_audio_attached: object = False,
        reference_audio_volume: object = 50,
        reference_audio_offset_ms: object = 0.0,
        beat_origin_ms: object = 0.0,
        transcription_review: object = None,
        transcription_assist_review: object = None,
        reference_layers: object = None,
        conversion_settings: object = None,
        pitch_transform: object = None,
        research: object = None,
    ) -> "ProjectMetadataSnapshot":
        denominator = (
            None
            if time_signature_denominator is None
            else int(time_signature_denominator)
        )
        reference = str(source_reference or "")
        reference_path = Path(reference)
        if reference and (
            reference_path.is_absolute() or ".." in reference_path.parts
        ):
            raise ValueError("source_reference must stay project-relative")
        reference_volume = int(reference_audio_volume)
        if not 0 <= reference_volume <= 100:
            raise ValueError("reference_audio_volume must be between 0 and 100")
        reference_offset = float(reference_audio_offset_ms)
        beat_origin = float(beat_origin_ms)
        if not math.isfinite(reference_offset):
            raise ValueError("reference_audio_offset_ms must be finite")
        if not math.isfinite(beat_origin):
            raise ValueError("beat_origin_ms must be finite")
        return cls(
            schema_version=int(schema_version),
            project_id=str(project_id or ""),
            saved_at=str(saved_at or ""),
            reason=str(reason or "autosave"),
            source_format=str(source_format or "project"),
            source_reference=reference,
            output_name=str(output_name or ""),
            owner_id=int(owner_id or 0),
            character_name=str(character_name or ""),
            bpm=int(bpm or 120),
            time_signature=int(time_signature or 4),
            time_signature_denominator=denominator,
            tempo_changes=int(tempo_changes or 1),
            lyric_events=_frozen_array(lyric_events, path="lyric_events"),
            reference_audio_attached=bool(reference_audio_attached),
            reference_audio_volume=reference_volume,
            reference_audio_offset_ms=reference_offset,
            beat_origin_ms=beat_origin,
            transcription_review=_frozen_object(
                transcription_review or {},
                path="transcription_review",
            ),
            transcription_assist_review=_frozen_object(
                transcription_assist_review or {},
                path="transcription_assist_review",
            ),
            reference_layers=_frozen_object(
                reference_layers or {},
                path="reference_layers",
            ),
            conversion_settings=_frozen_object(
                conversion_settings or {},
                path="conversion_settings",
            ),
            pitch_transform=_frozen_object(
                pitch_transform or {},
                path="pitch_transform",
            ),
            research=_frozen_object(research or {}, path="research"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "path_policy": "project-relative-v1",
            "saved_at": self.saved_at,
            "reason": self.reason,
            "source_format": self.source_format,
            "original_midi_path": "",
            "source_midi_path": self.source_reference,
            "output_name": self.output_name,
            "owner_id": self.owner_id,
            "char_name": self.character_name,
            "bpm": self.bpm,
            "time_sig": self.time_signature,
            "time_sig_denominator": self.time_signature_denominator,
            "tempo_changes": self.tempo_changes,
            "lyric_events": thaw_json_value(self.lyric_events),
            "reference_audio_path": "",
            "reference_audio_attached": self.reference_audio_attached,
            "reference_audio_volume": self.reference_audio_volume,
            "reference_audio_offset_ms": self.reference_audio_offset_ms,
            "beat_origin_ms": self.beat_origin_ms,
            "transcription_review": thaw_json_value(
                self.transcription_review
            ),
            "transcription_assist_review": thaw_json_value(
                self.transcription_assist_review
            ),
            "reference_layers": thaw_json_value(self.reference_layers),
            "conversion_settings": thaw_json_value(
                self.conversion_settings
            ),
            "pitch_transform": thaw_json_value(self.pitch_transform),
            "research": thaw_json_value(self.research),
        }


@dataclass(frozen=True, slots=True)
class AutosaveRequest:
    project_dir: Path
    metadata: ProjectMetadataSnapshot
    tracks: tuple[ProjectTrackSnapshot, ...]
    source_path: Path | None = None
    source_copy: Path | None = None


def freeze_project_tracks(
    tracks: Sequence[object],
) -> tuple[ProjectTrackSnapshot, ...]:
    return tuple(
        ProjectTrackSnapshot.capture(track, path=f"tracks[{index}]")
        for index, track in enumerate(tracks)
    )


def _track_payload(track: ProjectTrackSnapshot) -> dict[str, Any]:
    return track.to_payload()


def _safe_instrument_ids(values: Sequence[object]) -> list[int]:
    instrument_ids: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            if isinstance(value, ProjectTrackSnapshot):
                instrument_id = value.bdo_instrument_id
            elif isinstance(value, Mapping):
                instrument_id = int(value.get("bdo_instrument_id"))
            else:
                continue
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

    payload = request.metadata.to_payload()
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
            "saved_at": request.metadata.saved_at,
            "instrument_ids": _safe_instrument_ids(request.tracks),
        },
    )
    with (request.project_dir / "autosave.log").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write(
            f"[{request.metadata.saved_at}] {request.metadata.reason}\n"
        )
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
    "FrozenJsonArray",
    "FrozenJsonObject",
    "PROJECT_INDEX_NAME",
    "ProjectNoteSnapshot",
    "ProjectTrackSnapshot",
    "ProjectMetadataSnapshot",
    "freeze_json_value",
    "freeze_project_tracks",
    "new_project_id",
    "normalize_project_id",
    "project_id_for_path",
    "rename_project",
    "thaw_json_value",
    "write_autosave",
]
