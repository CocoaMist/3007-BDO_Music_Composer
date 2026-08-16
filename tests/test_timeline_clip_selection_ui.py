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
            from bdo_music_composer.editor.editor_models import (
                ArrangementClipState,
                TrackState,
            )
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
            deleted = []
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
            canvas.clip_delete_requested.connect(
                lambda item, clip_id: deleted.append((item, clip_id))
            )

            menu, actions = canvas._build_clip_context_menu()
            assert [
                action.text() for action in menu.actions()
                if not action.isSeparator()
            ] == [
                "打开音符编辑器", "复制音块", "重复音块…",
                "在播放头切分", "复制片段", "在播放头粘贴片段",
                "Clip 力度基数…",
                "收紧右边界到最后音符", "合并所选音块",
                "重命名音块…", "音块颜色…", "删除片段",
            ]
            assert set(actions) == {
                "open", "duplicate", "repeat", "split", "copy", "paste",
                "velocity_base", "crop", "consolidate", "rename", "color",
                "delete",
            }

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

            QTest.keyClick(canvas, Qt.Key_Delete)
            app.processEvents()
            assert deleted == [(track, "track-1-main")]

            QTest.mouseDClick(canvas, Qt.LeftButton, pos=point)
            app.processEvents()
            assert not opened
            assert opened_clips == [(track, "track-1-main")]
            assert not committed

            # Selection is a per-Clip visual state, not merely a selected
            # track state.  Only the chosen Clip gets the bright outline and
            # clicking empty lane space clears that selection.
            track.notes = [
                Note(60, 90, 100.0, 100.0, 0),
                Note(64, 90, 700.0, 100.0, 0),
            ]
            track.arrangement_clips = [
                ArrangementClipState(
                    "first", 0.0, 400.0, 0.0, 400.0
                ),
                ArrangementClipState(
                    "second", 600.0, 1000.0, 600.0, 1000.0
                ),
            ]
            canvas.set_tracks([track])
            canvas.repaint()
            app.processEvents()
            clip_regions = {
                action.split("|", 1)[1]: rect
                for rect, action, item in canvas.hit_regions
                if item is track and action.startswith("clip_body|")
            }
            first_point = QPoint(
                int(clip_regions["first"].center().x()),
                int(clip_regions["first"].center().y()),
            )
            QTest.mouseClick(canvas, Qt.LeftButton, pos=first_point)
            app.processEvents()
            assert canvas._selected_clip_id == "first", (
                canvas._selected_clip_id, canvas._selected_clip_track_id
            )
            assert canvas._selected_clip_track_id == int(track.track_id)
            assert canvas.arrangement_tool == "select", canvas.arrangement_tool
            canvas.repaint()
            app.processEvents()
            painted_regions = {
                action.split("|", 1)[1]: rect
                for rect, action, item in canvas.hit_regions
                if item is track and action.startswith("clip_body|")
            }
            image = canvas.grab().toImage()
            def painted_colors(rect):
                return {
                    image.pixelColor(x, y).name()
                    for x in range(int(rect.left()), int(rect.right()) + 1)
                    for y in range(int(rect.top()), int(rect.bottom()) + 1)
                }

            selected_colors = painted_colors(painted_regions["first"])
            sibling_colors = painted_colors(painted_regions["second"])
            assert "#ffd766" in selected_colors, selected_colors
            assert "#ffd766" not in sibling_colors, sibling_colors
            assert canvas._selected_clip_id == "first"

            lane = next(
                rect for rect, action, item in canvas.hit_regions
                if item is track and action == "lane"
            )
            blank_point = QPoint(
                int(lane.right() - 8), int(lane.center().y())
            )
            assert not any(
                rect.contains(blank_point) for rect in clip_regions.values()
            )
            QTest.mouseClick(canvas, Qt.LeftButton, pos=blank_point)
            app.processEvents()
            assert canvas._selected_clip_id == ""
            assert canvas._selected_clip_track_id is None

            QTest.mouseClick(canvas, Qt.LeftButton, pos=first_point)
            app.processEvents()
            assert canvas._selected_clip_id == "first"
            track.arrangement_clips = [track.arrangement_clips[1]]
            track.notes = [track.notes[1]]
            canvas.set_tracks([track])
            app.processEvents()
            assert canvas._selected_clip_id == ""
            assert canvas._selected_clip_track_id is None

            # Clip region resizing exposes only the right handle. The left edge
            # is the fixed anchor even when the Clip is empty.
            track.notes = []
            track.arrangement_clips = [
                ArrangementClipState(
                    "empty", 0.0, 3000.0, 0.0, 3000.0
                )
            ]
            canvas.set_tracks([track])
            canvas.set_arrangement_tool("select")
            canvas.repaint()
            app.processEvents()
            assert not any(
                action == "clip_start|empty"
                for _rect, action, item in canvas.hit_regions
                if item is track
            )
            end_handle = next(
                rect for rect, action, item in canvas.hit_regions
                if item is track and action == "clip_end|empty"
            )
            end_point = QPoint(
                int(end_handle.center().x()),
                int(end_handle.center().y()),
            )
            committed.clear()
            assert canvas._clip_action_at(end_point)[2] == "clip_body"
            QTest.mouseClick(canvas, Qt.LeftButton, pos=end_point)
            app.processEvents()
            assert canvas._selected_clip_id == "empty"
            assert not committed
            assert canvas.cursor().shape() == Qt.SizeHorCursor
            canvas.repaint()
            app.processEvents()
            end_handle = next(
                rect for rect, action, item in canvas.hit_regions
                if item is track and action == "clip_end|empty"
            )
            end_point = QPoint(
                int(end_handle.center().x()),
                int(end_handle.center().y()),
            )
            QTest.mouseMove(canvas, pos=end_point)
            app.processEvents()
            assert canvas.cursor().shape() == Qt.SizeHorCursor
            trimmed_point = QPoint(end_point.x() - 45, end_point.y())
            QTest.mousePress(canvas, Qt.LeftButton, pos=end_point)
            assert canvas._clip_drag_mode == "resize_end"
            assert canvas._clip_group_drag_keys == ()
            QTest.mouseMove(canvas, pos=trimmed_point)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=trimmed_point)
            app.processEvents()
            assert len(committed) == 1
            assert committed[0].mode == "resize_end"
            assert 10.0 <= committed[0].new_end_ms < 3000.0
            assert committed[0].clip_id == "empty"
            assert canvas.cursor().shape() == Qt.SizeHorCursor
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
