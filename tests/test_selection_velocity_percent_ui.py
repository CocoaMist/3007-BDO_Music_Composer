from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SelectionVelocityPercentUiTests(unittest.TestCase):
    def test_scope_track_multiselect_and_materialized_clip_percentage(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication

            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import ArrangementClipState
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            first = TrackState(
                1,
                [Note(60, 80, 0.0, 100.0, 0), Note(64, 100, 500.0, 100.0, 0)],
                0, False, "Piano", 0x0B,
                arrangement_clips=[
                    ArrangementClipState("a", 0.0, 300.0, 0.0, 300.0),
                    ArrangementClipState("b", 500.0, 700.0, 500.0, 700.0),
                ],
            )
            second = TrackState(
                2, [Note(67, 70, 0.0, 100.0, 0)], 0, False, "Strings", 0x0B,
                arrangement_clips=[ArrangementClipState("c", 0.0, 300.0, 0.0, 300.0)],
            )
            window.tracks = [first, second]
            window.timeline.set_tracks(window.tracks)
            window._autosave_project = lambda *args, **kwargs: None
            window._restart_preview_after_timeline_change = lambda *args, **kwargs: None

            window.timeline.set_selected_clip(first, "a")
            assert window.timeline.selection_scope == "clip"
            assert window.timeline.selected_track is first
            assert window.toolbar_velocity_scope.text() == "作用域：Clip · a"
            window._begin_selection_velocity_percent()
            window._preview_selection_velocity_percent(140)
            window._commit_selection_velocity_percent()
            assert [note.vel for note in first.notes] == [112, 100]
            assert [clip.velocity_percent for clip in first.arrangement_clips] == [140, 100]

            # Synchronising the parent Track must retain the Clip edit scope.
            window._select_track(first)
            assert window.timeline.selection_scope == "clip"
            assert window.timeline.selected_clip_keys == frozenset({(1, "a")})

            window.timeline._select_pointer_track(first, Qt.NoModifier)
            window.timeline._select_pointer_track(second, Qt.ShiftModifier)
            assert window.timeline.selection_scope == "track"
            assert {track.track_id for track in window.timeline.selected_track_items()} == {1, 2}
            assert "2 条轨道" in window.toolbar_velocity_scope.text()
            window._begin_selection_velocity_percent()
            window._preview_selection_velocity_percent(120)
            window._commit_selection_velocity_percent()
            assert [clip.velocity_percent for clip in first.arrangement_clips] == [120, 120]
            assert [clip.velocity_percent for clip in second.arrangement_clips] == [120]
            assert [note.vel for note in first.notes] == [96, 120]
            assert [note.vel for note in second.notes] == [84]

            window.toolbar_global_gain_mode.setCurrentIndex(1)
            assert window.toolbar_global_gain_mode.currentData() == "percent"
            assert window.toolbar_global_gain.value() == 100
            assert window.toolbar_global_gain_value.suffix() == "%"
            window._begin_toolbar_global_gain_drag()
            window.toolbar_global_gain.setValue(50)
            window._commit_toolbar_global_gain()
            assert [note.vel for note in first.notes] == [48, 60]
            assert [note.vel for note in second.notes] == [42]
            window.toolbar_global_gain_mode.setCurrentIndex(0)
            assert window.toolbar_global_gain.value() == 0
            assert [note.vel for note in first.notes] == [48, 60]
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_scoped_edit_reanchors_global_session_without_stale_overwrite(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import (
                ArrangementClipState, TrackState,
            )
            from bdo_music_composer.ui.main_window import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1, [Note(60, 80, 0.0, 100.0, 0)],
                0, False, "Piano", 0x0B,
                bdo_source_note_records=((60, 80, 0.0, 100.0, 0, 60),),
                arrangement_clips=[
                    ArrangementClipState("a", 0.0, 200.0, 0.0, 200.0)
                ],
            )
            window.tracks = [track]
            window.timeline.set_tracks([track])
            window._autosave_project = lambda *args, **kwargs: None
            window._restart_preview_after_timeline_change = lambda *args, **kwargs: None
            window._push_project_snapshot = lambda: None
            window.timeline.set_selected_clip(track, "a")

            def local(percent):
                window._begin_selection_velocity_percent()
                window._preview_selection_velocity_percent(percent)
                window._commit_selection_velocity_percent()

            def global_percent(percent):
                window._begin_toolbar_global_gain_drag()
                window.toolbar_global_gain.setValue(percent)
                window._commit_toolbar_global_gain()

            local(140)
            window.toolbar_global_gain_mode.setCurrentIndex(1)
            global_percent(50)
            assert track.notes[0].vel == 56
            assert track.arrangement_clips[0].velocity_baseline_a == (40,)

            local(120)
            assert track.notes[0].vel == 48
            assert track.bdo_source_note_records[0][5] == 36
            assert window.toolbar_global_gain.value() == 100

            # The new global session starts from the scoped result instead of
            # replaying the stale pre-50% note value (the former 112 bug).
            global_percent(200)
            assert track.notes[0].vel == 96
            assert track.arrangement_clips[0].velocity_percent == 120
            assert track.arrangement_clips[0].velocity_baseline_a == (80,)
            assert track.bdo_source_note_records[0][5] == 72

            local(100)
            assert track.notes[0].vel == 80
            assert track.bdo_source_note_records[0][5] == 60
            assert track.arrangement_clips[0].velocity_baseline_a == (80,)
            assert window.toolbar_global_gain.value() == 100
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
