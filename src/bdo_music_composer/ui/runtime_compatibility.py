"""Path-free runtime compatibility evidence for desktop qualification."""

from __future__ import annotations

import json
import platform
from typing import Any

from PySide6.QtCore import QLibraryInfo, qVersion
from PySide6.QtGui import QGuiApplication

from bdo_music_composer.app.application_metadata import APP_VERSION


COMPATIBILITY_REPORT_SCHEMA = 1


def collect_runtime_compatibility(*, include_qt: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": COMPATIBILITY_REPORT_SCHEMA,
        "application_version": APP_VERSION,
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
    }
    if not include_qt:
        return report
    report["qt_version"] = qVersion()
    report["qt_build"] = QLibraryInfo.build()
    application = QGuiApplication.instance()
    report["screens"] = [] if application is None else [
        {
            "width": screen.size().width(),
            "height": screen.size().height(),
            "logical_dpi": round(screen.logicalDotsPerInch(), 2),
            "device_pixel_ratio": round(screen.devicePixelRatio(), 2),
        }
        for screen in application.screens()
    ]
    return report


def compatibility_report_json(*, include_qt: bool = True) -> str:
    return json.dumps(
        collect_runtime_compatibility(include_qt=include_qt),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


__all__ = [
    "COMPATIBILITY_REPORT_SCHEMA",
    "collect_runtime_compatibility",
    "compatibility_report_json",
]
