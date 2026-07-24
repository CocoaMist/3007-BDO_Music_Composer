from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DenseProjectUiTests(unittest.TestCase):
    def test_visible_range_caches_and_cursor_anchored_zoom(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, QPointF, Qt
            from PySide6.QtWidgets import QApplication
            from pyside_bdo_gui import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, ReferenceAudioController,
                TimelineCanvas, TrackState,
            )

            app = QApplication([])
            tracks = []
            for track_id in range(120):
                notes = [
                    Note(48 + index % 24, 90, float(index * 125), 100.0, 0)
                    for index in range(400)
                ]
                tracks.append(TrackState(track_id, notes, 0, False, f"track-{track_id}", 0x0B))

            timeline = TimelineCanvas()
            reference = ReferenceAudioController(timeline)
            timeline.set_reference_audio(reference)
            timeline.resize(1200, 500)
            timeline.set_tracks(tracks)
            timeline.show()
            app.processEvents()
            actions = {action for _rect, action, _track in timeline.hit_regions}
            assert "shorten" not in actions
            assert "lengthen" not in actions
            assert "fx" not in actions
            normal_lane = next(
                rect for rect, action, track in timeline.hit_regions
                if action == "lane" and track is tracks[0]
            )
            normal_controls = [
                rect for rect, action, track in timeline.hit_regions
                if action in {"mute", "solo"} and track is tracks[0]
            ]
            assert len(normal_controls) == 2
            assert all(abs(rect.center().y() - normal_lane.center().y()) < 0.01 for rect in normal_controls)

            marnian = TrackState(999, tracks[0].notes, 0, False, "marnian", 0x14)
            timeline.set_tracks([marnian])
            app.processEvents()
            marnian_lane = next(
                rect for rect, action, track in timeline.hit_regions
                if action == "lane" and track is marnian
            )
            marnian_controls = [
                rect for rect, action, track in timeline.hit_regions
                if action in {"mute", "solo", "fx"} and track is marnian
            ]
            assert {action for _rect, action, _track in timeline.hit_regions} >= {"mute", "solo", "fx"}
            assert len(marnian_controls) == 3
            assert all(abs(rect.center().y() - marnian_lane.center().y()) < 0.01 for rect in marnian_controls)
            timeline.set_tracks(tracks)
            app.processEvents()
            initial_audio_lane = next(
                rect for rect, action, target in timeline.hit_regions
                if action == "audio_lane" and target is reference
            )
            first, last = timeline._visible_track_row_range(450.0)
            assert last - first <= 10
            timeline.track_scroll.setValue(timeline.track_scroll.maximum())
            first, last = timeline._visible_track_row_range(450.0)
            assert first > 0 and last == len(tracks)
            app.processEvents()
            scrolled_audio_lane = next(
                rect for rect, action, target in timeline.hit_regions
                if action == "audio_lane" and target is reference
            )
            assert scrolled_audio_lane.top() == initial_audio_lane.top()
            audio_actions = {
                action for _rect, action, target in timeline.hit_regions
                if target is reference
            }
            assert audio_actions >= {
                "audio_lane", "audio_load", "audio_waveform",
                "audio_volume_down", "audio_volume", "audio_volume_up",
            }
            assert "audio_play" not in audio_actions
            assert "audio_stop" not in audio_actions
            reference._audio_path = __import__("pathlib").Path("loaded.wav")
            timeline.update()
            app.processEvents()
            loaded_audio_actions = {
                action for _rect, action, target in timeline.hit_regions
                if target is reference
            }
            assert "audio_unload" in loaded_audio_actions
            assert "audio_load" not in loaded_audio_actions
            unload_rect = next(
                rect for rect, action, target in timeline.hit_regions
                if action == "audio_unload" and target is reference
            )
            from PySide6.QtTest import QTest
            QTest.mouseClick(
                timeline,
                Qt.LeftButton,
                Qt.NoModifier,
                unload_rect.center().toPoint(),
            )
            app.processEvents()
            assert not reference.audio_path
            timeline.set_zoom_percent(800)
            ordered, lo, hi = timeline._visible_track_note_window(
                tracks[0], timeline.view_start_ms,
                timeline.view_start_ms + timeline._visible_duration_ms(),
            )
            assert ordered and hi - lo < 80
            timeline._refresh_scaled_background()
            cache_key = timeline._scaled_background.cacheKey()
            timeline._refresh_scaled_background()
            assert timeline._scaled_background.cacheKey() == cache_key
            for _ in range(3):
                for pitch in range(128):
                    timeline._note_has_conversion_problem(tracks[0], pitch)
            assert len(timeline._conversion_problem_cache) <= 128
            reference.waveform = [(0.0, 90000.0, 0.5)]
            reference.waveform_starts = [0.0]
            reference.timeline_changed.emit()
            assert timeline._timeline_end_ms() == 90000.0

            dense_notes = [
                Note(40 + index % 48, 90, float(index * 50), 45.0, 0)
                for index in range(12000)
            ]
            ghost_notes = [
                Note(45 + index % 36, 80, float(index * 70), 55.0, 0)
                for index in range(8000)
            ]
            dense = TrackState(1000, dense_notes, 0, False, "dense", 0x0B)
            ghost = TrackState(1001, ghost_notes, 0, False, "ghost", 0x0B)
            window = MidiToBdoWindow()
            window.tracks = [dense, ghost]
            editor = MidiNoteEditorDialog(window, dense, 120, 4)
            editor.resize(1180, 720)
            editor.show()
            app.processEvents()
            visible_first = editor.canvas.visible_note_indices()
            visible_second = editor.canvas.visible_note_indices()
            assert visible_first is visible_second
            assert 0 < len(visible_first) < len(dense_notes) // 10
            assert 0 < len(editor.canvas.visible_ghost_notes()) < len(ghost_notes) // 10
            assert editor.canvas.content_end_ms == dense_notes[-1].start + dense_notes[-1].dur

            class WheelEvent:
                def __init__(self, x):
                    self._position = QPointF(x, 200)
                    self.accepted = False

                def angleDelta(self):
                    return QPoint(0, 120)

                def modifiers(self):
                    return Qt.ControlModifier

                def position(self):
                    return self._position

                def accept(self):
                    self.accepted = True

            anchor_x = 560.0
            before = editor.canvas.time_at(anchor_x)
            wheel = WheelEvent(anchor_x)
            editor.canvas.wheelEvent(wheel)
            after = editor.canvas.time_at(anchor_x)
            assert wheel.accepted
            assert abs(before - after) < 0.01
            assert editor.editor_zoom.value() == round(editor.canvas.px_per_beat)

            editor.close()
            window.close()
            timeline.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
