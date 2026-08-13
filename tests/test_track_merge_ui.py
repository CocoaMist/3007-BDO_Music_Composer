from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrackMergeUiTests(unittest.TestCase):
    def test_commit_is_one_undo_step_and_marks_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.editor.track_merge import plan_track_merge
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                def track(track_id, pitch, start):
                    return TrackState(
                        track_id=track_id,
                        notes=[Note(pitch, 90, start, 200.0, 0)],
                        gm_program=0, is_percussion=False,
                        display_name=f"Track {track_id}", bdo_instrument_id=0x12,
                    )

                app = QApplication([])
                window = MidiToBdoWindow()
                left = track(1, 60, 0.0)
                right = track(2, 64, 100.0)
                window.tracks = [left, right]
                window._refresh_tracks()
                plan = plan_track_merge(left, right)
                window._commit_track_merge_plan(plan)
                assert len(window.tracks) == 1
                assert len(window.tracks[0].notes) == 2
                assert len(window.project_commands._undo) == 1
                assert window.timeline._merge_overlap_track_id == 1
                assert len(window.timeline._merge_overlap_regions) == 1
                window._undo_project()
                assert len(window.tracks) == 2
                assert window.timeline._merge_overlap_track_id is None
                window.autosave_timer.stop()
                window.close()
                app.processEvents()
                print("track-merge-ui-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=90, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("track-merge-ui-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
