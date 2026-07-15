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
            from i18n import install_localizer
            from pyside_bdo_gui import MidiOptimizeDialog, Note, TrackState

            app = QApplication([])
            translations = install_localizer(app, "zh_CN")
            track = TrackState(1, [Note(60, 80, 0, 400, 0)], 0, False, "melody", 0x0B)
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
            assert dialog.algorithm_combo.count() >= 1
            assert dialog.intensity_combo.count() == 3
            assert not dialog.apply_button.isEnabled()
            assert not hasattr(dialog, "style_combo")
            assert not hasattr(dialog, "lyric_combo")
            assert not hasattr(dialog, "marnian_check")
            dialog.show()
            app.processEvents()
            translations.set_language("en_US")
            assert dialog.analyse_button.text() == "Analyze Optimization"
            translations.set_language("ja_JP")
            assert dialog.analyse_button.text() == "最適化を解析"
            translations.set_language("ko_KR")
            assert dialog.analyse_button.text() == "최적화 분석"
            translations.set_language("zh_CN")
            dialog._analyse()
            worker = dialog.analysis_worker
            assert worker is not None
            while worker.isRunning():
                app.processEvents()
            app.processEvents()
            assert dialog.session is not None
            assert dialog.analysis_worker is None
            assert dialog.apply_button.isEnabled()
            result = dialog.optimized_tracks()
            assert len(result) == 1
            dialog.intensity_combo.setCurrentIndex(0)
            assert dialog.session is None
            assert not dialog.apply_button.isEnabled()
            dialog.close()
            from pyside_bdo_gui import MidiNoteEditorDialog
            editor = MidiNoteEditorDialog(parent, track, 120, 4)
            assert editor.ghost_box.isChecked()
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
