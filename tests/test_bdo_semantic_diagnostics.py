from __future__ import annotations

import unittest

from bdo_midi import Note
from bdo_music_composer.editor.bdo_semantic_diagnostics import (
    diagnose_bdo_authoring,
    semantic_diff,
    semantic_readiness_score,
)
from bdo_music_composer.editor.editor_models import TrackState


class BdoSemanticDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def _track(notes: list[Note], *, percussion: bool = False) -> TrackState:
        return TrackState(7, notes, 0, percussion, "User track", 0x0D if percussion else 1)

    def test_diagnostics_are_deterministic_and_non_mutating(self) -> None:
        notes = [Note(47, 100, 0.0, 0.0, 0)]
        track = self._track(notes, percussion=True)
        before = tuple(notes)
        first = diagnose_bdo_authoring([track])
        second = diagnose_bdo_authoring([track])
        self.assertEqual(first, second)
        self.assertEqual(tuple(notes), before)
        self.assertEqual(
            [item.code for item in first],
            ["non-positive-duration", "non-canonical-drum-note"],
        )
        self.assertEqual(semantic_readiness_score(first), 65)

    def test_semantic_diff_reports_explicit_changes(self) -> None:
        before = [Note(60, 80, 0.0, 100.0, 0)]
        after = [Note(62, 90, 5.0, 100.0, 1)]
        result = semantic_diff(before, after)
        self.assertEqual(result.added, 1)
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.pitch_delta[2], 1)
        self.assertEqual(result.timing_changed, 1)
        self.assertEqual(result.velocity_changed, 1)
        self.assertEqual(result.articulation_changed, 1)


if __name__ == "__main__":
    unittest.main()
