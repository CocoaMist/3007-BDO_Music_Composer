from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(script: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
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


class TranscriptionUiTests(unittest.TestCase):
    def test_candidates_are_sidecar_and_accept_is_one_undoable_edit(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_transcription import TranscriptionCandidate, TranscriptionResult
            from pyside_bdo_gui import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            target = TrackState(
                1, [Note(60, 96, 0.0, 400.0, 3)],
                0, False, "target", 0x0B,
            )
            ghost = TrackState(
                2, [Note(67, 80, 200.0, 300.0, 0)],
                0, False, "ghost", 0x0B,
            )
            window = MidiToBdoWindow()
            window.tracks = [target, ghost]
            editor = MidiNoteEditorDialog(window, target, 120, 4)
            editor.transcription_mode_toggle.setChecked(True)
            initial_track_notes = list(target.notes)
            emitted = []
            editor.notes_applied.connect(lambda notes: emitted.append(list(notes)))

            candidates = (
                TranscriptionCandidate(60, 70, 0.0, 400.0, 0.77),
                TranscriptionCandidate(64, 91, 600.0, 320.0, 0.88),
                TranscriptionCandidate(100, 84, 1000.0, 250.0, 0.66),
            )
            result = TranscriptionResult(candidates, "unit-test")
            editor._transcription_succeeded(editor.transcription_generation, result)

            # Analysis and overlay updates never touch either source TrackState or
            # the editor's authoritative draft note list.
            assert list(target.notes) == initial_track_notes
            assert list(editor.canvas.notes) == initial_track_notes
            assert emitted == []
            assert editor.canvas.transcription_candidates_visible
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert editor.canvas.ghost_notes == list(ghost.notes)

            # Candidate and ghost layers have independent visibility and storage.
            editor.ghost_box.setChecked(False)
            assert editor.canvas.ghost_notes == []
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert len(editor.canvas.visible_transcription_candidates()) == 3
            editor.ghost_box.setChecked(True)
            assert editor.canvas.ghost_notes == list(ghost.notes)

            editor.accept_transcription_candidates()
            assert len(editor.canvas.notes) == 2
            accepted = editor.canvas.notes[1]
            assert (accepted.pitch, accepted.vel, accepted.start, accepted.dur, accepted.ntype) == (
                64, 91, 600.0, 320.0, 0,
            )
            assert len(editor.undo_stack) == 1
            assert list(target.notes) == initial_track_notes
            assert emitted == []

            # A second write is a no-op: the accepted candidate and the original
            # note are both deduplicated, while the out-of-range pitch is rejected.
            editor.accept_transcription_candidates()
            assert len(editor.canvas.notes) == 2
            assert len(editor.undo_stack) == 1
            assert all(note.pitch != 100 for note in editor.canvas.notes)

            # One undo removes the whole accepted batch without discarding the
            # sidecar, so the same candidate can be reviewed and written again.
            editor.undo()
            assert list(editor.canvas.notes) == initial_track_notes
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert editor.canvas.transcription_candidates_visible
            editor.accept_transcription_candidates()
            assert len(editor.canvas.notes) == 2
            assert editor.canvas.notes[1].ntype == 0
            assert len(editor.undo_stack) == 1

            editor.apply_notes()
            assert len(emitted) == 1
            assert any(note.pitch == 64 and note.ntype == 0 for note in emitted[0])
            assert list(target.notes) == initial_track_notes

            editor.clear_transcription_candidates()
            assert editor.canvas.transcription_candidates == []
            assert len(editor.canvas.notes) == 2
            editor.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_reference_only_and_combined_transport_share_editor_timeline(self) -> None:
        completed = _run_offscreen(
            """
            from types import SimpleNamespace
            from PySide6.QtWidgets import QApplication
            from pyside_bdo_gui import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

            class FakePlayer:
                def __init__(self):
                    self.value = 0.0

                def position(self):
                    return self.value

            class FakeReference:
                def __init__(self):
                    self.audio_path = "reference.wav"
                    self.duration_ms = 3000.0
                    self.is_playing = False
                    self.player = FakePlayer()
                    self.positions = []
                    self.play_count = 0
                    self.pause_count = 0
                    self.stop_count = 0

                def set_position(self, value):
                    self.player.value = float(value)
                    self.positions.append(float(value))

                def play(self):
                    self.is_playing = True
                    self.play_count += 1

                def pause(self):
                    self.is_playing = False
                    self.pause_count += 1

                def stop(self):
                    self.is_playing = False
                    self.player.value = 0.0
                    self.stop_count += 1

            class FakeRealtime:
                def __init__(self):
                    self.status = SimpleNamespace(
                        preload_progress=1.0,
                        preload_loaded=1,
                        preload_total=1,
                        position_ms=0.0,
                        duration_ms=1000.0,
                        state="stopped",
                    )
                    self.ready = False
                    self.loaded_from = None
                    self.seek_calls = []
                    self.play_count = 0
                    self.pause_count = 0

                def load_project_async(self, _tracks, _mapping, start, *_effects):
                    self.loaded_from = float(start)
                    self.status.state = "loading"

                def get_status(self):
                    return self.status

                def finish_loading(self, start):
                    if not self.ready:
                        return None
                    self.status.position_ms = float(start)
                    return {"events": 1, "samples": 1, "cache_bytes": 1, "unverified": []}

                def play(self):
                    self.status.state = "playing"
                    self.play_count += 1

                def pause(self):
                    self.status.state = "paused"
                    self.pause_count += 1

                def stop(self):
                    self.status.state = "stopped"

                def seek(self, value):
                    self.status.position_ms = float(value)
                    self.seek_calls.append(float(value))

                def cancel_loading(self):
                    self.status.state = "stopped"

            app = QApplication([])
            track = TrackState(
                1, [Note(60, 96, 0.0, 900.0, 0)],
                0, False, "target", 0x0B,
            )
            window = MidiToBdoWindow()
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            original_reference = window.reference_audio
            reference = FakeReference()
            realtime = FakeRealtime()
            window.reference_audio = reference
            window.realtime_audio = realtime
            window._stop_preview = lambda reset_playhead=False: None
            editor.transcription_mode_toggle.setChecked(True)

            # With no game sample available the editor remains useful: reference
            # audio owns the same playhead, seek, pause and resume state.
            window._realtime_preview_blockers = lambda _tracks: ["missing sample"]
            editor.set_draft_playhead(250.0)
            editor.play_draft()
            assert editor.draft_reference_only
            assert editor.draft_playback_state == "playing"
            assert reference.is_playing and reference.positions[-1] == 250.0
            editor.seek_draft(700.0)
            assert reference.positions[-1] == 700.0
            assert realtime.seek_calls == []
            editor.pause_draft()
            assert editor.draft_playback_state == "paused"
            assert not reference.is_playing
            editor.poll_draft_playback()
            assert editor.draft_playback_state == "paused"
            editor.resume_draft()
            assert editor.draft_playback_state == "playing"
            assert reference.is_playing and reference.positions[-1] == 700.0
            stop_count = reference.stop_count
            editor.transcription_mode_toggle.setChecked(False)
            assert editor.draft_playback_state == "stopped"
            assert not reference.is_playing
            assert reference.stop_count == stop_count + 1
            editor.transcription_mode_toggle.setChecked(True)
            editor.set_draft_playhead(900.0)
            editor.play_draft()
            assert editor.draft_reference_only and reference.is_playing
            reference.player.value = 900.0
            editor.poll_draft_playback()
            assert editor.playhead_ms == 900.0
            reference.is_playing = False
            editor.poll_draft_playback()
            assert editor.draft_playback_state == "stopped"
            assert editor.playhead_ms == 0.0

            # When game samples are available, both engines start from the same
            # position. An already-playing reference is not continuously re-seeked.
            window._realtime_preview_blockers = lambda _tracks: []
            editor.set_draft_playhead(200.0)
            realtime.ready = True
            editor.play_draft()
            assert editor.draft_playback_state == "loading"
            assert realtime.loaded_from == 200.0
            editor.poll_draft_playback()
            assert editor.draft_playback_state == "playing"
            assert realtime.status.state == "playing"
            assert reference.is_playing
            assert reference.positions[-1] == 200.0
            reference.positions.clear()
            realtime.status.position_ms = 450.0
            editor.poll_draft_playback()
            assert editor.playhead_ms == 450.0
            assert reference.positions == []
            editor.pause_draft()
            assert realtime.status.state == "paused"
            assert not reference.is_playing
            editor.resume_draft()
            assert realtime.status.state == "playing"
            assert reference.is_playing and reference.positions[-1] == 450.0

            # The reference clock cleanly takes over when it outlasts the BDO
            # preview, without resetting the shared playhead.
            realtime.status.position_ms = realtime.status.duration_ms
            reference.player.value = 1200.0
            editor.poll_draft_playback()
            assert editor.draft_reference_only
            reference.player.value = 1400.0
            editor.poll_draft_playback()
            assert editor.playhead_ms == 1400.0

            editor.stop_draft()
            editor.close()
            window.reference_audio = original_reference
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_closing_editor_waits_for_transcription_thread_to_finish(self) -> None:
        completed = _run_offscreen(
            """
            import threading
            import time
            from pathlib import Path
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            import pyside_bdo_gui as gui

            started = threading.Event()

            def cancellable_transcription(_path, _progress, cancelled):
                started.set()
                while not cancelled():
                    time.sleep(0.005)
                # Keep the thread alive briefly to prove closeEvent does not
                # destroy its QObject parent before QThread.finished.
                time.sleep(0.12)
                raise gui.TranscriptionCancelled("cancelled")

            gui.transcription_backend_available = lambda: True
            gui.transcribe_reference_audio = cancellable_transcription

            app = QApplication([])
            track = gui.TrackState(
                1, [gui.Note(60, 96, 0.0, 400.0, 0)],
                0, False, "target", 0x0B,
            )
            window = gui.MidiToBdoWindow()
            window.tracks = [track]
            window.reference_audio._audio_path = Path.cwd() / "README.md"

            for action in ("close", "reject"):
                started.clear()
                editor = gui.MidiNoteEditorDialog(window, track, 120, 4)
                editor.show()
                editor.transcription_mode_toggle.setChecked(True)
                editor.start_transcription_analysis()
                assert started.wait(2.0)
                assert editor.transcription_worker is not None
                assert editor.transcription_worker.isRunning()

                getattr(editor, action)()
                app.processEvents()
                assert editor.transcription_close_pending
                assert editor.isVisible()
                QTest.qWait(260)
                app.processEvents()
                assert editor.transcription_worker is None
                assert editor.isHidden()
                if action == "reject":
                    assert editor.result() == gui.QDialog.Rejected

            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
