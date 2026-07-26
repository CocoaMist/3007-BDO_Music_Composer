from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import tracemalloc
import unittest
from unittest.mock import patch

import numpy as np

import bdo_transcription
from bdo_transcription import (
    BasicPitchTranscriptionBackend,
    EvidenceDescriptor,
    FRAME_THRESHOLD,
    LEGACY_TRANSCRIPTION_CLEANUP_PROFILE,
    LEGACY_TRANSCRIPTION_POSTPROCESS_VERSION,
    ONSET_THRESHOLD,
    POSTPROCESS_VERSION,
    TranscriptionBackend,
    TranscriptionCancelled,
    TranscriptionCandidate,
    TranscriptionError,
    TranscriptionResult,
    blockwise_harmonic_signal,
    fuse_transcription_evidence,
    _candidates_from_basic_pitch,
    _load_cached_result,
    _write_cached_result,
    basic_pitch_frame_times_ms,
    load_cached_transcription_result,
    load_transcription_evidence,
    load_transcription_evidence_descriptor,
    load_transcription_frame_times,
    prune_transcription_cache,
    redecode_transcription_full,
    redecode_transcription_interval,
    transcription_audio_fingerprint,
    transcription_backend_message,
    transcription_backend_quick_status,
    transcription_backend_status,
    transcription_candidate_id,
    transcription_cache_key,
    transcription_min_note_length_frames,
    transcription_thresholds,
    transcribe_reference_audio,
)


class BdoTranscriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        bdo_transcription._clear_transcription_backend_status_cache()

    def tearDown(self) -> None:
        bdo_transcription._clear_transcription_backend_status_cache()

    def _write_synthetic_cache(
        self,
        audio: Path,
        cache_root: Path,
        *,
        frame_count: int = 240,
        output: dict[str, np.ndarray] | None = None,
        candidates: tuple[TranscriptionCandidate, ...] = (),
        analysis_mode: str = "standard",
    ) -> tuple[TranscriptionResult, EvidenceDescriptor, np.ndarray]:
        if output is None:
            output = {
                "note": np.zeros((frame_count, 88), dtype=np.float32),
                "onset": np.zeros((frame_count, 88), dtype=np.float32),
                "contour": np.zeros((frame_count, 264), dtype=np.float32),
            }
        times_ms = np.arange(frame_count, dtype=np.float64) * 10.0
        result = TranscriptionResult(
            candidates,
            transcription_cache_key(
                audio,
                analysis_mode=analysis_mode,
            ),
            ("frame", "onset", "contour"),
        )
        descriptor = _write_cached_result(
            result,
            output,
            cache_root,
            frame_times_ms=times_ms,
            duration_ms=float(times_ms[-1] + 10.0),
            audio_fingerprint=transcription_audio_fingerprint(audio),
            analysis_mode=analysis_mode,
        )
        return result, descriptor, times_ms

    def test_missing_backend_has_source_and_frozen_specific_guidance(self) -> None:
        with patch(
            "bdo_transcription.importlib.util.find_spec",
            return_value=None,
        ):
            available, source_message = transcription_backend_status()
            self.assertFalse(available)
            self.assertIn("扒谱组件", source_message)
            self.assertNotIn("\ufffd", source_message)
            self.assertIn("install_transcription.ps1", source_message)
            with patch("bdo_transcription.sys.frozen", True, create=True):
                frozen_message = transcription_backend_message()
            self.assertIn("本地扒谱引擎未能加载", frozen_message)
            self.assertNotIn("\ufffd", frozen_message)
            self.assertIn("完整程序", frozen_message)
            self.assertNotIn("install_transcription.ps1", frozen_message)

    def test_quick_backend_status_does_not_import_heavy_runtime(self) -> None:
        with (
            patch(
                "bdo_transcription.importlib.util.find_spec",
                return_value=SimpleNamespace(),
            ) as find_spec,
            patch(
                "bdo_transcription._import_basic_pitch",
                side_effect=AssertionError("quick probe must not import"),
            ),
        ):
            self.assertEqual(transcription_backend_quick_status(), (True, ""))
        self.assertEqual(find_spec.call_count, 3)

    def test_transitive_backend_import_failure_is_not_install_guidance(
        self,
    ) -> None:
        missing_transitive = ModuleNotFoundError(
            "No module named 'unittest'",
            name="unittest",
        )
        self.assertEqual(
            bdo_transcription._backend_import_failure_message(
                missing_transitive
            ),
            bdo_transcription.BACKEND_MODULE_LOAD_FAILED_MESSAGE,
        )
        failure = TranscriptionError(
            bdo_transcription.BACKEND_MODULE_LOAD_FAILED_MESSAGE
        )
        with (
            patch(
                "bdo_transcription.importlib.util.find_spec",
                return_value=SimpleNamespace(),
            ),
            patch(
                "bdo_transcription._import_basic_pitch",
                side_effect=failure,
            ),
            self.assertLogs("bdo_transcription", level="WARNING") as logs,
        ):
            available, message = transcription_backend_status()
        self.assertFalse(available)
        self.assertEqual(
            message,
            bdo_transcription.BACKEND_MODULE_LOAD_FAILED_MESSAGE,
        )
        self.assertNotIn("install_transcription.ps1", message)
        self.assertIn("TranscriptionError", "\n".join(logs.output))

    def test_full_backend_status_is_cached_after_cold_check(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            model_path = Path(folder_name) / "nmp.onnx"
            model_path.write_bytes(b"model")
            fake_basic_pitch = SimpleNamespace(
                ONNX_PRESENT=True,
                FilenameSuffix=SimpleNamespace(onnx="onnx"),
                build_icassp_2022_model_path=lambda _suffix: model_path,
            )
            fake_onnxruntime = SimpleNamespace(
                get_available_providers=lambda: ["CPUExecutionProvider"]
            )
            imported = (
                fake_basic_pitch,
                SimpleNamespace(),
                SimpleNamespace(),
                fake_onnxruntime,
            )
            with (
                patch(
                    "bdo_transcription.importlib.util.find_spec",
                    return_value=SimpleNamespace(),
                ),
                patch(
                    "bdo_transcription._import_basic_pitch",
                    return_value=imported,
                ) as import_backend,
            ):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    statuses = tuple(
                        pool.map(
                            lambda _index: transcription_backend_status(),
                            range(16),
                        )
                    )
                self.assertEqual(statuses, ((True, ""),) * 16)
                self.assertEqual(transcription_backend_status(), (True, ""))
            import_backend.assert_called_once_with()

    def test_basic_pitch_notes_become_non_authoritative_candidates(self) -> None:
        notes = [
            SimpleNamespace(pitch=60, velocity=96, start=0.1, end=0.5),
            SimpleNamespace(pitch=64, velocity=80, start=0.6, end=1.25),
        ]
        midi = SimpleNamespace(instruments=[SimpleNamespace(notes=notes)])
        result = _candidates_from_basic_pitch(
            midi,
            [
                (0.1, 0.5, 60, 0.42, None),
                (0.6, 1.25, 64, 0.91, None),
            ],
        )
        self.assertEqual(
            result[0],
            TranscriptionCandidate(60, 96, 100.0, 400.0, 0.42),
        )
        self.assertEqual(result[1].source, "basic-pitch")
        self.assertAlmostEqual(result[1].confidence, 0.91)

    def test_same_pitch_events_are_matched_once_by_time(self) -> None:
        notes = [
            SimpleNamespace(pitch=60, velocity=80, start=0.1, end=0.3),
            SimpleNamespace(pitch=60, velocity=100, start=0.8, end=1.2),
        ]
        midi = SimpleNamespace(instruments=[SimpleNamespace(notes=notes)])
        result = _candidates_from_basic_pitch(
            midi,
            [
                (0.8, 1.2, 60, 0.87, None),
                (0.1, 0.3, 60, 0.41, None),
            ],
        )
        self.assertEqual(
            [round(candidate.confidence, 2) for candidate in result],
            [0.41, 0.87],
        )

    def test_candidate_id_is_stable_without_breaking_legacy_values(self) -> None:
        legacy = TranscriptionCandidate(60, 96, 100.0, 400.0, 0.42)
        cache_key = "a" * 24
        identifier = transcription_candidate_id(cache_key, legacy)
        identified = TranscriptionCandidate(
            60,
            96,
            100.0,
            400.0,
            0.42,
            candidate_id=identifier,
        )
        self.assertEqual(legacy, identified)
        self.assertEqual(
            identifier,
            transcription_candidate_id(cache_key, identified),
        )
        changed = legacy.__class__(
            60,
            97,
            100.0,
            400.0,
            0.42,
        )
        self.assertNotEqual(
            identifier,
            transcription_candidate_id(cache_key, changed),
        )

    def test_cache_key_is_independent_from_decode_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            audio = Path(folder_name) / "reference.wav"
            audio.write_bytes(b"audio")
            first = transcription_cache_key(audio)
            with (
                patch("bdo_transcription.ONSET_THRESHOLD", 0.99),
                patch("bdo_transcription.FRAME_THRESHOLD", 0.01),
            ):
                second = transcription_cache_key(audio)
            self.assertEqual(first, second)

    def test_cache_key_isolated_by_analysis_mode(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            audio = Path(folder_name) / "reference.wav"
            audio.write_bytes(b"audio")
            standard = transcription_cache_key(
                audio,
                analysis_mode="standard",
            )
            enhanced = transcription_cache_key(
                audio,
                analysis_mode="mixed_enhanced",
            )
            self.assertNotEqual(standard, enhanced)
            self.assertEqual(len(standard), 24)
            self.assertEqual(len(enhanced), 24)

    def test_blockwise_hpss_preserves_samples_across_overlap(self) -> None:
        audio = np.linspace(-1.0, 1.0, 95, dtype=np.float32)
        block_lengths: list[int] = []
        progress: list[int] = []

        def separator(block: np.ndarray) -> np.ndarray:
            block_lengths.append(block.size)
            return block * 0.5

        harmonic = blockwise_harmonic_signal(
            audio,
            10,
            block_seconds=3.0,
            overlap_seconds=0.5,
            harmonic_separator=separator,
            progress=progress.append,
        )

        self.assertEqual(harmonic.shape, audio.shape)
        np.testing.assert_allclose(harmonic, audio * 0.5, atol=1e-6)
        self.assertGreater(len(block_lengths), 1)
        self.assertTrue(all(length <= 30 for length in block_lengths))
        self.assertEqual(progress[-1], 100)

    def test_blockwise_hpss_honours_cancellation_between_blocks(self) -> None:
        calls = 0

        def separator(block: np.ndarray) -> np.ndarray:
            nonlocal calls
            calls += 1
            return block

        with self.assertRaises(TranscriptionCancelled):
            blockwise_harmonic_signal(
                np.ones(100, dtype=np.float32),
                10,
                block_seconds=2.0,
                overlap_seconds=0.5,
                harmonic_separator=separator,
                cancelled=lambda: calls >= 2,
            )
        self.assertEqual(calls, 2)

    def test_stream_window_iterator_matches_basic_pitch_padding_contract(
        self,
    ) -> None:
        audio = np.arange(25, dtype=np.float32)
        inference = SimpleNamespace(
            AUDIO_N_SAMPLES=16,
            AUDIO_SAMPLE_RATE=8,
        )
        overlap_len = 4
        hop_size = 12
        padded = np.concatenate(
            (
                np.zeros(overlap_len // 2, dtype=np.float32),
                audio,
            )
        )
        expected: list[tuple[np.ndarray, dict[str, float], int]] = []
        for start in range(0, padded.size, hop_size):
            window = padded[start : start + inference.AUDIO_N_SAMPLES]
            window = np.pad(
                window,
                (0, inference.AUDIO_N_SAMPLES - window.size),
            )
            expected.append(
                (
                    window.reshape(1, inference.AUDIO_N_SAMPLES, 1),
                    {
                        "start": start / inference.AUDIO_SAMPLE_RATE,
                        "end": (
                            start + inference.AUDIO_N_SAMPLES
                        )
                        / inference.AUDIO_SAMPLE_RATE,
                    },
                    audio.size,
                )
            )

        actual = list(
            bdo_transcription._signal_audio_input(
                audio,
                inference,
                overlap_len,
                hop_size,
            )
        )

        self.assertEqual(len(actual), len(expected))
        for actual_window, expected_window in zip(actual, expected):
            np.testing.assert_array_equal(
                actual_window[0],
                expected_window[0],
            )
            self.assertEqual(actual_window[1:], expected_window[1:])

    def test_stream_decode_resamples_stereo_without_full_audio_copy(
        self,
    ) -> None:
        import soundfile
        import soxr

        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio_path = root / "stereo.wav"
            source_rate = 44_100
            target_rate = 22_050
            samples = np.arange(44_101, dtype=np.float32)
            left = np.sin(samples * (2.0 * np.pi * 440.0 / source_rate))
            right = left * 0.5
            soundfile.write(
                audio_path,
                np.column_stack((left, right)),
                source_rate,
                subtype="FLOAT",
            )
            cache_root = root / "cache"
            with bdo_transcription._transcription_workspace(
                cache_root
            ) as workspace:
                streamed = (
                    bdo_transcription._stream_decode_reference_audio(
                        audio_path,
                        workspace,
                        target_sample_rate=target_rate,
                    )
                )
                decoded = streamed.open()
                try:
                    expected = soxr.resample(
                        (left + right) * 0.5,
                        source_rate,
                        target_rate,
                        quality="HQ",
                    )
                    self.assertEqual(decoded.dtype, np.dtype("float32"))
                    np.testing.assert_allclose(
                        decoded,
                        expected,
                        rtol=0.0,
                        atol=2e-7,
                    )
                finally:
                    bdo_transcription._close_memmap(decoded)
                workspace_path = workspace
            self.assertFalse(workspace_path.exists())

    def test_stream_hpss_preserves_boundaries_and_cleans_weights(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            workspace = Path(folder_name)
            audio = np.linspace(-1.0, 1.0, 95, dtype=np.float32)
            source_path = workspace / "source.f32"
            source_path.write_bytes(audio.astype("<f4").tobytes())
            source = bdo_transcription._StreamedAudioBuffer(
                source_path,
                audio.size,
                10,
            )
            block_lengths: list[int] = []

            def separator(block: np.ndarray) -> np.ndarray:
                block_lengths.append(block.size)
                return block * 0.5

            harmonic = bdo_transcription._stream_harmonic_audio(
                source,
                workspace,
                librosa_module=SimpleNamespace(),
                block_seconds=3.0,
                overlap_seconds=0.5,
                harmonic_separator=separator,
            )
            mapped = harmonic.open()
            try:
                np.testing.assert_allclose(
                    mapped,
                    audio * 0.5,
                    atol=1e-6,
                )
            finally:
                bdo_transcription._close_memmap(mapped)
            self.assertGreater(len(block_lengths), 1)
            self.assertTrue(all(length <= 30 for length in block_lengths))
            self.assertFalse(
                (workspace / "harmonic-weights.f32").exists()
            )

    def test_fast_hpss_parameters_are_fixed(self) -> None:
        calls: list[dict[str, object]] = []

        def harmonic(block: np.ndarray, **kwargs):
            calls.append(kwargs)
            return block

        audio = np.ones(32, dtype=np.float32)
        actual = bdo_transcription._fast_harmonic_separator(
            SimpleNamespace(
                effects=SimpleNamespace(harmonic=harmonic)
            ),
            audio,
        )

        np.testing.assert_array_equal(actual, audio)
        self.assertEqual(
            calls,
            [
                {
                    "n_fft": 1024,
                    "hop_length": 512,
                    "kernel_size": 9,
                    "power": 2.0,
                    "margin": 1.0,
                }
            ],
        )

    def test_stream_evidence_fuses_each_pair_into_one_float16_timeline(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            original = np.linspace(-1.0, 1.0, 24, dtype=np.float32)
            harmonic = original * 0.5
            inference = SimpleNamespace(
                AUDIO_N_SAMPLES=16,
                AUDIO_SAMPLE_RATE=8,
                ANNOTATIONS_FPS=4,
            )
            predict_calls = 0

            def predict(_window):
                nonlocal predict_calls
                pair_index = predict_calls // 2
                harmonic_route = predict_calls % 2
                predict_calls += 1
                value = (
                    (0.1 + pair_index * 0.1)
                    if harmonic_route == 0
                    else (0.9 - pair_index * 0.1)
                )
                return {
                    "note": np.full(
                        (1, 8, 88),
                        value,
                        dtype=np.float32,
                    ),
                    "onset": np.full(
                        (1, 8, 88),
                        value,
                        dtype=np.float32,
                    ),
                    "contour": np.full(
                        (1, 8, 264),
                        value,
                        dtype=np.float32,
                    ),
                }

            evidence, original_length = (
                bdo_transcription._stream_basic_pitch_evidence(
                    original,
                    SimpleNamespace(predict=predict),
                    inference,
                    Path(folder_name),
                    harmonic=harmonic,
                    overlapping_frames=2,
                    overlap_len=4,
                    hop_size=12,
                    frame_harmonic_weight=0.75,
                    onset_harmonic_weight=0.25,
                    contour_harmonic_weight=0.50,
                )
            )
            try:
                self.assertEqual(original_length, original.size)
                self.assertEqual(predict_calls, 4)
                self.assertEqual(
                    set(evidence),
                    {"note", "onset", "contour"},
                )
                self.assertEqual(evidence["note"].dtype, np.dtype("float16"))
                expected_note = np.repeat(
                    np.array((0.70, 0.65), dtype=np.float16),
                    6,
                )
                expected_onset = np.repeat(
                    np.array((0.30, 0.35), dtype=np.float16),
                    6,
                )
                expected_contour = np.repeat(
                    np.array((0.50, 0.50), dtype=np.float16),
                    6,
                )
                np.testing.assert_array_equal(
                    evidence["note"][:, 0],
                    expected_note,
                )
                np.testing.assert_array_equal(
                    evidence["onset"][:, 0],
                    expected_onset,
                )
                np.testing.assert_array_equal(
                    evidence["contour"][:, 0],
                    expected_contour,
                )
                self.assertFalse(
                    (Path(folder_name) / "original-note.npy").exists()
                )
                self.assertFalse(
                    (Path(folder_name) / "harmonic-note.npy").exists()
                )
            finally:
                for array in evidence.values():
                    bdo_transcription._close_memmap(array)

    def test_stream_evidence_is_elementwise_equal_to_unwrapped_windows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            audio = np.linspace(-0.5, 0.5, 24, dtype=np.float32)

            def unwrap_output(
                values: np.ndarray,
                original_length: int,
                overlapping_frames: int,
            ) -> np.ndarray:
                trim = overlapping_frames // 2
                trimmed = values[:, trim:-trim, :]
                frame_count = int(
                    np.floor(original_length * (4.0 / 8.0))
                )
                return trimmed.reshape(
                    -1,
                    trimmed.shape[-1],
                )[:frame_count]

            inference = SimpleNamespace(
                AUDIO_N_SAMPLES=16,
                AUDIO_SAMPLE_RATE=8,
                ANNOTATIONS_FPS=4,
                unwrap_output=unwrap_output,
            )

            def predict(window: np.ndarray) -> dict[str, np.ndarray]:
                base = np.float32(np.mean(window) + 0.5)
                time_values = (
                    base
                    + np.arange(8, dtype=np.float32) / 100.0
                ).reshape(1, 8, 1)
                return {
                    "note": np.broadcast_to(
                        time_values,
                        (1, 8, 88),
                    ).copy(),
                    "onset": np.broadcast_to(
                        time_values * 0.8,
                        (1, 8, 88),
                    ).copy(),
                    "contour": np.broadcast_to(
                        time_values * 0.6,
                        (1, 8, 264),
                    ).copy(),
                }

            expected, _length = (
                bdo_transcription._predict_basic_pitch_windows(
                    bdo_transcription._signal_audio_input(
                        audio,
                        inference,
                        4,
                        12,
                    ),
                    SimpleNamespace(predict=predict),
                    inference,
                    overlapping_frames=2,
                    overlap_len=4,
                    hop_size=12,
                )
            )
            actual, _length = (
                bdo_transcription._stream_basic_pitch_evidence(
                    audio,
                    SimpleNamespace(predict=predict),
                    inference,
                    Path(folder_name),
                    overlapping_frames=2,
                    overlap_len=4,
                    hop_size=12,
                )
            )
            try:
                for layer in ("note", "onset", "contour"):
                    np.testing.assert_array_equal(
                        actual[layer],
                        np.asarray(expected[layer], dtype=np.float16),
                    )
            finally:
                for array in actual.values():
                    bdo_transcription._close_memmap(array)

    def test_stream_evidence_cancellation_closes_partial_maps(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            calls = 0

            def predict(_window):
                nonlocal calls
                calls += 1
                bins = {
                    "note": 88,
                    "onset": 88,
                    "contour": 264,
                }
                return {
                    key: np.zeros((1, 8, value), dtype=np.float32)
                    for key, value in bins.items()
                }

            with self.assertRaises(TranscriptionCancelled):
                bdo_transcription._stream_basic_pitch_evidence(
                    np.ones(48, dtype=np.float32),
                    SimpleNamespace(predict=predict),
                    SimpleNamespace(
                        AUDIO_N_SAMPLES=16,
                        AUDIO_SAMPLE_RATE=8,
                        ANNOTATIONS_FPS=4,
                    ),
                    Path(folder_name),
                    harmonic=np.ones(48, dtype=np.float32),
                    overlapping_frames=2,
                    overlap_len=4,
                    hop_size=12,
                    cancelled=lambda: calls >= 2,
                )
            self.assertEqual(calls, 2)
            for path in Path(folder_name).glob("evidence-*.npy"):
                path.unlink()
            self.assertFalse(
                tuple(Path(folder_name).glob("evidence-*.npy"))
            )

    def test_long_stream_evidence_keeps_intermediate_heap_bounded(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            workspace = Path(folder_name)
            sample_rate = 22_050
            sample_count = sample_rate * 180
            source_path = workspace / "long-source.f32"
            with source_path.open("wb") as stream:
                stream.seek(sample_count * 4 - 1)
                stream.write(b"\0")
            source = np.memmap(
                source_path,
                dtype=np.dtype("<f4"),
                mode="r",
                shape=(sample_count,),
            )
            prediction = {
                "note": np.zeros((1, 172, 88), dtype=np.float32),
                "onset": np.zeros((1, 172, 88), dtype=np.float32),
                "contour": np.zeros((1, 172, 264), dtype=np.float32),
            }
            inference = SimpleNamespace(
                AUDIO_N_SAMPLES=43_844,
                AUDIO_SAMPLE_RATE=sample_rate,
                ANNOTATIONS_FPS=86,
            )
            tracemalloc.start()
            try:
                evidence, original_length = (
                    bdo_transcription._stream_basic_pitch_evidence(
                        source,
                        SimpleNamespace(
                            predict=lambda _window: prediction
                        ),
                        inference,
                        workspace,
                        overlapping_frames=30,
                        overlap_len=30 * 256,
                        hop_size=43_844 - 30 * 256,
                    )
                )
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
                bdo_transcription._close_memmap(source)
            try:
                self.assertEqual(original_length, sample_count)
                self.assertEqual(
                    evidence["note"].shape[0],
                    int(np.floor(180 * 86)),
                )
                self.assertLess(peak, 12 * 1024**2)
                evidence_bytes = sum(
                    path.stat().st_size
                    for path in workspace.glob("evidence-*.npy")
                )
                self.assertGreater(evidence_bytes, 10 * 1024**2)
            finally:
                for array in evidence.values():
                    bdo_transcription._close_memmap(array)

    def test_abandoned_stream_workspaces_are_pruned_guardedly(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            cache_root = Path(folder_name)
            stale = cache_root / ".transcription-work-abcdefgh"
            stale.mkdir()
            (stale / "audio.f32").write_bytes(b"temporary")
            os.utime(stale, (0, 0))
            unknown = cache_root / "do-not-delete"
            unknown.mkdir()
            symlink = cache_root / ".transcription-work-ijklmnop"
            try:
                symlink.symlink_to(unknown, target_is_directory=True)
            except OSError:
                symlink = None

            removed = bdo_transcription.prune_transcription_workspaces(
                cache_root,
                stale_seconds=1.0,
            )

            self.assertEqual(removed, 1)
            self.assertFalse(stale.exists())
            self.assertTrue(unknown.is_dir())
            if symlink is not None:
                self.assertTrue(symlink.is_symlink())

    def test_stream_workspace_cleans_on_cancellation_and_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            cache_root = Path(folder_name)
            for exception in (
                TranscriptionCancelled("cancelled"),
                RuntimeError("failed"),
            ):
                with (
                    self.subTest(exception=type(exception).__name__),
                    self.assertRaises(type(exception)),
                ):
                    with bdo_transcription._transcription_workspace(
                        cache_root
                    ) as workspace:
                        (workspace / "audio.f32").write_bytes(b"temporary")
                        raise exception
                self.assertFalse(
                    tuple(
                        cache_root.glob(".transcription-work-*")
                    )
                )

    def test_evidence_fusion_preserves_timeline_and_range(self) -> None:
        original = {
            "note": np.full((4, 88), 0.2, dtype=np.float32),
            "onset": np.full((4, 88), 0.9, dtype=np.float32),
            "contour": np.full((4, 264), 0.1, dtype=np.float32),
        }
        harmonic = {
            "note": np.full((4, 88), 1.0, dtype=np.float32),
            "onset": np.full((4, 88), 0.1, dtype=np.float32),
            "contour": np.full((4, 264), 0.7, dtype=np.float32),
        }

        fused = fuse_transcription_evidence(
            original,
            harmonic,
            frame_harmonic_weight=0.75,
            onset_harmonic_weight=0.25,
            contour_harmonic_weight=0.5,
        )

        self.assertEqual(fused["note"].shape, (4, 88))
        self.assertEqual(fused["onset"].shape, (4, 88))
        self.assertEqual(fused["contour"].shape, (4, 264))
        np.testing.assert_allclose(fused["note"], 0.8, atol=1e-7)
        np.testing.assert_allclose(fused["onset"], 0.7, atol=1e-7)
        np.testing.assert_allclose(fused["contour"], 0.4, atol=1e-7)
        self.assertGreaterEqual(min(np.min(value) for value in fused.values()), 0)
        self.assertLessEqual(max(np.max(value) for value in fused.values()), 1)

    def test_audio_identity_depends_on_bytes_not_path_or_file_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            first_path = root / "first.wav"
            moved_path = root / "moved.wav"
            original = b"abcdefgh"
            replacement = b"ABCDEFGH"
            first_path.write_bytes(original)
            moved_path.write_bytes(original)
            first_stat = first_path.stat()

            first_fingerprint = transcription_audio_fingerprint(first_path)
            self.assertEqual(
                first_fingerprint,
                transcription_audio_fingerprint(moved_path),
            )
            self.assertEqual(
                transcription_cache_key(first_path),
                transcription_cache_key(moved_path),
            )

            first_path.write_bytes(replacement)
            os.utime(
                first_path,
                ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns),
            )
            self.assertEqual(first_path.stat().st_size, len(original))
            self.assertNotEqual(
                first_fingerprint,
                transcription_audio_fingerprint(first_path),
            )
            self.assertNotEqual(
                transcription_cache_key(first_path),
                transcription_cache_key(moved_path),
            )

    def test_frame_time_helper_uses_backend_window_mapping(self) -> None:
        expected_seconds = np.arange(174, dtype=np.float64) * 0.01
        expected_seconds[172:] -= 0.008
        calls: list[int] = []

        def model_frames_to_time(frame_count: int) -> np.ndarray:
            calls.append(frame_count)
            return expected_seconds

        actual = basic_pitch_frame_times_ms(
            174,
            note_creation=SimpleNamespace(
                model_frames_to_time=model_frames_to_time
            ),
        )
        self.assertEqual(calls, [174])
        np.testing.assert_allclose(actual, expected_seconds * 1000.0)
        self.assertNotAlmostEqual(actual[172] - actual[171], 10.0)

    def test_backend_protocol_and_sensitivity_contract(self) -> None:
        backend = BasicPitchTranscriptionBackend()
        self.assertIsInstance(backend, TranscriptionBackend)
        self.assertTrue(
            bdo_transcription.MIXED_ENHANCED_RELEASE_DEFAULT_VERIFIED
        )
        self.assertEqual(
            bdo_transcription.DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
            "mixed_enhanced",
        )
        self.assertEqual(
            transcription_thresholds("conservative"),
            (0.65, 0.45),
        )
        self.assertEqual(
            transcription_thresholds("balanced"),
            (ONSET_THRESHOLD, FRAME_THRESHOLD),
        )
        self.assertEqual(
            transcription_thresholds("sensitive"),
            (0.35, 0.20),
        )
        self.assertEqual(
            transcription_thresholds(
                "conservative",
                "mixed_enhanced",
            ),
            (0.70, 0.40),
        )
        self.assertEqual(
            transcription_thresholds(
                "balanced",
                "mixed_enhanced",
            ),
            (0.55, 0.25),
        )
        self.assertEqual(
            transcription_thresholds(
                "sensitive",
                "mixed_enhanced",
            ),
            (0.40, 0.15),
        )
        self.assertEqual(
            tuple(
                transcription_min_note_length_frames(
                    sensitivity,
                    "mixed_enhanced",
                )
                for sensitivity in (
                    "conservative",
                    "balanced",
                    "sensitive",
                )
            ),
            (8, 5, 2),
        )
        with self.assertRaises(ValueError):
            transcription_thresholds("unknown")

    def test_cache_roundtrip_uses_memory_mapped_evidence_and_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"first")
            cache_root = root / "cache"
            cache_key = transcription_cache_key(audio)
            result = TranscriptionResult(
                (TranscriptionCandidate(69, 88, 10.0, 500.0, 0.75),),
                cache_key,
                ("frame", "onset", "contour"),
            )
            output = {
                # The real Basic Pitch 0.4 ONNX output calls this matrix
                # ``note``; the cache exposes the stable public name ``frame``.
                "note": np.ones((12, 88), dtype=np.float32),
                "onset": np.ones((12, 88), dtype=np.float32) * 0.5,
                "contour": np.ones((12, 264), dtype=np.float32) * 0.25,
            }
            times_ms = np.arange(12, dtype=np.float64) * 11.609977
            descriptor = _write_cached_result(
                result,
                output,
                cache_root,
                frame_times_ms=times_ms,
                duration_ms=600.0,
                audio_fingerprint=transcription_audio_fingerprint(audio),
            )

            cached = _load_cached_result(audio, cache_root)
            self.assertIsNotNone(cached)
            self.assertTrue(cached.cache_hit)
            self.assertEqual(cached.candidates, result.candidates)
            self.assertIsInstance(
                cached.evidence_descriptor,
                EvidenceDescriptor,
            )
            self.assertEqual(cached.evidence_descriptor, descriptor)
            self.assertEqual(descriptor.layer("contour").bins_per_semitone, 3)
            self.assertEqual(descriptor.midi_min, 21)
            self.assertTrue(cached.candidates[0].candidate_id)
            self.assertEqual(
                load_transcription_evidence_descriptor(
                    cache_key,
                    cache_root=cache_root,
                ),
                descriptor,
            )
            self.assertEqual(
                load_cached_transcription_result(
                    cache_key,
                    cache_root=cache_root,
                ),
                cached,
            )
            evidence = load_transcription_evidence(
                cache_key, "contour", cache_root=cache_root
            )
            self.assertIsInstance(evidence, np.memmap)
            self.assertEqual(evidence.shape, (12, 264))
            evidence._mmap.close()
            del evidence
            frame = load_transcription_evidence(
                cache_key, "frame", cache_root=cache_root
            )
            self.assertIsInstance(frame, np.memmap)
            self.assertEqual(frame.shape, (12, 88))
            frame._mmap.close()
            del frame
            times = load_transcription_frame_times(
                cache_key,
                cache_root=cache_root,
            )
            self.assertIsInstance(times, np.memmap)
            np.testing.assert_allclose(times, times_ms)
            times._mmap.close()
            del times
            with patch(
                "bdo_transcription.transcription_backend_status",
                return_value=(False, "backend unavailable"),
            ):
                cache_only = transcribe_reference_audio(
                    audio,
                    cache_root=cache_root,
                )
            self.assertTrue(cache_only.cache_hit)
            self.assertEqual(cache_only.candidates, result.candidates)

            audio.write_bytes(b"changed-size")
            self.assertIsNone(_load_cached_result(audio, cache_root))

    def test_cached_load_rehashes_audio_after_evidence_validation(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"first-audio")
            cache_root = root / "cache"
            _result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            initial_fingerprint = transcription_audio_fingerprint(audio)
            original_reader = bdo_transcription._read_valid_cache_entry

            def mutate_after_validation(*args, **kwargs):
                cached = original_reader(*args, **kwargs)
                audio.write_bytes(b"other-audio")
                return cached

            with patch(
                "bdo_transcription._read_valid_cache_entry",
                side_effect=mutate_after_validation,
            ):
                self.assertIsNone(
                    _load_cached_result(
                        audio,
                        cache_root,
                        audio_fingerprint=initial_fingerprint,
                    )
                )

    def test_cache_validation_hash_honours_cooperative_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
                frame_count=12_000,
            )
            with bdo_transcription._CACHE_VALIDATION_LOCK:
                bdo_transcription._VALIDATED_CACHE_ENTRIES.clear()
            cancel_requested = threading.Event()
            original_hash = bdo_transcription._sha256_file

            def cancel_during_hash(path, *, cancelled=None):
                cancel_requested.set()
                return original_hash(path, cancelled=cancelled)

            with (
                patch(
                    "bdo_transcription._sha256_file",
                    side_effect=cancel_during_hash,
                ),
                self.assertRaises(TranscriptionCancelled),
            ):
                load_cached_transcription_result(
                    result.cache_key,
                    cache_root=cache_root,
                    cancelled=cancel_requested.is_set,
                )

    def test_atomic_npy_publication_cancels_between_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            target = Path(folder_name) / "evidence.npy"
            calls = 0

            def cancelled() -> bool:
                nonlocal calls
                calls += 1
                return calls >= 3

            with self.assertRaises(TranscriptionCancelled):
                bdo_transcription._write_npy_atomic(
                    target,
                    np.zeros(2_100_000, dtype=np.float16),
                    cancelled=cancelled,
                )

            self.assertFalse(target.exists())
            self.assertFalse(
                target.with_name(f"{target.name}.tmp").exists()
            )

    def test_source_change_after_inference_prevents_cache_write(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            audio = Path(folder_name) / "reference.wav"
            audio.write_bytes(b"audio")
            frame = np.zeros((4, 88), dtype=np.float32)
            onset = np.zeros((4, 88), dtype=np.float32)
            contour = np.zeros((4, 264), dtype=np.float32)
            fake_inference = SimpleNamespace(
                FFT_HOP=2,
                AUDIO_N_SAMPLES=16,
                AUDIO_SAMPLE_RATE=8_000,
                get_audio_input=lambda *_args: iter(
                    ((np.zeros(16, dtype=np.float32), 0.0, 16),)
                ),
                unwrap_output=lambda values, *_args: values,
            )
            fake_note_creation = SimpleNamespace(
                model_output_to_notes=lambda *_args, **_kwargs: (
                    SimpleNamespace(instruments=[]),
                    (),
                )
            )
            fake_model = SimpleNamespace(
                predict=lambda _window: {
                    "note": frame,
                    "onset": onset,
                    "contour": contour,
                }
            )
            with (
                patch(
                    "bdo_transcription.transcription_audio_fingerprint",
                    side_effect=("1" * 64, "2" * 64),
                ),
                patch(
                    "bdo_transcription._load_cached_result",
                    return_value=None,
                ),
                patch(
                    "bdo_transcription.transcription_backend_status",
                    return_value=(True, ""),
                ),
                patch(
                    "bdo_transcription._import_basic_pitch",
                    return_value=(
                        SimpleNamespace(ONNX_PRESENT=True),
                        fake_inference,
                        fake_note_creation,
                        SimpleNamespace(),
                    ),
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    return_value=fake_model,
                ),
                patch(
                    "bdo_transcription._run_streamed_analysis",
                    return_value=(
                        {
                            "note": frame,
                            "onset": onset,
                            "contour": contour,
                        },
                        16,
                    ),
                ),
                patch(
                    "bdo_transcription._write_cached_result"
                ) as cache_writer,
                self.assertRaisesRegex(
                    bdo_transcription.TranscriptionError,
                    "changed during transcription",
                ),
            ):
                transcribe_reference_audio(
                    audio,
                    cache_root=Path(folder_name) / "cache",
                )
            cache_writer.assert_not_called()

    def test_mixed_mode_runs_original_and_harmonic_with_one_model(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            audio = Path(folder_name) / "reference.wav"
            audio.write_bytes(b"audio")
            frame = np.zeros((4, 88), dtype=np.float32)
            onset = np.zeros((4, 88), dtype=np.float32)
            contour = np.zeros((4, 264), dtype=np.float32)
            predict_calls = 0
            decode_kwargs: list[dict[str, object]] = []

            def predict(_window):
                nonlocal predict_calls
                predict_calls += 1
                return {
                    "note": frame,
                    "onset": onset,
                    "contour": contour,
                }

            def window_audio_file(signal, _hop):
                window = np.pad(
                    np.asarray(signal, dtype=np.float32),
                    (0, max(0, 16 - len(signal))),
                )[:16]
                yield np.expand_dims(window, -1), {
                    "start": 0.0,
                    "end": 1.0,
                }

            fake_librosa = SimpleNamespace(
                load=lambda *_args, **_kwargs: (
                    np.zeros(8, dtype=np.float32),
                    8,
                ),
                effects=SimpleNamespace(
                    harmonic=lambda block: np.asarray(block)
                ),
            )
            fake_inference = SimpleNamespace(
                FFT_HOP=2,
                AUDIO_N_SAMPLES=16,
                AUDIO_SAMPLE_RATE=8,
                librosa=fake_librosa,
                window_audio_file=window_audio_file,
                unwrap_output=lambda values, *_args: values,
            )

            def decode(*_args, **kwargs):
                decode_kwargs.append(kwargs)
                return []

            fake_note_creation = SimpleNamespace(
                output_to_notes_polyphonic=decode,
                model_frames_to_time=lambda count: (
                    np.arange(count, dtype=np.float64) * 0.1
                ),
            )

            def run_streamed(
                _path,
                model,
                _inference,
                _workspace,
                **_kwargs,
            ):
                model.predict(None)
                model.predict(None)
                return {
                    "note": frame,
                    "onset": onset,
                    "contour": contour,
                }, 8

            with (
                patch(
                    "bdo_transcription.transcription_audio_fingerprint",
                    return_value="1" * 64,
                ),
                patch(
                    "bdo_transcription._load_cached_result",
                    return_value=None,
                ),
                patch(
                    "bdo_transcription.transcription_backend_status",
                    return_value=(True, ""),
                ),
                patch(
                    "bdo_transcription._import_basic_pitch",
                    return_value=(
                        SimpleNamespace(ONNX_PRESENT=True),
                        fake_inference,
                        fake_note_creation,
                        SimpleNamespace(),
                    ),
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    return_value=SimpleNamespace(predict=predict),
                ),
                patch(
                    "bdo_transcription._run_streamed_analysis",
                    side_effect=run_streamed,
                ),
            ):
                result = transcribe_reference_audio(
                    audio,
                    analysis_mode="mixed_enhanced",
                    sensitivity="sensitive",
                    cache_root=Path(folder_name) / "cache",
                )

            self.assertEqual(result.candidates, ())
            self.assertEqual(predict_calls, 2)
            self.assertEqual(len(decode_kwargs), 1)
            self.assertEqual(decode_kwargs[0]["onset_thresh"], 0.40)
            self.assertEqual(decode_kwargs[0]["frame_thresh"], 0.15)
            self.assertEqual(decode_kwargs[0]["min_note_len"], 2)

    def test_initial_and_cached_decode_share_quantized_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"stable-audio")
            cache_root = root / "cache"
            frame = np.array(
                [
                    [0.12347] * 88,
                    [0.23458] * 88,
                    [0.34569] * 88,
                    [0.45671] * 88,
                ],
                dtype=np.float16,
            )
            onset = np.array(frame * np.float16(0.5), dtype=np.float16)
            contour = np.full((4, 264), 0.3333, dtype=np.float16)
            first_decode: dict[str, np.ndarray] = {}
            cached_decode: dict[str, np.ndarray] = {}

            def output_to_notes_polyphonic(
                decoded_frame,
                decoded_onset,
                **_kwargs,
            ):
                first_decode["frame"] = np.array(
                    decoded_frame,
                    dtype=np.float32,
                    copy=True,
                )
                first_decode["onset"] = np.array(
                    decoded_onset,
                    dtype=np.float32,
                    copy=True,
                )
                return []

            fake_note_creation = SimpleNamespace(
                output_to_notes_polyphonic=output_to_notes_polyphonic,
                model_frames_to_time=lambda count: (
                    np.arange(count, dtype=np.float64) * 0.1
                ),
            )
            fake_inference = SimpleNamespace(AUDIO_SAMPLE_RATE=8)
            with (
                patch(
                    "bdo_transcription._load_cached_result",
                    return_value=None,
                ),
                patch(
                    "bdo_transcription.transcription_backend_status",
                    return_value=(True, ""),
                ),
                patch(
                    "bdo_transcription._import_basic_pitch",
                    return_value=(
                        SimpleNamespace(ONNX_PRESENT=True),
                        fake_inference,
                        fake_note_creation,
                        SimpleNamespace(),
                    ),
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    return_value=SimpleNamespace(),
                ),
                patch(
                    "bdo_transcription._run_streamed_analysis",
                    return_value=(
                        {
                            "note": frame,
                            "onset": onset,
                            "contour": contour,
                        },
                        8,
                    ),
                ),
            ):
                result = transcribe_reference_audio(
                    audio,
                    cache_root=cache_root,
                )

            def output_to_notes_polyphonic(
                cached_frame,
                cached_onset,
                **_kwargs,
            ):
                cached_decode["frame"] = np.array(
                    cached_frame,
                    copy=True,
                )
                cached_decode["onset"] = np.array(
                    cached_onset,
                    copy=True,
                )
                return []

            with patch(
                "bdo_transcription._import_basic_pitch_note_creation",
                return_value=SimpleNamespace(
                    output_to_notes_polyphonic=(
                        output_to_notes_polyphonic
                    )
                ),
            ):
                cached = bdo_transcription.redecode_transcription_full(
                    result.cache_key,
                    cache_root=cache_root,
                )

            self.assertTrue(cached.cache_hit)
            np.testing.assert_array_equal(
                first_decode["frame"],
                cached_decode["frame"],
            )
            np.testing.assert_array_equal(
                first_decode["onset"],
                cached_decode["onset"],
            )

    def test_evidence_decode_projects_and_hashes_unique_events_once(
        self,
    ) -> None:
        event_count = 240
        raw_events = [
            (
                index * 2,
                index * 2 + 1,
                48 + index % 24,
                0.5 + (index % 10) * 0.01,
            )
            for index in range(event_count)
        ]
        # Preserve raw-event accounting for an exact duplicate while sharing
        # its identical frame/time projection and stable candidate ID.
        raw_events.append(raw_events[-1])
        frame_count = event_count * 2 + 1
        frame = np.zeros((frame_count, 88), dtype=np.float32)
        onset = np.zeros_like(frame)
        times_ms = np.arange(frame_count, dtype=np.float64) * 10.0
        note_creation = SimpleNamespace(
            output_to_notes_polyphonic=lambda *_args, **_kwargs: raw_events
        )
        project = bdo_transcription._candidate_from_frame_event
        identify = bdo_transcription.transcription_candidate_id

        with (
            patch(
                "bdo_transcription._candidate_from_frame_event",
                wraps=project,
            ) as project_mock,
            patch(
                "bdo_transcription.transcription_candidate_id",
                wraps=identify,
            ) as identify_mock,
        ):
            candidates, report = (
                bdo_transcription._decode_evidence_candidates(
                    note_creation,
                    frame,
                    onset,
                    times_ms,
                    cache_key="a" * 24,
                    onset_threshold=0.5,
                    frame_threshold=0.3,
                    min_note_len=1,
                    cleanup_profile="preserve",
                )
            )

        self.assertEqual(report.raw_candidate_count, event_count + 1)
        self.assertEqual(len(candidates), event_count)
        self.assertEqual(project_mock.call_count, event_count)
        self.assertEqual(identify_mock.call_count, event_count)

    def test_every_decode_entry_point_uses_identical_frame_postprocess(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"stable-audio")
            cache_root = root / "cache"
            frame_count = 120
            frame = np.zeros((frame_count, 88), dtype=np.float32)
            onset = np.zeros((frame_count, 88), dtype=np.float32)
            contour = np.zeros((frame_count, 264), dtype=np.float32)
            frame[:, 0] = np.arange(frame_count, dtype=np.float32) / 128.0
            frame[58:82, 60 - 21] = 0.8
            onset[60, 60 - 21] = 0.8
            onset[71, 60 - 21] = 0.02
            raw_global_events = (
                (60, 70, 60, 0.55),
                (71, 80, 60, 0.25),
            )

            def output_to_notes_polyphonic(
                decoded_frame,
                _decoded_onset,
                **_kwargs,
            ):
                base = int(round(float(decoded_frame[0, 0]) * 128.0))
                limit = base + int(decoded_frame.shape[0])
                return [
                    (
                        start - base,
                        end - base,
                        pitch,
                        confidence,
                    )
                    for start, end, pitch, confidence in raw_global_events
                    if base <= start and end <= limit
                ]

            fake_note_creation = SimpleNamespace(
                output_to_notes_polyphonic=output_to_notes_polyphonic,
                model_frames_to_time=lambda count: (
                    np.arange(count, dtype=np.float64) * 0.01
                ),
            )
            fake_inference = SimpleNamespace(AUDIO_SAMPLE_RATE=1_000)
            with (
                patch(
                    "bdo_transcription._load_cached_result",
                    return_value=None,
                ),
                patch(
                    "bdo_transcription.transcription_backend_status",
                    return_value=(True, ""),
                ),
                patch(
                    "bdo_transcription._import_basic_pitch",
                    return_value=(
                        SimpleNamespace(ONNX_PRESENT=True),
                        fake_inference,
                        fake_note_creation,
                        SimpleNamespace(),
                    ),
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    return_value=SimpleNamespace(),
                ),
                patch(
                    "bdo_transcription._run_streamed_analysis",
                    return_value=(
                        {
                            "note": frame,
                            "onset": onset,
                            "contour": contour,
                        },
                        1_200,
                    ),
                ),
            ):
                initial = transcribe_reference_audio(
                    audio,
                    analysis_mode="mixed_enhanced",
                    sensitivity="balanced",
                    cleanup_profile="balanced",
                    cache_root=cache_root,
                )

            with (
                patch(
                    "bdo_transcription._import_basic_pitch_note_creation",
                    return_value=fake_note_creation,
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    side_effect=AssertionError("ONNX must not run"),
                ),
            ):
                full = redecode_transcription_full(
                    initial.cache_key,
                    sensitivity="balanced",
                    cleanup_profile="balanced",
                    cache_root=cache_root,
                )
                interval = redecode_transcription_interval(
                    initial.cache_key,
                    600.0,
                    850.0,
                    sensitivity="balanced",
                    cleanup_profile="balanced",
                    context_ms=500.0,
                    cache_root=cache_root,
                )

            self.assertEqual(initial.candidates, full.candidates)
            self.assertEqual(full.candidates, interval.candidates)
            self.assertEqual(len(initial.candidates), 1)
            self.assertEqual(
                tuple(candidate.pitch for candidate in initial.candidates),
                (60,),
            )
            self.assertEqual(
                initial.postprocess_report.annotations,
                full.postprocess_report.annotations,
            )
            self.assertEqual(
                full.postprocess_report.annotations,
                interval.postprocess_report.annotations,
            )
            self.assertEqual(
                initial.postprocess_report.automatic_merge_count,
                1,
            )
            self.assertTrue(
                initial.postprocess_report.automatic_actions_enabled
            )
            annotation = initial.postprocess_report.annotations[0]
            self.assertEqual(annotation.disposition, "merged")
            self.assertIn("auto_merged", annotation.flags)
            self.assertEqual(len(annotation.lineage_ids), 2)
            self.assertNotIn(
                initial.candidates[0].candidate_id,
                annotation.lineage_ids,
            )

    def test_cached_profile_switch_redecodes_without_running_onnx(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            note_creation = SimpleNamespace(
                output_to_notes_polyphonic=lambda *_args, **_kwargs: [
                    (30, 35, 72, 0.20)
                ]
            )
            with (
                patch(
                    "bdo_transcription._import_basic_pitch_note_creation",
                    return_value=note_creation,
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    side_effect=AssertionError("ONNX must not run"),
                ),
            ):
                decoded = transcribe_reference_audio(
                    audio,
                    analysis_mode="standard",
                    cleanup_profile="clean",
                    cache_root=cache_root,
                )

            self.assertEqual(decoded.cache_key, result.cache_key)
            self.assertTrue(decoded.cache_hit)
            self.assertIsNotNone(decoded.postprocess_report)
            self.assertEqual(decoded.postprocess_report.profile, "clean")
            self.assertTrue(
                decoded.postprocess_report.automatic_actions_enabled
            )
            self.assertEqual(decoded.candidates, ())
            self.assertEqual(decoded.postprocess_report.suppressed_count, 1)
            self.assertEqual(
                len(decoded.postprocess_report.suppressed_candidates),
                1,
            )
            hidden = decoded.postprocess_report.suppressed_candidates[0]
            self.assertEqual(hidden.pitch, 72)
            hidden_annotation = decoded.postprocess_report.annotations[0]
            self.assertEqual(hidden_annotation.candidate_id, hidden.candidate_id)
            self.assertEqual(hidden_annotation.disposition, "suppressed")
            self.assertIn("clean_suppressed", hidden_annotation.flags)
            self.assertEqual(len(hidden_annotation.lineage_ids), 1)
            self.assertEqual(
                hidden_annotation.lineage_ids[0],
                hidden.candidate_id,
            )
            self.assertEqual(
                decoded.evidence_descriptor.cleanup_profile,
                "clean",
            )
            self.assertEqual(
                decoded.evidence_descriptor.postprocess_version,
                POSTPROCESS_VERSION,
            )

    def test_unchanged_cache_uses_bounded_validation_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            # Simulate a new process: freshly written entries are already
            # certified by the writer that validated their source arrays.
            with bdo_transcription._CACHE_VALIDATION_LOCK:
                bdo_transcription._VALIDATED_CACHE_ENTRIES.clear()
            original_validator = bdo_transcription._validate_evidence_files
            with patch(
                "bdo_transcription._validate_evidence_files",
                wraps=original_validator,
            ) as validator:
                first = load_transcription_evidence(
                    result.cache_key,
                    "frame",
                    cache_root=cache_root,
                )
                self.assertIsNotNone(first)
                first._mmap.close()
                second = load_transcription_evidence(
                    result.cache_key,
                    "frame",
                    cache_root=cache_root,
                )
                self.assertIsNotNone(second)
                second._mmap.close()
                self.assertEqual(validator.call_count, 1)

                frame_path = cache_root / result.cache_key / "frame.npy"
                frame_stat = frame_path.stat()
                os.utime(
                    frame_path,
                    ns=(
                        frame_stat.st_atime_ns,
                        frame_stat.st_mtime_ns + 1_000_000,
                    ),
                )
                third = load_transcription_evidence(
                    result.cache_key,
                    "frame",
                    cache_root=cache_root,
                )
                self.assertIsNotNone(third)
                third._mmap.close()
                self.assertEqual(validator.call_count, 2)

    def test_broken_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            folder = root / "cache" / transcription_cache_key(audio)
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(
                json.dumps({"version": 999}),
                encoding="utf-8",
            )
            self.assertIsNone(_load_cached_result(audio, root / "cache"))

    def test_legacy_manifest_without_cleanup_metadata_loads_as_preserve(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            manifest_path = (
                cache_root / result.cache_key / "manifest.json"
            )
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            descriptor_payload = manifest["evidence_descriptor"]
            descriptor_payload.pop("cleanup_profile")
            descriptor_payload.pop("postprocess_version")
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with bdo_transcription._CACHE_VALIDATION_LOCK:
                bdo_transcription._VALIDATED_CACHE_ENTRIES.clear()

            loaded = load_cached_transcription_result(
                result.cache_key,
                cache_root=cache_root,
            )

            self.assertIsNotNone(loaded)
            self.assertEqual(
                loaded.evidence_descriptor.cleanup_profile,
                LEGACY_TRANSCRIPTION_CLEANUP_PROFILE,
            )
            self.assertEqual(
                loaded.evidence_descriptor.postprocess_version,
                LEGACY_TRANSCRIPTION_POSTPROCESS_VERSION,
            )

    def test_old_postprocess_descriptor_keeps_redecodable_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            manifest_path = (
                cache_root / result.cache_key / "manifest.json"
            )
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            manifest["evidence_descriptor"][
                "postprocess_version"
            ] = "fragment-cleanup-v1"
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            with bdo_transcription._CACHE_VALIDATION_LOCK:
                bdo_transcription._VALIDATED_CACHE_ENTRIES.clear()

            loaded = load_cached_transcription_result(
                result.cache_key,
                cache_root=cache_root,
            )

            self.assertIsNotNone(loaded)
            self.assertEqual(
                loaded.evidence_descriptor.postprocess_version,
                "fragment-cleanup-v1",
            )

    def test_manifest_shape_and_truncated_evidence_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            folder = cache_root / result.cache_key
            manifest_path = folder / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["evidence_descriptor"]["layers"][0]["shape"] = [240, 87]
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            self.assertIsNone(_load_cached_result(audio, cache_root))

            self._write_synthetic_cache(audio, cache_root)
            frame_path = folder / "frame.npy"
            frame_path.write_bytes(frame_path.read_bytes()[:64])
            self.assertIsNone(_load_cached_result(audio, cache_root))
            self.assertIsNone(
                load_transcription_evidence(
                    result.cache_key,
                    "frame",
                    cache_root=cache_root,
                )
            )

            self._write_synthetic_cache(audio, cache_root)
            times_path = folder / "times_ms.npy"
            times_path.write_bytes(times_path.read_bytes()[:64])
            self.assertIsNone(
                load_transcription_evidence(
                    result.cache_key,
                    "frame",
                    cache_root=cache_root,
                )
            )

            self._write_synthetic_cache(audio, cache_root)
            frame_path = folder / "frame.npy"
            with frame_path.open("wb") as stream:
                np.save(
                    stream,
                    np.zeros((240, 88), dtype=np.float32),
                    allow_pickle=False,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            layer = manifest["evidence_descriptor"]["layers"][0]
            layer["file_size"] = frame_path.stat().st_size
            layer["sha256"] = hashlib.sha256(
                frame_path.read_bytes()
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            self.assertIsNone(_load_cached_result(audio, cache_root))

    def test_non_finite_evidence_fails_closed_even_with_matching_digest(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, _descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            folder = cache_root / result.cache_key
            frame_path = folder / "frame.npy"
            frame = np.load(frame_path, allow_pickle=False)
            frame[0, 0] = np.nan
            with frame_path.open("wb") as stream:
                np.save(stream, frame, allow_pickle=False)
            manifest_path = folder / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            layer = manifest["evidence_descriptor"]["layers"][0]
            layer["file_size"] = frame_path.stat().st_size
            layer["sha256"] = hashlib.sha256(frame_path.read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            self.assertIsNone(_load_cached_result(audio, cache_root))

    def test_interval_redecode_uses_cached_evidence_without_onnx(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            cache_root = root / "cache"
            result, descriptor, _times = self._write_synthetic_cache(
                audio,
                cache_root,
            )
            calls: list[tuple[tuple[int, int], float, float]] = []

            def output_to_notes_polyphonic(
                frames: np.ndarray,
                _onsets: np.ndarray,
                *,
                onset_thresh: float,
                frame_thresh: float,
                **_kwargs,
            ) -> list[tuple[int, int, int, float]]:
                calls.append((frames.shape, onset_thresh, frame_thresh))
                # With 500ms context this maps to project times 400, 800 and
                # 1200ms; only the middle onset belongs to [800, 1200).
                return [
                    (10, 20, 59, 0.4),
                    (50, 70, 60, 0.8),
                    (90, 100, 61, 0.7),
                ]

            fake_note_creation = SimpleNamespace(
                output_to_notes_polyphonic=output_to_notes_polyphonic
            )
            with (
                patch(
                    "bdo_transcription._import_basic_pitch_note_creation",
                    return_value=fake_note_creation,
                ),
                patch(
                    "bdo_transcription._onnx_model",
                    side_effect=AssertionError("ONNX must not run"),
                ),
            ):
                decoded = redecode_transcription_interval(
                    result.cache_key,
                    800.0,
                    1200.0,
                    sensitivity="sensitive",
                    cache_root=cache_root,
                )

            self.assertEqual(calls, [((141, 88), 0.35, 0.20)])
            self.assertEqual(len(decoded.candidates), 1)
            candidate = decoded.candidates[0]
            self.assertEqual(candidate.pitch, 60)
            self.assertAlmostEqual(candidate.start_ms, 800.0)
            self.assertAlmostEqual(candidate.duration_ms, 200.0)
            self.assertEqual(candidate.velocity, 102)
            self.assertTrue(candidate.candidate_id)
            self.assertTrue(decoded.cache_hit)
            self.assertEqual(
                decoded.evidence_descriptor.cache_key,
                descriptor.cache_key,
            )
            self.assertEqual(
                decoded.evidence_descriptor.decode_sensitivity,
                "sensitive",
            )
            self.assertEqual(
                decoded.evidence_descriptor.cleanup_profile,
                "preserve",
            )
            self.assertEqual(
                _load_cached_result(
                    audio,
                    cache_root,
                    analysis_mode="standard",
                ).candidates,
                (),
            )

    def test_cache_pruning_is_bounded_and_ignores_unknown_entries(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            cache_root = Path(folder_name)
            keys = ("0" * 24, "1" * 24, "2" * 24)
            for index, key in enumerate(keys):
                folder = cache_root / key
                folder.mkdir()
                (folder / "evidence.bin").write_bytes(b"x" * 10)
                timestamp = 1_700_000_000 + index
                os.utime(folder, (timestamp, timestamp))
            unknown = cache_root / "do-not-delete"
            unknown.mkdir()
            (unknown / "user.bin").write_bytes(b"user")

            removed_entries, removed_bytes = prune_transcription_cache(
                cache_root,
                max_entries=1,
                max_bytes=15,
                keep_keys=(keys[2],),
            )

            self.assertEqual(removed_entries, 2)
            self.assertEqual(removed_bytes, 20)
            self.assertFalse((cache_root / keys[0]).exists())
            self.assertFalse((cache_root / keys[1]).exists())
            self.assertTrue((cache_root / keys[2]).is_dir())
            self.assertTrue(unknown.is_dir())

    def test_evidence_loader_rejects_non_cache_keys(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            self.assertIsNone(
                load_transcription_evidence(
                    "../outside",
                    "frame",
                    cache_root=Path(folder_name),
                )
            )


if __name__ == "__main__":
    unittest.main()
