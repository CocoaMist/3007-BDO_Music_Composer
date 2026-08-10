from __future__ import annotations

import unittest

from bdo_music_composer.app.workspace_refresh_controller import (
    RefreshPlan,
    WorkspaceRefreshController,
)
from bdo_music_composer.editor.model_change import ModelChange


class WorkspaceRefreshControllerTests(unittest.TestCase):
    def test_grid_change_refreshes_projection_without_rebuilding_tracks(self) -> None:
        plan = WorkspaceRefreshController().plan((ModelChange.grid(),))

        self.assertFalse(plan.advance_revision)
        self.assertFalse(plan.rebuild_timeline)
        self.assertTrue(plan.refresh_grid)
        self.assertTrue(plan.refresh_validation)
        self.assertTrue(plan.refresh_preview)

    def test_view_change_does_not_schedule_model_work(self) -> None:
        plan = WorkspaceRefreshController().plan((ModelChange.view(),))

        self.assertEqual(plan, RefreshPlan(refresh_view=True))
        self.assertFalse(plan.advance_revision)
        self.assertFalse(plan.refresh_validation)
        self.assertFalse(plan.refresh_transcription)

    def test_note_changes_merge_track_scope_once(self) -> None:
        plan = WorkspaceRefreshController().plan(
            (ModelChange.notes(3), ModelChange.notes(3, 7))
        )

        self.assertTrue(plan.advance_revision)
        self.assertFalse(plan.rebuild_timeline)
        self.assertEqual(plan.changed_track_ids, frozenset({3, 7}))
        self.assertTrue(plan.refresh_validation)
        self.assertTrue(plan.refresh_transcription)

    def test_structure_change_dominates_local_note_updates(self) -> None:
        plan = WorkspaceRefreshController().plan(
            (ModelChange.notes(3), ModelChange.structure())
        )

        self.assertTrue(plan.rebuild_timeline)
        self.assertEqual(plan.changed_track_ids, frozenset())
        self.assertTrue(plan.advance_revision)

    def test_empty_change_batch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WorkspaceRefreshController().plan(())


if __name__ == "__main__":
    unittest.main()
