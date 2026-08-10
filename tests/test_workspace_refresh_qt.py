from __future__ import annotations

import unittest

from bdo_music_composer.app.workspace_refresh_controller import RefreshPlan
from bdo_music_composer.ui.workspace_refresh_qt import apply_workspace_refresh


class _Counter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.zoom_factor = 1.0

    def set_tracks(self, tracks) -> None: self.calls.append(("set_tracks", tuple(tracks)))
    def update_tracks(self, track_ids) -> None: self.calls.append(("update_tracks", frozenset(track_ids)))
    def set_pitch_transform_plan(self, plan) -> None: self.calls.append(("pitch", plan))
    def set_musical_grid(self, bpm, meter, origin) -> None: self.calls.append(("grid", (bpm, meter, origin)))
    def update(self) -> None: self.calls.append(("update", None))
    def pan_percent(self) -> int: return 0


class _Host:
    def __init__(self) -> None:
        self.timeline = _Counter()
        self.tracks = [1, 2]
        self.bpm = 120
        self.bpm_override = None
        self.time_sig = 4
        self.beat_origin_ms = 0.0
        self._pitch_transform_plan = "pitch-plan"
        self.events: list[str] = []

    def _advance_model_revision(self, _reason) -> None: self.events.append("revision")
    def _sync_global_bpm_control(self) -> None: self.events.append("bpm")
    def _sync_toolbar_global_gain(self) -> None: self.events.append("gain")
    def _update_ensemble_metric(self) -> None: self.events.append("ensemble")
    def _refresh_transcription_workspace(self) -> None: self.events.append("transcription")
    def _schedule_timeline_validation_refresh(self) -> None: self.events.append("validation")


class WorkspaceRefreshQtTests(unittest.TestCase):
    def test_structural_refresh_does_not_enqueue_a_duplicate_full_update(self) -> None:
        host = _Host()
        apply_workspace_refresh(host, RefreshPlan(rebuild_timeline=True, refresh_view=True))
        self.assertEqual(host.timeline.calls, [("set_tracks", (1, 2))])

    def test_view_only_refresh_issues_one_update(self) -> None:
        host = _Host()
        apply_workspace_refresh(host, RefreshPlan(refresh_view=True))
        self.assertEqual(host.timeline.calls, [("update", None)])


if __name__ == "__main__":
    unittest.main()
