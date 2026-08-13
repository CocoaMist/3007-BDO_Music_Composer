from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
from bdo_music_composer.ui.editor.timeline_velocity_curve_qt import TimelineVelocityCurveOverlay


ROOT = Path(__file__).resolve().parents[1]


class TimelineClipVelocityUiTests(unittest.TestCase):
    def test_move_and_both_trim_handles_snap_to_grid(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPointF, QRectF, Qt
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

            app = QApplication([])
            canvas = TimelineCanvas()
            canvas.grid_rect = QRectF(0.0, 0.0, 1000.0, 100.0)
            canvas._timeline_end_cache = 4000.0
            canvas.bpm = 120
            canvas._clip_drag_origin_press_ms = 0.0
            canvas._clip_drag_origin_start_ms = 0.0
            canvas._clip_drag_origin_end_ms = 1000.0

            canvas._clip_drag_mode = "move"
            canvas._update_clip_drag_geometry(QPointF(122.5, 20.0), Qt.NoModifier)
            assert canvas._clip_drag_start_ms == 500.0
            assert canvas._clip_drag_end_ms == 1500.0

            canvas._clip_drag_mode = "resize_start"
            canvas._clip_drag_origin_start_ms = 250.0
            canvas._clip_drag_origin_end_ms = 1000.0
            canvas._update_clip_drag_geometry(QPointF(60.0, 20.0), Qt.NoModifier)
            assert canvas._clip_drag_start_ms == 500.0
            assert canvas._clip_drag_end_ms == 1000.0

            canvas._clip_drag_mode = "resize_end"
            canvas._clip_drag_origin_start_ms = 0.0
            canvas._clip_drag_origin_end_ms = 1000.0
            canvas._update_clip_drag_geometry(QPointF(122.5, 20.0), Qt.NoModifier)
            assert canvas._clip_drag_start_ms == 0.0
            assert canvas._clip_drag_end_ms == 1500.0

            canvas.close()
            app.processEvents()
            """
        )
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=environment,
            text=True, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_velocity_trace_never_connects_across_clip_gap(self) -> None:
        track = TrackState(1, [
            Note(60, 40, 100.0, 50.0, 0),
            Note(62, 80, 700.0, 50.0, 0),
        ], 0, False, "Track", 0x12)
        track.arrangement_clips = [
            ArrangementClipState("a", 100.0, 200.0, 100.0, 200.0),
            ArrangementClipState("b", 700.0, 800.0, 700.0, 800.0),
        ]
        segments = TimelineVelocityCurveOverlay._clip_velocity_trace(
            track, ((100.0, 40.0), (700.0, 80.0))
        )
        self.assertEqual(segments, (((100.0, 40.0),), ((700.0, 80.0),)))

    def test_velocity_selection_uses_moved_clip_display_time(self) -> None:
        track = TrackState(1, [
            Note(60, 40, 100.0, 50.0, 0),
            Note(62, 80, 300.0, 50.0, 0),
        ], 0, False, "Track", 0x12)
        track.arrangement_clips = [
            ArrangementClipState("moved", 700.0, 950.0, 100.0, 350.0, 600.0)
        ]
        overlay = TimelineVelocityCurveOverlay(None)

        self.assertEqual(overlay._indices_between(track, 690.0, 760.0), (0,))
        self.assertEqual(
            overlay._projected_starts_between(track, 690.0, 920.0),
            ((0, 700.0), (1, 900.0)),
        )

    def test_dense_note_overview_is_clipped_to_each_clip_not_track_union(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QRectF
            from PySide6.QtWidgets import QApplication
            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas, _TimelineNoteOverviewBin

            app = QApplication([])
            track = TrackState(1, [Note(60, 80, 150.0, 600.0, 0)], 0, False, "Track", 0x12)
            track.arrangement_clips = [
                ArrangementClipState("a", 100.0, 200.0, 100.0, 200.0),
                ArrangementClipState("b", 700.0, 800.0, 700.0, 800.0),
            ]
            canvas = TimelineCanvas()
            canvas.set_tracks([track])
            canvas._visible_note_overview_bins = lambda *_args: (
                _TimelineNoteOverviewBin(150.0, 750.0, 60, 60, 1 << 60, 0),
            )
            normal, _markers, invalid = canvas._timeline_note_rect_batches(
                track, QRectF(0.0, 0.0, 800.0, 40.0), 0.0, 800.0,
                60, 1, [track.notes[0]] * 401, 0, 401,
            )
            assert not invalid
            assert [(rect.left(), rect.right()) for rect in normal] == [
                (150.0, 200.0), (700.0, 750.0)
            ]
            canvas.close()
            app.processEvents()
            """
        )
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=environment,
            text=True, capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
