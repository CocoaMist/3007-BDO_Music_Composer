"""Privacy-preserving crash-log boundary for the application package."""

from __future__ import annotations

import faulthandler
import logging
import re
import sys
import threading
import time
import traceback

from bdo_music_composer.core.project_paths import USER_DATA_DIR


CRASH_LOG_PATH = USER_DATA_DIR / "out" / "bdo" / "crash.log"


def install_crash_logging() -> None:
    """Install process-wide Python and transcription exception reporting."""

    try:
        # Native fault dumps contain interpreter source paths and bypass the
        # redaction boundary, so retain them on stderr instead of persisting
        # them in the user-visible crash log.
        faulthandler.enable(all_threads=True)
    except Exception:
        pass

    def handle_exception(exc_type, exc, tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        append_crash_log("Unhandled exception", detail)
        sys.__excepthook__(exc_type, exc, tb)

    def handle_thread_exception(args) -> None:
        detail = "".join(
            traceback.format_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )
        )
        thread_name = args.thread.name if args.thread else "unknown"
        append_crash_log(
            f"Unhandled thread exception: {thread_name}",
            detail,
        )

    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception

    class _TranscriptionCrashLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                append_crash_log(
                    "Transcription diagnostic",
                    self.format(record),
                )
            except Exception:
                pass

    transcription_logger = logging.getLogger("bdo_transcription")
    if any(
        getattr(handler, "_bdo_transcription_crash_handler", False)
        for handler in transcription_logger.handlers
    ):
        return
    handler = _TranscriptionCrashLogHandler(logging.WARNING)
    handler._bdo_transcription_crash_handler = True
    handler.setFormatter(
        logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    transcription_logger.addHandler(handler)


def redact_log_paths(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)(?P<prefix>path|file|source|audio|midi|project)\s*=\s*(['\"])[^'\"]+\2",
        r"\g<prefix>='<private-path>'",
        text,
    )
    return re.sub(
        r"(?<![A-Za-z0-9_])(?:(?:[A-Za-z]:[\\/])|(?:\\\\))[^\s,;)\]}]+",
        "<private-path>",
        text,
    )


def append_crash_log(title: str, detail: str) -> None:
    try:
        CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CRASH_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(
                f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"{redact_log_paths(title)}\n"
            )
            file.write(redact_log_paths(detail).rstrip())
            file.write("\n")
    except Exception:
        pass
