#!/usr/bin/env python3
"""Extract embedded Wwise WEM files from BNK SoundBanks.

This handles the common Wwise DIDX/DATA layout used by the BDO instrument
SoundBanks. It deliberately does not attempt to resolve external media.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


def read_chunks(data: bytes) -> dict[bytes, tuple[int, int]]:
    chunks: dict[bytes, tuple[int, int]] = {}
    position = 0
    while position + 8 <= len(data):
        tag = data[position:position + 4]
        size = struct.unpack_from("<I", data, position + 4)[0]
        content_start = position + 8
        content_end = content_start + size
        if content_end > len(data):
            raise ValueError(f"invalid {tag!r} chunk length {size}")
        chunks[tag] = (content_start, size)
        position = content_end
    if position != len(data):
        raise ValueError("trailing incomplete SoundBank data")
    return chunks


def extract_bank(bank_path: Path, output_root: Path) -> list[tuple[str, int, int, str]]:
    data = bank_path.read_bytes()
    chunks = read_chunks(data)
    if b"BKHD" not in chunks or b"DIDX" not in chunks or b"DATA" not in chunks:
        return []
    didx_start, didx_size = chunks[b"DIDX"]
    data_start, data_size = chunks[b"DATA"]
    if didx_size % 12:
        raise ValueError(f"{bank_path.name}: DIDX size is not a multiple of 12")

    output_dir = output_root / bank_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    for index in range(0, didx_size, 12):
        wem_id, offset, size = struct.unpack_from("<III", data, didx_start + index)
        end = offset + size
        if end > data_size:
            raise ValueError(f"{bank_path.name}: WEM {wem_id} is outside DATA")
        wem_data = data[data_start + offset:data_start + end]
        if wem_data[:4] != b"RIFF":
            raise ValueError(f"{bank_path.name}: WEM {wem_id} is not RIFF data")
        target = output_dir / f"{wem_id}.wem"
        target.write_bytes(wem_data)
        extracted.append((bank_path.name, wem_id, len(wem_data), str(target)))
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract embedded WEM files from Wwise BNK files")
    parser.add_argument("input", type=Path, help="BNK file or directory containing BNK files")
    parser.add_argument("output", type=Path, help="Directory for extracted WEM files")
    parser.add_argument("--manifest", type=Path, help="Optional TSV output path")
    args = parser.parse_args()

    banks = [args.input] if args.input.is_file() else sorted(args.input.glob("*.bnk"))
    if not banks:
        raise SystemExit("No BNK files found")

    rows = []
    for bank in banks:
        rows.extend(extract_bank(bank, args.output))
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        lines = ["bank\twem_id\tbytes\tpath"]
        lines.extend("\t".join(map(str, row)) for row in rows)
        args.manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Extracted {len(rows)} WEM files from {len(banks)} SoundBanks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
