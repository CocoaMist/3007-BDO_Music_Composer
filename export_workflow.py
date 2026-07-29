"""Immutable editor-export snapshots and atomic BDO score installation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from atomic_io import atomic_copy_file, atomic_write_bytes
from bdo_codec import document_matches_logical_tracks, encode_score, score_summary
from bdo_export import channel_groups_to_bdo
from bdo_midi import MARNIAN_SYNTH_INSTRUMENT_IDS, MARNIAN_SYNTH_MODE_OFFSETS


@dataclass(frozen=True, slots=True)
class ExportTrackSnapshot:
    notes: tuple[Any, ...]
    gm_program: int
    is_percussion: bool
    bdo_instrument_id: int
    marnian_synth_mode: str
    duration_scale: float
    volume_scale: float
    articulation_type: int | None
    bdo_track_volume: int
    bdo_track_settings: tuple[int, ...]
    bdo_source_group_index: int | None
    bdo_source_note_records: tuple[tuple[Any, ...], ...]


def freeze_export_tracks(tracks: Sequence[object]) -> tuple[ExportTrackSnapshot, ...]:
    """Detach an export request from all mutable editor track containers."""

    return tuple(
        ExportTrackSnapshot(
            notes=tuple(getattr(track, "notes", ())),
            gm_program=int(getattr(track, "gm_program", 0)),
            is_percussion=bool(getattr(track, "is_percussion", False)),
            bdo_instrument_id=int(getattr(track, "bdo_instrument_id", 0)),
            marnian_synth_mode=str(
                getattr(track, "marnian_synth_mode", "basic") or "basic"
            ),
            duration_scale=float(getattr(track, "duration_scale", 1.0)),
            volume_scale=float(getattr(track, "volume_scale", 1.0)),
            articulation_type=(
                int(value)
                if (value := getattr(track, "articulation_type", None)) is not None
                else None
            ),
            bdo_track_volume=int(getattr(track, "bdo_track_volume", 70)),
            bdo_track_settings=tuple(
                int(value)
                for value in getattr(track, "bdo_track_settings", (0,) * 8)
            ),
            bdo_source_group_index=(
                int(value)
                if (value := getattr(track, "bdo_source_group_index", None))
                is not None
                else None
            ),
            bdo_source_note_records=tuple(
                tuple(record)
                for record in getattr(track, "bdo_source_note_records", ())
            ),
        )
        for track in tracks
    )


def serialized_bdo_instrument_id(track: object) -> int:
    instrument_id = int(getattr(track, "bdo_instrument_id"))
    if instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
        return instrument_id
    mode = str(getattr(track, "marnian_synth_mode", "basic") or "basic")
    return instrument_id + MARNIAN_SYNTH_MODE_OFFSETS.get(mode, 0)


def install_export_to_game(out_path: Path, game_dir: Path) -> Path:
    game_dir.mkdir(parents=True, exist_ok=True)
    return atomic_copy_file(out_path, game_dir / out_path.name)


def execute_export(params: Mapping[str, Any]) -> tuple[str, int, object, str, str]:
    """Encode and publish an editor snapshot.

    The user-selected output is the primary artifact.  Installing its copy in
    the game directory is a separate best-effort phase, so a permissions or
    directory error there must not misreport an already durable export as a
    conversion failure.  The final tuple member contains that phase-specific
    error, if any.
    """

    direct_tracks = tuple(params["direct_tracks"])
    channel_groups = [
        (
            [
                note._replace(dur=max(1.0, note.dur * track.duration_scale))
                for note in track.notes
            ],
            track.gm_program,
            track.is_percussion,
        )
        for track in direct_tracks
    ]
    direct_instrument_map = {
        index: serialized_bdo_instrument_id(track)
        for index, track in enumerate(direct_tracks)
    }
    source_document = params.get("bdo_source_document")
    exact_source = bool(
        source_document is not None
        and params.get("bpm_override") is None
        and not params.get("transpose")
        and not params.get("vel_range")
        and not params.get("vel_floor")
        and not params.get("vel_step")
        and not params.get("vel_layered")
        and not params.get("articulation_map")
        and document_matches_logical_tracks(
            source_document,
            direct_tracks,
            instrument_ids=[
                direct_instrument_map[index]
                for index in range(len(direct_tracks))
            ],
            track_settings=[
                params["track_settings_map"][index]
                for index in range(len(direct_tracks))
            ],
            owner_id=params["owner_id"],
            character_name=params["char_name"],
            bpm=params["bpm_for_temp"],
            time_signature=params["time_sig_for_temp"],
        )
    )
    if exact_source:
        bdo_data = encode_score(source_document, mode="lossless")
        summary = score_summary(source_document)
    else:
        bdo_data, summary = channel_groups_to_bdo(
            params["bpm_for_temp"],
            params["time_sig_for_temp"],
            channel_groups,
            bpm_override=params["bpm_override"],
            char_name=params["char_name"],
            vel_range=params["vel_range"],
            vel_floor=params["vel_floor"],
            vel_step=params["vel_step"],
            vel_layered=params["vel_layered"],
            transpose=params["transpose"],
            owner_id=params["owner_id"],
            instrument_map=direct_instrument_map,
            reverb=params["reverb"],
            delay=params["delay"],
            chorus=params["chorus"],
            vel_scales=params["vel_scales"],
            articulation_map=params["articulation_map"],
            preserve_note_types=True,
            track_volumes=params.get("track_volumes"),
            track_settings_map=params.get("track_settings_map"),
            velocity_b_maps=params.get("velocity_b_maps"),
        )

    out_path = Path(params["out_path"])
    atomic_write_bytes(out_path, bdo_data)
    installed_path = ""
    installation_error = ""
    try:
        installed_path = str(
            install_export_to_game(out_path, Path(params["game_dir"]))
        )
    except Exception as exc:
        installation_error = f"{type(exc).__name__}: {exc}"
    return (
        str(out_path),
        len(bdo_data),
        summary,
        installed_path,
        installation_error,
    )


__all__ = [
    "ExportTrackSnapshot",
    "MARNIAN_SYNTH_INSTRUMENT_IDS",
    "MARNIAN_SYNTH_MODE_OFFSETS",
    "execute_export",
    "freeze_export_tracks",
    "install_export_to_game",
    "serialized_bdo_instrument_id",
]
