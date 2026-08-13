from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArrangementImportUiTests(unittest.TestCase):
    def test_append_is_one_undoable_workspace_edit(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from pathlib import Path
                from types import SimpleNamespace
                from unittest.mock import patch

                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                import bdo_music_composer.ui.arrangement_import_qt as append_ui
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                def track(track_id, pitch, instrument):
                    return TrackState(
                        track_id=track_id,
                        notes=[Note(pitch, 90, 100.0, 200.0, 0)],
                        gm_program=0,
                        is_percussion=False,
                        display_name=f"Track {track_id}",
                        bdo_instrument_id=instrument,
                    )

                app = QApplication([])
                window = MidiToBdoWindow()
                original = track(41, 60, 0x0B)
                imported = SimpleNamespace(
                    tracks=(track(0, 67, 0x12),),
                    lyric_events=({"time": 250.0, "kind": "lyrics", "text": "A"},),
                    bpm=120,
                    time_signature=4,
                )
                window.tracks = [original]
                window.lyric_events = []
                window._refresh_tracks()
                window._arrangement_import_offset = lambda: 500.0
                with patch.object(append_ui, "prepare_midi_import", return_value=imported):
                    window._append_arrangement_source(Path("layer.mid"), "midi")

                assert len(window.tracks) == 2
                assert window.tracks[0] is original
                assert window.tracks[1].track_id == 42
                assert window.tracks[1].notes[0].start == 600.0
                assert window.lyric_events[0]["time"] == 750.0
                assert len(window.project_commands._undo) == 1

                window._undo_project()
                assert len(window.tracks) == 1
                assert window.tracks[0].track_id == 41
                assert window.lyric_events == []
                window.autosave_timer.stop()
                window.close()
                app.processEvents()
                print("arrangement-import-ui-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("arrangement-import-ui-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
