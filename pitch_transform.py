"""Immutable pitch-transform policy shared by UI, validation, preview, and export.

The editor always keeps source pitches unchanged.  This module resolves the
effective export/preview offset for a stable logical track ID, so consumers do
not independently reinterpret global transpose and per-voice octave choices.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence


PITCH_OVERRIDE_MODE_OCTAVE = "octave"
PITCH_OVERRIDE_MODE_SEMITONE = "semitone"
PITCH_OVERRIDE_MODES = frozenset(
    {PITCH_OVERRIDE_MODE_OCTAVE, PITCH_OVERRIDE_MODE_SEMITONE}
)

PITCH_OVERRIDE_PROVENANCE_USER = "user"
PITCH_OVERRIDE_PROVENANCE_AUTO = "auto"
PITCH_OVERRIDE_PROVENANCES = frozenset(
    {PITCH_OVERRIDE_PROVENANCE_USER, PITCH_OVERRIDE_PROVENANCE_AUTO}
)

MIN_PITCH_OFFSET = -48
MAX_PITCH_OFFSET = 48
BDO_DRUM_INSTRUMENT_ID = 0x0D


def _bounded_offset(value: object) -> int:
    offset = int(value)
    if not MIN_PITCH_OFFSET <= offset <= MAX_PITCH_OFFSET:
        raise ValueError(
            f"pitch offset must be in [{MIN_PITCH_OFFSET}, {MAX_PITCH_OFFSET}]"
        )
    return offset


def track_uses_percussion_pitch_semantics(
    track: object,
    *,
    drum_instrument_id: int = BDO_DRUM_INSTRUMENT_ID,
) -> bool:
    """Return whether pitch transforms must treat a track as percussion.

    ``is_percussion`` records source/MIDI semantics, while assigning the BDO
    drum-set instrument changes the destination semantics without necessarily
    mutating that source flag. Preview, validation and export must honor either
    signal so a mapped drum track is never transposed as a melody track.
    """

    if bool(getattr(track, "is_percussion", False)):
        return True
    try:
        instrument_id = int(getattr(track, "bdo_instrument_id"))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return instrument_id == int(drum_instrument_id)


@dataclass(frozen=True, slots=True)
class TrackPitchOverride:
    """One explicit transform attached to a stable logical track identity."""

    track_id: int
    semitones: int
    mode: str = PITCH_OVERRIDE_MODE_OCTAVE
    provenance: str = PITCH_OVERRIDE_PROVENANCE_USER

    def __post_init__(self) -> None:
        object.__setattr__(self, "track_id", int(self.track_id))
        offset = _bounded_offset(self.semitones)
        mode = str(self.mode or PITCH_OVERRIDE_MODE_OCTAVE)
        if mode not in PITCH_OVERRIDE_MODES:
            raise ValueError(f"unsupported pitch override mode: {mode}")
        if mode == PITCH_OVERRIDE_MODE_OCTAVE and offset % 12:
            raise ValueError("automatic/voice octave adaptation must use 12k semitones")
        provenance = str(
            self.provenance or PITCH_OVERRIDE_PROVENANCE_USER
        )
        if provenance not in PITCH_OVERRIDE_PROVENANCES:
            raise ValueError(
                f"unsupported pitch override provenance: {provenance}"
            )
        if (
            provenance == PITCH_OVERRIDE_PROVENANCE_AUTO
            and mode != PITCH_OVERRIDE_MODE_OCTAVE
        ):
            raise ValueError("automatic pitch overrides must be octave adaptations")
        object.__setattr__(self, "semitones", offset)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "provenance", provenance)

    @classmethod
    def from_payload(cls, value: object) -> "TrackPitchOverride":
        if not isinstance(value, Mapping):
            raise ValueError("track pitch override must be an object")
        return cls(
            track_id=int(value["track_id"]),
            semitones=int(value.get("semitones", 0)),
            mode=str(value.get("mode") or PITCH_OVERRIDE_MODE_OCTAVE),
            provenance=str(
                value.get("provenance") or PITCH_OVERRIDE_PROVENANCE_USER
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "semitones": self.semitones,
            "mode": self.mode,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class ResolvedTrackPitch:
    track_id: int
    global_semitones: int
    track_semitones: int
    effective_semitones: int
    mode: str | None
    provenance: str | None
    drum_exempt: bool = False


@dataclass(frozen=True, slots=True)
class PitchTransformPlan:
    """A deterministic, Qt-free projection over unchanged editor notes."""

    global_semitones: int = 0
    track_overrides: tuple[TrackPitchOverride, ...] = ()

    def __post_init__(self) -> None:
        # Global transpose predates this plan and historically accepted any
        # integer at non-UI compatibility boundaries. Keep that behavior;
        # validation remains responsible for blocking resulting wire ranges.
        global_semitones = int(self.global_semitones)
        normalized = tuple(
            sorted(
                (
                    item
                    if isinstance(item, TrackPitchOverride)
                    else TrackPitchOverride.from_payload(item)
                    for item in self.track_overrides
                ),
                key=lambda item: item.track_id,
            )
        )
        track_ids = [item.track_id for item in normalized]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("pitch transform plan contains duplicate track IDs")
        object.__setattr__(self, "global_semitones", global_semitones)
        object.__setattr__(self, "track_overrides", normalized)

    @classmethod
    def from_payload(
        cls,
        value: object,
        *,
        default_global_semitones: int = 0,
    ) -> "PitchTransformPlan":
        """Read a project payload and discard malformed optional overrides."""

        source = value if isinstance(value, Mapping) else {}
        global_semitones = source.get(
            "global_semitones",
            default_global_semitones,
        )
        raw_overrides = source.get("track_overrides", ())
        overrides: list[TrackPitchOverride] = []
        if isinstance(raw_overrides, Mapping):
            raw_overrides = [
                {
                    "track_id": track_id,
                    "semitones": semitones,
                    "mode": PITCH_OVERRIDE_MODE_OCTAVE,
                    "provenance": PITCH_OVERRIDE_PROVENANCE_USER,
                }
                for track_id, semitones in raw_overrides.items()
            ]
        if isinstance(raw_overrides, (list, tuple)):
            seen: set[int] = set()
            for raw in raw_overrides:
                try:
                    override = TrackPitchOverride.from_payload(raw)
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if override.track_id in seen:
                    continue
                seen.add(override.track_id)
                overrides.append(override)
        try:
            return cls(int(global_semitones), tuple(overrides))
        except (TypeError, ValueError, OverflowError):
            return cls(int(default_global_semitones), tuple(overrides))

    def to_payload(self) -> dict[str, Any]:
        return {
            "global_semitones": self.global_semitones,
            "track_overrides": [
                item.to_payload() for item in self.track_overrides
            ],
        }

    def override_for(self, track_id: int) -> TrackPitchOverride | None:
        target = int(track_id)
        return next(
            (item for item in self.track_overrides if item.track_id == target),
            None,
        )

    def resolve(
        self,
        track_id: int,
        *,
        is_drum: bool = False,
    ) -> ResolvedTrackPitch:
        target = int(track_id)
        override = self.override_for(target)
        if is_drum:
            return ResolvedTrackPitch(
                target,
                self.global_semitones,
                0,
                0,
                override.mode if override is not None else None,
                override.provenance if override is not None else None,
                True,
            )
        track_semitones = override.semitones if override is not None else 0
        return ResolvedTrackPitch(
            target,
            self.global_semitones,
            track_semitones,
            self.global_semitones + track_semitones,
            override.mode if override is not None else None,
            override.provenance if override is not None else None,
        )

    def effective_semitones(
        self,
        track_id: int,
        *,
        is_drum: bool = False,
    ) -> int:
        return self.resolve(track_id, is_drum=is_drum).effective_semitones

    def effective_track_semitones(
        self,
        track: object,
        *,
        drum_instrument_id: int = BDO_DRUM_INSTRUMENT_ID,
    ) -> int:
        """Resolve one track through the shared percussion classification."""

        return self.effective_semitones(
            int(getattr(track, "track_id")),
            is_drum=track_uses_percussion_pitch_semantics(
                track,
                drum_instrument_id=drum_instrument_id,
            ),
        )

    def with_global(self, semitones: int) -> "PitchTransformPlan":
        return replace(self, global_semitones=semitones)

    def with_track_octave(
        self,
        track_id: int,
        semitones: int,
        *,
        provenance: str = PITCH_OVERRIDE_PROVENANCE_USER,
    ) -> "PitchTransformPlan":
        target = int(track_id)
        offset = _bounded_offset(semitones)
        retained = tuple(
            item for item in self.track_overrides if item.track_id != target
        )
        if not offset:
            return replace(self, track_overrides=retained)
        return replace(
            self,
            track_overrides=(
                *retained,
                TrackPitchOverride(
                    target,
                    offset,
                    PITCH_OVERRIDE_MODE_OCTAVE,
                    provenance,
                ),
            ),
        )

    def without_track(self, track_id: int) -> "PitchTransformPlan":
        target = int(track_id)
        return replace(
            self,
            track_overrides=tuple(
                item for item in self.track_overrides
                if item.track_id != target
            ),
        )

    def pruned(self, track_ids: Iterable[int]) -> "PitchTransformPlan":
        valid = {int(track_id) for track_id in track_ids}
        return replace(
            self,
            track_overrides=tuple(
                item for item in self.track_overrides
                if item.track_id in valid
            ),
        )

    def is_neutral(self, tracks: Sequence[object] | None = None) -> bool:
        if tracks is None:
            return not self.global_semitones and not self.track_overrides
        return all(
            not self.effective_track_semitones(track)
            for track in tracks
        )


def transpose_notes(
    notes: Iterable[object],
    semitones: int,
) -> tuple[object, ...]:
    """Return detached note records while preserving the five-field shape."""

    offset = int(semitones)
    if not offset:
        return tuple(notes)
    return tuple(
        note._replace(pitch=int(note.pitch) + offset)
        for note in notes
    )


__all__ = [
    "MAX_PITCH_OFFSET",
    "MIN_PITCH_OFFSET",
    "BDO_DRUM_INSTRUMENT_ID",
    "PITCH_OVERRIDE_MODE_OCTAVE",
    "PITCH_OVERRIDE_MODE_SEMITONE",
    "PITCH_OVERRIDE_PROVENANCE_AUTO",
    "PITCH_OVERRIDE_PROVENANCE_USER",
    "PitchTransformPlan",
    "ResolvedTrackPitch",
    "TrackPitchOverride",
    "track_uses_percussion_pitch_semantics",
    "transpose_notes",
]
