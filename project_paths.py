"""Stable paths for project-owned resources.

External game assets remain configured separately; this module only describes
files tracked or generated inside the repository.
"""

from __future__ import annotations

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT
DATA_DIR = RESOURCE_ROOT / "data"
MAPPINGS_DIR = DATA_DIR / "mappings"
MANIFESTS_DIR = DATA_DIR / "manifests"
DOCS_DIR = RESOURCE_ROOT / "docs"
ASSETS_DIR = RESOURCE_ROOT / "assets"
WWISE_MIDI_MAP_PATH = MAPPINGS_DIR / "bdo_wwise_midi_map.json"
INSTRUMENT_SAMPLE_MAP_PATH = MAPPINGS_DIR / "bdo_instrument_sample_map.json"
