from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PreviewPauseUiTests(unittest.TestCase):
    def test_pause_requested_during_loading_survives_ready_completion(self) -> None:
        script = textwrap.dedent(
            """
            from types import SimpleNamespace

            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            class FakeAudio:
                def __init__(self):
                    self.status = SimpleNamespace(
                        state="loading", position_ms=0.0, duration_ms=1000.0,
                        preload_progress=0.5, preload_total=2, cache_misses=0,
                    )
                    self.ready = False
                    self.play_count = 0
                    self.pause_count = 0
                    self.last_error = ""

                def available(self): return True
                def get_status(self): return self.status
                def finish_loading(self, _start):
                    if not self.ready: return None
                    self.status.state = "stopped"
                    return {"unverified": []}
                def play(self):
                    self.play_count += 1
                    self.status.state = "playing"
                def pause(self):
                    self.pause_count += 1
                    self.status.state = "paused"
                def stop(self):
                    self.status.state = "stopped"

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(1, [Note(60, 80, 0.0, 500.0, 0)], 0, False, "one", 0x0B)
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            fake = FakeAudio()
            window.realtime_audio = fake
            window._realtime_preview_blockers = lambda _tracks: []
            window.preview_transport_coordinator.begin_loading(
                start_ms=0.0, tracks=[track], source="generic",
            )

            window._sync_preview_state()
            assert window.pause_button.isEnabled()
            window._pause_preview()
            assert window.preview_transport_coordinator.pause_requested
            assert fake.play_count == 0

            fake.ready = True
            window._poll_realtime_audio_status()
            assert not window.realtime_preview_loading
            assert window.realtime_preview_active
            assert window.preview_transport_coordinator.pause_requested
            assert fake.play_count == 0
            assert window.play_button.isEnabled()

            window._play_preview()
            assert not window.preview_transport_coordinator.pause_requested
            assert fake.play_count == 1
            assert fake.status.state == "playing"
            window.preview_transport_coordinator.clear_session()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
