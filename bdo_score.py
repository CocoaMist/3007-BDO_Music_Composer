"""Reusable BDO v9 score snapshots and deterministic structural diffs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import sys
from typing import Sequence


if not getattr(sys, "frozen", False):
    tool_dir = Path(__file__).resolve().parent / "tools" / "midi-to-bdo"
    if str(tool_dir) not in sys.path:
        sys.path.insert(0, str(tool_dir))

import _ice  # noqa: E402
from midi2bdo import BDO_VERSION, HEADER_SIZE, NAME_FIELD_SIZE  # noqa: E402


TRACK_HEADER = struct.Struct("<HH8sH")
NOTE_RECORD = struct.Struct("<BBBBdd")
TIME_TOLERANCE_MS = 0.001


@dataclass(frozen=True, slots=True)
class BdoNoteSnapshot:
    pitch: int
    ntype: int
    velocity_a: int
    velocity_b: int
    start_ms: float
    duration_ms: float


@dataclass(frozen=True, slots=True)
class BdoTrackSnapshot:
    group_index: int
    track_index: int
    instrument_id: int
    volume: int
    data_size: int
    settings: tuple[int, ...]
    notes: tuple[BdoNoteSnapshot, ...]


@dataclass(frozen=True, slots=True)
class BdoScoreSnapshot:
    version: int
    owner_id: int
    character_name_1: str
    character_name_2: str
    bpm: int
    time_signature: int
    instrument_tag: str
    instrument_count: int
    tracks: tuple[BdoTrackSnapshot, ...]
    payload_size: int
    parsed_bytes: int
    trailing_zero_bytes: int

    @property
    def total_notes(self) -> int:
        return sum(len(track.notes) for track in self.tracks)


@dataclass(frozen=True, slots=True)
class ScoreDiffEntry:
    path: str
    expected: object
    actual: object
    message: str


@dataclass(frozen=True, slots=True)
class ScoreDiff:
    differences: tuple[ScoreDiffEntry, ...]
    time_tolerance_ms: float = TIME_TOLERANCE_MS

    @property
    def identical(self) -> bool:
        return not self.differences

    def summary(self) -> str:
        if self.identical:
            return f"谱面结构与音符一致（时间容差 {self.time_tolerance_ms:g} ms）。"
        lines = [f"发现 {len(self.differences)} 项差异："]
        lines.extend(
            f"- {item.path}: {item.message} ({item.expected!r} -> {item.actual!r})"
            for item in self.differences
        )
        return "\n".join(lines)


def _decode_name(data: bytes) -> str:
    return data.decode("utf-16-le", errors="replace").rstrip("\x00")


def snapshot_from_bytes(data: bytes) -> BdoScoreSnapshot:
    if len(data) < 4:
        raise ValueError("BDO score is too small")
    version = struct.unpack_from("<I", data, 0)[0]
    if version != BDO_VERSION:
        raise ValueError(f"unsupported BDO version {version}; expected {BDO_VERSION}")
    plaintext = _ice.decrypt(data[4:])
    if len(plaintext) < HEADER_SIZE:
        raise ValueError("decrypted BDO payload is shorter than the fixed header")
    owner_id = struct.unpack_from("<I", plaintext, 0)[0]
    name_a_start = 8
    name_b_start = name_a_start + NAME_FIELD_SIZE
    bpm_offset = name_b_start + NAME_FIELD_SIZE
    bpm, time_signature = struct.unpack_from("<HH", plaintext, bpm_offset)
    instrument_tag = plaintext[bpm_offset + 4:HEADER_SIZE].split(b"\x00", 1)[0].decode(
        "ascii", errors="replace"
    )
    offset = HEADER_SIZE
    if offset >= len(plaintext) or plaintext[offset] != 0:
        raise ValueError(f"unexpected BDO group marker at 0x{offset:x}")
    offset += 1
    instrument_count = struct.unpack_from("<H", plaintext, offset)[0]
    offset += 2
    tracks: list[BdoTrackSnapshot] = []
    for group_index in range(instrument_count):
        if offset + 2 > len(plaintext):
            raise ValueError("BDO instrument group exceeds payload")
        track_count = struct.unpack_from("<H", plaintext, offset)[0]
        offset += 2
        for track_index in range(track_count):
            track_start = offset
            if offset + TRACK_HEADER.size > len(plaintext):
                raise ValueError(f"BDO track header exceeds payload at 0x{offset:x}")
            data_size, marker, settings, note_count = TRACK_HEADER.unpack_from(plaintext, offset)
            offset += TRACK_HEADER.size
            note_bytes = note_count * NOTE_RECORD.size
            if offset + note_bytes > len(plaintext):
                raise ValueError(f"BDO notes exceed payload at 0x{offset:x}")
            notes = []
            for _note_index in range(note_count):
                pitch, ntype, velocity_a, velocity_b, start_ms, duration_ms = NOTE_RECORD.unpack_from(
                    plaintext, offset
                )
                offset += NOTE_RECORD.size
                notes.append(BdoNoteSnapshot(
                    pitch, ntype, velocity_a, velocity_b, start_ms, duration_ms
                ))
            consumed = offset - track_start - 2
            if consumed > data_size:
                raise ValueError("BDO track data exceeds declared data_size")
            offset += data_size - consumed
            tracks.append(BdoTrackSnapshot(
                group_index,
                track_index,
                marker & 0xFF,
                (marker >> 8) & 0xFF,
                data_size,
                tuple(settings),
                tuple(notes),
            ))
    trailing = plaintext[offset:]
    if any(trailing):
        raise ValueError("BDO payload contains non-zero trailing data")
    return BdoScoreSnapshot(
        version,
        owner_id,
        _decode_name(plaintext[name_a_start:name_b_start]),
        _decode_name(plaintext[name_b_start:bpm_offset]),
        bpm,
        time_signature,
        instrument_tag,
        instrument_count,
        tuple(tracks),
        len(plaintext),
        offset,
        len(trailing),
    )


def read_bdo_score(path: Path) -> BdoScoreSnapshot:
    return snapshot_from_bytes(path.read_bytes())


def _append(differences: list[ScoreDiffEntry], path: str, expected: object,
            actual: object, message: str) -> None:
    if expected != actual:
        differences.append(ScoreDiffEntry(path, expected, actual, message))


def compare_scores(
    expected: BdoScoreSnapshot,
    actual: BdoScoreSnapshot,
    *,
    time_tolerance_ms: float = TIME_TOLERANCE_MS,
    compare_private_fields: bool = False,
) -> ScoreDiff:
    differences: list[ScoreDiffEntry] = []
    for field_name in ("version", "bpm", "time_signature", "instrument_tag", "instrument_count"):
        _append(differences, field_name, getattr(expected, field_name), getattr(actual, field_name), "字段不同")
    if compare_private_fields:
        for field_name in ("owner_id", "character_name_1", "character_name_2"):
            _append(differences, field_name, getattr(expected, field_name), getattr(actual, field_name), "私有字段不同")
    _append(differences, "tracks.length", len(expected.tracks), len(actual.tracks), "轨道数量不同")
    expected_order = tuple(track.instrument_id for track in expected.tracks)
    actual_order = tuple(track.instrument_id for track in actual.tracks)
    _append(differences, "tracks.instrument_order", expected_order, actual_order, "乐器轨道顺序不同")

    def keyed(tracks: Sequence[BdoTrackSnapshot]) -> dict[tuple[int, int], BdoTrackSnapshot]:
        counts: dict[int, int] = {}
        result = {}
        for track in tracks:
            ordinal = counts.get(track.instrument_id, 0)
            counts[track.instrument_id] = ordinal + 1
            result[(track.instrument_id, ordinal)] = track
        return result

    left_tracks = keyed(expected.tracks)
    right_tracks = keyed(actual.tracks)
    for key in sorted(set(left_tracks) | set(right_tracks)):
        left = left_tracks.get(key)
        right = right_tracks.get(key)
        prefix = f"tracks[0x{key[0]:02X}#{key[1] + 1}]"
        if left is None or right is None:
            differences.append(ScoreDiffEntry(prefix, left is not None, right is not None, "轨道缺失"))
            continue
        for field_name in ("group_index", "track_index", "instrument_id", "volume", "settings"):
            _append(differences, f"{prefix}.{field_name}", getattr(left, field_name), getattr(right, field_name), "轨道字段不同")
        _append(differences, f"{prefix}.notes.length", len(left.notes), len(right.notes), "音符数量不同")
        for note_index, (left_note, right_note) in enumerate(zip(left.notes, right.notes)):
            note_prefix = f"{prefix}.notes[{note_index}]"
            for field_name in ("pitch", "ntype", "velocity_a", "velocity_b"):
                _append(
                    differences, f"{note_prefix}.{field_name}",
                    getattr(left_note, field_name), getattr(right_note, field_name), "音符字段不同",
                )
            for field_name in ("start_ms", "duration_ms"):
                left_value = getattr(left_note, field_name)
                right_value = getattr(right_note, field_name)
                if abs(left_value - right_value) > time_tolerance_ms:
                    differences.append(ScoreDiffEntry(
                        f"{note_prefix}.{field_name}", left_value, right_value,
                        f"时间差超过 {time_tolerance_ms:g} ms",
                    ))
    return ScoreDiff(tuple(differences), time_tolerance_ms)


__all__ = [
    "BdoNoteSnapshot", "BdoScoreSnapshot", "BdoTrackSnapshot", "ScoreDiff",
    "ScoreDiffEntry", "TIME_TOLERANCE_MS", "compare_scores", "read_bdo_score",
    "snapshot_from_bytes",
]
