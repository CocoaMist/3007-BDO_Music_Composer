from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(script: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["BDO_STARTUP_SELF_TEST"] = "1"
    with tempfile.TemporaryDirectory() as user_data_dir:
        environment["BDO_USER_DATA_DIR"] = user_data_dir
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=40,
        )


class ReleaseNotesDialogTests(unittest.TestCase):
    def assert_script_ok(self, script: str) -> None:
        completed = _run_offscreen(script)
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_local_history_locale_and_missing_resource_fallback(self) -> None:
        self.assert_script_ok(
            """
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.app.release_notes import (
                ReleaseNotesError,
                parse_release_notes,
            )
            from bdo_music_composer.ui.dialogs.release_notes_dialog import (
                ReleaseNotesDialog,
            )

            app = QApplication([])
            document = parse_release_notes({
                "schema_version": 1,
                "development": {
                    "locales": {
                        "zh_CN": {
                            "title": "开发中",
                            "summary": "内部开发记录。",
                            "highlights": ["匿名开发项目。"],
                        },
                        "en_US": {
                            "title": "In development",
                            "summary": (
                                "Synthetic editor-to-game-format record."
                            ),
                            "highlights": ["Anonymous development item."],
                        },
                    },
                },
                "releases": [{
                    "version": "1.1.0",
                    "date": "2026-07-29",
                    "status": "stable",
                    "locales": {
                        "zh_CN": {
                            "title": "内部稳定记录",
                            "summary": "匿名稳定版记录。",
                            "highlights": ["匿名稳定项目。"],
                        },
                        "en_US": {
                            "title": "Internal stable record",
                            "summary": "Synthetic stable record.",
                            "highlights": ["Anonymous stable item."],
                        },
                    },
                }],
            })
            dialog = ReleaseNotesDialog(
                document,
                include_development=True,
                auto_check=False,
            )
            assert dialog.width() <= 640
            assert dialog.height() <= 420
            assert dialog.version_selector.count() == 2
            assert dialog.release_title.text() == "内部稳定记录"
            assert "尚未检查" in dialog.update_status_label.text()
            assert not hasattr(dialog, "subtitle_label")
            assert not hasattr(dialog, "version_list")
            assert not hasattr(dialog, "remote_notes")
            dialog.version_selector.setCurrentIndex(0)
            assert dialog.release_date.text() == "开发中"
            with patch(
                "bdo_music_composer.ui.dialogs.release_notes_dialog."
                "_active_locale",
                return_value="en_US",
            ):
                dialog.retranslate_dynamic_content()
            assert dialog.version_selector.currentIndex() == 0
            assert dialog.release_title.text() == "In development"
            assert "editor-to-game-format" in dialog.release_summary.text()
            dialog.close()

            with patch(
                "bdo_music_composer.ui.dialogs.release_notes_dialog."
                "load_release_notes",
                side_effect=ReleaseNotesError(
                    "resource_unavailable",
                    "missing",
                ),
            ):
                unavailable = ReleaseNotesDialog.from_resource(
                    auto_check=False
                )
            assert unavailable.document is None
            assert unavailable.version_selector.count() == 0
            assert "暂不可用" in unavailable.release_summary.text()
            assert unavailable.check_update_button.isEnabled()
            unavailable.close()
            app.processEvents()
            """
        )

    def test_update_states_safe_url_minimal_view_and_close_lifecycle(self) -> None:
        self.assert_script_ok(
            """
            from unittest.mock import patch
            from PySide6.QtCore import QObject, Qt, Signal
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.app.application_metadata import (
                GITHUB_RELEASES_URL,
            )
            from bdo_music_composer.app.release_notes import parse_release_notes
            from bdo_music_composer.app.update_check import (
                ReleaseInfo,
                SemanticVersion,
                UpdateCheckError,
                UpdateErrorCode,
                UpdateResult,
                UpdateStatus,
                safe_release_url,
            )
            from bdo_music_composer.ui.dialogs.release_notes_dialog import (
                ReleaseNotesDialog,
            )

            class FakeController(QObject):
                started = Signal()
                succeeded = Signal(object)
                failed = Signal(object)
                busy_changed = Signal(bool)
                def __init__(self):
                    super().__init__()
                    self.starts = 0
                    self.shutdowns = 0
                    self.is_busy = False
                def start(self, _version):
                    if self.is_busy:
                        return False
                    self.starts += 1
                    self.is_busy = True
                    self.started.emit()
                    self.busy_changed.emit(True)
                    return True
                def shutdown(self):
                    self.shutdowns += 1
                    self.is_busy = False

            def result(status, version):
                release_version = SemanticVersion.parse(version)
                return UpdateResult(
                    status=status,
                    current_version=SemanticVersion.parse("1.0.0"),
                    release=ReleaseInfo(
                        version=release_version,
                        tag_name=f"v{version}",
                        name=f"Release {version}",
                        body="<b>plain remote notes</b>",
                        published_at="2026-07-31T08:00:00Z",
                        release_url=safe_release_url(f"v{version}"),
                    ),
                )

            app = QApplication([])
            document = parse_release_notes({
                "schema_version": 1,
                "releases": [{
                    "version": "1.0.0",
                    "date": "2026-07-29",
                    "status": "stable",
                    "locales": {
                        "zh_CN": {
                            "title": "内部稳定记录",
                            "summary": "匿名稳定版记录。",
                            "highlights": ["匿名稳定项目。"],
                        },
                    },
                }],
            })
            controller = FakeController()
            dialog = ReleaseNotesDialog(
                document,
                update_controller=controller,
                include_development=False,
                auto_check=False,
            )
            dialog.show()
            app.processEvents()
            dialog.check_for_updates()
            assert controller.starts == 1
            assert not dialog.check_update_button.isEnabled()
            controller.is_busy = False
            controller.succeeded.emit(result(UpdateStatus.UPDATE, "1.1.0"))
            assert dialog.check_update_button.isEnabled()
            assert dialog.update_card.property("updateState") == "available"
            assert "1.1.0" in dialog.update_status_label.text()
            assert dialog.open_releases_button.isVisible()
            assert not hasattr(dialog, "remote_notes")
            assert "<b>" not in dialog.highlights_browser.toPlainText()
            with patch(
                "bdo_music_composer.ui.dialogs.release_notes_dialog."
                "QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                dialog._open_release_page()
            assert open_url.call_args.args[0].toString() == (
                safe_release_url("v1.1.0")
            )

            controller.is_busy = False
            dialog.check_for_updates()
            assert controller.starts == 2
            assert dialog.open_releases_button.isHidden()
            assert dialog._release_url == GITHUB_RELEASES_URL
            controller.is_busy = False
            controller.failed.emit(
                UpdateCheckError(UpdateErrorCode.RATE_LIMITED)
            )
            assert dialog.update_card.property("updateState") == "error"
            assert "请求受限" in dialog.update_status_label.text()
            assert "已是最新版" not in dialog.update_status_label.text()
            assert dialog.open_releases_button.isHidden()
            with patch(
                "bdo_music_composer.ui.dialogs.release_notes_dialog."
                "QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                dialog._open_release_page()
            assert open_url.call_args.args[0].toString() == (
                GITHUB_RELEASES_URL
            )
            assert dialog.release_title.text() == "内部稳定记录"
            dialog._on_update_succeeded(
                result(UpdateStatus.CURRENT, "1.0.0")
            )
            assert "已是最新版" in dialog.update_status_label.text()
            assert dialog.open_releases_button.isHidden()
            dialog._on_update_succeeded(
                result(UpdateStatus.LOCAL_AHEAD, "0.9.0")
            )
            assert "开发版本" in dialog.update_status_label.text()
            assert dialog.open_releases_button.isHidden()
            controller.failed.emit(
                UpdateCheckError(UpdateErrorCode.NETWORK_ERROR)
            )
            assert dialog.open_releases_button.isHidden()
            assert dialog._release_url == GITHUB_RELEASES_URL

            controller.is_busy = False
            dialog.check_for_updates()
            assert not dialog.check_update_button.isEnabled()
            dialog.close()
            assert controller.shutdowns == 1
            assert dialog.check_update_button.isEnabled()
            assert "尚未检查" in dialog.update_status_label.text()

            queued_controller = FakeController()
            queued = ReleaseNotesDialog(
                document,
                update_controller=queued_controller,
                include_development=False,
                auto_check=True,
            )
            queued.show()
            queued.reject()
            app.processEvents()
            assert queued_controller.starts == 0
            assert queued.check_update_button.isEnabled()

            queued.show()
            app.processEvents()
            assert queued_controller.starts == 1
            queued.close_button.click()
            app.processEvents()
            assert queued_controller.shutdowns == 2
            assert queued.check_update_button.isEnabled()

            queued.show()
            app.processEvents()
            assert queued_controller.starts == 2
            QTest.keyClick(queued, Qt.Key_Escape)
            app.processEvents()
            assert queued_controller.shutdowns == 3
            assert queued.check_update_button.isEnabled()
            app.processEvents()
            """
        )

    def test_prerelease_status_retranslates_in_a_subprocess(self) -> None:
        self.assert_script_ok(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.app.release_notes import parse_release_notes
            from bdo_music_composer.ui.dialogs.release_notes_dialog import (
                ReleaseNotesDialog,
            )
            from bdo_music_composer.ui.i18n import install_localizer

            app = QApplication([])
            active_localizer = install_localizer(app, "zh_CN")
            document = parse_release_notes({
                "schema_version": 1,
                "releases": [{
                    "version": "1.1.0-rc.1",
                    "date": "2026-07-31",
                    "status": "prerelease",
                    "locales": {
                        "zh_CN": {
                            "title": "候选版本",
                            "summary": "用于验证本地预发行日志展示。",
                            "highlights": ["状态必须与目录数据一致。"],
                        },
                    },
                }],
            })
            dialog = ReleaseNotesDialog(
                document,
                include_development=False,
                auto_check=False,
            )
            dialog.show()
            app.processEvents()
            expected = {
                "zh_CN": "预发行版",
                "zh_TW": "預發行版",
                "en_US": "Pre-release",
                "ja_JP": "プレリリース",
                "ko_KR": "사전 릴리스",
            }
            for language, label in expected.items():
                active_localizer.set_language(language)
                app.processEvents()
                assert label in dialog.release_date.text(), (
                    language,
                    dialog.release_date.text(),
                )
            assert "稳定版" not in dialog.release_date.text()
            dialog.close()
            app.processEvents()
            """
        )

    def test_home_footer_keeps_release_notes_internal(self) -> None:
        self.assert_script_ok(
            """
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui

            class FakeDialog:
                def __init__(self):
                    self.exec_count = 0
                def exec(self):
                    self.exec_count += 1

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            fake = FakeDialog()
            with patch.object(
                gui.ReleaseNotesDialog,
                "from_resource",
                return_value=fake,
            ) as factory:
                window.home_footer.release_notes_requested.emit()
                window._show_release_notes()
            assert gui.RELEASE_NOTES_UI_ENABLED is False
            assert factory.call_count == 0
            assert fake.exec_count == 0
            assert not hasattr(window, "_release_notes_dialog")
            assert window.home_footer.release_notes_button.objectName() == (
                "HomeReleaseNotesButton"
            )
            assert window.home_footer.release_notes_button.isHidden()
            assert window.home_footer.release_notes_button.text() == ""
            assert window.home_footer.local_badge.objectName() == (
                "HomeLocalBadge"
            )
            window.close()
            app.processEvents()
            """
        )


if __name__ == "__main__":
    unittest.main()
