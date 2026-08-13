"""Qt-free Track/Clip arrangement edits over canonical editor notes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
from collections.abc import Mapping, Sequence
from uuid import uuid4

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import (
    ArrangementClipState,
    TrackState,
)


MIN_CLIP_DURATION_MS = 10.0


@dataclass(frozen=True, slots=True)
class ClipBounds:
    start_ms: float
    end_ms: float

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


@dataclass(frozen=True, slots=True)
class ClipTrackUpdate:
    track_id: int
    notes: tuple[Note, ...]
    performance_controls: tuple[dict, ...]
    source_note_records: tuple[tuple, ...]
    source_group_index: int | None
    clip_start_ms: float | None
    clip_end_ms: float | None
    arrangement_clips: tuple[ArrangementClipState, ...]


@dataclass(frozen=True, slots=True)
class ClipEditPlan:
    updates: tuple[ClipTrackUpdate, ...]
    selected_track_id: int
    selected_clip_id: str = ""


@dataclass(frozen=True, slots=True)
class ClipClipboard:
    clip: ArrangementClipState
    notes: tuple[Note, ...]
    performance_controls: tuple[dict, ...]
    source_note_records: tuple[tuple, ...]


def _new_clip_id(track_id: int) -> str:
    return f"track-{int(track_id)}-{uuid4().hex[:12]}"


def copy_clip(track: TrackState, clip_id: str) -> ClipClipboard:
    clip = clip_by_id(track, clip_id)
    belongs = lambda value: (
        clip.content_start_ms <= float(value) < clip.content_end_ms
    )
    return ClipClipboard(
        clip,
        tuple(deepcopy(note) for note in track.notes if belongs(note.start)),
        tuple(
            deepcopy(value) for value in track.performance_controls
            if belongs(value.get("time", -1.0))
        ),
        tuple(
            deepcopy(tuple(value)) for value in track.bdo_source_note_records
            if belongs(value[2])
        ),
    )


def plan_clip_paste(
    target: TrackState,
    clipboard: ClipClipboard,
    *,
    start_ms: float,
) -> ClipEditPlan:
    """Paste a detached Clip instance at a new timeline position."""

    start = max(0.0, float(start_ms))
    duration = clipboard.clip.end_ms - clipboard.clip.start_ms
    end = start + duration
    if overlapping_clip_ids(target, start_ms=start, end_ms=end):
        raise ValueError("pasted clip overlaps an existing clip")
    existing_content_end = max(
        (
            clip.content_end_ms for clip in track_clips(target)
        ),
        default=max((_note_end(note) for note in target.notes), default=0.0),
    )
    content_base = max(0.0, existing_content_end + MIN_CLIP_DURATION_MS)
    source_base = clipboard.clip.content_start_ms
    source_window_start, _source_window_end = _clip_source_window(clipboard.clip)
    source_shift = content_base - source_base
    pasted_clip = ArrangementClipState(
        _new_clip_id(target.track_id),
        start,
        end,
        content_base,
        content_base + (
            clipboard.clip.content_end_ms - clipboard.clip.content_start_ms
        ),
        start - (source_window_start + source_shift),
    )
    notes = tuple(
        note._replace(start=float(note.start) + source_shift)
        for note in clipboard.notes
    )
    controls = tuple(
        _mapping_time(value, lambda time: time + source_shift)
        for value in clipboard.performance_controls
    )
    records = tuple(
        _record_time(value, lambda time: time + source_shift, 1.0)
        for value in clipboard.source_note_records
    )
    update = _base_update(target)
    return ClipEditPlan((replace(
        update,
        notes=tuple(sorted((*update.notes, *notes), key=lambda note: note.start)),
        performance_controls=tuple(sorted(
            (*update.performance_controls, *controls),
            key=lambda value: float(value.get("time", 0.0)),
        )),
        source_note_records=tuple(sorted(
            (*update.source_note_records, *records),
            key=lambda value: float(value[2]),
        )),
        source_group_index=None,
        arrangement_clips=(*update.arrangement_clips, pasted_clip),
    ),), int(target.track_id), pasted_clip.clip_id)


def _note_end(note: object, scale: float = 1.0) -> float:
    return float(note.start) + max(
        1.0, float(getattr(note, "dur", 0.0)) * scale
    )


def track_clips(track: TrackState) -> tuple[ArrangementClipState, ...]:
    explicit = tuple(getattr(track, "arrangement_clips", ()) or ())
    if explicit:
        return tuple(sorted(explicit, key=lambda clip: (clip.start_ms, clip.clip_id)))
    if not track.notes:
        return ()
    scale = float(getattr(track, "duration_scale", 1.0))
    content_start = min(float(note.start) for note in track.notes)
    content_end = max(_note_end(note, scale) for note in track.notes)
    raw_start = getattr(track, "clip_start_ms", None)
    raw_end = getattr(track, "clip_end_ms", None)
    start = content_start if raw_start is None else max(0.0, float(raw_start))
    end = content_end if raw_end is None else float(raw_end)
    end = max(start + MIN_CLIP_DURATION_MS, end)
    return (ArrangementClipState(
        clip_id=f"track-{int(getattr(track, 'track_id', -1))}-main",
        start_ms=start,
        end_ms=end,
        content_start_ms=content_start,
        content_end_ms=max(content_start + MIN_CLIP_DURATION_MS, content_end),
    ),)


def track_clip_bounds(track: TrackState) -> ClipBounds | None:
    clips = track_clips(track)
    if not clips:
        return None
    return ClipBounds(
        min(clip.start_ms for clip in clips),
        max(clip.end_ms for clip in clips),
    )


def clip_by_id(track: TrackState, clip_id: str) -> ArrangementClipState:
    clips = track_clips(track)
    if not clip_id and len(clips) == 1:
        return clips[0]
    for clip in clips:
        if clip.clip_id == clip_id:
            return clip
    raise ValueError("arrangement clip is no longer available")


def _note_with_times(note: object, *, start: float, duration: float) -> object:
    replace_method = getattr(note, "_replace", None)
    if callable(replace_method):
        return replace_method(start=start, dur=duration)
    result = deepcopy(note)
    setattr(result, "start", start)
    setattr(result, "dur", duration)
    return result


def _note_belongs_to_clip(note: object, clip: ArrangementClipState) -> bool:
    onset = float(note.start)
    return clip.content_start_ms <= onset < clip.content_end_ms


def _clip_source_window(clip: ArrangementClipState) -> tuple[float, float]:
    return (
        clip.start_ms - clip.time_offset_ms,
        clip.end_ms - clip.time_offset_ms,
    )


def clip_for_note(
    track: TrackState, note: object
) -> ArrangementClipState | None:
    return next(
        (clip for clip in track_clips(track) if _note_belongs_to_clip(note, clip)),
        None,
    )


def reconcile_track_clips_after_note_edit(
    track: TrackState, notes: Sequence[object]
) -> tuple[ArrangementClipState, ...]:
    """Keep newly created/moved notes attached to the nearest existing clip."""

    clips = list(track_clips(track))
    if not clips or not notes:
        return tuple(clips)
    assignments: list[list[object]] = [[] for _clip in clips]
    for note in notes:
        onset = float(note.start)
        matching = next((
            index for index, clip in enumerate(clips)
            if clip.content_start_ms <= onset < clip.content_end_ms
        ), None)
        if matching is None:
            matching = min(
                range(len(clips)),
                key=lambda index: min(
                    abs(onset - clips[index].content_start_ms),
                    abs(onset - clips[index].content_end_ms),
                ),
            )
        assignments[matching].append(note)
    reconciled: list[ArrangementClipState] = []
    for clip, assigned in zip(clips, assignments):
        if not assigned:
            reconciled.append(clip)
            continue
        content_start = min(float(note.start) for note in assigned)
        content_end = max(_note_end(note) for note in assigned)
        reconciled.append(replace(
            clip,
            start_ms=min(clip.start_ms, content_start),
            end_ms=max(clip.end_ms, content_end),
            content_start_ms=content_start,
            content_end_ms=max(content_start + MIN_CLIP_DURATION_MS, content_end),
        ))
    return tuple(reconciled)


def project_track_notes(track: TrackState) -> tuple[Note, ...]:
    """Project every independent clip without rewriting authored note content."""

    scale = float(getattr(track, "duration_scale", 1.0))
    projected: list[Note] = []
    for clip in track_clips(track):
        source_start, source_end = _clip_source_window(clip)
        for note in track.notes:
            if not _note_belongs_to_clip(note, clip):
                continue
            start = max(float(note.start), source_start)
            end = min(_note_end(note, scale), source_end)
            if end - start >= 1.0:
                projected.append(_note_with_times(
                    note,
                    start=start + clip.time_offset_ms,
                    duration=end - start,
                ))
    return tuple(sorted(
        projected,
        key=lambda note: (note.start, note.pitch, note.dur, note.vel, note.ntype),
    ))


def project_track_source_records(track: TrackState) -> tuple[tuple, ...]:
    projected: list[tuple] = []
    scale = float(getattr(track, "duration_scale", 1.0))
    for clip in track_clips(track):
        source_start, source_end = _clip_source_window(clip)
        for record in track.bdo_source_note_records:
            if len(record) < 6:
                continue
            onset = float(record[2])
            if not clip.content_start_ms <= onset < clip.content_end_ms:
                continue
            start = max(onset, source_start)
            end = min(
                onset + max(1.0, float(record[3]) * scale), source_end
            )
            if end - start < 1.0:
                continue
            value = list(deepcopy(tuple(record)))
            value[2], value[3] = start + clip.time_offset_ms, end - start
            projected.append(tuple(value))
    return tuple(sorted(projected, key=lambda value: (float(value[2]), int(value[0]))))


def _mapping_time(value: Mapping, transform) -> dict:
    result = deepcopy(dict(value))
    if "time" in result:
        result["time"] = transform(float(result["time"]))
    return result


def _record_time(record: Sequence[object], transform, duration_scale: float) -> tuple:
    if len(record) < 6:
        raise ValueError("BDO source note records must contain six values")
    result = list(deepcopy(tuple(record)))
    result[2] = transform(float(result[2]))
    result[3] = max(MIN_CLIP_DURATION_MS, float(result[3]) * duration_scale)
    return tuple(result)


def _base_update(track: TrackState) -> ClipTrackUpdate:
    return ClipTrackUpdate(
        int(track.track_id),
        tuple(deepcopy(track.notes)),
        tuple(deepcopy(track.performance_controls)),
        tuple(deepcopy(track.bdo_source_note_records)),
        track.bdo_source_group_index,
        None,
        None,
        track_clips(track),
    )


def _replace_clip(
    clips: Sequence[ArrangementClipState],
    clip_id: str,
    replacement: ArrangementClipState,
) -> tuple[ArrangementClipState, ...]:
    return tuple(replacement if clip.clip_id == clip_id else clip for clip in clips)


def _overlaps_other_clip(
    clips: Sequence[ArrangementClipState], candidate: ArrangementClipState,
    *, ignored_id: str = "",
) -> bool:
    return any(
        clip.clip_id != ignored_id
        and candidate.start_ms < clip.end_ms
        and clip.start_ms < candidate.end_ms
        for clip in clips
    )


def overlapping_clip_ids(
    track: TrackState,
    *,
    start_ms: float,
    end_ms: float,
    ignored_id: str = "",
) -> tuple[str, ...]:
    """Return stable IDs of Clips intersecting the proposed display range."""

    start, end = float(start_ms), float(end_ms)
    if not all(math.isfinite(value) for value in (start, end)) or end <= start:
        return ()
    return tuple(
        clip.clip_id
        for clip in track_clips(track)
        if clip.clip_id != ignored_id
        and start < clip.end_ms
        and clip.start_ms < end
    )


def plan_clip_edit(
    source: TrackState,
    *,
    mode: str,
    new_start_ms: float,
    new_end_ms: float,
    target: TrackState | None = None,
    clip_id: str = "",
    merge_overlaps: bool = False,
) -> ClipEditPlan:
    clip = clip_by_id(source, clip_id)
    start, end = float(new_start_ms), float(new_end_ms)
    if not all(math.isfinite(value) for value in (start, end)):
        raise ValueError("clip bounds must be finite")
    if start < 0.0 or end - start < MIN_CLIP_DURATION_MS:
        raise ValueError("clip duration is too short")
    destination = target or source

    if mode in {"resize_start", "resize_end"}:
        if destination is not source:
            raise ValueError("resizing cannot change the destination track")
        resized = replace(clip, start_ms=start, end_ms=end)
        update = _base_update(source)
        return ClipEditPlan((replace(
            update,
            arrangement_clips=_replace_clip(
                update.arrangement_clips, clip.clip_id, resized
            ),
        ),), int(source.track_id), clip.clip_id)
    if mode != "move":
        raise ValueError(f"unsupported clip edit mode: {mode}")

    delta = start - clip.start_ms
    moved_clip = replace(
        clip,
        start_ms=start,
        end_ms=end,
        time_offset_ms=clip.time_offset_ms + delta,
    )
    source_clips = track_clips(source)
    target_clips = source_clips if destination is source else track_clips(destination)
    overlap_ids = overlapping_clip_ids(
        destination,
        start_ms=moved_clip.start_ms,
        end_ms=moved_clip.end_ms,
        ignored_id=clip.clip_id if destination is source else "",
    )
    if overlap_ids and not merge_overlaps:
        raise ValueError("clip merge requires confirmation")
    if overlap_ids:
        overlapping = tuple(
            value for value in target_clips if value.clip_id in overlap_ids
        )
        moved_clip = replace(
            moved_clip,
            start_ms=min(moved_clip.start_ms, *(value.start_ms for value in overlapping)),
            end_ms=max(moved_clip.end_ms, *(value.end_ms for value in overlapping)),
            content_start_ms=min(
                moved_clip.content_start_ms,
                *(value.content_start_ms for value in overlapping),
            ),
            content_end_ms=max(
                moved_clip.content_end_ms,
                *(value.content_end_ms for value in overlapping),
            ),
        )

    def in_content(value: float) -> bool:
        return clip.content_start_ms <= value < clip.content_end_ms

    shared_source = any(
        value.clip_id != clip.clip_id
        and value.content_start_ms == clip.content_start_ms
        and value.content_end_ms == clip.content_end_ms
        for value in source_clips
    )

    moved_notes = tuple(
        deepcopy(note) for note in source.notes if in_content(float(note.start))
    )
    kept_notes = tuple(
        deepcopy(note) for note in source.notes
        if shared_source or not in_content(float(note.start))
    )
    moved_controls = tuple(
        deepcopy(value)
        for value in source.performance_controls
        if in_content(float(value.get("time", -1.0)))
    )
    kept_controls = tuple(
        deepcopy(value) for value in source.performance_controls
        if shared_source or not in_content(float(value.get("time", -1.0)))
    )
    moved_records = tuple(
        deepcopy(tuple(value))
        for value in source.bdo_source_note_records
        if in_content(float(value[2]))
    )
    kept_records = tuple(
        deepcopy(value) for value in source.bdo_source_note_records
        if shared_source or not in_content(float(value[2]))
    )

    if destination is source:
        update = _base_update(source)
        remaining_clips = tuple(
            value for value in source_clips
            if value.clip_id not in overlap_ids
        )
        return ClipEditPlan((replace(
            update,
            arrangement_clips=_replace_clip(
                remaining_clips, clip.clip_id, moved_clip
            ),
        ),), int(source.track_id), clip.clip_id)

    destination_update = _base_update(destination)
    destination_content_end = max(
        (value.content_end_ms for value in destination_update.arrangement_clips),
        default=max(
            (_note_end(note) for note in destination_update.notes),
            default=0.0,
        ),
    )
    content_shift = (
        max(0.0, destination_content_end + MIN_CLIP_DURATION_MS)
        - clip.content_start_ms
    )
    moved_clip = replace(
        moved_clip,
        content_start_ms=moved_clip.content_start_ms + content_shift,
        content_end_ms=moved_clip.content_end_ms + content_shift,
        time_offset_ms=moved_clip.time_offset_ms - content_shift,
    )
    moved_notes = tuple(
        note._replace(start=float(note.start) + content_shift)
        for note in moved_notes
    )
    moved_controls = tuple(
        _mapping_time(value, lambda time: time + content_shift)
        for value in moved_controls
    )
    moved_records = tuple(
        _record_time(value, lambda time: time + content_shift, 1.0)
        for value in moved_records
    )
    if overlap_ids:
        moved_preview = deepcopy(source)
        moved_preview.notes = list(moved_notes)
        moved_preview.arrangement_clips = [moved_clip]
        flattened_notes = tuple(sorted(
            (*project_track_notes(destination), *project_track_notes(moved_preview)),
            key=lambda note: (note.start, note.pitch, note.dur),
        ))
        merged_start = moved_clip.start_ms
        merged_end = moved_clip.end_ms
        moved_clip = ArrangementClipState(
            moved_clip.clip_id,
            merged_start,
            merged_end,
            merged_start,
            merged_end,
            0.0,
        )
        destination_update = replace(
            destination_update,
            notes=flattened_notes,
            performance_controls=(),
            source_note_records=(),
        )
        moved_notes = ()
        moved_controls = ()
        moved_records = ()
    source_update = replace(
        _base_update(source),
        notes=kept_notes,
        performance_controls=kept_controls,
        source_note_records=kept_records,
        source_group_index=None,
        arrangement_clips=tuple(value for value in source_clips if value.clip_id != clip.clip_id),
    )
    destination_update = replace(
        destination_update,
        notes=tuple(sorted((*destination_update.notes, *moved_notes), key=lambda note: note.start)),
        performance_controls=tuple(sorted((*destination_update.performance_controls, *moved_controls), key=lambda value: float(value.get("time", 0.0)))),
        source_note_records=tuple(sorted((*destination_update.source_note_records, *moved_records), key=lambda value: float(value[2]))),
        source_group_index=None,
        arrangement_clips=(
            *(
                value for value in destination_update.arrangement_clips
                if value.clip_id not in overlap_ids
            ),
            moved_clip,
        ),
    )
    return ClipEditPlan(
        (source_update, destination_update),
        int(destination.track_id),
        moved_clip.clip_id,
    )


def plan_clip_split(
    track: TrackState, *, clip_id: str, split_ms: float
) -> ClipEditPlan:
    clip = clip_by_id(track, clip_id)
    split = float(split_ms)
    if not math.isfinite(split) or not (
        clip.start_ms + MIN_CLIP_DURATION_MS
        <= split
        <= clip.end_ms - MIN_CLIP_DURATION_MS
    ):
        raise ValueError("razor position must be inside the clip")
    left_id, right_id = clip.clip_id, _new_clip_id(track.track_id)
    left = replace(
        clip,
        clip_id=left_id,
        end_ms=split,
    )
    right = replace(
        clip,
        clip_id=right_id,
        start_ms=split,
    )
    update = replace(
        _base_update(track),
        arrangement_clips=tuple(
            value for original in track_clips(track)
            for value in ((left, right) if original.clip_id == clip.clip_id else (original,))
        ),
    )
    return ClipEditPlan((update,), int(track.track_id), right_id)


def plan_clip_create(
    track: TrackState,
    *,
    start_ms: float,
    duration_ms: float,
    pitch: int,
    velocity: int = 90,
    ntype: int = 0,
) -> ClipEditPlan:
    start = max(0.0, float(start_ms))
    duration = max(MIN_CLIP_DURATION_MS, float(duration_ms))
    end = start + duration
    clip = ArrangementClipState(
        _new_clip_id(track.track_id), start, end, start, end
    )
    if _overlaps_other_clip(track_clips(track), clip):
        raise ValueError("new clip overlaps an existing clip")
    note = Note(int(pitch), int(velocity), start, duration, int(ntype))
    update = replace(
        _base_update(track),
        notes=tuple(sorted((*track.notes, note), key=lambda value: (value.start, value.pitch))),
        source_group_index=None,
        arrangement_clips=(*track_clips(track), clip),
    )
    return ClipEditPlan((update,), int(track.track_id), clip.clip_id)


__all__ = [
    "ClipBounds",
    "ClipEditPlan",
    "ClipClipboard",
    "ClipTrackUpdate",
    "MIN_CLIP_DURATION_MS",
    "clip_by_id",
    "copy_clip",
    "clip_for_note",
    "plan_clip_create",
    "plan_clip_edit",
    "plan_clip_paste",
    "plan_clip_split",
    "overlapping_clip_ids",
    "project_track_notes",
    "project_track_source_records",
    "reconcile_track_clips_after_note_edit",
    "track_clip_bounds",
    "track_clips",
]
