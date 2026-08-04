"""Game-first score semantics shared by UI, persistence, preview, and export.

The BDO authoring format stores notes and one mixer state per serialized game
instrument.  Mute/Solo are local monitoring controls and must never select the
formal score.  Legacy ``volume_scale`` values are likewise not game fields;
they are baked into visible note velocities at compatibility boundaries.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math
from typing import Callable, Iterable, Sequence

from bdo_midi import (
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    MARNIAN_SYNTH_MODE_OFFSETS,
    floor_velocity,
    layered_velocity,
    rescale_velocity,
    stepped_velocity,
)
from bdo_common.bdo_track_effects import (
    DEFAULT_TRACK_VOLUME,
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
    raw_track_settings,
)
from bdo_music_composer.core.conversion_settings import VELOCITY_MODE_PRESERVE


GAME_VELOCITY_MIN = 0
GAME_VELOCITY_MAX = 127
GAME_WIRE_BYTE_MAX = 255


def serialized_game_instrument_id(track: object) -> int:
    """Return the instrument identity that the v9 score actually stores."""

    instrument_id = int(getattr(track, "bdo_instrument_id"))
    if instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
        return instrument_id
    mode = str(getattr(track, "marnian_synth_mode", "basic") or "basic")
    if mode not in MARNIAN_SYNTH_MODE_OFFSETS:
        raise ValueError(f"unsupported Marnian synth mode: {mode}")
    return instrument_id + MARNIAN_SYNTH_MODE_OFFSETS[mode]


def decode_serialized_game_instrument_id(value: object) -> tuple[int, str]:
    """Return the logical instrument and Marnian mode stored by one wire ID."""

    serialized_id = int(value)
    for base_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
        for mode, offset in MARNIAN_SYNTH_MODE_OFFSETS.items():
            if serialized_id == base_id + offset:
                return base_id, mode
    return serialized_id, "basic"


def formal_score_tracks(tracks: Iterable[object]) -> tuple[object, ...]:
    """Return every editor track, independent of local monitoring state."""

    return tuple(tracks)


def preview_tracks(tracks: Iterable[object]) -> tuple[object, ...]:
    """Apply local Mute/Solo monitoring without changing the formal score."""

    values = tuple(tracks)
    has_solo = any(bool(getattr(track, "solo", False)) for track in values)
    if has_solo:
        return tuple(
            track
            for track in values
            if bool(getattr(track, "solo", False))
            and not bool(getattr(track, "muted", False))
        )
    return tuple(track for track in values if not bool(getattr(track, "muted", False)))


def _legacy_scale(value: object) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    if not math.isfinite(scale) or scale < 0.0:
        return 1.0
    return scale


def scaled_game_velocity(value: object, scale: object) -> int:
    """Bake one obsolete linear scale into the game's 0..127 velocity field."""

    velocity = round(float(value) * _legacy_scale(scale))
    return max(GAME_VELOCITY_MIN, min(GAME_VELOCITY_MAX, velocity))


def bake_legacy_velocity_scale(
    notes: Iterable[object],
    scale: object,
) -> tuple[object, ...]:
    """Return detached notes with a legacy scale made explicit in velocity."""

    values = tuple(notes)
    normalized = _legacy_scale(scale)
    if math.isclose(normalized, 1.0, abs_tol=1e-12):
        return values
    return tuple(
        note._replace(vel=scaled_game_velocity(getattr(note, "vel"), normalized))
        for note in values
    )


def bake_game_velocity_transform(
    notes: Iterable[object],
    settings: object,
    *,
    legacy_scale: object = 1.0,
) -> tuple[object, ...]:
    """Materialize the old export-only velocity policy into formal notes.

    This mirrors the historical exporter order, including the layered mode's
    palette scaling.  The result is game-native note data and therefore needs
    no later hidden velocity transform.
    """

    output = list(notes)
    original_types = [int(getattr(note, "ntype", 0)) for note in output]
    # The legacy exporter temporarily treated every note as a normal note so
    # velocity policies also covered manual articulations, then restored ntype.
    output = [note._replace(ntype=0) for note in output]
    mode = str(
        getattr(settings, "velocity_mode", VELOCITY_MODE_PRESERVE)
        or VELOCITY_MODE_PRESERVE
    )
    scale = _legacy_scale(legacy_scale)
    if mode == "rescale":
        value = getattr(settings, "vel_range", None)
        if value is not None:
            output = rescale_velocity(output, value[0], value[1])
    elif mode in {"floor", "stepped"}:
        value = getattr(settings, "vel_floor", None)
        if value:
            output = floor_velocity(output, value)
    if mode == "stepped":
        value = getattr(settings, "vel_step", None)
        if value:
            if isinstance(value, tuple):
                output = stepped_velocity(output, value[0], value[1])
            else:
                output = stepped_velocity(
                    output,
                    getattr(settings, "vel_floor", None) or 99,
                    value,
                )
    if mode == "layered":
        output = layered_velocity(output, scale=scale)
        scale = 1.0
    elif not math.isclose(scale, 1.0, abs_tol=1e-12):
        output = [
            note._replace(
                vel=scaled_game_velocity(getattr(note, "vel"), scale)
            )
            for note in output
        ]
    return tuple(
        note._replace(ntype=ntype)
        for note, ntype in zip(output, original_types)
    )


def normalize_legacy_track_velocity(track: object) -> bool:
    """Mutate one editor track to the visible, game-native velocity model."""

    raw_scale = getattr(track, "volume_scale", 1.0)
    normalized = _legacy_scale(raw_scale)
    if math.isclose(normalized, 1.0, abs_tol=1e-12):
        try:
            raw_is_neutral = math.isclose(
                float(raw_scale), 1.0, abs_tol=1e-12
            )
        except (TypeError, ValueError, OverflowError):
            raw_is_neutral = False
        if not raw_is_neutral:
            setattr(track, "volume_scale", 1.0)
            return True
        return False
    setattr(
        track,
        "notes",
        list(bake_legacy_velocity_scale(getattr(track, "notes", ()), normalized)),
    )
    setattr(track, "volume_scale", 1.0)
    return True


def _game_note_key(note: object) -> tuple[object, ...]:
    return (
        int(getattr(note, "pitch")),
        int(getattr(note, "vel")),
        float(getattr(note, "start")),
        float(getattr(note, "dur")),
        int(getattr(note, "ntype")),
    )


def _bound_previous_velocity_b(
    notes: Sequence[object],
    records: Sequence[Sequence[object]],
) -> tuple[int, ...]:
    record_lookup: dict[tuple[object, ...], deque[int]] = defaultdict(deque)
    for record in records:
        if len(record) < 6:
            continue
        key = (
            int(record[0]),
            int(record[1]),
            float(record[2]),
            float(record[3]),
            int(record[4]),
        )
        velocity_b = int(record[5])
        if 0 <= velocity_b <= GAME_VELOCITY_MAX:
            record_lookup[key].append(velocity_b)
    values: list[int] = []
    for note in notes:
        candidates = record_lookup.get(_game_note_key(note))
        values.append(
            candidates.popleft()
            if candidates
            else int(getattr(note, "vel"))
        )
    return tuple(values)


def _pair_velocity_matches(
    old_notes: Sequence[object],
    new_notes: Sequence[object],
    old_velocity_b: Sequence[int],
    unmatched_old: set[int],
    unmatched_new: set[int],
    assigned: dict[int, int],
    key: Callable[[object], tuple[object, ...]],
    *,
    velocity_edited: bool = False,
    unique_only: bool = False,
) -> None:
    old_groups: dict[tuple[object, ...], list[int]] = defaultdict(list)
    new_groups: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for index in sorted(unmatched_old):
        old_groups[key(old_notes[index])].append(index)
    for index in sorted(unmatched_new):
        new_groups[key(new_notes[index])].append(index)
    for value in old_groups.keys() & new_groups.keys():
        old_indices, new_indices = old_groups[value], new_groups[value]
        if unique_only and (len(old_indices) != 1 or len(new_indices) != 1):
            continue
        for old_index, new_index in zip(old_indices, new_indices):
            assigned[new_index] = (
                int(getattr(new_notes[new_index], "vel"))
                if velocity_edited
                else old_velocity_b[old_index]
            )
            unmatched_old.discard(old_index)
            unmatched_new.discard(new_index)


def reconcile_game_velocity_records(
    previous_notes: Iterable[object],
    previous_records: Iterable[Sequence[object]],
    next_notes: Iterable[object],
) -> tuple[tuple[object, ...], ...]:
    """Keep game off-velocity attached across non-velocity note edits."""

    records = tuple(tuple(record) for record in previous_records)
    if not records:
        return ()
    old_notes, new_notes = tuple(previous_notes), tuple(next_notes)
    old_velocity_b = _bound_previous_velocity_b(old_notes, records)
    unmatched_old, unmatched_new = set(range(len(old_notes))), set(range(len(new_notes)))
    assigned: dict[int, int] = {}

    def pair(key, *, velocity_edited=False, unique_only=False) -> None:
        _pair_velocity_matches(
            old_notes, new_notes, old_velocity_b,
            unmatched_old, unmatched_new, assigned, key,
            velocity_edited=velocity_edited, unique_only=unique_only,
        )

    pair(_game_note_key)
    # Editing visible Velocity intentionally makes both game velocity bytes
    # follow the new value.
    pair(
        lambda note: (note.pitch, note.start, note.dur, note.ntype),
        velocity_edited=True,
    )
    # Preserve B for common one-field block edits.
    for key in (
        lambda note: (note.pitch, note.vel, note.start, note.dur),
        lambda note: (note.pitch, note.vel, note.start, note.ntype),
        lambda note: (note.pitch, note.vel, note.dur, note.ntype),
        lambda note: (note.vel, note.start, note.dur, note.ntype),
    ):
        pair(key)
    # A drag may change pitch and time together. Carry B only when the
    # remaining identity is unique, avoiding cross-note misbinding.
    for key in (
        lambda note: (note.vel, note.dur, note.ntype),
        lambda note: (note.pitch, note.vel, note.ntype),
        lambda note: (note.vel, note.start, note.ntype),
    ):
        pair(key, unique_only=True)
    # A single block can be edited through several inspector fields before one
    # Apply. A unique unchanged Velocity is the final conservative lineage
    # signal for that case.
    pair(lambda note: (note.vel,), unique_only=True)

    return tuple(
        (
            int(getattr(note, "pitch")),
            int(getattr(note, "vel")),
            float(getattr(note, "start")),
            float(getattr(note, "dur")),
            int(getattr(note, "ntype")),
            int(assigned.get(index, getattr(note, "vel"))),
        )
        for index, note in enumerate(new_notes)
    )


def reconcile_track_game_velocity_records(
    track: object,
    next_notes: Iterable[object],
) -> None:
    """Update one track's dual-velocity sidecar before replacing its notes."""

    setattr(track, "bdo_source_note_records", reconcile_game_velocity_records(
        getattr(track, "notes", ()),
        getattr(track, "bdo_source_note_records", ()),
        next_notes,
    ))


@dataclass(frozen=True, slots=True)
class GameInstrumentMix:
    """The mixer fields owned by one serialized BDO instrument."""

    volume: int
    reverb_send: int
    delay_send: int
    chorus_send: int

    def __post_init__(self) -> None:
        for field_name in (
            "volume",
            "reverb_send",
            "delay_send",
            "chorus_send",
        ):
            value = int(getattr(self, field_name))
            if not 0 <= value <= GAME_WIRE_BYTE_MAX:
                raise ValueError(f"{field_name} must be a v9 byte")

    @classmethod
    def from_track(cls, track: object) -> "GameInstrumentMix":
        settings = raw_track_settings(
            getattr(track, "bdo_track_settings", (0,) * 8)
        )
        return cls(
            volume=int(getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)),
            reverb_send=settings[TRACK_REVERB_SEND_INDEX],
            delay_send=settings[TRACK_DELAY_SEND_INDEX],
            chorus_send=settings[TRACK_CHORUS_SEND_INDEX],
        )

    def apply_to(
        self,
        track: object,
        *,
        volume: bool = True,
        sends: bool = True,
        send_indices: Iterable[int] | None = None,
    ) -> bool:
        selected_indices = (
            frozenset(
                {
                    TRACK_REVERB_SEND_INDEX,
                    TRACK_DELAY_SEND_INDEX,
                    TRACK_CHORUS_SEND_INDEX,
                }
                if send_indices is None
                else (int(index) for index in send_indices)
            )
            if sends
            else frozenset()
        )
        allowed_indices = {
            TRACK_REVERB_SEND_INDEX,
            TRACK_DELAY_SEND_INDEX,
            TRACK_CHORUS_SEND_INDEX,
        }
        if not selected_indices <= allowed_indices:
            raise ValueError("only game Aux send indices may be propagated")
        # Validate the complete destination before changing any field so an
        # invalid settings record cannot leave a half-updated mixer.
        settings = (
            list(raw_track_settings(
                getattr(track, "bdo_track_settings", (0,) * 8)
            ))
            if selected_indices
            else None
        )
        changed = False
        if volume and int(
            getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
        ) != self.volume:
            setattr(track, "bdo_track_volume", self.volume)
            changed = True
        if settings is not None:
            replacements = {
                TRACK_REVERB_SEND_INDEX: self.reverb_send,
                TRACK_DELAY_SEND_INDEX: self.delay_send,
                TRACK_CHORUS_SEND_INDEX: self.chorus_send,
            }
            replacements = {
                index: value
                for index, value in replacements.items()
                if index in selected_indices
            }
            if any(settings[index] != value for index, value in replacements.items()):
                for index, value in replacements.items():
                    settings[index] = value
                setattr(track, "bdo_track_settings", tuple(settings))
                changed = True
        return changed


def propagate_game_instrument_mix(
    tracks: Sequence[object],
    source: object,
    *,
    volume: bool = True,
    sends: bool = True,
    send_indices: Iterable[int] | None = None,
    serialize: Callable[[object], int] = serialized_game_instrument_id,
) -> tuple[int, ...]:
    """Apply the source mixer state to every lane of the same game instrument."""

    key = int(serialize(source))
    mix = GameInstrumentMix.from_track(source)
    # Callers may supply a one-shot iterator.  Freeze it before the first
    # destination so every lane receives the same field-level patch.
    stable_send_indices = (
        tuple(int(index) for index in send_indices)
        if sends and send_indices is not None
        else send_indices
    )
    allowed_send_indices = {
        TRACK_REVERB_SEND_INDEX,
        TRACK_DELAY_SEND_INDEX,
        TRACK_CHORUS_SEND_INDEX,
    }
    if (
        sends
        and stable_send_indices is not None
        and not set(stable_send_indices) <= allowed_send_indices
    ):
        raise ValueError("only game Aux send indices may be propagated")
    peers = [
        track
        for track in tracks
        if track is not source and int(serialize(track)) == key
    ]
    # Preflight every destination before the first mutation.
    for track in peers:
        if sends:
            raw_track_settings(getattr(track, "bdo_track_settings", (0,) * 8))
        if volume:
            int(getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME))
    changed: list[int] = []
    for track in peers:
        if mix.apply_to(
            track,
            volume=volume,
            sends=sends,
            send_indices=stable_send_indices,
        ):
            changed.append(int(getattr(track, "track_id", -1)))
    return tuple(changed)


def inherit_game_instrument_mix(
    tracks: Sequence[object],
    target: object,
    *,
    serialize: Callable[[object], int] = serialized_game_instrument_id,
) -> int | None:
    """Adopt an existing destination instrument's mixer state after remapping."""

    key = int(serialize(target))
    peers = [
        track
        for track in tracks
        if track is not target and int(serialize(track)) == key
    ]
    if not peers:
        return None
    mixes = {GameInstrumentMix.from_track(track) for track in peers}
    if len(mixes) != 1:
        raise ValueError(
            "destination game instrument has conflicting mixer states"
        )
    # Validate target settings before changing its volume.
    raw_track_settings(getattr(target, "bdo_track_settings", (0,) * 8))
    next(iter(mixes)).apply_to(target)
    return int(getattr(peers[0], "track_id", -1))


__all__ = [
    "GAME_VELOCITY_MAX",
    "GAME_VELOCITY_MIN",
    "GAME_WIRE_BYTE_MAX",
    "GameInstrumentMix",
    "bake_game_velocity_transform",
    "bake_legacy_velocity_scale",
    "decode_serialized_game_instrument_id",
    "formal_score_tracks",
    "inherit_game_instrument_mix",
    "normalize_legacy_track_velocity",
    "preview_tracks",
    "propagate_game_instrument_mix",
    "reconcile_game_velocity_records",
    "reconcile_track_game_velocity_records",
    "scaled_game_velocity",
    "serialized_game_instrument_id",
]
