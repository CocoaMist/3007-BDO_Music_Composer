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
    def test_music_reference_reopens_same_evidence_background(self) -> None:
        completed = _run_offscreen(
            """
            from types import SimpleNamespace
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.transcription.bdo_transcription import TranscriptionResult
            from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession
            from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            track = TrackState(
                1, [Note(60, 90, 0.0, 400.0, 0)],
                0, False, "target", 0x0B,
            )
            window = MidiToBdoWindow()
            window.tracks = [track]
            descriptor = SimpleNamespace(cache_key="stable-evidence")
            window.transcription_result = TranscriptionResult(
                (), "stable-evidence", evidence_descriptor=descriptor,
            )
            window.transcription_session = TranscriptionSession(
                (), cache_key="stable-evidence",
            )
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            opened = []

            def record_descriptor(value, *, audio_offset_ms=0.0):
                opened.append((value, float(audio_offset_ms)))
                editor.canvas._evidence_descriptor = value

            editor.canvas.set_evidence_descriptor = record_descriptor
            assert editor.transcription_mode_toggle.text() == "音乐参考"
            editor.transcription_mode_toggle.setChecked(True)
            assert opened == [(descriptor, 0.0)]
            assert editor.canvas._evidence_descriptor is descriptor

            editor.transcription_mode_toggle.setChecked(False)
            assert editor.canvas._evidence_descriptor is None
            assert editor._canvas_evidence_cache_key is None

            editor.transcription_mode_toggle.setChecked(True)
            assert opened == [(descriptor, 0.0), (descriptor, 0.0)]
            assert editor.canvas._evidence_descriptor is descriptor
            assert editor.transcription_waveform.reference_audio is window.reference_audio

            editor.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_reference_layer_controls_restore_and_update_project_state(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.project.project_schema import (
                normalize_reference_layer_settings,
            )

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            target = gui.TrackState(
                1, [gui.Note(60, 90, 0.0, 400.0, 0)],
                0, False, "target", 0x0B,
            )
            other = gui.TrackState(
                2, [gui.Note(67, 80, 100.0, 300.0, 0)],
                0, False, "other", 0x0B,
            )
            window.tracks = [target, other]
            window.reference_layer_settings = normalize_reference_layer_settings({
                "ghost_visible": False,
                "ghost_opacity_percent": 32,
                "candidate_visible": True,
                "candidate_opacity_percent": 36,
                "background_opacity_percent": 44,
                "contour_denoise": "high",
                "melody_lines_visible": False,
                "frame_visible": True,
                "onset_visible": False,
                "contour_visible": True,
                "spectrogram_visible": True,
            })

            editor = gui.MidiNoteEditorDialog(window, target, 120, 4)
            assert not editor.ghost_box.isChecked()
            assert not editor.ghost_box.isHidden()
            assert not editor.ghost_opacity_slider.isEnabled()
            assert editor.ghost_opacity_slider.value() == 32
            assert editor.ghost_opacity_label.text() == "32%"
            assert editor.canvas.ghost_notes == []
            assert editor.canvas._ghost_opacity == 0.32
            assert editor.canvas._reference_background_opacity == 0.44
            assert editor.canvas._transcription_candidate_opacity == 0.36
            assert editor.transcription_panel.candidate_layer_visible
            assert editor.transcription_panel.candidate_opacity == 0.36
            assert editor.transcription_panel.reference_background_opacity == 0.44
            assert editor.transcription_panel.contour_denoise == "high"
            assert editor.canvas._contour_denoise_profile == "high"
            assert editor.transcription_panel.visible_evidence_layers == frozenset(
                {"frame", "contour"}
            )
            assert not editor.transcription_panel.melody_lines_visible
            assert editor.transcription_panel.spectrogram_visible

            editor.ghost_box.setChecked(True)
            assert editor.ghost_opacity_slider.isEnabled()
            editor.ghost_opacity_slider.setValue(58)
            editor.transcription_panel.reference_opacity_slider.setValue(27)
            editor.transcription_panel.frame_checkbox.setChecked(False)
            editor.transcription_panel.melody_lines_button.setChecked(True)
            editor.transcription_panel.spectrogram_checkbox.setChecked(False)
            editor.transcription_panel.candidate_opacity_slider.setValue(61)
            editor.transcription_panel.candidate_layer_button.setChecked(False)
            editor.transcription_panel.contour_denoise_combo.setCurrentIndex(
                editor.transcription_panel.contour_denoise_combo.findData("low")
            )
            assert len(editor.canvas.ghost_notes) == 1
            assert window.reference_layer_settings["ghost_visible"]
            assert window.reference_layer_settings["ghost_opacity_percent"] == 58
            assert window.reference_layer_settings["background_opacity_percent"] == 27
            assert not window.reference_layer_settings["frame_visible"]
            assert window.reference_layer_settings["contour_visible"]
            assert window.reference_layer_settings["melody_lines_visible"]
            assert not window.reference_layer_settings["spectrogram_visible"]
            assert not window.reference_layer_settings["candidate_visible"]
            assert window.reference_layer_settings["candidate_opacity_percent"] == 61
            assert window.reference_layer_settings["contour_denoise"] == "low"

            editor.close()
            restored = gui.MidiNoteEditorDialog(window, target, 120, 4)
            assert restored.ghost_box.isChecked()
            assert restored.ghost_opacity_slider.value() == 58
            assert restored.ghost_opacity_label.text() == "58%"
            assert restored.transcription_panel.reference_opacity_slider.value() == 27
            assert not restored.transcription_panel.candidate_layer_visible
            assert restored.transcription_panel.candidate_opacity == 0.61
            assert restored.canvas._transcription_candidate_opacity == 0.61
            assert restored.transcription_panel.contour_denoise == "low"
            assert restored.canvas._contour_denoise_profile == "low"
            assert restored.transcription_panel.visible_evidence_layers == frozenset(
                {"contour"}
            )
            assert restored.transcription_panel.melody_lines_visible
            assert not restored.transcription_panel.spectrogram_visible
            restored.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_practical_handoff_checks_game_fit_without_mutating_draft(self) -> None:
        completed = _run_offscreen(
            """
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as gui
            import bdo_music_composer.ui.editor.midi_note_editor as editor_module

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            target = gui.TrackState(
                1,
                [gui.Note(60, 90, 0.0, 400.0, 0)],
                0,
                False,
                "target",
                0x10,
            )
            window.tracks = [target]
            editor = gui.MidiNoteEditorDialog(window, target, 120, 4)
            editor.show()
            original = tuple(editor.edited_notes())
            editor.transcription_mode_toggle.setChecked(True)
            app.processEvents()
            assert not hasattr(
                editor.transcription_panel,
                "game_adaptation_button",
            )
            assert not hasattr(
                editor.transcription_panel,
                "continue_creation_button",
            )

            with patch.object(
                editor_module.QMessageBox,
                "information",
                return_value=editor_module.QMessageBox.Ok,
            ) as information:
                editor.show_game_adaptation_check()
            assert information.call_count == 1
            assert "不会移动、删除、量化或改写" in information.call_args.args[2]
            assert tuple(editor.edited_notes()) == original

            editor.continue_creation_from_transcription()
            assert not editor.transcription_mode_toggle.isChecked()
            assert tuple(editor.edited_notes()) == original
            assert "草稿保持可编辑" in editor.status.text()

            editor.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_cache_restore_worker_rehashes_and_cancels_cooperatively(self) -> None:
        completed = _run_offscreen(
            """
            import hashlib
            import tempfile
            import threading
            import time
            from pathlib import Path

            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui

            app = QApplication([])
            import bdo_music_composer.ui.transcription.transcription_workers as workers
            real_fingerprint = workers.transcription_audio_fingerprint
            with tempfile.TemporaryDirectory() as folder:
                audio = Path(folder) / "reference.wav"
                audio.write_bytes(b"first-audio")
                expected = hashlib.sha256(b"first-audio").hexdigest()
                load_calls = []
                marker = object()

                def changing_load(_cache_key, **kwargs):
                    load_calls.append(kwargs)
                    audio.write_bytes(b"other-audio")
                    return marker

                workers.load_cached_transcription_result = changing_load
                worker = workers.TranscriptionCacheLoadWorker(
                    "a" * 24,
                    audio_path=audio,
                    expected_audio_fingerprint=expected,
                )
                restored = []
                worker.succeeded.connect(restored.append)
                worker.run()
                assert restored == [None]
                assert callable(load_calls[0]["cancelled"])
                assert worker.current_audio_fingerprint == hashlib.sha256(
                    b"other-audio"
                ).hexdigest()

                started = threading.Event()

                def cancellable_fingerprint(_path, *, cancelled=None):
                    started.set()
                    while not cancelled():
                        time.sleep(0.002)
                    raise gui.TranscriptionCancelled("cancelled")

                workers.transcription_audio_fingerprint = cancellable_fingerprint
                cancelled_worker = workers.TranscriptionCacheLoadWorker(
                    "b" * 24,
                    audio_path=audio,
                )
                cancelled_events = []
                cancelled_worker.cancelled.connect(
                    lambda: cancelled_events.append(True)
                )
                cancelled_worker.start()
                assert started.wait(2.0)
                cancelled_worker.cancel()
                assert cancelled_worker.wait(3_000)
                app.processEvents()
                assert cancelled_events == [True]

            workers.transcription_audio_fingerprint = real_fingerprint
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_loading_reference_audio_enables_embedded_analysis(self) -> None:
        completed = _run_offscreen(
            """
            import tempfile
            import wave
            from pathlib import Path

            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui

            gui.transcription_backend_quick_status = lambda: (True, "")
            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            track = gui.TrackState(
                1, [], 0, False, "target", 0x0B,
            )
            window.tracks = [track]
            editor = gui.MidiNoteEditorDialog(
                window,
                track,
                120,
                4,
                transcription_mode=True,
            )
            window.active_transcription_editor = editor
            window._refresh_transcription_workspace()
            assert not editor.transcription_panel.analyze_button.isEnabled()

            with tempfile.TemporaryDirectory() as folder:
                audio_path = Path(folder) / "reference.wav"
                with wave.open(str(audio_path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(8_000)
                    audio.writeframes(b"\\0\\0" * 8_000)
                assert window.reference_audio.set_audio_path(audio_path)
                app.processEvents()
                assert editor.transcription_panel._audio_loaded
                assert editor.transcription_panel.analyze_button.isEnabled()
                window.reference_audio.set_audio_path(None)
                app.processEvents()

            editor.close()
            window.active_transcription_editor = None
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_candidates_are_sidecar_and_accept_is_one_undoable_edit(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate, TranscriptionResult
            from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession
            from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

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
            window._autosave_project = lambda *_args, **_kwargs: None
            window.tracks = [target, ghost]
            candidates = (
                TranscriptionCandidate(60, 70, 0.0, 400.0, 0.77),
                TranscriptionCandidate(64, 91, 600.0, 320.0, 0.88),
                TranscriptionCandidate(100, 84, 1000.0, 250.0, 0.66),
            )
            result = TranscriptionResult(candidates, "unit-test")
            window.transcription_result = result
            window.transcription_session = TranscriptionSession(
                candidates,
                cache_key=result.cache_key,
            )
            window.transcription_session.set_selection(
                window.transcription_session.candidate_id(candidate)
                for candidate in candidates
            )

            editor = MidiNoteEditorDialog(window, target, 120, 4)
            editor.ghost_box.setChecked(True)
            window.active_transcription_editor = editor
            editor.transcription_mode_toggle.setChecked(True)
            initial_track_notes = list(target.notes)
            emitted = []
            editor.notes_applied.connect(lambda notes: emitted.append(list(notes)))
            editor._sync_shared_transcription_projection()

            # Analysis and overlay updates never touch either source TrackState or
            # the editor's authoritative draft note list.
            assert list(target.notes) == initial_track_notes
            assert list(editor.canvas.notes) == initial_track_notes
            assert emitted == []
            assert editor.canvas.transcription_candidates_visible
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert [item.note for item in editor.canvas.ghost_notes] == list(ghost.notes)
            assert editor.canvas.ghost_notes[0].track_id == ghost.track_id
            assert editor.canvas.ghost_notes[0].instrument_id == ghost.bdo_instrument_id
            assert editor.canvas.ghost_notes[0].color == ghost.color

            # Candidate and ghost layers have independent visibility and storage.
            editor.ghost_box.setChecked(False)
            assert editor.canvas.ghost_notes == []
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert len(editor.canvas.visible_transcription_candidates()) == 3
            editor.transcription_panel.candidate_layer_button.setChecked(False)
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert editor.canvas.visible_transcription_candidates() == []
            candidate_position = editor.canvas.candidate_rect(candidates[0]).center()
            assert editor.canvas.candidate_at(candidate_position) is None
            editor.transcription_panel.candidate_layer_button.setChecked(True)
            assert len(editor.canvas.visible_transcription_candidates()) == 3
            editor.ghost_box.setChecked(True)
            assert [item.note for item in editor.canvas.ghost_notes] == list(ghost.notes)

            editor.accept_transcription_candidates()
            assert len(editor.canvas.notes) == 2
            accepted = editor.canvas.notes[1]
            assert (accepted.pitch, accepted.vel, accepted.start, accepted.dur, accepted.ntype) == (
                64, 91, 600.0, 320.0, 0,
            )
            assert len(editor.undo_stack) == 1
            assert len(editor.staged_primary_routes) == 1
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
            assert editor.staged_primary_routes == set()
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert editor.canvas.transcription_candidates_visible
            editor.accept_transcription_candidates()
            assert len(editor.canvas.notes) == 2
            assert editor.canvas.notes[1].ntype == 0
            assert len(editor.undo_stack) == 1

            report = editor.apply_notes()
            assert report is not None and report.project_changed
            assert emitted == []
            assert any(note.pitch == 64 and note.ntype == 0 for note in target.notes)
            assert editor.staged_primary_routes == set()
            assert tuple(window.transcription_session.candidates) == candidates
            assert tuple(editor.canvas.transcription_candidates) == candidates
            assert len(editor.canvas.notes) == 2
            editor.close()
            window.active_transcription_editor = None
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
            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession
            from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

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
                    self.loaded_tracks = []
                    self.seek_calls = []
                    self.play_count = 0
                    self.pause_count = 0
                    self.stop_count = 0
                    self.clear_count = 0

                def load_project_async(self, _tracks, _mapping, start, *_effects):
                    self.loaded_tracks = list(_tracks)
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
                    self.stop_count += 1

                def clear_playback(self):
                    self.status.state = "stopped"
                    self.clear_count += 1

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
            editor.transcription_audition_source = "combined"
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

            # Game-candidate A/B is exclusive: it reuses the same transport
            # but does not mix or silently substitute the reference stream.
            clear_count = realtime.clear_count
            editor.stop_draft()
            assert realtime.clear_count == clear_count + 1
            assert realtime.stop_count == 0
            candidate = TranscriptionCandidate(
                60, 90, 300.0, 400.0, 0.9,
                candidate_id="voice-note",
            )
            window.transcription_session = TranscriptionSession(
                (candidate,), cache_key="cache",
            )
            group = SimpleNamespace(
                group_id="voice-1",
                candidate_ids=("voice-note",),
            )
            window._active_voice_group = lambda: group
            window.instrument_match_analysis = SimpleNamespace(
                matches_for_group=lambda _group_id: (
                    SimpleNamespace(instrument_id=0x0B),
                    SimpleNamespace(instrument_id=0x0B),
                ),
            )
            window._realtime_preview_blockers = lambda _tracks: []
            editor.transcription_audition_source = "candidate_a"
            editor.transpose = 12
            reference.positions.clear()
            reference_play_count = reference.play_count
            editor.set_draft_playhead(300.0)
            editor.play_draft()
            assert editor.draft_playback_state == "loading"
            assert realtime.loaded_tracks[0].notes[0].pitch == 72
            editor.poll_draft_playback()
            assert editor.draft_playback_state == "playing"
            assert reference.play_count == reference_play_count
            assert reference.positions == []

            editor.stop_draft()
            window._realtime_preview_blockers = lambda _tracks: [
                "missing game sample"
            ]
            editor.transcription_audition_source = "candidate_b"
            reference_play_count = reference.play_count
            editor.play_draft()
            assert editor.draft_playback_state == "stopped"
            assert reference.play_count == reference_play_count
            assert "没有回退播放原音" in editor.transcription_panel.status_label.text()

            editor.close()
            window.reference_audio = original_reference
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_closing_editor_does_not_own_shared_transcription_worker(self) -> None:
        completed = _run_offscreen(
            """
            import threading
            import time
            from pathlib import Path
            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui

            started = threading.Event()

            def cancellable_transcription(
                _path, _progress, cancelled, **_options
            ):
                started.set()
                while not cancelled():
                    time.sleep(0.005)
                # Keep the thread alive briefly to prove closeEvent does not
                # destroy its QObject parent before QThread.finished.
                time.sleep(0.12)
                raise gui.TranscriptionCancelled("cancelled")

            gui.transcription_backend_quick_status = lambda: (True, "")
            import bdo_music_composer.ui.transcription.transcription_workers as workers
            workers.transcribe_reference_audio = cancellable_transcription

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
                window.active_transcription_editor = editor
                editor.show()
                editor.transcription_mode_toggle.setChecked(True)
                editor.start_transcription_analysis()
                assert started.wait(2.0)
                worker = window.workspace_transcription_worker
                assert worker is not None
                assert worker.isRunning()
                assert worker.parent() is window
                assert window.transcription_analysis_busy
                assert not hasattr(editor, "transcription_worker")

                getattr(editor, action)()
                app.processEvents()
                assert editor.isHidden()
                assert window.workspace_transcription_worker is worker
                assert worker.isRunning()
                if action == "reject":
                    assert editor.result() == gui.QDialog.Rejected
                if window.active_transcription_editor is editor:
                    window.active_transcription_editor = None

                # The main-window session owns analysis independently of the
                # embedded editor projection. Explicitly cancel and drain that
                # owner before starting another analysis or closing the window.
                worker.cancel()
                assert worker.wait(3_000)
                app.processEvents()
                assert window.workspace_transcription_worker is None
                assert not window.transcription_analysis_busy

            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_audio_change_invalidates_queued_shared_worker_result(self) -> None:
        completed = _run_offscreen(
            """
            import threading
            from pathlib import Path

            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate, TranscriptionResult

            finished_in_worker = threading.Event()
            old_result = TranscriptionResult(
                (
                    TranscriptionCandidate(
                        60,
                        90,
                        100.0,
                        200.0,
                        0.9,
                        candidate_id="old-audio-candidate",
                    ),
                ),
                "old-audio-cache",
            )

            def quick_transcription(
                _path, _progress, _cancelled, **_options
            ):
                finished_in_worker.set()
                return old_result

            gui.transcription_backend_quick_status = lambda: (True, "")
            import bdo_music_composer.ui.transcription.transcription_workers as workers
            workers.transcribe_reference_audio = quick_transcription

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window.reference_audio._audio_path = Path.cwd() / "README.md"
            window.reference_audio_path = "old-reference.wav"
            window._start_workspace_transcription_analysis()
            worker = window.workspace_transcription_worker
            assert worker is not None
            assert finished_in_worker.wait(2.0)
            assert worker.wait(3_000)

            # succeeded/finished are queued to the GUI thread. Confirming an
            # audio change before processing them invalidates the old token.
            old_generation = window.workspace_transcription_generation
            window._reference_audio_changed("new-reference.wav")
            assert window.workspace_transcription_generation == old_generation + 1
            assert window.workspace_transcription_worker is worker
            assert window.transcription_result is None
            assert window.transcription_session.candidates == ()

            app.processEvents()
            assert window.workspace_transcription_worker is None
            assert window.transcription_result is None
            assert window.transcription_session.candidates == ()
            assert not window.transcription_session.state.cache_key

            # A late finished callback from any stale worker cannot clear a
            # replacement currently owned by the window.
            replacement = object()
            window.workspace_transcription_worker = replacement
            window._workspace_transcription_finished(
                old_generation,
                object(),
            )
            assert window.workspace_transcription_worker is replacement
            window.workspace_transcription_worker = None

            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_analysis_worker_never_drops_explicit_cleanup_profile(self) -> None:
        completed = _run_offscreen(
            """
            from pathlib import Path

            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.transcription.bdo_transcription import TranscriptionResult

            app = QApplication([])
            observed = []

            def strict_transcription(
                _path,
                _progress,
                _cancelled,
                *,
                analysis_mode,
                sensitivity,
                cleanup_profile,
            ):
                observed.append(
                    (analysis_mode, sensitivity, cleanup_profile)
                )
                return TranscriptionResult((), "strict-cache")

            import bdo_music_composer.ui.transcription.transcription_workers as workers
            workers.transcribe_reference_audio = strict_transcription
            worker = workers.TranscriptionAnalysisWorker(
                Path.cwd() / "README.md",
                analysis_mode="mixed_enhanced",
                sensitivity="sensitive",
                cleanup_profile="clean",
            )
            succeeded = []
            failed = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)
            worker.run()
            assert observed == [
                ("mixed_enhanced", "sensitive", "clean")
            ]
            assert len(succeeded) == 1
            assert not failed

            legacy_calls = []

            def legacy_adapter(_path, _progress, _cancelled):
                legacy_calls.append(True)
                return TranscriptionResult((), "legacy-cache")

            gui.append_crash_log = lambda *_args, **_kwargs: None
            workers.transcribe_reference_audio = legacy_adapter
            legacy_worker = workers.TranscriptionAnalysisWorker(
                Path.cwd() / "README.md",
                cleanup_profile="balanced",
            )
            legacy_succeeded = []
            legacy_failed = []
            legacy_worker.succeeded.connect(legacy_succeeded.append)
            legacy_worker.failed.connect(legacy_failed.append)
            legacy_worker.run()
            assert not legacy_calls
            assert not legacy_succeeded
            assert len(legacy_failed) == 1

            app.quit()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_save_config_creates_missing_user_data_directory(self) -> None:
        completed = _run_offscreen(
            """
            from pathlib import Path
            import tempfile
            from unittest.mock import patch

            import bdo_music_composer.ui.main_window as gui

            with tempfile.TemporaryDirectory() as folder_name:
                config_path = (
                    Path(folder_name)
                    / "missing"
                    / "nested"
                    / ".pyside_bdo_gui.json"
                )
                assert not config_path.parent.exists()
                with patch.object(gui, "CONFIG_PATH", config_path):
                    gui.save_config({"language": "en_US"})
                    assert gui.load_config() == {"language": "en_US"}
                assert config_path.is_file()
            """
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
