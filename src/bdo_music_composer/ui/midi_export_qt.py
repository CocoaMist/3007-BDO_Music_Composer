"""Atomic standard-MIDI publication from the current editor model."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox

from bdo_common.atomic_io import atomic_write_bytes
from bdo_music_composer.editor.game_score_model import formal_score_tracks
from bdo_music_composer.editor.preview_midi_writer import build_filtered_midi_bytes
from bdo_music_composer.ui.i18n import tr, trf


class MidiExportHostMixin:
    def _install_midi_export_action(self, project_menu: QMenu) -> None:
        action = project_menu.addAction(tr("导出标准 MIDI…"))
        action.triggered.connect(self._export_standard_midi)

    def _export_standard_midi(self) -> None:
        name = self.output_name.text().strip() or tr("未命名曲谱")
        default_path = Path(self.last_output_dir) / f"{name}.mid"
        raw_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("导出标准 MIDI"),
            str(default_path),
            tr("MIDI 文件 (*.mid *.midi);;所有文件 (*.*)"),
        )
        if not raw_path:
            return
        target = Path(raw_path)
        if target.suffix.lower() not in {".mid", ".midi"}:
            target = target.with_suffix(".mid")
        try:
            tracks = list(formal_score_tracks(self.tracks))
            if not tracks:
                raise ValueError(tr("当前工程没有可导出的轨道"))
            payload = build_filtered_midi_bytes(
                tracks,
                int(self.bpm_override or self.bpm),
                int(self.time_sig),
                self.lyric_events,
            )
            atomic_write_bytes(target, payload)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("导出 MIDI 失败"),
                trf("无法导出 MIDI：{error}", error=exc),
            )
            return
        self.last_output_dir = str(target.parent)
        message = trf(
            "已导出 {file} · {tracks} 轨",
            file=target.name,
            tracks=len(tracks),
        )
        self.status_label.setText(message)
        self.show_toast(message, kind="success")


__all__ = ["MidiExportHostMixin"]
