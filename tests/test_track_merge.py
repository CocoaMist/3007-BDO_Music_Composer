from __future__ import annotations

from copy import deepcopy
import unittest

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.output_routing import game_output_route_identity
from bdo_music_composer.editor.track_merge import plan_track_merge


def _track(track_id: int, notes: list[Note], *, instrument: int = 0x12) -> TrackState:
    return TrackState(
        track_id=track_id,
        notes=notes,
        gm_program=0,
        is_percussion=False,
        display_name=f"Track {track_id}",
        bdo_instrument_id=instrument,
    )


class TrackMergeTests(unittest.TestCase):
    def test_merge_preserves_every_note_and_reports_overlap_risk(self) -> None:
        left = _track(1, [
            Note(60, 90, 0.0, 100.0, 0),
            Note(64, 80, 150.0, 100.0, 0),
        ])
        right = _track(2, [
            Note(60, 90, 0.0, 100.0, 0),
            Note(67, 70, 50.0, 150.0, 0),
        ])
        original_left, original_right = deepcopy(left), deepcopy(right)

        plan = plan_track_merge(left, right)

        self.assertEqual(len(plan.merged_track.notes), 4)
        self.assertEqual(plan.report.overlap_pair_count, 3)
        self.assertEqual(plan.report.same_pitch_pair_count, 1)
        self.assertEqual(plan.report.exact_duplicate_count, 1)
        self.assertEqual(len(plan.report.overlap_regions), 2)
        self.assertEqual(
            (plan.report.overlap_regions[0].start_ms,
             plan.report.overlap_regions[0].end_ms),
            (0.0, 100.0),
        )
        self.assertEqual(plan.report.overlap_duration_ms, 150.0)
        self.assertEqual(left, original_left)
        self.assertEqual(right, original_right)

    def test_requires_the_complete_serialized_game_route_to_match(self) -> None:
        left = _track(1, [])
        different_instrument = _track(2, [], instrument=0x13)
        with self.assertRaisesRegex(ValueError, "different game instruments"):
            plan_track_merge(left, different_instrument)

        different_volume = _track(3, [])
        different_volume.bdo_track_volume += 1
        with self.assertRaisesRegex(ValueError, "different game volumes"):
            plan_track_merge(left, different_volume)

        different_settings = _track(4, [])
        different_settings.bdo_track_settings = (0, 0, 1, 0, 0, 0, 0, 0)
        with self.assertRaisesRegex(ValueError, "different game mixer"):
            plan_track_merge(left, different_settings)

    def test_bakes_duration_and_secondary_velocity_without_source_mutation(self) -> None:
        left = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        left.duration_scale = 2.0
        left.bdo_source_note_records = ((60, 90, 100.0, 100.0, 0, 44),)
        left.performance_controls = [{"time": 120.0, "kind": "pitchwheel"}]
        right = _track(2, [Note(64, 80, 400.0, 50.0, 0)])

        merged = plan_track_merge(left, right).merged_track

        self.assertEqual(merged.duration_scale, 1.0)
        self.assertEqual([note.dur for note in merged.notes], [200.0, 50.0])
        self.assertEqual(merged.bdo_source_note_records[0][3], 200.0)
        self.assertEqual(merged.bdo_source_note_records[0][5], 44)
        self.assertEqual(len(merged.bdo_source_note_records), 2)
        self.assertEqual(merged.performance_controls[0]["time"], 120.0)

    def test_reports_physical_split_but_keeps_one_route_identity(self) -> None:
        left = _track(1, [Note(60, 90, float(i), 1.0, 0) for i in range(731)])
        right = _track(2, [])
        plan = plan_track_merge(left, right)
        self.assertEqual(plan.report.physical_note_track_count, 2)
        self.assertEqual(
            plan.report.route, game_output_route_identity(plan.merged_track)
        )


if __name__ == "__main__":
    unittest.main()
