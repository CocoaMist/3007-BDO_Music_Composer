from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineVelocityCurveUiTests(unittest.TestCase):
    def test_inline_curve_is_not_exposed_but_backend_remains_transactional(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPointF, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

            app = QApplication([])
            track = TrackState(
                1,
                [
                    Note(60, 60, 0.0, 400.0, 0),
                    Note(64, 80, 1000.0, 400.0, 0),
                    Note(67, 100, 2000.0, 400.0, 0),
                ],
                0,
                False,
                "lead",
                0x0B,
            )
            canvas = TimelineCanvas()
            canvas.resize(1000, 420)
            canvas.set_tracks([track])
            canvas.set_selected_track(track)
            canvas.show()
            app.processEvents()
            overlay = canvas.velocity_curve_overlay
            assert overlay.velocity_trace_points(track, 0.0, 2000.0) == (
                (0.0, 60.0),
                (1000.0, 80.0),
                (2000.0, 100.0),
            )
            track.notes[1] = track.notes[1]._replace(vel=35)
            canvas.set_tracks([track])
            assert overlay.velocity_trace_points(track, 0.0, 2000.0)[1] == (
                1000.0,
                35.0,
            )
            track.notes[1] = track.notes[1]._replace(vel=80)
            canvas.set_tracks([track])
            canvas.set_selected_track(track)
            canvas.repaint()
            app.processEvents()
            assert not any(
                action == "activate"
                for _rect, action in overlay._hit_regions
            )
            assert not overlay.active
            # Keep the dormant transaction backend covered without exposing
            # the rejected multitrack control in the workspace.
            overlay._activate()
            app.processEvents()
            assert overlay.active
            assert [point.velocity for point in overlay.points] == [60.0, 80.0, 100.0]
            original = list(track.notes)
            committed = []
            canvas.velocity_curve_committed.connect(
                lambda target, notes: committed.append((target, list(notes)))
            )
            geometry = overlay._geometry
            assert geometry is not None
            created_at = QPointF(
                geometry.left() + geometry.width() * 0.25,
                geometry.center().y() - 8.0,
            )
            assert overlay.mouse_press(created_at, Qt.LeftButton)
            assert overlay.mouse_release(Qt.LeftButton)
            assert len(overlay.points) == 4
            canvas.repaint()
            app.processEvents()
            middle_point = next(
                rect for rect, action in overlay._hit_regions
                if action == "point:2"
            )
            assert overlay.mouse_press(middle_point.center(), Qt.LeftButton)
            assert overlay.mouse_move(middle_point.center() - QPointF(0.0, 12.0))
            assert overlay.mouse_release(Qt.LeftButton)
            canvas.repaint()
            app.processEvents()
            left_weight = next(
                rect for rect, action in overlay._hit_regions
                if action == "weight:2:left"
            )
            previous_left_weight = overlay.points[2].left_weight
            assert overlay.mouse_press(left_weight.center(), Qt.LeftButton)
            assert overlay.mouse_move(left_weight.center() - QPointF(12.0, 0.0))
            assert overlay.mouse_release(Qt.LeftButton)
            assert overlay.points[2].left_weight > previous_left_weight
            assert overlay.points[2].right_weight == 1.0 / 3.0
            canvas.repaint()
            app.processEvents()
            extra_at = QPointF(
                geometry.left() + geometry.width() * 0.75,
                geometry.center().y(),
            )
            assert overlay.mouse_press(extra_at, Qt.LeftButton)
            assert overlay.mouse_release(Qt.LeftButton)
            canvas.repaint()
            app.processEvents()
            removable = next(
                rect for rect, action in overlay._hit_regions
                if action == "point:3"
            )
            assert overlay.mouse_press(removable.center(), Qt.RightButton)
            assert len(overlay.points) == 4
            assert track.notes == original
            assert committed == []
            canvas.repaint()
            app.processEvents()
            apply_rect = next(
                rect for rect, action in overlay._hit_regions
                if action == "apply"
            )
            QTest.mouseClick(
                canvas,
                Qt.LeftButton,
                Qt.NoModifier,
                apply_rect.center().toPoint(),
            )
            app.processEvents()
            assert len(committed) == 1
            assert committed[0][0] is track
            assert [note.vel for note in track.notes] == [60, 80, 100]
            assert committed[0][1][1].vel > 80
            assert committed[0][1][-1].vel == 100
            assert committed[0][1][0].vel == 60
            canvas.close()
            app.quit()
            """
        )
        self._run_offscreen(script)

    def test_curve_commit_is_undoable_and_immediately_autosaved(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.editor.velocity_curve import (
                VelocityEnvelopePoint,
                apply_velocity_level_envelope,
            )
            from bdo_music_composer.ui.main_window import (
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                7,
                [
                    Note(60, 50, 0.0, 250.0, 0),
                    Note(62, 80, 1000.0, 250.0, 0),
                ],
                0,
                False,
                "lead",
                0x0B,
            )
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            autosaves = []
            window._autosave_project = (
                lambda reason, immediate=False: autosaves.append(
                    (reason, immediate)
                )
            )
            next_notes = apply_velocity_level_envelope(
                track.notes,
                range(2),
                (
                    VelocityEnvelopePoint(0.0, 50.0),
                    VelocityEnvelopePoint(0.4, 90.0),
                    VelocityEnvelopePoint(1.0, 120.0),
                ),
            )
            window._commit_timeline_velocity_curve(track, next_notes)
            assert [note.vel for note in track.notes] == [50, 120]
            assert autosaves == [("velocity envelope", True)]
            window._undo_project()
            assert [note.vel for note in window.tracks[0].notes] == [50, 80]
            assert autosaves[-1] == ("project undo", True)
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self._run_offscreen(script)

    def _run_offscreen(self, script: str) -> None:
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
