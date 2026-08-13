"""Focused mixer-track ordering behavior for the main workspace."""

from __future__ import annotations

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.track_group import move_group_block
from bdo_music_composer.editor.model_change import ModelChange


class TrackOrderingMixin:
    """Move selected musical lanes without changing their stable identities."""

    def _move_track(
        self,
        track: TrackState | None,
        direction: int,
    ) -> None:
        if track is None or track not in self.tracks:
            return
        ordered = move_group_block(self.tracks, track, direction)
        if tuple(self.tracks) == ordered:
            return
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.tracks = list(ordered)
        self._apply_workspace_change(ModelChange.structure())
        self._select_track(track)
        self._schedule_timeline_validation_refresh()
        self._autosave_project("move track", immediate=True)


__all__ = ["TrackOrderingMixin"]
