"""Non-modal presentation for one signed background update."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.ui.i18n import localizer, tr, trf
from bdo_music_composer.update.manifest import UpdateManifest


def _active_locale() -> str:
    active = localizer()
    return str(active.language) if active is not None else "zh_CN"


class SelfUpdateDialog(QDialog):
    """Show authenticated release notes without blocking background work."""

    def __init__(
        self,
        manifest: UpdateManifest,
        source: str,
        *,
        auto_download: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manifest = manifest
        self.source = str(source)
        self.auto_download = bool(auto_download)
        self._ready = False
        self._progress_percent: int | None = None
        self.setObjectName("SelfUpdateDialog")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(620, 440)
        self.setMinimumSize(500, 340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("PanelTitle")
        layout.addWidget(self.title_label)

        self.source_label = QLabel()
        self.source_label.setObjectName("Muted")
        layout.addWidget(self.source_label)

        self.notes_label = QLabel()
        self.notes_label.setObjectName("SectionLabel")
        layout.addWidget(self.notes_label)

        self.notes_view = QTextBrowser()
        self.notes_view.setObjectName("SelfUpdateNotes")
        self.notes_view.setOpenExternalLinks(False)
        layout.addWidget(self.notes_view, stretch=1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.close_button = buttons.button(QDialogButtonBox.Close)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)
        self._render()

    def _render(self) -> None:
        version = str(self.manifest.version)
        self.setWindowTitle(trf("更新日志 · v{version}", version=version))
        self.title_label.setText(trf("更新日志 · v{version}", version=version))
        source_label = {"github": "GitHub", "gitee": "Gitee"}.get(
            self.source.casefold(),
            self.source,
        )
        self.source_label.setText(
            trf("更新来源：{source}", source=source_label)
        )
        self.notes_label.setText(tr("本次更新"))
        notes = self.manifest.localized_notes(_active_locale()).strip()
        self.notes_view.setPlainText(notes or tr("此版本暂无详细说明。"))
        self.close_button.setText(tr("稍后"))
        if self._ready:
            self.status_label.setText(
                tr("更新包已通过验证；将在下次启动时自动安装。")
            )
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat(tr("准备完成"))
        elif self.auto_download:
            self.status_label.setText(tr("正在后台下载更新…"))
            if self._progress_percent is None:
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setFormat("")
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(self._progress_percent)
                self.progress_bar.setFormat(
                    trf("下载进度：{percent}%", percent=self._progress_percent)
                )
        else:
            self.status_label.setText(
                tr("已发现新版本；可在软件更新设置中启用后台下载。")
            )
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(tr("等待下载"))

    def set_progress(self, downloaded: int, total: int) -> None:
        if total <= 0:
            return
        self._progress_percent = max(
            0,
            min(100, round(int(downloaded) * 100 / int(total))),
        )
        self._render()

    def set_ready(self) -> None:
        self._ready = True
        self._progress_percent = 100
        self._render()

    def retranslate_dynamic_content(self) -> None:
        self._render()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange:
            self._render()


__all__ = ["SelfUpdateDialog"]
