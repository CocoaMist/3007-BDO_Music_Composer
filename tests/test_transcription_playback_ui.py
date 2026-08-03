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


EDITOR_HARNESS = r"""
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, TrackState


class FakePlayer:
    def __init__(self, reference):
        self.reference = reference

    def position(self):
        return self.reference.audio_position_ms


class FakeReference:
    def __init__(self, *, offset_ms=0.0, duration_ms=3_000.0):
        self.audio_path = "reference.wav"
        self.offset_ms = float(offset_ms)
        self.duration_ms = float(duration_ms)
        self.audio_position_ms = 0.0
        self.is_playing = False
        self.positions = []
        self.play_count = 0
        self.pause_count = 0
        self.stop_count = 0
        self.player = FakePlayer(self)

    @property
    def project_start_ms(self):
        return self.offset_ms

    @property
    def project_end_ms(self):
        return self.offset_ms + self.duration_ms

    @property
    def project_position_ms(self):
        return self.audio_to_project(self.audio_position_ms)

    def project_to_audio(self, project_ms):
        return float(project_ms) - self.offset_ms

    def audio_to_project(self, audio_ms):
        return float(audio_ms) + self.offset_ms

    def set_position(self, project_ms):
        self.audio_position_ms = max(0.0, self.project_to_audio(project_ms))
        self.positions.append(float(project_ms))

    def play(self):
        self.is_playing = True
        self.play_count += 1

    def pause(self):
        self.is_playing = False
        self.pause_count += 1

    def stop(self):
        self.is_playing = False
        self.audio_position_ms = 0.0
        self.stop_count += 1


class FakeRealtime:
    def __init__(self):
        self.status = SimpleNamespace(
            preload_progress=1.0,
            preload_loaded=1,
            preload_total=1,
            position_ms=0.0,
            duration_ms=2_000.0,
            state="stopped",
        )
        self.loaded_tracks = []
        self.load_start_ms = None
        self.play_count = 0
        self.pause_count = 0
        self.clear_count = 0

    def load_project_async(self, tracks, _mapping, start_ms, *_effects):
        self.loaded_tracks = list(tracks)
        self.load_start_ms = float(start_ms)
        self.status.state = "loading"

    def finish_loading(self, start_ms):
        self.status.position_ms = float(start_ms)
        return {
            "events": sum(len(track.notes) for track in self.loaded_tracks),
            "samples": 1,
            "cache_bytes": 1,
            "unverified": [],
        }

    def get_status(self):
        return self.status

    def play(self):
        self.status.state = "playing"
        self.play_count += 1

    def pause(self):
        self.status.state = "paused"
        self.pause_count += 1

    def clear_playback(self):
        self.status.state = "stopped"
        self.clear_count += 1

    def cancel_loading(self):
        self.status.state = "stopped"

    def seek(self, position_ms):
        self.status.position_ms = float(position_ms)


app = QApplication([])
window = MidiToBdoWindow()
track = TrackState(1, [], 0, False, "empty target", 0x0B)
window.tracks = [track]
editor = MidiNoteEditorDialog(
    window,
    track,
    120,
    4,
    transcription_mode=True,
)
editor.transcription_mode_toggle.setChecked(True)
old_reference = window.reference_audio
old_realtime = window.realtime_audio
reference = FakeReference()
realtime = FakeRealtime()
window.reference_audio = reference
window.realtime_audio = realtime
window._stop_preview = lambda reset_playhead=False: None
"""


EDITOR_CLEANUP = r"""
editor.hide()
window.reference_audio = old_reference
window.realtime_audio = old_realtime
window.hide()
app.processEvents()
app.quit()
"""


class TranscriptionPlaybackUiTests(unittest.TestCase):
    def assert_offscreen_ok(self, script: str) -> None:
        completed = _run_offscreen(EDITOR_HARNESS + script + EDITOR_CLEANUP)
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_reference_only_transport_skips_leading_project_silence(self) -> None:
        self.assert_offscreen_ok(
            r"""
reference = FakeReference(offset_ms=1_000.0, duration_ms=3_000.0)
window.reference_audio = reference
editor.transcription_audition_source = "combined"
window._realtime_preview_blockers = lambda _tracks: []
editor.set_draft_playhead(0.0)

editor.play_draft()
assert editor.draft_reference_only, (
    "combined playback with no edited notes must immediately use the "
    "reference-only clock"
)
assert realtime.loaded_tracks == [], (
    "combined playback with an empty draft must not create a zero-event game "
    "clock that prevents the reference stream from starting"
)
assert editor.draft_playback_state == "playing"
assert editor.playhead_ms == 1_000.0, (
    "reference-only transport must use the same first-audible-frame rule "
    "as the main timeline"
)
assert reference.positions[-1] == 1_000.0
assert reference.is_playing and reference.play_count == 1

editor.pause_draft()
assert editor.draft_playback_state == "paused"
assert not reference.is_playing and reference.pause_count == 1
editor.resume_draft()
assert editor.draft_playback_state == "playing"
assert reference.is_playing and reference.positions[-1] == 1_000.0

reference.audio_position_ms = 650.0
editor.poll_draft_playback()
assert editor.playhead_ms == 1_650.0
editor.stop_draft()
assert editor.draft_playback_state == "stopped"
assert editor.playhead_ms == 0.0
assert not reference.is_playing and reference.stop_count == 1
"""
        )

    def test_loaded_reference_can_start_before_duration_metadata_arrives(self) -> None:
        self.assert_offscreen_ok(
            r"""
reference = FakeReference(offset_ms=0.0, duration_ms=0.0)
window.reference_audio = reference
editor.transcription_audition_source = "original"
editor.set_draft_playhead(420.0)

editor.play_draft()
assert editor.draft_reference_only
assert editor.draft_playback_state == "playing"
assert reference.is_playing and reference.play_count == 1, (
    "a loaded local source with pending duration metadata must be allowed "
    "to bootstrap QMediaPlayer"
)
assert reference.positions[-1] == 420.0

# Metadata publication must not lose the requested project position or create
# a second transport.  The same controller remains the reference clock.
reference.duration_ms = 3_000.0
editor.poll_draft_playback()
assert editor.playhead_ms == 420.0
editor.pause_draft()
assert not reference.is_playing
editor.resume_draft()
assert reference.is_playing and reference.positions[-1] == 420.0
editor.stop_draft()
assert editor.draft_playback_state == "stopped"
"""
        )

    def test_controller_reapplies_seek_when_duration_metadata_arrives(self) -> None:
        completed = _run_offscreen(
            r"""
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import ReferenceAudioController

            class FakePlayer:
                def __init__(self):
                    self.duration_value = 0
                    self.positions = []

                def duration(self):
                    return self.duration_value

                def setPosition(self, value):
                    self.positions.append(int(value))

            app = QApplication([])
            controller = ReferenceAudioController()
            player = FakePlayer()
            controller.player = player
            controller._project_offset_ms = 100.0

            controller.set_position(420.0)
            assert controller._pending_project_position_ms == 420.0
            assert player.positions[-1] == 320

            player.duration_value = 3_000
            controller._apply_pending_position()
            assert controller._pending_project_position_ms is None
            assert player.positions[-1] == 320
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_semantic_audition_source_is_absent_from_practical_panel(self) -> None:
        completed = _run_offscreen(
            r"""
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.transcription.transcription_editor_qt import TranscriptionEditorPanel

            app = QApplication([])
            panel = TranscriptionEditorPanel()
            panel.show()
            app.processEvents()
            assert not hasattr(panel, "assist_panel")
            assert not hasattr(panel, "assist_toggle_button")
            panel.clear_voice_group_matches()
            panel.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_candidate_preview_is_exclusive_but_combined_uses_edited_draft(self) -> None:
        self.assert_offscreen_ok(
            r"""
from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession
from bdo_music_composer.ui.main_window import Note

candidate = TranscriptionCandidate(
    60,
    90,
    300.0,
    400.0,
    0.9,
    candidate_id="voice-note",
)
window.transcription_session = TranscriptionSession(
    (candidate,),
    cache_key="cache",
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

# Candidate A/B must never silently fall back to the reference recording.
window._realtime_preview_blockers = lambda _tracks: ["missing game sample"]
editor.transcription_audition_source = "candidate_a"
editor.play_draft()
assert editor.draft_playback_state == "stopped"
assert reference.play_count == 0
assert realtime.loaded_tracks == []

# Combined mode uses the editor-local draft, not the formal TrackState, and
# starts the same reference controller on the same project clock.
editor.canvas.notes = [Note(64, 96, 250.0, 600.0, 0)]
editor.transcription_audition_source = "combined"
window._realtime_preview_blockers = lambda _tracks: []
editor.set_draft_playhead(200.0)
editor.play_draft()
assert editor.draft_playback_state == "loading"
assert realtime.load_start_ms == 200.0
assert realtime.loaded_tracks[0].notes == editor.edited_notes()
assert track.notes == []
editor.poll_draft_playback()
assert editor.draft_playback_state == "playing"
assert realtime.status.state == "playing"
assert reference.is_playing and reference.positions[-1] == 200.0
editor.pause_draft()
assert realtime.status.state == "paused" and not reference.is_playing
editor.resume_draft()
assert realtime.status.state == "playing" and reference.is_playing
editor.stop_draft()
assert realtime.clear_count == 1
assert reference.stop_count == 1
"""
        )


if __name__ == "__main__":
    unittest.main()
