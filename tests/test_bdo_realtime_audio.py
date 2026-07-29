from __future__ import annotations

import unittest
import json
import tempfile
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtMultimedia import QAudioFormat

from bdo_audio_lifecycle import (
    sample_output_frames,
    voice_lifecycle,
)
from bdo_preview_effects import PreviewEffectSettings
from bdo_realtime_audio import (
    AudioEngineError,
    BdoRealtimeAudioEngine,
    _AudioOutputWorker,
    _Event,
    _LoadCancelled,
    _Sample,
    articulation_preview_envelope,
    bank_for_instrument,
    choose_output_audio_format,
    normalise_sample_loudness,
    resolve_bdo_pitch,
    select_wwise_zone,
    select_wwise_zone_variants,
    soft_limit_in_place,
)
from pyside_bdo_gui import BDO_ARTICULATIONS, BDO_EDITOR_PITCH_RANGES


APP = QCoreApplication.instance() or QCoreApplication([])


class RealtimeAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BdoRealtimeAudioEngine(None, {"paz_root": "", "audio_root": ""})
        self.engine._sample_rate = 48_000

    def tearDown(self) -> None:
        self.engine.stop()

    @staticmethod
    def audio_format(
        sample_rate: int,
        channels: int = 2,
        sample_format: QAudioFormat.SampleFormat = QAudioFormat.SampleFormat.Int16,
    ) -> QAudioFormat:
        audio_format = QAudioFormat()
        audio_format.setSampleRate(sample_rate)
        audio_format.setChannelCount(channels)
        audio_format.setSampleFormat(sample_format)
        return audio_format

    def test_output_format_prefers_native_36khz_int16(self) -> None:
        preferred = self.audio_format(
            96_000,
            sample_format=QAudioFormat.SampleFormat.Float,
        )

        class Device:
            def isFormatSupported(self, audio_format: QAudioFormat) -> bool:
                return audio_format.sampleRate() in {36_000, 48_000}

            def preferredFormat(self) -> QAudioFormat:
                return preferred

        selected = choose_output_audio_format(Device())
        self.assertEqual(selected.sampleRate(), 36_000)
        self.assertEqual(selected.channelCount(), 2)
        self.assertEqual(
            selected.sampleFormat(),
            QAudioFormat.SampleFormat.Int16,
        )

    def test_output_format_falls_back_to_48khz_int16(self) -> None:
        preferred = self.audio_format(96_000)

        class Device:
            def isFormatSupported(self, audio_format: QAudioFormat) -> bool:
                return audio_format.sampleRate() == 48_000

            def preferredFormat(self) -> QAudioFormat:
                return preferred

        selected = choose_output_audio_format(Device())
        self.assertEqual(selected.sampleRate(), 48_000)
        self.assertEqual(
            selected.sampleFormat(),
            QAudioFormat.SampleFormat.Int16,
        )

    def test_output_format_accepts_valid_preferred_format_last(self) -> None:
        preferred = self.audio_format(
            96_000,
            sample_format=QAudioFormat.SampleFormat.Float,
        )

        class Device:
            def isFormatSupported(self, _audio_format: QAudioFormat) -> bool:
                return False

            def preferredFormat(self) -> QAudioFormat:
                return preferred

        selected = choose_output_audio_format(Device())
        self.assertIs(selected, preferred)
        self.assertEqual(selected.sampleRate(), 96_000)

    def test_output_format_rejects_invalid_preferred_format(self) -> None:
        preferred_formats = (
            self.audio_format(96_000, channels=1),
            self.audio_format(
                96_000,
                sample_format=QAudioFormat.SampleFormat.Int32,
            ),
        )
        for preferred in preferred_formats:
            with self.subTest(
                channels=preferred.channelCount(),
                sample_format=preferred.sampleFormat(),
            ):
                class Device:
                    def isFormatSupported(
                        self,
                        _audio_format: QAudioFormat,
                    ) -> bool:
                        return False

                    def preferredFormat(self) -> QAudioFormat:
                        return preferred

                with self.assertRaisesRegex(
                    AudioEngineError,
                    "首选格式也不是双声道",
                ):
                    choose_output_audio_format(Device())

    def test_event_is_mixed_at_its_exact_frame(self) -> None:
        sample = _Sample(np.ones((128, 2), dtype=np.float32), 48_000, 128)
        self.engine._events = [_Event(5, sample, 1.0, 0.5)]
        self.engine._duration_frames = 133
        self.engine._playing = True
        rendered = self.engine._render_locked(16)
        self.assertTrue(np.allclose(rendered[:5], 0.0))
        self.assertGreater(float(rendered[5, 0]), 0.0)
        self.assertGreater(float(rendered[5:, 0].max()), float(rendered[5, 0]))
        self.assertEqual(self.engine._frame, 16)

    def test_scheduled_notes_receive_a_short_click_free_attack(self) -> None:
        sample = _Sample(np.ones((512, 2), dtype=np.float32), 48_000, 512)
        self.engine._start_event(_Event(0, sample, 1.0, 1.0))
        voice = self.engine._voices[0]
        self.assertEqual(voice.fade_in_frames, 144)
        self.engine._playing = True
        self.engine._duration_frames = 512
        rendered = self.engine._render_locked(144)
        self.assertLess(float(rendered[0, 0]), float(rendered[-1, 0]))

    def test_native_harp_chord_sample_is_not_stacked_again(self) -> None:
        sample = _Sample(np.ones((512, 2), dtype=np.float32), 48_000, 512)
        self.engine._start_event(
            _Event(
                0,
                sample,
                1.0,
                1.0,
                512,
                0x10,
                9,
                native_articulation=True,
            )
        )
        self.assertEqual(len(self.engine._voices), 1)
        self.engine._voices.clear()
        self.engine._start_event(
            _Event(
                0,
                sample,
                1.0,
                1.0,
                512,
                0x10,
                9,
                native_articulation=False,
            )
        )
        self.assertEqual(len(self.engine._voices), 3)

    def test_seek_restores_an_active_voice_without_disk_io(self) -> None:
        sample = _Sample(np.ones((128, 2), dtype=np.float32), 48_000, 128)
        self.engine._events = [_Event(0, sample, 1.0, 1.0)]
        self.engine._seek_locked(32)
        self.assertEqual(len(self.engine._voices), 1)
        self.assertEqual(self.engine._voices[0].position, 32.0)

    def test_seek_does_not_restore_voice_at_or_after_audible_endpoint(self) -> None:
        sample = _Sample(
            np.ones((48_000 * 6, 2), dtype=np.float32),
            48_000,
            48_000 * 6,
            48_000 * 6,
        )
        lifecycle = voice_lifecycle(
            0x01, 0, 4_800, sample_output_frames(sample.active_frames, 1.0),
            48_000,
        )
        event = _Event(
            0, sample, 1.0, 1.0, 4_800, 0x01, 0, -1, -1,
            lifecycle.audible_frames, lifecycle.fade_out_frames,
        )
        self.engine._events = [event]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._max_event_tail_frames = lifecycle.audible_frames

        self.engine._seek_locked(lifecycle.audible_frames - 1)
        self.assertEqual(len(self.engine._voices), 1)
        self.engine._seek_locked(lifecycle.audible_frames)
        self.assertEqual(self.engine._voices, [])

    def test_six_second_flute_sample_obeys_100ms_note_boundary(self) -> None:
        sample = _Sample(
            np.ones((48_000 * 6, 2), dtype=np.float32),
            48_000,
            48_000 * 6,
            48_000 * 6,
        )
        lifecycle = voice_lifecycle(
            0x01, 0, 4_800, sample_output_frames(sample.active_frames, 1.0),
            48_000,
        )
        self.engine._events = [_Event(
            0, sample, 1.0, 1.0, 4_800, 0x01, 0, -1, -1,
            lifecycle.audible_frames, lifecycle.fade_out_frames,
        )]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._duration_frames = lifecycle.audible_frames
        self.engine._playing = True

        rendered = self.engine._render_locked(lifecycle.audible_frames)
        fade = rendered[-lifecycle.fade_out_frames:, 0]
        self.assertGreater(float(fade[0]), float(fade[-1]))
        self.assertAlmostEqual(float(fade[-1]), 0.0, places=6)
        self.assertEqual(self.engine._voices, [])
        after = self.engine._render_locked(round(0.012 * 48_000))
        self.assertTrue(np.allclose(after, 0.0))

    def test_pause_freezes_mixer_position_and_resume_does_not_retrigger(self) -> None:
        sample = _Sample(np.ones((4_096, 2), dtype=np.float32), 48_000, 4_096)
        self.engine._events = [_Event(0, sample, 1.0, 0.5)]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._duration_frames = 4_096
        self.engine._playing = True
        self.engine._render_locked(256)
        position_before_pause = self.engine._frame
        voice_age_before_pause = self.engine._voices[0].age_frames

        self.engine.pause()
        paused_audio = self.engine._render_locked(256)
        self.assertTrue(np.allclose(paused_audio, 0.0))
        self.assertEqual(self.engine._frame, position_before_pause)
        self.assertEqual(self.engine._voices[0].age_frames, voice_age_before_pause)
        with patch.object(self.engine, "start"):
            self.engine.play()
        self.engine._render_locked(128)
        self.assertEqual(self.engine._frame, position_before_pause + 128)
        self.assertEqual(
            self.engine._voices[0].age_frames,
            voice_age_before_pause + 128,
        )

    def test_transport_state_is_explicit_across_seek_end_stop_and_clear(self) -> None:
        sample = _Sample(
            np.ones((256, 2), dtype=np.float32) * 0.01,
            48_000,
            256,
        )
        self.engine._events = [
            _Event(0, sample, 1.0, 0.5, audible_frames=128)
        ]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._duration_frames = 128

        # Prepared events are retained for replay, but do not imply Pause.
        self.assertEqual(self.engine.get_status().state, "stopped")
        with patch.object(self.engine, "start"):
            self.engine.play()
        self.assertEqual(self.engine.get_status().state, "playing")

        self.engine.seek(1.0)
        self.assertEqual(self.engine.get_status().state, "playing")
        self.engine.pause()
        self.assertEqual(self.engine.get_status().state, "paused")
        self.engine.seek(0.5)
        self.assertEqual(self.engine.get_status().state, "paused")

        with patch.object(self.engine, "start"):
            self.engine.play()
        self.engine._render_locked(256)
        self.assertEqual(self.engine.get_status().state, "stopped")

        self.engine._last_voice_prune_frame = 123
        self.engine.stop()
        self.assertTrue(self.engine._events)
        self.assertIsNone(self.engine._last_voice_prune_frame)
        self.assertEqual(self.engine.get_status().state, "stopped")
        self.engine._last_voice_prune_frame = 123
        self.engine.clear_playback()
        self.assertFalse(self.engine._events)
        self.assertIsNone(self.engine._last_voice_prune_frame)
        self.assertEqual(self.engine.get_status().state, "stopped")

    def test_audio_worker_suspend_preserves_and_reset_discards_queue(self) -> None:
        class FakeSink:
            def __init__(self) -> None:
                self.suspend_calls = 0
                self.resume_calls = 0
                self.reset_calls = 0
                self.start_calls = 0
                self.output = object()

            def suspend(self) -> None:
                self.suspend_calls += 1

            def resume(self) -> None:
                self.resume_calls += 1

            def reset(self) -> None:
                self.reset_calls += 1

            def start(self):
                self.start_calls += 1
                return self.output

        worker = _AudioOutputWorker(self.engine)
        sink = FakeSink()
        worker.sink = sink
        worker.output = object()
        worker.pending_pcm = b"preserve-me"

        worker.suspend_output()
        self.assertTrue(worker.suspended)
        self.assertEqual(worker.pending_pcm, b"preserve-me")
        worker.resume_output()
        self.assertFalse(worker.suspended)
        self.assertEqual(worker.pending_pcm, b"preserve-me")
        with self.engine._lock:
            self.engine._mark_output_reset_pending_locked()
        worker.reset_output()
        self.assertEqual(worker.pending_pcm, b"")
        self.assertTrue(worker.suspended)
        self.assertIs(worker.output, sink.output)
        self.assertEqual(sink.suspend_calls, 2)
        self.assertEqual(sink.resume_calls, 1)
        self.assertEqual(sink.reset_calls, 1)
        self.assertEqual(sink.start_calls, 1)
        self.assertEqual(
            self.engine._output_reset_serial,
            self.engine._output_reset_completed_serial,
        )

    def test_audio_worker_refills_in_bounded_quanta_not_timer_dribbles(
        self,
    ) -> None:
        worker = _AudioOutputWorker(self.engine)
        self.engine._buffer_frames = 4_608
        worker.target_frames = 3_456
        worker.low_water_frames = 2_432

        # A 96-frame timer deficit stays above the low watermark and waits.
        self.assertEqual(worker._refill_frame_count(1_248), 0)
        # Once below the low watermark the worker renders at least 1024 frames.
        self.assertEqual(worker._refill_frame_count(2_208), 1_056)
        # An empty queue still uses the bounded 2048-frame maximum.
        self.assertEqual(worker._refill_frame_count(4_608), 2_048)

    def test_dense_voice_refill_uses_larger_block_within_existing_buffer(self) -> None:
        worker = _AudioOutputWorker(self.engine)
        self.engine._buffer_frames = 3_456
        worker.target_frames = 2_592
        worker.low_water_frames = 1_568

        self.engine._voices = [SimpleNamespace()] * 63
        self.assertEqual(worker._refill_frame_count(1_888), 1_024)

        self.engine._voices.append(SimpleNamespace())
        # At the threshold, use all currently free frames but never exceed
        # either bytesFree or the existing 2048-frame block ceiling.
        self.assertEqual(worker._refill_frame_count(1_888), 1_888)
        self.assertEqual(worker._refill_frame_count(4_000), 2_048)
        # The original low-water boundary still controls when refilling starts.
        self.assertEqual(worker._refill_frame_count(1_887), 0)

    def test_dense_voice_refill_uses_extra_physical_queue_headroom(self) -> None:
        worker = _AudioOutputWorker(self.engine)
        self.engine._buffer_frames = 4_608
        # Sparse playback keeps the former 72 ms target/latency.
        worker.target_frames = 2_592
        worker.low_water_frames = 1_568
        self.engine._voices = [SimpleNamespace()] * 63
        self.assertEqual(worker._refill_frame_count(2_608), 0)

        # Dense playback starts while 2,000 frames remain queued and can use
        # the larger physical sink without exceeding the 2,048-frame ceiling.
        self.engine._voices.append(SimpleNamespace())
        self.assertEqual(worker._refill_frame_count(2_608), 2_048)

    def test_dense_render_pressure_uses_bounded_emergency_headroom(self) -> None:
        worker = _AudioOutputWorker(self.engine)
        self.engine._buffer_frames = 4_608
        worker.target_frames = 2_592
        worker.low_water_frames = 1_568
        self.engine._voices = [SimpleNamespace()] * 64

        # At the ordinary dense watermark 2,808 queued frames would wait.
        self.assertEqual(worker._refill_frame_count(1_800), 0)
        self.engine._render_loads.append(0.50)
        # A measured heavy block raises the target to 87.5% of the existing
        # physical buffer, without increasing the 2,048-frame render ceiling.
        self.assertEqual(worker._refill_frame_count(1_800), 1_800)

    def test_pending_device_reset_blocks_mixer_timeline_advance(self) -> None:
        sample = _Sample(np.ones((4_096, 2), dtype=np.float32), 48_000, 4_096)
        self.engine._events = [_Event(0, sample, 1.0, 0.5)]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._duration_frames = 4_096
        self.engine._playing = True
        with self.engine._lock:
            self.engine._mark_output_reset_pending_locked()

        self.assertEqual(self.engine._read_pcm(512), b"")
        self.assertEqual(self.engine._frame, 0)
        self.engine._complete_output_reset(
            self.engine._output_reset_snapshot()
        )
        self.assertNotEqual(self.engine._read_pcm(512), b"")
        self.assertGreater(self.engine._frame, 0)

    def test_warmed_pcm_callback_has_no_file_or_json_io_and_reports_load(
        self,
    ) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32) * 0.01,
            48_000,
            4_096,
        )
        self.engine._events = [
            _Event(0, sample, 1.0, 0.5, audible_frames=4_096)
        ]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._duration_frames = 4_096
        self.engine._playing = True
        self.engine._ensure_render_buffers(1_024)

        with (
            patch("builtins.open", side_effect=AssertionError("callback file I/O")),
            patch(
                "bdo_realtime_audio.json.loads",
                side_effect=AssertionError("callback JSON parse"),
            ),
            patch(
                "bdo_realtime_audio.wave.open",
                side_effect=AssertionError("callback WAV decode"),
            ),
        ):
            payload = self.engine._read_pcm(1_024 * 4)

        self.assertEqual(len(payload), 1_024 * 4)
        status = self.engine.get_status()
        self.assertGreater(status.render_p95_ms, 0.0)
        self.assertGreater(status.render_p95_load, 0.0)

    def test_warmed_effect_callback_has_no_io_or_numpy_buffer_allocation(
        self,
    ) -> None:
        sample = _Sample(
            np.ones((8_192, 2), dtype=np.float32) * 0.01,
            48_000,
            8_192,
        )
        event = _Event(
            0,
            sample,
            1.0,
            0.5,
            audible_frames=8_192,
            reverb_send=0.5,
            delay_send=0.4,
            chorus_send=0.3,
            reverb_time=60,
            delay_feedback=40,
            chorus_feedback=30,
            chorus_lfo_depth=50,
            chorus_lfo_frequency=45,
        )
        self.engine._commit_project(
            [event],
            {},
            sample.pcm.nbytes,
            ["approximate FX"],
            8_192,
            start_ms=0.0,
        )
        self.engine._playing = True
        self.engine._ensure_render_buffers(1_024)
        self.engine._render_locked(64)

        with (
            patch("builtins.open", side_effect=AssertionError("callback file I/O")),
            patch(
                "bdo_realtime_audio.json.loads",
                side_effect=AssertionError("callback JSON parse"),
            ),
            patch(
                "bdo_realtime_audio.wave.open",
                side_effect=AssertionError("callback WAV decode"),
            ),
            patch(
                "bdo_realtime_audio.np.empty",
                side_effect=AssertionError("callback scratch allocation"),
            ),
            patch(
                "bdo_realtime_audio.np.zeros",
                side_effect=AssertionError("callback scratch allocation"),
            ),
        ):
            rendered = self.engine._render_locked(1_024)

        self.assertGreater(float(np.max(np.abs(rendered))), 0.0)
        self.assertTrue(self.engine._preview_effects.active)

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

    def test_partial_device_write_is_retained_before_next_render(self) -> None:
        class PartialOutput:
            def __init__(self) -> None:
                self.accepted = bytearray()

            def write(self, payload: bytes) -> int:
                count = min(3, len(payload))
                self.accepted.extend(payload[:count])
                return count

        worker = _AudioOutputWorker(self.engine)
        output = PartialOutput()
        worker.output = output
        worker.pending_pcm = b"abcdefgh"

        self.assertFalse(worker._write_pending())
        self.assertEqual(worker.pending_pcm, b"defgh")
        self.assertFalse(worker._write_pending())
        self.assertEqual(worker.pending_pcm, b"gh")
        self.assertTrue(worker._write_pending())
        self.assertEqual(worker.pending_pcm, b"")
        self.assertEqual(bytes(output.accepted), b"abcdefgh")

        self.assertFalse(self.engine._playing)
        self.assertEqual(self.engine._events, [])
        self.assertEqual(self.engine._voices, [])
        self.assertEqual(self.engine._duration_frames, 0)
        self.engine.clear_playback()

    def test_audition_handoff_crossfades_without_stopping_stream(self) -> None:
        sample = _Sample(np.ones((4096, 2), dtype=np.float32), 48_000, 4096)
        self.engine._start_voice(sample, 0.0, 1.0, 0.5)
        old = self.engine._voices[0]
        self.engine._playing = True
        future = Future()
        future.set_result(([_Event(0, sample, 1.0, 0.5)], {}, 0, [], 4096))
        self.engine._load_future = future

        result = self.engine.finish_audition_loading()

        self.assertEqual(result["events"], 1)
        self.assertAlmostEqual(result["duration_ms"], 4096 / 48.0, places=3)
        self.assertTrue(self.engine._playing)
        self.assertEqual(len(self.engine._voices), 2)
        self.assertGreater(old.release_frames, 0)
        self.assertGreater(self.engine._voices[-1].fade_in_frames, 0)
        self.engine._render_locked(old.release_frames + 1)
        self.assertNotIn(old, self.engine._voices)

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

    def test_only_verified_hand_authored_game_ranges_are_enforced(self) -> None:
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x0A]), max(BDO_EDITOR_PITCH_RANGES[0x0A])), (36, 88))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x0E]), max(BDO_EDITOR_PITCH_RANGES[0x0E])), (28, 64))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x0F]), max(BDO_EDITOR_PITCH_RANGES[0x0F])), (28, 64))
        self.assertEqual((min(BDO_EDITOR_PITCH_RANGES[0x12]), max(BDO_EDITOR_PITCH_RANGES[0x12])), (43, 88))
        self.assertNotIn(0x13, BDO_EDITOR_PITCH_RANGES)

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

    def test_project_preload_carries_game_gain_loop_release_and_instance_policy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wav_path = root / "sample.wav"
            wav_path.touch()
            map_path = root / "map.json"
            bank = "midi_instrument_10_proguitar"
            map_path.write_text(
                json.dumps({"banks": {bank: [{
                    "wav_exists": True,
                    "wav_path": str(wav_path),
                    "source_id": 7,
                    "key_min": 0,
                    "key_max": 127,
                    "velocity_min": 0,
                    "velocity_max": 127,
                    "root_note": 60,
                    "route_ntypes": [0],
                    "volume_db": -6.020599913,
                    "release_ms": 50.0,
                    "sample_loops": 1,
                    "loop_start_frame": 100,
                    "loop_end_frame": 500,
                    "instance_group_id": 42,
                    "max_instances": 1,
                    "kill_newest": True,
                    "instance_limit_global": False,
                    "instance_use_virtual_behavior": False,
                }]}}),
                encoding="utf-8",
            )
            sample = _Sample(
                np.ones((1_000, 2), dtype=np.float32),
                48_000,
                1_000,
                1_000,
            )
            original_decode = self.engine._decode_wav
            self.engine._decode_wav = lambda _path: sample
            track = SimpleNamespace(
                track_id=3,
                bdo_instrument_id=0x0A,
                marnian_synth_mode="basic",
                volume_scale=1.0,
                bdo_track_volume=35,
                duration_scale=1.0,
                articulation_type=None,
                notes=[
                    SimpleNamespace(
                        pitch=60,
                        vel=90,
                        start=0,
                        dur=100,
                        ntype=0,
                    ),
                    SimpleNamespace(
                        pitch=60,
                        vel=90,
                        start=10,
                        dur=100,
                        ntype=0,
                    ),
                ],
            )
            try:
                events, *_rest = self.engine._prepare_project(
                    [track],
                    map_path,
                    0,
                    0,
                    0,
                    None,
                    1024 * 1024,
                )
            finally:
                self.engine._decode_wav = original_decode

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertAlmostEqual(
            event.gain,
            90 / 127.0 * 0.35 * 0.5,
            places=6,
        )
        self.assertEqual(
            (event.loop_start_frame, event.loop_end_frame),
            (100, 500),
        )
        self.assertEqual(event.audible_frames, 4_800 + 2_400)
        self.assertEqual(event.fade_out_frames, 2_400)
        self.assertTrue(event.native_sample_route)
        self.assertTrue(event.native_articulation)
        # Project preload is the sole authority: the second note was rejected
        # and the surviving event no longer carries a runtime policy that could
        # execute again during playback or seek.
        self.assertEqual(event.instance_group_id, -1)
        self.assertEqual(event.max_instances, 0)
        self.assertFalse(event.kill_newest)
        self.assertFalse(event.instance_limit_global)

    def test_preplanned_project_limit_is_not_executed_again_at_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wav_path = root / "sample.wav"
            wav_path.touch()
            map_path = root / "map.json"
            bank = "midi_instrument_10_proguitar"
            map_path.write_text(
                json.dumps({"banks": {bank: [{
                    "wav_exists": True,
                    "wav_path": str(wav_path),
                    "source_id": 7,
                    "key_min": 0,
                    "key_max": 127,
                    "velocity_min": 0,
                    "velocity_max": 127,
                    "root_note": 60,
                    "instance_group_id": 42,
                    "max_instances": 1,
                    "kill_newest": False,
                    "instance_limit_global": False,
                    "instance_use_virtual_behavior": False,
                }]}}),
                encoding="utf-8",
            )
            sample = _Sample(
                np.ones((48_000, 2), dtype=np.float32) * 0.01,
                48_000,
                48_000,
                48_000,
            )
            original_decode = self.engine._decode_wav
            self.engine._decode_wav = lambda _path: sample
            track = SimpleNamespace(
                track_id=3,
                bdo_instrument_id=0x0A,
                marnian_synth_mode="basic",
                volume_scale=1.0,
                duration_scale=1.0,
                articulation_type=None,
                notes=[
                    SimpleNamespace(
                        pitch=60, vel=90, start=0, dur=500, ntype=0
                    ),
                    SimpleNamespace(
                        pitch=60, vel=90, start=100, dur=500, ntype=0
                    ),
                ],
            )
            try:
                events, *_rest, duration = self.engine._prepare_project(
                    [track],
                    map_path,
                    0,
                    0,
                    0,
                    None,
                    1024 * 1024,
                )
            finally:
                self.engine._decode_wav = original_decode

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].audible_frames, round(0.104 * 48_000))
        self.assertEqual(events[0].fade_out_frames, round(0.004 * 48_000))
        self.assertTrue(all(event.max_instances == 0 for event in events))
        self.assertEqual(duration, 52_800)

        self.engine._events = events
        self.engine._event_frames = np.asarray(
            [event.frame for event in events], dtype=np.int64
        )
        self.engine._duration_frames = duration
        self.engine._playing = True
        self.engine._render_locked(6_000)
        self.assertEqual(self.engine._voice_steals, 0)

    def test_project_preload_memoizes_repeated_zone_lookups(self) -> None:
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
            sample = _Sample(np.ones((8, 2), dtype=np.float32), 48_000, 8)
            original_decode = self.engine._decode_wav
            self.engine._decode_wav = lambda _path: sample
            track = SimpleNamespace(
                bdo_instrument_id=0x0A, marnian_synth_mode="basic", volume_scale=1.0,
                articulation_type=None,
                notes=[
                    SimpleNamespace(pitch=60, vel=90, start=index * 10, dur=100, ntype=0)
                    for index in range(500)
                ],
            )
            try:
                with patch(
                    "bdo_realtime_audio.select_wwise_zone_variants",
                    wraps=select_wwise_zone_variants,
                ) as select_mock:
                    events, _cache, _bytes, _unverified, _duration = self.engine._prepare_project(
                        [track], map_path, 0, 0, 0, None, 1024 * 1024
                    )
            finally:
                self.engine._decode_wav = original_decode
            self.assertEqual(len(events), 500)
            self.assertEqual(select_mock.call_count, 1)

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

    def test_wav_decode_observes_cancellation_between_bounded_reads(self) -> None:
        cancel_event = threading.Event()

        class ChunkedWave:
            reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getsampwidth(self) -> int:
                return 2

            def getnchannels(self) -> int:
                return 2

            def getframerate(self) -> int:
                return 48_000

            def getnframes(self) -> int:
                return 200_000

            def readframes(self, _frames: int) -> bytes:
                self.reads += 1
                cancel_event.set()
                return bytes(4 * 16)

        source = ChunkedWave()
        with patch("bdo_realtime_audio.wave.open", return_value=source):
            with self.assertRaises(_LoadCancelled):
                self.engine._decode_wav(Path("unused.wav"), cancel_event)
        self.assertEqual(source.reads, 1)

    def test_preload_submission_is_bounded_to_one_worker_window(self) -> None:
        class RecordingExecutor:
            def __init__(self) -> None:
                self.futures: list[Future] = []

            def submit(self, _fn, *_args) -> Future:
                future = Future()
                self.futures.append(future)
                return future

            def shutdown(self, **_kwargs) -> None:
                for future in self.futures:
                    future.cancel()

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bank = "midi_instrument_10_proguitar"
            rows = [{
                "wav_exists": True,
                "wav_path": str(root / f"{pitch}.wav"),
                "source_id": pitch,
                "key_min": pitch,
                "key_max": pitch,
                "velocity_min": 0,
                "velocity_max": 127,
                "root_note": pitch,
            } for pitch in range(40, 52)]
            map_path = root / "map.json"
            map_path.write_text(json.dumps({"banks": {bank: rows}}), encoding="utf-8")
            track = SimpleNamespace(
                bdo_instrument_id=0x0A,
                marnian_synth_mode="basic",
                volume_scale=1.0,
                articulation_type=None,
                notes=[
                    SimpleNamespace(pitch=pitch, vel=90, start=0, dur=100, ntype=0)
                    for pitch in range(40, 52)
                ],
            )
            executor = RecordingExecutor()
            self.engine._decode_workers = 4
            self.engine._decode_pool = executor
            cancel_event = threading.Event()
            errors: list[BaseException] = []

            def prepare() -> None:
                try:
                    self.engine._prepare_project(
                        [track], map_path, 0, 0, 0, None, 1024 * 1024,
                        load_generation=1,
                        cancel_event=cancel_event,
                    )
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=prepare)
            worker.start()
            deadline = time.monotonic() + 1.0
            while len(executor.futures) < 4 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(len(executor.futures), 4)
            time.sleep(0.05)
            self.assertEqual(len(executor.futures), 4)
            cancel_event.set()
            worker.join(1.0)
            self.assertFalse(worker.is_alive())
            self.assertTrue(errors)
            self.assertIsInstance(errors[0], _LoadCancelled)

    def test_new_preload_supersedes_a_running_decode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bank = "midi_instrument_10_proguitar"
            map_path = root / "map.json"
            map_path.write_text(json.dumps({"banks": {bank: [{
                "wav_exists": True,
                "wav_path": str(root / "sample.wav"),
                "source_id": 7,
                "key_min": 0,
                "key_max": 127,
                "velocity_min": 0,
                "velocity_max": 127,
                "root_note": 60,
            }]}}), encoding="utf-8")
            track = SimpleNamespace(
                track_id=1,
                bdo_instrument_id=0x0A,
                marnian_synth_mode="basic",
                volume_scale=1.0,
                duration_scale=1.0,
                articulation_type=None,
                notes=[SimpleNamespace(pitch=60, vel=90, start=0, dur=100, ntype=0)],
            )
            first_started = threading.Event()
            second_finished = threading.Event()
            call_count = 0
            call_lock = threading.Lock()
            sample = _Sample(np.ones((128, 2), dtype=np.float32), 48_000, 128)

            def decode(_path: Path, cancel_event: threading.Event | None = None) -> _Sample:
                nonlocal call_count
                with call_lock:
                    call_count += 1
                    call_number = call_count
                if call_number == 1:
                    first_started.set()
                    self.assertIsNotNone(cancel_event)
                    if not cancel_event.wait(1.0):
                        self.fail("the superseded decode was not cancelled")
                    raise _LoadCancelled()
                second_finished.set()
                return sample

            self.engine._decode_wav = decode
            with patch.object(self.engine, "start"):
                self.engine.load_project_async([track], map_path, 0)
                self.assertTrue(first_started.wait(1.0))
                self.engine.load_project_async([track], map_path, 0)
                self.assertTrue(second_finished.wait(1.0))

            deadline = time.monotonic() + 1.0
            result = None
            while result is None and time.monotonic() < deadline:
                result = self.engine.finish_loading(0)
                if result is None:
                    time.sleep(0.005)
            self.assertIsNotNone(result)
            self.assertEqual(result["events"], 1)
            self.assertEqual(call_count, 2)

    def test_stop_releases_preload_pools_and_next_load_recreates_them(self) -> None:
        first_loader, first_decode_pool = self.engine._ensure_preload_executors()
        self.engine.stop()
        self.assertIsNone(self.engine._loader)
        self.assertIsNone(self.engine._decode_pool)

        second_loader, second_decode_pool = self.engine._ensure_preload_executors()
        self.assertIsNot(first_loader, second_loader)
        self.assertIsNot(first_decode_pool, second_decode_pool)
        self.assertEqual(second_loader.submit(lambda: 7).result(timeout=1.0), 7)

    def test_engine_can_play_again_after_stop_releases_workers(self) -> None:
        sample = _Sample(np.ones((128, 2), dtype=np.float32), 48_000, 128)
        self.engine._events = [_Event(0, sample, 1.0, 0.5)]
        self.engine._event_frames = np.asarray([0], dtype=np.int64)
        self.engine._duration_frames = 128
        self.engine._ensure_preload_executors()
        self.engine.stop()

        with patch.object(self.engine, "start"):
            self.engine.play()
        rendered = self.engine._render_locked(16)

        self.assertTrue(self.engine._playing)
        self.assertGreater(float(rendered[:, 0].max()), 0.0)

    def test_dense_same_source_mix_reuses_fixed_frame_scratch(self) -> None:
        frames = 256
        sample = _Sample(np.ones((4096, 2), dtype=np.float32), 48_000, 4096)
        for index in range(16):
            self.engine._start_voice(
                sample,
                float(index),
                0.9 + index * 0.002,
                0.01,
            )
        self.engine._playing = True
        self.engine._duration_frames = 4096
        self.engine._ensure_render_buffers(frames)
        scratch_ids = (
            id(self.engine._voice_a),
            id(self.engine._voice_b),
            id(self.engine._voice_positions),
            id(self.engine._voice_indices),
            id(self.engine._limiter_magnitude),
            id(self.engine._limiter_denominator),
            id(self.engine._limiter_mask),
            id(self.engine._pcm_i16),
        )

        # The removed batch mixer called np.asarray on per-voice lists and then
        # built voices×frames arrays. Rendering now needs only preallocated
        # frame-sized scratch, independent of the number of same-source voices.
        with patch(
            "bdo_realtime_audio.np.asarray",
            side_effect=AssertionError("per-block voice array allocation"),
        ):
            rendered = self.engine._render_locked(frames)

        self.assertTrue(np.isfinite(rendered).all())
        self.assertEqual(scratch_ids, (
            id(self.engine._voice_a),
            id(self.engine._voice_b),
            id(self.engine._voice_positions),
            id(self.engine._voice_indices),
            id(self.engine._limiter_magnitude),
            id(self.engine._limiter_denominator),
            id(self.engine._limiter_mask),
            id(self.engine._pcm_i16),
        ))

    def test_linear_voice_tiles_match_scalar_mix_and_keep_logical_state(self) -> None:
        frames = 1_024
        phase = np.arange(4_096, dtype=np.float32)
        mono = np.sin(phase * (2.0 * np.pi * 220.0 / 48_000)) * 0.01
        sample = _Sample(
            np.column_stack((mono, mono)),
            48_000,
            len(mono),
            len(mono),
        )
        sample_b = _Sample(
            np.column_stack((mono * 0.7, mono * -0.5)),
            48_000,
            len(mono),
            len(mono),
        )

        def configured_engine() -> BdoRealtimeAudioEngine:
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            engine._sample_rate = 48_000
            engine._track_meter_ids = list(range(8))
            engine._track_peaks = np.zeros(8, dtype=np.float32)
            engine._track_block_peaks = np.zeros(8, dtype=np.float32)
            for index in range(48):
                engine._start_voice(
                    sample if index % 2 == 0 else sample_b,
                    float(index % 31),
                    0.58 + index * 0.006,
                    0.004 + (index % 5) * 0.001,
                    age_frames=256 + index,
                    track_slot=index % 8,
                    audible_frames=16_384,
                    loop_start_frame=0,
                    loop_end_frame=4_096,
                    start_frame=index,
                )
            engine._playing = True
            engine._duration_frames = 16_384
            return engine

        tiled = configured_engine()
        scalar = configured_engine()
        try:
            tiled._ensure_render_buffers(frames)
            with (
                patch(
                    "bdo_realtime_audio.np.empty",
                    side_effect=AssertionError("callback scratch allocation"),
                ),
                patch.object(
                    tiled,
                    "_mix_single_voice",
                    wraps=tiled._mix_single_voice,
                ) as tiled_scalar_mix,
            ):
                tiled_pcm = tiled._render_locked(frames).copy()
            with (
                patch(
                    "bdo_realtime_audio.LINEAR_VOICE_BATCH_THRESHOLD",
                    1_000,
                ),
                patch.object(
                    scalar,
                    "_mix_single_voice",
                    wraps=scalar._mix_single_voice,
                ) as scalar_mix,
            ):
                scalar_pcm = scalar._render_locked(frames).copy()

            self.assertEqual(tiled_scalar_mix.call_count, 0)
            self.assertEqual(scalar_mix.call_count, 48)
            np.testing.assert_allclose(
                tiled_pcm,
                scalar_pcm,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            np.testing.assert_allclose(
                tiled._track_peaks,
                scalar._track_peaks,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            self.assertEqual(
                [(voice.position, voice.age_frames) for voice in tiled._voices],
                [(voice.position, voice.age_frames) for voice in scalar._voices],
            )
        finally:
            tiled.stop()
            scalar.stop()

    def test_linear_voice_tiles_preserve_independent_effect_sends(self) -> None:
        frames = 1_024
        phase = np.arange(4_096, dtype=np.float32)
        mono = np.sin(phase * (2.0 * np.pi * 220.0 / 48_000)) * 0.006
        sample = _Sample(
            np.column_stack((mono, mono)),
            48_000,
            len(mono),
            len(mono),
        )

        def configured_engine() -> BdoRealtimeAudioEngine:
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            engine._sample_rate = 48_000
            engine._track_meter_ids = list(range(8))
            engine._track_peaks = np.zeros(8, dtype=np.float32)
            engine._track_block_peaks = np.zeros(8, dtype=np.float32)
            for index in range(48):
                engine._start_voice(
                    sample,
                    float(index % 31),
                    0.58 + index * 0.006,
                    0.004 + (index % 5) * 0.001,
                    age_frames=256 + index,
                    track_slot=index % 8,
                    audible_frames=16_384,
                    loop_start_frame=0,
                    loop_end_frame=4_096,
                    start_frame=index,
                    reverb_send=(index % 3) * 0.2,
                    delay_send=(index % 4) * 0.15,
                    chorus_send=(index % 5) * 0.1,
                )
            engine._preview_effects.configure(
                PreviewEffectSettings(50, 45, 40, 55, 35),
                reverb_send=True,
                delay_send=True,
                chorus_send=True,
            )
            engine._playing = True
            engine._duration_frames = 16_384
            return engine

        tiled = configured_engine()
        scalar = configured_engine()
        try:
            tiled._ensure_render_buffers(frames)
            with (
                patch(
                    "bdo_realtime_audio.np.empty",
                    side_effect=AssertionError("callback scratch allocation"),
                ),
                patch.object(
                    tiled,
                    "_mix_single_voice",
                    wraps=tiled._mix_single_voice,
                ) as tiled_scalar_mix,
            ):
                tiled_pcm = tiled._render_locked(frames).copy()
            with (
                patch(
                    "bdo_realtime_audio.LINEAR_VOICE_BATCH_THRESHOLD",
                    1_000,
                ),
                patch.object(
                    scalar,
                    "_mix_single_voice",
                    wraps=scalar._mix_single_voice,
                ) as scalar_mix,
            ):
                scalar_pcm = scalar._render_locked(frames).copy()

            self.assertEqual(tiled_scalar_mix.call_count, 0)
            self.assertEqual(scalar_mix.call_count, 48)
            np.testing.assert_allclose(
                tiled_pcm,
                scalar_pcm,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            np.testing.assert_allclose(
                tiled._track_peaks,
                scalar._track_peaks,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            self.assertEqual(
                [(voice.position, voice.age_frames) for voice in tiled._voices],
                [(voice.position, voice.age_frames) for voice in scalar._voices],
            )
        finally:
            tiled.stop()
            scalar.stop()

    def test_equivalent_voice_groups_preserve_weighted_effect_sends(self) -> None:
        frames = 1_024
        phase = np.arange(4_096, dtype=np.float32)
        mono = np.sin(phase * (2.0 * np.pi * 220.0 / 48_000)) * 0.004
        sample = _Sample(
            np.column_stack((mono, mono * 0.9)),
            48_000,
            len(mono),
            len(mono),
        )

        def configured_engine() -> BdoRealtimeAudioEngine:
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            engine._sample_rate = 48_000
            engine._track_meter_ids = list(range(8))
            engine._track_peaks = np.zeros(8, dtype=np.float32)
            engine._track_block_peaks = np.zeros(8, dtype=np.float32)
            for index in range(128):
                engine._start_voice(
                    sample,
                    17.0,
                    0.73,
                    0.001 + (index % 7) * 0.0003,
                    age_frames=256,
                    track_slot=index % 8,
                    audible_frames=16_384,
                    loop_start_frame=0,
                    loop_end_frame=4_096,
                    start_frame=0,
                    reverb_send=(index % 3) * 0.2,
                    delay_send=(index % 4) * 0.15,
                    chorus_send=(index % 5) * 0.1,
                )
            engine._preview_effects.configure(
                PreviewEffectSettings(50, 45, 40, 55, 35),
                reverb_send=True,
                delay_send=True,
                chorus_send=True,
            )
            engine._playing = True
            engine._duration_frames = 16_384
            return engine

        grouped = configured_engine()
        scalar = configured_engine()
        try:
            grouped._ensure_render_buffers(frames)
            with patch.object(
                grouped,
                "_mix_single_voice",
                wraps=grouped._mix_single_voice,
            ) as grouped_mix:
                grouped_pcm = grouped._render_locked(frames).copy()
            with (
                patch(
                    "bdo_realtime_audio.EQUIVALENT_VOICE_GROUP_THRESHOLD",
                    1_000,
                ),
                patch(
                    "bdo_realtime_audio.EQUIVALENT_EFFECT_VOICE_GROUP_THRESHOLD",
                    1_000,
                ),
                patch(
                    "bdo_realtime_audio.LINEAR_VOICE_BATCH_THRESHOLD",
                    1_000,
                ),
                patch.object(
                    scalar,
                    "_mix_single_voice",
                    wraps=scalar._mix_single_voice,
                ) as scalar_mix,
            ):
                scalar_pcm = scalar._render_locked(frames).copy()

            self.assertEqual(grouped_mix.call_count, 1)
            self.assertEqual(scalar_mix.call_count, 128)
            np.testing.assert_allclose(
                grouped_pcm,
                scalar_pcm,
                rtol=8.0e-6,
                atol=3.0e-6,
            )
            np.testing.assert_allclose(
                grouped._track_peaks,
                scalar._track_peaks,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            self.assertEqual(
                [(voice.position, voice.age_frames) for voice in grouped._voices],
                [(voice.position, voice.age_frames) for voice in scalar._voices],
            )
        finally:
            grouped.stop()
            scalar.stop()

    def test_equivalent_probe_keeps_unrelated_singletons_on_tile_path(self) -> None:
        frames = 1_024
        phase = np.arange(4_096, dtype=np.float32)
        mono = np.sin(phase * (2.0 * np.pi * 220.0 / 48_000)) * 0.004
        sample = _Sample(
            np.column_stack((mono, mono * 0.9)),
            48_000,
            len(mono),
            len(mono),
        )

        def configured_engine() -> BdoRealtimeAudioEngine:
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            engine._sample_rate = 48_000
            engine._track_meter_ids = list(range(8))
            engine._track_peaks = np.zeros(8, dtype=np.float32)
            engine._track_block_peaks = np.zeros(8, dtype=np.float32)
            for index in range(128):
                duplicate = index < 2
                engine._start_voice(
                    sample,
                    17.0 if duplicate else 17.0 + index * 0.25,
                    0.73 if duplicate else 0.73 + index * 0.001,
                    0.001 + (index % 7) * 0.0003,
                    age_frames=256,
                    track_slot=index % 8,
                    audible_frames=16_384,
                    loop_start_frame=0,
                    loop_end_frame=4_096,
                    start_frame=0,
                    reverb_send=0.35,
                    delay_send=0.25,
                    chorus_send=0.20,
                )
            engine._preview_effects.configure(
                PreviewEffectSettings(50, 45, 40, 55, 35),
                reverb_send=True,
                delay_send=True,
                chorus_send=True,
            )
            engine._playing = True
            engine._duration_frames = 16_384
            return engine

        tiled = configured_engine()
        scalar = configured_engine()
        try:
            tiled._ensure_render_buffers(frames)
            with patch.object(
                tiled,
                "_mix_single_voice",
                wraps=tiled._mix_single_voice,
            ) as tiled_mix:
                tiled_pcm = tiled._render_locked(frames).copy()
            with (
                patch(
                    "bdo_realtime_audio.EQUIVALENT_EFFECT_VOICE_GROUP_THRESHOLD",
                    1_000,
                ),
                patch(
                    "bdo_realtime_audio.LINEAR_VOICE_BATCH_THRESHOLD",
                    1_000,
                ),
                patch.object(
                    scalar,
                    "_mix_single_voice",
                    wraps=scalar._mix_single_voice,
                ) as scalar_mix,
            ):
                scalar_pcm = scalar._render_locked(frames).copy()

            self.assertEqual(tiled_mix.call_count, 1)
            self.assertEqual(scalar_mix.call_count, 128)
            np.testing.assert_allclose(
                tiled_pcm,
                scalar_pcm,
                rtol=8.0e-6,
                atol=3.0e-6,
            )
            np.testing.assert_allclose(
                tiled._track_peaks,
                scalar._track_peaks,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            self.assertEqual(
                [(voice.position, voice.age_frames) for voice in tiled._voices],
                [(voice.position, voice.age_frames) for voice in scalar._voices],
            )
        finally:
            tiled.stop()
            scalar.stop()

    def test_packed_sample_arena_batches_unrelated_sources_without_state_loss(self) -> None:
        frames = 1_024
        source_cache = {}
        for source_id in range(12):
            phase = np.arange(4_096, dtype=np.float32)
            mono = np.sin(
                phase * (2.0 * np.pi * (180.0 + source_id * 7.0) / 48_000)
            ) * (0.004 + source_id * 0.0001)
            source_cache[("bank", source_id)] = _Sample(
                np.column_stack((mono, mono * (0.9 - source_id * 0.01))),
                48_000,
                len(mono),
                len(mono),
            )
        cache_bytes = sum(sample.pcm.nbytes for sample in source_cache.values())
        packed = self.engine._pack_sample_cache(source_cache, cache_bytes)
        arena = self.engine._shared_sample_arena(packed)
        self.assertIsNotNone(arena)
        self.assertEqual(len({id(sample.arena) for sample in packed.values()}), 1)
        for key, sample in packed.items():
            np.testing.assert_array_equal(sample.pcm, source_cache[key].pcm)

        def configured_engine() -> BdoRealtimeAudioEngine:
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            engine._sample_rate = 48_000
            engine._sample_arena = arena
            engine._track_meter_ids = list(range(8))
            engine._track_peaks = np.zeros(8, dtype=np.float32)
            engine._track_block_peaks = np.zeros(8, dtype=np.float32)
            samples = list(packed.values())
            for index in range(48):
                engine._start_voice(
                    samples[index % len(samples)],
                    float(index % 19),
                    0.61 + index * 0.005,
                    0.003 + (index % 5) * 0.001,
                    age_frames=256 + index,
                    track_slot=index % 8,
                    audible_frames=16_384,
                    start_frame=index,
                )
            engine._playing = True
            engine._duration_frames = 16_384
            return engine

        tiled = configured_engine()
        scalar = configured_engine()
        try:
            with patch.object(
                tiled,
                "_mix_single_voice",
                wraps=tiled._mix_single_voice,
            ) as tiled_scalar_mix:
                tiled_pcm = tiled._render_locked(frames).copy()
            with patch(
                "bdo_realtime_audio.LINEAR_VOICE_BATCH_THRESHOLD",
                1_000,
            ):
                scalar_pcm = scalar._render_locked(frames).copy()

            self.assertEqual(tiled_scalar_mix.call_count, 0)
            np.testing.assert_allclose(
                tiled_pcm,
                scalar_pcm,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            np.testing.assert_allclose(
                tiled._track_peaks,
                scalar._track_peaks,
                rtol=4.0e-6,
                atol=2.0e-6,
            )
            self.assertEqual(
                [(voice.position, voice.age_frames) for voice in tiled._voices],
                [(voice.position, voice.age_frames) for voice in scalar._voices],
            )
        finally:
            tiled.stop()
            scalar.stop()

    def test_realtime_articulation_reuses_preallocated_envelope_scratch(self) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32) * 0.01,
            48_000,
            4_096,
        )
        self.engine._start_voice(
            sample,
            0.0,
            1.0,
            0.5,
            duration_frames=4_096,
            instrument_id=0x0E,
            ntype=20,
            age_frames=256,
            audible_frames=4_096,
        )
        self.engine._playing = True
        self.engine._duration_frames = 4_096
        self.engine._ensure_render_buffers(512)
        scratch_ids = (
            id(self.engine._articulation_envelope),
            id(self.engine._articulation_scratch),
        )

        with patch(
            "bdo_audio_mixing.np.empty_like",
            side_effect=AssertionError("articulation callback allocation"),
        ):
            rendered = self.engine._render_locked(512)

        self.assertTrue(np.isfinite(rendered).all())
        self.assertEqual(
            scratch_ids,
            (
                id(self.engine._articulation_envelope),
                id(self.engine._articulation_scratch),
            ),
        )

    def test_equivalent_linear_voices_share_interpolation_without_merging_state(self) -> None:
        frames = 1_024
        phase = np.arange(4_096, dtype=np.float32)
        mono = np.sin(phase * (2.0 * np.pi * 220.0 / 48_000)) * 0.01
        sample = _Sample(
            np.column_stack((mono, mono)),
            48_000,
            len(mono),
            len(mono),
        )

        def configured_engine() -> BdoRealtimeAudioEngine:
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            engine._sample_rate = 48_000
            engine._track_meter_ids = list(range(8))
            engine._track_peaks = np.zeros(8, dtype=np.float32)
            engine._track_block_peaks = np.zeros(8, dtype=np.float32)
            for index in range(128):
                engine._start_voice(
                    sample,
                    0.0,
                    0.75 + (index % 8) * 0.025,
                    0.005 + (index % 3) * 0.001,
                    age_frames=0,
                    track_slot=index % 8,
                    audible_frames=8_192,
                    loop_start_frame=0,
                    loop_end_frame=4_096,
                )
            engine._playing = True
            engine._duration_frames = 8_192
            return engine

        grouped = configured_engine()
        scalar = configured_engine()
        try:
            with patch.object(
                grouped,
                "_mix_single_voice",
                wraps=grouped._mix_single_voice,
            ) as grouped_mix:
                grouped_pcm = grouped._render_locked(frames).copy()
            with patch(
                "bdo_realtime_audio.EQUIVALENT_VOICE_GROUP_THRESHOLD",
                1_000,
            ):
                scalar_pcm = scalar._render_locked(frames).copy()

            self.assertEqual(grouped_mix.call_count, 8)
            self.assertEqual(len(grouped._voices), 128)
            np.testing.assert_allclose(
                grouped_pcm,
                scalar_pcm,
                rtol=3.0e-6,
                atol=2.0e-6,
            )
            np.testing.assert_allclose(
                grouped._track_peaks,
                scalar._track_peaks,
                rtol=3.0e-6,
                atol=2.0e-6,
            )
            self.assertEqual(
                [(voice.position, voice.age_frames) for voice in grouped._voices],
                [(voice.position, voice.age_frames) for voice in scalar._voices],
            )
        finally:
            grouped.stop()
            scalar.stop()

    def test_nonlinear_articulations_stay_on_per_voice_mix_path(self) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32) * 0.01,
            48_000,
            4_096,
        )
        for _index in range(128):
            self.engine._start_voice(
                sample,
                0.0,
                1.0,
                0.5,
                duration_frames=2_048,
                instrument_id=0x0E,
                ntype=22,
                audible_frames=2_048,
            )
        self.engine._playing = True
        self.engine._duration_frames = 2_048

        with patch.object(
            self.engine,
            "_mix_single_voice",
            wraps=self.engine._mix_single_voice,
        ) as mix_mock:
            self.engine._render_locked(512)

        self.assertEqual(mix_mock.call_count, 128)

    def test_dense_distinct_onsets_mix_each_voice_once_per_block(self) -> None:
        sample = _Sample(
            np.ones((8_192, 2), dtype=np.float32),
            48_000,
            8_192,
        )
        self.engine._events = [
            _Event(
                frame,
                sample,
                1.0,
                0.01,
                audible_frames=8_192,
            )
            for frame in range(0, 2_048, 32)
        ]
        self.engine._event_frames = np.asarray(
            [event.frame for event in self.engine._events],
            dtype=np.int64,
        )
        self.engine._duration_frames = 8_192
        self.engine._playing = True

        with patch.object(
            self.engine,
            "_mix_single_voice",
            wraps=self.engine._mix_single_voice,
        ) as mix_mock:
            rendered = self.engine._render_locked(2_048)

        self.assertEqual(mix_mock.call_count, len(self.engine._events))
        self.assertTrue(np.isfinite(rendered).all())

    def test_dense_onsets_do_not_rescan_the_voice_pool_per_event(self) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32) * 0.01,
            48_000,
            4_096,
        )
        self.engine._events = [
            _Event(0, sample, 1.0, 0.01, audible_frames=4_096)
            for _ in range(128)
        ]
        self.engine._event_frames = np.zeros(128, dtype=np.int64)
        self.engine._duration_frames = 4_096
        self.engine._playing = True

        with patch.object(
            self.engine,
            "_voice_is_alive_at_frame",
            wraps=self.engine._voice_is_alive_at_frame,
        ) as alive_mock:
            rendered = self.engine._render_locked(1_024)

        self.assertLessEqual(alive_mock.call_count, len(self.engine._events))
        self.assertEqual(len(self.engine._voices), len(self.engine._events))
        self.assertTrue(np.isfinite(rendered).all())

    def test_same_frame_pressure_prunes_once_and_block_invalidates_cache(self) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32) * 0.01,
            48_000,
            4_096,
        )
        self.engine._events = [
            _Event(0, sample, 1.0, 0.01, audible_frames=4_096)
            for _ in range(64)
        ]
        self.engine._event_frames = np.zeros(64, dtype=np.int64)
        self.engine._duration_frames = 4_096
        self.engine._playing = True

        with (
            patch("bdo_realtime_audio.SOFT_VOICE_LIMIT", 32),
            patch.object(
                self.engine,
                "_voice_is_alive_at_frame",
                wraps=self.engine._voice_is_alive_at_frame,
            ) as alive_mock,
        ):
            self.engine._render_locked(256)

        self.assertEqual(alive_mock.call_count, 32)
        self.assertIsNone(self.engine._last_voice_prune_frame)

    def test_seek_back_and_adjacent_frame_invalidate_prune_cache(self) -> None:
        sample = _Sample(
            np.ones((512, 2), dtype=np.float32) * 0.01,
            48_000,
            512,
        )
        self.engine._last_voice_prune_frame = 100
        self.engine._seek_locked(100)
        self.assertIsNone(self.engine._last_voice_prune_frame)

        with patch("bdo_realtime_audio.SOFT_VOICE_LIMIT", 1):
            expired, _retired = self.engine._start_voice(
                sample,
                0.0,
                1.0,
                0.5,
                audible_frames=50,
                start_frame=0,
                scheduler_frame=100,
            )
            current, retired_same = self.engine._start_voice(
                sample,
                0.0,
                1.0,
                0.5,
                audible_frames=1,
                start_frame=100,
                scheduler_frame=100,
            )
            self.assertTrue(any(voice is expired for voice in retired_same))
            self.assertEqual(self.engine._last_voice_prune_frame, 100)

            _next, retired_adjacent = self.engine._start_voice(
                sample,
                0.0,
                1.0,
                0.5,
                audible_frames=50,
                start_frame=101,
                scheduler_frame=101,
            )
            self.assertTrue(any(voice is current for voice in retired_adjacent))
            self.assertEqual(self.engine._last_voice_prune_frame, 101)

    def test_master_headroom_reduces_dense_mix_with_slow_release(self) -> None:
        self.engine._ensure_render_buffers(512)
        dense = np.full((512, 2), 2.0, dtype=np.float32)
        self.engine._apply_master_headroom(dense, len(dense))
        reduced_gain = self.engine._master_gain

        self.assertLessEqual(float(np.max(np.abs(dense[-32:]))), 0.91)
        self.assertLess(reduced_gain, 0.5)

        quiet = np.full((512, 2), 0.1, dtype=np.float32)
        self.engine._apply_master_headroom(quiet, len(quiet))
        self.assertGreater(self.engine._master_gain, reduced_gain)
        self.assertLess(self.engine._master_gain, 1.0)

    def test_voice_pressure_uses_short_release_before_hard_cap(self) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32),
            48_000,
            4_096,
        )
        for _ in range(225):
            self.engine._start_voice(
                sample,
                0.0,
                1.0,
                0.5,
                audible_frames=4_096,
            )

        self.assertEqual(len(self.engine._voices), 225)
        self.assertEqual(self.engine._voice_steals, 1)
        self.assertEqual(
            sum(voice.release_start_age >= 0 for voice in self.engine._voices),
            1,
        )

    def test_looping_voice_wraps_without_reading_past_loop_end(self) -> None:
        mono = np.asarray(
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
            dtype=np.float32,
        )
        sample = _Sample(
            np.column_stack((mono, mono)),
            48_000,
            len(mono),
        )
        voice, _retired = self.engine._start_voice(
            sample,
            0.0,
            1.0,
            1.0,
            audible_frames=10,
            loop_start_frame=2,
            loop_end_frame=5,
        )
        self.engine._ensure_render_buffers(10)
        output = np.zeros((10, 2), dtype=np.float32)

        self.engine._mix_single_voice(output, 10, voice)

        expected = np.asarray(
            [0.01, 0.02, 0.03, 0.04, 0.05, 0.03, 0.04, 0.05, 0.03, 0.04],
            dtype=np.float32,
        )
        np.testing.assert_allclose(output[:, 0], expected, atol=1.0e-6)

    def test_release_endpoint_bounds_looped_and_non_looped_mix_work(self) -> None:
        sample = _Sample(
            np.ones((512, 2), dtype=np.float32) * 0.01,
            48_000,
            512,
        )
        self.engine._ensure_render_buffers(128)

        for loop_bounds, position in (((0, 0), 0.0), ((8, 40), 32.0)):
            with self.subTest(loop_bounds=loop_bounds):
                self.engine._voices.clear()
                voice, _retired = self.engine._start_voice(
                    sample,
                    position,
                    1.0,
                    1.0,
                    audible_frames=512,
                    loop_start_frame=loop_bounds[0],
                    loop_end_frame=loop_bounds[1],
                )
                voice.release_start_age = 0
                voice.release_frames = 32
                output = np.zeros((128, 2), dtype=np.float32)
                with patch.object(
                    self.engine,
                    "_apply_voice_transition",
                    wraps=self.engine._apply_voice_transition,
                ) as transition_mock:
                    self.engine._mix_single_voice(output, 128, voice)

                self.assertEqual(transition_mock.call_args.args[1], 32)
                self.assertGreater(float(np.max(np.abs(output[:32]))), 0.0)
                self.assertTrue(np.allclose(output[32:], 0.0))

                voice.age_frames = 32
                output.fill(0.0)
                with patch.object(
                    self.engine,
                    "_apply_voice_transition",
                    wraps=self.engine._apply_voice_transition,
                ) as ended_mock:
                    self.engine._mix_single_voice(output, 128, voice)
                ended_mock.assert_not_called()
                self.assertTrue(np.allclose(output, 0.0))

    def test_release_span_crosses_blocks_without_changing_fade_endpoint(self) -> None:
        sample = _Sample(
            np.ones((1_024, 2), dtype=np.float32) * 0.01,
            48_000,
            1_024,
        )
        voice, _retired = self.engine._start_voice(
            sample,
            0.0,
            1.0,
            1.0,
            audible_frames=1_024,
        )
        voice.release_start_age = 100
        voice.release_frames = 100
        first = np.zeros((128, 2), dtype=np.float32)
        second = np.zeros((128, 2), dtype=np.float32)
        self.engine._ensure_render_buffers(128)
        with patch.object(
            self.engine,
            "_apply_voice_transition",
            wraps=self.engine._apply_voice_transition,
        ) as transition_mock:
            self.engine._render_voice_span(first, voice, 0, 128)
            self.engine._render_voice_span(second, voice, 0, 128)

        self.assertEqual(
            [call.args[1] for call in transition_mock.call_args_list],
            [128, 72],
        )
        self.assertTrue(np.allclose(second[72:], 0.0))
        self.assertFalse(self.engine._voice_is_alive(voice))

        fade_voice, _retired = self.engine._start_voice(
            sample,
            0.0,
            1.0,
            1.0,
            audible_frames=64,
            fade_out_frames=16,
        )
        fade_voice.release_start_age = 1_000
        fade_voice.release_frames = 10
        faded = np.zeros((64, 2), dtype=np.float32)
        self.engine._mix_single_voice(faded, 64, fade_voice)
        self.assertGreater(float(faded[-16, 0]), float(faded[-1, 0]))
        self.assertAlmostEqual(float(faded[-1, 0]), 0.0, places=6)

    def test_same_block_voice_steal_uses_relative_voice_age(self) -> None:
        sample = _Sample(
            np.ones((4_096, 2), dtype=np.float32) * 0.01,
            48_000,
            4_096,
        )
        self.engine._events = [
            _Event(100, sample, 1.0, 0.5, audible_frames=4_096),
            _Event(200, sample, 1.0, 0.5, audible_frames=4_096),
        ]
        self.engine._event_frames = np.asarray([100, 200], dtype=np.int64)
        self.engine._duration_frames = 4_096
        self.engine._playing = True

        with patch("bdo_realtime_audio.SOFT_VOICE_LIMIT", 1):
            self.engine._render_locked(300)

        older = next(
            voice
            for voice in self.engine._voices
            if voice.start_frame == 100
        )
        self.assertEqual(older.release_start_age, 100)

    def test_voice_ending_before_later_onset_does_not_trigger_steal(self) -> None:
        sample = _Sample(
            np.ones((512, 2), dtype=np.float32) * 0.01,
            48_000,
            512,
        )
        self.engine._events = [
            _Event(0, sample, 1.0, 0.5, audible_frames=50),
            _Event(100, sample, 1.0, 0.5, audible_frames=200),
        ]
        self.engine._event_frames = np.asarray([0, 100], dtype=np.int64)
        self.engine._duration_frames = 300
        self.engine._playing = True

        with patch("bdo_realtime_audio.SOFT_VOICE_LIMIT", 1):
            self.engine._render_locked(200)

        self.assertEqual(self.engine._voice_steals, 0)
        self.assertEqual(
            [voice.start_frame for voice in self.engine._voices],
            [100],
        )

    def test_instance_limit_releases_oldest_voice_and_seek_rebuilds_order(self) -> None:
        sample = _Sample(
            np.ones((2_048, 2), dtype=np.float32) * 0.01,
            48_000,
            2_048,
        )
        events = [
            _Event(
                0,
                sample,
                1.0,
                0.5,
                audible_frames=1_500,
                instance_group_id=77,
                max_instances=1,
            ),
            _Event(
                100,
                sample,
                1.0,
                0.5,
                audible_frames=1_500,
                instance_group_id=77,
                max_instances=1,
            ),
        ]
        self.engine._events = events
        self.engine._event_frames = np.asarray([0, 100], dtype=np.int64)
        self.engine._max_event_tail_frames = 1_500
        self.engine._duration_frames = 1_600

        self.engine._seek_locked(200)
        older = next(
            voice
            for voice in self.engine._voices
            if voice.start_frame == 0
        )
        self.assertEqual(older.release_start_age, 100)

        self.engine._seek_locked(400)
        self.assertEqual(
            [voice.start_frame for voice in self.engine._voices],
            [100],
        )

    def test_instance_limit_kill_newest_suppresses_new_voice(self) -> None:
        sample = _Sample(
            np.ones((512, 2), dtype=np.float32) * 0.01,
            48_000,
            512,
        )
        first = _Event(
            0,
            sample,
            1.0,
            0.5,
            audible_frames=400,
            instance_group_id=9,
            max_instances=1,
        )
        newest = _Event(
            100,
            sample,
            1.0,
            0.5,
            audible_frames=400,
            instance_group_id=9,
            max_instances=1,
            kill_newest=True,
        )
        self.engine._start_event(first)
        self.engine._start_event(newest)

        self.assertEqual(len(self.engine._voices), 1)
        self.assertEqual(self.engine._voices[0].start_frame, 0)

    def test_instance_limit_scope_is_per_track_unless_marked_global(self) -> None:
        sample = _Sample(
            np.ones((2_048, 2), dtype=np.float32) * 0.01,
            48_000,
            2_048,
        )
        first_track = _Event(
            0,
            sample,
            1.0,
            0.5,
            track_id=101,
            audible_frames=1_500,
            instance_group_id=77,
            max_instances=1,
        )
        other_track = _Event(
            10,
            sample,
            1.0,
            0.5,
            track_id=202,
            audible_frames=1_500,
            instance_group_id=77,
            max_instances=1,
        )
        same_track = _Event(
            20,
            sample,
            1.0,
            0.5,
            track_id=101,
            audible_frames=1_500,
            instance_group_id=77,
            max_instances=1,
        )

        self.engine._start_event(first_track)
        self.engine._start_event(other_track)
        self.engine._start_event(same_track)

        by_start = {voice.start_frame: voice for voice in self.engine._voices}
        self.assertEqual(by_start[0].release_start_age, 20)
        self.assertEqual(by_start[10].release_start_age, -1)
        self.assertEqual(by_start[20].release_start_age, -1)

        self.engine._voices.clear()
        first_track.instance_limit_global = True
        other_track.instance_limit_global = True
        self.engine._start_event(first_track)
        self.engine._start_event(other_track)
        by_start = {voice.start_frame: voice for voice in self.engine._voices}
        self.assertEqual(by_start[0].release_start_age, 10)
        self.assertEqual(by_start[10].release_start_age, -1)

    def test_sample_preparation_preserves_authored_relative_loudness(self) -> None:
        quiet = np.full((4096, 2), 0.02, dtype=np.float32)
        loud = np.full((4096, 2), 0.80, dtype=np.float32)
        quiet_matched, quiet_gain = normalise_sample_loudness(quiet)
        loud_matched, loud_gain = normalise_sample_loudness(loud)
        self.assertEqual(quiet_gain, 1.0)
        self.assertEqual(loud_gain, 1.0)
        self.assertAlmostEqual(
            float(np.max(np.abs(loud_matched)))
            / float(np.max(np.abs(quiet_matched))),
            40.0,
            places=4,
        )
        over_range = np.full((64, 2), 2.0, dtype=np.float32)
        protected, protected_gain = normalise_sample_loudness(over_range)
        self.assertLess(protected_gain, 1.0)
        self.assertLessEqual(float(np.max(np.abs(protected))), 1.0)

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
        # These values select native Wwise Events/layers rather than fallback
        # envelope DSP. Type 99 is the canonical BDO drum-set route.
        event_routes = {9, 10, 14, 99}
        for instrument_id, definitions in BDO_ARTICULATIONS.items():
            for ntype, _label in definitions:
                if ntype == 0 or (instrument_id, ntype) in basic_aliases or ntype in event_routes:
                    continue
                envelope = articulation_preview_envelope(
                    instrument_id, ntype, ages, 4096, 48_000
                )
                self.assertTrue(
                    np.isfinite(envelope).all(),
                    f"0x{instrument_id:02x}/type {ntype} produced non-finite DSP",
                )
                self.assertFalse(
                    np.allclose(envelope, 1.0),
                    f"0x{instrument_id:02x}/type {ntype} has no preview processing",
                )

    def test_every_declared_articulation_has_a_bounded_lifecycle(self) -> None:
        sample_frames = 48_000 * 6
        for instrument_id, definitions in BDO_ARTICULATIONS.items():
            for ntype, _label in definitions:
                ratio = 2.0 if ntype == 14 else 1.0
                lifecycle = voice_lifecycle(
                    instrument_id,
                    ntype,
                    12_000,
                    sample_output_frames(sample_frames, ratio),
                    48_000,
                )
                self.assertGreater(
                    lifecycle.audible_frames,
                    0,
                    f"0x{instrument_id:02x}/type {ntype}",
                )
                self.assertLessEqual(
                    lifecycle.audible_frames,
                    sample_output_frames(sample_frames, ratio),
                    f"0x{instrument_id:02x}/type {ntype}",
                )
                self.assertLessEqual(
                    lifecycle.fade_out_frames,
                    lifecycle.audible_frames,
                    f"0x{instrument_id:02x}/type {ntype}",
                )


if __name__ == "__main__":
    unittest.main()
