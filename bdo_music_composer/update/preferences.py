"""Normalized local preferences for the production self-update workflow."""

from __future__ import annotations

from typing import Any, Mapping


UPDATE_PREFERENCES_KEY = "updates"
UPDATE_SOURCES = frozenset({"auto", "github", "gitee"})


def update_preferences(config: Mapping[str, Any]) -> dict[str, Any]:
    raw = config.get(UPDATE_PREFERENCES_KEY)
    source = raw if isinstance(raw, Mapping) else {}
    preferred_source = str(source.get("source", "auto"))
    if preferred_source not in UPDATE_SOURCES:
        preferred_source = "auto"
    highest_version = source.get("highest_version", "")
    if not isinstance(highest_version, str):
        highest_version = ""
    last_source = str(source.get("last_source", ""))
    if last_source not in {"github", "gitee"}:
        last_source = ""
    last_check = source.get("last_check", 0)
    if isinstance(last_check, bool) or not isinstance(last_check, (int, float)):
        last_check = 0
    return {
        "enabled": source.get("enabled", True) is not False,
        "auto_download": source.get("auto_download", True) is not False,
        "source": preferred_source,
        "highest_version": highest_version,
        "last_source": last_source,
        "last_check": max(0, int(last_check)),
    }
__all__ = ["UPDATE_PREFERENCES_KEY", "UPDATE_SOURCES", "update_preferences"]
