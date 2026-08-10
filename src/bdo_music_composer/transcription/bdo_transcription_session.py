"""Qt-free transcription review state and routing operations.

The session deliberately remains a sidecar to the editor's authoritative
``TrackState``/``Note`` model.  It stores stable candidate identifiers and
lightweight review decisions only; decoded evidence and candidate matrices
remain disposable cache data.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from bdo_music_composer.transcription.bdo_transcription import (
    DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
    transcription_thresholds,
)


SENSITIVITY_PRESETS: dict[str, tuple[float, float]] = {
    "conservative": (0.65, 0.45),
    "balanced": (0.50, 0.30),
    "sensitive": (0.35, 0.20),
}
DEFAULT_SENSITIVITY = "balanced"
ANALYSIS_MODES = frozenset(("standard", "mixed_enhanced"))
DEFAULT_ANALYSIS_MODE = DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
LEGACY_ANALYSIS_MODE = "standard"
CLEANUP_PROFILES = frozenset(("preserve", "balanced", "clean"))
DEFAULT_CLEANUP_PROFILE = "preserve"
LEGACY_CLEANUP_PROFILE = "preserve"
TRANSCRIPTION_REVIEW_PAYLOAD_VERSION = 4
_MAX_REVIEW_IDS = 100_000
_MAX_CANDIDATE_ID_LENGTH = 128
_MAX_ANNOTATION_TOKEN_LENGTH = 128


def _candidate_value(candidate: object, *names: str, default: object = None) -> object:
    for name in names:
        if hasattr(candidate, name):
            return getattr(candidate, name)
        if isinstance(candidate, Mapping) and name in candidate:
            return candidate[name]
    return default


def _valid_candidate_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate_id = value.strip()
    if not candidate_id or len(candidate_id) > _MAX_CANDIDATE_ID_LENGTH:
        return None
    return candidate_id


def _normalise_annotation_tokens(value: object) -> frozenset[str]:
    # Runtime ``typing.Sequence`` checks are comparatively expensive at the
    # 100k-candidate boundary. Internal annotations already use frozensets, so
    # preserve the empty/common trusted shape before entering defensive
    # external-payload validation.
    if value == frozenset():
        return frozenset()
    if isinstance(value, frozenset) and all(
        isinstance(item, str)
        and item == item.strip()
        and 0 < len(item) <= _MAX_ANNOTATION_TOKEN_LENGTH
        for item in value
    ):
        return value
    if isinstance(value, str):
        items: Sequence[object] = (value,)
    elif isinstance(value, (set, frozenset)):
        items = tuple(value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = value
    else:
        return frozenset()
    tokens: set[str] = set()
    for item in items[:_MAX_REVIEW_IDS]:
        if not isinstance(item, str):
            continue
        token = item.strip()
        if token and len(token) <= _MAX_ANNOTATION_TOKEN_LENGTH:
            tokens.add(token)
    return frozenset(tokens)


@dataclass(frozen=True, slots=True)
class CandidateAnnotation:
    """Serializable runtime metadata kept beside immutable candidates.

    ``lineage_ids`` names every source lineage represented by the candidate.
    A candidate always belongs to its own lineage as well.  ``flags`` is an
    intentionally open set so fragment classifiers can add small, stable tags
    without changing :class:`bdo_transcription.TranscriptionCandidate`.
    """

    candidate_id: str
    flags: frozenset[str] = frozenset()
    lineage_ids: frozenset[str] = frozenset()
    disposition: str = "kept"

    def __post_init__(self) -> None:
        candidate_id = _valid_candidate_id(self.candidate_id)
        if candidate_id is None:
            raise ValueError("candidate annotation requires a valid candidate id")
        flags = _normalise_annotation_tokens(self.flags)
        lineage_ids = set(_normalise_annotation_tokens(self.lineage_ids))
        lineage_ids.add(candidate_id)
        disposition = str(self.disposition or "kept").strip()
        if (
            not disposition
            or len(disposition) > _MAX_ANNOTATION_TOKEN_LENGTH
        ):
            disposition = "kept"
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "flags", flags)
        object.__setattr__(self, "lineage_ids", frozenset(lineage_ids))
        object.__setattr__(self, "disposition", disposition)

    def to_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "flags": sorted(self.flags),
            "lineage_ids": sorted(self.lineage_ids),
            "disposition": self.disposition,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "CandidateAnnotation | None":
        if not isinstance(payload, Mapping):
            return None
        candidate_id = _valid_candidate_id(payload.get("candidate_id"))
        if candidate_id is None:
            return None
        return cls(
            candidate_id=candidate_id,
            flags=_normalise_annotation_tokens(payload.get("flags")),
            lineage_ids=_normalise_annotation_tokens(
                payload.get("lineage_ids")
            ),
            disposition=str(payload.get("disposition") or "kept"),
        )


def _default_candidate_annotation(candidate_id: str) -> CandidateAnnotation:
    """Construct the already-validated internal default without re-parsing.

    ``set_candidates`` obtains IDs exclusively from ``stable_candidate_id``;
    explicit IDs have passed ``_valid_candidate_id`` and generated IDs are
    bounded hashes. External payloads still use the defensive dataclass path.
    """

    annotation = object.__new__(CandidateAnnotation)
    object.__setattr__(annotation, "candidate_id", candidate_id)
    object.__setattr__(annotation, "flags", frozenset())
    object.__setattr__(annotation, "lineage_ids", frozenset((candidate_id,)))
    object.__setattr__(annotation, "disposition", "kept")
    return annotation


def stable_candidate_id(
    candidate: object,
    *,
    cache_key: str,
    backend_id: str = "",
) -> str:
    """Return a stable, privacy-safe identifier for one decoded candidate.

    Newer ``bdo_transcription`` candidates already carry the identifier
    produced by the backend.  The deterministic fallback keeps this module
    usable with cached projects, tests, and third-party backends without
    importing any optional model packages.
    """

    # A candidate may have been projected from audio time into project time.
    # Its backend-assigned ID is still authoritative; recomputing from the
    # shifted start/end would break persisted review decisions when offset
    # changes.
    explicit = _valid_candidate_id(
        _candidate_value(candidate, "candidate_id", default="")
    )
    if explicit is not None:
        return explicit

    # Prefer the canonical helper for candidates that have not been identified
    # yet.  Importing bdo_transcription is safe (optional ML packages are lazy).
    try:
        from bdo_music_composer.transcription.bdo_transcription import transcription_candidate_id

        canonical = _valid_candidate_id(
            transcription_candidate_id(str(cache_key), candidate)
        )
        if canonical is not None:
            return canonical
    except (ImportError, TypeError, ValueError, AttributeError):
        pass

    start_ms = float(_candidate_value(candidate, "start_ms", "start", default=0.0))
    duration_ms = max(
        0.0,
        float(_candidate_value(candidate, "duration_ms", "dur", default=0.0)),
    )
    start_us = round(start_ms * 1000.0)
    payload = {
        "backend_id": str(backend_id),
        "cache_key": str(cache_key),
        "duration_us": round(duration_ms * 1000.0),
        "end_us": start_us + round(duration_ms * 1000.0),
        "pitch": int(_candidate_value(candidate, "pitch", default=0)),
        "source": str(_candidate_value(candidate, "source", default="")),
        "start_us": start_us,
        "velocity": int(
            _candidate_value(candidate, "velocity", "vel", default=0)
        ),
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"tc-{digest[:32]}"


def _normalise_track_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        track_id = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return track_id if track_id >= 0 else None


@dataclass(frozen=True, order=True, slots=True)
class CandidateRoute:
    candidate_id: str
    track_id: int

    def __post_init__(self) -> None:
        candidate_id = _valid_candidate_id(self.candidate_id)
        track_id = _normalise_track_id(self.track_id)
        if candidate_id is None:
            raise ValueError("candidate route requires a valid candidate id")
        if track_id is None:
            raise ValueError("candidate route requires a non-negative track id")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "track_id", track_id)

    def to_payload(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id, "track_id": self.track_id}

    @classmethod
    def from_payload(cls, payload: object) -> "CandidateRoute | None":
        if not isinstance(payload, Mapping):
            return None
        candidate_id = _valid_candidate_id(payload.get("candidate_id"))
        track_id = _normalise_track_id(payload.get("track_id"))
        if candidate_id is None or track_id is None:
            return None
        return cls(candidate_id, track_id)


def _coerce_candidate_route(value: object) -> CandidateRoute:
    if isinstance(value, CandidateRoute):
        return value
    route = CandidateRoute.from_payload(value)
    if route is None:
        raise ValueError("expected a valid candidate route")
    return route


def _normalise_route_tuple(
    values: Iterable[CandidateRoute] | None,
) -> tuple[CandidateRoute, ...]:
    if values is None:
        return ()
    return tuple(sorted({_coerce_candidate_route(value) for value in values}))


@dataclass(frozen=True, slots=True)
class StagedCandidateRoute:
    """One dialog-local route that has not crossed the project boundary.

    ``primary`` identifies candidates written through the current-track draft
    action.  Explicit multi-track copies use ``primary=False``.  The wrapper is
    deliberately not part of :class:`TranscriptionSessionState`; cancelling an
    editor therefore cannot leak staged routes into autosave.
    """

    route: CandidateRoute
    primary: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "route", _coerce_candidate_route(self.route))
        object.__setattr__(self, "primary", bool(self.primary))

    @property
    def candidate_id(self) -> str:
        return self.route.candidate_id

    @property
    def track_id(self) -> int:
        return self.route.track_id


@dataclass(frozen=True, slots=True)
class TranscriptionEditorCommit:
    """Qt-free payload prepared by a note-editor Apply/OK transaction.

    Draft notes remain opaque so this review module does not depend on the
    editor's concrete ``Note`` implementation.  Routes are kept separate by
    intent: primary routes correspond to candidate notes in the current-track
    draft, while copy routes are explicit writes to additional tracks.
    """

    current_track_id: int
    draft_notes: tuple[object, ...] = ()
    primary_routes: tuple[CandidateRoute, ...] = ()
    copy_routes: tuple[CandidateRoute, ...] = ()
    cache_key: str = ""
    analysis_fingerprint: str = ""
    new_track_specs: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        current_track_id = _normalise_track_id(self.current_track_id)
        if current_track_id is None:
            raise ValueError("editor commit requires a non-negative track id")
        primary_routes = _normalise_route_tuple(self.primary_routes)
        if any(route.track_id != current_track_id for route in primary_routes):
            raise ValueError(
                "primary editor routes must target the current track"
            )
        object.__setattr__(self, "current_track_id", current_track_id)
        object.__setattr__(self, "draft_notes", tuple(self.draft_notes))
        object.__setattr__(self, "primary_routes", primary_routes)
        object.__setattr__(
            self, "copy_routes", _normalise_route_tuple(self.copy_routes)
        )
        object.__setattr__(self, "cache_key", str(self.cache_key or ""))
        object.__setattr__(
            self,
            "analysis_fingerprint",
            str(self.analysis_fingerprint or ""),
        )
        track_specs: list[tuple[int, int]] = []
        seen_track_ids: set[int] = set()
        for value in self.new_track_specs:
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                raise ValueError(
                    "new track specs must contain (track_id, instrument_id)"
                )
            track_id = _normalise_track_id(value[0])
            instrument_id = _normalise_track_id(value[1])
            if (
                track_id is None
                or instrument_id is None
                or track_id in seen_track_ids
            ):
                raise ValueError("invalid or duplicate new track specification")
            seen_track_ids.add(track_id)
            track_specs.append((track_id, instrument_id))
        object.__setattr__(
            self,
            "new_track_specs",
            tuple(sorted(track_specs)),
        )

    @property
    def staged_routes(self) -> tuple[StagedCandidateRoute, ...]:
        primary = (
            StagedCandidateRoute(route, primary=True)
            for route in self.primary_routes
        )
        copies = (
            StagedCandidateRoute(route, primary=False)
            for route in self.copy_routes
        )
        return tuple((*primary, *copies))

    @property
    def routes(self) -> tuple[CandidateRoute, ...]:
        return tuple(sorted(set((*self.primary_routes, *self.copy_routes))))

    @property
    def has_staged_routes(self) -> bool:
        return bool(self.primary_routes or self.copy_routes)


@dataclass(frozen=True, slots=True)
class TranscriptionEditorCommitReport:
    """Structured result of one editor-to-project commit."""

    created_routes: tuple[CandidateRoute, ...] = ()
    satisfied_routes: tuple[CandidateRoute, ...] = ()
    invalid_routes: tuple[CandidateRoute, ...] = ()
    orphaned_routes: tuple[CandidateRoute, ...] = ()
    unresolved_routes: tuple[CandidateRoute, ...] = ()
    project_changed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "created_routes",
            "satisfied_routes",
            "invalid_routes",
            "orphaned_routes",
            "unresolved_routes",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalise_route_tuple(getattr(self, field_name)),
            )
        object.__setattr__(self, "project_changed", bool(self.project_changed))

    @property
    def applied_routes(self) -> tuple[CandidateRoute, ...]:
        return tuple(
            sorted(set((*self.created_routes, *self.satisfied_routes)))
        )

    @property
    def blocking_unresolved(self) -> tuple[CandidateRoute, ...]:
        return tuple(
            sorted(
                set(
                    (
                        *self.invalid_routes,
                        *self.orphaned_routes,
                        *self.unresolved_routes,
                    )
                )
            )
        )

    @property
    def created_count(self) -> int:
        return len(self.created_routes)

    @property
    def satisfied_count(self) -> int:
        return len(self.satisfied_routes)

    @property
    def applied_count(self) -> int:
        return len(self.applied_routes)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid_routes)

    @property
    def orphaned_count(self) -> int:
        return len(self.orphaned_routes)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved_routes)

    @property
    def blocking_count(self) -> int:
        return len(self.blocking_unresolved)


def _normalise_region(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        start_value = value.get("start_ms")
        end_value = value.get("end_ms")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 2:
            return None
        start_value, end_value = value
    else:
        return None
    try:
        start_ms = float(start_value)
        end_ms = float(end_value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(start_ms) or not math.isfinite(end_ms):
        return None
    if end_ms < start_ms:
        start_ms, end_ms = end_ms, start_ms
    if end_ms <= start_ms:
        return None
    return start_ms, end_ms


def _normalise_ids(value: object) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return frozenset()
    values: list[str] = []
    for item in value[:_MAX_REVIEW_IDS]:
        candidate_id = _valid_candidate_id(item)
        if candidate_id is not None:
            values.append(candidate_id)
    return frozenset(values)


def _normalise_routes(value: object) -> tuple[CandidateRoute, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    routes: set[CandidateRoute] = set()
    for item in value[:_MAX_REVIEW_IDS]:
        route = CandidateRoute.from_payload(item)
        if route is not None:
            routes.add(route)
    return tuple(sorted(routes))


def _coerce_candidate_annotation(
    value: object,
    *,
    candidate_id_hint: object = None,
) -> CandidateAnnotation | None:
    hinted_id = _valid_candidate_id(candidate_id_hint)
    if isinstance(value, CandidateAnnotation):
        if hinted_id is not None and value.candidate_id != hinted_id:
            return None
        return value
    if not isinstance(value, Mapping):
        return None
    payload = dict(value)
    if "candidate_id" not in payload and hinted_id is not None:
        payload["candidate_id"] = hinted_id
    annotation = CandidateAnnotation.from_payload(payload)
    if (
        annotation is None
        or hinted_id is not None
        and annotation.candidate_id != hinted_id
    ):
        return None
    return annotation


def _normalise_annotations(
    value: object,
) -> dict[str, CandidateAnnotation]:
    annotations: dict[str, CandidateAnnotation] = {}
    if isinstance(value, Mapping):
        items: Iterable[tuple[object, object]] = value.items()
        for index, (candidate_id, raw_annotation) in enumerate(items):
            if index >= _MAX_REVIEW_IDS:
                break
            annotation = _coerce_candidate_annotation(
                raw_annotation,
                candidate_id_hint=candidate_id,
            )
            if annotation is not None:
                annotations.setdefault(annotation.candidate_id, annotation)
        return annotations
    if not isinstance(value, Iterable) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return annotations
    for index, raw_annotation in enumerate(value):
        if index >= _MAX_REVIEW_IDS:
            break
        annotation = _coerce_candidate_annotation(raw_annotation)
        if annotation is not None:
            annotations.setdefault(annotation.candidate_id, annotation)
    return annotations


@dataclass(frozen=True, slots=True)
class TranscriptionSessionState:
    """Serializable review decisions, never decoded evidence or audio data."""

    cache_key: str = ""
    analysis_fingerprint: str = ""
    region: tuple[float, float] | None = None
    analysis_mode: str = DEFAULT_ANALYSIS_MODE
    sensitivity: str = DEFAULT_SENSITIVITY
    cleanup_profile: str = DEFAULT_CLEANUP_PROFILE
    selected_candidate_ids: frozenset[str] = frozenset()
    rejected_candidate_ids: frozenset[str] = frozenset()
    pending_routes: tuple[CandidateRoute, ...] = ()
    applied_routes: tuple[CandidateRoute, ...] = ()

    def __post_init__(self) -> None:
        sensitivity = str(self.sensitivity)
        if sensitivity not in SENSITIVITY_PRESETS:
            sensitivity = DEFAULT_SENSITIVITY
        analysis_mode = str(self.analysis_mode)
        if analysis_mode not in ANALYSIS_MODES:
            analysis_mode = DEFAULT_ANALYSIS_MODE
        cleanup_profile = str(self.cleanup_profile)
        if cleanup_profile not in CLEANUP_PROFILES:
            cleanup_profile = DEFAULT_CLEANUP_PROFILE
        object.__setattr__(self, "cache_key", str(self.cache_key or ""))
        object.__setattr__(
            self, "analysis_fingerprint", str(self.analysis_fingerprint or "")
        )
        object.__setattr__(self, "region", _normalise_region(self.region))
        object.__setattr__(self, "analysis_mode", analysis_mode)
        object.__setattr__(self, "sensitivity", sensitivity)
        object.__setattr__(self, "cleanup_profile", cleanup_profile)
        object.__setattr__(
            self,
            "selected_candidate_ids",
            frozenset(
                candidate_id
                for value in self.selected_candidate_ids
                if (candidate_id := _valid_candidate_id(value)) is not None
            ),
        )
        object.__setattr__(
            self,
            "rejected_candidate_ids",
            frozenset(
                candidate_id
                for value in self.rejected_candidate_ids
                if (candidate_id := _valid_candidate_id(value)) is not None
            ),
        )
        rejected = self.rejected_candidate_ids
        applied = {
            route
            for route in self.applied_routes
            if route.candidate_id not in rejected
        }
        pending = {
            route
            for route in self.pending_routes
            if route.candidate_id not in rejected and route not in applied
        }
        object.__setattr__(
            self, "pending_routes", tuple(sorted(pending))
        )
        object.__setattr__(
            self, "applied_routes", tuple(sorted(applied))
        )

    @property
    def reviewed_candidate_ids(self) -> frozenset[str]:
        routed = {
            route.candidate_id
            for route in (*self.pending_routes, *self.applied_routes)
        }
        return self.rejected_candidate_ids.union(routed)

    @property
    def onset_threshold(self) -> float:
        return transcription_thresholds(
            self.sensitivity,
            self.analysis_mode,
        )[0]

    @property
    def frame_threshold(self) -> float:
        return transcription_thresholds(
            self.sensitivity,
            self.analysis_mode,
        )[1]

    def to_payload(self) -> dict[str, object]:
        region_payload = (
            None
            if self.region is None
            else {"start_ms": self.region[0], "end_ms": self.region[1]}
        )
        return {
            "version": TRANSCRIPTION_REVIEW_PAYLOAD_VERSION,
            "cache_key": self.cache_key,
            "analysis_fingerprint": self.analysis_fingerprint,
            "region": region_payload,
            "analysis_mode": self.analysis_mode,
            "sensitivity": self.sensitivity,
            "cleanup_profile": self.cleanup_profile,
            "selected_candidate_ids": sorted(self.selected_candidate_ids),
            "rejected_candidate_ids": sorted(self.rejected_candidate_ids),
            "pending_routes": [
                route.to_payload() for route in self.pending_routes
            ],
            "applied_routes": [
                route.to_payload() for route in self.applied_routes
            ],
        }

    @classmethod
    def from_payload(cls, payload: object) -> "TranscriptionSessionState":
        if not isinstance(payload, Mapping):
            return cls()
        # Unknown future payloads fail closed to an empty review state rather
        # than accidentally routing stale candidate identifiers.
        try:
            version = int(payload.get("version", TRANSCRIPTION_REVIEW_PAYLOAD_VERSION))
        except (TypeError, ValueError, OverflowError):
            return cls()
        if version not in (1, 2, 3, TRANSCRIPTION_REVIEW_PAYLOAD_VERSION):
            return cls()
        return cls(
            cache_key=str(payload.get("cache_key") or ""),
            analysis_fingerprint=str(payload.get("analysis_fingerprint") or ""),
            region=_normalise_region(payload.get("region")),
            analysis_mode=str(
                (
                    payload.get("analysis_mode")
                    if version >= 2
                    else LEGACY_ANALYSIS_MODE
                )
                or (
                    DEFAULT_ANALYSIS_MODE
                    if version >= 2
                    else LEGACY_ANALYSIS_MODE
                )
            ),
            sensitivity=str(payload.get("sensitivity") or DEFAULT_SENSITIVITY),
            cleanup_profile=(
                str(
                    payload.get("cleanup_profile")
                    or DEFAULT_CLEANUP_PROFILE
                )
                if version >= TRANSCRIPTION_REVIEW_PAYLOAD_VERSION
                else LEGACY_CLEANUP_PROFILE
            ),
            selected_candidate_ids=_normalise_ids(
                payload.get("selected_candidate_ids")
            ),
            rejected_candidate_ids=_normalise_ids(
                payload.get("rejected_candidate_ids")
            ),
            pending_routes=_normalise_routes(payload.get("pending_routes")),
            applied_routes=_normalise_routes(payload.get("applied_routes")),
        )


@dataclass(frozen=True, slots=True)
class RouteResult:
    candidate_ids: tuple[str, ...] = ()
    routes: tuple[CandidateRoute, ...] = ()
    skipped_rejected: tuple[str, ...] = ()
    skipped_applied: tuple[str, ...] = ()
    skipped_missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegionReplaceResult:
    added_candidate_ids: tuple[str, ...] = ()
    removed_candidate_ids: tuple[str, ...] = ()
    protected_candidate_ids: tuple[str, ...] = ()
    skipped_duplicate_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateReplaceResult:
    added_candidate_ids: tuple[str, ...] = ()
    removed_candidate_ids: tuple[str, ...] = ()
    protected_candidate_ids: tuple[str, ...] = ()
    skipped_lineage_candidate_ids: tuple[str, ...] = ()

    @property
    def skipped_candidate_ids(self) -> tuple[str, ...]:
        return self.skipped_lineage_candidate_ids


@dataclass(frozen=True, slots=True)
class TranscriptionReviewSnapshot:
    state: TranscriptionSessionState
    candidates: tuple[object, ...]
    annotations: tuple[CandidateAnnotation, ...] = ()


class TranscriptionReviewCommandStack:
    """Bounded undo history independent from the formal project note stack."""

    def __init__(self, limit: int = 100) -> None:
        self.limit = max(1, int(limit))
        self._undo: list[TranscriptionReviewSnapshot] = []
        self._redo: list[TranscriptionReviewSnapshot] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, before: TranscriptionReviewSnapshot) -> None:
        self._undo.append(before)
        del self._undo[:-self.limit]
        self._redo.clear()

    def undo(
        self, current: TranscriptionReviewSnapshot
    ) -> TranscriptionReviewSnapshot | None:
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(
        self, current: TranscriptionReviewSnapshot
    ) -> TranscriptionReviewSnapshot | None:
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def checkpoint(
        self,
    ) -> tuple[
        tuple[TranscriptionReviewSnapshot, ...],
        tuple[TranscriptionReviewSnapshot, ...],
    ]:
        """Freeze list ownership so a failed project commit can restore it."""

        return tuple(self._undo), tuple(self._redo)

    def restore_checkpoint(
        self,
        checkpoint: tuple[
            tuple[TranscriptionReviewSnapshot, ...],
            tuple[TranscriptionReviewSnapshot, ...],
        ],
    ) -> None:
        undo, redo = checkpoint
        self._undo = list(undo[-self.limit:])
        self._redo = list(redo)

    def discard_redo(self) -> None:
        """Invalidate only the abandoned redo branch."""

        self._redo.clear()


class TranscriptionSession:
    """Mutable coordinator for candidates and lightweight review decisions."""

    def __init__(
        self,
        candidates: Iterable[object] = (),
        *,
        cache_key: str = "",
        backend_id: str = "",
        analysis_fingerprint: str = "",
        state: TranscriptionSessionState | None = None,
        annotations: (
            Mapping[str, object] | Iterable[CandidateAnnotation]
        ) = (),
        undo_limit: int = 100,
    ) -> None:
        initial_state = state or TranscriptionSessionState(
            cache_key=str(cache_key),
            analysis_fingerprint=str(analysis_fingerprint),
        )
        self.state = initial_state
        self.backend_id = str(backend_id)
        self._candidates: dict[str, object] = {}
        self._ordered_candidates: tuple[object, ...] = ()
        self._ordered_candidate_ids: tuple[str, ...] = ()
        self._candidate_starts: tuple[float, ...] = ()
        self._candidate_ends: tuple[float, ...] = ()
        self._candidate_prefix_max_ends: tuple[float, ...] = ()
        self._candidate_order: dict[str, int] = {}
        self._candidate_ids_by_identity: dict[int, str] = {}
        self._last_candidate_range_query_inspections = 0
        self._annotations: dict[str, CandidateAnnotation] = {}
        self._ordered_annotations: tuple[CandidateAnnotation, ...] = ()
        self.commands = TranscriptionReviewCommandStack(undo_limit)
        self.set_candidates(
            candidates,
            clear_history=False,
            annotations=annotations,
        )

    @classmethod
    def from_payload(
        cls,
        payload: object,
        candidates: Iterable[object] = (),
        *,
        backend_id: str = "",
        annotations: (
            Mapping[str, object] | Iterable[CandidateAnnotation]
        ) = (),
        undo_limit: int = 100,
    ) -> "TranscriptionSession":
        return cls(
            candidates,
            backend_id=backend_id,
            state=TranscriptionSessionState.from_payload(payload),
            annotations=annotations,
            undo_limit=undo_limit,
        )

    @property
    def candidates(self) -> tuple[object, ...]:
        return self._ordered_candidates

    @property
    def ordered_candidate_ids(self) -> tuple[str, ...]:
        return self._ordered_candidate_ids

    @property
    def last_candidate_range_query_inspections(self) -> int:
        """Number of candidates inspected by the latest indexed range query."""

        return self._last_candidate_range_query_inspections

    @property
    def annotations(self) -> tuple[CandidateAnnotation, ...]:
        return self._ordered_annotations

    @property
    def candidate_annotations(self) -> tuple[CandidateAnnotation, ...]:
        return self.annotations

    def annotation_for_id(self, candidate_id: str) -> CandidateAnnotation | None:
        valid_id = _valid_candidate_id(candidate_id)
        return None if valid_id is None else self._annotations.get(valid_id)

    def to_payload(self) -> dict[str, object]:
        return self.state.to_payload()

    def restore_state(
        self, state: TranscriptionSessionState | Mapping[str, object] | None
    ) -> None:
        """Restore a project-owned sidecar and reset review-only history."""

        candidates = self.candidates
        self.state = (
            state
            if isinstance(state, TranscriptionSessionState)
            else TranscriptionSessionState.from_payload(state)
        )
        self.set_candidates(candidates, clear_history=False)
        self.commands.clear()

    def candidate_id(self, candidate: object) -> str:
        known = self._candidate_ids_by_identity.get(id(candidate))
        if known is not None and self._candidates.get(known) is candidate:
            return known
        return stable_candidate_id(
            candidate,
            cache_key=self.state.cache_key,
            backend_id=self.backend_id,
        )

    def candidate_for_id(self, candidate_id: str) -> object | None:
        return self._candidates.get(str(candidate_id))

    def set_candidates(
        self,
        candidates: Iterable[object],
        *,
        clear_history: bool = True,
        annotations: (
            Mapping[str, object] | Iterable[CandidateAnnotation] | None
        ) = None,
    ) -> None:
        mapped: dict[str, object] = {}
        for candidate in candidates:
            candidate_id = stable_candidate_id(
                candidate,
                cache_key=self.state.cache_key,
                backend_id=self.backend_id,
            )
            mapped.setdefault(candidate_id, candidate)
        supplied_annotations = (
            {}
            if annotations is None
            else _normalise_annotations(annotations)
        )
        previous_annotations = self._annotations
        self._annotations = {
            candidate_id: (
                supplied_annotations.get(candidate_id)
                or (
                    previous_annotations.get(candidate_id)
                    if annotations is None
                    else None
                )
                or _default_candidate_annotation(candidate_id)
            )
            for candidate_id in mapped
        }
        self._candidates = mapped
        measured = [
            (
                candidate_id,
                candidate,
                float(
                    _candidate_value(
                        candidate,
                        "start_ms",
                        "start",
                        default=0.0,
                    )
                ),
                int(_candidate_value(candidate, "pitch", default=0)),
                float(
                    _candidate_value(
                        candidate,
                        "duration_ms",
                        "dur",
                        default=0.0,
                    )
                ),
            )
            for candidate_id, candidate in mapped.items()
        ]
        ordered = sorted(
            measured,
            key=lambda value: (value[2], value[3], value[4], value[0]),
        )
        self._ordered_candidates = tuple(
            value[1] for value in ordered
        )
        self._ordered_candidate_ids = tuple(
            value[0] for value in ordered
        )
        self._candidate_starts = tuple(
            value[2] for value in ordered
        )
        self._candidate_ends = tuple(
            value[2] + value[4] for value in ordered
        )
        prefix_max_ends: list[float] = []
        maximum_end = float("-inf")
        for end_ms in self._candidate_ends:
            maximum_end = max(maximum_end, end_ms)
            prefix_max_ends.append(maximum_end)
        self._candidate_prefix_max_ends = tuple(prefix_max_ends)
        self._candidate_order = {
            value[0]: index for index, value in enumerate(ordered)
        }
        self._ordered_annotations = tuple(
            self._annotations[candidate_id]
            for candidate_id in sorted(self._annotations)
        )
        self._candidate_ids_by_identity = {
            id(candidate): candidate_id
            for candidate_id, candidate in mapped.items()
        }
        if clear_history:
            self.commands.clear()

    def set_analysis_identity(
        self,
        cache_key: str,
        analysis_fingerprint: str = "",
        analysis_mode: str | None = None,
    ) -> None:
        candidates = self.candidates
        self.state = replace(
            self.state,
            cache_key=str(cache_key or ""),
            analysis_fingerprint=str(analysis_fingerprint or ""),
            analysis_mode=(
                self.state.analysis_mode
                if analysis_mode is None
                else str(analysis_mode)
            ),
        )
        self.set_candidates(candidates, clear_history=False)
        self.commands.clear()

    def set_region(
        self, start_ms: float | None, end_ms: float | None = None
    ) -> tuple[float, float] | None:
        region = (
            None
            if start_ms is None or end_ms is None
            else _normalise_region((start_ms, end_ms))
        )
        self.state = replace(self.state, region=region)
        return region

    def clear_region(self) -> None:
        self.set_region(None)

    def set_sensitivity(self, sensitivity: str) -> str:
        value = str(sensitivity)
        if value not in SENSITIVITY_PRESETS:
            raise ValueError(f"unknown transcription sensitivity: {value}")
        self.state = replace(self.state, sensitivity=value)
        return value

    def set_analysis_mode(self, analysis_mode: str) -> str:
        value = str(analysis_mode)
        if value not in ANALYSIS_MODES:
            raise ValueError(
                f"unknown transcription analysis mode: {value}"
            )
        self.state = replace(self.state, analysis_mode=value)
        return value

    def set_cleanup_profile(self, cleanup_profile: str) -> str:
        value = str(cleanup_profile)
        if value not in CLEANUP_PROFILES:
            raise ValueError(
                f"unknown transcription cleanup profile: {value}"
            )
        self.state = replace(self.state, cleanup_profile=value)
        return value

    def set_selection(
        self, candidate_ids: Iterable[str], *, additive: bool = False
    ) -> frozenset[str]:
        valid = {
            candidate_id
            for value in candidate_ids
            if (candidate_id := _valid_candidate_id(value)) in self._candidates
        }
        if additive:
            valid.update(self.state.selected_candidate_ids)
        self.state = replace(self.state, selected_candidate_ids=frozenset(valid))
        return self.state.selected_candidate_ids

    def clear_selection(self) -> None:
        self.state = replace(self.state, selected_candidate_ids=frozenset())

    def _snapshot(self) -> TranscriptionReviewSnapshot:
        return TranscriptionReviewSnapshot(
            self.state,
            self.candidates,
            self.annotations,
        )

    def _restore(self, snapshot: TranscriptionReviewSnapshot) -> None:
        self.state = snapshot.state
        self.set_candidates(
            snapshot.candidates,
            clear_history=False,
            annotations=snapshot.annotations,
        )

    def undo(self) -> bool:
        restored = self.commands.undo(self._snapshot())
        if restored is None:
            return False
        self._restore(restored)
        return True

    def redo(self) -> bool:
        restored = self.commands.redo(self._snapshot())
        if restored is None:
            return False
        self._restore(restored)
        return True

    def _commit_review(
        self,
        new_state: TranscriptionSessionState,
        new_candidates: Mapping[str, object] | None = None,
        new_annotations: (
            Mapping[str, object] | Iterable[CandidateAnnotation] | None
        ) = None,
    ) -> bool:
        # Most review commands only replace the immutable session state.  Keep
        # that hot path O(1): rebuilding and sorting all candidates here made a
        # single reject or route action scale with the full transcription.
        if new_candidates is None and new_annotations is None:
            if new_state == self.state:
                return False
            before = self._snapshot()
            self.state = new_state
            self.commands.push(before)
            return True

        candidate_mapping = self._candidates if new_candidates is None else new_candidates
        annotation_mapping = (
            self._annotations
            if new_annotations is None
            else _normalise_annotations(new_annotations)
        )
        if (
            new_state == self.state
            and dict(candidate_mapping) == self._candidates
            and annotation_mapping == self._annotations
        ):
            return False
        before = self._snapshot()
        self.state = new_state
        self.set_candidates(
            candidate_mapping.values(),
            clear_history=False,
            annotations=annotation_mapping,
        )
        self.commands.push(before)
        return True

    def _candidate_starts_in_region(
        self, candidate: object, region: tuple[float, float]
    ) -> bool:
        start_ms = float(
            _candidate_value(candidate, "start_ms", "start", default=0.0)
        )
        return region[0] <= start_ms < region[1]

    def order_candidate_ids(
        self,
        candidate_ids: Iterable[str],
    ) -> tuple[str, ...]:
        requested = {
            candidate_id
            for value in candidate_ids
            if (candidate_id := _valid_candidate_id(value)) in self._candidates
        }
        return tuple(
            sorted(requested, key=self._candidate_order.__getitem__)
        )

    def candidate_ids_starting_in_project_region(
        self,
        region: tuple[float, float],
        *,
        reference_audio_offset_ms: float = 0.0,
    ) -> tuple[str, ...]:
        """Return candidates whose projected start lies in ``[A, B)``."""

        start_project_ms, end_project_ms = map(float, region)
        if end_project_ms <= start_project_ms:
            self._last_candidate_range_query_inspections = 0
            return ()
        offset_ms = float(reference_audio_offset_ms)
        first = bisect_left(
            self._candidate_starts,
            start_project_ms - offset_ms,
        )
        last = bisect_left(
            self._candidate_starts,
            end_project_ms - offset_ms,
        )
        self._last_candidate_range_query_inspections = max(0, last - first)
        return self._ordered_candidate_ids[first:last]

    def candidate_ids_overlapping_audio_range(
        self,
        start_audio_ms: float,
        end_audio_ms: float,
    ) -> tuple[str, ...]:
        """Return candidates overlapping one audio-time half-open interval."""

        start_ms = float(start_audio_ms)
        end_ms = float(end_audio_ms)
        if end_ms <= start_ms or not self._ordered_candidate_ids:
            self._last_candidate_range_query_inspections = 0
            return ()
        # The monotonic prefix maximum skips every early candidate that is
        # guaranteed to end at or before the requested interval.  The final
        # predicate is still checked because candidate durations may overlap.
        first = bisect_right(self._candidate_prefix_max_ends, start_ms)
        last = bisect_left(self._candidate_starts, end_ms)
        self._last_candidate_range_query_inspections = max(0, last - first)
        return tuple(
            self._ordered_candidate_ids[index]
            for index in range(first, last)
            if self._candidate_ends[index] > start_ms
        )

    def eligible_candidate_ids(
        self,
        *,
        reference_audio_offset_ms: float = 0.0,
        include_routed: bool = False,
    ) -> tuple[str, ...]:
        """Resolve selected-first/A-B review scope in stable candidate order."""

        state = self.state
        if state.selected_candidate_ids:
            self._last_candidate_range_query_inspections = 0
            return self.order_candidate_ids(
                state.selected_candidate_ids.difference(
                    state.rejected_candidate_ids
                )
            )
        if state.region is None:
            self._last_candidate_range_query_inspections = 0
            return ()
        candidates = self.candidate_ids_starting_in_project_region(
            state.region,
            reference_audio_offset_ms=reference_audio_offset_ms,
        )
        routed = (
            set()
            if include_routed
            else {
                route.candidate_id
                for route in (*state.pending_routes, *state.applied_routes)
            }
        )
        return tuple(
            candidate_id
            for candidate_id in candidates
            if candidate_id not in state.rejected_candidate_ids
            and candidate_id not in routed
        )

    def resolve_route_candidate_ids(
        self, candidate_ids: Iterable[str] | None = None
    ) -> tuple[str, ...]:
        """Resolve explicit/selected candidates before falling back to A-B.

        With no explicit or selected candidates, the region fallback only
        returns unrouted, unrejected candidates.  With no region it returns an
        empty tuple, preventing accidental whole-song writes.
        """

        if candidate_ids is None:
            return self.eligible_candidate_ids()
        requested = {
            candidate_id
            for value in candidate_ids or ()
            if (candidate_id := _valid_candidate_id(value)) is not None
        }
        requested.difference_update(self.state.rejected_candidate_ids)
        requested.intersection_update(self._candidates)
        return tuple(
            sorted(requested, key=self._candidate_order.__getitem__)
        )

    def _route_request_ids(
        self, candidate_ids: Iterable[str] | None
    ) -> tuple[str, ...]:
        if candidate_ids is not None:
            requested = {
                candidate_id
                for value in candidate_ids
                if (candidate_id := _valid_candidate_id(value)) is not None
            }
        elif self.state.selected_candidate_ids:
            requested = set(self.state.selected_candidate_ids)
        elif self.state.region is not None:
            routed = {
                route.candidate_id
                for route in (*self.state.pending_routes, *self.state.applied_routes)
            }
            requested = {
                candidate_id
                for candidate_id, candidate in self._candidates.items()
                if candidate_id not in routed
                and self._candidate_starts_in_region(candidate, self.state.region)
            }
        else:
            return ()
        existing = requested.intersection(self._candidates)
        ordered = sorted(existing, key=self._candidate_order.__getitem__)
        ordered.extend(sorted(requested.difference(existing)))
        return tuple(ordered)

    def reject(self, candidate_ids: Iterable[str] | None = None) -> tuple[str, ...]:
        resolved = self.resolve_route_candidate_ids(candidate_ids)
        routed = {
            route.candidate_id
            for route in (*self.state.pending_routes, *self.state.applied_routes)
        }
        rejected = tuple(value for value in resolved if value not in routed)
        if not rejected:
            return ()
        new_state = replace(
            self.state,
            rejected_candidate_ids=self.state.rejected_candidate_ids.union(rejected),
            selected_candidate_ids=self.state.selected_candidate_ids.difference(
                rejected
            ),
        )
        self._commit_review(new_state)
        return rejected

    def restore_rejected(self, candidate_ids: Iterable[str]) -> tuple[str, ...]:
        restored = tuple(
            candidate_id
            for value in candidate_ids
            if (candidate_id := _valid_candidate_id(value))
            in self.state.rejected_candidate_ids
        )
        if not restored:
            return ()
        self._commit_review(
            replace(
                self.state,
                rejected_candidate_ids=self.state.rejected_candidate_ids.difference(
                    restored
                ),
            )
        )
        return restored

    def route_to_track(
        self,
        track_id: int,
        candidate_ids: Iterable[str] | None = None,
        *,
        copy: bool = False,
    ) -> RouteResult:
        target = _normalise_track_id(track_id)
        if target is None:
            raise ValueError("target track id must be non-negative")
        resolved = self._route_request_ids(candidate_ids)
        rejected: list[str] = []
        applied: list[str] = []
        missing: list[str] = []
        accepted: list[str] = []
        pending = set(self.state.pending_routes)
        applied_routes = set(self.state.applied_routes)
        applied_candidate_ids = {
            route.candidate_id for route in applied_routes
        }
        routable: list[str] = []
        for candidate_id in resolved:
            if candidate_id not in self._candidates:
                missing.append(candidate_id)
                continue
            if candidate_id in self.state.rejected_candidate_ids:
                rejected.append(candidate_id)
                continue
            if candidate_id in applied_candidate_ids and not copy:
                applied.append(candidate_id)
                continue
            routable.append(candidate_id)

        # Replace-mode routing removes prior destinations in one pass instead
        # of rebuilding the whole pending set once per selected candidate.
        if routable and not copy:
            routable_ids = set(routable)
            pending = {
                route
                for route in pending
                if route.candidate_id not in routable_ids
            }

        for candidate_id in routable:
            route = CandidateRoute(candidate_id, target)
            if route in pending or route in applied_routes:
                continue
            pending.add(route)
            accepted.append(candidate_id)
        new_state = replace(
            self.state,
            pending_routes=tuple(sorted(pending)),
            selected_candidate_ids=self.state.selected_candidate_ids.difference(
                accepted
            ),
        )
        self._commit_review(new_state)
        routes = tuple(
            CandidateRoute(candidate_id, target) for candidate_id in accepted
        )
        return RouteResult(
            tuple(accepted),
            routes,
            tuple(rejected),
            tuple(applied),
            tuple(missing),
        )

    def remove_pending_routes(
        self, routes: Iterable[CandidateRoute]
    ) -> tuple[CandidateRoute, ...]:
        requested = set(routes)
        removed = tuple(
            route for route in self.state.pending_routes if route in requested
        )
        if removed:
            self._commit_review(
                replace(
                    self.state,
                    pending_routes=tuple(
                        route
                        for route in self.state.pending_routes
                        if route not in requested
                    ),
                )
            )
        return removed

    def mark_routes_applied(
        self, routes: Iterable[CandidateRoute] | None = None
    ) -> tuple[CandidateRoute, ...]:
        """Move pending routes across the formal-project commit boundary.

        This transition intentionally does not enter the review undo stack.
        The caller must capture ``ProjectSnapshot(..., transcription_state)``
        before creating formal notes; project undo then restores both tracks
        and this sidecar atomically.  Clearing review history prevents a later
        review-only undo from desynchronising an already-created formal note.
        """

        requested = (
            set(self.state.pending_routes) if routes is None else set(routes)
        )
        moved = tuple(
            route for route in self.state.pending_routes if route in requested
        )
        if not moved:
            return ()
        self.commit_project_routes(moved)
        return moved

    def commit_project_routes(
        self,
        applied_routes: Iterable[CandidateRoute],
        *,
        pending_routes: Iterable[CandidateRoute] | None = None,
    ) -> tuple[CandidateRoute, ...]:
        """Commit a prevalidated route batch across the project boundary.

        ``applied_routes`` may contain routes staged only in an editor and
        therefore not present in the persisted pending sidecar.  When
        ``pending_routes`` is supplied it is the caller's complete final
        pending set, normally the invalid/orphaned/unresolved routes reported
        by project preflight.  Omitting it preserves every existing pending
        route except the successful batch.

        The state replacement is one deterministic mutation and never enters
        the review-only command stack.  Project code must capture its formal
        track/session snapshot before changing notes and invoking this method;
        clearing review history then prevents review Undo from diverging from
        the committed formal notes.
        """

        committed = _normalise_route_tuple(applied_routes)
        committed_set = set(committed)
        final_pending = (
            set(self.state.pending_routes).difference(committed_set)
            if pending_routes is None
            else set(_normalise_route_tuple(pending_routes))
        )
        final_applied = set(self.state.applied_routes).union(committed_set)
        self.state = replace(
            self.state,
            pending_routes=tuple(sorted(final_pending)),
            applied_routes=tuple(sorted(final_applied)),
        )
        self.commands.clear()
        return tuple(
            route for route in committed if route in self.state.applied_routes
        )

    def orphaned_routes(
        self, valid_track_ids: Iterable[int]
    ) -> tuple[CandidateRoute, ...]:
        valid = {
            track_id
            for value in valid_track_ids
            if (track_id := _normalise_track_id(value)) is not None
        }
        return tuple(
            route
            for route in (*self.state.pending_routes, *self.state.applied_routes)
            if route.track_id not in valid
        )

    @staticmethod
    def _candidate_is_duplicate(
        first: object,
        second: object,
        *,
        onset_tolerance_ms: float,
        overlap_ratio: float,
    ) -> bool:
        if int(_candidate_value(first, "pitch", default=-1)) != int(
            _candidate_value(second, "pitch", default=-2)
        ):
            return False
        first_start = float(
            _candidate_value(first, "start_ms", "start", default=0.0)
        )
        second_start = float(
            _candidate_value(second, "start_ms", "start", default=0.0)
        )
        if abs(first_start - second_start) > onset_tolerance_ms:
            return False
        first_duration = max(
            1.0,
            float(
                _candidate_value(first, "duration_ms", "dur", default=1.0)
            ),
        )
        second_duration = max(
            1.0,
            float(
                _candidate_value(second, "duration_ms", "dur", default=1.0)
            ),
        )
        overlap = max(
            0.0,
            min(first_start + first_duration, second_start + second_duration)
            - max(first_start, second_start),
        )
        return overlap / min(first_duration, second_duration) >= overlap_ratio

    def replace_all_candidates(
        self,
        candidates: Iterable[object],
        *,
        annotations: (
            Mapping[str, object] | Iterable[CandidateAnnotation]
        ) = (),
    ) -> CandidateReplaceResult:
        """Replace the disposable candidate set without overwriting review.

        Every existing rejected, pending, or applied candidate is retained.
        Incoming derived candidates are also skipped when their annotation
        shares any lineage with those protected candidates.  Unreviewed old
        candidates are replaced wholesale, and the transient selection is
        narrowed to candidates that still exist.
        """

        incoming_annotations = _normalise_annotations(annotations)
        incoming: dict[str, object] = {}
        for candidate in candidates:
            candidate_id = stable_candidate_id(
                candidate,
                cache_key=self.state.cache_key,
                backend_id=self.backend_id,
            )
            incoming.setdefault(candidate_id, candidate)

        reviewed_ids = self.state.reviewed_candidate_ids
        protected_ids = {
            candidate_id
            for candidate_id in self._candidates
            if candidate_id in reviewed_ids
        }
        protected_lineages: set[str] = set()
        for candidate_id in reviewed_ids:
            annotation = self._annotations.get(candidate_id)
            if annotation is None:
                protected_lineages.add(candidate_id)
            else:
                protected_lineages.update(annotation.lineage_ids)

        blocked_incoming_ids: set[str] = set()
        retained_source_ids: set[str] = set()
        for candidate_id in incoming:
            annotation = incoming_annotations.get(
                candidate_id,
                CandidateAnnotation(candidate_id),
            )
            if (
                candidate_id in reviewed_ids
                or not annotation.lineage_ids.isdisjoint(
                    protected_lineages
                )
            ):
                blocked_incoming_ids.add(candidate_id)
                retained_source_ids.update(
                    annotation.lineage_ids.intersection(self._candidates)
                )
        protected_ids.update(retained_source_ids)
        updated = {
            candidate_id: self._candidates[candidate_id]
            for candidate_id in protected_ids
        }
        updated_annotations = {
            candidate_id: self._annotations.get(
                candidate_id,
                CandidateAnnotation(candidate_id),
            )
            for candidate_id in protected_ids
        }
        added: list[str] = []
        skipped_lineage: list[str] = []
        for candidate_id, candidate in incoming.items():
            annotation = incoming_annotations.get(
                candidate_id,
                CandidateAnnotation(candidate_id),
            )
            if candidate_id in blocked_incoming_ids:
                skipped_lineage.append(candidate_id)
                continue
            updated[candidate_id] = candidate
            updated_annotations[candidate_id] = annotation
            added.append(candidate_id)

        removed = tuple(
            candidate_id
            for candidate_id in self._candidates
            if candidate_id not in protected_ids
        )
        valid_ids = set(updated)
        new_state = replace(
            self.state,
            selected_candidate_ids=self.state.selected_candidate_ids.intersection(
                valid_ids
            ),
        )
        self._commit_review(
            new_state,
            updated,
            updated_annotations,
        )
        return CandidateReplaceResult(
            tuple(sorted(added)),
            tuple(sorted(removed)),
            tuple(sorted(protected_ids)),
            tuple(sorted(skipped_lineage)),
        )

    def replace_region_candidates(
        self,
        candidates: Iterable[object],
        start_ms: float | None = None,
        end_ms: float | None = None,
        *,
        onset_tolerance_ms: float = 40.0,
        overlap_ratio: float = 0.5,
        annotations: (
            Mapping[str, object] | Iterable[CandidateAnnotation]
        ) = (),
    ) -> RegionReplaceResult:
        """Replace only unreviewed candidates whose onsets are in A-B.

        Rejected, pending, and applied candidates are protected.  Incoming
        candidates are deduplicated against every survivor by pitch, onset,
        and duration overlap so local decoding cannot stack near-identical
        notes over reviewed or boundary candidates.
        """

        region = (
            self.state.region
            if start_ms is None or end_ms is None
            else _normalise_region((start_ms, end_ms))
        )
        if region is None:
            raise ValueError("region replacement requires a non-empty A-B range")
        onset_tolerance_ms = max(0.0, float(onset_tolerance_ms))
        overlap_ratio = max(0.0, min(1.0, float(overlap_ratio)))
        reviewed = self.state.reviewed_candidate_ids
        incoming_annotations = _normalise_annotations(annotations)
        incoming = sorted(
            candidates,
            key=lambda candidate: (
                float(
                    _candidate_value(
                        candidate,
                        "start_ms",
                        "start",
                        default=0.0,
                    )
                ),
                int(_candidate_value(candidate, "pitch", default=0)),
            ),
        )
        incoming_with_metadata_items: list[
            tuple[str, object, CandidateAnnotation]
        ] = []
        for candidate in incoming:
            candidate_id = self.candidate_id(candidate)
            incoming_with_metadata_items.append(
                (
                    candidate_id,
                    candidate,
                    incoming_annotations.get(
                        candidate_id,
                        CandidateAnnotation(candidate_id),
                    ),
                )
            )
        incoming_with_metadata = tuple(incoming_with_metadata_items)
        protected_lineages: set[str] = set()
        for candidate_id in reviewed:
            annotation = self._annotations.get(candidate_id)
            if annotation is None:
                protected_lineages.add(candidate_id)
            else:
                protected_lineages.update(annotation.lineage_ids)
        blocked_incoming_ids = {
            candidate_id
            for candidate_id, _candidate, annotation
            in incoming_with_metadata
            if (
                candidate_id in reviewed
                or not annotation.lineage_ids.isdisjoint(
                    protected_lineages
                )
            )
        }
        retained_source_ids = {
            lineage_id
            for candidate_id, _candidate, annotation
            in incoming_with_metadata
            if candidate_id in blocked_incoming_ids
            for lineage_id in annotation.lineage_ids
            if lineage_id in self._candidates
        }
        protected = tuple(
            candidate_id
            for candidate_id, candidate in self._candidates.items()
            if (
                candidate_id in reviewed
                or candidate_id in retained_source_ids
            )
            and self._candidate_starts_in_region(candidate, region)
        )
        protected_set = set(protected)
        removed = tuple(
            candidate_id
            for candidate_id, candidate in self._candidates.items()
            if candidate_id not in protected_set
            and self._candidate_starts_in_region(candidate, region)
        )
        removed_set = set(removed)
        updated = {
            candidate_id: candidate
            for candidate_id, candidate in self._candidates.items()
            if candidate_id not in removed_set
        }
        updated_annotations = {
            candidate_id: self._annotations.get(
                candidate_id,
                CandidateAnnotation(candidate_id),
            )
            for candidate_id in updated
        }
        # Region re-decodes can contain thousands of candidates. Comparing
        # each incoming note with every survivor makes this path O(N*M) and
        # blocks the GUI when the worker result is committed. Pitch/onset
        # buckets narrow the exact same duplicate predicate to the only notes
        # that can possibly fall inside the onset tolerance.
        duplicate_bucket_width = max(1.0, onset_tolerance_ms)
        duplicate_buckets: dict[tuple[int, int], list[object]] | None = (
            {} if math.isfinite(onset_tolerance_ms) else None
        )

        def duplicate_bucket_position(
            candidate: object,
        ) -> tuple[int, float] | None:
            try:
                pitch = int(
                    _candidate_value(candidate, "pitch", default=-1)
                )
                start = float(
                    _candidate_value(
                        candidate,
                        "start_ms",
                        "start",
                        default=0.0,
                    )
                )
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(start):
                return None
            return pitch, start

        def index_duplicate_candidate(candidate: object) -> None:
            if duplicate_buckets is None:
                return
            position = duplicate_bucket_position(candidate)
            if position is None:
                return
            pitch, start = position
            bucket = math.floor(start / duplicate_bucket_width)
            duplicate_buckets.setdefault((pitch, bucket), []).append(
                candidate
            )

        def has_duplicate(candidate: object) -> bool:
            position = duplicate_bucket_position(candidate)
            if duplicate_buckets is None or position is None:
                return any(
                    self._candidate_is_duplicate(
                        candidate,
                        survivor,
                        onset_tolerance_ms=onset_tolerance_ms,
                        overlap_ratio=overlap_ratio,
                    )
                    for survivor in updated.values()
                )
            pitch, start = position
            first_bucket = math.floor(
                (start - onset_tolerance_ms) / duplicate_bucket_width
            )
            last_bucket = math.floor(
                (start + onset_tolerance_ms) / duplicate_bucket_width
            )
            return any(
                self._candidate_is_duplicate(
                    candidate,
                    survivor,
                    onset_tolerance_ms=onset_tolerance_ms,
                    overlap_ratio=overlap_ratio,
                )
                for bucket in range(first_bucket, last_bucket + 1)
                for survivor in duplicate_buckets.get((pitch, bucket), ())
            )

        for survivor in updated.values():
            index_duplicate_candidate(survivor)

        added: list[str] = []
        duplicates: list[str] = []
        for candidate_id, candidate, annotation in incoming_with_metadata:
            if not self._candidate_starts_in_region(candidate, region):
                continue
            if candidate_id in blocked_incoming_ids:
                duplicates.append(candidate_id)
                continue
            if candidate_id in updated or has_duplicate(candidate):
                duplicates.append(candidate_id)
                continue
            updated[candidate_id] = candidate
            updated_annotations[candidate_id] = annotation
            index_duplicate_candidate(candidate)
            added.append(candidate_id)
        valid_ids = set(updated)
        new_state = replace(
            self.state,
            selected_candidate_ids=self.state.selected_candidate_ids.intersection(
                valid_ids
            ),
        )
        self._commit_review(
            new_state,
            updated,
            updated_annotations,
        )
        return RegionReplaceResult(
            tuple(added),
            tuple(removed),
            tuple(sorted(protected)),
            tuple(duplicates),
        )


__all__ = [
    "ANALYSIS_MODES",
    "CLEANUP_PROFILES",
    "CandidateAnnotation",
    "CandidateReplaceResult",
    "CandidateRoute",
    "DEFAULT_ANALYSIS_MODE",
    "DEFAULT_CLEANUP_PROFILE",
    "DEFAULT_SENSITIVITY",
    "LEGACY_CLEANUP_PROFILE",
    "RegionReplaceResult",
    "RouteResult",
    "SENSITIVITY_PRESETS",
    "StagedCandidateRoute",
    "TRANSCRIPTION_REVIEW_PAYLOAD_VERSION",
    "TranscriptionEditorCommit",
    "TranscriptionEditorCommitReport",
    "TranscriptionReviewCommandStack",
    "TranscriptionReviewSnapshot",
    "TranscriptionSession",
    "TranscriptionSessionState",
    "stable_candidate_id",
]
