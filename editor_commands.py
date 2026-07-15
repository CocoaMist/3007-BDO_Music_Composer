"""Bounded project-level undo snapshots for cross-dialog editor operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    tracks: tuple[object, ...]
    reverb: int
    delay: int
    chorus: tuple[int, int, int] | None

    @classmethod
    def capture(cls, tracks: Sequence[object], reverb: int, delay: int,
                chorus: tuple[int, int, int] | None) -> "ProjectSnapshot":
        return cls(tuple(deepcopy(list(tracks))), int(reverb), int(delay), deepcopy(chorus))

    def restored_tracks(self) -> list:
        return deepcopy(list(self.tracks))


class ProjectCommandStack:
    def __init__(self, limit: int = 50) -> None:
        self.limit = max(1, int(limit))
        self._undo: list[ProjectSnapshot] = []
        self._redo: list[ProjectSnapshot] = []

    def push(self, before: ProjectSnapshot) -> None:
        self._undo.append(before)
        del self._undo[:-self.limit]
        self._redo.clear()

    def undo(self, current: ProjectSnapshot) -> ProjectSnapshot | None:
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current: ProjectSnapshot) -> ProjectSnapshot | None:
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


__all__ = ["ProjectCommandStack", "ProjectSnapshot"]
