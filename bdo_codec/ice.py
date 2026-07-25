"""Independent ICE level-0 block cipher used by BDO music score v9."""

from __future__ import annotations

from .model import BdoCodecError


_KEY = bytes(left ^ right for left, right in zip(
    bytes.fromhex("a3718f9246b2c855"),
    bytes.fromhex("f28280834296a255"),
))
_MODULI = ((333, 313, 505, 369), (379, 375, 319, 391),
           (361, 445, 451, 397), (397, 425, 395, 505))
_XORS = ((0x83, 0x85, 0x9B, 0xCD), (0xCC, 0xA7, 0xAD, 0x41),
         (0x4B, 0x2E, 0xD4, 0x33), (0xEA, 0xCB, 0x2E, 0x04))
_PERMUTATION = (
    0x00000001, 0x00000080, 0x00000400, 0x00002000, 0x00080000, 0x00200000, 0x01000000, 0x40000000,
    0x00000008, 0x00000020, 0x00000100, 0x00004000, 0x00010000, 0x00800000, 0x04000000, 0x20000000,
    0x00000004, 0x00000010, 0x00000200, 0x00008000, 0x00020000, 0x00400000, 0x08000000, 0x10000000,
    0x00000002, 0x00000040, 0x00000800, 0x00001000, 0x00040000, 0x00100000, 0x02000000, 0x80000000,
)
_ROTATION = (0, 1, 2, 3, 2, 1, 3, 0)


def _gf_multiply(left: int, right: int, modulus: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        left <<= 1
        right >>= 1
        if left & 0x100:
            left ^= modulus
    return result


def _gf_power_seven(value: int, modulus: int) -> int:
    if not value:
        return 0
    square = _gf_multiply(value, value, modulus)
    cube = _gf_multiply(value, square, modulus)
    sixth = _gf_multiply(cube, cube, modulus)
    return _gf_multiply(value, sixth, modulus)


def _permute(value: int) -> int:
    output = 0
    bit = 0
    while value:
        if value & 1:
            output |= _PERMUTATION[bit]
        bit += 1
        value >>= 1
    return output


def _make_sboxes() -> tuple[tuple[int, ...], ...]:
    boxes: list[tuple[int, ...]] = []
    shifts = (24, 16, 8, 0)
    for box_index, shift in enumerate(shifts):
        entries = []
        for value in range(1024):
            column = (value >> 1) & 0xFF
            row = (value & 1) | ((value >> 8) & 2)
            transformed = _gf_power_seven(column ^ _XORS[box_index][row], _MODULI[box_index][row])
            entries.append(_permute(transformed << shift))
        boxes.append(tuple(entries))
    return tuple(boxes)


def _make_schedule() -> tuple[tuple[int, int, int], ...]:
    words = [0] * 4
    for index in range(4):
        words[3 - index] = int.from_bytes(_KEY[index * 2:index * 2 + 2], "big")
    schedule: list[tuple[int, int, int]] = []
    for rotation in _ROTATION:
        row = [0, 0, 0]
        for bit_index in range(15):
            for word_index in range(4):
                selected = (rotation + word_index) & 3
                bit = words[selected] & 1
                slot = bit_index % 3
                row[slot] = (row[slot] << 1) | bit
                words[selected] = (words[selected] >> 1) | ((bit ^ 1) << 15)
        schedule.append(tuple(row))
    return tuple(schedule)


_SBOXES = _make_sboxes()
_SCHEDULE = _make_schedule()


def _round_function(value: int, subkey: tuple[int, int, int]) -> int:
    left = ((value >> 16) & 0x3FF) | (((value >> 14) | (value << 18)) & 0xFFC00)
    right = (value & 0x3FF) | ((value << 2) & 0xFFC00)
    mixed = subkey[2] & (left ^ right)
    right_index = mixed ^ right ^ subkey[1]
    left_index = mixed ^ left ^ subkey[0]
    return (_SBOXES[0][left_index >> 10] | _SBOXES[1][left_index & 0x3FF]
            | _SBOXES[2][right_index >> 10] | _SBOXES[3][right_index & 0x3FF])


def _crypt_block(block: bytes, *, decrypting: bool) -> bytes:
    left = int.from_bytes(block[:4], "big")
    right = int.from_bytes(block[4:], "big")
    pairs = range(7, 0, -2) if decrypting else range(0, 8, 2)
    for index in pairs:
        if decrypting:
            left ^= _round_function(right, _SCHEDULE[index])
            right ^= _round_function(left, _SCHEDULE[index - 1])
        else:
            left ^= _round_function(right, _SCHEDULE[index])
            right ^= _round_function(left, _SCHEDULE[index + 1])
    return right.to_bytes(4, "big") + left.to_bytes(4, "big")


def _crypt(data: bytes, *, decrypting: bool) -> bytes:
    if len(data) % 8:
        raise BdoCodecError("ICE payload length must be an exact multiple of 8 bytes")
    return b"".join(
        _crypt_block(data[offset:offset + 8], decrypting=decrypting)
        for offset in range(0, len(data), 8)
    )


def encrypt(data: bytes) -> bytes:
    return _crypt(data, decrypting=False)


def decrypt(data: bytes) -> bytes:
    return _crypt(data, decrypting=True)


__all__ = ["encrypt", "decrypt"]
