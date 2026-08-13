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
                assert window.timeline.arrangement_tool == "marquee"
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
                from bdo_music_composer.editor.arrangement_clip import plan_clip_edit
                sync_plan = plan_clip_edit(
                    window.tracks[0],
                    mode="resize_end",
                    new_start_ms=225.0,
                    new_end_ms=350.0,
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
                from bdo_music_composer.editor.arrangement_clip import project_track_notes
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
                window._create_timeline_clip(empty, 900.0)
                assert len(empty.notes) == 1
                assert empty.notes[0].start == 900.0
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
