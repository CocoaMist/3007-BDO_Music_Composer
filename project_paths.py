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
SAMPLE_PACK_CACHE_DIR = ROOT / "sample_cache"


def _transcription_cache_dir() -> Path:
    override = os.environ.get("BDO_TRANSCRIPTION_CACHE")
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return (
            Path(local_app_data)
            / "BDO Music Composer"
            / "transcription_cache"
        )
    # LOCALAPPDATA normally exists on Windows. Keep the fallback user-writable
    # for unusual launch environments instead of writing next to a frozen EXE.
    return (
        Path.home()
        / "AppData"
        / "Local"
        / "BDO Music Composer"
        / "transcription_cache"
    )


TRANSCRIPTION_CACHE_DIR = _transcription_cache_dir()
