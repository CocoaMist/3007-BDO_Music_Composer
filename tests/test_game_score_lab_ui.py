from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GameScoreLabUiTests(unittest.TestCase):
    def test_conversion_issues_are_listed_and_can_focus_notes(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.export.bdo_validation import ValidationIssue
            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import ConversionCheckDialog, MidiToBdoWindow, Note, TrackState

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
            dialog = ConversionCheckDialog(window)
            dialog.show()
            app.processEvents()
            assert dialog.issue_list.count() >= 1
            assert dialog.issue_list.item(0).data(256) is not None
            translations.set_language("en_US")
            assert dialog.status_card.text().startswith("Status\\n")
            assert dialog.issue_list.item(0).text().startswith("[Action required] Track 7")
            translations.set_language("ja_JP")
            assert dialog.status_card.text().startswith("状態\\n")
            translations.set_language("ko_KR")
            assert dialog.status_card.text().startswith("상태\\n")
            dialog.close()
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
