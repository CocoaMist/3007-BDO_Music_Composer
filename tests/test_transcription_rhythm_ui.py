from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionRhythmUiTests(unittest.TestCase):
    def test_explicit_button_emits_once_and_renders_sidecar_state(self) -> None:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    from PySide6.QtTest import QTest
                    from PySide6.QtCore import Qt
                    from PySide6.QtWidgets import QApplication

                    from bdo_music_composer.ui.transcription.transcription_editor_qt import TranscriptionEditorPanel

                    app = QApplication([])
                    panel = TranscriptionEditorPanel()
                    requests = []
                    panel.rhythm_diagnostic_requested.connect(
                        lambda: requests.append("requested")
                    )
                    assert not panel.rhythm_diagnostic_button.isEnabled()
                    panel.set_action_state(
                        write_enabled=False,
                        candidate_count=2,
                    )
                    assert panel.rhythm_diagnostic_button.isEnabled()
                    QTest.mouseClick(
                        panel.rhythm_diagnostic_button,
                        Qt.LeftButton,
                    )
                    assert requests == ["requested"]
                    panel.set_rhythm_diagnostic_state(busy=True)
                    assert not panel.rhythm_diagnostic_button.isEnabled()
                    panel.set_rhythm_diagnostic_state(
                        busy=False,
                        proposal_count=3,
                    )
                    assert "3" in panel.rhythm_diagnostic_button.text()
                    panel.close()
                    app.processEvents()
                    app.quit()
                    """
                ),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
