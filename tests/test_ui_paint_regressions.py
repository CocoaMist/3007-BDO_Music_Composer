from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UiPaintRegressionTests(unittest.TestCase):
    def test_marquee_stays_translucent_and_volume_uses_locale_width(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile

            from PySide6.QtCore import QRectF
            from PySide6.QtGui import QColor, QImage, QPainter
            from PySide6.QtWidgets import QApplication

            from i18n import install_localizer, tr
            import pyside_bdo_gui as gui
            from pyside_bdo_gui import MidiToBdoWindow, PianoRollCanvas

            app = QApplication([])

            # Reproduce the former brush leak: note painting left an opaque
            # brush active before the marquee border was drawn.
            image = QImage(80, 80, QImage.Format_ARGB32)
            base = QColor(28, 28, 30)
            image.fill(base)
            painter = QPainter(image)
            painter.setBrush(QColor(130, 70, 70))
            PianoRollCanvas._paint_marquee_overlay(
                painter,
                QRectF(10, 10, 60, 60),
            )
            painter.end()
            center = image.pixelColor(40, 40)
            assert base.red() < center.red() < 55, center.getRgb()
            assert center.green() < 50, center.getRgb()

            translations = install_localizer(app, "en_US")
            config_dir = tempfile.TemporaryDirectory()
            gui.CONFIG_PATH = Path(config_dir.name) / "config.json"
            window = MidiToBdoWindow()
            translations.set_language("en_US")
            label = tr("音量")
            assert label == "Volume"
            metrics = window.timeline.fontMetrics()
            width = window.timeline._volume_label_width(metrics, label)
            assert width >= metrics.horizontalAdvance(label) + 8
            assert width > 25

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
