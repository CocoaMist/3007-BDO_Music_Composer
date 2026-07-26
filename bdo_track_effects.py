"""Game-aligned track mixer and effect-setting semantics.

The composition UI exposes two separate layers:

* one volume and three Aux sends per instrument track; and
* five master effect parameters shared by the score.

Black Desert stores both layers in each physical track's eight setting bytes.
The UI/XML names and 0..100 authoring range are verified from the local game
composition client.  The byte positions are strongly inferred from that order,
existing score inspection, and round trips, but still require one-variable
in-game save differentials before DSP behavior can be called verified.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


GAME_PERCENT_MIN = 0
GAME_PERCENT_MAX = 100
DEFAULT_TRACK_VOLUME = 70
TRACK_SETTINGS_SIZE = 8

TRACK_REVERB_SEND_INDEX = 0
MASTER_REVERB_TIME_INDEX = 1
TRACK_DELAY_SEND_INDEX = 2
MASTER_DELAY_FEEDBACK_INDEX = 3
TRACK_CHORUS_SEND_INDEX = 4
MASTER_CHORUS_FEEDBACK_INDEX = 5
MASTER_CHORUS_LFO_DEPTH_INDEX = 6
MASTER_CHORUS_LFO_FREQUENCY_INDEX = 7


def _raw_byte(value: object, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be an integer byte") from exc
    if not 0 <= result <= 255:
        raise ValueError(f"{label} must be between 0 and 255")
    return result


def game_percent(value: object, label: str) -> int:
    """Validate one value authored through the current game UI."""

    result = _raw_byte(value, label)
    if result > GAME_PERCENT_MAX:
        raise ValueError(
            f"{label} must be between {GAME_PERCENT_MIN} and "
            f"{GAME_PERCENT_MAX}"
        )
    return result


def raw_track_settings(values: Sequence[int] | bytes | bytearray) -> tuple[int, ...]:
    """Return eight lossless bytes without applying authoring-range clamps."""

    result = tuple(_raw_byte(value, "track setting") for value in values)
    if len(result) != TRACK_SETTINGS_SIZE:
        raise ValueError("track settings must contain exactly eight bytes")
    return result


@dataclass(frozen=True, slots=True)
class TrackEffectSends:
    reverb: int = 0
    delay: int = 0
    chorus: int = 0

    @classmethod
    def authored(
        cls,
        reverb: object = 0,
        delay: object = 0,
        chorus: object = 0,
    ) -> "TrackEffectSends":
        return cls(
            game_percent(reverb, "track reverb send"),
            game_percent(delay, "track delay send"),
            game_percent(chorus, "track chorus send"),
        )


@dataclass(frozen=True, slots=True)
class MasterEffects:
    reverb_time: int = 0
    delay_feedback: int = 0
    chorus_feedback: int = 0
    chorus_lfo_depth: int = 0
    chorus_lfo_frequency: int = 0

    @classmethod
    def authored(
        cls,
        reverb_time: object = 0,
        delay_feedback: object = 0,
        chorus_feedback: object = 0,
        chorus_lfo_depth: object = 0,
        chorus_lfo_frequency: object = 0,
    ) -> "MasterEffects":
        return cls(
            game_percent(reverb_time, "master reverb time"),
            game_percent(delay_feedback, "master delay feedback"),
            game_percent(chorus_feedback, "master chorus feedback"),
            game_percent(chorus_lfo_depth, "master chorus LFO depth"),
            game_percent(
                chorus_lfo_frequency,
                "master chorus LFO frequency",
            ),
        )

    @classmethod
    def from_legacy(
        cls,
        reverb: object = 0,
        delay: object = 0,
        chorus: Sequence[int] | None = None,
        *,
        authored: bool = False,
    ) -> "MasterEffects":
        values = tuple(chorus or (0, 0, 0))
        if len(values) != 3:
            raise ValueError("chorus must contain feedback, depth, and frequency")
        constructor = cls.authored if authored else cls
        return constructor(reverb, delay, *values)

    def legacy_values(self) -> tuple[int, int, tuple[int, int, int] | None]:
        chorus = (
            int(self.chorus_feedback),
            int(self.chorus_lfo_depth),
            int(self.chorus_lfo_frequency),
        )
        return (
            int(self.reverb_time),
            int(self.delay_feedback),
            chorus if any(chorus) else None,
        )


def decode_track_effects(
    values: Sequence[int] | bytes | bytearray,
) -> tuple[TrackEffectSends, MasterEffects]:
    settings = raw_track_settings(values)
    return (
        TrackEffectSends(
            settings[TRACK_REVERB_SEND_INDEX],
            settings[TRACK_DELAY_SEND_INDEX],
            settings[TRACK_CHORUS_SEND_INDEX],
        ),
        MasterEffects(
            settings[MASTER_REVERB_TIME_INDEX],
            settings[MASTER_DELAY_FEEDBACK_INDEX],
            settings[MASTER_CHORUS_FEEDBACK_INDEX],
            settings[MASTER_CHORUS_LFO_DEPTH_INDEX],
            settings[MASTER_CHORUS_LFO_FREQUENCY_INDEX],
        ),
    )


def encode_track_effects(
    base: Sequence[int] | bytes | bytearray = bytes(TRACK_SETTINGS_SIZE),
    *,
    sends: TrackEffectSends | None = None,
    master: MasterEffects | None = None,
) -> tuple[int, ...]:
    """Replace only the requested layer and preserve all other raw bytes."""

    settings = list(raw_track_settings(base))
    if sends is not None:
        settings[TRACK_REVERB_SEND_INDEX] = game_percent(
            sends.reverb, "track reverb send"
        )
        settings[TRACK_DELAY_SEND_INDEX] = game_percent(
            sends.delay, "track delay send"
        )
        settings[TRACK_CHORUS_SEND_INDEX] = game_percent(
            sends.chorus, "track chorus send"
        )
    if master is not None:
        normalized = MasterEffects.authored(
            master.reverb_time,
            master.delay_feedback,
            master.chorus_feedback,
            master.chorus_lfo_depth,
            master.chorus_lfo_frequency,
        )
        settings[MASTER_REVERB_TIME_INDEX] = normalized.reverb_time
        settings[MASTER_DELAY_FEEDBACK_INDEX] = normalized.delay_feedback
        settings[MASTER_CHORUS_FEEDBACK_INDEX] = normalized.chorus_feedback
        settings[MASTER_CHORUS_LFO_DEPTH_INDEX] = normalized.chorus_lfo_depth
        settings[MASTER_CHORUS_LFO_FREQUENCY_INDEX] = (
            normalized.chorus_lfo_frequency
        )
    return tuple(settings)


def track_volume_preview_gain(value: object) -> float:
    """Return the bounded linear preview interpretation of game track volume.

    The client confirms the 0..100 value but not the native Wwise taper.  A
    linear preview is therefore deterministic and honest, while export keeps
    the exact integer.  Raw legacy bytes above 100 preview at the UI maximum.
    """

    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        numeric = float(DEFAULT_TRACK_VOLUME)
    if not math.isfinite(numeric):
        numeric = float(DEFAULT_TRACK_VOLUME)
    return min(float(GAME_PERCENT_MAX), max(0.0, numeric)) / 100.0


__all__ = [
    "DEFAULT_TRACK_VOLUME",
    "GAME_PERCENT_MAX",
    "GAME_PERCENT_MIN",
    "MASTER_CHORUS_FEEDBACK_INDEX",
    "MASTER_CHORUS_LFO_DEPTH_INDEX",
    "MASTER_CHORUS_LFO_FREQUENCY_INDEX",
    "MASTER_DELAY_FEEDBACK_INDEX",
    "MASTER_REVERB_TIME_INDEX",
    "MasterEffects",
    "TRACK_CHORUS_SEND_INDEX",
    "TRACK_DELAY_SEND_INDEX",
    "TRACK_REVERB_SEND_INDEX",
    "TRACK_SETTINGS_SIZE",
    "TrackEffectSends",
    "decode_track_effects",
    "encode_track_effects",
    "game_percent",
    "raw_track_settings",
    "track_volume_preview_gain",
]
