from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineValidationMarkTests(unittest.TestCase):
    def test_only_exact_current_error_notes_are_red_and_clear_invalidates_cache(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import Note, TimelineCanvas, TrackState

            app = QApplication([])
            first = Note(60, 80, 0.0, 100.0, 0)
            second = Note(60, 80, 200.0, 100.0, 7)
            track = TrackState(1, [first, second], 0, False, "same pitch", 0x0B)
            timeline = TimelineCanvas()
            timeline.set_tracks([track])

            timeline.set_validation_notices({
                1: {
                    "errors": ("only second is invalid",),
                    "attentions": (),
                    "invalid_note_keys": (timeline._validation_note_key(second),),
                }
            })
            assert not timeline._note_has_conversion_problem(track, first)
            assert timeline._note_has_conversion_problem(track, second)
            assert timeline._conversion_problem_mask(track) == (1 << 60)

            timeline._static_timeline_cache_key = ("stale",)
            timeline.set_validation_notices({})
            assert timeline._static_timeline_cache_key is None
            assert not timeline._note_has_conversion_problem(track, first)
            assert not timeline._note_has_conversion_problem(track, second)
            timeline.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
