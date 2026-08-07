"""Immutable workspace change intent for precise cache invalidation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ChangeKind = Literal[
    "structure",
    "notes",
    "track_meta",
    "mixer",
    "grid",
    "view",
    "transport",
]


@dataclass(frozen=True, slots=True)
class ModelChange:
    kind: ChangeKind
    track_ids: frozenset[int] = frozenset()
    advances_revision: bool = False
    rebuilds_timeline: bool = False
    affects_validation: bool = False
    affects_preview: bool = False
    affects_autosave: bool = False

    @classmethod
    def structure(cls) -> "ModelChange":
        return cls(
            "structure",
            advances_revision=True,
            rebuilds_timeline=True,
            affects_validation=True,
            affects_preview=True,
            affects_autosave=True,
        )

    @classmethod
    def notes(cls, *track_ids: int) -> "ModelChange":
        scope = frozenset(int(track_id) for track_id in track_ids)
        if not scope:
            raise ValueError("note changes require at least one track ID")
        return cls(
            "notes",
            track_ids=scope,
            advances_revision=True,
            affects_validation=True,
            affects_preview=True,
            affects_autosave=True,
        )

    @classmethod
    def view(cls) -> "ModelChange":
        return cls("view")

    @classmethod
    def transport(cls) -> "ModelChange":
        return cls("transport", affects_preview=True)


__all__ = ["ChangeKind", "ModelChange"]
