from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(
    script: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TranscriptionLifecycleSnapshotUiTests(unittest.TestCase):
    def assert_offscreen_success(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_pending_window_close_stops_debounce_and_blocks_new_assist(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import EvidenceDescriptor, TranscriptionResult
            from pyside_bdo_gui import MidiToBdoWindow


            class RunningWorker:
                def __init__(self):
                    self.running = True
                    self.cancelled = False

                def isRunning(self):
                    return self.running

                def cancel(self):
                    self.cancelled = True


            app = QApplication([])
            window = MidiToBdoWindow()
            window._flush_autosave = lambda: None
            window._autosave_project = lambda *_args, **_kwargs: None
            descriptor = EvidenceDescriptor(
                "current-cache",
                "test-backend",
                "current-audio",
                1000.0,
                0,
                "times_ms.npy",
                (0,),
                "float64",
                0,
                "",
            )
            window.transcription_result = TranscriptionResult(
                (),
                "current-cache",
                evidence_descriptor=descriptor,
            )
            running = RunningWorker()
            window.workspace_transcription_worker = running
            window.transcription_assist_refresh_timer.start(10)
            assert window.transcription_assist_refresh_timer.isActive()

            event = QCloseEvent()
            window.closeEvent(event)
            assert not event.isAccepted()
            assert running.cancelled
            assert window.workspace_close_pending
            assert not window.transcription_assist_refresh_timer.isActive()

            # A queued timeout or any other late caller cannot start a new
            # assist worker while the existing worker is draining.
            window.transcription_assist_restart_pending = True
            window.transcription_assist_restart_harmony_only = True
            window.transcription_assist_restart_allow_review_recovery = False
            window._start_transcription_assist_analysis()
            assert window.transcription_assist_worker is None
            assert not window.transcription_assist_restart_pending
            assert not window.transcription_assist_restart_harmony_only
            assert window.transcription_assist_restart_allow_review_recovery

            running.running = False
            window.workspace_transcription_worker = None
            window.workspace_close_pending = False
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_snapshot_assist_is_orphaned_against_current_audio_identity(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import (
                EvidenceDescriptor,
                TranscriptionCandidate,
                TranscriptionResult,
            )
            from bdo_transcription_assist import (
                KeyReviewOverride,
                LockedChordReview,
                ManualVoiceGroupReview,
                TranscriptionAssistReviewState,
            )
            from bdo_music_composer.editor.editor_commands import ProjectSnapshot
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._flush_autosave = lambda: None
            window._autosave_project = lambda *_args, **_kwargs: None
            window._stop_preview = lambda *_args, **_kwargs: None
            window.tracks = [TrackState(1, [], 0, False, "lead", 0x0B)]
            window.timeline.set_tracks(window.tracks)

            current_candidate = TranscriptionCandidate(
                60,
                90,
                100.0,
                300.0,
                0.9,
                candidate_id="current-candidate",
            )
            descriptor = EvidenceDescriptor(
                "current-cache",
                "test-backend",
                "current-audio",
                1000.0,
                0,
                "times_ms.npy",
                (0,),
                "float64",
                0,
                "",
            )
            window.transcription_result = TranscriptionResult(
                (current_candidate,),
                "current-cache",
                evidence_descriptor=descriptor,
            )
            window.transcription_assist_previous_candidates = (
                current_candidate,
            )

            old_review = TranscriptionAssistReviewState(
                audio_fingerprint="old-audio",
                key_override=KeyReviewOverride(0, "major"),
                locked_chord_segments=(
                    LockedChordReview(
                        "old-chord-review",
                        "old-segment",
                        100.0,
                        400.0,
                        0,
                        "major",
                        0,
                        ("old-candidate",),
                    ),
                ),
                voice_groups=(
                    ManualVoiceGroupReview(
                        "old-voice-review",
                        "old-group",
                        ("old-candidate",),
                        100.0,
                        400.0,
                        "primary_melody",
                        0x0B,
                    ),
                ),
            )
            snapshot = ProjectSnapshot.capture(
                window.tracks,
                window.reverb,
                window.delay,
                window.chorus,
                None,
                old_review.to_payload(),
            )
            assist_starts = []
            window._start_transcription_assist_analysis = (
                lambda *args, **kwargs: assist_starts.append(
                    (args, kwargs)
                )
            )

            window._restore_project_snapshot(snapshot, "project undo")
            restored = window.transcription_assist_review
            assert restored.audio_fingerprint == "current-audio"
            assert restored.active_key_override is None
            assert restored.active_chord_segments == ()
            assert restored.active_voice_groups == ()
            assert restored.has_orphaned_reviews
            assert window.transcription_assist_previous_candidates == ()
            assert assist_starts == [
                ((), {"allow_review_recovery": False})
            ]

            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)


if __name__ == "__main__":
    unittest.main()
