from __future__ import annotations

from dataclasses import dataclass
import unittest

from editor_commands import ProjectCommandStack, ProjectSnapshot


@dataclass
class Track:
    track_id: int
    notes: list


class EditorCommandTests(unittest.TestCase):
    def test_project_snapshots_are_isolated_and_support_undo_redo(self) -> None:
        tracks = [Track(1, ["a"])]
        transcription = {"pending_routes": [{"candidate_id": "a", "track_id": 1}]}
        before = ProjectSnapshot.capture(
            tracks, 1, 2, (3, 4, 5), transcription
        )
        tracks[0].notes.append("b")
        transcription["pending_routes"].clear()
        current = ProjectSnapshot.capture(tracks, 6, 7, None)
        stack = ProjectCommandStack(limit=3)
        stack.push(before)
        restored = stack.undo(current)
        self.assertEqual(restored.restored_tracks()[0].notes, ["a"])
        redone = stack.redo(restored)
        self.assertEqual(redone.restored_tracks()[0].notes, ["a", "b"])
        self.assertEqual(redone.reverb, 6)
        restored_review = restored.restored_transcription_state()
        self.assertEqual(
            restored_review,
            {"pending_routes": [{"candidate_id": "a", "track_id": 1}]},
        )
        restored_review["pending_routes"].clear()
        self.assertEqual(
            restored.restored_transcription_state(),
            {"pending_routes": [{"candidate_id": "a", "track_id": 1}]},
        )

    def test_old_capture_call_keeps_optional_transcription_state_none(self) -> None:
        snapshot = ProjectSnapshot.capture([Track(1, [])], 0, 0, None)
        self.assertIsNone(snapshot.transcription_state)


if __name__ == "__main__":
    unittest.main()
