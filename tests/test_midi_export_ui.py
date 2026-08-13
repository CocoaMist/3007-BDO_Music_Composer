from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MidiExportUiTests(unittest.TestCase):
    def test_current_editor_model_is_published_as_atomic_midi(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            output = root / "current.mid"
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(root / "data")
            script = textwrap.dedent(
                f"""
                from pathlib import Path
                from unittest.mock import patch
                import mido
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                import bdo_music_composer.ui.midi_export_qt as export_ui
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                app = QApplication([])
                window = MidiToBdoWindow()
                window.tracks = [TrackState(
                    track_id=1,
                    notes=[Note(72, 91, 250.0, 500.0, 0)],
                    gm_program=8,
                    is_percussion=False,
                    display_name="current",
                    bdo_instrument_id=0x12,
                )]
                window.lyric_events = [{{"time": 250.0, "kind": "lyrics", "text": "A"}}]
                with patch.object(
                    export_ui.QFileDialog,
                    "getSaveFileName",
                    return_value=({str(output)!r}, ""),
                ):
                    window._export_standard_midi()
                midi = mido.MidiFile(Path({str(output)!r}))
                assert any(message.type == "note_on" and message.note == 72 for message in midi.tracks[1])
                assert any(message.type == "lyrics" for message in midi.tracks[0])
                window.autosave_timer.stop()
                window.close()
                app.processEvents()
                print("midi-export-ui-ok")
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
            self.assertTrue(output.is_file())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("midi-export-ui-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
