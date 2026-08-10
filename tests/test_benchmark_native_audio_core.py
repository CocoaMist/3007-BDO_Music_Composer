from __future__ import annotations

import unittest

from bdo_music_composer.audio.native_audio_core import native_audio_core_available
from tools.benchmark_native_audio_core import benchmark_native_audio_core


@unittest.skipUnless(native_audio_core_available(), "native audio core not built")
class NativeAudioCoreBenchmarkTests(unittest.TestCase):
    def test_small_workload_reports_low_latency_distribution(self) -> None:
        result = benchmark_native_audio_core(
            voices=16,
            unique_samples=4,
            sample_rate=48_000,
            block_frames=128,
            blocks=8,
        )

        self.assertEqual(result["voices"], 16)
        self.assertEqual(result["unique_samples"], 4)
        self.assertEqual(result["block_frames"], 128)
        self.assertGreater(result["render_p99_ms"], 0.0)
        self.assertGreaterEqual(result["render_p999_ms"], result["render_p99_ms"])


if __name__ == "__main__":
    unittest.main()
