from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

from process_metrics import ProcessMetricsSampler, current_working_set_bytes


ROOT = Path(__file__).resolve().parents[1]


class ProcessMetricsTests(unittest.TestCase):
    def test_delta_cpu_is_normalized_and_memory_is_current_sample(self) -> None:
        wall = iter((10.0, 11.0, 13.0))
        process = iter((2.0, 2.8, 3.2))
        sampler = ProcessMetricsSampler(
            wall_clock=lambda: next(wall),
            process_clock=lambda: next(process),
            memory_reader=lambda: 256 * 1024 * 1024,
            logical_cpu_count=4,
        )
        first = sampler.sample()
        second = sampler.sample()
        self.assertAlmostEqual(20.0, first.cpu_percent)
        self.assertAlmostEqual(5.0, second.cpu_percent)
        self.assertEqual(256.0, second.working_set_mib)

    def test_native_working_set_reader_is_safe(self) -> None:
        self.assertGreaterEqual(current_working_set_bytes(), 0)

    def test_workspace_has_compact_process_and_audio_metrics(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication, QFrame
            from pyside_bdo_gui import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            window._show_workspace()
            window._update_process_metrics()
            app.processEvents()
            strip = window.findChild(QFrame, "PerformanceStrip")
            assert strip is not None
            assert strip.height() == 30
            assert window.process_cpu_label.text().startswith("CPU ")
            assert window.process_ram_label.text().startswith("RAM ")
            assert "XRUN" in window.audio_load_label.text()
            assert "乐器 0" in window.ensemble_metric_label.text()
            assert "0/5 人" in window.ensemble_metric_label.text()

            window.tracks = [
                TrackState(
                    1, [Note(60, 90, 0.0, 100.0, 0)], 0, False,
                    "Marnian basic", 0x14,
                    marnian_synth_mode="basic",
                ),
                TrackState(
                    2, [Note(64, 90, 0.0, 100.0, 0)], 0, False,
                    "Marnian stereo", 0x14,
                    marnian_synth_mode="stereo",
                ),
                TrackState(
                    3, [Note(67, 90, 0.0, 100.0, 0)], 0, False,
                    "Piano", 0x11,
                ),
            ]
            window._update_ensemble_metric()
            assert "乐器 2" in window.ensemble_metric_label.text()
            assert "2/5 人" in window.ensemble_metric_label.text()
            assert window.ensemble_metric_label.property("ensembleState") == "ok"

            window.tracks = [
                TrackState(
                    index, [Note(60, 90, 0.0, 100.0, 0)], 0, False,
                    f"Track {index}", instrument_id,
                )
                for index, instrument_id in enumerate(
                    (0x00, 0x01, 0x02, 0x04, 0x05, 0x06), start=1
                )
            ]
            window._update_ensemble_metric()
            assert "乐器 6" in window.ensemble_metric_label.text()
            assert "超过 5 人" in window.ensemble_metric_label.text()
            assert window.ensemble_metric_label.property("ensembleState") == "over"
            window.close()
            app.processEvents()
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
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
