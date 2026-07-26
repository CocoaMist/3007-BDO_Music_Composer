"""Index selected Black Desert PAZ paths without extracting game assets."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path
from typing import Iterator, TextIO


SMOD = ((333, 313, 505, 369), (379, 375, 319, 391), (361, 445, 451, 397), (397, 425, 395, 505))
SXOR = ((0x83, 0x85, 0x9B, 0xCD), (0xCC, 0xA7, 0xAD, 0x41), (0x4B, 0x2E, 0xD4, 0x33), (0xEA, 0xCB, 0x2E, 0x04))
PBOX = (0x00000001, 0x00000080, 0x00000400, 0x00002000, 0x00080000, 0x00200000, 0x01000000, 0x40000000,
        0x00000008, 0x00000020, 0x00000100, 0x00004000, 0x00010000, 0x00800000, 0x04000000, 0x20000000,
        0x00000004, 0x00000010, 0x00000200, 0x00008000, 0x00020000, 0x00400000, 0x08000000, 0x10000000,
        0x00000002, 0x00000040, 0x00000800, 0x00001000, 0x00040000, 0x00100000, 0x02000000, 0x80000000)
KEYROT = (0, 1, 2, 3, 2, 1, 3, 0, 1, 3, 2, 0, 3, 1, 0, 2)
MASK = 0xFFFFFFFF
DEFAULT_EXTENSIONS = (
    ".wem", ".wav", ".ogg", ".mp3", ".fsb",
    ".bnk", ".acb", ".hca", ".awb", ".wma",
)


def gf_mult(a: int, b: int, m: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        b >>= 1
        if a >= 256:
            a ^= m
    return result


def gf_exp7(b: int, m: int) -> int:
    if b == 0:
        return 0
    x = gf_mult(b, b, m)
    x = gf_mult(b, x, m)
    x = gf_mult(x, x, m)
    return gf_mult(b, x, m)


def perm32(value: int) -> int:
    result = 0
    index = 0
    while value:
        if value & 1:
            result |= PBOX[index]
        value >>= 1
        index += 1
    return result


class Ice:
    def __init__(self, key: bytes):
        self.sbox = [[0] * 1024 for _ in range(4)]
        for i in range(1024):
            col, row = (i >> 1) & 0xFF, (i & 1) | ((i & 0x200) >> 8)
            for box in range(4):
                self.sbox[box][i] = perm32(gf_exp7(col ^ SXOR[box][row], SMOD[box][row]) << (24 - 8 * box))
        kb = [(key[i * 2] << 8) | key[i * 2 + 1] for i in range(4)][::-1]
        self.schedule = self._build_schedule(kb)

    @staticmethod
    def _build_schedule(kb: list[int]) -> list[tuple[int, int, int]]:
        schedule = []
        for kr in KEYROT[:8]:
            words = [0, 0, 0]
            for j in range(15):
                for k in range(4):
                    pos = (kr + k) & 3
                    bit = kb[pos] & 1
                    words[j % 3] = ((words[j % 3] << 1) | bit) & MASK
                    kb[pos] = (kb[pos] >> 1) | ((bit ^ 1) << 15)
            schedule.append(tuple(words))
        return schedule

    def _f(self, p: int, sk: tuple[int, int, int]) -> int:
        tl = ((p >> 16) & 0x3FF) | (((p >> 14) | (p << 18)) & 0xFFC00)
        tr = (p & 0x3FF) | ((p << 2) & 0xFFC00)
        al = sk[2] & (tl ^ tr)
        ar = al ^ tr
        al = (al ^ tl ^ sk[0]) & MASK
        ar = (ar ^ sk[1]) & MASK
        return self.sbox[0][al >> 10] | self.sbox[1][al & 0x3FF] | self.sbox[2][ar >> 10] | self.sbox[3][ar & 0x3FF]

    def decrypt(self, data: bytes) -> bytes:
        if len(data) % 8:
            raise ValueError(f"ICE input is not eight-byte aligned: {len(data)}")
        output = bytearray(len(data))
        for offset in range(0, len(data), 8):
            left, right = struct.unpack(">II", data[offset:offset + 8])
            for i in range(7, 0, -2):
                left = (left ^ self._f(right, self.schedule[i])) & MASK
                right = (right ^ self._f(left, self.schedule[i - 1])) & MASK
            output[offset:offset + 8] = struct.pack(">II", right, left)
        return bytes(output)


def normalized_extensions(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Return deterministic case-insensitive suffixes accepted by the index."""

    result = {
        value.strip().lower()
        if value.strip().startswith(".")
        else f".{value.strip().lower()}"
        for value in values
        if value.strip()
    }
    return tuple(sorted(result))


def path_matches(
    path: str,
    *,
    extensions: tuple[str, ...],
    contains: tuple[str, ...] = (),
    all_files: bool = False,
) -> bool:
    """Apply portable path filters; repeated text filters use OR semantics."""

    value = path.replace("\\", "/").lower()
    if not all_files and not value.endswith(extensions):
        return False
    needles = tuple(item.strip().lower() for item in contains if item.strip())
    return not needles or any(needle in value for needle in needles)


def decode_game_path(value: bytes) -> tuple[str, str]:
    """Decode archive paths while reporting legacy Korean path encoding."""

    try:
        return value.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        try:
            return value.decode("cp949"), "cp949"
        except UnicodeDecodeError:
            return value.decode("utf-8", "replace"), "replacement"


def validate_game_path(value: str) -> str:
    """Return a normalized relative path or reject report-unsafe metadata."""

    normalized = value.replace("\\", "/")
    if not normalized:
        raise ValueError("empty PAZ path")
    if any(character in normalized for character in ("\0", "\r", "\n", "\t")):
        raise ValueError(f"control character in PAZ path: {value!r}")
    if normalized.startswith("/") or (
        len(normalized) >= 2
        and normalized[0].isalpha()
        and normalized[1] == ":"
    ):
        raise ValueError(f"absolute PAZ path: {value!r}")
    if ".." in normalized.split("/"):
        raise ValueError(f"parent traversal in PAZ path: {value!r}")
    return normalized.lower()


def archive_table_span(
    archive_size: int,
    file_count: int,
    path_length: int,
) -> tuple[int, int]:
    """Validate table sizes before allocating data declared by an archive."""

    if min(archive_size, file_count, path_length) < 0:
        raise ValueError("negative PAZ archive layout value")
    info_size = file_count * 24
    table_end = 12 + info_size + path_length
    if path_length % 8:
        raise ValueError(
            f"encrypted PAZ path table is not eight-byte aligned: {path_length}"
        )
    if table_end > archive_size:
        raise ValueError(
            "PAZ archive tables exceed file size: "
            f"need {table_end}, have {archive_size}"
        )
    return info_size, table_end


def stable_path_digest(paths: set[str]) -> str:
    """Hash a normalized path set without depending on archive scan order."""

    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@contextmanager
def atomic_text_output(path: Path) -> Iterator[TextIO]:
    """Replace a report only after its complete contents are durable."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary as output:
            yield output
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paz_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Optional portable integrity/filter summary.",
    )
    parser.add_argument(
        "--extension",
        action="append",
        default=[],
        help=(
            "File suffix to index (repeatable). Defaults to common audio and "
            "SoundBank suffixes."
        ),
    )
    parser.add_argument(
        "--contains",
        action="append",
        default=[],
        help="Case-insensitive path substring (repeatable, matches any).",
    )
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="Case-insensitive normalized path prefix (repeatable, matches any).",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Disable the extension filter; pair with --contains or --prefix.",
    )
    parser.add_argument(
        "--archive",
        action="append",
        type=int,
        default=[],
        help="Only inspect this numeric PAD archive (repeatable).",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Return success when archives referenced by meta are absent.",
    )
    args = parser.parse_args()
    archive_filter = set(args.archive)
    if args.all_files and not (
        args.contains or args.prefix or archive_filter
    ):
        parser.error(
            "--all-files requires --contains, --prefix, or --archive "
            "to keep the scan bounded"
        )
    meta = args.paz_dir / "pad00000.meta"
    metadata = meta.read_bytes()
    if len(metadata) < 8:
        raise ValueError(f"{meta}: truncated PAZ metadata header")
    version, count = struct.unpack("<II", metadata[:8])
    table_end = 8 + count * 12
    if len(metadata) < table_end:
        raise ValueError(f"{meta}: truncated PAZ archive table")
    tables = tuple(struct.iter_unpack("<III", metadata[8:table_end]))
    declared_archives = [number for number, _crc, _size in tables]
    if len(set(declared_archives)) != len(declared_archives):
        raise ValueError(f"{meta}: duplicate PAZ archive id")
    unknown_archives = sorted(archive_filter - set(declared_archives))
    if unknown_archives:
        raise ValueError(
            f"{meta}: requested archives not declared: {unknown_archives}"
        )
    ice = Ice(bytes.fromhex("51 F3 0F 11 04 24 6A 00"))
    extensions = normalized_extensions(
        args.extension or list(DEFAULT_EXTENSIONS)
    )
    prefixes = tuple(
        item.replace("\\", "/").strip().lower()
        for item in args.prefix
        if item.strip()
    )
    found = 0
    files_seen = 0
    scanned = 0
    missing: list[int] = []
    duplicate_paths = 0
    cp949_paths = 0
    replacement_paths = 0
    seen_paths: set[str] = set()
    matched_extensions: Counter[str] = Counter()
    with atomic_text_output(args.output) as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow((
            "paz", "offset", "packed_size", "original_size", "path",
        ))
        for number, _crc, expected_size in tables:
            if archive_filter and number not in archive_filter:
                continue
            archive = args.paz_dir / f"PAD{number:05}.PAZ"
            if not archive.exists():
                missing.append(number)
                continue
            archive_size = archive.stat().st_size
            if expected_size and archive_size != expected_size:
                raise ValueError(
                    f"{archive}: size {archive_size} != meta {expected_size}"
                )
            with archive.open("rb") as stream:
                header = stream.read(12)
                if len(header) != 12:
                    raise ValueError(f"{archive}: truncated archive header")
                _archive_crc, file_count, path_length = struct.unpack(
                    "<III",
                    header,
                )
                info_size, _table_end = archive_table_span(
                    archive_size,
                    file_count,
                    path_length,
                )
                info_bytes = stream.read(info_size)
                if len(info_bytes) != info_size:
                    raise ValueError(f"{archive}: truncated file table")
                infos = tuple(struct.iter_unpack("<IIIIII", info_bytes))
                encrypted_paths = stream.read(path_length)
            if len(encrypted_paths) != path_length:
                raise ValueError(f"{archive}: truncated encrypted path table")
            paths = ice.decrypt(encrypted_paths).split(b"\0")
            scanned += 1
            for (
                _file_crc,
                folder_id,
                file_id,
                offset,
                packed_size,
                original_size,
            ) in infos:
                files_seen += 1
                if offset > archive_size or packed_size > archive_size - offset:
                    raise ValueError(
                        f"{archive}: payload outside archive at {offset} "
                        f"for {packed_size} bytes"
                    )
                if folder_id >= len(paths) or file_id >= len(paths):
                    raise ValueError(
                        f"{archive}: invalid path ids {folder_id}/{file_id}"
                    )
                name, encoding = decode_game_path(
                    paths[folder_id] + paths[file_id]
                )
                if encoding == "cp949":
                    cp949_paths += 1
                elif encoding == "replacement":
                    replacement_paths += 1
                normalized_name = validate_game_path(name)
                if prefixes and not any(
                    normalized_name.startswith(prefix)
                    for prefix in prefixes
                ):
                    continue
                if not path_matches(
                    name,
                    extensions=extensions,
                    contains=tuple(args.contains),
                    all_files=args.all_files,
                ):
                    continue
                if normalized_name in seen_paths:
                    duplicate_paths += 1
                else:
                    seen_paths.add(normalized_name)
                matched_extensions[Path(normalized_name).suffix] += 1
                writer.writerow((
                    number,
                    offset,
                    packed_size,
                    original_size,
                    name.replace("\\", "/"),
                ))
                found += 1
    summary = {
        "format": 1,
        "meta_version": version,
        "meta_sha256": hashlib.sha256(metadata).hexdigest(),
        "archives_declared": count,
        "archives_scanned": scanned,
        "archives_missing": missing,
        "matched_entries": found,
        "files_seen": files_seen,
        "matched_path_set_sha256": stable_path_digest(seen_paths),
        "matched_extensions": dict(sorted(matched_extensions.items())),
        "duplicate_matched_paths": duplicate_paths,
        "cp949_paths_seen": cp949_paths,
        "replacement_paths_seen": replacement_paths,
        "all_files": bool(args.all_files),
        "extensions": list(extensions),
        "contains": list(args.contains),
        "prefixes": list(prefixes),
        "archive_filter": sorted(archive_filter),
    }
    if args.summary_json:
        with atomic_text_output(args.summary_json) as output:
            json.dump(summary, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(
        f"PAZ meta version: {version}; archives scanned: {scanned}/{count}; "
        f"missing: {len(missing)}; matched entries: {found}; "
        f"duplicate matched paths: {duplicate_paths}; "
        f"cp949/replacement paths: {cp949_paths}/{replacement_paths}"
    )
    print(args.output)
    missing_ok = args.allow_missing or not missing
    return 0 if missing_ok and not duplicate_paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
