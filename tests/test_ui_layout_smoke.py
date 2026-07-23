from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UiLayoutSmokeTests(unittest.TestCase):
    def test_primary_windows_fit_at_supported_minimum_sizes(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QFrame, QListWidget, QScrollArea, QStackedWidget, QWidget
            from pyside_bdo_gui import (
                GlobalToast, MidiNoteEditorDialog, MidiToBdoWindow, Note,
                SettingsDialog, StartupSplash, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window.resize(window.minimumSize())
            window.show()
            app.processEvents()
            assert app.property("bdoFixedDarkTheme") is True
            assert window._system_uses_dark_theme()

            splash = StartupSplash()
            splash.show()
            app.processEvents()
            assert splash.size().width() == 470
            assert splash.size().height() == 734
            assert splash.artwork.has_artwork
            assert not splash.artwork._cover.isNull()
            assert splash.spinner._timer.isActive()
            initial_spinner_frame = splash.spinner.frame
            QTest.qWait(90)
            app.processEvents()
            assert splash.spinner.frame != initial_spinner_frame
            splash.set_status("准备完成")
            assert splash.status_label.text() == "准备完成"
            splash.finish(window, minimum_visible_ms=0)
            QTest.qWait(20)
            app.processEvents()
            assert splash.isHidden()

            toast = window.show_toast("测试提示", duration_ms=80)
            app.processEvents()
            assert isinstance(toast, GlobalToast)
            assert toast.isVisible()
            assert toast.message.text() == "测试提示"
            assert 0 <= toast.x() <= window.width() - toast.width()
            QTest.qWait(190)
            assert toast.opacity.opacity() > 0.9
            QTest.qWait(380)
            app.processEvents()
            assert toast.isHidden()

            inspector = window.findChild(QFrame, "Inspector")
            assert inspector is not None
            assert inspector.height() >= 70

            settings = SettingsDialog(window)
            settings.resize(settings.minimumSize())
            settings.show()
            app.processEvents()
            scroll = settings.findChild(QScrollArea, "SettingsScroll")
            assert scroll is not None
            assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert scroll.widget().minimumSizeHint().width() <= scroll.viewport().width()
            assert scroll.verticalScrollBar().sizeHint().width() == 12
            nav = settings.findChild(QListWidget, "SettingsNav")
            pages = settings.findChild(QStackedWidget, "SettingsPages")
            assert nav is not None and pages is not None
            assert nav.count() == pages.count() == 3
            assert [nav.item(index).text() for index in range(nav.count())] == [
                "通用与导出", "MIDI 与力度", "音源与效果"
            ]
            for index in range(nav.count()):
                nav.setCurrentRow(index)
                app.processEvents()
                assert pages.currentIndex() == index
                active_scroll = pages.currentWidget()
                assert isinstance(active_scroll, QScrollArea)
                assert active_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
                assert active_scroll.widget().minimumSizeHint().width() <= active_scroll.viewport().width()
            settings.close()

            track = TrackState(1, [Note(60, 96, 0, 400, 0)], 0, False, "lead", 0x0B)
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            assert window.realtime_status_timer.interval() == 16
            assert editor.playback_timer.interval() == 16
            assert editor.objectName() == "MidiNoteEditorDialog"
            assert editor.windowFlags() & Qt.WindowMinimizeButtonHint
            assert editor.windowFlags() & Qt.WindowMaximizeButtonHint
            editor.resize(editor.minimumSize())
            editor.show()
            app.processEvents()
            toolbar = editor.findChild(QFrame, "EditorToolbar")
            assert toolbar is not None
            assert toolbar.height() >= 38
            workspace = editor.findChild(QFrame, "EditorWorkspace")
            assert workspace is not None
            workspace_left = workspace.mapTo(editor, QPoint(0, 0)).x()
            assert workspace_left == editor.contentsRect().left()
            assert workspace_left + workspace.width() == editor.contentsRect().right() + 1
            assert toolbar.mapTo(editor, QPoint(0, 0)).x() > workspace_left
            assert toolbar.isAncestorOf(editor.apply_button)
            assert toolbar.isAncestorOf(editor.cancel_button)
            assert toolbar.isAncestorOf(editor.confirm_button)
            assert not hasattr(editor, "playback_timeline")
            top_inspector = editor.findChild(QFrame, "NoteInspectorTop")
            assert top_inspector is not None and top_inspector.isVisible()
            assert top_inspector.isAncestorOf(editor.velocity_toggle)
            assert editor.canvas.ROW_H == 20
            assert editor.canvas.KEY_W == 86
            assert editor.canvas.BLACK_KEY_X == 8
            assert editor.canvas.BLACK_KEY_W == 48
            inspector_height = top_inspector.height()
            assert editor.note_mode_button.height() == editor.articulation_mode_button.height() == editor.grid_mode_button.height()
            assert editor.note_controls.isVisible()
            assert not editor.articulation_controls.isVisible()
            assert not editor.grid_controls.isVisible()
            assert editor.pitch_scroll.width() == 12
            assert editor.time_scroll.height() == 12
            grid_rect = editor.canvas.grid_rect()
            assert grid_rect.left() == editor.canvas.KEY_W
            assert grid_rect.right() == editor.canvas.width()
            assert editor.canvas.note_rect(editor.canvas.notes[0]).left() == editor.canvas.x_at_time(
                editor.canvas.notes[0].start
            )
            scroll_corner = editor.findChild(QWidget, "PianoScrollCorner")
            assert scroll_corner is not None and scroll_corner.size().width() == 12
            editor.articulation_mode_button.click()
            app.processEvents()
            assert top_inspector.height() == inspector_height
            assert editor.articulation_controls.isVisible()
            assert not editor.note_controls.isVisible()
            editor.canvas.selected = {0}
            editor.refresh_fields()
            editor.articulation_buttons[3].click()
            assert editor.canvas.notes[0].ntype == 3
            editor.grid_mode_button.click()
            app.processEvents()
            assert top_inspector.height() == inspector_height
            assert editor.grid_controls.isVisible()
            assert not editor.note_controls.isVisible()
            editor_toast = getattr(editor, "_global_toast", None)
            assert isinstance(editor_toast, GlobalToast)
            assert "Ctrl+拖动复制" in editor_toast.message.text()
            assert editor_toast.y() >= workspace.geometry().top()
            editor.note_mode_button.click()
            app.processEvents()
            assert top_inspector.height() == inspector_height
            assert editor.note_controls.isVisible()
            footer = editor.findChild(QFrame, "EditorFooter")
            assert footer is not None
            assert footer.height() == 31
            assert footer.geometry().bottom() <= editor.contentsRect().bottom()
            assert not editor.velocity_lane.isVisible()
            editor.canvas.selected = {0}
            editor.refresh_fields()
            assert editor.selection_summary.text().startswith("已选择 1 个音符")
            ruler_x = round(editor.canvas.KEY_W + 500.0 * editor.canvas.px_per_ms)
            QTest.mouseClick(editor.canvas, Qt.LeftButton, pos=QPoint(ruler_x, 5))
            assert abs(editor.playhead_ms - 500.0) < 10.0
            editor.velocity_toggle.setChecked(True)
            app.processEvents()
            assert editor.velocity_lane.isVisible()
            bar = editor.velocity_lane._bar_rect(0)
            target_y = editor.velocity_lane._y_for_velocity(64)
            QTest.mouseClick(
                editor.velocity_lane, Qt.LeftButton,
                pos=QPoint(round(bar.center().x()), round(target_y)),
            )
            assert abs(editor.canvas.notes[0].vel - 64) <= 1
            editor.canvas.setFocus()
            QTest.keyClick(editor.canvas, Qt.Key_Up, Qt.ControlModifier)
            assert editor.canvas.notes[0].vel == 65
            editor.resize(1440, 900)
            app.processEvents()
            assert editor.canvas.width() > 1300

            class FakeAudio:
                def __init__(self):
                    from types import SimpleNamespace
                    self.status = SimpleNamespace(
                        preload_progress=0.0, preload_loaded=0, preload_total=4,
                        position_ms=0.0, duration_ms=2000.0, state="paused",
                    )
                    self.ready = False
                    self.loaded_from = None
                    self.loaded_pitch = None
                    self.committed_from = None
                    self.played = False
                    self.clear_count = 0

                def load_project_async(self, _tracks, _map, start, *_effects):
                    self.loaded_from = start
                    self.loaded_pitch = _tracks[0].notes[0].pitch if _tracks and _tracks[0].notes else None
                    self.status.preload_loaded = 0
                    self.status.preload_total = 4
                    self.status.preload_progress = 0.0

                def get_status(self):
                    return self.status

                def finish_loading(self, start):
                    if not self.ready:
                        return None
                    self.committed_from = start
                    return {"events": 1, "samples": 1, "cache_bytes": 64, "unverified": []}

                def finish_audition_loading(self):
                    if not self.ready:
                        return None
                    self.committed_from = 0.0
                    self.played = True
                    self.status.state = "playing"
                    return {"events": 1, "samples": 1, "cache_bytes": 64, "unverified": []}

                def play(self):
                    self.played = True
                    self.status.state = "playing"

                def stop(self):
                    self.status.state = "stopped"

                def clear_playback(self):
                    self.clear_count += 1
                    self.cancel_loading()
                    self.status.state = "stopped"

                def cancel_loading(self):
                    self.status.preload_loaded = self.status.preload_total = 0

                def seek(self, position):
                    self.status.position_ms = position

            fake = FakeAudio()
            window.realtime_audio = fake
            window._stop_preview = lambda reset_playhead=False: fake.stop()
            window._realtime_preview_blockers = lambda _tracks: []
            editor.draw_mode_button.setChecked(True)
            before_count = len(editor.canvas.notes)
            draw_start = QPoint(editor.canvas.KEY_W + 500, editor.canvas.RULER_H + 180)
            draw_end = QPoint(draw_start.x() + 90, draw_start.y() - 10)
            QTest.mousePress(editor.canvas, Qt.LeftButton, pos=draw_start)
            QTest.mouseMove(editor.canvas, pos=draw_end)
            QTest.mouseRelease(editor.canvas, Qt.LeftButton, pos=draw_end)
            assert len(editor.canvas.notes) == before_count + 1
            drawn = editor.canvas.notes[-1]
            assert drawn.dur > editor.quantize_ms()
            assert drawn.vel > 100
            drawn_pitch = drawn.pitch
            QTest.keyClick(editor.canvas, Qt.Key_Up)
            assert editor.canvas.notes[-1].pitch == drawn_pitch + 1
            duplicate_count = len(editor.canvas.notes)
            QTest.keyClick(editor.canvas, Qt.Key_D, Qt.ControlModifier)
            assert len(editor.canvas.notes) == duplicate_count + 1
            QTest.keyClick(editor.canvas, Qt.Key_B)
            assert not editor.draw_mode_button.isChecked()
            fake.loaded_from = None
            keyboard_y = editor.canvas.RULER_H + (editor.canvas.pitch_top - 60) * editor.canvas.ROW_H + 5
            QTest.mouseClick(editor.canvas, Qt.LeftButton, pos=QPoint(20, round(keyboard_y)))
            assert editor.audition_pending
            assert fake.loaded_from == 0.0
            assert fake.loaded_pitch == 60
            editor._stop_note_audition()
            next_keyboard_y = keyboard_y - editor.canvas.ROW_H * 2
            cleared_before_gliss = fake.clear_count
            QTest.mousePress(
                editor.canvas, Qt.LeftButton,
                pos=QPoint(20, round(keyboard_y)),
            )
            assert editor.canvas.piano_key_dragging
            assert editor.canvas.piano_pressed_pitch == 60
            QTest.mouseMove(editor.canvas, pos=QPoint(20, round(next_keyboard_y)))
            app.processEvents()
            assert editor.canvas.piano_pressed_pitch == 62
            assert fake.loaded_pitch == 62
            assert fake.clear_count == cleared_before_gliss
            QTest.mouseRelease(
                editor.canvas, Qt.LeftButton,
                pos=QPoint(20, round(next_keyboard_y)),
            )
            assert not editor.canvas.piano_key_dragging
            assert editor.canvas.piano_pressed_pitch is None
            editor._stop_note_audition()
            note_rect = editor.canvas.note_rect(editor.canvas.notes[0])
            QTest.mouseClick(
                editor.canvas, Qt.LeftButton,
                pos=QPoint(round(note_rect.center().x()), round(note_rect.center().y())),
            )
            assert editor.audition_pending
            assert fake.loaded_from == 0.0
            fake.ready = True
            editor._poll_note_audition()
            assert fake.played
            assert not editor.audition_pending
            editor._stop_note_audition()
            fake.ready = False
            fake.played = False
            editor.play_draft()
            assert editor.draft_playback_state == "loading"
            assert editor.canvas.preload_state == "loading"
            fake.status.preload_loaded = 2
            fake.status.preload_progress = 0.5
            editor.poll_draft_playback()
            assert editor.canvas.preload_progress == 0.5
            editor.seek_draft(750.0)
            fake.ready = True
            editor.poll_draft_playback()
            assert fake.committed_from == 750.0
            assert fake.played
            assert editor.canvas.preload_state == "ready"
            editor._notes_changed()
            assert editor.draft_playback_state == "stopped"
            assert editor.canvas.preload_state == "idle"
            editor.close()
            window.close()
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
