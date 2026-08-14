"""Qt-free, undo-ready track presentation and duplication operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from bdo_music_composer.editor.editor_models import TrackState


def duplicate_track_state(
    source: TrackState,
    *,
    track_id: int,
    display_name: str,
    color: str | None = None,
) -> TrackState:
    """Return an independent track copy with collision-free Clip identities."""

    duplicated = deepcopy(source)
    duplicated.track_id = int(track_id)
    duplicated.display_name = str(display_name).strip()[:160]
    if color is not None:
        duplicated.color = str(color)
    duplicated.bdo_source_group_index = None
    duplicated.arrangement_group_id = ""
    duplicated.arrangement_clips = [
        replace(clip, clip_id=f"track-{int(track_id)}-copy-{index + 1}")
        for index, clip in enumerate(source.arrangement_clips)
    ]
    return duplicated


__all__ = ["duplicate_track_state"]
