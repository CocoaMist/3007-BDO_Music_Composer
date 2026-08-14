"""Cached, license-safe instrument watermarks for timeline lanes.

The repository deliberately ships no Black Desert artwork.  It includes a
small set of original AI-assisted instrument-family icons and can optionally
preload user-supplied images from a local directory.  User art overrides the
built-in family icon; missing families fall back to the built-in art and then
to the app-owned vector silhouette.  Directory scanning and image decoding
happen only during reload; :meth:`pixmap_for` and the paint helper do no
filesystem access.
"""

from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
)

from bdo_music_composer.core.project_paths import ASSETS_DIR


ARTWORK_FILE_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")
MAX_ARTWORK_FILE_BYTES = 8 * 1024 * 1024
MAX_ARTWORK_PIXELS = 20_000_000
PRELOAD_HEIGHT = 96
PRELOAD_MAX_WIDTH = 720
BUILTIN_INSTRUMENT_ART_DIR = ASSETS_DIR / "instruments" / "ai_v1"
ACTIVE_HEADER_ART_OPACITY = 0.085
INACTIVE_HEADER_ART_OPACITY = 0.032
_DECODED_IMAGE_CACHE_LIMIT = 64
_DECODED_IMAGE_CACHE: OrderedDict[tuple[str, int, int], QImage] = OrderedDict()


def _family_key(visual_key: str) -> str:
    value = str(visual_key or "").casefold()
    if "drum_set" in value:
        return "drum_set"
    if "hand_drum" in value:
        return "hand_drum"
    if "cymbal" in value:
        return "cymbals"
    if "handpan" in value:
        return "handpan"
    if "guitar" in value or "bass.electric" in value:
        return "guitar"
    if "contrabass" in value or "violin" in value:
        return "bowed_strings"
    if "harp" in value:
        return "harp"
    if "piano" in value:
        return "piano"
    if "synth" in value:
        return "synth"
    if "horn" in value:
        return "horn"
    if "clarinet" in value or "recorder" in value:
        return "reed"
    if "flute" in value:
        return "flute"
    return value.partition(".")[0] or "generic"


def _candidate_stems(instrument_id: int, visual_key: str) -> tuple[str, ...]:
    normalized = str(visual_key).casefold().replace(".", "_")
    family = _family_key(visual_key)
    return tuple(dict.fromkeys((
        f"instrument_{int(instrument_id):02x}",
        f"{int(instrument_id):02x}",
        normalized,
        family,
    )))


class InstrumentLaneArtwork:
    """Preloaded local instrument art; safe to query from a paint event."""

    def __init__(self) -> None:
        self.source_dir = ""
        self.using_builtin = False
        # Keep decoded QImages rather than native-window QPixmaps.  Several
        # offscreen Qt test/application lifecycles can invalidate a QPixmap
        # when the platform integration is restarted, while a detached image
        # remains process-local and needs no filesystem access during paint.
        self._images: dict[int, QImage] = {}
        self.warnings: tuple[str, ...] = ()

    def clear(self) -> None:
        self.source_dir = ""
        self.using_builtin = False
        self._images.clear()
        self.warnings = ()

    def reload(
        self,
        directory: str | Path | None,
        visual_keys: Mapping[int, str],
    ) -> int:
        """Decode bounded artwork outside the timeline paint path.

        A configured local directory has priority.  The packaged original
        family atlas is a per-instrument fallback, so a partial custom set is
        useful without leaving the remaining lanes blank.
        """

        self.clear()
        raw_directory = str(directory or "").strip()
        warnings: list[str] = []
        roots: list[tuple[Path, bool]] = []
        if raw_directory:
            custom_root = Path(raw_directory)
            if custom_root.is_dir():
                custom_root = custom_root.resolve()
                self.source_dir = str(custom_root)
                roots.append((custom_root, False))
            else:
                warnings.append("instrument artwork directory is unavailable")
        if BUILTIN_INSTRUMENT_ART_DIR.is_dir():
            roots.append((BUILTIN_INSTRUMENT_ART_DIR, True))
        elif not roots:
            warnings.append("built-in instrument artwork is unavailable")

        decoded_by_path: dict[Path, QImage | None] = {}
        for instrument_id, visual_key in sorted(visual_keys.items()):
            selected: Path | None = None
            selected_is_builtin = False
            for root, is_builtin in roots:
                for stem in _candidate_stems(instrument_id, visual_key):
                    for extension in ARTWORK_FILE_EXTENSIONS:
                        candidate = root / f"{stem}{extension}"
                        if candidate.is_file():
                            selected = candidate
                            selected_is_builtin = is_builtin
                            break
                    if selected is not None:
                        break
                if selected is not None:
                    break
            if selected is None:
                continue
            if selected_is_builtin:
                self.using_builtin = True
            try:
                image = decoded_by_path.get(selected)
                if selected not in decoded_by_path:
                    stat = selected.stat()
                    if stat.st_size > MAX_ARTWORK_FILE_BYTES:
                        warnings.append(f"0x{instrument_id:02X}: file too large")
                        decoded_by_path[selected] = None
                        continue
                    cache_key = (
                        str(selected.resolve()),
                        int(stat.st_mtime_ns),
                        int(stat.st_size),
                    )
                    cached = _DECODED_IMAGE_CACHE.get(cache_key)
                    if cached is not None:
                        _DECODED_IMAGE_CACHE.move_to_end(cache_key)
                        image = QImage(cached)
                    else:
                        reader = QImageReader(str(selected))
                        reader.setAutoTransform(True)
                        size = reader.size()
                        if (
                            not size.isValid()
                            or size.width() <= 0
                            or size.height() <= 0
                            or size.width() * size.height() > MAX_ARTWORK_PIXELS
                        ):
                            warnings.append(f"0x{instrument_id:02X}: invalid image size")
                            decoded_by_path[selected] = None
                            continue
                        scale = min(
                            PRELOAD_MAX_WIDTH / size.width(),
                            PRELOAD_HEIGHT / size.height(),
                            1.0,
                        )
                        reader.setScaledSize(QSize(
                            max(1, round(size.width() * scale)),
                            max(1, round(size.height() * scale)),
                        ))
                        loaded = reader.read()
                        if loaded.isNull():
                            warnings.append(f"0x{instrument_id:02X}: unreadable image")
                            decoded_by_path[selected] = None
                            continue
                        # Detach from QImageReader and its source device. The
                        # local file may be moved after configuration.
                        image = loaded.copy()
                        _DECODED_IMAGE_CACHE[cache_key] = QImage(image)
                        while len(_DECODED_IMAGE_CACHE) > _DECODED_IMAGE_CACHE_LIMIT:
                            _DECODED_IMAGE_CACHE.popitem(last=False)
                    decoded_by_path[selected] = image
                if image is not None:
                    self._images[int(instrument_id)] = image
            except OSError:
                warnings.append(f"0x{instrument_id:02X}: image read failed")
                decoded_by_path[selected] = None
        self.warnings = tuple(warnings)
        return len(self._images)

    def pixmap_for(self, instrument_id: int) -> QImage | None:
        """Return ready raster art without opening or decoding any file.

        The historical method name is retained for UI-call compatibility.
        """

        image = self._images.get(int(instrument_id))
        return image if image is not None and not image.isNull() else None


@lru_cache(maxsize=16)
def instrument_watermark_path(family: str) -> QPainterPath:
    """Return one normalized app-owned silhouette (0..100 by 0..44)."""

    key = _family_key(family)
    path = QPainterPath()
    if key == "guitar":
        path.addEllipse(QRectF(10, 14, 24, 24))
        path.addEllipse(QRectF(29, 11, 19, 28))
        path.moveTo(44, 22)
        path.lineTo(86, 9)
        path.lineTo(90, 13)
        path.lineTo(47, 27)
        path.moveTo(18, 26)
        path.lineTo(84, 10)
    elif key == "bowed_strings":
        path.cubicTo(18, 4, 35, 8, 30, 20)
        path.cubicTo(24, 31, 42, 39, 51, 30)
        path.cubicTo(60, 19, 50, 8, 60, 4)
        path.moveTo(44, 27)
        path.lineTo(76, 2)
        path.moveTo(15, 42)
        path.lineTo(79, 5)
    elif key == "harp":
        path.moveTo(16, 39)
        path.lineTo(35, 5)
        path.cubicTo(66, 8, 81, 21, 84, 39)
        path.closeSubpath()
        for x in (34, 43, 52, 61, 70):
            path.moveTo(x, 9)
            path.lineTo(x + 7, 38)
    elif key == "piano":
        path.addRoundedRect(QRectF(8, 8, 84, 29), 4, 4)
        for x in range(18, 88, 10):
            path.moveTo(x, 21)
            path.lineTo(x, 37)
        for x in (23, 43, 53, 73):
            path.addRect(QRectF(x, 8, 5, 17))
    elif key == "synth":
        path.addRoundedRect(QRectF(7, 7, 86, 31), 5, 5)
        path.moveTo(14, 23)
        path.cubicTo(24, 4, 34, 42, 44, 23)
        path.cubicTo(54, 4, 64, 42, 74, 23)
        path.lineTo(87, 23)
    elif key == "drum_set":
        path.addEllipse(QRectF(35, 13, 31, 28))
        path.addEllipse(QRectF(12, 17, 22, 17))
        path.addEllipse(QRectF(68, 17, 22, 17))
        path.moveTo(22, 17)
        path.lineTo(18, 4)
        path.moveTo(79, 17)
        path.lineTo(85, 4)
        path.addEllipse(QRectF(4, 2, 29, 5))
        path.addEllipse(QRectF(70, 2, 28, 5))
    elif key == "hand_drum":
        path.addEllipse(QRectF(27, 5, 46, 10))
        path.moveTo(28, 10)
        path.lineTo(36, 40)
        path.lineTo(64, 40)
        path.lineTo(72, 10)
    elif key == "cymbals":
        path.addEllipse(QRectF(8, 12, 56, 10))
        path.addEllipse(QRectF(37, 23, 56, 10))
        path.moveTo(36, 17)
        path.lineTo(20, 39)
        path.moveTo(65, 28)
        path.lineTo(82, 42)
    elif key == "handpan":
        path.addEllipse(QRectF(24, 3, 52, 39))
        path.addEllipse(QRectF(44, 17, 12, 10))
        for x, y in ((34, 11), (61, 11), (32, 29), (62, 30)):
            path.addEllipse(QRectF(x, y, 7, 6))
    elif key == "horn":
        path.addEllipse(QRectF(18, 8, 40, 29))
        path.addEllipse(QRectF(29, 15, 20, 15))
        path.moveTo(54, 20)
        path.cubicTo(67, 10, 78, 11, 92, 5)
        path.lineTo(88, 26)
        path.cubicTo(75, 20, 66, 28, 53, 25)
    elif key in {"flute", "reed"}:
        path.moveTo(10, 31)
        path.lineTo(85, 8 if key == "flute" else 3)
        path.lineTo(90, 11)
        path.lineTo(14, 35)
        for x in (30, 42, 54, 66, 78):
            path.addEllipse(QRectF(x, 19 - (x - 30) * 0.3, 3, 3))
    else:
        path.moveTo(7, 27)
        path.cubicTo(22, 4, 35, 41, 50, 20)
        path.cubicTo(65, 2, 77, 39, 93, 15)
    return path


def instrument_header_background_rect(header_rect: QRectF) -> QRectF:
    """Return the full-bleed art area behind one track-header tile."""

    if header_rect.width() < 80.0 or header_rect.height() < 24.0:
        return QRectF()
    return header_rect.adjusted(5.0, 2.0, -5.0, -2.0)


def aspect_fill_source_rect(source_rect: QRectF, target_rect: QRectF) -> QRectF:
    """Return the centered source crop for a proportional ``cover`` draw.

    Timeline headers are much wider than the square family artwork.  Drawing
    the complete source into that rectangle distorts the instrument, while a
    proportional ``contain`` draw leaves most of the requested background
    empty.  A centered source crop keeps one scale factor on both axes and
    fills the clipped header at every row width and device scale.
    """

    source = QRectF(source_rect)
    if (
        source.width() <= 0.0
        or source.height() <= 0.0
        or target_rect.width() <= 0.0
        or target_rect.height() <= 0.0
    ):
        return QRectF()
    target_aspect = target_rect.width() / target_rect.height()
    source_aspect = source.width() / source.height()
    if source_aspect > target_aspect:
        crop_width = source.height() * target_aspect
        source.setLeft(source.center().x() - crop_width * 0.5)
        source.setWidth(crop_width)
    elif source_aspect < target_aspect:
        crop_height = source.width() / target_aspect
        source.setTop(source.center().y() - crop_height * 0.5)
        source.setHeight(crop_height)
    return source


def paint_instrument_header_background(
    painter: QPainter,
    rect: QRectF,
    *,
    visual_key: str,
    accent: QColor,
    pixmap: QImage | None = None,
    active: bool = True,
) -> None:
    """Fill a header tile with low-opacity, memory-only instrument art."""

    if rect.width() < 10.0 or rect.height() < 10.0:
        return
    painter.save()
    painter.setClipRect(rect)
    if pixmap is not None and not pixmap.isNull():
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(
            ACTIVE_HEADER_ART_OPACITY if active else INACTIVE_HEADER_ART_OPACITY
        )
        source_rect = aspect_fill_source_rect(QRectF(pixmap.rect()), rect)
        if not source_rect.isEmpty():
            painter.drawImage(rect, pixmap, source_rect)
    else:
        color = QColor(accent)
        color.setAlpha(255)
        painter.setOpacity(
            ACTIVE_HEADER_ART_OPACITY if active else INACTIVE_HEADER_ART_OPACITY
        )
        pen = QPen(color, 1.15)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = instrument_watermark_path(visual_key)
        bounds = path.boundingRect()
        if bounds.width() > 0.0 and bounds.height() > 0.0:
            scale = max(
                rect.width() / bounds.width(),
                rect.height() / bounds.height(),
            )
            painter.translate(rect.center())
            painter.scale(scale, scale)
            painter.translate(-bounds.center().x(), -bounds.center().y())
            painter.drawPath(path)
    painter.restore()


__all__ = [
    "ARTWORK_FILE_EXTENSIONS",
    "ACTIVE_HEADER_ART_OPACITY",
    "BUILTIN_INSTRUMENT_ART_DIR",
    "INACTIVE_HEADER_ART_OPACITY",
    "InstrumentLaneArtwork",
    "aspect_fill_source_rect",
    "instrument_header_background_rect",
    "instrument_watermark_path",
    "paint_instrument_header_background",
]
