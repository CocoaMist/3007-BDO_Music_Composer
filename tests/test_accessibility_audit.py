from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AccessibilityAuditTests(unittest.TestCase):
    def test_reports_only_unlabelled_interactive_widget(self) -> None:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", textwrap.dedent("""
                from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget
                from bdo_music_composer.ui.accessibility_audit import audit_widget_tree

                application = QApplication([])
                root = QWidget()
                layout = QVBoxLayout(root)
                layout.addWidget(QPushButton("Save"))
                missing = QLineEdit()
                missing.setObjectName("missing")
                layout.addWidget(missing)
                root.show()
                application.processEvents()
                findings = audit_widget_tree(root)
                assert [(item.code, item.object_name) for item in findings] == [
                    ("missing-accessible-name", "missing")
                ]
                root.close()
            """)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
