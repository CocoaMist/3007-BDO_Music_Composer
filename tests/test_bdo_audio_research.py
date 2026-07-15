from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np

from bdo_audio_research import compare_audio, sample_coverage_for_tracks


Note = namedtuple("Note", "pitch vel start dur ntype")


@dataclass
class Track:
    bdo_instrument_id: int
    notes: list
    volume_scale: float = 1.0


def write_wav(path: Path, signal: np.ndarray, rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(np.clip(signal * 32767, -32768, 32767).astype("<i2").tobytes())


class BdoAudioResearchTests(unittest.TestCase):
    def test_sample_coverage_reports_missing_note_indices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "map.json"
            mapping.write_text(json.dumps({"banks": {
                "midi_instrument_11_proflute": [{
                    "wav_exists": True, "key_min": 60, "key_max": 60,
                    "velocity_min": 1, "velocity_max": 127, "root_note": 60,
                    "source_id": 1, "wav_path": "unused.wav",
                }]
            }}), encoding="utf-8")
            track = Track(11, [Note(60, 80, 0, 100, 0), Note(61, 80, 100, 100, 0)])
            coverage = sample_coverage_for_tracks([track], mapping)[0]
            self.assertEqual(coverage.covered_notes, 1)
            self.assertEqual(coverage.missing_note_indices, (1,))

    def test_audio_alignment_returns_measurements_without_storing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal = np.zeros(1000, dtype=np.float32)
            signal[100:300] = 0.5
            write_wav(root / "a.wav", signal)
            write_wav(root / "b.wav", np.concatenate((np.zeros(10, dtype=np.float32), signal[:-10])))
            report = compare_audio(root / "a.wav", root / "b.wav")
            self.assertEqual(report.sample_rate, 8000)
            self.assertIsInstance(report.alignment_frames, int)
            self.assertFalse(hasattr(report, "reference_path"))


if __name__ == "__main__":
    unittest.main()
