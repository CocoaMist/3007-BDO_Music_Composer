"""Qt single-writer lifecycle for reliable project autosaves."""

from __future__ import annotations

from dataclasses import replace
import traceback

from PySide6.QtCore import QThread, QTimer, Signal

from bdo_music_composer.app.crash_logging import append_crash_log
from bdo_music_composer.project.project_persistence import (
    AutosaveRequest,
    write_autosave,
)
from bdo_music_composer.ui.i18n import trf


class AutosaveWriteWorker(QThread):
    """Write one already-frozen request away from the GUI thread."""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, request: AutosaveRequest):
        super().__init__()
        self.request = request

    def run(self) -> None:
        try:
            self.succeeded.emit(str(write_autosave(self.request)))
        except BaseException as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")


class ProjectAutosaveHostMixin:
    """Own latest-state coalescing, bounded retries, and close continuation."""

    def _autosave_note_editor_draft(
        self,
        editor: object,
        reason: str = "note block edit",
    ) -> bool:
        """Checkpoint one completed editor transaction without committing it."""

        if (
            editor is not self.active_transcription_editor
            or editor.track not in self.tracks
            or self.loading_project
        ):
            return False
        self._autosave_project(str(reason or "note block edit"), immediate=True)
        return True

    def _autosave_track_view(self) -> tuple[object, ...]:
        """Overlay the active draft only in an immutable recovery snapshot."""

        editor = self.active_transcription_editor
        if editor is None or editor.track not in self.tracks:
            return tuple(self.tracks)
        draft_notes = list(editor.edited_notes())
        target_track_id = int(editor.track.track_id)
        return tuple(
            replace(track, notes=list(draft_notes))
            if int(track.track_id) == target_track_id
            else track
            for track in self.tracks
        )

    def _start_autosave_worker(self, request: AutosaveRequest) -> None:
        if request is not self._autosave_retry_request:
            self._autosave_retry_request = None
            self._autosave_retry_count = 0
        worker = AutosaveWriteWorker(request)
        self.autosave_worker = worker
        worker.succeeded.connect(
            lambda _path, current=worker:
            self._autosave_succeeded(current)
        )
        worker.failed.connect(
            lambda message, current=worker:
            self._autosave_failed(current, message)
        )
        worker.finished.connect(
            lambda current=worker: self._autosave_worker_finished(current)
        )
        worker.start()

    def _autosave_succeeded(self, worker: AutosaveWriteWorker) -> None:
        if self.autosave_worker is not worker:
            return
        if self._autosave_retry_request is worker.request:
            self._autosave_retry_request = None
            self._autosave_retry_count = 0

    def _autosave_failed(
        self,
        worker: AutosaveWriteWorker,
        message: str,
    ) -> None:
        if self.autosave_worker is not worker:
            return
        append_crash_log("Autosave failed", message)
        self.status_label.setText(
            trf("自动保存失败：{error}", error=message.splitlines()[0])
        )
        if self.pending_autosave_request is None:
            if self._autosave_retry_request is worker.request:
                self._autosave_retry_count += 1
            else:
                self._autosave_retry_request = worker.request
                self._autosave_retry_count = 1
            if self._autosave_retry_count <= 3:
                self.pending_autosave_request = worker.request

    def _autosave_worker_finished(self, worker: AutosaveWriteWorker) -> None:
        if self.autosave_worker is not worker:
            return
        self.autosave_worker = None
        worker.deleteLater()
        pending = self.pending_autosave_request
        self.pending_autosave_request = None
        if pending is not None:
            self._start_autosave_worker(pending)
        elif self.workspace_close_pending:
            QTimer.singleShot(0, self.close)


__all__ = ["AutosaveWriteWorker", "ProjectAutosaveHostMixin"]
