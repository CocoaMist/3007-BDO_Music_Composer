"""Monotonic editor-model revisions shared by derived-state caches."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ModelRevision:
    """Track explicit model mutations without inspecting mutable note lists.

    ``TrackState.notes`` remains intentionally mutable for the editor.  A cache
    must therefore depend on this explicit boundary instead of object identity,
    list length, or a second full-song fingerprint scan.
    """

    value: int = 0
    reason: str = "initial"

    def advance(self, reason: str) -> int:
        self.value += 1
        self.reason = str(reason or "model changed")
        return self.value


__all__ = ["ModelRevision"]
