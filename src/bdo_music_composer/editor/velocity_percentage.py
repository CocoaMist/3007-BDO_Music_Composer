"""Materialized, reversible velocity percentages for Tracks and Clips."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from bdo_music_composer.editor.arrangement_clip import (
    clip_authored_note_index_map,
    track_clips,
)
from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
from bdo_music_composer.editor.game_score_model import (
    bound_game_velocity_b_values,
)
from bdo_music_composer.editor.global_velocity_gain import base_velocity_map


MIN_VELOCITY_PERCENT = 10
MAX_VELOCITY_PERCENT = 200
NEUTRAL_VELOCITY_PERCENT = 100


def _bounded_percent(value: int) -> int:
    return max(MIN_VELOCITY_PERCENT, min(MAX_VELOCITY_PERCENT, int(value)))


def _scaled(value: int, percent: int) -> int:
    result = (int(value) * int(percent) + 50) // 100
    return max(0, min(127, result))


def _rebased(current: int, old_percent: int) -> int:
    if old_percent <= 0:
        return int(current)
    numerator = int(current) * 100
    result = (numerator + int(old_percent) // 2) // int(old_percent)
    return max(0, min(127, result))


def _effective_baselines(
    current: tuple[int, ...], stored: tuple[int, ...], old_percent: int
) -> tuple[int, ...]:
    if len(stored) != len(current):
        return tuple(_rebased(value, old_percent) for value in current)
    return tuple(
        base if _scaled(base, old_percent) == value else _rebased(value, old_percent)
        for value, base in zip(current, stored)
    )


def _ensure_explicit_clips(track: TrackState) -> None:
    if not track.arrangement_clips:
        track.arrangement_clips = list(track_clips(track))


def apply_clip_velocity_percent(
    track: TrackState, clip_ids: tuple[str, ...], percent: int
) -> bool:
    """Bake one absolute percentage into selected Clips and retain restoration data."""

    percent = _bounded_percent(percent)
    _ensure_explicit_clips(track)
    selected = {str(value) for value in clip_ids}
    notes = list(track.notes)
    records = tuple(track.bdo_source_note_records)
    current_b = tuple(bound_game_velocity_b_values(notes, records))
    next_b = list(current_b)
    index_map = clip_authored_note_index_map(track, tuple(selected))
    changed = False
    updated_clips: list[ArrangementClipState] = []
    for clip in track.arrangement_clips:
        if clip.clip_id not in selected:
            updated_clips.append(clip)
            continue
        indices = index_map.get(str(clip.clip_id), ())
        current_a = tuple(int(notes[index].vel) for index in indices)
        clip_current_b = tuple(int(current_b[index]) for index in indices)
        baseline_a = _effective_baselines(
            current_a, tuple(clip.velocity_baseline_a), int(clip.velocity_percent)
        )
        baseline_b = _effective_baselines(
            clip_current_b, tuple(clip.velocity_baseline_b), int(clip.velocity_percent)
        )
        for index, baseline in zip(indices, baseline_a):
            notes[index] = notes[index]._replace(vel=_scaled(baseline, percent))
        for index, baseline in zip(indices, baseline_b):
            next_b[index] = _scaled(baseline, percent)
        updated_clips.append(replace(
            clip,
            velocity_percent=percent,
            velocity_baseline_a=baseline_a,
            velocity_baseline_b=baseline_b,
        ))
        changed = changed or percent != int(clip.velocity_percent) or bool(indices)
    if not changed:
        return False
    track.bdo_source_note_records = (
        tuple(
            (
                int(note.pitch),
                int(note.vel),
                float(note.start),
                float(note.dur),
                int(note.ntype),
                int(next_b[index]),
            )
            for index, note in enumerate(notes)
        )
        if records else ()
    )
    track.notes = notes
    track.arrangement_clips = updated_clips
    return True


def apply_clip_velocity_base(
    track: TrackState,
    clip_ids: tuple[str, ...],
    velocity_base: int,
    *,
    equalize: bool,
) -> bool:
    """Change selected Clip baselines, then reapply each existing percentage."""

    _ensure_explicit_clips(track)
    selected = {str(value) for value in clip_ids}
    notes = list(track.notes)
    records = tuple(track.bdo_source_note_records)
    current_b = tuple(bound_game_velocity_b_values(notes, records))
    next_b = list(current_b)
    index_map = clip_authored_note_index_map(track, tuple(selected))
    updated_clips: list[ArrangementClipState] = []
    changed = False
    for clip in track.arrangement_clips:
        if str(clip.clip_id) not in selected:
            updated_clips.append(clip)
            continue
        indices = index_map.get(str(clip.clip_id), ())
        current_a = tuple(int(notes[index].vel) for index in indices)
        clip_current_b = tuple(int(current_b[index]) for index in indices)
        baseline_a = _effective_baselines(
            current_a, tuple(clip.velocity_baseline_a), int(clip.velocity_percent)
        )
        baseline_b = _effective_baselines(
            clip_current_b, tuple(clip.velocity_baseline_b), int(clip.velocity_percent)
        )
        values = [*baseline_a, *baseline_b]
        velocity_map = base_velocity_map(
            values, int(velocity_base), 0, equalize=bool(equalize)
        )
        next_a = tuple(velocity_map[value] for value in baseline_a)
        next_clip_b = tuple(velocity_map[value] for value in baseline_b)
        percent = int(clip.velocity_percent)
        for index, base_a, base_b in zip(indices, next_a, next_clip_b):
            notes[index] = notes[index]._replace(vel=_scaled(base_a, percent))
            next_b[index] = _scaled(base_b, percent)
        updated_clips.append(replace(
            clip,
            velocity_baseline_a=next_a,
            velocity_baseline_b=next_clip_b,
        ))
        changed = changed or next_a != baseline_a or next_clip_b != baseline_b
    if not changed:
        return False
    track.notes = notes
    if records:
        track.bdo_source_note_records = tuple(
            (
                int(note.pitch), int(note.vel), float(note.start),
                float(note.dur), int(note.ntype), int(next_b[index]),
            )
            for index, note in enumerate(notes)
        )
    track.arrangement_clips = updated_clips
    return True


def apply_track_velocity_percent(track: TrackState, percent: int) -> bool:
    """Bake one percentage into every Clip and uncontained note on a Track."""

    percent = _bounded_percent(percent)
    _ensure_explicit_clips(track)
    clip_ids = tuple(str(clip.clip_id) for clip in track.arrangement_clips)
    changed = apply_clip_velocity_percent(track, clip_ids, percent)
    owned = {
        index for indices in clip_authored_note_index_map(
            track, clip_ids
        ).values() for index in indices
    }
    indices = tuple(
        index for index in range(len(track.notes)) if index not in owned
    )
    if not indices:
        track.loose_velocity_percent = percent
        return changed
    notes = list(track.notes)
    records = tuple(track.bdo_source_note_records)
    current_b = tuple(bound_game_velocity_b_values(notes, records))
    baseline_a = _effective_baselines(
        tuple(int(notes[index].vel) for index in indices),
        tuple(track.loose_velocity_baseline_a),
        int(track.loose_velocity_percent),
    )
    baseline_b = _effective_baselines(
        tuple(int(current_b[index]) for index in indices),
        tuple(track.loose_velocity_baseline_b),
        int(track.loose_velocity_percent),
    )
    next_b = list(current_b)
    for index, base_a, base_b in zip(indices, baseline_a, baseline_b):
        notes[index] = notes[index]._replace(vel=_scaled(base_a, percent))
        next_b[index] = _scaled(base_b, percent)
    track.notes = notes
    if records:
        track.bdo_source_note_records = tuple(
            (
                int(note.pitch), int(note.vel), float(note.start),
                float(note.dur), int(note.ntype), int(next_b[index]),
            )
            for index, note in enumerate(notes)
        )
    track.loose_velocity_percent = percent
    track.loose_velocity_baseline_a = baseline_a
    track.loose_velocity_baseline_b = baseline_b
    return True


def apply_global_velocity_adjustment(
    tracks: Sequence[TrackState],
    value: int,
    *,
    percent_mode: bool,
    equalize: bool = False,
) -> tuple[int, ...]:
    """Transform recoverable A/B baselines, then replay scoped percentages.

    Global adjustment is intentionally below the Track/Clip percentage layer.
    This keeps every persisted percentage truthful and prevents a later global
    preview from replacing a newer scoped edit with stale final-note values.
    """

    prepared: list[dict[str, object]] = []
    baseline_values: list[int] = []
    for track in tracks:
        notes = list(track.notes)
        records = tuple(track.bdo_source_note_records)
        current_b = tuple(bound_game_velocity_b_values(notes, records))
        clips = tuple(track.arrangement_clips)
        clip_ids = tuple(str(clip.clip_id) for clip in clips)
        index_map = (
            clip_authored_note_index_map(track, clip_ids) if clip_ids else {}
        )
        owned: set[int] = set()
        clip_rows: list[
            tuple[ArrangementClipState, tuple[int, ...], tuple[int, ...], tuple[int, ...]]
        ] = []
        for clip in clips:
            indices = tuple(index_map.get(str(clip.clip_id), ()))
            owned.update(indices)
            baseline_a = _effective_baselines(
                tuple(int(notes[index].vel) for index in indices),
                tuple(clip.velocity_baseline_a),
                int(clip.velocity_percent),
            )
            baseline_b = _effective_baselines(
                tuple(int(current_b[index]) for index in indices),
                tuple(clip.velocity_baseline_b),
                int(clip.velocity_percent),
            )
            baseline_values.extend((*baseline_a, *baseline_b))
            clip_rows.append((clip, indices, baseline_a, baseline_b))
        loose_indices = tuple(
            index for index in range(len(notes)) if index not in owned
        )
        loose_a = _effective_baselines(
            tuple(int(notes[index].vel) for index in loose_indices),
            tuple(track.loose_velocity_baseline_a),
            int(track.loose_velocity_percent),
        )
        loose_b = _effective_baselines(
            tuple(int(current_b[index]) for index in loose_indices),
            tuple(track.loose_velocity_baseline_b),
            int(track.loose_velocity_percent),
        )
        baseline_values.extend((*loose_a, *loose_b))
        prepared.append({
            "track": track,
            "notes": notes,
            "records": records,
            "current_b": current_b,
            "clip_rows": clip_rows,
            "loose_indices": loose_indices,
            "loose_a": loose_a,
            "loose_b": loose_b,
        })

    velocity_map = (
        {level: _scaled(level, int(value)) for level in set(baseline_values)}
        if percent_mode
        else base_velocity_map(
            baseline_values, int(value), 0, equalize=bool(equalize)
        )
    )
    changed_ids: list[int] = []
    for row in prepared:
        track = row["track"]
        assert isinstance(track, TrackState)
        notes = list(row["notes"])
        records = tuple(row["records"])
        next_b = list(row["current_b"])
        updated_clips: list[ArrangementClipState] = []
        for clip, indices, baseline_a, baseline_b in row["clip_rows"]:
            next_a = tuple(velocity_map[value] for value in baseline_a)
            next_clip_b = tuple(velocity_map[value] for value in baseline_b)
            percent = int(clip.velocity_percent)
            for index, base_a, base_b in zip(indices, next_a, next_clip_b):
                notes[index] = notes[index]._replace(
                    vel=_scaled(base_a, percent)
                )
                next_b[index] = _scaled(base_b, percent)
            updated_clips.append(replace(
                clip,
                velocity_baseline_a=next_a,
                velocity_baseline_b=next_clip_b,
            ))
        loose_a = tuple(velocity_map[value] for value in row["loose_a"])
        loose_b = tuple(velocity_map[value] for value in row["loose_b"])
        loose_percent = int(track.loose_velocity_percent)
        for index, base_a, base_b in zip(
            row["loose_indices"], loose_a, loose_b
        ):
            notes[index] = notes[index]._replace(
                vel=_scaled(base_a, loose_percent)
            )
            next_b[index] = _scaled(base_b, loose_percent)
        next_records = (
            tuple(
                (
                    int(note.pitch), int(note.vel), float(note.start),
                    float(note.dur), int(note.ntype), int(next_b[index]),
                )
                for index, note in enumerate(notes)
            )
            if records else ()
        )
        changed = (
            notes != track.notes
            or next_records != track.bdo_source_note_records
            or updated_clips != track.arrangement_clips
            or loose_a != tuple(track.loose_velocity_baseline_a)
            or loose_b != tuple(track.loose_velocity_baseline_b)
        )
        track.notes = notes
        track.bdo_source_note_records = next_records
        track.arrangement_clips = updated_clips
        track.loose_velocity_baseline_a = loose_a
        track.loose_velocity_baseline_b = loose_b
        if changed:
            changed_ids.append(int(track.track_id))
    return tuple(changed_ids)


def selection_velocity_percent(
    selections: tuple[tuple[TrackState, str], ...]
) -> int | None:
    values = {
        int(clip.velocity_percent)
        for track, clip_id in selections
        for clip in track_clips(track)
        if clip.clip_id == clip_id
    }
    return next(iter(values)) if len(values) == 1 else None


def track_velocity_percent(track: TrackState) -> int | None:
    clips = track_clips(track)
    values = {int(clip.velocity_percent) for clip in clips}
    owned = {
        index for indices in clip_authored_note_index_map(
            track, tuple(str(clip.clip_id) for clip in clips)
        ).values() for index in indices
    }
    if len(owned) < len(track.notes):
        values.add(int(track.loose_velocity_percent))
    return next(iter(values)) if len(values) == 1 else None


__all__ = [
    "MAX_VELOCITY_PERCENT",
    "MIN_VELOCITY_PERCENT",
    "NEUTRAL_VELOCITY_PERCENT",
    "apply_clip_velocity_percent",
    "apply_clip_velocity_base",
    "apply_global_velocity_adjustment",
    "apply_track_velocity_percent",
    "selection_velocity_percent",
    "track_velocity_percent",
]
