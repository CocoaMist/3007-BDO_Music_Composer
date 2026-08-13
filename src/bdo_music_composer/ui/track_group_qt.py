"""Automatic main-window classification for same-instrument Track groups."""

from __future__ import annotations

from bdo_music_composer.editor.track_group import same_instrument_group_ids
from bdo_music_composer.editor.model_change import ModelChange


class TrackGroupHostMixin:
    def _auto_group_same_instrument_tracks(self) -> None:
        assignments = same_instrument_group_ids(self.tracks)
        ordered = []
        seen: set[str] = set()
        for source in self.tracks:
            source_id = int(source.track_id)
            group_key = assignments.get(source_id, "") or f"track:{source_id}"
            if group_key in seen:
                continue
            seen.add(group_key)
            ordered.extend(
                track for track in self.tracks
                if (
                    assignments.get(int(track.track_id), "")
                    or f"track:{int(track.track_id)}"
                ) == group_key
            )
        self.tracks = ordered
        for track in self.tracks:
            track.arrangement_group_id = assignments.get(int(track.track_id), "")

    def _apply_arrangement_group_control(
        self, group_id: str, action: str
    ) -> None:
        members = [
            track for track in self.tracks
            if str(track.arrangement_group_id or "") == str(group_id)
        ]
        if len(members) < 2 or action not in {"mute", "solo"}:
            return
        self._push_project_snapshot()
        if action == "mute":
            next_value = not all(track.muted for track in members)
            for track in members:
                track.muted = next_value
        else:
            next_value = not all(track.solo for track in members)
            for track in members:
                track.solo = next_value
        self._restart_preview_after_timeline_change(
            ModelChange.track_meta(*(int(track.track_id) for track in members))
        )
        self._autosave_project("arrangement group control")

__all__ = ["TrackGroupHostMixin"]
