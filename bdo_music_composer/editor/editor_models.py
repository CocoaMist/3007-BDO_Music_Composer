"""Canonical Qt-free editor state and shared note-lane rules.

These types are consumed by the timeline, piano roll, project persistence and
main-window orchestration.  Keeping them outside the GUI entry module prevents
large widgets from depending on the main window merely for data annotations.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from functools import lru_cache

from bdo_instrument_adaptation import instrument_editor_display_adaptations
from bdo_track_effects import DEFAULT_TRACK_VOLUME


BDO_DRUM_PITCH_NAMES = {
    48: "Kck",
    49: "SnrSide",
    50: "SnrHit",
    51: "RimShot",
    52: "SnrFlam",
    53: "Tom1",
    54: "HihatC",
    55: "Tom2",
    56: "HatPdl",
    57: "Tom3",
    58: "HihatO",
    59: "Tom4",
    60: "Tom5",
    61: "CymCrsh",
    62: "CymRide",
    63: "SnrRollS",
    64: "SnrRollL",
}
BDO_DRUM_MIN = 48
BDO_DRUM_MAX = 64
BDO_SAMPLE_ONLY_PERCUSSION = frozenset({0x04, 0x05, 0x13})
ARTICULATION_ONSET_TOLERANCE_MS = 12.0


BDO_EDITOR_PITCH_RANGES = {
    instrument_id: adaptation.legal_pitches
    for instrument_id, adaptation in instrument_editor_display_adaptations().items()
    if adaptation.legal_pitches is not None
}


def note_name(midi_note: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    octave = int(midi_note) // 12 - 1
    return f"{names[int(midi_note) % 12]}{octave}"


@dataclass
class TrackState:
    track_id: int
    notes: list
    gm_program: int
    is_percussion: bool
    display_name: str
    bdo_instrument_id: int
    muted: bool = False
    solo: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None
    marnian_synth_mode: str = "basic"
    color: str = "#d88c6f"
    effect_settings_placeholder: dict = field(default_factory=dict)
    performance_controls: list[dict] = field(default_factory=list)
    notes_optimized: bool = False
    bdo_track_volume: int = DEFAULT_TRACK_VOLUME
    bdo_track_settings: tuple[int, ...] = (0,) * 8
    bdo_source_group_index: int | None = None
    bdo_source_note_records: tuple[tuple, ...] = ()

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def end_ms(self) -> float:
        return max((note.start + note.dur for note in self.notes), default=0.0)

    @property
    def pitch_range(self) -> str:
        if not self.notes:
            return "-"
        low = min(note.pitch for note in self.notes)
        high = max(note.pitch for note in self.notes)
        return f"{note_name(low)} - {note_name(high)}"


@dataclass(frozen=True, slots=True)
class GhostNoteProjection:
    """One formal note projected from another track without losing identity."""

    note: object
    track_id: int = -1
    instrument_id: int = -1
    color: str = "#77787c"

    @property
    def pitch(self) -> int:
        return int(self.note.pitch)

    @property
    def vel(self) -> int:
        return int(self.note.vel)

    @property
    def start(self) -> float:
        return float(self.note.start)

    @property
    def dur(self) -> float:
        return float(self.note.dur)

    @property
    def ntype(self) -> int:
        return int(self.note.ntype)


def track_uses_canonical_drum_lanes(track: TrackState) -> bool:
    """Distinguish BDO 48–64/type-99 notes from imported GM drum keys."""

    if int(track.bdo_instrument_id) != 0x0D:
        return False
    if track.bdo_source_group_index is not None or not track.notes:
        return True
    return all(
        BDO_DRUM_MIN <= int(note.pitch) <= BDO_DRUM_MAX
        and int(getattr(note, "ntype", 0)) == 99
        for note in track.notes
    )


def same_onset_articulation_indices(
    notes: list,
    selected_indices: set[int],
    tolerance_ms: float = ARTICULATION_ONSET_TOLERANCE_MS,
) -> set[int]:
    """Expand a selection to every note sharing one of its onsets."""

    selected_starts = sorted(
        float(notes[index].start)
        for index in selected_indices
        if 0 <= index < len(notes)
    )
    if not selected_starts:
        return set()
    tolerance = max(0.0, float(tolerance_ms))
    matched: set[int] = set()
    for index, note in enumerate(notes):
        start = float(note.start)
        insertion = bisect_left(selected_starts, start)
        neighbors = selected_starts[max(0, insertion - 1) : insertion + 1]
        if any(abs(start - selected_start) <= tolerance for selected_start in neighbors):
            matched.add(index)
    return matched


@lru_cache(maxsize=96)
def game_supported_pitches(
    instrument_id: int,
    synth_mode: str = "basic",
) -> frozenset[int] | None:
    """Return verified game-editor pitches, independent of preview coverage."""

    del synth_mode
    editor_range = BDO_EDITOR_PITCH_RANGES.get(int(instrument_id))
    return frozenset(editor_range) if editor_range is not None else None
