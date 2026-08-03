from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal

from bdo_music_composer.transcription.bdo_transcription import TranscriptionCancelled
from bdo_music_composer.transcription.rhythm_cleanup import (
    RHYTHM_CLEANUP_VERSION,
    RhythmDiagnosticSidecar,
)
from bdo_music_composer.transcription.rhythm_grid import (
    ProjectRhythmSettings,
    build_project_rhythm_grid,
    rhythm_analysis_identity,
    transcription_candidate_revision,
)
from bdo_music_composer.ui.transcription.transcription_workers import (
    TranscriptionRhythmDiagnosticRunner,
    TranscriptionRhythmDiagnosticWorker,
)


class _FakeWorker(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)
    finished = Signal()

    def __init__(self, *, generation: int, **_kwargs: object) -> None:
        super().__init__()
        self.generation = int(generation)
        self.started = False
        self.cancel_requested = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancel_requested = True


def _empty_sidecar(cache_key: str) -> RhythmDiagnosticSidecar:
    candidates: tuple[object, ...] = ()
    grid = build_project_rhythm_grid(
        ProjectRhythmSettings(enabled=True, bpm=120.0)
    )
    assert grid is not None
    revision = transcription_candidate_revision(candidates)
    return RhythmDiagnosticSidecar(
        identity=rhythm_analysis_identity(
            evidence_cache_key=cache_key,
            candidate_revision=revision,
            grid=grid,
            algorithm_version=RHYTHM_CLEANUP_VERSION,
        ),
        evidence_cache_key=cache_key,
        candidate_revision=revision,
        grid=grid,
        features=(),
        proposals=(),
        processed_candidate_count=0,
        evidence_window_read_count=0,
    )


class RhythmDiagnosticRunnerTests(unittest.TestCase):
    def test_runner_refuses_implicit_or_concurrent_request(self) -> None:
        runner = TranscriptionRhythmDiagnosticRunner()
        self.assertFalse(
            runner.start_diagnostic(
                cache_key="a" * 64,
                candidates=(),
                settings=ProjectRhythmSettings(enabled=False),
            )
        )
        self.assertFalse(runner.busy)

    def test_runner_has_one_slot_and_rejects_stale_completion(self) -> None:
        cache_key = "a" * 64
        settings = ProjectRhythmSettings(enabled=True, bpm=120.0)
        delivered: list[RhythmDiagnosticSidecar] = []
        runner = TranscriptionRhythmDiagnosticRunner()
        runner.succeeded.connect(delivered.append)
        with patch(
            "bdo_music_composer.ui.transcription.transcription_workers.TranscriptionRhythmDiagnosticWorker",
            _FakeWorker,
        ):
            self.assertTrue(
                runner.start_diagnostic(
                    cache_key=cache_key,
                    candidates=(),
                    settings=settings,
                )
            )
            worker = runner._worker
            self.assertIsInstance(worker, _FakeWorker)
            assert isinstance(worker, _FakeWorker)
            self.assertTrue(worker.started)
            self.assertFalse(
                runner.start_diagnostic(
                    cache_key=cache_key,
                    candidates=(),
                    settings=settings,
                )
            )
            runner.invalidate()
            self.assertTrue(worker.cancel_requested)
            worker.succeeded.emit(worker.generation, _empty_sidecar(cache_key))
            self.assertEqual(delivered, [])
            worker.finished.emit()
            self.assertFalse(runner.busy)

    def test_worker_reports_cache_validation_cancellation(self) -> None:
        worker = TranscriptionRhythmDiagnosticWorker(
            generation=7,
            cache_key="a" * 64,
            candidates=(),
            settings=ProjectRhythmSettings(enabled=True, bpm=120.0),
        )
        cancelled: list[int] = []
        worker.cancelled.connect(cancelled.append)
        with patch(
            "bdo_music_composer.ui.transcription.transcription_workers.load_transcription_evidence_descriptor",
            side_effect=TranscriptionCancelled("cancelled"),
        ):
            worker.run()
        self.assertEqual(cancelled, [7])


if __name__ == "__main__":
    unittest.main()
