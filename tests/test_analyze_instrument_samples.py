from __future__ import annotations

import unittest

import numpy as np

from tools.analyze_instrument_samples import estimate_pitch


class InstrumentSamplePitchAnalysisTests(unittest.TestCase):
    sample_rate = 36_000

    def _tone(self, frequency: float, harmonics: tuple[float, ...]) -> np.ndarray:
        time = np.arange(
            round(self.sample_rate * 1.2),
            dtype=np.float64,
        ) / self.sample_rate
        signal = sum(
            amplitude
            * np.sin(2.0 * np.pi * frequency * index * time)
            for index, amplitude in enumerate(harmonics, start=1)
        )
        return np.asarray(signal, dtype=np.float32)

    def test_pure_tone_does_not_select_near_zero_lag_shoulder(self) -> None:
        frequency, confidence = estimate_pitch(
            self._tone(220.0, (1.0,)),
            self.sample_rate,
        )

        self.assertAlmostEqual(frequency or 0.0, 220.0, delta=2.0)
        self.assertGreater(confidence, 0.9)

    def test_bright_harmonic_tone_keeps_its_fundamental_period(self) -> None:
        frequency, confidence = estimate_pitch(
            self._tone(220.0, (0.2, 1.0, 0.4)),
            self.sample_rate,
        )

        self.assertAlmostEqual(frequency or 0.0, 220.0, delta=2.0)
        self.assertGreater(confidence, 0.9)


if __name__ == "__main__":
    unittest.main()
