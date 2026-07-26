from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from bdo_instrument_lane_art_qt import (
    ACTIVE_HEADER_ART_OPACITY,
    BUILTIN_INSTRUMENT_ART_DIR,
    INACTIVE_HEADER_ART_OPACITY,
    InstrumentLaneArtwork,
    aspect_fill_source_rect,
    instrument_header_background_rect,
    instrument_watermark_path,
    paint_instrument_header_background,
)


class InstrumentLaneArtworkTests(unittest.TestCase):
    def test_builtin_original_art_is_the_default_for_all_families(self) -> None:
        self.assertTrue(BUILTIN_INSTRUMENT_ART_DIR.is_dir())
        visual_keys = {
            index: key
            for index, key in enumerate((
                "strings.guitar.acoustic",
                "strings.violin.pro",
                "strings.harp",
                "keys.piano",
                "keys.synth.saw",
                "percussion.drum_set",
                "percussion.hand_drum",
                "percussion.cymbals",
                "percussion.handpan",
                "wind.flute",
                "wind.clarinet",
                "wind.horn",
            ))
        }
        cache = InstrumentLaneArtwork()
        self.assertEqual(len(visual_keys), cache.reload(None, visual_keys))
        self.assertTrue(cache.using_builtin)
        self.assertEqual("", cache.source_dir)
        self.assertTrue(all(cache.pixmap_for(key) is not None for key in visual_keys))

    def test_every_visual_family_has_a_nonempty_app_owned_fallback(self) -> None:
        for key in (
            "strings.guitar.acoustic",
            "strings.violin.pro",
            "strings.harp",
            "keys.piano",
            "keys.synth.saw",
            "percussion.drum_set",
            "percussion.hand_drum",
            "percussion.cymbals",
            "percussion.handpan",
            "wind.flute",
            "wind.clarinet",
            "wind.horn",
        ):
            with self.subTest(key=key):
                self.assertFalse(instrument_watermark_path(key).isEmpty())

    def test_local_art_is_preloaded_and_survives_source_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instrument_0a.png"
            image = QImage(180, 72, QImage.Format_ARGB32)
            image.fill(QColor("#d89a3d"))
            self.assertTrue(image.save(str(path)))
            cache = InstrumentLaneArtwork()
            self.assertEqual(
                1,
                cache.reload(directory, {0x0A: "strings.guitar.acoustic.pro"}),
            )
            self.assertFalse(cache.using_builtin)
            loaded = cache.pixmap_for(0x0A)
            self.assertIsNotNone(loaded)
            self.assertLessEqual(loaded.height(), 96)
            path.unlink()
            # The paint-time lookup is memory-only; it cannot depend on the
            # source file still existing.
            self.assertIs(cache.pixmap_for(0x0A), loaded)

    def test_missing_directory_falls_back_to_packaged_original_art(self) -> None:
        cache = InstrumentLaneArtwork()
        self.assertEqual(
            1,
            cache.reload("Z:/definitely/missing/instrument-art", {0x11: "keys.piano"}),
        )
        self.assertIsNotNone(cache.pixmap_for(0x11))
        self.assertTrue(cache.using_builtin)
        self.assertTrue(cache.warnings)

    def test_header_background_fills_the_track_information_tile(self) -> None:
        header = QRectF(40.0, 80.0, 320.0, 58.0)
        background = instrument_header_background_rect(header)
        self.assertEqual(QRectF(45.0, 82.0, 310.0, 54.0), background)
        self.assertGreater(background.width(), header.width() * 0.9)
        self.assertLessEqual(background.bottom(), header.bottom())

        # A compressed row fails closed rather than muddying its controls.
        self.assertTrue(
            instrument_header_background_rect(
                QRectF(0.0, 0.0, 70.0, 20.0)
            ).isEmpty()
        )

    def test_header_background_paint_fills_and_stays_clipped(self) -> None:
        canvas = QImage(80, 50, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        source = QImage(80, 40, QImage.Format_ARGB32)
        source.fill(QColor("#d89a3d"))
        slot = QRectF(6.0, 4.0, 68.0, 42.0)

        painter = QPainter(canvas)
        paint_instrument_header_background(
            painter,
            slot,
            visual_key="keys.piano",
            accent=QColor("#d89a3d"),
            pixmap=source,
        )
        painter.end()

        self.assertGreater(canvas.pixelColor(8, 25).alpha(), 0)
        self.assertGreater(canvas.pixelColor(72, 25).alpha(), 0)
        self.assertEqual(0, canvas.pixelColor(2, 25).alpha())

    def test_header_art_uses_centered_aspect_fill_crop(self) -> None:
        source = QRectF(0.0, 0.0, 384.0, 341.0)
        target = QRectF(5.0, 2.0, 310.0, 54.0)
        crop = aspect_fill_source_rect(source, target)

        self.assertAlmostEqual(
            target.width() / target.height(),
            crop.width() / crop.height(),
        )
        self.assertAlmostEqual(source.center().x(), crop.center().x())
        self.assertAlmostEqual(source.center().y(), crop.center().y())
        self.assertEqual(source.width(), crop.width())
        self.assertLess(crop.height(), source.height())

        # Device pixel ratio changes resolution, not geometry: the same
        # square source at 2x must retain the same centered proportional crop.
        high_dpi_crop = aspect_fill_source_rect(
            QRectF(0.0, 0.0, 768.0, 682.0),
            target,
        )
        self.assertAlmostEqual(crop.left() * 2.0, high_dpi_crop.left())
        self.assertAlmostEqual(crop.top() * 2.0, high_dpi_crop.top())
        self.assertAlmostEqual(crop.width() * 2.0, high_dpi_crop.width())
        self.assertAlmostEqual(crop.height() * 2.0, high_dpi_crop.height())

    def test_header_art_is_not_non_uniformly_stretched(self) -> None:
        # A square vertical gradient drawn into a 4:1 header must use only the
        # centered quarter of the source.  A legacy width/height stretch would
        # instead map the full 0..255 gradient into the target.
        source = QImage(100, 100, QImage.Format_ARGB32)
        for y in range(source.height()):
            color = QColor(y * 255 // 99, 90, 30, 255)
            for x in range(source.width()):
                source.setPixelColor(x, y, color)
        canvas = QImage(200, 50, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)

        painter = QPainter(canvas)
        paint_instrument_header_background(
            painter,
            QRectF(0.0, 0.0, 200.0, 50.0),
            visual_key="keys.piano",
            accent=QColor("#d89a3d"),
            pixmap=source,
        )
        painter.end()

        # Source rows ~37..62 are the proportional center crop.  Opacity is
        # intentionally low, so inspect the unpremultiplied QColor channels.
        self.assertGreater(canvas.pixelColor(100, 1).red(), 70)
        self.assertLess(canvas.pixelColor(100, 48).red(), 190)
        self.assertGreater(canvas.pixelColor(100, 25).alpha(), 0)

    def test_header_art_opacity_remains_a_background_layer(self) -> None:
        self.assertGreater(ACTIVE_HEADER_ART_OPACITY, INACTIVE_HEADER_ART_OPACITY)
        self.assertLessEqual(ACTIVE_HEADER_ART_OPACITY, 0.10)
        self.assertGreater(INACTIVE_HEADER_ART_OPACITY, 0.0)


if __name__ == "__main__":
    unittest.main()
