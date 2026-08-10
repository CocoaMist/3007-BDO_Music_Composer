"""Typed, lossless data model for Black Desert music score v9 files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


BDO_VERSION = 9
HEADER_SIZE = 0x150
NAME_FIELD_SIZE = 62
MAX_NOTES_PER_TRACK = 730


class BdoCodecError(ValueError):
    """Base class for deterministic codec failures."""


class BdoDecodeError(BdoCodecError):
    """The input cannot be safely decoded as a BDO v9 score."""


class BdoEncodeError(BdoCodecError):
    """The document cannot be safely encoded as a BDO v9 score."""


class UnsafeOpaqueDataError(BdoEncodeError):
    """A structural edit would detach unknown bytes from their source record."""

    def __init__(self, path: str, offset: int, message: str) -> None:
        self.path = path
        self.offset = offset
        super().__init__(f"{path} at 0x{offset:x}: {message}")


@dataclass(frozen=True, slots=True)
class BdoTrackSettings:
    values: tuple[int, ...] = (0,) * 8

    def __post_init__(self) -> None:
        if len(self.values) != 8 or any(not 0 <= int(value) <= 255 for value in self.values):
            raise BdoCodecError("track settings must contain exactly eight bytes")

    @classmethod
    def from_bytes(cls, data: bytes) -> "BdoTrackSettings":
        return cls(tuple(data))

    def to_bytes(self) -> bytes:
        return bytes(self.values)

    def __iter__(self):
        return iter(self.values)


@dataclass(frozen=True, slots=True)
class BdoNote:
    pitch: int
    ntype: int
    velocity_a: int
    velocity_b: int
    start_ms: float
    duration_ms: float
    source_offset: int | None = field(default=None, compare=False, repr=False)
    _raw_record: bytes | None = field(default=None, compare=False, repr=False)
    _original_values: tuple[Any, ...] | None = field(default=None, compare=False, repr=False)

    def values(self) -> tuple[Any, ...]:
        return (
            self.pitch, self.ntype, self.velocity_a, self.velocity_b,
            self.start_ms, self.duration_ms,
        )


@dataclass(frozen=True, slots=True)
class BdoTrack:
    instrument_id: int
    volume: int
    settings: BdoTrackSettings
    notes: tuple[BdoNote, ...]
    declared_data_size: int = 0
    extra_data: bytes = b""
    source_offset: int | None = field(default=None, compare=False)
    _original_note_count: int | None = field(default=None, compare=False, repr=False)
    _raw_prefix: bytes | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class BdoInstrumentGroup:
    tracks: tuple[BdoTrack, ...]
    source_index: int | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class BdoHeader:
    owner_id: int
    reserved: bytes
    character_name_1: str
    character_name_2: str
    bpm: int
    time_signature: int
    instrument_tag: str
    padding: bytes = b""
    _raw_name_1: bytes | None = field(default=None, compare=False, repr=False)
    _raw_name_2: bytes | None = field(default=None, compare=False, repr=False)
    _original_names: tuple[str, str] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class BdoDocument:
    version: int
    header: BdoHeader
    groups: tuple[BdoInstrumentGroup, ...]
    trailing_data: bytes = b""
    source_bytes: bytes | None = field(default=None, compare=False, repr=False)
    _source_fingerprint: bytes | None = field(default=None, compare=False, repr=False)
    _source_group_shape: tuple[int, ...] | None = field(default=None, compare=False, repr=False)
    _source_opaque_tracks: tuple[tuple[str, int], ...] = field(default=(), compare=False, repr=False)
    _trailing_offset: int | None = field(default=None, compare=False, repr=False)

    @property
    def total_notes(self) -> int:
        return sum(len(track.notes) for group in self.groups for track in group.tracks)


@dataclass(frozen=True, slots=True)
class CodecIssue:
    code: str
    severity: str
    path: str
    message: str
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class CodecDiffEntry:
    path: str
    expected: object
    actual: object


__all__ = [
    "BDO_VERSION", "HEADER_SIZE", "NAME_FIELD_SIZE", "MAX_NOTES_PER_TRACK",
    "BdoCodecError", "BdoDecodeError", "BdoEncodeError", "UnsafeOpaqueDataError",
    "BdoTrackSettings", "BdoNote", "BdoTrack", "BdoInstrumentGroup", "BdoHeader",
    "BdoDocument", "CodecIssue", "CodecDiffEntry",
]
