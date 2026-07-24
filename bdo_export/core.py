"""Editor/MIDI adaptation into the independent BDO v9 document codec."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
import struct
from typing import NamedTuple
import warnings

from bdo_codec import (
    BDO_VERSION,
    MAX_NOTES_PER_TRACK,
    BdoDocument,
    BdoHeader,
    BdoInstrumentGroup,
    BdoNote,
    BdoTrack,
    BdoTrackSettings,
    build_plaintext,
    encode_score,
    read_score,
)
from bdo_codec.ice import encrypt as encrypt_ice
from bdo_midi import (
    BDO_INSTRUMENT_NAMES,
    BDO_INSTRUMENTS,
    DEFAULT_INSTRUMENT,
    Note,
    clamp_notes,
    floor_velocity,
    gm_to_bdo_instrument,
    layered_velocity,
    map_drum_notes,
    normalize_drum_note_timing,
    parse_midi,
    rescale_velocity,
    stepped_velocity,
    transpose_notes,
)
from bdo_midi.transforms import bounded_int, bounded_velocity


MAX_NOTES_PER_INSTRUMENT = 10_000
DEFAULT_TRACK_VOLUME = 70
TRACK_SETTINGS = bytes(8)
BDO_BPM_MIN = 1
BDO_BPM_MAX = 200


class _EncodedNote(NamedTuple):
    pitch: int
    vel: int
    start: float
    dur: float
    ntype: int
    velocity_b: int


def split_notes(notes: Sequence, max_per_track: int = MAX_NOTES_PER_TRACK) -> list:
    if max_per_track <= 0:
        raise ValueError("max_per_track must be positive")
    return [list(notes[offset:offset + max_per_track]) for offset in range(0, len(notes), max_per_track)] or [[]]


def make_track_settings(
    reverb: int = 0,
    delay: int = 0,
    chorus: tuple[int, int, int] | None = None,
) -> bytes:
    settings = bytearray(8)
    settings[1] = bounded_int(reverb, 0, 127, "reverb")
    settings[3] = bounded_int(delay, 0, 127, "delay")
    if chorus is not None:
        feedback, depth, frequency = chorus
        settings[5] = bounded_int(feedback, 0, 127, "chorus feedback")
        settings[6] = bounded_int(depth, 0, 127, "chorus depth")
        settings[7] = bounded_int(frequency, 0, 127, "chorus frequency")
    return bytes(settings)


def _codec_note(note: object) -> BdoNote:
    velocity_a = bounded_velocity(getattr(note, "vel"))
    velocity_b = bounded_velocity(getattr(note, "velocity_b", velocity_a), "velocity_b")
    return BdoNote(
        pitch=bounded_int(getattr(note, "pitch"), 0, 127, "pitch"),
        ntype=bounded_int(getattr(note, "ntype"), 0, 255, "ntype"),
        velocity_a=velocity_a,
        velocity_b=velocity_b,
        start_ms=float(getattr(note, "start")),
        duration_ms=float(getattr(note, "dur")),
    )


def build_score_document(
    bpm: int,
    time_sig_num: int,
    instrument_groups: Sequence[tuple[int, Sequence[Sequence]]],
    char_name: str = "MIDI",
    *,
    owner_id: int = 0,
    track_settings: bytes | bytearray | Sequence[int] | None = None,
    track_volumes: Mapping[int, int] | None = None,
    track_settings_by_group: Mapping[int, bytes | bytearray | Sequence[int]] | None = None,
) -> BdoDocument:
    """Create a canonical BDO document from already split physical tracks."""
    bpm_value = bounded_int(bpm, BDO_BPM_MIN, BDO_BPM_MAX, "bpm")
    meter = bounded_int(time_sig_num, 1, 255, "time signature numerator")
    default_settings = BdoTrackSettings.from_bytes(bytes(
        TRACK_SETTINGS if track_settings is None else track_settings
    ))
    volume_map = track_volumes or {}
    settings_map = track_settings_by_group or {}
    groups: list[BdoInstrumentGroup] = []

    for group_index, (instrument_id, note_lists) in enumerate(instrument_groups):
        instrument = bounded_int(instrument_id, 0, 0xFFFF, "instrument id")
        volume = bounded_int(volume_map.get(group_index, DEFAULT_TRACK_VOLUME), 0, 255, "track volume")
        group_settings = BdoTrackSettings.from_bytes(bytes(
            settings_map.get(group_index, default_settings.values)
        ))
        tracks = [
            BdoTrack(
                instrument_id=instrument,
                volume=volume,
                settings=group_settings,
                notes=tuple(_codec_note(note) for note in physical_notes),
            )
            for physical_notes in note_lists
        ]
        if any(len(track.notes) > MAX_NOTES_PER_TRACK for track in tracks):
            raise ValueError(f"physical BDO tracks may contain at most {MAX_NOTES_PER_TRACK} notes")
        tracks.append(BdoTrack(instrument, volume, group_settings, ()))
        groups.append(BdoInstrumentGroup(tuple(tracks), source_index=group_index))

    return BdoDocument(
        version=BDO_VERSION,
        header=BdoHeader(
            owner_id=bounded_int(owner_id, 0, 0xFFFFFFFF, "owner_id"),
            reserved=b"\x00" * 4,
            character_name_1=str(char_name),
            character_name_2=str(char_name),
            bpm=bpm_value,
            time_signature=meter,
            instrument_tag="",
        ),
        groups=tuple(groups),
    )


def build_bdo_binary(
    bpm: int,
    time_sig_num: int,
    instrument_groups: Sequence[tuple[int, Sequence[Sequence]]],
    char_name: str = "MIDI",
    owner_id: int = 0,
    track_settings: bytes | bytearray | Sequence[int] | None = None,
    track_volumes: Mapping[int, int] | None = None,
    track_settings_by_group: Mapping[int, bytes | bytearray | Sequence[int]] | None = None,
) -> bytes:
    """Build the aligned plaintext payload used by BDO v9."""
    document = build_score_document(
        bpm,
        time_sig_num,
        instrument_groups,
        char_name,
        owner_id=owner_id,
        track_settings=track_settings,
        track_volumes=track_volumes,
        track_settings_by_group=track_settings_by_group,
    )
    return build_plaintext(document, mode="canonical")


def encrypt_bdo(plaintext: bytes) -> bytes:
    """Encrypt an aligned v9 payload and prepend its version record."""
    return struct.pack("<I", BDO_VERSION) + encrypt_ice(plaintext)


def extract_owner_id(bdo_path: str | Path) -> tuple[int, str]:
    document = read_score(bdo_path)
    return document.header.owner_id, document.header.character_name_1


def _velocity_b_lookup(
    records: Sequence[Sequence] | None,
) -> dict[tuple[int, int, float, float, int], list[int]]:
    lookup: dict[tuple[int, int, float, float, int], list[int]] = defaultdict(list)
    for record in records or ():
        if len(record) < 6:
            continue
        identity = (
            int(record[0]), int(record[1]), float(record[2]),
            float(record[3]), int(record[4]),
        )
        lookup[identity].append(bounded_velocity(record[5], "velocity_b"))
    return lookup


def channel_groups_to_bdo(
    bpm,
    time_sig_num,
    channel_groups,
    bpm_override=None,
    char_name="MIDI",
    vel_range=None,
    vel_floor=None,
    vel_step=None,
    vel_layered=False,
    transpose=0,
    owner_id=0,
    instrument_map=None,
    reverb=0,
    delay=0,
    chorus=None,
    vel_scales=None,
    articulation_map=None,
    preserve_note_types=False,
    track_volumes=None,
    track_settings_map=None,
    velocity_b_maps=None,
):
    """Convert logical editor groups to an encrypted canonical BDO v9 score."""
    output_bpm = bounded_int(
        bpm_override if bpm_override is not None else bpm,
        BDO_BPM_MIN,
        BDO_BPM_MAX,
        "bpm",
    )
    meter = bounded_int(time_sig_num, 1, 255, "time signature numerator")
    drum_id = BDO_INSTRUMENTS["drum_set"]
    notes_by_instrument: dict[int, list[_EncodedNote]] = defaultdict(list)
    volumes_by_instrument: dict[int, int] = {}
    settings_by_instrument: dict[int, bytes] = {}

    for channel_index, (source_notes, gm_program, is_percussion) in enumerate(channel_groups):
        automatic_id = gm_to_bdo_instrument(gm_program, is_percussion)
        if instrument_map is None:
            instrument_id = automatic_id
        else:
            instrument_id = instrument_map.get(
                channel_index,
                instrument_map.get((gm_program, is_percussion), automatic_id),
            )
        instrument_id = bounded_int(instrument_id, 0, 0xFFFF, "instrument id")
        drum_track = bool(is_percussion or instrument_id == drum_id)
        notes: list[Note] = list(source_notes)
        if drum_track:
            notes = map_drum_notes(notes)
        else:
            if transpose:
                notes = transpose_notes(notes, int(transpose))
            notes = clamp_notes(notes)

        original_types = [note.ntype for note in notes] if preserve_note_types else None
        if original_types is not None:
            notes = [note._replace(ntype=0) for note in notes]
        if vel_range is not None:
            if len(vel_range) != 2:
                raise ValueError("vel_range requires two values")
            notes = rescale_velocity(notes, vel_range[0], vel_range[1])
        if vel_floor:
            notes = floor_velocity(notes, vel_floor)
        if vel_step:
            notes = stepped_velocity(notes, vel_step[0], vel_step[1])
        if vel_layered:
            notes = layered_velocity(
                notes,
                scale=vel_scales.get(channel_index, 1.0) if vel_scales else 1.0,
            )
        elif vel_scales and channel_index in vel_scales:
            scale = float(vel_scales[channel_index])
            notes = [
                note._replace(vel=bounded_velocity(round(note.vel * scale)))
                for note in notes
            ]

        if not drum_track and articulation_map and channel_index in articulation_map:
            note_type = bounded_int(articulation_map[channel_index], 0, 255, "articulation")
            notes = [note._replace(ntype=note_type) for note in notes]
        elif original_types is not None:
            notes = [
                note._replace(ntype=note_type)
                for note, note_type in zip(notes, original_types)
            ]

        if track_volumes and channel_index in track_volumes:
            volume = bounded_int(track_volumes[channel_index], 0, 255, "track volume")
            if instrument_id in volumes_by_instrument and volumes_by_instrument[instrument_id] != volume:
                raise ValueError(
                    f"instrument 0x{instrument_id:02x} cannot merge tracks "
                    "with different game volumes"
                )
            volumes_by_instrument[instrument_id] = volume
        if track_settings_map and channel_index in track_settings_map:
            settings = bytes(track_settings_map[channel_index])
            if len(settings) != 8:
                raise ValueError("track settings must contain exactly 8 bytes")
            if instrument_id in settings_by_instrument and settings_by_instrument[instrument_id] != settings:
                raise ValueError(
                    f"instrument 0x{instrument_id:02x} cannot merge tracks "
                    "with different settings"
                )
            settings_by_instrument[instrument_id] = settings

        second_velocities = _velocity_b_lookup(
            velocity_b_maps.get(channel_index) if velocity_b_maps else None
        )
        for note in notes:
            identity = (note.pitch, note.vel, float(note.start), float(note.dur), note.ntype)
            candidates = second_velocities.get(identity)
            velocity_b = candidates.pop(0) if candidates else note.vel
            notes_by_instrument[instrument_id].append(_EncodedNote(
                note.pitch, note.vel, note.start, note.dur, note.ntype, velocity_b
            ))

    if drum_id in notes_by_instrument:
        notes_by_instrument[drum_id] = normalize_drum_note_timing(notes_by_instrument[drum_id])

    notes_dropped = 0
    for instrument_id, instrument_notes in notes_by_instrument.items():
        instrument_notes.sort(key=lambda note: note.start)
        if len(instrument_notes) <= MAX_NOTES_PER_INSTRUMENT:
            continue
        dropped = len(instrument_notes) - MAX_NOTES_PER_INSTRUMENT
        del instrument_notes[MAX_NOTES_PER_INSTRUMENT:]
        notes_dropped += dropped
        name = BDO_INSTRUMENT_NAMES.get(instrument_id, f"0x{instrument_id:02x}")
        warnings.warn(
            f"{name}: {dropped} notes dropped (10k per-instrument limit)",
            stacklevel=2,
        )

    instrument_groups: list[tuple[int, list[list[_EncodedNote]]]] = [
        (instrument_id, split_notes(notes))
        for instrument_id, notes in notes_by_instrument.items()
    ]
    if not instrument_groups:
        instrument_groups = [(DEFAULT_INSTRUMENT, [[]])]

    group_volumes: dict[int, int] = {}
    group_settings: dict[int, bytes] = {}
    track_details: list[dict] = []
    total_notes = 0
    total_tracks = 0
    for group_index, (instrument_id, physical_tracks) in enumerate(instrument_groups):
        if instrument_id in volumes_by_instrument:
            group_volumes[group_index] = volumes_by_instrument[instrument_id]
        if instrument_id in settings_by_instrument:
            group_settings[group_index] = settings_by_instrument[instrument_id]
        instrument_name = BDO_INSTRUMENT_NAMES.get(instrument_id, f"0x{instrument_id:02x}")
        for track_notes in physical_tracks:
            total_tracks += 1
            total_notes += len(track_notes)
            track_details.append({
                "notes": len(track_notes),
                "pitch_min": min((note.pitch for note in track_notes), default=0),
                "pitch_max": max((note.pitch for note in track_notes), default=0),
                "duration_ms": max((note.start + note.dur for note in track_notes), default=0),
                "instrument": instrument_name,
            })
        total_tracks += 1

    document = build_score_document(
        output_bpm,
        meter,
        instrument_groups,
        char_name,
        owner_id=owner_id,
        track_settings=make_track_settings(reverb, delay, chorus),
        track_volumes=group_volumes,
        track_settings_by_group=group_settings,
    )
    summary = {
        "bpm": output_bpm,
        "time_sig": meter,
        "tracks": total_tracks,
        "total_notes": total_notes,
        "instruments": len(instrument_groups),
        "track_details": track_details,
        "notes_dropped": notes_dropped,
    }
    return encode_score(document, mode="canonical"), summary


def midi_to_bdo(
    midi_path,
    bpm_override=None,
    char_name="MIDI",
    vel_range=None,
    vel_floor=None,
    vel_step=None,
    vel_layered=False,
    transpose=0,
    apply_sustain=True,
    flatten_tempo=False,
    owner_id=0,
    instrument_map=None,
    reverb=0,
    delay=0,
    chorus=None,
    vel_scales=None,
    articulation_map=None,
):
    bpm, meter, groups, _tempo_count = parse_midi(
        midi_path,
        apply_sustain=apply_sustain,
        flatten_tempo=flatten_tempo,
    )
    return channel_groups_to_bdo(
        bpm,
        meter,
        groups,
        bpm_override=bpm_override,
        char_name=char_name,
        vel_range=vel_range,
        vel_floor=vel_floor,
        vel_step=vel_step,
        vel_layered=vel_layered,
        transpose=transpose,
        owner_id=owner_id,
        instrument_map=instrument_map,
        reverb=reverb,
        delay=delay,
        chorus=chorus,
        vel_scales=vel_scales,
        articulation_map=articulation_map,
    )


__all__ = [
    "BDO_BPM_MAX", "BDO_BPM_MIN", "DEFAULT_TRACK_VOLUME",
    "MAX_NOTES_PER_INSTRUMENT", "TRACK_SETTINGS", "build_bdo_binary",
    "build_score_document", "channel_groups_to_bdo", "encrypt_bdo",
    "extract_owner_id", "make_track_settings", "midi_to_bdo", "split_notes",
]
