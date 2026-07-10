from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QCoreApplication

from bdo_realtime_audio import (
    BdoRealtimeAudioEngine,
    _Event,
    _Sample,
    bank_for_instrument,
    resolve_bdo_pitch,
    select_wwise_zone,
)
from pyside_bdo_gui import BDO_EDITOR_PITCH_RANGES


APP = QCoreApplication.instance() or QCoreApplication([])


class RealtimeAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BdoRealtimeAudioEngine(None, {"paz_root": r"F:\缓存\Paz", "audio_root": r"F:\缓存\BDO音源"})
        self.engine._sample_rate = 48_000

    def test_event_is_mixed_at_its_exact_frame(self) -> None:
        sample = _Sample(np.ones((128, 2), dtype=np.float32), 48_000, 128)
        self.engine._events = [_Event(5, sample, 1.0, 0.5)]
        self.engine._duration_frames = 133
        self.engine._playing = True
        rendered = self.engine._render_locked(16)
        self.assertTrue(np.allclose(rendered[:5], 0.0))
        self.assertGreater(float(rendered[5:, 0].max()), 0.49)
        self.assertEqual(self.engine._frame, 16)

    def test_seek_restores_an_active_voice_without_disk_io(self) -> None:
        sample = _Sample(np.ones((128, 2), dtype=np.float32), 48_000, 128)
        self.engine._events = [_Event(0, sample, 1.0, 1.0)]
        self.engine._seek_locked(32)
        self.assertEqual(len(self.engine._voices), 1)
        self.assertEqual(self.engine._voices[0].position, 32.0)

    def test_voice_pool_is_capped_at_256(self) -> None:
        sample = _Sample(np.ones((4, 2), dtype=np.float32), 48_000, 4)
        for _ in range(300):
            self.engine._start_voice(sample, 0.0, 1.0, 1.0)
        self.assertEqual(len(self.engine._voices), 256)

    def test_interpolation_at_float_sample_tail_does_not_read_past_pcm(self) -> None:
        sample = _Sample(np.ones((4, 2), dtype=np.float32), 48_000, 4)
        voice = SimpleNamespace(sample=sample, position=3.0 - 1e-10, ratio=1.0, gain=1.0)
        self.engine._ensure_render_buffers(4)
        output = np.zeros((4, 2), dtype=np.float32)
        self.engine._mix_single_voice(output, 4, voice)
        self.assertTrue(np.isfinite(output).all())

    def test_canonical_game_drum_keys_are_not_remapped_as_gm(self) -> None:
        self.assertEqual(resolve_bdo_pitch(0x0D, 48, 99), 48)
        self.assertEqual(resolve_bdo_pitch(0x0D, 64, 99), 64)
        self.assertEqual(resolve_bdo_pitch(0x0D, 48, 0), 60)

    def test_marnian_modes_route_to_the_selected_synth_bank(self) -> None:
        self.assertEqual(bank_for_instrument(0x14), "midi_instrument_synth_saw_basic")
        self.assertEqual(bank_for_instrument(0x14, "stereo"), "midi_instrument_synth_saw_stereo")
        self.assertEqual(bank_for_instrument(0x20, "superoct"), "midi_instrument_synth_triangle_superoct")
        banks = {
            "midi_instrument_synth_saw_super": [{
                "wav_exists": True, "key_min": 12, "key_max": 107,
                "velocity_min": 0, "velocity_max": 127, "root_note": 60, "source_id": 1,
            }]
        }
        selected = select_wwise_zone(banks, 0x14, 60, 100, synth_mode="super")
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], "midi_instrument_synth_saw_super")

    def test_hand_authored_game_ranges_are_enforced(self) -> None:
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x0A]), max(BDO_EDITOR_PITCH_RANGES[0x0A])), (36, 88))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x0E]), max(BDO_EDITOR_PITCH_RANGES[0x0E])), (28, 64))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x0F]), max(BDO_EDITOR_PITCH_RANGES[0x0F])), (28, 64))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x12]), max(BDO_EDITOR_PITCH_RANGES[0x12])), (43, 88))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x13]), max(BDO_EDITOR_PITCH_RANGES[0x13])), (45, 88))

    def test_project_preload_deduplicates_sources_before_parallel_decode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wav_path = root / "sample.wav"
            wav_path.touch()
            map_path = root / "map.json"
            bank = "midi_instrument_10_proguitar"
            map_path.write_text(json.dumps({"banks": {bank: [{
                "wav_exists": True, "wav_path": str(wav_path), "source_id": 7,
                "key_min": 0, "key_max": 127, "velocity_min": 0,
                "velocity_max": 127, "root_note": 60,
            }]}}), encoding="utf-8")
            calls = []
            original = self.engine._decode_wav
            self.engine._decode_wav = lambda path: (calls.append(path), _Sample(np.ones((8, 2), dtype=np.float32), 48_000, 8))[1]
            try:
                track = SimpleNamespace(
                    bdo_instrument_id=0x0A, marnian_synth_mode="basic", volume_scale=1.0,
                    articulation_type=None,
                    notes=[SimpleNamespace(pitch=60, vel=90, start=0, ntype=0),
                           SimpleNamespace(pitch=64, vel=90, start=100, ntype=0)],
                )
                events, cache, _bytes, _unverified, _duration = self.engine._prepare_project(
                    [track], map_path, 0, 0, 0, None, 1024 * 1024
                )
            finally:
                self.engine._decode_wav = original
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(cache), 1)
            self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
