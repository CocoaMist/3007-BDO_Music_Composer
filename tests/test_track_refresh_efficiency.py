import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class TrackRefreshEfficiencyTests(unittest.TestCase):
    def test_midi_load_rebuilds_timeline_index_once(self) -> None:
        script = textwrap.dedent(
            """
            import os
            import tempfile
            from pathlib import Path
            from unittest.mock import patch

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtWidgets import QApplication

            import pyside_bdo_gui as gui


            app = QApplication.instance() or QApplication([])
            window = gui.MidiToBdoWindow()
            window._flush_autosave = lambda: None
            note = gui.Note(60, 90, 0.0, 250.0, 0)
            original = window.timeline.set_tracks
            calls = []

            def counted(tracks):
                calls.append(tuple(tracks))
                original(tracks)

            with patch.object(window.timeline, "set_tracks", side_effect=counted), patch.object(
                gui,
                "parse_midi",
                return_value=(120, 4, [([note], 0, False)], 1, [[]], []),
            ), tempfile.TemporaryDirectory() as temp:
                assert window._load_midi_info(str(Path(temp) / "source.mid"))

            assert len(calls) == 1, len(calls)
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
