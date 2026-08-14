from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArrangementClipUiTests(unittest.TestCase):
    def test_host_commit_moves_clip_across_tracks_as_one_undo_step(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from types import SimpleNamespace
                from PySide6.QtWidgets import QApplication, QMessageBox
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                def track(track_id, notes):
                    return TrackState(
                        track_id=track_id, notes=notes, gm_program=0,
                        is_percussion=False, display_name=str(track_id),
                        bdo_instrument_id=0x12,
                    )

                app = QApplication([])
                window = MidiToBdoWindow()
                group_first = track(11, [Note(60, 90, 100.0, 100.0, 0)])
                group_second = track(12, [Note(64, 90, 500.0, 100.0, 0)])
                window.tracks = [group_first, group_second]
                window._refresh_tracks()
                window._select_track(group_second)
                window.timeline.set_selected_clip_keys({
                    (11, "track-11-main"), (12, "track-12-main")
                }, primary_key=(12, "track-12-main"))
                autosaves = []
                window._autosave_project = lambda reason, immediate=False: (
                    autosaves.append((reason, immediate))
                )
                window._move_timeline_clips(SimpleNamespace(
                    selections=(
                        (group_first, "track-11-main"),
                        (group_second, "track-12-main"),
                    ),
                    delta_ms=125.0,
                ))
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                })
                assert window.timeline.arrangement_tool == "select"
                assert window.selected_track is group_second
                assert autosaves == [
                    ("move selected arrangement clips", True)
                ]
                window._move_timeline_clips(SimpleNamespace(
                    selections=(
                        (group_first, "track-11-main"),
                        (group_second, "track-12-main"),
                    ),
                    delta_ms=25.0,
                    primary_key=(12, "track-12-main"),
                ))
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                })
                assert window.timeline._selected_clip_track_id == 12
                assert autosaves == [
                    ("move selected arrangement clips", True),
                    ("move selected arrangement clips", True),
                ]
                window._undo_project()
                assert window.selected_track.track_id == 12
                assert window.timeline.selected_track.track_id == 12
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                })
                window._redo_project()
                assert window.selected_track.track_id == 12
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                })
                lower = track(13, [])
                window.tracks.append(lower)
                window._refresh_tracks()
                autosave_count = len(autosaves)
                window._move_timeline_clips(SimpleNamespace(
                    selections=(
                        (window.tracks[0], "track-11-main"),
                        (window.tracks[1], "track-12-main"),
                    ),
                    delta_ms=0.0,
                    track_offset=1,
                    primary_key=(12, "track-12-main"),
                ))
                assert window.timeline.selected_clip_keys == frozenset({
                    (12, "track-11-main"), (13, "track-12-main")
                })
                assert window.timeline._selected_clip_track_id == 13
                assert len(autosaves) == autosave_count + 1
                assert autosaves[-1] == (
                    "move selected arrangement clips", True
                )
                from bdo_music_composer.editor.arrangement_clip import project_track_notes
                assert window.tracks[0].notes == []
                assert [note.pitch for note in project_track_notes(window.tracks[1])] == [60]
                assert [note.pitch for note in project_track_notes(window.tracks[2])] == [64]
                window._undo_project()
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                }), window.timeline.selected_clip_keys
                assert [note.pitch for note in project_track_notes(window.tracks[0])] == [60]
                assert [note.pitch for note in project_track_notes(window.tracks[1])] == [64]
                window._redo_project()
                assert window.timeline.selected_clip_keys == frozenset({
                    (12, "track-11-main"), (13, "track-12-main")
                })
                window._undo_project()
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                })
                from bdo_music_composer.editor.arrangement_clip import plan_clip_edit, track_clips
                scale_start = track_clips(window.tracks[0])[0].start_ms
                sync_plan = plan_clip_edit(
                    window.tracks[0],
                    mode="resize_end",
                    new_start_ms=scale_start,
                    new_end_ms=scale_start + 125.0,
                    clip_id="track-11-main",
                )
                window._publish_clip_plan(
                    sync_plan,
                    "test live clip synchronization",
                    push_snapshot=False,
                    preserve_clip_selection=True,
                )
                assert window.timeline.selected_clip_keys == frozenset({
                    (11, "track-11-main"), (12, "track-12-main")
                })
                window.project_commands.clear()

                source = track(1, [Note(60, 90, 100.0, 200.0, 0)])
                target = track(2, [Note(67, 80, 50.0, 100.0, 0)])
                window.tracks = [source, target]
                window._refresh_tracks()
                window._show_workspace()
                window.resize(1200, 760)
                window.show()
                app.processEvents()
                window.timeline.repaint()
                app.processEvents()
                assert any(
                    action.startswith("clip_body|") and item is source
                    for _rect, action, item in window.timeline.hit_regions
                )
                window._commit_timeline_clip_edit(SimpleNamespace(
                    source_track=source,
                    target_track=target,
                    mode="move",
                    new_start_ms=500.0,
                    new_end_ms=700.0,
                    clip_id="track-1-main",
                ))
                assert source.notes == []
                assert [note.start for note in project_track_notes(target)] == [50.0, 500.0]
                assert len(window.project_commands._undo) == 1
                window._undo_project()
                assert len(window.tracks[0].notes) == 1
                assert len(window.tracks[1].notes) == 1
                overlap_source = track(6, [Note(60, 90, 100.0, 100.0, 0)])
                overlap_target = track(7, [Note(64, 80, 400.0, 100.0, 0)])
                window.tracks = [overlap_source, overlap_target]
                window._refresh_tracks()
                undo_count = len(window.project_commands._undo)
                original_warning = QMessageBox.warning
                QMessageBox.warning = staticmethod(
                    lambda *_args, **_kwargs: QMessageBox.StandardButton.No
                )
                try:
                    window._commit_timeline_clip_edit(SimpleNamespace(
                        source_track=overlap_source,
                        target_track=overlap_target,
                        mode="move",
                        new_start_ms=450.0,
                        new_end_ms=550.0,
                        clip_id="track-6-main",
                    ))
                finally:
                    QMessageBox.warning = original_warning
                assert overlap_source.notes[0].start == 100.0
                assert overlap_target.notes[0].start == 400.0
                assert len(window.project_commands._undo) == undo_count
                empty = track(3, [])
                window.tracks.append(empty)
                window._refresh_tracks()
                window._open_note_editor = lambda _track: None
                create_undo_count = len(window.project_commands._undo)
                create_autosave_count = len(autosaves)
                window._create_timeline_clip(empty, 900.0)
                assert empty.notes == []
                created_clip = empty.arrangement_clips[0]
                assert created_clip.start_ms == 900.0
                assert created_clip.end_ms == 3900.0
                assert len(window.project_commands._undo) == create_undo_count + 1
                assert len(autosaves) == create_autosave_count + 1
                assert autosaves[-1] == ("create arrangement clip", True)
                window._undo_project()
                empty = next(
                    item for item in window.tracks if item.track_id == 3
                )
                assert empty.notes == []
                assert empty.arrangement_clips == []
                window._redo_project()
                empty = next(
                    item for item in window.tracks if item.track_id == 3
                )
                assert empty.notes == []
                assert len(empty.arrangement_clips) == 1
                assert empty.arrangement_clips[0].end_ms == 3900.0
                resize_undo_count = len(window.project_commands._undo)
                resize_autosave_count = len(autosaves)
                window._commit_timeline_clip_edit(SimpleNamespace(
                    source_track=empty,
                    target_track=empty,
                    mode="resize_end",
                    new_start_ms=900.0,
                    new_end_ms=2900.0,
                    clip_id=empty.arrangement_clips[0].clip_id,
                ))
                assert empty.notes == []
                assert empty.arrangement_clips[0].end_ms == 2900.0
                assert len(window.project_commands._undo) == resize_undo_count + 1
                assert len(autosaves) == resize_autosave_count + 1
                assert autosaves[-1] == ("arrangement clip edit", True)
                window._undo_project()
                empty = next(
                    item for item in window.tracks if item.track_id == 3
                )
                assert empty.arrangement_clips[0].end_ms == 3900.0
                window._redo_project()
                empty = next(
                    item for item in window.tracks if item.track_id == 3
                )
                assert empty.arrangement_clips[0].end_ms == 2900.0

                # Non-empty right-edge expansion is one command/autosave and
                # undo/redo never rewrite note timing or track properties.
                scaled_track = track(
                    8, [Note(60, 77, 100.0, 100.0, 5)]
                )
                scaled_track.bdo_track_volume = 42
                scaled_track.bdo_track_settings = (
                    11, 22, 33, 44, 55, 66, 77, 88
                )
                window.tracks = [scaled_track]
                window._refresh_tracks()
                window.project_commands.clear()
                scale_autosave_count = len(autosaves)
                window._commit_timeline_clip_edit(SimpleNamespace(
                    source_track=scaled_track,
                    target_track=scaled_track,
                    mode="resize_end",
                    new_start_ms=100.0,
                    new_end_ms=300.0,
                    clip_id="track-8-main",
                ))
                assert project_track_notes(scaled_track) == (
                    Note(60, 77, 100.0, 100.0, 5),
                )
                assert scaled_track.bdo_track_volume == 42
                assert scaled_track.bdo_track_settings == (
                    11, 22, 33, 44, 55, 66, 77, 88
                )
                assert len(window.project_commands._undo) == 1
                assert len(autosaves) == scale_autosave_count + 1
                assert autosaves[-1] == ("arrangement clip edit", True)
                window._undo_project()
                scaled_track = window.tracks[0]
                assert project_track_notes(scaled_track) == (
                    Note(60, 77, 100.0, 100.0, 5),
                )
                assert scaled_track.bdo_track_volume == 42
                assert scaled_track.bdo_track_settings == (
                    11, 22, 33, 44, 55, 66, 77, 88
                )
                window._redo_project()
                scaled_track = window.tracks[0]
                assert project_track_notes(scaled_track) == (
                    Note(60, 77, 100.0, 100.0, 5),
                )
                assert scaled_track.bdo_track_volume == 42
                assert scaled_track.bdo_track_settings == (
                    11, 22, 33, 44, 55, 66, 77, 88
                )

                risky_source = track(4, [Note(100, 90, 100.0, 100.0, 0)])
                risky_source.bdo_instrument_id = 0x11
                risky_target = track(5, [])
                risky_target.bdo_instrument_id = 0x12
                window.tracks = [risky_source, risky_target]
                window._refresh_tracks()
                window._commit_timeline_clip_edit(SimpleNamespace(
                    source_track=risky_source,
                    target_track=risky_target,
                    mode="move",
                    new_start_ms=300.0,
                    new_end_ms=400.0,
                    clip_id="track-4-main",
                ))
                notice = window.timeline.track_validation_notices[5]
                assert project_track_notes(risky_target)[0].start == 300.0
                assert notice["errors"]
                assert notice["invalid_note_keys"] == (
                    (100, 90, 300.0, 100.0, 0),
                )
                window.autosave_timer.stop()
                window.close()
                app.processEvents()
                print("arrangement-clip-ui-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("arrangement-clip-ui-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
