from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SelfUpdateUiTests(unittest.TestCase):
    def test_non_modal_release_notes_follow_download_and_locale(self) -> None:
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    r'''
                    import json
                    from pathlib import Path
                    from PySide6.QtWidgets import QApplication, QMainWindow
                    from bdo_music_composer.ui.i18n import install_localizer
                    from bdo_music_composer.ui.self_update_host import SelfUpdateHostMixin
                    from bdo_music_composer.ui.self_update_qt import PreparedUpdate
                    from bdo_music_composer.update.manifest import _parse_manifest_payload

                    class Host(SelfUpdateHostMixin, QMainWindow):
                        def __init__(self):
                            super().__init__()
                            self.config = {"updates": {"auto_download": True}}
                            self._manual_update_check = False
                            self.toasts = []

                        def show_toast(self, text, kind="info", duration_ms=2600):
                            self.toasts.append((text, kind, duration_ms))

                    payload = {
                        "schema_version": 1,
                        "app_id": "CocoaMist.BDOMusicComposer",
                        "channel": "stable",
                        "version": "1.2.0.1",
                        "published_at": "2026-08-09T12:00:00Z",
                        "update_protocol": 1,
                        "mandatory": False,
                        "release_notes": {
                            "zh_CN": "中文更新内容",
                            "en_US": "English release notes",
                        },
                        "artifacts": [{
                            "platform": "windows",
                            "architecture": "x86_64",
                            "type": "pyinstaller-onefile",
                            "filename": "BDO-Music-Composer.exe",
                            "size": 100,
                            "sha256": "a" * 64,
                            "urls": {
                                "github": "https://github.com/CocoaMist/repo/releases/download/v1.2.0.1/BDO-Music-Composer.exe",
                                "gitee": "https://gitee.com/raionnyan/repo/releases/download/v1.2.0.1/BDO-Music-Composer.exe",
                            },
                        }],
                    }
                    app = QApplication([])
                    active = install_localizer(app, "zh_CN")
                    manifest = _parse_manifest_payload(
                        json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    )
                    host = Host()
                    host._on_update_available(manifest, "gitee")
                    app.processEvents()
                    dialog = host._self_update_dialog
                    assert not dialog.isModal()
                    assert dialog.isVisible()
                    assert "1.2.0.1" in dialog.windowTitle()
                    assert dialog.notes_view.toPlainText() == "中文更新内容"
                    assert "Gitee" in dialog.source_label.text()

                    host._on_update_progress(50, 100)
                    assert dialog.progress_bar.value() == 50
                    assert "50%" in dialog.progress_bar.format()

                    prepared = PreparedUpdate(
                        manifest,
                        Path("BDO-Music-Composer.exe"),
                        "gitee",
                    )
                    host._on_update_ready(prepared)
                    assert dialog.progress_bar.value() == 1
                    assert "下次启动" in dialog.status_label.text()

                    active.set_language("en_US")
                    app.processEvents()
                    assert dialog.notes_view.toPlainText() == "English release notes", dialog.notes_view.toPlainText()
                    assert dialog.notes_label.text() == "What's new", dialog.notes_label.text()
                    assert "next launch" in dialog.status_label.text(), dialog.status_label.text()
                    dialog.close()
                    host.close()
                    app.processEvents()
                    '''
                ),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=40,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
