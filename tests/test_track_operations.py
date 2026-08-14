from __future__ import annotations

import unittest

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import (
    ArrangementClipState,
    TrackState,
)
from bdo_music_composer.editor.track_operations import duplicate_track_state


class TrackOperationsTests(unittest.TestCase):
    def test_duplicate_is_independent_and_remaps_clip_identity(self) -> None:
        source = TrackState(
            2,
            [Note(60, 90, 100.0, 120.0, 0)],
            0,
            False,
            "Lead",
            0x12,
            arrangement_group_id="group-a",
            arrangement_clips=[ArrangementClipState(
                "original", 0.0, 400.0, 0.0, 400.0,
                display_name="Verse", color="#123456",
            )],
        )

        result = duplicate_track_state(
            source,
            track_id=8,
            display_name="Lead copy",
            color="#abcdef",
        )

        self.assertEqual((result.track_id, result.display_name), (8, "Lead copy"))
        self.assertEqual(result.arrangement_group_id, "")
        self.assertEqual(result.arrangement_clips[0].clip_id, "track-8-copy-1")
        self.assertEqual(result.arrangement_clips[0].display_name, "Verse")
        self.assertEqual(result.color, "#abcdef")
        result.notes.append(Note(64, 80, 300.0, 100.0, 0))
        self.assertEqual(len(source.notes), 1)


if __name__ == "__main__":
    unittest.main()
