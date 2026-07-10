#!/usr/bin/env python3
"""Convert extracted WEM files to one-pass WAV previews with vgmstream-cli."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert WEM files to WAV using vgmstream-cli")
    parser.add_argument("input", type=Path, help="Root directory of extracted WEM files")
    parser.add_argument("output", type=Path, help="Root directory for WAV files")
    parser.add_argument("--vgmstream", type=Path, required=True, help="Path to vgmstream-cli.exe")
    parser.add_argument("--manifest", type=Path, help="Optional TSV manifest")
    args = parser.parse_args()

    if not args.vgmstream.is_file():
        raise SystemExit(f"vgmstream-cli not found: {args.vgmstream}")
    files = sorted(args.input.rglob("*.wem"))
    if not files:
        raise SystemExit("No WEM files found")

    converted: list[tuple[str, str, int]] = []
    failed: list[tuple[str, str]] = []
    for index, source in enumerate(files, start=1):
        relative = source.relative_to(args.input).with_suffix(".wav")
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.stat().st_size == 0:
            completed = subprocess.run(
                [str(args.vgmstream), "-i", "-o", str(target), str(source)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode:
                failed.append((str(source), completed.stderr.strip().replace("\n", " ")))
                continue
        converted.append((str(source), str(target), target.stat().st_size))
        if index % 100 == 0 or index == len(files):
            print(f"Converted {index}/{len(files)}")

    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        lines = ["wem_path\twav_path\twav_bytes"]
        lines.extend("\t".join(map(str, row)) for row in converted)
        if failed:
            lines.append("")
            lines.append("failed_wem\treason")
            lines.extend("\t".join(row) for row in failed)
        args.manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Converted {len(converted)} WEM files; failed {len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
