from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionSemanticCanvasUiTests(unittest.TestCase):
    def test_mixed_review_undo_order_and_top3_confirmation_are_fail_closed(
        self,
    ) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_instruments import (
                BdoInstrumentMatch,
                InstrumentMatchAnalysis,
                VoiceGroup,
            )
            from bdo_transcription_session import TranscriptionSession
            from pyside_bdo_gui import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            autosaves = []
            window._autosave_project = (
                lambda reason, *_args, **_kwargs: autosaves.append(reason)
            )
            window.show_toast = lambda *_args, **_kwargs: None
            candidate = TranscriptionCandidate(
                60, 90, 100.0, 300.0, 0.2, candidate_id="candidate"
            )
            window.transcription_session = TranscriptionSession(
                (candidate,), cache_key="cache"
            )
            candidate_id = window.transcription_session.candidate_id(
                candidate
            )
            window.transcription_session.set_selection((candidate_id,))

            window._reject_transcription_candidates()
            assert candidate_id in (
                window.transcription_session.state.rejected_candidate_ids
            )
            window._set_assist_key_override(
                0, "major", manual=True, locked=True
            )
            assert window.transcription_review_action_undo == [
                "session", "assist"
            ]

            window._undo_transcription_review()
            assert window.transcription_assist_review.key_override is None
            assert candidate_id in (
                window.transcription_session.state.rejected_candidate_ids
            )
            window._undo_transcription_review()
            assert candidate_id not in (
                window.transcription_session.state.rejected_candidate_ids
            )
            window._redo_transcription_review()
            assert candidate_id in (
                window.transcription_session.state.rejected_candidate_ids
            )
            window._undo_transcription_review()
            window._set_assist_key_override(
                9, "minor", manual=True, locked=False
            )
            assert not window._can_redo_transcription_review()

            # The opposite mixed branch is invalidated as well: a new
            # session edit after undoing an assist edit cannot replay that
            # abandoned assist branch.
            window._undo_transcription_review()
            assert window.transcription_assist_review.key_override is None
            assert window.transcription_assist_review_redo
            window._reject_transcription_candidates()
            assert candidate_id in (
                window.transcription_session.state.rejected_candidate_ids
            )
            assert not window.transcription_assist_review_redo
            assert not window.transcription_review_action_redo
            assert not window._can_redo_transcription_review()

            group = VoiceGroup(
                "voice",
                (candidate_id,),
                0.0,
                1000.0,
                "primary_melody",
                0.8,
            )
            match = BdoInstrumentMatch(
                0x0B, 0.8, 1.0, None, 0.8, ("range",)
            )
            analysis = InstrumentMatchAnalysis(
                "match-cache",
                "",
                (group,),
                (("voice", (match,)),),
            )
            window.instrument_match_analysis = analysis
            review_before = window.transcription_assist_review
            history_before = (
                tuple(window.transcription_assist_review_undo),
                tuple(window.transcription_assist_review_redo),
                tuple(window.transcription_review_action_undo),
                tuple(window.transcription_review_action_redo),
            )
            autosave_count = len(autosaves)
            window._confirm_assist_instrument_match("voice", 0x7F)
            assert window.transcription_assist_review == review_before
            assert (
                tuple(window.transcription_assist_review_undo),
                tuple(window.transcription_assist_review_redo),
                tuple(window.transcription_review_action_undo),
                tuple(window.transcription_review_action_redo),
            ) == history_before
            assert len(autosaves) == autosave_count
            window._confirm_assist_instrument_match("voice", 0x0B)
            assert (
                window.transcription_assist_review.voice_groups[0]
                .confirmed_instrument_id
            ) == 0x0B

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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_assist_worker_forwards_harmony_cancellation_and_emits_cancelled(
        self,
    ) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription_harmony import HarmonyAnalysisCancelled
            import pyside_bdo_gui as gui
            import transcription_workers as workers

            app = QApplication([])
            worker = gui.TranscriptionAssistAnalysisWorker(
                cache_key="cache",
                candidates=(),
                audio_time_notes=(),
                descriptors=(),
                bpm=120.0,
                time_signature=4,
                beat_origin_audio_ms=0.0,
                duration_ms=1000.0,
                midi_min=21,
            )
            callback_checks = []

            def cancelling_harmony(
                *_args,
                cancelled=None,
                **_kwargs,
            ):
                assert callable(cancelled)
                callback_checks.append(cancelled())
                worker.cancel()
                callback_checks.append(cancelled())
                raise HarmonyAnalysisCancelled("cancelled")

            workers.load_transcription_evidence = lambda *_args: object()
            workers.load_transcription_frame_times = lambda *_args: object()
            workers.analyse_harmony = cancelling_harmony

            events = []
            worker.cancelled.connect(
                lambda: events.append(("cancelled", None))
            )
            worker.failed.connect(
                lambda message: events.append(("failed", message))
            )
            worker.succeeded.connect(
                lambda value: events.append(("succeeded", value))
            )
            worker.run()

            assert callback_checks == [False, True]
            assert events == [("cancelled", None)]

            worker.deleteLater()
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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_manual_chord_split_merge_and_repeat_edit_are_stable(
        self,
    ) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_harmony import (
                ChordSegment,
                HarmonyAnalysis,
                KeyEstimate,
            )
            from bdo_transcription_instruments import InstrumentMatchAnalysis
            from bdo_transcription_session import TranscriptionSession
            from pyside_bdo_gui import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            window._current_analysis_fingerprint = lambda: "audio-fingerprint"
            window.reference_audio_offset_ms = 100.0
            candidates = (
                TranscriptionCandidate(
                    60, 90, 100.0, 240.0, 0.9, candidate_id="c1"
                ),
                TranscriptionCandidate(
                    64, 88, 620.0, 240.0, 0.9, candidate_id="c2"
                ),
            )
            window.transcription_session = TranscriptionSession(
                candidates, cache_key="cache"
            )
            automatic = HarmonyAnalysis(
                "harmony-cache",
                KeyEstimate(0, "major", 0.8),
                (
                    ChordSegment(
                        "auto-segment",
                        0.0,
                        1000.0,
                        0,
                        "major",
                        0,
                        0.8,
                    ),
                ),
            )
            window.automatic_harmony_analysis = automatic
            window.automatic_instrument_match_analysis = (
                InstrumentMatchAnalysis("match", "", (), ())
            )
            window.harmony_analysis = automatic
            window.instrument_match_analysis = (
                window.automatic_instrument_match_analysis
            )

            # Project 600 ms maps to audio 500 ms exactly once.
            window._split_transcription_chord_segment(
                "auto-segment", 600.0
            )
            reviews = window.transcription_assist_review.locked_chord_segments
            assert len(reviews) == 2
            assert [
                (item.start_audio_ms, item.end_audio_ms)
                for item in reviews
            ] == [(0.0, 500.0), (500.0, 1000.0)]
            assert all(item.manual and item.locked for item in reviews)
            rendered = window.harmony_analysis.chord_segments
            assert len(rendered) == 2

            window._merge_transcription_chord_segments(
                rendered[0].segment_id,
                rendered[1].segment_id,
                rendered[0].segment_id,
            )
            reviews = window.transcription_assist_review.locked_chord_segments
            assert len(reviews) == 1
            assert (
                reviews[0].start_audio_ms,
                reviews[0].end_audio_ms,
            ) == (0.0, 1000.0)
            merged = window.harmony_analysis.chord_segments[0]
            assert (merged.start_audio_ms, merged.end_audio_ms) == (
                0.0,
                1000.0,
            )

            # Rendered manual IDs are regenerated by the pure overlay. A
            # second edit must replace the interval review instead of adding
            # an overlapping duplicate.
            window._set_assist_chord_review(
                merged,
                root_pc=9,
                quality="minor",
                bass_pc=9,
                manual=True,
                locked=True,
            )
            edited = window.harmony_analysis.chord_segments[0]
            window._set_assist_chord_review(
                edited,
                root_pc=7,
                quality="7",
                bass_pc=7,
                manual=True,
                locked=True,
            )
            reviews = window.transcription_assist_review.locked_chord_segments
            assert len(reviews) == 1
            assert (reviews[0].root_pc, reviews[0].quality) == (7, "7")

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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_semantic_projection_uses_one_canvas_and_three_lod_levels(
        self,
    ) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPointF, Qt
            from PySide6.QtGui import QImage, QPainter
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import (
                TranscriptionCandidate,
                TranscriptionCandidateAnnotation,
                TranscriptionPostprocessReport,
                TranscriptionResult,
            )
            from bdo_transcription_harmony import (
                ChordSegment,
                HarmonyAnalysis,
                KeyEstimate,
            )
            from bdo_transcription_instruments import VoiceGroup
            from bdo_transcription_session import TranscriptionSession
            from pyside_bdo_gui import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                PianoRollCanvas,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            # Diagnostic layers are intentionally persisted for real users;
            # isolate this default-state assertion from the developer's
            # machine-local UI preferences.
            window.config["transcription_ui"] = {}
            window.reference_audio_offset_ms = 125.0
            track = TrackState(1, [], 0, False, "target", 0x0B)
            window.tracks = [track]
            candidates = (
                TranscriptionCandidate(
                    60, 90, 100.0, 400.0, 0.92, candidate_id="c-root"
                ),
                TranscriptionCandidate(
                    60, 88, 110.0, 380.0, 0.76, candidate_id="c-alt"
                ),
                TranscriptionCandidate(
                    64, 86, 180.0, 300.0, 0.81, candidate_id="c-third"
                ),
                TranscriptionCandidate(
                    67, 70, 520.0, 220.0, 0.08, candidate_id="c-low"
                ),
            )
            session = TranscriptionSession(candidates, cache_key="cache")
            window.transcription_session = session
            editor = MidiNoteEditorDialog(
                window, track, 120, 4, transcription_mode=True
            )
            window.active_transcription_editor = editor
            editor.resize(980, 700)
            editor.show()
            app.processEvents()
            canvas = editor.canvas
            assert len(editor.findChildren(PianoRollCanvas)) == 1
            assert not canvas._show_frame_evidence
            assert not canvas._show_onset_evidence
            assert not canvas._show_contour_evidence
            assert not editor.transcription_panel.frame_checkbox.isChecked()
            assert not editor.transcription_panel.onset_checkbox.isChecked()
            assert not editor.transcription_panel.contour_checkbox.isChecked()

            canvas.set_transcription_review(
                candidates,
                session.candidate_id,
                audio_offset_ms=125.0,
                visible=True,
            )
            low_id = session.candidate_id(candidates[3])
            editor.transcription_panel.set_confidence_floor(0.95)
            editor._sync_shared_transcription_projection()
            assert candidates[3] in canvas.visible_transcription_candidates()
            canvas.set_transcription_review(
                candidates,
                session.candidate_id,
                audio_offset_ms=125.0,
                visible=True,
                fragment_ids={"c-low"},
                suppressed_ids={"c-low"},
            )
            assert canvas._fragment_candidate_ids == {"c-low"}
            assert canvas._suppressed_candidate_ids == {"c-low"}
            low_pos = canvas.candidate_rect(candidates[3]).center()
            assert canvas.candidate_at(low_pos) == low_id
            QTest.mouseClick(
                canvas,
                Qt.LeftButton,
                Qt.NoModifier,
                low_pos.toPoint(),
            )
            app.processEvents()
            assert low_id in session.state.selected_candidate_ids
            assert low_id in editor.eligible_transcription_candidate_ids()

            # Review-only changes must reuse the expensive annotation and
            # active+suppressed projections.  In particular, showing hidden
            # candidates must not rebuild/sort the canvas source on every
            # selection refresh.
            suppressed = TranscriptionCandidate(
                72,
                65,
                760.0,
                30.0,
                0.18,
                candidate_id="c-suppressed",
            )
            report = TranscriptionPostprocessReport(
                profile="clean",
                version="test",
                raw_candidate_count=5,
                output_candidate_count=4,
                exact_duplicate_count=0,
                nms_removed_count=0,
                automatic_merge_count=0,
                suspected_fragment_count=1,
                severe_fragment_count=1,
                density_short_count=1,
                pitch_flicker_count=0,
                suppressed_count=1,
                annotations=(
                    TranscriptionCandidateAnnotation(
                        "c-suppressed",
                        ("review_fragment", "severe_fragment"),
                        ("c-suppressed",),
                        "suppressed",
                    ),
                ),
                suppressed_candidates=(suppressed,),
                automatic_actions_enabled=True,
            )
            window.transcription_result = TranscriptionResult(
                candidates,
                "cache",
                postprocess_report=report,
            )
            editor.transcription_panel.show_suppressed_checkbox.setChecked(
                True
            )
            editor._sync_shared_transcription_projection()
            first_canvas_source = canvas._candidate_source_object
            first_annotation_cache = (
                editor._transcription_annotation_projection_cache
            )
            first_display_cache = (
                editor._transcription_display_projection_cache
            )
            assert first_canvas_source is not None
            assert len(first_canvas_source) == 5
            assert "c-suppressed" in canvas._suppressed_candidate_ids
            assert "c-suppressed" in canvas._fragment_candidate_ids
            session.set_selection(("c-third",))
            editor._sync_shared_transcription_projection()
            assert canvas._candidate_source_object is first_canvas_source
            assert (
                editor._transcription_annotation_projection_cache
                is first_annotation_cache
            )
            assert (
                editor._transcription_display_projection_cache
                is first_display_cache
            )
            assert canvas._selected_candidate_ids == {"c-third"}

            session.clear_selection()
            group = VoiceGroup(
                "voice-1",
                ("c-root", "c-alt", "c-third"),
                100.0,
                500.0,
                "primary_melody",
                0.86,
            )
            harmony = HarmonyAnalysis(
                "harmony",
                KeyEstimate(0, "major", 0.8),
                (
                    ChordSegment(
                        "chord-1",
                        0.0,
                        600.0,
                        0,
                        "major",
                        0,
                        0.82,
                    ),
                ),
            )
            canvas.set_transcription_assist_projection(
                voice_groups=(group,),
                harmony_analysis=harmony,
                group_colors={"voice-1": "#6f9fd8"},
            )
            assert canvas._candidate_group_ids == {
                "c-root": "voice-1",
                "c-alt": "voice-1",
                "c-third": "voice-1",
            }
            assert canvas._candidate_group_colors["c-root"] == "#6f9fd8"
            assert canvas._candidate_chord_roles["c-root"] == "root"
            assert canvas._candidate_chord_roles["c-third"] == "third"
            assert canvas._folded_candidate_primary["c-alt"] == "c-root"
            assert canvas._fold_alternative_counts["c-root"] == 1
            canvas._hovered_candidate_id = "c-root"
            alternative_rect = canvas._candidate_display_rect(
                "c-alt",
                candidates[1],
            )
            assert alternative_rect != canvas.candidate_rect(candidates[1])
            assert canvas.candidate_at(alternative_rect.center()) == "c-alt"
            canvas._hovered_candidate_id = ""

            # Candidate and harmony geometry apply the independent audio
            # offset exactly once.
            root_rect = canvas.candidate_rect(candidates[0])
            assert abs(root_rect.left() - canvas.x_at_time(225.0)) < 0.01
            segment = canvas._chord_segment_at(
                QPointF(
                    canvas.x_at_time(300.0),
                    canvas.TIME_RULER_H + 3.0,
                )
            )
            assert segment is harmony.chord_segments[0]
            assert canvas._voice_group_for_candidate("c-root") is group
            assert canvas._adjacent_voice_groups("voice-1") == ()

            image = QImage(980, 700, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            outline_calls = []
            original_outline = canvas._paint_voice_group_outlines
            canvas._paint_voice_group_outlines = (
                lambda *args: outline_calls.append(args)
            )
            canvas.px_per_beat = 39.0
            canvas._paint_transcription_candidates(
                painter, canvas.grid_rect(), 0.0, 1000.0
            )
            assert len(outline_calls) == 1
            canvas.px_per_beat = 40.0
            canvas._paint_transcription_candidates(
                painter, canvas.grid_rect(), 0.0, 1000.0
            )
            assert len(outline_calls) == 1
            canvas.px_per_beat = 161.0
            canvas._paint_transcription_candidates(
                painter, canvas.grid_rect(), 0.0, 1000.0
            )
            assert len(outline_calls) == 1
            canvas._paint_voice_group_outlines = original_outline
            painter.end()

            editor.close()
            window.active_transcription_editor = None
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
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
