from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CrossEditorNoteClipboardUiTests(unittest.TestCase):
    def test_copy_paste_crosses_open_clip_editors_without_silent_clamping(self) -> None:
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(
                """
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.arrangement_clip import project_track_notes
                from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                app = QApplication([])
                window = MidiToBdoWindow()
                autosaves = []
                window._autosave_project = lambda reason, immediate=False: (
                    autosaves.append((reason, immediate)) or True
                )
                window._stop_preview = lambda *_args, **_kwargs: None
                source = TrackState(
                    1,
                    [
                        Note(60, 77, 100.0, 80.0, 5),
                        Note(64, 91, 225.0, 120.0, 0),
                    ],
                    0, False, "Source", 0x0A,
                    arrangement_clips=[ArrangementClipState(
                        "source", 100.0, 400.0, 100.0, 400.0
                    )],
                )
                target = TrackState(
                    2, [], 0, False, "Target", 0x0A,
                    arrangement_clips=[ArrangementClipState(
                        "target", 500.0, 900.0, 500.0, 900.0
                    )],
                )
                window.tracks = [source, target]
                window.timeline.set_tracks(window.tracks)
                window._open_clip_note_editor(source, "source")
                window._open_clip_note_editor(target, "target")
                app.processEvents()
                editors = {
                    editor.arrangement_clip_id: editor
                    for editor in window._note_editors.values()
                }
                source_editor = editors["source"]
                target_editor = editors["target"]

                source_editor.canvas.selected = {0, 1}
                source_editor.copy_selected()
                assert source_editor.clipboard
                assert target_editor.clipboard == []
                source_editor.close()
                app.processEvents()
                target_editor.snap_box.setChecked(False)
                target_editor.canvas.set_edit_cursor(600.0)
                autosaves.clear()
                target_editor.paste_notes()
                app.processEvents()

                pasted = project_track_notes(target)
                assert pasted == (
                    Note(60, 77, 600.0, 80.0, 5),
                    Note(64, 91, 725.0, 120.0, 0),
                ), pasted
                assert target_editor.canvas.selected == {0, 1}
                assert len(target_editor.undo_stack) == 1
                assert autosaves == [("live arrangement clip note edit", True)]
                target_editor.undo()
                assert project_track_notes(target) == ()
                target_editor.redo()
                assert project_track_notes(target) == pasted

                before = target_editor.edited_notes()
                undo_count = len(target_editor.undo_stack)
                target_editor.canvas.set_edit_cursor(875.0)
                target_editor.paste_notes()
                app.processEvents()
                assert target_editor.edited_notes() == before
                assert len(target_editor.undo_stack) == undo_count

                target_editor.close()
                window.close()
                app.processEvents()
                """
            )],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
