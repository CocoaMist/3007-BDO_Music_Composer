from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

from bdo_midi import Note
from bdo_music_composer.editor.arrangement_clip import (
    ClipEditError,
    clip_edit_fingerprint,
    clip_editor_notes,
    clip_editor_scope,
    default_empty_clip,
    plan_clip_create,
    plan_clip_delete,
    plan_clips_delete,
    plan_clips_move,
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
from bdo_music_composer.ui.arrangement_clip_qt import ArrangementClipHostMixin


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
    def test_host_batches_cross_track_move_into_one_publication(self) -> None:
        first = _track(1)
        first.arrangement_clips = [
            ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0)
        ]
        second = _track(2)
        second.arrangement_clips = [
            ArrangementClipState("second", 500.0, 600.0, 500.0, 600.0)
        ]

        class Host(ArrangementClipHostMixin):
            def __init__(self) -> None:
                self.tracks = [first, second]
                self.selected_track = second
                self.publications = []
                self.publish_kwargs = []
                self.toasts = []

            def _publish_clip_plan(self, plan, reason, **kwargs) -> None:
                self.publications.append((plan, reason))
                self.publish_kwargs.append(kwargs)

            def show_toast(self, message, **kwargs) -> None:
                self.toasts.append((message, kwargs))

        host = Host()
        host._move_timeline_clips(SimpleNamespace(
            selections=((first, "first"), (second, "second")),
            delta_ms=125.0,
            primary_key=(1, "first"),
        ))

        self.assertEqual(len(host.publications), 1)
        plan, reason = host.publications[0]
        self.assertEqual(reason, "move selected arrangement clips")
        self.assertEqual(
            host.publications[0][0].selected_clip_id, "first"
        )
        self.assertEqual(
            host.publish_kwargs,
            [{"selected_clip_keys": ((1, "first"), (2, "second"))}],
        )
        self.assertEqual(plan.selected_track_id, 1)
        self.assertEqual(
            tuple(
                update.arrangement_clips[0].start_ms
                for update in plan.updates
            ),
            (225.0, 625.0),
        )
        self.assertEqual(len(host.toasts), 1)

    def test_move_multiple_clips_preserves_relative_layout_and_notes(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(62, 90, 500.0, 100.0, 0),
        ])
        source.arrangement_clips = [
            ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("second", 500.0, 600.0, 500.0, 600.0),
        ]

        plan = plan_clips_move(
            source, clip_ids=("first", "second"), delta_ms=250.0
        )

        update = plan.updates[0]
        self.assertEqual(update.notes, tuple(source.notes))
        self.assertEqual(
            tuple((clip.start_ms, clip.end_ms) for clip in update.arrangement_clips),
            ((350.0, 450.0), (750.0, 850.0)),
        )
        self.assertEqual(
            tuple(clip.time_offset_ms for clip in update.arrangement_clips),
            (250.0, 250.0),
        )
        moved = deepcopy(source)
        moved.arrangement_clips = list(update.arrangement_clips)
        self.assertEqual(
            tuple(
                (note.pitch, note.vel, note.start, note.dur, note.ntype)
                for note in project_track_notes(moved)
            ),
            (
                (60, 90, 350.0, 100.0, 0),
                (62, 90, 750.0, 100.0, 0),
            ),
        )
        self.assertEqual(moved.bdo_instrument_id, source.bdo_instrument_id)

    def test_move_multiple_clips_rejects_unselected_overlap_atomically(self) -> None:
        source = _track(1)
        source.arrangement_clips = [
            ArrangementClipState("move", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("keep", 300.0, 400.0, 300.0, 400.0),
        ]

        with self.assertRaisesRegex(ClipEditError, "overlap"):
            plan_clips_move(source, clip_ids=("move",), delta_ms=150.0)

        self.assertEqual(source.arrangement_clips[0].start_ms, 100.0)

    def test_host_batches_cross_track_selection_into_one_publication(self) -> None:
        first = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(64, 90, 900.0, 100.0, 0),
        ])
        first.arrangement_clips = [
            ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("keep", 900.0, 1000.0, 900.0, 1000.0),
        ]
        second = _track(2, [Note(62, 90, 500.0, 100.0, 0)])
        second.arrangement_clips = [
            ArrangementClipState("second", 500.0, 600.0, 500.0, 600.0)
        ]

        class Host(ArrangementClipHostMixin):
            def __init__(self) -> None:
                self.tracks = [first, second]
                self.selected_track = second
                self.publications = []
                self.toasts = []

            def _publish_clip_plan(self, plan, reason, **_kwargs) -> None:
                self.publications.append((plan, reason))

            def show_toast(self, message, **kwargs) -> None:
                self.toasts.append((message, kwargs))

        host = Host()
        host._delete_timeline_clips((
            (second, "second"),
            (first, "first"),
            (second, "second"),
        ))

        self.assertEqual(len(host.publications), 1)
        plan, reason = host.publications[0]
        self.assertEqual(reason, "delete arrangement clip")
        self.assertEqual(plan.selected_track_id, 1)
        self.assertEqual(plan.selected_clip_id, "keep")
        self.assertEqual(
            tuple(update.track_id for update in plan.updates), (1, 2)
        )
        self.assertEqual(
            tuple(note.pitch for note in plan.updates[0].notes), (64,)
        )
        self.assertEqual(
            tuple(
                clip.clip_id
                for clip in plan.updates[0].arrangement_clips
            ),
            ("keep",),
        )
        self.assertFalse(plan.updates[1].notes)
        self.assertFalse(plan.updates[1].arrangement_clips)
        self.assertEqual(len(host.toasts), 1)

    def test_delete_multiple_clips_is_atomic_and_preserves_sibling(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(62, 90, 500.0, 100.0, 0),
            Note(64, 90, 900.0, 100.0, 0),
        ])
        source.arrangement_clips = [
            ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("second", 500.0, 600.0, 500.0, 600.0),
            ArrangementClipState("keep", 900.0, 1000.0, 900.0, 1000.0),
        ]

        plan = plan_clips_delete(
            source, clip_ids=("second", "first", "second")
        )

        self.assertEqual(plan.selected_clip_id, "keep")
        self.assertEqual(
            plan.updates[0].notes,
            (Note(64, 90, 900.0, 100.0, 0),),
        )
        self.assertEqual(
            tuple(
                clip.clip_id
                for clip in plan.updates[0].arrangement_clips
            ),
            ("keep",),
        )
        self.assertEqual(source.note_count, 3)
        self.assertEqual(len(source.arrangement_clips), 3)

    def test_delete_multiple_clips_rejects_stale_selection_before_mutation(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.arrangement_clips = [
            ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0)
        ]

        with self.assertRaisesRegex(ClipEditError, "unavailable"):
            plan_clips_delete(source, clip_ids=("first", "missing"))

        self.assertEqual(source.note_count, 1)
        self.assertEqual(source.arrangement_clips[0].clip_id, "first")

    def test_delete_clip_removes_exclusive_notes_controls_and_records(self) -> None:
        source = _track(1, [
            Note(60, 90, 100.0, 100.0, 0),
            Note(64, 80, 500.0, 100.0, 0),
        ])
        source.performance_controls = [
            {"time": 150.0, "kind": "pitchwheel"},
            {"time": 550.0, "kind": "cc"},
        ]
        source.bdo_source_note_records = (
            (60, 90, 100.0, 100.0, 0, 75),
            (64, 80, 500.0, 100.0, 0, 70),
        )
        source.arrangement_clips = [
            ArrangementClipState("delete", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("keep", 500.0, 600.0, 500.0, 600.0),
        ]

        plan = plan_clip_delete(source, clip_id="delete")

        self.assertEqual(plan.selected_clip_id, "keep")
        self.assertEqual(plan.updates[0].notes, (
            Note(64, 80, 500.0, 100.0, 0),
        ))
        self.assertEqual(
            plan.updates[0].performance_controls,
            ({"time": 550.0, "kind": "cc"},),
        )
        self.assertEqual(
            plan.updates[0].source_note_records,
            ((64, 80, 500.0, 100.0, 0, 70),),
        )
        self.assertEqual(
            tuple(clip.clip_id for clip in plan.updates[0].arrangement_clips),
            ("keep",),
        )

    def test_delete_shared_clip_preserves_sibling_content(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.arrangement_clips = [
            ArrangementClipState("delete", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("keep", 600.0, 700.0, 100.0, 200.0, 500.0),
        ]

        plan = plan_clip_delete(source, clip_id="delete")
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(plan.updates[0].arrangement_clips)

        self.assertEqual(updated.notes, source.notes)
        self.assertEqual(
            clip_editor_notes(updated, "keep"),
            (Note(60, 90, 600.0, 100.0, 0),),
        )

    def test_delete_last_empty_clip_leaves_empty_track(self) -> None:
        source = _track(1)
        source.arrangement_clips = [default_empty_clip(1, duration_ms=500.0)]

        plan = plan_clip_delete(source, clip_id="track-1-main")

        self.assertEqual(plan.selected_clip_id, "")
        self.assertEqual(plan.updates[0].notes, ())
        self.assertEqual(plan.updates[0].arrangement_clips, ())

    def test_delete_preserves_malformed_legacy_metadata_fail_closed(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.performance_controls = [{"time": "legacy", "kind": "cc"}]
        source.bdo_source_note_records = (("legacy",),)
        source.arrangement_clips = [
            ArrangementClipState("delete", 100.0, 200.0, 100.0, 200.0)
        ]

        plan = plan_clip_delete(source, clip_id="delete")

        self.assertEqual(
            plan.updates[0].performance_controls,
            ({"time": "legacy", "kind": "cc"},),
        )
        self.assertEqual(plan.updates[0].source_note_records, (("legacy",),))

    def test_clip_editor_scope_uses_exact_moved_timeline_bounds(self) -> None:
        track = _track(1, [Note(60, 80, 100.0, 100.0, 0)])
        track.arrangement_clips = [
            ArrangementClipState("moved", 900.0, 1_500.0, 100.0, 700.0, 800.0)
        ]

        scope = clip_editor_scope(track, "moved")

        self.assertEqual(
            (scope.timeline_start_ms, scope.timeline_end_ms, scope.duration_ms),
            (900.0, 1_500.0, 600.0),
        )
        self.assertEqual(scope.fingerprint, clip_edit_fingerprint(track, "moved"))
        self.assertTrue(scope.contains_note(Note(60, 80, 900.0, 600.0, 0)))
        self.assertFalse(scope.contains_note(Note(60, 80, 1_499.0, 2.0, 0)))

    def test_clip_editor_projects_crossing_note_and_unchanged_apply_is_lossless(self) -> None:
        original = Note(60, 90, 100.0, 300.0, 0)
        track = _track(1, [original])
        track.arrangement_clips = [
            ArrangementClipState("trimmed", 200.0, 350.0, 100.0, 400.0)
        ]

        visible = clip_editor_notes(track, "trimmed")
        self.assertEqual(visible, (Note(60, 90, 200.0, 150.0, 0),))

        plan = plan_clip_note_edit(track, clip_id="trimmed", notes=visible)

        self.assertEqual(plan.updates[0].notes, (original,))
        self.assertEqual(
            plan.updates[0].arrangement_clips,
            tuple(track.arrangement_clips),
        )

    def test_clip_note_plan_reports_structured_out_of_scope_error(self) -> None:
        track = _track(1)
        track.arrangement_clips = [
            ArrangementClipState("clip", 100.0, 500.0, 100.0, 500.0)
        ]

        with self.assertRaises(ClipEditError) as raised:
            plan_clip_note_edit(
                track,
                clip_id="clip",
                notes=(Note(60, 90, 450.0, 100.0, 0),),
            )

        self.assertEqual(raised.exception.code, "note_out_of_scope")

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

    def test_new_note_in_extended_clip_space_expands_content_ownership(self) -> None:
        source = _track(1, [Note(60, 90, 0.0, 100.0, 0)])
        source.arrangement_clips = [ArrangementClipState(
            "extended", 0.0, 400.0, 0.0, 100.0
        )]

        plan = plan_clip_note_edit(
            source,
            clip_id="extended",
            notes=(
                Note(60, 90, 0.0, 100.0, 0),
                Note(64, 80, 250.0, 100.0, 0),
            ),
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(
            plan.updates[0].arrangement_clips
        )

        self.assertEqual(
            clip_editor_notes(updated, "extended"),
            (
                Note(60, 90, 0.0, 100.0, 0),
                Note(64, 80, 250.0, 100.0, 0),
            ),
        )
        self.assertEqual(
            updated.arrangement_clips[0].content_end_ms, 350.0
        )

    def test_uniquely_recoverable_legacy_orphan_is_visible_and_repaired(self) -> None:
        source = _track(1, [
            Note(60, 90, 0.0, 100.0, 0),
            Note(64, 80, 250.0, 100.0, 0),
        ])
        source.arrangement_clips = [ArrangementClipState(
            "extended", 0.0, 400.0, 0.0, 100.0
        )]

        visible = clip_editor_notes(source, "extended")
        self.assertEqual(
            visible,
            (
                Note(60, 90, 0.0, 100.0, 0),
                Note(64, 80, 250.0, 100.0, 0),
            ),
        )
        self.assertEqual(project_track_notes(source), visible)

        plan = plan_clip_note_edit(
            source, clip_id="extended", notes=visible
        )
        self.assertEqual(
            plan.updates[0].arrangement_clips[0].content_end_ms,
            350.0,
        )

    def test_new_note_in_extended_moved_clip_keeps_timeline_position(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.arrangement_clips = [ArrangementClipState(
            "moved", 900.0, 1_300.0, 100.0, 200.0, 800.0
        )]

        plan = plan_clip_note_edit(
            source,
            clip_id="moved",
            notes=(
                Note(60, 90, 900.0, 100.0, 0),
                Note(67, 85, 1_150.0, 100.0, 0),
            ),
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(
            plan.updates[0].arrangement_clips
        )

        self.assertEqual(
            [(note.pitch, note.start) for note in clip_editor_notes(
                updated, "moved"
            )],
            [(60, 900.0), (67, 1_150.0)],
        )

    def test_editing_shared_content_detaches_complete_target_projection(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.arrangement_clips = [
            ArrangementClipState("target", 100.0, 400.0, 100.0, 200.0),
            ArrangementClipState("sibling", 600.0, 700.0, 100.0, 200.0, 500.0),
        ]

        plan = plan_clip_note_edit(
            source,
            clip_id="target",
            notes=(
                Note(60, 90, 100.0, 100.0, 0),
                Note(64, 80, 300.0, 50.0, 0),
            ),
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(
            plan.updates[0].arrangement_clips
        )

        self.assertEqual(
            [(note.pitch, note.start) for note in clip_editor_notes(
                updated, "target"
            )],
            [(60, 100.0), (64, 300.0)],
        )
        self.assertEqual(
            clip_editor_notes(updated, "sibling"),
            (Note(60, 90, 600.0, 100.0, 0),),
        )

    def test_content_expansion_collision_detaches_without_orphan_copy(self) -> None:
        source = _track(1, [
            Note(60, 90, 0.0, 100.0, 0),
            Note(72, 70, 500.0, 100.0, 0),
        ])
        source.arrangement_clips = [
            ArrangementClipState("target", 0.0, 600.0, 0.0, 100.0),
            ArrangementClipState(
                "sibling", 1_000.0, 1_100.0,
                500.0, 600.0, 500.0,
            ),
        ]

        plan = plan_clip_note_edit(
            source,
            clip_id="target",
            notes=(
                Note(60, 90, 0.0, 100.0, 0),
                Note(67, 80, 550.0, 50.0, 0),
            ),
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(
            plan.updates[0].arrangement_clips
        )

        self.assertEqual(len(updated.notes), 3)
        self.assertEqual(
            [(note.pitch, note.start) for note in clip_editor_notes(
                updated, "target"
            )],
            [(60, 0.0), (67, 550.0)],
        )
        self.assertEqual(
            clip_editor_notes(updated, "sibling"),
            (Note(72, 70, 1_000.0, 100.0, 0),),
        )

    def test_delete_from_shared_content_preserves_sibling(self) -> None:
        source = _track(1, [Note(60, 90, 100.0, 100.0, 0)])
        source.arrangement_clips = [
            ArrangementClipState("target", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("sibling", 600.0, 700.0, 100.0, 200.0, 500.0),
        ]

        plan = plan_clip_note_edit(
            source, clip_id="target", notes=()
        )
        updated = deepcopy(source)
        updated.notes = list(plan.updates[0].notes)
        updated.arrangement_clips = list(
            plan.updates[0].arrangement_clips
        )

        self.assertEqual(clip_editor_notes(updated, "target"), ())
        self.assertEqual(
            clip_editor_notes(updated, "sibling"),
            (Note(60, 90, 600.0, 100.0, 0),),
        )

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

    def test_resize_can_use_empty_edges_but_cannot_trim_notes(self) -> None:
        source = _track(1, [Note(60, 90, 200.0, 100.0, 0)])
        source.arrangement_clips = [ArrangementClipState(
            "editable", 100.0, 400.0, 100.0, 400.0
        )]

        left = plan_clip_edit(
            source,
            mode="resize_start",
            new_start_ms=150.0,
            new_end_ms=400.0,
            clip_id="editable",
        )
        self.assertEqual(
            left.updates[0].arrangement_clips[0].start_ms, 150.0
        )
        right = plan_clip_edit(
            source,
            mode="resize_end",
            new_start_ms=100.0,
            new_end_ms=350.0,
            clip_id="editable",
        )
        self.assertEqual(
            right.updates[0].arrangement_clips[0].end_ms, 350.0
        )

        for mode, start, end in (
            ("resize_start", 250.0, 400.0),
            ("resize_end", 100.0, 250.0),
        ):
            with self.assertRaises(ClipEditError) as raised:
                plan_clip_edit(
                    source,
                    mode=mode,
                    new_start_ms=start,
                    new_end_ms=end,
                    clip_id="editable",
                )
            self.assertEqual(raised.exception.code, "clip_resize_over_notes")

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
