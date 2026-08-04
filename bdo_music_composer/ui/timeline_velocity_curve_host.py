"""Main-workspace transaction host for inline timeline velocity curves."""

from __future__ import annotations

from collections.abc import Sequence

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.game_score_model import (
    reconcile_track_game_velocity_records,
)
from bdo_music_composer.ui.i18n import tr, trf


class TimelineVelocityCurveHostMixin:
    """Publish one curve edit through the normal project transaction path."""

    def _commit_timeline_velocity_curve(
        self,
        track: TrackState,
        changed_notes: Sequence[object],
    ) -> None:
        if not any(candidate is track for candidate in self.tracks):
            self.show_toast(tr("力度节点目标轨道已经失效"), kind="error")
            return
        next_notes = list(changed_notes)
        if next_notes == track.notes:
            return
        changed_count = sum(
            int(previous.vel) != int(current.vel)
            for previous, current in zip(track.notes, next_notes)
        )
        self._push_project_snapshot()
        reconcile_track_game_velocity_records(track, next_notes)
        track.notes = next_notes
        self.timeline.set_tracks(self.tracks)
        self._select_track(track)
        self._mark_conversion_check_dirty()
        self._restart_preview_after_timeline_change()
        self._autosave_project("velocity envelope", immediate=True)
        self._schedule_transcription_assist_refresh()
        self.show_toast(
            trf(
                "已应用 {track} 的精准力度 · {count} 音符",
                track=track.display_name,
                count=changed_count,
            ),
            kind="success",
        )


__all__ = ["TimelineVelocityCurveHostMixin"]
