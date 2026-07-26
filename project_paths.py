"""Stable paths for project-owned resources.

External game assets remain configured separately; this module only describes
files tracked or generated inside the repository.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT
DATA_DIR = RESOURCE_ROOT / "data"
MAPPINGS_DIR = DATA_DIR / "mappings"
MANIFESTS_DIR = DATA_DIR / "manifests"
PROFILES_DIR = DATA_DIR / "profiles"
DOCS_DIR = RESOURCE_ROOT / "docs"
ASSETS_DIR = RESOURCE_ROOT / "assets"
WWISE_MIDI_MAP_PATH = MAPPINGS_DIR / "bdo_wwise_midi_map.json"
INSTRUMENT_SAMPLE_MAP_PATH = MAPPINGS_DIR / "bdo_instrument_sample_map.json"


def _user_data_dir() -> Path:
    override = os.environ.get("BDO_USER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BDO Music Composer"
    return Path.home() / "AppData" / "Local" / "BDO Music Composer"


def _local_cache_dir(name: str, override_name: str) -> Path:
    override = os.environ.get(override_name)
    if override:
        return Path(override).expanduser()
    # LOCALAPPDATA normally exists on Windows. Keep the fallback user-writable
    # for unusual launch environments instead of writing next to a frozen EXE.
    return _user_data_dir() / name


def _transcription_cache_dir() -> Path:
    """Resolve the writable transcription cache without freezing env state."""

    return _local_cache_dir(
        "transcription_cache",
        "BDO_TRANSCRIPTION_CACHE",
    )


SAMPLE_PACK_CACHE_DIR = _local_cache_dir(
    "sample_cache",
    "BDO_SAMPLE_PACK_CACHE",
)
GAME_ART_CACHE_DIR = _local_cache_dir(
    "game_art_cache",
    "BDO_GAME_ART_CACHE",
)
TRANSCRIPTION_CACHE_DIR = _transcription_cache_dir()
USER_DATA_DIR = _user_data_dir()
