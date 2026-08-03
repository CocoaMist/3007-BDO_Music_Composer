from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SettingsLayoutUiTests(unittest.TestCase):
    def test_default_page_fits_and_related_fields_share_a_baseline(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QApplication, QScrollArea

            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, SettingsDialog

            app = QApplication([])
            translations = install_localizer(app, "zh_CN")
            window = MidiToBdoWindow()
            dialog = SettingsDialog(window)
            dialog.show()
            app.processEvents()

            assert dialog.settings_nav.width() == 184
            assert dialog.settings_nav.uniformItemSizes()
            nav_rects = [
                dialog.settings_nav.visualItemRect(dialog.settings_nav.item(i))
                for i in range(dialog.settings_nav.count())
            ]
            assert all(rect.height() == 48 for rect in nav_rects)
            assert all(rect.left() == 0 for rect in nav_rects)

            general_scroll = dialog.findChild(QScrollArea, "SettingsScroll")
            assert general_scroll is not None
            for language in ("zh_CN", "zh_TW", "en_US", "ja_JP", "ko_KR"):
                translations.set_language(language)
                app.processEvents()
                assert general_scroll.horizontalScrollBar().maximum() == 0
                assert general_scroll.verticalScrollBar().maximum() == 0
                assert dialog.owner_load_button.isVisible()
                assert dialog.owner_status.isVisible()

            output_left = dialog.output_dir.mapTo(dialog, QPoint()).x()
            game_left = dialog.game_music_dir.mapTo(dialog, QPoint()).x()
            assert output_left == game_left

            dialog.settings_nav.setCurrentRow(2)
            app.processEvents()
            audio_field_lefts = {
                widget.mapTo(dialog, QPoint()).x()
                for widget in (
                    dialog.preview_mode,
                    dialog.audio_source,
                    dialog.instrument_art_dir,
                )
            }
            assert len(audio_field_lefts) == 1

            dialog.settings_nav.setCurrentRow(1)
            app.processEvents()
            radio_rows = {
                radio.geometry().y()
                for radio in dialog.vel_radios.values()
            }
            assert len(radio_rows) == 2
            assert all(radio.height() == 16 for radio in dialog.vel_radios.values())

            dialog.settings_nav.setCurrentRow(0)
            dialog.resize(dialog.minimumSize())
            app.processEvents()
            assert general_scroll.verticalScrollBar().maximum() > 0
            assert general_scroll.horizontalScrollBar().maximum() == 0
            assert dialog.settings_footer.isVisible()
            assert (
                dialog.settings_footer.geometry().bottom()
                <= dialog.contentsRect().bottom()
            )

            dialog.close()
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
