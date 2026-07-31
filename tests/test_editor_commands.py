from __future__ import annotations

from dataclasses import dataclass
import unittest

from conversion_settings import ConversionSettings
from bdo_music_composer.editor.editor_commands import (
    ProjectCommandStack,
    ProjectSnapshot,
)
from pitch_transform import PitchTransformPlan


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
        self.assertIsNone(snapshot.conversion_settings)

    def test_snapshot_restores_conversion_settings_atomically(self) -> None:
        settings = ConversionSettings(
            bpm_override=148,
            transpose=-8,
            velocity_mode="floor",
            vel_floor=42,
        )
        snapshot = ProjectSnapshot.capture(
            [Track(1, [])],
            0,
            0,
            None,
            conversion_settings=settings,
        )
        restored = snapshot.restored_conversion_settings()
        self.assertEqual(restored, settings)
        self.assertIsNot(restored, settings)

    def test_snapshot_restores_track_pitch_plan_atomically(self) -> None:
        plan = PitchTransformPlan(-8).with_track_octave(7, 12)
        snapshot = ProjectSnapshot.capture(
            [Track(7, [])],
            0,
            0,
            None,
            pitch_transform_plan=plan,
        )

        restored = snapshot.restored_pitch_transform_plan()

        self.assertEqual(restored, plan)
        self.assertIsNot(restored, plan)


if __name__ == "__main__":
    unittest.main()
