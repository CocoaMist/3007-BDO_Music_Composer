from __future__ import annotations

import unittest

import numpy as np

from bdo_music_composer.audio.bdo_audio_lifecycle import (
    InstanceTimelineItem,
    decide_instance_limit,
    detect_active_signal_frames,
    milliseconds_to_frames,
    plan_instance_timeline,
    voice_lifecycle,
)


class AudioLifecycleTests(unittest.TestCase):
    RATE = 48_000

    def lifecycle(
        self,
        instrument_id: int,
        *,
        ntype: int = 0,
        note_ms: float = 250.0,
        signal_ms: float = 10_000.0,
        **policy,
    ):
        return voice_lifecycle(
            instrument_id,
            ntype,
            milliseconds_to_frames(note_ms, self.RATE),
            milliseconds_to_frames(signal_ms, self.RATE),
            self.RATE,
            **policy,
        )

    def test_gated_families_end_at_formal_note(self) -> None:
        for instrument_id in (0x01, 0x08, 0x0E, 0x0F, 0x12, 0x14, 0x20):
            with self.subTest(instrument_id=instrument_id):
                lifecycle = self.lifecycle(instrument_id, note_ms=100.0)
                self.assertEqual(lifecycle.audible_frames, 4_800)
                self.assertEqual(lifecycle.fade_out_frames, 576)

    def test_natural_tail_caps_are_family_specific(self) -> None:
        expected_ms = {
            0x00: 1_050.0,
            0x06: 1_050.0,
            0x07: 1_450.0,
            0x04: 850.0,
            0x0D: 850.0,
            0x13: 1_450.0,
            0x05: 2_750.0,
        }
        for instrument_id, audible_ms in expected_ms.items():
            with self.subTest(instrument_id=instrument_id):
                lifecycle = self.lifecycle(instrument_id)
                self.assertEqual(
                    lifecycle.audible_frames,
                    milliseconds_to_frames(audible_ms, self.RATE),
                )

    def test_piano_pedal_tail_is_bounded_to_2500_ms(self) -> None:
        lifecycle = self.lifecycle(0x11, ntype=11)
        self.assertEqual(
            lifecycle.audible_frames,
            milliseconds_to_frames(2_750.0, self.RATE),
        )

    def test_short_articulations_override_family_tail_without_extending_note(self) -> None:
        expected_ms = {2: 87.5, 13: 137.5, 22: 220.0, 24: 100.0}
        for ntype, audible_ms in expected_ms.items():
            with self.subTest(ntype=ntype):
                lifecycle = self.lifecycle(0x07, ntype=ntype)
                self.assertEqual(
                    lifecycle.audible_frames,
                    milliseconds_to_frames(audible_ms, self.RATE),
                )
        very_short = self.lifecycle(0x07, ntype=2, note_ms=20.0)
        self.assertEqual(
            very_short.audible_frames,
            milliseconds_to_frames(20.0, self.RATE),
        )

    def test_type_one_does_not_shorten_note_or_natural_tail(self) -> None:
        self.assertEqual(
            self.lifecycle(0x0A, ntype=1).audible_frames,
            self.lifecycle(0x0A, ntype=0).audible_frames,
        )

    def test_actual_signal_endpoint_caps_every_policy(self) -> None:
        lifecycle = self.lifecycle(0x05, signal_ms=320.0)
        self.assertEqual(
            lifecycle.audible_frames,
            milliseconds_to_frames(320.0, self.RATE),
        )

    def test_native_one_shot_uses_note_off_release_not_legacy_guesses(
        self,
    ) -> None:
        legacy = self.lifecycle(
            0x07,
            ntype=13,
            note_ms=250.0,
            signal_ms=400.0,
        )
        native = self.lifecycle(
            0x07,
            ntype=13,
            note_ms=250.0,
            signal_ms=400.0,
            native_articulation=True,
            release_ms=80.0,
        )
        self.assertEqual(
            legacy.audible_frames,
            milliseconds_to_frames(137.5, self.RATE),
        )
        self.assertEqual(
            native.audible_frames,
            milliseconds_to_frames(330.0, self.RATE),
        )

        native_guitar = self.lifecycle(
            0x0A,
            note_ms=100.0,
            signal_ms=320.0,
            native_articulation=True,
            release_ms=79.0,
        )
        self.assertEqual(
            native_guitar.audible_frames,
            milliseconds_to_frames(179.0, self.RATE),
        )

    def test_loop_source_follows_note_plus_release_beyond_file_length(
        self,
    ) -> None:
        lifecycle = self.lifecycle(
            0x01,
            note_ms=250.0,
            signal_ms=40.0,
            native_articulation=True,
            sample_loops=True,
            release_ms=80.0,
        )
        self.assertEqual(
            lifecycle.audible_frames,
            milliseconds_to_frames(330.0, self.RATE),
        )
        self.assertEqual(
            lifecycle.fade_out_frames,
            milliseconds_to_frames(80.0, self.RATE),
        )

    def test_zero_loop_release_keeps_click_safe_boundary_fade(self) -> None:
        lifecycle = self.lifecycle(
            0x01,
            note_ms=100.0,
            signal_ms=40.0,
            sample_loops=True,
            release_ms=0.0,
        )
        self.assertEqual(
            lifecycle.audible_frames,
            milliseconds_to_frames(100.0, self.RATE),
        )
        self.assertEqual(
            lifecycle.fade_out_frames,
            milliseconds_to_frames(12.0, self.RATE),
        )

    def test_active_signal_endpoint_ignores_trailing_silence_and_nan(self) -> None:
        pcm = np.zeros((4_800, 2), dtype=np.float32)
        pcm[:1_200] = 0.4
        pcm[2_000, 0] = np.nan
        self.assertEqual(
            detect_active_signal_frames(pcm, self.RATE),
            1_200 + milliseconds_to_frames(20.0, self.RATE),
        )

    def test_instance_decision_discards_oldest_or_rejects_newest(self) -> None:
        oldest = decide_instance_limit([10, 20, 30], 3, False)
        self.assertTrue(oldest.accept_new)
        self.assertEqual(oldest.victim_indices, (0,))
        newest = decide_instance_limit([10, 20, 30], 3, True)
        self.assertFalse(newest.accept_new)
        self.assertEqual(newest.victim_indices, ())

    def test_instance_timeline_releases_oldest_without_consuming_capacity(
        self,
    ) -> None:
        plan = plan_instance_timeline(
            [
                InstanceTimelineItem(0, 100, 7, 1, 1, False),
                InstanceTimelineItem(10, 100, 7, 1, 1, False),
                InstanceTimelineItem(10, 100, 7, 1, 1, False),
            ],
            release_frames=4,
        )
        self.assertEqual(plan.accepted, (True, True, True))
        self.assertEqual(plan.audible_frames, (14, 4, 100))
        self.assertEqual(plan.forced_release, (True, True, False))

    def test_instance_timeline_keeps_per_object_scopes_independent(self) -> None:
        plan = plan_instance_timeline(
            [
                InstanceTimelineItem(0, 100, 7, 101, 1, False),
                InstanceTimelineItem(10, 100, 7, 202, 1, False),
            ],
            release_frames=4,
        )
        self.assertEqual(plan.accepted, (True, True))
        self.assertEqual(plan.audible_frames, (100, 100))
        self.assertEqual(plan.forced_release, (False, False))


if __name__ == "__main__":
    unittest.main()
