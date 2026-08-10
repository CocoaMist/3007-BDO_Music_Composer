"""Qt-free planning for precise workspace refresh side effects."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from bdo_music_composer.editor.model_change import ModelChange


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    advance_revision: bool = False
    rebuild_timeline: bool = False
    changed_track_ids: frozenset[int] = frozenset()
    refresh_view: bool = False
    refresh_grid: bool = False
    refresh_metadata: bool = False
    refresh_ensemble: bool = False
    refresh_transcription: bool = False
    refresh_validation: bool = False
    refresh_preview: bool = False


class WorkspaceRefreshController:
    """Merge immutable model changes into one bounded UI refresh plan."""

    def plan(self, changes: Sequence[ModelChange]) -> RefreshPlan:
        if not changes:
            raise ValueError("workspace refresh requires at least one change")
        rebuild_timeline = any(change.rebuilds_timeline for change in changes)
        kinds = frozenset(change.kind for change in changes)
        track_ids = frozenset().union(
            *(change.track_ids for change in changes)
        )
        if rebuild_timeline:
            track_ids = frozenset()
        model_changed = any(change.advances_revision for change in changes)
        return RefreshPlan(
            advance_revision=model_changed,
            rebuild_timeline=rebuild_timeline,
            changed_track_ids=track_ids,
            refresh_view=True,
            refresh_grid=bool(kinds & {"structure", "grid"}),
            refresh_metadata=bool(kinds & {"structure", "notes", "track_meta", "mixer", "grid"}),
            refresh_ensemble=bool(kinds & {"structure", "notes", "track_meta", "mixer"}),
            refresh_transcription=bool(kinds & {"structure", "notes", "grid"}),
            refresh_validation=any(change.affects_validation for change in changes),
            refresh_preview=any(change.affects_preview for change in changes),
        )


__all__ = ["RefreshPlan", "WorkspaceRefreshController"]
