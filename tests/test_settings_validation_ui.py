from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class SettingsValidationUiTests(unittest.TestCase):
    def test_invalid_path_keeps_settings_open_and_game_folder_is_configurable(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

            from pyside_bdo_gui import MidiToBdoWindow, SettingsDialog


            app = QApplication.instance() or QApplication([])
            window = MidiToBdoWindow()
            dialog = SettingsDialog(window)
            with tempfile.TemporaryDirectory() as folder_name:
                root = Path(folder_name)
                invalid = root / "not-a-folder"
                invalid.write_text("file", encoding="utf-8")
                dialog.game_music_dir.setText(str(invalid))
                with patch.object(QMessageBox, "warning") as warning:
                    dialog.accept()
                assert dialog.result() != QDialog.Accepted
                assert dialog.settings_nav.currentRow() == 0
                assert dialog.focusWidget() is dialog.game_music_dir
                assert warning.call_count == 1

                wanted = root / "Black Desert" / "music"
                dialog.game_music_dir.setText(str(wanted))
                dialog.output_dir.setText(str(root / "exports"))
                dialog.audio_source.clear()
                dialog.instrument_art_dir.clear()
                dialog.accept()
                assert dialog.result() == QDialog.Accepted
                assert dialog.game_music_dir.text() == str(wanted)

            window.close()
            app.processEvents()
            app.quit()
            """
        )
        with tempfile.TemporaryDirectory() as folder_name:
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "user-data")
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
