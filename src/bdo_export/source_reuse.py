"""Game-export inspection and lossless source-reuse decisions.

The wire codec owns only ``BdoDocument`` encoding and validation.  Comparing
that document with an editor/export projection belongs here, at the adapter
layer that understands both shapes.
"""

from __future__ import annotations

from collections import Counter
from typing import Protocol, Sequence

from bdo_codec import BdoDocument
from bdo_midi import BDO_INSTRUMENT_NAMES, BDO_INSTRUMENTS
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME


class SourceProjectionTrack(Protocol):
    """Minimal frozen-track surface required for lossless source reuse."""

    notes: Sequence[object]
    bdo_source_group_index: int | None
    bdo_track_volume: int
    duration_scale: float
    volume_scale: float


def _source_note_identity(note: object) -> tuple[int, int, float, float, int]:
    return (
        int(getattr(note, "pitch")),
        int(getattr(note, "velocity_a")),
        float(getattr(note, "start_ms")),
        float(getattr(note, "duration_ms")),
        int(getattr(note, "ntype")),
    )


def _editor_note_identity(note: object) -> tuple[int, int, float, float, int]:
    return (
        int(getattr(note, "pitch")),
        int(getattr(note, "vel")),
        float(getattr(note, "start")),
        float(getattr(note, "dur")),
        int(getattr(note, "ntype")),
    )


def _source_velocity_identity(
    note: object,
) -> tuple[int, int, float, float, int, int]:
    return (*_source_note_identity(note), int(getattr(note, "velocity_b")))


def _record_velocity_identity(
    record: Sequence[object],
) -> tuple[int, int, float, float, int, int]:
    if len(record) < 6:
        raise ValueError("velocity B record requires six fields")
    return (
        int(record[0]),
        int(record[1]),
        float(record[2]),
        float(record[3]),
        int(record[4]),
        int(record[5]),
    )


def _source_group_matches_track(
    group: object,
    track: SourceProjectionTrack,
    *,
    instrument_id: int,
    track_settings: Sequence[int],
    track_volume: int,
    velocity_b_records: Sequence[Sequence[object]] | None,
    percussion_semantics: bool | None,
) -> bool:
    physical_tracks = tuple(getattr(group, "tracks", ()))
    if not physical_tracks or any(
        item.instrument_id != int(instrument_id)
        for item in physical_tracks
    ):
        return False
    if percussion_semantics is not None and (
        percussion_semantics
        != (int(instrument_id) == BDO_INSTRUMENTS["drum_set"])
    ):
        return False
    expected_settings = tuple(int(value) for value in track_settings)
    if any(item.volume != int(track_volume) for item in physical_tracks):
        return False
    if any(
        item.settings.values != expected_settings
        for item in physical_tracks
    ):
        return False
    if float(track.duration_scale) != 1.0:
        return False
    if float(track.volume_scale) != 1.0:
        return False
    source_notes = [
        note for physical in physical_tracks for note in physical.notes
    ]
    try:
        if Counter(map(_source_note_identity, source_notes)) != Counter(
            map(_editor_note_identity, track.notes)
        ):
            return False
        if velocity_b_records is not None and Counter(
            map(_source_velocity_identity, source_notes)
        ) != Counter(map(_record_velocity_identity, velocity_b_records)):
            return False
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return True


def document_matches_logical_tracks(
    document: BdoDocument,
    tracks: Sequence[SourceProjectionTrack],
    *,
    instrument_ids: Sequence[int],
    track_settings: Sequence[Sequence[int]],
    owner_id: int,
    character_name: str,
    bpm: int,
    time_signature: int,
    track_volumes: Sequence[int] | None = None,
    velocity_b_records: Sequence[
        Sequence[Sequence[object]] | None
    ] | None = None,
    percussion_semantics: Sequence[bool] | None = None,
) -> bool:
    """Return whether an export projection is still the untouched source."""

    if (
        document.header.owner_id != int(owner_id)
        or document.header.character_name_1 != str(character_name)
        or document.header.character_name_2 != str(character_name)
        or document.header.bpm != int(bpm)
        or document.header.time_signature != int(time_signature)
        or len(tracks) != len(document.groups)
        or len(instrument_ids) != len(tracks)
        or len(track_settings) != len(tracks)
        or (track_volumes is not None and len(track_volumes) != len(tracks))
        or (
            velocity_b_records is not None
            and len(velocity_b_records) != len(tracks)
        )
        or (
            percussion_semantics is not None
            and len(percussion_semantics) != len(tracks)
        )
    ):
        return False
    seen_groups: set[int] = set()
    for index, track in enumerate(tracks):
        source_group = track.bdo_source_group_index
        if source_group is None or not 0 <= int(source_group) < len(document.groups):
            return False
        source_group = int(source_group)
        if source_group in seen_groups:
            return False
        seen_groups.add(source_group)
        group = document.groups[source_group]
        expected_volume = (
            int(track_volumes[index])
            if track_volumes is not None
            else int(getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME))
        )
        records = (
                velocity_b_records[index]
                if velocity_b_records is not None else None
        )
        percussion = (
            bool(percussion_semantics[index])
            if percussion_semantics is not None else None
        )
        if not _source_group_matches_track(
            group,
            track,
            instrument_id=int(instrument_ids[index]),
            track_settings=track_settings[index],
            track_volume=expected_volume,
            velocity_b_records=records,
            percussion_semantics=percussion,
        ):
            return False
    return seen_groups == set(range(len(document.groups)))


def score_summary(document: BdoDocument) -> dict[str, object]:
    """Build one summary from the final document for every export path."""

    data_tracks = [
        track
        for group in document.groups
        for track in group.tracks
        if track.notes
    ]
    return {
        "bpm": document.header.bpm,
        "time_sig": document.header.time_signature,
        "tracks": sum(len(group.tracks) for group in document.groups),
        "total_notes": document.total_notes,
        "instruments": len(document.groups),
        "track_details": [
            {
                "notes": len(track.notes),
                "pitch_min": min(note.pitch for note in track.notes),
                "pitch_max": max(note.pitch for note in track.notes),
                "duration_ms": max(
                    note.start_ms + note.duration_ms
                    for note in track.notes
                ),
                "instrument": BDO_INSTRUMENT_NAMES.get(
                    track.instrument_id,
                    f"0x{track.instrument_id:02x}",
                ),
            }
            for track in data_tracks
        ],
        "notes_dropped": 0,
    }


__all__ = [
    "SourceProjectionTrack",
    "document_matches_logical_tracks",
    "score_summary",
]
