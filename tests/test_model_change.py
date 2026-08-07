from __future__ import annotations

import unittest

from bdo_music_composer.editor.model_change import ModelChange


class ModelChangeTests(unittest.TestCase):
    def test_structure_change_requires_full_model_refresh(self) -> None:
        change = ModelChange.structure()

        self.assertTrue(change.advances_revision)
        self.assertTrue(change.rebuilds_timeline)
        self.assertTrue(change.affects_validation)
        self.assertTrue(change.affects_preview)
        self.assertEqual(change.track_ids, frozenset())

    def test_note_change_is_scoped_to_stable_track_ids(self) -> None:
        change = ModelChange.notes(7, 7, 3)

        self.assertEqual(change.kind, "notes")
        self.assertEqual(change.track_ids, frozenset({3, 7}))
        self.assertTrue(change.advances_revision)
        self.assertFalse(change.rebuilds_timeline)
        self.assertTrue(change.affects_validation)
        self.assertTrue(change.affects_preview)

    def test_view_and_transport_changes_do_not_mutate_model_revision(self) -> None:
        for change in (ModelChange.view(), ModelChange.transport()):
            with self.subTest(kind=change.kind):
                self.assertFalse(change.advances_revision)
                self.assertFalse(change.rebuilds_timeline)
                self.assertFalse(change.affects_validation)
                self.assertFalse(change.affects_autosave)

    def test_track_scoped_change_rejects_empty_scope(self) -> None:
        with self.assertRaises(ValueError):
            ModelChange.notes()


if __name__ == "__main__":
    unittest.main()
