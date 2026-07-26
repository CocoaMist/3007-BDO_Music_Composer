from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from bdo_transcription_evidence_qt import (
    DEFAULT_IMAGE_CACHE_BYTES,
    EvidenceImageCache,
    EvidenceTile,
    EvidenceTileController,
    EvidenceTileKey,
    TILE_DURATION_MS,
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


@dataclass
class _Descriptor:
    cache_key: str
    layer_paths: dict[str, Path]
    evidence_layers: tuple[str, ...]
    frame_period_ms: float = 10.0
    midi_min: float = 21.0


class TranscriptionEvidenceQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _app()

    def test_visible_tiles_are_pooled_coloured_and_contour_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            frame = np.zeros((500, 88), dtype=np.float32)
            onset = np.zeros((500, 88), dtype=np.float32)
            contour = np.zeros((500, 264), dtype=np.float32)
            pitch_index = 60 - 21
            frame[10:210, pitch_index] = 0.82
            onset[312, pitch_index] = 1.0
            contour[220:250, pitch_index * 3 + 1] = 0.9
            paths: dict[str, Path] = {}
            for name, value in (
                ("frame", frame),
                ("onset", onset),
                ("contour", contour),
            ):
                path = root / f"{name}.npy"
                np.save(path, value, allow_pickle=False)
                paths[name] = path

            descriptor = _Descriptor(
                "evidence-colour",
                paths,
                ("frame", "onset", "contour"),
            )
            controller = EvidenceTileController(max_workers=2)
            ready: list[EvidenceTile] = []
            failures: list[str] = []
            controller.tile_ready.connect(ready.append)
            controller.tile_failed.connect(failures.append)
            generation = controller.begin_source(descriptor)

            cached = controller.request_visible(
                descriptor,
                start_ms=0.0,
                end_ms=4_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
            )
            self.assertEqual(cached, ())
            self.assertTrue(_wait_until(lambda: len(ready) == 2))
            self.assertEqual(failures, [])
            by_layer = {tile.layer: tile for tile in ready}
            self.assertEqual(set(by_layer), {"frame", "onset"})
            self.assertEqual(by_layer["frame"].image.width(), 5)
            self.assertEqual(by_layer["frame"].image.height(), 1)
            self.assertEqual(by_layer["onset"].image.width(), 5)
            self.assertEqual(by_layer["frame"].time_end_ms, TILE_DURATION_MS)

            frame_colours = [
                by_layer["frame"].image.pixelColor(x, 0)
                for x in range(by_layer["frame"].image.width())
            ]
            onset_colours = [
                by_layer["onset"].image.pixelColor(x, 0)
                for x in range(by_layer["onset"].image.width())
            ]
            strongest_frame = max(frame_colours, key=QColor.alpha)
            strongest_onset = max(onset_colours, key=QColor.alpha)
            self.assertGreater(strongest_frame.alpha(), 0)
            self.assertLessEqual(strongest_frame.alpha(), 72)
            self.assertGreater(strongest_frame.blue(), strongest_frame.red())
            # Onsets use maximum pooling so an isolated transient survives a
            # five-pixel-wide, five-second tile.
            self.assertGreater(strongest_onset.alpha(), 0)
            self.assertGreater(strongest_onset.red(), strongest_onset.blue())

            already_ready = controller.request_visible(
                descriptor,
                start_ms=0.0,
                end_ms=4_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
            )
            self.assertEqual({tile.layer for tile in already_ready}, {"frame", "onset"})

            controller.request_visible(
                descriptor,
                start_ms=0.0,
                end_ms=4_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
                include_contour=True,
            )
            self.assertTrue(_wait_until(lambda: any(tile.layer == "contour" for tile in ready)))
            contour_tile = next(tile for tile in ready if tile.layer == "contour")
            self.assertEqual(contour_tile.image.height(), 3)
            self.assertEqual(contour_tile.bins_per_semitone, 3)
            controller.close()
            self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_generation_and_cache_key_drop_stale_worker_results(self) -> None:
        old_started = threading.Event()
        release_old = threading.Event()
        old_array = np.ones((100, 88), dtype=np.float32)
        new_array = np.ones((100, 88), dtype=np.float32) * 0.7
        old = {
            "cache_key": "old-source",
            "evidence_layers": ("frame",),
            "layers": {"frame": old_array},
            "frame_period_ms": 50.0,
        }
        new = {
            "cache_key": "new-source",
            "evidence_layers": ("frame",),
            "layers": {"frame": new_array},
            "frame_period_ms": 50.0,
        }

        def loader(descriptor: object, layer: str):
            assert layer == "frame"
            if descriptor["cache_key"] == "old-source":
                old_started.set()
                release_old.wait(2.0)
            return descriptor["layers"][layer]

        controller = EvidenceTileController(max_workers=2, layer_loader=loader)
        emitted: list[EvidenceTile] = []
        controller.tile_ready.connect(emitted.append)
        old_generation = controller.begin_source(old)
        controller.request_visible(
            old,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=old_generation,
            layers=("frame",),
        )
        self.assertTrue(old_started.wait(1.0))

        new_generation = controller.begin_source(new)
        controller.request_visible(
            new,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=new_generation,
            layers=("frame",),
        )
        self.assertEqual(
            controller.request_visible(
                old,
                start_ms=0.0,
                end_ms=4_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.002,
                generation=old_generation,
                layers=("frame",),
            ),
            (),
        )
        self.assertEqual(controller.active_cache_key, "new-source")
        self.assertTrue(
            _wait_until(
                lambda: any(tile.cache_key == "new-source" for tile in emitted)
            )
        )
        release_old.set()
        self.assertTrue(controller.thread_pool.waitForDone(2_000))
        _app().processEvents()
        self.assertTrue(emitted)
        self.assertEqual({tile.cache_key for tile in emitted}, {"new-source"})
        self.assertEqual({tile.generation for tile in emitted}, {new_generation})
        controller.close()

    def test_close_clears_all_pending_entries_when_queued_jobs_never_run(self) -> None:
        first_started = threading.Event()
        release_first = threading.Event()
        layer = np.ones((1_200, 88), dtype=np.float32)
        calls = 0

        def loader(_descriptor: object, _layer: str):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_started.set()
                release_first.wait(2.0)
            return layer

        descriptor = {
            "cache_key": "pending-close",
            "evidence_layers": ("frame",),
            "frame_period_ms": 50.0,
            "duration_ms": 60_000.0,
        }
        controller = EvidenceTileController(max_workers=1, layer_loader=loader)
        emitted: list[EvidenceTile] = []
        controller.tile_ready.connect(emitted.append)
        generation = controller.begin_source(descriptor)
        controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=59_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.001,
            generation=generation,
            layers=("frame",),
        )
        self.assertTrue(first_started.wait(1.0))
        self.assertEqual(len(controller._pending), 12)

        controller.close()
        # Eleven queued runnables were removed by QThreadPool.clear() and will
        # never emit.  Their bookkeeping must be gone immediately.
        self.assertEqual(len(controller._pending), 0)
        release_first.set()
        self.assertTrue(controller.thread_pool.waitForDone(2_000))
        _app().processEvents()
        self.assertEqual(len(controller._pending), 0)
        self.assertEqual(emitted, [])

    def test_begin_source_clears_queued_pending_and_accepts_only_new_source(self) -> None:
        old_started = threading.Event()
        release_old = threading.Event()
        old_layer = np.ones((1_200, 88), dtype=np.float32)
        new_layer = np.ones((100, 88), dtype=np.float32) * 0.5
        old = {
            "cache_key": "pending-old",
            "evidence_layers": ("frame",),
            "frame_period_ms": 50.0,
            "duration_ms": 60_000.0,
        }
        new = {
            "cache_key": "pending-new",
            "evidence_layers": ("frame",),
            "frame_period_ms": 50.0,
            "duration_ms": 5_000.0,
        }

        def loader(descriptor: object, _layer: str):
            if descriptor["cache_key"] == "pending-old":
                old_started.set()
                release_old.wait(2.0)
                return old_layer
            return new_layer

        controller = EvidenceTileController(max_workers=1, layer_loader=loader)
        emitted: list[EvidenceTile] = []
        controller.tile_ready.connect(emitted.append)
        old_generation = controller.begin_source(old)
        controller.request_visible(
            old,
            start_ms=0.0,
            end_ms=59_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.001,
            generation=old_generation,
            layers=("frame",),
        )
        self.assertTrue(old_started.wait(1.0))
        self.assertEqual(len(controller._pending), 12)

        new_generation = controller.begin_source(new)
        self.assertEqual(len(controller._pending), 0)
        controller.request_visible(
            new,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.001,
            generation=new_generation,
            layers=("frame",),
        )
        self.assertEqual(len(controller._pending), 1)
        release_old.set()
        self.assertTrue(_wait_until(lambda: len(emitted) == 1))
        self.assertEqual(emitted[0].cache_key, "pending-new")
        self.assertEqual(emitted[0].generation, new_generation)
        self.assertEqual(len(controller._pending), 0)
        controller.close()
        self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_stale_viewport_tiles_do_not_emit_or_delay_current_viewport(self) -> None:
        first_started = threading.Event()
        release_first = threading.Event()
        layer = np.ones((1_200, 88), dtype=np.float32)
        calls = 0

        def loader(_descriptor: object, _layer: str):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_started.set()
                release_first.wait(2.0)
            return layer

        descriptor = {
            "cache_key": "viewport-expiry",
            "evidence_layers": ("frame",),
            "frame_period_ms": 50.0,
            "duration_ms": 60_000.0,
        }
        controller = EvidenceTileController(max_workers=1, layer_loader=loader)
        emitted: list[EvidenceTile] = []
        controller.tile_ready.connect(emitted.append)
        generation = controller.begin_source(descriptor)
        controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=59_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.001,
            generation=generation,
            layers=("frame",),
        )
        self.assertTrue(first_started.wait(1.0))
        self.assertEqual(len(controller._pending), 12)

        controller.request_visible(
            descriptor,
            start_ms=55_000.0,
            end_ms=59_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.001,
            generation=generation,
            layers=("frame",),
        )
        # The eleven obsolete queued jobs are removed; one current tile waits
        # behind the already-running stale slice.
        self.assertEqual(len(controller._pending), 1)
        release_first.set()
        self.assertTrue(_wait_until(lambda: len(emitted) == 1))
        self.assertEqual(emitted[0].key.tile_index, 11)
        self.assertTrue(controller.thread_pool.waitForDone(2_000))
        _app().processEvents()
        self.assertEqual([tile.key.tile_index for tile in emitted], [11])
        self.assertEqual(len(controller._pending), 0)
        controller.close()

    def test_cursor_repaint_reads_cache_without_replacing_viewport(self) -> None:
        descriptor = {
            "cache_key": "cursor-repaint",
            "evidence_layers": ("frame",),
            "layers": {
                "frame": np.ones((200, 88), dtype=np.float32)
            },
            "frame_period_ms": 50.0,
            "duration_ms": 10_000.0,
        }
        controller = EvidenceTileController(
            max_workers=1,
            layer_loader=lambda source, layer: source["layers"][layer],
        )
        emitted: list[EvidenceTile] = []
        controller.tile_ready.connect(emitted.append)
        generation = controller.begin_source(descriptor)
        controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=generation,
            layers=("frame",),
        )
        self.assertTrue(_wait_until(lambda: len(emitted) == 1))
        viewport_keys = controller._viewport_keys
        viewport_generation = controller._viewport_generation

        cached = controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=100.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=generation,
            layers=("frame",),
            update_viewport=False,
        )
        self.assertEqual(len(cached), 1)
        missing = controller.request_visible(
            descriptor,
            start_ms=5_000.0,
            end_ms=5_100.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=generation,
            layers=("frame",),
            update_viewport=False,
        )
        self.assertEqual(missing, ())
        self.assertEqual(controller._viewport_keys, viewport_keys)
        self.assertEqual(
            controller._viewport_generation,
            viewport_generation,
        )
        self.assertEqual(len(controller._pending), 0)
        controller.close()
        self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_intensity_is_quantized_into_cache_key_and_scales_alpha(self) -> None:
        descriptor = {
            "cache_key": "evidence-intensity",
            "evidence_layers": ("frame",),
            "layers": {"frame": np.ones((100, 88), dtype=np.float32)},
            "frame_period_ms": 50.0,
        }
        controller = EvidenceTileController(
            max_workers=1,
            layer_loader=lambda source, layer: source["layers"][layer],
        )
        emitted: list[EvidenceTile] = []
        controller.tile_ready.connect(emitted.append)
        generation = controller.begin_source(descriptor)

        controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=generation,
            layers=("frame",),
        )
        self.assertTrue(_wait_until(lambda: len(emitted) == 1))
        default_tile = emitted[0]
        default_alpha = max(
            default_tile.image.pixelColor(x, 0).alpha()
            for x in range(default_tile.image.width())
        )
        self.assertEqual(default_tile.key.intensity_percent, 100)

        controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=generation,
            layers=("frame",),
            intensity=0.5,
        )
        self.assertTrue(_wait_until(lambda: len(emitted) == 2))
        dim_tile = emitted[1]
        dim_alpha = max(
            dim_tile.image.pixelColor(x, 0).alpha()
            for x in range(dim_tile.image.width())
        )
        self.assertEqual(dim_tile.key.intensity_percent, 50)
        self.assertNotEqual(default_tile.key, dim_tile.key)
        self.assertGreater(default_alpha, dim_alpha)
        self.assertGreater(dim_alpha, 0)
        self.assertEqual(len(controller.cache), 2)

        nearly_default = controller.request_visible(
            descriptor,
            start_ms=0.0,
            end_ms=4_999.0,
            pitch_min=60,
            pitch_max=60,
            pixels_per_ms=0.002,
            generation=generation,
            layers=("frame",),
            intensity=1.004,
        )
        self.assertEqual(len(nearly_default), 1)
        self.assertEqual(nearly_default[0].key, default_tile.key)
        self.assertEqual(len(emitted), 2)
        controller.close()
        self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_core_descriptor_uses_official_frame_times_and_tuple_layers(self) -> None:
        layer = SimpleNamespace(
            name="frame",
            filename="frame.npy",
            shape=(3, 88),
            dtype="<f2",
            midi_min=21,
            bins_per_semitone=1,
        )

        class CoreDescriptor:
            cache_key = "a" * 24
            times_filename = "times_ms.npy"
            midi_min = 21

            def __init__(self, layer_value):
                self.layers = (layer_value,)

            @property
            def layer_names(self):
                return ("frame",)

            def layer(self, name):
                return layer if name == "frame" else None

        descriptor = CoreDescriptor(layer)
        evidence = np.zeros((3, 88), dtype=np.float32)
        evidence[2, 60 - 21] = 1.0
        frame_times = np.asarray((0.0, 4_000.0, 6_000.0), dtype=np.float64)
        official_times_loaded = threading.Event()

        def load_times(cache_key, **_kwargs):
            self.assertEqual(cache_key, "a" * 24)
            official_times_loaded.set()
            return frame_times

        controller = EvidenceTileController(
            layer_loader=lambda _descriptor, _layer: evidence,
        )
        ready: list[EvidenceTile] = []
        controller.tile_ready.connect(ready.append)
        with patch(
            "bdo_transcription.load_transcription_frame_times",
            side_effect=load_times,
        ):
            generation = controller.begin_source(descriptor)
            controller.request_visible(
                descriptor,
                start_ms=5_000.0,
                end_ms=7_000.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
                layers=("frame",),
            )
            self.assertTrue(_wait_until(lambda: bool(ready)))
        self.assertTrue(official_times_loaded.is_set())
        self.assertEqual(ready[0].key.tile_index, 1)
        self.assertGreater(
            max(
                ready[0].image.pixelColor(x, 0).alpha()
                for x in range(ready[0].image.width())
            ),
            0,
        )
        controller.close()
        self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_worker_closes_disposable_memmap_before_emitting_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            path = root / "frame.npy"
            np.save(path, np.ones((100, 88), dtype=np.float32), allow_pickle=False)
            released = threading.Event()

            def loader(_descriptor: object, _layer: str):
                array = np.load(path, mmap_mode="r", allow_pickle=False)

                def release(_array) -> None:
                    released.set()

                return array, release

            descriptor = {
                "cache_key": "mmap-release",
                "evidence_layers": ("frame",),
                "frame_period_ms": 50.0,
            }
            controller = EvidenceTileController(layer_loader=loader)
            ready: list[EvidenceTile] = []
            controller.tile_ready.connect(ready.append)
            generation = controller.begin_source(descriptor)
            controller.request_visible(
                descriptor,
                start_ms=0.0,
                end_ms=4_999.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.002,
                generation=generation,
                layers=("frame",),
            )
            self.assertTrue(_wait_until(lambda: bool(ready)))
            self.assertTrue(released.is_set())
            # This is the behaviour that matters on Windows: no worker-owned
            # mapping remains after the detached QImage is delivered.
            path.unlink()
            self.assertFalse(path.exists())
            controller.close()
            self.assertTrue(controller.thread_pool.waitForDone(2_000))

    def test_five_second_partition_and_lru_byte_budget(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            path = root / "frame.npy"
            np.save(path, np.ones((1_200, 88), dtype=np.float32), allow_pickle=False)
            descriptor = _Descriptor(
                "tile-partition",
                {"frame": path},
                ("frame",),
            )
            controller = EvidenceTileController()
            emitted: list[EvidenceTile] = []
            controller.tile_ready.connect(emitted.append)
            generation = controller.begin_source(descriptor)
            controller.request_visible(
                descriptor,
                start_ms=2_500.0,
                end_ms=10_500.0,
                pitch_min=60,
                pitch_max=60,
                pixels_per_ms=0.001,
                generation=generation,
                layers=("frame",),
            )
            self.assertTrue(_wait_until(lambda: len(emitted) == 3))
            self.assertEqual(
                {tile.key.tile_index for tile in emitted},
                {0, 1, 2},
            )
            final_tile = next(tile for tile in emitted if tile.key.tile_index == 2)
            self.assertGreater(final_tile.image.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(
                final_tile.image.pixelColor(final_tile.image.width() - 1, 0).alpha(),
                0,
            )
            controller.close()
            self.assertTrue(controller.thread_pool.waitForDone(2_000))

        self.assertEqual(DEFAULT_IMAGE_CACHE_BYTES, 48 * 1024 * 1024)
        cache = EvidenceImageCache(max_bytes=600)

        def tile(index: int) -> EvidenceTile:
            image = QImage(10, 10, QImage.Format.Format_RGBA8888)
            image.fill(QColor(10 + index, 20, 30, 40))
            key = EvidenceTileKey("cache", "frame", index, 60, 60, 10)
            return EvidenceTile(
                key,
                1,
                index * TILE_DURATION_MS,
                (index + 1) * TILE_DURATION_MS,
                60.0,
                61.0,
                1,
                image,
            )

        first = tile(0)
        second = tile(1)
        self.assertEqual(first.byte_count, 400)
        self.assertTrue(cache.put(first))
        self.assertTrue(cache.put(second))
        self.assertEqual(len(cache), 1)
        self.assertIsNone(cache.get(first.key))
        self.assertIs(cache.get(second.key), second)
        self.assertLessEqual(cache.bytes_used, 600)


if __name__ == "__main__":
    unittest.main()
