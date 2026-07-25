"""Adapters between the lossless score document and editor-style logical tracks."""

from __future__ import annotations

import math
from typing import Callable, Sequence

from .model import BdoDocument


def document_matches_logical_tracks(
    document: BdoDocument,
    tracks: Sequence[object],
    *,
    instrument_ids: Sequence[int],
    track_settings: Sequence[Sequence[int]],
    owner_id: int,
    character_name: str,
    bpm: int,
    time_signature: int,
) -> bool:
    """Return whether an editor projection is still the untouched source document."""
    if (
        document.header.owner_id != int(owner_id)
        or document.header.character_name_1 != str(character_name)
        or document.header.character_name_2 != str(character_name)
        or document.header.bpm != int(bpm)
        or document.header.time_signature != int(time_signature)
        or len(tracks) != len(document.groups)
        or len(instrument_ids) != len(tracks)
        or len(track_settings) != len(tracks)
    ):
        return False
    seen_groups: set[int] = set()
    for index, track in enumerate(tracks):
        source_group = getattr(track, "bdo_source_group_index", None)
        if source_group is None or not 0 <= int(source_group) < len(document.groups):
            return False
        source_group = int(source_group)
        if source_group in seen_groups:
            return False
        seen_groups.add(source_group)
        group = document.groups[source_group]
        if not group.tracks:
            return False
        if any(item.instrument_id != int(instrument_ids[index]) for item in group.tracks):
            return False
        if any(item.volume != int(getattr(track, "bdo_track_volume", 70)) for item in group.tracks):
            return False
        expected_settings = tuple(int(value) for value in track_settings[index])
        if any(item.settings.values != expected_settings for item in group.tracks):
            return False
        if not math.isclose(float(getattr(track, "duration_scale", 1.0)), 1.0):
            return False
        if not math.isclose(float(getattr(track, "volume_scale", 1.0)), 1.0):
            return False
        source_notes = sorted(
            (note for physical in group.tracks for note in physical.notes),
            key=lambda note: (note.start_ms, note.pitch, note.duration_ms),
        )
        editor_notes = list(getattr(track, "notes", ()))
        if len(source_notes) != len(editor_notes):
            return False
        for source, editor in zip(source_notes, editor_notes):
            if (
                source.pitch != int(editor.pitch)
                or source.velocity_a != int(editor.vel)
                or source.start_ms != float(editor.start)
                or source.duration_ms != float(editor.dur)
                or source.ntype != int(editor.ntype)
            ):
                return False
    return seen_groups == set(range(len(document.groups)))


def score_summary(document: BdoDocument) -> dict:
    data_tracks = [
        track for group in document.groups for track in group.tracks if track.notes
    ]
    return {
        "bpm": document.header.bpm,
        "time_sig": document.header.time_signature,
        "tracks": sum(len(group.tracks) for group in document.groups),
        "total_notes": document.total_notes,
        "instruments": len(document.groups),
        "track_details": [{
            "notes": len(track.notes),
            "pitch_min": min(note.pitch for note in track.notes),
            "pitch_max": max(note.pitch for note in track.notes),
            "duration_ms": max(note.start_ms + note.duration_ms for note in track.notes),
            "instrument": f"0x{track.instrument_id:02x}",
        } for track in data_tracks],
        "notes_dropped": 0,
    }


__all__ = ["document_matches_logical_tracks", "score_summary"]
