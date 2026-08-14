"""Versioned, bounded clipboard wire format for MIDI-note selections."""

from __future__ import annotations

import json
import math
from typing import Iterable

from bdo_midi import Note


NOTE_CLIPBOARD_VERSION = 1
MAX_CLIPBOARD_NOTES = 50_000
MAX_CLIPBOARD_BYTES = 2 * 1024 * 1024


def normalized_clipboard_notes(notes: Iterable[Note]) -> tuple[Note, ...]:
    values = tuple(notes)
    if not values:
        return ()
    if len(values) > MAX_CLIPBOARD_NOTES:
        raise ValueError("note clipboard selection is too large")
    origin = min(float(note.start) for note in values)
    normalized = tuple(
        note._replace(start=float(note.start) - origin)
        for note in values
    )
    _validate_notes(normalized)
    return normalized


def encode_note_clipboard(notes: Iterable[Note]) -> bytes:
    normalized = normalized_clipboard_notes(notes)
    if not normalized:
        raise ValueError("note clipboard selection is empty")
    payload = json.dumps(
        {
            "version": NOTE_CLIPBOARD_VERSION,
            "notes": [list(note) for note in normalized],
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_CLIPBOARD_BYTES:
        raise ValueError("note clipboard payload is too large")
    return payload


def decode_note_clipboard(payload: bytes | bytearray | memoryview) -> tuple[Note, ...]:
    raw = bytes(payload)
    if not raw or len(raw) > MAX_CLIPBOARD_BYTES:
        raise ValueError("invalid note clipboard payload size")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid note clipboard JSON") from exc
    if not isinstance(document, dict) or document.get("version") != NOTE_CLIPBOARD_VERSION:
        raise ValueError("unsupported note clipboard version")
    rows = document.get("notes")
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_CLIPBOARD_NOTES:
        raise ValueError("invalid note clipboard note count")
    notes: list[Note] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError("invalid note clipboard note shape")
        try:
            pitch, velocity, start, duration, ntype = row
            note = Note(
                int(pitch), int(velocity), float(start), float(duration), int(ntype)
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid note clipboard note value") from exc
        notes.append(note)
    result = tuple(notes)
    _validate_notes(result)
    if min(float(note.start) for note in result) != 0.0:
        raise ValueError("note clipboard starts must be relative")
    return result


def _validate_notes(notes: tuple[Note, ...]) -> None:
    for note in notes:
        if not (
            0 <= int(note.pitch) <= 127
            and 0 <= int(note.vel) <= 127
            and math.isfinite(float(note.start))
            and float(note.start) >= 0.0
            and math.isfinite(float(note.dur))
            and float(note.dur) > 0.0
            and 0 <= int(note.ntype) <= 255
        ):
            raise ValueError("invalid note clipboard note value")


__all__ = [
    "MAX_CLIPBOARD_BYTES",
    "MAX_CLIPBOARD_NOTES",
    "decode_note_clipboard",
    "encode_note_clipboard",
    "normalized_clipboard_notes",
]
