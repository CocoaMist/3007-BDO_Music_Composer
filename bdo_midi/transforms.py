"""Pure note-list transformations used before BDO serialization."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from .instruments import BDO_NOTE_MAX, BDO_NOTE_MIN, _GM_TO_BDO_DRUM
from .model import Note


DRUM_NOTE_TYPE = 99
DRUM_NOTE_MAX_DURATION_MS = 80.0
DRUM_ROLL_PITCHES = frozenset({63, 64})
BDO_VEL_LEVELS = (80, 90, 100, 121)


def bounded_int(value: object, low: int, high: int, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer") from None
    if not low <= result <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return result


def bounded_velocity(value: object, label: str = "velocity") -> int:
    return bounded_int(value, 0, 127, label)


def clamp_notes(notes: Iterable[Note]) -> list[Note]:
    return [note._replace(pitch=max(BDO_NOTE_MIN, min(BDO_NOTE_MAX, note.pitch))) for note in notes]


def transpose_notes(notes: Iterable[Note], semitones: int) -> list[Note]:
    return [note._replace(pitch=note.pitch + semitones) for note in notes]


def map_drum_notes(notes: Iterable[Note]) -> list[Note]:
    result: list[Note] = []
    for note in notes:
        already_canonical = note.ntype == DRUM_NOTE_TYPE and 48 <= note.pitch <= 64
        pitch = note.pitch if already_canonical else _GM_TO_BDO_DRUM.get(note.pitch, 48)
        duration = note.dur if pitch in DRUM_ROLL_PITCHES else min(note.dur, DRUM_NOTE_MAX_DURATION_MS)
        result.append(Note(pitch, note.vel, note.start, max(1.0, duration), DRUM_NOTE_TYPE))
    return result


def normalize_drum_note_timing(notes: Sequence[Note]) -> list[Note]:
    strongest: dict[tuple[int, float, int], Note] = {}
    for note in notes:
        identity = (note.pitch, round(note.start, 3), note.ntype)
        if identity not in strongest or note.vel > strongest[identity].vel:
            strongest[identity] = note

    one_shots: dict[int, list[Note]] = defaultdict(list)
    output: list[Note] = []
    for note in strongest.values():
        if note.ntype == DRUM_NOTE_TYPE and note.pitch not in DRUM_ROLL_PITCHES:
            one_shots[note.pitch].append(note)
        else:
            output.append(note)

    for pitch_notes in one_shots.values():
        ordered = sorted(pitch_notes, key=lambda note: (note.start, note.dur))
        for index, note in enumerate(ordered):
            duration = min(note.dur, DRUM_NOTE_MAX_DURATION_MS)
            if index + 1 < len(ordered):
                gap = ordered[index + 1].start - note.start
                if duration >= gap:
                    duration = gap - 1.0
            output.append(note._replace(dur=max(1.0, duration)))
    return sorted(output, key=lambda note: (note.start, note.pitch, note.ntype))


def rescale_velocity(notes: Sequence[Note], vel_min: int = 0, vel_max: int = 127) -> list[Note]:
    low = bounded_velocity(vel_min, "vel_min")
    high = bounded_velocity(vel_max, "vel_max")
    if low > high:
        raise ValueError("vel_min cannot be greater than vel_max")
    source = [note.vel for note in notes if note.ntype == 0]
    if not source:
        return list(notes)
    source_low, source_high = min(source), max(source)
    if source_low == source_high:
        midpoint = (low + high) // 2
        return [note._replace(vel=midpoint) if note.ntype == 0 else note for note in notes]
    span = source_high - source_low
    target_span = high - low
    return [
        note._replace(vel=round(low + (note.vel - source_low) * target_span / span))
        if note.ntype == 0 else note
        for note in notes
    ]


def floor_velocity(notes: Sequence[Note], floor: int = 100) -> list[Note]:
    target = bounded_velocity(floor, "vel_floor")
    normal = [note.vel for note in notes if note.ntype == 0]
    if not normal or min(normal) == 0 or min(normal) >= target:
        return list(notes)
    multiplier = target / min(normal)
    return [
        note._replace(vel=min(127, round(note.vel * multiplier))) if note.ntype == 0 else note
        for note in notes
    ]


def stepped_velocity(notes: Sequence[Note], base: int = 99, step: int = 5) -> list[Note]:
    first = bounded_velocity(base, "vel_step base")
    increment = bounded_int(step, 0, 127, "vel_step step")
    values = sorted({note.vel for note in notes if note.ntype == 0})
    if not values:
        return list(notes)
    mapping = {value: min(127, first + index * increment) for index, value in enumerate(values)}
    mapping[values[-1]] = 127
    return [note._replace(vel=mapping[note.vel]) if note.ntype == 0 else note for note in notes]


def layered_velocity(
    notes: Sequence[Note],
    levels: Sequence[int] | None = None,
    scale: float = 1.0,
) -> list[Note]:
    palette = tuple(levels or BDO_VEL_LEVELS)
    if scale != 1.0:
        palette = tuple(sorted({max(1, min(127, round(level * scale))) for level in palette}))
    values = sorted({note.vel for note in notes if note.ntype == 0})
    if not values:
        return list(notes)
    if len(values) == 1:
        mapping = {values[0]: palette[len(palette) // 2]}
    else:
        mapping = {
            value: palette[round(index * (len(palette) - 1) / (len(values) - 1))]
            for index, value in enumerate(values)
        }
    return [note._replace(vel=mapping[note.vel]) if note.ntype == 0 else note for note in notes]


__all__ = [
    "BDO_VEL_LEVELS", "DRUM_NOTE_MAX_DURATION_MS", "DRUM_NOTE_TYPE",
    "DRUM_ROLL_PITCHES", "bounded_int", "bounded_velocity", "clamp_notes",
    "floor_velocity", "layered_velocity", "map_drum_notes",
    "normalize_drum_note_timing", "rescale_velocity", "stepped_velocity",
    "transpose_notes",
]
