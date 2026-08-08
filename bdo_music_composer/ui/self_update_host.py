"""Thin main-window presentation host for seamless background updates."""

from __future__ import annotations

import os

from bdo_music_composer.app.application_metadata import APP_VERSION
from bdo_music_composer.app.crash_logging import append_crash_log
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.self_update_qt import PreparedUpdate
from bdo_music_composer.update.preferences import update_preferences
from bdo_music_composer.update.install import (
    POST_UPDATE_STATE_ENVIRONMENT,
    POST_UPDATE_TOKEN_ENVIRONMENT,
    confirm_post_update,
)


class SelfUpdateHostMixin:
    def _show_startup_notice(self) -> None:
        state_path = os.environ.pop(POST_UPDATE_STATE_ENVIRONMENT, "")
        token = os.environ.pop(POST_UPDATE_TOKEN_ENVIRONMENT, "")
        if state_path and token and confirm_post_update(state_path, token):
            self.show_toast(
                trf("已更新至 v{version}", version=APP_VERSION),
                kind="success",
                duration_ms=5000,
            )
        elif not self.owner_id:
            self.show_toast(
                tr("Owner ID 未设置；导出前需要从游戏曲谱读取。"),
                kind="warning",
                duration_ms=5000,
            )
        else:
            self.show_toast(
                tr("双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。")
            )

    def _start_background_update(self) -> None:
        self.self_update_controller.start(manual=False)

    def check_for_updates(self) -> bool:
        self._manual_update_check = True
        started = self.self_update_controller.start(manual=True)
        if started:
            self.show_toast(tr("正在检查更新…"))
        return started

    def _on_update_available(self, manifest, _source: str) -> None:
        preferences = update_preferences(self.config)
        message = trf(
            (
                "发现新版本 v{version}，正在后台下载"
                if preferences["auto_download"]
                else "发现新版本 v{version}"
            ),
            version=str(manifest.version),
        )
        self.show_toast(message, duration_ms=4200)
        if not preferences["auto_download"]:
            self._manual_update_check = False

    def _on_update_ready(self, prepared: PreparedUpdate) -> None:
        self.show_toast(
            trf(
                "v{version} 已准备好，将在下次启动时更新",
                version=str(prepared.manifest.version),
            ),
            kind="success",
            duration_ms=6000,
        )
        self._manual_update_check = False

    def _on_update_current(self) -> None:
        if self._manual_update_check:
            self.show_toast(tr("已是最新版"), kind="success")
        self._manual_update_check = False

    def _on_update_failed(self, message: str) -> None:
        if self._manual_update_check:
            self.show_toast(tr("检查更新失败，请稍后重试"), kind="error")
        else:
            append_crash_log("Background update check failed", str(message))
        self._manual_update_check = False


__all__ = ["SelfUpdateHostMixin"]
