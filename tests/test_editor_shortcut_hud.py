from __future__ import annotations

import inspect
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EditorShortcutHudTests(unittest.TestCase):
    def test_registry_resolves_every_canvas_key_without_conflicts(self) -> None:
        from PySide6.QtCore import Qt

        from bdo_music_composer.ui.editor.editor_shortcuts import (
            CANVAS_SCOPE,
            EDITOR_SHORTCUT_SPECS,
            GLOBAL_SCOPE,
            resolve_editor_key_command,
        )

        canvas_specs = tuple(
            spec
            for spec in EDITOR_SHORTCUT_SPECS
            if spec.scope == CANVAS_SCOPE
        )
        combinations = [
            (key, spec.modifiers)
            for spec in canvas_specs
            for key in spec.keys
        ]
        self.assertEqual(len(combinations), len(set(combinations)))
        self.assertEqual(
            [spec.command for spec in EDITOR_SHORTCUT_SPECS if spec.scope == GLOBAL_SCOPE],
            ["show_shortcuts"],
        )
        for spec in canvas_specs:
            for key in spec.keys:
                with self.subTest(command=spec.command, key=key):
                    self.assertEqual(
                        resolve_editor_key_command(
                            key,
                            spec.modifiers,
                            has_selection=True,
                        ),
                        spec.command,
                    )
                    if spec.requires_selection:
                        self.assertIsNone(
                            resolve_editor_key_command(
                                key,
                                spec.modifiers,
                                has_selection=False,
                            )
                        )

    def test_hud_tracks_real_editor_context_without_blocking_the_canvas(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.editor.editor_shortcut_hud import (
                EditorShortcutHelpDialog,
                EditorShortcutHud,
            )
            from bdo_music_composer.ui.editor.editor_shortcuts import (
                EDITOR_GESTURE_SPECS,
                EDITOR_SHORTCUT_SPECS,
            )
            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            translations = install_localizer(app, "zh_CN")
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [Note(60, 96, 0.0, 400.0, 0)],
                0,
                False,
                "lead",
                0x0B,
            )
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(920, 680)
            editor.show()
            app.processEvents()

            hud = editor.shortcut_hud
            assert isinstance(hud, EditorShortcutHud)
            assert hud.parent() is editor.canvas
            assert not hud.user_visible
            assert not hud.isVisible()
            assert not editor.shortcut_hud_button.isChecked()
            editor.shortcut_hud_button.click()
            app.processEvents()
            assert hud.user_visible
            assert hud.isVisible()
            assert hud.testAttribute(Qt.WA_TransparentForMouseEvents)
            assert hud.focusPolicy() == Qt.NoFocus
            assert hud.property("visualWeight") == "quiet"
            assert hud.property("surfaceTreatment") == "translucent"
            assert hud.height() <= 136

            def visible_copy() -> list[tuple[str, str]]:
                rows = [row for row in hud.shortcut_rows if row.isVisible()]
                assert 3 <= len(rows) <= 4
                previous_bottom = -1
                copy = []
                for row in rows:
                    assert row.y() > previous_bottom
                    previous_bottom = row.geometry().bottom()
                    assert row.key_label.text()
                    assert row.action_label.text()
                    assert (
                        row.action_label.fontMetrics().horizontalAdvance(
                            row.action_label.text()
                        )
                        <= row.action_label.width() + 2
                    ), (
                        row.action_label.text(),
                        row.action_label.fontMetrics().horizontalAdvance(
                            row.action_label.text()
                        ),
                        row.action_label.width(),
                        hud.width(),
                    )
                    copy.append(
                        (
                            row.key_label.text(),
                            row.action_label.text(),
                        )
                    )
                return copy

            def assert_anchored() -> None:
                assert hud.x() >= editor.canvas.KEY_W + 10
                assert hud.y() >= editor.canvas.RULER_H
                assert hud.geometry().right() < editor.canvas.width()
                assert hud.geometry().bottom() < editor.canvas.height()
                assert hud.height() <= 136

            assert_anchored()
            assert hud.context == EditorShortcutHud.SELECT_CONTEXT
            assert visible_copy() == [
                ("双击", "新建音符"),
                ("B", "切换绘制模式"),
                ("Ctrl+拖动", "复制音符"),
                ("Space", "播放或暂停"),
            ]

            editor.canvas.selected = {0}
            editor.canvas.selection_changed.emit()
            app.processEvents()
            assert hud.context == EditorShortcutHud.SELECTION_CONTEXT
            assert visible_copy() == [
                ("←/→ · ↑/↓", "时间 · 音高"),
                ("Shift+方向键", "时值 · 八度"),
                ("Ctrl+↑/↓ · Ctrl+D", "力度 · 复制"),
                ("Del / 右键", "删除（可撤销）"),
            ]

            editor.pitch_edit.setFocus()
            app.processEvents()
            assert not hud.shortcut_active
            assert not hud.property("shortcutActive")
            assert "点击画布启用" in hud.mode_label.text()
            before = list(editor.canvas.notes)
            QTest.keyClick(editor.pitch_edit, Qt.Key_Delete)
            QTest.keyClick(editor.pitch_edit, Qt.Key_D, Qt.ControlModifier)
            QTest.keyClick(editor.pitch_edit, Qt.Key_B)
            app.processEvents()
            assert editor.canvas.notes == before
            assert not editor.draw_mode_button.isChecked()

            editor.canvas.setFocus()
            app.processEvents()
            assert hud.shortcut_active
            assert hud.property("shortcutActive")
            assert "点击画布启用" not in hud.mode_label.text()
            QTest.keyClick(editor.canvas, Qt.Key_B)
            app.processEvents()
            assert editor.draw_mode_button.isChecked()
            assert hud.context == EditorShortcutHud.DRAW_CONTEXT
            assert visible_copy() == [
                ("拖动", "设置长度和力度"),
                ("Alt", "临时取消吸附"),
                ("B / Esc", "退出绘制模式"),
                ("F1", "打开完整快捷键"),
            ]

            QTest.keyClick(editor.canvas, Qt.Key_Escape)
            app.processEvents()
            assert not editor.draw_mode_button.isChecked()
            assert hud.context == EditorShortcutHud.SELECTION_CONTEXT

            contexts = (
                EditorShortcutHud.SELECT_CONTEXT,
                EditorShortcutHud.SELECTION_CONTEXT,
                EditorShortcutHud.DRAW_CONTEXT,
            )
            for language in ("zh_TW", "en_US", "ja_JP", "ko_KR", "zh_CN"):
                translations.set_language(language)
                app.processEvents()
                for context in contexts:
                    hud.set_context(context)
                    app.processEvents()
                    assert hud.mode_label.text()
                    assert hud.accessibleName()
                    assert hud.accessibleDescription()
                    assert hud.width() <= 390
                    visible_copy()
                    assert_anchored()

            editor.shortcut_help_button.click()
            app.processEvents()
            help_dialog = editor._shortcut_help_dialog
            assert isinstance(help_dialog, EditorShortcutHelpDialog)
            assert help_dialog.isVisible()
            assert len(help_dialog.shortcut_rows) == (
                len(EDITOR_SHORTCUT_SPECS) + len(EDITOR_GESTURE_SPECS)
            )
            help_copy = [
                (key.text(), action.text())
                for key, action in help_dialog.shortcut_rows
            ]
            assert any(
                "右键" in key and "可撤销" in action
                for key, action in help_copy
            )
            assert any("Ctrl+Shift+↑" in key for key, _action in help_copy)
            help_dialog.close()
            editor.activateWindow()
            editor.pitch_edit.setFocus()
            app.processEvents()
            QTest.keyClick(editor.pitch_edit, Qt.Key_F1)
            app.processEvents()
            assert editor._shortcut_help_dialog.isVisible()
            editor._shortcut_help_dialog.close()

            editor.resize(1440, 900)
            app.processEvents()
            assert_anchored()

            editor.close()
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
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_registered_shortcuts_execute_the_documented_note_edits(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            install_localizer(app, "zh_CN")
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [Note(60, 80, 500.0, 400.0, 0)],
                0,
                False,
                "lead",
                0x0B,
            )
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.resize(920, 680)
            editor.show()
            app.processEvents()
            canvas = editor.canvas
            base = Note(60, 80, 500.0, 400.0, 0)

            def reset(notes=None, selected=None):
                canvas.notes = list(notes if notes is not None else [base])
                canvas.selected = set(selected if selected is not None else {0})
                canvas.anchor_index = min(canvas.selected) if canvas.selected else None
                canvas.rebuild_note_index()
                canvas.set_edit_cursor(0.0)
                editor.undo_stack.clear()
                editor.redo_stack.clear()
                editor.clipboard = []
                editor.refresh_fields()
                canvas.setFocus()
                app.processEvents()

            def press(key, modifiers=Qt.NoModifier):
                QTest.keyClick(canvas, key, modifiers)
                app.processEvents()

            reset(); press(Qt.Key_Up)
            assert canvas.notes[0].pitch == 61
            reset(); press(Qt.Key_Up, Qt.ShiftModifier)
            assert canvas.notes[0].pitch == 72
            reset(); press(Qt.Key_Right)
            assert canvas.notes[0].start == base.start + editor.quantize_ms()
            reset(); press(Qt.Key_Right, Qt.AltModifier)
            assert canvas.notes[0].start == base.start + editor.quantize_ms() / 8.0
            reset(); press(Qt.Key_Right, Qt.ShiftModifier)
            assert canvas.notes[0].dur == base.dur + editor.quantize_ms()
            reset(); press(Qt.Key_Right, Qt.AltModifier | Qt.ShiftModifier)
            assert canvas.notes[0].dur == base.dur + editor.quantize_ms() / 8.0
            reset(); press(Qt.Key_Up, Qt.ControlModifier)
            assert canvas.notes[0].vel == 81
            reset(); press(Qt.Key_Up, Qt.ControlModifier | Qt.ShiftModifier)
            assert canvas.notes[0].vel == 88

            reset(); press(Qt.Key_D, Qt.ControlModifier)
            assert len(canvas.notes) == 2 and canvas.selected == {1}
            reset(); press(Qt.Key_C, Qt.ControlModifier)
            canvas.set_edit_cursor(1500.0)
            press(Qt.Key_V, Qt.ControlModifier)
            assert len(canvas.notes) == 2 and canvas.notes[1].start == 1500.0
            reset(); press(Qt.Key_X, Qt.ControlModifier)
            assert canvas.notes == [] and editor.clipboard

            for delete_key in (Qt.Key_Delete, Qt.Key_Backspace):
                reset(); press(delete_key)
                assert canvas.notes == []
                press(Qt.Key_Z, Qt.ControlModifier)
                assert canvas.notes == [base]
                press(Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
                assert canvas.notes == []

            reset(); press(Qt.Key_Delete)
            press(Qt.Key_Z, Qt.ControlModifier)
            press(Qt.Key_Y, Qt.ControlModifier)
            assert canvas.notes == []

            second = base._replace(pitch=64, start=1000.0)
            reset([base, second], {0})
            press(Qt.Key_A, Qt.ControlModifier)
            assert canvas.selected == {0, 1}

            reset(); press(Qt.Key_B)
            assert editor.draw_mode_button.isChecked()
            press(Qt.Key_Escape)
            assert not editor.draw_mode_button.isChecked()

            playback_calls = []
            editor.toggle_draft_playback = lambda: playback_calls.append("toggle")
            reset(); press(Qt.Key_Space)
            assert playback_calls == ["toggle"]

            reset([base, second], {0})
            editor.pitch_edit.setFocus()
            app.processEvents()
            QTest.keyClick(editor.pitch_edit, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(editor.pitch_edit, Qt.Key_Space)
            app.processEvents()
            assert canvas.selected == {0}
            assert playback_calls == ["toggle"]

            editor.close()
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
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_hud_surface_contract_stays_translucent(self) -> None:
        from bdo_music_composer.ui.theme.main_window_style import (
            MainWindowStyleMixin,
        )

        style_source = inspect.getsource(MainWindowStyleMixin)
        match = re.search(
            r"QFrame#EditorShortcutHud\s*\{"
            r"[^}]*background:\s*rgba\([^;]*,\s*(\d+)\);",
            style_source,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertLess(int(match.group(1)), 128)
        self.assertRegex(
            style_source,
            r"QFrame#ShortcutHudRow\s*\{[^}]*background:\s*transparent;",
        )


if __name__ == "__main__":
    unittest.main()
