"""Independent MIDI import and transformation package."""

from .instruments import (
    BDO_ENSEMBLE_PLAYER_LIMIT,
    BDO_INSTRUMENT_NAMES,
    BDO_INSTRUMENTS,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    DEFAULT_INSTRUMENT,
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    MARNIAN_SYNTH_MODE_OFFSETS,
    _GM_TO_BDO_DRUM,
    gm_program_name,
    gm_to_bdo_instrument,
    performance_instrument_id,
    unique_performance_instrument_ids,
)
from .gm_preview import (
    BDO_CYMBAL_TO_GM_PITCH,
    BDO_DRUM_SET_TO_GM_PITCH,
    BDO_TO_GM_PREVIEW_ROUTE,
    GmPreviewLayer,
    GmPreviewRoute,
    MARNIAN_GM_PREVIEW_LAYERS,
    gm_preview_layers,
    gm_preview_pitch,
    gm_preview_route,
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
    "BDO_CYMBAL_TO_GM_PITCH", "BDO_DRUM_SET_TO_GM_PITCH",
    "BDO_ENSEMBLE_PLAYER_LIMIT", "BDO_INSTRUMENT_NAMES", "BDO_INSTRUMENTS",
    "BDO_NOTE_MAX", "BDO_NOTE_MIN",
    "BDO_TO_GM_PREVIEW_ROUTE",
    "BDO_VEL_LEVELS", "ChannelGroup", "DEFAULT_BPM", "DEFAULT_INSTRUMENT",
    "DEFAULT_TIME_SIGNATURE", "DRUM_NOTE_MAX_DURATION_MS", "DRUM_NOTE_TYPE",
    "DRUM_ROLL_PITCHES", "GmPreviewLayer", "GmPreviewRoute",
    "MARNIAN_GM_PREVIEW_LAYERS", "MARNIAN_SYNTH_INSTRUMENT_IDS",
    "MARNIAN_SYNTH_MODE_OFFSETS", "Note", "_GM_TO_BDO_DRUM", "clamp_notes",
    "floor_velocity", "gm_preview_layers", "gm_preview_pitch",
    "gm_preview_route", "gm_program_name", "gm_to_bdo_instrument",
    "layered_velocity", "map_drum_notes", "normalize_drum_note_timing",
    "parse_midi", "performance_instrument_id", "rescale_velocity",
    "stepped_velocity", "transpose_notes", "unique_performance_instrument_ids",
]
