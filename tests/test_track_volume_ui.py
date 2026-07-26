from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrackVolumeUiTests(unittest.TestCase):
    def test_painted_game_volume_control_is_bounded_and_preserves_raw_imports(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QSlider

            from pyside_bdo_gui import Note, TimelineCanvas, TrackState

            app = QApplication([])
            canvas = TimelineCanvas()
            canvas.resize(820, 400)
            # Raw score bytes above the game's authoring limit remain intact
            # until the user deliberately edits the row control.
            track = TrackState(
                3,
                [Note(60, 90, 0.0, 500.0, 0)],
                0,
                False,
                "lead",
                0x0B,
                bdo_track_volume=118,
            )
            canvas.set_tracks([track])
            canvas.show()
            app.processEvents()
            assert track.bdo_track_volume == 118
            assert canvas.findChildren(QSlider) == []
            volume_regions = [
                rect for rect, action, item in canvas.hit_regions
                if action == "track_volume" and item is track
            ]
            assert len(volume_regions) == 1
            rect = volume_regions[0]
            changes = []
            canvas.track_state_changed.connect(lambda: changes.append(track.bdo_track_volume))
            target = QPoint(
                round(rect.left() + rect.width() * 0.75),
                round(rect.center().y()),
            )
            QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, target)
            QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, target)
            app.processEvents()
            assert 74 <= track.bdo_track_volume <= 76
            assert changes == [track.bdo_track_volume]
            assert canvas._track_volume_from_position(rect, rect.left() - 50) == 0
            assert canvas._track_volume_from_position(rect, rect.right() + 50) == 100
            assert TrackState(4, [], 0, False, "default", 0x0B).bdo_track_volume == 70
            canvas.close()
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

    def test_output_controls_live_in_settings_not_bottom_bar(self) -> None:
        script = textwrap.dedent(
            """
            import tempfile
            from pathlib import Path

            from PySide6.QtWidgets import QApplication, QFrame, QWidget

            from pyside_bdo_gui import (
                MidiToBdoWindow, Note, SettingsDialog, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window._show_workspace()
            window.show()
            app.processEvents()
            assert window.findChild(QFrame, "Inspector") is None
            assert window.findChild(QFrame, "PerformanceStrip") is not None
            assert window.workspace_page.layout().count() == 2
            assert not hasattr(window, "selected_volume")
            assert not hasattr(window, "open_output_button")
            settings = SettingsDialog(window)
            assert settings.output_dir.objectName() == "OutputDirectoryEdit"
            assert settings.findChild(QWidget, "BrowseOutputDirectoryButton") is not None
            assert settings.findChild(QWidget, "OpenOutputDirectoryButton") is not None
            settings.close()
            with tempfile.TemporaryDirectory() as temp:
                window.output_dir_path = temp
                window.output_name.setText("volume-ui-test")
                window.source_format = "project"
                window.owner_id = 1
                window.tracks = [
                    TrackState(
                        0,
                        [Note(60, 90, 0.0, 200.0, 0)],
                        0,
                        False,
                        "lead",
                        0x0B,
                    )
                ]
                params = window._build_params()
                assert Path(params["out_path"]).parent == Path(temp)
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
