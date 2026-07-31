from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from bdo_transcription_session import (
    CandidateAnnotation,
    TranscriptionSession,
)
from bdo_validation import ValidationContext, ValidationIssue
from bdo_music_composer.app.conversion_validation_controller import (
    ConversionValidationController,
)
from bdo_music_composer.editor.model_revision import ModelRevision
from pitch_transform import PitchTransformPlan
from bdo_music_composer.audio.preview_transport_controller import (
    PreviewPlayAction,
    PreviewTransportCoordinator,
)
from bdo_music_composer.project.project_lifecycle_controller import (
    ProjectLifecycleController,
)
from bdo_music_composer.transcription.transcription_workspace_controller import (
    TranscriptionAnalysisCoordinator,
    TranscriptionReviewController,
)


class ControllerBoundaryTests(unittest.TestCase):
    def test_model_revision_is_explicit_and_monotonic(self) -> None:
        revision = ModelRevision()
        self.assertEqual(revision.value, 0)
        self.assertEqual(revision.advance("notes committed"), 1)
        self.assertEqual(revision.advance("instrument changed"), 2)
        self.assertEqual(revision.reason, "instrument changed")

    def test_conversion_validation_reuses_only_same_revision_and_scope(self) -> None:
        calls: list[tuple[object, ...]] = []
        issue = ValidationIssue("test", "info", "ok")

        def validator(tracks, _profile, _context):
            calls.append(tuple(tracks))
            return (issue,)

        controller = ConversionValidationController(validator)
        profile = object()
        context = ValidationContext(
            transpose=0,
            active_track_ids=frozenset(),
            instrument_names={},
            gm_drum_map={},
            serialize_instrument=lambda _track: 0,
            pitch_plan=PitchTransformPlan(),
        )
        first = controller.snapshot(
            revision=3,
            scope_key="en",
            tracks=(object(),),
            profile=profile,
            context=context,
        )
        repeated = controller.snapshot(
            revision=3,
            scope_key="en",
            tracks=(object(),),
            profile=profile,
            context=context,
        )
        self.assertIs(first, repeated)
        self.assertEqual(len(calls), 1)

        localized = controller.snapshot(
            revision=3,
            scope_key="ja",
            tracks=(),
            profile=profile,
            context=context,
        )
        changed = controller.snapshot(
            revision=4,
            scope_key="ja",
            tracks=(),
            profile=profile,
            context=context,
        )
        self.assertIsNot(localized, changed)
        self.assertEqual(len(calls), 3)

    def test_transcription_generations_and_restart_merge_are_deterministic(self) -> None:
        coordinator = TranscriptionAnalysisCoordinator()
        workspace = coordinator.next_workspace_generation()
        assist = coordinator.next_assist_generation()
        self.assertTrue(coordinator.is_current_workspace(workspace))
        self.assertTrue(coordinator.is_current_assist(assist))

        coordinator.queue_assist_restart(
            harmony_only=True,
            allow_review_recovery=True,
        )
        coordinator.queue_assist_restart(
            harmony_only=False,
            allow_review_recovery=False,
        )
        restart = coordinator.consume_assist_restart()
        self.assertIsNotNone(restart)
        assert restart is not None
        self.assertFalse(restart.harmony_only)
        self.assertFalse(restart.allow_review_recovery)
        self.assertIsNone(coordinator.consume_assist_restart())

        coordinator.invalidate_all()
        self.assertFalse(coordinator.is_current_workspace(workspace))
        self.assertFalse(coordinator.is_current_assist(assist))

    def test_transcription_review_controller_preserves_mixed_action_order(self) -> None:
        controller = TranscriptionReviewController[str](history_limit=3)
        controller.record_action("session")
        controller.record_assist_change("assist-0")
        self.assertEqual(controller.action_undo, ["session", "assist"])

        kind = controller.take_undo_action()
        changed, review = controller.undo_assist("assist-1")
        self.assertEqual(kind, "assist")
        self.assertTrue(changed)
        self.assertEqual(review, "assist-0")
        controller.complete_undo(kind)

        kind = controller.take_redo_action()
        changed, review = controller.redo_assist(review)
        self.assertEqual(kind, "assist")
        self.assertTrue(changed)
        self.assertEqual(review, "assist-1")
        controller.complete_redo(kind)

        controller.take_undo_action()
        controller.undo_assist(review)
        controller.complete_undo("assist")
        controller.record_action("session")
        self.assertEqual(controller.assist_redo, [])
        self.assertEqual(controller.action_redo, [])

    def test_transcription_review_history_is_bounded_and_validated(self) -> None:
        controller = TranscriptionReviewController[int](history_limit=2)
        for value in range(4):
            controller.record_assist_change(value)
        self.assertEqual(controller.assist_undo, [2, 3])
        self.assertEqual(controller.action_undo, ["assist", "assist"])
        with self.assertRaises(ValueError):
            controller.record_action("project")

    def test_transcription_review_plans_share_indexed_candidate_scope(self) -> None:
        candidates = tuple(
            SimpleNamespace(
                pitch=60 + index,
                velocity=90,
                start_ms=float(index * 100),
                duration_ms=80.0,
                candidate_id=candidate_id,
            )
            for index, candidate_id in enumerate(
                ("outside", "fragment", "flicker", "plain")
            )
        )
        session = TranscriptionSession(
            candidates,
            annotations=(
                CandidateAnnotation(
                    "fragment",
                    flags=frozenset({"review_fragment"}),
                ),
                CandidateAnnotation(
                    "flicker",
                    flags=frozenset({"pitch_flicker"}),
                ),
            ),
        )
        session.set_region(100.0, 300.0)
        controller = TranscriptionReviewController[object]()

        eligible = controller.plan_eligible_candidates(
            session,
            reference_audio_offset_ms=0.0,
        )
        fragments = controller.plan_fragment_selection(
            session,
            reference_audio_offset_ms=0.0,
        )
        self.assertEqual(eligible.source, "region")
        self.assertEqual(eligible.candidate_ids, ("fragment", "flicker"))
        self.assertEqual(
            fragments.candidate_ids,
            ("fragment", "flicker"),
        )

        session.reject(["fragment"])
        session.set_selection(["fragment"])
        restore = controller.plan_restore_candidates(
            session,
            reference_audio_offset_ms=0.0,
        )
        self.assertEqual(restore.source, "selection")
        self.assertEqual(restore.candidate_ids, ("fragment",))

        session.clear_selection()
        session.clear_region()
        session.state = replace(
            session.state,
            rejected_candidate_ids=(
                session.state.rejected_candidate_ids.union({"orphan"})
            ),
        )
        restore_all = controller.plan_restore_candidates(
            session,
            reference_audio_offset_ms=0.0,
        )
        self.assertEqual(restore_all.source, "all")
        self.assertEqual(restore_all.candidate_ids, ("fragment", "orphan"))

    def test_project_lifecycle_rejects_stale_completion(self) -> None:
        controller = ProjectLifecycleController()
        first = controller.begin_loading("first")
        second = controller.begin_loading("second")
        self.assertFalse(controller.finish_loading(first))
        self.assertTrue(controller.loading)
        self.assertTrue(controller.finish_loading(second))
        self.assertFalse(controller.loading)

    def test_preview_transport_owns_bounded_session_state(self) -> None:
        controller = PreviewTransportCoordinator()
        self.assertIs(
            controller.play_action(),
            PreviewPlayAction.START_SESSION,
        )
        generation = controller.begin_loading(
            start_ms=125.0,
            tracks=("one", "two"),
            source="generic",
        )
        self.assertTrue(controller.is_current(generation))
        self.assertTrue(controller.active)
        self.assertTrue(controller.loading)
        self.assertIs(
            controller.play_action(),
            PreviewPlayAction.WAIT_FOR_LOAD,
        )
        self.assertEqual(controller.tracks, ["one", "two"])
        controller.mark_ready("verified")
        self.assertFalse(controller.loading)
        self.assertIs(controller.play_action(), PreviewPlayAction.RESUME)
        self.assertEqual(controller.validation_state, "verified")
        controller.clear_session()
        self.assertFalse(controller.active)
        self.assertEqual(controller.tracks, [])
        self.assertFalse(controller.is_current(generation))


if __name__ == "__main__":
    unittest.main()
