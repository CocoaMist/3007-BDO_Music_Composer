"""Bounded PAZ primitives used only by the allow-listed local artwork import.

This is deliberately not an archive browser or extraction API.  The only
production caller applies its own exact path allow-list before reading two UI
resources into a user-selected local cache.
"""

from __future__ import annotations

import struct


SMOD = (
    (333, 313, 505, 369),
    (379, 375, 319, 391),
    (361, 445, 451, 397),
    (397, 425, 395, 505),
)
SXOR = (
    (0x83, 0x85, 0x9B, 0xCD),
    (0xCC, 0xA7, 0xAD, 0x41),
    (0x4B, 0x2E, 0xD4, 0x33),
    (0xEA, 0xCB, 0x2E, 0x04),
)
PBOX = (
    0x00000001, 0x00000080, 0x00000400, 0x00002000,
    0x00080000, 0x00200000, 0x01000000, 0x40000000,
    0x00000008, 0x00000020, 0x00000100, 0x00004000,
    0x00010000, 0x00800000, 0x04000000, 0x20000000,
    0x00000004, 0x00000010, 0x00000200, 0x00008000,
    0x00020000, 0x00400000, 0x08000000, 0x10000000,
    0x00000002, 0x00000040, 0x00000800, 0x00001000,
    0x00040000, 0x00100000, 0x02000000, 0x80000000,
)
KEYROT = (0, 1, 2, 3, 2, 1, 3, 0, 1, 3, 2, 0, 3, 1, 0, 2)
MASK = 0xFFFFFFFF


def _gf_mult(a: int, b: int, modulus: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        b >>= 1
        if a >= 256:
            a ^= modulus
    return result


def _gf_exp7(value: int, modulus: int) -> int:
    if value == 0:
        return 0
    square = _gf_mult(value, value, modulus)
    cube = _gf_mult(value, square, modulus)
    sixth = _gf_mult(cube, cube, modulus)
    return _gf_mult(value, sixth, modulus)


def _perm32(value: int) -> int:
    result = 0
    index = 0
    while value:
        if value & 1:
            result |= PBOX[index]
        value >>= 1
        index += 1
    return result


class Ice:
    """Minimal one-round ICE decoder required for the bounded path table."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 8:
            raise ValueError("ICE key must be exactly eight bytes")
        self._sbox = [[0] * 1024 for _ in range(4)]
        for index in range(1024):
            column = (index >> 1) & 0xFF
            row = (index & 1) | ((index & 0x200) >> 8)
            for box in range(4):
                self._sbox[box][index] = _perm32(
                    _gf_exp7(column ^ SXOR[box][row], SMOD[box][row])
                    << (24 - 8 * box)
                )
        key_words = [
            (key[index * 2] << 8) | key[index * 2 + 1]
            for index in range(4)
        ][::-1]
        self._schedule = self._build_schedule(key_words)

    @staticmethod
    def _build_schedule(key_words: list[int]) -> list[tuple[int, int, int]]:
        schedule: list[tuple[int, int, int]] = []
        for rotation in KEYROT[:8]:
            words = [0, 0, 0]
            for index in range(15):
                for key_index in range(4):
                    position = (rotation + key_index) & 3
                    bit = key_words[position] & 1
                    words[index % 3] = ((words[index % 3] << 1) | bit) & MASK
                    key_words[position] = (
                        (key_words[position] >> 1) | ((bit ^ 1) << 15)
                    )
            schedule.append(tuple(words))
        return schedule

    def _round(self, value: int, subkey: tuple[int, int, int]) -> int:
        left = ((value >> 16) & 0x3FF) | (
            ((value >> 14) | (value << 18)) & 0xFFC00
        )
        right = (value & 0x3FF) | ((value << 2) & 0xFFC00)
        mixed = subkey[2] & (left ^ right)
        right = mixed ^ right
        left = (mixed ^ left ^ subkey[0]) & MASK
        right = (right ^ subkey[1]) & MASK
        return (
            self._sbox[0][left >> 10]
            | self._sbox[1][left & 0x3FF]
            | self._sbox[2][right >> 10]
            | self._sbox[3][right & 0x3FF]
        )

    def decrypt(self, data: bytes) -> bytes:
        if len(data) % 8:
            raise ValueError(f"ICE input is not eight-byte aligned: {len(data)}")
        output = bytearray(len(data))
        for offset in range(0, len(data), 8):
            left, right = struct.unpack(">II", data[offset : offset + 8])
            for index in range(7, 0, -2):
                left = (
                    left ^ self._round(right, self._schedule[index])
                ) & MASK
                right = (
                    right ^ self._round(left, self._schedule[index - 1])
                ) & MASK
            output[offset : offset + 8] = struct.pack(">II", right, left)
        return bytes(output)


def archive_table_span(
    archive_size: int,
    file_count: int,
    path_length: int,
) -> tuple[int, int]:
    """Validate table sizes before allocating archive-declared data."""

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


def decode_game_path(value: bytes) -> tuple[str, str]:
    """Decode a path while reporting the legacy Korean encoding fallback."""

    try:
        return value.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        try:
            return value.decode("cp949"), "cp949"
        except UnicodeDecodeError:
            return value.decode("utf-8", "replace"), "replacement"


def validate_game_path(value: str) -> str:
    """Return a normalized relative path or reject unsafe path metadata."""

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


__all__ = [
    "Ice",
    "archive_table_span",
    "decode_game_path",
    "validate_game_path",
]
