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
    # UI policy only: this never changes score export or copies samples into
    # a project.
    "preview_mode": "auto",
}
PREVIEW_SOURCE_MODES = frozenset({"auto", "bdo", "generic"})


def default_game_music_dir() -> Path:
    return user_documents_dir() / "Black Desert" / "music"


def preview_source_mode(source_config: dict[str, str]) -> str:
    """Return a supported persistent preview-source policy."""

    value = str(source_config.get("preview_mode", "auto") or "auto").casefold()
    return value if value in PREVIEW_SOURCE_MODES else "auto"


def audio_source_config(config: dict) -> dict[str, str]:
    """Return persistent local source roots without copying game assets."""

    saved = config.get("audio_sources", {})
    result = {
        key: str(saved.get(key) or value)
        for key, value in DEFAULT_AUDIO_SOURCES.items()
    }
    result["preview_mode"] = preview_source_mode(result)
    return result


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
