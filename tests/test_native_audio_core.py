from __future__ import annotations

import unittest

import numpy as np

from bdo_music_composer.audio.bdo_realtime_audio import (
    BdoRealtimeAudioEngine,
    _Event,
    _Sample,
)
from bdo_music_composer.audio.bdo_audio_mixing import (
    apply_articulation_preview_in_place,
)
from bdo_music_composer.audio.native_audio_core import (
    NativeAudioCore,
    NativeAudioCoreError,
    NativePlaybackEventV1,
    native_audio_core_available,
    REQUIRED_NATIVE_AUDIO_CAPABILITIES,
)
from bdo_music_composer.audio.native_audio_parity import compare_audio_blocks


@unittest.skipUnless(
    native_audio_core_available(),
    "optional native audio core has not been built",
)
class NativeAudioCoreTests(unittest.TestCase):
    def test_abi_capabilities_are_explicit(self) -> None:
        with NativeAudioCore(48_000) as core:
            self.assertEqual(
                core.capabilities & REQUIRED_NATIVE_AUDIO_CAPABILITIES,
                REQUIRED_NATIVE_AUDIO_CAPABILITIES,
            )

    def test_steady_basic_mix_matches_python_reference(self) -> None:
        sample = np.column_stack((
            np.linspace(0.0, 0.05, 2_048, dtype=np.float32),
            np.linspace(0.05, 0.0, 2_048, dtype=np.float32),
        ))
        python_sample = _Sample(sample, 48_000, len(sample))
        python_event = _Event(
            0,
            python_sample,
            1.0,
            0.2,
            1_500,
            audible_frames=1_500,
            fade_out_frames=0,
        )
        engine = BdoRealtimeAudioEngine(
            None,
            {"paz_root": "", "audio_root": ""},
        )
        try:
            with engine._lock:
                engine._sample_rate = 48_000
                engine._events = [python_event]
                engine._event_frames = np.asarray([0], dtype=np.int64)
                engine._duration_frames = 1_500
                engine._playing = True
                engine._track_meter_ids = []
                engine._track_peaks = np.zeros(0, dtype=np.float32)
                engine._track_block_peaks = np.zeros(0, dtype=np.float32)
                engine._ensure_render_buffers(1_024)
                engine._render_locked(512)  # consume the production fade-in
                expected = engine._render_locked(512).copy()
        finally:
            engine.stop()

        with NativeAudioCore(48_000) as core:
            core.load_plan(
                [sample],
                [NativePlaybackEventV1(0, 0, 1.0, 0.2, 1_500)],
            )
            core.render(512)
            actual = core.render(512)

        self.assertTrue(np.array_equal(actual, expected))

    def test_prepared_event_projection_is_explicit_and_fails_closed(self) -> None:
        sample = _Sample(np.ones((32, 2), dtype=np.float32), 48_000, 32)
        basic = _Event(0, sample, 1.0, 0.25, 16, audible_frames=16)
        effected = _Event(
            0,
            sample,
            1.0,
            0.25,
            16,
            audible_frames=16,
            reverb_send=0.5,
        )
        with NativeAudioCore(48_000) as core:
            core.load_prepared_events([basic])
            self.assertEqual(core.render(1)[0, 0], 0.25)
            with self.assertRaises(NativeAudioCoreError):
                core.load_prepared_events([effected])

    def test_prepared_event_attack_and_release_match_python_lifecycle(self) -> None:
        pcm = np.ones((64, 2), dtype=np.float32)
        sample = _Sample(pcm, 48_000, len(pcm))
        event = _Event(
            0,
            sample,
            1.0,
            0.2,
            16,
            audible_frames=16,
            fade_out_frames=4,
        )
        engine = BdoRealtimeAudioEngine(
            None,
            {"paz_root": "", "audio_root": ""},
        )
        try:
            with engine._lock:
                engine._sample_rate = 48_000
                engine._events = []
                engine._event_frames = np.zeros(0, dtype=np.int64)
                engine._duration_frames = 20
                engine._playing = True
                engine._track_meter_ids = []
                engine._track_peaks = np.zeros(0, dtype=np.float32)
                engine._track_block_peaks = np.zeros(0, dtype=np.float32)
                engine._ensure_render_buffers(32)
                engine._start_voice(
                    sample,
                    0.0,
                    1.0,
                    0.2,
                    duration_frames=16,
                    fade_in_frames=4,
                    audible_frames=16,
                    fade_out_frames=4,
                )
                expected = engine._render_locked(20).copy()
        finally:
            engine.stop()

        with NativeAudioCore(48_000) as core:
            core.load_prepared_events([event], fade_in_frames=4)
            actual = core.render(20)
            core.seek(14)
            resumed = core.render(6)

        parity = compare_audio_blocks(expected, actual)
        self.assertTrue(parity.passed, parity)
        self.assertAlmostEqual(float(actual[0, 0]), 0.05, places=6)
        self.assertAlmostEqual(float(actual[15, 0]), 0.0, places=6)
        self.assertTrue(np.array_equal(actual[16:], np.zeros((4, 2), dtype=np.float32)))
        resumed_parity = compare_audio_blocks(expected[14:20], resumed)
        self.assertTrue(resumed_parity.passed, resumed_parity)

    def test_prepared_articulation_envelope_matches_python_renderer(self) -> None:
        pcm = np.full((128, 2), 0.25, dtype=np.float32)
        sample = _Sample(pcm, 48_000, len(pcm))
        event = _Event(
            0,
            sample,
            1.0,
            0.2,
            64,
            audible_frames=64,
            instrument_id=0x0B,
            ntype=12,
        )
        engine = BdoRealtimeAudioEngine(
            None,
            {"paz_root": "", "audio_root": ""},
        )
        try:
            with engine._lock:
                engine._sample_rate = 48_000
                engine._events = []
                engine._event_frames = np.zeros(0, dtype=np.int64)
                engine._duration_frames = 64
                engine._playing = True
                engine._track_meter_ids = []
                engine._track_peaks = np.zeros(0, dtype=np.float32)
                engine._track_block_peaks = np.zeros(0, dtype=np.float32)
                engine._ensure_render_buffers(64)
                engine._start_voice(
                    sample,
                    0.0,
                    1.0,
                    0.2,
                    duration_frames=64,
                    instrument_id=0x0B,
                    ntype=12,
                    audible_frames=64,
                )
                expected = engine._render_locked(64).copy()
        finally:
            engine.stop()

        with NativeAudioCore(48_000) as core:
            core.load_prepared_events([event])
            actual = core.render(64)

        parity = compare_audio_blocks(expected, actual)
        self.assertTrue(parity.passed, parity)

    def test_all_fallback_articulation_envelopes_match_python(self) -> None:
        pcm = np.full((128, 2), 0.25, dtype=np.float32)
        sample = _Sample(pcm, 48_000, len(pcm))
        ages = np.arange(64, dtype=np.float32)
        for ntype in tuple(range(1, 29)):
            with self.subTest(ntype=ntype):
                expected = np.full((64, 2), 0.05, dtype=np.float32)
                apply_articulation_preview_in_place(
                    expected,
                    0x0B,
                    ntype,
                    ages,
                    64,
                    48_000,
                )
                event = _Event(
                    0,
                    sample,
                    1.0,
                    0.2,
                    64,
                    audible_frames=64,
                    instrument_id=0x0B,
                    ntype=ntype,
                )
                with NativeAudioCore(48_000) as core:
                    core.load_prepared_events([event])
                    actual = core.render(64)
                parity = compare_audio_blocks(
                    expected,
                    actual,
                    max_absolute_error=2.0e-6,
                    max_rms_error=2.0e-7,
                )
                self.assertTrue(parity.passed, parity)

    def test_master_headroom_and_soft_limiter_match_python(self) -> None:
        pcm = np.full((256, 2), 0.75, dtype=np.float32)
        sample = _Sample(pcm, 48_000, len(pcm))
        engine = BdoRealtimeAudioEngine(None, {"paz_root": "", "audio_root": ""})
        try:
            with engine._lock:
                engine._sample_rate = 48_000
                engine._events = []
                engine._event_frames = np.zeros(0, dtype=np.int64)
                engine._duration_frames = 128
                engine._playing = True
                engine._track_meter_ids = []
                engine._track_peaks = np.zeros(0, dtype=np.float32)
                engine._track_block_peaks = np.zeros(0, dtype=np.float32)
                engine._ensure_render_buffers(128)
                engine._start_voice(sample, 0.0, 1.0, 2.0, duration_frames=128, audible_frames=128)
                expected = engine._render_locked(128).copy()
        finally:
            engine.stop()

        with NativeAudioCore(48_000) as core:
            core.load_plan(
                [pcm],
                [NativePlaybackEventV1(0, 0, 1.0, 2.0, 128)],
            )
            actual = core.render(128)

        parity = compare_audio_blocks(expected, actual)
        self.assertTrue(parity.passed, parity)
        self.assertLessEqual(float(np.max(np.abs(actual))), 1.0)

    def test_exact_frame_start_linear_mix_and_seek(self) -> None:
        sample = np.column_stack((
            np.linspace(0.0, 1.0, 16, dtype=np.float32),
            np.linspace(1.0, 0.0, 16, dtype=np.float32),
        ))
        with NativeAudioCore(48_000, max_voices=8) as core:
            core.load_plan(
                [sample],
                [NativePlaybackEventV1(3, 0, 1.0, 0.5, 8)],
            )
            rendered = core.render(12)
            self.assertTrue(np.allclose(rendered[:3], 0.0))
            self.assertTrue(np.allclose(rendered[3:11], sample[:8] * 0.5))
            self.assertEqual(core.position_frame, 12)

            core.seek(6)
            resumed = core.render(3)
            self.assertTrue(np.allclose(resumed, sample[3:6] * 0.5))

    def test_voice_pool_is_bounded_and_reports_steals(self) -> None:
        sample = np.ones((32, 2), dtype=np.float32)
        events = [
            NativePlaybackEventV1(0, 0, 1.0, 0.01, 16)
            for _ in range(10)
        ]
        with NativeAudioCore(48_000, max_voices=4) as core:
            core.load_plan([sample], events)
            core.render(1)
            self.assertEqual(core.active_voices, 4)
            self.assertEqual(core.voice_steals, 6)

    def test_looping_is_deterministic_across_blocks(self) -> None:
        # Keep this transport invariant below the master-protection threshold;
        # high-level blocks intentionally follow the production block limiter.
        sample = np.arange(12, dtype=np.float32).reshape(6, 2) * 0.01
        event = NativePlaybackEventV1(0, 0, 1.0, 1.0, 8, 1, 4)
        with NativeAudioCore(48_000) as whole, NativeAudioCore(48_000) as split:
            whole.load_plan([sample], [event])
            split.load_plan([sample], [event])
            expected = whole.render(8)
            actual = np.vstack((split.render(3), split.render(5)))
            self.assertTrue(np.array_equal(actual, expected))


if __name__ == "__main__":
    unittest.main()
