"""Typed, Qt-free preparation of a project document before UI commit."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any

from bdo_track_effects import MasterEffects
from bdo_transcription_assist import TranscriptionAssistReviewState
from bdo_transcription_session import TranscriptionSessionState
from conversion_settings import ConversionSettings
from bdo_music_composer.editor.editor_import import (
    EditorImportError,
    TrackImportPresentation,
    tracks_from_project_payload,
)
from bdo_music_composer.editor.editor_models import TrackState
from pitch_transform import PitchTransformPlan
from .project_lifecycle_controller import (
    ProjectOpenError,
    ProjectOpenRequest,
    ProjectSourceFormat,
)
from .project_schema import (
    CURRENT_PROJECT_SCHEMA,
    migrate_project,
    normalize_reference_layer_settings,
    resolve_project_file_reference,
)


class ProjectLoadErrorCode(str, Enum):
    INVALID_JSON = "invalid_json"
    INVALID_ROOT = "invalid_root"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    INVALID_FIELD = "invalid_field"
    INVALID_SOURCE_REFERENCE = "invalid_source_reference"
    MISSING_SOURCE = "missing_source"
    INVALID_TRACKS = "invalid_tracks"


class ProjectLoadError(ValueError):
    """Stable project-load failure with one JSON path and debug detail."""

    def __init__(
        self,
        code: ProjectLoadErrorCode,
        path: str,
        detail: str,
    ) -> None:
        self.code = code
        self.path = str(path)
        self.detail = str(detail)
        super().__init__(f"{self.path}: {self.detail}")


@dataclass(frozen=True, slots=True)
class ProjectResearchPlan:
    profile_id: str
    experiments: tuple[tuple[tuple[str, object], ...], ...]

    def experiments_payload(self) -> list[dict[str, object]]:
        return [dict(item) for item in self.experiments]


@dataclass(frozen=True, slots=True)
class ProjectReferencePlan:
    volume_percent: int
    offset_ms: float
    beat_origin_ms: float
    layers: tuple[tuple[str, object], ...]
    candidate_path: Path | None
    was_attached: bool

    def layers_payload(self) -> dict[str, object]:
        return dict(self.layers)


@dataclass(frozen=True, slots=True)
class ProjectLoadPlan:
    """Complete ownership-transfer plan; no raw project mapping survives."""

    open_request: ProjectOpenRequest
    tracks: tuple[TrackState, ...]
    conversion: ConversionSettings
    master_effects: MasterEffects
    pitch_plan: PitchTransformPlan
    bpm: int
    time_signature: int
    time_signature_denominator: int | None
    tempo_changes: int
    owner_id: int
    character_name: str
    lyric_events: tuple[tuple[tuple[str, object], ...], ...]
    research: ProjectResearchPlan
    reference: ProjectReferencePlan
    transcription_state: TranscriptionSessionState
    assist_review: TranscriptionAssistReviewState

    def lyric_payload(self) -> list[dict[str, object]]:
        return [dict(item) for item in self.lyric_events]


FileExists = Callable[[Path], bool]
MidiMeterReader = Callable[[Path], int]


def _load_error(
    code: ProjectLoadErrorCode,
    path: str,
    detail: object,
) -> ProjectLoadError:
    return ProjectLoadError(code, path, str(detail))


def _decode_and_migrate(project_text: str) -> dict[str, Any]:
    try:
        decoded = json.loads(project_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_JSON,
            "$",
            exc,
        ) from exc
    if not isinstance(decoded, Mapping):
        raise _load_error(
            ProjectLoadErrorCode.INVALID_ROOT,
            "$",
            "project root must be an object",
        )

    raw_version = decoded.get("schema_version", decoded.get("version", 1))
    try:
        version = int(raw_version)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            "schema_version",
            "must be an integer",
        ) from exc
    if not 1 <= version <= CURRENT_PROJECT_SCHEMA:
        raise _load_error(
            ProjectLoadErrorCode.UNSUPPORTED_SCHEMA,
            "schema_version",
            f"unsupported project schema version: {version}",
        )
    try:
        return migrate_project(decoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            "$",
            exc,
        ) from exc


def _integer(
    payload: Mapping[str, object],
    key: str,
    default: int,
) -> int:
    raw_value = payload.get(key, default)
    if raw_value is None or raw_value == "":
        raw_value = default
    try:
        return int(raw_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            key,
            "must be an integer",
        ) from exc


def _finite_float(
    payload: Mapping[str, object],
    key: str,
    default: float,
) -> float:
    raw_value = payload.get(key, default)
    if raw_value is None or raw_value == "":
        raw_value = default
    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            key,
            "must be a finite number",
        ) from exc
    if not math.isfinite(value):
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            key,
            "must be a finite number",
        )
    return value


def _mapping_items(value: object) -> tuple[tuple[str, object], ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple((str(key), item) for key, item in value.items())


def _event_payloads(value: object) -> tuple[tuple[tuple[str, object], ...], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        _mapping_items(item)
        for item in value
        if isinstance(item, Mapping)
    )


def _conversion_plan(
    payload: Mapping[str, object],
    source_format: str,
) -> tuple[ConversionSettings, MasterEffects, str]:
    raw_conversion = payload.get("conversion_settings")
    if not isinstance(raw_conversion, Mapping):
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            "conversion_settings",
            "must be an object",
        )
    conversion_payload = dict(raw_conversion)
    try:
        conversion = ConversionSettings.from_project_payload(
            conversion_payload,
            source_format=source_format,
        )
        raw_chorus = conversion_payload.get("chorus")
        if isinstance(raw_chorus, Mapping):
            raw_chorus = (
                raw_chorus.get("feedback", 0),
                raw_chorus.get("depth", 0),
                raw_chorus.get("freq", 0),
            )
        master = MasterEffects.from_legacy(
            conversion_payload.get("reverb", 0),
            conversion_payload.get("delay", 0),
            raw_chorus,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            "conversion_settings",
            exc,
        ) from exc
    character_name = str(
        payload.get("char_name")
        or conversion_payload.get("char_name")
        or ""
    )
    return conversion, master, character_name


def _validate_reference(
    project_dir: Path,
    payload: Mapping[str, object],
    key: str,
    *,
    allow_legacy_absolute: bool,
) -> Path | None:
    raw_value = payload.get(key)
    if raw_value is None or str(raw_value).strip() == "":
        return None
    candidate = resolve_project_file_reference(
        project_dir,
        raw_value,
        allow_legacy_absolute=allow_legacy_absolute,
    )
    if candidate is None:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_SOURCE_REFERENCE,
            key,
            "path is absolute, escapes the project, or is not a path",
        )
    return candidate


def _reference_plan(
    project_path: Path,
    payload: Mapping[str, object],
    open_request: ProjectOpenRequest,
    file_exists: FileExists,
) -> ProjectReferencePlan:
    raw_reference = payload.get("reference_audio_path")
    was_attached = bool(
        payload.get("reference_audio_attached", bool(raw_reference))
    )
    candidate = _validate_reference(
        project_path.parent,
        payload,
        "reference_audio_path",
        allow_legacy_absolute=open_request.allow_legacy_absolute_paths,
    )
    if candidate is not None and not file_exists(candidate):
        candidate = None
    volume = _integer(payload, "reference_audio_volume", 50)
    if not 0 <= volume <= 100:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            "reference_audio_volume",
            "must be between 0 and 100",
        )
    layers = normalize_reference_layer_settings(payload.get("reference_layers"))
    return ProjectReferencePlan(
        volume_percent=volume,
        offset_ms=_finite_float(payload, "reference_audio_offset_ms", 0.0),
        beat_origin_ms=_finite_float(payload, "beat_origin_ms", 0.0),
        layers=tuple(layers.items()),
        candidate_path=candidate,
        was_attached=was_attached,
    )


def _meter_denominator(
    payload: Mapping[str, object],
    open_request: ProjectOpenRequest,
    midi_meter_reader: MidiMeterReader,
) -> int | None:
    raw_value = payload.get("time_sig_denominator")
    if raw_value is not None:
        return _integer(payload, "time_sig_denominator", 4)
    if open_request.source_format in {
        ProjectSourceFormat.BDO,
        ProjectSourceFormat.PROJECT,
    }:
        return 4
    if open_request.source_path is None:
        return None
    try:
        return int(midi_meter_reader(open_request.source_path))
    except (OSError, TypeError, ValueError, OverflowError):
        return None


def _research_plan(payload: Mapping[str, object]) -> ProjectResearchPlan:
    raw_research = payload.get("research")
    if not isinstance(raw_research, Mapping):
        return ProjectResearchPlan("", ())
    return ProjectResearchPlan(
        profile_id=str(raw_research.get("profile_id") or ""),
        experiments=_event_payloads(raw_research.get("ab_experiments")),
    )


def prepare_project_load(
    project_path: Path,
    project_text: str,
    presentation: TrackImportPresentation,
    *,
    file_exists: FileExists,
    midi_meter_reader: MidiMeterReader,
) -> ProjectLoadPlan:
    """Validate and type one project completely before any UI state changes."""

    payload = _decode_and_migrate(project_text)
    try:
        tracks = tracks_from_project_payload(payload, presentation)
    except EditorImportError as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_TRACKS,
            exc.path,
            f"{exc.code.value}: {exc.detail}",
        ) from exc

    path = Path(project_path)
    allow_legacy = str(payload.get("path_policy") or "") != "project-relative-v1"
    for key in ("source_midi_path", "original_midi_path"):
        _validate_reference(
            path.parent,
            payload,
            key,
            allow_legacy_absolute=allow_legacy,
        )
    try:
        open_request = ProjectOpenRequest.from_payload(
            path,
            payload,
            file_exists=file_exists,
        )
    except ProjectOpenError as exc:
        raise _load_error(
            ProjectLoadErrorCode.MISSING_SOURCE,
            "source_midi_path",
            exc,
        ) from exc

    source_format = open_request.source_format.value
    conversion, master, character_name = _conversion_plan(
        payload,
        source_format,
    )
    try:
        pitch_plan = PitchTransformPlan.from_payload(
            payload.get("pitch_transform"),
            default_global_semitones=conversion.transpose,
        ).with_global(conversion.transpose).pruned(
            track.track_id for track in tracks
        )
        transcription_state = TranscriptionSessionState.from_payload(
            payload.get("transcription_review")
        )
        assist_review = TranscriptionAssistReviewState.from_payload(
            payload.get("transcription_assist_review")
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise _load_error(
            ProjectLoadErrorCode.INVALID_FIELD,
            "pitch_transform",
            exc,
        ) from exc

    return ProjectLoadPlan(
        open_request=open_request,
        tracks=tuple(tracks),
        conversion=conversion,
        master_effects=master,
        pitch_plan=pitch_plan,
        bpm=_integer(payload, "bpm", 120),
        time_signature=_integer(payload, "time_sig", 4),
        time_signature_denominator=_meter_denominator(
            payload,
            open_request,
            midi_meter_reader,
        ),
        tempo_changes=_integer(payload, "tempo_changes", 1),
        owner_id=_integer(payload, "owner_id", 0),
        character_name=character_name,
        lyric_events=_event_payloads(payload.get("lyric_events")),
        research=_research_plan(payload),
        reference=_reference_plan(path, payload, open_request, file_exists),
        transcription_state=transcription_state,
        assist_review=assist_review,
    )


__all__ = [
    "ProjectLoadError",
    "ProjectLoadErrorCode",
    "ProjectLoadPlan",
    "ProjectReferencePlan",
    "ProjectResearchPlan",
    "prepare_project_load",
]
