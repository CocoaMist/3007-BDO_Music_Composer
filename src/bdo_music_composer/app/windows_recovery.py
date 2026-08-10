"""Minimal Windows restart registration for frozen desktop recovery."""

from __future__ import annotations

import sys


RESTART_NO_CRASH = 1
RESTART_NO_HANG = 2
RESTART_NO_PATCH = 4
RESTART_NO_REBOOT = 8


def register_frozen_application_restart() -> bool:
    """Ask Windows to offer a clean restart; autosave owns data recovery."""

    if sys.platform != "win32" or not bool(getattr(sys, "frozen", False)):
        return False
    try:
        import ctypes

        flags = RESTART_NO_PATCH | RESTART_NO_REBOOT
        result = ctypes.windll.kernel32.RegisterApplicationRestart(None, flags)
    except (AttributeError, OSError):
        return False
    return int(result) == 0


__all__ = ["register_frozen_application_restart"]
