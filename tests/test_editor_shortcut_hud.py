from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EditorShortcutHudTests(unittest.TestCase):
    def test_hud_tracks_real_editor_context_without_blocking_the_canvas(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.editor.editor_shortcut_hud import (
                EditorShortcutHud,
            )
            from i18n import install_localizer
            from pyside_bdo_gui import (
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
            assert hud.isVisible()
            assert hud.testAttribute(Qt.WA_TransparentForMouseEvents)
            assert hud.focusPolicy() == Qt.NoFocus
            assert hud.property("visualWeight") == "quiet"
            assert hud.height() <= 36

            def assert_anchored() -> None:
                assert hud.x() >= editor.canvas.KEY_W + 10
                assert hud.y() >= editor.canvas.RULER_H
                assert hud.geometry().right() < editor.canvas.width()
                assert hud.geometry().bottom() < editor.canvas.height()
                assert hud.height() <= 36

            assert_anchored()
            assert hud.context == EditorShortcutHud.SELECT_CONTEXT
            assert "B" in hud.hint_label.text()
            assert "Space" in hud.hint_label.text()

            editor.canvas.selected = {0}
            editor.canvas.selection_changed.emit()
            app.processEvents()
            assert hud.context == EditorShortcutHud.SELECTION_CONTEXT
            assert "Shift+←→" in hud.hint_label.text()
            assert "Ctrl+↑↓" in hud.hint_label.text()
            assert "Del" in hud.hint_label.text()

            editor.canvas.setFocus()
            QTest.keyClick(editor.canvas, Qt.Key_B)
            app.processEvents()
            assert editor.draw_mode_button.isChecked()
            assert hud.context == EditorShortcutHud.DRAW_CONTEXT
            assert "Alt" in hud.hint_label.text()
            assert "Esc" in hud.hint_label.text()

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
                    assert hud.hint_label.text()
                    assert hud.accessibleName()
                    assert hud.accessibleDescription()
                    assert hud.width() <= 520
                    assert (
                        hud.hint_label.fontMetrics().horizontalAdvance(
                            hud.hint_label.text()
                        )
                        <= hud.hint_label.width() + 2
                    )
                    assert_anchored()

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


if __name__ == "__main__":
    unittest.main()
