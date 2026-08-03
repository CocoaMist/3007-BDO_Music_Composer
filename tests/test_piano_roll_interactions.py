from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PianoRollInteractionTests(unittest.TestCase):
    def test_safe_creation_cursor_paste_and_ctrl_drag_clone(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QLabel
            from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            track = TrackState(
                1,
                [
                    Note(60, 91, 0.0, 250.0, 0),
                    Note(64, 82, 750.0, 250.0, 0),
                ],
                0,
                False,
                "lead",
                0x0B,
            )
            window = MidiToBdoWindow()
            reference_track = TrackState(
                2,
                [Note(70, 75, 1500.0, 300.0, 0)],
                0,
                False,
                "reference",
                0x0B,
            )
            window.tracks = [track, reference_track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(1180, 720)
            editor.show()
            app.processEvents()
            assert editor.width() >= editor.minimumWidth()
            assert editor.height() >= editor.minimumHeight()
            track_title = editor.findChild(QLabel, "EditorTrackTitle")
            assert track_title is not None and track_title.text() == "lead"
            assert "lead" not in editor.track_meta.text()

            # The vertical bar follows the usual viewport direction: dragging
            # down reveals lower pitches and never scrolls below MIDI pitch 0.
            editor.update_scrollbars()
            pitch_min, pitch_max = editor.pitch_top_bounds()
            visible_rows = editor.visible_pitch_rows()
            assert editor.pitch_scroll.minimum() == 0
            assert editor.pitch_scroll.maximum() == pitch_max - pitch_min
            assert editor.pitch_scroll.pageStep() == visible_rows
            editor.pitch_scroll.setValue(editor.pitch_scroll.maximum())
            assert editor.canvas.pitch_top == pitch_min
            assert editor.canvas.pitch_top - visible_rows + 1 >= editor.canvas.MIN_PITCH
            editor.pitch_scroll.setValue(0)
            assert editor.canvas.pitch_top == editor.canvas.MAX_PITCH
            editor.pitch_scroll.setValue(editor.canvas.MAX_PITCH - 84)
            assert editor.canvas.pitch_top == 84

            # Game-style note blocks keep a four-DIP velocity rail inside the
            # body.  Its active width is monotonic, pixel-aligned at fractional
            # DPI, and velocity zero never invents a visible value.
            visual_rect = editor.canvas.note_rect(editor.canvas.notes[0])
            zero_geometry = editor.canvas.note_velocity_bar_rects(
                visual_rect, 0, 1.0
            )
            middle_geometry = editor.canvas.note_velocity_bar_rects(
                visual_rect, 64, 1.0
            )
            full_geometry = editor.canvas.note_velocity_bar_rects(
                visual_rect, 127, 1.0
            )
            assert zero_geometry is not None
            assert middle_geometry is not None
            assert full_geometry is not None
            zero_rail, zero_fill = zero_geometry
            middle_rail, middle_fill = middle_geometry
            full_rail, full_fill = full_geometry
            assert zero_rail.height() == editor.canvas.NOTE_VELOCITY_BAR_HEIGHT == 4.0
            assert visual_rect.contains(zero_rail)
            assert zero_fill.width() == 0.0
            assert 0.49 < middle_fill.width() / middle_rail.width() < 0.52
            assert full_fill.width() == full_rail.width()
            scaled_rail, _scaled_fill = editor.canvas.note_velocity_bar_rects(
                visual_rect, 100, 1.25
            )
            assert abs(scaled_rail.height() * 1.25 - round(scaled_rail.height() * 1.25)) < 1e-9

            # A compact note has no truthful room for two resize handles.  Its
            # centre must remain draggable; wider notes expose aligned edges.
            compact = Note(60, 90, 0.0, 1.0, 0)
            editor.canvas.set_notes([compact])
            compact_rect = editor.canvas.note_rect(compact)
            assert compact_rect.width() == 4.0
            assert editor.canvas.note_at(compact_rect.center()) == (0, "move")
            twelve_px = Note(
                60,
                90,
                0.0,
                editor.canvas.NOTE_RESIZE_VISUAL_MIN_WIDTH / editor.canvas.px_per_ms,
                0,
            )
            editor.canvas.set_notes([twelve_px])
            resize_rect = editor.canvas.note_rect(twelve_px)
            assert editor.canvas.note_velocity_bar_rects(
                resize_rect, 90, 1.0
            ) is None
            assert editor.canvas.note_velocity_bar_rects(
                QRectF(0.0, 0.0, 80.0, 8.0), 90, 1.0
            ) is None
            centre_y = resize_rect.center().y()
            assert editor.canvas.note_at(
                QPointF(resize_rect.left() + 1.0, centre_y)
            ) == (0, "resize_left")
            assert editor.canvas.note_at(resize_rect.center()) == (0, "move")
            assert editor.canvas.note_at(
                QPointF(resize_rect.right() - 1.0, centre_y)
            ) == (0, "resize_right")
            editor.canvas.set_notes([
                Note(60, 91, 0.0, 250.0, 0),
                Note(64, 82, 750.0, 250.0, 0),
            ])

            # Content/zoom changes must clamp the canvas and the horizontal bar
            # together instead of leaving the roll stranded in blank space.
            initial_notes = list(editor.canvas.notes)
            editor.canvas.set_notes([Note(60, 91, 0.0, 12000.0, 0)])
            editor.editor_zoom.setValue(320)
            editor.update_scrollbars()
            assert editor.time_scroll.maximum() > 0
            editor.set_time_scroll(10**9)
            assert editor.canvas.scroll_ms == editor.time_scroll.maximum()
            assert editor.time_scroll.value() == editor.time_scroll.maximum()
            editor.canvas.set_notes(initial_notes)
            editor.editor_zoom.setValue(30)
            editor.update_scrollbars()
            assert editor.time_scroll.maximum() == 0
            assert editor.time_scroll.value() == 0
            assert editor.canvas.scroll_ms == 0
            editor.editor_zoom.setValue(92)
            editor.canvas.set_notes(initial_notes)
            editor.update_scrollbars()

            # Game velocity has a real zero value.  Numeric edits and the
            # velocity lane must not silently lift it to one.
            editor.canvas.selected = {0}
            editor.apply_field("vel", "0")
            assert editor.canvas.notes[0].vel == 0
            lane_bottom = editor.velocity_lane.height() - 5.0
            assert editor.velocity_lane._velocity_at(lane_bottom) == 0
            assert abs(editor.velocity_lane._y_for_velocity(0) - lane_bottom) < 0.01
            editor.undo()
            assert editor.canvas.notes == initial_notes

            def grid_point(time_ms, pitch):
                return QPoint(
                    round(editor.canvas.x_at_time(time_ms)),
                    round(editor.canvas.RULER_H + (editor.canvas.pitch_top - pitch) * editor.canvas.ROW_H + 8),
                )

            # Selection mode uses an empty click only for cursor placement.
            blank = grid_point(1500.0, 70)
            before = list(editor.canvas.notes)
            QTest.mouseClick(editor.canvas, Qt.LeftButton, pos=blank)
            assert editor.canvas.notes == before
            assert not editor.canvas.selected
            assert abs(editor.canvas.edit_cursor_ms - 1500.0) < 0.01

            # Double-click creation is a single undoable edit.
            QTest.mouseDClick(editor.canvas, Qt.LeftButton, pos=blank)
            assert len(editor.canvas.notes) == len(before) + 1
            assert editor.canvas.notes[-1].start == 1500.0
            editor.undo()
            assert editor.canvas.notes == before

            # Other-track reference lines are paint-only. They never block
            # creating an editable note at the same pitch and time.
            editor.ghost_box.setChecked(True)
            assert len(editor.canvas.ghost_notes) == 1
            QTest.mouseDClick(editor.canvas, Qt.LeftButton, pos=blank)
            assert len(editor.canvas.notes) == len(before) + 1
            assert editor.canvas.notes[-1].pitch == 70
            assert editor.canvas.notes[-1].start == 1500.0
            editor.undo()
            assert editor.canvas.notes == before

            # Paste targets the visible edit cursor instead of a viewport offset.
            editor.canvas.selected = {0}
            editor.copy_selected()
            paste_at = grid_point(2000.0, 70)
            QTest.mouseClick(editor.canvas, Qt.LeftButton, pos=paste_at)
            editor.paste_notes()
            assert editor.canvas.notes[-1].start == 2000.0
            assert editor.canvas.notes[-1].vel == before[0].vel
            editor.undo()
            assert editor.canvas.notes == before

            # Keyboard paste at the copied note's own onset must move the
            # whole group to the nearest free grid position instead of
            # creating an invisible same-pitch overlap. Repeated Ctrl+V keeps
            # advancing from the newly pasted selection.
            editor.canvas.selected = {0}
            editor.canvas.set_edit_cursor(0.0)
            QTest.keyClick(editor.canvas, Qt.Key_C, Qt.ControlModifier)
            QTest.keyClick(editor.canvas, Qt.Key_V, Qt.ControlModifier)
            assert editor.canvas.notes[-1].pitch == before[0].pitch
            assert editor.canvas.notes[-1].start == editor.quantize_ms()
            QTest.keyClick(editor.canvas, Qt.Key_V, Qt.ControlModifier)
            assert editor.canvas.notes[-1].start == editor.quantize_ms() * 2
            same_pitch = sorted(
                (note for note in editor.canvas.notes if note.pitch == 60),
                key=lambda note: note.start,
            )
            assert all(
                left.start + left.dur <= right.start
                for left, right in zip(same_pitch, same_pitch[1:])
            )
            editor.undo()
            editor.undo()
            assert editor.canvas.notes == before

            # Ctrl-drag clones the grabbed note and preserves the source note.
            source = editor.canvas.note_rect(editor.canvas.notes[0]).center()
            target = QPointF(source.x() + editor.canvas.px_per_beat, source.y() - editor.canvas.ROW_H)
            for event in (
                QMouseEvent(
                    QEvent.MouseButtonPress, source, source,
                    Qt.LeftButton, Qt.LeftButton, Qt.ControlModifier,
                ),
                QMouseEvent(
                    QEvent.MouseMove, target, target,
                    Qt.NoButton, Qt.LeftButton, Qt.ControlModifier,
                ),
                QMouseEvent(
                    QEvent.MouseButtonRelease, target, target,
                    Qt.LeftButton, Qt.NoButton, Qt.ControlModifier,
                ),
            ):
                QApplication.sendEvent(editor.canvas, event)
            assert len(editor.canvas.notes) == len(before) + 1
            clone = editor.canvas.notes[-1]
            assert clone.start == before[0].start + editor.canvas.beat_ms
            assert clone.pitch == before[0].pitch + 1
            assert clone.vel == before[0].vel
            assert clone.dur == before[0].dur
            editor.undo()
            assert editor.canvas.notes == before

            # A Ctrl-click remains selection toggling and never creates a clone.
            editor.canvas.selected = {0}
            source_point = QPoint(round(source.x()), round(source.y()))
            QTest.mouseClick(
                editor.canvas, Qt.LeftButton, Qt.ControlModifier, pos=source_point,
            )
            assert len(editor.canvas.notes) == len(before)
            assert 0 not in editor.canvas.selected

            # A long note that begins before the horizontal viewport must be
            # clipped at the grid edge instead of painting through piano keys.
            editor.canvas.notes = [Note(60, 91, 0.0, 3000.0, 0)]
            editor.canvas.rebuild_note_index()
            editor.canvas.pitch_top = 72
            editor.set_time_scroll(1000)
            editor.canvas.update()
            app.processEvents()
            note_y = round(editor.canvas.note_rect(editor.canvas.notes[0]).center().y())
            with_note = editor.canvas.grab().toImage()
            editor.canvas.notes = []
            editor.canvas.rebuild_note_index()
            editor.canvas.update()
            app.processEvents()
            without_note = editor.canvas.grab().toImage()
            assert with_note.pixelColor(editor.canvas.KEY_W - 5, note_y) == without_note.pixelColor(
                editor.canvas.KEY_W - 5, note_y
            )
            assert with_note.pixelColor(editor.canvas.KEY_W + 5, note_y) != without_note.pixelColor(
                editor.canvas.KEY_W + 5, note_y
            )
            assert editor.canvas.note_at(QPointF(editor.canvas.KEY_W - 5, note_y))[0] is None

            editor.close()

            # The empty-score invitation is custom-painted and must remain safe
            # when there are no note rectangles or visible-note indexes.
            empty_track = TrackState(2, [], 0, False, "empty", 0x0B)
            window.tracks = [empty_track]
            empty_editor = MidiNoteEditorDialog(window, empty_track, 120, 4)
            empty_editor.resize(1000, 700)
            empty_editor.show()
            app.processEvents()
            assert not empty_editor.canvas.grab().isNull()
            assert empty_editor.track_meta.text().startswith("♫ 0")
            empty_editor.close()
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
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
