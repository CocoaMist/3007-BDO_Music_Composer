"""Stable host-owned contract for trusted local optimizer bundles."""

from __future__ import annotations

from collections import Counter
from copy import copy
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable


PLUGIN_API_VERSION = 1
DERIVED_TRACK_NOTE_BUDGET = 680
VALID_SCOPES = frozenset({"global", "single_track"})


class OptimizationIntensity(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    DEEP = "deep"


ALL_INTENSITIES = tuple(item.value for item in OptimizationIntensity)


@dataclass(frozen=True, slots=True)
class NoteSnapshot:
    pitch: int
    vel: int
    start: float
    dur: float
    ntype: int


@dataclass(frozen=True, slots=True)
class TrackSnapshot:
    track_id: int
    notes: tuple[NoteSnapshot, ...]
    gm_program: int
    is_percussion: bool
    display_name: str
    instrument_id: int
    articulation_type: int | None = None
    marnian_synth_mode: str = "basic"


@dataclass(frozen=True, slots=True)
class OptimizationLimits:
    derived_track_note_budget: int = DERIVED_TRACK_NOTE_BUDGET
    export_track_note_limit: int = 730
    max_song_notes: int = 50_000
    max_song_beats: int = 20_000


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    source_fingerprint: str
    tracks: tuple[TrackSnapshot, ...]
    bpm: int
    time_sig: int
    target_track_ids: frozenset[int]
    supported_pitches: dict[int, frozenset[int]]
    supported_articulations: dict[int, tuple[tuple[int, str], ...]]
    intensity: OptimizationIntensity
    scope: str
    limits: OptimizationLimits = field(default_factory=OptimizationLimits)
    valid_instrument_ids: frozenset[int] = frozenset()
    drum_instrument_id: int = 0x0D


@dataclass(frozen=True, slots=True)
class ReplaceTrackNotes:
    track_id: int
    before: tuple[NoteSnapshot, ...]
    after: tuple[NoteSnapshot, ...]
    category: str = "optimization"
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ReplaceNote:
    track_id: int
    note_index: int
    before: NoteSnapshot
    after: NoteSnapshot
    category: str = "optimization"
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class InsertNote:
    track_id: int
    note_index: int
    note: NoteSnapshot
    category: str = "optimization"
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DeleteNote:
    track_id: int
    note_index: int
    before: NoteSnapshot
    category: str = "optimization"
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SetTrackInstrument:
    track_id: int
    before: int
    after: int
    category: str = "orchestration"
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CreateTrack:
    name: str
    instrument_id: int
    is_percussion: bool
    notes: tuple[NoteSnapshot, ...]
    source_track_id: int | None = None
    category: str = "arrangement"
    confidence: float = 1.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EffectChange:
    reverb: int
    delay: int
    chorus: tuple[int, int, int] | None
    reason: str = ""


NoteOperation = ReplaceTrackNotes | ReplaceNote | InsertNote | DeleteNote
OptimizationOperation = NoteOperation | SetTrackInstrument | CreateTrack | EffectChange


@dataclass(frozen=True, slots=True)
class OptimizationPreview:
    source_fingerprint: str
    algorithm_id: str
    algorithm_version: str
    operations: tuple[OptimizationOperation, ...] = ()
    summary: str = ""
    details: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    deterministic: bool = True


@dataclass(frozen=True, slots=True)
class PluginEnvironment:
    bundle_root: Path

    def resource_path(self, relative_path: str) -> Path:
        candidate = (self.bundle_root / relative_path).resolve()
        if self.bundle_root.resolve() not in candidate.parents and candidate != self.bundle_root.resolve():
            raise ValueError("plugin resource path escapes bundle root")
        return candidate


@runtime_checkable
class OptimizerPlugin(Protocol):
    def analyse(self, request: OptimizationRequest, environment: PluginEnvironment) -> OptimizationPreview: ...


class InvalidOptimizationPreview(ValueError):
    """The plugin returned an unsafe, stale, or malformed preview."""


def note_snapshot(note: object) -> NoteSnapshot:
    return NoteSnapshot(
        int(note.pitch), int(note.vel), float(note.start), float(note.dur), int(note.ntype)
    )


def track_snapshot(track: object) -> TrackSnapshot:
    return TrackSnapshot(
        track_id=int(track.track_id),
        notes=tuple(note_snapshot(note) for note in track.notes),
        gm_program=int(getattr(track, "gm_program", 0)),
        is_percussion=bool(getattr(track, "is_percussion", False)),
        display_name=str(getattr(track, "display_name", f"Track {track.track_id}")),
        instrument_id=int(getattr(track, "instrument_id", getattr(track, "bdo_instrument_id", 0))),
        articulation_type=getattr(track, "articulation_type", None),
        marnian_synth_mode=str(getattr(track, "marnian_synth_mode", "basic")),
    )


def snapshot_tracks(tracks: Sequence[object]) -> tuple[TrackSnapshot, ...]:
    return tuple(track_snapshot(track) for track in tracks)


def tracks_fingerprint(tracks: Sequence[object]) -> str:
    payload = [
        {
            "track_id": track.track_id,
            "instrument_id": track.instrument_id,
            "is_percussion": track.is_percussion,
            "notes": [[note.pitch, note.vel, note.start, note.dur, note.ntype] for note in track.notes],
        }
        for track in snapshot_tracks(tracks)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_request(
    tracks: Sequence[object],
    bpm: int,
    time_sig: int,
    target_track_ids: frozenset[int],
    supported_pitches: dict[int, frozenset[int]],
    supported_articulations: dict[int, Sequence[tuple[int, str]]],
    intensity: OptimizationIntensity,
    scope: str,
    *,
    valid_instrument_ids: frozenset[int] | None = None,
    drum_instrument_id: int = 0x0D,
    limits: OptimizationLimits | None = None,
) -> OptimizationRequest:
    if scope not in VALID_SCOPES:
        raise ValueError(f"invalid optimization scope: {scope}")
    snapshots = snapshot_tracks(tracks)
    limits = limits or OptimizationLimits()
    track_ids = [track.track_id for track in snapshots]
    if len(track_ids) != len(set(track_ids)):
        raise InvalidOptimizationPreview("optimizer input contains duplicate track IDs")
    target_ids = frozenset(int(item) for item in target_track_ids)
    if not target_ids.issubset(track_ids):
        raise InvalidOptimizationPreview("optimizer target scope references an unknown track")
    note_total = sum(len(track.notes) for track in snapshots)
    if note_total > limits.max_song_notes:
        raise InvalidOptimizationPreview("song exceeds the optimizer note limit")
    end_ms = max(
        (note.start + note.dur for track in snapshots for note in track.notes),
        default=0.0,
    )
    song_beats = end_ms * max(1, int(bpm)) / 60_000.0
    if song_beats > limits.max_song_beats:
        raise InvalidOptimizationPreview("song exceeds the optimizer beat limit")
    allowed_instruments = frozenset(
        int(item) for item in (
            valid_instrument_ids
            if valid_instrument_ids is not None
            else set(supported_pitches).union(track.instrument_id for track in snapshots)
        )
    )
    return OptimizationRequest(
        source_fingerprint=tracks_fingerprint(snapshots),
        tracks=snapshots,
        bpm=max(1, int(bpm)),
        time_sig=max(1, int(time_sig)),
        target_track_ids=target_ids,
        supported_pitches={int(key): frozenset(int(pitch) for pitch in value) for key, value in supported_pitches.items()},
        supported_articulations={
            int(key): tuple((int(ntype), str(label)) for ntype, label in value)
            for key, value in supported_articulations.items()
        },
        intensity=OptimizationIntensity(intensity),
        scope=scope,
        limits=limits,
        valid_instrument_ids=allowed_instruments,
        drum_instrument_id=int(drum_instrument_id),
    )


def preview_from_tracks(
    request: OptimizationRequest,
    proposed_tracks: Sequence[object],
    *,
    algorithm_id: str,
    algorithm_version: str,
    summary: str,
    details: Sequence[str] = (),
    diagnostics: Sequence[str] = (),
) -> OptimizationPreview:
    before = {track.track_id: track for track in request.tracks}
    after = {track.track_id: track_snapshot(track) for track in proposed_tracks}
    operations: list[OptimizationOperation] = []
    for track_id, source in before.items():
        target = after.get(track_id)
        if target is None:
            raise InvalidOptimizationPreview("plugins may not remove complete source tracks")
        if source.notes != target.notes:
            operations.append(ReplaceTrackNotes(track_id, source.notes, target.notes))
        if source.instrument_id != target.instrument_id:
            operations.append(SetTrackInstrument(track_id, source.instrument_id, target.instrument_id))
    for target in proposed_tracks:
        track_id = int(target.track_id)
        if track_id in before:
            continue
        operations.append(CreateTrack(
            name=str(getattr(target, "display_name", "Optimizer Suggestion")),
            instrument_id=int(getattr(target, "instrument_id", getattr(target, "bdo_instrument_id", 0))),
            is_percussion=bool(getattr(target, "is_percussion", False)),
            notes=tuple(note_snapshot(note) for note in target.notes),
            source_track_id=None,
        ))
    return OptimizationPreview(
        source_fingerprint=request.source_fingerprint,
        algorithm_id=algorithm_id,
        algorithm_version=algorithm_version,
        operations=tuple(operations),
        summary=str(summary),
        details=tuple(str(item) for item in details),
        diagnostics=tuple(str(item) for item in diagnostics),
    )


def _validate_note(note: NoteSnapshot, instrument_id: int, percussion: bool,
                   supported_pitches: dict[int, frozenset[int]],
                   supported_articulations: dict[int, tuple[tuple[int, str], ...]],
                   preserved_ntypes: frozenset[int] = frozenset()) -> None:
    if not 0 <= note.pitch <= 127 or not 1 <= note.vel <= 127 or not 0 <= note.ntype <= 255:
        raise InvalidOptimizationPreview("note pitch, velocity, or ntype is outside the wire range")
    if not math.isfinite(note.start) or not math.isfinite(note.dur) or note.start < 0 or note.dur <= 0:
        raise InvalidOptimizationPreview("note timing must be finite, non-negative, and non-zero")
    if percussion and (not 48 <= note.pitch <= 64 or note.ntype != 99):
        raise InvalidOptimizationPreview("derived drum notes require BDO pitch 48..64 and ntype=99")
    supported = supported_pitches.get(instrument_id)
    if supported and note.pitch not in supported:
        raise InvalidOptimizationPreview(
            f"pitch {note.pitch} is unsupported for BDO instrument {instrument_id}"
        )
    valid_ntypes = {0, *(ntype for ntype, _label in supported_articulations.get(instrument_id, ()))}
    if not percussion and note.ntype not in valid_ntypes and note.ntype not in preserved_ntypes:
        raise InvalidOptimizationPreview(
            f"ntype {note.ntype} is unsupported for BDO instrument {instrument_id}"
        )


def _validate_instrument(request: OptimizationRequest, instrument_id: int, percussion: bool) -> None:
    if request.valid_instrument_ids and instrument_id not in request.valid_instrument_ids:
        raise InvalidOptimizationPreview(f"unknown BDO instrument ID: {instrument_id}")
    if percussion != (instrument_id == request.drum_instrument_id):
        raise InvalidOptimizationPreview(
            "drum tracks must use the canonical BDO drum-set instrument"
        )


def _materialize_note_operations(
    source: TrackSnapshot,
    operations: Sequence[OptimizationOperation],
) -> tuple[NoteSnapshot, ...]:
    note_ops = [item for item in operations if isinstance(item, (ReplaceTrackNotes, ReplaceNote, InsertNote, DeleteNote))]
    batches = [item for item in note_ops if isinstance(item, ReplaceTrackNotes)]
    if batches:
        if len(batches) != 1 or len(note_ops) != 1:
            raise InvalidOptimizationPreview("whole-track and indexed note operations may not be mixed")
        if batches[0].before != source.notes:
            raise InvalidOptimizationPreview(f"stale note replacement for track {source.track_id}")
        return batches[0].after
    replacements: dict[int, NoteSnapshot] = {}
    deletes: set[int] = set()
    inserts: dict[int, list[NoteSnapshot]] = {}
    for operation in note_ops:
        index = int(operation.note_index)
        if isinstance(operation, InsertNote):
            if not 0 <= index <= len(source.notes):
                raise InvalidOptimizationPreview(f"insert index outside track {source.track_id}")
            inserts.setdefault(index, []).append(operation.note)
            continue
        if not 0 <= index < len(source.notes):
            raise InvalidOptimizationPreview(f"note index outside track {source.track_id}")
        if operation.before != source.notes[index]:
            raise InvalidOptimizationPreview(f"stale indexed note operation for track {source.track_id}")
        if index in replacements or index in deletes:
            raise InvalidOptimizationPreview(f"duplicate indexed note operation for track {source.track_id}")
        if isinstance(operation, ReplaceNote):
            replacements[index] = operation.after
        else:
            deletes.add(index)
    materialized: list[NoteSnapshot] = []
    for index in range(len(source.notes) + 1):
        materialized.extend(inserts.get(index, ()))
        if index < len(source.notes) and index not in deletes:
            materialized.append(replacements.get(index, source.notes[index]))
    return tuple(materialized)


def validate_preview(request: OptimizationRequest, preview: OptimizationPreview) -> None:
    if preview.source_fingerprint != request.source_fingerprint:
        raise InvalidOptimizationPreview("preview source fingerprint does not match its request")
    source = {track.track_id: track for track in request.tracks}
    final_instruments = {track.track_id: track.instrument_id for track in request.tracks}
    note_operations: dict[int, list[OptimizationOperation]] = {}
    for operation in preview.operations:
        if isinstance(operation, (ReplaceTrackNotes, ReplaceNote, InsertNote, DeleteNote)):
            note_operations.setdefault(operation.track_id, []).append(operation)
    replacement_notes = {
        track_id: _materialize_note_operations(source[track_id], operations)
        for track_id, operations in note_operations.items() if track_id in source
    }
    instrument_writes: set[int] = set()
    for operation in preview.operations:
        if isinstance(operation, SetTrackInstrument):
            if operation.track_id in instrument_writes:
                raise InvalidOptimizationPreview("a preview may set each source instrument only once")
            instrument_writes.add(operation.track_id)
            final_instruments[operation.track_id] = operation.after
    source_note_total = sum(len(track.notes) for track in request.tracks)
    proposed_note_total = source_note_total
    effect_writes = 0
    for operation in preview.operations:
        if isinstance(operation, EffectChange):
            effect_writes += 1
            if effect_writes > 1:
                raise InvalidOptimizationPreview("a preview may contain only one global effect change")
            if request.scope != "global":
                raise InvalidOptimizationPreview("single-track optimization may not write global effects")
            values = (operation.reverb, operation.delay, *(operation.chorus or (0, 0, 0)))
            if any(not 0 <= int(value) <= 127 for value in values):
                raise InvalidOptimizationPreview("effect values must be in [0, 127]")
            continue
        if isinstance(operation, CreateTrack):
            if request.scope != "global":
                raise InvalidOptimizationPreview("single-track optimization may not create tracks")
            if not operation.notes:
                raise InvalidOptimizationPreview("derived tracks must contain at least one note")
            if operation.source_track_id is not None and operation.source_track_id not in source:
                raise InvalidOptimizationPreview("derived track references an unknown source track")
            _validate_instrument(request, operation.instrument_id, operation.is_percussion)
            for note in operation.notes:
                _validate_note(
                    note, operation.instrument_id, operation.is_percussion,
                    request.supported_pitches, request.supported_articulations,
                )
            proposed_note_total += len(operation.notes)
            continue
        track = source.get(operation.track_id)
        if track is None or operation.track_id not in request.target_track_ids:
            raise InvalidOptimizationPreview(f"operation writes outside target scope: {operation.track_id}")
        if isinstance(operation, SetTrackInstrument):
            if operation.before != track.instrument_id:
                raise InvalidOptimizationPreview(f"stale instrument replacement for track {operation.track_id}")
            _validate_instrument(request, operation.after, track.is_percussion)
            for note in replacement_notes.get(track.track_id, track.notes):
                _validate_note(
                    note, operation.after, track.is_percussion,
                    request.supported_pitches, request.supported_articulations,
                )
    for track_id, notes in replacement_notes.items():
        track = source[track_id]
        proposed_note_total += len(notes) - len(track.notes)
        preserved_ntypes = frozenset(note.ntype for note in track.notes)
        valid_ntypes = {0, *(ntype for ntype, _label in request.supported_articulations.get(final_instruments[track_id], ()))}
        before_invalid = Counter(note.ntype for note in track.notes if note.ntype not in valid_ntypes)
        after_invalid = Counter(note.ntype for note in notes if note.ntype not in valid_ntypes)
        if any(count > before_invalid[ntype] for ntype, count in after_invalid.items()):
            raise InvalidOptimizationPreview("preview may not duplicate or invent unsupported manual articulations")
        for note in notes:
            _validate_note(
                note, final_instruments[track_id], track.is_percussion,
                request.supported_pitches, request.supported_articulations, preserved_ntypes,
            )
    if proposed_note_total > max(source_note_total, request.limits.max_song_notes):
        raise InvalidOptimizationPreview("preview exceeds the host song-note limit")


def apply_preview(
    tracks: Sequence[object],
    request: OptimizationRequest,
    preview: OptimizationPreview,
) -> tuple[list, EffectChange | None]:
    if tracks_fingerprint(tracks) != request.source_fingerprint:
        raise InvalidOptimizationPreview("the editor changed after analysis; analyse again")
    validate_preview(request, preview)
    result = [copy(track) for track in tracks]
    for track in result:
        track.notes = list(track.notes)
    by_id = {int(track.track_id): track for track in result}
    effects = None
    next_id = max(by_id, default=0) + 1
    prototype = result[0] if result else None
    note_prototype = next((note for track in result for note in track.notes), None)
    source_by_id = {track.track_id: track for track in request.tracks}
    note_operations: dict[int, list[OptimizationOperation]] = {}
    for operation in preview.operations:
        if isinstance(operation, (ReplaceTrackNotes, ReplaceNote, InsertNote, DeleteNote)):
            note_operations.setdefault(operation.track_id, []).append(operation)
    for track_id, operations in note_operations.items():
        target = by_id[track_id]
        prototype_note = target.notes[0] if target.notes else note_prototype
        materialized = _materialize_note_operations(source_by_id[track_id], operations)
        if prototype_note is None and materialized:
            raise InvalidOptimizationPreview("cannot materialize notes without a host Note prototype")
        target.notes = [
            prototype_note._replace(
                pitch=note.pitch, vel=note.vel, start=note.start, dur=note.dur, ntype=note.ntype
            )
            for note in materialized
        ]
    for operation in preview.operations:
        if isinstance(operation, (ReplaceTrackNotes, ReplaceNote, InsertNote, DeleteNote)):
            continue
        if isinstance(operation, SetTrackInstrument):
            by_id[operation.track_id].bdo_instrument_id = operation.after
        elif isinstance(operation, CreateTrack):
            if prototype is None or note_prototype is None:
                raise InvalidOptimizationPreview("cannot create a derived track without a source track")
            source_prototype = by_id.get(operation.source_track_id, prototype)
            source_note_prototype = next(iter(source_prototype.notes), note_prototype)
            chunks = [
                operation.notes[index:index + request.limits.derived_track_note_budget]
                for index in range(0, len(operation.notes), request.limits.derived_track_note_budget)
            ]
            for part, chunk in enumerate(chunks, 1):
                derived = copy(source_prototype)
                derived.track_id = next_id
                next_id += 1
                suffix = f" {part}/{len(chunks)}" if len(chunks) > 1 else ""
                derived.display_name = f"{operation.name}{suffix}"
                derived.gm_program = 0
                derived.is_percussion = operation.is_percussion
                derived.bdo_instrument_id = operation.instrument_id
                derived.articulation_type = None
                derived.marnian_synth_mode = "basic"
                derived.notes_optimized = True
                derived.notes = [
                    source_note_prototype._replace(
                        pitch=note.pitch, vel=note.vel, start=note.start, dur=note.dur, ntype=note.ntype
                    )
                    for note in chunk
                ]
                result.append(derived)
        elif isinstance(operation, EffectChange):
            effects = operation
    return result, effects
