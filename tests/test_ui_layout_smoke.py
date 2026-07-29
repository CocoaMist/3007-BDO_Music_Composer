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
            from PySide6.QtCore import QPoint, Qt, QTimer
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFrame, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QStackedWidget, QStyleOptionViewItem, QTextBrowser, QWidget
            from pyside_bdo_gui import (
                EnsembleCapacityBadge, GlobalToast, HOME_INSTRUMENT_IDS_ROLE, HomeEntry,
                HomeEntryDelegate, MidiNoteEditorDialog, MidiToBdoWindow, Note,
                MasterEffectsDialog, ReferenceAudioController,
                SettingsDialog, StartupSplash, TrackFxDialog, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window.resize(window.minimumSize())
            window.show()
            app.processEvents()
            assert app.property("bdoFixedDarkTheme") is True
            assert window._system_uses_dark_theme()
            main_toolbar = window.findChild(QFrame, "Toolbar")
            assert main_toolbar is not None
            assert 50 <= main_toolbar.height() <= 60
            ensemble_badge = window.findChild(
                EnsembleCapacityBadge, "EnsembleCapacityBadge"
            )
            assert ensemble_badge is not None
            assert ensemble_badge.player_count == 0
            assert not ensemble_badge.is_over_limit
            assert ensemble_badge.size().width() == 36
            assert ensemble_badge.size().height() == 36
            assert not ensemble_badge._icon.isNull()
            assert ensemble_badge.toolTip()
            page_switch_paint_states = []
            window.page_stack.currentChanged.connect(
                lambda _index: page_switch_paint_states.append(
                    window.updatesEnabled()
                )
            )
            window._show_workspace()
            app.processEvents()
            assert window.toolbar_master_effects_btn.isVisible()
            workspace_anchor_positions = (
                ensemble_badge.mapTo(window, QPoint(0, 0)).x(),
                window.toolbar_settings_btn.mapTo(window, QPoint(0, 0)).x(),
                window.convert_button.mapTo(window, QPoint(0, 0)).x(),
            )
            timeline_controls = window.findChild(
                QFrame, "TimelineControlBar"
            )
            assert timeline_controls is not None
            assert 47 <= timeline_controls.height() <= 53
            assert window.timeline._lane_height() == 68
            window._show_home()
            app.processEvents()
            assert not window.toolbar_master_effects_btn.isVisible()
            assert window.project_toolbar_group.isVisible()
            assert not window.convert_button.isEnabled()
            assert workspace_anchor_positions == (
                ensemble_badge.mapTo(window, QPoint(0, 0)).x(),
                window.toolbar_settings_btn.mapTo(window, QPoint(0, 0)).x(),
                window.convert_button.mapTo(window, QPoint(0, 0)).x(),
            )
            assert page_switch_paint_states
            assert not any(page_switch_paint_states)

            home_shell = window.findChild(QFrame, "HomeShell")
            home_stack = window.findChild(QStackedWidget, "HomeLibraryStack")
            home_actions = window.findChildren(QPushButton, "HomeQuickAction")
            assert home_shell is not None and home_stack is not None
            assert window.home_backdrop is home_shell
            assert window.home_backdrop.has_artwork
            assert not window.home_backdrop._cover.isNull()
            assert len(home_actions) == 3
            assert home_stack.currentIndex() == 0
            assert window.home_project_nav.isChecked()
            assert not window.home_game_nav.isChecked()
            assert window.project_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert window.game_score_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert window.project_list.height() >= 200
            window.project_list.clear()
            window._add_home_entry(
                window.project_list,
                HomeEntry(
                    "project", "Instrument probe",
                    __import__("pathlib").Path("C:/virtual/project.json"),
                    "2026-07-29 12:00", 1.0,
                    instrument_ids=(0x0B, 0x11),
                ),
            )
            instrument_probe = window.project_list.item(0)
            assert instrument_probe.data(HOME_INSTRUMENT_IDS_ROLE) == (0x0B, 0x11)
            assert instrument_probe.data(Qt.UserRole)["required_players"] == 2
            app.processEvents()
            assert ensemble_badge.player_count == 2
            assert isinstance(window.project_list.itemDelegate(), HomeEntryDelegate)
            row_option = QStyleOptionViewItem()
            row_option.initFrom(window.project_list)
            row_hint = window.project_list.itemDelegate().sizeHint(
                row_option, window.project_list.model().index(0, 0)
            )
            assert row_hint.height() >= 56
            assert "C:/virtual" not in instrument_probe.toolTip()
            assert instrument_probe.toolTip().count("\\n") <= 1
            window._add_home_entry(
                window.project_list,
                HomeEntry(
                    "project",
                    "Long project title " * 18,
                    __import__("pathlib").Path("C:/virtual/long/project.json"),
                    "2026-07-29 12:01", 2.0,
                    instrument_ids=(0x0B,),
                ),
            )
            long_item = window.project_list.item(window.project_list.count() - 1)
            long_hint = window.project_list.itemDelegate().sizeHint(
                row_option, window.project_list.indexFromItem(long_item)
            )
            assert long_hint.height() > row_hint.height()
            window.project_list.setCurrentRow(1)
            app.processEvents()
            assert ensemble_badge.player_count == 1
            window.project_list.setCurrentRow(0)
            app.processEvents()
            assert ensemble_badge.player_count == 2
            assert window.home_instrument_art.pixmap_for(0x0B) is not None
            if not window.project_open_button.isEnabled():
                probe_item = QListWidgetItem("Layout probe")
                probe_item.setData(Qt.UserRole, {
                    "kind": "project",
                    "path": "C:/virtual/project.json",
                    "label": "Layout probe",
                })
                window.project_list.addItem(probe_item)
                window.project_list.setCurrentItem(probe_item)
                app.processEvents()
            assert window.project_open_button.isEnabled()
            window.home_search.setText("__no_visible_home_match__")
            app.processEvents()
            assert not window.project_open_button.isEnabled()
            window.home_search.clear()
            app.processEvents()
            assert window.project_open_button.isEnabled()
            home_rect = window.home_page.contentsRect()
            shell_top_left = home_shell.mapTo(window.home_page, QPoint(0, 0))
            shell_rect = home_shell.rect().translated(shell_top_left)
            assert shell_rect.left() == home_rect.left()
            assert shell_rect.right() == home_rect.right()
            assert shell_rect.top() == home_rect.top()
            assert shell_rect.bottom() == home_rect.bottom()
            assert window.home_sidebar.geometry().topLeft() == QPoint(0, 0)
            assert window.home_sidebar.height() == home_shell.height()
            assert 560 <= window.home_sidebar.width() <= 620
            assert window.home_sidebar.width() < home_shell.width()
            action_rects = [
                action.rect().translated(action.mapTo(window.home_page, QPoint(0, 0)))
                for action in home_actions
            ]
            assert all(home_rect.contains(rect) for rect in action_rects)
            assert not any(
                action_rects[left].intersects(action_rects[right])
                for left in range(len(action_rects))
                for right in range(left + 1, len(action_rects))
            )
            window.home_game_nav.click()
            app.processEvents()
            assert home_stack.currentIndex() == 1
            assert window.home_game_nav.isChecked()
            window.home_project_nav.click()
            app.processEvents()
            assert home_stack.currentIndex() == 0

            splash = StartupSplash()
            splash.show()
            app.processEvents()
            assert splash.size().width() == 470
            assert splash.size().height() == 734
            splash_margins = splash.layout().contentsMargins()
            assert splash_margins.left() == splash_margins.right() == 0
            assert splash_margins.top() == splash_margins.bottom() == 0
            assert splash.artwork.size() == splash.size()
            assert splash.property("uiSurface") == "startup"
            splash_card = splash.findChild(QFrame, "StartupSplashCard")
            assert splash_card is not None
            assert splash_card.property("uiRole") == "startupCanvas"
            assert splash.windowFlags() & Qt.WindowStaysOnTopHint
            assert splash.MINIMUM_VISIBLE_MS >= 1400
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
            QTest.qWait(splash.FADE_OUT_MS // 2)
            app.processEvents()
            assert splash.isVisible()
            assert 0.0 < splash.opacity.opacity() < 1.0
            QTest.qWait(splash.FADE_OUT_MS)
            app.processEvents()
            assert splash.isHidden()

            toast = window.show_toast(
                "测试提示", kind="warning", duration_ms=80
            )
            app.processEvents()
            assert isinstance(toast, GlobalToast)
            assert toast.isVisible()
            assert toast.message.text() == "测试提示"
            assert toast.property("toastKind") == "warning"
            assert toast.marker.text() == "!"
            toast_margins = toast.layout().contentsMargins()
            assert toast_margins.top() == toast_margins.bottom() == 8
            assert toast.height() <= 44
            assert toast.y() == main_toolbar.geometry().bottom() + 9
            assert 0 <= toast.x() <= window.width() - toast.width()
            QTest.qWait(190)
            assert toast.opacity.opacity() > 0.9
            QTest.qWait(380)
            app.processEvents()
            assert toast.isHidden()

            inspector = window.findChild(QFrame, "Inspector")
            assert inspector is None
            performance_strip = window.findChild(QFrame, "PerformanceStrip")
            assert performance_strip is not None
            assert window.workspace_page.layout().count() == 2
            assert window.findChild(QFrame, "InfoBar") is None
            assert window.status_label.isHidden()
            assert window.inspector_text.isHidden()
            assert not hasattr(window, "selected_volume")
            assert not hasattr(window, "out_dir")
            assert not hasattr(window, "open_output_button")
            assert not hasattr(window, "install_check")
            assert window.track_actions_button.menu() is not None
            assert len(window.track_actions_button.menu().actions()) == 4
            assert not window.transcription_tools_slot.isHidden()
            assert not window.transcription_entry_button.isHidden()
            assert not hasattr(window, "delete_track_button")
            reference = window.reference_audio
            assert isinstance(reference, ReferenceAudioController)
            assert reference.parent() is window
            assert window.timeline.reference_audio is reference
            assert not reference.audio_path
            assert not reference.is_playing
            assert reference.volume_percent == 50

            marnian = TrackState(99, [], 0, False, "marnian", 0x14)
            fx_dialog = TrackFxDialog(window, marnian)
            assert not hasattr(fx_dialog, "articulation")
            assert fx_dialog.marnian_mode is not None
            fx_dialog.close()

            settings = SettingsDialog(window)
            assert settings.game_art_button is not None
            assert settings.game_art_worker is None
            assert settings.output_dir.objectName() == "OutputDirectoryEdit"
            assert settings.output_dir.text() == window.output_dir_path
            assert settings.findChild(QWidget, "OpenOutputDirectoryButton") is not None
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
            settings_header = settings.findChild(QFrame, "SettingsHeader")
            assert settings_header is not None
            assert settings_header.property("uiRole") == "dialogHeader"
            assert settings.settings_footer.property("uiRole") == "dialogFooter"
            assert settings.settings_buttons.property("uiRole") == "dialogButtonRow"
            settings_footer_margins = settings.settings_footer.layout().contentsMargins()
            assert settings_footer_margins.left() == settings_footer_margins.right() == 24
            assert settings_footer_margins.top() == settings_footer_margins.bottom() == 10
            settings_sections = settings.findChildren(QFrame, "SettingsSection")
            assert settings_sections
            assert all(
                section.property("uiRole") == "settingsSection"
                for section in settings_sections
            )
            assert [nav.item(index).text() for index in range(nav.count())] == [
                "通用与导出", "MIDI 与力度", "音源与外观"
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

            thanks_checked = {"value": False}
            def inspect_thanks_dialog():
                thanks = app.activeModalWidget()
                assert isinstance(thanks, QDialog)
                assert thanks.objectName() == "ThanksDialog"
                thanks_header = thanks.findChild(QFrame, "ThanksHeader")
                thanks_body = thanks.findChild(QFrame, "ThanksTextPanel")
                thanks_text = thanks.findChild(QTextBrowser, "ThanksText")
                thanks_buttons = thanks.findChild(QDialogButtonBox, "ThanksButtons")
                thanks_footer = thanks.findChild(QFrame, "ThanksFooter")
                assert thanks_header is not None and thanks_body is not None
                assert thanks_text is not None and thanks_buttons is not None
                assert thanks_footer is not None
                assert thanks_header.property("uiRole") == "dialogHeader"
                assert thanks_body.property("uiRole") == "dialogBody"
                assert thanks_buttons.property("uiRole") == "dialogButtonRow"
                thanks_footer_margins = thanks_footer.layout().contentsMargins()
                assert thanks_footer_margins.left() == thanks_footer_margins.right() == 24
                assert thanks_footer_margins.top() == thanks_footer_margins.bottom() == 10
                thanks_checked["value"] = True
                thanks.accept()
            QTimer.singleShot(0, inspect_thanks_dialog)
            window._show_acknowledgements()
            assert thanks_checked["value"]

            master_effects = MasterEffectsDialog(
                window, window._current_master_effects()
            )
            master_effects.resize(master_effects.minimumSize())
            master_effects.show()
            app.processEvents()
            assert master_effects.objectName() == "MasterEffectsDialog"
            assert master_effects.minimumSizeHint().width() <= master_effects.width()
            assert master_effects.findChild(QWidget, "MasterReverbTime") is not None
            assert master_effects.findChild(QWidget, "MasterDelayFeedback") is not None
            assert master_effects.findChild(QWidget, "MasterChorusFeedback") is not None
            master_effects.close()

            track = TrackState(1, [Note(60, 96, 0, 400, 0)], 0, False, "lead", 0x0B)
            track.color = "#b77bd3"
            window.tracks = [track]
            window._show_workspace()
            window._on_track_changed()
            assert ensemble_badge.player_count == 1
            window._switch_main_page(window.home_page, home=True)
            assert ensemble_badge.player_count == 2
            window._show_workspace()
            assert ensemble_badge.player_count == 1
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
            assert 40 <= toolbar.height() <= 45
            workspace = editor.findChild(QFrame, "EditorWorkspace")
            assert workspace is not None
            workspace_left = workspace.mapTo(editor, QPoint(0, 0)).x()
            assert workspace_left == editor.contentsRect().left()
            assert workspace_left + workspace.width() == editor.contentsRect().right() + 1
            assert toolbar.mapTo(editor, QPoint(0, 0)).x() > workspace_left
            assert toolbar.isAncestorOf(editor.apply_button)
            assert toolbar.isAncestorOf(editor.cancel_button)
            assert toolbar.isAncestorOf(editor.confirm_button)
            assert editor.apply_button.property("kind") == "secondary"
            assert not hasattr(editor, "playback_timeline")
            top_inspector = editor.findChild(QFrame, "NoteInspectorTop")
            assert top_inspector is not None and top_inspector.isVisible()
            assert top_inspector.height() == 38
            assert top_inspector.isAncestorOf(editor.velocity_toggle)
            assert editor.canvas.ROW_H == 24
            assert editor.canvas.KEY_W == 86
            assert editor.canvas.BLACK_KEY_X == 8
            assert editor.canvas.BLACK_KEY_W == 48
            assert editor.canvas._editable_note_base_color().name().lower() == track.color.lower()
            inspector_height = top_inspector.height()
            assert editor.note_mode_button.height() == editor.articulation_mode_button.height() == editor.grid_mode_button.height()
            assert editor.note_controls.isVisible()
            assert not editor.articulation_controls.isVisible()
            assert not editor.grid_controls.isVisible()
            assert editor.quantize_quick.isVisible()
            assert editor.quantize_combo.currentText() == "1/4"
            assert editor.quantize_ms() == editor.canvas.beat_ms
            assert editor.ghost_opacity_slider.value() == 24
            assert editor.canvas._ghost_opacity == 0.24
            assert editor.pitch_scroll.width() == 12
            assert editor.time_scroll.height() == 12
            grid_rect = editor.canvas.grid_rect()
            assert grid_rect.left() == editor.canvas.KEY_W
            assert grid_rect.right() == editor.canvas.width()
            assert editor.canvas.note_rect(editor.canvas.notes[0]).left() == editor.canvas.x_at_time(
                editor.canvas.notes[0].start
            )
            assert workspace.geometry().top() <= 100
            scroll_corner = editor.findChild(QWidget, "PianoScrollCorner")
            assert scroll_corner is not None and scroll_corner.size().width() == 12
            editor.articulation_mode_button.click()
            app.processEvents()
            assert top_inspector.height() == inspector_height
            assert editor.articulation_controls.isVisible()
            assert not editor.note_controls.isVisible()
            editor.canvas.selected = {0}
            editor.refresh_fields()
            # Keep this broad layout smoke independent of the real asynchronous
            # audio worker.  Dedicated editor/audio tests cover articulation
            # audition with a controlled engine below.
            editor.note_preview_box.setChecked(False)
            editor.articulation_buttons[3].click()
            assert editor.canvas.notes[0].ntype == 3
            editor.note_preview_box.setChecked(True)
            editor.grid_mode_button.click()
            app.processEvents()
            assert top_inspector.height() == inspector_height
            assert editor.grid_controls.isVisible()
            assert [
                editor.quantize_combo.itemText(index)
                for index in range(editor.quantize_combo.count())
            ] == ["1/4", "1/8", "1/16", "1/32", "1/64"]
            editor.quantize_combo.setCurrentIndex(0)
            app.processEvents()
            assert editor.quantize_ms() == editor.canvas.beat_ms
            editor.quantize_combo.setCurrentIndex(2)
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
            assert footer.isAncestorOf(editor.music_volume_slider)
            assert footer.isAncestorOf(editor.transcription_mode_toggle)
            assert editor.music_volume_slider.value() == window.reference_audio.volume_percent == 50
            editor.music_volume_slider.setValue(35)
            assert editor.music_volume_value.text() == "35%"
            assert window.reference_audio.volume_percent == 35
            editor.transcription_mode_toggle.setChecked(True)
            assert editor.transcription_mode_enabled
            assert not editor.velocity_lane.isVisible()
            assert not hasattr(editor, "velocity_curve_button")
            assert editor.velocity_toggle.property("fluentSymbol") == "curve"
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
                    return {
                        "events": 1,
                        "samples": 1,
                        "cache_bytes": 64,
                        "unverified": [],
                        "duration_ms": 1_234.0,
                    }

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
            assert editor.audition_stop_timer.remainingTime() > 1_000
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
