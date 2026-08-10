from __future__ import annotations

from pathlib import Path, PurePosixPath
import unittest

from bdo_music_composer.core.content_boundary import (
    CONTENT_BOUNDARY_PARAGRAPHS,
    CONTENT_BOUNDARY_TITLE,
    PROHIBITED_GAME_AUDIO_TOOL_FILENAMES,
)
from bdo_music_composer.core.paz_readonly import (
    Ice,
    archive_table_span,
    validate_game_path,
)
from bdo_music_composer.ui.i18n import TRANSLATIONS
from tools.check_repository_hygiene import forbidden_path_errors


ROOT = Path(__file__).resolve().parents[1]


class ContentBoundaryTests(unittest.TestCase):
    def test_boundary_is_localized_for_every_supported_ui_language(self) -> None:
        for language in ("en_US", "ja_JP", "ko_KR"):
            catalog = TRANSLATIONS[language]
            self.assertIn(CONTENT_BOUNDARY_TITLE, catalog)
            for paragraph in CONTENT_BOUNDARY_PARAGRAPHS:
                self.assertIn(paragraph, catalog)

    def test_retired_client_audio_tools_are_absent_and_rejected(self) -> None:
        paths = tuple(
            PurePosixPath(f"tools/{name}")
            for name in sorted(PROHIBITED_GAME_AUDIO_TOOL_FILENAMES)
        )
        self.assertTrue(all(not (ROOT / path).exists() for path in paths))
        self.assertEqual(len(forbidden_path_errors(paths)), len(paths))

    def test_artwork_primitive_keeps_bounded_path_invariants(self) -> None:
        codec = Ice(bytes.fromhex("51 F3 0F 11 04 24 6A 00"))
        self.assertEqual(
            codec.decrypt(bytes.fromhex("c3bdf28b3c7dde63")),
            bytes.fromhex("0001020304050607"),
        )
        self.assertEqual(archive_table_span(100, 2, 16), (48, 76))
        self.assertEqual(
            validate_game_path("UI_Data\\MusicComposition.css"),
            "ui_data/musiccomposition.css",
        )
        with self.assertRaises(ValueError):
            validate_game_path("../sound/example.wem")


if __name__ == "__main__":
    unittest.main()
