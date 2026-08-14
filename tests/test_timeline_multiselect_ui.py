from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineMultiselectUiTests(unittest.TestCase):
    def test_modifier_and_marquee_select_clips_across_tracks(self) -> None:
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
            from bdo_music_composer.ui.editor.timeline_canvas import (
                TimelineCanvas,
            )

            app = QApplication([])
            first = TrackState(
                1,
                [Note(60, 90, 800.0, 600.0, 0)],
                0,
                False,
                "First",
                0x12,
                arrangement_clips=[
                    ArrangementClipState(
                        "one", 800.0, 1400.0, 800.0, 1400.0
                    )
                ],
            )
            second = TrackState(
                2,
                [Note(64, 90, 1600.0, 600.0, 0)],
                0,
                False,
                "Second",
                0x12,
                arrangement_clips=[
                    ArrangementClipState(
                        "two", 1600.0, 2200.0, 1600.0, 2200.0
                    )
                ],
            )
            third = TrackState(
                3, [], 0, False, "Third", 0x12,
                arrangement_clips=[],
            )
            canvas = TimelineCanvas()
            canvas.resize(1000, 360)
            canvas.set_tracks([first, second, third])
            canvas.show()
            app.processEvents()
            canvas.repaint()
            app.processEvents()
            assert canvas.arrangement_tool == "select"

            def clip_regions():
                return {
                    (int(item.track_id), action.split("|", 1)[1]): rect
                    for rect, action, item in canvas.hit_regions
                    if action.startswith("clip_body|")
                }

            regions = clip_regions()
            one = regions[(1, "one")]
            two = regions[(2, "two")]
            one_point = QPoint(
                int(one.center().x()), int(one.center().y())
            )
            two_point = QPoint(
                int(two.center().x()), int(two.center().y())
            )

            QTest.mouseClick(canvas, Qt.LeftButton, pos=one_point)
            QTest.mouseClick(
                canvas,
                Qt.LeftButton,
                Qt.ControlModifier,
                two_point,
            )
            app.processEvents()
            assert canvas.selected_clip_keys == frozenset({
                (1, "one"), (2, "two")
            })
            assert canvas._selected_clip_id == "two"
            assert canvas.selected_track is second

            QTest.mouseClick(
                canvas,
                Qt.LeftButton,
                Qt.ControlModifier,
                one_point,
            )
            assert canvas.selected_clip_keys == frozenset({(2, "two")})

            edits = []
            canvas.clip_edit_requested.connect(edits.append)
            canvas.set_arrangement_tool("select")
            drag_target = QPoint(one_point.x() + 36, one_point.y())
            QTest.mousePress(canvas, Qt.LeftButton, pos=one_point)
            QTest.mouseMove(canvas, pos=drag_target)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=drag_target)
            app.processEvents()
            assert len(edits) == 1
            assert edits[0].mode == "move"
            assert edits[0].clip_id == "one"
            assert canvas._marquee_press_pos is None
            canvas.set_arrangement_tool("marquee")
            canvas.set_selected_clip(None)

            lanes = {
                int(item.track_id): rect
                for rect, action, item in canvas.hit_regions
                if action == "lane"
            }
            # Default marquee mode can start directly over a Clip without
            # accidentally moving it.
            start = QPoint(int(one.left() + 4), int(one.top() + 4))
            end = QPoint(
                int(max(one.right(), two.right()) + 4),
                int(lanes[2].bottom() - 4),
            )
            assert one.contains(start)
            QTest.mousePress(canvas, Qt.LeftButton, pos=start)
            QTest.mouseMove(canvas, pos=end)
            app.processEvents()
            assert canvas._marquee_active
            assert canvas._marquee_preview_clip_keys == {
                (1, "one"), (2, "two")
            }
            marquee_image = canvas.grab().toImage()
            assert marquee_image.pixelColor(
                int(start.x() + 1), int(start.y() + 1)
            ).alpha() > 0
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=end)
            app.processEvents()
            assert canvas._marquee_press_pos is None
            assert canvas.selected_clip_keys == frozenset({
                (1, "one"), (2, "two")
            })

            # A selected Clip edge is a single-Clip resize handle, never the
            # overlapping body hit used for moving the whole selection.
            canvas.set_arrangement_tool("select")
            canvas.repaint()
            app.processEvents()
            one_end = next(
                rect for rect, action, item in canvas.hit_regions
                if item is first and action == "clip_end|one"
            )
            edge_point = QPoint(
                int(one_end.center().x()), int(one_end.center().y())
            )
            edit_count = len(edits)
            QTest.mousePress(canvas, Qt.LeftButton, pos=edge_point)
            assert canvas._clip_drag_mode == "resize_end"
            assert canvas._clip_group_drag_keys == ()
            edge_target = QPoint(edge_point.x() + 18, edge_point.y())
            QTest.mouseMove(canvas, pos=edge_target)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=edge_target)
            app.processEvents()
            assert len(edits) == edit_count + 1
            assert edits[-1].mode == "resize_end"
            canvas.set_selected_clip_keys({(1, "one"), (2, "two")})

            group_moves = []
            canvas.clips_move_requested.connect(group_moves.append)
            canvas.set_arrangement_tool("select")
            group_target = QPoint(one_point.x() + 42, one_point.y())
            QTest.mousePress(canvas, Qt.LeftButton, pos=one_point)
            QTest.mouseMove(canvas, pos=group_target)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=group_target)
            app.processEvents()
            assert len(group_moves) == 1
            assert tuple(
                (int(track.track_id), clip_id)
                for track, clip_id in group_moves[0].selections
            ) == ((1, "one"), (2, "two"))
            assert group_moves[0].delta_ms > 0.0
            assert group_moves[0].track_offset == 0
            assert group_moves[0].primary_key == (1, "one")
            assert canvas._marquee_press_pos is None
            assert canvas.selected_clip_keys == frozenset({
                (1, "one"), (2, "two")
            })

            lanes = {
                int(item.track_id): rect
                for rect, action, item in canvas.hit_regions
                if action == "lane"
            }
            vertical_target = QPoint(
                one_point.x() + 22,
                int(lanes[2].center().y()),
            )
            QTest.mousePress(canvas, Qt.LeftButton, pos=one_point)
            QTest.mouseMove(canvas, pos=vertical_target)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=vertical_target)
            app.processEvents()
            assert len(group_moves) == 2
            assert group_moves[1].track_offset == 1
            assert group_moves[1].primary_key == (1, "one")

            seeks = []
            canvas.seek_requested.connect(seeks.append)
            blank = QPoint(
                int(canvas.grid_rect.right() - 12),
                int(lanes[3].center().y()),
            )
            QTest.mousePress(canvas, Qt.LeftButton, pos=blank)
            QTest.mouseMove(canvas, pos=QPoint(blank.x() - 30, blank.y()))
            QTest.mouseRelease(
                canvas, Qt.LeftButton,
                pos=QPoint(blank.x() - 30, blank.y()),
            )
            app.processEvents()
            assert canvas._marquee_press_pos is None
            assert canvas.selected_clip_keys == frozenset()
            assert len(seeks) == 1
            canvas.set_selected_clip_keys({(1, "one"), (2, "two")})

            # Marquee mode never steals a selected Clip drag for movement.
            canvas.set_arrangement_tool("marquee")
            move_count = len(group_moves)
            QTest.mousePress(canvas, Qt.LeftButton, pos=one_point)
            QTest.mouseMove(canvas, pos=group_target)
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=group_target)
            app.processEvents()
            assert len(group_moves) == move_count
            canvas.set_selected_clip_keys({(1, "one"), (2, "two")})

            canvas.repaint()
            app.processEvents()
            image = canvas.grab().toImage()
            for rect in clip_regions().values():
                colors = {
                    image.pixelColor(x, y).name()
                    for x in range(int(rect.left()), int(rect.right()) + 1)
                    for y in range(int(rect.top()), int(rect.bottom()) + 1)
                }
                assert "#ffd766" in colors, colors

            deleted = []
            canvas.clips_delete_requested.connect(deleted.append)
            QTest.keyClick(canvas, Qt.Key_Delete)
            app.processEvents()
            assert len(deleted) == 1
            assert tuple(
                (int(track.track_id), clip_id)
                for track, clip_id in deleted[0]
            ) == ((1, "one"), (2, "two"))

            # A concurrent model refresh may remove only the primary Clip.
            # Reconciliation must retain every other still-valid selection.
            second.arrangement_clips.clear()
            canvas.set_tracks([first, second, third])
            app.processEvents()
            assert canvas.selected_clip_keys == frozenset({(1, "one")})
            assert canvas._selected_clip_track_id == 1
            assert canvas._selected_clip_id == "one"

            canvas.close()
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
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
