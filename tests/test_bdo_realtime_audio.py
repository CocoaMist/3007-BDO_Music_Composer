from __future__ import annotations

import unittest
import json
import tempfile
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QCoreApplication

from bdo_realtime_audio import (
    BdoRealtimeAudioEngine,
    _Event,
    _Sample,
    articulation_preview_envelope,
    bank_for_instrument,
    normalise_sample_loudness,
    resolve_bdo_pitch,
    select_wwise_zone,
    soft_limit_in_place,
)
from pyside_bdo_gui import BDO_ARTICULATIONS, BDO_EDITOR_PITCH_RANGES


APP = QCoreApplication.instance() or QCoreApplication([])


class RealtimeAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BdoRealtimeAudioEngine(None, {"paz_root": "", "audio_root": ""})
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

    def test_clear_playback_silences_without_destroying_output_state(self) -> None:
        sample = _Sample(np.ones((32, 2), dtype=np.float32), 48_000, 32)
        self.engine._events = [_Event(0, sample, 1.0, 0.5)]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._voices = [SimpleNamespace(sample=sample)]
        self.engine._playing = True
        self.engine._duration_frames = 32

        self.engine.clear_playback()

        self.assertFalse(self.engine._playing)
        self.assertEqual(self.engine._events, [])
        self.assertEqual(self.engine._voices, [])
        self.assertEqual(self.engine._duration_frames, 0)

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

    def test_preload_progress_is_reported(self) -> None:
        self.engine._preload_total = 8
        self.engine._preload_loaded = 3
        status = self.engine.get_status()
        self.assertEqual(status.preload_loaded, 3)
        self.assertEqual(status.preload_total, 8)
        self.assertAlmostEqual(status.preload_progress, 0.375)

    def test_cancel_loading_invalidates_future_and_resets_progress(self) -> None:
        future = Future()
        self.engine._load_future = future
        self.engine._load_generation = 7
        self.engine._preload_total = 8
        self.engine._preload_loaded = 3

        self.engine.cancel_loading()

        self.assertTrue(future.cancelled())
        self.assertEqual(self.engine._load_generation, 8)
        self.assertFalse(self.engine.is_loading())
        self.assertIsNone(self.engine.finish_loading(0.0))
        status = self.engine.get_status()
        self.assertEqual(status.preload_loaded, 0)
        self.assertEqual(status.preload_total, 0)
        self.assertEqual(status.preload_progress, 0.0)

    def test_sample_loudness_matching_reduces_source_level_difference(self) -> None:
        quiet = np.full((4096, 2), 0.02, dtype=np.float32)
        loud = np.full((4096, 2), 0.80, dtype=np.float32)
        quiet_matched, quiet_gain = normalise_sample_loudness(quiet)
        loud_matched, loud_gain = normalise_sample_loudness(loud)
        self.assertGreater(quiet_gain, 1.0)
        self.assertLess(loud_gain, 1.0)
        self.assertLess(float(np.max(np.abs(loud_matched))), 0.63)
        self.assertLess(
            abs(float(np.sqrt(np.mean(quiet_matched ** 2))) - float(np.sqrt(np.mean(loud_matched ** 2)))),
            0.04,
        )

    def test_soft_limiter_preserves_normal_audio_and_catches_hot_mix(self) -> None:
        audio = np.array([[-0.5, 0.5], [-2.0, 2.0]], dtype=np.float32)
        soft_limit_in_place(audio)
        self.assertTrue(np.allclose(audio[0], [-0.5, 0.5]))
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)
        self.assertGreater(float(audio[1, 1]), 0.82)

    def test_nonbasic_articulations_have_audible_preview_envelopes(self) -> None:
        ages = np.arange(48_000, dtype=np.float32)
        basic = articulation_preview_envelope(0x0A, 0, ages, 48_000, 48_000)
        for ntype in (1, 2, 3, 4, 12, 13, 15, 16, 20, 21, 22, 24, 25, 26, 27):
            processed = articulation_preview_envelope(0x0A, ntype, ages, 48_000, 48_000)
            self.assertFalse(np.allclose(processed, basic), f"ntype {ntype} fell back to basic")

    def test_harp_chord_articulation_starts_three_voices(self) -> None:
        sample = _Sample(np.ones((48_000, 2), dtype=np.float32), 48_000, 48_000)
        self.engine._start_event(_Event(0, sample, 1.0, 0.5, 24_000, 0x10, 9))
        self.assertEqual(len(self.engine._voices), 3)
        self.assertEqual(len({round(voice.ratio, 5) for voice in self.engine._voices}), 3)

    def test_every_declared_nonbasic_articulation_has_a_preview_route(self) -> None:
        ages = np.arange(4096, dtype=np.float32)
        basic_aliases = {(0x1C, 1), (0x20, 1)}
        event_routes = {9, 10, 14}
        for instrument_id, definitions in BDO_ARTICULATIONS.items():
            for ntype, _label in definitions:
                if ntype == 0 or (instrument_id, ntype) in basic_aliases or ntype in event_routes:
                    continue
                envelope = articulation_preview_envelope(
                    instrument_id, ntype, ages, 4096, 48_000
                )
                self.assertFalse(
                    np.allclose(envelope, 1.0),
                    f"0x{instrument_id:02x}/type {ntype} has no preview processing",
                )


if __name__ == "__main__":
    unittest.main()
