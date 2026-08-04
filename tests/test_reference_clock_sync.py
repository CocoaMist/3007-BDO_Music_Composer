from __future__ import annotations

import unittest

from bdo_music_composer.audio.reference_clock_sync import (
    REFERENCE_CLOCK_HARD_DRIFT_MS,
    REFERENCE_CLOCK_SOFT_DRIFT_MS,
    reference_clock_decision,
)


class ReferenceClockSyncTests(unittest.TestCase):
    def decision(self, **changes: object):
        values: dict[str, object] = {
            "master_project_ms": 5_000.0,
            "reference_project_ms": 5_000.0,
            "reference_audio_ms": 5_000.0,
            "reference_duration_ms": 10_000.0,
            "reference_is_playing": True,
            "want_playback": True,
            "force_seek": False,
            "now_seconds": 10.0,
            "last_resync_seconds": 0.0,
        }
        values.update(changes)
        return reference_clock_decision(**values)

    def test_playing_reference_is_resynchronized_to_master_clock(self) -> None:
        lag = REFERENCE_CLOCK_SOFT_DRIFT_MS + 1.0
        decision = self.decision(reference_project_ms=5_000.0 - lag)
        self.assertTrue(decision.seek)
        self.assertAlmostEqual(decision.drift_ms, -lag)

    def test_small_jitter_does_not_cause_repeated_seeks(self) -> None:
        decision = self.decision(
            reference_project_ms=5_000.0
            + REFERENCE_CLOCK_SOFT_DRIFT_MS
            - 1.0,
        )
        self.assertFalse(decision.seek)

    def test_hard_drift_bypasses_resync_cooldown(self) -> None:
        decision = self.decision(
            reference_project_ms=(
                5_000.0 - REFERENCE_CLOCK_HARD_DRIFT_MS - 1.0
            ),
            now_seconds=10.0,
            last_resync_seconds=9.99,
        )
        self.assertTrue(decision.seek)

    def test_reference_outside_content_range_is_paused(self) -> None:
        decision = self.decision(
            master_project_ms=12_000.0,
            reference_project_ms=10_000.0,
            reference_audio_ms=12_000.0,
        )
        self.assertFalse(decision.inside_reference)
        self.assertTrue(decision.pause)
        self.assertFalse(decision.play)
        self.assertFalse(decision.seek)

    def test_stopped_reference_seeks_and_starts_from_master(self) -> None:
        decision = self.decision(
            reference_project_ms=4_000.0,
            reference_is_playing=False,
        )
        self.assertTrue(decision.seek)
        self.assertTrue(decision.play)


if __name__ == "__main__":
    unittest.main()
