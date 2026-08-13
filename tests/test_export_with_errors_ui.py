from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ExportWithErrorsUiTests(unittest.TestCase):
    def test_validation_errors_can_be_confirmed_before_hard_export_checks(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from types import SimpleNamespace
                from PySide6.QtWidgets import QApplication, QMessageBox
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                app = QApplication([])
                window = MidiToBdoWindow()
                issue = SimpleNamespace(severity="error", code="pitch.range")
                window._analyze_conversion = lambda: {
                    "issue_count": 1, "warning_count": 0, "issues": [issue]
                }
                reached = []
                window._build_params = lambda: reached.append(True) or (_ for _ in ()).throw(ValueError("hard check"))
                original_question = QMessageBox.question
                original_warning = QMessageBox.warning
                QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes
                QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
                try:
                    window._convert()
                finally:
                    QMessageBox.question = original_question
                    QMessageBox.warning = original_warning
                assert reached == [True]
                window.close()
                app.processEvents()
                print("export-with-errors-ui-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=90, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("export-with-errors-ui-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
