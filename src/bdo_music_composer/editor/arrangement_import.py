"""Transactional planning for appending external tracks to an arrangement."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from collections.abc import Mapping, Sequence

from bdo_common.bdo_track_effects import MasterEffects, encode_track_effects
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.arrangement_clip import track_clips
from bdo_music_composer.editor.game_score_model import inherit_game_instrument_mix


@dataclass(frozen=True, slots=True)
class ArrangementAppendPlan:
    """An isolated append payload that is safe to publish as one edit."""

    tracks: tuple[TrackState, ...]
    lyric_events: tuple[dict, ...]
    offset_ms: float

    @property
    def note_count(self) -> int:
        return sum(len(track.notes) for track in self.tracks)


def _shift_timed_mapping(value: Mapping, offset_ms: float) -> dict:
    shifted = deepcopy(dict(value))
    if "time" in shifted:
        shifted["time"] = float(shifted["time"]) + offset_ms
    return shifted


def _shift_source_record(record: Sequence[object], offset_ms: float) -> tuple:
    if len(record) < 6:
        raise ValueError("BDO source note records must contain six values")
    shifted = list(deepcopy(tuple(record)))
    shifted[2] = float(shifted[2]) + offset_ms
    return tuple(shifted)


def plan_arrangement_append(
    existing_tracks: Sequence[TrackState],
    imported_tracks: Sequence[TrackState],
    *,
    reserved_track_ids: Sequence[int] = (),
    offset_ms: float = 0.0,
    lyric_events: Sequence[Mapping] = (),
    master_effects: MasterEffects = MasterEffects(),
    colors: Sequence[str] = (),
) -> ArrangementAppendPlan:
    """Clone and adapt imported material without mutating either input.

    Source timing is expressed in milliseconds, so a different source tempo
    does not require destructive stretching. The destination owns the one
    score-wide master-effects layer, while imported per-instrument Aux sends
    remain intact unless an existing matching instrument already owns them.
    """

    try:
        normalized_offset = float(offset_ms)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("arrangement offset must be a finite number") from exc
    if not math.isfinite(normalized_offset) or normalized_offset < 0.0:
        raise ValueError("arrangement offset must be a finite non-negative number")
    if not imported_tracks:
        raise ValueError("the imported source does not contain tracks")

    reserved = {int(value) for value in reserved_track_ids}
    reserved.update(int(track.track_id) for track in existing_tracks)
    next_track_id = max(reserved, default=-1) + 1
    planned: list[TrackState] = []

    for index, source in enumerate(imported_tracks):
        track = deepcopy(source)
        track.track_id = next_track_id + index
        track.notes = [
            note._replace(start=float(note.start) + normalized_offset)
            for note in source.notes
        ]
        track.arrangement_clips = [
            type(clip)(
                f"track-{track.track_id}-import-{clip_index}",
                clip.start_ms + normalized_offset,
                clip.end_ms + normalized_offset,
                clip.content_start_ms + normalized_offset,
                clip.content_end_ms + normalized_offset,
                clip.time_offset_ms,
            )
            for clip_index, clip in enumerate(track_clips(source))
        ]
        track.clip_start_ms = None
        track.clip_end_ms = None
        track.performance_controls = [
            _shift_timed_mapping(control, normalized_offset)
            for control in source.performance_controls
        ]
        track.bdo_source_note_records = tuple(
            _shift_source_record(record, normalized_offset)
            for record in source.bdo_source_note_records
        )
        # An appended BDO score does not belong to the destination's source
        # document, so physical group reuse must be disabled. The explicit
        # note records above still preserve its secondary velocity bytes.
        track.bdo_source_group_index = None
        track.bdo_track_settings = encode_track_effects(
            track.bdo_track_settings,
            master=master_effects,
            master_authored=False,
        )
        if colors:
            track.color = str(colors[track.track_id % len(colors)])
        inherit_game_instrument_mix(
            (*existing_tracks, *planned, track),
            track,
        )
        planned.append(track)

    shifted_lyrics = tuple(
        _shift_timed_mapping(event, normalized_offset)
        for event in lyric_events
    )
    return ArrangementAppendPlan(
        tracks=tuple(planned),
        lyric_events=shifted_lyrics,
        offset_ms=normalized_offset,
    )


__all__ = ["ArrangementAppendPlan", "plan_arrangement_append"]
