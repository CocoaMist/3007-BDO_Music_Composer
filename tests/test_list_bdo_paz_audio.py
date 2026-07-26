from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from tools.list_bdo_paz_audio import (
    DEFAULT_EXTENSIONS,
    Ice,
    archive_table_span,
    atomic_text_output,
    decode_game_path,
    normalized_extensions,
    path_matches,
    stable_path_digest,
    validate_game_path,
)


class PazPathIndexTests(unittest.TestCase):
    def test_ice_matches_fixed_bdo_vectors(self) -> None:
        codec = Ice(bytes.fromhex("51 F3 0F 11 04 24 6A 00"))
        vectors = {
            "41ef586af7ca4f0e": "0000000000000000",
            "c3bdf28b3c7dde63": "0001020304050607",
            "ad82068a1a7a89a9": "0011223344556677",
        }

        for ciphertext, plaintext in vectors.items():
            with self.subTest(ciphertext=ciphertext):
                self.assertEqual(
                    plaintext,
                    codec.decrypt(bytes.fromhex(ciphertext)).hex(),
                )

    def test_ice_rejects_partial_blocks(self) -> None:
        codec = Ice(bytes.fromhex("51 F3 0F 11 04 24 6A 00"))

        with self.assertRaisesRegex(ValueError, "aligned"):
            codec.decrypt(b"partial")

    def test_extension_normalization_is_deterministic(self) -> None:
        self.assertEqual(
            (".bnk", ".xml"),
            normalized_extensions(["XML", ".BNK", "xml"]),
        )

    def test_path_decoder_reports_legacy_cp949(self) -> None:
        text, encoding = decode_game_path("악기.bnk".encode("cp949"))

        self.assertEqual("악기.bnk", text)
        self.assertEqual("cp949", encoding)

    def test_default_filter_keeps_audio_and_soundbanks(self) -> None:
        extensions = normalized_extensions(DEFAULT_EXTENSIONS)

        self.assertTrue(path_matches("sound/MIDI.BNK", extensions=extensions))
        self.assertTrue(path_matches("sound/voice.WEM", extensions=extensions))
        self.assertFalse(path_matches(
            "ui/musiccomposition.js",
            extensions=extensions,
        ))

    def test_contains_filters_use_case_insensitive_or_semantics(self) -> None:
        extensions = normalized_extensions((".bnk", ".bss"))

        self.assertTrue(path_matches(
            "gamecommondata/binary/MidiInstrument.bss",
            extensions=extensions,
            contains=("missing", "MIDIINSTRUMENT"),
        ))
        self.assertFalse(path_matches(
            "sound2022/windows/bgm_play.bnk",
            extensions=extensions,
            contains=("midi_instrument", "composition"),
        ))

    def test_all_files_still_honours_text_filter(self) -> None:
        self.assertTrue(path_matches(
            "ui_data/js/musiccomposition.js",
            extensions=(),
            contains=("musiccomposition",),
            all_files=True,
        ))
        self.assertFalse(path_matches(
            "ui_data/js/inventory.js",
            extensions=(),
            contains=("musiccomposition",),
            all_files=True,
        ))

    def test_atomic_output_preserves_previous_file_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "index.tsv"
            target.write_text("old", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                with atomic_text_output(target) as output:
                    output.write("partial")
                    raise RuntimeError("stop")

            self.assertEqual("old", target.read_text(encoding="utf-8"))
            self.assertEqual([], list(Path(directory).glob("*.tmp")))

    def test_archive_layout_is_checked_before_table_read(self) -> None:
        self.assertEqual((48, 76), archive_table_span(100, 2, 16))

        with self.assertRaisesRegex(ValueError, "exceed"):
            archive_table_span(75, 2, 16)
        with self.assertRaisesRegex(ValueError, "aligned"):
            archive_table_span(100, 2, 15)

    def test_game_paths_must_be_safe_relative_paths(self) -> None:
        self.assertEqual(
            "sound/midi_instrument_01.bnk",
            validate_game_path("Sound\\MIDI_INSTRUMENT_01.BNK"),
        )
        for unsafe in (
            "../secret.bnk",
            "/absolute.bnk",
            "C:/absolute.bnk",
            "sound/bad\tname.bnk",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    validate_game_path(unsafe)

    def test_path_set_digest_is_order_independent(self) -> None:
        self.assertEqual(
            stable_path_digest({"b.wem", "a.wem"}),
            stable_path_digest({"a.wem", "b.wem"}),
        )


if __name__ == "__main__":
    unittest.main()
