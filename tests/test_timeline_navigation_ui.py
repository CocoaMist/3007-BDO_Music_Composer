from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineNavigationUiTests(unittest.TestCase):
    def test_focus_navigation_layout_density_and_group_folding(self) -> None:
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        script = textwrap.dedent(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

            app = QApplication([])
            first = TrackState(
                1, [Note(60, 90, 100.0, 200.0, 0)], 0, False,
                "First", 0x12, arrangement_group_id="strings",
            )
            second = TrackState(
                2, [Note(64, 90, 500.0, 100.0, 0)], 0, False,
                "Second", 0x12, arrangement_group_id="strings",
            )
            third = TrackState(
                3, [Note(67, 90, 900.0, 100.0, 0)], 0, False,
                "Third", 0x13,
            )
            canvas = TimelineCanvas()
            canvas.resize(1100, 520)
            canvas.set_tracks([first, second, third])
            canvas.set_timeline_markers([{"time_ms": 450.0, "label": "A"}])
            canvas.set_selected_track(first)
            canvas.show()
            canvas.setFocus()
            app.processEvents()

            volume_commits = []
            moves = []
            clip_opens = []
            track_opens = []
            canvas.game_volume_committed.connect(
                lambda *values: volume_commits.append(values)
            )
            canvas.clips_move_requested.connect(moves.append)
            canvas.clip_note_editor_requested.connect(
                lambda *values: clip_opens.append(values)
            )
            canvas.note_editor_requested.connect(track_opens.append)

            canvas.set_playhead(250.0)
            QTest.keyClick(canvas, Qt.Key_Right)
            assert canvas.playhead_ms == 375.0
            assert first.bdo_track_volume == 70
            QTest.keyClick(canvas, Qt.Key_Right, Qt.AltModifier)
            assert first.bdo_track_volume == 71
            assert len(volume_commits) == 1

            canvas.set_selected_clip(first, "track-1-main")
            QTest.keyClick(canvas, Qt.Key_Left)
            assert len(moves) == 1
            assert moves[0].delta_ms == -125.0
            QTest.keyClick(canvas, Qt.Key_Return)
            assert clip_opens == [(first, "track-1-main")]

            QTest.keyClick(canvas, Qt.Key_Down)
            assert canvas.selected_track is second
            assert not canvas.selected_clip_keys
            QTest.keyClick(canvas, Qt.Key_Return)
            assert track_opens == [second]

            canvas.set_playhead(250.0)
            QTest.keyClick(canvas, Qt.Key_Right, Qt.ControlModifier)
            assert canvas.playhead_ms == 300.0
            canvas.set_selected_clip(first, "track-1-main")
            old_view = (canvas.zoom_factor, canvas.view_start_ms)
            QTest.keyClick(canvas, Qt.Key_Z)
            assert canvas.zoom_factor > old_view[0]
            QTest.keyClick(canvas, Qt.Key_X)
            assert (canvas.zoom_factor, canvas.view_start_ms) == old_view

            canvas.set_layout_metrics(
                header_width=999, lane_height=1,
                reference_lane_height=999,
            )
            assert (canvas.header_width, canvas.lane_height) == (420, 44)
            assert canvas.reference_lane_height == 180

            assert len(canvas._visible_track_rows()) == 3
            canvas._set_group_collapsed("strings", True)
            assert [track.track_id for _row, track in canvas._visible_track_rows()] == [1, 3]
            canvas.repaint(); app.processEvents()
            actions = [action for _rect, action, _item in canvas.hit_regions]
            assert actions.count("group_summary") == 1, actions
            group = canvas._arrangement_groups["strings"]
            assert (group.note_count, group.clip_count) == (2, 2)
            assert actions.count("group_mute") == 1
            assert actions.count("group_solo") == 1

            width_requests = []
            canvas.fit_width_requested.connect(lambda: width_requests.append(True))
            QTest.keyClick(canvas, Qt.Key_W)
            assert width_requests == [True]
            QTest.keyClick(canvas, Qt.Key_U)
            assert len(canvas._visible_track_rows()) == 3
            QTest.keyClick(canvas, Qt.Key_H)
            assert canvas.lane_height == 104
            canvas.reset_layout_metrics()
            assert (
                canvas.header_width,
                canvas.lane_height,
                canvas.reference_lane_height,
            ) == (276, 68, 68)
            canvas.set_all_groups_collapsed(True)
            assert [track.track_id for _row, track in canvas._visible_track_rows()] == [1, 3]
            canvas.set_all_groups_collapsed(False)
            assert len(canvas._visible_track_rows()) == 3
            canvas.close()
            app.processEvents()
            print("timeline-navigation-ui-ok")
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        self.assertIn("timeline-navigation-ui-ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
