"""Transactional merge planning for two ordinary editor tracks."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
import math

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.arrangement_clip import project_track_notes
from bdo_music_composer.editor.game_score_model import bound_game_velocity_b_values
from bdo_music_composer.editor.output_routing import (
    GameOutputRouteIdentity,
    game_output_route_identity,
)


# BDO v9's independent codec owns enforcement.  The editor repeats the public
# projection limit only to explain the post-merge physical split before export.
GAME_NOTES_PER_PHYSICAL_TRACK = 730


@dataclass(frozen=True, slots=True)
class TrackOverlapRegion:
    start_ms: float
    end_ms: float
    peak_note_count: int

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


@dataclass(frozen=True, slots=True)
class TrackMergeReport:
    route: GameOutputRouteIdentity
    source_note_count: int
    destination_note_count: int
    merged_note_count: int
    overlap_regions: tuple[TrackOverlapRegion, ...]
    overlap_duration_ms: float
    overlap_pair_count: int
    same_pitch_pair_count: int
    exact_duplicate_count: int
    peak_note_count: int
    physical_note_track_count: int

    @property
    def has_overlap(self) -> bool:
        return bool(self.overlap_regions)


@dataclass(frozen=True, slots=True)
class TrackMergePlan:
    source_track_id: int
    absorbed_track_id: int
    merged_track: TrackState
    report: TrackMergeReport


def _effective_notes(track: TrackState) -> tuple[Note, ...]:
    scale = float(track.duration_scale)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("track duration scale must be positive and finite")
    return project_track_notes(track)


def _overlap_pair_count(left: tuple[Note, ...], right: tuple[Note, ...]) -> int:
    starts = sorted(float(note.start) for note in right)
    ends = sorted(float(note.start) + float(note.dur) for note in right)
    return sum(
        bisect_left(starts, float(note.start) + float(note.dur))
        - bisect_right(ends, float(note.start))
        for note in left
    )


def _same_pitch_overlap_count(
    left: tuple[Note, ...], right: tuple[Note, ...]
) -> int:
    left_by_pitch: dict[int, list[Note]] = defaultdict(list)
    right_by_pitch: dict[int, list[Note]] = defaultdict(list)
    for note in left:
        left_by_pitch[int(note.pitch)].append(note)
    for note in right:
        right_by_pitch[int(note.pitch)].append(note)
    return sum(
        _overlap_pair_count(tuple(values), tuple(right_by_pitch[pitch]))
        for pitch, values in left_by_pitch.items()
        if pitch in right_by_pitch
    )


def _overlap_regions(
    left: tuple[Note, ...], right: tuple[Note, ...]
) -> tuple[tuple[TrackOverlapRegion, ...], int]:
    boundaries: dict[float, list[int]] = defaultdict(lambda: [0, 0])
    for source_index, notes in enumerate((left, right)):
        for note in notes:
            start = float(note.start)
            end = start + float(note.dur)
            boundaries[start][source_index] += 1
            boundaries[end][source_index] -= 1
    times = sorted(boundaries)
    active = [0, 0]
    regions: list[TrackOverlapRegion] = []
    peak = 0
    for index, start in enumerate(times[:-1]):
        active[0] += boundaries[start][0]
        active[1] += boundaries[start][1]
        end = times[index + 1]
        if end <= start or not active[0] or not active[1]:
            continue
        combined = active[0] + active[1]
        peak = max(peak, combined)
        if regions and math.isclose(regions[-1].end_ms, start, abs_tol=1e-9):
            previous = regions[-1]
            regions[-1] = TrackOverlapRegion(
                previous.start_ms,
                end,
                max(previous.peak_note_count, combined),
            )
        else:
            regions.append(TrackOverlapRegion(start, end, combined))
    return tuple(regions), peak


def _exact_duplicate_count(left: tuple[Note, ...], right: tuple[Note, ...]) -> int:
    left_counts = Counter(tuple(note) for note in left)
    right_counts = Counter(tuple(note) for note in right)
    return sum(
        min(count, right_counts[value])
        for value, count in left_counts.items()
        if value in right_counts
    )


def _merged_velocity_records(
    source: TrackState,
    absorbed: TrackState,
    source_notes: tuple[Note, ...],
    absorbed_notes: tuple[Note, ...],
) -> tuple[tuple, ...]:
    if not source.bdo_source_note_records and not absorbed.bdo_source_note_records:
        return ()
    result: list[tuple] = []
    for track, notes in ((source, source_notes), (absorbed, absorbed_notes)):
        velocities_b = bound_game_velocity_b_values(
            track.notes, track.bdo_source_note_records
        )
        result.extend(
            (note.pitch, note.vel, note.start, note.dur, note.ntype, velocity_b)
            for note, velocity_b in zip(notes, velocities_b)
        )
    return tuple(sorted(result, key=lambda value: (value[2], value[0], value[3])))


def plan_track_merge(source: TrackState, absorbed: TrackState) -> TrackMergePlan:
    """Validate and plan A+B without mutating either source track."""

    if source is absorbed or int(source.track_id) == int(absorbed.track_id):
        raise ValueError("a track cannot be merged with itself")
    source_route = game_output_route_identity(source)
    absorbed_route = game_output_route_identity(absorbed)
    if source_route.instrument_id != absorbed_route.instrument_id:
        raise ValueError("tracks target different game instruments")
    if source_route.percussion_pitch_semantics != absorbed_route.percussion_pitch_semantics:
        raise ValueError("tracks use different game pitch mappings")
    if source_route.volume != absorbed_route.volume:
        raise ValueError("tracks use different game volumes")
    if source_route.settings != absorbed_route.settings:
        raise ValueError("tracks use different game mixer settings")

    source_notes = _effective_notes(source)
    absorbed_notes = _effective_notes(absorbed)
    regions, peak = _overlap_regions(source_notes, absorbed_notes)
    merged_notes = tuple(sorted(
        (*source_notes, *absorbed_notes),
        key=lambda note: (note.start, note.pitch, note.dur, note.vel, note.ntype),
    ))
    pair_count = _overlap_pair_count(source_notes, absorbed_notes)
    report = TrackMergeReport(
        route=source_route,
        source_note_count=len(source_notes),
        destination_note_count=len(absorbed_notes),
        merged_note_count=len(merged_notes),
        overlap_regions=regions,
        overlap_duration_ms=sum(region.duration_ms for region in regions),
        overlap_pair_count=pair_count,
        same_pitch_pair_count=_same_pitch_overlap_count(source_notes, absorbed_notes),
        exact_duplicate_count=_exact_duplicate_count(source_notes, absorbed_notes),
        peak_note_count=peak,
        physical_note_track_count=max(
            1, math.ceil(len(merged_notes) / GAME_NOTES_PER_PHYSICAL_TRACK)
        ),
    )
    controls = sorted(
        deepcopy([*source.performance_controls, *absorbed.performance_controls]),
        key=lambda value: float(value.get("time", 0.0)),
    )
    merged = replace(
        deepcopy(source),
        notes=list(merged_notes),
        display_name=f"{source.display_name} + {absorbed.display_name}",
        duration_scale=1.0,
        performance_controls=controls,
        notes_optimized=bool(source.notes_optimized and absorbed.notes_optimized),
        bdo_source_group_index=None,
        bdo_source_note_records=_merged_velocity_records(
            source, absorbed, source_notes, absorbed_notes
        ),
    )
    return TrackMergePlan(
        source_track_id=int(source.track_id),
        absorbed_track_id=int(absorbed.track_id),
        merged_track=merged,
        report=report,
    )


__all__ = [
    "TrackMergePlan",
    "TrackMergeReport",
    "TrackOverlapRegion",
    "plan_track_merge",
]
