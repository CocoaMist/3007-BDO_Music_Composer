"""Independent MIDI import and transformation package."""

from .instruments import (
    BDO_INSTRUMENT_NAMES,
    BDO_INSTRUMENTS,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    DEFAULT_INSTRUMENT,
    _GM_TO_BDO_DRUM,
    gm_program_name,
    gm_to_bdo_instrument,
)
from .model import ChannelGroup, Note
from .parser import DEFAULT_BPM, DEFAULT_TIME_SIGNATURE, parse_midi
from .transforms import (
    BDO_VEL_LEVELS,
    DRUM_NOTE_MAX_DURATION_MS,
    DRUM_NOTE_TYPE,
    DRUM_ROLL_PITCHES,
    clamp_notes,
    floor_velocity,
    layered_velocity,
    map_drum_notes,
    normalize_drum_note_timing,
    rescale_velocity,
    stepped_velocity,
    transpose_notes,
)

__all__ = [
    "BDO_INSTRUMENT_NAMES", "BDO_INSTRUMENTS", "BDO_NOTE_MAX", "BDO_NOTE_MIN",
    "BDO_VEL_LEVELS", "ChannelGroup", "DEFAULT_BPM", "DEFAULT_INSTRUMENT",
    "DEFAULT_TIME_SIGNATURE", "DRUM_NOTE_MAX_DURATION_MS", "DRUM_NOTE_TYPE",
    "DRUM_ROLL_PITCHES", "Note", "_GM_TO_BDO_DRUM", "clamp_notes",
    "floor_velocity", "gm_program_name", "gm_to_bdo_instrument",
    "layered_velocity", "map_drum_notes", "normalize_drum_note_timing",
    "parse_midi", "rescale_velocity", "stepped_velocity", "transpose_notes",
]
