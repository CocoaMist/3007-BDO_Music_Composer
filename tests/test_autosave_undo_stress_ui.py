from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AutosaveUndoStressUiTests(unittest.TestCase):
    def test_save_storm_coalesces_latest_state_across_undo_redo(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder) / "data")
            script = textwrap.dedent(
                """
                import json
                import time
                from pathlib import Path
                from unittest.mock import patch
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                import bdo_music_composer.ui.project_autosave_qt as autosave_qt
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                app = QApplication([]); window = MidiToBdoWindow()
                track = TrackState(1, [Note(60, 90, 0, 100, 0)], 0, False, "lead", 0x12)
                window.source_format = "project"; window.output_name.setText("Storm")
                window.tracks = [track]; window._refresh_tracks()
                real_write = autosave_qt.write_autosave
                writes = []
                def slow_write(request):
                    writes.append(request.metadata.reason)
                    time.sleep(0.008)
                    return real_write(request)

                with patch.object(autosave_qt, "write_autosave", slow_write):
                    for serial in range(80):
                        window._push_project_snapshot()
                        track.notes.append(Note(61 + serial % 12, 70, serial * 20 + 200, 50, 0))
                        window._autosave_project(f"burst-{serial}", immediate=True)
                    assert window._wait_for_autosave_idle(30_000)
                    project_path = window.autosave_project_dir / "project.json"
                    payload = json.loads(project_path.read_text("utf-8"))
                    assert payload["reason"] == "burst-79", payload["reason"]
                    assert len(payload["tracks"][0]["notes"]) == 81
                    assert len(writes) < 30, len(writes)

                    for _ in range(20):
                        snapshot = window.project_commands.undo(window._project_snapshot())
                        assert snapshot is not None
                        window._restore_project_snapshot(snapshot, "project undo")
                    assert window._wait_for_autosave_idle(30_000)
                    payload = json.loads(project_path.read_text("utf-8"))
                    assert len(payload["tracks"][0]["notes"]) == 61

                    for _ in range(20):
                        snapshot = window.project_commands.redo(window._project_snapshot())
                        assert snapshot is not None
                        window._restore_project_snapshot(snapshot, "project redo")
                    assert window._wait_for_autosave_idle(30_000)
                    payload = json.loads(project_path.read_text("utf-8"))
                    assert len(payload["tracks"][0]["notes"]) == 81
                    assert window.autosave_worker is None
                    assert window.pending_autosave_request is None
                window.autosave_timer.stop(); window.close(); app.processEvents()
                print("autosave-undo-storm-ok")
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=120, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("autosave-undo-storm-ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()
