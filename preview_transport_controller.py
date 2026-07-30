"""Qt-free real-time preview transport state and generation gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class PreviewPlayAction(str, Enum):
    """UI-independent command selected for a transport Play request."""

    WAIT_FOR_LOAD = "wait_for_load"
    RESUME = "resume"
    START_SESSION = "start_session"


@dataclass(slots=True)
class PreviewTransportCoordinator:
    """Own preview session state without touching audio or Qt objects."""

    generation: int = 0
    active: bool = False
    loading: bool = False
    source: str = "bdo"
    start_ms: float = 0.0
    tracks: list[object] = field(default_factory=list)
    validation_state: str = "approximate"

    def play_action(self) -> PreviewPlayAction:
        if self.loading:
            return PreviewPlayAction.WAIT_FOR_LOAD
        if self.active:
            return PreviewPlayAction.RESUME
        return PreviewPlayAction.START_SESSION

    def invalidate(self) -> int:
        self.generation += 1
        return self.generation

    def is_current(self, generation: int) -> bool:
        return int(generation) == self.generation

    def begin_loading(
        self,
        *,
        start_ms: float,
        tracks: Sequence[object],
        source: str,
        advance: bool = True,
    ) -> int:
        if advance:
            self.invalidate()
        self.active = True
        self.loading = True
        self.source = str(source)
        self.start_ms = float(start_ms)
        self.tracks = list(tracks)
        self.validation_state = "approximate"
        return self.generation

    def mark_ready(self, validation_state: str) -> None:
        self.loading = False
        self.validation_state = str(validation_state)

    def clear_session(self, *, advance: bool = True) -> int:
        if advance:
            self.invalidate()
        self.active = False
        self.loading = False
        self.tracks = []
        return self.generation


__all__ = ["PreviewPlayAction", "PreviewTransportCoordinator"]
