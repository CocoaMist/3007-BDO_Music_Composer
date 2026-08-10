"""Privacy-preserving, user-initiated desktop support bundles."""

from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from pathlib import Path

from bdo_common.atomic_io import atomic_write_bytes
from bdo_music_composer.app.application_metadata import APP_NAME, APP_VERSION
from bdo_music_composer.app.crash_logging import CRASH_LOG_PATH, redact_log_paths


SUPPORT_BUNDLE_SCHEMA = 1
MAX_CRASH_LOG_BYTES = 512 * 1024


def _bounded_log_tail(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - MAX_CRASH_LOG_BYTES))
            payload = stream.read(MAX_CRASH_LOG_BYTES)
    except OSError:
        return ""
    return redact_log_paths(payload.decode("utf-8", errors="replace"))


def support_metadata() -> dict[str, object]:
    """Return path-free, account-free runtime facts useful for diagnosis."""

    return {
        "schema": SUPPORT_BUNDLE_SCHEMA,
        "application": APP_NAME,
        "application_version": APP_VERSION,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "system_release": platform.release(),
        "system_version": platform.version(),
        "machine": platform.machine(),
    }


def build_support_bundle_bytes() -> bytes:
    """Build a bounded ZIP without projects, Owner IDs, or local paths."""

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        metadata = json.dumps(
            support_metadata(), ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        archive.writestr("support.json", metadata)
        crash_tail = _bounded_log_tail(CRASH_LOG_PATH)
        if crash_tail:
            archive.writestr("crash.log", crash_tail.encode("utf-8"))
        archive.writestr(
            "PRIVACY.txt",
            (
                "This bundle is generated locally and is not uploaded automatically.\n"
                "It excludes projects, scores, Owner IDs, audio, settings, and local paths.\n"
            ).encode("utf-8"),
        )
    return output.getvalue()


def export_support_bundle(destination: str | Path) -> Path:
    """Atomically publish a support bundle selected by the user."""

    target = Path(destination)
    if target.suffix.lower() != ".zip":
        raise ValueError("support bundle destination must use the .zip suffix")
    atomic_write_bytes(target, build_support_bundle_bytes())
    return target


__all__ = [
    "MAX_CRASH_LOG_BYTES",
    "SUPPORT_BUNDLE_SCHEMA",
    "build_support_bundle_bytes",
    "export_support_bundle",
    "support_metadata",
]
