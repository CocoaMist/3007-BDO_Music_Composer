import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class ExportLifecycleUiTests(unittest.TestCase):
    def test_close_waits_for_export_worker(self) -> None:
        script = textwrap.dedent(
            """
            import os

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow


            class RunningExport:
                def isRunning(self):
                    return True


            app = QApplication.instance() or QApplication([])
            window = MidiToBdoWindow()
            window._flush_autosave = lambda: None
            window.worker = RunningExport()
            event = QCloseEvent()

            window.closeEvent(event)

            assert not event.isAccepted()
            assert window.workspace_close_pending
            window.worker = None
            window.workspace_close_pending = False
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_close_queues_final_autosave_only_once(self) -> None:
        script = textwrap.dedent(
            """
            import os

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow


            class SlowAutosave:
                def isRunning(self):
                    return True

                def wait(self, _timeout_ms):
                    return False


            app = QApplication.instance() or QApplication([])
            window = MidiToBdoWindow()
            flushes = []

            def queue_slow_save():
                flushes.append("save")
                window.autosave_worker = SlowAutosave()

            window._flush_autosave = queue_slow_save
            first = QCloseEvent()
            window.closeEvent(first)
            assert not first.isAccepted()
            assert window.workspace_close_pending
            assert flushes == ["save"]

            # A worker completion schedules another closeEvent.  It must not
            # enqueue a second final snapshot even if the first took >30 s.
            window.autosave_worker = None
            second = QCloseEvent()
            window.closeEvent(second)
            assert second.isAccepted()
            assert flushes == ["save"]
            app.processEvents()
            app.quit()
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
