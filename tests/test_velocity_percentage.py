from __future__ import annotations

import unittest

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import (
    ArrangementClipState,
    TrackState,
)
from bdo_music_composer.editor.editor_import import (
    TrackImportPresentation,
    tracks_from_project_payload,
)
from bdo_music_composer.project.project_persistence import freeze_project_tracks
from bdo_music_composer.editor.velocity_percentage import (
    apply_clip_velocity_base,
    apply_clip_velocity_percent,
    apply_global_velocity_adjustment,
    selection_velocity_percent,
)


def _track() -> TrackState:
    notes = [
        Note(60, 80, 0.0, 100.0, 0),
        Note(64, 100, 120.0, 100.0, 0),
        Note(67, 70, 500.0, 100.0, 0),
    ]
    return TrackState(
        track_id=1,
        notes=notes,
        gm_program=0,
        is_percussion=False,
        display_name="Piano",
        bdo_instrument_id=0x0B,
        bdo_source_note_records=(
            (60, 80, 0.0, 100.0, 0, 60),
            (64, 100, 120.0, 100.0, 0, 90),
            (67, 70, 500.0, 100.0, 0, 55),
        ),
        arrangement_clips=[
            ArrangementClipState("a", 0.0, 300.0, 0.0, 300.0),
            ArrangementClipState("b", 500.0, 700.0, 500.0, 700.0),
        ],
    )


class VelocityPercentageTests(unittest.TestCase):
    def test_clip_percentage_bakes_and_restores_exact_baseline(self) -> None:
        track = _track()
        self.assertTrue(apply_clip_velocity_percent(track, ("a",), 140))
        self.assertEqual([note.vel for note in track.notes], [112, 127, 70])
        self.assertEqual(
            [record[5] for record in track.bdo_source_note_records],
            [84, 126, 55],
        )
        self.assertEqual(selection_velocity_percent(((track, "a"),)), 140)

        apply_clip_velocity_percent(track, ("a",), 100)
        self.assertEqual([note.vel for note in track.notes], [80, 100, 70])
        self.assertEqual(
            [record[5] for record in track.bdo_source_note_records],
            [60, 90, 55],
        )

    def test_manual_final_velocity_edit_rebases_only_that_note(self) -> None:
        track = _track()
        apply_clip_velocity_percent(track, ("a",), 140)
        track.notes[0] = track.notes[0]._replace(vel=90)

        apply_clip_velocity_percent(track, ("a",), 120)
        self.assertEqual(track.notes[0].vel, 77)
        self.assertEqual(track.notes[1].vel, 120)

    def test_mixed_selection_reports_no_single_value(self) -> None:
        track = _track()
        apply_clip_velocity_percent(track, ("a",), 140)
        self.assertIsNone(
            selection_velocity_percent(((track, "a"), (track, "b")))
        )

    def test_project_payload_retains_baked_value_and_restoration_baseline(self) -> None:
        track = _track()
        apply_clip_velocity_percent(track, ("a",), 140)
        payload = freeze_project_tracks((track,))[0].to_payload()
        restored = tracks_from_project_payload(
            {"tracks": [payload]},
            TrackImportPresentation(
                colors=("#111111",),
                bdo_instrument_name=lambda value: str(value),
                gm_program_name=lambda value: str(value),
                drum_track_name=lambda: "Drums",
                new_track_name=lambda value: str(value),
            ),
        )[0]

        self.assertEqual(restored.notes[0].vel, 112)
        self.assertEqual(restored.arrangement_clips[0].velocity_percent, 140)
        self.assertEqual(
            restored.arrangement_clips[0].velocity_baseline_a,
            (80, 100),
        )
        apply_clip_velocity_percent(restored, ("a",), 100)
        self.assertEqual([note.vel for note in restored.notes], [80, 100, 70])

    def test_clip_base_changes_baseline_without_resetting_percentage(self) -> None:
        track = _track()
        apply_clip_velocity_percent(track, ("a",), 140)

        self.assertTrue(apply_clip_velocity_base(
            track, ("a",), 10, equalize=False
        ))
        self.assertEqual(track.arrangement_clips[0].velocity_percent, 140)
        self.assertEqual(
            track.arrangement_clips[0].velocity_baseline_a,
            (90, 110),
        )
        self.assertEqual([note.vel for note in track.notes], [126, 127, 70])
        self.assertEqual(
            [record[5] for record in track.bdo_source_note_records],
            [98, 127, 55],
        )

        apply_clip_velocity_percent(track, ("a",), 100)
        self.assertEqual([note.vel for note in track.notes], [90, 110, 70])
        self.assertEqual(
            [record[5] for record in track.bdo_source_note_records],
            [70, 100, 55],
        )

    def test_global_adjustment_transforms_baselines_below_clip_percentage(self) -> None:
        track = _track()
        apply_clip_velocity_percent(track, ("a",), 140)

        self.assertEqual(
            apply_global_velocity_adjustment(
                (track,), 50, percent_mode=True
            ),
            (1,),
        )
        self.assertEqual([note.vel for note in track.notes], [56, 70, 35])
        self.assertEqual(
            [record[5] for record in track.bdo_source_note_records],
            [42, 63, 28],
        )
        self.assertEqual(track.arrangement_clips[0].velocity_percent, 140)
        self.assertEqual(
            track.arrangement_clips[0].velocity_baseline_a, (40, 50)
        )
        self.assertEqual(
            track.arrangement_clips[0].velocity_baseline_b, (30, 45)
        )

        apply_clip_velocity_percent(track, ("a",), 120)
        self.assertEqual([note.vel for note in track.notes], [48, 60, 35])
        self.assertEqual(
            [record[5] for record in track.bdo_source_note_records],
            [36, 54, 28],
        )

        payload = freeze_project_tracks((track,))[0].to_payload()
        restored = tracks_from_project_payload(
            {"tracks": [payload]},
            TrackImportPresentation(
                colors=("#111111",),
                bdo_instrument_name=lambda value: str(value),
                gm_program_name=lambda value: str(value),
                drum_track_name=lambda: "Drums",
                new_track_name=lambda value: str(value),
            ),
        )[0]
        self.assertEqual([note.vel for note in restored.notes], [48, 60, 35])
        self.assertEqual(
            restored.arrangement_clips[0].velocity_baseline_a, (40, 50)
        )
        apply_clip_velocity_percent(restored, ("a",), 100)
        self.assertEqual([note.vel for note in restored.notes], [40, 50, 35])

    def test_original_slider_range_and_common_scaling_cases_remain_compatible(self) -> None:
        track = _track()
        apply_clip_velocity_percent(track, ("a",), 134)
        self.assertEqual([note.vel for note in track.notes], [107, 127, 70])
        apply_clip_velocity_percent(track, ("a",), 10)
        self.assertEqual([note.vel for note in track.notes], [8, 10, 70])
        apply_clip_velocity_percent(track, ("a",), 200)
        self.assertEqual([note.vel for note in track.notes], [127, 127, 70])


if __name__ == "__main__":
    unittest.main()
