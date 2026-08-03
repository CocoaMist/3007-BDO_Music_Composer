from __future__ import annotations

from dataclasses import dataclass
import unittest

from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.editor.editor_commands import (
    ProjectCommandStack,
    ProjectSnapshot,
    next_non_overlapping_paste_origin,
)
from bdo_midi import Note
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan


@dataclass
class Track:
    track_id: int
    notes: list


class EditorCommandTests(unittest.TestCase):
    def test_paste_origin_skips_same_pitch_collisions_as_one_group(self) -> None:
        existing = (
            Note(60, 90, 0.0, 250.0, 0),
            Note(60, 90, 375.0, 250.0, 0),
            Note(64, 90, 0.0, 2_000.0, 0),
        )
        clipboard = (
            Note(60, 80, 0.0, 200.0, 0),
            Note(67, 80, 125.0, 200.0, 0),
        )

        self.assertEqual(
            next_non_overlapping_paste_origin(
                existing,
                clipboard,
                0.0,
                grid_step_ms=125.0,
            ),
            625.0,
        )
        # A different-pitch chord lane does not force a horizontal shift.
        self.assertEqual(
            next_non_overlapping_paste_origin(
                existing,
                (Note(72, 80, 0.0, 200.0, 0),),
                0.0,
                grid_step_ms=125.0,
            ),
            0.0,
        )
        self.assertEqual(
            next_non_overlapping_paste_origin(
                existing,
                (Note(60, 80, 0.0, 200.0, 0),),
                0.0,
                grid_step_ms=None,
            ),
            625.0,
        )

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
