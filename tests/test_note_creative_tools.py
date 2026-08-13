from __future__ import annotations

import unittest

from bdo_midi import Note
from bdo_music_composer.editor.note_creative_tools import (
    humanize_notes,
    quantize_note_starts,
    strum_chords,
)


class NoteCreativeToolsTests(unittest.TestCase):
    def test_quantize_selection_preserves_duration(self) -> None:
        notes = [Note(60, 90, 117.0, 400.0, 0), Note(62, 80, 220.0, 300.0, 0)]
        result = quantize_note_starts(notes, {0}, 125.0)
        self.assertEqual(result[0].start, 125.0)
        self.assertEqual(result[0].dur, 400.0)
        self.assertEqual(result[1], notes[1])

    def test_humanize_is_deterministic_and_bounded(self) -> None:
        notes = [Note(60, 90, 100.0, 400.0, 0)]
        first = humanize_notes(notes, set(), 125.0, seed="track")
        second = humanize_notes(notes, set(), 125.0, seed="track")
        self.assertEqual(first, second)
        self.assertLessEqual(abs(first[0].start - 100.0), 12.0)
        self.assertLessEqual(abs(first[0].vel - 90), 4)

    def test_strum_preserves_chord_end(self) -> None:
        notes = [Note(64, 90, 100.0, 400.0, 0), Note(60, 90, 100.0, 400.0, 0)]
        result = strum_chords(notes, set(), step_ms=20.0)
        low = result[1]
        high = result[0]
        self.assertEqual(low.start, 100.0)
        self.assertEqual(high.start, 120.0)
        self.assertEqual(high.start + high.dur, 500.0)


if __name__ == "__main__":
    unittest.main()
