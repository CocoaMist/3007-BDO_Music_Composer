"""Workspace-level global tempo control and rehearsal-sync launcher."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QWidget,
)

from bdo_export import BDO_BPM_MAX
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentConfig,
)
from bdo_music_composer.transcription.reference_tempo import (
    ReferenceTempoError,
    estimate_reference_tempo,
)
from bdo_music_composer.ui.i18n import tr, trf


BDO_STATIC_BPM_MAX = BDO_BPM_MAX


class ReferenceTempoWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        path: str | Path,
        parent: QWidget,
        *,
        prior_bpm: float,
    ) -> None:
        super().__init__(parent)
        self.path = str(path)
        self.prior_bpm = float(prior_bpm)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            estimate = estimate_reference_tempo(
                self.path,
                prior_bpm=self.prior_bpm,
                cancelled=self._cancelled.is_set,
            )
        except ReferenceTempoError as exc:
            if not self._cancelled.is_set():
                self.failed.emit(str(exc))
        except Exception as exc:
            if not self._cancelled.is_set():
                self.failed.emit(str(exc) or type(exc).__name__)
        else:
            if not self._cancelled.is_set():
                self.succeeded.emit(estimate)


class WorkspaceTempoHostMixin:
    """Keep one project BPM authoritative across editor consumers."""

    def _build_global_bpm_control(self) -> QWidget:
        self.reference_tempo_worker = None
        self._pending_reference_tempo_path = ""
        control = QFrame()
        self.global_bpm_control = control
        control.setObjectName("GlobalBpmControl")
        control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(7, 1, 7, 1)
        layout.setSpacing(5)
        self.global_bpm_label = QLabel("BPM")
        self.global_bpm_label.setObjectName("TimelineControlLabel")
        self.global_bpm_label.setAccessibleName(tr("全局 BPM"))
        self.global_bpm_spin = QSpinBox()
        self.global_bpm_spin.setObjectName("GlobalBpmSpin")
        self.global_bpm_spin.setRange(1, BDO_STATIC_BPM_MAX)
        self.global_bpm_spin.setKeyboardTracking(False)
        self.global_bpm_spin.setAlignment(Qt.AlignCenter)
        self.global_bpm_spin.setFixedWidth(84)
        self.global_bpm_spin.setAccessibleName(tr("全局 BPM"))
        tooltip = tr(
            "所有轨道共用；同步时间网格、试听、分析、自动保存和 BDO 导出。"
            "导出兼容范围 1–200；游戏官方作曲指南当前标注上限 180。"
        )
        control.setToolTip(tooltip)
        self.global_bpm_spin.setToolTip(tooltip)
        self.global_bpm_spin.setValue(
            min(BDO_STATIC_BPM_MAX, max(1, int(self.bpm_override or self.bpm)))
        )
        self.global_bpm_spin.editingFinished.connect(
            self._commit_global_bpm_from_control
        )
        self.reference_bpm_follow = QToolButton()
        self.reference_bpm_follow.setObjectName("ReferenceBpmFollow")
        self.reference_bpm_follow.setCheckable(True)
        self.reference_bpm_follow.setText(tr("自动跟随"))
        self.reference_bpm_follow.setAccessibleName(tr("跟随参考 BPM"))
        self.reference_bpm_follow.setToolTip(
            tr("参考音频分析得到可靠节拍后，自动更新工程全局 BPM")
        )
        self.reference_bpm_follow.setChecked(
            bool(self.reference_layer_settings.get("follow_reference_bpm", True))
        )
        self.reference_bpm_follow.setEnabled(bool(self.reference_audio_path))
        self.reference_bpm_follow.toggled.connect(
            self._reference_bpm_follow_toggled
        )
        layout.addWidget(self.global_bpm_label)
        layout.addWidget(self.global_bpm_spin)
        layout.addWidget(self.reference_bpm_follow)
        return control

    def _sync_global_bpm_control(self) -> None:
        if not hasattr(self, "global_bpm_spin"):
            return
        value = min(
            BDO_STATIC_BPM_MAX,
            max(1, int(self.bpm_override or self.bpm)),
        )
        self.global_bpm_spin.blockSignals(True)
        self.global_bpm_spin.setValue(value)
        self.global_bpm_spin.blockSignals(False)
        self._sync_reference_bpm_follow_control()

    def _sync_reference_bpm_follow_control(self) -> None:
        if not hasattr(self, "reference_bpm_follow"):
            return
        self.reference_bpm_follow.blockSignals(True)
        self.reference_bpm_follow.setChecked(
            bool(self.reference_layer_settings.get("follow_reference_bpm", True))
        )
        self.reference_bpm_follow.setEnabled(bool(self.reference_audio_path))
        self.reference_bpm_follow.blockSignals(False)

    def _set_global_bpm_compact(self, compact: bool) -> None:
        if not hasattr(self, "global_bpm_spin"):
            return
        self.global_bpm_label.setVisible(True)
        self.reference_bpm_follow.setText("AUTO" if compact else tr("自动跟随"))
        self.reference_bpm_follow.setFixedWidth(48 if compact else 72)
        self.global_bpm_spin.setFixedWidth(84)
        self.global_bpm_control.setFixedWidth(188 if compact else 212)

    def _commit_global_bpm_from_control(self) -> None:
        new_bpm = int(self.global_bpm_spin.value())
        self.reference_layer_settings["follow_reference_bpm"] = False
        self._pending_reference_tempo_path = ""
        self._cancel_reference_tempo_worker()
        self._sync_reference_bpm_follow_control()
        self._apply_global_bpm(
            new_bpm,
            autosave_reason="global bpm",
            toast=trf(
                "全局 BPM 已设为 {bpm}；已停止自动跟随参考音乐",
                bpm=new_bpm,
            ),
        )

    def _apply_global_bpm(
        self,
        new_bpm: int,
        *,
        autosave_reason: str,
        toast: str,
    ) -> bool:
        new_bpm = max(1, min(BDO_STATIC_BPM_MAX, int(new_bpm)))
        if new_bpm == int(self.bpm_override or self.bpm):
            self._autosave_project(autosave_reason, immediate=True)
            return False
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.bpm_override = new_bpm
        self._invalidate_transcription_rhythm_diagnostic()
        self.automatic_harmony_analysis = None
        self.harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.instrument_match_analysis = None
        self._apply_workspace_change(ModelChange.grid())
        self._schedule_timeline_validation_refresh()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis()
            self._start_reference_timbre_analysis(force_restart=True)
        self._autosave_project(autosave_reason, immediate=True)
        self.show_toast(toast, kind="success")
        return True

    def _reference_bpm_follow_toggled(self, checked: bool) -> None:
        self.reference_layer_settings["follow_reference_bpm"] = bool(checked)
        if checked and self.transcription_result is not None:
            self._maybe_start_reference_bpm_follow(interval=False)
        elif checked and self.reference_audio_path:
            self._start_reference_tempo_analysis(self.reference_audio_path)
        elif not checked:
            self._pending_reference_tempo_path = ""
            self._cancel_reference_tempo_worker()
        if not self.loading_project:
            self._autosave_project("reference bpm follow", immediate=True)

    def _maybe_start_reference_bpm_follow(self, *, interval: bool) -> bool:
        if (
            interval
            or not self.reference_audio_path
            or not bool(
                self.reference_layer_settings.get("follow_reference_bpm", True)
            )
            or self.transcription_rhythm_runner.busy
            or not self.transcription_session.state.cache_key
            or not self.transcription_session.candidates
        ):
            return False
        self._reference_bpm_follow_pending = True
        started = self.transcription_rhythm_runner.start_diagnostic(
            cache_key=self.transcription_session.state.cache_key,
            candidates=tuple(self.transcription_session.candidates),
            settings=self._current_project_rhythm_settings(),
            alignment_config=RhythmAlignmentConfig(profile="auto"),
        )
        if not started:
            self._reference_bpm_follow_pending = False
        return started

    def _consume_reference_bpm_follow_result(self, sidecar: object) -> bool:
        if not getattr(self, "_reference_bpm_follow_pending", False):
            return False
        self._reference_bpm_follow_pending = False
        alignment = getattr(sidecar, "alignment", None)
        estimate = getattr(alignment, "estimate", None)
        self._apply_reference_tempo_estimate(estimate)
        return True

    def _apply_reference_tempo_estimate(self, estimate: object) -> bool:
        reliable = bool(
            estimate is not None
            and not bool(getattr(estimate, "used_project_fallback", False))
            and float(getattr(estimate, "confidence", 0.0)) >= 0.58
            and int(getattr(estimate, "beat_count", 0)) >= 8
            and float(getattr(estimate, "tempo_drift_ratio", 1.0)) <= 0.12
        )
        if not reliable:
            self._set_transcription_status(
                tr("参考 BPM 证据不足；保留当前全局 BPM，可手动调节")
            )
            return False
        detected_value = float(getattr(estimate, "detected_bpm"))
        while detected_value > BDO_STATIC_BPM_MAX:
            detected_value /= 2.0
        while detected_value < 30.0 and detected_value * 2.0 <= BDO_STATIC_BPM_MAX:
            detected_value *= 2.0
        detected = max(1, min(BDO_STATIC_BPM_MAX, round(detected_value)))
        changed = self._apply_global_bpm(
            detected,
            autosave_reason="reference bpm follow",
            toast=trf(
                "已跟随参考音乐：全局 BPM {bpm} · 置信 {confidence}%",
                bpm=detected,
                confidence=round(float(getattr(estimate, "confidence")) * 100),
            ),
        )
        if not changed:
            self._set_transcription_status(
                trf("参考音乐 BPM 与工程一致：{bpm}", bpm=detected)
            )
        return True

    def _reference_bpm_follow_stopped(self) -> None:
        self._reference_bpm_follow_pending = False

    def _reference_bpm_audio_changed(self, path: str) -> None:
        self._sync_reference_bpm_follow_control()
        should_analyze = bool(path) and bool(
            self.reference_layer_settings.get("follow_reference_bpm", True)
        )
        self._pending_reference_tempo_path = path if should_analyze else ""
        self._cancel_reference_tempo_worker()
        if should_analyze and getattr(self, "reference_tempo_worker", None) is None:
            self._start_reference_tempo_analysis(path)

    def _start_reference_tempo_analysis(self, path: str) -> None:
        if getattr(self, "reference_tempo_worker", None) is not None:
            self._pending_reference_tempo_path = path
            return
        self._pending_reference_tempo_path = ""
        worker = ReferenceTempoWorker(
            path,
            self,
            prior_bpm=float(self.bpm_override or self.bpm),
        )
        self.reference_tempo_worker = worker
        worker.succeeded.connect(
            lambda estimate, current=worker:
            self._reference_tempo_succeeded(current, estimate)
        )
        worker.failed.connect(
            lambda _message, current=worker:
            self._reference_tempo_failed(current)
        )
        worker.finished.connect(
            lambda current=worker: self._reference_tempo_finished(current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_status(tr("正在检测参考音乐 BPM…"))
        worker.start()

    def _reference_tempo_succeeded(
        self,
        worker: ReferenceTempoWorker,
        estimate: object,
    ) -> None:
        if (
            worker is not getattr(self, "reference_tempo_worker", None)
            or worker.path != self.reference_audio_path
            or not bool(
                self.reference_layer_settings.get("follow_reference_bpm", True)
            )
        ):
            return
        self._apply_reference_tempo_estimate(estimate)

    def _reference_tempo_failed(self, worker: ReferenceTempoWorker) -> None:
        if worker is getattr(self, "reference_tempo_worker", None):
            self._set_transcription_status(
                tr("未能可靠检测参考 BPM；保留当前值，可手动调节")
            )

    def _reference_tempo_finished(self, worker: ReferenceTempoWorker) -> None:
        if worker is getattr(self, "reference_tempo_worker", None):
            self.reference_tempo_worker = None
        if getattr(self, "workspace_close_pending", False):
            self._pending_reference_tempo_path = ""
            QTimer.singleShot(0, self.close)
            return
        pending_path = getattr(self, "_pending_reference_tempo_path", "")
        if pending_path:
            QTimer.singleShot(
                0,
                lambda path=pending_path: self._start_pending_reference_tempo_analysis(
                    path
                ),
            )

    def _start_pending_reference_tempo_analysis(self, path: str) -> None:
        if (
            path != self.reference_audio_path
            or not bool(
                self.reference_layer_settings.get("follow_reference_bpm", True)
            )
        ):
            return
        self._start_reference_tempo_analysis(path)

    def _cancel_reference_tempo_worker(self) -> None:
        worker = getattr(self, "reference_tempo_worker", None)
        if worker is not None:
            worker.cancel()

    def _open_multiplayer_synchronizer(self) -> None:
        from bdo_music_composer.ui.dialogs.multiplayer_sync_dialog import (
            MultiplayerSyncDialog,
        )

        dialog = MultiplayerSyncDialog(
            self,
            global_bpm=int(self.bpm_override or self.bpm),
            meter=int(self.time_sig),
        )
        dialog.exec()


__all__ = ["BDO_STATIC_BPM_MAX", "WorkspaceTempoHostMixin"]
