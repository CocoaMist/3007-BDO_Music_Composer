"""Qt-free ownership of project loading lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProjectLifecycleController:
    """Gate autosave/UI reactions while one project transition is active."""

    loading: bool = False
    generation: int = 0
    reason: str = ""

    def begin_loading(self, reason: str) -> int:
        self.generation += 1
        self.loading = True
        self.reason = str(reason or "project loading")
        return self.generation

    def finish_loading(self, generation: int) -> bool:
        if int(generation) != self.generation:
            return False
        self.loading = False
        self.reason = ""
        return True

    def set_loading(self, loading: bool, reason: str = "") -> None:
        if loading:
            self.begin_loading(reason)
        else:
            self.loading = False
            self.reason = ""


__all__ = ["ProjectLifecycleController"]
