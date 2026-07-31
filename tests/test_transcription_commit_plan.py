from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

from bdo_midi import Note
from bdo_transcription import TranscriptionCandidate
from bdo_transcription_session import CandidateRoute
from transcription_commit_plan import (
    CommitCandidateRecord,
    CommitCandidateView,
    CommitPlanError,
    CommitPlanErrorCode,
    CommitPlanInput,
    CommitTrackView,
    plan_transcription_commit,
)


def _candidate(
    candidate_id: str,
    *,
    pitch: int = 60,
    velocity: int = 90,
    start_ms: float = 100.0,
    duration_ms: float = 200.0,
) -> TranscriptionCandidate:
    return TranscriptionCandidate(
        pitch,
        velocity,
        start_ms,
        duration_ms,
        0.9,
        candidate_id=candidate_id,
    )


def _track(
    track_id: int,
    notes: tuple[Note, ...] = (),
) -> CommitTrackView:
    return CommitTrackView(
        track_id=track_id,
        notes=notes,
        instrument_id=0x0B,
        marnian_synth_mode="basic",
        is_percussion=False,
        effective_transpose=0,
    )


def _request(
    *,
    draft_notes: tuple[Note, ...] = (),
    local_routes: tuple[CandidateRoute, ...] = (),
    pending_routes: tuple[CandidateRoute, ...] = (),
    applied_routes: tuple[CandidateRoute, ...] = (),
    candidates: tuple[TranscriptionCandidate, ...] = (),
    candidate_records: tuple[CommitCandidateRecord, ...] | None = None,
    tracks: tuple[CommitTrackView, ...] | None = None,
    rejected_candidate_ids: frozenset[str] = frozenset(),
    provisional_new_track_ids: frozenset[int] = frozenset(),
    request_cache_key: str = "cache-v1",
    request_fingerprint: str = "fingerprint-v1",
    session_cache_key: str = "cache-v1",
    session_fingerprint: str = "fingerprint-v1",
    reference_audio_offset_ms: float = 0.0,
) -> CommitPlanInput:
    return CommitPlanInput(
        current_track_id=1,
        draft_notes=draft_notes,
        local_routes=local_routes,
        pending_routes=pending_routes,
        applied_routes=applied_routes,
        rejected_candidate_ids=rejected_candidate_ids,
        candidates=(
            candidate_records
            if candidate_records is not None
            else tuple(
                CommitCandidateRecord.capture(
                    candidate.candidate_id,
                    candidate,
                )
                for candidate in candidates
            )
        ),
        tracks=tracks if tracks is not None else (_track(1),),
        failed_new_track_ids=frozenset(),
        provisional_new_track_ids=provisional_new_track_ids,
        request_cache_key=request_cache_key,
        request_fingerprint=request_fingerprint,
        session_cache_key=session_cache_key,
        session_fingerprint=session_fingerprint,
        reference_audio_offset_ms=reference_audio_offset_ms,
    )


class TranscriptionCommitPlanTests(unittest.TestCase):
    def test_stale_identity_does_not_commit_candidate_draft_note(self) -> None:
        existing = Note(55, 72, 10.0, 120.0, 0)
        stale_draft = Note(60, 90, 500.0, 240.0, 0)
        candidate = _candidate(
            "stale-candidate",
            start_ms=500.0,
            duration_ms=240.0,
        )
        route = CandidateRoute(candidate.candidate_id, 1)
        request = _request(
            draft_notes=(existing, stale_draft),
            local_routes=(route,),
            candidates=(candidate,),
            tracks=(_track(1, (existing,)),),
            request_fingerprint="stale-fingerprint",
        )

        plan = plan_transcription_commit(request)

        self.assertEqual(dict(plan.final_notes_by_track), {1: (existing,)})
        self.assertEqual(plan.unresolved_routes, (route,))
        self.assertEqual(plan.successful_routes, ())
        self.assertEqual(plan.final_applied_routes, ())
        self.assertFalse(plan.sidecar_changed)
        self.assertFalse(plan.project_changed)

    def test_existing_formal_note_satisfies_route_without_duplicate(self) -> None:
        candidate = _candidate("already-formal")
        route = CandidateRoute(candidate.candidate_id, 2)
        formal_note = Note(60, 41, 100.0, 200.0, 11)
        request = _request(
            local_routes=(route,),
            candidates=(candidate,),
            tracks=(_track(1), _track(2, (formal_note,))),
        )

        plan = plan_transcription_commit(request)

        self.assertEqual(plan.satisfied_routes, (route,))
        self.assertEqual(plan.created_routes, ())
        self.assertEqual(plan.successful_routes, (route,))
        self.assertEqual(plan.final_applied_routes, (route,))
        self.assertEqual(dict(plan.final_notes_by_track), {1: ()})
        self.assertEqual(request.tracks[1].notes, (formal_note,))

    def test_duplicate_matches_use_route_order_deterministically(self) -> None:
        first_candidate = _candidate("candidate-a")
        second_candidate = _candidate("candidate-b")
        first_route = CandidateRoute(first_candidate.candidate_id, 1)
        second_route = CandidateRoute(second_candidate.candidate_id, 1)
        only_draft_match = Note(60, 78, 100.0, 200.0, 0)
        reversed_request = _request(
            draft_notes=(only_draft_match,),
            local_routes=(second_route, first_route),
            candidates=(second_candidate, first_candidate),
        )
        ordered_request = _request(
            draft_notes=(only_draft_match,),
            local_routes=(first_route, second_route),
            candidates=(first_candidate, second_candidate),
        )

        reversed_plan = plan_transcription_commit(reversed_request)
        ordered_plan = plan_transcription_commit(ordered_request)

        self.assertEqual(reversed_plan, ordered_plan)
        self.assertEqual(reversed_plan.created_routes, (first_route,))
        self.assertEqual(reversed_plan.unresolved_routes, (second_route,))
        self.assertEqual(
            dict(reversed_plan.final_notes_by_track),
            {1: (only_draft_match,)},
        )

    def test_same_input_is_repeatable_and_remains_unchanged(self) -> None:
        candidate = _candidate(
            "repeatable-copy",
            pitch=64,
            velocity=103,
            start_ms=350.0,
            duration_ms=180.0,
        )
        route = CandidateRoute(candidate.candidate_id, 2)
        existing = Note(57, 66, 25.0, 110.0, 0)
        request = _request(
            local_routes=(route,),
            candidates=(candidate,),
            tracks=(_track(1), _track(2, (existing,))),
            reference_audio_offset_ms=75.0,
        )
        original = deepcopy(request)

        first = plan_transcription_commit(request)
        second = plan_transcription_commit(request)
        third = plan_transcription_commit(request)

        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(request, original)
        self.assertEqual(request.tracks[1].notes, (existing,))
        self.assertEqual(
            dict(first.final_notes_by_track)[2],
            (existing, Note(64, 103, 425.0, 180.0, 0)),
        )

    def test_creates_provisional_track_and_writes_across_tracks(self) -> None:
        existing_copy = _candidate(
            "existing-copy",
            pitch=62,
            velocity=91,
            start_ms=200.0,
            duration_ms=210.0,
        )
        new_copy = _candidate(
            "new-copy",
            pitch=64,
            velocity=92,
            start_ms=300.0,
            duration_ms=220.0,
        )
        existing_route = CandidateRoute(existing_copy.candidate_id, 2)
        new_route = CandidateRoute(new_copy.candidate_id, 9)
        current_note = Note(55, 70, 0.0, 100.0, 4)
        request = _request(
            draft_notes=(current_note,),
            local_routes=(new_route, existing_route),
            candidates=(new_copy, existing_copy),
            tracks=(
                _track(1, (current_note,)),
                _track(2),
                _track(9),
            ),
            provisional_new_track_ids=frozenset({9}),
            reference_audio_offset_ms=50.0,
        )

        plan = plan_transcription_commit(request)
        notes_by_track = dict(plan.final_notes_by_track)

        self.assertEqual(notes_by_track[1], (current_note,))
        self.assertEqual(notes_by_track[2], (Note(62, 91, 250.0, 210.0, 0),))
        self.assertEqual(notes_by_track[9], (Note(64, 92, 350.0, 220.0, 0),))
        self.assertEqual(plan.created_track_ids, (9,))
        self.assertEqual(plan.created_routes, (existing_route, new_route))
        self.assertEqual(plan.successful_routes, (existing_route, new_route))
        self.assertTrue(plan.sidecar_changed)
        self.assertTrue(plan.project_changed)

    def test_structural_input_errors_have_stable_codes(self) -> None:
        duplicate_tracks = _request(tracks=(_track(1), _track(1)))
        with self.assertRaises(CommitPlanError) as duplicate_error:
            plan_transcription_commit(duplicate_tracks)
        self.assertEqual(
            duplicate_error.exception.code,
            CommitPlanErrorCode.DUPLICATE_TRACK_ID,
        )

        unknown_new_track = _request(
            provisional_new_track_ids=frozenset({9})
        )
        with self.assertRaises(CommitPlanError) as provisional_error:
            plan_transcription_commit(unknown_new_track)
        self.assertEqual(
            provisional_error.exception.code,
            CommitPlanErrorCode.UNKNOWN_PROVISIONAL_TRACK,
        )

        with self.assertRaises(CommitPlanError) as candidate_error:
            CommitCandidateView.capture(
                "bad-candidate",
                SimpleNamespace(
                    pitch=60,
                    velocity="not-an-integer",
                    start_ms=0.0,
                    duration_ms=100.0,
                ),
            )
        self.assertEqual(
            candidate_error.exception.code,
            CommitPlanErrorCode.INVALID_CANDIDATE,
        )

    def test_malformed_candidate_only_blocks_routes_that_need_its_note(
        self,
    ) -> None:
        malformed = CommitCandidateRecord.capture(
            "malformed",
            SimpleNamespace(
                pitch=60,
                velocity="not-an-integer",
                start_ms=100.0,
                duration_ms=200.0,
            ),
        )
        manual_note = Note(67, 88, 400.0, 160.0, 0)

        orphan = CandidateRoute("malformed", 999)
        orphan_plan = plan_transcription_commit(_request(
            draft_notes=(manual_note,),
            pending_routes=(orphan,),
            candidate_records=(malformed,),
        ))
        self.assertEqual(orphan_plan.orphaned_routes, (orphan,))
        self.assertEqual(
            dict(orphan_plan.final_notes_by_track)[1],
            (manual_note,),
        )

        rejected = CandidateRoute("malformed", 1)
        rejected_plan = plan_transcription_commit(_request(
            draft_notes=(manual_note,),
            local_routes=(rejected,),
            candidate_records=(malformed,),
            rejected_candidate_ids=frozenset({"malformed"}),
        ))
        self.assertEqual(rejected_plan.invalid_routes, (rejected,))
        self.assertEqual(rejected_plan.unresolved_routes, (rejected,))
        self.assertEqual(
            dict(rejected_plan.final_notes_by_track)[1],
            (manual_note,),
        )

        stale = CandidateRoute("malformed", 2)
        stale_plan = plan_transcription_commit(_request(
            draft_notes=(manual_note,),
            local_routes=(stale,),
            candidate_records=(malformed,),
            tracks=(_track(1), _track(2)),
            request_fingerprint="stale",
        ))
        self.assertEqual(stale_plan.unresolved_routes, (stale,))
        self.assertEqual(
            dict(stale_plan.final_notes_by_track)[1],
            (manual_note,),
        )


if __name__ == "__main__":
    unittest.main()
