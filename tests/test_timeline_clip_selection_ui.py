from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineClipSelectionUiTests(unittest.TestCase):
    def test_single_click_selects_clip_without_opening_editor_or_committing(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

            app = QApplication([])
            track = TrackState(
                1, [Note(60, 90, 100.0, 200.0, 0)],
                0, False, "Track", 0x12,
            )
            canvas = TimelineCanvas()
            canvas.resize(1000, 360)
            canvas.set_tracks([track])
            canvas.show()
            app.processEvents()
            canvas.repaint()
            app.processEvents()

            body = next(
                rect for rect, action, item in canvas.hit_regions
                if item is track and action.startswith("clip_body|")
            )
            point = QPoint(int(body.center().x()), int(body.center().y()))
            opened = []
            opened_clips = []
            committed = []
            copied = []
            pasted = []
            canvas.note_editor_requested.connect(opened.append)
            canvas.clip_note_editor_requested.connect(
                lambda item, clip_id: opened_clips.append((item, clip_id))
            )
            canvas.clip_edit_requested.connect(committed.append)
            canvas.clip_copy_requested.connect(
                lambda item, clip_id: copied.append((item, clip_id))
            )
            canvas.clip_paste_requested.connect(
                lambda item, time_ms: pasted.append((item, time_ms))
            )

            QTest.mouseClick(canvas, Qt.LeftButton, pos=point)
            app.processEvents()
            assert canvas._selected_clip_id == "track-1-main"
            assert not opened
            assert not committed

            QTest.keyClick(canvas, Qt.Key_C, Qt.ControlModifier)
            QTest.keyClick(canvas, Qt.Key_V, Qt.ControlModifier)
            app.processEvents()
            assert copied == [(track, "track-1-main")]
            assert pasted == [(track, canvas.playhead_ms)]
            assert not opened

            QTest.mouseDClick(canvas, Qt.LeftButton, pos=point)
            app.processEvents()
            assert not opened
            assert opened_clips == [(track, "track-1-main")]
            assert not committed
            canvas.close()
            app.processEvents()
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
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
