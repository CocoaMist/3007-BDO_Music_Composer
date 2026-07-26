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


class TranscriptionEditorCommitUiTests(unittest.TestCase):
    def test_recommended_new_track_is_part_of_one_atomic_apply(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_session import (
                CandidateRoute,
                TranscriptionEditorCommit,
                TranscriptionSession,
            )
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._stop_preview = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            window._autosave_project = lambda *_args, **_kwargs: None
            current = TrackState(
                1, [], 0, False, "current", 0x0B,
            )
            window.tracks = [current]
            window.timeline.set_tracks(window.tracks)
            candidate = TranscriptionCandidate(
                60,
                92,
                500.0,
                240.0,
                0.91,
                candidate_id="new-track-note",
            )
            window.transcription_session = TranscriptionSession(
                (candidate,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            route = CandidateRoute("new-track-note", 9)
            request = TranscriptionEditorCommit(
                current_track_id=1,
                draft_notes=(),
                copy_routes=(route,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
                new_track_specs=((9, 0x0B),),
            )

            report = window._commit_note_editor(request)
            assert report is not None and report.project_changed
            assert report.created_routes == (route,)
            assert len(window.tracks) == 2
            created = next(track for track in window.tracks if track.track_id == 9)
            assert created.bdo_instrument_id == 0x0B
            assert [(note.pitch, note.start, note.ntype) for note in created.notes] == [
                (60, 500.0, 0)
            ]
            assert len(window.project_commands._undo) == 1
            assert window.transcription_session.state.applied_routes == (route,)

            window._undo_project()
            assert [track.track_id for track in window.tracks] == [1]
            assert window.transcription_session.state.applied_routes == ()
            window._redo_project()
            assert [track.track_id for track in window.tracks] == [1, 9]
            recreated = next(track for track in window.tracks if track.track_id == 9)
            assert [(note.pitch, note.start) for note in recreated.notes] == [
                (60, 500.0)
            ]
            assert window.transcription_session.state.applied_routes == (route,)

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

    def test_three_track_commit_has_one_snapshot_and_is_idempotent(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_session import (
                CandidateRoute,
                TranscriptionEditorCommit,
                TranscriptionSession,
            )
            from pyside_bdo_gui import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._stop_preview = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            autosaves = []
            window._autosave_project = (
                lambda reason, **kwargs: autosaves.append((reason, kwargs))
            )
            window.reference_audio_offset_ms = 150.0

            current = TrackState(
                1,
                [Note(55, 70, 0.0, 100.0, 4)],
                0,
                False,
                "current",
                0x0B,
                notes_optimized=True,
            )
            second = TrackState(
                2,
                [Note(57, 75, 20.0, 120.0, 0)],
                0,
                False,
                "second",
                0x0B,
                notes_optimized=True,
            )
            third = TrackState(
                3,
                [],
                0,
                False,
                "third",
                0x0B,
                notes_optimized=True,
            )
            window.tracks = [current, second, third]
            window.timeline.set_tracks(window.tracks)

            candidates = (
                TranscriptionCandidate(
                    60, 90, 100.0, 200.0, 0.9, candidate_id="primary"
                ),
                TranscriptionCandidate(
                    62, 91, 200.0, 210.0, 0.9, candidate_id="copy-second"
                ),
                TranscriptionCandidate(
                    64, 92, 300.0, 220.0, 0.9, candidate_id="copy-third"
                ),
            )
            window.transcription_session = TranscriptionSession(
                candidates,
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            request = TranscriptionEditorCommit(
                current_track_id=1,
                draft_notes=(
                    Note(55, 70, 0.0, 100.0, 4),
                    Note(60, 90, 250.0, 200.0, 0),
                ),
                primary_routes=(CandidateRoute("primary", 1),),
                copy_routes=(
                    CandidateRoute("copy-second", 2),
                    CandidateRoute("copy-third", 3),
                ),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )

            first = window._commit_note_editor(request)
            assert first is not None and first.project_changed
            assert first.created_routes == (
                CandidateRoute("copy-second", 2),
                CandidateRoute("copy-third", 3),
                CandidateRoute("primary", 1),
            )
            assert first.satisfied_routes == ()
            assert window.transcription_session.state.pending_routes == ()
            assert window.transcription_session.state.applied_routes == (
                CandidateRoute("copy-second", 2),
                CandidateRoute("copy-third", 3),
                CandidateRoute("primary", 1),
            )
            assert [(note.pitch, note.start) for note in current.notes] == [
                (55, 0.0),
                (60, 250.0),
            ]
            assert [(note.pitch, note.start) for note in second.notes] == [
                (57, 20.0),
                (62, 350.0),
            ]
            assert [(note.pitch, note.start) for note in third.notes] == [
                (64, 450.0),
            ]
            assert not current.notes_optimized
            assert not second.notes_optimized
            assert not third.notes_optimized
            assert len(window.project_commands._undo) == 1
            assert len(autosaves) == 1
            assert autosaves[0][0] == "transcription editor apply"
            assert autosaves[0][1] == {"immediate": True}

            # The one snapshot contains every pre-commit track and the
            # pre-commit sidecar, so project Undo can restore the batch.
            before = window.project_commands._undo[0]
            restored = before.restored_tracks()
            assert [len(track.notes) for track in restored] == [1, 1, 0]
            restored_review = before.restored_transcription_state()
            assert restored_review["pending_routes"] == []
            assert restored_review["applied_routes"] == []

            second_apply = window._commit_note_editor(request)
            assert second_apply is not None
            assert not second_apply.project_changed
            assert second_apply.created_routes == ()
            assert second_apply.satisfied_routes == (
                CandidateRoute("copy-second", 2),
                CandidateRoute("copy-third", 3),
                CandidateRoute("primary", 1),
            )
            assert len(window.project_commands._undo) == 1
            assert len(autosaves) == 1
            assert len(second.notes) == 2
            assert len(third.notes) == 1

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

    def test_local_failures_stay_local_old_pending_survives_and_offset_is_once(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_session import (
                CandidateRoute,
                TranscriptionEditorCommit,
                TranscriptionSession,
            )
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

            app = QApplication([])
            for offset_ms in (175.0, -125.0):
                window = MidiToBdoWindow()
                window._stop_preview = lambda *_args, **_kwargs: None
                window.show_toast = lambda *_args, **_kwargs: None
                autosaves = []
                window._autosave_project = (
                    lambda reason, **kwargs: autosaves.append(
                        (reason, kwargs)
                    )
                )
                window.reference_audio_offset_ms = offset_ms

                current = TrackState(
                    1, [], 0, False, "current", 0x0B
                )
                target = TrackState(
                    2, [], 0, False, "target", 0x0B
                )
                window.tracks = [current, target]
                window.timeline.set_tracks(window.tracks)

                candidates = (
                    TranscriptionCandidate(
                        60,
                        90,
                        500.0,
                        200.0,
                        0.9,
                        candidate_id="valid-copy",
                    ),
                    TranscriptionCandidate(
                        100,
                        90,
                        600.0,
                        200.0,
                        0.9,
                        candidate_id="invalid-local",
                    ),
                    TranscriptionCandidate(
                        65,
                        90,
                        700.0,
                        200.0,
                        0.9,
                        candidate_id="orphan-local",
                    ),
                    TranscriptionCandidate(
                        67,
                        90,
                        800.0,
                        200.0,
                        0.9,
                        candidate_id="old-pending",
                    ),
                )
                session = TranscriptionSession(
                    candidates,
                    cache_key="cache-key",
                    analysis_fingerprint="audio-fingerprint",
                )
                old_pending = CandidateRoute("old-pending", 777)
                session.route_to_track(
                    old_pending.track_id,
                    [old_pending.candidate_id],
                )
                window.transcription_session = session

                valid = CandidateRoute("valid-copy", 2)
                invalid = CandidateRoute("invalid-local", 2)
                orphan_local = CandidateRoute("orphan-local", 999)
                request = TranscriptionEditorCommit(
                    current_track_id=1,
                    draft_notes=(),
                    copy_routes=(valid, invalid, orphan_local),
                    cache_key="cache-key",
                    analysis_fingerprint="audio-fingerprint",
                )
                report = window._commit_note_editor(request)

                assert report is not None and report.project_changed
                assert report.created_routes == (valid,)
                assert report.invalid_routes == (invalid,)
                assert report.orphaned_routes == (
                    old_pending,
                    orphan_local,
                )
                # Only dialog-local failures remain staged/unresolved.
                assert report.unresolved_routes == (invalid, orphan_local)
                assert report.blocking_unresolved == (
                    invalid,
                    old_pending,
                    orphan_local,
                )
                # Local failures never leak into schema pending. The orphaned
                # route that was already persisted remains pending.
                assert session.state.pending_routes == (old_pending,)
                assert session.state.applied_routes == (valid,)
                assert invalid not in session.state.pending_routes
                assert orphan_local not in session.state.pending_routes

                assert len(target.notes) == 1
                note = target.notes[0]
                expected_start = 500.0 + offset_ms
                assert note.start == expected_start
                assert note.start != 500.0 + 2.0 * offset_ms
                assert (note.pitch, note.vel, note.dur, note.ntype) == (
                    60,
                    90,
                    200.0,
                    0,
                )
                assert len(window.project_commands._undo) == 1
                assert len(autosaves) == 1

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

    def test_negative_project_time_keeps_cross_track_pending_fail_closed(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_session import (
                CandidateRoute,
                TranscriptionEditorCommit,
                TranscriptionSession,
            )
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._stop_preview = lambda *_args, **_kwargs: None
            window._autosave_project = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            window.reference_audio_offset_ms = -500.0
            current = TrackState(1, [], 0, False, "current", 0x0B)
            target = TrackState(2, [], 0, False, "target", 0x0B)
            window.tracks = [current, target]
            window.timeline.set_tracks(window.tracks)
            candidate = TranscriptionCandidate(
                60,
                90,
                100.0,
                200.0,
                0.9,
                candidate_id="before-project-zero",
            )
            session = TranscriptionSession(
                (candidate,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            route = CandidateRoute("before-project-zero", 2)
            session.route_to_track(2, (candidate.candidate_id,))
            window.transcription_session = session
            request = TranscriptionEditorCommit(
                current_track_id=1,
                draft_notes=(),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )

            report = window._commit_note_editor(request)
            assert report is not None
            assert not report.project_changed
            assert report.invalid_routes == (route,)
            assert report.blocking_unresolved == (route,)
            assert session.state.pending_routes == (route,)
            assert session.state.applied_routes == ()
            assert target.notes == []
            assert len(window.project_commands._undo) == 0

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

    def test_rejected_top3_group_cannot_stage_or_cross_commit_boundary(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_instruments import (
                InstrumentMatchAnalysis,
                VoiceGroup,
            )
            from bdo_transcription_session import (
                CandidateRoute,
                TranscriptionEditorCommit,
                TranscriptionSession,
            )
            from pyside_bdo_gui import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window._stop_preview = lambda *_args, **_kwargs: None
            window._autosave_project = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            current = TrackState(1, [], 0, False, "current", 0x0B)
            target = TrackState(2, [], 0, False, "target", 0x0B)
            window.tracks = [current, target]
            window.timeline.set_tracks(window.tracks)
            candidate = TranscriptionCandidate(
                60,
                90,
                500.0,
                200.0,
                0.9,
                candidate_id="rejected",
            )
            session = TranscriptionSession(
                (candidate,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            session.reject(("rejected",))
            window.transcription_session = session
            window.instrument_match_analysis = InstrumentMatchAnalysis(
                "match-cache",
                "",
                (
                    VoiceGroup(
                        "voice",
                        ("rejected",),
                        500.0,
                        700.0,
                        "primary_melody",
                        0.9,
                    ),
                ),
                (),
            )
            editor = MidiNoteEditorDialog(
                window,
                current,
                120,
                4,
                transcription_mode=True,
            )
            window.active_transcription_editor = editor

            # Top-3 group actions provide candidate-id overrides. Rejection
            # remains a hard gate even though selection/A-B is bypassed.
            editor._stage_voice_group_routes("voice", 2)
            editor._stage_new_voice_group_track("voice", 0x0B)
            assert editor.staged_primary_routes == set()
            assert editor.staged_copy_routes == set()
            assert editor.staged_new_track_specs == {}

            # A forged/stale editor payload cannot bypass project preflight.
            primary = CandidateRoute("rejected", 1)
            copy = CandidateRoute("rejected", 2)
            request = TranscriptionEditorCommit(
                current_track_id=1,
                draft_notes=(Note(60, 90, 500.0, 200.0, 0),),
                primary_routes=(primary,),
                copy_routes=(copy,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            report = window._commit_note_editor(request)
            assert report is not None
            assert not report.project_changed
            assert report.invalid_routes == (primary, copy)
            assert report.unresolved_routes == (primary, copy)
            assert report.applied_routes == ()
            assert current.notes == []
            assert target.notes == []
            assert session.state.applied_routes == ()
            assert len(window.project_commands._undo) == 0

            editor.deleteLater()
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

    def test_new_track_spec_collision_is_unresolved_not_existing_track_write(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_session import (
                CandidateRoute,
                TranscriptionEditorCommit,
                TranscriptionSession,
            )
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._stop_preview = lambda *_args, **_kwargs: None
            window._autosave_project = lambda *_args, **_kwargs: None
            window.show_toast = lambda *_args, **_kwargs: None
            current = TrackState(1, [], 0, False, "current", 0x0B)
            existing = TrackState(9, [], 0, False, "existing", 0x0B)
            window.tracks = [current, existing]
            window.timeline.set_tracks(window.tracks)
            candidate = TranscriptionCandidate(
                60,
                90,
                500.0,
                200.0,
                0.9,
                candidate_id="collision",
            )
            session = TranscriptionSession(
                (candidate,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
            )
            window.transcription_session = session
            route = CandidateRoute("collision", 9)
            request = TranscriptionEditorCommit(
                current_track_id=1,
                draft_notes=(),
                copy_routes=(route,),
                cache_key="cache-key",
                analysis_fingerprint="audio-fingerprint",
                new_track_specs=((9, 0x0B),),
            )

            report = window._commit_note_editor(request)
            assert report is not None
            assert not report.project_changed
            assert report.invalid_routes == (route,)
            assert report.unresolved_routes == (route,)
            assert report.applied_routes == ()
            assert [track.track_id for track in window.tracks] == [1, 9]
            assert existing.notes == []
            assert session.state.applied_routes == ()
            assert len(window.project_commands._undo) == 0

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

    def test_deleted_highest_track_id_is_not_reused_while_route_history_refs_it(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QMessageBox

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_session import CandidateRoute, TranscriptionSession
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

            app = QApplication([])
            for history_kind in ("pending", "applied"):
                window = MidiToBdoWindow()
                window._stop_preview = lambda *_args, **_kwargs: None
                window._autosave_project = lambda *_args, **_kwargs: None
                window.show_toast = lambda *_args, **_kwargs: None
                current = TrackState(0, [], 0, False, "current", 0x0B)
                highest = TrackState(9, [], 0, False, "highest", 0x0B)
                window.tracks = [current, highest]
                window.timeline.set_tracks(window.tracks)
                candidate = TranscriptionCandidate(
                    60,
                    90,
                    500.0,
                    200.0,
                    0.9,
                    candidate_id=history_kind,
                )
                session = TranscriptionSession((candidate,), cache_key="cache")
                route = CandidateRoute(history_kind, 9)
                session.route_to_track(9, (history_kind,))
                if history_kind == "applied":
                    session.commit_project_routes((route,))
                window.transcription_session = session

                window._select_track(highest)
                QMessageBox.question = (
                    lambda *_args, **_kwargs: QMessageBox.Yes
                )
                window._delete_selected_track()
                assert [track.track_id for track in window.tracks] == [0]
                window._create_track(0x0B)

                # max(current)+1 would incorrectly reuse 9. Route history
                # reserves it, so the new track is distinct and cannot become
                # the old pending/applied route's accidental target.
                assert [track.track_id for track in window.tracks] == [0, 10]
                created = window.tracks[-1]
                assert created.notes == []
                if history_kind == "pending":
                    assert session.state.pending_routes == (route,)
                    assert session.state.applied_routes == ()
                else:
                    assert session.state.pending_routes == ()
                    assert session.state.applied_routes == (route,)

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


if __name__ == "__main__":
    unittest.main()
