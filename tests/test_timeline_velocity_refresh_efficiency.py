from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineVelocityRefreshEfficiencyTests(unittest.TestCase):
    def test_velocity_curve_commit_uses_one_local_index_rebuild(self) -> None:
        script = textwrap.dedent(
            """
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._flush_autosave = lambda: None
            window._autosave_project = lambda *args, **kwargs: None
            window._restart_preview_after_timeline_change = (
                lambda change=None: window._apply_workspace_change(change)
            )
            tracks = [
                TrackState(
                    track_id,
                    [Note(60, 90, 0.0, 100.0, 0)],
                    0,
                    False,
                    f"track-{track_id}",
                    0x0B,
                )
                for track_id in range(120)
            ]
            window.tracks = tracks
            window.timeline.set_tracks(tracks)
            changed = [Note(60, 110, 0.0, 100.0, 0)]
            original = window.timeline._build_track_index
            calls = []

            def counted(track):
                calls.append(track)
                return original(track)

            with patch.object(
                window.timeline, "_build_track_index", side_effect=counted
            ):
                window._commit_timeline_velocity_curve(tracks[73], changed)

            assert calls == [tracks[73]], len(calls)
            assert tracks[73].notes == changed
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        with __import__("tempfile").TemporaryDirectory() as user_data:
            environment["BDO_USER_DATA_DIR"] = user_data
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
