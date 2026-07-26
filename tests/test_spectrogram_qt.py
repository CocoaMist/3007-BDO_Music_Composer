from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor

from bdo_spectrogram import choose_fft_size
from bdo_spectrogram_qt import (
    DEFAULT_SPECTROGRAM_CACHE_BYTES,
    SpectrogramTileController,
)


def _app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    application = _app()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    application.processEvents()
    return bool(predicate())


def _write_sine_wave(path: Path) -> None:
    sample_rate = 22_050
    times = np.arange(sample_rate, dtype=np.float64) / sample_rate
    samples = np.rint(
        np.sin(2.0 * np.pi * 440.0 * times) * 16_000.0
    ).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


def _silent_tile(sample_rate: int = 8_000):
    tile_frames = sample_rate * 5
    half = choose_fft_size(sample_rate) // 2
    return (
        np.zeros(tile_frames + half * 2, dtype=np.float32),
        float(sample_rate),
        tile_frames,
        half,
    )


class SpectrogramQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _app()

    def test_worker_reads_audio_and_delivers_subtle_detached_tile(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "reference.wav"
            _write_sine_wave(path)
            controller = SpectrogramTileController(max_workers=1)
            ready = []
            failures: list[str] = []
            controller.tile_ready.connect(ready.append)
            controller.tile_failed.connect(failures.append)
            generation = controller.begin_source(path, duration_ms=1_000.0)

            cached = controller.request_visible(
                start_ms=0.0,
                end_ms=999.0,
                pitch_min=60,
                pitch_max=72,
                pixels_per_ms=0.01,
                generation=generation,
            )
            self.assertEqual(cached, ())
            self.assertTrue(_wait_until(lambda: len(ready) == 1))
            self.assertEqual(failures, [])
            tile = ready[0]
            self.assertEqual(tile.image.width(), 50)
            self.assertEqual(tile.image.height(), 13)
            self.assertEqual(tile.pitch_min, 60.0)
            self.assertEqual(tile.pitch_max_exclusive, 73.0)
            colours = [
                tile.image.pixelColor(x, y)
                for x in range(tile.image.width())
                for y in range(tile.image.height())
            ]
            self.assertGreater(max(colours, key=QColor.alpha).alpha(), 0)
            self.assertLessEqual(max(colours, key=QColor.alpha).alpha(), 48)
            self.assertEqual(DEFAULT_SPECTROGRAM_CACHE_BYTES, 24 * 1024 * 1024)
            self.assertLessEqual(
                controller.cache.bytes_used,
                DEFAULT_SPECTROGRAM_CACHE_BYTES,
            )

            again = controller.request_visible(
                start_ms=0.0,
                end_ms=999.0,
                pitch_min=60,
                pitch_max=72,
                pixels_per_ms=0.01,
                generation=generation,
            )
            self.assertEqual(len(again), 1)
            controller.close()
            self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_viewport_change_cancels_queued_tiles_and_rejects_stale_result(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "private-reference.bin"
            path.write_bytes(b"source identity only")
            started = threading.Event()
            release = threading.Event()
            calls = 0

            def loader(_source, _start_ms, _end_ms):
                nonlocal calls
                calls += 1
                if calls == 1:
                    started.set()
                    release.wait(2.0)
                return _silent_tile()

            controller = SpectrogramTileController(
                max_workers=1,
                audio_slice_loader=loader,
            )
            emitted = []
            controller.tile_ready.connect(emitted.append)
            generation = controller.begin_source(path, duration_ms=60_000.0)
            controller.request_visible(
                start_ms=0.0,
                end_ms=59_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
            )
            self.assertTrue(started.wait(1.0))
            self.assertEqual(len(controller._pending), 12)

            controller.request_visible(
                start_ms=55_000.0,
                end_ms=59_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
            )
            self.assertEqual(len(controller._pending), 1)
            release.set()
            self.assertTrue(_wait_until(lambda: len(emitted) == 1))
            self.assertEqual(emitted[0].key.tile_index, 11)
            self.assertEqual(len(controller._pending), 0)
            controller.close()
            self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_toggle_cancel_retains_cache_but_close_releases_everything(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "reference.bin"
            path.write_bytes(b"identity")
            controller = SpectrogramTileController(
                audio_slice_loader=lambda *_args: _silent_tile(),
            )
            emitted = []
            controller.tile_ready.connect(emitted.append)
            controller.begin_source(path, duration_ms=5_000.0)
            controller.request_visible(
                start_ms=0.0,
                end_ms=4_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
            )
            self.assertTrue(_wait_until(lambda: len(emitted) == 1))
            cached_bytes = controller.cache.bytes_used
            controller.cancel_pending()
            self.assertEqual(controller.cache.bytes_used, cached_bytes)
            self.assertEqual(controller._viewport_keys, frozenset())
            controller.close()
            self.assertEqual(controller.cache.bytes_used, 0)
            self.assertIsNone(controller.source)
            self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_late_duration_update_clamps_same_source_without_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            path = Path(folder_name) / "reference.bin"
            path.write_bytes(b"identity")
            controller = SpectrogramTileController(
                audio_slice_loader=lambda *_args: _silent_tile(),
            )
            generation = controller.begin_source(path, duration_ms=0.0)
            cache_key = controller.active_cache_key
            controller.set_duration_ms(1_000.0)
            self.assertEqual(controller.generation, generation)
            self.assertEqual(controller.active_cache_key, cache_key)
            self.assertIsNotNone(controller.source)
            self.assertEqual(controller.source.duration_ms, 1_000.0)
            self.assertEqual(
                controller.request_visible(
                    start_ms=5_000.0,
                    end_ms=6_000.0,
                    pitch_min=60,
                    pitch_max=72,
                    pixels_per_ms=0.01,
                ),
                (),
            )
            self.assertEqual(len(controller._pending), 0)
            controller.close()


if __name__ == "__main__":
    unittest.main()
