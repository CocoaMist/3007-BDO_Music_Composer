"""Canonical Qt-free adapters from score documents to editor tracks.

This module is the only place that constructs a complete ``TrackState`` from
external score data.  Parsing is transactional: malformed authoritative
project data raises a path-aware error instead of returning a partial score.
Presentation strings and lane colors are injected by the UI composition root.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path
from typing import Any

import mido

from bdo_midi import (
    MARNIAN_SYNTH_MODE_OFFSETS,
    Note,
    gm_to_bdo_instrument,
    parse_midi,
)
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME, raw_track_settings
from bdo_music_composer.core.conversion_settings import (
    VELOCITY_MODE_PRESERVE,
    ConversionSettings,
)
from .editor_models import TrackState
from bdo_music_composer.editor.game_score_model import (
    bake_game_velocity_transform,
    decode_serialized_game_instrument_id,
)


class EditorImportErrorCode(str, Enum):
    INVALID_CONTAINER = "invalid_container"
    INVALID_TRACK = "invalid_track"
    INVALID_NOTE = "invalid_note"
    DUPLICATE_TRACK_ID = "duplicate_track_id"
    MIXED_INSTRUMENT = "mixed_instrument"
    CONFLICTING_VOLUME = "conflicting_volume"
    CONFLICTING_EFFECTS = "conflicting_effects"
    CONFLICTING_MASTER_EFFECTS = "conflicting_master_effects"


class EditorImportError(ValueError):
    """One deterministic, location-aware import failure."""

    def __init__(
        self,
        code: EditorImportErrorCode,
        path: str,
        detail: str,
    ) -> None:
        self.code = code
        self.path = str(path)
        self.detail = str(detail)
        super().__init__(f"{self.path}: {self.detail}")


class MidiMeterReadError(ValueError):
    """Raised when the source meter cannot be inspected safely."""


@dataclass(frozen=True, slots=True)
class TrackImportPresentation:
    """UI-owned names and colors used while constructing editor tracks."""

    colors: tuple[str, ...]
    bdo_instrument_name: Callable[[int], str]
    gm_program_name: Callable[[int], str]
    drum_track_name: Callable[[], str]
    new_track_name: Callable[[int], str]

    def __post_init__(self) -> None:
        if not self.colors:
            raise ValueError("track import presentation requires at least one color")

    def color(self, index: int) -> str:
        return self.colors[int(index) % len(self.colors)]


@dataclass(frozen=True, slots=True)
class MidiImportData:
    """A completely parsed MIDI import, safe to commit as one operation."""

    bpm: int
    time_signature: int
    time_signature_denominator: int
    tempo_changes: int
    lyric_events: tuple[dict[str, Any], ...]
    tracks: tuple[TrackState, ...]
    conversion_settings: ConversionSettings


def read_midi_time_signature_denominator(midi_path: str | Path) -> int:
    """Return the first declared MIDI meter denominator, defaulting to ``/4``."""

    try:
        midi = mido.MidiFile(str(midi_path), clip=True)
        for midi_track in midi.tracks:
            for message in midi_track:
                if message.type == "time_signature":
                    return int(message.denominator)
    except Exception as exc:
        raise MidiMeterReadError(str(exc)) from exc
    return 4


def _import_error(
    code: EditorImportErrorCode,
    path: str,
    detail: str,
    exc: BaseException | None = None,
) -> EditorImportError:
    error = EditorImportError(code, path, detail)
    if exc is not None:
        error.__cause__ = exc
    return error


def _integer(
    value: object,
    *,
    path: str,
    code: EditorImportErrorCode,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        raise _import_error(code, path, "expected an integer, not a boolean")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _import_error(code, path, "expected an integer", exc)
    if isinstance(value, float) and value != result:
        raise _import_error(code, path, "expected a whole integer value")
    if minimum is not None and result < minimum:
        raise _import_error(code, path, f"must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise _import_error(code, path, f"must be at most {maximum}")
    return result


def _finite_number(
    value: object,
    *,
    path: str,
    code: EditorImportErrorCode,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if isinstance(value, bool):
        raise _import_error(code, path, "expected a number, not a boolean")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _import_error(code, path, "expected a finite number", exc)
    if not math.isfinite(result):
        raise _import_error(code, path, "must be finite")
    if positive and result <= 0.0:
        raise _import_error(code, path, "must be greater than zero")
    if nonnegative and result < 0.0:
        raise _import_error(code, path, "must not be negative")
    return result


def _is_data_sequence(value: object) -> bool:
    """Exclude text and byte buffers from structural score sequences."""

    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _project_note(value: object, *, path: str) -> Note:
    if not isinstance(value, (list, tuple)) or len(value) < 5:
        raise _import_error(
            EditorImportErrorCode.INVALID_NOTE,
            path,
            "expected [pitch, velocity, start_ms, duration_ms, ntype]",
        )
    return Note(
        _integer(
            value[0], path=f"{path}[0]", code=EditorImportErrorCode.INVALID_NOTE,
            minimum=0, maximum=127,
        ),
        _integer(
            value[1], path=f"{path}[1]", code=EditorImportErrorCode.INVALID_NOTE,
            minimum=0, maximum=127,
        ),
        _finite_number(
            value[2], path=f"{path}[2]", code=EditorImportErrorCode.INVALID_NOTE,
        ),
        _finite_number(
            value[3], path=f"{path}[3]", code=EditorImportErrorCode.INVALID_NOTE,
            nonnegative=True,
        ),
        _integer(
            value[4], path=f"{path}[4]", code=EditorImportErrorCode.INVALID_NOTE,
            minimum=0, maximum=255,
        ),
    )


def _source_note_record(value: object, *, path: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)) or len(value) < 6:
        raise _import_error(
            EditorImportErrorCode.INVALID_NOTE,
            path,
            "expected a six-field source note record",
        )
    note = _project_note(value, path=path)
    velocity_b = _integer(
        value[5],
        path=f"{path}[5]",
        code=EditorImportErrorCode.INVALID_NOTE,
        minimum=0,
        maximum=127,
    )
    return (
        note.pitch,
        note.vel,
        note.start,
        note.dur,
        note.ntype,
        velocity_b,
    )


@dataclass(frozen=True, slots=True)
class _ImportedBdoNote:
    note: Note
    velocity_b: int

    @property
    def source_record(self) -> tuple[Any, ...]:
        return (
            self.note.pitch,
            self.note.vel,
            self.note.start,
            self.note.dur,
            self.note.ntype,
            self.velocity_b,
        )


@dataclass(frozen=True, slots=True)
class _PhysicalBdoTrack:
    source_path: str
    group_index: int
    track_index: int
    instrument_id: int
    volume: int
    settings: tuple[int, ...]
    notes: tuple[_ImportedBdoNote, ...]

    @property
    def master_settings(self) -> tuple[int, int, int, int, int]:
        return (
            self.settings[1],
            self.settings[3],
            self.settings[5],
            self.settings[6],
            self.settings[7],
        )


def _bdo_snapshot_note(value: object, *, path: str) -> _ImportedBdoNote:
    note = Note(
        _integer(
            getattr(value, "pitch", None),
            path=f"{path}.pitch",
            code=EditorImportErrorCode.INVALID_NOTE,
            minimum=0,
            maximum=127,
        ),
        _integer(
            getattr(value, "velocity_a", None),
            path=f"{path}.velocity_a",
            code=EditorImportErrorCode.INVALID_NOTE,
            minimum=0,
            maximum=127,
        ),
        _finite_number(
            getattr(value, "start_ms", None),
            path=f"{path}.start_ms",
            code=EditorImportErrorCode.INVALID_NOTE,
        ),
        _finite_number(
            getattr(value, "duration_ms", None),
            path=f"{path}.duration_ms",
            code=EditorImportErrorCode.INVALID_NOTE,
            nonnegative=True,
        ),
        _integer(
            getattr(value, "ntype", None),
            path=f"{path}.ntype",
            code=EditorImportErrorCode.INVALID_NOTE,
            minimum=0,
            maximum=255,
        ),
    )
    velocity_b = _integer(
        getattr(value, "velocity_b", None),
        path=f"{path}.velocity_b",
        code=EditorImportErrorCode.INVALID_NOTE,
        minimum=0,
        maximum=127,
    )
    return _ImportedBdoNote(note, velocity_b)


def _physical_bdo_track(
    value: object,
    *,
    snapshot_index: int,
) -> _PhysicalBdoTrack:
    path = f"snapshot.tracks[{snapshot_index}]"
    raw_notes = getattr(value, "notes", None)
    if not _is_data_sequence(raw_notes):
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.notes",
            "expected a sequence of notes",
        )
    try:
        settings = raw_track_settings(getattr(value, "settings", ()))
    except (TypeError, ValueError, OverflowError) as exc:
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.settings",
            str(exc),
            exc,
        )
    return _PhysicalBdoTrack(
        source_path=path,
        group_index=_integer(
            getattr(value, "group_index", None),
            path=f"{path}.group_index",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
        ),
        track_index=_integer(
            getattr(value, "track_index", None),
            path=f"{path}.track_index",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
        ),
        instrument_id=_integer(
            getattr(value, "instrument_id", None),
            path=f"{path}.instrument_id",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
            maximum=0xFFFF,
        ),
        volume=_integer(
            getattr(value, "volume", None),
            path=f"{path}.volume",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
            maximum=255,
        ),
        settings=settings,
        notes=tuple(
            _bdo_snapshot_note(
                note,
                path=f"{path}.notes[{note_index}]",
            )
            for note_index, note in enumerate(raw_notes)
        ),
    )


def _validated_bdo_physical_tracks(
    snapshot: object,
) -> tuple[_PhysicalBdoTrack, ...]:
    raw_tracks = getattr(snapshot, "tracks", None)
    if not _is_data_sequence(raw_tracks):
        raise _import_error(
            EditorImportErrorCode.INVALID_CONTAINER,
            "snapshot.tracks",
            "expected a sequence of physical tracks",
        )

    tracks: list[_PhysicalBdoTrack] = []
    physical_keys: set[tuple[int, int]] = set()
    master_settings: set[tuple[int, int, int, int, int]] = set()
    for snapshot_index, raw_track in enumerate(raw_tracks):
        track = _physical_bdo_track(
            raw_track,
            snapshot_index=snapshot_index,
        )
        key = (track.group_index, track.track_index)
        if key in physical_keys:
            raise _import_error(
                EditorImportErrorCode.INVALID_TRACK,
                track.source_path,
                "duplicate physical track index within one instrument group",
            )
        physical_keys.add(key)
        master_settings.add(track.master_settings)
        tracks.append(track)
    if len(master_settings) > 1:
        raise _import_error(
            EditorImportErrorCode.CONFLICTING_MASTER_EFFECTS,
            "snapshot.tracks",
            "BDO physical tracks contain conflicting master effect settings",
        )
    return tuple(tracks)


def _single_group_value(
    values: set[Any],
    *,
    code: EditorImportErrorCode,
    path: str,
    detail: str,
) -> Any:
    if len(values) != 1:
        raise _import_error(code, path, detail)
    return next(iter(values))


def _bdo_group_state(
    track_id: int,
    group_index: int,
    tracks: Sequence[_PhysicalBdoTrack],
    presentation: TrackImportPresentation,
) -> TrackState:
    ordered = tuple(sorted(tracks, key=lambda track: track.track_index))
    group_path = f"snapshot.groups[{group_index}]"
    serialized_id = int(_single_group_value(
        {track.instrument_id for track in ordered},
        code=EditorImportErrorCode.MIXED_INSTRUMENT,
        path=group_path,
        detail="BDO instrument group contains mixed instrument IDs",
    ))
    volume = int(_single_group_value(
        {track.volume for track in ordered},
        code=EditorImportErrorCode.CONFLICTING_VOLUME,
        path=group_path,
        detail="BDO instrument group contains conflicting volumes",
    ))
    settings = tuple(_single_group_value(
        {track.settings for track in ordered},
        code=EditorImportErrorCode.CONFLICTING_EFFECTS,
        path=group_path,
        detail="BDO instrument group contains conflicting effect settings",
    ))
    imported_notes = tuple(
        imported
        for track in ordered
        for imported in track.notes
    )
    notes = sorted(
        (imported.note for imported in imported_notes),
        key=lambda note: (note.start, note.pitch, note.dur),
    )
    source_records = tuple(
        imported.source_record
        for imported in imported_notes
    )
    instrument_id, marnian_mode = decode_serialized_game_instrument_id(
        serialized_id
    )
    return TrackState(
        track_id=track_id,
        notes=notes,
        gm_program=0,
        is_percussion=serialized_id == 0x0D,
        display_name=presentation.bdo_instrument_name(instrument_id),
        bdo_instrument_id=instrument_id,
        marnian_synth_mode=marnian_mode,
        color=presentation.color(track_id),
        effect_settings_placeholder={
            "source_format": "bdo_v9",
            "track_volume": volume,
            "track_settings": list(settings),
            "physical_track_count": len(ordered),
            "velocity_pair_mismatches": sum(
                imported.note.vel != imported.velocity_b
                for imported in imported_notes
            ),
        },
        bdo_track_volume=volume,
        bdo_track_settings=settings,
        bdo_source_group_index=group_index,
        bdo_source_note_records=source_records,
    )


def tracks_from_bdo_snapshot(
    snapshot: object,
    presentation: TrackImportPresentation,
) -> tuple[TrackState, ...]:
    """Collapse validated 730-note BDO chunks into logical editor tracks."""

    grouped: dict[int, list[_PhysicalBdoTrack]] = {}
    for track in _validated_bdo_physical_tracks(snapshot):
        grouped.setdefault(track.group_index, []).append(track)
    return tuple(
        _bdo_group_state(
            track_id,
            group_index,
            grouped[group_index],
            presentation,
        )
        for track_id, group_index in enumerate(sorted(grouped))
    )


def _project_track_id(item: Mapping[str, object], *, path: str) -> int:
    if "track_id" not in item:
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.track_id",
            "field is required",
        )
    return _integer(
        item["track_id"],
        path=f"{path}.track_id",
        code=EditorImportErrorCode.INVALID_TRACK,
        minimum=0,
    )


def _project_notes(item: Mapping[str, object], *, path: str) -> list[Note]:
    values = item.get("notes", [])
    if not isinstance(values, list):
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.notes",
            "expected a list",
        )
    return [
        _project_note(note, path=f"{path}.notes[{note_index}]")
        for note_index, note in enumerate(values)
    ]


def _project_track_settings(
    item: Mapping[str, object],
    *,
    path: str,
) -> tuple[int, ...]:
    try:
        return raw_track_settings(
            item.get("bdo_track_settings", (0,) * 8)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.bdo_track_settings",
            str(exc),
            exc,
        )


def _project_source_records(
    item: Mapping[str, object],
    *,
    path: str,
) -> tuple[tuple[Any, ...], ...]:
    values = item.get("bdo_source_note_records", ())
    if not isinstance(values, (list, tuple)):
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.bdo_source_note_records",
            "expected a list",
        )
    return tuple(
        _source_note_record(
            record,
            path=f"{path}.bdo_source_note_records[{record_index}]",
        )
        for record_index, record in enumerate(values)
    )


def _project_performance_controls(
    item: Mapping[str, object],
    *,
    path: str,
) -> list[dict[str, object]]:
    values = item.get("performance_controls", ())
    if not isinstance(values, (list, tuple)):
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.performance_controls",
            "expected a list",
        )
    controls: list[dict[str, object]] = []
    for control_index, control in enumerate(values):
        if not isinstance(control, Mapping):
            raise _import_error(
                EditorImportErrorCode.INVALID_TRACK,
                f"{path}.performance_controls[{control_index}]",
                "expected an object",
            )
        controls.append(dict(control))
    return controls


def _project_marnian_mode(
    item: Mapping[str, object],
    *,
    path: str,
) -> str:
    mode = str(item.get("marnian_synth_mode", "basic") or "basic")
    if mode not in MARNIAN_SYNTH_MODE_OFFSETS:
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.marnian_synth_mode",
            f"unsupported Marnian mode: {mode}",
        )
    return mode


def _require_materialized_project_velocity(
    item: Mapping[str, object],
    *,
    path: str,
) -> None:
    legacy_scale = _finite_number(
        item.get("volume_scale", 1.0),
        path=f"{path}.volume_scale",
        code=EditorImportErrorCode.INVALID_TRACK,
    )
    if not math.isclose(legacy_scale, 1.0, abs_tol=1e-12):
        raise _import_error(
            EditorImportErrorCode.INVALID_TRACK,
            f"{path}.volume_scale",
            "legacy velocity scale was not materialized by schema migration",
        )


def _optional_project_integer(
    value: object,
    *,
    path: str,
) -> int | None:
    if value is None:
        return None
    return _integer(
        value,
        path=path,
        code=EditorImportErrorCode.INVALID_TRACK,
        minimum=0,
        maximum=255,
    )


def _project_track_state(
    item: Mapping[str, object],
    *,
    path: str,
    index: int,
    track_id: int,
    presentation: TrackImportPresentation,
) -> TrackState:
    _require_materialized_project_velocity(item, path=path)
    source_group = item.get("bdo_source_group_index")
    return TrackState(
        track_id=track_id,
        notes=_project_notes(item, path=path),
        gm_program=_integer(
            item.get("gm_program", 0),
            path=f"{path}.gm_program",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
            maximum=127,
        ),
        is_percussion=bool(item.get("is_percussion", False)),
        display_name=str(
            item.get("display_name")
            or presentation.new_track_name(track_id)
        ),
        bdo_instrument_id=_integer(
            item.get("bdo_instrument_id", 0x0B),
            path=f"{path}.bdo_instrument_id",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
            maximum=0xFFFF,
        ),
        muted=bool(item.get("muted", False)),
        solo=bool(item.get("solo", False)),
        volume_scale=1.0,
        duration_scale=_finite_number(
            item.get("duration_scale", 1.0),
            path=f"{path}.duration_scale",
            code=EditorImportErrorCode.INVALID_TRACK,
            positive=True,
        ),
        articulation_type=_optional_project_integer(
            item.get("articulation_type"),
            path=f"{path}.articulation_type",
        ),
        marnian_synth_mode=_project_marnian_mode(item, path=path),
        color=presentation.color(index),
        effect_settings_placeholder={
            "track_effects_enabled": False,
            "note_effects_reserved": True,
        },
        performance_controls=_project_performance_controls(
            item,
            path=path,
        ),
        notes_optimized=bool(item.get("notes_optimized", False)),
        bdo_track_volume=_integer(
            item.get("bdo_track_volume", DEFAULT_TRACK_VOLUME),
            path=f"{path}.bdo_track_volume",
            code=EditorImportErrorCode.INVALID_TRACK,
            minimum=0,
            maximum=255,
        ),
        bdo_track_settings=_project_track_settings(item, path=path),
        bdo_source_group_index=(
            _integer(
                source_group,
                path=f"{path}.bdo_source_group_index",
                code=EditorImportErrorCode.INVALID_TRACK,
                minimum=0,
            )
            if source_group is not None
            else None
        ),
        bdo_source_note_records=_project_source_records(item, path=path),
    )


def tracks_from_project_payload(
    payload: Mapping[str, object],
    presentation: TrackImportPresentation,
) -> tuple[TrackState, ...]:
    """Restore a complete editor snapshot, rejecting partial corruption."""

    if not isinstance(payload, Mapping):
        raise _import_error(
            EditorImportErrorCode.INVALID_CONTAINER,
            "$",
            "expected an object",
        )
    raw_tracks = payload.get("tracks")
    if raw_tracks is None:
        return ()
    if not isinstance(raw_tracks, list):
        raise _import_error(
            EditorImportErrorCode.INVALID_CONTAINER,
            "tracks",
            "expected a list",
        )

    states: list[TrackState] = []
    seen_track_ids: set[int] = set()
    for index, item in enumerate(raw_tracks):
        path = f"tracks[{index}]"
        if not isinstance(item, Mapping):
            raise _import_error(
                EditorImportErrorCode.INVALID_TRACK,
                path,
                "expected an object",
            )
        track_id = _project_track_id(item, path=path)
        if track_id in seen_track_ids:
            raise _import_error(
                EditorImportErrorCode.DUPLICATE_TRACK_ID,
                f"{path}.track_id",
                f"duplicate track ID {track_id}",
            )
        seen_track_ids.add(track_id)
        states.append(_project_track_state(
            item,
            path=path,
            index=index,
            track_id=track_id,
            presentation=presentation,
        ))
    return tuple(states)


def prepare_midi_import(
    path: str | Path,
    settings: ConversionSettings,
    presentation: TrackImportPresentation,
) -> MidiImportData:
    """Parse and transform a MIDI without touching the open editor project."""

    bpm, time_signature, groups, tempo_changes, controls, lyric_events = (
        parse_midi(
            path,
            apply_sustain=settings.apply_sustain,
            flatten_tempo=settings.flatten_tempo,
            include_controls=True,
            include_lyrics=True,
        )
    )
    tracks: list[TrackState] = []
    for index, (notes, gm_program, is_percussion) in enumerate(groups):
        game_notes = list(bake_game_velocity_transform(notes, settings))
        tracks.append(TrackState(
            track_id=index,
            notes=game_notes,
            gm_program=gm_program,
            is_percussion=is_percussion,
            display_name=(
                presentation.drum_track_name()
                if is_percussion
                else presentation.gm_program_name(gm_program)
            ),
            bdo_instrument_id=gm_to_bdo_instrument(
                gm_program,
                is_percussion,
            ),
            color=presentation.color(index),
            effect_settings_placeholder={
                "track_effects_enabled": False,
                "note_effects_reserved": True,
            },
            performance_controls=(
                [dict(control) for control in controls[index]]
                if index < len(controls)
                else []
            ),
        ))
    return MidiImportData(
        bpm=int(bpm),
        time_signature=int(time_signature),
        time_signature_denominator=read_midi_time_signature_denominator(path),
        tempo_changes=int(tempo_changes),
        lyric_events=tuple(
            dict(event) for event in lyric_events if isinstance(event, Mapping)
        ),
        tracks=tuple(tracks),
        # Velocity policies are now visible note data and cannot run again at
        # export time.
        conversion_settings=settings.with_updates(
            velocity_mode=VELOCITY_MODE_PRESERVE
        ),
    )


__all__ = [
    "EditorImportError",
    "EditorImportErrorCode",
    "MidiImportData",
    "MidiMeterReadError",
    "TrackImportPresentation",
    "prepare_midi_import",
    "read_midi_time_signature_denominator",
    "tracks_from_bdo_snapshot",
    "tracks_from_project_payload",
]
