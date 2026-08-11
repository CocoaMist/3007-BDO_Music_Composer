from __future__ import annotations

import unittest

import numpy as np

from bdo_music_composer.audio.pcm_wav import (
    pcm_bytes_to_float32,
    stereo_pcm,
)


def _pcm24(values: tuple[int, ...]) -> bytes:
    payload = bytearray()
    for value in values:
        unsigned = int(value) & 0xFFFFFF
        payload.extend((
            unsigned & 0xFF,
            (unsigned >> 8) & 0xFF,
            (unsigned >> 16) & 0xFF,
        ))
    return bytes(payload)


class PcmWavTests(unittest.TestCase):
    def test_decodes_signed_24_bit_boundaries_and_stereo_frames(self) -> None:
        decoded = pcm_bytes_to_float32(
            _pcm24((-8388608, 8388607, 0, -4194304)),
            3,
            2,
        )
        self.assertEqual(decoded.shape, (2, 2))
        np.testing.assert_allclose(
            decoded,
            np.array(((-1.0, 8388607 / 8388608), (0.0, -0.5)), dtype=np.float32),
            atol=1e-7,
        )

    def test_mono_projection_duplicates_the_channel(self) -> None:
        decoded = pcm_bytes_to_float32(_pcm24((0, 4194304)), 3, 1)
        stereo = stereo_pcm(decoded)
        self.assertEqual(stereo.shape, (2, 2))
        np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])

    def test_rejects_unsupported_or_unaligned_pcm(self) -> None:
        with self.assertRaises(ValueError):
            pcm_bytes_to_float32(b"\0\0\0\0", 4, 1)
        with self.assertRaises(ValueError):
            pcm_bytes_to_float32(b"\0\0", 3, 1)


if __name__ == "__main__":
    unittest.main()
