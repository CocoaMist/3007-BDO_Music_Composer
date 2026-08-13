from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GameScoreLabUiTests(unittest.TestCase):
    def test_export_issue_can_focus_notes_without_conversion_dialog(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.export.bdo_validation import ValidationIssue
            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            translations = install_localizer(app, "zh_CN")
            window = MidiToBdoWindow()
            track = TrackState(7, [Note(47, 80, 0, 200, 0)], 0, False, "lead", 0x0B)
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            captured = []
            window._open_note_editor = lambda item, indices=(): captured.append((item.track_id, indices))
            issue = ValidationIssue(
                "pitch.instrument_unsupported", "error", "outside", 7, (0,), "fixture", "verified"
            )
            window._focus_validation_issue(issue)
            assert window.selected_track is track
            assert captured == [(7, (0,))]
            assert not hasattr(window, "_open_conversion_check")
            assert not hasattr(window, "_open_track_conversion_check")
            translations.set_language("en_US")
            translations.set_language("ja_JP")
            translations.set_language("ko_KR")
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
