"""Qt-free output-route identities for editor operations.

``TrackState`` still carries the BDO fields today.  Editor operations consume
this value object instead of treating the lane itself as an instrument, so a
future DAW-style Track/Route split does not change their compatibility rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME, raw_track_settings
from bdo_music_composer.editor.game_score_model import serialized_game_instrument_id
from bdo_music_composer.editor.pitch_transform import (
    track_uses_percussion_pitch_semantics,
)


@dataclass(frozen=True, slots=True)
class GameOutputRouteIdentity:
    """Everything that must agree for two lanes to become one game route."""

    instrument_id: int
    percussion_pitch_semantics: bool
    volume: int
    settings: tuple[int, ...]


def game_output_route_identity(track: object) -> GameOutputRouteIdentity:
    """Project one current editor lane onto its serialized BDO destination."""

    return GameOutputRouteIdentity(
        instrument_id=serialized_game_instrument_id(track),
        percussion_pitch_semantics=track_uses_percussion_pitch_semantics(track),
        volume=int(getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)),
        settings=tuple(raw_track_settings(
            getattr(track, "bdo_track_settings", (0,) * 8)
        )),
    )


__all__ = ["GameOutputRouteIdentity", "game_output_route_identity"]
