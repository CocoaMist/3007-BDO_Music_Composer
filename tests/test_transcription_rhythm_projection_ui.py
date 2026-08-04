from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionRhythmProjectionUiTests(unittest.TestCase):
    def test_focus_and_pitch_line_follow_the_visible_timing_projection(self) -> None:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    """
                    from types import SimpleNamespace
                    from unittest.mock import patch
                    import numpy as np
                    from PySide6.QtGui import QColor, QImage, QPainter
                    from PySide6.QtWidgets import QApplication

                    from bdo_midi import Note
                    from bdo_music_composer.project.project_schema import normalize_reference_layer_settings
                    from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate, TranscriptionResult
                    from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession
                    from bdo_music_composer.transcription.rhythm_alignment import RhythmAlignmentConfig, analyse_rhythm_alignment
                    from bdo_music_composer.transcription.rhythm_grid import ProjectRhythmSettings
                    from bdo_music_composer.ui.main_window import MidiNoteEditorDialog, MidiToBdoWindow, TrackState

                    app = QApplication([])
                    candidates = (
                        TranscriptionCandidate(60, 90, 6_017.0, 420.0, 0.92, candidate_id="a"),
                        TranscriptionCandidate(62, 90, 12_017.0, 420.0, 0.92, candidate_id="b"),
                    )
                    result = TranscriptionResult(candidates, "f" * 24)
                    times = np.arange(0.0, 13_000.0, 10.0, dtype=np.float64)
                    onset = np.zeros((len(times), 88), dtype=np.float32)
                    for value in range(0, 13_000, 600):
                        onset[value // 10, 60 - 21] = 1.0
                    alignment = analyse_rhythm_alignment(
                        evidence_cache_key=result.cache_key,
                        candidates=candidates,
                        settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
                        frame_times_ms=times,
                        onset_evidence=onset,
                        config=RhythmAlignmentConfig(profile="strict_1_64"),
                    )
                    projected = tuple(alignment.apply_to(value) for value in candidates)
                    assert all(
                        0.0 < abs(left.start_ms - right.start_ms) <= 45.0
                        for left, right in zip(candidates, projected)
                    )

                    track = TrackState(
                        1,
                        [
                            Note(value.pitch, 90, value.start_ms, value.duration_ms, 0)
                            for value in projected
                        ],
                        0,
                        False,
                        "target",
                        0x0B,
                    )
                    window = MidiToBdoWindow()
                    window.tracks = [track]
                    window.transcription_result = result
                    window.transcription_session = TranscriptionSession(
                        candidates,
                        cache_key=result.cache_key,
                    )
                    window.instrument_match_analysis = SimpleNamespace(
                        groups=(SimpleNamespace(
                            group_id="source-a",
                            candidate_ids=("a", "b"),
                            candidate_confidences=(("a", 0.9), ("b", 0.9)),
                            confidence=0.85,
                            color="#4AA3DF",
                        ),),
                        matches={},
                    )
                    window.reference_layer_settings = normalize_reference_layer_settings({
                        "timbre_grouping_enabled": False,
                        "melody_guidance_enabled": True,
                    })
                    editor = MidiNoteEditorDialog(
                        window,
                        track,
                        120,
                        4,
                        transcription_mode=True,
                    )
                    editor.set_transcription_rhythm_alignment(alignment)
                    editor._sync_shared_transcription_projection()

                    assert tuple(
                        value.start_ms for value in editor.canvas.transcription_candidates
                    ) == tuple(value.start_ms for value in projected)
                    assert editor.canvas._melody_guidance.focus_group_id == "source-a"
                    cached_guidance = editor.canvas._melody_guidance
                    with patch(
                        "bdo_music_composer.ui.editor.midi_note_editor.build_reference_melody_guidance",
                        side_effect=AssertionError("guidance cache missed"),
                    ):
                        editor._sync_shared_transcription_projection()
                    assert editor.canvas._melody_guidance is cached_guidance
                    assert all(
                        span.focused
                        and span.target_instrument_id == 0x0B
                        and span.color == track.color
                        for span in editor.canvas._contour_color_spans
                    )
                    assert tuple(
                        span.start_ms for span in editor.canvas._contour_color_spans
                    ) == (6_017.0, 12_017.0)
                    first_projected = projected[0]
                    editor.canvas.set_transcription_candidates_visible(True)
                    assert editor.canvas._candidate_time_warps, (
                        editor.canvas._candidate_source_timings,
                        tuple(
                            (value.candidate_id, value.start_ms)
                            for value in editor.canvas.transcription_candidates
                        ),
                    )
                    warp_entries = editor.canvas._visible_contour_time_warps(
                        first_projected.start_ms,
                        first_projected.start_ms + first_projected.duration_ms,
                    )
                    assert len(warp_entries) == 1, warp_entries
                    tile = SimpleNamespace(
                        time_start_ms=4_000.0,
                        time_end_ms=8_000.0,
                        pitch_min=21.0,
                        pitch_max_exclusive=109.0,
                        image=QImage(400, 88, QImage.Format_ARGB32),
                    )
                    segments = editor.canvas._contour_warp_segments_for_tile(
                        tile,
                        warp_entries,
                    )
                    assert len(segments) == 1, segments
                    _clip, target_rect, source_rect = segments[0]
                    assert abs(
                        target_rect.left()
                        - editor.canvas.candidate_rect(
                            editor.canvas.transcription_candidates[0]
                        ).left()
                    ) < 0.01
                    assert abs(source_rect.left() - 201.7) < 0.01, source_rect

                    editor.canvas.resize(1200, 600)
                    editor.canvas.scroll_ms = max(
                        0.0,
                        first_projected.start_ms - 1_000.0,
                    )
                    tile.image.fill(QColor("#ff0000"))
                    tile.layer = "contour"
                    editor.canvas._evidence_descriptor = object()
                    editor.canvas._show_contour_evidence = True
                    editor.canvas._contour_opacity = 1.0
                    editor.canvas._evidence.request_visible = (
                        lambda *_args, **_kwargs: (tile,)
                    )
                    rendered = QImage(
                        editor.canvas.size(),
                        QImage.Format_ARGB32,
                    )
                    rendered.fill(0)
                    painter = QPainter(rendered)
                    editor.canvas._paint_transcription_evidence(
                        painter,
                        editor.canvas.grid_rect(),
                        first_projected.start_ms - 100.0,
                        first_projected.start_ms
                        + first_projected.duration_ms
                        + 100.0,
                    )
                    painter.end()
                    projected_rect = editor.canvas.candidate_rect(
                        editor.canvas.transcription_candidates[0]
                    )
                    projected_pixel = rendered.pixelColor(
                        round(projected_rect.center().x()),
                        round(projected_rect.center().y()),
                    )
                    assert projected_pixel.red() > 200, (
                        projected_pixel.getRgb(),
                        projected_rect,
                        editor.canvas.grid_rect(),
                        target_rect,
                        source_rect,
                        editor.canvas._transcription_contour_clip_path(
                            editor.canvas.grid_rect(),
                            editor.canvas.scroll_ms,
                            editor.canvas.time_at(editor.canvas.width()),
                        ).boundingRect(),
                    )

                    editor.transcription_panel.rhythm_projection_checkbox.setChecked(False)
                    assert tuple(
                        value.start_ms for value in editor.canvas.transcription_candidates
                    ) == (6_017.0, 12_017.0), tuple(
                        value.start_ms for value in editor.canvas.transcription_candidates
                    )
                    assert editor.canvas._melody_guidance.focus_group_id == "source-a", (
                        editor.canvas._melody_guidance.focus_group_id
                    )
                    assert all(
                        span.focused for span in editor.canvas._contour_color_spans
                    ), editor.canvas._contour_color_spans

                    editor.transcription_panel.rhythm_projection_checkbox.setChecked(True)
                    assert editor.canvas._melody_guidance.focus_group_id == "source-a", (
                        editor.canvas._melody_guidance.focus_group_id
                    )
                    assert all(
                        span.focused for span in editor.canvas._contour_color_spans
                    ), editor.canvas._contour_color_spans

                    editor.close(); window.close(); app.processEvents(); app.quit()
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
            msg=completed.stdout + completed.stderr,
        )

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
