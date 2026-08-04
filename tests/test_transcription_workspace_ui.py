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


class EmbeddedTranscriptionUiTests(unittest.TestCase):
    def assert_offscreen_success(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_practical_analysis_forces_safe_defaults_and_skips_assist(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from pathlib import Path

            from PySide6.QtCore import QObject, Signal
            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as main_window
            from bdo_music_composer.transcription.bdo_transcription_session import (
                TranscriptionSession,
                TranscriptionSessionState,
            )

            captured = {}

            class FakeWorker(QObject):
                progress_changed = Signal(int)
                succeeded = Signal(object)
                failed = Signal(str)
                cancelled = Signal()
                finished = Signal()

                def __init__(
                    self,
                    audio_path,
                    parent,
                    *,
                    analysis_mode,
                    sensitivity,
                    cleanup_profile,
                ):
                    super().__init__(parent)
                    captured.update(
                        audio_path=str(audio_path),
                        analysis_mode=analysis_mode,
                        sensitivity=sensitivity,
                        cleanup_profile=cleanup_profile,
                    )

                def start(self):
                    captured["started"] = True

            app = QApplication([])
            main_window.transcription_backend_quick_status = lambda: (True, "")
            main_window.TranscriptionAnalysisWorker = FakeWorker
            window = main_window.MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window._flush_autosave = lambda: None
            window._stop_preview = lambda **_kwargs: None
            window.reference_audio._audio_path = Path("reference.wav")
            window.transcription_session = TranscriptionSession(
                state=TranscriptionSessionState(
                    analysis_mode="mixed_enhanced",
                    sensitivity="sensitive",
                    cleanup_profile="clean",
                )
            )

            window._start_workspace_transcription_analysis()
            assert captured == {
                "audio_path": "reference.wav",
                "analysis_mode": "standard",
                "sensitivity": "balanced",
                "cleanup_profile": "preserve",
                "started": True,
            }
            state = window.transcription_session.state
            assert state.analysis_mode == "standard"
            assert state.sensitivity == "balanced"
            assert state.cleanup_profile == "preserve"

            window._start_transcription_assist_analysis()
            assert window.transcription_assist_worker is None
            assert window.harmony_analysis is None
            assert window.instrument_match_analysis is None

            window.workspace_transcription_worker = None
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_entry_resolves_melodic_target_and_opens_embedded_editor(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window._flush_autosave = lambda: None
            first = TrackState(1, [], 0, False, "same melody", 0x0B)
            second = TrackState(2, [], 0, False, "same melody", 0x0B)
            drums = TrackState(3, [], 0, True, "drums", 0x0D)
            mapped_drums = TrackState(
                4,
                [],
                0,
                False,
                "mapped drums",
                0x0D,
            )
            window.tracks = [first, second, drums, mapped_drums]
            window.timeline.set_tracks(window.tracks)
            window._show_workspace()
            window.show()
            app.processEvents()

            calls = []

            def open_editor(
                track,
                selected_note_indices=(),
                *,
                transcription_mode=False,
            ):
                calls.append(
                    (
                        track.track_id,
                        tuple(selected_note_indices),
                        transcription_mode,
                    )
                )

            window._open_note_editor = open_editor
            assert not hasattr(window, "transcription_entry_button")
            assert not hasattr(window, "transcription_tools_slot")

            # A valid current selection opens directly without a chooser.
            window.selected_track = first
            window._open_transcription_mode()
            assert calls == [(1, (), True)]

            # Percussion is never silently substituted. The user explicitly
            # chooses one of the available melodic tracks.
            original_get_item = QInputDialog.getItem
            QInputDialog.getItem = (
                lambda *_args, **_kwargs: (
                    next(
                        label
                        for label in _args[3]
                        if "#2" in label
                    ),
                    True,
                )
            )
            try:
                window.selected_track = drums
                window._open_transcription_mode()
            finally:
                QInputDialog.getItem = original_get_item
            assert calls[-1] == (2, (), True)

            # A score containing only percussion reports the missing target and
            # does not open any editor.
            messages = []
            original_information = QMessageBox.information
            QMessageBox.information = (
                lambda _parent, title, message, *_args, **_kwargs:
                messages.append((title, message))
            )
            try:
                window.tracks = [drums, mapped_drums]
                window.selected_track = drums
                window._open_transcription_mode()
            finally:
                QMessageBox.information = original_information
            assert len(calls) == 2
            assert messages
            assert "旋律乐器轨" in messages[-1][1]

            assert not hasattr(window, "workspace_mode_stack")
            assert not hasattr(window, "transcription_workspace")
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_mode_reuses_exactly_one_piano_roll(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                PianoRollCanvas,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window._flush_autosave = lambda: None
            track = TrackState(
                1,
                [Note(60, 96, 0.0, 400.0, 0)],
                0,
                False,
                "lead",
                0x0B,
            )
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            window._show_workspace()
            window.show()
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.show()
            app.processEvents()

            canvas = editor.canvas
            assert editor.findChildren(PianoRollCanvas) == [canvas]
            assert window.findChildren(PianoRollCanvas) == [canvas]
            assert not hasattr(window, "workspace_mode_stack")
            assert not hasattr(window, "transcription_workspace")
            assert window.timeline.isVisible()

            editor.transcription_mode_toggle.setChecked(True)
            app.processEvents()
            assert editor.canvas is canvas
            assert editor.findChildren(PianoRollCanvas) == [canvas]
            assert editor.transcription_panel.isVisible()
            assert editor.transcription_waveform.isVisible()
            assert editor.transcription_waveform.height() == 72
            assert editor.velocity_toggle.isEnabled()
            assert not editor.velocity_toggle.isChecked()
            editor.velocity_toggle.click()
            app.processEvents()
            assert editor.velocity_toggle.isChecked()
            assert editor.velocity_lane.isVisible()
            assert window.timeline.isVisible()

            # Leaving the mode preserves the same editing layout and canvas.
            editor.transcription_mode_toggle.setChecked(False)
            app.processEvents()
            assert editor.canvas is canvas
            assert not editor.transcription_panel.isVisible()
            assert not editor.transcription_waveform.isVisible()
            assert editor.velocity_toggle.isEnabled()
            assert editor.velocity_toggle.isChecked()
            assert editor.velocity_lane.isVisible()

            editor.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_staging_is_dialog_local_undoable_and_cancel_is_lossless(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QDialog

            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.transcription.bdo_transcription_session import CandidateRoute, TranscriptionSession
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            target = TrackState(
                1,
                [Note(55, 80, 0.0, 300.0, 0)],
                0,
                False,
                "target",
                0x0B,
            )
            other = TrackState(2, [], 0, False, "other", 0x0B)
            candidate = TranscriptionCandidate(
                60,
                90,
                500.0,
                240.0,
                0.95,
                candidate_id="draft-candidate",
            )
            preexisting = TranscriptionCandidate(
                62,
                88,
                900.0,
                180.0,
                0.92,
                candidate_id="preexisting-route",
            )

            window = MidiToBdoWindow()
            autosaves = []
            window._autosave_project = (
                lambda reason, *_args, **_kwargs: autosaves.append(reason)
            )
            window._flush_autosave = lambda: None
            window.tracks = [target, other]
            window.timeline.set_tracks(window.tracks)
            window.transcription_session = TranscriptionSession(
                [candidate, preexisting],
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            window.transcription_session.route_to_track(
                2,
                ["preexisting-route"],
            )
            window.transcription_session.set_selection(["draft-candidate"])
            pending_before = window.transcription_session.state.pending_routes
            original_notes = list(target.notes)

            editor = MidiNoteEditorDialog(
                window,
                target,
                120,
                4,
                transcription_mode=True,
            )
            editor.show()
            app.processEvents()
            editor._sync_shared_transcription_projection()
            editor.accept_transcription_candidates()

            route = CandidateRoute("draft-candidate", 1)
            assert len(editor.canvas.notes) == len(original_notes) + 1
            assert editor.staged_primary_routes == {route}
            assert list(target.notes) == original_notes
            assert window.transcription_session.state.pending_routes == pending_before
            assert window.transcription_session.state.applied_routes == ()
            assert autosaves == []

            # One local command owns both the draft note and its staged route.
            editor.undo()
            assert list(editor.canvas.notes) == original_notes
            assert editor.staged_primary_routes == set()
            editor.redo()
            assert len(editor.canvas.notes) == len(original_notes) + 1
            assert editor.staged_primary_routes == {route}
            assert list(target.notes) == original_notes

            editor.reject()
            app.processEvents()
            assert editor.result() == QDialog.Rejected
            assert list(target.notes) == original_notes
            assert window.transcription_session.state.pending_routes == pending_before
            assert window.transcription_session.state.applied_routes == ()
            assert autosaves == []

            editor.deleteLater()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_multitrack_apply_is_atomic_idempotent_and_undoable(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QDialog

            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.transcription.bdo_transcription_session import CandidateRoute, TranscriptionSession
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                TrackState,
            )

            app = QApplication([])
            current = TrackState(1, [], 0, False, "current", 0x0B)
            second = TrackState(2, [], 0, False, "second", 0x0B)
            third = TrackState(3, [], 0, False, "third", 0x0B)
            candidate = TranscriptionCandidate(
                60,
                91,
                100.0,
                220.0,
                0.96,
                candidate_id="shared-candidate",
            )
            review_candidate = TranscriptionCandidate(
                72,
                70,
                1800.0,
                160.0,
                0.20,
                candidate_id="review-only",
            )

            window = MidiToBdoWindow()
            autosaves = []
            window._autosave_project = (
                lambda reason, *_args, **_kwargs: autosaves.append(reason)
            )
            window._flush_autosave = lambda: None
            window._stop_preview = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            window.tracks = [current, second, third]
            window.timeline.set_tracks(window.tracks)
            window.reference_audio_offset_ms = 125.0
            window.transcription_session = TranscriptionSession(
                [candidate, review_candidate],
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            window.transcription_session.set_selection(["shared-candidate"])

            editor = MidiNoteEditorDialog(
                window,
                current,
                120,
                4,
                transcription_mode=True,
            )
            editor.show()
            app.processEvents()
            editor._sync_shared_transcription_projection()
            editor.accept_transcription_candidates()
            editor._stage_transcription_copy(2)
            editor._stage_transcription_copy(3)

            expected_routes = {
                CandidateRoute("shared-candidate", 1),
                CandidateRoute("shared-candidate", 2),
                CandidateRoute("shared-candidate", 3),
            }
            assert editor.staged_primary_routes == {
                CandidateRoute("shared-candidate", 1)
            }
            assert editor.staged_copy_routes == expected_routes.difference(
                editor.staged_primary_routes
            )
            assert all(track.notes == [] for track in window.tracks)

            # Seed both sides of both review histories while keeping the
            # selected route eligible. Formal Apply must cross into project
            # history and clear every stale review snapshot.
            window._start_transcription_assist_analysis = lambda: None
            window._set_assist_key_override(
                0, "major", manual=True, locked=True
            )
            window._set_assist_key_override(
                9, "minor", manual=True, locked=False
            )
            window._undo_transcription_review()
            session = window.transcription_session
            session.reject(("review-only",))
            session.restore_rejected(("review-only",))
            assert session.undo()
            assert session.commands.can_undo
            assert session.commands.can_redo
            assert window.transcription_assist_review_undo
            assert window.transcription_assist_review_redo
            assert window.transcription_review_action_undo
            assert window.transcription_review_action_redo
            autosaves.clear()

            report = editor.apply_notes()
            assert report is not None
            assert report.project_changed
            assert report.created_count == 3
            assert set(report.created_routes) == expected_routes
            assert editor.staged_primary_routes == set()
            assert editor.staged_copy_routes == set()
            assert len(window.project_commands._undo) == 1
            assert autosaves == ["transcription editor apply"]
            assert set(
                window.transcription_session.state.applied_routes
            ) == expected_routes
            assert window.transcription_session.state.pending_routes == ()
            assert not window.transcription_session.commands.can_undo
            assert not window.transcription_session.commands.can_redo
            assert not window.transcription_assist_review_undo
            assert not window.transcription_assist_review_redo
            assert not window.transcription_review_action_undo
            assert not window.transcription_review_action_redo
            assert not window._can_undo_transcription_review()
            assert not window._can_redo_transcription_review()
            for track in window.tracks:
                assert len(track.notes) == 1
                note = track.notes[0]
                assert (note.pitch, note.start, note.dur, note.ntype) == (
                    60,
                    225.0,
                    220.0,
                    0,
                )

            # Repeated Apply and the Apply performed by OK are both no-ops.
            second_report = editor.apply_notes()
            assert second_report is not None
            assert not second_report.project_changed
            assert len(window.project_commands._undo) == 1
            assert autosaves == ["transcription editor apply"]
            assert all(len(track.notes) == 1 for track in window.tracks)

            editor.accept_with_apply()
            app.processEvents()
            assert editor.result() == QDialog.Accepted
            assert len(window.project_commands._undo) == 1
            assert autosaves == ["transcription editor apply"]
            assert all(len(track.notes) == 1 for track in window.tracks)

            # Project undo/redo restores all tracks and the review sidecar as
            # one transaction. Snapshot restore replaces TrackState objects, so
            # assertions deliberately resolve them again by track id.
            window.setFocus()
            app.processEvents()
            window._undo_project()
            assert all(track.notes == [] for track in window.tracks)
            assert window.transcription_session.state.applied_routes == ()
            assert len(window.project_commands._undo) == 0
            assert len(window.project_commands._redo) == 1

            window.setFocus()
            app.processEvents()
            window._redo_project()
            assert len(window.project_commands._undo) == 1
            assert len(window.project_commands._redo) == 0
            assert set(
                window.transcription_session.state.applied_routes
            ) == expected_routes
            restored_by_id = {
                track.track_id: track for track in window.tracks
            }
            assert set(restored_by_id) == {1, 2, 3}
            for track in restored_by_id.values():
                assert len(track.notes) == 1
                note = track.notes[0]
                assert (note.pitch, note.start, note.dur, note.ntype) == (
                    60,
                    225.0,
                    220.0,
                    0,
                )

            editor.deleteLater()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_fragment_profile_is_independent_and_respects_staging_lock(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.transcription.bdo_transcription_session import (
                CandidateAnnotation,
                CandidateRoute,
                TranscriptionSession,
            )
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            autosaves = []
            window._autosave_project = (
                lambda reason, *_args, **_kwargs: autosaves.append(reason)
            )
            window._flush_autosave = lambda: None
            track = TrackState(1, [], 0, False, "lead", 0x0B)
            candidate = TranscriptionCandidate(
                60,
                50,
                100.0,
                60.0,
                0.25,
                candidate_id="fragment",
            )
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            window.transcription_session = TranscriptionSession(
                [candidate],
                annotations=[
                    CandidateAnnotation(
                        "fragment",
                        flags=frozenset(
                            {"review_fragment", "severe_fragment"}
                        ),
                    )
                ],
            )
            editor = MidiNoteEditorDialog(
                window,
                track,
                120,
                4,
                transcription_mode=True,
            )
            window.active_transcription_editor = editor
            editor.show()
            app.processEvents()

            assert window.transcription_session.state.sensitivity == "balanced"
            assert window.transcription_session.state.cleanup_profile == "preserve"
            assert editor.transcription_panel.cleanup_profile == "preserve"
            clean_index = editor.transcription_panel.cleanup_profile_combo.findData(
                "clean"
            )
            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                clean_index
            )
            app.processEvents()
            assert window.transcription_session.state.cleanup_profile == "clean"
            assert window.transcription_session.state.sensitivity == "balanced"
            assert autosaves == ["transcription fragment cleanup"]

            warnings = []
            editor.warn_transcription_staging_blocked = (
                lambda: warnings.append(True)
            )
            editor.staged_primary_routes = {
                CandidateRoute("fragment", 1)
            }
            preserve_index = (
                editor.transcription_panel.cleanup_profile_combo.findData(
                    "preserve"
                )
            )
            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                preserve_index
            )
            app.processEvents()
            assert warnings == [True]
            assert window.transcription_session.state.cleanup_profile == "clean"
            assert editor.transcription_panel.cleanup_profile == "clean"

            editor.staged_primary_routes.clear()
            window._select_suspected_transcription_fragments()
            assert window.transcription_session.state.selected_candidate_ids == {
                "fragment"
            }
            assert "1" in editor.transcription_panel.status_label.text()

            editor.close()
            window.active_transcription_editor = None
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def _obsolete_test_fragment_profile_cached_redecode_projects_real_actions_without_apply(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.transcription.bdo_transcription import (
                TranscriptionCandidate,
                TranscriptionCandidateAnnotation,
                TranscriptionPostprocessReport,
                TranscriptionResult,
            )
            from bdo_music_composer.transcription.bdo_transcription_session import (
                TranscriptionSession,
                TranscriptionSessionState,
            )
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window._flush_autosave = lambda: None
            window._start_transcription_assist_analysis = lambda: None
            formal = Note(55, 80, 0.0, 300.0, 0)
            track = TrackState(1, [formal], 0, False, "lead", 0x0B)
            source_a = TranscriptionCandidate(
                60, 70, 100.0, 90.0, 0.42, candidate_id="source-a"
            )
            source_b = TranscriptionCandidate(
                60, 68, 150.0, 90.0, 0.35, candidate_id="source-b"
            )
            merged = TranscriptionCandidate(
                60, 70, 100.0, 140.0, 0.42, candidate_id="merged"
            )
            intact = TranscriptionCandidate(
                64, 82, 400.0, 180.0, 0.88, candidate_id="intact"
            )
            hidden = TranscriptionCandidate(
                67, 45, 760.0, 45.0, 0.18, candidate_id="hidden"
            )

            def report(profile, candidates, *, suppressed=()):
                annotations = [
                    TranscriptionCandidateAnnotation(
                        candidate_id=candidate.candidate_id,
                        flags=(),
                        lineage_ids=(candidate.candidate_id,),
                        disposition="kept",
                    )
                    for candidate in candidates
                ]
                annotations[0] = TranscriptionCandidateAnnotation(
                    candidate_id="merged",
                    flags=("automatic_merge",),
                    lineage_ids=("source-a", "source-b"),
                    disposition="merged",
                )
                annotations.extend(
                    TranscriptionCandidateAnnotation(
                        candidate_id=candidate.candidate_id,
                        flags=("review_fragment", "severe_fragment"),
                        lineage_ids=(candidate.candidate_id,),
                        disposition="suppressed",
                    )
                    for candidate in suppressed
                )
                return TranscriptionPostprocessReport(
                    profile=profile,
                    version="ui-integration",
                    raw_candidate_count=4,
                    output_candidate_count=len(candidates),
                    exact_duplicate_count=0,
                    nms_removed_count=0,
                    automatic_merge_count=1,
                    suspected_fragment_count=len(suppressed),
                    severe_fragment_count=len(suppressed),
                    density_short_count=len(suppressed),
                    pitch_flicker_count=0,
                    suppressed_count=len(suppressed),
                    annotations=tuple(annotations),
                    suppressed_candidates=tuple(suppressed),
                    automatic_actions_enabled=True,
                )

            balanced_candidates = (merged, intact, hidden)
            clean_candidates = (merged, intact)
            results = {
                "preserve": TranscriptionResult(
                    (source_a, source_b, intact, hidden),
                    "shared-evidence",
                    postprocess_report=TranscriptionPostprocessReport(
                        profile="preserve",
                        version="ui-integration",
                        raw_candidate_count=4,
                        output_candidate_count=4,
                        exact_duplicate_count=0,
                        nms_removed_count=0,
                        automatic_merge_count=0,
                        suspected_fragment_count=1,
                        severe_fragment_count=1,
                        density_short_count=1,
                        pitch_flicker_count=0,
                        suppressed_count=0,
                        annotations=tuple(
                            TranscriptionCandidateAnnotation(
                                candidate_id=candidate.candidate_id,
                                flags=(
                                    ("review_fragment", "severe_fragment")
                                    if candidate.candidate_id == "hidden"
                                    else ()
                                ),
                                lineage_ids=(candidate.candidate_id,),
                                disposition="kept",
                            )
                            for candidate in (
                                source_a,
                                source_b,
                                intact,
                                hidden,
                            )
                        ),
                        automatic_actions_enabled=False,
                    ),
                ),
                "balanced": TranscriptionResult(
                    balanced_candidates,
                    "shared-evidence",
                    postprocess_report=report(
                        "balanced",
                        balanced_candidates,
                    ),
                ),
                "clean": TranscriptionResult(
                    clean_candidates,
                    "shared-evidence",
                    postprocess_report=report(
                        "clean",
                        clean_candidates,
                        suppressed=(hidden,),
                    ),
                ),
            }
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            window.transcription_session = TranscriptionSession(
                (source_a, source_b, intact, hidden),
                state=TranscriptionSessionState(
                    cache_key="shared-evidence",
                    cleanup_profile="preserve",
                ),
            )
            editor = MidiNoteEditorDialog(
                window,
                track,
                120,
                4,
                transcription_mode=True,
            )
            window.active_transcription_editor = editor
            editor.show()
            app.processEvents()
            original_formal_notes = tuple(track.notes)
            redecode_calls = []

            def fake_restore_cached_transcription(
                *,
                status=None,
                cleanup_profile=None,
                rollback_cleanup_profile=None,
            ):
                profile = str(
                    cleanup_profile
                    or window.transcription_session.state.cleanup_profile
                )
                redecode_calls.append((profile, status))
                window.workspace_transcription_generation += 1
                generation = window.workspace_transcription_generation
                if rollback_cleanup_profile is not None:
                    window._pending_transcription_cleanup_profile = (
                        generation,
                        str(rollback_cleanup_profile),
                        profile,
                    )
                QTimer.singleShot(
                    0,
                    lambda: window._workspace_transcription_succeeded(
                        generation,
                        results[profile],
                        False,
                        True,
                    ),
                )
                return generation

            window._restore_cached_transcription = (
                fake_restore_cached_transcription
            )

            balanced_index = (
                editor.transcription_panel.cleanup_profile_combo.findData(
                    "balanced"
                )
            )
            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                balanced_index
            )
            assert window.transcription_session.state.cleanup_profile == (
                "preserve"
            )
            app.processEvents()
            assert redecode_calls[0][0] == "balanced"
            assert "缓存证据重新解码" in redecode_calls[0][1]
            assert {
                "merged", "intact", "hidden"
            } == set(editor.canvas._transcription_candidate_ids)
            assert "实验性自动整理" in (
                editor.transcription_panel.status_label.text()
            ), editor.transcription_panel.status_label.text()
            assert "自动合并 1" in editor.transcription_panel.status_label.text()
            assert tuple(track.notes) == original_formal_notes

            clean_index = (
                editor.transcription_panel.cleanup_profile_combo.findData(
                    "clean"
                )
            )
            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                clean_index
            )
            app.processEvents()
            assert redecode_calls[-1][0] == "clean"
            assert set(editor.canvas._transcription_candidate_ids) == {
                "merged", "intact"
            }
            assert "已隐藏 1" in editor.transcription_panel.status_label.text()
            assert not editor.canvas._suppressed_candidate_ids
            editor.transcription_panel.set_advanced_controls_expanded(True)
            assert editor.transcription_panel.candidate_layer_button.isVisible()
            assert not editor.transcription_panel.show_suppressed_checkbox.isVisible()

            editor.transcription_panel.show_suppressed_checkbox.setChecked(True)
            app.processEvents()
            assert set(editor.canvas._transcription_candidate_ids) == {
                "merged", "intact", "hidden"
            }
            assert editor.canvas._suppressed_candidate_ids == {"hidden"}
            assert tuple(track.notes) == original_formal_notes
            assert tuple(editor.canvas.notes) == original_formal_notes

            editor.transcription_panel.show_suppressed_checkbox.setChecked(
                False
            )
            preserve_index = (
                editor.transcription_panel.cleanup_profile_combo.findData(
                    "preserve"
                )
            )
            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                preserve_index
            )
            app.processEvents()
            assert redecode_calls[-1][0] == "preserve"
            assert window.transcription_session.state.cleanup_profile == (
                "preserve"
            )
            assert set(editor.canvas._transcription_candidate_ids) == {
                "source-a", "source-b", "intact", "hidden"
            }
            assert not editor.canvas._suppressed_candidate_ids
            assert tuple(track.notes) == original_formal_notes
            assert tuple(editor.canvas.notes) == original_formal_notes

            editor.close()
            window.active_transcription_editor = None
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)

    def test_fragment_profile_cache_switch_rolls_back_on_failure_or_cancel(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
            from bdo_music_composer.transcription.bdo_transcription_session import (
                TranscriptionSession,
                TranscriptionSessionState,
            )
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            window._flush_autosave = lambda: None
            formal = Note(55, 80, 0.0, 300.0, 0)
            track = TrackState(1, [formal], 0, False, "lead", 0x0B)
            candidate = TranscriptionCandidate(
                60,
                70,
                100.0,
                90.0,
                0.42,
                candidate_id="candidate",
            )
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            window.transcription_session = TranscriptionSession(
                (candidate,),
                state=TranscriptionSessionState(
                    cache_key="shared-evidence",
                    cleanup_profile="preserve",
                ),
            )
            editor = MidiNoteEditorDialog(
                window,
                track,
                120,
                4,
                transcription_mode=True,
            )
            window.active_transcription_editor = editor
            editor.show()
            app.processEvents()
            generations = []

            def fake_restore_cached_transcription(
                *,
                status=None,
                cleanup_profile=None,
                rollback_cleanup_profile=None,
            ):
                del status
                window.workspace_transcription_generation += 1
                generation = window.workspace_transcription_generation
                requested = str(cleanup_profile)
                window._pending_transcription_cleanup_profile = (
                    generation,
                    str(rollback_cleanup_profile),
                    requested,
                )
                generations.append(generation)
                return generation

            window._restore_cached_transcription = (
                fake_restore_cached_transcription
            )
            clean_index = (
                editor.transcription_panel.cleanup_profile_combo.findData(
                    "clean"
                )
            )

            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                clean_index
            )
            generation = generations[-1]
            assert window.transcription_session.state.cleanup_profile == (
                "preserve"
            )
            assert editor.transcription_panel.cleanup_profile == "clean"
            window._workspace_transcription_failed(
                generation,
                "broken cache",
                quiet=True,
            )
            assert window.transcription_session.state.cleanup_profile == (
                "preserve"
            )
            assert editor.transcription_panel.cleanup_profile == "preserve"
            assert window.transcription_session.candidates == (candidate,)
            assert tuple(track.notes) == (formal,)
            assert "已恢复原档位" in window.transcription_ui_status

            editor.transcription_panel.cleanup_profile_combo.setCurrentIndex(
                clean_index
            )
            generation = generations[-1]
            assert editor.transcription_panel.cleanup_profile == "clean"
            window._workspace_transcription_cancelled(generation)
            assert window.transcription_session.state.cleanup_profile == (
                "preserve"
            )
            assert editor.transcription_panel.cleanup_profile == "preserve"
            assert window.transcription_session.candidates == (candidate,)
            assert tuple(track.notes) == (formal,)
            assert "已恢复原档位" in window.transcription_ui_status

            editor.close()
            window.active_transcription_editor = None
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assert_offscreen_success(completed)


if __name__ == "__main__":
    unittest.main()
