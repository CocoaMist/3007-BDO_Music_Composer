"""Qt-free Track/Clip arrangement edits over canonical editor notes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import math
from collections.abc import Mapping, Sequence
from uuid import uuid4

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import (
    ArrangementClipState,
    TrackState,
)


MIN_CLIP_DURATION_MS = 10.0
DEFAULT_EMPTY_CLIP_DURATION_MS = 3_000.0


@dataclass(frozen=True, slots=True)
class ClipBounds:
    start_ms: float
    end_ms: float

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


class ClipEditError(ValueError):
    """Stable failure raised when a Clip draft cannot be published safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


@dataclass(frozen=True, slots=True)
class ClipEditorScope:
    """Immutable timeline/content boundary shared by every Clip editor path."""

    track_id: int
    clip_id: str
    timeline_start_ms: float
    timeline_end_ms: float
    content_start_ms: float
    content_end_ms: float
    time_offset_ms: float
    resize_end_limit_ms: float | None
    fingerprint: str

    @property
    def duration_ms(self) -> float:
        return self.timeline_end_ms - self.timeline_start_ms

    def contains_note(self, note: object) -> bool:
        try:
            start = float(note.start)
            end = start + float(note.dur)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False
        return (
            math.isfinite(start)
            and math.isfinite(end)
            and self.timeline_start_ms <= start
            and start < end
            and end <= self.timeline_end_ms + 1e-6
        )


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


def default_empty_clip(
    track_id: int, *, duration_ms: float
) -> ArrangementClipState:
    """Create the stable initial Clip owned by a newly authored track."""

    duration = max(DEFAULT_EMPTY_CLIP_DURATION_MS, float(duration_ms))
    if not math.isfinite(duration):
        raise ValueError("default clip duration must be finite")
    return ArrangementClipState(
        f"track-{int(track_id)}-main",
        0.0,
        duration,
        0.0,
        duration,
    )


def copy_clip(track: TrackState, clip_id: str) -> ClipClipboard:
    clip = clip_by_id(track, clip_id)
    clips = track_clips(track)
    belongs = lambda value: (
        clip.content_start_ms <= float(value) < clip.content_end_ms
    )
    return ClipClipboard(
        clip,
        tuple(
            deepcopy(note) for note in track.notes
            if _note_belongs_to_clip(
                track, note, clip, clips=clips
            )
        ),
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
        clipboard.clip.display_name,
        clipboard.clip.color,
        clipboard.clip.velocity_percent,
        tuple(clipboard.clip.velocity_baseline_a),
        tuple(clipboard.clip.velocity_baseline_b),
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


def plan_clip_duplicate(track: TrackState, *, clip_id: str) -> ClipEditPlan:
    """Duplicate one Clip immediately after its current right edge."""

    clip = clip_by_id(track, clip_id)
    return plan_clip_paste(
        track,
        copy_clip(track, clip_id),
        start_ms=float(clip.end_ms),
    )


def plan_clip_metadata(
    track: TrackState,
    *,
    clip_id: str,
    display_name: str | None = None,
    color: str | None = None,
) -> ClipEditPlan:
    """Update presentation metadata without touching authored MIDI content."""

    clip = clip_by_id(track, clip_id)
    name = clip.display_name if display_name is None else str(display_name).strip()
    resolved_color = clip.color if color is None else str(color).strip()
    updated_clip = replace(
        clip,
        display_name=name[:120],
        color=resolved_color[:32],
    )
    update = replace(
        _base_update(track),
        arrangement_clips=tuple(
            updated_clip if value.clip_id == clip.clip_id else value
            for value in track_clips(track)
        ),
    )
    return ClipEditPlan((update,), int(track.track_id), clip.clip_id)


def _apply_update_to_preview(
    track: TrackState, update: ClipTrackUpdate
) -> None:
    track.notes = list(update.notes)
    track.performance_controls = list(update.performance_controls)
    track.bdo_source_note_records = update.source_note_records
    track.bdo_source_group_index = update.source_group_index
    track.duration_scale = 1.0
    track.clip_start_ms = update.clip_start_ms
    track.clip_end_ms = update.clip_end_ms
    track.arrangement_clips = list(update.arrangement_clips)


def plan_clip_repeat(
    track: TrackState, *, clip_id: str, additional_copies: int
) -> ClipEditPlan:
    """Materialize repeated Clips so preview, undo and export stay identical."""

    count = int(additional_copies)
    if not 1 <= count <= 64:
        raise ValueError("repeat count must be between 1 and 64")
    working = deepcopy(track)
    selected_id = str(clip_id)
    for _index in range(count):
        plan = plan_clip_duplicate(working, clip_id=selected_id)
        _apply_update_to_preview(working, plan.updates[0])
        selected_id = plan.selected_clip_id
    return ClipEditPlan(
        (_base_update(working),), int(track.track_id), selected_id
    )


def plan_clip_crop_right(track: TrackState, *, clip_id: str) -> ClipEditPlan:
    """Move only the right boundary to the last audible note edge."""

    clip = clip_by_id(track, clip_id)
    bounds = clip_projected_note_bounds(track, clip_id)
    if bounds is None:
        raise ValueError("empty clip has no note content to crop")
    new_end = max(
        clip.start_ms + MIN_CLIP_DURATION_MS,
        min(clip.end_ms, bounds.end_ms),
    )
    if math.isclose(new_end, clip.end_ms, abs_tol=1e-6):
        raise ValueError("clip already ends at its last note")
    return plan_clip_edit(
        track,
        target=track,
        mode="resize_end",
        new_start_ms=clip.start_ms,
        new_end_ms=new_end,
        clip_id=clip_id,
    )


def plan_clips_consolidate(
    track: TrackState, *, clip_ids: Sequence[str]
) -> ClipEditPlan:
    """Flatten two or more Clips into one exported-equivalent Clip."""

    requested = tuple(dict.fromkeys(str(value) for value in clip_ids))
    if len(requested) < 2:
        raise ValueError("at least two clips are required")
    requested_set = set(requested)
    selected = tuple(
        clip for clip in track_clips(track)
        if clip.clip_id in requested_set
    )
    if len(selected) != len(requested):
        raise ValueError("one or more clips are no longer available")
    start_ms = min(clip.start_ms for clip in selected)
    end_ms = max(clip.end_ms for clip in selected)
    projected_notes, projected_controls, projected_records = _clip_projection(
        track, selected
    )
    first = min(selected, key=lambda clip: (clip.start_ms, clip.clip_id))
    merged_clip, merged_notes, merged_controls, merged_records = (
        _detached_merged_content(
            track,
            clip_id=first.clip_id,
            start_ms=start_ms,
            end_ms=end_ms,
            notes=projected_notes,
            controls=projected_controls,
            records=projected_records,
        )
    )
    merged_clip = replace(
        merged_clip,
        display_name=first.display_name,
        color=first.color,
    )

    def selected_content_time(value: float) -> bool:
        try:
            time_ms = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return any(
            clip.content_start_ms <= time_ms < clip.content_end_ms
            for clip in selected
        )

    kept_notes = tuple(
        note for note in track.notes
        if not selected_content_time(note.start)
    )
    kept_controls = tuple(
        value for value in track.performance_controls
        if not selected_content_time(value.get("time", -1.0))
    )
    kept_records = tuple(
        value for value in track.bdo_source_note_records
        if not selected_content_time(value[2])
    )
    update = replace(
        _base_update(track),
        notes=tuple(sorted(
            (*kept_notes, *merged_notes), key=lambda note: note.start
        )),
        performance_controls=tuple(sorted(
            (*kept_controls, *merged_controls),
            key=lambda value: float(value.get("time", 0.0)),
        )),
        source_note_records=tuple(sorted(
            (*kept_records, *merged_records),
            key=lambda value: float(value[2]),
        )),
        source_group_index=None,
        arrangement_clips=tuple(sorted(
            (
                *(clip for clip in track_clips(track)
                  if clip.clip_id not in requested_set),
                merged_clip,
            ),
            key=lambda clip: (clip.start_ms, clip.clip_id),
        )),
    )
    return ClipEditPlan(
        (update,), int(track.track_id), merged_clip.clip_id
    )


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
    raise ClipEditError("clip_missing", "arrangement clip is no longer available")


def _note_with_times(note: object, *, start: float, duration: float) -> object:
    replace_method = getattr(note, "_replace", None)
    if callable(replace_method):
        return replace_method(start=start, dur=duration)
    result = deepcopy(note)
    setattr(result, "start", start)
    setattr(result, "dur", duration)
    return result


def _note_belongs_to_clip(
    track: TrackState,
    note: object,
    clip: ArrangementClipState,
    *,
    clips: Sequence[ArrangementClipState] | None = None,
) -> bool:
    """Resolve content ownership, including uniquely recoverable old orphans."""

    onset = float(note.start)
    if clip.content_start_ms <= onset < clip.content_end_ms:
        return True
    all_clips = tuple(clips) if clips is not None else track_clips(track)
    if any(
        value.content_start_ms <= onset < value.content_end_ms
        for value in all_clips
    ):
        return False
    source_candidates = tuple(
        value for value in all_clips
        if (
            value.start_ms - value.time_offset_ms
            <= onset
            < value.end_ms - value.time_offset_ms
        )
    )
    return (
        len(source_candidates) == 1
        and source_candidates[0].clip_id == clip.clip_id
    )


def _clip_source_window(clip: ArrangementClipState) -> tuple[float, float]:
    return (
        clip.start_ms - clip.time_offset_ms,
        clip.end_ms - clip.time_offset_ms,
    )


def clip_for_note(
    track: TrackState, note: object
) -> ArrangementClipState | None:
    clips = track_clips(track)
    return next(
        (
            clip for clip in clips
            if _note_belongs_to_clip(
                track, note, clip, clips=clips
            )
        ),
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


def project_track_note_refs(track: TrackState) -> tuple[tuple[int, Note], ...]:
    """Project Clips while retaining each authored note's stable list index."""

    scale = float(getattr(track, "duration_scale", 1.0))
    projected: list[tuple[int, Note]] = []
    clips = track_clips(track)
    if len(clips) == 1 and math.isclose(scale, 1.0, abs_tol=1e-12):
        clip = clips[0]
        source_start, source_end = _clip_source_window(clip)
        if math.isclose(clip.time_offset_ms, 0.0, abs_tol=1e-12) and all(
            clip.content_start_ms <= float(note.start) < clip.content_end_ms
            and source_start <= float(note.start)
            and _note_end(note) <= source_end
            for note in track.notes
        ):
            # The overwhelmingly common identity Clip needs neither tuple
            # cloning nor per-note namedtuple replacement.  Keeping the
            # stable sort still protects imported tracks with unordered data.
            return tuple(sorted(
                enumerate(track.notes),
                key=lambda item: (
                    float(getattr(item[1], "start", 0.0)),
                    int(getattr(item[1], "pitch", 0)),
                    float(getattr(item[1], "dur", 0.0)),
                    int(getattr(item[1], "vel", 0)),
                    int(getattr(item[1], "ntype", 0)),
                    item[0],
                ),
            ))
    for clip in clips:
        source_start, source_end = _clip_source_window(clip)
        for note_index, note in enumerate(track.notes):
            if not _note_belongs_to_clip(
                track, note, clip, clips=clips
            ):
                continue
            start = max(float(note.start), source_start)
            end = min(_note_end(note, scale), source_end)
            if end - start >= 1.0:
                projected.append((note_index, _note_with_times(
                    note, start=start + clip.time_offset_ms, duration=end - start,
                )))
    return tuple(sorted(
        projected,
        key=lambda item: (
            item[1].start, item[1].pitch, item[1].dur,
            item[1].vel, item[1].ntype, item[0],
        ),
    ))


def project_track_notes(track: TrackState) -> tuple[Note, ...]:
    """Project every independent clip without rewriting authored note content."""

    return tuple(note for _index, note in project_track_note_refs(track))


def _clip_editor_note_pairs(
    track: TrackState, clip: ArrangementClipState
) -> tuple[tuple[int, Note], ...]:
    """Return authored indexes plus the exact visible Clip projection."""

    source_start, source_end = _clip_source_window(clip)
    clips = track_clips(track)
    projected: list[tuple[int, Note]] = []
    for note_index, note in enumerate(track.notes):
        if not _note_belongs_to_clip(
            track, note, clip, clips=clips
        ):
            continue
        visible_start = max(float(note.start), source_start)
        visible_end = min(_note_end(note), source_end)
        if visible_end - visible_start < 1.0:
            continue
        projected.append((note_index, _note_with_times(
            note,
            start=visible_start + clip.time_offset_ms,
            duration=visible_end - visible_start,
        )))
    return tuple(sorted(
        projected,
        key=lambda item: (
            item[1].start, item[1].pitch, item[1].dur,
            item[1].vel, item[1].ntype, item[0],
        ),
    ))


def clip_editor_notes(
    track: TrackState, clip_id: str
) -> tuple[Note, ...]:
    """Project editable onsets in one Clip without exposing sibling content."""

    clip = clip_by_id(track, clip_id)
    return tuple(note for _index, note in _clip_editor_note_pairs(track, clip))


def clip_authored_note_indices(
    track: TrackState, clip_id: str
) -> tuple[int, ...]:
    """Return authored note indexes in the same stable order as Clip editing."""

    clip = clip_by_id(track, clip_id)
    return tuple(index for index, _note in _clip_editor_note_pairs(track, clip))


def clip_authored_note_index_map(
    track: TrackState, clip_ids: Sequence[str] | None = None
) -> dict[str, tuple[int, ...]]:
    """Resolve several Clip note-index sets with one shared ownership pass."""

    clips = track_clips(track)
    requested = None if clip_ids is None else {str(value) for value in clip_ids}
    selected = tuple(
        clip for clip in clips
        if requested is None or str(clip.clip_id) in requested
    )
    pairs: dict[str, list[tuple[int, Note]]] = {
        str(clip.clip_id): [] for clip in selected
    }
    for note_index, note in enumerate(track.notes):
        for clip in selected:
            if not _note_belongs_to_clip(track, note, clip, clips=clips):
                continue
            source_start, source_end = _clip_source_window(clip)
            visible_start = max(float(note.start), source_start)
            visible_end = min(_note_end(note), source_end)
            if visible_end - visible_start < 1.0:
                continue
            projected = _note_with_times(
                note,
                start=visible_start + clip.time_offset_ms,
                duration=visible_end - visible_start,
            )
            pairs[str(clip.clip_id)].append((note_index, projected))
    return {
        clip_id: tuple(
            index for index, _note in sorted(
                values,
                key=lambda item: (
                    item[1].start, item[1].pitch, item[1].dur,
                    item[1].vel, item[1].ntype, item[0],
                ),
            )
        )
        for clip_id, values in pairs.items()
    }


def clip_projected_note_bounds(
    track: TrackState, clip_id: str
) -> ClipBounds | None:
    """Return the occupied projected timeline interval inside one Clip."""

    notes = clip_editor_notes(track, clip_id)
    if not notes:
        return None
    return ClipBounds(
        min(float(note.start) for note in notes),
        max(_note_end(note) for note in notes),
    )


def clip_edit_fingerprint(track: TrackState, clip_id: str) -> str:
    """Identify the exact Clip/note state used to open a note-editor draft."""

    clip = clip_by_id(track, clip_id)
    clips = track_clips(track)
    payload = (
        tuple((
            clip.clip_id,
            clip.start_ms,
            clip.end_ms,
            clip.content_start_ms,
            clip.content_end_ms,
            clip.time_offset_ms,
        )),
        tuple(
            tuple(note)
            for note in track.notes
            if _note_belongs_to_clip(
                track, note, clip, clips=clips
            )
        ),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def clip_editor_scope(track: TrackState, clip_id: str) -> ClipEditorScope:
    """Capture the one authoritative boundary used by a Clip editor session."""

    clip = clip_by_id(track, clip_id)
    return ClipEditorScope(
        track_id=int(track.track_id),
        clip_id=clip.clip_id,
        timeline_start_ms=float(clip.start_ms),
        timeline_end_ms=float(clip.end_ms),
        content_start_ms=float(clip.content_start_ms),
        content_end_ms=float(clip.content_end_ms),
        time_offset_ms=float(clip.time_offset_ms),
        resize_end_limit_ms=min(
            (
                float(value.start_ms)
                for value in track_clips(track)
                if value.clip_id != clip.clip_id
                and value.start_ms >= clip.end_ms - 1e-6
            ),
            default=None,
        ),
        fingerprint=clip_edit_fingerprint(track, clip.clip_id),
    )


def plan_clip_note_edit(
    track: TrackState,
    *,
    clip_id: str,
    notes: Sequence[Note],
) -> ClipEditPlan:
    """Replace only the authored note-onsets visible in one Clip window."""

    clip = clip_by_id(track, clip_id)
    source_start, source_end = _clip_source_window(clip)
    projected = tuple(notes)
    if any(
        not math.isfinite(float(value))
        for note in projected
        for value in (note.start, note.dur)
    ):
        raise ClipEditError("invalid_timing", "clip notes must have finite timing")
    if any(
        not (
            clip.start_ms <= float(note.start)
            and float(note.start) + float(note.dur) <= clip.end_ms + 1e-6
            and float(note.dur) > 0.0
        )
        for note in projected
    ):
        raise ClipEditError(
            "note_out_of_scope", "edited notes must remain inside the clip"
        )
    baseline_pairs = _clip_editor_note_pairs(track, clip)
    if projected == tuple(note for _index, note in baseline_pairs):
        baseline_source_notes = tuple(
            track.notes[source_index]
            for source_index, _visible in baseline_pairs
        )
        repaired_clip = replace(
            clip,
            content_start_ms=min(
                clip.content_start_ms,
                *(float(note.start) for note in baseline_source_notes),
            ),
            content_end_ms=max(
                clip.content_end_ms,
                *(_note_end(note) for note in baseline_source_notes),
            ),
        ) if baseline_source_notes else clip
        update = _base_update(track)
        if repaired_clip != clip:
            update = replace(
                update,
                arrangement_clips=_replace_clip(
                    update.arrangement_clips,
                    clip.clip_id,
                    repaired_clip,
                ),
            )
        return ClipEditPlan(
            (update,), int(track.track_id), clip.clip_id
        )
    unmatched_baseline = list(baseline_pairs)
    preserved_indices: set[int] = set()
    replacement: list[Note] = []
    for note in projected:
        match = next((
            index for index, (_source_index, visible) in enumerate(unmatched_baseline)
            if visible == note
        ), None)
        if match is not None:
            source_index, _visible = unmatched_baseline.pop(match)
            preserved_indices.add(source_index)
            continue
        replacement.append(
            note._replace(start=float(note.start) - clip.time_offset_ms)
        )
    replaced_indices = {
        source_index for source_index, _visible in baseline_pairs
        if source_index not in preserved_indices
    }
    replacement_tuple = tuple(replacement)
    clips = track_clips(track)
    target_content_indices = {
        note_index
        for note_index, note in enumerate(track.notes)
        if _note_belongs_to_clip(
            track, note, clip, clips=clips
        )
    }
    materialized_source_notes = tuple(
        deepcopy(note)
        for note_index, note in enumerate(track.notes)
        if note_index in target_content_indices
        and note_index not in replaced_indices
    ) + replacement_tuple
    desired_content_start = min(
        (
            float(note.start)
            for note in materialized_source_notes
        ),
        default=clip.content_start_ms,
    )
    desired_content_end = max(
        (
            _note_end(note)
            for note in materialized_source_notes
        ),
        default=clip.content_end_ms,
    )
    desired_content_start = min(
        clip.content_start_ms, desired_content_start
    )
    desired_content_end = max(clip.content_end_ms, desired_content_end)
    other_clips = tuple(
        value for value in clips
        if value.clip_id != clip.clip_id
    )
    content_overlaps_sibling = any(
        desired_content_start < value.content_end_ms
        and value.content_start_ms < desired_content_end
        for value in other_clips
    )
    current_content_shared = any(
        clip.content_start_ms < value.content_end_ms
        and value.content_start_ms < clip.content_end_ms
        for value in other_clips
    )
    if content_overlaps_sibling:
        existing_content_end = max(
            (
                value.content_end_ms for value in clips
            ),
            default=max(
                (_note_end(note) for note in track.notes), default=0.0
            ),
        )
        content_shift = (
            max(0.0, existing_content_end + MIN_CLIP_DURATION_MS)
            - desired_content_start
        )
        detached_clip = replace(
            clip,
            content_start_ms=desired_content_start + content_shift,
            content_end_ms=desired_content_end + content_shift,
            time_offset_ms=clip.time_offset_ms - content_shift,
        )
        detached_notes = tuple(
            note._replace(start=float(note.start) + content_shift)
            for note in materialized_source_notes
        )
        controls = tuple(
            _mapping_time(value, lambda time: time + content_shift)
            for value in track.performance_controls
            if clip.content_start_ms
            <= float(value.get("time", -1.0))
            < clip.content_end_ms
        )
        records = tuple(
            _record_time(value, lambda time: time + content_shift, 1.0)
            for value in track.bdo_source_note_records
            if clip.content_start_ms <= float(value[2]) < clip.content_end_ms
        )
        base_notes = tuple(track.notes) if current_content_shared else tuple(
            note for note_index, note in enumerate(track.notes)
            if note_index not in target_content_indices
        )
        base_controls = (
            tuple(track.performance_controls)
            if current_content_shared
            else tuple(
                value for value in track.performance_controls
                if not (
                    clip.content_start_ms
                    <= float(value.get("time", -1.0))
                    < clip.content_end_ms
                )
            )
        )
        base_records = (
            tuple(track.bdo_source_note_records)
            if current_content_shared
            else tuple(
                value for value in track.bdo_source_note_records
                if not (
                    clip.content_start_ms
                    <= float(value[2])
                    < clip.content_end_ms
                )
            )
        )
        update = replace(
            _base_update(track),
            notes=tuple(sorted(
                (*base_notes, *detached_notes),
                key=lambda note: (
                    note.start, note.pitch, note.dur, note.vel, note.ntype
                ),
            )),
            performance_controls=tuple(sorted(
                (*base_controls, *controls),
                key=lambda value: float(value.get("time", 0.0)),
            )),
            source_note_records=tuple(sorted(
                (*base_records, *records),
                key=lambda value: float(value[2]),
            )),
            source_group_index=None,
            arrangement_clips=_replace_clip(
                track_clips(track), clip.clip_id, detached_clip
            ),
        )
        return ClipEditPlan(
            (update,), int(track.track_id), detached_clip.clip_id
        )
    kept = tuple(
        deepcopy(note)
        for note_index, note in enumerate(track.notes)
        if note_index not in replaced_indices
    )
    update = replace(
        _base_update(track),
        notes=tuple(sorted(
            (*kept, *replacement_tuple),
            key=lambda note: (note.start, note.pitch, note.dur, note.vel, note.ntype),
        )),
        source_group_index=None,
        arrangement_clips=_replace_clip(
            track_clips(track),
            clip.clip_id,
            replace(
                clip,
                content_start_ms=desired_content_start,
                content_end_ms=desired_content_end,
            ),
        ),
    )
    return ClipEditPlan((update,), int(track.track_id), clip.clip_id)


def project_track_performance_controls(track: TrackState) -> tuple[dict, ...]:
    """Project point-in-time MIDI controls through independent Clip windows."""

    projected: list[dict] = []
    for clip in track_clips(track):
        source_start, source_end = _clip_source_window(clip)
        for control in track.performance_controls:
            try:
                time_ms = float(control.get("time", -1.0))
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                clip.content_start_ms <= time_ms < clip.content_end_ms
                and source_start <= time_ms < source_end
            ):
                projected.append(_mapping_time(
                    control,
                    lambda value, offset=clip.time_offset_ms: value + offset,
                ))
    return tuple(sorted(
        projected,
        key=lambda value: float(value.get("time", 0.0)),
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


def _clip_projection(
    track: TrackState,
    clips: Sequence[ArrangementClipState],
) -> tuple[tuple[Note, ...], tuple[dict, ...], tuple[tuple, ...]]:
    preview = deepcopy(track)
    preview.arrangement_clips = list(clips)
    return (
        project_track_notes(preview),
        project_track_performance_controls(preview),
        project_track_source_records(preview),
    )


def _detached_merged_content(
    track: TrackState,
    *,
    clip_id: str,
    start_ms: float,
    end_ms: float,
    notes: Sequence[Note],
    controls: Sequence[Mapping],
    records: Sequence[Sequence[object]],
) -> tuple[
    ArrangementClipState, tuple[Note, ...], tuple[dict, ...], tuple[tuple, ...]
]:
    """Store one flattened merge away from every existing content window."""

    content_base = max(
        (value.content_end_ms for value in track_clips(track)),
        default=max((_note_end(note) for note in track.notes), default=0.0),
    ) + MIN_CLIP_DURATION_MS
    shift = content_base - start_ms
    merged_clip = ArrangementClipState(
        clip_id,
        start_ms,
        end_ms,
        content_base,
        content_base + (end_ms - start_ms),
        start_ms - content_base,
    )
    return (
        merged_clip,
        tuple(note._replace(start=float(note.start) + shift) for note in notes),
        tuple(_mapping_time(value, lambda time: time + shift) for value in controls),
        tuple(_record_time(value, lambda time: time + shift, 1.0) for value in records),
    )


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


def _content_payload_ceiling(track: TrackState) -> float:
    candidates = [
        *(float(value.content_end_ms) for value in track_clips(track)),
        *(_note_end(note) for note in track.notes),
    ]
    for value in track.performance_controls:
        try:
            candidates.append(float(value.get("time", 0.0)))
        except (TypeError, ValueError, OverflowError):
            continue
    for value in track.bdo_source_note_records:
        if len(value) < 4:
            continue
        try:
            candidates.append(float(value[2]) + max(1.0, float(value[3])))
        except (TypeError, ValueError, OverflowError):
            continue
    return max(candidates, default=0.0)


def _resize_clip_right_edge(
    track: TrackState,
    clip: ArrangementClipState,
    *,
    end_ms: float,
) -> ClipEditPlan:
    """Move only a Clip's right boundary, preserving all authored payload."""

    new_end = float(end_ms)
    desired_content_end = new_end - float(clip.time_offset_ms)
    resized = replace(
        clip,
        end_ms=new_end,
        content_end_ms=desired_content_end,
    )
    if _overlaps_other_clip(
        track_clips(track), resized, ignored_id=clip.clip_id
    ):
        raise ClipEditError(
            "clip_resize_overlap",
            "the resized clip would overlap another clip",
        )
    occupied = clip_projected_note_bounds(track, clip.clip_id)
    if occupied is not None and new_end < occupied.end_ms - 1e-6:
        raise ClipEditError(
            "clip_resize_over_notes",
            "the right clip edge cannot cross an existing note",
        )
    clips = track_clips(track)
    other_clips = tuple(value for value in clips if value.clip_id != clip.clip_id)
    content_conflict = any(
        clip.content_start_ms < value.content_end_ms
        and value.content_start_ms < desired_content_end
        for value in other_clips
    ) or any(
        clip.content_end_ms <= float(note.start) < desired_content_end
        and not _note_belongs_to_clip(track, note, clip, clips=clips)
        for note in track.notes
    ) or any(
        clip.content_end_ms
        <= float(value.get("time", -1.0))
        < desired_content_end
        for value in track.performance_controls
    ) or any(
        len(value) >= 3
        and clip.content_end_ms <= float(value[2]) < desired_content_end
        for value in track.bdo_source_note_records
    )
    update = _base_update(track)
    if content_conflict and desired_content_end > clip.content_end_ms:
        # The newly exposed empty region must not claim unrelated legacy data.
        # Materialize this Clip in a private source range while keeping every
        # projected note/control at its existing timeline time.
        content_start = _content_payload_ceiling(track) + MIN_CLIP_DURATION_MS
        content_end = content_start + (new_end - clip.start_ms)
        new_offset = clip.start_ms - content_start
        visible_pairs = _clip_editor_note_pairs(track, clip)
        visible_indices = {index for index, _note in visible_pairs}
        materialized_notes = tuple(
            note._replace(start=float(note.start) - new_offset)
            for _index, note in visible_pairs
        )
        source_start, source_end = _clip_source_window(clip)
        shared_content = any(
            value.content_start_ms < clip.content_end_ms
            and clip.content_start_ms < value.content_end_ms
            for value in other_clips
        )
        kept_notes = (
            tuple(deepcopy(track.notes))
            if shared_content
            else tuple(
                deepcopy(note)
                for index, note in enumerate(track.notes)
                if index not in visible_indices
            )
        )
        visible_controls = tuple(
            _mapping_time(
                value,
                lambda time: time + clip.time_offset_ms - new_offset,
            )
            for value in track.performance_controls
            if (
                clip.content_start_ms
                <= float(value.get("time", -1.0))
                < clip.content_end_ms
                and source_start
                <= float(value.get("time", -1.0))
                < source_end
            )
        )
        kept_controls = (
            tuple(deepcopy(track.performance_controls))
            if shared_content
            else tuple(
                deepcopy(value)
                for value in track.performance_controls
                if not (
                    clip.content_start_ms
                    <= float(value.get("time", -1.0))
                    < clip.content_end_ms
                )
            )
        )
        visible_records = tuple(
            _record_time(
                value,
                lambda time: time + clip.time_offset_ms - new_offset,
                1.0,
            )
            for value in track.bdo_source_note_records
            if (
                len(value) >= 6
                and clip.content_start_ms
                <= float(value[2])
                < clip.content_end_ms
                and source_start <= float(value[2]) < source_end
            )
        )
        kept_records = (
            tuple(deepcopy(track.bdo_source_note_records))
            if shared_content
            else tuple(
                deepcopy(tuple(value))
                for value in track.bdo_source_note_records
                if not (
                    len(value) >= 3
                    and clip.content_start_ms
                    <= float(value[2])
                    < clip.content_end_ms
                )
            )
        )
        resized = replace(
            resized,
            content_start_ms=content_start,
            content_end_ms=content_end,
            time_offset_ms=new_offset,
        )
        update = replace(
            update,
            notes=tuple(sorted(
                (*kept_notes, *materialized_notes),
                key=lambda note: (
                    note.start, note.pitch, note.dur, note.vel, note.ntype
                ),
            )),
            performance_controls=tuple(sorted(
                (*kept_controls, *visible_controls),
                key=lambda value: float(value.get("time", 0.0)),
            )),
            source_note_records=tuple(sorted(
                (*kept_records, *visible_records),
                key=lambda value: float(value[2]),
            )),
            source_group_index=None,
        )
    return ClipEditPlan(
        (replace(
            update,
            arrangement_clips=_replace_clip(
                update.arrangement_clips, clip.clip_id, resized
            ),
        ),),
        int(track.track_id),
        resized.clip_id,
    )


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
        if mode == "resize_start" or not math.isclose(
            start, clip.start_ms, abs_tol=1e-6
        ):
            raise ClipEditError(
                "clip_left_anchor_fixed",
                "clip resizing keeps the left edge fixed",
            )
        return _resize_clip_right_edge(source, clip, end_ms=end)
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
        if overlap_ids:
            moved_preview = deepcopy(source)
            moved_preview.arrangement_clips = [moved_clip]
            overlap_projection = _clip_projection(source, overlapping)
            moved_projection = _clip_projection(moved_preview, (moved_clip,))
            merged_clip, merged_notes, merged_controls, merged_records = (
                _detached_merged_content(
                    source,
                    clip_id=clip.clip_id,
                    start_ms=moved_clip.start_ms,
                    end_ms=moved_clip.end_ms,
                    notes=(*overlap_projection[0], *moved_projection[0]),
                    controls=(*overlap_projection[1], *moved_projection[1]),
                    records=(*overlap_projection[2], *moved_projection[2]),
                )
            )
            return ClipEditPlan((replace(
                update,
                notes=tuple(sorted(
                    (*update.notes, *merged_notes), key=lambda note: note.start
                )),
                performance_controls=tuple(sorted(
                    (*update.performance_controls, *merged_controls),
                    key=lambda value: float(value.get("time", 0.0)),
                )),
                source_note_records=tuple(sorted(
                    (*update.source_note_records, *merged_records),
                    key=lambda value: float(value[2]),
                )),
                source_group_index=None,
                arrangement_clips=(
                    *(
                        value for value in source_clips
                        if value.clip_id not in {*overlap_ids, clip.clip_id}
                    ),
                    merged_clip,
                ),
            ),), int(source.track_id), merged_clip.clip_id)
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
        moved_preview.performance_controls = list(moved_controls)
        moved_preview.bdo_source_note_records = tuple(moved_records)
        moved_preview.arrangement_clips = [moved_clip]
        overlap_projection = _clip_projection(destination, overlapping)
        moved_projection = _clip_projection(moved_preview, (moved_clip,))
        moved_clip, moved_notes, moved_controls, moved_records = (
            _detached_merged_content(
                destination,
                clip_id=moved_clip.clip_id,
                start_ms=moved_clip.start_ms,
                end_ms=moved_clip.end_ms,
                notes=(*overlap_projection[0], *moved_projection[0]),
                controls=(*overlap_projection[1], *moved_projection[1]),
                records=(*overlap_projection[2], *moved_projection[2]),
            )
        )
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
    existing_content_end = max(
        (value.content_end_ms for value in track_clips(track)),
        default=max((_note_end(note) for note in track.notes), default=0.0),
    )
    content_shift = (
        max(0.0, existing_content_end + MIN_CLIP_DURATION_MS)
        - clip.content_start_ms
    )
    right = replace(
        clip,
        clip_id=right_id,
        start_ms=split,
        content_start_ms=clip.content_start_ms + content_shift,
        content_end_ms=clip.content_end_ms + content_shift,
        time_offset_ms=clip.time_offset_ms - content_shift,
    )
    belongs = lambda value: (
        clip.content_start_ms <= float(value) < clip.content_end_ms
    )
    duplicated_notes = tuple(
        deepcopy(note)._replace(start=float(note.start) + content_shift)
        for note in track.notes if belongs(note.start)
    )
    duplicated_controls = tuple(
        _mapping_time(value, lambda time: time + content_shift)
        for value in track.performance_controls
        if belongs(value.get("time", -1.0))
    )
    duplicated_records = tuple(
        _record_time(value, lambda time: time + content_shift, 1.0)
        for value in track.bdo_source_note_records
        if belongs(value[2])
    )
    update = replace(
        _base_update(track),
        notes=tuple(sorted(
            (*track.notes, *duplicated_notes), key=lambda note: note.start
        )),
        performance_controls=tuple(sorted(
            (*track.performance_controls, *duplicated_controls),
            key=lambda value: float(value.get("time", 0.0)),
        )),
        source_note_records=tuple(sorted(
            (*track.bdo_source_note_records, *duplicated_records),
            key=lambda value: float(value[2]),
        )),
        source_group_index=None,
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
) -> ClipEditPlan:
    """Create a genuinely empty Clip with a useful initial edit window."""

    start = max(0.0, float(start_ms))
    duration = max(DEFAULT_EMPTY_CLIP_DURATION_MS, float(duration_ms))
    end = start + duration
    clip = ArrangementClipState(
        _new_clip_id(track.track_id), start, end, start, end
    )
    if _overlaps_other_clip(track_clips(track), clip):
        raise ValueError("new clip overlaps an existing clip")
    update = replace(
        _base_update(track),
        source_group_index=None,
        arrangement_clips=(*track_clips(track), clip),
    )
    return ClipEditPlan((update,), int(track.track_id), clip.clip_id)


def plan_clip_delete(track: TrackState, *, clip_id: str) -> ClipEditPlan:
    """Delete one Clip and only content not owned by a surviving sibling."""

    clip = clip_by_id(track, clip_id)
    clips = track_clips(track)
    survivors = tuple(
        value for value in clips if value.clip_id != clip.clip_id
    )

    def owned_by_survivor(time_ms: float) -> bool:
        return any(
            value.content_start_ms <= float(time_ms) < value.content_end_ms
            for value in survivors
        )

    def control_is_exclusive(value: Mapping) -> bool:
        try:
            time_ms = float(value.get("time", -1.0))
        except (TypeError, ValueError):
            return False
        return (
            clip.content_start_ms <= time_ms < clip.content_end_ms
            and not owned_by_survivor(time_ms)
        )

    def record_is_exclusive(value: Sequence[object]) -> bool:
        if len(value) < 6:
            return False
        try:
            time_ms = float(value[2])
        except (TypeError, ValueError):
            return False
        return (
            clip.content_start_ms <= time_ms < clip.content_end_ms
            and not owned_by_survivor(time_ms)
        )

    kept_notes = tuple(
        deepcopy(note)
        for note in track.notes
        if not (
            _note_belongs_to_clip(track, note, clip, clips=clips)
            and not owned_by_survivor(float(note.start))
        )
    )
    kept_controls = tuple(
        deepcopy(value)
        for value in track.performance_controls
        if not control_is_exclusive(value)
    )
    kept_records = tuple(
        deepcopy(tuple(value))
        for value in track.bdo_source_note_records
        if not record_is_exclusive(value)
    )
    update = replace(
        _base_update(track),
        notes=kept_notes,
        performance_controls=kept_controls,
        source_note_records=kept_records,
        source_group_index=None,
        arrangement_clips=survivors,
    )
    selected_clip_id = survivors[0].clip_id if survivors else ""
    return ClipEditPlan(
        (update,), int(track.track_id), selected_clip_id
    )


def plan_clips_delete(
    track: TrackState, *, clip_ids: Sequence[str]
) -> ClipEditPlan:
    """Delete several Clips from one track as one immutable transaction."""

    requested = tuple(dict.fromkeys(str(value) for value in clip_ids))
    if not requested:
        raise ValueError("at least one clip must be selected")
    available = {clip.clip_id for clip in track_clips(track)}
    missing = tuple(value for value in requested if value not in available)
    if missing:
        raise ClipEditError(
            "clip_missing",
            f"selected clips are unavailable: {', '.join(missing)}",
        )

    working = deepcopy(track)
    for clip_id in requested:
        plan = plan_clip_delete(working, clip_id=clip_id)
        update = plan.updates[0]
        working.notes = list(update.notes)
        working.performance_controls = list(update.performance_controls)
        working.bdo_source_note_records = update.source_note_records
        working.bdo_source_group_index = update.source_group_index
        working.clip_start_ms = update.clip_start_ms
        working.clip_end_ms = update.clip_end_ms
        working.arrangement_clips = list(update.arrangement_clips)

    update = _base_update(working)
    selected_clip_id = (
        update.arrangement_clips[0].clip_id
        if update.arrangement_clips
        else ""
    )
    return ClipEditPlan(
        (update,), int(track.track_id), selected_clip_id
    )


def plan_clips_move(
    track: TrackState,
    *,
    clip_ids: Sequence[str],
    delta_ms: float,
) -> ClipEditPlan:
    """Move several same-track Clip views by one common timeline delta."""

    requested = tuple(dict.fromkeys(str(value) for value in clip_ids))
    if not requested:
        raise ValueError("at least one clip must be selected")
    delta = float(delta_ms)
    if not math.isfinite(delta):
        raise ValueError("clip move delta must be finite")
    clips = track_clips(track)
    selected_ids = set(requested)
    available = {clip.clip_id for clip in clips}
    missing = tuple(value for value in requested if value not in available)
    if missing:
        raise ClipEditError(
            "clip_missing",
            f"selected clips are unavailable: {', '.join(missing)}",
        )
    moved_by_id = {
        clip.clip_id: replace(
            clip,
            start_ms=clip.start_ms + delta,
            end_ms=clip.end_ms + delta,
            time_offset_ms=clip.time_offset_ms + delta,
        )
        for clip in clips
        if clip.clip_id in selected_ids
    }
    if any(clip.start_ms < 0.0 for clip in moved_by_id.values()):
        raise ClipEditError(
            "clip_group_before_zero",
            "selected clips cannot move before the timeline start",
        )
    unselected = tuple(
        clip for clip in clips if clip.clip_id not in selected_ids
    )
    for moved in moved_by_id.values():
        if any(
            moved.start_ms < other.end_ms
            and other.start_ms < moved.end_ms
            for other in unselected
        ):
            raise ClipEditError(
                "clip_group_overlap",
                "selected clips would overlap an unselected clip",
            )
    update = _base_update(track)
    primary_id = requested[0]
    return ClipEditPlan((replace(
        update,
        arrangement_clips=tuple(
            moved_by_id.get(clip.clip_id, clip) for clip in clips
        ),
    ),), int(track.track_id), primary_id)


def plan_clips_relocate(
    tracks: Sequence[TrackState],
    *,
    selections: Sequence[tuple[int, str]],
    delta_ms: float,
    track_offset: int,
    primary_key: tuple[int, str] | None = None,
) -> tuple[ClipEditPlan, tuple[tuple[int, str], ...]]:
    """Move a Clip selection in time and across lanes as one atomic plan.

    A vertical move is an index offset, not a destination track ID.  This
    preserves the selection's relative lane layout (for example lanes 2/3
    moved up once become lanes 1/2).  Selected Clips are removed from their
    source lanes before collision checks so a block can move into lanes that
    another member is vacating in the same transaction.
    """

    ordered_tracks = tuple(tracks)
    if not ordered_tracks:
        raise ValueError("at least one track is required")
    requested = tuple(dict.fromkeys(
        (int(track_id), str(clip_id))
        for track_id, clip_id in selections
    ))
    if not requested:
        raise ValueError("at least one clip must be selected")
    delta = float(delta_ms)
    if not math.isfinite(delta):
        raise ValueError("clip move delta must be finite")
    lane_delta = int(track_offset)
    rows_by_id = {
        int(track.track_id): index
        for index, track in enumerate(ordered_tracks)
    }
    tracks_by_id = {
        int(track.track_id): track for track in ordered_tracks
    }
    source_clips_by_id = {
        int(track.track_id): track_clips(track) for track in ordered_tracks
    }
    selected_by_track: dict[int, set[str]] = {}
    payloads: list[tuple[TrackState, ArrangementClipState, ClipClipboard, TrackState]] = []
    relocated_keys: list[tuple[int, str]] = []
    for track_id, clip_id in requested:
        source = tracks_by_id.get(track_id)
        source_row = rows_by_id.get(track_id)
        if source is None or source_row is None:
            raise ClipEditError("clip_missing", "selected track is unavailable")
        destination_row = source_row + lane_delta
        if not 0 <= destination_row < len(ordered_tracks):
            raise ClipEditError(
                "clip_group_track_bounds",
                "selected clips cannot move beyond the available tracks",
            )
        clip = clip_by_id(source, clip_id)
        moved_start = float(clip.start_ms) + delta
        if moved_start < 0.0:
            raise ClipEditError(
                "clip_group_before_zero",
                "selected clips cannot move before the timeline start",
            )
        destination = ordered_tracks[destination_row]
        selected_by_track.setdefault(track_id, set()).add(clip_id)
        payloads.append((source, clip, copy_clip(source, clip_id), destination))
        relocated_keys.append((int(destination.track_id), clip_id))

    affected_ids = {
        *(track_id for track_id, _clip_id in requested),
        *(track_id for track_id, _clip_id in relocated_keys),
    }
    working = {
        int(track.track_id): deepcopy(track)
        for track in ordered_tracks
        if int(track.track_id) in affected_ids
    }
    for track_id, selected_ids in selected_by_track.items():
        source = tracks_by_id[track_id]
        original_clips = source_clips_by_id[track_id]
        remaining_clips = tuple(
            clip for clip in original_clips if clip.clip_id not in selected_ids
        )

        def retained_content_time(value: float) -> bool:
            return any(
                clip.content_start_ms <= value < clip.content_end_ms
                for clip in remaining_clips
            )

        draft = working[track_id]
        draft.notes = [
            deepcopy(note) for note in source.notes
            if retained_content_time(float(note.start))
            or not any(
                _note_belongs_to_clip(source, note, clip, clips=original_clips)
                for clip in original_clips
                if clip.clip_id in selected_ids
            )
        ]
        draft.performance_controls = [
            deepcopy(value) for value in source.performance_controls
            if retained_content_time(float(value.get("time", -1.0)))
            or not any(
                clip.content_start_ms <= float(value.get("time", -1.0))
                < clip.content_end_ms
                for clip in original_clips
                if clip.clip_id in selected_ids
            )
        ]
        draft.bdo_source_note_records = tuple(
            deepcopy(tuple(value)) for value in source.bdo_source_note_records
            if retained_content_time(float(value[2]))
            or not any(
                clip.content_start_ms <= float(value[2]) < clip.content_end_ms
                for clip in original_clips
                if clip.clip_id in selected_ids
            )
        )
        draft.bdo_source_group_index = None
        draft.arrangement_clips = list(remaining_clips)

    for _source, clip, clipboard, destination in payloads:
        draft = working[int(destination.track_id)]
        existing_clips = track_clips(draft)
        new_start = float(clip.start_ms) + delta
        new_end = float(clip.end_ms) + delta
        if overlapping_clip_ids(
            draft, start_ms=new_start, end_ms=new_end
        ):
            raise ClipEditError(
                "clip_group_overlap",
                "selected clips would overlap another clip",
            )
        if any(value.clip_id == clip.clip_id for value in existing_clips):
            raise ClipEditError(
                "clip_id_conflict",
                "the destination track already contains this clip",
            )
        content_end = max(
            (value.content_end_ms for value in existing_clips),
            default=max(
                (_note_end(note) for note in draft.notes), default=0.0
            ),
        )
        content_base = max(0.0, content_end + MIN_CLIP_DURATION_MS)
        content_shift = content_base - float(clip.content_start_ms)
        moved_clip = replace(
            clip,
            start_ms=new_start,
            end_ms=new_end,
            content_start_ms=float(clip.content_start_ms) + content_shift,
            content_end_ms=float(clip.content_end_ms) + content_shift,
            time_offset_ms=float(clip.time_offset_ms) + delta - content_shift,
        )
        draft.notes.extend(
            note._replace(start=float(note.start) + content_shift)
            for note in clipboard.notes
        )
        draft.performance_controls.extend(
            _mapping_time(value, lambda time, shift=content_shift: time + shift)
            for value in clipboard.performance_controls
        )
        draft.bdo_source_note_records = tuple((
            *draft.bdo_source_note_records,
            *(
                _record_time(
                    value,
                    lambda time, shift=content_shift: time + shift,
                    1.0,
                )
                for value in clipboard.source_note_records
            ),
        ))
        draft.bdo_source_group_index = None
        draft.arrangement_clips.append(moved_clip)

    updates = tuple(
        replace(
            _base_update(working[int(track.track_id)]),
            notes=tuple(sorted(
                working[int(track.track_id)].notes,
                key=lambda note: float(note.start),
            )),
            performance_controls=tuple(sorted(
                working[int(track.track_id)].performance_controls,
                key=lambda value: float(value.get("time", 0.0)),
            )),
            source_note_records=tuple(sorted(
                working[int(track.track_id)].bdo_source_note_records,
                key=lambda value: float(value[2]),
            )),
            source_group_index=working[int(track.track_id)].bdo_source_group_index,
        )
        for track in ordered_tracks
        if int(track.track_id) in affected_ids
    )
    key_map = dict(zip(requested, relocated_keys))
    requested_primary = (
        (int(primary_key[0]), str(primary_key[1]))
        if primary_key is not None else requested[0]
    )
    relocated_primary = key_map.get(requested_primary, relocated_keys[0])
    return (
        ClipEditPlan(updates, relocated_primary[0], relocated_primary[1]),
        tuple(relocated_keys),
    )


__all__ = [
    "ClipBounds",
    "ClipEditError",
    "ClipEditPlan",
    "ClipEditorScope",
    "ClipClipboard",
    "ClipTrackUpdate",
    "DEFAULT_EMPTY_CLIP_DURATION_MS",
    "MIN_CLIP_DURATION_MS",
    "clip_by_id",
    "clip_editor_notes",
    "clip_authored_note_indices",
    "clip_authored_note_index_map",
    "clip_editor_scope",
    "clip_projected_note_bounds",
    "clip_edit_fingerprint",
    "copy_clip",
    "default_empty_clip",
    "clip_for_note",
    "plan_clip_create",
    "plan_clip_delete",
    "plan_clips_delete",
    "plan_clips_move",
    "plan_clips_relocate",
    "plan_clips_consolidate",
    "plan_clip_edit",
    "plan_clip_note_edit",
    "plan_clip_paste",
    "plan_clip_duplicate",
    "plan_clip_metadata",
    "plan_clip_repeat",
    "plan_clip_crop_right",
    "plan_clip_split",
    "overlapping_clip_ids",
    "project_track_notes",
    "project_track_note_refs",
    "project_track_performance_controls",
    "project_track_source_records",
    "reconcile_track_clips_after_note_edit",
    "track_clip_bounds",
    "track_clips",
]
