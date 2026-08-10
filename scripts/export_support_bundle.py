#!/usr/bin/env python3
"""Export a bounded local diagnostic bundle chosen by the user."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_music_composer.app.support_bundle import export_support_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(export_support_bundle(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
