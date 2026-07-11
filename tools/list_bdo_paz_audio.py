"""List audio-like entries in Black Desert PAZ archives without extracting data."""
from __future__ import annotations

import argparse
import struct
from pathlib import Path


SMOD = ((333, 313, 505, 369), (379, 375, 319, 391), (361, 445, 451, 397), (397, 425, 395, 505))
SXOR = ((0x83, 0x85, 0x9B, 0xCD), (0xCC, 0xA7, 0xAD, 0x41), (0x4B, 0x2E, 0xD4, 0x33), (0xEA, 0xCB, 0x2E, 0x04))
PBOX = (0x00000001, 0x00000080, 0x00000400, 0x00002000, 0x00080000, 0x00200000, 0x01000000, 0x40000000,
        0x00000008, 0x00000020, 0x00000100, 0x00004000, 0x00010000, 0x00800000, 0x04000000, 0x20000000,
        0x00000004, 0x00000010, 0x00000100 >> 1, 0x00008000, 0x00020000, 0x00400000, 0x08000000, 0x10000000,
        0x00000002, 0x00000040, 0x00000800, 0x00001000, 0x00040000, 0x00100000, 0x02000000, 0x80000000)
# Corrected from source's third PBOX group (index 18 is 0x00000100, not a shifted value).
PBOX = PBOX[:18] + (0x00000100,) + PBOX[19:]
KEYROT = (0, 1, 2, 3, 2, 1, 3, 0, 1, 3, 2, 0, 3, 1, 0, 2)
MASK = 0xFFFFFFFF


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paz_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    meta = args.paz_dir / "pad00000.meta"
    version, count = struct.unpack("<II", meta.read_bytes()[:8])
    tables = struct.iter_unpack("<III", meta.read_bytes()[8:8 + count * 12])
    ice = Ice(bytes.fromhex("51 F3 0F 11 04 24 6A 00"))
    extensions = (".wem", ".wav", ".ogg", ".mp3", ".fsb", ".bnk", ".acb", ".hca", ".awb", ".wma")
    found: list[str] = []
    for number, _crc, _size in tables:
        archive = args.paz_dir / f"PAD{number:05}.PAZ"
        if not archive.exists():
            continue
        with archive.open("rb") as stream:
            _crc, file_count, path_length = struct.unpack("<III", stream.read(12))
            infos = [struct.unpack("<IIIIII", stream.read(24)) for _ in range(file_count)]
            encrypted_paths = stream.read(path_length)
        paths = ice.decrypt(encrypted_paths).split(b"\0")
        for _crc, folder_id, file_id, offset, packed_size, original_size in infos:
            if folder_id >= len(paths) or file_id >= len(paths):
                continue
            name = (paths[folder_id] + paths[file_id]).decode("utf-8", "replace")
            if name.lower().endswith(extensions):
                found.append(f"{number}\t{offset}\t{packed_size}\t{original_size}\t{name}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("paz\toffset\tpacked_size\toriginal_size\tpath\n" + "\n".join(found) + "\n", encoding="utf-8")
    print(f"PAZ meta version: {version}; archives: {count}; audio-like entries: {len(found)}")
    print(args.output)


if __name__ == "__main__":
    main()
