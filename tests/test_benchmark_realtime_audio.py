from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication

from tools.benchmark_realtime_audio import (
    _actual_tracks,
    build_synthetic_engine,
    run_offline_benchmark,
)


APP = QCoreApplication.instance() or QCoreApplication([])


class RealtimeAudioBenchmarkTests(unittest.TestCase):
    def test_multitrack_game_workload_is_simultaneous_and_bounded(self) -> None:
        tracks = _actual_tracks(256, 3.0, "multitrack")
        notes = [note for track in tracks for note in track.notes]

        self.assertGreater(len(tracks), 16)
        self.assertEqual(len(notes), 256)
        self.assertTrue(all(note.start == 0 for note in notes))
        self.assertTrue(all(note.dur == 3_000 for note in notes))
        self.assertTrue(
            all(
                note.ntype == 99
                for track in tracks
                if track.bdo_instrument_id == 0x0D
                for note in track.notes
            )
        )

    def test_synthetic_offline_benchmark_uses_one_adaptive_producer(self) -> None:
        engine = build_synthetic_engine(128, 0.2, 36_000)
        try:
            result = run_offline_benchmark(engine, 0.2)
            output_thread = engine._output_thread
        finally:
            engine.stop()

        self.assertEqual(result["mode"], "offline")
        self.assertIsNone(output_thread)
        self.assertEqual(result["sample_rate"], 36_000)
        self.assertEqual(result["active_voices_peak"], 128)
        self.assertEqual(result["underruns"], 0)
        self.assertGreater(result["render_p95_ms"], 0.0)
        self.assertGreater(result["render_p95_load"], 0.0)
        self.assertGreater(result["render_p99_ms"], 0.0)
        self.assertEqual(result["render_block_frames"], 2_048)
        self.assertIn("2048", result["block_distribution"])
        self.assertEqual(result["buffer_frames"], 4_608)

    def test_low_latency_multisample_workload_uses_requested_quantum(self) -> None:
        engine = build_synthetic_engine(
            32,
            0.2,
            48_000,
            unique_samples=8,
        )
        try:
            result = run_offline_benchmark(
                engine,
                0.2,
                render_block_frames=256,
            )
            unique_samples = len({id(event.sample) for event in engine._events})
        finally:
            engine.stop()

        self.assertEqual(result["render_block_frames"], 256)
        self.assertIn("256", result["block_distribution"])
        self.assertEqual(unique_samples, 8)
        self.assertGreaterEqual(result["render_p999_ms"], result["render_p99_ms"])

    def test_synthetic_all_effects_workload_is_active_and_bounded(self) -> None:
        engine = build_synthetic_engine(
            64,
            0.2,
            36_000,
            effect_preview=True,
        )
        try:
            self.assertTrue(engine._preview_effects.active)
            self.assertTrue(engine._preview_effects.reverb_enabled)
            self.assertTrue(engine._preview_effects.delay_enabled)
            self.assertTrue(engine._preview_effects.chorus_enabled)
            self.assertTrue(all(event.reverb_send > 0.0 for event in engine._events))
            self.assertTrue(all(event.delay_send > 0.0 for event in engine._events))
            self.assertTrue(all(event.chorus_send > 0.0 for event in engine._events))

            result = run_offline_benchmark(engine, 0.2)
        finally:
            engine.stop()

        self.assertEqual(result["active_voices_peak"], 64)
        self.assertEqual(result["underruns"], 0)


if __name__ == "__main__":
    unittest.main()
