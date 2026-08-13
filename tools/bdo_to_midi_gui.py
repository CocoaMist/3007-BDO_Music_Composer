#!/usr/bin/env python3
"""Small standalone window for :mod:`bdo_to_midi`; not part of the app UI."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QCheckBox, QVBoxLayout,
    QWidget,
)

from bdo_to_midi import convert_bdo_to_midi, read_score, verify_lossless_metadata


class BdoToMidiWindow(QMainWindow):
    """A deliberately self-contained, one-job conversion window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BDO → MIDI 临时转换工具")
        self.setMinimumWidth(620)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        heading = QLabel("BDO v9 → MIDI")
        heading.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(heading)
        explanation = QLabel(
            "输出为可播放的标准 MIDI，并在 MIDI 元数据内无损保留 BDO 的 "
            "音高、ntype、双力度、毫秒时间、乐器与轨道设置。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("选择 .bdo 曲谱文件")
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("选择输出 .mid 文件")
        form.addRow("BDO 文件：", self._path_row(self.input_edit, self._choose_input))
        form.addRow("MIDI 输出：", self._path_row(self.output_edit, self._choose_output))
        layout.addLayout(form)

        self.verify_check = QCheckBox("转换后回读校验无损 BDO 元数据")
        self.verify_check.setChecked(True)
        layout.addWidget(self.verify_check)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        self.status = QLabel("请选择 BDO 文件。")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        layout.addStretch()
        self.convert_button = QPushButton("转换为 MIDI")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(self._convert)
        layout.addWidget(self.convert_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.setCentralWidget(root)

    @staticmethod
    def _path_row(edit: QLineEdit, callback) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit)
        button = QPushButton("浏览…")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return row

    def _choose_input(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "选择 BDO 曲谱", "", "BDO 曲谱 (*.bdo);;所有文件 (*.*)")
        if not selected:
            return
        source = Path(selected)
        self.input_edit.setText(str(source))
        if not self.output_edit.text().strip():
            self.output_edit.setText(str(source.with_suffix(".mid")))

    def _choose_output(self) -> None:
        suggested = self.output_edit.text().strip() or self.input_edit.text().strip()
        selected, _ = QFileDialog.getSaveFileName(self, "保存 MIDI", suggested, "MIDI 文件 (*.mid *.midi)")
        if selected:
            output = Path(selected)
            self.output_edit.setText(str(output if output.suffix else output.with_suffix(".mid")))

    def _convert(self) -> None:
        source = Path(self.input_edit.text().strip()).expanduser()
        output_text = self.output_edit.text().strip()
        output = Path(output_text).expanduser() if output_text else source.with_suffix(".mid")
        if not source.is_file():
            self._show_error("请选择存在的 BDO 文件。")
            return
        if output.exists() and QMessageBox.question(
            self, "覆盖输出", f"文件已存在，是否覆盖？\n{output}",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.convert_button.setEnabled(False)
        self.status.setText("正在转换…")
        QApplication.processEvents()
        try:
            document = read_score(source)
            convert_bdo_to_midi(document, output)
            if self.verify_check.isChecked():
                verify_lossless_metadata(document, output)
        except (OSError, ValueError) as error:
            self._show_error(str(error))
        else:
            verified = "；无损元数据已校验" if self.verify_check.isChecked() else ""
            self.status.setText(f"完成：{document.total_notes} 个音符已写入\n{output}{verified}")
        finally:
            self.convert_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.status.setText(f"失败：{message}")
        QMessageBox.critical(self, "转换失败", message)


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("BDO to MIDI Temporary Tool")
    window = BdoToMidiWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
