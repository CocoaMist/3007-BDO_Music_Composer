"""Immutable editor-export requests, pure preparation, and atomic publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from atomic_io import atomic_copy_file, atomic_write_bytes
from bdo_codec import document_matches_logical_tracks, encode_score, score_summary
from bdo_export import channel_groups_to_bdo
from bdo_midi import MARNIAN_SYNTH_INSTRUMENT_IDS, MARNIAN_SYNTH_MODE_OFFSETS
from conversion_settings import ConversionSettings
from pitch_transform import (
    PitchTransformPlan,
    track_uses_percussion_pitch_semantics,
    transpose_notes,
)


@dataclass(frozen=True, slots=True)
class ExportTrackSnapshot:
    track_id: int
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
            track_id=int(getattr(track, "track_id", index)),
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
        for index, track in enumerate(tracks)
    )


_T = TypeVar("_T")


def _freeze_index_map(
    value: object,
    convert: Callable[[object], _T],
) -> tuple[tuple[int, _T], ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(
        sorted(
            (int(index), convert(item))
            for index, item in value.items()
        )
    )


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """Complete typed input for a deterministic export preparation pass."""

    direct_tracks: tuple[ExportTrackSnapshot, ...]
    bpm: int
    time_signature: int
    out_path: Path
    character_name: str
    owner_id: int
    conversion: ConversionSettings
    pitch_plan: PitchTransformPlan
    reverb: int
    delay: int
    chorus: tuple[int, int, int] | None
    game_dir: Path
    source_path: str = ""
    velocity_scales: tuple[tuple[int, float], ...] = ()
    articulation_map: tuple[tuple[int, int], ...] = ()
    track_volumes: tuple[tuple[int, int], ...] = ()
    track_settings: tuple[tuple[int, tuple[int, ...]], ...] = ()
    velocity_b_maps: tuple[
        tuple[int, tuple[tuple[Any, ...], ...]], ...
    ] = ()
    source_document: object | None = None

    def __post_init__(self) -> None:
        if self.pitch_plan.global_semitones != self.conversion.transpose:
            raise ValueError(
                "pitch plan global transpose must match conversion settings"
            )

    def legacy_parameters(self) -> dict[str, Any]:
        """Project the typed request for read-only legacy integrations."""

        return {
            "midi_path": self.source_path,
            "direct_tracks": self.direct_tracks,
            "bpm_for_temp": self.bpm,
            "time_sig_for_temp": self.time_signature,
            "out_path": str(self.out_path),
            "char_name": self.character_name,
            "owner_id": self.owner_id,
            "conversion_settings": self.conversion,
            "pitch_transform_plan": self.pitch_plan,
            "reverb": self.reverb,
            "delay": self.delay,
            "chorus": self.chorus,
            "vel_scales": dict(self.velocity_scales) or None,
            "articulation_map": dict(self.articulation_map) or None,
            "track_volumes": dict(self.track_volumes),
            "track_settings_map": dict(self.track_settings),
            "velocity_b_maps": dict(self.velocity_b_maps) or None,
            "bdo_source_document": self.source_document,
            "game_dir": str(self.game_dir),
        }

    def __getitem__(self, key: str) -> Any:
        return self.legacy_parameters()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.legacy_parameters().get(key, default)

    @classmethod
    def from_parameters(
        cls,
        params: Mapping[str, Any],
    ) -> "ExportRequest":
        """Normalize the pre-v10 mapping boundary for plugins and old callers."""

        conversion = ConversionSettings.from_export_parameters(params)
        raw_plan = params.get("pitch_transform_plan")
        if isinstance(raw_plan, PitchTransformPlan):
            pitch_plan = raw_plan.with_global(conversion.transpose)
        else:
            pitch_plan = PitchTransformPlan.from_payload(
                params.get("pitch_transform"),
                default_global_semitones=conversion.transpose,
            ).with_global(conversion.transpose)
        raw_chorus = params.get("chorus")
        chorus = (
            tuple(int(value) for value in raw_chorus)
            if isinstance(raw_chorus, (list, tuple)) and len(raw_chorus) == 3
            else None
        )
        return cls(
            direct_tracks=tuple(params["direct_tracks"]),
            bpm=int(params["bpm_for_temp"]),
            time_signature=int(params["time_sig_for_temp"]),
            out_path=Path(params["out_path"]),
            character_name=str(params["char_name"]),
            owner_id=int(params["owner_id"]),
            conversion=conversion,
            pitch_plan=pitch_plan,
            reverb=int(params.get("reverb", 0)),
            delay=int(params.get("delay", 0)),
            chorus=chorus,
            game_dir=Path(params["game_dir"]),
            source_path=str(params.get("midi_path") or ""),
            velocity_scales=_freeze_index_map(
                params.get("vel_scales"), float
            ),
            articulation_map=_freeze_index_map(
                params.get("articulation_map"), int
            ),
            track_volumes=_freeze_index_map(
                params.get("track_volumes"), int
            ),
            track_settings=_freeze_index_map(
                params.get("track_settings_map"),
                lambda values: tuple(int(value) for value in values),
            ),
            velocity_b_maps=_freeze_index_map(
                params.get("velocity_b_maps"),
                lambda records: tuple(tuple(record) for record in records),
            ),
            source_document=params.get("bdo_source_document"),
        )


@dataclass(frozen=True, slots=True)
class PreparedExport:
    """Pure export result awaiting durable publication."""

    out_path: Path
    game_dir: Path
    data: bytes
    summary: object


def serialized_bdo_instrument_id(track: object) -> int:
    instrument_id = int(getattr(track, "bdo_instrument_id"))
    if instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
        return instrument_id
    mode = str(getattr(track, "marnian_synth_mode", "basic") or "basic")
    return instrument_id + MARNIAN_SYNTH_MODE_OFFSETS.get(mode, 0)


def prepare_export(request: ExportRequest) -> PreparedExport:
    """Build bytes without touching the filesystem."""

    direct_tracks = request.direct_tracks
    channel_groups = []
    for track in direct_tracks:
        percussion_pitch_semantics = track_uses_percussion_pitch_semantics(
            track
        )
        effective_transpose = request.pitch_plan.effective_track_semitones(
            track
        )
        projected_notes = transpose_notes(track.notes, effective_transpose)
        channel_groups.append(
            (
                [
                    note._replace(
                        dur=max(1.0, note.dur * track.duration_scale)
                    )
                    for note in projected_notes
                ],
                track.gm_program,
                percussion_pitch_semantics,
            )
        )
    direct_instrument_map = {
        index: serialized_bdo_instrument_id(track)
        for index, track in enumerate(direct_tracks)
    }
    transform = request.conversion.export_transform_parameters()
    articulation_map = dict(request.articulation_map)
    track_settings_map = dict(request.track_settings)
    source_document = request.source_document
    exact_source = bool(
        source_document is not None
        and request.conversion.is_neutral_export_transform()
        and request.pitch_plan.is_neutral(direct_tracks)
        and not articulation_map
        and document_matches_logical_tracks(
            source_document,
            direct_tracks,
            instrument_ids=[
                direct_instrument_map[index]
                for index in range(len(direct_tracks))
            ],
            track_settings=[
                track_settings_map[index]
                for index in range(len(direct_tracks))
            ],
            owner_id=request.owner_id,
            character_name=request.character_name,
            bpm=request.bpm,
            time_signature=request.time_signature,
        )
    )
    if exact_source:
        bdo_data = encode_score(source_document, mode="lossless")
        summary = score_summary(source_document)
    else:
        bdo_data, summary = channel_groups_to_bdo(
            request.bpm,
            request.time_signature,
            channel_groups,
            bpm_override=transform["bpm_override"],
            char_name=request.character_name,
            vel_range=transform["vel_range"],
            vel_floor=transform["vel_floor"],
            vel_step=transform["vel_step"],
            vel_layered=transform["vel_layered"],
            # Every track, including the global fallback, was projected once
            # above.  Passing the legacy scalar again would double-transpose.
            transpose=0,
            owner_id=request.owner_id,
            instrument_map=direct_instrument_map,
            reverb=request.reverb,
            delay=request.delay,
            chorus=request.chorus,
            vel_scales=dict(request.velocity_scales) or None,
            articulation_map=articulation_map or None,
            preserve_note_types=True,
            track_volumes=dict(request.track_volumes) or None,
            track_settings_map=track_settings_map or None,
            velocity_b_maps=dict(request.velocity_b_maps) or None,
        )
    return PreparedExport(
        request.out_path,
        request.game_dir,
        bdo_data,
        summary,
    )


def install_export_to_game(out_path: Path, game_dir: Path) -> Path:
    game_dir.mkdir(parents=True, exist_ok=True)
    return atomic_copy_file(out_path, game_dir / out_path.name)


def publish_export(
    prepared: PreparedExport,
) -> tuple[str, int, object, str, str]:
    """Atomically publish the primary artifact, then best-effort install it."""

    atomic_write_bytes(prepared.out_path, prepared.data)
    installed_path = ""
    installation_error = ""
    try:
        installed_path = str(
            install_export_to_game(prepared.out_path, prepared.game_dir)
        )
    except Exception as exc:
        installation_error = f"{type(exc).__name__}: {exc}"
    return (
        str(prepared.out_path),
        len(prepared.data),
        prepared.summary,
        installed_path,
        installation_error,
    )


def execute_export(
    params: ExportRequest | Mapping[str, Any],
) -> tuple[str, int, object, str, str]:
    """Prepare and publish a typed request or a compatible legacy mapping."""

    request = (
        params
        if isinstance(params, ExportRequest)
        else ExportRequest.from_parameters(params)
    )
    return publish_export(prepare_export(request))


__all__ = [
    "ExportRequest",
    "ExportTrackSnapshot",
    "MARNIAN_SYNTH_INSTRUMENT_IDS",
    "MARNIAN_SYNTH_MODE_OFFSETS",
    "PreparedExport",
    "execute_export",
    "freeze_export_tracks",
    "install_export_to_game",
    "prepare_export",
    "publish_export",
    "serialized_bdo_instrument_id",
]
