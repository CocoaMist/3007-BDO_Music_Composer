"""Privacy-preserving application crash log boundary."""

from __future__ import annotations

import re
import time

from project_paths import USER_DATA_DIR


CRASH_LOG_PATH = USER_DATA_DIR / "out" / "bdo" / "crash.log"


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
