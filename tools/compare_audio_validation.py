#!/usr/bin/env python3
"""Measure one game-capture/local-render pair for the validation matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_audio_research import compare_audio  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="game capture WAV")
    parser.add_argument("candidate", type=Path, help="local renderer WAV")
    parser.add_argument("--output", type=Path, help="write JSON report")
    args = parser.parse_args()
    measurement = compare_audio(args.reference, args.candidate)
    # Paths are useful for this local CLI report but are deliberately excluded
    # from the reusable measurement object and committed experiment records.
    report = {
        "format": 2,
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        **asdict(measurement),
        "listener_pass": None,
        "verification": "pending_listener_review",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
