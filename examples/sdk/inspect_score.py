"""Inspect and validate a BDO v9 score without printing private identity."""

from __future__ import annotations

import argparse
from pathlib import Path

from bdo_music_composer.sdk.core_api import read_score, score_summary, validate_score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("score", type=Path)
    args = parser.parse_args()

    document = read_score(args.score)
    issues = validate_score(document)
    summary = score_summary(document)
    print(f"version={document.version}")
    print(f"bpm={document.header.bpm} meter={document.header.time_signature}/4")
    print(f"groups={len(document.groups)} notes={document.total_notes}")
    print(f"summary={summary}")
    for issue in issues:
        print(f"{issue.severity}: {issue.code} at {issue.path}: {issue.message}")
    return 1 if any(issue.severity == "error" for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
