"""Immutable editor-export requests, pure preparation, and atomic publication."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from bdo_common.atomic_io import atomic_copy_file, atomic_write_bytes
from bdo_codec import UnsafeOpaqueDataError, encode_score
from bdo_export import (
    bind_dual_velocities,
    channel_groups_to_bdo,
    document_matches_logical_tracks,
    make_track_settings,
    score_summary,
)
from bdo_midi import MARNIAN_SYNTH_INSTRUMENT_IDS, MARNIAN_SYNTH_MODE_OFFSETS
from bdo_common.bdo_track_effects import (
    DEFAULT_TRACK_VOLUME,
    MasterEffects,
    encode_track_effects,
)
from bdo_music_composer.core.conversion_settings import (
    MATERIALIZED_VELOCITY_MODES,
    ConversionSettings,
)
from bdo_music_composer.editor.game_score_model import (
    formal_score_tracks,
    serialized_game_instrument_id,
)
from bdo_music_composer.export.export_verification import (
    ExportExpectation,
    ExportVerificationError,
    ExportVerificationReport,
    build_export_expectation,
    verify_export_bytes,
    verify_published_export,
)
from bdo_music_composer.editor.pitch_transform import (
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
    """Detach game-native export tracks from mutable editor containers.

    ``volume_scale`` predates the verified game mixer model.  It must be
    materialized together with the complete velocity policy before this
    boundary; partially applying it here would change transform order.
    """

    snapshots: list[ExportTrackSnapshot] = []
    for index, track in enumerate(tracks):
        if isinstance(track, Mapping) or not hasattr(track, "notes"):
            raise TypeError(
                "export tracks must be editor track objects, not mappings"
            )
        legacy_scale = float(getattr(track, "volume_scale", 1.0))
        if not math.isclose(legacy_scale, 1.0, abs_tol=1e-12):
            raise ValueError(
                "legacy volume_scale must be baked into note velocities "
                "before freezing an export"
            )
        snapshots.append(ExportTrackSnapshot(
            track_id=int(getattr(track, "track_id", index)),
            notes=tuple(getattr(track, "notes", ())),
            gm_program=int(getattr(track, "gm_program", 0)),
            is_percussion=bool(getattr(track, "is_percussion", False)),
            bdo_instrument_id=int(getattr(track, "bdo_instrument_id", 0)),
            marnian_synth_mode=str(
                getattr(track, "marnian_synth_mode", "basic") or "basic"
            ),
            duration_scale=float(getattr(track, "duration_scale", 1.0)),
            # Retained on the compatibility snapshot shape.  Formal exports
            # always carry the already-baked neutral value.
            volume_scale=1.0,
            articulation_type=(
                int(value)
                if (value := getattr(track, "articulation_type", None)) is not None
                else None
            ),
            bdo_track_volume=int(
                getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
            ),
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
        ))
    return tuple(snapshots)


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
        if not isinstance(self.direct_tracks, tuple) or any(
            not isinstance(track, ExportTrackSnapshot)
            for track in self.direct_tracks
        ):
            raise TypeError(
                "direct_tracks must be an immutable snapshot from "
                "freeze_export_tracks"
            )
        if any(
            not math.isclose(
                float(track.volume_scale),
                1.0,
                abs_tol=1e-12,
            )
            for track in self.direct_tracks
        ):
            raise ValueError(
                "legacy volume_scale must be baked into note velocities "
                "before creating an export request"
            )
        if self.pitch_plan.global_semitones != self.conversion.transpose:
            raise ValueError(
                "pitch plan global transpose must match conversion settings"
            )
        if self.velocity_scales:
            raise ValueError(
                "velocity_scales are not game fields; materialize them into "
                "note velocities before creating an export request"
            )
        if self.conversion.velocity_mode not in MATERIALIZED_VELOCITY_MODES:
            raise ValueError(
                "velocity policy must be materialized into note velocities "
                "before creating an export request"
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
            "vel_scales": None,
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
        direct_tracks = freeze_export_tracks(tuple(params["direct_tracks"]))
        return cls(
            direct_tracks=direct_tracks,
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
class ExportRequestSpec:
    """Validated UI-independent values needed to freeze one export request."""

    bpm: int
    time_signature: int
    out_path: Path
    character_name: str
    owner_id: int
    conversion: ConversionSettings
    pitch_plan: PitchTransformPlan
    master_effects: MasterEffects
    game_dir: Path
    source_path: str = ""
    source_document: object | None = None


def build_export_request(
    tracks: Sequence[object],
    spec: ExportRequestSpec,
) -> ExportRequest:
    """Freeze the formal score and derive all compatibility projections.

    Track Aux bytes remain lossless while the one score-wide Master layer is
    projected into every track setting. Malformed source settings fail closed
    instead of being replaced with zeros.
    """

    direct_tracks = freeze_export_tracks(formal_score_tracks(tracks))
    if not direct_tracks:
        raise ValueError("an export request requires at least one formal track")

    track_settings = tuple(
        (
            index,
            encode_track_effects(
                track.bdo_track_settings,
                master=spec.master_effects,
                master_authored=False,
            ),
        )
        for index, track in enumerate(direct_tracks)
    )
    reverb, delay, chorus = spec.master_effects.legacy_values()
    return ExportRequest(
        direct_tracks=direct_tracks,
        bpm=int(spec.bpm),
        time_signature=int(spec.time_signature),
        out_path=Path(spec.out_path),
        character_name=str(spec.character_name),
        owner_id=int(spec.owner_id),
        conversion=spec.conversion,
        pitch_plan=spec.pitch_plan.with_global(spec.conversion.transpose),
        reverb=reverb,
        delay=delay,
        chorus=chorus,
        game_dir=Path(spec.game_dir),
        source_path=str(spec.source_path),
        articulation_map=tuple(
            (index, int(track.articulation_type))
            for index, track in enumerate(direct_tracks)
            if track.articulation_type is not None
        ),
        track_volumes=tuple(
            (index, int(track.bdo_track_volume))
            for index, track in enumerate(direct_tracks)
        ),
        track_settings=track_settings,
        velocity_b_maps=tuple(
            (index, tuple(track.bdo_source_note_records))
            for index, track in enumerate(direct_tracks)
            if track.bdo_source_note_records
        ),
        source_document=spec.source_document,
    )


@dataclass(frozen=True, slots=True)
class PreparedExport:
    """Pure export result awaiting durable publication."""

    out_path: Path
    game_dir: Path
    data: bytes
    summary: object


def serialized_bdo_instrument_id(track: object) -> int:
    """Compatibility alias for the game-model serialization boundary."""

    return serialized_game_instrument_id(track)


def _effective_velocity_b_map(
    request: ExportRequest,
) -> dict[int, tuple[tuple[Any, ...], ...]]:
    requested_velocity_b = dict(request.velocity_b_maps)
    return {
        index: requested_velocity_b.get(
            index,
            tuple(track.bdo_source_note_records),
        )
        for index, track in enumerate(request.direct_tracks)
        if index in requested_velocity_b or track.bdo_source_note_records
    }


def _effective_track_volume_map(request: ExportRequest) -> dict[int, int]:
    requested = dict(request.track_volumes)
    return {
        index: int(requested.get(index, track.bdo_track_volume))
        for index, track in enumerate(request.direct_tracks)
    }


def _project_channel_groups(
    request: ExportRequest,
    velocity_b_map: Mapping[int, Sequence[Sequence[object]]],
) -> list[tuple[list[object], int, bool]]:
    groups: list[tuple[list[object], int, bool]] = []
    for track_index, track in enumerate(request.direct_tracks):
        percussion_pitch_semantics = track_uses_percussion_pitch_semantics(
            track
        )
        effective_transpose = request.pitch_plan.effective_track_semitones(
            track
        )
        bound_notes = bind_dual_velocities(
            track.notes,
            velocity_b_map.get(track_index),
        )
        projected_notes = transpose_notes(bound_notes, effective_transpose)
        groups.append(
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
    return groups


def _request_matches_source_document(
    request: ExportRequest,
    instrument_map: Mapping[int, int],
    settings_map: Mapping[int, Sequence[int]],
    volume_map: Mapping[int, int],
    velocity_b_map: Mapping[int, Sequence[Sequence[object]]],
) -> bool:
    source_document = request.source_document
    tracks = request.direct_tracks
    if (
        source_document is None
        or not request.conversion.is_neutral_export_transform()
        or not request.pitch_plan.is_neutral(tracks)
        or request.articulation_map
    ):
        return False
    default_settings = tuple(make_track_settings(
        request.reverb,
        request.delay,
        request.chorus,
    ))
    return document_matches_logical_tracks(
        source_document,
        tracks,
        instrument_ids=[instrument_map[index] for index in range(len(tracks))],
        track_settings=[
            settings_map.get(index, default_settings)
            for index in range(len(tracks))
        ],
        owner_id=request.owner_id,
        character_name=request.character_name,
        bpm=request.bpm,
        time_signature=request.time_signature,
        track_volumes=[volume_map[index] for index in range(len(tracks))],
        velocity_b_records=[
            velocity_b_map.get(index) for index in range(len(tracks))
        ],
        percussion_semantics=[
            track_uses_percussion_pitch_semantics(track) for track in tracks
        ],
    )


def _reject_unsafe_opaque_source_rebuild(source_document: object) -> None:
    """Fail closed before an editor rebuild could discard unknown wire data."""

    for group_index, group in enumerate(getattr(source_document, "groups", ())):
        for track_index, track in enumerate(getattr(group, "tracks", ())):
            extra_data = bytes(getattr(track, "extra_data", b""))
            if any(extra_data):
                raise UnsafeOpaqueDataError(
                    f"groups[{group_index}].tracks[{track_index}].extra_data",
                    int(getattr(track, "source_offset", 0) or 0),
                    "editor rebuild would discard unknown track data",
                )
    trailing_data = bytes(getattr(source_document, "trailing_data", b""))
    if any(trailing_data):
        raise UnsafeOpaqueDataError(
            "trailing_data",
            int(getattr(source_document, "_trailing_offset", 0) or 0),
            "editor rebuild would discard unknown trailing data",
        )


def prepare_export(request: ExportRequest) -> PreparedExport:
    """Build bytes without touching the filesystem."""

    direct_tracks = request.direct_tracks
    velocity_b_map = _effective_velocity_b_map(request)
    channel_groups = _project_channel_groups(request, velocity_b_map)
    direct_instrument_map = {
        index: serialized_bdo_instrument_id(track)
        for index, track in enumerate(direct_tracks)
    }
    transform = request.conversion.export_transform_parameters()
    articulation_map = dict(request.articulation_map)
    track_settings_map = dict(request.track_settings)
    track_volume_map = _effective_track_volume_map(request)
    source_document = request.source_document
    exact_source = _request_matches_source_document(
        request,
        direct_instrument_map,
        track_settings_map,
        track_volume_map,
        velocity_b_map,
    )
    if exact_source:
        bdo_data = encode_score(source_document, mode="lossless")
        summary = score_summary(source_document)
    else:
        if source_document is not None:
            _reject_unsafe_opaque_source_rebuild(source_document)
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
            vel_scales=None,
            articulation_map=articulation_map or None,
            preserve_note_types=True,
            track_volumes=track_volume_map or None,
            track_settings_map=track_settings_map or None,
            # B was bound to each occurrence before pitch/time/articulation
            # projection, so identity-changing transforms cannot drop it.
            velocity_b_maps=None,
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


def _install_prepared_export(prepared: PreparedExport) -> tuple[str, str]:
    installed_path = ""
    installation_error = ""
    try:
        installed_path = str(
            install_export_to_game(prepared.out_path, prepared.game_dir)
        )
    except Exception as exc:
        installation_error = f"{type(exc).__name__}: {exc}"
    return installed_path, installation_error


def publish_export(
    prepared: PreparedExport,
) -> tuple[str, int, object, str, str]:
    """Atomically publish the primary artifact, then best-effort install it."""

    atomic_write_bytes(prepared.out_path, prepared.data)
    installed_path, installation_error = _install_prepared_export(prepared)
    return (
        str(prepared.out_path),
        len(prepared.data),
        prepared.summary,
        installed_path,
        installation_error,
    )


def _publish_verified_export(
    prepared: PreparedExport,
    expectation: ExportExpectation,
    prepared_report: ExportVerificationReport,
) -> tuple[str, int, object, str, str]:
    """Publish only bytes that retain the frozen editor's game semantics."""

    atomic_write_bytes(prepared.out_path, prepared.data)
    primary_report = verify_published_export(
        expectation,
        prepared.data,
        prepared.out_path,
        prepared_report=prepared_report,
    )
    if not primary_report.matches:
        # Do not copy an output whose durable primary bytes already disagree.
        raise ExportVerificationError(primary_report)

    installed_path, installation_error = _install_prepared_export(prepared)
    report = verify_published_export(
        expectation,
        prepared.data,
        prepared.out_path,
        installed_path or None,
        prepared_report=prepared_report,
    )
    summary = dict(prepared.summary)
    summary["verification_report"] = report
    return (
        str(prepared.out_path),
        len(prepared.data),
        summary,
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
    expectation = build_export_expectation(request)
    prepared = prepare_export(request)
    prepared_report = verify_export_bytes(
        expectation,
        prepared.data,
        stage="prepared",
    )
    if not prepared_report.matches:
        raise ExportVerificationError(prepared_report)
    return _publish_verified_export(
        prepared,
        expectation,
        prepared_report,
    )


__all__ = [
    "ExportRequest",
    "ExportRequestSpec",
    "ExportTrackSnapshot",
    "MARNIAN_SYNTH_INSTRUMENT_IDS",
    "MARNIAN_SYNTH_MODE_OFFSETS",
    "PreparedExport",
    "build_export_request",
    "execute_export",
    "freeze_export_tracks",
    "install_export_to_game",
    "prepare_export",
    "publish_export",
    "serialized_bdo_instrument_id",
]
