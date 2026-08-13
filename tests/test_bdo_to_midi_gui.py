from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


ROOT = Path(__file__).resolve().parents[1]


class BdoToMidiGuiTests(unittest.TestCase):
    def test_window_is_standalone_and_verifies_by_default(self) -> None:
        script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tools"))
from PySide6.QtWidgets import QApplication
from bdo_to_midi_gui import BdoToMidiWindow
application = QApplication([])
window = BdoToMidiWindow()
assert window.windowTitle() == "BDO → MIDI 临时转换工具"
assert window.verify_check.isChecked()
assert window.input_edit.text() == ""
window.close()
"""
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
