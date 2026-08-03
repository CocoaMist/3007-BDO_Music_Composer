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
            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.ui.main_window import (
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
            visible_duration = timeline._visible_duration_ms()
            overview_grid_width = timeline.width() - 320
            assert not timeline._show_measure_banding(
                visible_duration, overview_grid_width
            )
            overview_ticks = timeline._visible_musical_ticks(
                0.0, visible_duration, overview_grid_width
            )
            tick_positions = [
                value / visible_duration * overview_grid_width
                for value, _major, _label in overview_ticks
            ]
            assert all(
                right - left >= timeline.GRID_MIN_TICK_SPACING_PX - 0.01
                for left, right in zip(tick_positions, tick_positions[1:])
            )
            assert timeline._show_measure_banding(
                visible_duration / 8.0, overview_grid_width
            )
            actions = {action for _rect, action, _track in timeline.hit_regions}
            assert "shorten" not in actions
            assert "lengthen" not in actions
            assert "fx" in actions
            normal_lane = next(
                rect for rect, action, track in timeline.hit_regions
                if action == "lane" and track is tracks[0]
            )
            normal_controls = [
                rect for rect, action, track in timeline.hit_regions
                if action in {"mute", "solo", "fx"} and track is tracks[0]
            ]
            normal_volume = next(
                rect for rect, action, track in timeline.hit_regions
                if action == "track_volume" and track is tracks[0]
            )
            assert len(normal_controls) == 3
            assert len({round(rect.center().y(), 3) for rect in normal_controls}) == 1
            assert normal_controls[0].center().y() < normal_lane.center().y()
            assert normal_volume.center().y() > normal_lane.center().y()

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
            assert len({round(rect.center().y(), 3) for rect in marnian_controls}) == 1
            assert marnian_controls[0].center().y() < marnian_lane.center().y()
            timeline.set_tracks(tracks)
            app.processEvents()
            initial_audio_lane = next(
                rect for rect, action, target in timeline.hit_regions
                if action == "audio_lane" and target is reference
            )
            assert initial_audio_lane.height() == 34
            assert initial_audio_lane.height() < timeline._lane_height()
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
            loaded_audio_lane = next(
                rect for rect, action, target in timeline.hit_regions
                if action == "audio_lane" and target is reference
            )
            assert loaded_audio_lane.height() == timeline._lane_height()
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
            editor.ghost_box.setChecked(True)
            editor.canvas.grab()
            roll_background_key = editor.canvas._background_cache.cacheKey()
            editor.canvas.grab()
            assert (
                editor.canvas._background_cache.cacheKey()
                == roll_background_key
            )
            visible_first = editor.canvas.visible_note_indices()
            visible_second = editor.canvas.visible_note_indices()
            assert visible_first is visible_second
            assert 0 < len(visible_first) < len(dense_notes) // 10
            assert 0 < len(editor.canvas.visible_ghost_notes()) < len(ghost_notes) // 10
            assert editor.canvas.content_end_ms == dense_notes[-1].start + dense_notes[-1].dur

            # One song-long candidate must not widen every later viewport
            # query to the full candidate list.  The block-max-end index
            # should inspect only the long-note block and the local blocks.
            transcription_candidates = [
                TranscriptionCandidate(
                    60, 90, 0.0, 300000.0, 0.9,
                    candidate_id="candidate-long",
                ),
                *[
                    TranscriptionCandidate(
                        40 + index % 48,
                        80,
                        float(index * 25),
                        10.0,
                        0.7,
                        candidate_id=f"candidate-{index}",
                    )
                    for index in range(1, 12000)
                ],
            ]
            editor.canvas.set_transcription_review(
                tuple(transcription_candidates),
                lambda candidate: candidate.candidate_id,
            )
            query_left = 290000.0
            query_right = 291000.0
            visible_candidates = editor.canvas._visible_candidate_pairs(
                query_left,
                query_right,
            )
            visible_ids = {
                candidate_id
                for candidate_id, _candidate in visible_candidates
            }
            assert "candidate-long" in visible_ids
            assert 1 < len(visible_candidates) < 100
            pixel_margin_ms = 4.0 / editor.canvas.px_per_ms
            assert all(
                candidate.start_ms <= query_right
                and candidate.start_ms + candidate.duration_ms
                >= query_left - pixel_margin_ms
                for _candidate_id, candidate in visible_candidates
            )
            assert (
                editor.canvas._last_candidate_query_inspections
                <= editor.canvas.CANDIDATE_QUERY_BLOCK_SIZE * 4
            )

            class WheelEvent:
                def __init__(
                    self,
                    x,
                    modifiers=Qt.ControlModifier,
                    y=200,
                    *,
                    angle_delta=QPoint(0, 120),
                    pixel_delta=QPoint(0, 0),
                ):
                    self._position = QPointF(x, y)
                    self._modifiers = modifiers
                    self._angle_delta = angle_delta
                    self._pixel_delta = pixel_delta
                    self.accepted = False

                def angleDelta(self):
                    return self._angle_delta

                def pixelDelta(self):
                    return self._pixel_delta

                def modifiers(self):
                    return self._modifiers

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

            anchor_y = 320.0
            anchor_pitch = editor.canvas.pitch_at(anchor_y)
            old_row_height = editor.canvas.ROW_H
            vertical_wheel = WheelEvent(
                anchor_x,
                Qt.AltModifier,
                anchor_y,
            )
            editor.canvas.wheelEvent(vertical_wheel)
            assert vertical_wheel.accepted
            assert editor.canvas.ROW_H > old_row_height, (
                old_row_height, editor.canvas.ROW_H
            )
            vertical_wheel_height = editor.canvas.ROW_H
            assert abs(editor.canvas.pitch_at(anchor_y) - anchor_pitch) <= 1, (
                anchor_pitch, editor.canvas.pitch_at(anchor_y),
                editor.canvas.pitch_top, editor.canvas.ROW_H,
            )
            horizontal_driver_wheel = WheelEvent(
                anchor_x,
                Qt.AltModifier,
                anchor_y,
                angle_delta=QPoint(-120, 0),
            )
            editor.canvas.wheelEvent(horizontal_driver_wheel)
            assert horizontal_driver_wheel.accepted
            assert editor.canvas.ROW_H < vertical_wheel_height

            row_height_before_touchpad = editor.canvas.ROW_H
            smooth_touchpad_wheel = WheelEvent(
                anchor_x,
                Qt.AltModifier,
                anchor_y,
                angle_delta=QPoint(0, 0),
                pixel_delta=QPoint(0, 25),
            )
            editor.canvas.wheelEvent(smooth_touchpad_wheel)
            assert smooth_touchpad_wheel.accepted
            assert editor.canvas.ROW_H > row_height_before_touchpad
            assert "px" in editor.status.text()

            for _index in range(80):
                editor.canvas.wheelEvent(
                    WheelEvent(anchor_x, Qt.ControlModifier)
                )
            assert editor.canvas.px_per_beat > 320.0, editor.canvas.px_per_beat
            assert editor.canvas.px_per_beat <= editor.canvas.MAX_PX_PER_BEAT

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
