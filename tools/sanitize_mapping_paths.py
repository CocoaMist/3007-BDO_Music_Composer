#!/usr/bin/env python3
"""Remove machine-local prefixes from tracked BDO mapping metadata."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


JSON_AUDIO_PREFIX = re.compile(
    r'[A-Za-z]:\\\\[^"\r\n]*?\\\\乐器_(?:WAV|WEM)\\\\'
)
JSON_SOURCE_ROOT = re.compile(
    r'("source_root"\s*:\s*")[A-Za-z]:\\\\[^"]*(")'
)
TSV_AUDIO_PREFIX = re.compile(
    r"[A-Za-z]:\\[^\t\r\n]*?\\乐器_(?:WAV|WEM)\\"
)


def sanitize_text(path: Path, text: str) -> str:
    if path.suffix.lower() == ".json":
        text = JSON_AUDIO_PREFIX.sub("", text)
        return JSON_SOURCE_ROOT.sub(r"\1\2", text)
    if path.suffix.lower() == ".tsv":
        return TSV_AUDIO_PREFIX.sub("", text)
    return text


def sanitize_tree(root: Path) -> tuple[int, int]:
    changed_files = 0
    removed_prefixes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".tsv"}:
            continue
        original = path.read_text(encoding="utf-8")
        sanitized = sanitize_text(path, original)
        if sanitized == original:
            continue
        removed_prefixes += original.count(":\\") - sanitized.count(":\\")
        path.write_text(sanitized, encoding="utf-8", newline="")
        changed_files += 1
    return changed_files, removed_prefixes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data",
    )
    args = parser.parse_args()
    changed, prefixes = sanitize_tree(args.root.resolve())
    print(f"changed_files={changed} removed_absolute_prefixes={prefixes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
