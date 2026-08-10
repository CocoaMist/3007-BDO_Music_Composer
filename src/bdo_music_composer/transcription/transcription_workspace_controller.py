"""Qt-free transcription worker lifecycle and mixed review command state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Generic, Literal, Protocol, TypeVar


ReviewStateT = TypeVar("ReviewStateT")


class CandidateReviewSession(Protocol):
    state: object
    ordered_candidate_ids: tuple[str, ...]

    def order_candidate_ids(
        self,
        candidate_ids: Iterable[str],
    ) -> tuple[str, ...]: ...

    def candidate_ids_starting_in_project_region(
        self,
        region: tuple[float, float],
        *,
        reference_audio_offset_ms: float = 0.0,
    ) -> tuple[str, ...]: ...

    def eligible_candidate_ids(
        self,
        *,
        reference_audio_offset_ms: float = 0.0,
        include_routed: bool = False,
    ) -> tuple[str, ...]: ...

    def annotation_for_id(self, candidate_id: str) -> object | None: ...


@dataclass(frozen=True, slots=True)
class CandidateReviewPlan:
    kind: Literal["eligible", "reject", "restore", "select_fragments"]
    source: Literal["selection", "region", "all", "none"]
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssistRestartRequest:
    harmony_only: bool
    allow_review_recovery: bool


@dataclass(slots=True)
class TranscriptionAnalysisCoordinator:
    """Own worker generations and coalesced assist-analysis restarts."""

    workspace_generation: int = 0
    assist_generation: int = 0
    assist_restart_pending: bool = False
    assist_restart_harmony_only: bool = False
    assist_restart_allow_review_recovery: bool = True

    def next_workspace_generation(self) -> int:
        self.workspace_generation += 1
        return self.workspace_generation

    def next_assist_generation(self) -> int:
        self.assist_generation += 1
        return self.assist_generation

    def is_current_workspace(self, generation: int) -> bool:
        return int(generation) == self.workspace_generation

    def is_current_assist(self, generation: int) -> bool:
        return int(generation) == self.assist_generation

    def invalidate_all(self) -> None:
        self.next_workspace_generation()
        self.next_assist_generation()
        self.clear_assist_restart()

    def queue_assist_restart(
        self,
        *,
        harmony_only: bool,
        allow_review_recovery: bool,
    ) -> AssistRestartRequest:
        if self.assist_restart_pending:
            harmony_only = bool(
                self.assist_restart_harmony_only and harmony_only
            )
            allow_review_recovery = bool(
                self.assist_restart_allow_review_recovery
                and allow_review_recovery
            )
        request = AssistRestartRequest(
            bool(harmony_only),
            bool(allow_review_recovery),
        )
        self.assist_restart_pending = True
        self.assist_restart_harmony_only = request.harmony_only
        self.assist_restart_allow_review_recovery = (
            request.allow_review_recovery
        )
        return request

    def clear_assist_restart(self) -> None:
        self.assist_restart_pending = False
        self.assist_restart_harmony_only = False
        self.assist_restart_allow_review_recovery = True

    def consume_assist_restart(self) -> AssistRestartRequest | None:
        if not self.assist_restart_pending:
            return None
        request = AssistRestartRequest(
            self.assist_restart_harmony_only,
            self.assist_restart_allow_review_recovery,
        )
        self.clear_assist_restart()
        return request


@dataclass(slots=True)
class TranscriptionReviewController(Generic[ReviewStateT]):
    """Own the bounded mixed session/assist review command history.

    Session commands retain their domain-specific undo stack.  This controller
    records how those commands interleave with immutable assist-review
    snapshots, so the Qt host only has to execute the selected command and
    refresh the presentation.
    """

    history_limit: int = 100
    assist_undo: list[ReviewStateT] = field(default_factory=list)
    assist_redo: list[ReviewStateT] = field(default_factory=list)
    action_undo: list[str] = field(default_factory=list)
    action_redo: list[str] = field(default_factory=list)

    @staticmethod
    def _action_kind(kind: str) -> str:
        value = str(kind)
        if value not in {"session", "assist"}:
            raise ValueError("unknown transcription review action")
        return value

    def _append_bounded(self, values: list, value: object) -> None:
        values.append(value)
        del values[:-max(1, int(self.history_limit))]

    def record_action(self, kind: str) -> str:
        value = self._action_kind(kind)
        if value == "session":
            # A new session edit abandons an undone assist-review branch.
            self.assist_redo.clear()
        self._append_bounded(self.action_undo, value)
        self.action_redo.clear()
        return value

    def record_assist_change(self, previous: ReviewStateT) -> None:
        self._append_bounded(self.assist_undo, previous)
        self.assist_redo.clear()
        self.record_action("assist")

    def take_undo_action(self) -> str:
        return self.action_undo.pop() if self.action_undo else "session"

    def take_redo_action(self) -> str:
        return self.action_redo.pop() if self.action_redo else "session"

    def undo_assist(
        self,
        current: ReviewStateT,
    ) -> tuple[bool, ReviewStateT]:
        if not self.assist_undo:
            return False, current
        self._append_bounded(self.assist_redo, current)
        return True, self.assist_undo.pop()

    def redo_assist(
        self,
        current: ReviewStateT,
    ) -> tuple[bool, ReviewStateT]:
        if not self.assist_redo:
            return False, current
        self._append_bounded(self.assist_undo, current)
        return True, self.assist_redo.pop()

    def complete_undo(self, kind: str) -> None:
        self._append_bounded(self.action_redo, self._action_kind(kind))

    def complete_redo(self, kind: str) -> None:
        self._append_bounded(self.action_undo, self._action_kind(kind))

    def clear(self) -> None:
        self.assist_undo.clear()
        self.assist_redo.clear()
        self.action_undo.clear()
        self.action_redo.clear()

    def can_undo(self, *, session_can_undo: bool) -> bool:
        return bool(self.action_undo) or bool(session_can_undo)

    def can_redo(self, *, session_can_redo: bool) -> bool:
        return bool(self.action_redo) or bool(session_can_redo)

    @staticmethod
    def _scope_source(
        session: CandidateReviewSession,
    ) -> Literal["selection", "region", "none"]:
        state = session.state
        if getattr(state, "selected_candidate_ids", ()):
            return "selection"
        if getattr(state, "region", None) is not None:
            return "region"
        return "none"

    def plan_eligible_candidates(
        self,
        session: CandidateReviewSession,
        *,
        reference_audio_offset_ms: float,
        include_routed: bool = False,
    ) -> CandidateReviewPlan:
        return CandidateReviewPlan(
            "eligible",
            self._scope_source(session),
            session.eligible_candidate_ids(
                reference_audio_offset_ms=reference_audio_offset_ms,
                include_routed=include_routed,
            ),
        )

    def plan_reject_candidates(
        self,
        session: CandidateReviewSession,
        *,
        reference_audio_offset_ms: float,
    ) -> CandidateReviewPlan:
        eligible = self.plan_eligible_candidates(
            session,
            reference_audio_offset_ms=reference_audio_offset_ms,
        )
        return CandidateReviewPlan(
            "reject",
            eligible.source,
            eligible.candidate_ids,
        )

    @staticmethod
    def _ordered_with_unknown_ids(
        session: CandidateReviewSession,
        candidate_ids: Iterable[str],
    ) -> tuple[str, ...]:
        requested = {str(candidate_id) for candidate_id in candidate_ids}
        known = session.order_candidate_ids(requested)
        return known + tuple(sorted(requested.difference(known)))

    def plan_restore_candidates(
        self,
        session: CandidateReviewSession,
        *,
        reference_audio_offset_ms: float,
    ) -> CandidateReviewPlan:
        state = session.state
        rejected = getattr(state, "rejected_candidate_ids", frozenset())
        selected = getattr(state, "selected_candidate_ids", frozenset())
        selected_rejected = selected.intersection(rejected)
        if selected_rejected:
            source = "selection"
            candidate_ids = self._ordered_with_unknown_ids(
                session,
                selected_rejected,
            )
        else:
            region = getattr(state, "region", None)
            if region is not None:
                source = "region"
                candidate_ids = tuple(
                    candidate_id
                    for candidate_id in (
                        session.candidate_ids_starting_in_project_region(
                            region,
                            reference_audio_offset_ms=(
                                reference_audio_offset_ms
                            ),
                        )
                    )
                    if candidate_id in rejected
                )
            else:
                source = "all"
                candidate_ids = self._ordered_with_unknown_ids(
                    session,
                    rejected,
                )
        return CandidateReviewPlan("restore", source, candidate_ids)

    def plan_fragment_selection(
        self,
        session: CandidateReviewSession,
        *,
        reference_audio_offset_ms: float,
    ) -> CandidateReviewPlan:
        state = session.state
        region = getattr(state, "region", None)
        rejected = getattr(state, "rejected_candidate_ids", frozenset())
        if region is None:
            source = "all"
            scoped_ids = session.ordered_candidate_ids
        else:
            source = "region"
            scoped_ids = session.candidate_ids_starting_in_project_region(
                region,
                reference_audio_offset_ms=reference_audio_offset_ms,
            )
        selected: list[str] = []
        for candidate_id in scoped_ids:
            annotation = session.annotation_for_id(candidate_id)
            flags = getattr(annotation, "flags", frozenset())
            if (
                candidate_id not in rejected
                and {"review_fragment", "pitch_flicker"}.intersection(flags)
            ):
                selected.append(candidate_id)
        return CandidateReviewPlan(
            "select_fragments",
            source,
            tuple(selected),
        )


__all__ = [
    "AssistRestartRequest",
    "CandidateReviewPlan",
    "TranscriptionAnalysisCoordinator",
    "TranscriptionReviewController",
]
