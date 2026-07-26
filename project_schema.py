"""Small, explicit migrations for autosaved BDO Music Composer projects."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from typing import Any, Mapping


CURRENT_PROJECT_SCHEMA = 9


DEFAULT_REFERENCE_LAYER_SETTINGS: dict[str, Any] = {
    "version": 1,
    "ghost_visible": True,
    "ghost_opacity_percent": 70,
    "background_opacity_percent": 60,
    "melody_lines_visible": True,
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
    result = dict(defaults)
    for key in (
        "ghost_visible",
        "melody_lines_visible",
        "frame_visible",
        "onset_visible",
        "contour_visible",
        "spectrogram_visible",
    ):
        candidate = source.get(key)
        if isinstance(candidate, bool):
            result[key] = candidate
    for key in (
        "ghost_opacity_percent",
        "background_opacity_percent",
    ):
        try:
            candidate = float(source.get(key, defaults[key]))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(candidate):
            result[key] = max(0, min(100, round(candidate)))
    result["version"] = 1
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
            track.setdefault("bdo_track_volume", 70)
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
    result["schema_version"] = version
    result.pop("version", None)
    return result


__all__ = [
    "CURRENT_PROJECT_SCHEMA",
    "DEFAULT_REFERENCE_LAYER_SETTINGS",
    "LEGACY_REFERENCE_LAYER_SETTINGS",
    "migrate_project",
    "normalize_reference_layer_settings",
    "project_relative_file_reference",
    "resolve_project_file_reference",
]
