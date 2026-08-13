from __future__ import annotations

from copy import deepcopy
import unittest

from bdo_midi import Note
from bdo_music_composer.editor.arrangement_clip import (
    clip_edit_fingerprint,
    clip_editor_notes,
    default_empty_clip,
    plan_clip_create,
    plan_clip_edit,
    plan_clip_note_edit,
    plan_clip_paste,
    plan_clip_split,
    copy_clip,
    track_clip_bounds,
    project_track_notes,
    project_track_performance_controls,
)
from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState


def _track(track_id: int, notes=None) -> TrackState:
    return TrackState(
        track_id=track_id,
        notes=list(notes or []),
        gm_program=0,
        is_percussion=False,
        display_name=f"Track {track_id}",
        bdo_instrument_id=0x12,
    )


class ArrangementClipTests(unittest.TestCase):
    def test_clip_fingerprint_tracks_target_but_ignores_sibling(self) -> None:
        track = _track(1, [
            Note(60, 80, 100.0, 100.0, 0),
            Note(64, 90, 500.0, 100.0, 0),
        ])
        track.arrangement_clips = [
            ArrangementClipState("target", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("sibling", 500.0, 600.0, 500.0, 600.0),
        ]
        original = clip_edit_fingerprint(track, "target")

        track.notes[1] = track.notes[1]._replace(vel=70)
        self.assertEqual(
            clip_edit_fingerprint(track, "target"), original
        )

        track.notes[0] = track.notes[0]._replace(vel=70)
        self.assertNotEqual(
            clip_edit_fingerprint(track, "target"), original
        )

    def test_clip_fingerprint_tracks_target_geometry(self) -> None:
        track = _track(1, [Note(60, 80, 100.0, 100.0, 0)])
        track.arrangement_clips = [
            ArrangementClipState("target", 100.0, 200.0, 100.0, 200.0)
        ]
        original = clip_edit_fingerprint(track, "target")
        track.arrangement_clips[0] = ArrangementClipState(
            "target", 300.0, 400.0, 100.0, 200.0, 200.0
        )
        self.assertNotEqual(
            clip_edit_fingerprint(track, "target"), original
        )

    def test_new_track_clip_is_stable_and_editable_while_empty(self) -> None:
        clip = default_empty_clip(7, duration_ms=2_000.0)
        self.assertEqual(clip.clip_id, "track-7-main")
        self.assertEqual((clip.start_ms, clip.end_ms), (0.0, 2_000.0))
        source = _track(7)
        source.arrangement_clips = [clip]

        plan = plan_clip_note_edit(
            source,
            clip_id=clip.clip_id,
            notes=(Note(60, 90, 250.0, 300.0, 0),),
        )

        self.assertEqual(plan.updates[0].notes[0].start, 250.0)
        self.assertEqual(plan.updates[0].arrangement_clips, (clip,))

    def test_editing_one_of_multiple_clips_preserves_sibling_timing(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(64, 80, 500.0, 100.0, 0),
        ])
        source.arrangement_clips = [
            ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("last", 900.0, 1000.0, 500.0, 600.0, 400.0),
        ]
        self.assertEqual(
            [(note.pitch, note.start) for note in clip_editor_notes(source, "first")],
            [(60, 100.0)],
        )

        plan = plan_clip_note_edit(
            source,
            clip_id="first",
            notes=(Note(62, 91, 120.0, 60.0, 0),),
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(plan.updates[0].arrangement_clips)

        self.assertEqual(
            [(note.pitch, note.start) for note in project_track_notes(updated)],
            [(62, 120.0), (64, 900.0)],
        )

    def test_razor_views_are_already_independent_before_first_edit(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(64, 80, 500.0, 100.0, 0),
        ])
        split = plan_clip_split(source, clip_id="", split_ms=350.0)
        source.arrangement_clips = list(split.updates[0].arrangement_clips)
        right_id = split.selected_clip_id

        plan = plan_clip_note_edit(
            source,
            clip_id=right_id,
            notes=(Note(67, 88, 500.0, 80.0, 0),),
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(plan.updates[0].arrangement_clips)

        self.assertNotEqual(
            updated.arrangement_clips[0].content_start_ms,
            updated.arrangement_clips[1].content_start_ms,
        )
        self.assertEqual(
            [(note.pitch, note.start) for note in project_track_notes(updated)],
            [(60, 100.0), (67, 500.0)],
        )

    def test_move_offsets_clip_without_rewriting_authored_content(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 200.0, 0)])
        source.performance_controls = [{"time": 150.0, "kind": "pitchwheel"}]
        source.bdo_source_group_index = 2
        source.bdo_source_note_records = ((60, 90, 100.0, 200.0, 0, 75),)
        original = deepcopy(source)

        plan = plan_clip_edit(
            source, mode="move", new_start_ms=600.0, new_end_ms=800.0
        )

        update = plan.updates[0]
        self.assertEqual(update.notes[0].start, 100.0)
        self.assertEqual(update.performance_controls[0]["time"], 150.0)
        self.assertEqual(update.source_note_records[0][2:4], (100.0, 200.0))
        moved = deepcopy(source)
        moved.arrangement_clips = list(update.arrangement_clips)
        self.assertEqual(project_track_notes(moved)[0].start, 600.0)
        self.assertEqual(
            project_track_performance_controls(moved)[0]["time"], 650.0
        )
        self.assertEqual(source, original)

    def test_resize_changes_clip_boundary_without_rewriting_notes(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(64, 90, 300.0, 100.0, 0),
        ])
        plan = plan_clip_edit(
            source, mode="resize_end", new_start_ms=100.0, new_end_ms=700.0
        )
        self.assertEqual(
            [(note.start, note.dur) for note in plan.updates[0].notes],
            [(100.0, 100.0), (300.0, 100.0)],
        )
        self.assertEqual(plan.updates[0].arrangement_clips[0].start_ms, 100.0)
        self.assertEqual(plan.updates[0].arrangement_clips[0].end_ms, 700.0)

    def test_trim_projects_crossing_notes_but_preserves_authored_notes(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 300.0, 0)])
        source.clip_start_ms = 200.0
        source.clip_end_ms = 350.0
        self.assertEqual(
            project_track_notes(source),
            (Note(60, 90, 200.0, 150.0, 0),),
        )
        self.assertEqual(source.notes, [Note(60, 90, 100.0, 300.0, 0)])

    def test_vertical_move_merges_into_destination_and_empties_source(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        target = _track(2, [Note(67, 80, 50.0, 100.0, 0)])
        plan = plan_clip_edit(
            source,
            target=target,
            mode="move",
            new_start_ms=300.0,
            new_end_ms=400.0,
        )
        self.assertEqual(plan.updates[0].notes, ())
        destination = deepcopy(target)
        destination.notes = list(plan.updates[1].notes)
        destination.arrangement_clips = list(plan.updates[1].arrangement_clips)
        self.assertEqual([note.start for note in project_track_notes(destination)], [50.0, 300.0])
        self.assertEqual(plan.selected_track_id, 2)

    def test_cross_track_move_keeps_mapping_risks_for_validator(self) -> None:
        source = _track(1, [Note(48, 90, 100.0, 100.0, 99)])
        source.is_percussion = True
        source.bdo_instrument_id = 0x0D
        target = _track(2)

        plan = plan_clip_edit(
            source, target=target, mode="move",
            new_start_ms=300.0, new_end_ms=400.0,
        )

        self.assertEqual(plan.updates[0].notes, ())
        destination = deepcopy(target)
        destination.notes = list(plan.updates[1].notes)
        destination.arrangement_clips = list(plan.updates[1].arrangement_clips)
        self.assertEqual(project_track_notes(destination), (Note(48, 90, 300.0, 100.0, 99),))

    def test_create_adds_one_editable_note(self) -> None:
        track = _track(4)
        plan = plan_clip_create(track, start_ms=500.0, duration_ms=250.0, pitch=64)
        self.assertEqual(plan.updates[0].notes, (Note(64, 90, 500.0, 250.0, 0),))
        self.assertEqual(track_clip_bounds(track), None)

    def test_copy_paste_creates_independent_content_and_timeline_instance(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 200.0, 0)])
        clipboard = copy_clip(source, "track-1-main")
        target = _track(2)
        plan = plan_clip_paste(target, clipboard, start_ms=800.0)
        update = plan.updates[0]
        pasted = deepcopy(target)
        pasted.notes = list(update.notes)
        pasted.arrangement_clips = list(update.arrangement_clips)
        self.assertEqual(project_track_notes(pasted), (Note(60, 90, 800.0, 200.0, 0),))
        self.assertNotEqual(update.arrangement_clips[0].clip_id, clipboard.clip.clip_id)
        self.assertEqual(source.notes[0].start, 100.0)

    def test_razor_creates_two_nondestructive_views_of_complete_content(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 300.0, 0),
            Note(64, 80, 500.0, 100.0, 0),
        ])
        clip_id = plan_clip_edit(
            source, mode="resize_end", new_start_ms=100.0, new_end_ms=600.0
        ).selected_clip_id
        source.arrangement_clips = list(plan_clip_edit(
            source, mode="resize_end", new_start_ms=100.0, new_end_ms=600.0
        ).updates[0].arrangement_clips)
        plan = plan_clip_split(source, clip_id=clip_id, split_ms=300.0)
        self.assertEqual(len(plan.updates[0].arrangement_clips), 2)
        self.assertEqual(len(plan.updates[0].notes), len(source.notes) * 2)
        left, right = plan.updates[0].arrangement_clips
        self.assertNotEqual(
            (left.content_start_ms, left.content_end_ms),
            (right.content_start_ms, right.content_end_ms),
        )

    def test_only_selected_clip_moves_within_one_track(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(64, 80, 400.0, 100.0, 0),
        ])
        split = plan_clip_split(
            source,
            clip_id="track-1-main",
            split_ms=300.0,
        )
        source.notes = list(split.updates[0].notes)
        source.arrangement_clips = list(split.updates[0].arrangement_clips)
        right_id = source.arrangement_clips[1].clip_id
        plan = plan_clip_edit(
            source,
            clip_id=right_id,
            mode="move",
            new_start_ms=600.0,
            new_end_ms=800.0,
        )
        self.assertEqual(len(plan.updates[0].notes), 4)
        self.assertEqual(
            [clip.start_ms for clip in plan.updates[0].arrangement_clips],
            [100.0, 600.0],
        )

    def test_overlap_requires_confirmation_and_confirmed_move_merges_clips(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        target = _track(2, [Note(64, 80, 400.0, 100.0, 0)])
        target.arrangement_clips = [
            ArrangementClipState("target", 400.0, 500.0, 400.0, 500.0)
        ]

        with self.assertRaisesRegex(ValueError, "requires confirmation"):
            plan_clip_edit(
                source, target=target, mode="move",
                new_start_ms=450.0, new_end_ms=550.0,
            )
        self.assertEqual(source.notes[0].start, 100.0)
        self.assertEqual(target.notes[0].start, 400.0)

        plan = plan_clip_edit(
            source, target=target, mode="move",
            new_start_ms=450.0, new_end_ms=550.0,
            merge_overlaps=True,
        )
        destination = plan.updates[1]
        self.assertEqual(len(destination.arrangement_clips), 1)
        self.assertEqual(
            (destination.arrangement_clips[0].start_ms,
             destination.arrangement_clips[0].end_ms),
            (400.0, 550.0),
        )
        projected = deepcopy(target)
        projected.notes = list(destination.notes)
        projected.arrangement_clips = list(destination.arrangement_clips)
        self.assertEqual([note.start for note in project_track_notes(projected)], [400.0, 450.0])

    def test_confirmed_merge_preserves_unrelated_clip_and_controls(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.performance_controls = [
            {"time": 120.0, "kind": "pitchwheel", "pitch": 10}
        ]
        target = _track(2, [
            Note(64, 80, 400.0, 100.0, 0),
            Note(67, 70, 900.0, 100.0, 0),
        ])
        target.performance_controls = [
            {"time": 420.0, "kind": "pitchwheel", "pitch": 20},
            {"time": 920.0, "kind": "pitchwheel", "pitch": 30},
        ]
        target.arrangement_clips = [
            ArrangementClipState("overlap", 400.0, 500.0, 400.0, 500.0),
            ArrangementClipState("unrelated", 900.0, 1000.0, 900.0, 1000.0),
        ]

        plan = plan_clip_edit(
            source,
            target=target,
            mode="move",
            new_start_ms=450.0,
            new_end_ms=550.0,
            merge_overlaps=True,
        )
        update = plan.updates[1]
        projected = deepcopy(target)
        projected.notes = list(update.notes)
        projected.performance_controls = list(update.performance_controls)
        projected.arrangement_clips = list(update.arrangement_clips)
        self.assertEqual(
            [(note.pitch, note.start) for note in project_track_notes(projected)],
            [(64, 400.0), (60, 450.0), (67, 900.0)],
        )
        self.assertEqual(
            [
                value["time"]
                for value in project_track_performance_controls(projected)
            ],
            [420.0, 470.0, 920.0],
        )
        self.assertEqual(
            {clip.clip_id for clip in update.arrangement_clips},
            {"track-1-main", "unrelated"},
        )


if __name__ == "__main__":
    unittest.main()
