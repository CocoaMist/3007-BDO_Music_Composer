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
        before = ProjectSnapshot.capture(tracks, 1, 2, (3, 4, 5))
        tracks[0].notes.append("b")
        current = ProjectSnapshot.capture(tracks, 6, 7, None)
        stack = ProjectCommandStack(limit=3)
        stack.push(before)
        restored = stack.undo(current)
        self.assertEqual(restored.restored_tracks()[0].notes, ["a"])
        redone = stack.redo(restored)
        self.assertEqual(redone.restored_tracks()[0].notes, ["a", "b"])
        self.assertEqual(redone.reverb, 6)


if __name__ == "__main__":
    unittest.main()
