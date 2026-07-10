"""Stable paths for project-owned resources.

External game assets remain configured separately; this module only describes
files tracked or generated inside the repository.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MAPPINGS_DIR = DATA_DIR / "mappings"
MANIFESTS_DIR = DATA_DIR / "manifests"
DOCS_DIR = ROOT / "docs"
ASSETS_DIR = ROOT / "assets"
WWISE_MIDI_MAP_PATH = MAPPINGS_DIR / "bdo_wwise_midi_map.json"
INSTRUMENT_SAMPLE_MAP_PATH = MAPPINGS_DIR / "bdo_instrument_sample_map.json"
