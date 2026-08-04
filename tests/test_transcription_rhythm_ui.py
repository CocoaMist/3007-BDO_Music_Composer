from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace
import unittest

from bdo_music_composer.ui.transcription_rhythm_diagnostic import (
    TranscriptionRhythmDiagnosticMixin,
)


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionRhythmUiTests(unittest.TestCase):
    def test_diagnostic_start_reads_profile_from_active_editor(self) -> None:
        class Runner:
            busy = False

            def __init__(self) -> None:
                self.request = None

            def start_diagnostic(self, **request) -> bool:
                self.request = request
                return True

        host = object.__new__(TranscriptionRhythmDiagnosticMixin)
        host.transcription_session = SimpleNamespace(
            state=SimpleNamespace(cache_key="evidence-key"),
            candidates=(SimpleNamespace(start=0.0),),
        )
        host.workspace_transcription_worker = None
        host.transcription_rhythm_runner = Runner()
        host.transcription_rhythm_sidecar = object()
        host.active_transcription_editor = SimpleNamespace(
            transcription_panel=SimpleNamespace(
                rhythm_alignment_profile="strict_1_64"
            )
        )
        host.bpm_override = 0
        host.bpm = 120
        host.beat_origin_ms = 0.0
        host.reference_audio_offset_ms = 0.0
        host.time_sig = 4
        statuses = []
        host._set_transcription_status = statuses.append
        host.show_toast = lambda *_args, **_kwargs: None

        host._start_transcription_rhythm_diagnostic()

        request = host.transcription_rhythm_runner.request
        self.assertIsNotNone(request)
        self.assertEqual(
            request["alignment_config"].profile,
            "strict_1_64",
        )
        self.assertIsNone(host.transcription_rhythm_sidecar)
        self.assertTrue(statuses)

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
