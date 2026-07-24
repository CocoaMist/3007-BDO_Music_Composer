"""Editor-facing MIDI value objects."""

from __future__ import annotations

from typing import NamedTuple


class Note(NamedTuple):
    """Immutable note shape shared by the editor, optimizer, and exporter."""

    pitch: int
    vel: int
    start: float
    dur: float
    ntype: int


ChannelGroup = tuple[list[Note], int, bool]


__all__ = ["ChannelGroup", "Note"]
