"""Lossless decoder and deterministic encoder for BDO music score v9."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import struct
from typing import Iterable

from . import ice
from .model import (
    BDO_VERSION, HEADER_SIZE, MAX_NOTES_PER_TRACK, NAME_FIELD_SIZE,
    BdoDecodeError, BdoDocument, BdoEncodeError, BdoHeader,
    BdoInstrumentGroup, BdoNote, BdoTrack, BdoTrackSettings,
    CodecDiffEntry, CodecIssue, UnsafeOpaqueDataError,
)


TRACK_PREFIX = struct.Struct("<HH8sH")
NOTE_RECORD = struct.Struct("<BBBBdd")
VERSION_RECORD = struct.Struct("<I")
HEADER_NAMES_OFFSET = 8
HEADER_BPM_OFFSET = HEADER_NAMES_OFFSET + NAME_FIELD_SIZE * 2
HEADER_TAG_OFFSET = HEADER_BPM_OFFSET + 4


def _fail(message: str, offset: int | None = None) -> BdoDecodeError:
    return BdoDecodeError(f"{message}{f' at 0x{offset:x}' if offset is not None else ''}")


def _decode_name(raw: bytes) -> str:
    return raw.decode("utf-16-le", errors="replace").rstrip("\x00")


def _encode_name(value: str, raw: bytes | None, original: str | None) -> bytes:
    if raw is not None and original == value:
        return raw
    encoded = value[:NAME_FIELD_SIZE // 2].encode("utf-16-le")
    return encoded.ljust(NAME_FIELD_SIZE, b"\x00")[:NAME_FIELD_SIZE]


def _fingerprint(document: BdoDocument) -> bytes:
    payload = {
        "version": document.version,
        "header": {
            "owner_id": document.header.owner_id,
            "reserved": document.header.reserved.hex(),
            "names": [document.header.character_name_1, document.header.character_name_2],
            "bpm": document.header.bpm,
            "time_signature": document.header.time_signature,
            "instrument_tag": document.header.instrument_tag,
            "padding": document.header.padding.hex(),
        },
        "groups": [[{
            "instrument_id": track.instrument_id,
            "volume": track.volume,
            "settings": list(track.settings.values),
            "extra": track.extra_data.hex(),
            "notes": [list(note.values()) for note in track.notes],
        } for track in group.tracks] for group in document.groups],
        "trailing": document.trailing_data.hex(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).digest()


def decode_score(data: bytes) -> BdoDocument:
    if len(data) < 4:
        raise _fail("BDO score is shorter than the version field")
    version = VERSION_RECORD.unpack_from(data)[0]
    if version != BDO_VERSION:
        raise _fail(f"unsupported BDO score version {version}; expected {BDO_VERSION}")
    ciphertext = data[4:]
    if not ciphertext or len(ciphertext) % 8:
        raise _fail("encrypted BDO payload must be non-empty and 8-byte aligned", 4)
    plaintext = ice.decrypt(ciphertext)
    if len(plaintext) < HEADER_SIZE + 3:
        raise _fail("decrypted BDO payload is shorter than the fixed header")

    raw_name_1 = plaintext[HEADER_NAMES_OFFSET:HEADER_NAMES_OFFSET + NAME_FIELD_SIZE]
    raw_name_2 = plaintext[HEADER_NAMES_OFFSET + NAME_FIELD_SIZE:HEADER_BPM_OFFSET]
    name_1, name_2 = _decode_name(raw_name_1), _decode_name(raw_name_2)
    owner_id = struct.unpack_from("<I", plaintext, 0)[0]
    bpm, time_signature = struct.unpack_from("<HH", plaintext, HEADER_BPM_OFFSET)
    raw_tag_area = plaintext[HEADER_TAG_OFFSET:HEADER_SIZE]
    nul = raw_tag_area.find(b"\x00")
    if nul < 0:
        tag_bytes, padding = raw_tag_area, b""
    else:
        tag_bytes, padding = raw_tag_area[:nul], raw_tag_area[nul:]
    try:
        instrument_tag = tag_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _fail("instrument tag is not ASCII", HEADER_TAG_OFFSET) from exc
    header = BdoHeader(
        owner_id=owner_id,
        reserved=plaintext[4:8],
        character_name_1=name_1,
        character_name_2=name_2,
        bpm=bpm,
        time_signature=time_signature,
        instrument_tag=instrument_tag,
        padding=padding,
        _raw_name_1=raw_name_1,
        _raw_name_2=raw_name_2,
        _original_names=(name_1, name_2),
    )

    offset = HEADER_SIZE
    if plaintext[offset] != 0:
        raise _fail("unexpected instrument group marker", offset)
    offset += 1
    instrument_count = struct.unpack_from("<H", plaintext, offset)[0]
    offset += 2
    groups: list[BdoInstrumentGroup] = []
    for group_index in range(instrument_count):
        if offset + 2 > len(plaintext):
            raise _fail("instrument group track count exceeds payload", offset)
        track_count = struct.unpack_from("<H", plaintext, offset)[0]
        offset += 2
        tracks: list[BdoTrack] = []
        for track_index in range(track_count):
            track_offset = offset
            if offset + TRACK_PREFIX.size > len(plaintext):
                raise _fail("track prefix exceeds payload", offset)
            raw_prefix = plaintext[offset:offset + TRACK_PREFIX.size]
            data_size, marker, raw_settings, note_count = TRACK_PREFIX.unpack(raw_prefix)
            if data_size < 12:
                raise _fail("track data_size is smaller than its fixed body", track_offset)
            track_end = track_offset + 2 + data_size
            if track_end > len(plaintext):
                raise _fail("track data_size exceeds payload", track_offset)
            offset += TRACK_PREFIX.size
            notes: list[BdoNote] = []
            note_bytes = note_count * NOTE_RECORD.size
            if offset + note_bytes > track_end:
                raise _fail("note records exceed declared track data_size", offset)
            for note_index in range(note_count):
                note_offset = offset
                raw_record = plaintext[offset:offset + NOTE_RECORD.size]
                values = NOTE_RECORD.unpack(raw_record)
                notes.append(BdoNote(
                    *values,
                    source_offset=note_offset,
                    _raw_record=raw_record,
                    _original_values=values,
                ))
                offset += NOTE_RECORD.size
            extra_data = plaintext[offset:track_end]
            offset = track_end
            tracks.append(BdoTrack(
                instrument_id=marker & 0xFF,
                volume=(marker >> 8) & 0xFF,
                settings=BdoTrackSettings.from_bytes(raw_settings),
                notes=tuple(notes),
                declared_data_size=data_size,
                extra_data=extra_data,
                source_offset=track_offset,
                _original_note_count=note_count,
                _raw_prefix=raw_prefix,
            ))
        groups.append(BdoInstrumentGroup(tuple(tracks), source_index=group_index))
    trailing = plaintext[offset:]
    document = BdoDocument(
        version=version,
        header=header,
        groups=tuple(groups),
        trailing_data=trailing,
        source_bytes=bytes(data),
        _source_group_shape=tuple(len(group.tracks) for group in groups),
        _source_opaque_tracks=tuple(
            (f"groups[{group_index}].tracks[{track_index}].extra_data", track.source_offset or 0)
            for group_index, group in enumerate(groups)
            for track_index, track in enumerate(group.tracks)
            if any(track.extra_data)
        ),
        _trailing_offset=offset,
    )
    return BdoDocument(
        version=document.version,
        header=document.header,
        groups=document.groups,
        trailing_data=document.trailing_data,
        source_bytes=document.source_bytes,
        _source_fingerprint=_fingerprint(document),
        _source_group_shape=document._source_group_shape,
        _source_opaque_tracks=document._source_opaque_tracks,
        _trailing_offset=document._trailing_offset,
    )


def _validate_byte(value: int, path: str) -> None:
    if not 0 <= int(value) <= 255:
        raise BdoEncodeError(f"{path} must fit in one byte")


def _encode_note(note: BdoNote, path: str) -> bytes:
    if not 0 <= int(note.pitch) <= 127:
        raise BdoEncodeError(f"{path}.pitch must be in 0..127")
    if not 0 <= int(note.ntype) <= 255:
        raise BdoEncodeError(f"{path}.ntype must be in 0..255")
    if not 0 <= int(note.velocity_a) <= 127 or not 0 <= int(note.velocity_b) <= 127:
        raise BdoEncodeError(f"{path} velocities must be in 0..127")
    if note._raw_record is not None and note._original_values == note.values():
        return note._raw_record
    try:
        return NOTE_RECORD.pack(*note.values())
    except (OverflowError, struct.error) as exc:
        raise BdoEncodeError(f"{path} contains an invalid numeric value: {exc}") from exc


def build_plaintext(document: BdoDocument, *, mode: str = "canonical") -> bytes:
    if mode not in {"lossless", "canonical"}:
        raise BdoEncodeError(f"unsupported encoding mode: {mode}")
    if document.version != BDO_VERSION:
        raise BdoEncodeError(f"only BDO score version {BDO_VERSION} can be encoded")
    if len(document.header.reserved) != 4:
        raise BdoEncodeError("header.reserved must contain exactly four bytes")
    for name, value, limit in (("owner_id", document.header.owner_id, 0xFFFFFFFF),
                               ("bpm", document.header.bpm, 0xFFFF),
                               ("time_signature", document.header.time_signature, 0xFFFF)):
        if not 0 <= int(value) <= limit:
            raise BdoEncodeError(f"header.{name} is outside its unsigned integer range")

    groups = document.groups
    if mode == "canonical":
        normalized_groups: list[BdoInstrumentGroup] = []
        for group_index, group in enumerate(groups):
            if not group.tracks:
                raise BdoEncodeError(f"groups[{group_index}] has no track template")
            normalized_tracks: list[BdoTrack] = []
            for track_index, track in enumerate(group.tracks):
                if len(track.notes) <= MAX_NOTES_PER_TRACK:
                    normalized_tracks.append(track)
                    continue
                if any(track.extra_data):
                    raise UnsafeOpaqueDataError(
                        f"groups[{group_index}].tracks[{track_index}].extra_data",
                        track.source_offset or 0,
                        "track must be split while opaque data is present",
                    )
                for start in range(0, len(track.notes), MAX_NOTES_PER_TRACK):
                    normalized_tracks.append(replace(
                        track,
                        notes=track.notes[start:start + MAX_NOTES_PER_TRACK],
                        declared_data_size=0,
                        source_offset=None,
                        _original_note_count=None,
                        _raw_prefix=None,
                    ))
            if not normalized_tracks or normalized_tracks[-1].notes:
                template = normalized_tracks[-1] if normalized_tracks else group.tracks[0]
                normalized_tracks.append(BdoTrack(
                    template.instrument_id, template.volume, template.settings, (),
                ))
            normalized_groups.append(BdoInstrumentGroup(tuple(normalized_tracks), group.source_index))
        groups = tuple(normalized_groups)

    current_shape = tuple(len(group.tracks) for group in groups)
    if document._source_group_shape is not None and current_shape != document._source_group_shape:
        if document._source_opaque_tracks:
            opaque_path, opaque_offset = document._source_opaque_tracks[0]
            raise UnsafeOpaqueDataError(
                opaque_path, opaque_offset,
                "track layout changed while opaque track data is present",
            )
        for group_index, group in enumerate(document.groups):
            for track_index, track in enumerate(group.tracks):
                if any(track.extra_data):
                    raise UnsafeOpaqueDataError(
                        f"groups[{group_index}].tracks[{track_index}].extra_data",
                        track.source_offset or 0,
                        "track layout changed while opaque track data is present",
                    )

    derived_tag = ",".join(
        str(group.tracks[0].instrument_id)
        for group in groups if group.tracks
    )
    tag = document.header.instrument_tag if mode == "lossless" else derived_tag
    try:
        tag_bytes = tag.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BdoEncodeError("header.instrument_tag must be ASCII") from exc
    available_tag_bytes = HEADER_SIZE - HEADER_TAG_OFFSET
    if len(tag_bytes) > available_tag_bytes:
        raise BdoEncodeError("instrument tag does not fit in the fixed header")

    original_names = document.header._original_names or (None, None)
    output = bytearray()
    output.extend(struct.pack("<I", document.header.owner_id))
    output.extend(document.header.reserved)
    output.extend(_encode_name(document.header.character_name_1, document.header._raw_name_1, original_names[0]))
    output.extend(_encode_name(document.header.character_name_2, document.header._raw_name_2, original_names[1]))
    output.extend(struct.pack("<HH", document.header.bpm, document.header.time_signature))
    output.extend(tag_bytes)
    remaining = HEADER_SIZE - len(output)
    if len(document.header.padding) == remaining:
        output.extend(document.header.padding)
    else:
        if any(document.header.padding):
            raise UnsafeOpaqueDataError(
                "header.padding", HEADER_TAG_OFFSET + len(tag_bytes),
                "instrument tag length changed while non-zero header padding is present",
            )
        output.extend(b"\x00" * remaining)

    output.append(0)
    output.extend(struct.pack("<H", len(groups)))
    for group_index, group in enumerate(groups):
        output.extend(struct.pack("<H", len(group.tracks)))
        for track_index, track in enumerate(group.tracks):
            path = f"groups[{group_index}].tracks[{track_index}]"
            _validate_byte(track.instrument_id, f"{path}.instrument_id")
            _validate_byte(track.volume, f"{path}.volume")
            if any(track.extra_data) and track._original_note_count is not None and len(track.notes) != track._original_note_count:
                raise UnsafeOpaqueDataError(
                    f"{path}.extra_data", track.source_offset or 0,
                    "note count changed while opaque track data is present",
                )
            note_data = b"".join(_encode_note(note, f"{path}.notes[{index}]")
                                 for index, note in enumerate(track.notes))
            data_size = 12 + len(note_data) + len(track.extra_data)
            if data_size > 0xFFFF or len(track.notes) > 0xFFFF:
                raise BdoEncodeError(f"{path} exceeds the v9 uint16 track limits")
            marker = int(track.instrument_id) | (int(track.volume) << 8)
            output.extend(TRACK_PREFIX.pack(
                data_size, marker, track.settings.to_bytes(), len(track.notes)
            ))
            output.extend(note_data)
            output.extend(track.extra_data)

    modified = document._source_fingerprint is not None and document._source_fingerprint != _fingerprint(document)
    if any(document.trailing_data):
        if modified or mode == "canonical":
            raise UnsafeOpaqueDataError(
                "trailing_data", document._trailing_offset or len(output),
                "document layout may change while non-zero trailing data is present",
            )
        output.extend(document.trailing_data)
    else:
        remainder = len(output) % 8
        if remainder:
            output.extend(b"\x00" * (8 - remainder))
    if len(output) % 8:
        raise BdoEncodeError("encoded plaintext is not 8-byte aligned")
    return bytes(output)


def encode_score(document: BdoDocument, *, mode: str = "lossless") -> bytes:
    if mode == "lossless" and document.source_bytes is not None:
        if document._source_fingerprint == _fingerprint(document):
            return document.source_bytes
    plaintext = build_plaintext(document, mode=mode)
    return VERSION_RECORD.pack(BDO_VERSION) + ice.encrypt(plaintext)


def read_score(path: str | Path) -> BdoDocument:
    return decode_score(Path(path).read_bytes())


def write_score(path: str | Path, document: BdoDocument, *, mode: str = "lossless") -> None:
    Path(path).write_bytes(encode_score(document, mode=mode))


def validate_score(document: BdoDocument) -> tuple[CodecIssue, ...]:
    issues: list[CodecIssue] = []
    if document.version != BDO_VERSION:
        issues.append(CodecIssue("version.unsupported", "error", "version", f"expected {BDO_VERSION}"))
    if not document.groups:
        issues.append(CodecIssue("groups.empty", "error", "groups", "score has no instrument groups"))
    for group_index, group in enumerate(document.groups):
        if not group.tracks:
            issues.append(CodecIssue("tracks.empty", "error", f"groups[{group_index}]", "group has no tracks"))
            continue
        if group.tracks[-1].notes:
            issues.append(CodecIssue(
                "tracks.trailing_missing", "error", f"groups[{group_index}]",
                "instrument group does not end with an empty track",
            ))
        instruments = {track.instrument_id for track in group.tracks}
        if len(instruments) != 1:
            issues.append(CodecIssue(
                "tracks.instrument_mixed", "error", f"groups[{group_index}]",
                "physical tracks in one group use different instrument IDs",
            ))
        for track_index, track in enumerate(group.tracks):
            path = f"groups[{group_index}].tracks[{track_index}]"
            if len(track.notes) > MAX_NOTES_PER_TRACK:
                issues.append(CodecIssue("tracks.note_limit", "error", path, "track exceeds 730 notes"))
            if any(track.extra_data):
                issues.append(CodecIssue(
                    "tracks.opaque_data", "warning", f"{path}.extra_data",
                    f"track contains {len(track.extra_data)} opaque bytes", track.source_offset,
                ))
            for note_index, note in enumerate(track.notes):
                note_path = f"{path}.notes[{note_index}]"
                if not 0 <= note.pitch <= 127:
                    issues.append(CodecIssue("notes.pitch", "error", note_path, "pitch is outside MIDI range", note.source_offset))
                if not 0 <= note.ntype <= 255:
                    issues.append(CodecIssue("notes.ntype", "error", note_path, "ntype does not fit in one byte", note.source_offset))
                if not 0 <= note.velocity_a <= 127 or not 0 <= note.velocity_b <= 127:
                    issues.append(CodecIssue("notes.velocity", "error", note_path, "velocity is outside game range", note.source_offset))
    if any(document.trailing_data):
        issues.append(CodecIssue(
            "payload.trailing_opaque", "warning", "trailing_data",
            f"payload contains {len(document.trailing_data)} non-zero trailing bytes",
        ))
    if any(document.header.reserved):
        issues.append(CodecIssue(
            "header.reserved_nonzero", "warning", "header.reserved",
            "reserved header bytes are non-zero",
        ))
    if any(document.header.padding):
        issues.append(CodecIssue(
            "header.padding_opaque", "warning", "header.padding",
            "header padding contains non-zero bytes",
        ))
    derived_tag = ",".join(str(group.tracks[0].instrument_id) for group in document.groups if group.tracks)
    if document.header.instrument_tag != derived_tag:
        issues.append(CodecIssue(
            "header.instrument_tag_mismatch", "warning", "header.instrument_tag",
            f"stored tag {document.header.instrument_tag!r} differs from groups {derived_tag!r}",
        ))
    return tuple(issues)


def compare_score_documents(left: BdoDocument, right: BdoDocument) -> tuple[CodecDiffEntry, ...]:
    differences: list[CodecDiffEntry] = []
    fields: list[tuple[str, object, object]] = [
        ("version", left.version, right.version),
        ("header.owner_id", left.header.owner_id, right.header.owner_id),
        ("header.reserved", left.header.reserved, right.header.reserved),
        ("header.character_name_1", left.header.character_name_1, right.header.character_name_1),
        ("header.character_name_2", left.header.character_name_2, right.header.character_name_2),
        ("header.bpm", left.header.bpm, right.header.bpm),
        ("header.time_signature", left.header.time_signature, right.header.time_signature),
        ("header.instrument_tag", left.header.instrument_tag, right.header.instrument_tag),
        ("header.padding", left.header.padding, right.header.padding),
        ("trailing_data", left.trailing_data, right.trailing_data),
        ("groups.length", len(left.groups), len(right.groups)),
    ]
    for group_index, (left_group, right_group) in enumerate(zip(left.groups, right.groups)):
        group_path = f"groups[{group_index}]"
        fields.append((f"{group_path}.tracks.length", len(left_group.tracks), len(right_group.tracks)))
        for track_index, (left_track, right_track) in enumerate(zip(left_group.tracks, right_group.tracks)):
            track_path = f"{group_path}.tracks[{track_index}]"
            fields.extend((
                (f"{track_path}.instrument_id", left_track.instrument_id, right_track.instrument_id),
                (f"{track_path}.volume", left_track.volume, right_track.volume),
                (f"{track_path}.settings", left_track.settings.values, right_track.settings.values),
                (f"{track_path}.declared_data_size", left_track.declared_data_size, right_track.declared_data_size),
                (f"{track_path}.extra_data", left_track.extra_data, right_track.extra_data),
                (f"{track_path}.notes.length", len(left_track.notes), len(right_track.notes)),
            ))
            for note_index, (left_note, right_note) in enumerate(zip(left_track.notes, right_track.notes)):
                fields.append((
                    f"{track_path}.notes[{note_index}]",
                    left_note.values(), right_note.values(),
                ))
    for path, expected, actual in fields:
        if expected != actual:
            differences.append(CodecDiffEntry(path, expected, actual))
    return tuple(differences)


def document_to_dict(document: BdoDocument, *, include_private: bool = True) -> dict:
    header = {
        "owner_id": document.header.owner_id if include_private else None,
        "reserved_hex": document.header.reserved.hex(),
        "character_name_1": document.header.character_name_1 if include_private else "<redacted>",
        "character_name_2": document.header.character_name_2 if include_private else "<redacted>",
        "bpm": document.header.bpm,
        "time_signature": document.header.time_signature,
        "instrument_tag": document.header.instrument_tag,
        "padding_hex": document.header.padding.hex(),
    }
    return {
        "schema": "bdo-score-document/v1",
        "version": document.version,
        "header": header,
        "groups": [{"tracks": [{
            "instrument_id": track.instrument_id,
            "volume": track.volume,
            "settings": list(track.settings.values),
            "declared_data_size": track.declared_data_size,
            "extra_data_hex": track.extra_data.hex(),
            "notes": [{
                "pitch": note.pitch, "ntype": note.ntype,
                "velocity_a": note.velocity_a, "velocity_b": note.velocity_b,
                "start_ms": note.start_ms, "duration_ms": note.duration_ms,
            } for note in track.notes],
        } for track in group.tracks]} for group in document.groups],
        "trailing_data_hex": document.trailing_data.hex(),
    }


def document_from_dict(payload: dict) -> BdoDocument:
    if payload.get("schema") != "bdo-score-document/v1":
        raise BdoDecodeError("unsupported JSON score document schema")
    raw_header = dict(payload["header"])
    if raw_header.get("owner_id") is None or str(raw_header.get("character_name_1", "")).startswith("<redacted>"):
        raise BdoDecodeError("redacted inspect JSON cannot be encoded; use the decode command")
    header = BdoHeader(
        owner_id=int(raw_header["owner_id"]),
        reserved=bytes.fromhex(str(raw_header.get("reserved_hex", "00000000"))),
        character_name_1=str(raw_header.get("character_name_1", "")),
        character_name_2=str(raw_header.get("character_name_2", "")),
        bpm=int(raw_header["bpm"]),
        time_signature=int(raw_header["time_signature"]),
        instrument_tag=str(raw_header.get("instrument_tag", "")),
        padding=bytes.fromhex(str(raw_header.get("padding_hex", ""))),
    )
    groups = []
    for group_index, raw_group in enumerate(payload.get("groups", [])):
        tracks = []
        for raw_track in raw_group.get("tracks", []):
            notes = tuple(BdoNote(
                int(item["pitch"]), int(item["ntype"]),
                int(item["velocity_a"]), int(item["velocity_b"]),
                float(item["start_ms"]), float(item["duration_ms"]),
            ) for item in raw_track.get("notes", []))
            tracks.append(BdoTrack(
                instrument_id=int(raw_track["instrument_id"]),
                volume=int(raw_track["volume"]),
                settings=BdoTrackSettings(tuple(int(value) for value in raw_track.get("settings", (0,) * 8))),
                notes=notes,
                declared_data_size=int(raw_track.get("declared_data_size", 0)),
                extra_data=bytes.fromhex(str(raw_track.get("extra_data_hex", ""))),
            ))
        groups.append(BdoInstrumentGroup(tuple(tracks), source_index=group_index))
    return BdoDocument(
        version=int(payload.get("version", BDO_VERSION)),
        header=header,
        groups=tuple(groups),
        trailing_data=bytes.fromhex(str(payload.get("trailing_data_hex", ""))),
    )


__all__ = [
    "TRACK_PREFIX", "NOTE_RECORD", "decode_score", "encode_score", "build_plaintext",
    "read_score", "write_score", "validate_score", "compare_score_documents",
    "document_to_dict", "document_from_dict",
]
