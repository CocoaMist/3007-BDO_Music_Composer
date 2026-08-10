from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

import bdo_music_composer.app.local_game_art as game_art
from bdo_music_composer.app.local_game_art import (
    COMPOSITION_CSS_PATH,
    EDITOR_INSTRUMENT_IDS,
    GameArtImportError,
    INSTRUMENT_SPRITE_PATH,
    PazEntry,
    PazMeta,
    decompress_paz_payload,
    parse_instrument_sprite_layout,
    read_paz_meta,
)
from bdo_music_composer.ui.local_game_art_qt import import_game_instrument_art


def _css_payload() -> bytes:
    lines = [
        ".icn_instrument { width: 240px; height: 100px; "
        "background: url(../img/spr_instrument.png?v=3) no-repeat; }"
    ]
    for index, instrument_id in enumerate(EDITOR_INSTRUMENT_IDS):
        x = (index % 3) * 250
        y = (index // 3) * 100
        lines.append(
            f".icn_instrument.instrument_{instrument_id} "
            f"{{ background-position: -{x}px -{y}px; }}"
        )
    return "\n".join(lines).encode("utf-8")


def _sprite_payload() -> bytes:
    image = QImage(740, 900, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    for index, _instrument_id in enumerate(EDITOR_INSTRUMENT_IDS):
        x = (index % 3) * 250
        y = (index // 3) * 100
        color = QColor.fromHsv((index * 29) % 360, 180, 220, 255)
        for row in range(y, min(y + 100, image.height())):
            for column in range(x, min(x + 240, image.width())):
                image.setPixelColor(column, row, color)
    buffer = QBuffer()
    if not buffer.open(QIODevice.WriteOnly) or not image.save(buffer, "PNG"):
        raise AssertionError("fixture PNG encode failed")
    return bytes(buffer.data())


class PazPayloadTests(unittest.TestCase):
    def test_decodes_raw_and_stored_wrappers(self) -> None:
        payload = b"example payload"
        self.assertEqual(
            payload,
            decompress_paz_payload(payload + b"padding", expected_size=len(payload)),
        )
        wrapped = b"\x6e" + struct.pack(
            "<II", 9 + len(payload), len(payload)
        ) + payload
        self.assertEqual(
            payload,
            decompress_paz_payload(wrapped, expected_size=len(payload)),
        )

    def test_decodes_literal_and_match_tokens(self) -> None:
        # One four-byte literal, a three-byte back-reference at distance four,
        # then the decoder's bounded eleven-byte literal tail.
        expected = b"abcdabc01234567890"
        body = (
            struct.pack("<I", 0x30)
            + b"abcd"
            + b"\x10"
            + b"\x00\x00\x00\x00"
            + b"01234567890"
        )
        wrapped = b"\x6f" + struct.pack(
            "<II", 9 + len(body), len(expected)
        ) + body

        self.assertEqual(
            expected,
            decompress_paz_payload(wrapped, expected_size=len(expected)),
        )

    def test_size_and_truncation_fail_closed(self) -> None:
        for payload, expected in (
            (b"", 1),
            (b"\x6e" + struct.pack("<II", 20, 5) + b"a", 5),
            (b"raw", 8),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(GameArtImportError):
                    decompress_paz_payload(payload, expected_size=expected)
        with self.assertRaises(GameArtImportError):
            decompress_paz_payload(b"raw", expected_size=20_000_000)


class SpriteLayoutTests(unittest.TestCase):
    def test_parses_grouped_and_individual_instrument_rules(self) -> None:
        css = _css_payload().decode("utf-8")
        css += (
            "\n.icn_instrument.instrument_90,\n"
            ".icn_instrument.instrument_91,\n"
            ".icn_instrument.instrument_92,\n"
            ".icn_instrument.instrument_93 "
            "{ background-position: -500px 0px; }"
        )
        layout = parse_instrument_sprite_layout(css.encode("utf-8"))

        self.assertEqual((240, 100), (layout.tile_width, layout.tile_height))
        self.assertEqual((500, 0), layout.positions[90])
        self.assertEqual((500, 0), layout.positions[93])

    def test_missing_editor_instrument_is_rejected(self) -> None:
        css = _css_payload().decode("utf-8")
        css = css.replace(
            ".icn_instrument.instrument_40 { background-position:",
            ".ignored.instrument_40 { background-position:",
        )
        with self.assertRaisesRegex(GameArtImportError, "incomplete"):
            parse_instrument_sprite_layout(css.encode("utf-8"))


class LocalGameArtImportTests(unittest.TestCase):
    def test_reviewed_meta_versions_include_current_v782(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in (757, 782):
                with self.subTest(version=version):
                    (root / "pad00000.meta").write_bytes(
                        struct.pack("<II", version, 0)
                    )
                    self.assertEqual(version, read_paz_meta(root).version)

    def test_unreviewed_meta_version_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pad00000.meta").write_bytes(struct.pack("<II", 758, 0))

            with self.assertRaisesRegex(GameArtImportError, "not reviewed"):
                read_paz_meta(root)
            meta = read_paz_meta(root, allow_unverified_meta_version=True)
            self.assertEqual(758, meta.version)

    def test_cache_path_rejects_game_and_git_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paz = root / "Paz"
            paz.mkdir()
            with self.assertRaisesRegex(GameArtImportError, "PAZ directory"):
                game_art._safe_cache_root(paz, paz / "art")

            repository = root / "repository"
            (repository / ".git").mkdir(parents=True)
            with self.assertRaisesRegex(GameArtImportError, "Git"):
                game_art._safe_cache_root(paz, repository / "local-art")

    def test_import_is_atomic_local_and_integrity_checked(self) -> None:
        css = _css_payload()
        sprite = _sprite_payload()
        meta = PazMeta(757, "a" * 64, {6445: (0, 1)})
        entries = {
            COMPOSITION_CSS_PATH: PazEntry(
                6445, 1, 8, len(css), COMPOSITION_CSS_PATH
            ),
            INSTRUMENT_SPRITE_PATH: PazEntry(
                6445, 2, 8, len(sprite), INSTRUMENT_SPRITE_PATH
            ),
        }

        def read_asset(_root: object, entry: PazEntry) -> bytes:
            return css if entry.game_path == COMPOSITION_CSS_PATH else sprite

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paz = root / "Paz"
            cache = root / "cache"
            paz.mkdir()
            with (
                mock.patch.object(
                    game_art,
                    "index_composition_ui_assets",
                    return_value=(meta, entries),
                ),
                mock.patch.object(
                    game_art, "read_indexed_asset", side_effect=read_asset
                ),
            ):
                first = import_game_instrument_art(paz, cache)
                second = import_game_instrument_art(paz, cache)

                self.assertFalse(first.reused)
                self.assertTrue(second.reused)
                output = Path(first.output_dir)
                self.assertEqual(len(EDITOR_INSTRUMENT_IDS), first.image_count)
                self.assertEqual(
                    len(EDITOR_INSTRUMENT_IDS),
                    len(list(output.glob("instrument_*.png"))),
                )
                manifest_text = (
                    output / "bdo-local-art-manifest.json"
                ).read_text(encoding="utf-8")
                manifest = json.loads(manifest_text)
                self.assertNotIn(str(paz), manifest_text)
                self.assertEqual(1, manifest["format"])

                # An existing corrupted cache is never silently overwritten.
                damaged = output / "instrument_00.png"
                damaged.write_bytes(b"damaged")
                with self.assertRaisesRegex(GameArtImportError, "integrity"):
                    import_game_instrument_art(paz, cache)
                self.assertEqual(b"damaged", damaged.read_bytes())


if __name__ == "__main__":
    unittest.main()
