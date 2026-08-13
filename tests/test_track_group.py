from __future__ import annotations

import unittest

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.track_group import (
    move_group_block,
    same_instrument_group_ids,
)


def _track(track_id: int, instrument_id: int) -> TrackState:
    return TrackState(track_id, [], 0, False, f"Track {track_id}", instrument_id)


class TrackGroupTests(unittest.TestCase):
    def test_auto_group_assigns_only_duplicate_instruments(self) -> None:
        tracks = [_track(1, 0x12), _track(2, 0x11), _track(3, 0x12)]
        self.assertEqual(same_instrument_group_ids(tracks), {
            1: "game-instrument:18", 2: "", 3: "game-instrument:18",
        })

    def test_auto_group_ignores_stale_saved_group_ids(self) -> None:
        tracks = [_track(1, 0x12), _track(2, 0x11)]
        tracks[0].arrangement_group_id = "stale-a"
        tracks[1].arrangement_group_id = "stale-b"
        self.assertEqual(same_instrument_group_ids(tracks), {1: "", 2: ""})

    def test_move_treats_group_as_one_block(self) -> None:
        first, second, other = _track(1, 0x12), _track(2, 0x12), _track(3, 0x11)
        first.arrangement_group_id = second.arrangement_group_id = "instrument:18"
        self.assertEqual(
            [track.track_id for track in move_group_block(
                [first, second, other], other, -1
            )],
            [3, 1, 2],
        )


if __name__ == "__main__":
    unittest.main()
