"""Non-destructive arrangement grouping for tracks sharing one game instrument."""

from __future__ import annotations

from typing import Sequence

from bdo_music_composer.editor.game_score_model import serialized_game_instrument_id


def same_instrument_group_ids(tracks: Sequence[object]) -> dict[int, str]:
    """Return automatic Group assignments for duplicate game instruments."""

    buckets: dict[int, list[object]] = {}
    for track in tracks:
        buckets.setdefault(serialized_game_instrument_id(track), []).append(track)
    result: dict[int, str] = {}
    for instrument_id, members in buckets.items():
        group_id = f"game-instrument:{instrument_id}" if len(members) > 1 else ""
        for track in members:
            result[int(track.track_id)] = group_id
    return result


def move_group_block(
    tracks: Sequence[object], source: object, direction: int
) -> tuple[object, ...]:
    """Move one Track or its contiguous Group across the adjacent block."""

    blocks: list[list[object]] = []
    for track in tracks:
        group_id = str(getattr(track, "arrangement_group_id", "") or "")
        if (
            group_id
            and blocks
            and str(getattr(blocks[-1][0], "arrangement_group_id", "") or "")
            == group_id
        ):
            blocks[-1].append(track)
        else:
            blocks.append([track])
    source_block = next(
        (index for index, block in enumerate(blocks) if source in block), None
    )
    if source_block is None:
        return tuple(tracks)
    destination = source_block + (1 if direction > 0 else -1)
    if not 0 <= destination < len(blocks):
        return tuple(tracks)
    blocks[source_block], blocks[destination] = blocks[destination], blocks[source_block]
    return tuple(track for block in blocks for track in block)


__all__ = ["move_group_block", "same_instrument_group_ids"]
