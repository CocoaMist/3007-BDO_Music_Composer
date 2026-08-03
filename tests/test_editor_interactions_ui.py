from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EditorInteractionUiTests(unittest.TestCase):
    def test_selection_transport_and_distant_candidate_blocks(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window.show_toast = lambda *_args, **_kwargs: None
            track = TrackState(
                1,
                [
                    Note(60, 96, 0.0, 300.0, 0),
                    Note(64, 88, 500.0, 250.0, 0),
                ],
                0,
                False,
                "lead",
                0x0B,
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(1000, 720)
            editor.show()
            app.processEvents()

            # Note-editing shortcuts follow canvas focus, leaving text fields
            # with their native editing keys.
            editor.pitch_edit.setFocus()
            editor.canvas.selected = {0}
            QTest.keyClick(
                editor.pitch_edit,
                Qt.Key_A,
                Qt.ControlModifier,
            )
            app.processEvents()
            assert editor.canvas.selected == {0}
            editor.canvas.setFocus()
            QTest.keyClick(
                editor.canvas,
                Qt.Key_A,
                Qt.ControlModifier,
            )
            app.processEvents()
            assert editor.canvas.selected == {0, 1}

            # Space follows the same focus rule and remains one play/pause
            # toggle per physical key press.
            toggles = []
            editor.toggle_draft_playback = lambda: toggles.append("toggle")
            editor.pitch_edit.setFocus()
            QTest.keyClick(editor.pitch_edit, Qt.Key_Space)
            app.processEvents()
            assert toggles == []
            editor.canvas.setFocus()
            QTest.keyClick(editor.canvas, Qt.Key_Space)
            app.processEvents()
            assert toggles == ["toggle"]

            # Clicking inside the note grid positions the shared playhead,
            # rather than moving only the edit cursor.
            editor.canvas.scroll_ms = 0.0
            target_ms = 1250.0
            x = round(editor.canvas.x_at_time(target_ms))
            y = round(editor.canvas.RULER_H + editor.canvas.ROW_H * 2.5)
            QTest.mouseClick(
                editor.canvas,
                Qt.LeftButton,
                Qt.NoModifier,
                QPoint(x, y),
            )
            app.processEvents()
            assert abs(editor.playhead_ms - target_ms) < 20.0

            # At the minimum horizontal zoom, candidates still paint as
            # compact blocks even when voice grouping is not available.
            candidate = TranscriptionCandidate(
                editor.canvas.pitch_top,
                90,
                1000.0,
                300.0,
                0.9,
                candidate_id="distant-note",
            )
            editor.canvas.set_transcription_candidates([candidate])
            editor.canvas.px_per_beat = 30.0
            editor.canvas.update()
            app.processEvents()
            rect = editor.canvas.candidate_rect(candidate)
            image = editor.canvas.grab().toImage()
            inside = image.pixelColor(
                round(rect.center().x()),
                round(rect.center().y()),
            )
            outside = image.pixelColor(
                round(rect.right() + 8),
                round(rect.center().y()),
            )
            assert inside.rgba() != outside.rgba()

            editor.close()
            window.close()
            """
        )
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
