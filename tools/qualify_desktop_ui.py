#!/usr/bin/env python3
"""Run the real main window accessibility baseline in an isolated profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


WINDOW_CONSTRUCT_LIMIT_MS = 1_500.0
FIRST_FRAME_LIMIT_MS = 500.0
INPUT_TO_PAINT_P95_LIMIT_MS = 16.7


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["BDO_UI_PERF_DIAGNOSTICS"] = "1"
    with tempfile.TemporaryDirectory(prefix="bdo-ui-qualification-") as directory:
        os.environ["BDO_USER_DATA_DIR"] = directory
        from PySide6.QtWidgets import QApplication

        from bdo_music_composer.ui.runtime_compatibility import (
            collect_runtime_compatibility,
        )
        from bdo_music_composer.ui.accessibility_audit import audit_widget_tree
        from bdo_music_composer.ui.main_window import MidiToBdoWindow

        application = QApplication.instance() or QApplication([])
        construct_started = time.perf_counter()
        window = MidiToBdoWindow()
        construct_ms = (time.perf_counter() - construct_started) * 1000.0
        first_frame_started = time.perf_counter()
        window.show()
        application.processEvents()
        first_frame_ms = (time.perf_counter() - first_frame_started) * 1000.0
        probe = window.ui_performance_probe
        if probe is not None:
            probe.begin_interaction_window()
            for _ in range(6):
                probe.note_synthetic_input()
                window.update()
                application.processEvents()
        findings = audit_widget_tree(window)
        report = collect_runtime_compatibility()
        report["qualification_timings"] = {
            "window_construct_ms": construct_ms,
            "first_frame_ms": first_frame_ms,
        }
        report["ui_performance"] = (
            probe.recorder.snapshot().to_dict()
            if probe is not None
            else None
        )
        performance_findings: list[str] = []
        if platform.system() != "Windows" or platform.machine().upper() not in {
            "AMD64",
            "X86_64",
        }:
            performance_findings.append("unsupported-windows-x64-runtime")
        if construct_ms > WINDOW_CONSTRUCT_LIMIT_MS:
            performance_findings.append("window-construction-budget")
        if first_frame_ms > FIRST_FRAME_LIMIT_MS:
            performance_findings.append("first-frame-budget")
        if probe is not None:
            snapshot = probe.recorder.snapshot()
            if snapshot.input_to_paint_p95_ms > INPUT_TO_PAINT_P95_LIMIT_MS:
                performance_findings.append("input-to-paint-budget")
            if snapshot.stall_count:
                performance_findings.append("event-loop-stall")
        report["performance_findings"] = performance_findings
        report["accessibility_findings"] = [
            {
                "code": finding.code,
                "object_name": finding.object_name,
                "widget_type": finding.widget_type,
            }
            for finding in findings
        ]
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if probe is not None:
            probe.shutdown()
        window.close()
    return 1 if findings or performance_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
