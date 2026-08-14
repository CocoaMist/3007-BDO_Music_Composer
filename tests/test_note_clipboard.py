from __future__ import annotations

import json
import unittest

from bdo_midi import Note
from bdo_music_composer.editor.note_clipboard import (
    decode_note_clipboard,
    encode_note_clipboard,
    normalized_clipboard_notes,
)


class NoteClipboardTests(unittest.TestCase):
    def test_round_trip_preserves_group_rhythm_and_all_note_fields(self) -> None:
        notes = (
            Note(60, 77, 125.0, 80.0, 5),
            Note(64, 91, 250.0, 120.0, 0),
        )

        normalized = normalized_clipboard_notes(notes)
        decoded = decode_note_clipboard(encode_note_clipboard(notes))

        self.assertEqual(decoded, normalized)
        self.assertEqual(
            decoded,
            (
                Note(60, 77, 0.0, 80.0, 5),
                Note(64, 91, 125.0, 120.0, 0),
            ),
        )

    def test_decode_rejects_invalid_version_shape_and_values(self) -> None:
        invalid = (
            b"{}",
            json.dumps({"version": 1, "notes": []}).encode(),
            json.dumps({"version": 1, "notes": [[60, 80, 0, -1, 0]]}).encode(),
            json.dumps({"version": 1, "notes": [[60, 80, 10, 20, 0]]}).encode(),
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    decode_note_clipboard(payload)


if __name__ == "__main__":
    unittest.main()
