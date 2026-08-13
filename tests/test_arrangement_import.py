from __future__ import annotations

from copy import deepcopy
import unittest

from bdo_common.bdo_track_effects import MasterEffects
from bdo_midi import Note
from bdo_music_composer.editor.arrangement_import import plan_arrangement_append
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.editor_models import ArrangementClipState
from bdo_music_composer.editor.arrangement_clip import project_track_notes


def _track(track_id: int, instrument_id: int = 0x12) -> TrackState:
    return TrackState(
        track_id=track_id,
        notes=[Note(60, 90, 100.0, 240.0, 0)],
        gm_program=0,
        is_percussion=False,
        display_name=f"Track {track_id}",
        bdo_instrument_id=instrument_id,
        bdo_track_volume=63,
        bdo_track_settings=(11, 12, 13, 14, 15, 16, 17, 18),
    )


class ArrangementImportTests(unittest.TestCase):
    def test_append_plan_shifts_all_timed_material_and_preserves_source(self) -> None:
        source = _track(0)
        source.performance_controls = [
            {"time": 150.0, "kind": "control_change", "value": 64}
        ]
        source.bdo_source_group_index = 3
        source.bdo_source_note_records = ((60, 90, 100.0, 240.0, 0, 77),)
        original = deepcopy(source)

        plan = plan_arrangement_append(
            [],
            [source],
            reserved_track_ids=(8,),
            offset_ms=500.0,
            lyric_events=({"time": 200.0, "kind": "lyrics", "text": "A"},),
            master_effects=MasterEffects.raw(21, 22, 23, 24, 25),
            colors=("#000000", "#111111"),
        )

        track = plan.tracks[0]
        self.assertEqual(track.track_id, 9)
        self.assertEqual(track.notes[0].start, 600.0)
        self.assertEqual(track.performance_controls[0]["time"], 650.0)
        self.assertEqual(track.bdo_source_note_records[0][2], 600.0)
        self.assertEqual(track.bdo_source_note_records[0][5], 77)
        self.assertIsNone(track.bdo_source_group_index)
        self.assertEqual(track.bdo_track_settings, (11, 21, 13, 22, 15, 23, 24, 25))
        self.assertEqual(track.color, "#111111")
        self.assertEqual(plan.lyric_events[0]["time"], 700.0)
        self.assertEqual(plan.note_count, 1)
        self.assertEqual(source, original)

    def test_matching_destination_instrument_owns_shared_mixer_state(self) -> None:
        existing = _track(4)
        existing.bdo_track_volume = 42
        existing.bdo_track_settings = (31, 1, 32, 2, 33, 3, 4, 5)
        source = _track(0)

        plan = plan_arrangement_append(
            [existing],
            [source],
            master_effects=MasterEffects.raw(21, 22, 23, 24, 25),
        )

        appended = plan.tracks[0]
        self.assertEqual(appended.bdo_track_volume, 42)
        self.assertEqual(appended.bdo_track_settings[:5:2], (31, 32, 33))
        self.assertEqual(
            tuple(appended.bdo_track_settings[index] for index in (1, 3, 5, 6, 7)),
            (21, 22, 23, 24, 25),
        )

    def test_append_preserves_moved_clip_display_time(self) -> None:
        source = _track(0)
        source.arrangement_clips = [
            ArrangementClipState(
                "moved", 700.0, 940.0, 100.0, 340.0, 600.0
            )
        ]

        appended = plan_arrangement_append(
            [], [source], offset_ms=500.0
        ).tracks[0]

        self.assertEqual(appended.arrangement_clips[0].time_offset_ms, 600.0)
        self.assertEqual(project_track_notes(appended)[0].start, 1200.0)

    def test_conflicting_destination_mix_fails_without_mutating_sources(self) -> None:
        first = _track(1)
        second = _track(2)
        second.bdo_track_volume = 20
        source = _track(0)
        original = deepcopy(source)

        with self.assertRaisesRegex(ValueError, "conflicting mixer states"):
            plan_arrangement_append([first, second], [source])

        self.assertEqual(source, original)

    def test_invalid_offset_and_empty_source_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_arrangement_append([], [_track(0)], offset_ms=-1.0)
        with self.assertRaises(ValueError):
            plan_arrangement_append([], [])


if __name__ == "__main__":
    unittest.main()
