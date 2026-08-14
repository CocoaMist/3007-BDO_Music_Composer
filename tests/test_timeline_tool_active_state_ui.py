from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineToolActiveStateUiTests(unittest.TestCase):
    def test_optional_clip_edit_and_razor_render_active_state(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QEvent, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window.resize(1160, 720)
            window._show_workspace()
            window.show()
            app.processEvents()

            marquee = window.timeline_marquee_tool
            select = window.timeline_select_tool
            razor = window.timeline_razor_tool
            active_color = "#61471d"

            def presentation(button):
                image = button.grab().toImage()
                return image.pixelColor(4, button.height() // 2).name()

            assert marquee.objectName() == "TimelineToolButton"
            assert select.objectName() == "TimelineToolButton"
            assert razor.objectName() == "TimelineToolButton"
            assert not marquee.isChecked()
            assert select.isChecked()
            assert not razor.isChecked()
            assert window.timeline.arrangement_tool == "select"
            assert presentation(marquee) != active_color
            assert presentation(select) == active_color
            assert presentation(razor) != active_color

            QTest.mouseClick(marquee, Qt.LeftButton)
            app.processEvents()
            assert marquee.isChecked()
            assert not select.isChecked()
            assert not razor.isChecked()
            assert window.timeline.arrangement_tool == "marquee"
            assert presentation(marquee) == active_color

            QTest.mouseClick(marquee, Qt.LeftButton)
            app.processEvents()
            assert not select.isChecked()
            assert not razor.isChecked()
            assert marquee.isChecked()
            assert window.timeline.arrangement_tool == "marquee"

            QTest.mouseClick(razor, Qt.LeftButton)
            app.processEvents()
            assert not select.isChecked()
            assert not marquee.isChecked()
            assert razor.isChecked()
            assert window.timeline.arrangement_tool == "razor"
            assert presentation(razor) == active_color, presentation(razor)

            QTest.mouseClick(select, Qt.LeftButton)
            app.processEvents()
            assert select.isChecked()
            assert not marquee.isChecked()
            assert not razor.isChecked()
            assert window.timeline.arrangement_tool == "select"

            QTest.mouseClick(select, Qt.LeftButton)
            app.processEvents()
            assert select.isChecked()
            assert not razor.isChecked()
            assert not marquee.isChecked()
            assert window.timeline.arrangement_tool == "select"

            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            app.quit()
            """
        )
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
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
