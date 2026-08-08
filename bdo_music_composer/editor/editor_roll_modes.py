"""Qt-free roll-mode capabilities shared by editor presentations.

Roll modes change how the existing ``Note`` wire values are presented and
edited.  They never create a second note model or reinterpret export data.
Future layouts that need extra identity (for example guitar string/fret) must
store that identity in a separate, optional sidecar rather than changing
``Note(pitch, vel, start, dur, ntype)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EditorRollMode(str, Enum):
    PIANO = "piano"
    PERCUSSION = "percussion"


@dataclass(frozen=True, slots=True)
class EditorRollModeSpec:
    mode: EditorRollMode
    source_label: str
    shows_piano_keys: bool
    shows_note_duration: bool
    note_shape: str


PIANO_ROLL_MODE = EditorRollModeSpec(
    EditorRollMode.PIANO,
    "钢琴模式",
    True,
    True,
    "block",
)
PERCUSSION_ROLL_MODE = EditorRollModeSpec(
    EditorRollMode.PERCUSSION,
    "打击乐模式",
    False,
    False,
    "diamond",
)

ROLL_MODE_SPECS = {
    spec.mode: spec
    for spec in (PIANO_ROLL_MODE, PERCUSSION_ROLL_MODE)
}


def available_roll_modes(instrument_id: int) -> tuple[EditorRollModeSpec, ...]:
    """Return safe presentation modes for one BDO target instrument."""

    if int(instrument_id) == 0x0D:
        return PIANO_ROLL_MODE, PERCUSSION_ROLL_MODE
    return (PIANO_ROLL_MODE,)


def default_roll_mode(instrument_id: int) -> EditorRollModeSpec:
    """Select percussion presentation only for the canonical drum-set target."""

    if int(instrument_id) == 0x0D:
        return PERCUSSION_ROLL_MODE
    return PIANO_ROLL_MODE
