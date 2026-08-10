"""Canonical product boundary for game-owned content and preview sources.

This module records a product decision, not a claim of legal authorization.
Keeping the wording in one Qt-free owner lets the desktop UI, documentation,
packaging checks, and future extension hosts share the same fail-closed rule.
"""

from __future__ import annotations


CONTENT_BOUNDARY_TITLE = "内容边界"
CONTENT_BOUNDARY_PARAGRAPHS = (
    "本工具不提供受限制内容的获取或传播能力；外部内容须由用户自行确保来源与授权。",
)

PROHIBITED_GAME_AUDIO_TOOL_FILENAMES = frozenset(
    {
        "convert_wem_to_wav.py",
        "extract_bdo_bgm.cpp",
        "extract_bdo_instruments.cpp",
        "extract_wwise_wem.py",
        "list_bdo_paz_audio.cpp",
        "list_bdo_paz_audio.py",
        "validate_paz_key.cpp",
    }
)


__all__ = [
    "CONTENT_BOUNDARY_PARAGRAPHS",
    "CONTENT_BOUNDARY_TITLE",
    "PROHIBITED_GAME_AUDIO_TOOL_FILENAMES",
]
