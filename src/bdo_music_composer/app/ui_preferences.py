"""Validated application-local UI preferences.

These values describe how controls are presented and operated, not musical
project state.  They stay in the local application configuration and are
bounded before Qt consumes them.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, MutableMapping


UI_PREFERENCES_KEY = "ui_preferences"
UI_PREFERENCES_VERSION = 1

DEFAULT_UI_PREFERENCES: dict[str, Any] = {
    "version": UI_PREFERENCES_VERSION,
    "workspace": {
        "window_width": 1360,
        "window_height": 820,
        "window_maximized": False,
        "timeline_zoom_percent": 100,
        "timeline_pan_percent": 0,
        "timeline_loop_enabled": False,
        "reference_volume_percent": 50,
    },
    "editor": {
        "window_width": 1440,
        "window_height": 860,
        "horizontal_zoom": 92,
        "note_row_height": 24.0,
        "quantize_divisor": 1,
        "snap_enabled": True,
        "note_preview_enabled": True,
        "draw_mode_enabled": False,
        "inspector_mode": "note",
        "loop_enabled": False,
        "velocity_visible": False,
        "velocity_mode": "brush",
        "velocity_radius_beats": 2.0,
        "velocity_scope": "track",
    },
    "transcription": {
        "confidence_percent": 30,
        "show_rejected": False,
        "show_suppressed": False,
        "rhythm_projection_enabled": True,
        "rhythm_profile": "auto",
    },
}


def _bounded_number(
    value: object,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, number)) if math.isfinite(number) else default


def normalize_ui_preferences(value: object) -> dict[str, Any]:
    """Return a complete, bounded and forward-compatible preference object."""

    source = dict(value) if isinstance(value, Mapping) else {}
    result = deepcopy(DEFAULT_UI_PREFERENCES)
    workspace = source.get("workspace")
    editor = source.get("editor")
    transcription = source.get("transcription")
    workspace = workspace if isinstance(workspace, Mapping) else {}
    editor = editor if isinstance(editor, Mapping) else {}
    transcription = transcription if isinstance(transcription, Mapping) else {}
    numeric_fields = (
        (result["workspace"], workspace, "window_width", 920, 7680),
        (result["workspace"], workspace, "window_height", 680, 4320),
        (result["workspace"], workspace, "timeline_zoom_percent", 100, 800),
        (result["workspace"], workspace, "timeline_pan_percent", 0, 1000),
        (result["workspace"], workspace, "reference_volume_percent", 0, 100),
        (result["editor"], editor, "window_width", 920, 7680),
        (result["editor"], editor, "window_height", 680, 4320),
        (result["editor"], editor, "horizontal_zoom", 8, 1600),
        (result["editor"], editor, "note_row_height", 10, 72),
        (result["editor"], editor, "velocity_radius_beats", 0.5, 8.0),
        (result["transcription"], transcription, "confidence_percent", 0, 100),
    )
    for target, raw, key, minimum, maximum in numeric_fields:
        default = float(target[key])
        bounded = _bounded_number(raw.get(key, default), default, minimum, maximum)
        target[key] = bounded if isinstance(target[key], float) else round(bounded)
    for target, raw, keys in (
        (result["workspace"], workspace, ("window_maximized", "timeline_loop_enabled")),
        (result["editor"], editor, ("snap_enabled", "note_preview_enabled", "draw_mode_enabled", "loop_enabled", "velocity_visible")),
        (result["transcription"], transcription, ("show_rejected", "show_suppressed", "rhythm_projection_enabled")),
    ):
        for key in keys:
            if isinstance(raw.get(key), bool):
                target[key] = raw[key]
    divisor = editor.get("quantize_divisor")
    if isinstance(divisor, int) and not isinstance(divisor, bool) and divisor in {1, 2, 4, 8, 16}:
        result["editor"]["quantize_divisor"] = divisor
    for key, allowed in (
        ("inspector_mode", {"note", "articulation", "grid"}),
        ("velocity_mode", {"point", "brush"}),
        ("velocity_scope", {"track", "selection"}),
    ):
        if str(editor.get(key, "")) in allowed:
            result["editor"][key] = str(editor[key])
    if str(transcription.get("rhythm_profile", "")) in {"auto", "strict_1_64"}:
        result["transcription"]["rhythm_profile"] = str(transcription["rhythm_profile"])
    result["version"] = UI_PREFERENCES_VERSION
    return result


def ui_preferences(config: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_ui_preferences(config.get(UI_PREFERENCES_KEY))


def store_ui_preferences(
    config: MutableMapping[str, Any],
    preferences: object,
) -> dict[str, Any]:
    normalized = normalize_ui_preferences(preferences)
    config[UI_PREFERENCES_KEY] = normalized
    return normalized


__all__ = [
    "DEFAULT_UI_PREFERENCES",
    "UI_PREFERENCES_KEY",
    "UI_PREFERENCES_VERSION",
    "normalize_ui_preferences",
    "store_ui_preferences",
    "ui_preferences",
]
