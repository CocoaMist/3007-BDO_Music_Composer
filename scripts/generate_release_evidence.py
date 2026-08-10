#!/usr/bin/env python3
"""Generate SHA-256 and SPDX evidence for one release artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_music_composer.app.release_evidence import write_release_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    for path in write_release_evidence(args.artifact, args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
