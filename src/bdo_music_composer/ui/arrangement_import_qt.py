"""Qt host actions for appending MIDI or BDO material to an open project."""

from __future__ import annotations

from pathlib import Path

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


class ArrangementImportHostMixin:
    """Add external material without replacing project-owned global state."""

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


__all__ = ["ArrangementImportHostMixin"]
