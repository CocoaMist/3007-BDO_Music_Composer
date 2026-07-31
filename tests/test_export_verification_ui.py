from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ExportVerificationUiTests(unittest.TestCase):
    def test_result_copy_is_scoped_and_game_copy_failure_is_visible(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile

            from PySide6.QtWidgets import QApplication

            from export_verification import (
                ExportVerificationIssue, ExportVerificationReport,
            )
            from i18n import install_localizer
            import pyside_bdo_gui as gui
            from pyside_bdo_gui import MidiToBdoWindow

            app = QApplication([])
            install_localizer(app, "zh_CN")
            config_dir = tempfile.TemporaryDirectory()
            gui.CONFIG_PATH = Path(config_dir.name) / "config.json"
            gui.append_crash_log = lambda *_args, **_kwargs: None
            window = MidiToBdoWindow()
            window._autosave_project = lambda *_args, **_kwargs: None
            common = {
                "instruments": 1,
                "tracks": 2,
                "total_notes": 1,
            }
            passed = ExportVerificationReport(
                issues=(),
                omitted_issue_count=0,
                expected_note_count=1,
                actual_note_count=1,
                expected_instrument_count=1,
                actual_instrument_count=1,
                checked_stages=("prepared", "primary", "game_copy"),
            )
            window._on_convert_finished(
                str(Path(config_dir.name) / "score.bdo"),
                128,
                {**common, "verification_report": passed},
                str(Path(config_dir.name) / "game" / "score.bdo"),
                "",
            )
            assert "编辑器→BDO v9 数据一致" in window.inspector_text.text()
            assert "游戏目录副本一致" in window.inspector_text.text()
            assert "不代表程序绝对无 Bug" in window.inspector_text.toolTip()

            failed = ExportVerificationReport(
                issues=(ExportVerificationIssue(
                    "game_copy",
                    "publication.game_copy_bytes_mismatch",
                    "publication.game_copy",
                    "expected fingerprint",
                    "actual fingerprint",
                ),),
                omitted_issue_count=0,
                expected_note_count=1,
                actual_note_count=1,
                expected_instrument_count=1,
                actual_instrument_count=1,
                checked_stages=("prepared", "primary", "game_copy"),
            )
            window._on_convert_finished(
                str(Path(config_dir.name) / "score.bdo"),
                128,
                {**common, "verification_report": failed},
                str(Path(config_dir.name) / "game" / "score.bdo"),
                "",
            )
            assert window.status_label.text() == "转换完成（数据一致性检查失败）"
            assert "一致性检查发现 1 项差异" in window.inspector_text.text()
            assert "游戏目录副本未通过一致性检查" in window.inspector_text.text()

            window.close()
            app.processEvents()
            config_dir.cleanup()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
