from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OptimizerPluginUiSmokeTests(unittest.TestCase):
    def test_simplified_panel_requires_explicit_analysis_and_has_no_legacy_option_grid(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication, QWidget
            from bdo_music_composer.ui.i18n import install_localizer, trf
            from bdo_music_composer.ui.main_window import (
                MidiOptimizeDialog,
                MidiToBdoWindow,
                Note,
                TrackState,
                _optimizer_diagnostic_value,
                _optimizer_host_message_value,
            )

            app = QApplication([])
            translations = install_localizer(app, "zh_CN")
            # Pitch 89 is outside instrument 0x0B's verified game range.  It
            # must remain a conversion-check warning instead of disabling the
            # optimizer dialog (the original user-visible regression).
            track = TrackState(1, [Note(89, 80, 0, 400, 0)], 0, False, "melody", 0x0B)
            parent = QWidget()
            parent.tracks = [track]
            parent.bpm_override = 0
            parent.bpm = 120
            parent.time_sig = 4
            parent.lyric_events = []
            parent.reverb = 0
            parent.delay = 0
            parent.chorus = (0, 0, 0)
            dialog = MidiOptimizeDialog(parent, source_tracks=[track])
            assert dialog.windowTitle() == "MIDI 优化"
            assert dialog.scope_combo.count() == 2
            assert dialog.scope == "global"
            assert dialog.target_track_id is None
            assert "可调整全局效果" in dialog.scope_summary_label.text()
            import bdo_music_composer.ui.dialogs.optimizer_dialog as optimizer_dialog_module
            original_discovery = optimizer_dialog_module.discover_host_algorithms
            optimizer_dialog_module.discover_host_algorithms = lambda: (_ for _ in ()).throw(
                AssertionError("scope changes must not rescan algorithm packages")
            )
            dialog.scope_combo.setCurrentIndex(1)
            assert dialog.scope == "single_track"
            assert dialog.target_track_id == 1
            assert "不修改全局效果" in dialog.scope_summary_label.text()
            dialog.scope_combo.setCurrentIndex(0)
            optimizer_dialog_module.discover_host_algorithms = original_discovery
            assert dialog.algorithm_combo.count() >= 1
            assert dialog.intensity_combo.count() == 3
            assert not dialog.apply_button.isEnabled()
            assert dialog.summary_label.text() == "选择算法和强度，然后分析优化。"
            assert not hasattr(dialog, "style_combo")
            assert not hasattr(dialog, "lyric_combo")
            assert not hasattr(dialog, "marnian_check")
            dialog._analysis_error = (
                "song exceeds the optimizer note limit",
                True,
                True,
            )
            dialog._render_analysis_failure()
            assert "曲目超过优化器音符上限" in dialog.summary_label.text()
            dialog.show()
            app.processEvents()
            translations.set_language("en_US")
            assert dialog.analyse_button.text() == "Analyze Optimization"
            assert dialog.scope_combo.itemText(0) == "Entire Project"
            assert "exceeds the optimizer note limit" in dialog.summary_label.text()
            diagnostic = trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(
                    "bad.bdoopt: unsafe bundle path: ../payload.py"
                ),
            )
            assert "unsafe path" in diagnostic
            assert "../payload.py" in diagnostic
            translations.set_language("ja_JP")
            assert dialog.analyse_button.text() == "最適化を解析"
            assert dialog.scope_combo.itemText(0) == "プロジェクト全体"
            assert "ノート数上限" in dialog.summary_label.text()
            diagnostic = trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(
                    "bad.bdoopt: unsafe bundle path: ../payload.py"
                ),
            )
            assert "安全でないパス" in diagnostic
            translations.set_language("ko_KR")
            assert dialog.analyse_button.text() == "최적화 분석"
            assert dialog.scope_combo.itemText(0) == "전체 프로젝트"
            assert "음표 수 제한" in dialog.summary_label.text()
            diagnostic = trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(
                    "bad.bdoopt: unsafe bundle path: ../payload.py"
                ),
            )
            assert "안전하지 않은 경로" in diagnostic
            # Third-party exception text is opaque even when it happens to
            # equal a recognized host validation message.
            dialog._analysis_error = (
                "song exceeds the optimizer note limit",
                False,
                False,
            )
            dialog._render_analysis_failure()
            translations.set_language("ja_JP")
            assert "song exceeds the optimizer note limit" in dialog.summary_label.text()
            assert "song exceeds the optimizer note limit" in dialog.report_text.toPlainText()
            # Host preview validation remains structured, including dynamic
            # track/instrument values; only actual plugin exceptions stay raw.
            dialog._analysis_error = (
                "operation writes outside target scope: 9",
                False,
                True,
            )
            dialog._render_analysis_failure()
            assert "対象範囲外のトラック9" in dialog.summary_label.text()
            pitch_error = str(_optimizer_host_message_value(
                "pitch 100 is unsupported for BDO instrument 11"
            ))
            assert "音高100" in pitch_error
            assert "BDO楽器11" in pitch_error
            translations.set_language("ko_KR")
            assert "대상 범위 밖의 트랙 9" in dialog.summary_label.text()
            pitch_error = str(_optimizer_host_message_value(
                "pitch 100 is unsupported for BDO instrument 11"
            ))
            assert "음높이 100" in pitch_error
            assert "BDO 악기 11" in pitch_error
            translations.set_language("zh_CN")
            assert "目标范围外的轨道：9" in dialog.summary_label.text()
            dialog._invalidate_preview()
            dialog._analyse()
            worker = dialog.analysis_worker
            assert worker is not None
            while worker.isRunning():
                app.processEvents()
            app.processEvents()
            assert dialog.session is not None
            assert dialog.analysis_worker is None
            assert dialog.apply_button.isEnabled()
            translations.set_language("en_US")
            assert "edit operations" in dialog.summary_label.text()
            assert "Totals:" in dialog.report_text.toPlainText()
            translations.set_language("ja_JP")
            assert "変更操作" in dialog.summary_label.text()
            translations.set_language("ko_KR")
            assert "수정 작업" in dialog.summary_label.text()
            translations.set_language("zh_CN")
            result = dialog.optimized_tracks()
            assert len(result) == 1
            dialog.intensity_combo.setCurrentIndex(0)
            assert dialog.session is None
            assert not dialog.apply_button.isEnabled()
            assert dialog.summary_label.text() == "设置已更新，点击分析优化刷新预览。"
            dialog.close()
            locked = MidiToBdoWindow.create_midi_optimize_dialog(
                parent,
                1,
                source_tracks=[track],
            )
            assert locked.scope == "single_track"
            assert locked.target_track_id == 1
            assert not locked.scope_combo.isEnabled()
            assert "范围锁定" in locked.scope_help_label.text()
            locked.close()
            from bdo_music_composer.ui.main_window import MidiNoteEditorDialog
            editor = MidiNoteEditorDialog(parent, track, 120, 4)
            assert not editor.ghost_box.isChecked()
            assert editor.loop_box is not None
            assert editor.velocity_lane.minimumHeight() >= 72
            editor.close()
            parent.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
