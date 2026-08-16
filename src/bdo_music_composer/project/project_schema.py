"""Small packaged migrations for autosaved BDO Music Composer projects."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any, Mapping

from bdo_midi import Note
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME
from bdo_music_composer.core.conversion_settings import (
    MATERIALIZED_VELOCITY_MODES,
    VELOCITY_MODE_PRESERVE,
    ConversionSettings,
)
from bdo_music_composer.editor.game_score_model import bake_game_velocity_transform
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan


CURRENT_PROJECT_SCHEMA = 17
REFERENCE_LAYER_SETTINGS_VERSION = 10


DEFAULT_REFERENCE_LAYER_SETTINGS: dict[str, Any] = {
    "version": REFERENCE_LAYER_SETTINGS_VERSION,
    # Other-track notes are an optional harmonic reference, not part of the
    # editable score. New projects start with that layer out of the way.
    "ghost_visible": False,
    "ghost_opacity_percent": 30,
    # Analysis candidates are provisional note blocks.  Their presentation is
    # independent from both editable notes and the other-track reference.
    "candidate_visible": True,
    "candidate_opacity_percent": 52,
    # Anonymous timbre colours are a display-only analysis sidecar.  Generic
    # instrument labels require a separately installed external backend and
    # therefore remain opt-in.
    "timbre_grouping_enabled": True,
    "external_instrument_labels_enabled": False,
    # Reference-audio analysis supplies the default project tempo only when
    # its onset evidence is strong; a direct BPM edit turns this off.
    "follow_reference_bpm": True,
    "background_opacity_percent": 45,
    # Pitch contours are a foreground analysis guide, so their strength is
    # independent from the frame/onset evidence background.
    "contour_opacity_percent": 82,
    # Display-only pitch-guide cleanup.  This never changes recognition
    # candidates, editable notes or export data.
    "contour_denoise": "standard",
    # Explicit opt-in weak supervision from editable melody notes.  It only
    # changes the display emphasis of matching timbre groups.
    "melody_guidance_enabled": False,
    # The derived melody connectors are optional context and can become noisy
    # on dense full-song recognition.  Keep the raw pitch guide discoverable
    # instead of covering new projects with inferred jumps.
    "melody_lines_visible": False,
    "frame_visible": False,
    "onset_visible": False,
    "contour_visible": False,
    "spectrogram_visible": False,
}

# Before schema v9 the layers had no user opacity control.  Migrated projects
# retain that exact full-strength rendering, while genuinely new projects use
# the quieter defaults above so reference material does not overpower notes.
LEGACY_REFERENCE_LAYER_SETTINGS: dict[str, Any] = {
    **DEFAULT_REFERENCE_LAYER_SETTINGS,
    "ghost_opacity_percent": 100,
    "background_opacity_percent": 100,
    "contour_opacity_percent": 100,
}


def normalize_reference_layer_settings(
    value: object,
    *,
    legacy_defaults: bool = False,
) -> dict[str, Any]:
    """Return bounded, forward-compatible reference-layer view settings."""

    defaults = (
        LEGACY_REFERENCE_LAYER_SETTINGS
        if legacy_defaults
        else DEFAULT_REFERENCE_LAYER_SETTINGS
    )
    source = dict(value) if isinstance(value, Mapping) else {}
    try:
        source_version = int(source.get("version", 1))
    except (TypeError, ValueError, OverflowError):
        source_version = 1
    result = dict(defaults)
    for key in (
        "ghost_visible",
        "candidate_visible",
        "timbre_grouping_enabled",
        "external_instrument_labels_enabled",
        "follow_reference_bpm",
        "melody_guidance_enabled",
        "melody_lines_visible",
        "frame_visible",
        "onset_visible",
        "contour_visible",
        "spectrogram_visible",
    ):
        candidate = source.get(key)
        if isinstance(candidate, bool):
            result[key] = candidate
    contour_denoise = str(
        source.get("contour_denoise", defaults["contour_denoise"])
    )
    if contour_denoise in {"low", "standard", "high"}:
        result["contour_denoise"] = contour_denoise
    for key in (
        "ghost_opacity_percent",
        "candidate_opacity_percent",
        "background_opacity_percent",
        "contour_opacity_percent",
    ):
        try:
            candidate = float(source.get(key, defaults[key]))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(candidate):
            result[key] = max(0, min(100, round(candidate)))
    # Version 8 coupled contour strength to the shared evidence opacity.  Keep
    # that effective strength for existing projects while new projects receive
    # the clearer independent default above.
    if source and source_version < 9 and "contour_opacity_percent" not in source:
        result["contour_opacity_percent"] = int(
            result["background_opacity_percent"]
        )
    # Earlier versions shipped 70%, 40%, then 24% as their ghost defaults, plus
    # a 60% evidence-background default.  Migrate only those exact defaults;
    # deliberate custom values remain untouched.
    if not legacy_defaults and source_version < REFERENCE_LAYER_SETTINGS_VERSION:
        old_ghost_defaults = {40}
        if source_version < 4:
            old_ghost_defaults.add(24)
        if source_version < 2:
            old_ghost_defaults.add(70)
        if result["ghost_opacity_percent"] in old_ghost_defaults:
            result["ghost_opacity_percent"] = int(
                DEFAULT_REFERENCE_LAYER_SETTINGS["ghost_opacity_percent"]
            )
        if result["background_opacity_percent"] == 60:
            result["background_opacity_percent"] = int(
                DEFAULT_REFERENCE_LAYER_SETTINGS["background_opacity_percent"]
            )
    result["version"] = REFERENCE_LAYER_SETTINGS_VERSION
    return result


def _migrate_transcription_review(
    value: object,
    *,
    legacy_project: bool = False,
) -> dict[str, Any]:
    review = dict(value) if isinstance(value, Mapping) else {}
    try:
        review_version = int(
            review.get("version", 1 if legacy_project else 4)
        )
    except (TypeError, ValueError, OverflowError):
        if legacy_project:
            review.setdefault("analysis_mode", "standard")
            review["cleanup_profile"] = "preserve"
            review["version"] = 4
        return review
    if review_version > 4:
        return review
    if legacy_project or review_version < 4:
        review.setdefault("analysis_mode", "standard")
        # Cleanup choices saved before v4 did not execute automatic actions.
        # Preserve their candidate stream rather than silently activating a
        # formerly inert balanced/clean selection after an application update.
        review["cleanup_profile"] = "preserve"
    else:
        review.setdefault("cleanup_profile", "preserve")
    review["version"] = 4
    return review


def project_relative_file_reference(
    project_dir: Path,
    file_path: Path | str | None,
) -> str:
    """Return a portable project-local reference, never an absolute path."""

    if not file_path:
        return ""
    base = Path(project_dir).resolve()
    candidate = Path(file_path).resolve()
    try:
        relative = candidate.relative_to(base)
    except ValueError:
        return ""
    if not relative.parts or relative == Path("."):
        return ""
    return relative.as_posix()


def resolve_project_file_reference(
    project_dir: Path,
    reference: object,
    *,
    allow_legacy_absolute: bool = False,
) -> Path | None:
    """Resolve a project file reference without permitting directory traversal.

    Current projects use project-relative references.  Absolute paths are
    accepted only at the explicit legacy compatibility boundary; callers must
    never pass that option for untrusted current-schema relative references.
    """

    if not isinstance(reference, (str, Path)):
        return None
    raw_text = str(reference).strip()
    if not raw_text:
        return None
    raw_path = Path(raw_text)
    if raw_path.is_absolute():
        if not allow_legacy_absolute:
            return None
        candidate = raw_path.resolve()
    else:
        base = Path(project_dir).resolve()
        candidate = (base / raw_path).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return None
        if candidate == base:
            return None
    return candidate


def _normalized_pitch_transform(result: Mapping[str, Any]) -> dict[str, Any]:
    conversion = result.get("conversion_settings")
    conversion_source = conversion if isinstance(conversion, Mapping) else {}
    pitch_source = result.get("pitch_transform")
    pitch_mapping = pitch_source if isinstance(pitch_source, Mapping) else {}
    try:
        global_semitones = int(
            conversion_source.get(
                "transpose",
                pitch_mapping.get("global_semitones", 0),
            )
        )
    except (TypeError, ValueError, OverflowError):
        global_semitones = 0
    return PitchTransformPlan.from_payload(
        pitch_source,
        default_global_semitones=global_semitones,
    ).with_global(global_semitones).to_payload()


def _bake_game_velocity_policy(result: dict[str, Any]) -> None:
    """Materialize export-only velocity transforms into project note data."""

    raw_conversion = result.get("conversion_settings")
    conversion_payload = (
        dict(raw_conversion) if isinstance(raw_conversion, Mapping) else {}
    )
    settings = ConversionSettings.from_project_payload(
        conversion_payload,
        source_format=str(result.get("source_format") or "midi"),
    )
    for track in result.get("tracks", []):
        if not isinstance(track, dict):
            continue
        raw_notes = track.get("notes")
        positions: list[int] = []
        notes: list[Note] = []
        if isinstance(raw_notes, list):
            for position, raw_note in enumerate(raw_notes):
                if not isinstance(raw_note, list) or len(raw_note) < 5:
                    continue
                try:
                    notes.append(Note(
                        int(raw_note[0]),
                        int(raw_note[1]),
                        float(raw_note[2]),
                        float(raw_note[3]),
                        int(raw_note[4]),
                    ))
                except (TypeError, ValueError, OverflowError):
                    continue
                positions.append(position)
        transformed = bake_game_velocity_transform(
            notes,
            settings,
            legacy_scale=track.get("volume_scale", 1.0),
        )
        if isinstance(raw_notes, list):
            for position, note in zip(positions, transformed):
                raw_notes[position][1] = int(note.vel)
        track["volume_scale"] = 1.0
    conversion_payload.update(
        settings.with_updates(
            velocity_mode=VELOCITY_MODE_PRESERVE
        ).to_payload()
    )
    result["conversion_settings"] = conversion_payload


def _normalize_current_velocity_policy(result: dict[str, Any]) -> None:
    """Validate schema-v11 velocity state without revisiting every note.

    Schema v11 stores only game-native note velocities.  ``off`` and
    ``preserve`` are equivalent at that boundary and are normalized to the
    single canonical value.  Any transform or per-track scale in an already
    current document means a historical migration was skipped; applying it
    here would silently transform the notes every time the project is opened.
    """

    raw_conversion = result.get("conversion_settings")
    if raw_conversion is not None and not isinstance(raw_conversion, Mapping):
        raise ValueError("conversion_settings must be an object")
    conversion_payload = (
        dict(raw_conversion) if isinstance(raw_conversion, Mapping) else {}
    )
    raw_mode = conversion_payload.get(
        "velocity_mode",
        VELOCITY_MODE_PRESERVE,
    )
    mode = str(raw_mode or VELOCITY_MODE_PRESERVE)
    if mode not in MATERIALIZED_VELOCITY_MODES:
        raise ValueError(
            "schema v11 velocity transforms must already be materialized "
            f"(found {mode!r})"
        )
    settings = ConversionSettings.from_project_payload(
        conversion_payload,
        source_format=str(result.get("source_format") or "midi"),
    )
    conversion_payload.update(
        settings.with_updates(
            velocity_mode=VELOCITY_MODE_PRESERVE
        ).to_payload()
    )
    result["conversion_settings"] = conversion_payload

    raw_tracks = result.get("tracks", ())
    if not isinstance(raw_tracks, list):
        return
    for track_index, track in enumerate(raw_tracks):
        if not isinstance(track, Mapping):
            continue
        raw_scale = track.get("volume_scale", 1.0)
        try:
            scale = float(raw_scale)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"tracks[{track_index}].volume_scale must be finite"
            ) from exc
        if not math.isfinite(scale):
            raise ValueError(
                f"tracks[{track_index}].volume_scale must be finite"
            )
        if not math.isclose(scale, 1.0, abs_tol=1e-12):
            raise ValueError(
                f"tracks[{track_index}].volume_scale must already be "
                "materialized in schema v11"
            )


def _migrate_arrangement_schema(
    result: dict[str, Any], version: int
) -> int:
    if version == 11:
        for track in result.get("tracks") or ():
            if isinstance(track, dict):
                track.setdefault("clip_start_ms", None)
                track.setdefault("clip_end_ms", None)
                track.setdefault("arrangement_group_id", "")
        result["schema_version"] = version = 12
    if version == 12:
        for track in result.get("tracks") or ():
            if isinstance(track, dict):
                track.setdefault("arrangement_clips", [])
        result["schema_version"] = version = 13
    if version == 13:
        for track in result.get("tracks") or ():
            if not isinstance(track, dict):
                continue
            for clip in track.get("arrangement_clips") or ():
                if isinstance(clip, dict):
                    clip.setdefault("time_offset_ms", 0.0)
        result["schema_version"] = version = 14
    if version == 14:
        # Schema 15 was briefly used by development builds for Clip trim
        # limits.  Keep the version readable, but the corrected left-anchored
        # scaling model needs no persisted fields of its own.
        result["schema_version"] = version = 15
    if version == 15:
        for track in result.get("tracks") or ():
            if not isinstance(track, dict):
                continue
            for clip in track.get("arrangement_clips") or ():
                if isinstance(clip, dict):
                    clip.setdefault("display_name", "")
                    clip.setdefault("color", "")
        result["schema_version"] = version = 16
    if version == 16:
        for track in result.get("tracks") or ():
            if not isinstance(track, dict):
                continue
            track.setdefault("loose_velocity_percent", 100)
            track.setdefault("loose_velocity_baseline_a", [])
            track.setdefault("loose_velocity_baseline_b", [])
            for clip in track.get("arrangement_clips") or ():
                if isinstance(clip, dict):
                    clip.setdefault("velocity_percent", 100)
                    clip.setdefault("velocity_baseline_a", [])
                    clip.setdefault("velocity_baseline_b", [])
        result["schema_version"] = version = 17
    return version


def migrate_project(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    version = int(result.get("schema_version", result.get("version", 1)))
    if version < 1 or version > CURRENT_PROJECT_SCHEMA:
        raise ValueError(f"unsupported project schema version: {version}")
    if version == 1:
        result["schema_version"] = 2
        result.setdefault("research", {"profile_id": "bdo-global-v9-2026.07", "ab_experiments": []})
        version = 2
    if version == 2:
        for track in result.get("tracks", []):
            if not isinstance(track, dict):
                continue
            track.setdefault("bdo_track_volume", DEFAULT_TRACK_VOLUME)
            track.setdefault("bdo_track_settings", [0] * 8)
            track.setdefault("bdo_source_group_index", None)
            track.setdefault("bdo_source_note_records", [])
        result["schema_version"] = 3
        version = 3
    if version == 3:
        result.setdefault("reference_audio_offset_ms", 0.0)
        result.setdefault("beat_origin_ms", 0.0)
        result.setdefault("transcription_review", {})
        result["schema_version"] = 4
        version = 4
    if version == 4:
        result.setdefault("transcription_assist_review", {})
        result["schema_version"] = 5
        version = 5
    if version == 5:
        result["transcription_review"] = _migrate_transcription_review(
            result.get("transcription_review"),
            legacy_project=True,
        )
        result["schema_version"] = 6
        version = 6
    if version == 6:
        result["transcription_review"] = _migrate_transcription_review(
            result.get("transcription_review"),
            legacy_project=True,
        )
        result["schema_version"] = 7
        version = 7
    if version == 7:
        result["transcription_review"] = _migrate_transcription_review(
            result.get("transcription_review"),
            legacy_project=True,
        )
        result["schema_version"] = 8
        version = 8
    if version == 8:
        result["reference_layers"] = normalize_reference_layer_settings(
            result.get("reference_layers"),
            legacy_defaults=True,
        )
        result["schema_version"] = 9
        version = 9
    if version == 9:
        result["pitch_transform"] = _normalized_pitch_transform(result)
        result["schema_version"] = 10
        version = 10
    if version == 10:
        _bake_game_velocity_policy(result)
        result["schema_version"] = 11
        version = 11
    version = _migrate_arrangement_schema(result, version)
    for track in result.get("tracks") or ():
        if not isinstance(track, dict):
            continue
        track.setdefault("loose_velocity_percent", 100)
        track.setdefault("loose_velocity_baseline_a", [])
        track.setdefault("loose_velocity_baseline_b", [])
        for clip in track.get("arrangement_clips") or ():
            if isinstance(clip, dict):
                clip.setdefault("velocity_percent", 100)
                clip.setdefault("velocity_baseline_a", [])
                clip.setdefault("velocity_baseline_b", [])
    # A hand-written current project can omit optional fields.  Keep migration
    # idempotent and give every current project the same safe defaults.
    result.setdefault("reference_audio_offset_ms", 0.0)
    result.setdefault("beat_origin_ms", 0.0)
    result["transcription_review"] = _migrate_transcription_review(
        result.get("transcription_review")
    )
    result.setdefault("transcription_assist_review", {})
    result["reference_layers"] = normalize_reference_layer_settings(
        result.get("reference_layers")
    )
    result["pitch_transform"] = _normalized_pitch_transform(result)
    _normalize_current_velocity_policy(result)
    result["schema_version"] = version
    result.pop("version", None)
    return result


__all__ = [
    "CURRENT_PROJECT_SCHEMA",
    "DEFAULT_REFERENCE_LAYER_SETTINGS",
    "LEGACY_REFERENCE_LAYER_SETTINGS",
    "REFERENCE_LAYER_SETTINGS_VERSION",
    "migrate_project",
    "normalize_reference_layer_settings",
    "project_relative_file_reference",
    "resolve_project_file_reference",
]
