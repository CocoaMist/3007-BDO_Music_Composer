"""Qt host lifecycle for display-only music-reference timbre analysis."""

from __future__ import annotations

from PySide6.QtCore import QTimer

from bdo_music_composer.ui.transcription.transcription_workers import (
    ReferenceTimbreAnalysisWorker,
)
from bdo_music_composer.transcription.reference_timbre import (
    ReferenceTimbreAnalysis,
)


class ReferenceTimbreHostMixin:
    """Keep optional timbre worker orchestration out of the main GUI owner."""

    def _configured_muscriptor_executable(self) -> str:
        ui_config = (
            self.config.get("transcription_ui", {})
            if isinstance(self.config, dict)
            and isinstance(self.config.get("transcription_ui", {}), dict)
            else {}
        )
        return str(ui_config.get("muscriptor_executable", "") or "")

    def _set_reference_timbre_grouping_enabled(self, enabled: bool) -> None:
        if not bool(enabled):
            self._clear_reference_timbre_analysis(cancel_worker=True)
            self._refresh_transcription_workspace()
            return
        self._start_reference_timbre_analysis()

    def _set_reference_instrument_labels_enabled(self, enabled: bool) -> None:
        del enabled
        if bool(
            self.reference_layer_settings.get(
                "timbre_grouping_enabled", True
            )
        ):
            self._start_reference_timbre_analysis(force_restart=True)

    def _clear_reference_timbre_analysis(
        self,
        *,
        cancel_worker: bool = False,
    ) -> None:
        self.reference_timbre_analysis = None
        self.reference_timbre_prediction = None
        self.reference_timbre_analysis_error = False
        self._reference_timbre_restart_pending = False
        worker = self.reference_timbre_worker
        if cancel_worker and worker is not None:
            worker.cancel()
        elif worker is None:
            self.reference_timbre_analysis_busy = False

    def _start_reference_timbre_analysis(
        self,
        *,
        force_restart: bool = False,
    ) -> None:
        enabled = bool(
            self.reference_layer_settings.get(
                "timbre_grouping_enabled", True
            )
        )
        result = self.transcription_result
        descriptor = result.evidence_descriptor if result is not None else None
        if (
            not enabled
            or result is None
            or descriptor is None
            or not descriptor.cache_key
            or not self.reference_audio.audio_path
            or self.workspace_close_pending
        ):
            self._clear_reference_timbre_analysis(cancel_worker=True)
            self._refresh_transcription_workspace()
            return
        if self.reference_timbre_worker is not None:
            if force_restart:
                self._reference_timbre_restart_pending = True
                self.reference_timbre_worker.cancel()
            return
        current_ids = frozenset(
            str(getattr(candidate, "candidate_id", "") or "")
            for candidate in self.transcription_session.candidates
        )
        existing_ids = (
            frozenset(
                candidate_id
                for group in self.reference_timbre_analysis.groups
                for candidate_id in group.candidate_ids
            )
            if self.reference_timbre_analysis is not None
            else frozenset()
        )
        external_enabled = bool(
            self.reference_layer_settings.get(
                "external_instrument_labels_enabled", False
            )
        )
        expected_label_backend = "muscriptor-small" if external_enabled else ""
        if (
            not force_restart
            and self.reference_timbre_analysis is not None
            and self.reference_timbre_analysis.evidence_stage == "acoustic"
            and self.reference_timbre_analysis.cache_key == descriptor.cache_key
            and existing_ids == current_ids
            and self.reference_timbre_analysis.label_backend
            == expected_label_backend
        ):
            return
        worker = ReferenceTimbreAnalysisWorker(
            cache_key=descriptor.cache_key,
            candidates=tuple(self.transcription_session.candidates),
            bpm=float(max(1, self.bpm_override or self.bpm)),
            midi_min=int(descriptor.midi_min),
            reference_audio_path=str(self.reference_audio.audio_path),
            external_labels_enabled=external_enabled,
            muscriptor_executable=self._configured_muscriptor_executable(),
            parent=self,
        )
        self.reference_timbre_worker = worker
        self._reference_timbre_restart_pending = False
        self.reference_timbre_analysis_busy = True
        self.reference_timbre_analysis_error = False
        worker.succeeded.connect(
            lambda analysis, current=worker:
            self._reference_timbre_succeeded(current, analysis)
        )
        worker.predicted.connect(
            lambda analysis, current=worker:
            self._reference_timbre_predicted(current, analysis)
        )
        worker.failed.connect(
            lambda _message, current=worker:
            self._reference_timbre_failed(current)
        )
        worker.finished.connect(
            lambda current=worker:
            self._reference_timbre_finished(current)
        )
        worker.finished.connect(worker.deleteLater)
        self._refresh_transcription_workspace()
        worker.start()

    def _reference_timbre_predicted(
        self,
        worker: ReferenceTimbreAnalysisWorker,
        analysis: ReferenceTimbreAnalysis,
    ) -> None:
        """Publish structural colours while acoustic profiling continues."""

        if self.reference_timbre_worker is not worker:
            return
        descriptor = (
            self.transcription_result.evidence_descriptor
            if self.transcription_result is not None
            else None
        )
        current_ids = frozenset(
            str(getattr(candidate, "candidate_id", "") or "")
            for candidate in self.transcription_session.candidates
        )
        prediction_ids = frozenset(
            candidate_id
            for group in analysis.groups
            for candidate_id in group.candidate_ids
        )
        if (
            descriptor is None
            or analysis.cache_key != descriptor.cache_key
            or prediction_ids != current_ids
        ):
            return
        self.reference_timbre_prediction = analysis
        self.reference_timbre_analysis_error = False
        self._refresh_transcription_workspace()

    def _reference_timbre_succeeded(
        self,
        worker: ReferenceTimbreAnalysisWorker,
        analysis: ReferenceTimbreAnalysis,
    ) -> None:
        if self.reference_timbre_worker is not worker:
            return
        descriptor = (
            self.transcription_result.evidence_descriptor
            if self.transcription_result is not None
            else None
        )
        current_ids = frozenset(
            str(getattr(candidate, "candidate_id", "") or "")
            for candidate in self.transcription_session.candidates
        )
        analysis_ids = frozenset(
            candidate_id
            for group in analysis.groups
            for candidate_id in group.candidate_ids
        )
        if (
            descriptor is None
            or analysis.cache_key != descriptor.cache_key
            or analysis_ids != current_ids
        ):
            self._reference_timbre_restart_pending = True
            return
        self.reference_timbre_analysis = analysis
        self.reference_timbre_analysis_error = False
        self._refresh_transcription_workspace()

    def _reference_timbre_failed(
        self,
        worker: ReferenceTimbreAnalysisWorker,
    ) -> None:
        if self.reference_timbre_worker is not worker:
            return
        # Keep the explicitly provisional structural result visible when
        # acoustic verification fails.  Clearing it recreates the misleading
        # permanent "waiting for analysis" state.
        self.reference_timbre_analysis = None
        self.reference_timbre_analysis_error = True
        self._refresh_transcription_workspace()

    def _reference_timbre_finished(
        self,
        worker: ReferenceTimbreAnalysisWorker,
    ) -> None:
        if self.reference_timbre_worker is not worker:
            return
        self.reference_timbre_worker = None
        self.reference_timbre_analysis_busy = False
        restart = self._reference_timbre_restart_pending
        self._reference_timbre_restart_pending = False
        self._refresh_transcription_workspace()
        if restart and not self.workspace_close_pending:
            QTimer.singleShot(0, self._start_reference_timbre_analysis)
        elif self.workspace_close_pending:
            QTimer.singleShot(0, self.close)


__all__ = ["ReferenceTimbreHostMixin"]
