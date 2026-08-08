"""Offline release notes and an explicit GitHub update-check surface."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.app.application_metadata import (
    APP_VERSION,
    GITHUB_RELEASES_URL,
)
from bdo_music_composer.app.release_notes import (
    ReleaseNotesDocument,
    ReleaseNotesError,
    load_release_notes,
)
from bdo_music_composer.app.update_check import (
    UpdateCheckError,
    UpdateErrorCode,
    UpdateResult,
    UpdateStatus,
)
from bdo_music_composer.ui.update_check_qt import UpdateCheckController
from bdo_music_composer.ui.i18n import localizer, tr, trf


def _active_locale() -> str:
    active = localizer()
    return str(active.language) if active is not None else "zh_CN"


class ReleaseNotesDialog(QDialog):
    """Keep local history usable even when the optional GitHub check fails."""

    @classmethod
    def from_resource(
        cls,
        *,
        parent: QWidget | None = None,
        auto_check: bool = True,
    ) -> "ReleaseNotesDialog":
        try:
            document = load_release_notes()
        except ReleaseNotesError as exc:
            logging.getLogger(__name__).warning(
                "release notes unavailable: %s",
                exc.code,
            )
            document = None
        return cls(document, parent=parent, auto_check=auto_check)

    def __init__(
        self,
        document: ReleaseNotesDocument | None,
        *,
        parent: QWidget | None = None,
        update_controller: UpdateCheckController | None = None,
        include_development: bool | None = None,
        auto_check: bool = True,
    ) -> None:
        super().__init__(parent)
        self.document = document
        self.include_development = (
            not bool(getattr(sys, "frozen", False))
            if include_development is None
            else bool(include_development)
        )
        self.update_controller = update_controller or UpdateCheckController(self)
        self._auto_check = bool(auto_check)
        self._auto_check_started = False
        self._hide_prepared = False
        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setSingleShot(True)
        self._auto_check_timer.timeout.connect(
            self._start_auto_check_if_visible
        )
        self._checking = False
        self._last_update_result: UpdateResult | None = None
        self._last_update_error: UpdateCheckError | None = None
        self._release_url = GITHUB_RELEASES_URL
        self._display_entries: list[tuple[str, object, bool]] = []

        self.setObjectName("ReleaseNotesDialog")
        self.setProperty("uiSurface", "utility")
        self.resize(620, 400)
        self.setMinimumSize(520, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setProperty("uiRole", "dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)
        header_layout.setSpacing(12)
        self.title_label = QLabel()
        self.title_label.setProperty("uiRole", "dialogTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        self.version_selector = QComboBox()
        self.version_selector.setObjectName("ReleaseVersionSelector")
        self.version_selector.setMinimumWidth(130)
        self.version_selector.setMaximumWidth(220)
        self.version_selector.currentIndexChanged.connect(
            self._render_selected_release
        )
        header_layout.addWidget(self.version_selector)
        root.addWidget(header)

        body = QFrame()
        body.setObjectName("ReleaseNotesBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 14, 20, 14)
        body_layout.setSpacing(10)

        self.update_card = QFrame()
        self.update_card.setObjectName("UpdateStatusCard")
        update_layout = QHBoxLayout(self.update_card)
        update_layout.setContentsMargins(0, 0, 0, 10)
        update_layout.setSpacing(8)
        self.update_status_label = QLabel()
        self.update_status_label.setObjectName("UpdateStatusTitle")
        self.update_status_label.setWordWrap(True)
        update_layout.addWidget(self.update_status_label, stretch=1)
        self.check_update_button = QPushButton()
        self.check_update_button.setProperty("kind", "secondary")
        self.check_update_button.clicked.connect(self.check_for_updates)
        update_layout.addWidget(self.check_update_button)
        body_layout.addWidget(self.update_card)

        details = QFrame()
        details.setObjectName("ReleaseDetails")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 4, 0, 0)
        details_layout.setSpacing(8)
        self.release_title = QLabel()
        self.release_title.setObjectName("ReleaseVersionTitle")
        self.release_title.setWordWrap(True)
        self.release_date = QLabel()
        self.release_date.setObjectName("ReleaseDate")
        self.release_summary = QLabel()
        self.release_summary.setObjectName("ReleaseSummary")
        self.release_summary.setWordWrap(True)
        self.highlights_browser = QTextBrowser()
        self.highlights_browser.setObjectName("ReleaseHighlights")
        self.highlights_browser.setOpenExternalLinks(False)
        self.highlights_browser.setFocusPolicy(Qt.NoFocus)
        for widget in (
            self.release_title,
            self.release_date,
            self.release_summary,
            self.highlights_browser,
        ):
            details_layout.addWidget(widget)
        details_layout.setStretchFactor(self.highlights_browser, 1)
        body_layout.addWidget(details, stretch=1)
        root.addWidget(body, stretch=1)

        footer = QFrame()
        footer.setProperty("uiRole", "dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 8, 20, 8)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.setProperty("uiRole", "dialogButtonRow")
        self.open_releases_button = buttons.addButton(
            "",
            QDialogButtonBox.ActionRole,
        )
        self.open_releases_button.setProperty("kind", "ghost")
        self.open_releases_button.hide()
        self.open_releases_button.clicked.connect(self._open_release_page)
        self.close_button = buttons.button(QDialogButtonBox.Close)
        self.close_button.setProperty("kind", "secondary")
        buttons.rejected.connect(self.reject)
        footer_layout.addWidget(buttons)
        root.addWidget(footer)

        self.update_controller.started.connect(self._on_update_started)
        self.update_controller.succeeded.connect(self._on_update_succeeded)
        self.update_controller.failed.connect(self._on_update_failed)
        self.retranslate_dynamic_content()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._hide_prepared = False
        if self._auto_check and not self._auto_check_started:
            self._auto_check_started = True
            self._auto_check_timer.start(0)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._prepare_to_hide()
        super().closeEvent(event)

    def reject(self) -> None:
        self._prepare_to_hide()
        super().reject()

    def done(self, result: int) -> None:
        self._prepare_to_hide()
        super().done(result)

    def _start_auto_check_if_visible(self) -> None:
        if not self.isVisible():
            self._auto_check_started = False
            return
        self.check_for_updates()

    def _prepare_to_hide(self) -> None:
        if self._hide_prepared:
            return
        self._hide_prepared = True
        had_pending_check = self._auto_check_timer.isActive() or self._checking
        self._auto_check_timer.stop()
        self.update_controller.shutdown()
        if had_pending_check:
            self._auto_check_started = False
        if self._checking:
            self._checking = False
            self._last_update_error = None
            self.check_update_button.setEnabled(True)
            self._render_update_status()

    def check_for_updates(self) -> None:
        """Start one bounded asynchronous request without blocking the dialog."""

        if self.update_controller.start(APP_VERSION):
            self._auto_check_started = True

    def _on_update_started(self) -> None:
        self._checking = True
        self._last_update_result = None
        self._last_update_error = None
        self._reset_release_action()
        self.check_update_button.setEnabled(False)
        self._render_update_status()

    def _on_update_succeeded(self, result: UpdateResult) -> None:
        self._checking = False
        self._last_update_result = result
        self._last_update_error = None
        self.check_update_button.setEnabled(True)
        self._release_url = result.release.release_url
        self._render_update_status()

    def _on_update_failed(self, error: UpdateCheckError) -> None:
        self._checking = False
        self._last_update_result = None
        self._last_update_error = error
        self._reset_release_action()
        self.check_update_button.setEnabled(True)
        self._render_update_status()

    def _reset_release_action(self) -> None:
        self._release_url = GITHUB_RELEASES_URL
        self.open_releases_button.hide()

    def _set_update_card(self, state: str, text: str) -> None:
        self.update_card.setProperty("updateState", state)
        self.update_status_label.setProperty("updateState", state)
        self.update_status_label.setText(text)
        for widget in (self.update_card, self.update_status_label):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)

    def _render_update_status(self) -> None:
        self.open_releases_button.hide()
        if self._checking:
            self._set_update_card(
                "checking",
                tr("正在检查…"),
            )
            return
        if self._last_update_error is not None:
            self._set_update_card(
                "error",
                self._update_error_text(self._last_update_error.code),
            )
            return
        result = self._last_update_result
        if result is None:
            self._set_update_card(
                "idle",
                tr("尚未检查更新"),
            )
        elif result.status is UpdateStatus.UPDATE:
            self._set_update_card(
                "available",
                trf(
                    "新版本 {version}",
                    version=str(result.release.version),
                ),
            )
            self.open_releases_button.show()
        elif result.status is UpdateStatus.CURRENT:
            self._set_update_card("ok", tr("已是最新版"))
        else:
            self._set_update_card("ok", tr("开发版本"))

    @staticmethod
    def _update_error_text(code: UpdateErrorCode) -> str:
        if code is UpdateErrorCode.RATE_LIMITED:
            return tr("GitHub 请求受限")
        if code is UpdateErrorCode.NOT_FOUND:
            return tr("暂无稳定版")
        if code is UpdateErrorCode.API_VERSION_UNSUPPORTED:
            return tr("检查服务不可用")
        if code is UpdateErrorCode.TIMEOUT:
            return tr("检查超时")
        if code is UpdateErrorCode.TLS_ERROR:
            return tr("安全连接失败")
        if code is UpdateErrorCode.NETWORK_ERROR:
            return tr("无法连接 GitHub")
        if code is UpdateErrorCode.CANCELLED:
            return tr("已取消")
        if code is UpdateErrorCode.SELF_TEST_DISABLED:
            return tr("自检期间不联网")
        if code in {
            UpdateErrorCode.PAYLOAD_TOO_LARGE,
            UpdateErrorCode.INVALID_PAYLOAD,
            UpdateErrorCode.NO_STABLE_RELEASE,
        }:
            return tr("版本信息无效")
        return tr("检查失败")

    def _release_key_for_index(self, index: int) -> str:
        if 0 <= index < len(self._display_entries):
            return self._display_entries[index][0]
        return ""

    def _populate_versions(self, selected_key: str = "") -> None:
        self.version_selector.blockSignals(True)
        self.version_selector.clear()
        self._display_entries.clear()
        if (
            self.document is not None
            and self.include_development
            and self.document.development is not None
        ):
            self._display_entries.append(
                ("development", self.document.development, True)
            )
            self.version_selector.addItem(tr("开发中"))
        if self.document is not None:
            for entry in self.document.releases:
                key = str(entry.version)
                self._display_entries.append((key, entry, False))
                self.version_selector.addItem(f"v{entry.version}")
        self.version_selector.blockSignals(False)
        if not self._display_entries:
            self._render_unavailable()
            return
        keys = [item[0] for item in self._display_entries]
        latest_release_key = next(
            (
                key
                for key, _entry, is_development in self._display_entries
                if not is_development
            ),
            keys[0],
        )
        target = (
            selected_key
            if selected_key in keys
            else APP_VERSION
            if APP_VERSION in keys
            else latest_release_key
        )
        target_index = keys.index(target)
        self.version_selector.setCurrentIndex(target_index)
        self._render_selected_release(target_index)

    def _render_selected_release(self, index: int) -> None:
        if not 0 <= index < len(self._display_entries):
            self._render_unavailable()
            return
        _key, entry, is_development = self._display_entries[index]
        localized = entry.localized(_active_locale())
        if is_development:
            self.release_title.setText(localized.title)
            self.release_date.setText(tr("开发中"))
        else:
            self.release_title.setText(localized.title)
            release_status = (
                tr("预发行版") if entry.is_prerelease else tr("稳定版")
            )
            self.release_date.setText(
                f"{entry.release_date.isoformat()} · {release_status}"
            )
        self.release_summary.setText(localized.summary)
        self.highlights_browser.setPlainText(
            "\n\n".join(f"• {highlight}" for highlight in localized.highlights)
        )

    def _render_unavailable(self) -> None:
        self.release_title.setText(f"v{APP_VERSION}")
        self.release_date.clear()
        self.release_summary.setText(tr("更新日志暂不可用"))
        self.highlights_browser.setPlainText(tr("此版本暂无详细说明。"))

    def _open_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release_url))

    def retranslate_dynamic_content(self) -> None:
        selected_key = self._release_key_for_index(
            self.version_selector.currentIndex()
        )
        self.setWindowTitle(tr("更新日志"))
        self.title_label.setText(tr("更新日志"))
        self.check_update_button.setText(tr("检查更新"))
        self.open_releases_button.setText(tr("查看版本"))
        self.close_button.setText(tr("关闭"))
        self._populate_versions(selected_key)
        self._render_update_status()


__all__ = ["ReleaseNotesDialog"]
