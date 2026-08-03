"""Optional, local Basic Pitch transcription for the note editor.

The module is deliberately independent from Qt and the editor's authoritative
``Note`` wire shape. It returns immutable candidates plus cached evidence; the
UI decides whether any candidate becomes a real editor note.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
import hashlib
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from typing import Callable, Literal, Protocol, runtime_checkable
import warnings

import numpy as np

from bdo_music_composer.transcription.bdo_transcription_postprocess import (
    BALANCED_CLEANUP_PROFILE,
    CLEAN_CLEANUP_PROFILE,
    POSTPROCESS_VERSION,
    PRESERVE_CLEANUP_PROFILE,
    CleanupProfile,
    FrameNoteEvent,
    FragmentPostprocessResult,
    postprocess_frame_events,
)
from bdo_music_composer.core.project_paths import TRANSCRIPTION_CACHE_DIR


ProgressCallback = Callable[[int], None]
CancelCallback = Callable[[], bool]

TRANSCRIPTION_CACHE_VERSION = 4
# Update this identifier whenever the backend package, bundled model, or
# interpretation of its output changes. It intentionally participates in the
# cache key so evidence produced by different models can never be mixed.
TRANSCRIPTION_BACKEND_ID = "basic-pitch-0.4.0:icassp-2022-onnx:fusion-v3"
STANDARD_ANALYSIS_MODE = "standard"
MIXED_ENHANCED_ANALYSIS_MODE = "mixed_enhanced"
# BabySlakh Track00013-00020 passed every fixed v2 accuracy/resource gate:
# +0.02222 onset+offset F1, 1.9668x runtime, and 414.22 MiB peak working set.
MIXED_ENHANCED_RELEASE_DEFAULT_VERIFIED = True
DEFAULT_TRANSCRIPTION_ANALYSIS_MODE = (
    MIXED_ENHANCED_ANALYSIS_MODE
    if MIXED_ENHANCED_RELEASE_DEFAULT_VERIFIED
    else STANDARD_ANALYSIS_MODE
)
TRANSCRIPTION_FUSION_VERSION = (
    "hpss-fast-stream-30s-2s-1024-512-k9:v2"
)
HPSS_BLOCK_SECONDS = 30.0
HPSS_OVERLAP_SECONDS = 2.0
HPSS_N_FFT = 1024
HPSS_HOP_LENGTH = 512
HPSS_KERNEL_SIZE = 9
HPSS_POWER = 2.0
HPSS_MARGIN = 1.0
# Selected once from the 243-config Track00001-00012 tuning search, then
# validated once on Track00013-00020. These values are never tuned at runtime.
MIXED_ENHANCED_FRAME_HARMONIC_WEIGHT = 0.55
MIXED_ENHANCED_ONSET_HARMONIC_WEIGHT = 0.25
MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT = 0.70
MIXED_ENHANCED_BALANCED_ONSET_THRESHOLD = 0.55
MIXED_ENHANCED_BALANCED_FRAME_THRESHOLD = 0.25
MIXED_ENHANCED_BALANCED_MIN_NOTE_LENGTH_FRAMES = 5
TRANSCRIPTION_CACHE_MAX_BYTES = 2 * 1024**3
TRANSCRIPTION_CACHE_MAX_ENTRIES = 128
_CACHE_KEY_PATTERN = re.compile(r"[0-9a-f]{24}")
_WORKSPACE_NAME_PATTERN = re.compile(
    r"\.transcription-work-[0-9a-z_-]{8,64}"
)
_WORKSPACE_STALE_SECONDS = 24 * 60 * 60
_STREAM_DECODE_FRAMES = 65_536
ONSET_THRESHOLD = 0.5
FRAME_THRESHOLD = 0.3
TRANSCRIPTION_MIDI_MIN = 21
TRANSCRIPTION_NOTE_BINS = 88
TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE = 3
TRANSCRIPTION_TIME_DTYPE = np.dtype("<f8")
TRANSCRIPTION_EVIDENCE_DTYPE = np.dtype("<f2")
_AUDIO_FINGERPRINT_CHUNK_BYTES = 1024 * 1024
_CACHE_VALIDATION_CHUNK_ELEMENTS = 1024 * 1024
STANDARD_TRANSCRIPTION_SENSITIVITY_PRESETS: dict[
    str, tuple[float, float]
] = {
    "conservative": (0.65, 0.45),
    "balanced": (ONSET_THRESHOLD, FRAME_THRESHOLD),
    "sensitive": (0.35, 0.20),
}
# Compatibility alias retained for callers that inspect the original mapping.
TRANSCRIPTION_SENSITIVITY_PRESETS = (
    STANDARD_TRANSCRIPTION_SENSITIVITY_PRESETS
)
STANDARD_MIN_NOTE_LENGTH_FRAMES: dict[str, int] = {
    "conservative": 14,
    "balanced": 11,
    "sensitive": 8,
}
DENSE_SHORT_MIN_FRAMES = 2
DENSE_SHORT_MAX_GAP_FRAMES = 8
DENSE_SHORT_REGULARITY_TOLERANCE = 0.35
TranscriptionSensitivity = Literal["conservative", "balanced", "sensitive"]
TranscriptionAnalysisMode = Literal["standard", "mixed_enhanced"]
TRANSCRIPTION_CLEANUP_PROFILES = frozenset(
    (
        PRESERVE_CLEANUP_PROFILE,
        BALANCED_CLEANUP_PROFILE,
        CLEAN_CLEANUP_PROFILE,
    )
)
DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE: CleanupProfile = (
    PRESERVE_CLEANUP_PROFILE
)
LEGACY_TRANSCRIPTION_CLEANUP_PROFILE: CleanupProfile = (
    PRESERVE_CLEANUP_PROFILE
)
LEGACY_TRANSCRIPTION_POSTPROCESS_VERSION = "legacy"
FROZEN_BACKEND_UNAVAILABLE_MESSAGE = (
    "本地扒谱引擎未能加载，当前程序安装可能不完整。"
    "请重新构建或安装完整程序后再试。"
)
SOURCE_BACKEND_UNAVAILABLE_MESSAGE = (
    "扒谱组件尚未安装或不可用。请在程序目录运行：\n"
    "powershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1"
)
BACKEND_CHECK_FAILED_MESSAGE = (
    "扒谱组件检查失败。详细原因已写入日志。"
)
BACKEND_MODULE_LOAD_FAILED_MESSAGE = (
    "扒谱引擎加载失败（缺少运行模块）。详细原因已写入日志。"
)
_INFERENCE_LOCK = threading.Lock()
_ONNX_MODEL = None
_BACKEND_STATUS_LOCK = threading.RLock()
_BACKEND_STATUS_CACHE: dict[bool, tuple[bool, str]] = {}
_CACHE_VALIDATION_LOCK = threading.RLock()
_CACHE_VALIDATION_MAX_ENTRIES = 128


class TranscriptionError(RuntimeError):
    pass


class TranscriptionCancelled(TranscriptionError):
    pass


@dataclass(frozen=True)
class TranscriptionCandidate:
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float
    confidence: float
    source: str = "basic-pitch"
    # Excluded from equality so legacy callers constructing the original
    # five/six-field value continue to compare equal to identified candidates.
    candidate_id: str = field(default="", compare=False)

    @property
    def start(self) -> float:
        return self.start_ms

    @property
    def dur(self) -> float:
        return self.duration_ms

    @property
    def vel(self) -> int:
        return self.velocity


@dataclass(frozen=True)
class EvidenceLayerDescriptor:
    """Validated on-disk metadata for one frame-aligned evidence matrix."""

    name: str
    filename: str
    shape: tuple[int, int]
    dtype: str
    midi_min: int
    bins_per_semitone: int
    file_size: int
    sha256: str


@dataclass(frozen=True)
class EvidenceDescriptor:
    """Backend-independent description of a cached evidence timeline."""

    cache_key: str
    backend_id: str
    audio_fingerprint: str
    duration_ms: float
    frame_count: int
    times_filename: str
    times_shape: tuple[int]
    times_dtype: str
    times_file_size: int
    times_sha256: str
    analysis_mode: str = STANDARD_ANALYSIS_MODE
    fusion_version: str = TRANSCRIPTION_FUSION_VERSION
    decode_sensitivity: str = "balanced"
    cleanup_profile: str = LEGACY_TRANSCRIPTION_CLEANUP_PROFILE
    postprocess_version: str = LEGACY_TRANSCRIPTION_POSTPROCESS_VERSION
    midi_min: int = TRANSCRIPTION_MIDI_MIN
    layers: tuple[EvidenceLayerDescriptor, ...] = ()

    @property
    def layer_names(self) -> tuple[str, ...]:
        return tuple(layer.name for layer in self.layers)

    def layer(self, name: str) -> EvidenceLayerDescriptor | None:
        return next((layer for layer in self.layers if layer.name == name), None)


@dataclass(frozen=True)
class TranscriptionResult:
    candidates: tuple[TranscriptionCandidate, ...]
    cache_key: str
    evidence_layers: tuple[str, ...] = ()
    cache_hit: bool = False
    evidence_descriptor: EvidenceDescriptor | None = None
    postprocess_report: "TranscriptionPostprocessReport | None" = None


@dataclass(frozen=True)
class TranscriptionCandidateAnnotation:
    """Review-only metadata for one active or reversibly hidden candidate."""

    candidate_id: str
    flags: tuple[str, ...] = ()
    lineage_ids: tuple[str, ...] = ()
    disposition: str = "kept"


@dataclass(frozen=True)
class TranscriptionPostprocessReport:
    """Explainable fragment cleanup sidecar; never authoritative note data."""

    profile: str
    version: str
    raw_candidate_count: int
    output_candidate_count: int
    exact_duplicate_count: int
    nms_removed_count: int
    automatic_merge_count: int
    suspected_fragment_count: int
    severe_fragment_count: int
    density_short_count: int
    pitch_flicker_count: int
    suppressed_count: int
    annotations: tuple[TranscriptionCandidateAnnotation, ...] = ()
    suppressed_candidates: tuple[TranscriptionCandidate, ...] = ()
    automatic_actions_enabled: bool = False


def _empty_transcription_postprocess_report(
    profile: CleanupProfile | str,
) -> TranscriptionPostprocessReport:
    cleanup = normalise_transcription_cleanup_profile(profile)
    return TranscriptionPostprocessReport(
        profile=cleanup,
        version=POSTPROCESS_VERSION,
        raw_candidate_count=0,
        output_candidate_count=0,
        exact_duplicate_count=0,
        nms_removed_count=0,
        automatic_merge_count=0,
        suspected_fragment_count=0,
        severe_fragment_count=0,
        density_short_count=0,
        pitch_flicker_count=0,
        suppressed_count=0,
        automatic_actions_enabled=(
            cleanup != PRESERVE_CLEANUP_PROFILE
        ),
    )


@dataclass(frozen=True)
class _ValidatedCacheEntry:
    file_stamps: tuple[tuple[str, int, int, int, int], ...]
    candidates: tuple[TranscriptionCandidate, ...]
    descriptor: EvidenceDescriptor


@dataclass(frozen=True)
class _StreamedAudioBuffer:
    """Anonymous mono float32 audio stored in one guarded work directory."""

    path: Path
    sample_count: int
    sample_rate: int

    def open(self, mode: str = "r") -> np.memmap:
        if self.sample_count <= 0:
            raise TranscriptionError(
                "参考音频中没有可分析的音频帧"
            )
        return np.memmap(
            self.path,
            dtype=np.dtype("<f4"),
            mode=mode,
            shape=(self.sample_count,),
        )


_VALIDATED_CACHE_ENTRIES: OrderedDict[
    tuple[str, str],
    _ValidatedCacheEntry,
] = OrderedDict()


@runtime_checkable
class TranscriptionBackend(Protocol):
    """Qt-free backend contract used by editor/workspace adapters."""

    backend_id: str

    def status(self) -> tuple[bool, str]:
        ...

    def transcribe(
        self,
        audio_path: Path | str,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
        *,
        analysis_mode: TranscriptionAnalysisMode = (
            DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
        ),
        sensitivity: TranscriptionSensitivity = "balanced",
        cleanup_profile: CleanupProfile = (
            DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE
        ),
        cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    ) -> TranscriptionResult:
        ...

    def redecode_interval(
        self,
        cache_key: str,
        start_ms: float,
        end_ms: float,
        *,
        sensitivity: TranscriptionSensitivity = "balanced",
        cleanup_profile: CleanupProfile = (
            DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE
        ),
        context_ms: float = 500.0,
        cache_root: Path = TRANSCRIPTION_CACHE_DIR,
        cancelled: CancelCallback | None = None,
    ) -> TranscriptionResult:
        ...


def _backend_install_message() -> str:
    if getattr(sys, "frozen", False):
        return FROZEN_BACKEND_UNAVAILABLE_MESSAGE
    return SOURCE_BACKEND_UNAVAILABLE_MESSAGE


def _backend_import_failure_message(exc: ModuleNotFoundError) -> str:
    missing_root = str(exc.name or "").partition(".")[0]
    if missing_root in {"basic_pitch", "onnxruntime"}:
        return _backend_install_message()
    return BACKEND_MODULE_LOAD_FAILED_MESSAGE


class _OptionalBackendFilter(logging.Filter):
    PREFIXES = (
        "Coremltools is not installed.",
        "tflite-runtime is not installed.",
        "Tensorflow is not installed.",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith(self.PREFIXES)


def _import_basic_pitch():
    root_logger = logging.getLogger()
    backend_filter = _OptionalBackendFilter()
    root_logger.addFilter(backend_filter)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"pkg_resources is deprecated as an API\..*",
                category=UserWarning,
                module=r"resampy\.filters",
            )
            import basic_pitch
            import basic_pitch.inference as inference
            import basic_pitch.note_creation as note_creation
            import onnxruntime
    except ModuleNotFoundError as exc:
        # A missing top-level optional dependency is an installation issue.
        # A transitive import failure (for example a stdlib module omitted
        # from a frozen build) is a packaging/runtime defect and must not be
        # presented as the same "install the optional component" guidance.
        raise TranscriptionError(
            _backend_import_failure_message(exc)
        ) from exc
    finally:
        root_logger.removeFilter(backend_filter)
    return basic_pitch, inference, note_creation, onnxruntime


def transcription_backend_quick_status() -> tuple[bool, str]:
    """Return a cheap UI hint without importing Basic Pitch or ONNX Runtime.

    A positive result only means the required top-level packages are
    discoverable. It deliberately does not claim that the model or CPU
    provider can be loaded; the full status check remains the fail-closed
    analysis boundary.
    """

    try:
        missing = [
            name
            for name in ("basic_pitch", "onnxruntime", "librosa")
            if importlib.util.find_spec(name) is None
        ]
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "transcription backend discovery failed: %s",
            exc,
        )
        return False, BACKEND_CHECK_FAILED_MESSAGE
    if missing:
        return False, _backend_install_message()
    return True, ""


def transcription_backend_quick_available() -> bool:
    return transcription_backend_quick_status()[0]


def _compute_transcription_backend_status() -> tuple[bool, str]:
    quick_available, quick_message = transcription_backend_quick_status()
    if not quick_available:
        return False, quick_message
    try:
        basic_pitch, _inference, _note_creation, onnxruntime = (
            _import_basic_pitch()
        )
        model_path = Path(
            basic_pitch.build_icassp_2022_model_path(
                basic_pitch.FilenameSuffix.onnx
            )
        )
        providers = set(onnxruntime.get_available_providers())
        if (
            not bool(getattr(basic_pitch, "ONNX_PRESENT", False))
            or not model_path.is_file()
            or "CPUExecutionProvider" not in providers
        ):
            return False, _backend_install_message()
    except TranscriptionError as exc:
        logging.getLogger(__name__).warning(
            "transcription backend component check failed: %s",
            exc,
            exc_info=True,
        )
        return False, str(exc) or BACKEND_CHECK_FAILED_MESSAGE
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "transcription backend component check failed: %s",
            exc,
            exc_info=True,
        )
        return False, BACKEND_CHECK_FAILED_MESSAGE
    return True, ""


def transcription_backend_status() -> tuple[bool, str]:
    """Fully validate the inference backend once per process/runtime mode.

    The first call imports the native inference stack and can be relatively
    expensive. Holding the lock through that cold check prevents concurrent
    editor/worker callers from repeating it. Analysis still calls this full
    boundary and therefore fails closed if model/provider loading is invalid.
    """

    cache_key = bool(getattr(sys, "frozen", False))
    with _BACKEND_STATUS_LOCK:
        cached = _BACKEND_STATUS_CACHE.get(cache_key)
        if cached is not None:
            return cached
        status = _compute_transcription_backend_status()
        _BACKEND_STATUS_CACHE[cache_key] = status
        return status


def _clear_transcription_backend_status_cache() -> None:
    """Clear the process-local probe cache for isolated tests."""

    with _BACKEND_STATUS_LOCK:
        _BACKEND_STATUS_CACHE.clear()


def transcription_backend_available() -> bool:
    return transcription_backend_status()[0]


def transcription_backend_message() -> str:
    return transcription_backend_status()[1]


def _onnx_model(basic_pitch, inference, onnxruntime):
    global _ONNX_MODEL
    if _ONNX_MODEL is not None:
        return _ONNX_MODEL
    cpu_count = os.cpu_count() or 1
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, cpu_count // 2))
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    model_path = basic_pitch.build_icassp_2022_model_path(
        basic_pitch.FilenameSuffix.onnx
    )
    model = inference.Model.__new__(inference.Model)
    model.model_type = inference.Model.MODEL_TYPES.ONNX
    model.model = onnxruntime.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    _ONNX_MODEL = model
    return model


def _cancel_if_requested(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise TranscriptionCancelled("扒谱分析已取消")


def _mapped_progress(
    progress: ProgressCallback | None,
    start: int,
    span: int,
) -> ProgressCallback | None:
    if progress is None:
        return None
    return lambda value: progress(
        int(start) + round(max(0, min(100, int(value))) * int(span) / 100)
    )


def _remove_transcription_workspace(path: Path, root: Path) -> bool:
    """Remove only one direct, generated analysis workspace."""

    try:
        resolved_root = root.resolve()
        if (
            path.is_symlink()
            or not path.is_dir()
            or path.parent.resolve() != resolved_root
            or path.resolve().parent != resolved_root
            or _WORKSPACE_NAME_PATTERN.fullmatch(path.name) is None
        ):
            return False
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def prune_transcription_workspaces(
    cache_root: Path | str = TRANSCRIPTION_CACHE_DIR,
    *,
    stale_seconds: float = _WORKSPACE_STALE_SECONDS,
) -> int:
    """Delete abandoned anonymous analysis buffers after a guarded age check."""

    root = Path(cache_root)
    if not root.is_dir() or root.is_symlink():
        return 0
    now = time.time()
    removed = 0
    try:
        children = tuple(root.iterdir())
    except OSError:
        return 0
    for child in children:
        if (
            _WORKSPACE_NAME_PATTERN.fullmatch(child.name) is None
            or child.is_symlink()
            or not child.is_dir()
        ):
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        if age >= max(0.0, float(stale_seconds)):
            removed += int(_remove_transcription_workspace(child, root))
    return removed


@contextmanager
def _transcription_workspace(cache_root: Path):
    """Yield a private local work directory and clean it on every exit."""

    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    prune_transcription_workspaces(root)
    workspace = Path(
        tempfile.mkdtemp(prefix=".transcription-work-", dir=root)
    )
    try:
        yield workspace
    finally:
        _remove_transcription_workspace(workspace, root)


def _stream_decode_reference_audio(
    audio_path: Path,
    workspace: Path,
    *,
    target_sample_rate: int,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> _StreamedAudioBuffer:
    """Decode and resample to an anonymous raw float32 stream."""

    from bdo_music_composer.audio.reference_audio_format import (
        ReferenceAudioFormatError,
        validate_reference_audio_file,
    )

    try:
        validate_reference_audio_file(audio_path)
    except ReferenceAudioFormatError as exc:
        raise TranscriptionError(str(exc)) from exc

    try:
        import soundfile
        import soxr
    except ModuleNotFoundError as exc:
        logging.getLogger(__name__).warning(
            "transcription decoder import failed: %s",
            exc,
            exc_info=True,
        )
        raise TranscriptionError(
            _backend_import_failure_message(exc)
        ) from exc

    output_path = workspace / "audio.f32"
    sample_count = 0
    try:
        with soundfile.SoundFile(str(audio_path)) as source, output_path.open(
            "wb"
        ) as output:
            source_rate = int(source.samplerate)
            if source_rate <= 0 or int(source.channels) <= 0:
                raise TranscriptionError(
                    "参考音频格式无效或没有可分析的声道"
                )
            resampler = (
                None
                if source_rate == int(target_sample_rate)
                else soxr.ResampleStream(
                    source_rate,
                    int(target_sample_rate),
                    1,
                    dtype="float32",
                    quality="HQ",
                )
            )
            total_frames = max(0, int(source.frames))
            read_frames = 0
            while True:
                _cancel_if_requested(cancelled)
                block = source.read(
                    _STREAM_DECODE_FRAMES,
                    dtype="float32",
                    always_2d=True,
                )
                if not block.size:
                    break
                read_frames += int(block.shape[0])
                mono = (
                    np.asarray(block[:, 0], dtype=np.float32)
                    if block.shape[1] == 1
                    else np.mean(block, axis=1, dtype=np.float32)
                )
                if not bool(np.isfinite(mono).all()):
                    raise TranscriptionError(
                        "参考音频包含非有限采样值"
                    )
                decoded = (
                    mono
                    if resampler is None
                    else resampler.resample_chunk(mono, last=False)
                )
                decoded = np.ascontiguousarray(
                    decoded,
                    dtype=np.dtype("<f4"),
                ).reshape(-1)
                decoded.tofile(output)
                sample_count += int(decoded.size)
                if progress is not None and total_frames:
                    progress(
                        min(
                            99,
                            round(100 * read_frames / total_frames),
                        )
                    )
            if resampler is not None:
                _cancel_if_requested(cancelled)
                tail = np.ascontiguousarray(
                    resampler.resample_chunk(
                        np.empty((0,), dtype=np.float32),
                        last=True,
                    ),
                    dtype=np.dtype("<f4"),
                ).reshape(-1)
                tail.tofile(output)
                sample_count += int(tail.size)
    except TranscriptionCancelled:
        raise
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(
            "参考音频无法通过本地流式解码器读取"
        ) from exc
    _cancel_if_requested(cancelled)
    if sample_count <= 0:
        raise TranscriptionError("参考音频中没有可分析的音频帧")
    expected_size = sample_count * np.dtype("<f4").itemsize
    if output_path.stat().st_size != expected_size:
        raise TranscriptionError("流式音频缓冲长度无效")
    if progress is not None:
        progress(100)
    return _StreamedAudioBuffer(
        output_path,
        sample_count,
        int(target_sample_rate),
    )


def _fast_harmonic_separator(librosa_module, block: np.ndarray) -> np.ndarray:
    return librosa_module.effects.harmonic(
        block,
        n_fft=HPSS_N_FFT,
        hop_length=HPSS_HOP_LENGTH,
        kernel_size=HPSS_KERNEL_SIZE,
        power=HPSS_POWER,
        margin=HPSS_MARGIN,
    )


def _stream_harmonic_audio(
    source: _StreamedAudioBuffer,
    workspace: Path,
    *,
    librosa_module,
    block_seconds: float = HPSS_BLOCK_SECONDS,
    overlap_seconds: float = HPSS_OVERLAP_SECONDS,
    harmonic_separator: Callable[[np.ndarray], np.ndarray] | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> _StreamedAudioBuffer:
    """Run overlap-add HPSS with only block-sized resident intermediates."""

    if (
        not math.isfinite(float(block_seconds))
        or not math.isfinite(float(overlap_seconds))
        or block_seconds <= 0.0
        or overlap_seconds < 0.0
        or overlap_seconds >= block_seconds
    ):
        raise ValueError("invalid HPSS block configuration")
    separator = harmonic_separator or (
        lambda block: _fast_harmonic_separator(librosa_module, block)
    )
    block_samples = max(
        1, int(round(float(block_seconds) * source.sample_rate))
    )
    overlap_samples = max(
        0, int(round(float(overlap_seconds) * source.sample_rate))
    )
    step_samples = block_samples - overlap_samples
    total_blocks = max(
        1,
        (source.sample_count + step_samples - 1) // step_samples,
    )
    harmonic_path = workspace / "harmonic.f32"
    weights_path = workspace / "harmonic-weights.f32"
    signal = source.open("r")
    harmonic = np.memmap(
        harmonic_path,
        dtype=np.dtype("<f4"),
        mode="w+",
        shape=(source.sample_count,),
    )
    weights = np.memmap(
        weights_path,
        dtype=np.dtype("<f4"),
        mode="w+",
        shape=(source.sample_count,),
    )
    harmonic[:] = 0.0
    weights[:] = 0.0
    try:
        for index, start in enumerate(
            range(0, source.sample_count, step_samples)
        ):
            _cancel_if_requested(cancelled)
            end = min(source.sample_count, start + block_samples)
            separated = np.asarray(
                separator(np.asarray(signal[start:end])),
                dtype=np.float32,
            )
            if (
                separated.shape != (end - start,)
                or not bool(np.isfinite(separated).all())
            ):
                raise TranscriptionError(
                    "HPSS returned an invalid harmonic block"
                )
            envelope = np.ones(separated.shape, dtype=np.float32)
            fade_samples = min(overlap_samples, separated.size)
            if fade_samples and start > 0:
                envelope[:fade_samples] *= np.linspace(
                    0.0,
                    1.0,
                    fade_samples,
                    endpoint=False,
                    dtype=np.float32,
                )
            if fade_samples and end < source.sample_count:
                envelope[-fade_samples:] *= np.linspace(
                    1.0,
                    0.0,
                    fade_samples,
                    endpoint=False,
                    dtype=np.float32,
                )
            harmonic[start:end] += separated * envelope
            weights[start:end] += envelope
            if progress is not None:
                progress(round(80 * (index + 1) / total_blocks))
        epsilon = np.finfo(np.float32).eps
        divide_chunks = max(1, block_samples)
        total_divisions = max(
            1,
            (
                source.sample_count + divide_chunks - 1
            )
            // divide_chunks,
        )
        for index, start in enumerate(
            range(0, source.sample_count, divide_chunks)
        ):
            _cancel_if_requested(cancelled)
            end = min(source.sample_count, start + divide_chunks)
            target = harmonic[start:end]
            denominator = weights[start:end]
            np.divide(
                target,
                denominator,
                out=target,
                where=denominator > epsilon,
            )
            if progress is not None:
                progress(
                    80 + round(20 * (index + 1) / total_divisions)
                )
        harmonic.flush()
    finally:
        _close_memmap(signal)
        _close_memmap(weights)
        _close_memmap(harmonic)
        try:
            weights_path.unlink(missing_ok=True)
        except OSError:
            pass
    _cancel_if_requested(cancelled)
    return _StreamedAudioBuffer(
        harmonic_path,
        source.sample_count,
        source.sample_rate,
    )


def transcription_audio_fingerprint(
    audio_path: Path | str,
    *,
    cancelled: CancelCallback | None = None,
) -> str:
    """Return a path-independent SHA-256 identity for the audio bytes."""

    path = Path(audio_path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        initial_stat = os.fstat(handle.fileno())
        while True:
            _cancel_if_requested(cancelled)
            chunk = handle.read(_AUDIO_FINGERPRINT_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
        final_stat = os.fstat(handle.fileno())
    current_stat = path.stat()
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    initial_identity = tuple(
        int(getattr(initial_stat, field, 0)) for field in stable_fields
    )
    if initial_identity != tuple(
        int(getattr(final_stat, field, 0)) for field in stable_fields
    ) or initial_identity[:-1] != tuple(
        int(getattr(current_stat, field, 0))
        for field in stable_fields[:-1]
    ):
        raise TranscriptionError(
            "reference audio changed while its content identity was read"
        )
    _cancel_if_requested(cancelled)
    return digest.hexdigest()


def transcription_cache_key(
    audio_path: Path | str,
    *,
    analysis_mode: TranscriptionAnalysisMode | str = (
        DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
    ),
    audio_fingerprint: str | None = None,
    cancelled: CancelCallback | None = None,
) -> str:
    """Identify inference evidence independently from decoding thresholds."""

    mode = normalise_transcription_analysis_mode(analysis_mode)
    fingerprint = (
        str(audio_fingerprint)
        if audio_fingerprint is not None
        else transcription_audio_fingerprint(
            audio_path,
            cancelled=cancelled,
        )
    )
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise ValueError("invalid transcription audio fingerprint")
    payload = {
        "version": TRANSCRIPTION_CACHE_VERSION,
        "backend_id": TRANSCRIPTION_BACKEND_ID,
        "analysis_mode": mode,
        "fusion_version": TRANSCRIPTION_FUSION_VERSION,
        "audio_fingerprint": fingerprint,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def normalise_transcription_analysis_mode(
    analysis_mode: TranscriptionAnalysisMode | str,
) -> TranscriptionAnalysisMode:
    value = str(analysis_mode)
    if value not in {
        STANDARD_ANALYSIS_MODE,
        MIXED_ENHANCED_ANALYSIS_MODE,
    }:
        raise ValueError(f"unknown transcription analysis mode: {value}")
    return value


def normalise_transcription_cleanup_profile(
    cleanup_profile: CleanupProfile | str,
) -> CleanupProfile:
    value = str(cleanup_profile)
    if value not in TRANSCRIPTION_CLEANUP_PROFILES:
        raise ValueError(
            f"unknown transcription cleanup profile: {cleanup_profile}"
        )
    return value


def transcription_candidate_id(
    cache_key: str,
    candidate: TranscriptionCandidate,
) -> str:
    """Build a stable ID from model/source facts, not review state."""

    if _CACHE_KEY_PATTERN.fullmatch(str(cache_key)) is None:
        raise ValueError("invalid transcription cache key")
    start_us = int(round(float(candidate.start_ms) * 1000.0))
    end_us = int(
        round(
            (float(candidate.start_ms) + float(candidate.duration_ms))
            * 1000.0
        )
    )
    payload = {
        "backend_id": TRANSCRIPTION_BACKEND_ID,
        "cache_key": str(cache_key),
        "pitch": int(candidate.pitch),
        "velocity": int(candidate.velocity),
        "start_us": start_us,
        "end_us": end_us,
        "source": str(candidate.source),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def _identify_candidates(
    cache_key: str,
    candidates: tuple[TranscriptionCandidate, ...],
) -> tuple[TranscriptionCandidate, ...]:
    return tuple(
        replace(
            candidate,
            candidate_id=transcription_candidate_id(cache_key, candidate),
        )
        for candidate in candidates
    )


def _cache_folder(cache_key: str, cache_root: Path) -> Path:
    if _CACHE_KEY_PATTERN.fullmatch(str(cache_key)) is None:
        raise ValueError("invalid transcription cache key")
    return cache_root / cache_key


def _sha256_file(
    path: Path,
    *,
    cancelled: CancelCallback | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            _cancel_if_requested(cancelled)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    _cancel_if_requested(cancelled)
    return digest.hexdigest()


def _close_memmap(array: np.ndarray) -> None:
    mmap = getattr(array, "_mmap", None)
    if mmap is not None:
        mmap.close()


def _validation_identity(
    folder: Path,
    cache_key: str,
) -> tuple[str, str] | None:
    try:
        return str(folder.parent.resolve()), cache_key
    except OSError:
        return None


def _file_stamp(path: Path) -> tuple[str, int, int, int, int] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        return (
            path.name,
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
            int(stat.st_ino),
        )
    except OSError:
        return None


def _cache_file_stamps(
    folder: Path,
    descriptor: EvidenceDescriptor,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[tuple[str, int, int, int, int], ...] | None:
    filenames = (
        "manifest.json",
        descriptor.times_filename,
        *(layer.filename for layer in descriptor.layers),
    )
    stamps: list[tuple[str, int, int, int, int]] = []
    for filename in filenames:
        _cancel_if_requested(cancelled)
        stamp = _file_stamp(folder / filename)
        if stamp is None:
            return None
        stamps.append(stamp)
    _cancel_if_requested(cancelled)
    return tuple(stamps)


def _cached_validation_entry(
    folder: Path,
    cache_key: str,
    *,
    expected_audio_fingerprint: str | None,
    cancelled: CancelCallback | None = None,
) -> _ValidatedCacheEntry | None:
    _cancel_if_requested(cancelled)
    identity = _validation_identity(folder, cache_key)
    if identity is None:
        return None
    with _CACHE_VALIDATION_LOCK:
        entry = _VALIDATED_CACHE_ENTRIES.get(identity)
        if entry is None:
            return None
        if (
            expected_audio_fingerprint is not None
            and entry.descriptor.audio_fingerprint
            != expected_audio_fingerprint
        ):
            return None
        if (
            _cache_file_stamps(
                folder,
                entry.descriptor,
                cancelled=cancelled,
            )
            != entry.file_stamps
        ):
            _VALIDATED_CACHE_ENTRIES.pop(identity, None)
            return None
        _VALIDATED_CACHE_ENTRIES.move_to_end(identity)
        _cancel_if_requested(cancelled)
        return entry


def _remember_validated_cache_entry(
    folder: Path,
    cache_key: str,
    entry: _ValidatedCacheEntry,
) -> None:
    identity = _validation_identity(folder, cache_key)
    if identity is None:
        return
    with _CACHE_VALIDATION_LOCK:
        _VALIDATED_CACHE_ENTRIES[identity] = entry
        _VALIDATED_CACHE_ENTRIES.move_to_end(identity)
        while (
            len(_VALIDATED_CACHE_ENTRIES)
            > _CACHE_VALIDATION_MAX_ENTRIES
        ):
            _VALIDATED_CACHE_ENTRIES.popitem(last=False)


def _forget_validated_cache_entry(folder: Path, cache_key: str) -> None:
    identity = _validation_identity(folder, cache_key)
    if identity is None:
        return
    with _CACHE_VALIDATION_LOCK:
        _VALIDATED_CACHE_ENTRIES.pop(identity, None)


def _open_validated_cached_array(
    folder: Path,
    *,
    filename: str,
    shape: tuple[int, ...],
    dtype: np.dtype,
) -> np.memmap | None:
    path = folder / filename
    try:
        if path.is_symlink() or not path.is_file():
            return None
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError, EOFError, TypeError):
        return None
    if array.shape != shape or array.dtype != dtype:
        _close_memmap(array)
        return None
    return array


def _descriptor_from_payload(
    value: object,
    *,
    cache_key: str,
) -> EvidenceDescriptor | None:
    if not isinstance(value, dict):
        return None
    try:
        backend_id = value["backend_id"]
        analysis_mode = normalise_transcription_analysis_mode(
            value["analysis_mode"]
        )
        fusion_version = value["fusion_version"]
        decode_sensitivity = str(value["decode_sensitivity"])
        cleanup_profile = normalise_transcription_cleanup_profile(
            value.get(
                "cleanup_profile",
                LEGACY_TRANSCRIPTION_CLEANUP_PROFILE,
            )
        )
        postprocess_version = str(
            value.get("postprocess_version")
            or LEGACY_TRANSCRIPTION_POSTPROCESS_VERSION
        )
        audio_fingerprint = value["audio_fingerprint"]
        duration_raw = value["duration_ms"]
        duration_ms = float(duration_raw)
        frame_count = value["frame_count"]
        times_shape_raw = value["times_shape"]
        midi_min = value["midi_min"]
        layers_raw = value["layers"]
        if (
            value["cache_key"] != cache_key
            or backend_id != TRANSCRIPTION_BACKEND_ID
            or fusion_version != TRANSCRIPTION_FUSION_VERSION
            or decode_sensitivity not in TRANSCRIPTION_SENSITIVITY_PRESETS
            or re.fullmatch(
                r"[A-Za-z0-9._:+-]{1,96}",
                postprocess_version,
            )
            is None
            or not isinstance(audio_fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", audio_fingerprint) is None
            or transcription_cache_key(
                "",
                analysis_mode=analysis_mode,
                audio_fingerprint=audio_fingerprint,
            )
            != cache_key
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or frame_count <= 0
            or isinstance(duration_raw, bool)
            or not isinstance(duration_raw, (int, float))
            or not math.isfinite(duration_ms)
            or duration_ms < 0.0
            or value["times_filename"] != "times_ms.npy"
            or not isinstance(times_shape_raw, list)
            or tuple(times_shape_raw) != (frame_count,)
            or value["times_dtype"] != TRANSCRIPTION_TIME_DTYPE.str
            or isinstance(value["times_file_size"], bool)
            or not isinstance(value["times_file_size"], int)
            or value["times_file_size"] <= 0
            or not isinstance(value["times_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["times_sha256"])
            is None
            or midi_min != TRANSCRIPTION_MIDI_MIN
            or not isinstance(layers_raw, list)
        ):
            return None
        expected = {
            "frame": (TRANSCRIPTION_NOTE_BINS, 1),
            "onset": (TRANSCRIPTION_NOTE_BINS, 1),
            "contour": (
                TRANSCRIPTION_NOTE_BINS
                * TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE,
                TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE,
            ),
        }
        layers: list[EvidenceLayerDescriptor] = []
        seen: set[str] = set()
        for item in layers_raw:
            if not isinstance(item, dict):
                return None
            name = item["name"]
            if name not in expected or name in seen:
                return None
            bins, bins_per_semitone = expected[name]
            shape_raw = item["shape"]
            if (
                item["filename"] != f"{name}.npy"
                or not isinstance(shape_raw, list)
                or tuple(shape_raw) != (frame_count, bins)
                or item["dtype"] != TRANSCRIPTION_EVIDENCE_DTYPE.str
                or item["midi_min"] != TRANSCRIPTION_MIDI_MIN
                or item["bins_per_semitone"] != bins_per_semitone
                or isinstance(item["file_size"], bool)
                or not isinstance(item["file_size"], int)
                or item["file_size"] <= 0
                or not isinstance(item["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                is None
            ):
                return None
            layers.append(
                EvidenceLayerDescriptor(
                    name=name,
                    filename=item["filename"],
                    shape=(frame_count, bins),
                    dtype=item["dtype"],
                    midi_min=TRANSCRIPTION_MIDI_MIN,
                    bins_per_semitone=bins_per_semitone,
                    file_size=item["file_size"],
                    sha256=item["sha256"],
                )
            )
            seen.add(name)
        if seen != set(expected):
            return None
        layers.sort(key=lambda item: ("frame", "onset", "contour").index(item.name))
        return EvidenceDescriptor(
            cache_key=cache_key,
            backend_id=backend_id,
            audio_fingerprint=audio_fingerprint,
            duration_ms=duration_ms,
            frame_count=frame_count,
            times_filename="times_ms.npy",
            times_shape=(frame_count,),
            times_dtype=TRANSCRIPTION_TIME_DTYPE.str,
            times_file_size=value["times_file_size"],
            times_sha256=value["times_sha256"],
            analysis_mode=analysis_mode,
            fusion_version=fusion_version,
            decode_sensitivity=decode_sensitivity,
            cleanup_profile=cleanup_profile,
            postprocess_version=postprocess_version,
            midi_min=TRANSCRIPTION_MIDI_MIN,
            layers=tuple(layers),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _validated_cached_array(
    folder: Path,
    *,
    filename: str,
    shape: tuple[int, ...],
    dtype: np.dtype,
    file_size: int,
    sha256: str,
    times: bool = False,
    cancelled: CancelCallback | None = None,
) -> np.memmap | None:
    path = folder / filename
    try:
        _cancel_if_requested(cancelled)
        if (
            path.is_symlink()
            or not path.is_file()
            or path.parent.resolve() != folder.resolve()
            or path.stat().st_size != file_size
            or _sha256_file(path, cancelled=cancelled) != sha256
        ):
            return None
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError):
        return None
    valid = False
    try:
        if array.shape != shape or array.dtype != dtype:
            return None
        row_width = (
            int(np.prod(array.shape[1:], dtype=np.int64))
            if array.ndim > 1
            else 1
        )
        rows_per_chunk = max(
            1,
            _CACHE_VALIDATION_CHUNK_ELEMENTS // max(1, row_width),
        )
        previous_time: float | None = None
        for start in range(0, int(array.shape[0]), rows_per_chunk):
            _cancel_if_requested(cancelled)
            stop = min(int(array.shape[0]), start + rows_per_chunk)
            chunk = np.asarray(array[start:stop])
            if not bool(np.isfinite(chunk).all()):
                return None
            if times:
                flat = chunk.reshape(-1)
                if (
                    (start == 0 and float(flat[0]) < 0.0)
                    or (
                        previous_time is not None
                        and float(flat[0]) <= previous_time
                    )
                    or (
                        flat.size > 1
                        and not bool(np.all(np.diff(flat) > 0.0))
                    )
                ):
                    return None
                previous_time = float(flat[-1])
            elif (
                float(np.min(chunk)) < 0.0
                or float(np.max(chunk)) > 1.0
            ):
                return None
        _cancel_if_requested(cancelled)
        valid = True
        return array
    finally:
        # Keep the mapping open only when it is returned to the caller.
        if not valid:
            _close_memmap(array)


def _validate_evidence_files(
    folder: Path,
    descriptor: EvidenceDescriptor,
    *,
    cancelled: CancelCallback | None = None,
) -> bool:
    _cancel_if_requested(cancelled)
    times = _validated_cached_array(
        folder,
        filename=descriptor.times_filename,
        shape=descriptor.times_shape,
        dtype=TRANSCRIPTION_TIME_DTYPE,
        file_size=descriptor.times_file_size,
        sha256=descriptor.times_sha256,
        times=True,
        cancelled=cancelled,
    )
    if times is None:
        return False
    if float(times[-1]) > descriptor.duration_ms + 1e-6:
        _close_memmap(times)
        return False
    _close_memmap(times)
    for layer in descriptor.layers:
        array = _validated_cached_array(
            folder,
            filename=layer.filename,
            shape=layer.shape,
            dtype=TRANSCRIPTION_EVIDENCE_DTYPE,
            file_size=layer.file_size,
            sha256=layer.sha256,
            cancelled=cancelled,
        )
        if array is None:
            return False
        _close_memmap(array)
    _cancel_if_requested(cancelled)
    return True


def _candidate_from_payload(
    item: object,
    *,
    cache_key: str,
) -> TranscriptionCandidate | None:
    if not isinstance(item, dict):
        return None
    try:
        if (
            isinstance(item["pitch"], bool)
            or not isinstance(item["pitch"], int)
            or isinstance(item["velocity"], bool)
            or not isinstance(item["velocity"], int)
            or isinstance(item["start_ms"], bool)
            or not isinstance(item["start_ms"], (int, float))
            or isinstance(item["duration_ms"], bool)
            or not isinstance(item["duration_ms"], (int, float))
            or isinstance(item["confidence"], bool)
            or not isinstance(item["confidence"], (int, float))
            or not isinstance(item["source"], str)
            or not isinstance(item["candidate_id"], str)
        ):
            return None
        candidate = TranscriptionCandidate(
            item["pitch"],
            item["velocity"],
            float(item["start_ms"]),
            float(item["duration_ms"]),
            float(item["confidence"]),
            item["source"],
            item["candidate_id"],
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        candidate.pitch < 0
        or candidate.pitch > 127
        or candidate.velocity < 1
        or candidate.velocity > 127
        or not math.isfinite(candidate.start_ms)
        or candidate.start_ms < 0.0
        or not math.isfinite(candidate.duration_ms)
        or candidate.duration_ms < 1.0
        or not math.isfinite(candidate.confidence)
        or not 0.0 <= candidate.confidence <= 1.0
        or not candidate.source
        or candidate.candidate_id
        != transcription_candidate_id(cache_key, candidate)
    ):
        return None
    return candidate


def _validated_candidate_sequence(
    candidates: tuple[TranscriptionCandidate, ...],
    descriptor: EvidenceDescriptor,
) -> tuple[TranscriptionCandidate, ...] | None:
    identifiers: set[str] = set()
    for candidate in candidates:
        if (
            candidate.candidate_id in identifiers
            or candidate.pitch < descriptor.midi_min
            or candidate.pitch
            >= descriptor.midi_min + TRANSCRIPTION_NOTE_BINS
            or candidate.start_ms > descriptor.duration_ms + 1.0
            or candidate.start_ms + candidate.duration_ms
            > descriptor.duration_ms + 1.0
        ):
            return None
        identifiers.add(candidate.candidate_id)
    if list(candidates) != sorted(
        candidates,
        key=lambda item: (item.start_ms, item.pitch, item.duration_ms),
    ):
        return None
    return candidates


def _read_valid_cache_entry(
    cache_key: str,
    cache_root: Path,
    *,
    expected_audio_fingerprint: str | None = None,
    cancelled: CancelCallback | None = None,
) -> tuple[
    tuple[TranscriptionCandidate, ...],
    EvidenceDescriptor,
] | None:
    _cancel_if_requested(cancelled)
    try:
        folder = _cache_folder(cache_key, cache_root)
        cached_entry = _cached_validation_entry(
            folder,
            cache_key,
            expected_audio_fingerprint=expected_audio_fingerprint,
            cancelled=cancelled,
        )
        if cached_entry is not None:
            return cached_entry.candidates, cached_entry.descriptor
        manifest = folder / "manifest.json"
        initial_manifest_stamp = _file_stamp(manifest)
        if (
            folder.is_symlink()
            or manifest.is_symlink()
            or initial_manifest_stamp is None
            or manifest.stat().st_size > 64 * 1024**2
        ):
            return None
        manifest_parts: list[str] = []
        with manifest.open("r", encoding="utf-8") as stream:
            while True:
                _cancel_if_requested(cancelled)
                part = stream.read(1024 * 1024)
                if not part:
                    break
                manifest_parts.append(part)
        payload = json.loads("".join(manifest_parts))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("version") != TRANSCRIPTION_CACHE_VERSION
        or payload.get("backend_id") != TRANSCRIPTION_BACKEND_ID
        or payload.get("cache_key") != cache_key
        or not isinstance(payload.get("candidates"), list)
    ):
        return None
    descriptor = _descriptor_from_payload(
        payload.get("evidence_descriptor"),
        cache_key=cache_key,
    )
    if (
        descriptor is None
        or payload.get("evidence_layers")
        != list(descriptor.layer_names)
        or (
            expected_audio_fingerprint is not None
            and descriptor.audio_fingerprint != expected_audio_fingerprint
        )
    ):
        return None
    stamps_before = _cache_file_stamps(
        folder,
        descriptor,
        cancelled=cancelled,
    )
    if (
        stamps_before is None
        or stamps_before[0] != initial_manifest_stamp
        or not _validate_evidence_files(
            folder,
            descriptor,
            cancelled=cancelled,
        )
    ):
        return None
    candidates: list[TranscriptionCandidate] = []
    for index, item in enumerate(payload["candidates"]):
        if index % 1024 == 0:
            _cancel_if_requested(cancelled)
        candidate = _candidate_from_payload(item, cache_key=cache_key)
        if candidate is None:
            return None
        candidates.append(candidate)
    candidates_tuple = _validated_candidate_sequence(
        tuple(candidates),
        descriptor,
    )
    if candidates_tuple is None:
        return None
    _cancel_if_requested(cancelled)
    stamps_after = _cache_file_stamps(
        folder,
        descriptor,
        cancelled=cancelled,
    )
    if stamps_after != stamps_before:
        return None
    _remember_validated_cache_entry(
        folder,
        cache_key,
        _ValidatedCacheEntry(
            stamps_after,
            candidates_tuple,
            descriptor,
        ),
    )
    _cancel_if_requested(cancelled)
    return candidates_tuple, descriptor


def _load_cached_result(
    audio_path: Path,
    cache_root: Path,
    *,
    analysis_mode: TranscriptionAnalysisMode | str = (
        DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
    ),
    audio_fingerprint: str | None = None,
    cancelled: CancelCallback | None = None,
) -> TranscriptionResult | None:
    try:
        fingerprint = (
            str(audio_fingerprint)
            if audio_fingerprint is not None
            else transcription_audio_fingerprint(
                audio_path,
                cancelled=cancelled,
            )
        )
        cache_key = transcription_cache_key(
            audio_path,
            analysis_mode=analysis_mode,
            audio_fingerprint=fingerprint,
        )
        cached = _read_valid_cache_entry(
            cache_key,
            cache_root,
            expected_audio_fingerprint=fingerprint,
            cancelled=cancelled,
        )
    except (OSError, ValueError, TypeError):
        return None
    if cached is None:
        return None
    try:
        current_fingerprint = transcription_audio_fingerprint(
            audio_path,
            cancelled=cancelled,
        )
    except OSError:
        return None
    if current_fingerprint != fingerprint:
        return None
    candidates, descriptor = cached
    return TranscriptionResult(
        candidates,
        cache_key,
        descriptor.layer_names,
        True,
        descriptor,
    )


def _normalise_evidence(value: object, expected_bins: int) -> np.ndarray | None:
    array = np.asarray(value)
    if array.ndim != 2:
        return None
    if array.shape[1] == expected_bins:
        return array
    if array.shape[0] == expected_bins:
        return array.T
    return None


def _evidence_values_are_valid(
    array: np.ndarray,
    *,
    cancelled: CancelCallback | None = None,
) -> bool:
    """Validate a probability matrix with bounded temporary allocations."""

    if array.ndim != 2 or array.shape[0] <= 0:
        return False
    rows_per_chunk = max(
        1,
        _CACHE_VALIDATION_CHUNK_ELEMENTS
        // max(1, int(array.shape[1])),
    )
    for start in range(0, int(array.shape[0]), rows_per_chunk):
        _cancel_if_requested(cancelled)
        chunk = np.asarray(array[start : start + rows_per_chunk])
        if (
            not bool(np.isfinite(chunk).all())
            or float(np.min(chunk)) < 0.0
            or float(np.max(chunk)) > 1.0
        ):
            return False
    _cancel_if_requested(cancelled)
    return True


def _evidence_value(
    model_output: dict[str, np.ndarray],
    layer: str,
) -> object:
    # Basic Pitch 0.4 exposes the 88-bin frame matrix under ``note`` even
    # though its public note-creation docs call that same matrix ``frame``.
    if layer == "frame" and "frame" not in model_output:
        return model_output.get("note")
    return model_output.get(layer)


def basic_pitch_frame_times_ms(
    frame_count: int,
    *,
    note_creation=None,
) -> np.ndarray:
    """Use Basic Pitch's window-aware mapping instead of a fixed FPS."""

    if isinstance(frame_count, bool) or int(frame_count) <= 0:
        raise ValueError("frame_count must be positive")
    module = (
        note_creation
        if note_creation is not None
        else _import_basic_pitch_note_creation()
    )
    times = np.asarray(
        module.model_frames_to_time(int(frame_count)),
        dtype=TRANSCRIPTION_TIME_DTYPE,
    )
    if (
        times.shape != (int(frame_count),)
        or not bool(np.isfinite(times).all())
        or float(times[0]) < 0.0
        or not bool(np.all(np.diff(times) > 0.0))
    ):
        raise TranscriptionError("Basic Pitch returned invalid frame times")
    return times * 1000.0


def _write_npy_atomic(
    path: Path,
    array: np.ndarray,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[int, str]:
    temporary = path.with_name(f"{path.name}.tmp")
    output: np.memmap | None = None
    try:
        _cancel_if_requested(cancelled)
        source = np.asarray(array)
        if source.ndim < 1:
            raise TranscriptionError("cached evidence must be an array")
        output = np.lib.format.open_memmap(
            temporary,
            mode="w+",
            dtype=source.dtype,
            shape=source.shape,
        )
        row_width = (
            int(np.prod(source.shape[1:], dtype=np.int64))
            if source.ndim > 1
            else 1
        )
        rows_per_chunk = max(
            1,
            _CACHE_VALIDATION_CHUNK_ELEMENTS // max(1, row_width),
        )
        for start in range(0, int(source.shape[0]), rows_per_chunk):
            _cancel_if_requested(cancelled)
            stop = min(int(source.shape[0]), start + rows_per_chunk)
            output[start:stop] = source[start:stop]
        output.flush()
        _close_memmap(output)
        output = None
        _cancel_if_requested(cancelled)
        temporary.replace(path)
        return path.stat().st_size, _sha256_file(
            path,
            cancelled=cancelled,
        )
    finally:
        if output is not None:
            _close_memmap(output)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _write_cached_result(
    result: TranscriptionResult,
    model_output: dict[str, np.ndarray],
    cache_root: Path,
    *,
    frame_times_ms: np.ndarray | None = None,
    duration_ms: float | None = None,
    audio_fingerprint: str | None = None,
    analysis_mode: TranscriptionAnalysisMode | str = (
        DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
    ),
    sensitivity: TranscriptionSensitivity = "balanced",
    cleanup_profile: CleanupProfile = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    cancelled: CancelCallback | None = None,
) -> EvidenceDescriptor:
    _cancel_if_requested(cancelled)
    mode = normalise_transcription_analysis_mode(analysis_mode)
    cleanup = normalise_transcription_cleanup_profile(cleanup_profile)
    transcription_thresholds(sensitivity, mode)
    folder = _cache_folder(result.cache_key, cache_root)
    _forget_validated_cache_entry(folder, result.cache_key)
    if folder.is_symlink():
        raise TranscriptionError("transcription cache target is a symlink")
    folder.mkdir(parents=True, exist_ok=True)
    expected_layers = (
        ("frame", TRANSCRIPTION_NOTE_BINS, 1),
        ("onset", TRANSCRIPTION_NOTE_BINS, 1),
        (
            "contour",
            TRANSCRIPTION_NOTE_BINS
            * TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE,
            TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE,
        ),
    )
    normalised: dict[str, np.ndarray] = {}
    frame_count: int | None = None
    for name, bins, _bins_per_semitone in expected_layers:
        _cancel_if_requested(cancelled)
        array = _normalise_evidence(_evidence_value(model_output, name), bins)
        if (
            array is None
            or not _evidence_values_are_valid(
                array,
                cancelled=cancelled,
            )
        ):
            raise TranscriptionError(
                f"invalid Basic Pitch evidence layer: {name}"
            )
        if frame_count is None:
            frame_count = int(array.shape[0])
        elif array.shape[0] != frame_count:
            raise TranscriptionError(
                "Basic Pitch evidence layers do not share one time axis"
            )
        normalised[name] = array.astype(
            TRANSCRIPTION_EVIDENCE_DTYPE,
            copy=False,
        )
    assert frame_count is not None
    if frame_times_ms is None:
        frame_times_ms = basic_pitch_frame_times_ms(frame_count)
    times = np.asarray(frame_times_ms, dtype=TRANSCRIPTION_TIME_DTYPE)
    if (
        times.shape != (frame_count,)
        or not bool(np.isfinite(times).all())
        or float(times[0]) < 0.0
        or not bool(np.all(np.diff(times) > 0.0))
    ):
        raise TranscriptionError("invalid Basic Pitch evidence frame times")
    if duration_ms is None:
        duration_ms = float(times[-1])
    duration_ms = float(duration_ms)
    if (
        not math.isfinite(duration_ms)
        or duration_ms < float(times[-1]) - 1e-6
    ):
        raise TranscriptionError("invalid transcription audio duration")
    if (
        not isinstance(audio_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", audio_fingerprint) is None
    ):
        raise TranscriptionError("invalid transcription audio fingerprint")

    times_file_size, times_sha256 = _write_npy_atomic(
        folder / "times_ms.npy",
        times,
        cancelled=cancelled,
    )
    layers: list[EvidenceLayerDescriptor] = []
    for name, bins, bins_per_semitone in expected_layers:
        filename = f"{name}.npy"
        file_size, sha256 = _write_npy_atomic(
            folder / filename,
            normalised[name],
            cancelled=cancelled,
        )
        layers.append(
            EvidenceLayerDescriptor(
                name=name,
                filename=filename,
                shape=(frame_count, bins),
                dtype=TRANSCRIPTION_EVIDENCE_DTYPE.str,
                midi_min=TRANSCRIPTION_MIDI_MIN,
                bins_per_semitone=bins_per_semitone,
                file_size=file_size,
                sha256=sha256,
            )
        )
    descriptor = EvidenceDescriptor(
        cache_key=result.cache_key,
        backend_id=TRANSCRIPTION_BACKEND_ID,
        audio_fingerprint=audio_fingerprint,
        duration_ms=duration_ms,
        frame_count=frame_count,
        times_filename="times_ms.npy",
        times_shape=(frame_count,),
        times_dtype=TRANSCRIPTION_TIME_DTYPE.str,
        times_file_size=times_file_size,
        times_sha256=times_sha256,
        analysis_mode=mode,
        fusion_version=TRANSCRIPTION_FUSION_VERSION,
        decode_sensitivity=str(sensitivity),
        cleanup_profile=cleanup,
        postprocess_version=POSTPROCESS_VERSION,
        midi_min=TRANSCRIPTION_MIDI_MIN,
        layers=tuple(layers),
    )
    identified_candidates = _identify_candidates(
        result.cache_key,
        result.candidates,
    )
    parsed_candidates = tuple(
        _candidate_from_payload(
            asdict(candidate),
            cache_key=result.cache_key,
        )
        for candidate in identified_candidates
    )
    if any(candidate is None for candidate in parsed_candidates):
        raise TranscriptionError("invalid transcription candidate data")
    validated_candidates = _validated_candidate_sequence(
        tuple(candidate for candidate in parsed_candidates if candidate is not None),
        descriptor,
    )
    if validated_candidates is None:
        raise TranscriptionError(
            "transcription candidates do not match cached evidence"
        )
    _cancel_if_requested(cancelled)
    manifest = {
        "version": TRANSCRIPTION_CACHE_VERSION,
        "backend_id": TRANSCRIPTION_BACKEND_ID,
        "analysis_mode": mode,
        "fusion_version": TRANSCRIPTION_FUSION_VERSION,
        "cache_key": result.cache_key,
        "candidates": [
            asdict(candidate) for candidate in validated_candidates
        ],
        "evidence_layers": list(descriptor.layer_names),
        "evidence_descriptor": asdict(descriptor),
    }
    temporary_manifest = folder / "manifest.json.tmp"
    try:
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _cancel_if_requested(cancelled)
        temporary_manifest.replace(folder / "manifest.json")
    finally:
        try:
            temporary_manifest.unlink(missing_ok=True)
        except OSError:
            pass
    stamps = _cache_file_stamps(folder, descriptor)
    if stamps is not None:
        _remember_validated_cache_entry(
            folder,
            result.cache_key,
            _ValidatedCacheEntry(
                stamps,
                validated_candidates,
                descriptor,
            ),
        )
    prune_transcription_cache(cache_root, keep_keys=(result.cache_key,))
    _cancel_if_requested(cancelled)
    return descriptor


def _cache_entry_size(folder: Path) -> int:
    total = 0
    for directory, child_directories, filenames in os.walk(
        folder,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        child_directories[:] = [
            name
            for name in child_directories
            if not (directory_path / name).is_symlink()
        ]
        for filename in filenames:
            path = directory_path / filename
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def prune_transcription_cache(
    cache_root: Path | str = TRANSCRIPTION_CACHE_DIR,
    *,
    max_bytes: int = TRANSCRIPTION_CACHE_MAX_BYTES,
    max_entries: int = TRANSCRIPTION_CACHE_MAX_ENTRIES,
    keep_keys: tuple[str, ...] = (),
) -> tuple[int, int]:
    """Remove oldest complete cache entries until count and size are bounded.

    Only direct, non-symlink children with the exact cache-key shape are
    eligible. Unknown files are left untouched, and ``keep_keys`` protects the
    entry produced by the current analysis even if that single entry is larger
    than the configured budget.
    """

    root = Path(cache_root)
    try:
        if not root.is_dir():
            return 0, 0
        resolved_root = root.resolve()
    except OSError:
        return 0, 0

    protected = {
        str(key)
        for key in keep_keys
        if _CACHE_KEY_PATTERN.fullmatch(str(key)) is not None
    }
    entries: list[tuple[int, str, Path, int]] = []
    try:
        children = tuple(root.iterdir())
    except OSError:
        return 0, 0
    for child in children:
        if (
            _CACHE_KEY_PATTERN.fullmatch(child.name) is None
            or child.is_symlink()
        ):
            continue
        try:
            if not child.is_dir() or child.parent.resolve() != resolved_root:
                continue
            manifest = child / "manifest.json"
            modified_ns = (
                manifest.stat().st_mtime_ns
                if manifest.is_file() and not manifest.is_symlink()
                else child.stat().st_mtime_ns
            )
            size = _cache_entry_size(child)
        except OSError:
            continue
        entries.append((modified_ns, child.name, child, size))

    max_bytes = max(0, int(max_bytes))
    max_entries = max(0, int(max_entries))
    total_size = sum(entry[3] for entry in entries)
    remaining = len(entries)
    removed_entries = 0
    removed_bytes = 0
    for _modified_ns, key, folder, size in sorted(entries):
        if remaining <= max_entries and total_size <= max_bytes:
            break
        if key in protected:
            continue
        try:
            if (
                folder.is_symlink()
                or not folder.is_dir()
                or folder.parent.resolve() != resolved_root
                or folder.resolve().parent != resolved_root
            ):
                continue
            shutil.rmtree(folder)
            _forget_validated_cache_entry(folder, key)
        except OSError:
            continue
        remaining -= 1
        total_size -= size
        removed_entries += 1
        removed_bytes += size
    return removed_entries, removed_bytes


def load_transcription_evidence(
    cache_key: str,
    layer: str,
    *,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    cancelled: CancelCallback | None = None,
) -> np.ndarray | None:
    if layer not in {"frame", "onset", "contour"}:
        return None
    try:
        cache_root = Path(cache_root)
        cached = _read_valid_cache_entry(
            str(cache_key),
            cache_root,
            cancelled=cancelled,
        )
    except ValueError:
        return None
    if cached is None:
        return None
    _candidates, descriptor = cached
    layer_descriptor = descriptor.layer(layer)
    if layer_descriptor is None:
        return None
    return _open_validated_cached_array(
        _cache_folder(str(cache_key), cache_root),
        filename=layer_descriptor.filename,
        shape=layer_descriptor.shape,
        dtype=TRANSCRIPTION_EVIDENCE_DTYPE,
    )


def load_cached_transcription_result(
    cache_key: str,
    *,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    expected_audio_fingerprint: str | None = None,
    cancelled: CancelCallback | None = None,
) -> TranscriptionResult | None:
    """Load a fully validated cached result by its privacy-safe key."""

    try:
        cached = _read_valid_cache_entry(
            str(cache_key),
            Path(cache_root),
            expected_audio_fingerprint=expected_audio_fingerprint,
            cancelled=cancelled,
        )
    except ValueError:
        return None
    if cached is None:
        return None
    candidates, descriptor = cached
    return TranscriptionResult(
        candidates,
        str(cache_key),
        descriptor.layer_names,
        True,
        descriptor,
    )


def load_transcription_frame_times(
    cache_key: str,
    *,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    cancelled: CancelCallback | None = None,
) -> np.ndarray | None:
    try:
        cache_root = Path(cache_root)
        cached = _read_valid_cache_entry(
            str(cache_key),
            cache_root,
            cancelled=cancelled,
        )
    except ValueError:
        return None
    if cached is None:
        return None
    _candidates, descriptor = cached
    return _open_validated_cached_array(
        _cache_folder(str(cache_key), cache_root),
        filename=descriptor.times_filename,
        shape=descriptor.times_shape,
        dtype=TRANSCRIPTION_TIME_DTYPE,
    )


def load_transcription_evidence_descriptor(
    cache_key: str,
    *,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    cancelled: CancelCallback | None = None,
) -> EvidenceDescriptor | None:
    try:
        cached = _read_valid_cache_entry(
            str(cache_key),
            Path(cache_root),
            cancelled=cancelled,
        )
    except ValueError:
        return None
    return cached[1] if cached is not None else None


def _candidates_from_basic_pitch(
    midi_data,
    note_events,
) -> tuple[TranscriptionCandidate, ...]:
    events_by_pitch: dict[int, list[tuple]] = {}
    for event in note_events or []:
        if len(event) >= 4:
            events_by_pitch.setdefault(int(event[2]), []).append(tuple(event))
    candidates: list[TranscriptionCandidate] = []
    for instrument in getattr(midi_data, "instruments", ()):
        for note in getattr(instrument, "notes", ()):
            matches = events_by_pitch.get(int(note.pitch), [])
            if matches:
                match_index = min(
                    range(len(matches)),
                    key=lambda index: (
                        abs(float(matches[index][0]) - float(note.start))
                        + abs(float(matches[index][1]) - float(note.end))
                    ),
                )
                # Each Basic Pitch event describes exactly one rendered MIDI
                # note. Consume it so repeated same-pitch notes cannot inherit
                # another note's confidence.
                match = matches.pop(match_index)
            else:
                match = None
            confidence = (
                float(match[3])
                if match is not None
                else float(note.velocity) / 127.0
            )
            candidates.append(
                TranscriptionCandidate(
                    max(0, min(127, int(note.pitch))),
                    max(1, min(127, round(float(note.velocity)))),
                    max(0.0, float(note.start) * 1000.0),
                    max(1.0, (float(note.end) - float(note.start)) * 1000.0),
                    max(0.0, min(1.0, confidence)),
                )
            )
    candidates.sort(
        key=lambda item: (item.start_ms, item.pitch, item.duration_ms)
    )
    return tuple(candidates)


def blockwise_harmonic_signal(
    audio: np.ndarray,
    sample_rate: int,
    *,
    block_seconds: float = HPSS_BLOCK_SECONDS,
    overlap_seconds: float = HPSS_OVERLAP_SECONDS,
    harmonic_separator: Callable[[np.ndarray], np.ndarray] | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> np.ndarray:
    """Return a length-preserving harmonic signal using bounded HPSS blocks."""

    signal = np.asarray(audio, dtype=np.float32)
    if signal.ndim != 1:
        raise ValueError("HPSS input must be mono")
    if not signal.size:
        return signal.copy()
    if (
        isinstance(sample_rate, bool)
        or int(sample_rate) <= 0
        or not math.isfinite(float(block_seconds))
        or not math.isfinite(float(overlap_seconds))
        or block_seconds <= 0.0
        or overlap_seconds < 0.0
        or overlap_seconds >= block_seconds
    ):
        raise ValueError("invalid HPSS block configuration")
    if not bool(np.isfinite(signal).all()):
        raise ValueError("HPSS input contains non-finite samples")
    if harmonic_separator is None:
        try:
            import librosa
        except ModuleNotFoundError as exc:
            raise TranscriptionError(_backend_install_message()) from exc
        harmonic_separator = (
            lambda block: _fast_harmonic_separator(librosa, block)
        )

    block_samples = max(1, int(round(block_seconds * int(sample_rate))))
    overlap_samples = max(
        0, int(round(overlap_seconds * int(sample_rate)))
    )
    step_samples = block_samples - overlap_samples
    starts = tuple(range(0, signal.size, step_samples))
    output = np.zeros(signal.shape, dtype=np.float32)
    weights = np.zeros(signal.shape, dtype=np.float32)
    for index, start in enumerate(starts):
        _cancel_if_requested(cancelled)
        end = min(signal.size, start + block_samples)
        separated = np.asarray(
            harmonic_separator(signal[start:end]),
            dtype=np.float32,
        )
        if (
            separated.shape != (end - start,)
            or not bool(np.isfinite(separated).all())
        ):
            raise TranscriptionError(
                "HPSS returned an invalid harmonic block"
            )
        envelope = np.ones(separated.shape, dtype=np.float32)
        fade_samples = min(overlap_samples, separated.size)
        if fade_samples and start > 0:
            envelope[:fade_samples] *= np.linspace(
                0.0,
                1.0,
                fade_samples,
                endpoint=False,
                dtype=np.float32,
            )
        if fade_samples and end < signal.size:
            envelope[-fade_samples:] *= np.linspace(
                1.0,
                0.0,
                fade_samples,
                endpoint=False,
                dtype=np.float32,
            )
        output[start:end] += separated * envelope
        weights[start:end] += envelope
        if progress:
            progress(round(100 * (index + 1) / len(starts)))
    _cancel_if_requested(cancelled)
    np.divide(
        output,
        weights,
        out=output,
        where=weights > np.finfo(np.float32).eps,
    )
    return output


def fuse_transcription_evidence(
    original: dict[str, np.ndarray],
    harmonic: dict[str, np.ndarray],
    *,
    frame_harmonic_weight: float = (
        MIXED_ENHANCED_FRAME_HARMONIC_WEIGHT
    ),
    onset_harmonic_weight: float = (
        MIXED_ENHANCED_ONSET_HARMONIC_WEIGHT
    ),
    contour_harmonic_weight: float = (
        MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT
    ),
) -> dict[str, np.ndarray]:
    """Fuse two frame-aligned Basic Pitch outputs without changing time."""

    weights = {
        "note": float(frame_harmonic_weight),
        "onset": float(onset_harmonic_weight),
        "contour": float(contour_harmonic_weight),
    }
    if any(
        not math.isfinite(weight) or not 0.0 <= weight <= 1.0
        for weight in weights.values()
    ):
        raise ValueError("transcription fusion weights must be in [0, 1]")
    fused: dict[str, np.ndarray] = {}
    for key, expected_bins in (
        ("note", TRANSCRIPTION_NOTE_BINS),
        ("onset", TRANSCRIPTION_NOTE_BINS),
        (
            "contour",
            TRANSCRIPTION_NOTE_BINS
            * TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE,
        ),
    ):
        raw = _normalise_evidence(original.get(key), expected_bins)
        separated = _normalise_evidence(harmonic.get(key), expected_bins)
        if (
            raw is None
            or separated is None
            or raw.shape != separated.shape
            or not bool(np.isfinite(raw).all())
            or not bool(np.isfinite(separated).all())
        ):
            raise TranscriptionError(
                f"Basic Pitch evidence timelines do not align: {key}"
            )
        weight = weights[key]
        values = (
            np.asarray(raw, dtype=np.float32) * (1.0 - weight)
            + np.asarray(separated, dtype=np.float32) * weight
        )
        fused[key] = np.clip(values, 0.0, 1.0)
    return fused


def _signal_audio_input(
    audio: np.ndarray,
    inference,
    overlap_len: int,
    hop_size: int,
):
    """Yield Basic Pitch windows without an audio-length padding copy."""

    signal = np.asarray(audio, dtype=np.float32)
    if signal.ndim != 1:
        raise ValueError("Basic Pitch input must be mono")
    original_length = int(signal.shape[0])
    prefix = int(overlap_len / 2)
    padded_length = prefix + original_length
    window_size = int(inference.AUDIO_N_SAMPLES)
    sample_rate = float(inference.AUDIO_SAMPLE_RATE)
    for start in range(0, padded_length, int(hop_size)):
        window = np.zeros((window_size,), dtype=np.float32)
        source_start = max(0, start - prefix)
        target_start = max(0, prefix - start)
        count = min(
            original_length - source_start,
            window_size - target_start,
        )
        if count > 0:
            window[target_start : target_start + count] = signal[
                source_start : source_start + count
            ]
        window_time = {
            "start": float(start) / sample_rate,
            "end": float(start + window_size) / sample_rate,
        }
        yield (
            window.reshape((1, window_size, 1)),
            window_time,
            original_length,
        )


def _prediction_frames(
    prediction: dict[str, np.ndarray],
    key: str,
    expected_bins: int,
    trim_frames: int,
) -> np.ndarray:
    value = prediction.get(key)
    if value is None:
        raise TranscriptionError(
            f"Basic Pitch output is missing {key}"
        )
    array = np.asarray(value, dtype=np.float32)
    if (
        array.ndim != 3
        or array.shape[0] != 1
        or array.shape[2] != expected_bins
        or array.shape[1] <= trim_frames * 2
        or not bool(np.isfinite(array).all())
    ):
        raise TranscriptionError(
            f"Basic Pitch returned an invalid {key} window"
        )
    return array[0, trim_frames:-trim_frames, :]


def _stream_basic_pitch_evidence(
    original: np.ndarray,
    model,
    inference,
    workspace: Path,
    *,
    harmonic: np.ndarray | None = None,
    overlapping_frames: int,
    overlap_len: int,
    hop_size: int,
    frame_harmonic_weight: float = (
        MIXED_ENHANCED_FRAME_HARMONIC_WEIGHT
    ),
    onset_harmonic_weight: float = (
        MIXED_ENHANCED_ONSET_HARMONIC_WEIGHT
    ),
    contour_harmonic_weight: float = (
        MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT
    ),
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> tuple[dict[str, np.memmap], int]:
    """Write one quantized evidence timeline while predicting each window."""

    signal = np.asarray(original, dtype=np.float32)
    if signal.ndim != 1 or not signal.size:
        raise TranscriptionError(
            "参考音频中没有可分析的音频帧"
        )
    separated_signal = (
        None
        if harmonic is None
        else np.asarray(harmonic, dtype=np.float32)
    )
    if (
        separated_signal is not None
        and separated_signal.shape != signal.shape
    ):
        raise TranscriptionError(
            "HPSS changed the transcription audio timeline"
        )
    original_length = int(signal.shape[0])
    annotation_fps = float(getattr(inference, "ANNOTATIONS_FPS", 86.0))
    frame_count = int(
        np.floor(
            original_length
            * annotation_fps
            / float(inference.AUDIO_SAMPLE_RATE)
        )
    )
    if frame_count <= 0:
        raise TranscriptionError(
            "参考音频中没有可分析的音频帧"
        )
    specifications = {
        "note": TRANSCRIPTION_NOTE_BINS,
        "onset": TRANSCRIPTION_NOTE_BINS,
        "contour": (
            TRANSCRIPTION_NOTE_BINS
            * TRANSCRIPTION_CONTOUR_BINS_PER_SEMITONE
        ),
    }
    weights = {
        "note": float(frame_harmonic_weight),
        "onset": float(onset_harmonic_weight),
        "contour": float(contour_harmonic_weight),
    }
    if any(
        not math.isfinite(weight) or not 0.0 <= weight <= 1.0
        for weight in weights.values()
    ):
        raise ValueError(
            "transcription fusion weights must be in [0, 1]"
        )
    output: dict[str, np.memmap] = {}
    try:
        for key, bins in specifications.items():
            output[key] = np.lib.format.open_memmap(
                workspace / f"evidence-{key}.npy",
                mode="w+",
                dtype=TRANSCRIPTION_EVIDENCE_DTYPE,
                shape=(frame_count, bins),
            )
        original_windows = iter(
            _signal_audio_input(
                signal,
                inference,
                overlap_len,
                hop_size,
            )
        )
        harmonic_windows = (
            None
            if separated_signal is None
            else iter(
                _signal_audio_input(
                    separated_signal,
                    inference,
                    overlap_len,
                    hop_size,
                )
            )
        )
        total_windows = max(
            1,
            (
                int(overlap_len / 2)
                + original_length
                + int(hop_size)
                - 1
            )
            // int(hop_size),
        )
        cursor = 0
        trim_frames = int(overlapping_frames / 2)
        for index, (
            original_window,
            _window_time,
            _window_length,
        ) in enumerate(original_windows):
            _cancel_if_requested(cancelled)
            original_prediction = model.predict(original_window)
            harmonic_prediction = None
            if harmonic_windows is not None:
                _cancel_if_requested(cancelled)
                try:
                    harmonic_window, _harmonic_time, harmonic_length = (
                        next(harmonic_windows)
                    )
                except StopIteration as exc:
                    raise TranscriptionError(
                        "HPSS inference timeline changed"
                    ) from exc
                if int(harmonic_length) != original_length:
                    raise TranscriptionError(
                        "HPSS inference timeline changed"
                    )
                harmonic_prediction = model.predict(harmonic_window)
            frames_this_window: int | None = None
            for key, bins in specifications.items():
                raw = _prediction_frames(
                    original_prediction,
                    key,
                    bins,
                    trim_frames,
                )
                if frames_this_window is None:
                    frames_this_window = int(raw.shape[0])
                elif raw.shape[0] != frames_this_window:
                    raise TranscriptionError(
                        "Basic Pitch evidence windows do not align"
                    )
                available = min(
                    int(raw.shape[0]),
                    frame_count - cursor,
                )
                if available <= 0:
                    continue
                values = raw[:available]
                if harmonic_prediction is not None:
                    separated = _prediction_frames(
                        harmonic_prediction,
                        key,
                        bins,
                        trim_frames,
                    )
                    if separated.shape != raw.shape:
                        raise TranscriptionError(
                            "Basic Pitch evidence timelines do not align"
                        )
                    weight = weights[key]
                    values = (
                        values * (1.0 - weight)
                        + separated[:available] * weight
                    )
                output[key][cursor : cursor + available] = np.clip(
                    values,
                    0.0,
                    1.0,
                )
            if frames_this_window is None:
                raise TranscriptionError(
                    "Basic Pitch returned no evidence"
                )
            cursor += min(
                frames_this_window,
                max(0, frame_count - cursor),
            )
            if progress is not None:
                progress(
                    min(
                        100,
                        round(100 * (index + 1) / total_windows),
                    )
                )
            if cursor >= frame_count:
                break
        if harmonic_windows is not None and cursor < frame_count:
            raise TranscriptionError(
                "HPSS inference timeline changed"
            )
        if cursor != frame_count:
            raise TranscriptionError(
                "Basic Pitch evidence timeline is incomplete"
            )
        for array in output.values():
            array.flush()
        _cancel_if_requested(cancelled)
        return output, original_length
    except Exception:
        for array in output.values():
            _close_memmap(array)
        raise


def _run_streamed_analysis(
    audio_path: Path,
    model,
    inference,
    workspace: Path,
    *,
    analysis_mode: TranscriptionAnalysisMode | str,
    frame_harmonic_weight: float = (
        MIXED_ENHANCED_FRAME_HARMONIC_WEIGHT
    ),
    onset_harmonic_weight: float = (
        MIXED_ENHANCED_ONSET_HARMONIC_WEIGHT
    ),
    contour_harmonic_weight: float = (
        MIXED_ENHANCED_CONTOUR_HARMONIC_WEIGHT
    ),
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> tuple[dict[str, np.memmap], int]:
    """Run the product evidence path with duration-scaled data on disk."""

    mode = normalise_transcription_analysis_mode(analysis_mode)
    decode_progress = _mapped_progress(
        progress,
        5,
        7 if mode == MIXED_ENHANCED_ANALYSIS_MODE else 10,
    )
    source = _stream_decode_reference_audio(
        audio_path,
        workspace,
        target_sample_rate=int(inference.AUDIO_SAMPLE_RATE),
        progress=decode_progress,
        cancelled=cancelled,
    )
    harmonic_source: _StreamedAudioBuffer | None = None
    if mode == MIXED_ENHANCED_ANALYSIS_MODE:
        harmonic_source = _stream_harmonic_audio(
            source,
            workspace,
            librosa_module=inference.librosa,
            progress=_mapped_progress(progress, 12, 23),
            cancelled=cancelled,
        )
    overlapping_frames = 30
    overlap_len = overlapping_frames * int(inference.FFT_HOP)
    hop_size = int(inference.AUDIO_N_SAMPLES) - overlap_len
    original_audio = source.open("r")
    harmonic_audio = (
        None
        if harmonic_source is None
        else harmonic_source.open("r")
    )
    try:
        return _stream_basic_pitch_evidence(
            original_audio,
            model,
            inference,
            workspace,
            harmonic=harmonic_audio,
            overlapping_frames=overlapping_frames,
            overlap_len=overlap_len,
            hop_size=hop_size,
            frame_harmonic_weight=frame_harmonic_weight,
            onset_harmonic_weight=onset_harmonic_weight,
            contour_harmonic_weight=contour_harmonic_weight,
            progress=_mapped_progress(
                progress,
                35 if harmonic_audio is not None else 15,
                55 if harmonic_audio is not None else 75,
            ),
            cancelled=cancelled,
        )
    finally:
        _close_memmap(original_audio)
        if harmonic_audio is not None:
            _close_memmap(harmonic_audio)


def _predict_basic_pitch_windows(
    audio_input,
    model,
    inference,
    *,
    overlapping_frames: int,
    overlap_len: int,
    hop_size: int,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> tuple[dict[str, np.ndarray], int]:
    output: dict[str, list[np.ndarray]] = {
        "note": [],
        "onset": [],
        "contour": [],
    }
    original_length = 0
    for index, (windowed, _window_time, original_length) in enumerate(
        audio_input
    ):
        _cancel_if_requested(cancelled)
        prediction = model.predict(windowed)
        for key in output:
            value = prediction.get(key)
            if value is None:
                raise TranscriptionError(
                    f"Basic Pitch output is missing {key}"
                )
            output[key].append(value)
        if progress and original_length:
            total = max(
                1,
                (original_length + overlap_len + hop_size - 1) // hop_size,
            )
            progress(min(100, round(100 * (index + 1) / total)))
    _cancel_if_requested(cancelled)
    if not original_length or not output["note"]:
        raise TranscriptionError("参考音频中没有可分析的音频帧")
    return (
        {
            key: inference.unwrap_output(
                np.concatenate(values),
                original_length,
                overlapping_frames,
            )
            for key, values in output.items()
        },
        original_length,
    )


def transcription_thresholds(
    sensitivity: TranscriptionSensitivity | str,
    analysis_mode: TranscriptionAnalysisMode | str = (
        STANDARD_ANALYSIS_MODE
    ),
) -> tuple[float, float]:
    mode = normalise_transcription_analysis_mode(analysis_mode)
    value = str(sensitivity)
    if mode == MIXED_ENHANCED_ANALYSIS_MODE:
        balanced_onset = (
            MIXED_ENHANCED_BALANCED_ONSET_THRESHOLD
        )
        balanced_frame = (
            MIXED_ENHANCED_BALANCED_FRAME_THRESHOLD
        )
        presets = {
            "conservative": (
                round(min(0.95, balanced_onset + 0.15), 2),
                round(min(0.95, balanced_frame + 0.15), 2),
            ),
            "balanced": (balanced_onset, balanced_frame),
            "sensitive": (
                round(max(0.05, balanced_onset - 0.15), 2),
                round(max(0.05, balanced_frame - 0.10), 2),
            ),
        }
    else:
        presets = STANDARD_TRANSCRIPTION_SENSITIVITY_PRESETS
    try:
        return presets[value]
    except KeyError as exc:
        raise ValueError(
            f"unknown transcription sensitivity: {sensitivity}"
        ) from exc


def transcription_min_note_length_frames(
    sensitivity: TranscriptionSensitivity | str,
    analysis_mode: TranscriptionAnalysisMode | str = (
        DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
    ),
) -> int:
    mode = normalise_transcription_analysis_mode(analysis_mode)
    if mode == MIXED_ENHANCED_ANALYSIS_MODE:
        balanced = (
            MIXED_ENHANCED_BALANCED_MIN_NOTE_LENGTH_FRAMES
        )
        presets = {
            "conservative": min(32, balanced + 3),
            "balanced": balanced,
            "sensitive": max(2, balanced - 3),
        }
    else:
        presets = STANDARD_MIN_NOTE_LENGTH_FRAMES
    try:
        return presets[str(sensitivity)]
    except KeyError as exc:
        raise ValueError(
            f"unknown transcription sensitivity: {sensitivity}"
        ) from exc


def _import_basic_pitch_note_creation():
    root_logger = logging.getLogger()
    backend_filter = _OptionalBackendFilter()
    root_logger.addFilter(backend_filter)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"pkg_resources is deprecated as an API\..*",
                category=UserWarning,
                module=r"resampy\.filters",
            )
            import basic_pitch.note_creation as note_creation
    except ModuleNotFoundError as exc:
        raise TranscriptionError(_backend_install_message()) from exc
    finally:
        root_logger.removeFilter(backend_filter)
    return note_creation


def _candidate_from_frame_event(
    event: FrameNoteEvent,
    frame_times_ms: np.ndarray,
    *,
    frame_offset: int = 0,
    duration_ms: float | None = None,
) -> TranscriptionCandidate | None:
    """Convert one exclusive-end frame event through the persisted time axis."""

    global_start = int(frame_offset) + int(event.start_frame)
    global_end = int(frame_offset) + int(event.end_frame)
    if (
        global_start < 0
        or global_start >= len(frame_times_ms)
        or global_end <= global_start
        or global_end > len(frame_times_ms)
    ):
        return None
    start_ms = float(frame_times_ms[global_start])
    if global_end < len(frame_times_ms):
        end_ms = float(frame_times_ms[global_end])
    elif duration_ms is not None:
        end_ms = float(duration_ms)
    elif len(frame_times_ms) >= 2:
        end_ms = float(frame_times_ms[-1]) + float(
            frame_times_ms[-1] - frame_times_ms[-2]
        )
    else:
        end_ms = start_ms + 1.0
    confidence = max(0.0, min(1.0, float(event.confidence)))
    return TranscriptionCandidate(
        pitch=max(0, min(127, int(event.pitch))),
        velocity=max(1, min(127, int(round(127.0 * confidence)))),
        start_ms=max(0.0, start_ms),
        duration_ms=max(1.0, end_ms - start_ms),
        confidence=confidence,
    )


def _recover_dense_short_frame_events(
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    existing_events: list[FrameNoteEvent],
    *,
    onset_threshold: float,
    frame_threshold: float,
    min_note_len: int,
) -> tuple[FrameNoteEvent, ...]:
    """Recover only strong short notes inside a regular dense onset run.

    Lowering Basic Pitch's minimum note length globally creates a large number
    of fragments.  This bounded side path instead requires a three-onset
    regular sequence, a strong pitch-specific onset, and sustained frame
    evidence.  It therefore targets 1/32–1/64 passages without changing the
    ordinary decoder threshold.
    """

    frame = np.asarray(frame_evidence, dtype=np.float32)
    onset = np.asarray(onset_evidence, dtype=np.float32)
    if (
        frame.ndim != 2
        or onset.shape != frame.shape
        or len(frame) < 5
        or int(min_note_len) < DENSE_SHORT_MIN_FRAMES
    ):
        return ()
    strong_onset = max(0.68, min(0.92, float(onset_threshold) + 0.12))
    global_onset = np.max(onset, axis=1)
    peak_indices = np.flatnonzero(
        (global_onset >= strong_onset)
        & (global_onset >= np.r_[global_onset[0], global_onset[:-1]])
        & (global_onset >= np.r_[global_onset[1:], global_onset[-1]])
    )
    if len(peak_indices) < 3:
        return ()
    dense_peaks: set[int] = set()
    for first, middle, last in zip(
        peak_indices,
        peak_indices[1:],
        peak_indices[2:],
    ):
        left_gap = int(middle - first)
        right_gap = int(last - middle)
        if (
            DENSE_SHORT_MIN_FRAMES <= left_gap <= DENSE_SHORT_MAX_GAP_FRAMES
            and DENSE_SHORT_MIN_FRAMES <= right_gap <= DENSE_SHORT_MAX_GAP_FRAMES
            and abs(left_gap - right_gap)
            <= max(1, round(max(left_gap, right_gap) * DENSE_SHORT_REGULARITY_TOLERANCE))
        ):
            dense_peaks.update((int(first), int(middle), int(last)))
    if not dense_peaks:
        return ()

    existing = {
        (int(event.pitch), int(event.start_frame) + delta)
        for event in existing_events
        for delta in (-1, 0, 1)
    }
    output: list[FrameNoteEvent] = []
    maximum_span = max(DENSE_SHORT_MIN_FRAMES, int(min_note_len))
    for start in sorted(dense_peaks):
        pitch_columns = np.flatnonzero(onset[start] >= strong_onset)
        for column in pitch_columns:
            pitch = int(column) + TRANSCRIPTION_MIDI_MIN
            if (pitch, start) in existing:
                continue
            end = start + 1
            weak_run = 0
            while end < len(frame) and end - start <= maximum_span:
                if float(onset[end, column]) >= strong_onset:
                    end = max(start + 1, end - weak_run)
                    break
                if float(frame[end, column]) >= float(frame_threshold):
                    weak_run = 0
                else:
                    weak_run += 1
                    if weak_run >= 2:
                        end -= 1
                        break
                end += 1
            span = end - start
            if not DENSE_SHORT_MIN_FRAMES <= span <= maximum_span:
                continue
            frame_support = float(np.mean(frame[start:end, column]))
            if frame_support < min(0.95, float(frame_threshold) + 0.08):
                continue
            confidence = max(
                0.0,
                min(
                    1.0,
                    0.55 * float(onset[start, column])
                    + 0.45 * frame_support,
                ),
            )
            recovered = FrameNoteEvent(start, end, pitch, confidence)
            output.append(recovered)
            existing.update((pitch, start + delta) for delta in (-1, 0, 1))
    return tuple(output)


def _decode_evidence_candidates(
    note_creation,
    frame_evidence: np.ndarray,
    onset_evidence: np.ndarray,
    frame_times_ms: np.ndarray,
    *,
    cache_key: str,
    onset_threshold: float,
    frame_threshold: float,
    min_note_len: int,
    cleanup_profile: CleanupProfile | str,
    frame_offset: int = 0,
    duration_ms: float | None = None,
    selection_start_ms: float | None = None,
    selection_end_ms: float | None = None,
) -> tuple[
    tuple[TranscriptionCandidate, ...],
    TranscriptionPostprocessReport,
]:
    """Decode and postprocess one evidence window for every entry point."""

    cleanup = normalise_transcription_cleanup_profile(cleanup_profile)
    frame = np.asarray(frame_evidence, dtype=np.float32)
    onset = np.asarray(onset_evidence, dtype=np.float32)
    if frame.shape != onset.shape or frame.ndim != 2:
        raise TranscriptionError(
            "frame and onset evidence do not share one time axis"
        )

    selection_start = (
        None
        if selection_start_ms is None
        else float(selection_start_ms)
    )
    selection_end = (
        None
        if selection_end_ms is None
        else float(selection_end_ms)
    )

    def in_selection(candidate: TranscriptionCandidate) -> bool:
        if (
            selection_start is not None
            and candidate.start_ms < selection_start
        ):
            return False
        return not (
            selection_end is not None
            and candidate.start_ms >= selection_end
        )

    events = note_creation.output_to_notes_polyphonic(
        frame,
        onset,
        onset_thresh=float(onset_threshold),
        frame_thresh=float(frame_threshold),
        infer_onsets=True,
        min_note_len=int(min_note_len),
        min_freq=None,
        max_freq=None,
        melodia_trick=True,
    )
    raw_events: list[FrameNoteEvent] = []
    projected_candidates: dict[
        tuple[int, int, int, float],
        TranscriptionCandidate,
    ] = {}
    raw_candidate_count = 0

    def projection_key(
        event: FrameNoteEvent,
    ) -> tuple[int, int, int, float]:
        # Lineage can change after NMS/merge while the projected candidate
        # facts stay identical.  Cache by only the facts consumed by the
        # frame-to-time projection and stable candidate ID.
        return (
            int(event.start_frame),
            int(event.end_frame),
            int(event.pitch),
            float(event.confidence),
        )

    def project_event(
        event: FrameNoteEvent,
    ) -> TranscriptionCandidate | None:
        key = projection_key(event)
        cached = projected_candidates.get(key)
        if cached is not None:
            return cached
        candidate = _candidate_from_frame_event(
            event,
            frame_times_ms,
            frame_offset=frame_offset,
            duration_ms=duration_ms,
        )
        if candidate is None:
            return None
        identified = replace(
            candidate,
            candidate_id=transcription_candidate_id(
                cache_key,
                candidate,
            ),
        )
        projected_candidates[key] = identified
        return identified

    for item in events:
        if len(item) < 4:
            continue
        try:
            local_event = FrameNoteEvent(
                int(item[0]),
                int(item[1]),
                max(0, min(127, int(item[2]))),
                max(0.0, min(1.0, float(item[3]))),
            )
        except (TypeError, ValueError, OverflowError):
            continue
        raw_candidate = project_event(local_event)
        if raw_candidate is None:
            continue
        if in_selection(raw_candidate):
            raw_candidate_count += 1
        raw_events.append(
            replace(
                local_event,
                lineage=(
                    raw_candidate.candidate_id,
                ),
            )
        )

    recovered_events = _recover_dense_short_frame_events(
        frame,
        onset,
        raw_events,
        onset_threshold=float(onset_threshold),
        frame_threshold=float(frame_threshold),
        min_note_len=int(min_note_len),
    )
    for recovered_event in recovered_events:
        recovered_candidate = project_event(recovered_event)
        if recovered_candidate is None:
            continue
        if in_selection(recovered_candidate):
            raw_candidate_count += 1
        raw_events.append(
            replace(
                recovered_event,
                lineage=(recovered_candidate.candidate_id,),
            )
        )

    processed = postprocess_frame_events(
        raw_events,
        frame,
        onset,
        profile=cleanup,
        onset_threshold=float(onset_threshold),
        frame_threshold=float(frame_threshold),
        midi_min=TRANSCRIPTION_MIDI_MIN,
    )
    audit_by_event = {
        item.event: item
        for item in processed.audit
        if item.action in {"kept", "merged", "suppressed"}
    }

    identified: list[TranscriptionCandidate] = []
    suppressed_candidates: list[TranscriptionCandidate] = []
    annotations: list[TranscriptionCandidateAnnotation] = []

    def append_event(event: FrameNoteEvent, *, suppressed: bool) -> None:
        candidate = project_event(event)
        if candidate is None or not in_selection(candidate):
            return
        audit = audit_by_event.get(event)
        annotation = TranscriptionCandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=tuple(sorted(audit.flags if audit is not None else ())),
            lineage_ids=tuple(event.lineage),
            disposition=(
                "suppressed"
                if suppressed
                else (
                    str(audit.action)
                    if audit is not None
                    else "kept"
                )
            ),
        )
        annotations.append(annotation)
        if suppressed:
            suppressed_candidates.append(candidate)
        else:
            identified.append(candidate)

    for event in processed.events:
        append_event(event, suppressed=False)
    for event in processed.suppressed:
        append_event(event, suppressed=True)
    identified.sort(
        key=lambda item: (
            item.start_ms,
            item.pitch,
            item.duration_ms,
            item.candidate_id,
        )
    )
    suppressed_candidates.sort(
        key=lambda item: (
            item.start_ms,
            item.pitch,
            item.duration_ms,
            item.candidate_id,
        )
    )
    annotations.sort(key=lambda item: item.candidate_id)
    selected_annotations = tuple(annotations)
    report = TranscriptionPostprocessReport(
        profile=processed.profile,
        version=processed.version,
        raw_candidate_count=raw_candidate_count,
        output_candidate_count=len(identified),
        exact_duplicate_count=processed.stats.exact_duplicate_count,
        nms_removed_count=processed.stats.nms_removed_count,
        automatic_merge_count=sum(
            item.disposition == "merged" for item in selected_annotations
        ),
        suspected_fragment_count=sum(
            "review_fragment" in item.flags
            for item in selected_annotations
        ),
        severe_fragment_count=sum(
            "severe_fragment" in item.flags
            for item in selected_annotations
        ),
        density_short_count=sum(
            "short_density" in item.flags
            for item in selected_annotations
        ),
        pitch_flicker_count=sum(
            "pitch_flicker" in item.flags
            for item in selected_annotations
        ),
        suppressed_count=len(suppressed_candidates),
        annotations=selected_annotations,
        suppressed_candidates=tuple(suppressed_candidates),
        automatic_actions_enabled=processed.automatic_actions_enabled,
    )
    return tuple(identified), report


def redecode_transcription_interval(
    cache_key: str,
    start_ms: float,
    end_ms: float,
    *,
    sensitivity: TranscriptionSensitivity = "balanced",
    cleanup_profile: CleanupProfile = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    context_ms: float = 500.0,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    cancelled: CancelCallback | None = None,
) -> TranscriptionResult:
    """Decode one A-B range from cached activations without running ONNX."""

    start_ms = float(start_ms)
    end_ms = float(end_ms)
    context_ms = float(context_ms)
    cleanup = normalise_transcription_cleanup_profile(cleanup_profile)
    if (
        not math.isfinite(start_ms)
        or not math.isfinite(end_ms)
        or not math.isfinite(context_ms)
        or start_ms < 0.0
        or end_ms <= start_ms
        or context_ms < 0.0
    ):
        raise ValueError("invalid transcription decode interval")
    _cancel_if_requested(cancelled)
    cache_root = Path(cache_root)
    try:
        cached = _read_valid_cache_entry(
            str(cache_key),
            cache_root,
            cancelled=cancelled,
        )
    except ValueError as exc:
        raise TranscriptionError("invalid transcription cache key") from exc
    if cached is None:
        raise TranscriptionError(
            "transcription evidence cache is missing or invalid"
    )
    _stored_candidates, descriptor = cached
    onset_threshold, frame_threshold = transcription_thresholds(
        sensitivity,
        descriptor.analysis_mode,
    )
    min_note_len = transcription_min_note_length_frames(
        sensitivity,
        descriptor.analysis_mode,
    )
    folder = _cache_folder(str(cache_key), cache_root)
    arrays: list[np.ndarray] = []
    try:
        times = np.load(
            folder / descriptor.times_filename,
            mmap_mode="r",
            allow_pickle=False,
        )
        frame = np.load(
            folder / descriptor.layer("frame").filename,
            mmap_mode="r",
            allow_pickle=False,
        )
        onset = np.load(
            folder / descriptor.layer("onset").filename,
            mmap_mode="r",
            allow_pickle=False,
        )
        arrays.extend((times, frame, onset))
        context_start = max(0.0, start_ms - context_ms)
        context_end = min(descriptor.duration_ms, end_ms + context_ms)
        lo = int(np.searchsorted(times, context_start, side="left"))
        hi = int(np.searchsorted(times, context_end, side="right"))
        if hi - lo < 2:
            result_descriptor = replace(
                descriptor,
                decode_sensitivity=str(sensitivity),
                cleanup_profile=cleanup,
                postprocess_version=POSTPROCESS_VERSION,
            )
            return TranscriptionResult(
                (),
                str(cache_key),
                descriptor.layer_names,
                True,
                result_descriptor,
                _empty_transcription_postprocess_report(cleanup),
            )
        _cancel_if_requested(cancelled)
        note_creation = _import_basic_pitch_note_creation()
        identified, postprocess_report = _decode_evidence_candidates(
            note_creation,
            frame[lo:hi],
            onset[lo:hi],
            times,
            cache_key=str(cache_key),
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            min_note_len=min_note_len,
            cleanup_profile=cleanup,
            frame_offset=lo,
            duration_ms=descriptor.duration_ms,
            selection_start_ms=start_ms,
            selection_end_ms=end_ms,
        )
        _cancel_if_requested(cancelled)
        result_descriptor = replace(
            descriptor,
            decode_sensitivity=str(sensitivity),
            cleanup_profile=cleanup,
            postprocess_version=POSTPROCESS_VERSION,
        )
        return TranscriptionResult(
            identified,
            str(cache_key),
            descriptor.layer_names,
            True,
            result_descriptor,
            postprocess_report,
        )
    except TranscriptionCancelled:
        raise
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(
            f"cached transcription decode failed: {exc}"
        ) from exc
    finally:
        for array in arrays:
            _close_memmap(array)


def redecode_transcription_full(
    cache_key: str,
    *,
    sensitivity: TranscriptionSensitivity = "balanced",
    cleanup_profile: CleanupProfile = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    cancelled: CancelCallback | None = None,
) -> TranscriptionResult:
    """Decode the full cached timeline without rerunning ONNX inference."""

    cached = _read_valid_cache_entry(
        str(cache_key),
        Path(cache_root),
        cancelled=cancelled,
    )
    if cached is None:
        raise TranscriptionError(
            "transcription evidence cache is missing or invalid"
        )
    descriptor = cached[1]
    return redecode_transcription_interval(
        str(cache_key),
        0.0,
        max(1.0, float(descriptor.duration_ms) + 1.0),
        sensitivity=sensitivity,
        cleanup_profile=cleanup_profile,
        context_ms=0.0,
        cache_root=Path(cache_root),
        cancelled=cancelled,
    )


def transcribe_reference_audio(
    audio_path: Path | str,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    *,
    analysis_mode: TranscriptionAnalysisMode = (
        DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
    ),
    sensitivity: TranscriptionSensitivity = "balanced",
    cleanup_profile: CleanupProfile = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
) -> TranscriptionResult:
    """Transcribe one local reference file into non-authoritative candidates."""
    mode = normalise_transcription_analysis_mode(analysis_mode)
    cleanup = normalise_transcription_cleanup_profile(cleanup_profile)
    onset_threshold, frame_threshold = transcription_thresholds(
        sensitivity,
        mode,
    )
    min_note_len = transcription_min_note_length_frames(sensitivity, mode)
    path = Path(audio_path).resolve()
    if not path.is_file():
        raise TranscriptionError(f"参考音频不存在：{path}")
    cache_root = Path(cache_root)
    audio_fingerprint = transcription_audio_fingerprint(
        path,
        cancelled=cancelled,
    )
    cached = _load_cached_result(
        path,
        cache_root,
        analysis_mode=mode,
        audio_fingerprint=audio_fingerprint,
        cancelled=cancelled,
    )
    if cached is not None:
        _cancel_if_requested(cancelled)
        descriptor = cached.evidence_descriptor
        if (
            descriptor is not None
            and (
                descriptor.decode_sensitivity != str(sensitivity)
                or descriptor.cleanup_profile != cleanup
                or descriptor.postprocess_version != POSTPROCESS_VERSION
            )
        ):
            cached = redecode_transcription_full(
                cached.cache_key,
                sensitivity=sensitivity,
                cleanup_profile=cleanup,
                cache_root=cache_root,
                cancelled=cancelled,
            )
        if progress:
            progress(100)
        return cached
    if progress:
        progress(1)
    backend_available, backend_message = transcription_backend_status()
    if not backend_available:
        raise TranscriptionError(backend_message)

    while not _INFERENCE_LOCK.acquire(timeout=0.1):
        _cancel_if_requested(cancelled)
    try:
        _cancel_if_requested(cancelled)
        if progress:
            progress(2)
        basic_pitch, inference, note_creation, onnxruntime = _import_basic_pitch()
        if not basic_pitch.ONNX_PRESENT:
            raise TranscriptionError(transcription_backend_message())
        model = _onnx_model(basic_pitch, inference, onnxruntime)
        model_output: dict[str, np.ndarray] = {}
        with _transcription_workspace(cache_root) as workspace:
            try:
                model_output, original_length = _run_streamed_analysis(
                    path,
                    model,
                    inference,
                    workspace,
                    analysis_mode=mode,
                    progress=progress,
                    cancelled=cancelled,
                )
                if progress:
                    progress(92)
                _cancel_if_requested(cancelled)
                current_audio_fingerprint = transcription_audio_fingerprint(
                    path,
                    cancelled=cancelled,
                )
                if current_audio_fingerprint != audio_fingerprint:
                    raise TranscriptionError(
                        "reference audio changed during transcription; "
                        "no cache was written"
                    )
                cache_key = transcription_cache_key(
                    path,
                    analysis_mode=mode,
                    audio_fingerprint=current_audio_fingerprint,
                )
                frame_evidence = _normalise_evidence(
                    _evidence_value(model_output, "frame"),
                    TRANSCRIPTION_NOTE_BINS,
                )
                onset_evidence = _normalise_evidence(
                    _evidence_value(model_output, "onset"),
                    TRANSCRIPTION_NOTE_BINS,
                )
                if frame_evidence is None or onset_evidence is None:
                    raise TranscriptionError(
                        "Basic Pitch returned incomplete note evidence"
                    )
                # Decode exactly the float16 evidence that is persisted.  A
                # first analysis and a later cache-only re-decode must not
                # diverge at threshold boundaries because of quantization.
                decode_frame_evidence = frame_evidence.astype(
                    TRANSCRIPTION_EVIDENCE_DTYPE,
                    copy=False,
                )
                decode_onset_evidence = onset_evidence.astype(
                    TRANSCRIPTION_EVIDENCE_DTYPE,
                    copy=False,
                )
                frame_times_ms = basic_pitch_frame_times_ms(
                    frame_evidence.shape[0],
                    note_creation=note_creation,
                )
                duration_ms = (
                    float(original_length)
                    / float(inference.AUDIO_SAMPLE_RATE)
                    * 1000.0
                )
                candidates, postprocess_report = (
                    _decode_evidence_candidates(
                        note_creation,
                        decode_frame_evidence,
                        decode_onset_evidence,
                        frame_times_ms,
                        cache_key=cache_key,
                        onset_threshold=onset_threshold,
                        frame_threshold=frame_threshold,
                        min_note_len=min_note_len,
                        cleanup_profile=cleanup,
                        duration_ms=duration_ms,
                    )
                )
                result = TranscriptionResult(
                    candidates,
                    cache_key,
                    tuple(
                        name
                        for name, bins in (
                            ("frame", 88),
                            ("onset", 88),
                            ("contour", 264),
                        )
                        if _normalise_evidence(
                            _evidence_value(model_output, name),
                            bins,
                        ) is not None
                    ),
                    False,
                    None,
                    postprocess_report,
                )
                if progress:
                    progress(95)
                descriptor = _write_cached_result(
                    result,
                    model_output,
                    cache_root,
                    frame_times_ms=frame_times_ms,
                    duration_ms=duration_ms,
                    audio_fingerprint=current_audio_fingerprint,
                    analysis_mode=mode,
                    sensitivity=sensitivity,
                    cleanup_profile=cleanup,
                    cancelled=cancelled,
                )
                result = replace(
                    result,
                    evidence_layers=descriptor.layer_names,
                    evidence_descriptor=descriptor,
                )
                if progress:
                    progress(100)
                return result
            finally:
                for evidence in model_output.values():
                    _close_memmap(evidence)
    except TranscriptionCancelled:
        raise
    except TranscriptionError:
        raise
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "transcription analysis failed"
        )
        raise TranscriptionError(f"扒谱分析失败：{exc}") from exc
    finally:
        _INFERENCE_LOCK.release()


@dataclass(frozen=True)
class BasicPitchTranscriptionBackend:
    """Concrete facade preserving the existing function-based API."""

    backend_id: str = field(
        default=TRANSCRIPTION_BACKEND_ID,
        init=False,
    )

    def status(self) -> tuple[bool, str]:
        return transcription_backend_status()

    def transcribe(
        self,
        audio_path: Path | str,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
        *,
        analysis_mode: TranscriptionAnalysisMode = (
            DEFAULT_TRANSCRIPTION_ANALYSIS_MODE
        ),
        sensitivity: TranscriptionSensitivity = "balanced",
        cleanup_profile: CleanupProfile = (
            DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE
        ),
        cache_root: Path = TRANSCRIPTION_CACHE_DIR,
    ) -> TranscriptionResult:
        return transcribe_reference_audio(
            audio_path,
            progress,
            cancelled,
            analysis_mode=analysis_mode,
            sensitivity=sensitivity,
            cleanup_profile=cleanup_profile,
            cache_root=cache_root,
        )

    def redecode_interval(
        self,
        cache_key: str,
        start_ms: float,
        end_ms: float,
        *,
        sensitivity: TranscriptionSensitivity = "balanced",
        cleanup_profile: CleanupProfile = (
            DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE
        ),
        context_ms: float = 500.0,
        cache_root: Path = TRANSCRIPTION_CACHE_DIR,
        cancelled: CancelCallback | None = None,
    ) -> TranscriptionResult:
        return redecode_transcription_interval(
            cache_key,
            start_ms,
            end_ms,
            sensitivity=sensitivity,
            cleanup_profile=cleanup_profile,
            context_ms=context_ms,
            cache_root=cache_root,
            cancelled=cancelled,
        )


DEFAULT_TRANSCRIPTION_BACKEND: TranscriptionBackend = (
    BasicPitchTranscriptionBackend()
)
