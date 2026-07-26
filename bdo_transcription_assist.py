"""Lightweight, Qt-free review sidecar for transcription assistance.

The automatic harmony, voice grouping, and timbre analyses are disposable
cache products.  This module persists only human decisions and stable
identifiers needed to reconcile those decisions with a later analysis.

All stored times use the original reference-audio timeline.  Project offset
projection belongs to the editor boundary and must never be applied here.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Callable, Iterable, Mapping, Sequence


ASSIST_REVIEW_PAYLOAD_VERSION = 1
_MAX_TOKEN_LENGTH = 160
_MAX_REVIEW_ITEMS = 4_096
_MAX_CANDIDATE_IDS_PER_ITEM = 2_048
_MAX_RECOVERY_CANDIDATES = 100_000

_KEY_MODES = frozenset({"major", "minor"})
_CHORD_QUALITIES = frozenset(
    {
        "major",
        "minor",
        "dim",
        "sus2",
        "sus4",
        "maj7",
        "7",
        "min7",
        "half_diminished7",
        "N",
    }
)
_VOICE_ROLES = frozenset(
    {
        "primary_melody",
        "secondary_melody",
        "harmony",
        "bass",
        "rhythm",
        "percussion",
        "pad",
        "ornament",
        "fx",
    }
)
_ROLE_ALIASES = {
    "melody": "primary_melody",
    "primary": "primary_melody",
    "secondary": "secondary_melody",
    "accompaniment": "harmony",
    "chord": "harmony",
    "drum": "percussion",
    "drums": "percussion",
    "effect": "fx",
}


def _safe_token(value: object, *, allow_empty: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return "" if allow_empty else None
    if len(token) > _MAX_TOKEN_LENGTH:
        return None
    if any(ord(character) < 32 for character in token):
        return None
    return token


def _audio_fingerprint(value: object) -> str:
    """Accept content identities, never file locations.

    Production fingerprints are SHA-256 hex strings.  Short opaque identities
    remain accepted for tests and third-party backends, while path-shaped
    values fail closed so a project cannot accidentally persist a private
    local source path in this sidecar.
    """

    token = _safe_token(value, allow_empty=True)
    if token is None:
        return ""
    if any(separator in token for separator in ("/", "\\", ":")):
        return ""
    return token


def _pitch_class(value: object, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError("pitch class must be an integer from 0 through 11")
    try:
        pitch_class = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("pitch class must be an integer from 0 through 11") from exc
    if pitch_class < 0 or pitch_class > 11:
        raise ValueError("pitch class must be an integer from 0 through 11")
    return pitch_class


def _finite_time(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _time_range(start_value: object, end_value: object) -> tuple[float, float]:
    start_ms = _finite_time(start_value, "start_audio_ms")
    end_ms = _finite_time(end_value, "end_audio_ms")
    if start_ms < 0.0 or end_ms <= start_ms:
        raise ValueError("review time range must be non-empty and non-negative")
    return start_ms, end_ms


def _normalise_candidate_ids(values: Iterable[object]) -> tuple[str, ...]:
    identifiers: set[str] = set()
    for value in values:
        if len(identifiers) >= _MAX_CANDIDATE_IDS_PER_ITEM:
            break
        identifier = _safe_token(value)
        if identifier is not None:
            identifiers.add(identifier)
    return tuple(sorted(identifiers))


def _normalise_role(value: object) -> str:
    role = str(value or "harmony").strip().casefold()
    role = _ROLE_ALIASES.get(role, role)
    return role if role in _VOICE_ROLES else "harmony"


def _instrument_id(value: object, *, allow_none: bool = True) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError("instrument id must be a non-negative integer")
    try:
        identifier = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("instrument id must be a non-negative integer") from exc
    if identifier < 0:
        raise ValueError("instrument id must be a non-negative integer")
    return identifier


def stable_assist_review_id(kind: str, *parts: object) -> str:
    """Return a deterministic, content-derived ID without exposing source data."""

    safe_kind = _safe_token(kind) or "review"
    encoded = json.dumps(
        parts,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"{safe_kind}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class KeyReviewOverride:
    """One human-selected global key.

    ``manual`` distinguishes a typed edit from a selected automatic
    alternative.  Either a manual or locked decision is protected from normal
    re-analysis.  ``orphaned`` makes the value displayable but ineligible for
    automatic application.
    """

    root_pc: int
    mode: str
    manual: bool = True
    locked: bool = True
    orphaned: bool = False

    def __post_init__(self) -> None:
        root_pc = _pitch_class(self.root_pc)
        mode = str(self.mode).strip().casefold()
        if mode not in _KEY_MODES:
            raise ValueError(f"unsupported key mode: {mode}")
        object.__setattr__(self, "root_pc", root_pc)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "manual", bool(self.manual))
        object.__setattr__(self, "locked", bool(self.locked))
        object.__setattr__(self, "orphaned", bool(self.orphaned))

    @property
    def protected(self) -> bool:
        return self.manual or self.locked

    @property
    def active(self) -> bool:
        return self.protected and not self.orphaned

    def to_payload(self) -> dict[str, object]:
        return {
            "root_pc": self.root_pc,
            "mode": self.mode,
            "manual": self.manual,
            "locked": self.locked,
            "orphaned": self.orphaned,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "KeyReviewOverride | None":
        if not isinstance(payload, Mapping):
            return None
        try:
            return cls(
                root_pc=payload.get("root_pc"),
                mode=str(payload.get("mode") or ""),
                manual=bool(payload.get("manual", True)),
                locked=bool(payload.get("locked", True)),
                orphaned=bool(payload.get("orphaned", False)),
            )
        except (TypeError, ValueError, OverflowError):
            return None


@dataclass(frozen=True, slots=True)
class LockedChordReview:
    """Human chord semantics anchored to a disposable automatic segment."""

    review_id: str
    segment_id: str
    start_audio_ms: float
    end_audio_ms: float
    root_pc: int | None
    quality: str
    bass_pc: int | None = None
    candidate_ids: tuple[str, ...] = ()
    manual: bool = True
    locked: bool = True
    orphaned: bool = False

    def __post_init__(self) -> None:
        quality = str(self.quality).strip()
        if quality not in _CHORD_QUALITIES:
            raise ValueError(f"unsupported chord quality: {quality}")
        start_ms, end_ms = _time_range(
            self.start_audio_ms, self.end_audio_ms
        )
        root_pc = _pitch_class(self.root_pc, allow_none=True)
        bass_pc = _pitch_class(self.bass_pc, allow_none=True)
        if quality == "N":
            root_pc = None
            bass_pc = None
        elif root_pc is None:
            raise ValueError("pitched chords require a root pitch class")
        review_id = _safe_token(self.review_id, allow_empty=True)
        segment_id = _safe_token(self.segment_id, allow_empty=True)
        if review_id is None or segment_id is None:
            raise ValueError("invalid chord review identifier")
        if not review_id:
            review_id = stable_assist_review_id(
                "chord",
                segment_id,
                round(start_ms, 3),
                round(end_ms, 3),
                root_pc,
                quality,
            )
        object.__setattr__(self, "review_id", review_id)
        object.__setattr__(self, "segment_id", segment_id)
        object.__setattr__(self, "start_audio_ms", start_ms)
        object.__setattr__(self, "end_audio_ms", end_ms)
        object.__setattr__(self, "root_pc", root_pc)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "bass_pc", bass_pc)
        object.__setattr__(
            self,
            "candidate_ids",
            _normalise_candidate_ids(self.candidate_ids),
        )
        object.__setattr__(self, "manual", bool(self.manual))
        object.__setattr__(self, "locked", bool(self.locked))
        object.__setattr__(self, "orphaned", bool(self.orphaned))

    @property
    def protected(self) -> bool:
        return self.manual or self.locked

    @property
    def active(self) -> bool:
        return self.protected and not self.orphaned

    def to_payload(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "segment_id": self.segment_id,
            "start_audio_ms": self.start_audio_ms,
            "end_audio_ms": self.end_audio_ms,
            "root_pc": self.root_pc,
            "quality": self.quality,
            "bass_pc": self.bass_pc,
            "candidate_ids": list(self.candidate_ids),
            "manual": self.manual,
            "locked": self.locked,
            "orphaned": self.orphaned,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "LockedChordReview | None":
        if not isinstance(payload, Mapping):
            return None
        candidate_ids = payload.get("candidate_ids", ())
        if not isinstance(candidate_ids, Sequence) or isinstance(
            candidate_ids, (str, bytes)
        ):
            candidate_ids = ()
        try:
            return cls(
                review_id=str(payload.get("review_id") or ""),
                segment_id=str(payload.get("segment_id") or ""),
                start_audio_ms=payload.get("start_audio_ms"),
                end_audio_ms=payload.get("end_audio_ms"),
                root_pc=payload.get("root_pc"),
                quality=str(payload.get("quality") or ""),
                bass_pc=payload.get("bass_pc"),
                candidate_ids=tuple(candidate_ids),
                manual=bool(payload.get("manual", True)),
                locked=bool(payload.get("locked", True)),
                orphaned=bool(payload.get("orphaned", False)),
            )
        except (TypeError, ValueError, OverflowError):
            return None


@dataclass(frozen=True, slots=True)
class ManualVoiceGroupReview:
    """Human voice grouping and optional confirmed BDO instrument."""

    review_id: str
    group_id: str
    candidate_ids: tuple[str, ...]
    start_audio_ms: float
    end_audio_ms: float
    role: str
    confirmed_instrument_id: int | None = None
    orphaned: bool = False

    def __post_init__(self) -> None:
        start_ms, end_ms = _time_range(
            self.start_audio_ms, self.end_audio_ms
        )
        candidate_ids = _normalise_candidate_ids(self.candidate_ids)
        if not candidate_ids:
            raise ValueError("a reviewed voice group requires candidate ids")
        review_id = _safe_token(self.review_id, allow_empty=True)
        group_id = _safe_token(self.group_id, allow_empty=True)
        if review_id is None or group_id is None:
            raise ValueError("invalid voice-group review identifier")
        if not review_id:
            review_id = stable_assist_review_id(
                "voice", candidate_ids, round(start_ms, 3), round(end_ms, 3)
            )
        if not group_id:
            group_id = review_id
        object.__setattr__(self, "review_id", review_id)
        object.__setattr__(self, "group_id", group_id)
        object.__setattr__(self, "candidate_ids", candidate_ids)
        object.__setattr__(self, "start_audio_ms", start_ms)
        object.__setattr__(self, "end_audio_ms", end_ms)
        object.__setattr__(self, "role", _normalise_role(self.role))
        object.__setattr__(
            self,
            "confirmed_instrument_id",
            _instrument_id(self.confirmed_instrument_id),
        )
        object.__setattr__(self, "orphaned", bool(self.orphaned))

    @property
    def active(self) -> bool:
        return not self.orphaned

    def to_payload(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "group_id": self.group_id,
            "candidate_ids": list(self.candidate_ids),
            "start_audio_ms": self.start_audio_ms,
            "end_audio_ms": self.end_audio_ms,
            "role": self.role,
            "confirmed_instrument_id": self.confirmed_instrument_id,
            "orphaned": self.orphaned,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "ManualVoiceGroupReview | None":
        if not isinstance(payload, Mapping):
            return None
        candidate_ids = payload.get("candidate_ids", ())
        if not isinstance(candidate_ids, Sequence) or isinstance(
            candidate_ids, (str, bytes)
        ):
            return None
        try:
            return cls(
                review_id=str(payload.get("review_id") or ""),
                group_id=str(payload.get("group_id") or ""),
                candidate_ids=tuple(candidate_ids),
                start_audio_ms=payload.get("start_audio_ms"),
                end_audio_ms=payload.get("end_audio_ms"),
                role=str(payload.get("role") or "harmony"),
                confirmed_instrument_id=payload.get("confirmed_instrument_id"),
                orphaned=bool(payload.get("orphaned", False)),
            )
        except (TypeError, ValueError, OverflowError):
            return None


def _canonical_payload(value: object) -> str:
    payload = value.to_payload()  # type: ignore[attr-defined]
    return json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _stable_dedupe(
    values: Iterable[object], id_attribute: str
) -> tuple[object, ...]:
    grouped: dict[str, list[object]] = {}
    for value in values:
        identifier = str(getattr(value, id_attribute))
        grouped.setdefault(identifier, []).append(value)
        if len(grouped) >= _MAX_REVIEW_ITEMS:
            break
    # A malformed payload can repeat one identity with conflicting values.
    # Selecting the canonical minimum makes decoding independent of list order.
    selected = [
        min(items, key=_canonical_payload) for items in grouped.values()
    ]
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class TranscriptionAssistReviewState:
    """Schema-v5 lightweight human-review state.

    No field can carry audio bytes, feature matrices, game sample paths, or
    automatic analysis arrays.
    """

    audio_fingerprint: str = ""
    key_override: KeyReviewOverride | None = None
    locked_chord_segments: tuple[LockedChordReview, ...] = ()
    voice_groups: tuple[ManualVoiceGroupReview, ...] = ()

    def __post_init__(self) -> None:
        fingerprint = _audio_fingerprint(self.audio_fingerprint)
        key_override = (
            self.key_override
            if isinstance(self.key_override, KeyReviewOverride)
            else None
        )
        chord_values = tuple(
            value
            for value in self.locked_chord_segments
            if isinstance(value, LockedChordReview)
        )
        group_values = tuple(
            value
            for value in self.voice_groups
            if isinstance(value, ManualVoiceGroupReview)
        )
        chords = _stable_dedupe(chord_values, "review_id")
        groups = _stable_dedupe(group_values, "review_id")
        chords = tuple(
            sorted(
                chords,
                key=lambda item: (
                    item.start_audio_ms,
                    item.end_audio_ms,
                    item.review_id,
                ),
            )
        )
        # Corrupt or hand-edited project sidecars may contain overlapping
        # active chord overrides.  Preserve every decision for inspection,
        # but only the deterministic first interval may stay active.
        non_overlapping_chords: list[LockedChordReview] = []
        active_end = -math.inf
        for chord in chords:
            if chord.orphaned:
                non_overlapping_chords.append(chord)
                continue
            if chord.start_audio_ms < active_end - 1e-9:
                non_overlapping_chords.append(
                    replace(chord, orphaned=True)
                )
                continue
            non_overlapping_chords.append(chord)
            active_end = chord.end_audio_ms
        chords = tuple(non_overlapping_chords)
        groups = tuple(
            sorted(
                groups,
                key=lambda item: (
                    item.start_audio_ms,
                    item.end_audio_ms,
                    item.review_id,
                ),
            )
        )
        # A decision without a trusted content identity must never become
        # active merely because a project was opened with some other audio.
        if not fingerprint:
            if key_override is not None:
                key_override = replace(key_override, orphaned=True)
            chords = tuple(replace(item, orphaned=True) for item in chords)
            groups = tuple(replace(item, orphaned=True) for item in groups)
        object.__setattr__(self, "audio_fingerprint", fingerprint)
        object.__setattr__(self, "key_override", key_override)
        object.__setattr__(self, "locked_chord_segments", chords)
        object.__setattr__(self, "voice_groups", groups)

    @property
    def active_key_override(self) -> KeyReviewOverride | None:
        value = self.key_override
        return value if value is not None and value.active else None

    @property
    def active_chord_segments(self) -> tuple[LockedChordReview, ...]:
        return tuple(item for item in self.locked_chord_segments if item.active)

    @property
    def active_voice_groups(self) -> tuple[ManualVoiceGroupReview, ...]:
        return tuple(item for item in self.voice_groups if item.active)

    @property
    def has_orphaned_reviews(self) -> bool:
        return bool(
            (self.key_override is not None and self.key_override.orphaned)
            or any(item.orphaned for item in self.locked_chord_segments)
            or any(item.orphaned for item in self.voice_groups)
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "version": ASSIST_REVIEW_PAYLOAD_VERSION,
            "audio_fingerprint": self.audio_fingerprint,
            "key_override": (
                None
                if self.key_override is None
                else self.key_override.to_payload()
            ),
            "locked_chord_segments": [
                item.to_payload() for item in self.locked_chord_segments
            ],
            "voice_groups": [item.to_payload() for item in self.voice_groups],
        }

    @classmethod
    def from_payload(cls, payload: object) -> "TranscriptionAssistReviewState":
        if not isinstance(payload, Mapping):
            return cls()
        try:
            version = int(
                payload.get("version", ASSIST_REVIEW_PAYLOAD_VERSION)
            )
        except (TypeError, ValueError, OverflowError):
            return cls()
        if version != ASSIST_REVIEW_PAYLOAD_VERSION:
            return cls()
        chord_payloads = payload.get("locked_chord_segments", ())
        group_payloads = payload.get("voice_groups", ())
        if not isinstance(chord_payloads, Sequence) or isinstance(
            chord_payloads, (str, bytes)
        ):
            chord_payloads = ()
        if not isinstance(group_payloads, Sequence) or isinstance(
            group_payloads, (str, bytes)
        ):
            group_payloads = ()
        chords: list[LockedChordReview] = []
        for value in chord_payloads[:_MAX_REVIEW_ITEMS]:
            chord = LockedChordReview.from_payload(value)
            if chord is not None:
                chords.append(chord)
        groups: list[ManualVoiceGroupReview] = []
        for value in group_payloads[:_MAX_REVIEW_ITEMS]:
            group = ManualVoiceGroupReview.from_payload(value)
            if group is not None:
                groups.append(group)
        return cls(
            audio_fingerprint=str(payload.get("audio_fingerprint") or ""),
            key_override=KeyReviewOverride.from_payload(
                payload.get("key_override")
            ),
            locked_chord_segments=tuple(chords),
            voice_groups=tuple(groups),
        )


def isolate_assist_review_for_audio(
    state: TranscriptionAssistReviewState,
    audio_fingerprint: str,
) -> TranscriptionAssistReviewState:
    """Bind review state to ``audio_fingerprint`` and orphan stale decisions.

    Matching identities return the original immutable value.  Any mismatch,
    including a missing/invalid identity, is fail-closed: decisions remain
    visible for recovery or manual confirmation but none is active.
    """

    if not isinstance(state, TranscriptionAssistReviewState):
        raise TypeError("state must be TranscriptionAssistReviewState")
    fingerprint = _audio_fingerprint(audio_fingerprint)
    if fingerprint and fingerprint == state.audio_fingerprint:
        return state
    key_override = state.key_override
    if key_override is not None:
        key_override = replace(key_override, orphaned=True)
    return TranscriptionAssistReviewState(
        audio_fingerprint=fingerprint,
        key_override=key_override,
        locked_chord_segments=tuple(
            replace(item, orphaned=True)
            for item in state.locked_chord_segments
        ),
        voice_groups=tuple(
            replace(item, orphaned=True) for item in state.voice_groups
        ),
    )


@dataclass(frozen=True, slots=True)
class _CandidateAnchor:
    candidate_id: str
    pitch: int
    start_audio_ms: float
    end_audio_ms: float


def _value(item: object, *names: str, default: object = None) -> object:
    for name in names:
        if isinstance(item, Mapping) and name in item:
            return item[name]
        if hasattr(item, name):
            return getattr(item, name)
    return default


def _candidate_anchor(value: object) -> _CandidateAnchor | None:
    candidate_id = _safe_token(_value(value, "candidate_id", default=""))
    if candidate_id is None:
        return None
    try:
        pitch = int(_value(value, "pitch"))
        start_ms = _finite_time(
            _value(value, "start_audio_ms", "start_ms", "start"),
            "candidate start",
        )
        end_value = _value(value, "end_audio_ms", "end_ms", default=None)
        if end_value is None:
            duration_ms = _finite_time(
                _value(value, "duration_ms", "dur"),
                "candidate duration",
            )
            end_ms = start_ms + duration_ms
        else:
            end_ms = _finite_time(end_value, "candidate end")
    except (TypeError, ValueError, OverflowError):
        return None
    if pitch < 0 or pitch > 127 or start_ms < 0.0 or end_ms <= start_ms:
        return None
    return _CandidateAnchor(candidate_id, pitch, start_ms, end_ms)


def _candidate_anchors(values: Iterable[object]) -> tuple[_CandidateAnchor, ...]:
    anchors: dict[str, _CandidateAnchor] = {}
    for index, value in enumerate(values):
        if index >= _MAX_RECOVERY_CANDIDATES:
            break
        anchor = _candidate_anchor(value)
        if anchor is None:
            continue
        current = anchors.get(anchor.candidate_id)
        if current is None or (
            anchor.start_audio_ms,
            anchor.pitch,
            anchor.end_audio_ms,
        ) < (
            current.start_audio_ms,
            current.pitch,
            current.end_audio_ms,
        ):
            anchors[anchor.candidate_id] = anchor
    return tuple(
        sorted(
            anchors.values(),
            key=lambda item: (
                item.start_audio_ms,
                item.pitch,
                item.end_audio_ms,
                item.candidate_id,
            ),
        )
    )


def _interval(value: object) -> tuple[float, float] | None:
    try:
        return _time_range(
            _value(value, "start_audio_ms", "start_ms"),
            _value(value, "end_audio_ms", "end_ms"),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _item_id(value: object, *names: str) -> str:
    return (
        _safe_token(_value(value, *names, default=""), allow_empty=True)
        or ""
    )


def _item_candidate_ids(value: object) -> tuple[str, ...]:
    values = _value(value, "candidate_ids", default=())
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return _normalise_candidate_ids(values)


def _interval_iou(
    left: tuple[float, float], right: tuple[float, float]
) -> float:
    intersection = max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union > 0.0 else 0.0


def _anchors_in_interval(
    anchors: Sequence[_CandidateAnchor],
    interval: tuple[float, float],
) -> tuple[_CandidateAnchor, ...]:
    return tuple(
        item
        for item in anchors
        if min(item.end_audio_ms, interval[1])
        > max(item.start_audio_ms, interval[0])
    )


def _anchors_for_ids(
    anchors: Sequence[_CandidateAnchor],
    candidate_ids: Sequence[str],
    interval: tuple[float, float],
) -> tuple[_CandidateAnchor, ...]:
    if candidate_ids:
        wanted = set(candidate_ids)
        matched = tuple(item for item in anchors if item.candidate_id in wanted)
        if matched:
            return matched
    return _anchors_in_interval(anchors, interval)


def _anchors_for_ids_indexed(
    anchors: Sequence[_CandidateAnchor],
    anchors_by_id: Mapping[str, _CandidateAnchor],
    candidate_ids: Sequence[str],
    interval: tuple[float, float],
) -> tuple[_CandidateAnchor, ...]:
    if candidate_ids:
        matched = tuple(
            anchor
            for candidate_id in candidate_ids
            if (anchor := anchors_by_id.get(str(candidate_id))) is not None
        )
        if matched:
            return matched
    return _anchors_in_interval(anchors, interval)


def _anchor_interval_iou(
    left: _CandidateAnchor, right: _CandidateAnchor
) -> float:
    return _interval_iou(
        (left.start_audio_ms, left.end_audio_ms),
        (right.start_audio_ms, right.end_audio_ms),
    )


def candidate_overlap_score(
    old_candidates: Iterable[object],
    new_candidates: Iterable[object],
) -> float:
    """Return deterministic ID/geometry overlap in the closed range 0..1."""

    old_values = tuple(old_candidates)
    new_values = tuple(new_candidates)
    old_anchors = (
        old_values
        if all(isinstance(item, _CandidateAnchor) for item in old_values)
        else _candidate_anchors(old_values)
    )
    new_anchors = (
        new_values
        if all(isinstance(item, _CandidateAnchor) for item in new_values)
        else _candidate_anchors(new_values)
    )
    if not old_anchors or not new_anchors:
        return 0.0
    old_by_id = {item.candidate_id: item for item in old_anchors}
    new_by_id = {item.candidate_id: item for item in new_anchors}
    matched_old = set(old_by_id).intersection(new_by_id)
    matched_new = set(matched_old)
    if (
        len(matched_old) == len(old_anchors)
        and len(matched_new) == len(new_anchors)
    ):
        return 1.0
    # Changed cache identities can also change candidate IDs.  Match remaining
    # values conservatively by pitch and local time geometry.  Each old anchor
    # inspects a bounded neighbourhood around its onset, avoiding the previous
    # O(old * new) Cartesian product on 20k-candidate sessions.
    pitch_buckets: dict[int, list[_CandidateAnchor]] = defaultdict(list)
    for item in new_anchors:
        if item.candidate_id not in matched_new:
            pitch_buckets[item.pitch].append(item)
    new_by_pitch: dict[int, tuple[list[float], list[_CandidateAnchor]]] = {}
    for pitch, values in pitch_buckets.items():
        new_by_pitch[pitch] = (
            [item.start_audio_ms for item in values],
            values,
        )
    for old in old_anchors:
        if old.candidate_id in matched_old:
            continue
        starts, values = new_by_pitch.get(old.pitch, ([], []))
        if not values:
            continue
        center = bisect_left(starts, old.start_audio_ms)
        indices = set(
            range(
                max(0, center - 8),
                min(len(values), center + 9),
            )
        )
        # Include a few interval-boundary values so a long sustained candidate
        # is not missed solely because its onset lies outside the local window.
        left = bisect_left(starts, old.start_audio_ms - 2_000.0)
        right = bisect_right(starts, old.end_audio_ms)
        indices.update(range(left, min(right, left + 4)))
        indices.update(range(max(left, right - 4), right))
        ranked: list[tuple[float, float, str, _CandidateAnchor]] = []
        for index in sorted(indices):
            new = values[index]
            if new.candidate_id in matched_new:
                continue
            overlap = _anchor_interval_iou(old, new)
            onset_delta = abs(old.start_audio_ms - new.start_audio_ms)
            onset_tolerance = max(
                35.0,
                0.20
                * min(
                    old.end_audio_ms - old.start_audio_ms,
                    new.end_audio_ms - new.start_audio_ms,
                ),
            )
            if overlap < 0.35 and onset_delta > onset_tolerance:
                continue
            ranked.append(
                (-overlap, onset_delta, new.candidate_id, new)
            )
        if not ranked:
            continue
        _overlap, _delta, new_id, _new = min(ranked)
        matched_old.add(old.candidate_id)
        matched_new.add(new_id)
    return len(matched_old) / max(len(old_anchors), len(new_anchors))


@dataclass(frozen=True, slots=True)
class AssistReviewRecoveryResult:
    state: TranscriptionAssistReviewState
    key_recovered: bool = False
    recovered_chord_review_ids: tuple[str, ...] = ()
    recovered_voice_review_ids: tuple[str, ...] = ()
    orphaned_chord_review_ids: tuple[str, ...] = ()
    orphaned_voice_review_ids: tuple[str, ...] = ()


def recover_assist_review(
    state: TranscriptionAssistReviewState,
    *,
    audio_fingerprint: str,
    old_candidates: Iterable[object],
    new_candidates: Iterable[object],
    chord_segments: Sequence[object] = (),
    voice_groups: Sequence[object] = (),
    minimum_candidate_overlap: float = 0.60,
    minimum_time_iou: float = 0.50,
    force_reanchor: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> AssistReviewRecoveryResult:
    """Recover orphaned human decisions onto one new automatic analysis.

    Recovery is one-to-one and requires *both* candidate overlap and interval
    overlap.  Human chord/key semantics, voice roles, and confirmed BDO
    instrument IDs are preserved; only disposable segment/group anchors are
    updated.  Unmatched values stay orphaned.
    """

    if not isinstance(state, TranscriptionAssistReviewState):
        raise TypeError("state must be TranscriptionAssistReviewState")
    if cancelled is not None and cancelled():
        raise RuntimeError("assist review recovery cancelled")
    fingerprint = _audio_fingerprint(audio_fingerprint)
    if not fingerprint:
        isolated = isolate_assist_review_for_audio(state, "")
        return AssistReviewRecoveryResult(
            isolated,
            orphaned_chord_review_ids=tuple(
                item.review_id for item in isolated.locked_chord_segments
            ),
            orphaned_voice_review_ids=tuple(
                item.review_id for item in isolated.voice_groups
            ),
        )
    candidate_threshold = float(minimum_candidate_overlap)
    time_threshold = float(minimum_time_iou)
    if (
        not math.isfinite(candidate_threshold)
        or not 0.0 <= candidate_threshold <= 1.0
        or not math.isfinite(time_threshold)
        or not 0.0 <= time_threshold <= 1.0
    ):
        raise ValueError("recovery thresholds must be finite values from 0 to 1")

    isolated = isolate_assist_review_for_audio(state, fingerprint)
    if force_reanchor and fingerprint == isolated.audio_fingerprint:
        isolated = replace(
            isolated,
            locked_chord_segments=tuple(
                replace(item, orphaned=True)
                for item in isolated.locked_chord_segments
            ),
            voice_groups=tuple(
                replace(item, orphaned=True)
                for item in isolated.voice_groups
            ),
        )
    old_anchors = _candidate_anchors(old_candidates)
    new_anchors = _candidate_anchors(new_candidates)
    old_anchors_by_id = {
        item.candidate_id: item for item in old_anchors
    }
    new_anchors_by_id = {
        item.candidate_id: item for item in new_anchors
    }

    key_override = isolated.key_override
    key_recovered = False
    if key_override is not None and key_override.orphaned:
        old_span = (
            (old_anchors[0].start_audio_ms, max(item.end_audio_ms for item in old_anchors))
            if old_anchors
            else None
        )
        new_span = (
            (new_anchors[0].start_audio_ms, max(item.end_audio_ms for item in new_anchors))
            if new_anchors
            else None
        )
        if (
            old_span is not None
            and new_span is not None
            and candidate_overlap_score(old_anchors, new_anchors)
            >= candidate_threshold
            and _interval_iou(old_span, new_span) >= time_threshold
        ):
            key_override = replace(key_override, orphaned=False)
            key_recovered = True

    valid_chord_targets: list[
        tuple[
            str,
            tuple[float, float],
            tuple[str, ...],
            tuple[_CandidateAnchor, ...],
            object,
        ]
    ] = []
    for target in chord_segments:
        if cancelled is not None and cancelled():
            raise RuntimeError("assist review recovery cancelled")
        interval = _interval(target)
        if interval is None:
            continue
        identifier = _item_id(target, "segment_id", "review_id")
        target_ids = _item_candidate_ids(target)
        if not target_ids:
            target_ids = tuple(
                item.candidate_id
                for item in _anchors_in_interval(new_anchors, interval)
            )
        target_anchors = _anchors_for_ids_indexed(
            new_anchors,
            new_anchors_by_id,
            target_ids,
            interval,
        )
        valid_chord_targets.append(
            (identifier, interval, target_ids, target_anchors, target)
        )
    valid_chord_targets.sort(key=lambda item: (item[1][0], item[1][1], item[0]))

    used_chords: set[int] = set()
    recovered_chord_ids: list[str] = []
    new_chord_reviews: list[LockedChordReview] = []
    for review in isolated.locked_chord_segments:
        if cancelled is not None and cancelled():
            raise RuntimeError("assist review recovery cancelled")
        if not review.orphaned:
            new_chord_reviews.append(review)
            continue
        review_interval = (review.start_audio_ms, review.end_audio_ms)
        review_anchors = _anchors_for_ids_indexed(
            old_anchors,
            old_anchors_by_id,
            review.candidate_ids,
            review_interval,
        )
        if not review_anchors and review.candidate_ids:
            review_anchors = _anchors_for_ids_indexed(
                new_anchors,
                new_anchors_by_id,
                review.candidate_ids,
                review_interval,
            )
        ranked_targets: list[tuple[float, float, str, int]] = []
        for index, (
            identifier,
            interval,
            _target_ids,
            target_anchors,
            _target,
        ) in enumerate(valid_chord_targets):
            if index in used_chords:
                continue
            time_iou = _interval_iou(review_interval, interval)
            if time_iou < time_threshold:
                continue
            overlap = candidate_overlap_score(review_anchors, target_anchors)
            if overlap < candidate_threshold:
                continue
            ranked_targets.append((-overlap, -time_iou, identifier, index))
        ranked_targets.sort()
        if not ranked_targets:
            new_chord_reviews.append(review)
            continue
        _overlap, _time, identifier, target_index = ranked_targets[0]
        used_chords.add(target_index)
        (
            _target_id,
            target_interval,
            target_ids,
            _target_anchors,
            _target,
        ) = valid_chord_targets[target_index]
        recovered_chord_ids.append(review.review_id)
        new_chord_reviews.append(
            replace(
                review,
                segment_id=identifier or review.segment_id,
                start_audio_ms=target_interval[0],
                end_audio_ms=target_interval[1],
                candidate_ids=target_ids,
                orphaned=False,
            )
        )

    valid_voice_targets: list[
        tuple[
            str,
            tuple[float, float],
            tuple[str, ...],
            tuple[_CandidateAnchor, ...],
            object,
        ]
    ] = []
    for target in voice_groups:
        if cancelled is not None and cancelled():
            raise RuntimeError("assist review recovery cancelled")
        interval = _interval(target)
        if interval is None:
            continue
        identifier = _item_id(target, "group_id", "review_id")
        target_ids = _item_candidate_ids(target)
        if not target_ids:
            continue
        target_anchors = _anchors_for_ids_indexed(
            new_anchors,
            new_anchors_by_id,
            target_ids,
            interval,
        )
        valid_voice_targets.append(
            (identifier, interval, target_ids, target_anchors, target)
        )
    valid_voice_targets.sort(key=lambda item: (item[1][0], item[1][1], item[0]))

    used_voices: set[int] = set()
    recovered_voice_ids: list[str] = []
    new_voice_reviews: list[ManualVoiceGroupReview] = []
    for review in isolated.voice_groups:
        if cancelled is not None and cancelled():
            raise RuntimeError("assist review recovery cancelled")
        if not review.orphaned:
            new_voice_reviews.append(review)
            continue
        review_interval = (review.start_audio_ms, review.end_audio_ms)
        review_anchors = _anchors_for_ids_indexed(
            old_anchors,
            old_anchors_by_id,
            review.candidate_ids,
            review_interval,
        )
        if not review_anchors and review.candidate_ids:
            review_anchors = _anchors_for_ids_indexed(
                new_anchors,
                new_anchors_by_id,
                review.candidate_ids,
                review_interval,
            )
        ranked_targets: list[tuple[float, float, str, int]] = []
        for index, (
            identifier,
            interval,
            _target_ids,
            target_anchors,
            _target,
        ) in enumerate(valid_voice_targets):
            if index in used_voices:
                continue
            time_iou = _interval_iou(review_interval, interval)
            if time_iou < time_threshold:
                continue
            overlap = candidate_overlap_score(review_anchors, target_anchors)
            if overlap < candidate_threshold:
                continue
            ranked_targets.append((-overlap, -time_iou, identifier, index))
        ranked_targets.sort()
        if not ranked_targets:
            new_voice_reviews.append(review)
            continue
        _overlap, _time, identifier, target_index = ranked_targets[0]
        used_voices.add(target_index)
        (
            _target_id,
            target_interval,
            target_ids,
            _target_anchors,
            _target,
        ) = valid_voice_targets[target_index]
        recovered_voice_ids.append(review.review_id)
        new_voice_reviews.append(
            replace(
                review,
                group_id=identifier or review.group_id,
                candidate_ids=target_ids,
                start_audio_ms=target_interval[0],
                end_audio_ms=target_interval[1],
                orphaned=False,
            )
        )

    recovered_state = TranscriptionAssistReviewState(
        audio_fingerprint=fingerprint,
        key_override=key_override,
        locked_chord_segments=tuple(new_chord_reviews),
        voice_groups=tuple(new_voice_reviews),
    )
    recovered_chord_set = set(recovered_chord_ids)
    recovered_voice_set = set(recovered_voice_ids)
    return AssistReviewRecoveryResult(
        state=recovered_state,
        key_recovered=key_recovered,
        recovered_chord_review_ids=tuple(sorted(recovered_chord_set)),
        recovered_voice_review_ids=tuple(sorted(recovered_voice_set)),
        orphaned_chord_review_ids=tuple(
            item.review_id
            for item in recovered_state.locked_chord_segments
            if item.orphaned and item.review_id not in recovered_chord_set
        ),
        orphaned_voice_review_ids=tuple(
            item.review_id
            for item in recovered_state.voice_groups
            if item.orphaned and item.review_id not in recovered_voice_set
        ),
    )


__all__ = [
    "ASSIST_REVIEW_PAYLOAD_VERSION",
    "AssistReviewRecoveryResult",
    "KeyReviewOverride",
    "LockedChordReview",
    "ManualVoiceGroupReview",
    "TranscriptionAssistReviewState",
    "candidate_overlap_score",
    "isolate_assist_review_for_audio",
    "recover_assist_review",
    "stable_assist_review_id",
]
