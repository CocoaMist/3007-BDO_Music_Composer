"""Small, undo-friendly MIDI note transformations for the piano roll."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import random


def _scope(notes: Sequence[object], selected: set[int]) -> set[int]:
    return set(selected) if selected else set(range(len(notes)))


def quantize_note_starts(
    notes: Sequence[object], selected: set[int], grid_ms: float, origin_ms: float = 0.0
) -> list[object]:
    """Align note starts to the grid while preserving duration and pitch."""

    grid = max(1.0, float(grid_ms))
    scope = _scope(notes, selected)
    return [
        note._replace(
            start=max(0.0, origin_ms + round((note.start - origin_ms) / grid) * grid)
        )
        if index in scope
        else note
        for index, note in enumerate(notes)
    ]


def humanize_notes(
    notes: Sequence[object], selected: set[int], grid_ms: float, *, seed: str
) -> list[object]:
    """Apply a conservative deterministic timing/velocity performance variation."""

    scope = _scope(notes, selected)
    timing = min(12.0, max(2.0, float(grid_ms) * 0.08))
    output: list[object] = []
    for index, note in enumerate(notes):
        if index not in scope:
            output.append(note)
            continue
        digest = hashlib.sha256(
            f"{seed}|{index}|{note.pitch}|{note.start:.6f}|{note.dur:.6f}".encode()
        ).digest()
        rng = random.Random(int.from_bytes(digest[:8], "little"))
        output.append(note._replace(
            start=max(0.0, float(note.start) + rng.uniform(-timing, timing)),
            vel=max(1, min(127, int(note.vel) + rng.randint(-4, 4))),
        ))
    return output


def strum_chords(
    notes: Sequence[object], selected: set[int], *, step_ms: float = 18.0
) -> list[object]:
    """Spread simultaneous chord notes low-to-high while preserving chord ends."""

    scope = _scope(notes, selected)
    groups: dict[int, list[int]] = {}
    for index, note in enumerate(notes):
        if index in scope:
            groups.setdefault(round(float(note.start) * 10.0), []).append(index)
    output = list(notes)
    minimum_duration = 1.0
    for indices in groups.values():
        if len(indices) < 2:
            continue
        ordered = sorted(indices, key=lambda index: (notes[index].pitch, index))
        for offset_index, note_index in enumerate(ordered):
            note = notes[note_index]
            offset = float(step_ms) * offset_index
            output[note_index] = note._replace(
                start=float(note.start) + offset,
                dur=max(minimum_duration, float(note.dur) - offset),
                vel=max(1, int(note.vel) - offset_index),
            )
    return output


__all__ = ["humanize_notes", "quantize_note_starts", "strum_chords"]
