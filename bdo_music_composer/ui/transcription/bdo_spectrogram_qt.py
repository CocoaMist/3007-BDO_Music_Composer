"""Asynchronous, viewport-bounded spectrogram tiles for the note editor.

Only workers open the reference audio and perform FFTs.  The piano-roll paint
path requests keys and draws detached ``QImage`` values already held by the
bounded LRU cache.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
from pathlib import Path
import threading
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QImage

from bdo_music_composer.audio.bdo_spectrogram import (
    SpectrogramCancelled,
    choose_fft_size,
    midi_spectrogram,
    spectrogram_column_count,
)
from bdo_music_composer.audio.reference_audio_format import (
    validate_reference_audio_file,
)
from bdo_music_composer.ui.transcription.bdo_transcription_evidence_qt import (
    EvidenceImageCache,
    EvidenceTile,
    EvidenceTileKey,
    TILE_DURATION_MS,
)


DEFAULT_SPECTROGRAM_CACHE_BYTES = 24 * 1024 * 1024
SPECTROGRAM_LAYER = "spectrogram"


@dataclass(frozen=True)
class SpectrogramSource:
    """Ephemeral source identity; it is never serialized into a project."""

    path: Path
    cache_key: str
    duration_ms: float = 0.0


@dataclass(frozen=True)
class _SpectrogramSpec:
    key: EvidenceTileKey
    generation: int
    viewport_generation: int
    time_start_ms: float
    time_end_ms: float
    cancel_event: threading.Event


@dataclass(frozen=True)
class _SpectrogramResult:
    spec: _SpectrogramSpec
    tile: EvidenceTile | None = None
    error: str = ""
    cancelled: bool = False


class _WorkerSignals(QObject):
    finished = Signal(object)


AudioSliceLoader = Callable[
    [SpectrogramSource, float, float],
    tuple[np.ndarray, float, int, int],
]


def _source_cache_key(path: Path) -> str:
    stat = path.stat()
    identity = (
        f"{path.resolve(strict=False)}\0{stat.st_size}\0{stat.st_mtime_ns}"
    ).encode("utf-8", "surrogatepass")
    return hashlib.sha256(identity).hexdigest()[:24]


def _read_audio_slice(
    source: SpectrogramSource,
    time_start_ms: float,
    time_end_ms: float,
) -> tuple[np.ndarray, float, int, int]:
    """Read at most one tile plus a half-window boundary on each side."""

    import soundfile as sf

    with sf.SoundFile(str(source.path), "r") as handle:
        sample_rate = float(handle.samplerate)
        fft_size = choose_fft_size(sample_rate)
        half_window = fft_size // 2
        tile_start = max(0, round(float(time_start_ms) * sample_rate / 1000.0))
        tile_end = max(
            tile_start,
            round(float(time_end_ms) * sample_rate / 1000.0),
        )
        tile_frames = tile_end - tile_start
        desired_start = tile_start - half_window
        desired_end = tile_end + half_window
        actual_start = max(0, desired_start)
        actual_end = min(int(handle.frames), desired_end)
        padded = np.zeros(tile_frames + fft_size, dtype=np.float32)
        if actual_end > actual_start:
            handle.seek(actual_start)
            decoded = handle.read(
                actual_end - actual_start,
                dtype="float32",
                always_2d=True,
            )
            mono = np.mean(decoded, axis=1, dtype=np.float32)
            destination = actual_start - desired_start
            padded[destination:destination + mono.size] = mono
        return padded, sample_rate, tile_frames, half_window


def _spectrogram_rgba_image(matrix: np.ndarray) -> QImage:
    values = np.nan_to_num(matrix, nan=0.0, posinf=1.0, neginf=0.0)
    values = np.clip(values, 0.0, 1.0)
    strength = np.clip((values - 0.10) / 0.90, 0.0, 1.0)
    alpha = np.rint(np.power(strength, 0.78) * 48.0).astype(np.uint8)
    # The transform is time x ascending pitch; piano-roll rows descend.
    alpha = alpha.T[::-1, :]
    height, width = alpha.shape
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[:, :, 0] = 100
    rgba[:, :, 1] = 137
    rgba[:, :, 2] = 151
    rgba[:, :, 3] = alpha
    image = QImage(
        rgba.data,
        width,
        height,
        int(rgba.strides[0]),
        QImage.Format.Format_RGBA8888,
    )
    return image.copy()


class _SpectrogramRunnable(QRunnable):
    def __init__(
        self,
        source: SpectrogramSource,
        spec: _SpectrogramSpec,
        audio_slice_loader: AudioSliceLoader,
    ) -> None:
        super().__init__()
        self.source = source
        self.spec = spec
        self.audio_slice_loader = audio_slice_loader
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        if self.spec.cancel_event.is_set():
            self.signals.finished.emit(
                _SpectrogramResult(self.spec, cancelled=True)
            )
            return
        try:
            samples, sample_rate, tile_frames, leading = self.audio_slice_loader(
                self.source,
                self.spec.time_start_ms,
                self.spec.time_end_ms,
            )
            matrix = midi_spectrogram(
                samples,
                sample_rate,
                pitch_min=self.spec.key.pitch_min,
                pitch_max=self.spec.key.pitch_max,
                output_columns=self.spec.key.output_columns_hint,
                tile_frame_count=tile_frames,
                leading_padding_frames=leading,
                cancel_requested=self.spec.cancel_event.is_set,
            )
            image = _spectrogram_rgba_image(matrix)
            tile = EvidenceTile(
                self.spec.key,
                self.spec.generation,
                self.spec.time_start_ms,
                self.spec.time_end_ms,
                float(self.spec.key.pitch_min),
                float(self.spec.key.pitch_max + 1),
                1,
                image,
            )
            self.signals.finished.emit(
                _SpectrogramResult(self.spec, tile=tile)
            )
        except SpectrogramCancelled:
            self.signals.finished.emit(
                _SpectrogramResult(self.spec, cancelled=True)
            )
        except Exception as exc:
            # Do not propagate a decoder's machine-local path in UI/log text.
            self.signals.finished.emit(
                _SpectrogramResult(
                    self.spec,
                    error=f"spectrogram tile unavailable ({type(exc).__name__})",
                )
            )


class SpectrogramTileController(QObject):
    """Own asynchronous reference-audio tiles for one piano-roll canvas."""

    tile_ready = Signal(object)
    tile_failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        cache_bytes: int = DEFAULT_SPECTROGRAM_CACHE_BYTES,
        max_workers: int = 1,
        audio_slice_loader: AudioSliceLoader | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = EvidenceImageCache(cache_bytes)
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(max(1, int(max_workers)))
        self.audio_slice_loader = audio_slice_loader or _read_audio_slice
        self._validate_audio_source = audio_slice_loader is None
        self._generation = 0
        self._viewport_generation = 0
        self._viewport_keys: frozenset[EvidenceTileKey] = frozenset()
        self._pending: set[tuple[int, int, EvidenceTileKey]] = set()
        self._unavailable: set[tuple[int, EvidenceTileKey]] = set()
        self._source: SpectrogramSource | None = None
        self._cancel_event = threading.Event()
        self._closed = True

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def source(self) -> SpectrogramSource | None:
        return self._source

    @property
    def active_cache_key(self) -> str:
        return self._source.cache_key if self._source is not None else ""

    def _invalidate_pending_work(self) -> None:
        self._cancel_event.set()
        self.thread_pool.clear()
        self._pending.clear()
        self._cancel_event = threading.Event()

    def _set_viewport(self, keys: frozenset[EvidenceTileKey]) -> None:
        if keys == self._viewport_keys:
            return
        self._viewport_generation += 1
        self._viewport_keys = keys
        self._invalidate_pending_work()

    def begin_source(
        self,
        audio_path: str | Path,
        *,
        duration_ms: float = 0.0,
    ) -> int:
        path = Path(audio_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise FileNotFoundError(path.name)
        if self._validate_audio_source:
            validate_reference_audio_file(path)
        self._invalidate_pending_work()
        self._generation += 1
        self._viewport_generation += 1
        self._viewport_keys = frozenset()
        duration = float(duration_ms)
        self._source = SpectrogramSource(
            path,
            _source_cache_key(path),
            duration if math.isfinite(duration) and duration > 0.0 else 0.0,
        )
        self._unavailable.clear()
        self._closed = False
        return self._generation

    set_source = begin_source

    def set_duration_ms(self, duration_ms: float) -> None:
        """Refine an asynchronously discovered media duration in place."""

        source = self._source
        if source is None:
            return
        duration = float(duration_ms)
        normalized = (
            duration
            if math.isfinite(duration) and duration > 0.0
            else 0.0
        )
        if math.isclose(source.duration_ms, normalized, abs_tol=0.001):
            return
        self._source = replace(source, duration_ms=normalized)
        # A previously unknown duration may make queued end-of-file tiles
        # obsolete.  Keep ready cache entries but cancel the old viewport.
        self.cancel_pending()

    def cancel_pending(self) -> None:
        """Cancel obsolete viewport work while retaining ready cache tiles."""

        if self._closed:
            return
        self._viewport_generation += 1
        self._viewport_keys = frozenset()
        self._invalidate_pending_work()

    def request_visible(
        self,
        *,
        start_ms: float,
        end_ms: float,
        pitch_min: int,
        pitch_max: int,
        pixels_per_ms: float,
        generation: int | None = None,
        update_viewport: bool = True,
    ) -> tuple[EvidenceTile, ...]:
        source = self._source
        if self._closed or source is None:
            return ()
        requested_generation = self._generation if generation is None else int(generation)
        if requested_generation != self._generation:
            return ()
        start = max(0.0, float(start_ms))
        end = max(start, float(end_ms))
        if source.duration_ms > 0.0:
            if start >= source.duration_ms:
                if update_viewport:
                    self._set_viewport(frozenset())
                return ()
            end = min(end, source.duration_ms)
        low_pitch = max(0, min(127, int(pitch_min)))
        high_pitch = max(low_pitch, min(127, int(pitch_max)))
        if end <= start:
            if update_viewport:
                self._set_viewport(frozenset())
            return ()
        first_tile = max(0, math.floor(start / TILE_DURATION_MS))
        last_tile = max(
            first_tile,
            math.floor(max(start, end - 1e-6) / TILE_DURATION_MS),
        )
        columns = spectrogram_column_count(
            TILE_DURATION_MS,
            pixels_per_ms,
        )
        keys = tuple(
            EvidenceTileKey(
                source.cache_key,
                SPECTROGRAM_LAYER,
                tile_index,
                low_pitch,
                high_pitch,
                columns,
            )
            for tile_index in range(first_tile, last_tile + 1)
        )
        if update_viewport:
            self._set_viewport(frozenset(keys))

        ready: list[EvidenceTile] = []
        for key in keys:
            cached = self.cache.get(key)
            if cached is not None:
                if cached.generation != requested_generation:
                    cached = replace(cached, generation=requested_generation)
                ready.append(cached)
                continue
            if not update_viewport:
                continue
            pending_key = (
                requested_generation,
                self._viewport_generation,
                key,
            )
            unavailable_key = (requested_generation, key)
            if pending_key in self._pending or unavailable_key in self._unavailable:
                continue
            spec = _SpectrogramSpec(
                key,
                requested_generation,
                self._viewport_generation,
                key.tile_index * TILE_DURATION_MS,
                (key.tile_index + 1) * TILE_DURATION_MS,
                self._cancel_event,
            )
            worker = _SpectrogramRunnable(
                source,
                spec,
                self.audio_slice_loader,
            )
            worker.signals.finished.connect(
                self._worker_finished,
                Qt.ConnectionType.QueuedConnection,
            )
            self._pending.add(pending_key)
            self.thread_pool.start(worker)
        ready.sort(key=lambda tile: tile.time_start_ms)
        return tuple(ready)

    @Slot(object)
    def _worker_finished(self, result: _SpectrogramResult) -> None:
        pending_key = (
            result.spec.generation,
            result.spec.viewport_generation,
            result.spec.key,
        )
        self._pending.discard(pending_key)
        source = self._source
        if (
            self._closed
            or source is None
            or result.spec.generation != self._generation
            or result.spec.key.cache_key != source.cache_key
            or result.spec.viewport_generation != self._viewport_generation
        ):
            return
        if result.cancelled:
            return
        unavailable_key = (result.spec.generation, result.spec.key)
        if result.tile is None:
            self._unavailable.add(unavailable_key)
            if result.spec.key in self._viewport_keys and result.error:
                self.tile_failed.emit(result.error)
            return
        self.cache.put(result.tile)
        if result.spec.key in self._viewport_keys:
            self.tile_ready.emit(result.tile)

    def close(self) -> None:
        self._closed = True
        self._cancel_event.set()
        self.thread_pool.clear()
        self._pending.clear()
        self._generation += 1
        self._viewport_generation += 1
        self._viewport_keys = frozenset()
        self._source = None
        self._unavailable.clear()
        self.cache.clear()

    release = close


__all__ = [
    "AudioSliceLoader",
    "DEFAULT_SPECTROGRAM_CACHE_BYTES",
    "SPECTROGRAM_LAYER",
    "SpectrogramSource",
    "SpectrogramTileController",
]
