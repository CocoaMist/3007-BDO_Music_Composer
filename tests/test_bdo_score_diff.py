from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bdo_score import compare_scores, read_bdo_score, snapshot_from_bytes
from pyside_bdo_gui import Note, channel_groups_to_bdo


def score(pitch: int, start: float = 0.0) -> bytes:
    data, _summary = channel_groups_to_bdo(
        120,
        4,
        [([Note(pitch, 90, start, 300.0, 0)], 0, False)],
        char_name="PrivateName",
        owner_id=12345,
        instrument_map={0: 11},
        preserve_note_types=True,
    )
    return data


class BdoScoreDiffTests(unittest.TestCase):
    def test_snapshot_contains_all_notes_and_binary_structure(self) -> None:
        snapshot = snapshot_from_bytes(score(60))
        self.assertEqual(snapshot.version, 9)
        self.assertEqual(snapshot.total_notes, 1)
        self.assertEqual(snapshot.tracks[0].notes[0].pitch, 60)
        self.assertEqual(snapshot.owner_id, 12345)
        self.assertGreaterEqual(snapshot.trailing_zero_bytes, 0)

    def test_large_game_score_can_supply_owner_identity(self) -> None:
        notes = [Note(60 + index % 12, 90, index * 100.0, 80.0, 0) for index in range(80)]
        data, _summary = channel_groups_to_bdo(
            120,
            4,
            [(notes, 0, False)],
            char_name="PrivateName",
            owner_id=12345,
            instrument_map={0: 11},
            preserve_note_types=True,
        )
        self.assertGreater(len(data), 1024)
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "game-score"
            path.write_bytes(data)
            snapshot = read_bdo_score(path, allow_trailing_data=True)
        self.assertEqual(snapshot.owner_id, 12345)
        self.assertEqual(snapshot.character_name_1, "PrivateName")

    def test_diff_ignores_private_fields_by_default_and_detects_notes(self) -> None:
        baseline = snapshot_from_bytes(score(60))
        same = snapshot_from_bytes(score(60))
        self.assertTrue(compare_scores(baseline, same).identical)
        changed = snapshot_from_bytes(score(61))
        result = compare_scores(baseline, changed)
        self.assertFalse(result.identical)
        self.assertTrue(any(item.path.endswith(".pitch") for item in result.differences))

    def test_reordered_instruments_do_not_create_false_note_differences(self) -> None:
        left_data, _ = channel_groups_to_bdo(
            120, 4,
            [([Note(60, 90, 0, 100, 0)], 0, False), ([Note(72, 90, 0, 100, 0)], 0, False)],
            instrument_map={0: 11, 1: 16}, preserve_note_types=True,
        )
        right_data, _ = channel_groups_to_bdo(
            120, 4,
            [([Note(72, 90, 0, 100, 0)], 0, False), ([Note(60, 90, 0, 100, 0)], 0, False)],
            instrument_map={0: 16, 1: 11}, preserve_note_types=True,
        )
        result = compare_scores(snapshot_from_bytes(left_data), snapshot_from_bytes(right_data))
        self.assertTrue(any(item.path == "tracks.instrument_order" for item in result.differences))
        self.assertFalse(any(item.path.endswith(".pitch") for item in result.differences))


if __name__ == "__main__":
    unittest.main()
