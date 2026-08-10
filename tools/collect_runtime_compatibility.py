#!/usr/bin/env python3
"""Print a path-free desktop compatibility report as JSON."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_music_composer.ui.runtime_compatibility import compatibility_report_json


if __name__ == "__main__":
    print(compatibility_report_json())
