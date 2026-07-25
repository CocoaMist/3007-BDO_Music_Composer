"""Reusable BDO v9 score snapshots and deterministic structural diffs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bdo_codec import (  # noqa: E402
    BDO_VERSION,
    BdoDocument,
    compare_score_documents,
    decode_score,
    encode_score,
    read_score,
    validate_score,
    write_score,
)
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


def snapshot_from_bytes(data: bytes, *, allow_trailing_data: bool = False) -> BdoScoreSnapshot:
    document = decode_score(data)
    if any(document.trailing_data) and not allow_trailing_data:
        raise ValueError("BDO payload contains non-zero trailing data")
    tracks: list[BdoTrackSnapshot] = []
    for group_index, group in enumerate(document.groups):
        for track_index, track in enumerate(group.tracks):
            tracks.append(BdoTrackSnapshot(
                group_index,
                track_index,
                track.instrument_id,
                track.volume,
                track.declared_data_size,
                tuple(track.settings.values),
                tuple(BdoNoteSnapshot(
                    note.pitch, note.ntype, note.velocity_a, note.velocity_b,
                    note.start_ms, note.duration_ms,
                ) for note in track.notes),
            ))
    return BdoScoreSnapshot(
        document.version,
        document.header.owner_id,
        document.header.character_name_1,
        document.header.character_name_2,
        document.header.bpm,
        document.header.time_signature,
        document.header.instrument_tag,
        len(document.groups),
        tuple(tracks),
        len(data) - 4,
        len(data) - 4 - len(document.trailing_data),
        len(document.trailing_data),
    )


def read_bdo_score(path: Path, *, allow_trailing_data: bool = False) -> BdoScoreSnapshot:
    return snapshot_from_bytes(path.read_bytes(), allow_trailing_data=allow_trailing_data)


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
    "snapshot_from_bytes", "BdoDocument", "compare_score_documents", "decode_score",
    "encode_score", "read_score", "validate_score", "write_score",
]
