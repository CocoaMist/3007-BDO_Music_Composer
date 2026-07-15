from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
import unittest

from bdo_profile import load_bdo_profile
from bdo_validation import ValidationContext, validate_tracks
from project_paths import PROFILES_DIR


Note = namedtuple("Note", "pitch vel start dur ntype")


@dataclass
class Track:
    track_id: int
    notes: list
    bdo_instrument_id: int
    display_name: str = "track"
    is_percussion: bool = False
    muted: bool = False
    solo: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None


class BdoProfileValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_bdo_profile(PROFILES_DIR / "bdo_global_v9.json")

    def context(self, tracks) -> ValidationContext:
        return ValidationContext(
            0,
            frozenset(track.track_id for track in tracks),
            {},
            {36: 48, 37: 49},
            lambda track: track.bdo_instrument_id,
        )

    def test_profile_loads_versioned_limits_and_evidence(self) -> None:
        self.assertEqual(self.profile.format_version, 9)
        self.assertEqual(self.profile.note_limit_per_track, 730)
        self.assertEqual(self.profile.drum_instrument_id, 13)
        self.assertEqual(self.profile.instruments[11].evidence.status, "verified")

    def test_validator_locates_unsupported_notes_and_describes_export_changes(self) -> None:
        track = Track(
            4,
            [Note(47, 90, 0, 200, 0), Note(60, 90, 300, 200, 0)],
            11,
            volume_scale=0.8,
        )
        issues = validate_tracks([track], self.profile, self.context([track]))
        pitch_issue = next(item for item in issues if item.code == "pitch.instrument_unsupported")
        self.assertEqual(pitch_issue.track_id, 4)
        self.assertEqual(pitch_issue.note_indices, (0,))
        self.assertTrue(any(item.code == "export.velocity_scale" for item in issues))

    def test_validator_blocks_unmapped_drums_and_capacity_loss(self) -> None:
        drums = Track(1, [Note(99, 90, 0, 100, 0)], 13, is_percussion=True)
        issues = validate_tracks([drums], self.profile, self.context([drums]))
        self.assertTrue(any(item.code == "drum.unmapped" and item.severity == "error" for item in issues))


if __name__ == "__main__":
    unittest.main()
