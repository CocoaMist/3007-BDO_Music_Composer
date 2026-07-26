from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
import json
import unittest
from unittest.mock import patch

from bdo_transcription_session import (
    CandidateAnnotation,
    CandidateRoute,
    CLEANUP_PROFILES,
    SENSITIVITY_PRESETS,
    StagedCandidateRoute,
    TranscriptionEditorCommit,
    TranscriptionEditorCommitReport,
    TranscriptionSession,
    TranscriptionSessionState,
    stable_candidate_id,
)


@dataclass(frozen=True)
class Candidate:
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float
    confidence: float = 0.8
    source: str = "test"
    candidate_id: str = ""


class TranscriptionSessionTests(unittest.TestCase):
    def candidate(self, name: str, start_ms: float, pitch: int = 60) -> Candidate:
        return Candidate(pitch, 90, start_ms, 100.0, candidate_id=name)

    def test_stable_candidate_id_fallback_is_deterministic_and_sensitive(self) -> None:
        candidate = Candidate(60, 90, 100.1234, 250.5, candidate_id="")
        first = stable_candidate_id(
            candidate, cache_key="cache-a", backend_id="backend-a"
        )
        second = stable_candidate_id(
            candidate, cache_key="cache-a", backend_id="backend-a"
        )
        changed = stable_candidate_id(
            candidate, cache_key="cache-b", backend_id="backend-a"
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertNotIn("100.1234", first)

    def test_stable_candidate_id_preserves_backend_id_after_time_projection(
        self,
    ) -> None:
        from bdo_transcription import (
            TranscriptionCandidate,
        )

        cache_key = "a" * 24
        candidate = TranscriptionCandidate(
            60, 90, 100.0, 250.0, 0.8, candidate_id="stable-backend-id"
        )
        projected = replace(candidate, start_ms=candidate.start_ms + 725.0)
        self.assertEqual(
            stable_candidate_id(
                projected, cache_key=cache_key, backend_id="ignored-fallback"
            ),
            "stable-backend-id",
        )

    def test_payload_is_lightweight_deterministic_and_tolerant(self) -> None:
        state = TranscriptionSessionState(
            cache_key="cache-key",
            analysis_fingerprint="audio-sha",
            region=(900.0, 100.0),
            analysis_mode="mixed_enhanced",
            sensitivity="conservative",
            selected_candidate_ids=frozenset({"b", "a"}),
            rejected_candidate_ids=frozenset({"z"}),
            pending_routes=(CandidateRoute("b", 2), CandidateRoute("a", 1)),
            applied_routes=(CandidateRoute("done", 4),),
        )
        payload = state.to_payload()
        self.assertEqual(payload["region"], {"start_ms": 100.0, "end_ms": 900.0})
        self.assertEqual(payload["selected_candidate_ids"], ["a", "b"])
        self.assertEqual(payload["analysis_mode"], "mixed_enhanced")
        self.assertEqual(payload["cleanup_profile"], "preserve")
        self.assertEqual(payload["version"], 4)
        self.assertEqual(
            payload["pending_routes"],
            [
                {"candidate_id": "a", "track_id": 1},
                {"candidate_id": "b", "track_id": 2},
            ],
        )
        self.assertNotIn("candidates", payload)
        self.assertNotIn("evidence", payload)
        self.assertEqual(
            TranscriptionSessionState.from_payload(
                json.loads(json.dumps(payload))
            ),
            state,
        )
        malformed = TranscriptionSessionState.from_payload(
            {
                "version": 1,
                "region": [float("nan"), 100],
                "sensitivity": "unexpected",
                "selected_candidate_ids": [None, "", "ok"],
                "pending_routes": [
                    {"candidate_id": "ok", "track_id": "3"},
                    {"candidate_id": "", "track_id": 2},
                ],
            }
        )
        self.assertIsNone(malformed.region)
        self.assertEqual(malformed.sensitivity, "balanced")
        self.assertEqual(malformed.selected_candidate_ids, frozenset({"ok"}))
        self.assertEqual(malformed.pending_routes, (CandidateRoute("ok", 3),))
        self.assertEqual(malformed.analysis_mode, "standard")
        self.assertEqual(malformed.cleanup_profile, "preserve")
        self.assertEqual(
            TranscriptionSessionState.from_payload(
                {"version": 2, "cleanup_profile": "clean"}
            ).cleanup_profile,
            "preserve",
        )
        self.assertEqual(
            TranscriptionSessionState.from_payload(
                {"version": 3, "cleanup_profile": "clean"}
            ).cleanup_profile,
            "preserve",
        )
        self.assertEqual(
            TranscriptionSessionState.from_payload(
                {"version": 4, "cleanup_profile": "clean"}
            ).cleanup_profile,
            "clean",
        )
        self.assertEqual(
            TranscriptionSessionState.from_payload({"version": 999}),
            TranscriptionSessionState(),
        )

    def test_candidate_annotation_round_trips_without_candidate_payload(self) -> None:
        annotation = CandidateAnnotation(
            "candidate-a",
            flags=frozenset({"short-fragment", "low-energy"}),
            lineage_ids=frozenset({"source-b", "source-a"}),
            disposition="kept",
        )

        self.assertEqual(
            annotation.to_payload(),
            {
                "candidate_id": "candidate-a",
                "flags": ["low-energy", "short-fragment"],
                "lineage_ids": [
                    "candidate-a",
                    "source-a",
                    "source-b",
                ],
                "disposition": "kept",
            },
        )
        self.assertEqual(
            CandidateAnnotation.from_payload(
                json.loads(json.dumps(annotation.to_payload()))
            ),
            annotation,
        )

    def test_analysis_mode_is_validated_and_mutable(self) -> None:
        session = TranscriptionSession()
        self.assertEqual(session.state.analysis_mode, "mixed_enhanced")
        self.assertEqual(
            session.set_analysis_mode("mixed_enhanced"),
            "mixed_enhanced",
        )
        self.assertEqual(
            session.state.analysis_mode,
            "mixed_enhanced",
        )
        with self.assertRaises(ValueError):
            session.set_analysis_mode("unknown")
        self.assertEqual(
            TranscriptionSessionState(
                analysis_mode="unknown"
            ).analysis_mode,
            "mixed_enhanced",
        )
        self.assertEqual(session.state.cleanup_profile, "preserve")
        self.assertEqual(
            session.set_cleanup_profile("preserve"),
            "preserve",
        )
        self.assertEqual(session.state.cleanup_profile, "preserve")
        self.assertEqual(session.set_cleanup_profile("balanced"), "balanced")
        self.assertEqual(
            TranscriptionSessionState.from_payload(
                session.state.to_payload()
            ).cleanup_profile,
            "balanced",
        )
        self.assertEqual(
            CLEANUP_PROFILES,
            frozenset({"preserve", "balanced", "clean"}),
        )
        with self.assertRaises(ValueError):
            session.set_cleanup_profile("unknown")

    def test_selected_candidates_take_priority_and_whole_song_is_never_implicit(
        self,
    ) -> None:
        first = self.candidate("first", 10)
        second = self.candidate("second", 110)
        outside = self.candidate("outside", 300)
        session = TranscriptionSession([first, second, outside])

        self.assertEqual(session.resolve_route_candidate_ids(), ())
        self.assertEqual(session.route_to_track(1).routes, ())

        session.set_region(0, 200)
        self.assertEqual(
            session.resolve_route_candidate_ids(), ("first", "second")
        )
        session.set_selection(["outside"])
        self.assertEqual(session.resolve_route_candidate_ids(), ("outside",))
        routed = session.route_to_track(7)
        self.assertEqual(routed.routes, (CandidateRoute("outside", 7),))
        self.assertEqual(
            session.state.pending_routes, (CandidateRoute("outside", 7),)
        )

    def test_default_route_is_single_track_and_copy_is_explicit(self) -> None:
        session = TranscriptionSession([self.candidate("note", 10)])
        session.set_selection(["note"])
        session.route_to_track(1)
        session.set_selection(["note"])
        session.route_to_track(2)
        self.assertEqual(
            session.state.pending_routes, (CandidateRoute("note", 2),)
        )

        session.set_selection(["note"])
        session.route_to_track(3, copy=True)
        self.assertEqual(
            session.state.pending_routes,
            (CandidateRoute("note", 2), CandidateRoute("note", 3)),
        )
        moved = session.mark_routes_applied([CandidateRoute("note", 2)])
        self.assertEqual(moved, (CandidateRoute("note", 2),))
        self.assertEqual(
            session.state.applied_routes, (CandidateRoute("note", 2),)
        )
        self.assertFalse(session.commands.can_undo)
        session.set_selection(["note"])
        blocked = session.route_to_track(4)
        self.assertEqual(blocked.routes, ())
        self.assertEqual(blocked.skipped_applied, ("note",))
        session.set_selection(["note"])
        copied = session.route_to_track(4, copy=True)
        self.assertEqual(copied.routes, (CandidateRoute("note", 4),))

    def test_editor_commit_keeps_draft_local_and_normalises_staged_routes(
        self,
    ) -> None:
        first_note = object()
        second_note = object()
        commit = TranscriptionEditorCommit(
            current_track_id=7,
            draft_notes=[first_note, second_note],
            primary_routes=[
                CandidateRoute("primary-b", 7),
                CandidateRoute("primary-a", 7),
                CandidateRoute("primary-a", 7),
            ],
            copy_routes=[
                CandidateRoute("copy", 9),
                CandidateRoute("copy", 8),
            ],
            cache_key="cache-key",
            analysis_fingerprint="audio-sha",
        )

        self.assertEqual(commit.draft_notes, (first_note, second_note))
        self.assertEqual(
            commit.primary_routes,
            (
                CandidateRoute("primary-a", 7),
                CandidateRoute("primary-b", 7),
            ),
        )
        self.assertEqual(
            commit.copy_routes,
            (CandidateRoute("copy", 8), CandidateRoute("copy", 9)),
        )
        self.assertEqual(
            commit.staged_routes,
            (
                StagedCandidateRoute(CandidateRoute("primary-a", 7), True),
                StagedCandidateRoute(CandidateRoute("primary-b", 7), True),
                StagedCandidateRoute(CandidateRoute("copy", 8), False),
                StagedCandidateRoute(CandidateRoute("copy", 9), False),
            ),
        )
        self.assertTrue(commit.has_staged_routes)
        self.assertEqual(
            commit.routes,
            (
                CandidateRoute("copy", 8),
                CandidateRoute("copy", 9),
                CandidateRoute("primary-a", 7),
                CandidateRoute("primary-b", 7),
            ),
        )
        with self.assertRaises(ValueError):
            TranscriptionEditorCommit(
                current_track_id=7,
                primary_routes=(CandidateRoute("wrong-track", 8),),
            )
        with self.assertRaises(FrozenInstanceError):
            commit.cache_key = "changed"  # type: ignore[misc]

    def test_editor_commit_report_is_deterministic_and_structured(self) -> None:
        created = CandidateRoute("created", 2)
        satisfied = CandidateRoute("satisfied", 1)
        invalid = CandidateRoute("invalid", 4)
        orphaned = CandidateRoute("orphaned", 9)
        unresolved = CandidateRoute("unresolved", 3)
        report = TranscriptionEditorCommitReport(
            created_routes=(created, created),
            satisfied_routes=(satisfied,),
            invalid_routes=(invalid,),
            orphaned_routes=(orphaned,),
            unresolved_routes=(unresolved, invalid),
            project_changed=True,
        )

        self.assertEqual(report.created_routes, (created,))
        self.assertEqual(report.applied_routes, (created, satisfied))
        self.assertEqual(
            report.blocking_unresolved,
            (invalid, orphaned, unresolved),
        )
        self.assertEqual(report.created_count, 1)
        self.assertEqual(report.satisfied_count, 1)
        self.assertEqual(report.applied_count, 2)
        self.assertEqual(report.invalid_count, 1)
        self.assertEqual(report.orphaned_count, 1)
        self.assertEqual(report.unresolved_count, 2)
        self.assertEqual(report.blocking_count, 3)
        self.assertTrue(report.project_changed)

    def test_batch_project_commit_accepts_local_routes_and_sets_final_pending(
        self,
    ) -> None:
        session = TranscriptionSession(
            [
                self.candidate("old", 10),
                self.candidate("local", 20),
                self.candidate("unresolved", 30),
            ]
        )
        session.route_to_track(7, ["old"])
        session.set_selection(["local"])
        session.reject(["unresolved"])
        self.assertTrue(session.commands.can_undo)

        old_route = CandidateRoute("old", 7)
        local_route = CandidateRoute("local", 7)
        unresolved_route = CandidateRoute("missing-cache-candidate", 12)
        committed = session.commit_project_routes(
            [local_route, old_route, local_route],
            pending_routes=[unresolved_route],
        )

        self.assertEqual(committed, (local_route, old_route))
        self.assertEqual(session.state.pending_routes, (unresolved_route,))
        self.assertEqual(
            session.state.applied_routes, (local_route, old_route)
        )
        self.assertFalse(session.commands.can_undo)
        self.assertFalse(session.commands.can_redo)

    def test_batch_project_commit_default_preserves_unresolved_old_pending(
        self,
    ) -> None:
        session = TranscriptionSession(
            [
                self.candidate("a", 10),
                self.candidate("b", 20),
                self.candidate("c", 30),
            ]
        )
        session.route_to_track(1, ["a"])
        session.route_to_track(2, ["b"], copy=True)
        route_a = CandidateRoute("a", 1)
        route_b = CandidateRoute("b", 2)

        self.assertEqual(session.commit_project_routes([route_a]), (route_a,))
        self.assertEqual(session.state.pending_routes, (route_b,))
        self.assertEqual(session.state.applied_routes, (route_a,))

        # Crossing a formal project boundary clears stale review history even
        # when preflight reports no route that can be applied.
        session.set_selection(["c"])
        session.reject(["c"])
        self.assertTrue(session.commands.can_undo)
        self.assertEqual(session.commit_project_routes([]), ())
        self.assertFalse(session.commands.can_undo)

    def test_review_commands_undo_and_redo_without_tracking_selection(self) -> None:
        session = TranscriptionSession(
            [self.candidate("a", 10), self.candidate("b", 50)]
        )
        session.set_region(0, 100)
        session.set_selection(["a"])
        self.assertFalse(session.commands.can_undo)
        session.reject()
        self.assertTrue(session.commands.can_undo)
        self.assertIn("a", session.state.rejected_candidate_ids)
        session.set_selection(["b"])
        session.route_to_track(9)
        self.assertEqual(session.state.pending_routes, (CandidateRoute("b", 9),))

        self.assertTrue(session.undo())
        self.assertEqual(session.state.pending_routes, ())
        self.assertEqual(session.state.selected_candidate_ids, frozenset({"b"}))
        self.assertTrue(session.undo())
        self.assertEqual(session.state.rejected_candidate_ids, frozenset())
        self.assertEqual(session.state.selected_candidate_ids, frozenset({"a"}))
        self.assertTrue(session.redo())
        self.assertEqual(session.state.rejected_candidate_ids, frozenset({"a"}))

    def test_state_only_review_does_not_reindex_candidates(self) -> None:
        session = TranscriptionSession(
            [self.candidate(f"candidate-{index}", index * 10.0)
             for index in range(200)]
        )

        with patch.object(
            session,
            "set_candidates",
            wraps=session.set_candidates,
        ) as set_candidates:
            session.reject(["candidate-100"])

        set_candidates.assert_not_called()
        self.assertTrue(session.undo())
        self.assertNotIn(
            "candidate-100",
            session.state.rejected_candidate_ids,
        )

    def test_explicit_candidate_resolution_uses_order_index(self) -> None:
        session = TranscriptionSession(
            [self.candidate(f"candidate-{index}", index * 10.0)
             for index in range(200)]
        )

        with patch.object(
            session,
            "candidate_id",
            wraps=session.candidate_id,
        ) as candidate_id:
            resolved = session.resolve_route_candidate_ids(
                ["candidate-150", "candidate-2", "candidate-150"]
            )

        self.assertEqual(
            resolved,
            ("candidate-2", "candidate-150"),
        )
        candidate_id.assert_not_called()

    def test_region_redecode_replaces_only_unreviewed_and_deduplicates(self) -> None:
        rejected = self.candidate("rejected", 20, 60)
        routed = self.candidate("routed", 60, 62)
        old = self.candidate("old", 120, 64)
        outside = self.candidate("outside", 300, 65)
        session = TranscriptionSession([rejected, routed, old, outside])
        session.set_region(0, 200)
        session.reject(["rejected"])
        session.route_to_track(3, ["routed"])

        result = session.replace_region_candidates(
            [
                self.candidate("near-rejected", 25, 60),
                self.candidate("near-routed", 65, 62),
                self.candidate("new", 160, 67),
                self.candidate("ignored-outside", 250, 68),
            ]
        )
        self.assertEqual(result.removed_candidate_ids, ("old",))
        self.assertEqual(result.added_candidate_ids, ("new",))
        self.assertEqual(
            set(result.protected_candidate_ids), {"rejected", "routed"}
        )
        self.assertEqual(
            set(result.skipped_duplicate_ids), {"near-rejected", "near-routed"}
        )
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"rejected", "routed", "new", "outside"},
        )

        self.assertTrue(session.undo())
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"rejected", "routed", "old", "outside"},
        )
        self.assertTrue(session.redo())
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"rejected", "routed", "new", "outside"},
        )

    def test_region_redecode_duplicate_checks_use_pitch_onset_buckets(
        self,
    ) -> None:
        existing = [
            self.candidate(
                f"existing-{index}",
                index * 25.0,
                48 + index % 24,
            )
            for index in range(4_000)
        ]
        incoming = [
            self.candidate(
                f"incoming-{index}",
                25_000.0 + index * 25.0,
                48 + index % 24,
            )
            for index in range(400)
        ]
        session = TranscriptionSession(existing)
        session.set_region(25_000.0, 35_000.0)
        original_duplicate_check = session._candidate_is_duplicate
        duplicate_check_count = 0

        def counted_duplicate_check(*args, **kwargs) -> bool:
            nonlocal duplicate_check_count
            duplicate_check_count += 1
            return original_duplicate_check(*args, **kwargs)

        session._candidate_is_duplicate = counted_duplicate_check
        result = session.replace_region_candidates(incoming)

        self.assertEqual(len(result.added_candidate_ids), len(incoming))
        self.assertEqual(len(result.removed_candidate_ids), len(incoming))
        self.assertLess(duplicate_check_count, len(incoming) * 4)

    def test_region_redecode_bucket_query_crosses_time_boundary(self) -> None:
        survivor = self.candidate("survivor", 39.0, 60)
        old = self.candidate("old", 100.0, 61)
        session = TranscriptionSession([survivor, old])
        session.set_region(40.0, 200.0)

        result = session.replace_region_candidates(
            [self.candidate("near-boundary", 41.0, 60)]
        )

        self.assertEqual(result.added_candidate_ids, ())
        self.assertEqual(result.skipped_duplicate_ids, ("near-boundary",))

    def test_full_replacement_protects_reviewed_candidate_lineages(self) -> None:
        rejected = self.candidate("rejected", 10)
        pending = self.candidate("pending", 20)
        applied = self.candidate("applied", 30)
        old = self.candidate("old", 40)
        session = TranscriptionSession(
            [rejected, pending, applied, old],
            annotations=[
                CandidateAnnotation(
                    "rejected", lineage_ids=frozenset({"lineage-r"})
                ),
                CandidateAnnotation(
                    "pending", lineage_ids=frozenset({"lineage-p"})
                ),
                CandidateAnnotation(
                    "applied", lineage_ids=frozenset({"lineage-a"})
                ),
                CandidateAnnotation(
                    "old",
                    flags=frozenset({"short-fragment"}),
                ),
            ],
        )
        session.reject(["rejected"])
        session.route_to_track(2, ["pending"])
        session.route_to_track(3, ["applied"])
        session.mark_routes_applied([CandidateRoute("applied", 3)])
        session.set_selection(["old"])

        result = session.replace_all_candidates(
            [
                self.candidate("derived-r", 11),
                self.candidate("derived-p", 21),
                self.candidate("derived-a", 31),
                self.candidate("fresh", 50),
            ],
            annotations=[
                CandidateAnnotation(
                    "derived-r", lineage_ids=frozenset({"lineage-r"})
                ),
                CandidateAnnotation(
                    "derived-p", lineage_ids=frozenset({"lineage-p"})
                ),
                CandidateAnnotation(
                    "derived-a", lineage_ids=frozenset({"lineage-a"})
                ),
                CandidateAnnotation(
                    "fresh",
                    flags=frozenset({"short-fragment"}),
                ),
            ],
        )

        self.assertEqual(result.added_candidate_ids, ("fresh",))
        self.assertEqual(result.removed_candidate_ids, ("old",))
        self.assertEqual(
            set(result.protected_candidate_ids),
            {"rejected", "pending", "applied"},
        )
        self.assertEqual(
            set(result.skipped_lineage_candidate_ids),
            {"derived-r", "derived-p", "derived-a"},
        )
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"rejected", "pending", "applied", "fresh"},
        )
        self.assertEqual(session.state.selected_candidate_ids, frozenset())
        self.assertEqual(
            session.annotation_for_id("fresh").flags,
            frozenset({"short-fragment"}),
        )
        self.assertNotIn("annotations", session.to_payload())

        self.assertTrue(session.undo())
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"rejected", "pending", "applied", "old"},
        )
        self.assertEqual(
            session.annotation_for_id("old").flags,
            frozenset({"short-fragment"}),
        )

    def test_lineage_block_retains_unreviewed_source_candidates(self) -> None:
        first = self.candidate("first", 10, 60)
        rejected = self.candidate("rejected", 80, 60)
        session = TranscriptionSession(
            [first, rejected],
            annotations=[
                CandidateAnnotation("first"),
                CandidateAnnotation("rejected"),
            ],
        )
        session.reject(["rejected"])
        merged = self.candidate("merged", 10, 60)
        annotation = CandidateAnnotation(
            "merged",
            lineage_ids=frozenset({"first", "rejected"}),
            disposition="merged",
        )

        result = session.replace_all_candidates(
            [merged],
            annotations=[annotation],
        )

        self.assertEqual(result.added_candidate_ids, ())
        self.assertEqual(result.removed_candidate_ids, ())
        self.assertEqual(
            set(result.protected_candidate_ids),
            {"first", "rejected"},
        )
        self.assertEqual(
            result.skipped_lineage_candidate_ids,
            ("merged",),
        )
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"first", "rejected"},
        )

    def test_region_redecode_lineage_cannot_replace_reviewed_source(self) -> None:
        first = self.candidate("first", 10, 60)
        rejected = self.candidate("rejected", 100, 60)
        session = TranscriptionSession(
            [first, rejected],
            annotations=[
                CandidateAnnotation("first"),
                CandidateAnnotation("rejected"),
            ],
        )
        session.set_region(0, 250)
        session.reject(["rejected"])
        merged = self.candidate("merged", 10, 60)

        result = session.replace_region_candidates(
            [merged],
            annotations=[
                CandidateAnnotation(
                    "merged",
                    lineage_ids=frozenset({"first", "rejected"}),
                    disposition="merged",
                )
            ],
        )

        self.assertEqual(result.added_candidate_ids, ())
        self.assertEqual(result.removed_candidate_ids, ())
        self.assertEqual(
            set(result.protected_candidate_ids),
            {"first", "rejected"},
        )
        self.assertEqual(result.skipped_duplicate_ids, ("merged",))
        self.assertEqual(
            {session.candidate_id(value) for value in session.candidates},
            {"first", "rejected"},
        )

    def test_orphaned_routes_are_never_silently_retargeted(self) -> None:
        session = TranscriptionSession([self.candidate("a", 10)])
        session.route_to_track(10, ["a"])
        self.assertEqual(
            session.orphaned_routes([1, 2]), (CandidateRoute("a", 10),)
        )
        self.assertEqual(
            session.state.pending_routes, (CandidateRoute("a", 10),)
        )

    def test_formal_apply_state_can_be_restored_by_project_snapshot_payload(
        self,
    ) -> None:
        session = TranscriptionSession([self.candidate("a", 10)])
        session.route_to_track(10, ["a"])
        before_apply = session.to_payload()
        session.mark_routes_applied()
        self.assertEqual(
            session.state.applied_routes, (CandidateRoute("a", 10),)
        )
        session.restore_state(before_apply)
        self.assertEqual(
            session.state.pending_routes, (CandidateRoute("a", 10),)
        )
        self.assertEqual(session.state.applied_routes, ())
        self.assertFalse(session.commands.can_undo)

    def test_sensitivity_presets_match_locked_thresholds(self) -> None:
        self.assertEqual(SENSITIVITY_PRESETS["conservative"], (0.65, 0.45))
        self.assertEqual(SENSITIVITY_PRESETS["balanced"], (0.50, 0.30))
        self.assertEqual(SENSITIVITY_PRESETS["sensitive"], (0.35, 0.20))
        state = TranscriptionSessionState(sensitivity="sensitive")
        self.assertEqual(state.onset_threshold, 0.40)
        self.assertEqual(state.frame_threshold, 0.15)


if __name__ == "__main__":
    unittest.main()
