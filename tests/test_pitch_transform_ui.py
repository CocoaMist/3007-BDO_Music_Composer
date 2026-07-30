from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PitchTransformUiTests(unittest.TestCase):
    def test_track_octave_is_undoable_persisted_and_used_by_preview(self) -> None:
        source = textwrap.dedent(
            """
            import json

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QDialog

            import pyside_bdo_gui as gui

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window._create_new_project("Pitch Plan")
            track = window.tracks[0]
            track.notes = [gui.Note(60, 90, 0.0, 250.0, 0)]
            assert window.transpose == -8

            def accept_dialog():
                dialog = app.activeModalWidget()
                assert isinstance(dialog, gui.TrackPitchDialog)
                index = dialog.octave_offset.findData(12)
                assert index >= 0
                dialog.octave_offset.setCurrentIndex(index)
                dialog.accept()

            QTimer.singleShot(0, accept_dialog)
            window._show_track_pitch_dialog(track)
            assert window._effective_track_transpose(track) == 4
            projected = window._project_tracks_for_preview([track])
            assert projected[0].notes[0].pitch == 64
            assert track.notes[0].pitch == 60
            assert window.timeline.pitch_transform_plan == window._pitch_transform_plan
            assert window._wait_for_autosave_idle()

            project_path = window.autosave_project_dir / "project.json"
            payload = json.loads(project_path.read_text(encoding="utf-8"))
            assert payload["schema_version"] == gui.CURRENT_PROJECT_SCHEMA
            assert payload["pitch_transform"]["global_semitones"] == -8
            assert payload["pitch_transform"]["track_overrides"] == [{
                "track_id": track.track_id,
                "semitones": 12,
                "mode": "octave",
                "provenance": "user",
            }]

            snapshot = window.project_commands.undo(window._project_snapshot())
            assert snapshot is not None
            window._restore_project_snapshot(snapshot, "project undo")
            restored = window.tracks[0]
            assert window._effective_track_transpose(restored) == -8
            assert window._pitch_transform_plan.override_for(restored.track_id) is None

            window.close()
            app.processEvents()
            app.quit()
            """
        )
        with tempfile.TemporaryDirectory() as folder_name:
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "user-data")
            completed = subprocess.run(
                [sys.executable, "-c", source],
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
