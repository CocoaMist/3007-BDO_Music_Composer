"""Optional, local Basic Pitch transcription for the note editor.

The module is deliberately independent from Qt and the editor's authoritative
``Note`` wire shape. It returns immutable candidates plus cached evidence; the
UI decides whether any candidate becomes a real editor note.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import threading
from typing import Callable
import warnings

import numpy as np

from project_paths import TRANSCRIPTION_CACHE_DIR


ProgressCallback = Callable[[int], None]
CancelCallback = Callable[[], bool]

TRANSCRIPTION_CACHE_VERSION = 2
# Update this identifier whenever the backend package, bundled model, or
# interpretation of its output changes. It intentionally participates in the
# cache key so evidence produced by different models can never be mixed.
TRANSCRIPTION_BACKEND_ID = "basic-pitch-0.4.0:icassp-2022-onnx:v1"
TRANSCRIPTION_CACHE_MAX_BYTES = 2 * 1024**3
TRANSCRIPTION_CACHE_MAX_ENTRIES = 128
_CACHE_KEY_PATTERN = re.compile(r"[0-9a-f]{24}")
ONSET_THRESHOLD = 0.5
FRAME_THRESHOLD = 0.3
_INFERENCE_LOCK = threading.Lock()
_ONNX_MODEL = None


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
class TranscriptionResult:
    candidates: tuple[TranscriptionCandidate, ...]
    cache_key: str
    evidence_layers: tuple[str, ...] = ()
    cache_hit: bool = False


def _backend_install_message() -> str:
    if getattr(sys, "frozen", False):
        return (
            "当前 Standard 单文件版未内置扒谱引擎。"
            "请使用独立扒谱版，或在源码环境安装可选组件。"
        )
    return (
        "扒谱组件尚未安装或不可用。请在程序目录运行：\n"
        "powershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1"
    )


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
        raise TranscriptionError(_backend_install_message()) from exc
    finally:
        root_logger.removeFilter(backend_filter)
    return basic_pitch, inference, note_creation, onnxruntime


def transcription_backend_status() -> tuple[bool, str]:
    missing = [
        name
        for name in ("basic_pitch", "onnxruntime", "librosa")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        return False, _backend_install_message()
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
    except Exception as exc:
        return (
            False,
            f"{_backend_install_message()}\n\n组件检查失败：{exc}",
        )
    return True, ""


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


def transcription_cache_key(audio_path: Path | str) -> str:
    path = Path(audio_path).resolve()
    stat = path.stat()
    payload = {
        "version": TRANSCRIPTION_CACHE_VERSION,
        "backend_id": TRANSCRIPTION_BACKEND_ID,
        "path": str(path).casefold(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "onset_threshold": ONSET_THRESHOLD,
        "frame_threshold": FRAME_THRESHOLD,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]


def _cache_folder(cache_key: str, cache_root: Path) -> Path:
    if _CACHE_KEY_PATTERN.fullmatch(str(cache_key)) is None:
        raise ValueError("invalid transcription cache key")
    return cache_root / cache_key


def _load_cached_result(
    audio_path: Path,
    cache_root: Path,
) -> TranscriptionResult | None:
    try:
        cache_key = transcription_cache_key(audio_path)
        payload = json.loads(
            (_cache_folder(cache_key, cache_root) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError, TypeError):
        return None
    if (
        payload.get("version") != TRANSCRIPTION_CACHE_VERSION
        or payload.get("backend_id") != TRANSCRIPTION_BACKEND_ID
        or payload.get("cache_key") != cache_key
    ):
        return None
    try:
        candidates = tuple(
            TranscriptionCandidate(
                int(item["pitch"]),
                int(item["velocity"]),
                float(item["start_ms"]),
                float(item["duration_ms"]),
                max(0.0, min(1.0, float(item["confidence"]))),
                str(item.get("source") or "basic-pitch"),
            )
            for item in payload.get("candidates", [])
        )
    except (KeyError, TypeError, ValueError):
        return None
    return TranscriptionResult(
        candidates,
        cache_key,
        tuple(str(value) for value in payload.get("evidence_layers", [])),
        True,
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


def _evidence_value(
    model_output: dict[str, np.ndarray],
    layer: str,
) -> object:
    # Basic Pitch 0.4 exposes the 88-bin frame matrix under ``note`` even
    # though its public note-creation docs call that same matrix ``frame``.
    if layer == "frame" and "frame" not in model_output:
        return model_output.get("note")
    return model_output.get(layer)


def _write_cached_result(
    result: TranscriptionResult,
    model_output: dict[str, np.ndarray],
    cache_root: Path,
) -> None:
    folder = _cache_folder(result.cache_key, cache_root)
    folder.mkdir(parents=True, exist_ok=True)
    layers: list[str] = []
    for name, bins in (("frame", 88), ("onset", 88), ("contour", 264)):
        array = _normalise_evidence(_evidence_value(model_output, name), bins)
        if array is None:
            continue
        temporary = folder / f"{name}.npy.tmp"
        with temporary.open("wb") as stream:
            np.save(stream, array.astype(np.float16, copy=False), allow_pickle=False)
        temporary.replace(folder / f"{name}.npy")
        layers.append(name)
    manifest = {
        "version": TRANSCRIPTION_CACHE_VERSION,
        "backend_id": TRANSCRIPTION_BACKEND_ID,
        "cache_key": result.cache_key,
        "candidates": [asdict(candidate) for candidate in result.candidates],
        "evidence_layers": layers,
    }
    temporary_manifest = folder / "manifest.json.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_manifest.replace(folder / "manifest.json")
    prune_transcription_cache(cache_root, keep_keys=(result.cache_key,))


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
) -> np.ndarray | None:
    if layer not in {"frame", "onset", "contour"}:
        return None
    try:
        path = _cache_folder(str(cache_key), Path(cache_root)) / f"{layer}.npy"
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError):
        return None


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


def transcribe_reference_audio(
    audio_path: Path | str,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    *,
    cache_root: Path = TRANSCRIPTION_CACHE_DIR,
) -> TranscriptionResult:
    """Transcribe one local reference file into non-authoritative candidates."""
    path = Path(audio_path).resolve()
    if not path.is_file():
        raise TranscriptionError(f"参考音频不存在：{path}")
    cache_root = Path(cache_root)
    cached = _load_cached_result(path, cache_root)
    if cached is not None:
        _cancel_if_requested(cancelled)
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
        overlapping_frames = 30
        overlap_len = overlapping_frames * inference.FFT_HOP
        hop_size = inference.AUDIO_N_SAMPLES - overlap_len
        output: dict[str, list[np.ndarray]] = {
            "note": [],
            "onset": [],
            "contour": [],
        }
        original_length = 0
        for index, (windowed, _window_time, original_length) in enumerate(
            inference.get_audio_input(str(path), overlap_len, hop_size)
        ):
            _cancel_if_requested(cancelled)
            for key, value in model.predict(windowed).items():
                output[key].append(value)
            if progress and original_length:
                total = max(
                    1,
                    (original_length + overlap_len + hop_size - 1) // hop_size,
                )
                progress(min(90, 5 + round(85 * (index + 1) / total)))
        _cancel_if_requested(cancelled)
        if not original_length or not output["note"]:
            raise TranscriptionError("参考音频中没有可分析的音频帧")
        model_output = {
            key: inference.unwrap_output(
                np.concatenate(values),
                original_length,
                overlapping_frames,
            )
            for key, values in output.items()
        }
        if progress:
            progress(94)
        min_note_len = int(
            np.round(
                127.7
                / 1000
                * (inference.AUDIO_SAMPLE_RATE / inference.FFT_HOP)
            )
        )
        midi_data, note_events = note_creation.model_output_to_notes(
            model_output,
            onset_thresh=ONSET_THRESHOLD,
            frame_thresh=FRAME_THRESHOLD,
            min_note_len=min_note_len,
            min_freq=None,
            max_freq=None,
            multiple_pitch_bends=False,
            melodia_trick=True,
            midi_tempo=120,
        )
        _cancel_if_requested(cancelled)
        cache_key = transcription_cache_key(path)
        result = TranscriptionResult(
            _candidates_from_basic_pitch(midi_data, note_events),
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
        )
        _write_cached_result(result, model_output, cache_root)
        if progress:
            progress(100)
        return result
    except TranscriptionCancelled:
        raise
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"扒谱分析失败：{exc}") from exc
    finally:
        _INFERENCE_LOCK.release()
