"""Qt adapter for the explicit transcription rhythm-diagnostic sidecar."""

from __future__ import annotations

from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.transcription.transcription_workers import TranscriptionRhythmDiagnosticRunner

from bdo_music_composer.transcription.rhythm_cleanup import (
    RhythmDiagnosticSidecar,
)
from bdo_music_composer.transcription.rhythm_grid import (
    ProjectRhythmSettings,
    build_project_rhythm_grid,
)
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentConfig,
)


class TranscriptionRhythmDiagnosticMixin:
    """Own rhythm-diagnostic Qt wiring while the window supplies app state."""

    def _initialize_transcription_rhythm_diagnostic(self) -> None:
        self.transcription_rhythm_sidecar: RhythmDiagnosticSidecar | None = None
        self.transcription_rhythm_runner = TranscriptionRhythmDiagnosticRunner(
            self
        )
        self.transcription_rhythm_runner.succeeded.connect(
            self._transcription_rhythm_diagnostic_succeeded
        )
        self.transcription_rhythm_runner.failed.connect(
            self._transcription_rhythm_diagnostic_failed
        )
        self.transcription_rhythm_runner.cancelled.connect(
            self._transcription_rhythm_diagnostic_cancelled
        )
        self.transcription_rhythm_runner.busy_changed.connect(
            self._transcription_rhythm_diagnostic_busy_changed
        )

    def _sync_transcription_rhythm_editor(self, editor=None) -> None:
        editor = editor or self.active_transcription_editor
        if editor is None:
            return
        sidecar = self.transcription_rhythm_sidecar
        alignment = None if sidecar is None else sidecar.alignment
        set_alignment = getattr(
            editor,
            "set_transcription_rhythm_alignment",
            None,
        )
        if callable(set_alignment):
            set_alignment(alignment)
        editor.transcription_panel.set_rhythm_diagnostic_state(
            busy=self.transcription_rhythm_runner.busy,
            proposal_count=(
                None if sidecar is None else len(sidecar.proposals)
            ),
            aligned_count=(
                None if alignment is None else alignment.aligned_count
            ),
            detected_bpm=(
                None
                if alignment is None
                else alignment.estimate.detected_bpm
            ),
            confidence=(
                None
                if alignment is None
                else alignment.estimate.confidence
            ),
        )

    def _current_project_rhythm_settings(self) -> ProjectRhythmSettings:
        return ProjectRhythmSettings(
            enabled=True,
            bpm=float(max(1, self.bpm_override or self.bpm)),
            beat_origin_audio_ms=(
                float(self.beat_origin_ms)
                - float(self.reference_audio_offset_ms)
            ),
            time_signature=max(1, int(self.time_sig)),
        )

    def _start_transcription_rhythm_diagnostic(self) -> None:
        """Explicitly build a disposable sidecar from cached evidence."""

        state = self.transcription_session.state
        candidates = tuple(self.transcription_session.candidates)
        if self.workspace_transcription_worker is not None:
            self.show_toast(
                tr("请等待当前扒谱分析完成。"),
                kind="warning",
            )
            return
        if not state.cache_key or not candidates:
            self.show_toast(
                tr("请先生成扒谱候选，再运行节奏诊断。"),
                kind="warning",
            )
            return
        if self.transcription_rhythm_runner.busy:
            return
        self.transcription_rhythm_sidecar = None
        editor = self.active_transcription_editor
        panel = getattr(editor, "transcription_panel", None)
        profile = str(
            getattr(
                panel,
                "rhythm_alignment_profile",
                "auto",
            )
        )
        started = self.transcription_rhythm_runner.start_diagnostic(
            cache_key=state.cache_key,
            candidates=candidates,
            settings=self._current_project_rhythm_settings(),
            alignment_config=RhythmAlignmentConfig(profile=profile),
        )
        if not started:
            self.show_toast(
                tr("节奏诊断未启动；没有修改任何音符。"),
                kind="warning",
            )
            return
        self._set_transcription_status(
            tr("正在读取缓存证据进行节奏诊断；不会运行模型。")
        )

    def _transcription_rhythm_diagnostic_succeeded(
        self,
        sidecar: RhythmDiagnosticSidecar,
    ) -> None:
        grid = build_project_rhythm_grid(
            self._current_project_rhythm_settings()
        )
        if grid is None or not sidecar.is_current(
            evidence_cache_key=self.transcription_session.state.cache_key,
            candidates=tuple(self.transcription_session.candidates),
            grid=grid,
        ):
            return
        consume_follow = getattr(
            self,
            "_consume_reference_bpm_follow_result",
            None,
        )
        if callable(consume_follow) and consume_follow(sidecar):
            return
        self.transcription_rhythm_sidecar = sidecar
        merge_count = sum(
            item.kind == "merge_same_pitch" for item in sidecar.proposals
        )
        suppress_count = sum(
            item.kind == "suppress_extra" for item in sidecar.proposals
        )
        self._set_transcription_status(
            trf(
                "节奏整理完成 · 对齐 {aligned} · 检测 BPM {bpm} · "
                "置信 {confidence}% · 合并复核 {merged} · 弱音复核 "
                "{suppressed}；原始识别结果仍可恢复。",
                aligned=(
                    0
                    if sidecar.alignment is None
                    else sidecar.alignment.aligned_count
                ),
                bpm=(
                    "--"
                    if sidecar.alignment is None
                    else f"{sidecar.alignment.estimate.detected_bpm:.1f}"
                ),
                confidence=(
                    0
                    if sidecar.alignment is None
                    else round(
                        sidecar.alignment.estimate.confidence * 100
                    )
                ),
                count=len(sidecar.proposals),
                merged=merge_count,
                suppressed=suppress_count,
            )
        )

    def _transcription_rhythm_diagnostic_failed(self, message: str) -> None:
        stopped = getattr(self, "_reference_bpm_follow_stopped", None)
        if callable(stopped):
            stopped()
        self.transcription_rhythm_sidecar = None
        self._set_transcription_status(
            trf(
                "节奏诊断失败：{error}；没有修改任何音符。",
                error=str(message),
            )
        )

    def _transcription_rhythm_diagnostic_cancelled(self) -> None:
        stopped = getattr(self, "_reference_bpm_follow_stopped", None)
        if callable(stopped):
            stopped()
        self.transcription_rhythm_sidecar = None
        self._set_transcription_status(
            tr("节奏诊断已取消；没有修改任何音符。")
        )

    def _transcription_rhythm_diagnostic_busy_changed(
        self,
        busy: bool,
    ) -> None:
        del busy
        self._sync_transcription_rhythm_editor()

    def _invalidate_transcription_rhythm_diagnostic(self) -> None:
        runner = getattr(self, "transcription_rhythm_runner", None)
        if runner is not None:
            runner.invalidate()
        self.transcription_rhythm_sidecar = None
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_rhythm_diagnostic_state(
                busy=bool(runner is not None and runner.busy),
                proposal_count=None,
            )
            set_alignment = getattr(
                editor,
                "set_transcription_rhythm_alignment",
                None,
            )
            if callable(set_alignment):
                set_alignment(None)


__all__ = ["TranscriptionRhythmDiagnosticMixin"]
