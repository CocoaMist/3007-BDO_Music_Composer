from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(script: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


class ClipEditorScopeUiTests(unittest.TestCase):
    def test_scope_controls_time_domain_multiple_editors_and_autosave(self) -> None:
        completed = _run_offscreen(
            """
            from types import SimpleNamespace
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_music_composer.editor.arrangement_clip import project_track_notes
            from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
            from bdo_music_composer.ui.main_window import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            autosaves = []
            window._autosave_project = (
                lambda reason, immediate=False:
                autosaves.append((reason, immediate))
            )
            window._stop_preview = lambda *_args, **_kwargs: None
            target = Note(60, 80, 100.0, 100.0, 0)
            sibling = Note(64, 90, 500.0, 100.0, 0)
            track = TrackState(1, [target, sibling], 0, False, "Track", 0x12)
            track.arrangement_clips = [
                ArrangementClipState("first", 100.0, 200.0, 100.0, 200.0),
                ArrangementClipState("second", 900.0, 1000.0, 500.0, 600.0, 400.0),
            ]
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)

            window._open_clip_note_editor(track, "first")
            window._open_clip_note_editor(track, "second")
            app.processEvents()
            assert len(window._note_editors) == 2
            editors = {
                editor.arrangement_clip_id: editor
                for editor in window._note_editors.values()
            }
            first = editors["first"]
            second = editors["second"]
            assert first.clip_scope.timeline_start_ms == 100.0
            assert first.clip_scope.timeline_end_ms == 200.0
            assert first.draft_start_ms() == 100.0
            assert first.draft_duration_ms() == 200.0
            assert first.time_scroll.minimum() == 100
            assert first.canvas.time_at(first.canvas.width()) == 200.0
            constrained = first.build_created_note(
                pitch=67, start_ms=250.0, duration_ms=100.0
            )
            assert 100.0 <= constrained.start < 200.0
            assert constrained.start + constrained.dur <= 200.0

            window._activate_note_editor(first)
            autosaves.clear()
            first.canvas.notes = [Note(62, 81, 120.0, 60.0, 0)]
            first._notes_changed()
            assert [(note.pitch, note.start) for note in project_track_notes(track)] == [
                (62, 120.0), (64, 900.0)
            ]
            assert first.last_applied == first.edited_notes()
            assert len(window.project_commands._undo) == 1
            assert autosaves == [
                ("live arrangement clip note edit", True)
            ], autosaves
            assert first.clip_start_spin.maximum() == 120.0
            assert first.clip_end_spin.minimum() == (
                first.edited_notes()[0].start + first.edited_notes()[0].dur
            )
            recovery = window._autosave_track_view()[0]
            assert [(note.pitch, note.start) for note in project_track_notes(recovery)] == [
                (62, 120.0), (64, 900.0)
            ]

            # Editor boundary controls and mixer handles share one rule: empty
            # edge space is resizable, occupied note time is not.
            first._request_clip_resize("resize_end", 300.0)
            assert track.arrangement_clips[0].end_ms == 300.0
            assert first.clip_scope.timeline_end_ms == 300.0
            assert first.clip_end_spin.value() == 300.0

            # Reproduce the canvas transaction boundary: append a created
            # note, emit the same completed-edit signal, click Done, then
            # reopen the same Clip.
            first.raise_()
            first.activateWindow()
            app.processEvents()
            first.push_snapshot()
            first.canvas.notes.append(first.build_created_note(
                pitch=67, start_ms=190.0, duration_ms=80.0
            ))
            first.canvas.notes_changed.emit()
            app.processEvents()
            assert any(
                note.pitch == 67
                for note in project_track_notes(track)
            ), (first.edited_notes(), project_track_notes(track))
            first.undo()
            assert all(
                note.pitch != 67 for note in project_track_notes(track)
            )
            first.redo()
            assert any(
                note.pitch == 67 for note in project_track_notes(track)
            )
            QTest.mouseClick(first.confirm_button, Qt.LeftButton)
            app.processEvents()
            assert all(
                editor.arrangement_clip_id != "first"
                for editor in window._note_editors.values()
            )
            window._open_clip_note_editor(track, "first")
            app.processEvents()
            first = next(
                editor for editor in window._note_editors.values()
                if editor.arrangement_clip_id == "first"
            )
            assert any(
                note.pitch == 67 for note in first.edited_notes()
            ), first.edited_notes()

            # The window close control is not a cancel boundary for a live
            # Clip editor.  A completed canvas transaction must remain in the
            # formal project and be present when the Clip is reopened.
            first.push_snapshot()
            first.canvas.notes.append(first.build_created_note(
                pitch=69, start_ms=200.0, duration_ms=50.0
            ))
            first.canvas.notes_changed.emit()
            app.processEvents()
            assert any(
                note.pitch == 69 for note in project_track_notes(track)
            )
            first.close()
            app.processEvents()
            assert all(
                editor.arrangement_clip_id != "first"
                for editor in window._note_editors.values()
            )
            window._open_clip_note_editor(track, "first")
            app.processEvents()
            first = next(
                editor for editor in window._note_editors.values()
                if editor.arrangement_clip_id == "first"
            )
            assert any(note.pitch == 69 for note in first.edited_notes())
            window._commit_timeline_clip_edit(SimpleNamespace(
                source_track=track,
                target_track=track,
                mode="resize_start",
                new_start_ms=110.0,
                new_end_ms=300.0,
                clip_id="first",
            ))
            assert track.arrangement_clips[0].start_ms == 110.0
            assert first.clip_scope.timeline_start_ms == 110.0
            window._commit_timeline_clip_edit(SimpleNamespace(
                source_track=track,
                target_track=track,
                mode="resize_start",
                new_start_ms=130.0,
                new_end_ms=300.0,
                clip_id="first",
            ))
            assert track.arrangement_clips[0].start_ms == 110.0

            # Blank lane context menu exposes clip creation at the clicked time.
            menu, actions = window.timeline._build_track_context_menu(
                track, create_clip_at_ms=1234.0
            )
            assert actions["create_clip"].text() == "在此处创建片段"
            assert actions["create_clip"].data() == 1234.0
            menu.close()

            # A concurrent target change invalidates only the recovery overlay;
            # formal project state remains the safe snapshot.
            track.notes[0] = track.notes[0]._replace(vel=110)
            stale_recovery = window._autosave_track_view()[0]
            assert stale_recovery is track
            assert track.notes[0].vel == 110

            # Every open Clip editor publishes completed transactions even
            # when it is not the active dialog.  The formal TrackState is the
            # autosave source and each transaction is serialized only once.
            window._activate_note_editor(first)
            autosaves.clear()
            second.canvas.notes = [Note(65, 91, 920.0, 50.0, 0)]
            second._notes_changed()
            assert any(
                note.pitch == 65 and note.start == 920.0
                for note in project_track_notes(track)
            )
            assert autosaves == [
                ("live arrangement clip note edit", True)
            ], autosaves
            inactive_recovery = window._autosave_track_view()[0]
            assert any(
                note.pitch == 65 and note.start == 920.0
                for note in project_track_notes(inactive_recovery)
            )

            # Deleting through the host removes exclusive content, clears the
            # selected Clip through the same transaction, closes its now-
            # orphan editor, and checkpoints exactly once.
            autosaves.clear()
            window._delete_timeline_clip(track, "second")
            app.processEvents()
            assert all(
                clip.clip_id != "second" for clip in track.arrangement_clips
            )
            assert all(
                editor.arrangement_clip_id != "second"
                for editor in window._note_editors.values()
            )
            assert all(
                note.pitch != 65 for note in project_track_notes(track)
            )
            assert autosaves == [
                ("delete arrangement clip", True)
            ], autosaves

            deleted_snapshot = window.project_commands.undo(
                window._project_snapshot()
            )
            assert deleted_snapshot is not None
            window._restore_project_snapshot(
                deleted_snapshot, "project undo"
            )
            app.processEvents()
            restored = window.tracks[0]
            assert any(
                clip.clip_id == "second"
                for clip in restored.arrangement_clips
            )
            assert any(
                note.pitch == 65 and note.start == 920.0
                for note in project_track_notes(restored)
            )
            assert autosaves[-1] == ("project undo", True)

            window._close_all_note_editors()
            window._final_autosave_queued = True
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
