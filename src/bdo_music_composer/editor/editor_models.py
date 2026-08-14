"""Canonical Qt-free editor state and shared note-lane rules.

These types are consumed by the timeline, piano roll, project persistence and
main-window orchestration.  Keeping them outside the GUI entry module prevents
large widgets from depending on the main window merely for data annotations.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from functools import lru_cache

from bdo_music_composer.editor.bdo_instrument_adaptation import (
    GameInstrumentFamily,
    instrument_editor_display_adaptation,
    instrument_editor_display_adaptations,
)
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME


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
BDO_DRUM_PITCH_TRANSLATION_KEYS = {
    48: "底鼓",
    49: "小军鼓边击",
    50: "小军鼓",
    51: "鼓边重击",
    52: "小军鼓复击",
    53: "嗵鼓 1",
    54: "闭合踩镲",
    55: "嗵鼓 2",
    56: "脚踩踩镲",
    57: "嗵鼓 3",
    58: "开放踩镲",
    59: "嗵鼓 4",
    60: "嗵鼓 5",
    61: "碎音镲",
    62: "节奏镲",
    63: "小军鼓短滚奏",
    64: "小军鼓长滚奏",
}
# General MIDI channel-10 keys remain in their original pitch space until the
# explicit export projection.  The editor still needs semantic lane names so a
# drummer can distinguish drums, hi-hats and cymbals without reading piano
# notes.  Keep these labels compact enough for the fixed piano-roll key rail.
GM_DRUM_PITCH_NAMES = {
    35: "Kick A",
    36: "Kick",
    37: "Side Stick",
    38: "Snare",
    39: "Clap",
    40: "Snare E",
    41: "Tom Floor L",
    42: "Hi-Hat C",
    43: "Tom Floor H",
    44: "Hi-Hat Pdl",
    45: "Tom Low",
    46: "Hi-Hat O",
    47: "Tom Low-Mid",
    48: "Tom Hi-Mid",
    49: "Crash 1",
    50: "Tom High",
    51: "Ride 1",
    52: "China Cym",
    53: "Ride Bell",
    54: "Tambourine",
    55: "Splash Cym",
    56: "Cowbell",
    57: "Crash 2",
    58: "Vibra Slap",
    59: "Ride 2",
    60: "Bongo H",
    61: "Bongo L",
}
GM_DRUM_PITCH_TRANSLATION_KEYS = {
    35: "原声底鼓",
    36: "底鼓",
    37: "鼓边轻击",
    38: "小军鼓",
    39: "拍手",
    40: "电子小军鼓",
    41: "低音落地嗵鼓",
    42: "闭合踩镲",
    43: "高音落地嗵鼓",
    44: "脚踩踩镲",
    45: "低音嗵鼓",
    46: "开放踩镲",
    47: "中低音嗵鼓",
    48: "中高音嗵鼓",
    49: "碎音镲 1",
    50: "高音嗵鼓",
    51: "节奏镲 1",
    52: "中国镲",
    53: "镲帽",
    54: "铃鼓",
    55: "水镲",
    56: "牛铃",
    57: "碎音镲 2",
    58: "颤音器",
    59: "节奏镲 2",
    60: "高音邦戈鼓",
    61: "低音邦戈鼓",
}
BDO_DRUM_MIN = 48
BDO_DRUM_MAX = 64
BDO_SAMPLE_ONLY_PERCUSSION = frozenset({0x04, 0x05, 0x13})
GAME_PERCUSSION_KEY_NAMES = {
    0x04: {
        60: "Bng1-Open",
        65: "Bng2-Open",
        66: "Bng2-Close",
        67: "Bng2-Flam",
        72: "Cng1-Open",
        73: "Cng1-Close",
        74: "Cng1-Flam",
        77: "Cng2-Open",
        78: "Cng2-Close",
        79: "Cng2-Flam",
    },
    0x05: {
        60: "HIT",
        65: "HIT",
        71: "HIT",
    },
}
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


@dataclass(frozen=True, slots=True)
class ArrangementClipState:
    """One independently movable/scalable module inside an arrangement track."""

    clip_id: str
    start_ms: float
    end_ms: float
    content_start_ms: float
    content_end_ms: float
    time_offset_ms: float = 0.0
    display_name: str = ""
    color: str = ""


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
    clip_start_ms: float | None = None
    clip_end_ms: float | None = None
    arrangement_group_id: str = ""
    arrangement_clips: list[ArrangementClipState] = field(default_factory=list)

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
        int(getattr(note, "ntype", 0)) == 99
        for note in track.notes
    )


def percussion_key_label_for_track(
    track: TrackState,
    pitch: int,
) -> str | None:
    """Return the source-space game key name for a percussion instrument.

    Drum-set tracks retain their BDO or pending-GM piece names. Hand-drum and
    cymbal tracks use labels observed in the game composer. Percussion without
    verified named-key evidence falls back to pitch names. This changes labels
    only and never remaps a ``Note``.
    """

    instrument_id = int(track.bdo_instrument_id)
    adaptation = instrument_editor_display_adaptation(instrument_id)
    if (
        adaptation is None
        or adaptation.family is not GameInstrumentFamily.PERCUSSION
    ):
        return None
    if instrument_id == 0x0D:
        labels = (
            BDO_DRUM_PITCH_NAMES
            if track_uses_canonical_drum_lanes(track)
            else GM_DRUM_PITCH_NAMES
        )
        return labels.get(int(pitch))
    if instrument_id in GAME_PERCUSSION_KEY_NAMES:
        return GAME_PERCUSSION_KEY_NAMES[instrument_id].get(int(pitch))
    return note_name(int(pitch))


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
