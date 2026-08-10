"""General MIDI preview routes for logical BDO instruments.

This module is the inverse *preview* boundary of :func:`gm_to_bdo_instrument`.
It does not participate in MIDI import or BDO export.  A SoundFont renderer may
use these routes when no user-owned BDO sample pack is active, while keeping
the score's BDO instrument IDs and note pitches unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from .instruments import (
    BDO_INSTRUMENT_NAMES,
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    MARNIAN_SYNTH_MODE_OFFSETS,
    performance_instrument_id,
)


@dataclass(frozen=True, slots=True)
class GmPreviewRoute:
    """One zero-based SoundFont bank/program selection.

    ``fallback_*`` is used when a GM-compatible bank does not provide the
    preferred variation.  Standard melodic presets use bank 0 and therefore
    need no separate fallback.  ``waveform`` records the intended Marnian
    oscillator family even when General MIDI has no exact triangle preset.
    """

    bank: int
    program: int
    percussion: bool = False
    fallback_bank: int | None = None
    fallback_program: int | None = None
    waveform: str | None = None


@dataclass(frozen=True, slots=True)
class GmPreviewLayer:
    """Deterministic unison layer for an approximate Marnian mode preview."""

    semitones: int = 0
    cents: float = 0.0
    pan: float = 0.0
    gain: float = 1.0


# Program numbers are General MIDI's zero-based values.  Beginner and
# Florchestra variants intentionally share a preset when GM has no honest
# distinction.  The route remains an editing aid, never a claim of BDO timbre.
BDO_TO_GM_PREVIEW_ROUTE: dict[int, GmPreviewRoute] = {
    0x00: GmPreviewRoute(0, 24),  # Nylon-string acoustic guitar
    0x01: GmPreviewRoute(0, 73),  # Flute
    0x02: GmPreviewRoute(0, 74),  # Recorder
    0x04: GmPreviewRoute(0, 116),  # Melodic taiko keeps the BDO hit pitches
    0x05: GmPreviewRoute(128, 0, percussion=True),
    0x06: GmPreviewRoute(0, 46),  # Orchestral harp
    0x07: GmPreviewRoute(0, 0),  # Acoustic grand piano
    0x08: GmPreviewRoute(0, 40),  # Violin
    0x0A: GmPreviewRoute(0, 25),  # Steel-string acoustic guitar
    0x0B: GmPreviewRoute(0, 73),  # Flute
    0x0D: GmPreviewRoute(128, 0, percussion=True),
    0x0E: GmPreviewRoute(0, 38),  # Synth bass 1
    0x0F: GmPreviewRoute(0, 43),  # Contrabass
    0x10: GmPreviewRoute(0, 46),  # Orchestral harp
    0x11: GmPreviewRoute(0, 0),  # Acoustic grand piano
    0x12: GmPreviewRoute(0, 40),  # Violin
    0x13: GmPreviewRoute(0, 114),  # Steel drums are the closest GM handpan
    0x14: GmPreviewRoute(0, 81, waveform="saw"),
    # MuseScore General and FluidR3 expose a sine variation at 8:80.  A plain
    # GM bank may fall back to its standard square lead instead.
    0x18: GmPreviewRoute(
        8,
        80,
        fallback_bank=0,
        fallback_program=80,
        waveform="sine",
    ),
    0x1C: GmPreviewRoute(0, 80, waveform="square"),
    # GM has no triangle-wave preset.  Warm pad is deliberately selected as a
    # soft, low-harmonic approximation rather than inventing an exact match.
    0x20: GmPreviewRoute(0, 89, waveform="triangle"),
    0x24: GmPreviewRoute(0, 27),  # Clean electric guitar
    0x25: GmPreviewRoute(0, 29),  # Overdriven guitar
    0x26: GmPreviewRoute(0, 30),  # Distortion guitar
    0x27: GmPreviewRoute(0, 71),  # Clarinet
    0x28: GmPreviewRoute(0, 60),  # French horn
}


# BDO's 48..64 drum lanes are semantic game IDs, not GM drum notes.  The
# reverse map is explicit so preview never guesses from pitch proximity.
BDO_DRUM_SET_TO_GM_PITCH: dict[int, int] = {
    48: 36,  # Kck -> Bass Drum 1
    49: 37,  # SnrSide -> Side Stick
    50: 38,  # SnrHit -> Acoustic Snare
    51: 37,  # RimShot -> Side Stick (closest GM lane)
    52: 38,  # SnrFlam -> Acoustic Snare (GM has no flam lane)
    53: 50,  # Tom1 -> High Tom
    54: 42,  # HihatC -> Closed Hi-Hat
    55: 48,  # Tom2 -> Hi-Mid Tom
    56: 44,  # HatPdl -> Pedal Hi-Hat
    57: 47,  # Tom3 -> Low-Mid Tom
    58: 46,  # HihatO -> Open Hi-Hat
    59: 45,  # Tom4 -> Low Tom
    60: 41,  # Tom5 -> Low Floor Tom
    61: 49,  # CymCrsh -> Crash Cymbal 1
    62: 51,  # CymRide -> Ride Cymbal 1
    63: 38,  # SnrRollS -> repeated snare in a future renderer
    64: 38,  # SnrRollL -> repeated snare in a future renderer
}


# The beginner cymbal exposes three game lanes rather than chromatic pitches.
BDO_CYMBAL_TO_GM_PITCH: dict[int, int] = {
    60: 49,  # Crash Cymbal 1
    65: 51,  # Ride Cymbal 1
    71: 57,  # Crash Cymbal 2
}


# These layers describe mode identity for the future SoundFont backend.  They
# are bounded approximations only; BDO samples remain the authoritative route.
MARNIAN_GM_PREVIEW_LAYERS: dict[str, tuple[GmPreviewLayer, ...]] = {
    "basic": (GmPreviewLayer(),),
    "stereo": (
        GmPreviewLayer(cents=-4.0, pan=-0.6, gain=0.72),
        GmPreviewLayer(cents=4.0, pan=0.6, gain=0.72),
    ),
    "super": (
        GmPreviewLayer(cents=-7.0, pan=-0.7, gain=0.56),
        GmPreviewLayer(gain=0.64),
        GmPreviewLayer(cents=7.0, pan=0.7, gain=0.56),
    ),
    "superoct": (
        GmPreviewLayer(cents=-5.0, pan=-0.55, gain=0.52),
        GmPreviewLayer(cents=5.0, pan=0.55, gain=0.52),
        GmPreviewLayer(semitones=12, gain=0.46),
    ),
}


def gm_preview_route(instrument_id: int) -> GmPreviewRoute:
    """Return the explicit GM preview route for one logical BDO instrument.

    Serialized Marnian mode IDs are collapsed to their physical base
    instrument.  Unknown IDs fail closed rather than silently sounding as a
    piano, which keeps new game instruments visible during review.
    """

    logical_id = performance_instrument_id(int(instrument_id))
    try:
        return BDO_TO_GM_PREVIEW_ROUTE[logical_id]
    except KeyError as exc:
        raise ValueError(
            f"no General MIDI preview route for BDO instrument 0x{logical_id:02x}"
        ) from exc


def gm_preview_pitch(instrument_id: int, pitch: int) -> int:
    """Map a BDO note to the selected GM preset's note-number semantics."""

    logical_id = performance_instrument_id(int(instrument_id))
    numeric_pitch = max(0, min(127, int(pitch)))
    if logical_id == 0x0D:
        return BDO_DRUM_SET_TO_GM_PITCH.get(numeric_pitch, 36)
    if logical_id == 0x05:
        return BDO_CYMBAL_TO_GM_PITCH.get(numeric_pitch, 49)
    return numeric_pitch


def gm_preview_layers(
    instrument_id: int,
    synth_mode: str = "basic",
) -> tuple[GmPreviewLayer, ...]:
    """Return bounded mode layers; non-Marnian instruments stay single-voice."""

    logical_id = performance_instrument_id(int(instrument_id))
    if logical_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
        return MARNIAN_GM_PREVIEW_LAYERS["basic"]
    mode = str(synth_mode or "basic").casefold()
    if mode not in MARNIAN_SYNTH_MODE_OFFSETS:
        mode = "basic"
    return MARNIAN_GM_PREVIEW_LAYERS[mode]


if set(BDO_TO_GM_PREVIEW_ROUTE) != set(BDO_INSTRUMENT_NAMES):
    raise RuntimeError("General MIDI preview routes must cover the BDO catalog exactly")


__all__ = [
    "BDO_CYMBAL_TO_GM_PITCH",
    "BDO_DRUM_SET_TO_GM_PITCH",
    "BDO_TO_GM_PREVIEW_ROUTE",
    "GmPreviewLayer",
    "GmPreviewRoute",
    "MARNIAN_GM_PREVIEW_LAYERS",
    "gm_preview_layers",
    "gm_preview_pitch",
    "gm_preview_route",
]
