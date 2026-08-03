from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionRhythmProjectionUiTests(unittest.TestCase):
    def test_preview_toggle_and_promotion_share_projected_timing(self) -> None:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    import numpy as np
                    from PySide6.QtWidgets import QApplication

                    from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate, TranscriptionResult
                    from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession
                    from bdo_music_composer.transcription.rhythm_alignment import RhythmAlignmentConfig, analyse_rhythm_alignment
                    from bdo_music_composer.transcription.rhythm_grid import ProjectRhythmSettings
                    from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState

                    app = QApplication([])
                    track = TrackState(1, [], 0, False, "target", 0x0B)
                    window = MidiToBdoWindow()
                    window._autosave_project = lambda *_args, **_kwargs: None
                    window.tracks = [track]
                    candidate = TranscriptionCandidate(
                        60, 90, 517.0, 83.0, 0.9,
                        candidate_id="candidate-a",
                    )
                    result = TranscriptionResult((candidate,), "a" * 24)
                    window.transcription_result = result
                    window.transcription_session = TranscriptionSession(
                        (candidate,), cache_key=result.cache_key,
                    )
                    window.transcription_session.set_selection(("candidate-a",))
                    times = np.arange(0.0, 2000.0, 10.0, dtype=np.float64)
                    onset = np.zeros((len(times), 88), dtype=np.float32)
                    for value in range(0, 2000, 500):
                        onset[value // 10, 60 - 21] = 1.0
                    alignment = analyse_rhythm_alignment(
                        evidence_cache_key=result.cache_key,
                        candidates=(candidate,),
                        settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
                        frame_times_ms=times,
                        onset_evidence=onset,
                        config=RhythmAlignmentConfig(profile="strict_1_64"),
                    )

                    editor = MidiNoteEditorDialog(window, track, 120, 4)
                    window.active_transcription_editor = editor
                    editor.transcription_mode_toggle.setChecked(True)
                    editor.set_transcription_rhythm_alignment(alignment)
                    editor._sync_shared_transcription_projection()
                    shown = tuple(editor.canvas.transcription_candidates)
                    assert len(shown) == 1
                    assert shown[0].start_ms != candidate.start_ms
                    assert abs(shown[0].start_ms / 31.25 - round(shown[0].start_ms / 31.25)) < 1e-9

                    editor.accept_transcription_candidates()
                    assert len(editor.canvas.notes) == 1
                    assert editor.canvas.notes[0].start == shown[0].start_ms
                    editor.undo()

                    editor.transcription_panel.rhythm_projection_checkbox.setChecked(False)
                    shown_raw = tuple(editor.canvas.transcription_candidates)
                    assert shown_raw[0].start_ms == candidate.start_ms
                    editor.accept_transcription_candidates()
                    assert editor.canvas.notes[0].start == candidate.start_ms

                    editor.close()
                    window.active_transcription_editor = None
                    window.close()
                    app.processEvents()
                    app.quit()
                    """
                ),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
