from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PianoRollInteractionTests(unittest.TestCase):
    def test_safe_creation_cursor_paste_and_ctrl_drag_clone(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QLabel
            from pyside_bdo_gui import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            track = TrackState(
                1,
                [
                    Note(60, 91, 0.0, 250.0, 0),
                    Note(64, 82, 750.0, 250.0, 0),
                ],
                0,
                False,
                "lead",
                0x0B,
            )
            window = MidiToBdoWindow()
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(1180, 720)
            editor.show()
            app.processEvents()
            assert editor.width() >= editor.minimumWidth()
            assert editor.height() >= editor.minimumHeight()
            track_title = editor.findChild(QLabel, "EditorTrackTitle")
            assert track_title is not None and track_title.text() == "lead"
            assert "lead" not in editor.track_meta.text()

            def grid_point(time_ms, pitch):
                return QPoint(
                    round(editor.canvas.x_at_time(time_ms)),
                    round(editor.canvas.RULER_H + (editor.canvas.pitch_top - pitch) * editor.canvas.ROW_H + 8),
                )

            # Selection mode uses an empty click only for cursor placement.
            blank = grid_point(1500.0, 70)
            before = list(editor.canvas.notes)
            QTest.mouseClick(editor.canvas, Qt.LeftButton, pos=blank)
            assert editor.canvas.notes == before
            assert not editor.canvas.selected
            assert abs(editor.canvas.edit_cursor_ms - 1500.0) < 0.01

            # Double-click creation is a single undoable edit.
            QTest.mouseDClick(editor.canvas, Qt.LeftButton, pos=blank)
            assert len(editor.canvas.notes) == len(before) + 1
            assert editor.canvas.notes[-1].start == 1500.0
            editor.undo()
            assert editor.canvas.notes == before

            # Paste targets the visible edit cursor instead of a viewport offset.
            editor.canvas.selected = {0}
            editor.copy_selected()
            paste_at = grid_point(2000.0, 70)
            QTest.mouseClick(editor.canvas, Qt.LeftButton, pos=paste_at)
            editor.paste_notes()
            assert editor.canvas.notes[-1].start == 2000.0
            assert editor.canvas.notes[-1].vel == before[0].vel
            editor.undo()
            assert editor.canvas.notes == before

            # Ctrl-drag clones the grabbed note and preserves the source note.
            source = editor.canvas.note_rect(editor.canvas.notes[0]).center()
            target = QPointF(source.x() + editor.canvas.px_per_beat, source.y() - editor.canvas.ROW_H)
            for event in (
                QMouseEvent(
                    QEvent.MouseButtonPress, source, source,
                    Qt.LeftButton, Qt.LeftButton, Qt.ControlModifier,
                ),
                QMouseEvent(
                    QEvent.MouseMove, target, target,
                    Qt.NoButton, Qt.LeftButton, Qt.ControlModifier,
                ),
                QMouseEvent(
                    QEvent.MouseButtonRelease, target, target,
                    Qt.LeftButton, Qt.NoButton, Qt.ControlModifier,
                ),
            ):
                QApplication.sendEvent(editor.canvas, event)
            assert len(editor.canvas.notes) == len(before) + 1
            clone = editor.canvas.notes[-1]
            assert clone.start == before[0].start + editor.canvas.beat_ms
            assert clone.pitch == before[0].pitch + 1
            assert clone.vel == before[0].vel
            assert clone.dur == before[0].dur
            editor.undo()
            assert editor.canvas.notes == before

            # A Ctrl-click remains selection toggling and never creates a clone.
            editor.canvas.selected = {0}
            source_point = QPoint(round(source.x()), round(source.y()))
            QTest.mouseClick(
                editor.canvas, Qt.LeftButton, Qt.ControlModifier, pos=source_point,
            )
            assert len(editor.canvas.notes) == len(before)
            assert 0 not in editor.canvas.selected

            # A long note that begins before the horizontal viewport must be
            # clipped at the grid edge instead of painting through piano keys.
            editor.canvas.notes = [Note(60, 91, 0.0, 3000.0, 0)]
            editor.canvas.rebuild_note_index()
            editor.canvas.pitch_top = 72
            editor.set_time_scroll(1000)
            editor.canvas.update()
            app.processEvents()
            note_y = round(editor.canvas.note_rect(editor.canvas.notes[0]).center().y())
            with_note = editor.canvas.grab().toImage()
            editor.canvas.notes = []
            editor.canvas.rebuild_note_index()
            editor.canvas.update()
            app.processEvents()
            without_note = editor.canvas.grab().toImage()
            assert with_note.pixelColor(editor.canvas.KEY_W - 5, note_y) == without_note.pixelColor(
                editor.canvas.KEY_W - 5, note_y
            )
            assert with_note.pixelColor(editor.canvas.KEY_W + 5, note_y) != without_note.pixelColor(
                editor.canvas.KEY_W + 5, note_y
            )
            assert editor.canvas.note_at(QPointF(editor.canvas.KEY_W - 5, note_y))[0] is None

            editor.close()

            # The empty-score invitation is custom-painted and must remain safe
            # when there are no note rectangles or visible-note indexes.
            empty_track = TrackState(2, [], 0, False, "empty", 0x0B)
            window.tracks = [empty_track]
            empty_editor = MidiNoteEditorDialog(window, empty_track, 120, 4)
            empty_editor.resize(1000, 700)
            empty_editor.show()
            app.processEvents()
            assert not empty_editor.canvas.grab().isNull()
            assert empty_editor.track_meta.text().startswith("♫ 0")
            empty_editor.close()
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
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
