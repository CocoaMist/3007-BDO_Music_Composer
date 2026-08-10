from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UiPaintRegressionTests(unittest.TestCase):
    def test_piano_roll_reuses_track_and_note_colors_within_one_frame(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
            )

            app = QApplication([])
            notes = [
                Note(60 + index % 5, 80 if index % 2 else 100, index * 25.0, 20.0, 0)
                for index in range(2_000)
            ]
            track = TrackState(1, notes, 0, False, "dense", 0x0B)
            window = MidiToBdoWindow()
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(1_180, 720)
            editor.show()
            app.processEvents()

            base_color_calls = []
            fill_color_calls = []
            original_base_color = editor.canvas._editable_note_base_color
            original_fill_color = editor.canvas._note_fill_color

            def counted_base_color():
                base_color_calls.append(1)
                return original_base_color()

            def counted_fill_color(note, **kwargs):
                fill_color_calls.append((int(note.vel), int(note.ntype)))
                return original_fill_color(note, **kwargs)

            editor.canvas._editable_note_base_color = counted_base_color
            editor.canvas._note_fill_color = counted_fill_color
            editor.canvas.grab()

            assert base_color_calls == [1], len(base_color_calls)
            assert set(fill_color_calls) == {(80, 0), (100, 0)}
            assert len(fill_color_calls) == 2, fill_color_calls
            editor.close()
            window.close()
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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_timeline_playback_reuses_static_frame_without_note_queries(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QRectF
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

            app = QApplication([])
            tracks = [
                TrackState(
                    track_id,
                    [
                        Note(
                            36 + note_index % 48,
                            80,
                            note_index * 37.0,
                            28.0,
                            0,
                        )
                        for note_index in range(2_000)
                    ],
                    0,
                    False,
                    f"Track {track_id}",
                    0x0B,
                )
                for track_id in range(12)
            ]
            canvas = TimelineCanvas()
            canvas.resize(1400, 760)
            canvas.set_tracks(tracks)
            canvas.show()
            app.processEvents()
            assert not canvas._static_timeline_cache.isNull()

            # Dense overview geometry is bounded by display resolution rather
            # than note count, while the authoritative interval index remains
            # untouched for editing and export.
            visible_duration = canvas._visible_duration_ms()
            ordered, note_lo, note_hi = canvas._visible_track_note_window(
                tracks[0], 0.0, visible_duration
            )
            pitch_min, pitch_max = canvas._track_pitch_bounds(tracks[0])
            normal, markers, invalid = canvas._timeline_note_rect_batches(
                tracks[0],
                QRectF(0.0, 0.0, 1200.0, 48.0),
                0.0,
                visible_duration,
                pitch_min,
                max(1, pitch_max - pitch_min),
                ordered,
                note_lo,
                note_hi,
            )
            assert 0 < len(normal) + len(invalid) <= 256
            assert not markers
            trace = canvas.velocity_curve_overlay.velocity_trace_points(
                tracks[0], 0.0, visible_duration
            )
            bounded_trace = canvas.velocity_curve_overlay._bounded_velocity_trace(
                trace, 0.0, visible_duration, 64
            )
            assert len(trace) == 2_000
            assert 0 < len(bounded_trace) <= 64

            trace_paints = []
            original_trace_paint = (
                canvas.velocity_curve_overlay.paint_velocity_trace
            )
            def counted_trace_paint(*args, **kwargs):
                trace_paints.append(1)
                return original_trace_paint(*args, **kwargs)
            canvas.velocity_curve_overlay.paint_velocity_trace = counted_trace_paint
            canvas.set_zoom_percent(400)
            app.processEvents()
            assert canvas._viewport_motion_active
            assert trace_paints == []
            QTest.qWait(180)
            app.processEvents()
            assert not canvas._viewport_motion_active
            assert trace_paints
            canvas.velocity_curve_overlay.paint_velocity_trace = original_trace_paint

            queries = []
            original_query = canvas._visible_track_note_window
            def counted_query(*args, **kwargs):
                queries.append(1)
                return original_query(*args, **kwargs)
            canvas._visible_track_note_window = counted_query

            for frame in range(30):
                canvas.set_playhead(frame * 16.0)
                app.processEvents()
            assert queries == [], len(queries)

            # Audio meters stay live but are outside the static cache.
            cache_key = canvas._static_timeline_cache_key
            canvas.set_track_levels({0: 0.9, 1: 0.5})
            app.processEvents()
            assert canvas._static_timeline_cache_key == cache_key
            assert queries == [], len(queries)

            # A real static visual change rebuilds once, then playback reuses
            # the new frame again.
            tracks[0].muted = True
            canvas.update()
            app.processEvents()
            assert queries, "mute change did not invalidate the static frame"
            queries.clear()
            for frame in range(30, 60):
                canvas.set_playhead(frame * 16.0)
                app.processEvents()
            assert queries == [], len(queries)

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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_marquee_stays_translucent_and_volume_uses_locale_width(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile

            from PySide6.QtCore import QRectF
            from PySide6.QtGui import QColor, QImage, QPainter
            from PySide6.QtWidgets import QApplication

            from bdo_midi import Note
            from bdo_music_composer.ui.i18n import install_localizer, tr
            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, PianoRollCanvas,
                TrackState,
            )

            app = QApplication([])

            # Reproduce the former brush leak: note painting left an opaque
            # brush active before the marquee border was drawn.
            image = QImage(80, 80, QImage.Format_ARGB32)
            base = QColor(28, 28, 30)
            image.fill(base)
            painter = QPainter(image)
            painter.setBrush(QColor(130, 70, 70))
            PianoRollCanvas._paint_marquee_overlay(
                painter,
                QRectF(10, 10, 60, 60),
            )
            painter.end()
            center = image.pixelColor(40, 40)
            assert base.red() < center.red() < 55, center.getRgb()
            assert center.green() < 50, center.getRgb()

            translations = install_localizer(app, "en_US")
            config_dir = tempfile.TemporaryDirectory()
            gui.CONFIG_PATH = Path(config_dir.name) / "config.json"
            window = MidiToBdoWindow()
            translations.set_language("en_US")
            label = tr("音量")
            assert label == "Volume"
            metrics = window.timeline.fontMetrics()
            width = window.timeline._volume_label_width(metrics, label)
            assert width >= metrics.horizontalAdvance(label) + 8
            assert width > 25

            # Exercise the actual paint order, not only the geometry helper:
            # a selected minimum-positive velocity retains one bright physical
            # pixel beside a dark 4-DIP rail and clear of both resize handles.
            track = TrackState(
                7, [Note(60, 1, 0.0, 100.0, 0)], 0, False, "rail", 0x0B
            )
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(1000, 700)
            editor.show()
            app.processEvents()
            editor.pitch_scroll.setValue(editor.canvas.MAX_PITCH - 76)
            painted_note = Note(
                60,
                1,
                0.0,
                20.0 / editor.canvas.px_per_ms,
                0,
            )
            editor.canvas.set_notes([painted_note])
            editor.canvas.selected = {0}
            editor.canvas.update()
            app.processEvents()
            note_rect = editor.canvas.note_rect(painted_note)
            assert note_rect.width() == 20.0
            rail, fill = editor.canvas.note_velocity_bar_rects(
                note_rect, 1, editor.canvas.devicePixelRatioF()
            )
            pixmap = editor.canvas.grab()
            ratio = pixmap.devicePixelRatio()
            image = pixmap.toImage()
            sample_y = round((rail.center().y()) * ratio)
            active = image.pixelColor(
                int(fill.left() * ratio),
                sample_y,
            )
            inactive = image.pixelColor(
                round((rail.right() - 1.0 / ratio) * ratio),
                sample_y,
            )
            assert rail.height() * ratio == round(4.0 * ratio)
            assert active.lightness() > inactive.lightness() + 45, (
                active.getRgb(), inactive.getRgb()
            )

            # At the minimum row height, semantic LOD removes text, the
            # velocity rail and resize handles instead of compressing them
            # into bright fragments. Black piano keys also drop labels while
            # octave landmarks remain available on natural C rows.
            editor.canvas.ROW_H = editor.canvas.MIN_ROW_H
            editor.canvas.pitch_top = 64
            compact_note = Note(
                60,
                127,
                0.0,
                160.0 / editor.canvas.px_per_ms,
                0,
            )
            editor.canvas.set_notes([compact_note])
            editor.canvas.selected = {0}
            editor.canvas.update()
            app.processEvents()
            compact_rect = editor.canvas.note_rect(compact_note)
            assert compact_rect.height() == 8.0
            assert editor.canvas.note_velocity_bar_rects(
                compact_rect,
                compact_note.vel,
                editor.canvas.devicePixelRatioF(),
            ) is None
            compact_image = editor.canvas.grab().toImage()
            compact_dpr = editor.canvas.devicePixelRatioF()
            bright_inner_pixels = []
            for x in range(
                round((compact_rect.left() + 6) * compact_dpr),
                round((compact_rect.right() - 6) * compact_dpr),
            ):
                for y in range(
                    round((compact_rect.top() + 2) * compact_dpr),
                    round((compact_rect.bottom() - 2) * compact_dpr),
                ):
                    color = compact_image.pixelColor(x, y)
                    if color.lightness() > 190:
                        bright_inner_pixels.append(color.getRgb())
            assert not bright_inner_pixels, bright_inner_pixels[:8]

            black_pitch_y = (
                editor.canvas.RULER_H
                + (editor.canvas.pitch_top - 61) * editor.canvas.ROW_H
            )
            black_key_bright_pixels = []
            for x in range(12, 52):
                for y in range(
                    round(black_pitch_y + 2),
                    round(black_pitch_y + editor.canvas.ROW_H - 2),
                ):
                    color = compact_image.pixelColor(x, y)
                    if color.lightness() > 150:
                        black_key_bright_pixels.append(color.getRgb())
            assert not black_key_bright_pixels, black_key_bright_pixels[:8]
            editor.close()

            window.close()
            app.processEvents()
            config_dir.cleanup()
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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
