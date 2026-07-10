#!/usr/bin/env python3
"""Create a TSV index for decoded instrument WAV samples."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path


def instrument_name(folder: str) -> str:
    name = folder.removeprefix("midi_instrument_")
    return name.replace("_", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Index WAV samples extracted from BDO instrument SoundBanks")
    parser.add_argument("input", type=Path, help="Root directory of instrument WAV folders")
    parser.add_argument("output", type=Path, help="TSV output path")
    args = parser.parse_args()

    rows = []
    for path in sorted(args.input.rglob("*.wav")):
        relative = path.relative_to(args.input)
        if len(relative.parts) < 2:
            continue
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            sample_rate = audio.getframerate()
            duration = frames / sample_rate if sample_rate else 0.0
            rows.append((
                relative.parts[0],
                instrument_name(relative.parts[0]),
                path.stem,
                audio.getnchannels(),
                sample_rate,
                audio.getsampwidth() * 8,
                frames,
                f"{duration:.3f}",
                path.stat().st_size,
                str(path),
            ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    header = "bank\tinstrument\twem_id\tchannels\tsample_rate\tbits\tframes\tduration_seconds\twav_bytes\tpath"
    args.output.write_text(
        header + "\n" + "\n".join("\t".join(map(str, row)) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(f"Indexed {len(rows)} WAV samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
