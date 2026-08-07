from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineIncrementalUpdateTests(unittest.TestCase):
    def test_single_track_update_rebuilds_only_that_interval_index(self) -> None:
        script = textwrap.dedent(
            """
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.editor.interval_index import IntervalIndex
            from bdo_music_composer.ui.main_window import Note, TimelineCanvas, TrackState

            app = QApplication([])
            tracks = [
                TrackState(
                    track_id,
                    [Note(60 + track_id % 4, 90, 0.0, 100.0, 0)],
                    0,
                    False,
                    f"track-{track_id}",
                    0x0B,
                )
                for track_id in range(120)
            ]
            timeline = TimelineCanvas()
            timeline.set_tracks(tracks)
            unchanged = timeline._track_note_indexes[id(tracks[0])].intervals
            tracks[73].notes = [Note(72, 100, 250.0, 300.0, 0)]
            original = IntervalIndex.build
            calls = []

            def counted(*args, **kwargs):
                calls.append(args[0])
                return original(*args, **kwargs)

            with patch.object(IntervalIndex, "build", side_effect=counted):
                timeline.update_tracks({73})

            assert len(calls) == 1, len(calls)
            assert timeline._track_note_indexes[id(tracks[0])].intervals is unchanged
            changed = timeline._track_note_indexes[id(tracks[73])].intervals
            assert changed.maximum_end == 550.0
            timeline.close()
            app.processEvents()
            app.quit()
            """
        )
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
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
