"""Bounded project-wide timeline marker normalization."""

from __future__ import annotations

import math
from typing import Iterable, Mapping


MAX_TIMELINE_MARKERS = 512
MAX_TIMELINE_MARKER_INPUTS = 4096
MAX_MARKER_LABEL_CHARS = 80
MAX_MARKER_ID_CHARS = 96
MAX_MARKER_TIME_MS = 30.0 * 24.0 * 60.0 * 60.0 * 1000.0


def _plain_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit].strip()


def normalize_timeline_markers(markers: object) -> tuple[dict[str, object], ...]:
    """Return finite, unique, paint-safe markers with a strict size bound."""

    if not isinstance(markers, (tuple, list)):
        return ()
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw in markers[:MAX_TIMELINE_MARKER_INPUTS]:
        if len(normalized) >= MAX_TIMELINE_MARKERS:
            break
        if not isinstance(raw, Mapping):
            continue
        marker_id = _plain_text(raw.get("id"), MAX_MARKER_ID_CHARS)
        label = _plain_text(raw.get("label"), MAX_MARKER_LABEL_CHARS)
        try:
            time_ms = float(raw.get("time_ms", 0.0))
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            not marker_id
            or marker_id in seen_ids
            or not label
            or not math.isfinite(time_ms)
        ):
            continue
        seen_ids.add(marker_id)
        normalized.append({
            "id": marker_id,
            "label": label,
            "time_ms": max(0.0, min(MAX_MARKER_TIME_MS, time_ms)),
        })
    normalized.sort(key=lambda item: (float(item["time_ms"]), str(item["id"])))
    return tuple(normalized)


__all__ = [
    "MAX_MARKER_LABEL_CHARS",
    "MAX_TIMELINE_MARKERS",
    "normalize_timeline_markers",
]
