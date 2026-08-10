"""Pure planning for note-editor drafts crossing into the formal project."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from bdo_midi import Note
from bdo_music_composer.transcription.bdo_transcription_session import (
    CandidateRoute,
    TranscriptionEditorCommitReport,
)
from bdo_music_composer.transcription.bdo_transcription_policy import CANDIDATE_NOTE_POLICY
from bdo_music_composer.editor.editor_models import game_supported_pitches


class CandidateView(Protocol):
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float


class CommitPlanErrorCode(str, Enum):
    CURRENT_TRACK_MISSING = "current_track_missing"
    DUPLICATE_TRACK_ID = "duplicate_track_id"
    DUPLICATE_CANDIDATE_ID = "duplicate_candidate_id"
    INVALID_CANDIDATE = "invalid_candidate"
    UNKNOWN_PROVISIONAL_TRACK = "unknown_provisional_track"
    CONFLICTING_NEW_TRACK_STATE = "conflicting_new_track_state"


class CommitPlanError(ValueError):
    """Stable preflight failure raised before any project mutation."""

    def __init__(self, code: CommitPlanErrorCode, detail: str = "") -> None:
        self.code = code
        self.detail = str(detail)
        super().__init__(f"{code.value}: {self.detail}".rstrip())


@dataclass(frozen=True, slots=True)
class CommitCandidateView:
    """Detached candidate values consumed by the pure commit planner."""

    candidate_id: str
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float

    @classmethod
    def capture(
        cls,
        candidate_id: object,
        candidate: object,
    ) -> "CommitCandidateView":
        stable_id = str(candidate_id or "").strip()
        if not stable_id:
            raise CommitPlanError(
                CommitPlanErrorCode.INVALID_CANDIDATE,
                "candidate id is empty",
            )
        try:
            return cls(
                candidate_id=stable_id,
                pitch=int(getattr(candidate, "pitch")),
                velocity=int(getattr(candidate, "velocity")),
                start_ms=float(getattr(candidate, "start_ms")),
                duration_ms=float(getattr(candidate, "duration_ms")),
            )
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            raise CommitPlanError(
                CommitPlanErrorCode.INVALID_CANDIDATE,
                stable_id,
            ) from exc


@dataclass(frozen=True, slots=True)
class CommitCandidateRecord:
    """Preserve candidate existence even when its musical fields are bad."""

    candidate_id: str
    candidate: CommitCandidateView | None

    @classmethod
    def capture(
        cls,
        candidate_id: object,
        candidate: object,
    ) -> "CommitCandidateRecord":
        stable_id = str(candidate_id or "").strip()
        if not stable_id:
            raise CommitPlanError(
                CommitPlanErrorCode.INVALID_CANDIDATE,
                "candidate id is empty",
            )
        try:
            view = CommitCandidateView.capture(stable_id, candidate)
        except CommitPlanError as exc:
            if exc.code is not CommitPlanErrorCode.INVALID_CANDIDATE:
                raise
            view = None
        return cls(stable_id, view)


@dataclass(frozen=True, slots=True)
class CommitTrackView:
    track_id: int
    notes: tuple[Note, ...]
    instrument_id: int
    marnian_synth_mode: str
    is_percussion: bool
    effective_transpose: int
    has_legacy_articulation: bool = False

    @classmethod
    def from_track(
        cls,
        track: object,
        *,
        effective_transpose: int,
    ) -> "CommitTrackView":
        return cls(
            track_id=int(getattr(track, "track_id")),
            notes=tuple(getattr(track, "notes", ())),
            instrument_id=int(getattr(track, "bdo_instrument_id")),
            marnian_synth_mode=str(
                getattr(track, "marnian_synth_mode", "basic") or "basic"
            ),
            is_percussion=bool(getattr(track, "is_percussion", False)),
            effective_transpose=int(effective_transpose),
            has_legacy_articulation=(
                getattr(track, "articulation_type", None) is not None
            ),
        )


@dataclass(frozen=True, slots=True)
class CommitPlanInput:
    current_track_id: int
    draft_notes: tuple[Note, ...]
    local_routes: tuple[CandidateRoute, ...]
    pending_routes: tuple[CandidateRoute, ...]
    applied_routes: tuple[CandidateRoute, ...]
    rejected_candidate_ids: frozenset[str]
    candidates: tuple[CommitCandidateRecord, ...]
    tracks: tuple[CommitTrackView, ...]
    failed_new_track_ids: frozenset[int]
    provisional_new_track_ids: frozenset[int]
    request_cache_key: str
    request_fingerprint: str
    session_cache_key: str
    session_fingerprint: str
    reference_audio_offset_ms: float


@dataclass(frozen=True, slots=True)
class TranscriptionCommitPlan:
    final_notes_by_track: tuple[tuple[int, tuple[Note, ...]], ...]
    created_track_ids: tuple[int, ...]
    successful_routes: tuple[CandidateRoute, ...]
    final_pending_routes: tuple[CandidateRoute, ...]
    final_applied_routes: tuple[CandidateRoute, ...]
    created_routes: tuple[CandidateRoute, ...]
    satisfied_routes: tuple[CandidateRoute, ...]
    invalid_routes: tuple[CandidateRoute, ...]
    orphaned_routes: tuple[CandidateRoute, ...]
    unresolved_routes: tuple[CandidateRoute, ...]
    clear_legacy_articulation: bool
    sidecar_changed: bool
    project_changed: bool

    def report(self) -> TranscriptionEditorCommitReport:
        return TranscriptionEditorCommitReport(
            self.created_routes,
            self.satisfied_routes,
            self.invalid_routes,
            self.orphaned_routes,
            self.unresolved_routes,
            self.project_changed,
        )


def _note_sort_key(note: Note) -> tuple[float, int, float, int, int]:
    return (
        float(note.start),
        int(note.pitch),
        float(note.dur),
        int(note.vel),
        int(note.ntype),
    )


class _PlanningIndexes:
    """Mutable indexes private to one otherwise pure planning invocation."""

    def __init__(
        self,
        draft_notes: tuple[Note, ...],
        current_notes: tuple[Note, ...],
        offset_ms: float,
    ) -> None:
        self.draft_notes = draft_notes
        self.offset_ms = float(offset_ms)
        self.unused_draft_indices = set(range(len(draft_notes)))
        self.blocked_draft_indices: set[int] = set()
        baseline_counts = Counter(current_notes)
        self.nonbaseline_draft_indices: set[int] = set()
        for index, note in enumerate(draft_notes):
            if baseline_counts[note] > 0:
                baseline_counts[note] -= 1
            else:
                self.nonbaseline_draft_indices.add(index)

        grouped_draft: dict[int, list[int]] = defaultdict(list)
        for index, note in enumerate(draft_notes):
            grouped_draft[int(note.pitch)].append(index)
        self.draft_by_pitch: dict[int, tuple[list[float], list[int]]] = {}
        for pitch, indices in grouped_draft.items():
            ordered = sorted(indices, key=lambda item: float(draft_notes[item].start))
            self.draft_by_pitch[pitch] = (
                [float(draft_notes[item].start) for item in ordered],
                ordered,
            )

        self.formal_by_track: dict[
            int,
            dict[int, tuple[list[float], list[Note]]],
        ] = {}

    def _formal_index(
        self,
        track: CommitTrackView,
    ) -> dict[int, tuple[list[float], list[Note]]]:
        cached = self.formal_by_track.get(track.track_id)
        if cached is not None:
            return cached
        grouped: dict[int, list[Note]] = defaultdict(list)
        for note in track.notes:
            grouped[int(note.pitch)].append(note)
        cached = {}
        for pitch, notes in grouped.items():
            ordered = sorted(notes, key=lambda note: float(note.start))
            cached[pitch] = (
                [float(note.start) for note in ordered],
                ordered,
            )
        self.formal_by_track[track.track_id] = cached
        return cached

    def matching_formal_notes(
        self,
        candidate: CandidateView,
        track: CommitTrackView,
    ) -> list[Note]:
        starts, notes = self._formal_index(track).get(
            int(candidate.pitch),
            ([], []),
        )
        window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
            candidate,
            self.offset_ms,
        )
        first = bisect_left(starts, window_start)
        last = bisect_right(starts, window_end)
        return [
            note
            for note in notes[first:last]
            if CANDIDATE_NOTE_POLICY.matches_note(
                candidate,
                note,
                self.offset_ms,
            )
        ]

    def best_draft_match(
        self,
        candidate: CandidateView,
        *,
        allowed_indices: set[int] | None = None,
    ) -> int | None:
        starts, indices = self.draft_by_pitch.get(
            int(candidate.pitch),
            ([], []),
        )
        project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
            candidate,
            self.offset_ms,
        )
        window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
            candidate,
            self.offset_ms,
        )
        first = bisect_left(starts, window_start)
        last = bisect_right(starts, window_end)
        matches = [
            index
            for index in indices[first:last]
            if index in self.unused_draft_indices
            if allowed_indices is None or index in allowed_indices
            if CANDIDATE_NOTE_POLICY.matches_note(
                candidate,
                self.draft_notes[index],
                self.offset_ms,
            )
        ]
        if not matches:
            return None
        return min(
            matches,
            key=lambda index: (
                abs(float(self.draft_notes[index].start) - project_start),
                abs(
                    float(self.draft_notes[index].dur)
                    - CANDIDATE_NOTE_POLICY.note_duration_ms(candidate)
                ),
                index,
            ),
        )

    def block_nonbaseline_draft(self, candidate: CandidateView) -> None:
        match_index = self.best_draft_match(
            candidate,
            allowed_indices=self.nonbaseline_draft_indices,
        )
        if match_index is None:
            return
        self.blocked_draft_indices.add(match_index)
        self.unused_draft_indices.discard(match_index)
        self.nonbaseline_draft_indices.discard(match_index)

    def add_formal_note(
        self,
        track: CommitTrackView,
        note: Note,
    ) -> None:
        starts, notes = self._formal_index(track).setdefault(
            int(note.pitch),
            ([], []),
        )
        insertion = bisect_right(starts, float(note.start))
        starts.insert(insertion, float(note.start))
        notes.insert(insertion, note)

    def committed_draft_notes(self) -> tuple[Note, ...]:
        return tuple(
            note
            for index, note in enumerate(self.draft_notes)
            if index not in self.blocked_draft_indices
        )


def _candidate_invalid_for_track(
    candidate: CandidateView,
    track: CommitTrackView,
    offset_ms: float,
) -> bool:
    if not CANDIDATE_NOTE_POLICY.project_timing_is_valid(candidate, offset_ms):
        return True
    supported = game_supported_pitches(
        track.instrument_id,
        track.marnian_synth_mode,
    )
    return not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
        candidate.pitch,
        is_percussion=track.is_percussion,
        instrument_id=track.instrument_id,
        transpose=track.effective_transpose,
        supported_pitches=supported,
    )


def _route_tuple(values: set[CandidateRoute]) -> tuple[CandidateRoute, ...]:
    return tuple(sorted(values))


@dataclass(slots=True)
class _RouteClassification:
    """Mutable scratch state that never escapes a planning invocation."""

    created: set[CandidateRoute] = field(default_factory=set)
    satisfied: set[CandidateRoute] = field(default_factory=set)
    invalid: set[CandidateRoute] = field(default_factory=set)
    orphaned: set[CandidateRoute] = field(default_factory=set)
    unresolved: set[CandidateRoute] = field(default_factory=set)
    successful: set[CandidateRoute] = field(default_factory=set)
    additions: dict[int, list[Note]] = field(
        default_factory=lambda: defaultdict(list)
    )


@dataclass(slots=True)
class _PlanningContext:
    request: CommitPlanInput
    current_track: CommitTrackView
    tracks_by_id: dict[int, CommitTrackView]
    candidates_by_id: dict[str, CommitCandidateRecord]
    local_routes: set[CandidateRoute]
    old_applied: set[CandidateRoute]
    identity_valid: bool
    indexes: _PlanningIndexes
    result: _RouteClassification = field(default_factory=_RouteClassification)


def _block_local_current_candidate(
    context: _PlanningContext,
    route: CandidateRoute,
    candidate: CandidateView | None,
    *,
    is_local: bool,
) -> None:
    if (
        is_local
        and candidate is not None
        and route.track_id == context.current_track.track_id
    ):
        context.indexes.block_nonbaseline_draft(candidate)


def _record_invalid_route(
    context: _PlanningContext,
    route: CandidateRoute,
    candidate: CandidateView | None,
    *,
    is_local: bool,
) -> None:
    context.result.invalid.add(route)
    if not is_local:
        return
    context.result.unresolved.add(route)
    _block_local_current_candidate(
        context,
        route,
        candidate,
        is_local=True,
    )


def _classify_valid_route(
    context: _PlanningContext,
    route: CandidateRoute,
    candidate: CandidateView,
    target: CommitTrackView,
    *,
    is_local: bool,
) -> None:
    if target.track_id == context.current_track.track_id:
        match_index = context.indexes.best_draft_match(candidate)
        if match_index is None:
            if is_local:
                context.result.unresolved.add(route)
            return
        context.indexes.unused_draft_indices.remove(match_index)
        destination = (
            context.result.satisfied
            if context.indexes.matching_formal_notes(candidate, target)
            else context.result.created
        )
        destination.add(route)
        context.result.successful.add(route)
        return
    if context.indexes.matching_formal_notes(candidate, target):
        context.result.satisfied.add(route)
        context.result.successful.add(route)
        return
    addition = CANDIDATE_NOTE_POLICY.to_note(
        candidate,
        context.request.reference_audio_offset_ms,
    )
    context.result.additions[target.track_id].append(addition)
    context.indexes.add_formal_note(target, addition)
    context.result.created.add(route)
    context.result.successful.add(route)


def _classify_route(
    context: _PlanningContext,
    route: CandidateRoute,
) -> None:
    is_local = route in context.local_routes
    candidate_record = context.candidates_by_id.get(route.candidate_id)
    candidate = (
        candidate_record.candidate
        if candidate_record is not None
        else None
    )
    if (
        candidate_record is not None
        and route.candidate_id in context.request.rejected_candidate_ids
    ):
        _record_invalid_route(
            context,
            route,
            candidate,
            is_local=is_local,
        )
        return
    if is_local and route.track_id in context.request.failed_new_track_ids:
        _record_invalid_route(
            context,
            route,
            candidate,
            is_local=True,
        )
        return
    if route in context.old_applied:
        context.result.satisfied.add(route)
        context.result.successful.add(route)
        return
    if is_local and not context.identity_valid:
        context.result.unresolved.add(route)
        _block_local_current_candidate(
            context,
            route,
            candidate,
            is_local=True,
        )
        return
    target = context.tracks_by_id.get(route.track_id)
    if target is None or candidate_record is None:
        context.result.orphaned.add(route)
        if is_local:
            context.result.unresolved.add(route)
        return
    if candidate is None:
        _record_invalid_route(
            context,
            route,
            None,
            is_local=is_local,
        )
        return
    if _candidate_invalid_for_track(
        candidate,
        target,
        context.request.reference_audio_offset_ms,
    ):
        _record_invalid_route(
            context,
            route,
            candidate,
            is_local=is_local,
        )
        return
    _classify_valid_route(
        context,
        route,
        candidate,
        target,
        is_local=is_local,
    )


def _final_notes_by_track(
    context: _PlanningContext,
) -> dict[int, tuple[Note, ...]]:
    final_notes = {
        context.current_track.track_id:
        context.indexes.committed_draft_notes(),
    }
    for track_id, new_notes in context.result.additions.items():
        final_notes[track_id] = tuple(sorted(
            (*context.tracks_by_id[track_id].notes, *new_notes),
            key=_note_sort_key,
        ))
    return final_notes


def _build_commit_plan(
    context: _PlanningContext,
    old_pending: set[CandidateRoute],
) -> TranscriptionCommitPlan:
    result = context.result
    final_pending = old_pending.difference(result.successful)
    final_applied = context.old_applied.union(result.successful)
    final_notes = _final_notes_by_track(context)
    created_track_ids = tuple(sorted(
        track_id
        for track_id in context.request.provisional_new_track_ids
        if final_notes.get(track_id)
    ))
    notes_changed = any(
        context.tracks_by_id[track_id].notes != notes
        for track_id, notes in final_notes.items()
    )
    sidecar_changed = (
        final_pending != old_pending
        or final_applied != context.old_applied
    )
    project_changed = bool(
        notes_changed
        or context.current_track.has_legacy_articulation
        or sidecar_changed
        or created_track_ids
    )
    return TranscriptionCommitPlan(
        final_notes_by_track=tuple(sorted(final_notes.items())),
        created_track_ids=created_track_ids,
        successful_routes=_route_tuple(result.successful),
        final_pending_routes=_route_tuple(final_pending),
        final_applied_routes=_route_tuple(final_applied),
        created_routes=_route_tuple(result.created),
        satisfied_routes=_route_tuple(result.satisfied),
        invalid_routes=_route_tuple(result.invalid),
        orphaned_routes=_route_tuple(result.orphaned),
        unresolved_routes=_route_tuple(result.unresolved),
        clear_legacy_articulation=(
            context.current_track.has_legacy_articulation
        ),
        sidecar_changed=sidecar_changed,
        project_changed=project_changed,
    )


def _track_map(request: CommitPlanInput) -> dict[int, CommitTrackView]:
    tracks_by_id: dict[int, CommitTrackView] = {}
    for track in request.tracks:
        if track.track_id in tracks_by_id:
            raise CommitPlanError(
                CommitPlanErrorCode.DUPLICATE_TRACK_ID,
                str(track.track_id),
            )
        tracks_by_id[track.track_id] = track
    return tracks_by_id


def _candidate_map(
    request: CommitPlanInput,
) -> dict[str, CommitCandidateRecord]:
    candidates_by_id: dict[str, CommitCandidateRecord] = {}
    for record in request.candidates:
        if not record.candidate_id:
            raise CommitPlanError(
                CommitPlanErrorCode.INVALID_CANDIDATE,
                "candidate id is empty",
            )
        if record.candidate_id in candidates_by_id:
            raise CommitPlanError(
                CommitPlanErrorCode.DUPLICATE_CANDIDATE_ID,
                record.candidate_id,
            )
        candidates_by_id[record.candidate_id] = record
    return candidates_by_id


def _validate_provisional_tracks(
    request: CommitPlanInput,
    tracks_by_id: dict[int, CommitTrackView],
) -> None:
    overlap = request.failed_new_track_ids.intersection(
        request.provisional_new_track_ids
    )
    if overlap or request.current_track_id in request.provisional_new_track_ids:
        detail = ",".join(str(value) for value in sorted(overlap))
        raise CommitPlanError(
            CommitPlanErrorCode.CONFLICTING_NEW_TRACK_STATE,
            detail or str(request.current_track_id),
        )
    unknown = request.provisional_new_track_ids.difference(tracks_by_id)
    if unknown:
        raise CommitPlanError(
            CommitPlanErrorCode.UNKNOWN_PROVISIONAL_TRACK,
            ",".join(str(value) for value in sorted(unknown)),
        )


def plan_transcription_commit(
    request: CommitPlanInput,
) -> TranscriptionCommitPlan:
    """Classify routes and calculate formal writes without mutating inputs."""

    tracks_by_id = _track_map(request)
    current_track = tracks_by_id.get(int(request.current_track_id))
    if current_track is None:
        raise CommitPlanError(
            CommitPlanErrorCode.CURRENT_TRACK_MISSING,
            str(request.current_track_id),
        )
    _validate_provisional_tracks(request, tracks_by_id)
    candidates_by_id = _candidate_map(request)

    old_pending = set(request.pending_routes)
    old_applied = set(request.applied_routes)
    local_routes = set(request.local_routes)
    context = _PlanningContext(
        request=request,
        current_track=current_track,
        tracks_by_id=tracks_by_id,
        candidates_by_id=candidates_by_id,
        local_routes=local_routes,
        old_applied=old_applied,
        identity_valid=(
            str(request.request_cache_key or "")
            == str(request.session_cache_key or "")
            and str(request.request_fingerprint or "")
            == str(request.session_fingerprint or "")
        ),
        indexes=_PlanningIndexes(
            request.draft_notes,
            current_track.notes,
            request.reference_audio_offset_ms,
        ),
    )
    for route in sorted(old_pending.union(local_routes)):
        _classify_route(context, route)
    return _build_commit_plan(context, old_pending)


__all__ = [
    "CommitCandidateRecord",
    "CommitCandidateView",
    "CommitPlanInput",
    "CommitPlanError",
    "CommitPlanErrorCode",
    "CommitTrackView",
    "TranscriptionCommitPlan",
    "plan_transcription_commit",
]
