from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EditorWorkspaceUiTests(unittest.TestCase):
    def test_multiple_editors_focus_playback_and_global_markers(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from unittest.mock import patch
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                app = QApplication([])
                window = MidiToBdoWindow()
                tracks = [
                    TrackState(1, [Note(60, 90, 0, 400, 0)], 0, False, "A", 0x12, color="#55aaff"),
                    TrackState(2, [Note(64, 90, 0, 400, 0)], 0, False, "B", 0x11, color="#cc77aa"),
                ]
                window.tracks = tracks
                window._refresh_tracks()
                window._open_note_editor(tracks[0])
                window._open_note_editor(tracks[1])
                app.processEvents()
                assert set(window._note_editors) == {1, 2}
                first, second = window._note_editors[1], window._note_editors[2]
                first.draft_playback_state = "playing"
                with patch.object(first, "stop_draft") as stop:
                    window._claim_playback_focus(second)
                    stop.assert_called_once()
                assert window.active_transcription_editor is second
                window.research_metadata["timeline_markers"] = [
                    {"id": "m1", "label": "副歌", "time_ms": 1000.0}
                ]
                window._refresh_tracks()
                assert window.timeline.timeline_markers[0]["label"] == "副歌"
                assert first.canvas.timeline_markers[0]["label"] == "副歌"
                assert second.canvas.timeline_markers[0]["label"] == "副歌"
                window._edit_timeline_marker({"action": "delete", "id": "m1"})
                assert not window.timeline.timeline_markers
                snapshot = window.project_commands.undo(window._project_snapshot())
                assert snapshot is not None
                window._restore_project_snapshot(snapshot, "project undo")
                assert window.timeline.timeline_markers[0]["id"] == "m1"
                assert first.canvas.timeline_markers[0]["id"] == "m1"
                assert not hasattr(window, "track_inspector")
                window._close_all_note_editors()
                window.close(); app.processEvents()
                print("editor-workspace-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=90, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("editor-workspace-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
