"""Focused conversion validation, comparison, and coverage dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.audio.bdo_audio_research import sample_coverage_for_tracks
from bdo_music_composer.export.bdo_score import compare_scores, read_bdo_score
from bdo_music_composer.export.bdo_validation import (
    ValidationIssue,
    localized_validation_message,
)
from bdo_music_composer.ui.i18n import tr, trf, trfv, trv
from bdo_music_composer.core.project_paths import WWISE_MIDI_MAP_PATH


BDO_SAMPLE_MAP_PATH = WWISE_MIDI_MAP_PATH


def _sample_coverage_status_value(status: str) -> object:
    source = {
        "verified_zone": "全部覆盖",
        "partial": "部分覆盖",
        "unmapped": "未映射",
    }.get(str(status))
    return trv(source) if source is not None else str(status)


class ConversionCheckDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.report = ""
        self.setWindowTitle(tr("转换检查"))
        self.resize(1000, 700)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel(tr("转换检查"))
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        subtitle = QLabel(tr("先处理阻断项，再逐条确认预期变化；双击问题可定位。"))
        subtitle.setObjectName("Muted")
        title_row.addWidget(subtitle, stretch=1)
        layout.addLayout(title_row)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        layout.addLayout(summary)
        self.status_card = QLabel()
        self.issue_card = QLabel()
        self.warning_card = QLabel()
        self.fix_card = QLabel()
        for card in (self.status_card, self.issue_card, self.warning_card, self.fix_card):
            card.setObjectName("CheckCard")
            card.setMinimumHeight(46)
            card.setWordWrap(True)
            summary.addWidget(card, stretch=1)

        report_label = QLabel(tr("导出摘要"))
        report_label.setObjectName("SectionLabel")
        layout.addWidget(report_label)
        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setMaximumHeight(140)
        layout.addWidget(self.report_view)

        issue_heading = QHBoxLayout()
        issue_label = QLabel(tr("问题与预期变化"))
        issue_label.setObjectName("SectionLabel")
        issue_heading.addWidget(issue_label)
        issue_hint = QLabel(tr("严重问题优先显示"))
        issue_hint.setObjectName("Muted")
        issue_heading.addWidget(issue_hint)
        issue_heading.addStretch(1)
        layout.addLayout(issue_heading)
        self.issue_list = QListWidget()
        self.issue_list.setToolTip(tr("双击问题可定位到对应轨道和音符"))
        self.issue_list.itemDoubleClicked.connect(self._focus_issue)
        layout.addWidget(self.issue_list, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.fix_btn = buttons.addButton(tr("修复可自动处理项"), QDialogButtonBox.ActionRole)
        self.fix_btn.clicked.connect(self._apply_fixes)
        copy_btn = buttons.addButton(tr("复制报告"), QDialogButtonBox.ActionRole)
        copy_btn.clicked.connect(self._copy_report)
        compare_btn = buttons.addButton(tr("比较 BDO 乐谱"), QDialogButtonBox.ActionRole)
        compare_btn.clicked.connect(self._compare_scores)
        coverage_btn = buttons.addButton(tr("样本覆盖"), QDialogButtonBox.ActionRole)
        coverage_btn.clicked.connect(self._show_sample_coverage)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self.report)

    def _apply_fixes(self) -> None:
        message = self.parent_window._apply_conversion_check_fixes()
        self._refresh()
        QMessageBox.information(self, tr("转换检查"), message)

    def _focus_issue(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.UserRole)
        if isinstance(issue, ValidationIssue):
            self.parent_window._focus_validation_issue(issue)

    def _compare_scores(self) -> None:
        first_default = str(getattr(self.parent_window, "last_export_path", "") or self.parent_window.last_output_dir)
        first, _filter = QFileDialog.getOpenFileName(
            self,
            tr("选择基准 BDO 乐谱"),
            first_default,
            tr("BDO 乐谱 (*);;所有文件 (*.*)"),
        )
        if not first:
            return
        second, _filter = QFileDialog.getOpenFileName(
            self,
            tr("选择对比 BDO 乐谱"),
            str(Path(first).parent),
            tr("BDO 乐谱 (*);;所有文件 (*.*)"),
        )
        if not second:
            return
        try:
            result = compare_scores(read_bdo_score(Path(first)), read_bdo_score(Path(second)))
        except Exception as exc:
            QMessageBox.warning(self, tr("谱面对比失败"), str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("BDO 谱面对比"))
        dialog.resize(860, 560)
        body = QVBoxLayout(dialog)
        header = QLabel(trf(
            "基准：{first}\n对比：{second}",
            first=Path(first).name,
            second=Path(second).name,
        ))
        header.setWordWrap(True)
        body.addWidget(header)
        report = QTextEdit()
        report.setReadOnly(True)
        report.setPlainText(result.summary(tr, trf))
        body.addWidget(report, stretch=1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        body.addWidget(close)
        dialog.exec()

    def _show_sample_coverage(self) -> None:
        try:
            tracks = list(self.parent_window.tracks)
            coverage = sample_coverage_for_tracks(tracks, BDO_SAMPLE_MAP_PATH)
        except Exception as exc:
            QMessageBox.warning(self, tr("样本覆盖检查失败"), str(exc))
            return
        lines = [tr("当前工程的 Wwise 键位/力度层映射覆盖（不代表 DSP 已通过游戏 A/B）："), ""]
        for track, item in zip(tracks, coverage):
            lines.append(trf(
                "轨道 {track_id} · {track}: {covered}/{total} · {status}",
                track_id=track.track_id,
                track=track.display_name,
                covered=item.covered_notes,
                total=item.total_notes,
                status=_sample_coverage_status_value(item.status),
            ))
            if item.missing_note_indices:
                lines.append(trf(
                    "  缺失音符索引: {indices}",
                    indices=list(item.missing_note_indices[:24]),
                ))
        QMessageBox.information(self, tr("样本覆盖"), "\n".join(lines))

    def _refresh(self) -> None:
        analysis = self.parent_window._analyze_conversion()
        self.report = analysis["report"]
        self.report_view.setPlainText(self.report)
        self.issue_list.clear()
        severity_labels = {
            "error": "需处理",
            "warning": "需人工确认",
            "info": "变化说明",
        }
        for issue in analysis["issues"]:
            if issue.track_id is not None:
                location = trfv("轨道 {track_id}", track_id=issue.track_id)
            elif issue.related_track_ids:
                location = trfv(
                    "轨道 {track_id}",
                    track_id=", ".join(
                        str(track_id) for track_id in issue.related_track_ids
                    ),
                )
            else:
                location = trv("全局")
            item = QListWidgetItem(trf(
                "[{severity}] {location} · {message}",
                severity=trv(severity_labels[issue.severity]),
                location=location,
                message=localized_validation_message(
                    issue,
                    tr,
                    format_translate=trf,
                ),
            ))
            item.setData(Qt.UserRole, issue)
            if issue.severity == "error":
                item.setForeground(QColor("#ef7772"))
            elif issue.severity == "warning":
                item.setForeground(QColor("#e2b968"))
            self.issue_list.addItem(item)
        if self.issue_list.count() == 0:
            item = QListWidgetItem(tr("未发现阻断项或待确认变化"))
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QColor("#79c58a"))
            self.issue_list.addItem(item)
        issue_count = analysis["issue_count"]
        warning_count = analysis["warning_count"]
        fixable_count = analysis["fixable_count"]
        if issue_count:
            status = "需处理"
        elif warning_count:
            status = "需人工确认"
        else:
            status = "可转换"
        self.status_card.setText(trf("状态\n{status}", status=trv(status)))
        self.issue_card.setText(trf("问题\n{count}", count=issue_count))
        self.warning_card.setText(trf("人工确认\n{count}", count=warning_count))
        transpose = analysis.get("suggested_transpose")
        fix_text = trf("可自动修复\n{count} 项", count=fixable_count)
        if transpose is not None:
            fix_text += trf(" · 移调 {transpose:+d}", transpose=transpose)
        self.fix_card.setText(fix_text)
        self.fix_btn.setEnabled(fixable_count > 0)

    def retranslate_dynamic_content(self) -> None:
        """Regenerate the structured check report in the active locale."""

        self._refresh()
