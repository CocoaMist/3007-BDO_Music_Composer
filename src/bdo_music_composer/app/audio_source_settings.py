"""Application persistence boundary for preview-audio source selection.

This module contains no Qt state.  Both the settings dialog and the playback
orchestrator consume the same normalization rules, so saving unrelated
settings cannot silently discard a raw sample directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from bdo_music_composer.audio.bdo_sample_pack import PACK_SUFFIX
from bdo_music_composer.core.project_paths import user_documents_dir


DEFAULT_AUDIO_SOURCES = {
    "paz_root": os.environ.get("BDO_PAZ_ROOT", ""),
    "audio_root": os.environ.get("BDO_AUDIO_ROOT", ""),
    "sample_pack": "",
    "pack_audio_root": "",
    "pack_sample_pack": "",
    # UI policy only: this never changes score export or copies samples into
    # a project.
    "preview_mode": "generic",
}
PREVIEW_SOURCE_MODES = frozenset({"generic", "pack"})


def default_game_music_dir() -> Path:
    return user_documents_dir() / "Black Desert" / "music"


def preview_source_mode(source_config: dict[str, str]) -> str:
    """Return a supported persistent preview-source policy."""

    value = str(
        source_config.get("preview_mode", "generic") or "generic"
    ).casefold()
    if value in {"auto", "bdo", "companion", "custom"}:
        return "pack"
    return value if value in PREVIEW_SOURCE_MODES else "generic"


def audio_source_config(config: dict) -> dict[str, str]:
    """Return persistent local source roots without copying game assets."""

    saved = config.get("audio_sources", {})
    saved = saved if isinstance(saved, dict) else {}
    result = {
        key: str(saved.get(key) or value)
        for key, value in DEFAULT_AUDIO_SOURCES.items()
    }
    result["preview_mode"] = preview_source_mode(result)
    if not result["pack_sample_pack"] and not result["pack_audio_root"]:
        legacy_mode = str(saved.get("preview_mode", "") or "").casefold()
        legacy_prefixes = (
            ("custom", "companion")
            if legacy_mode == "custom"
            else ("companion", "custom")
        )
        for prefix in legacy_prefixes:
            legacy_pack = str(saved.get(f"{prefix}_sample_pack", "") or "")
            legacy_root = str(saved.get(f"{prefix}_audio_root", "") or "")
            if legacy_pack or legacy_root:
                result["pack_sample_pack"] = legacy_pack
                result["pack_audio_root"] = legacy_root
                break
    if not result["pack_sample_pack"] and result["sample_pack"]:
        result["pack_sample_pack"] = result["sample_pack"]
    if not result["pack_audio_root"] and result["audio_root"]:
        result["pack_audio_root"] = result["audio_root"]
    activate_audio_source(result, result["preview_mode"])
    return result


def source_paths_for_mode(
    source_config: dict[str, str],
    mode: str,
) -> tuple[str, str]:
    """Return ``(sample_pack, audio_root)`` remembered for one source mode."""

    normalized = str(mode or "").casefold()
    if normalized != "pack":
        return "", ""
    return (
        str(source_config.get("pack_sample_pack", "") or ""),
        str(source_config.get("pack_audio_root", "") or ""),
    )


def remember_source_paths(
    source_config: dict[str, str],
    mode: str,
    sample_pack: str,
    audio_root: str,
) -> None:
    """Persist the selected external sample pack and prepared root."""

    normalized = str(mode or "").casefold()
    if normalized != "pack":
        return
    source_config["pack_sample_pack"] = str(sample_pack or "")
    source_config["pack_audio_root"] = str(audio_root or "")


def activate_audio_source(
    source_config: dict[str, str],
    mode: str,
) -> None:
    """Project the selected remembered source onto the audio-engine keys."""

    normalized = preview_source_mode({"preview_mode": mode})
    sample_pack, audio_root = source_paths_for_mode(source_config, normalized)
    source_config["preview_mode"] = normalized
    source_config["sample_pack"] = sample_pack
    source_config["audio_root"] = audio_root


def displayed_audio_source(source_config: dict[str, str]) -> str:
    """Return the one user-selected preview source without losing raw roots."""

    return str(
        source_config.get("sample_pack", "")
        or source_config.get("audio_root", "")
        or ""
    )


def classify_audio_source(value: str) -> tuple[str, str]:
    """Split a local preview source into ``(sample_pack, audio_root)``."""

    selected = str(value or "").strip()
    if not selected:
        return "", ""
    if selected.casefold().endswith(PACK_SUFFIX.casefold()):
        return selected, ""
    candidate = Path(selected)
    if candidate.is_dir():
        return "", str(candidate.resolve())
    raise ValueError(selected)
