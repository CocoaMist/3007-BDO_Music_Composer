"""Optional ctypes boundary for the experimental original C++ mixer.

The module never loads a DLL at import time. Production remains on the Python
engine unless an explicit caller constructs :class:`NativeAudioCore`; this
keeps source launches and public packages deterministic while the differential
prototype is evaluated.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


NATIVE_AUDIO_ABI_VERSION = 1
NATIVE_AUDIO_DLL_NAME = "bdo_native_audio_core.dll"
CAPABILITY_BASIC_STEREO_MIX = 1 << 0
CAPABILITY_EXACT_FRAME_SCHEDULING = 1 << 1
CAPABILITY_SEEK = 1 << 2
CAPABILITY_SAMPLE_LOOP = 1 << 3
CAPABILITY_BOUNDED_VOICES = 1 << 4
CAPABILITY_VOICE_ENVELOPE = 1 << 5
CAPABILITY_ARTICULATION_ENVELOPE = 1 << 6
CAPABILITY_MASTER_LIMITER = 1 << 7
REQUIRED_NATIVE_AUDIO_CAPABILITIES = (
    CAPABILITY_BASIC_STEREO_MIX
    | CAPABILITY_EXACT_FRAME_SCHEDULING
    | CAPABILITY_SEEK
    | CAPABILITY_SAMPLE_LOOP
    | CAPABILITY_BOUNDED_VOICES
    | CAPABILITY_VOICE_ENVELOPE
    | CAPABILITY_ARTICULATION_ENVELOPE
    | CAPABILITY_MASTER_LIMITER
)


class NativeAudioCoreError(RuntimeError):
    """The optional native core is missing, incompatible, or rejected input."""


@dataclass(frozen=True, slots=True)
class NativePlaybackEventV1:
    frame: int
    sample_index: int
    ratio: float
    gain: float
    duration_frames: int
    loop_start_frame: int = -1
    loop_end_frame: int = -1


@dataclass(frozen=True, slots=True)
class NativePlaybackEventV2(NativePlaybackEventV1):
    """Add an explicit audible lifecycle without changing V1 call sites."""

    audible_frames: int = 0
    fade_in_frames: int = 0
    fade_out_frames: int = 0
    instrument_id: int = 0
    ntype: int = 0
    native_articulation: bool = False


def default_native_audio_library_path() -> Path:
    return Path(__file__).resolve().with_name(NATIVE_AUDIO_DLL_NAME)


def native_audio_core_available(path: str | Path | None = None) -> bool:
    return Path(path or default_native_audio_library_path()).is_file()


class NativeAudioCore:
    """Own one bounded native mixer through an ABI-versioned C interface."""

    def __init__(
        self,
        sample_rate: int,
        *,
        max_voices: int = 256,
        library_path: str | Path | None = None,
    ) -> None:
        path = Path(library_path or default_native_audio_library_path())
        if not path.is_file():
            raise NativeAudioCoreError(f"native audio library is missing: {path}")
        try:
            library = ctypes.CDLL(str(path))
        except OSError as exc:
            raise NativeAudioCoreError(f"cannot load native audio library: {exc}") from exc
        self._configure_api(library)
        if int(library.bdo_audio_abi_version()) != NATIVE_AUDIO_ABI_VERSION:
            raise NativeAudioCoreError("native audio ABI version mismatch")
        capabilities = int(library.bdo_audio_capabilities())
        if capabilities & REQUIRED_NATIVE_AUDIO_CAPABILITIES != REQUIRED_NATIVE_AUDIO_CAPABILITIES:
            raise NativeAudioCoreError("native audio capability mismatch")
        handle = library.bdo_audio_create(int(sample_rate), int(max_voices))
        if not handle:
            raise NativeAudioCoreError("native audio mixer allocation failed")
        self._library = library
        self._handle = ctypes.c_void_p(handle)
        self._samples: list[np.ndarray] = []
        self._capabilities = capabilities

    @staticmethod
    def _configure_api(library: ctypes.CDLL) -> None:
        library.bdo_audio_abi_version.restype = ctypes.c_uint32
        library.bdo_audio_capabilities.restype = ctypes.c_uint64
        library.bdo_audio_create.argtypes = (ctypes.c_int32, ctypes.c_int32)
        library.bdo_audio_create.restype = ctypes.c_void_p
        library.bdo_audio_destroy.argtypes = (ctypes.c_void_p,)
        library.bdo_audio_reset_plan.argtypes = (ctypes.c_void_p,)
        library.bdo_audio_reset_plan.restype = ctypes.c_int32
        library.bdo_audio_add_sample_f32_stereo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int64,
        )
        library.bdo_audio_add_sample_f32_stereo.restype = ctypes.c_int32
        library.bdo_audio_add_event_v1.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_int32,
            ctypes.c_double,
            ctypes.c_float,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
        )
        library.bdo_audio_add_event_v1.restype = ctypes.c_int32
        library.bdo_audio_add_event_v2.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_int32,
            ctypes.c_double,
            ctypes.c_float,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
        )
        library.bdo_audio_add_event_v2.restype = ctypes.c_int32
        library.bdo_audio_add_event_v3.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.c_int32,
            ctypes.c_double,
            ctypes.c_float,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int64,
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.c_int32,
        )
        library.bdo_audio_add_event_v3.restype = ctypes.c_int32
        library.bdo_audio_finalise_plan.argtypes = (ctypes.c_void_p,)
        library.bdo_audio_finalise_plan.restype = ctypes.c_int32
        library.bdo_audio_seek.argtypes = (ctypes.c_void_p, ctypes.c_int64)
        library.bdo_audio_seek.restype = ctypes.c_int32
        library.bdo_audio_render_f32_stereo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int32,
        )
        library.bdo_audio_render_f32_stereo.restype = ctypes.c_int32
        library.bdo_audio_position_frame.argtypes = (ctypes.c_void_p,)
        library.bdo_audio_position_frame.restype = ctypes.c_int64
        library.bdo_audio_active_voices.argtypes = (ctypes.c_void_p,)
        library.bdo_audio_active_voices.restype = ctypes.c_int32
        library.bdo_audio_voice_steals.argtypes = (ctypes.c_void_p,)
        library.bdo_audio_voice_steals.restype = ctypes.c_uint64

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._library.bdo_audio_destroy(handle)
            self._handle = None
            self._samples.clear()

    def __enter__(self) -> "NativeAudioCore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def load_plan(
        self,
        samples: Iterable[np.ndarray],
        events: Iterable[NativePlaybackEventV1 | NativePlaybackEventV2],
    ) -> None:
        if self._library.bdo_audio_reset_plan(self._handle) != 0:
            raise NativeAudioCoreError("native plan reset failed")
        retained: list[np.ndarray] = []
        for sample in samples:
            pcm = np.ascontiguousarray(sample, dtype=np.float32)
            if pcm.ndim != 2 or pcm.shape[1] != 2 or len(pcm) <= 1:
                raise NativeAudioCoreError("samples must be non-empty float32 stereo arrays")
            sample_index = self._library.bdo_audio_add_sample_f32_stereo(
                self._handle,
                pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                len(pcm),
            )
            if sample_index != len(retained):
                raise NativeAudioCoreError("native sample projection failed")
            retained.append(pcm)
        for event in events:
            audible_frames = int(
                getattr(event, "audible_frames", 0)
            ) or int(
                event.duration_frames
            )
            result = self._library.bdo_audio_add_event_v3(
                self._handle,
                int(event.frame),
                int(event.sample_index),
                float(event.ratio),
                float(event.gain),
                int(event.duration_frames),
                int(event.loop_start_frame),
                int(event.loop_end_frame),
                audible_frames,
                int(getattr(event, "fade_in_frames", 0)),
                int(getattr(event, "fade_out_frames", 0)),
                int(getattr(event, "instrument_id", 0)),
                int(getattr(event, "ntype", 0)),
                int(bool(getattr(event, "native_articulation", False))),
            )
            if result != 0:
                raise NativeAudioCoreError("native event projection failed")
        if self._library.bdo_audio_finalise_plan(self._handle) != 0:
            raise NativeAudioCoreError("native plan finalisation failed")
        self._samples = retained

    def load_prepared_events(
        self,
        events: Iterable[object],
        *,
        fade_in_frames: int = 0,
    ) -> None:
        """Project the production engine's already-prepared basic events.

        The prototype fails closed for semantics it does not yet implement;
        callers must never mistake this differential surface for a production
        fallback that silently drops effects or articulation behavior.
        """

        prepared = tuple(events)
        sample_indices: dict[int, int] = {}
        samples: list[np.ndarray] = []
        projected: list[NativePlaybackEventV1] = []
        for event in prepared:
            unsupported = (
                float(getattr(event, "reverb_send", 0.0)) != 0.0
                or float(getattr(event, "delay_send", 0.0)) != 0.0
                or float(getattr(event, "chorus_send", 0.0)) != 0.0
            )
            if unsupported:
                raise NativeAudioCoreError(
                    "prepared event requires unsupported effect-bus DSP"
                )
            sample = getattr(event, "sample", None)
            pcm = getattr(sample, "pcm", None)
            if pcm is None:
                raise NativeAudioCoreError("prepared event has no decoded PCM")
            audible_frames = int(getattr(event, "audible_frames", 0))
            if audible_frames <= 0:
                raise NativeAudioCoreError(
                    "prepared event has no explicit audible lifecycle"
                )
            identity = id(sample)
            sample_index = sample_indices.get(identity)
            if sample_index is None:
                sample_index = len(samples)
                sample_indices[identity] = sample_index
                samples.append(pcm)
            projected.append(NativePlaybackEventV2(
                frame=int(getattr(event, "frame", 0)),
                sample_index=sample_index,
                ratio=float(getattr(event, "ratio", 1.0)),
                gain=float(getattr(event, "gain", 1.0)),
                duration_frames=int(getattr(event, "duration_frames", 0)),
                loop_start_frame=int(getattr(event, "loop_start_frame", -1)),
                loop_end_frame=int(getattr(event, "loop_end_frame", -1)),
                audible_frames=audible_frames,
                fade_in_frames=max(0, int(fade_in_frames)),
                fade_out_frames=max(
                    0,
                    int(getattr(event, "fade_out_frames", 0)),
                ),
                instrument_id=int(getattr(event, "instrument_id", 0)),
                ntype=int(getattr(event, "ntype", 0)),
                native_articulation=bool(
                    getattr(event, "native_articulation", False)
                ),
            ))
        self.load_plan(samples, projected)

    def render(self, frames: int) -> np.ndarray:
        count = max(1, int(frames))
        output = np.empty((count, 2), dtype=np.float32)
        rendered = self._library.bdo_audio_render_f32_stereo(
            self._handle,
            output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            count,
        )
        if rendered != count:
            raise NativeAudioCoreError("native render failed")
        return output

    def seek(self, frame: int) -> None:
        if self._library.bdo_audio_seek(self._handle, int(frame)) != 0:
            raise NativeAudioCoreError("native seek failed")

    @property
    def position_frame(self) -> int:
        return int(self._library.bdo_audio_position_frame(self._handle))

    @property
    def active_voices(self) -> int:
        return int(self._library.bdo_audio_active_voices(self._handle))

    @property
    def voice_steals(self) -> int:
        return int(self._library.bdo_audio_voice_steals(self._handle))

    @property
    def capabilities(self) -> int:
        return self._capabilities


__all__ = [
    "CAPABILITY_ARTICULATION_ENVELOPE",
    "CAPABILITY_MASTER_LIMITER",
    "CAPABILITY_VOICE_ENVELOPE",
    "NATIVE_AUDIO_ABI_VERSION",
    "REQUIRED_NATIVE_AUDIO_CAPABILITIES",
    "NativeAudioCore",
    "NativeAudioCoreError",
    "NativePlaybackEventV1",
    "NativePlaybackEventV2",
    "default_native_audio_library_path",
    "native_audio_core_available",
]
