"""Qt host actions for appending MIDI or BDO material to an open project."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QMenu

from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.editor.arrangement_import import plan_arrangement_append
from bdo_music_composer.export.bdo_score import read_bdo_score
from bdo_music_composer.ui.editor.editor_ui_helpers import TRACK_COLORS
from bdo_music_composer.ui.editor_import_qt import (
    prepare_midi_import,
    track_states_from_bdo_score,
)
from bdo_music_composer.ui.i18n import tr, trf


_DROPPABLE_ARRANGEMENT_SUFFIXES = {
    ".mid": "midi",
    ".midi": "midi",
    ".bdo": "bdo",
}


def arrangement_source_type(path: Path) -> str | None:
    """Classify only the user-facing score formats accepted by file drop."""

    return _DROPPABLE_ARRANGEMENT_SUFFIXES.get(path.suffix.casefold())


def _local_file_drop_paths(event: QDragEnterEvent | QDropEvent) -> tuple[Path, ...]:
    mime = event.mimeData()
    if not mime.hasUrls():
        return ()
    return tuple(
        Path(url.toLocalFile())
        for url in mime.urls()
        if url.isLocalFile() and url.toLocalFile()
    )


class ArrangementImportHostMixin:
    """Add external material without replacing project-owned global state."""

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        paths = _local_file_drop_paths(event)
        if (
            len(paths) == 1
            and paths[0].is_file()
            and arrangement_source_type(paths[0]) is not None
        ):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _local_file_drop_paths(event)
        if not self._handle_dropped_arrangement_paths(paths):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _handle_dropped_arrangement_paths(
        self,
        paths: tuple[Path, ...],
    ) -> bool:
        if len(paths) != 1:
            QMessageBox.warning(
                self,
                tr("拖入文件失败"),
                tr("一次只能拖入一个 MIDI 或游戏曲谱文件。"),
            )
            return False
        path = paths[0]
        source_type = arrangement_source_type(path)
        if source_type is None or not path.is_file():
            QMessageBox.warning(
                self,
                tr("拖入文件失败"),
                tr("仅支持 MIDI 文件（.mid、.midi）和游戏曲谱（.bdo）。"),
            )
            return False
        if self._arrangement_drop_import_is_busy():
            QMessageBox.warning(
                self,
                tr("暂时无法导入文件"),
                tr("当前有导出或分析任务正在运行。请等待任务完成后再拖入文件。"),
            )
            return False

        if not self.tracks:
            self._open_dropped_arrangement_source(path, source_type)
            return True

        action = self._prompt_dropped_arrangement_action(path)
        if action == "append":
            self._append_arrangement_source(path, source_type)
            return True
        if action == "save_open":
            if self._save_project_before_dropped_open(path):
                self._open_dropped_arrangement_source(path, source_type)
            return True
        return True

    def _arrangement_drop_import_is_busy(self) -> bool:
        return bool(
            getattr(self, "loading_project", False)
            or getattr(self, "worker", None) is not None
            or getattr(self, "workspace_transcription_worker", None) is not None
            or getattr(self, "transcription_assist_worker", None) is not None
        )

    def _prompt_dropped_arrangement_action(self, path: Path) -> str:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(tr("导入文件"))
        dialog.setText(trf(
            "当前混音台已有内容。如何处理 {file}？",
            file=path.name,
        ))
        dialog.setInformativeText(tr(
            "保存当前工程后打开该文件，或将它追加到现有混音台。"
        ))
        save_open_button = dialog.addButton(
            tr("保存并打开"), QMessageBox.ButtonRole.AcceptRole
        )
        append_button = dialog.addButton(
            tr("追加"), QMessageBox.ButtonRole.ActionRole
        )
        close_button = dialog.addButton(
            tr("关闭"), QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(append_button)
        dialog.setEscapeButton(close_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        role = (
            dialog.buttonRole(clicked)
            if clicked is not None
            else QMessageBox.ButtonRole.RejectRole
        )
        if role == QMessageBox.ButtonRole.AcceptRole:
            return "save_open"
        if role == QMessageBox.ButtonRole.ActionRole:
            return "append"
        return "close"

    def _save_project_before_dropped_open(self, path: Path) -> bool:
        queued = self._autosave_project(
            "save before opening dropped score",
            immediate=True,
        )
        saved = (
            queued is not False
            and self._wait_for_autosave_idle()
            and self._autosave_retry_request is None
            and self.autosave_project_dir is not None
            and (self.autosave_project_dir / "project.json").is_file()
        )
        if not saved:
            QMessageBox.warning(
                self,
                tr("保存当前工程失败"),
                trf(
                    "当前工程未能安全保存，已取消打开 {file}。",
                    file=path.name,
                ),
            )
            return False
        self._record_recent(
            "project",
            self.autosave_project_dir / "project.json",
            self.output_name.text().strip() or self.autosave_project_dir.name,
        )
        return True

    def _open_dropped_arrangement_source(
        self,
        path: Path,
        source_type: str,
    ) -> None:
        if source_type == "midi":
            self._open_midi_path(path)
            return
        if source_type == "bdo":
            self._open_bdo_score_path(path)
            return
        raise ValueError("unsupported arrangement source")

    def _install_arrangement_import_menu(self, project_menu: QMenu) -> None:
        append_menu = project_menu.addMenu(tr("追加音轨"))
        midi_action = append_menu.addAction(tr("从 MIDI 文件…"))
        midi_action.triggered.connect(self._browse_append_midi_tracks)
        bdo_action = append_menu.addAction(tr("从游戏曲谱…"))
        bdo_action.triggered.connect(self._browse_append_bdo_tracks)

    def _browse_append_midi_tracks(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择要追加的 MIDI 文件"),
            "",
            tr("MIDI 文件 (*.mid *.midi);;所有文件 (*.*)"),
        )
        if path:
            self._append_arrangement_source(Path(path), "midi")

    def _browse_append_bdo_tracks(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择要追加的游戏曲谱"),
            "",
            tr("游戏曲谱 (*.bdo);;所有文件 (*.*)"),
        )
        if path:
            self._append_arrangement_source(Path(path), "bdo")

    def _arrangement_import_offset(self) -> float | None:
        playhead_ms = max(0.0, float(self.timeline.playhead_ms))
        if playhead_ms <= 0.5:
            return 0.0
        at_playhead = tr("当前播放头")
        at_start = tr("工程开头")
        selected, accepted = QInputDialog.getItem(
            self,
            tr("放置追加音轨"),
            tr("选择导入内容的起始位置"),
            (at_playhead, at_start),
            0,
            False,
        )
        if not accepted:
            return None
        return playhead_ms if selected == at_playhead else 0.0

    def _append_arrangement_source(self, path: Path, source_type: str) -> None:
        try:
            if source_type == "midi":
                settings = ConversionSettings.from_preferences(
                    self.config.get("conversion_settings")
                )
                imported = prepare_midi_import(path, settings)
                source_tracks = imported.tracks
                source_lyrics = imported.lyric_events
                source_bpm = imported.bpm
                source_meter = imported.time_signature
            elif source_type == "bdo":
                snapshot = read_bdo_score(path, allow_trailing_data=True)
                source_tracks = track_states_from_bdo_score(snapshot)
                source_lyrics = ()
                source_bpm = int(snapshot.bpm)
                source_meter = int(snapshot.time_signature)
            else:
                raise ValueError("unsupported arrangement source")
            offset_ms = self._arrangement_import_offset()
            if offset_ms is None:
                return
            plan = plan_arrangement_append(
                self.tracks,
                source_tracks,
                reserved_track_ids=self._reserved_track_ids(),
                offset_ms=offset_ms,
                lyric_events=source_lyrics,
                master_effects=self._current_master_effects(),
                colors=TRACK_COLORS,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("追加音轨失败"),
                trf("无法追加 {file}：{error}", file=path.name, error=exc),
            )
            return

        self._stop_preview(reset_playhead=False)
        self._push_project_snapshot()
        self.tracks.extend(plan.tracks)
        self.lyric_events.extend(plan.lyric_events)
        self._select_track(plan.tracks[0])
        self._refresh_tracks()
        self._schedule_timeline_validation_refresh()
        self._autosave_project("append arrangement tracks", immediate=True)
        timing_note = (
            tr(" · 已按源文件实际时间保留，工程 BPM/拍号未改变")
            if source_bpm != self.bpm or source_meter != self.time_sig
            else ""
        )
        message = trf(
            "已追加 {file} · {tracks} 轨 · {notes} 音符{timing_note}",
            file=path.name,
            tracks=len(plan.tracks),
            notes=plan.note_count,
            timing_note=timing_note,
        )
        self.status_label.setText(message)
        self.inspector_text.setText(message)
        self.show_toast(message, kind="success", duration_ms=4200)


__all__ = ["ArrangementImportHostMixin", "arrangement_source_type"]
