from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NoteEditorCreatorWorkspaceTests(unittest.TestCase):
    def test_creator_tools_keep_formal_track_transactional(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            formal_note = Note(60, 96, 0, 400, 0)
            track = TrackState(1, [formal_note], 0, False, "lead", 0x0B)
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(1280, 760)
            editor.show()
            app.processEvents()

            assert editor.editor_tool_rail.isVisible()
            assert not editor.editor_properties_bar.isVisible()
            assert editor.active_note_tool == "select"
            assert editor.split_note_at(0, 200)
            assert len(editor.canvas.notes) == 2
            assert track.notes == [formal_note]
            editor.undo()
            assert editor.canvas.notes == [formal_note]

            editor.erase_tool_button.click()
            assert editor.active_note_tool == "erase"
            rect = editor.canvas.note_rect(editor.canvas.notes[0])
            QTest.mouseClick(
                editor.canvas,
                Qt.LeftButton,
                pos=QPoint(round(rect.center().x()), round(rect.center().y())),
            )
            assert editor.canvas.notes == []
            assert track.notes == [formal_note]
            editor.undo()
            assert editor.canvas.notes == [formal_note]

            editor.scale_combo.setCurrentIndex(1)
            assert editor.canvas.scale_pitch_classes == frozenset({0, 2, 4, 5, 7, 9, 11})
            editor.canvas.selected = {0}
            editor.refresh_fields()
            assert editor.editor_properties_bar.isVisible()
            assert editor.editor_properties_bar.height() == 44
            editor.follow_playhead_box.setChecked(False)
            assert not editor.follow_playhead_enabled
            editor.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        with tempfile.TemporaryDirectory() as user_data_dir:
            env["BDO_USER_DATA_DIR"] = user_data_dir
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
