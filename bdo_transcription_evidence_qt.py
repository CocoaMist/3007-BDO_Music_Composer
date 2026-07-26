"""Asynchronous, bounded Qt image tiles for transcription evidence.

The note editor must never scan a full Basic Pitch matrix from ``paintEvent``.
This module keeps that boundary explicit: callers request the visible five
second tiles, receive immutable ``QImage`` values, and only need to call
``QPainter.drawImage``.

The descriptor is deliberately duck typed.  A transcription backend may expose
layer paths, disposable memory maps, or an ``open_layer``/``load_layer`` method
without importing a UI-facing descriptor class here.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import math
from pathlib import Path
import re
import threading
from typing import Any, Callable, Mapping, Protocol

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QImage


TILE_DURATION_MS = 5_000.0
DEFAULT_IMAGE_CACHE_BYTES = 48 * 1024 * 1024
DEFAULT_EVIDENCE_INTENSITY = 1.0
MAX_EVIDENCE_INTENSITY = 2.0
EVIDENCE_INTENSITY_QUANTIZATION = 100
MAX_TILE_COLUMNS = 4_096
SUPPORTED_LAYERS = frozenset(("frame", "onset", "contour"))

_DEFAULT_SAMPLE_RATE = 22_050.0
_DEFAULT_HOP_LENGTH = 256.0
_DEFAULT_MIDI_MIN = 21.0
_SAFE_CACHE_KEY = re.compile(r"[0-9a-f]{24}")


class EvidenceDescriptorLike(Protocol):
    """Minimum descriptor surface used by :class:`EvidenceTileController`."""

    cache_key: str


LayerLoader = Callable[[object, str], object | None]


@dataclass(frozen=True)
class EvidenceTileKey:
    cache_key: str
    layer: str
    tile_index: int
    pitch_min: int
    pitch_max: int
    output_columns_hint: int
    intensity_percent: int = 100


@dataclass(frozen=True)
class EvidenceTile:
    """One ready-to-draw evidence image.

    ``pitch_max_exclusive`` is convenient for mapping the image to piano-roll
    rows: the image spans ``pitch_min <= pitch < pitch_max_exclusive``.
    """

    key: EvidenceTileKey
    generation: int
    time_start_ms: float
    time_end_ms: float
    pitch_min: float
    pitch_max_exclusive: float
    bins_per_semitone: int
    image: QImage

    @property
    def layer(self) -> str:
        return self.key.layer

    @property
    def cache_key(self) -> str:
        return self.key.cache_key

    @property
    def byte_count(self) -> int:
        return int(self.image.sizeInBytes())


class EvidenceImageCache:
    """Byte-bounded least-recently-used cache for implicitly shared QImages."""

    def __init__(self, max_bytes: int = DEFAULT_IMAGE_CACHE_BYTES) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self._entries: OrderedDict[EvidenceTileKey, EvidenceTile] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    @property
    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, key: EvidenceTileKey) -> EvidenceTile | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, tile: EvidenceTile) -> bool:
        size = tile.byte_count
        if size <= 0 or size > self.max_bytes:
            return False
        with self._lock:
            previous = self._entries.pop(tile.key, None)
            if previous is not None:
                self._bytes -= previous.byte_count
            self._entries[tile.key] = tile
            self._bytes += size
            while self._bytes > self.max_bytes and self._entries:
                _key, evicted = self._entries.popitem(last=False)
                self._bytes -= evicted.byte_count
        return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0


@dataclass(frozen=True)
class _LayerMetadata:
    midi_min: float
    bins_per_semitone: int
    time_origin_ms: float
    frame_period_ms: float
    frame_times_source: object | None


@dataclass(frozen=True)
class _CachedFrameTimes:
    cache_key: str
    cache_root: Path | None = None


@dataclass(frozen=True)
class _TileSpec:
    key: EvidenceTileKey
    generation: int
    viewport_generation: int
    time_start_ms: float
    time_end_ms: float


@dataclass(frozen=True)
class _TileResult:
    spec: _TileSpec
    tile: EvidenceTile | None = None
    error: str = ""


class _WorkerSignals(QObject):
    finished = Signal(object)


def _descriptor_value(
    descriptor: object,
    name: str,
    default: object | None = None,
) -> object | None:
    if isinstance(descriptor, Mapping):
        return descriptor.get(name, default)
    return getattr(descriptor, name, default)


def _mapping_value(value: object, name: str, default: object | None = None) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _descriptor_cache_key(descriptor: object) -> str:
    cache_key = str(_descriptor_value(descriptor, "cache_key", "") or "")
    if not cache_key:
        raise ValueError("evidence descriptor has no cache_key")
    return cache_key


def _effective_descriptor(descriptor: object) -> object:
    nested = _descriptor_value(descriptor, "evidence_descriptor", None)
    return nested if nested is not None else descriptor


def _descriptor_has_layer(descriptor: object, layer: str) -> bool:
    available = _descriptor_value(descriptor, "evidence_layers", None)
    if available is None:
        available = _descriptor_value(descriptor, "available_layers", None)
    if available is None:
        available = _descriptor_value(descriptor, "layer_names", None)
    if available is None:
        layer_values = _descriptor_value(descriptor, "layers", None)
        if isinstance(layer_values, (tuple, list)) and layer_values:
            available = tuple(
                str(_mapping_value(value, "name", ""))
                for value in layer_values
            )
    if available is None:
        return True
    if isinstance(available, Mapping):
        return layer in available
    try:
        return layer in available
    except TypeError:
        return True


def _layer_descriptor(descriptor: object, layer: str) -> object | None:
    layer_method = _descriptor_value(descriptor, "layer", None)
    if callable(layer_method):
        try:
            value = layer_method(layer)
        except (KeyError, TypeError):
            value = None
        if value is not None:
            return value
    metadata_method = _descriptor_value(descriptor, "layer_metadata", None)
    if callable(metadata_method):
        try:
            value = metadata_method(layer)
        except (KeyError, TypeError):
            value = None
        if value is not None:
            return value
    for name in ("layers", "layer_info", "layer_descriptors"):
        collection = _descriptor_value(descriptor, name, None)
        if isinstance(collection, Mapping) and layer in collection:
            return collection[layer]
        if isinstance(collection, (tuple, list)):
            for value in collection:
                if str(_mapping_value(value, "name", "") or "") == layer:
                    return value
    return None


def _descriptor_cache_file(
    descriptor: object,
    filename: object,
) -> Path | None:
    cache_key = _descriptor_cache_key(descriptor)
    filename_text = str(filename or "")
    if (
        _SAFE_CACHE_KEY.fullmatch(cache_key) is None
        or not filename_text
        or Path(filename_text).name != filename_text
    ):
        return None
    cache_root = _descriptor_value(descriptor, "cache_root", None)
    if cache_root is None:
        try:
            from project_paths import TRANSCRIPTION_CACHE_DIR

            cache_root = TRANSCRIPTION_CACHE_DIR
        except ImportError:
            return None
    return Path(cache_root) / cache_key / filename_text


def _numeric_value(
    descriptor: object,
    layer_value: object | None,
    names: tuple[str, ...],
    default: float,
) -> float:
    for source in (layer_value, descriptor):
        if source is None:
            continue
        for name in names:
            value = _mapping_value(source, name, None)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return float(default)


def _frame_times_source(
    descriptor: object,
    layer_value: object | None,
    layer: str,
) -> object | None:
    for source in (layer_value, descriptor):
        if source is None:
            continue
        for name in ("frame_times_ms", "times_ms", "time_values_ms"):
            value = _mapping_value(source, name, None)
            if isinstance(value, Mapping):
                value = value.get(layer)
            if value is not None:
                return value
        for name in ("frame_times_path", "times_path"):
            value = _mapping_value(source, name, None)
            if isinstance(value, Mapping):
                value = value.get(layer)
            if value is not None:
                return value
    times_filename = _descriptor_value(descriptor, "times_filename", None)
    if times_filename is not None:
        cache_root = _descriptor_value(descriptor, "cache_root", None)
        return _CachedFrameTimes(
            _descriptor_cache_key(descriptor),
            Path(cache_root) if cache_root is not None else None,
        )
    return None


def _layer_metadata(descriptor: object, layer: str) -> _LayerMetadata:
    layer_value = _layer_descriptor(descriptor, layer)
    default_bps = 3 if layer == "contour" else 1
    midi_min = _numeric_value(
        descriptor,
        layer_value,
        ("midi_min", "fmin_midi", "pitch_min"),
        _DEFAULT_MIDI_MIN,
    )
    bins_per_semitone = max(
        1,
        round(
            _numeric_value(
                descriptor,
                layer_value,
                ("bins_per_semitone", "pitch_bins_per_semitone"),
                default_bps,
            )
        ),
    )
    sample_rate = _numeric_value(
        descriptor,
        layer_value,
        ("sample_rate", "audio_sample_rate"),
        _DEFAULT_SAMPLE_RATE,
    )
    hop_length = _numeric_value(
        descriptor,
        layer_value,
        ("hop_length", "fft_hop"),
        _DEFAULT_HOP_LENGTH,
    )
    frame_rate = _numeric_value(
        descriptor,
        layer_value,
        ("frame_rate", "frames_per_second", "fps"),
        0.0,
    )
    fallback_period = (
        1000.0 / frame_rate
        if frame_rate > 0.0
        else 1000.0 * hop_length / max(1.0, sample_rate)
    )
    frame_period_ms = max(
        1e-6,
        _numeric_value(
            descriptor,
            layer_value,
            ("frame_period_ms", "time_step_ms", "hop_ms"),
            fallback_period,
        ),
    )
    time_origin_ms = _numeric_value(
        descriptor,
        layer_value,
        ("time_origin_ms", "first_frame_ms"),
        0.0,
    )
    return _LayerMetadata(
        midi_min,
        bins_per_semitone,
        time_origin_ms,
        frame_period_ms,
        _frame_times_source(descriptor, layer_value, layer),
    )


def _close_memmap(value: object | None) -> None:
    """Release NumPy mmap ownership without retaining Windows file handles."""

    visited: set[int] = set()
    current = value
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        mmap_handle = getattr(current, "_mmap", None)
        if mmap_handle is not None:
            try:
                mmap_handle.close()
            except (BufferError, OSError, ValueError):
                pass
        current = getattr(current, "base", None)


def _call_release(callback: Callable[..., object], array: object) -> None:
    try:
        callback(array)
    except TypeError:
        callback()


def _normalise_opened_value(value: object | None) -> tuple[np.ndarray | None, Callable[[], None]]:
    if value is None:
        return None, lambda: None
    release_callback: Callable[..., object] | None = None
    entered_context: object | None = None
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and callable(value[1])
    ):
        value, release_callback = value
    elif isinstance(value, Mapping):
        release_value = value.get("release")
        release_callback = release_value if callable(release_value) else None
        array_value = value.get("array")
        value = array_value if array_value is not None else value.get("path")
    elif (
        not isinstance(value, (str, Path, np.ndarray))
        and hasattr(value, "__enter__")
        and hasattr(value, "__exit__")
    ):
        entered_context = value
        value = value.__enter__()

    if isinstance(value, (str, Path)):
        array = np.load(Path(value), mmap_mode="r", allow_pickle=False)
    else:
        try:
            array = np.asanyarray(value)
        except (TypeError, ValueError):
            array = None

    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        try:
            if release_callback is not None:
                try:
                    _call_release(release_callback, array)
                except Exception:
                    pass
        finally:
            _close_memmap(array)
            if entered_context is not None:
                try:
                    entered_context.__exit__(None, None, None)
                except Exception:
                    pass

    return array, release


def _open_layer(
    descriptor: object,
    layer: str,
    loader: LayerLoader | None,
) -> tuple[np.ndarray | None, Callable[[], None]]:
    value: object | None = None
    if loader is not None:
        value = loader(descriptor, layer)
    else:
        for method_name in ("open_layer", "load_layer", "open_evidence_layer"):
            method = _descriptor_value(descriptor, method_name, None)
            if callable(method):
                try:
                    value = method(layer)
                except (KeyError, TypeError):
                    value = None
                if value is not None:
                    break
        if value is None:
            for collection_name in ("layer_paths", "evidence_paths"):
                collection = _descriptor_value(descriptor, collection_name, None)
                if isinstance(collection, Mapping):
                    value = collection.get(layer)
                    if value is not None:
                        break
        if value is None:
            layer_value = _layer_descriptor(descriptor, layer)
            if isinstance(layer_value, (str, Path, np.ndarray)):
                value = layer_value
            elif isinstance(layer_value, Mapping):
                # Preserve an optional ``release`` callback carried alongside
                # the array/path instead of stripping the mapping here.
                value = layer_value
            elif layer_value is not None:
                filename = _mapping_value(layer_value, "filename", None)
                if filename is not None:
                    value = _descriptor_cache_file(descriptor, filename)
        if value is None:
            cache_root = _descriptor_value(descriptor, "cache_root", None)
            if cache_root is not None:
                candidate = Path(cache_root) / _descriptor_cache_key(descriptor) / f"{layer}.npy"
                if candidate.is_file():
                    value = candidate
        if value is None:
            # Compatibility with the current cache service.  The import is lazy
            # so Basic Pitch/ONNX backend modules never become Qt dependencies.
            try:
                from bdo_transcription import load_transcription_evidence

                value = load_transcription_evidence(
                    _descriptor_cache_key(descriptor),
                    layer,
                )
            except (ImportError, OSError, ValueError):
                value = None
    return _normalise_opened_value(value)


def _open_time_values(source: object | None) -> tuple[np.ndarray | None, Callable[[], None]]:
    if isinstance(source, _CachedFrameTimes):
        try:
            from bdo_transcription import load_transcription_frame_times

            if source.cache_root is None:
                value = load_transcription_frame_times(source.cache_key)
            else:
                value = load_transcription_frame_times(
                    source.cache_key,
                    cache_root=source.cache_root,
                )
        except (ImportError, OSError, ValueError):
            value = None
        return _normalise_opened_value(value)
    return _normalise_opened_value(source)


def _time_frame_selection(
    frame_count: int,
    metadata: _LayerMetadata,
    start_ms: float,
    end_ms: float,
) -> tuple[int, int, np.ndarray]:
    values, release = _open_time_values(metadata.frame_times_source)
    try:
        if values is not None and values.ndim == 1 and values.size >= frame_count:
            times = values[:frame_count]
            lo = int(np.searchsorted(times, start_ms, side="left"))
            hi = int(np.searchsorted(times, end_ms, side="left"))
            lo = max(0, min(frame_count, lo))
            hi = max(0, min(frame_count, hi))
            return lo, hi, np.array(times[lo:hi], dtype=np.float64, copy=True)
    finally:
        release()
    lo = math.floor((start_ms - metadata.time_origin_ms) / metadata.frame_period_ms)
    hi = math.ceil((end_ms - metadata.time_origin_ms) / metadata.frame_period_ms)
    lo = max(0, min(frame_count, lo))
    hi = max(0, min(frame_count, hi))
    times = (
        metadata.time_origin_ms
        + np.arange(lo, hi, dtype=np.float64) * metadata.frame_period_ms
    )
    return lo, hi, times


def _pitch_bin_bounds(
    bin_count: int,
    metadata: _LayerMetadata,
    pitch_min: int,
    pitch_max: int,
) -> tuple[int, int]:
    low = math.floor((float(pitch_min) - metadata.midi_min) * metadata.bins_per_semitone)
    high = math.ceil(
        (float(pitch_max) + 1.0 - metadata.midi_min)
        * metadata.bins_per_semitone
    )
    return max(0, min(bin_count, low)), max(0, min(bin_count, high))


def _pool_time(
    matrix: np.ndarray,
    frame_times_ms: np.ndarray,
    time_start_ms: float,
    time_end_ms: float,
    output_columns: int,
    *,
    use_maximum: bool,
) -> np.ndarray:
    frame_count = int(matrix.shape[0])
    output_columns = max(1, int(output_columns))
    if frame_times_ms.shape != (frame_count,):
        raise ValueError("evidence values and frame times do not align")
    boundaries = np.linspace(
        float(time_start_ms),
        float(time_end_ms),
        output_columns + 1,
        dtype=np.float64,
    )
    frame_boundaries = np.searchsorted(
        frame_times_ms,
        boundaries,
        side="left",
    )
    pooled = np.empty((output_columns, matrix.shape[1]), dtype=np.float32)
    for index in range(output_columns):
        first = int(frame_boundaries[index])
        last = int(frame_boundaries[index + 1])
        if last <= first:
            pooled[index].fill(0.0)
            continue
        block = matrix[first:last]
        if use_maximum:
            pooled[index] = np.max(block, axis=0)
        else:
            pooled[index] = np.percentile(block, 95.0, axis=0)
    return pooled


def _quantized_intensity_percent(intensity: float) -> int:
    value = float(intensity)
    if not math.isfinite(value):
        value = DEFAULT_EVIDENCE_INTENSITY
    value = min(MAX_EVIDENCE_INTENSITY, max(0.0, value))
    return int(math.floor(value * EVIDENCE_INTENSITY_QUANTIZATION + 0.5))


def _rgba_image(
    matrix: np.ndarray,
    layer: str,
    intensity: float = DEFAULT_EVIDENCE_INTENSITY,
) -> QImage:
    values = np.nan_to_num(matrix, nan=0.0, posinf=1.0, neginf=0.0)
    values = np.clip(values, 0.0, 1.0)
    if layer == "onset":
        rgb = (220, 164, 82)
        threshold, maximum_alpha, gamma = 0.10, 118, 0.72
    elif layer == "contour":
        rgb = (107, 182, 177)
        threshold, maximum_alpha, gamma = 0.08, 84, 0.78
    else:
        rgb = (116, 145, 157)
        threshold, maximum_alpha, gamma = 0.06, 72, 0.80
    strength = np.clip((values - threshold) / max(1e-6, 1.0 - threshold), 0.0, 1.0)
    alpha = np.rint(
        np.clip(
            np.power(strength, gamma) * maximum_alpha * float(intensity),
            0.0,
            255.0,
        )
    ).astype(np.uint8)
    # Matrix is time x pitch.  Piano rolls paint high notes at the top.
    alpha = alpha.T[::-1, :]
    height, width = alpha.shape
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[:, :, 0] = rgb[0]
    rgba[:, :, 1] = rgb[1]
    rgba[:, :, 2] = rgb[2]
    rgba[:, :, 3] = alpha
    image = QImage(
        rgba.data,
        width,
        height,
        int(rgba.strides[0]),
        QImage.Format.Format_RGBA8888,
    )
    # Detach from NumPy before the worker releases its local buffers.
    return image.copy()


class _EvidenceTileRunnable(QRunnable):
    def __init__(
        self,
        descriptor: object,
        spec: _TileSpec,
        loader: LayerLoader | None,
    ) -> None:
        super().__init__()
        self.descriptor = descriptor
        self.spec = spec
        self.loader = loader
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        array: np.ndarray | None = None
        release: Callable[[], None] = lambda: None
        try:
            metadata = _layer_metadata(self.descriptor, self.spec.key.layer)
            array, release = _open_layer(
                self.descriptor,
                self.spec.key.layer,
                self.loader,
            )
            if array is None or array.ndim != 2:
                raise ValueError(
                    f"{self.spec.key.layer} evidence is unavailable or not two-dimensional"
                )
            time_axis = int(
                _numeric_value(
                    self.descriptor,
                    _layer_descriptor(self.descriptor, self.spec.key.layer),
                    ("time_axis",),
                    0.0,
                )
            )
            matrix = array.T if time_axis == 1 else array
            frame_lo, frame_hi, frame_times_ms = _time_frame_selection(
                int(matrix.shape[0]),
                metadata,
                self.spec.time_start_ms,
                self.spec.time_end_ms,
            )
            bin_lo, bin_hi = _pitch_bin_bounds(
                int(matrix.shape[1]),
                metadata,
                self.spec.key.pitch_min,
                self.spec.key.pitch_max,
            )
            if frame_hi <= frame_lo or bin_hi <= bin_lo:
                # Empty overlap is a normal viewport condition (for example
                # MIDI rows below A0), not an analysis/cache failure.
                self.signals.finished.emit(_TileResult(self.spec))
                return
            # Copy only the visible slice before closing the mmap.  All pooling
            # and colour work then happens on bounded, owned memory.
            visible = np.array(
                matrix[frame_lo:frame_hi, bin_lo:bin_hi],
                dtype=np.float32,
                copy=True,
            )
        except Exception as exc:
            self.signals.finished.emit(_TileResult(self.spec, error=str(exc)))
            return
        finally:
            release()
            array = None

        try:
            pooled = _pool_time(
                visible,
                frame_times_ms,
                self.spec.time_start_ms,
                self.spec.time_end_ms,
                self.spec.key.output_columns_hint,
                use_maximum=self.spec.key.layer == "onset",
            )
            image = _rgba_image(
                pooled,
                self.spec.key.layer,
                self.spec.key.intensity_percent
                / EVIDENCE_INTENSITY_QUANTIZATION,
            )
            tile = EvidenceTile(
                self.spec.key,
                self.spec.generation,
                self.spec.time_start_ms,
                self.spec.time_end_ms,
                metadata.midi_min
                + bin_lo / metadata.bins_per_semitone,
                metadata.midi_min
                + bin_hi / metadata.bins_per_semitone,
                metadata.bins_per_semitone,
                image,
            )
            self.signals.finished.emit(_TileResult(self.spec, tile=tile))
        except Exception as exc:
            self.signals.finished.emit(_TileResult(self.spec, error=str(exc)))


class EvidenceTileController(QObject):
    """Request visible evidence tiles without blocking paint or audio threads."""

    tile_ready = Signal(object)
    tile_failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        cache_bytes: int = DEFAULT_IMAGE_CACHE_BYTES,
        max_workers: int = 2,
        layer_loader: LayerLoader | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = EvidenceImageCache(cache_bytes)
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(max(1, int(max_workers)))
        self.layer_loader = layer_loader
        self._generation = 0
        self._viewport_generation = 0
        self._viewport_keys: frozenset[EvidenceTileKey] = frozenset()
        self._active_cache_key = ""
        self._descriptor: object | None = None
        self._pending: set[tuple[int, int, EvidenceTileKey]] = set()
        self._unavailable: set[tuple[int, EvidenceTileKey]] = set()
        self._closed = False

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def active_cache_key(self) -> str:
        return self._active_cache_key

    def _invalidate_pending_work(self) -> None:
        """Forget work that Qt may remove without running its callback.

        ``QThreadPool.clear()`` deletes queued runnables, so their ``finished``
        signal is never emitted.  Clear the matching bookkeeping at the same
        time.  Already-running jobs may still emit, but their source/viewport
        generation is stale and cannot remove or wake a newer request.
        """

        self.thread_pool.clear()
        self._pending.clear()

    def _set_viewport(self, keys: frozenset[EvidenceTileKey]) -> None:
        """Advance the viewport generation when the requested tile set changes."""

        if keys == self._viewport_keys:
            return
        self._viewport_generation += 1
        self._viewport_keys = keys
        # Prevent obsolete queued tiles from delaying the newly visible set.
        # Running jobs remain bounded by ``maxThreadCount`` and are rejected by
        # ``viewport_generation`` when their queued signal reaches this object.
        self._invalidate_pending_work()

    def begin_source(self, descriptor: EvidenceDescriptorLike | object) -> int:
        """Start a generation and invalidate all in-flight results logically."""

        descriptor = _effective_descriptor(descriptor)
        self._invalidate_pending_work()
        self._generation += 1
        self._viewport_generation += 1
        self._viewport_keys = frozenset()
        self._active_cache_key = _descriptor_cache_key(descriptor)
        self._descriptor = descriptor
        self._unavailable.clear()
        self._closed = False
        return self._generation

    set_source = begin_source

    def _columns_hint(
        self,
        descriptor: object,
        layer: str,
        pixels_per_ms: float,
    ) -> int:
        metadata = _layer_metadata(descriptor, layer)
        source_columns = max(
            1,
            math.ceil(TILE_DURATION_MS / metadata.frame_period_ms) + 2,
        )
        pixel_columns = max(1, math.ceil(TILE_DURATION_MS * pixels_per_ms))
        return min(MAX_TILE_COLUMNS, source_columns, pixel_columns)

    def request_visible(
        self,
        descriptor: EvidenceDescriptorLike | object | None = None,
        *,
        start_ms: float,
        end_ms: float,
        pitch_min: int,
        pitch_max: int,
        pixels_per_ms: float,
        generation: int | None = None,
        layers: tuple[str, ...] = ("frame", "onset"),
        include_contour: bool = False,
        intensity: float = DEFAULT_EVIDENCE_INTENSITY,
        update_viewport: bool = True,
    ) -> tuple[EvidenceTile, ...]:
        """Return cached visible tiles and schedule missing ones.

        The caller can immediately draw the returned images.  ``tile_ready`` is
        emitted later for each current-generation miss, normally triggering a
        bounded canvas update.
        """

        if self._closed:
            return ()
        if descriptor is not None:
            descriptor = _effective_descriptor(descriptor)
            cache_key = _descriptor_cache_key(descriptor)
            if not self._active_cache_key:
                generation = self.begin_source(descriptor)
            elif cache_key != self._active_cache_key:
                if generation is not None:
                    # A late paint/request from an old source must not switch
                    # the provider back after the host began a new generation.
                    return ()
                generation = self.begin_source(descriptor)
            else:
                self._descriptor = descriptor
        if self._descriptor is None:
            return ()
        requested_generation = self._generation if generation is None else int(generation)
        if (
            requested_generation != self._generation
            or _descriptor_cache_key(self._descriptor) != self._active_cache_key
        ):
            return ()

        start = max(0.0, float(start_ms))
        end = max(start, float(end_ms))
        duration_value = _descriptor_value(
            self._descriptor,
            "duration_ms",
            None,
        )
        try:
            duration_ms = float(duration_value)
        except (TypeError, ValueError):
            duration_ms = 0.0
        if math.isfinite(duration_ms) and duration_ms > 0.0:
            if start >= duration_ms:
                self._set_viewport(frozenset())
                return ()
            end = min(end, duration_ms)
        if end <= start or int(pitch_max) < int(pitch_min):
            self._set_viewport(frozenset())
            return ()
        intensity_percent = _quantized_intensity_percent(intensity)
        requested_layers = [
            layer
            for layer in layers
            if layer in SUPPORTED_LAYERS
        ]
        if include_contour and "contour" not in requested_layers:
            requested_layers.append("contour")
        first_tile = max(0, math.floor(start / TILE_DURATION_MS))
        last_tile = max(
            first_tile,
            math.floor(max(start, end - 1e-6) / TILE_DURATION_MS),
        )
        requested_keys: list[EvidenceTileKey] = []
        for layer in requested_layers:
            if not _descriptor_has_layer(self._descriptor, layer):
                continue
            columns_hint = self._columns_hint(
                self._descriptor,
                layer,
                max(1e-7, float(pixels_per_ms)),
            )
            requested_keys.extend(
                EvidenceTileKey(
                    self._active_cache_key,
                    layer,
                    tile_index,
                    int(pitch_min),
                    int(pitch_max),
                    columns_hint,
                    intensity_percent,
                )
                for tile_index in range(first_tile, last_tile + 1)
            )
        if update_viewport:
            self._set_viewport(frozenset(requested_keys))

        ready: list[EvidenceTile] = []
        for key in requested_keys:
            cached = self.cache.get(key)
            if cached is not None:
                if cached.generation != requested_generation:
                    cached = replace(
                        cached,
                        generation=requested_generation,
                    )
                ready.append(cached)
                continue
            if not update_viewport:
                # Cursor-only repaints consume ready images without replacing
                # the actual scroll/zoom viewport or queuing duplicate work.
                continue
            unavailable_key = (requested_generation, key)
            pending_key = (
                requested_generation,
                self._viewport_generation,
                key,
            )
            if (
                pending_key in self._pending
                or unavailable_key in self._unavailable
            ):
                continue
            spec = _TileSpec(
                key,
                requested_generation,
                self._viewport_generation,
                key.tile_index * TILE_DURATION_MS,
                (key.tile_index + 1) * TILE_DURATION_MS,
            )
            worker = _EvidenceTileRunnable(
                self._descriptor,
                spec,
                self.layer_loader,
            )
            worker.signals.finished.connect(
                self._worker_finished,
                Qt.ConnectionType.QueuedConnection,
            )
            self._pending.add(pending_key)
            self.thread_pool.start(worker)
        layer_order = {"frame": 0, "contour": 1, "onset": 2}
        ready.sort(
            key=lambda tile: (
                tile.time_start_ms,
                layer_order.get(tile.layer, 99),
            )
        )
        return tuple(ready)

    @Slot(object)
    def _worker_finished(self, result: _TileResult) -> None:
        pending_key = (
            result.spec.generation,
            result.spec.viewport_generation,
            result.spec.key,
        )
        self._pending.discard(pending_key)
        if (
            self._closed
            or result.spec.generation != self._generation
            or result.spec.key.cache_key != self._active_cache_key
        ):
            return
        unavailable_key = (result.spec.generation, result.spec.key)
        if result.tile is None:
            self._unavailable.add(unavailable_key)
            if (
                result.error
                and result.spec.viewport_generation == self._viewport_generation
                and result.spec.key in self._viewport_keys
            ):
                self.tile_failed.emit(result.error)
            return
        self.cache.put(result.tile)
        if (
            result.spec.viewport_generation == self._viewport_generation
            and result.spec.key in self._viewport_keys
        ):
            self.tile_ready.emit(result.tile)

    def close(self) -> None:
        """Invalidate work and release cached QImages without blocking the GUI."""

        if self._closed:
            return
        self._closed = True
        self._invalidate_pending_work()
        self._generation += 1
        self._viewport_generation += 1
        self._viewport_keys = frozenset()
        self._active_cache_key = ""
        self._descriptor = None
        self._unavailable.clear()
        self.cache.clear()
        # Already-running workers finish their small visible slice and close
        # their mmap in ``finally``; generation guards reject their result.

    release = close


# ``Provider`` is the public integration name; ``Controller`` remains an
# explicit compatibility spelling for tests and early callers.
EvidenceTileProvider = EvidenceTileController


__all__ = [
    "DEFAULT_EVIDENCE_INTENSITY",
    "DEFAULT_IMAGE_CACHE_BYTES",
    "EVIDENCE_INTENSITY_QUANTIZATION",
    "EvidenceDescriptorLike",
    "EvidenceImageCache",
    "EvidenceTile",
    "EvidenceTileController",
    "EvidenceTileProvider",
    "EvidenceTileKey",
    "MAX_EVIDENCE_INTENSITY",
    "MAX_TILE_COLUMNS",
    "SUPPORTED_LAYERS",
    "TILE_DURATION_MS",
]
