from __future__ import annotations

import unittest

import numpy as np

from bdo_music_composer.audio.bdo_spectrogram import (
    SpectrogramCancelled,
    choose_fft_size,
    midi_spectrogram,
    spectrogram_column_count,
)


class SpectrogramTransformTests(unittest.TestCase):
    def test_sine_energy_peaks_at_matching_midi_pitch(self) -> None:
        sample_rate = 22_050
        times = np.arange(sample_rate, dtype=np.float32) / sample_rate
        samples = 0.5 * np.sin(2.0 * np.pi * 440.0 * times)
        matrix = midi_spectrogram(
            samples,
            sample_rate,
            pitch_min=48,
            pitch_max=84,
            output_columns=50,
        )

        self.assertEqual(matrix.shape, (50, 37))
        self.assertEqual(int(np.argmax(np.mean(matrix, axis=0))) + 48, 69)
        self.assertGreater(float(np.mean(matrix[:, 69 - 48])), 0.80)
        self.assertTrue(np.all(np.isfinite(matrix)))
        self.assertGreaterEqual(float(np.min(matrix)), 0.0)
        self.assertLessEqual(float(np.max(matrix)), 1.0)

    def test_silence_nonfinite_values_and_empty_input_are_bounded(self) -> None:
        samples = np.zeros(2_205, dtype=np.float32)
        samples[10:13] = (np.nan, np.inf, -np.inf)
        matrix = midi_spectrogram(
            samples,
            22_050,
            pitch_min=60,
            pitch_max=72,
            output_columns=8,
        )
        self.assertEqual(matrix.shape, (8, 13))
        self.assertTrue(np.all(matrix == 0.0))

        empty = midi_spectrogram(
            np.zeros(0, dtype=np.float32),
            22_050,
            pitch_min=72,
            pitch_max=60,
            output_columns=0,
        )
        self.assertEqual(empty.shape, (1, 1))

    def test_resolution_is_source_and_viewport_bounded(self) -> None:
        self.assertEqual(spectrogram_column_count(5_000.0, 0.001), 5)
        self.assertEqual(spectrogram_column_count(5_000.0, 1.0), 250)
        self.assertEqual(
            spectrogram_column_count(
                5_000.0,
                1.0,
                maximum_columns=120,
            ),
            120,
        )
        self.assertEqual(choose_fft_size(22_050), 1_024)
        self.assertEqual(choose_fft_size(44_100), 2_048)
        self.assertLessEqual(choose_fft_size(192_000), 4_096)

    def test_cancellation_is_checked_before_fft_work(self) -> None:
        with self.assertRaises(SpectrogramCancelled):
            midi_spectrogram(
                np.ones(22_050, dtype=np.float32),
                22_050,
                pitch_min=48,
                pitch_max=84,
                output_columns=250,
                cancel_requested=lambda: True,
            )


if __name__ == "__main__":
    unittest.main()
