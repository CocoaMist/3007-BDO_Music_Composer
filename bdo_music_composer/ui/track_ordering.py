"""Focused mixer-track ordering behavior for the main workspace."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.ui.i18n import tr


class TrackOrderingMixin:
    """Move selected musical lanes without changing their stable identities."""

    def _build_track_actions_menu(self) -> QMenu:
        menu = QMenu(self.track_actions_button)
        delete_action = menu.addAction(tr("删除轨道"))
        delete_action.triggered.connect(self._delete_selected_track)
        for source, direction in (("上移轨道", -1), ("下移轨道", 1)):
            action = menu.addAction(tr(source))
            action.triggered.connect(
                lambda _checked=False, direction=direction: self._move_selected_track(direction)
            )
        menu.addSeparator()
        clear_solo_action = menu.addAction(tr("清除 Solo"))
        clear_solo_action.triggered.connect(self._clear_solo)
        unmute_action = menu.addAction(tr("取消静音"))
        unmute_action.triggered.connect(self._unmute_all)
        return menu

    def _move_selected_track(self, direction: int) -> None:
        self._move_track(self.selected_track, direction)

    def _move_track(
        self,
        track: TrackState | None,
        direction: int,
    ) -> None:
        if track is None or track not in self.tracks:
            return
        source_index = self.tracks.index(track)
        destination_index = source_index + (1 if direction > 0 else -1)
        if not 0 <= destination_index < len(self.tracks):
            return
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.tracks[source_index], self.tracks[destination_index] = (
            self.tracks[destination_index],
            self.tracks[source_index],
        )
        self.timeline.set_tracks(self.tracks)
        self._select_track(track)
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("move track", immediate=True)


__all__ = ["TrackOrderingMixin"]
