from __future__ import annotations

import unittest

import numpy as np

from bdo_music_composer.audio.native_audio_parity import compare_audio_blocks


class NativeAudioParityTests(unittest.TestCase):
    def test_exact_blocks_pass(self) -> None:
        block = np.arange(32, dtype=np.float32).reshape(16, 2) / 100.0
        result = compare_audio_blocks(block, block.copy())
        self.assertTrue(result.passed)
        self.assertEqual(result.reason, "passed")

    def test_shape_nonfinite_and_audio_mismatch_fail_closed(self) -> None:
        block = np.zeros((8, 2), dtype=np.float32)
        self.assertEqual(compare_audio_blocks(block, block[:, :1]).reason, "shape-mismatch")
        nonfinite = block.copy()
        nonfinite[0, 0] = np.nan
        self.assertEqual(compare_audio_blocks(block, nonfinite).reason, "non-finite")
        mismatch = block.copy()
        mismatch[0, 0] = 0.1
        self.assertEqual(compare_audio_blocks(block, mismatch).reason, "audio-mismatch")


if __name__ == "__main__":
    unittest.main()
