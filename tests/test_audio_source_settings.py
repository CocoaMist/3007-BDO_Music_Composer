from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bdo_music_composer.ui.main_window import (
    activate_audio_source,
    audio_source_config,
    classify_audio_source,
    displayed_audio_source,
    preview_source_mode,
    remember_source_paths,
    source_paths_for_mode,
)


class AudioSourceSettingsTests(unittest.TestCase):
    def test_preview_mode_defaults_and_fails_closed_to_builtin(self) -> None:
        self.assertEqual(preview_source_mode({}), "generic")
        self.assertEqual(preview_source_mode({"preview_mode": "generic"}), "generic")
        self.assertEqual(preview_source_mode({"preview_mode": "pack"}), "pack")
        self.assertEqual(preview_source_mode({"preview_mode": "companion"}), "pack")
        self.assertEqual(preview_source_mode({"preview_mode": "custom"}), "pack")
        self.assertEqual(preview_source_mode({"preview_mode": "BDO"}), "pack")
        self.assertEqual(preview_source_mode({"preview_mode": "unknown"}), "generic")
        self.assertEqual(
            audio_source_config(
                {"audio_sources": {"preview_mode": "unknown"}}
            )["preview_mode"],
            "generic",
        )

    def test_selected_pack_path_is_remembered(self) -> None:
        sources = audio_source_config({})
        remember_source_paths(sources, "pack", "C:/packs/selected.bdosamples", "C:/cache/a")

        activate_audio_source(sources, "pack")
        self.assertEqual(
            source_paths_for_mode(sources, "pack"),
            ("C:/packs/selected.bdosamples", "C:/cache/a"),
        )
        self.assertEqual(sources["sample_pack"], "C:/packs/selected.bdosamples")
        activate_audio_source(sources, "generic")
        self.assertEqual(sources["sample_pack"], "")

    def test_legacy_external_selection_migrates_to_pack(self) -> None:
        sources = audio_source_config({"audio_sources": {
            "preview_mode": "bdo",
            "sample_pack": "C:/packs/legacy.bdosamples",
            "audio_root": "C:/cache/legacy",
        }})
        self.assertEqual(sources["preview_mode"], "pack")
        self.assertEqual(
            source_paths_for_mode(sources, "pack"),
            ("C:/packs/legacy.bdosamples", "C:/cache/legacy"),
        )

    def test_display_prefers_portable_pack_then_preserves_raw_root(self) -> None:
        self.assertEqual(
            displayed_audio_source(
                {"sample_pack": "C:/samples/local.bdosamples", "audio_root": "C:/cache"}
            ),
            "C:/samples/local.bdosamples",
        )
        self.assertEqual(
            displayed_audio_source({"sample_pack": "", "audio_root": "C:/cache"}),
            "C:/cache",
        )

    def test_classify_accepts_pack_or_existing_directory(self) -> None:
        pack, root = classify_audio_source("C:/samples/local.BDOSAMPLES")
        self.assertEqual(pack, "C:/samples/local.BDOSAMPLES")
        self.assertEqual(root, "")
        with tempfile.TemporaryDirectory() as directory:
            pack, root = classify_audio_source(directory)
            self.assertEqual(pack, "")
            self.assertEqual(Path(root), Path(directory).resolve())

    def test_classify_rejects_non_pack_file_and_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "not-an-audio-root.txt"
            invalid.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                classify_audio_source(str(invalid))
        with self.assertRaises(ValueError):
            classify_audio_source("Z:/definitely/missing/bdo-source")

if __name__ == "__main__":
    unittest.main()
