"""Qt-bound Clip hit-testing and marquee selection geometry.

Pure functions extracted from :class:`TimelineCanvas` so the timeline hit
index and selection rules stay independently testable.  They never read or
mutate canvas state; callers pass the hit regions and tool/selection state in.
"""

from __future__ import annotations

from collections.abc import Sequence, Set

from PySide6.QtCore import QPointF, QRectF

from bdo_music_composer.editor.editor_models import TrackState


HitRegion = tuple[QRectF, str, object]
"""One resolved interactive region: geometry, action tag, and target item."""


def marquee_rect(
    press_pos: QPointF | None,
    current_pos: QPointF,
    grid_rect: QRectF,
) -> QRectF:
    """Return the normalized marquee rectangle, clipped to the grid area."""

    if press_pos is None:
        return QRectF()
    return QRectF(press_pos, current_pos).normalized().intersected(grid_rect)


def clip_keys_intersecting(
    hit_regions: Sequence[HitRegion],
    rect: QRectF,
) -> set[tuple[int, str]]:
    """Return every Clip body region intersecting a marquee rectangle."""

    if rect.isEmpty():
        return set()
    return {
        (int(item.track_id), action.split("|", 1)[1])
        for region, action, item in hit_regions
        if (
            action.startswith("clip_body|")
            and isinstance(item, TrackState)
            and region.intersects(rect)
        )
    }


def clip_action_at(
    hit_regions: Sequence[HitRegion],
    position: QPointF,
    *,
    arrangement_tool: str,
    selected_clip_keys: Set[tuple[int, str]] | None = None,
) -> tuple[TrackState, str, str] | None:
    """Resolve one Clip gesture, with visible handles above the body."""

    selected = selected_clip_keys if selected_clip_keys is not None else frozenset()
    for rect, action, item in reversed(hit_regions):
        action_kind, _separator, clip_id = action.partition("|")
        if (
            action_kind in {"clip_body", "clip_start", "clip_end"}
            and isinstance(item, TrackState)
            and rect.contains(position)
        ):
            key = (int(item.track_id), str(clip_id))
            if (
                action_kind in {"clip_start", "clip_end"}
                and (
                    arrangement_tool != "select"
                    or key not in selected
                )
            ):
                action_kind = "clip_body"
            return item, str(clip_id), action_kind
    return None


__all__ = [
    "HitRegion",
    "clip_action_at",
    "clip_keys_intersecting",
    "marquee_rect",
]
