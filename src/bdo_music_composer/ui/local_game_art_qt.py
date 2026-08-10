"""Qt image adapter for the validated local composition-art workflow."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

from bdo_music_composer.app.local_game_art import (
    EDITOR_INSTRUMENT_IDS,
    GameArtImportError,
    GameArtImportReport,
    SpriteLayout,
    import_game_instrument_art as _import_game_instrument_art,
)


def _write_tiles(
    sprite_payload: bytes,
    layout: SpriteLayout,
    destination: Path,
) -> list[dict[str, object]]:
    image = QImage.fromData(sprite_payload, "PNG")
    if image.isNull():
        raise GameArtImportError("instrument sprite cannot be decoded")
    records: list[dict[str, object]] = []
    for instrument_id in EDITOR_INSTRUMENT_IDS:
        x, y = layout.positions[instrument_id]
        if (
            x + layout.tile_width > image.width()
            or y + layout.tile_height > image.height()
        ):
            raise GameArtImportError(
                f"instrument {instrument_id} sprite tile is outside the image"
            )
        tile = image.copy(x, y, layout.tile_width, layout.tile_height)
        if tile.isNull():
            raise GameArtImportError(f"instrument {instrument_id} tile is empty")
        buffer = QBuffer()
        if not buffer.open(QIODevice.WriteOnly) or not tile.save(buffer, "PNG"):
            raise GameArtImportError(
                f"instrument {instrument_id} tile encode failed"
            )
        encoded = bytes(buffer.data())
        filename = f"instrument_{instrument_id:02x}.png"
        (destination / filename).write_bytes(encoded)
        records.append(
            {
                "instrument_id": instrument_id,
                "file": filename,
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "width": layout.tile_width,
                "height": layout.tile_height,
                "source_xy": [x, y],
            }
        )
    return records


def import_game_instrument_art(
    paz_root: str | Path,
    cache_root: str | Path,
    *,
    allow_unverified_meta_version: bool = False,
) -> GameArtImportReport:
    return _import_game_instrument_art(
        paz_root,
        cache_root,
        tile_writer=_write_tiles,
        allow_unverified_meta_version=allow_unverified_meta_version,
    )


__all__ = [
    "GameArtImportError",
    "GameArtImportReport",
    "import_game_instrument_art",
]
