"""In-process real-time BDO sample player for the PySide editor.

All filesystem work happens while a project is prepared.  A dedicated Qt audio
thread feeds the output device; its hot path only mixes pre-decoded NumPy
arrays and never creates a temporary WAV or starts a subprocess.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import wave
from collections import deque
from concurrent.futures import (
    CancelledError,
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from bdo_music_composer.audio.pcm_wav import (
    pcm_bytes_to_float32,
    stereo_pcm,
)
from PySide6.QtCore import QIODevice, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from bdo_music_composer.audio.bdo_audio_mixing import (
    apply_articulation_preview_in_place,
    articulation_preview_envelope,
    normalise_sample_loudness,
    preview_chord_intervals,
)
from bdo_music_composer.audio.bdo_audio_lifecycle import (
    INSTANCE_LIMIT_RELEASE_MS,
    InstanceTimelineItem,
    decide_instance_limit,
    detect_active_signal_frames,
    plan_instance_timeline,
    sample_output_frames,
    voice_lifecycle,
)
from bdo_music_composer.audio.bdo_instrument_samples import (
    BDO_BANK_BY_ID as BANK_BY_ID,
    MARNIAN_SYNTH_MODES,
    MARNIAN_SYNTH_WAVEFORM_BY_ID,
    WwiseContainerRotation,
    bank_for_instrument,
    marnian_synth_matrix,
    preview_has_native_articulation,
    preview_pitch_offset_semitones,
    preview_route_ntype,
    resolve_bdo_pitch,
    row_instance_limit,
    row_loop_points,
    row_release_ms,
    row_routes_ntype,
    row_volume_gain,
    sample_pitch_ratio,
    select_zone_variants,
)
from bdo_common.bdo_track_effects import (
    DEFAULT_TRACK_VOLUME,
    decode_track_effects,
    track_volume_preview_gain,
)
from bdo_midi.instruments import instrument_supports_composer_effects
from bdo_music_composer.audio.bdo_preview_effects import (
    PreviewEffectProcessor,
    PreviewEffectSettings,
    preview_send_gain,
)
from bdo_music_composer.editor.arrangement_clip import project_track_notes


PLAYBACK_ATTACK_MS = 3.0
AUDITION_CROSSFADE_MS = 18.0
AUDIO_BUFFER_MS = 128
# Keep ordinary piano-key audition at the former 72 ms target even though the
# sink has more physical headroom. Dense playback may use the extra queue space
# below; sparse playback therefore does not inherit the larger latency.
AUDIO_NOMINAL_QUEUE_MS = 72
AUDIO_REFILL_TARGET_RATIO = 0.75
AUDIO_PRESSURE_REFILL_TARGET_RATIO = 0.875
AUDIO_RENDER_PRESSURE_THRESHOLD = 0.45
AUDIO_RENDER_BLOCK_FRAMES = 2048
AUDIO_MIN_RENDER_FRAMES = 1024
# Per-voice interpolation has a fixed NumPy dispatch cost.  At 64 simultaneous
# voices the 1024-frame refill quantum already approaches the device budget on
# typical desktop CPUs, while the 2048-frame ceiling remains well inside the
# dense queue reserve. Amortise that overhead before it becomes an underrun
# instead of waiting until the hard 128-voice stress case.
DENSE_REFILL_VOICE_THRESHOLD = 64
WAV_DECODE_CHUNK_FRAMES = 64 * 1024
PRELOAD_CANCEL_POLL_SECONDS = 0.025
MASTER_TARGET_PEAK = 0.90
MASTER_ATTACK_MS = 3.0
MASTER_RELEASE_MS = 240.0
MAX_VOICES = 256
SOFT_VOICE_LIMIT = 224
VOICE_STEAL_RELEASE_MS = INSTANCE_LIMIT_RELEASE_MS
TRACK_METER_RENDER_INTERVAL = 4
# Rendering strictly equivalent linear voices once removes repeated NumPy
# interpolation dispatch without changing the logical voice pool.  Below this
# size the small grouping table costs more than it saves.
EQUIVALENT_VOICE_GROUP_THRESHOLD = 112
# Effect routing makes repeated interpolation more expensive, while weighted
# Aux aggregation remains exactly linear. Probe earlier for effect-enabled
# projects once they reach the same density that activates larger refills.
EQUIVALENT_EFFECT_VOICE_GROUP_THRESHOLD = 64
# Different pitches routed to the same Wwise source are much more common than
# exactly duplicated voices in real multitrack projects.  Interpolate a small,
# fixed-size tile together when every member is on the simple linear path.  The
# tile is deliberately bounded: callback memory remains independent of the
# project voice count and lifecycle/instance-limit state stays per voice.
LINEAR_VOICE_BATCH_SIZE = 8
LINEAR_VOICE_BATCH_THRESHOLD = 4
LINEAR_VOICE_BUCKET_SLOTS = 512
# Packing a normal project's decoded samples into one immutable arena lets a
# fixed interpolation tile gather unrelated Wwise sources in one NumPy call.
# The copy happens during preload and is deliberately capped so a very large
# user sample pack cannot create an unbounded transient memory spike.
SAMPLE_ARENA_MAX_BYTES = 192 * 1024 * 1024


class AudioEngineError(RuntimeError):
    pass


class _LoadCancelled(Exception):
    """Internal cooperative-cancellation signal for abandoned preload work."""


def choose_output_audio_format(device: Any) -> QAudioFormat:
    """Prefer the native 36 kHz game-sample rate, with safe fallbacks."""

    for sample_rate in (36_000, 48_000):
        candidate = QAudioFormat()
        candidate.setSampleRate(sample_rate)
        candidate.setChannelCount(2)
        candidate.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if device.isFormatSupported(candidate):
            return candidate

    preferred = device.preferredFormat()
    if (
        preferred.channelCount() != 2
        or preferred.sampleFormat()
        not in {
            QAudioFormat.SampleFormat.Int16,
            QAudioFormat.SampleFormat.Float,
        }
    ):
        raise AudioEngineError(
            "音频设备既不支持 36/48 kHz 双声道 Int16，"
            "首选格式也不是双声道 Int16/Float PCM"
        )
    return preferred


@lru_cache(maxsize=4)
def _cached_mapping_payload(
    path_string: str,
    modified_ns: int,
    size: int,
) -> dict:
    """Parse one immutable mapping revision outside the audio callback."""
    del modified_ns, size
    return json.loads(Path(path_string).read_text(encoding="utf-8"))


@dataclass
class AudioStatus:
    state: str = "stopped"
    position_ms: float = 0.0
    duration_ms: float = 0.0
    sample_rate: int = 0
    buffer_frames: int = 0
    cache_bytes: int = 0
    cache_misses: int = 0
    preload_loaded: int = 0
    preload_total: int = 0
    preload_progress: float = 0.0
    underruns: int = 0
    render_p95_ms: float = 0.0
    render_max_ms: float = 0.0
    render_p95_load: float = 0.0
    active_voices: int = 0
    voice_steals: int = 0
    master_gain: float = 1.0
    unverified: list[str] = field(default_factory=list)
    track_levels: dict[int, float] = field(default_factory=dict)


@dataclass
class _Sample:
    pcm: np.ndarray
    rate: int
    frames: int
    active_frames: int = 0
    arena_offset: int = -1
    arena: np.ndarray | None = field(default=None, repr=False, compare=False)


@dataclass
class _Event:
    frame: int
    sample: _Sample
    ratio: float
    gain: float
    duration_frames: int = 0
    instrument_id: int = 0
    ntype: int = 0
    track_slot: int = -1
    track_id: int = -1
    audible_frames: int = 0
    fade_out_frames: int = 0
    native_articulation: bool = False
    native_sample_route: bool = False
    loop_start_frame: int = 0
    loop_end_frame: int = 0
    instance_group_id: int = -1
    max_instances: int = 0
    kill_newest: bool = False
    instance_limit_global: bool = False
    reverb_send: float = 0.0
    delay_send: float = 0.0
    chorus_send: float = 0.0
    reverb_time: int = 0
    delay_feedback: int = 0
    chorus_feedback: int = 0
    chorus_lfo_depth: int = 0
    chorus_lfo_frequency: int = 0


@dataclass
class _Voice:
    sample: _Sample
    position: float
    ratio: float
    gain: float
    duration_frames: int = 0
    instrument_id: int = 0
    ntype: int = 0
    age_frames: int = 0
    track_slot: int = -1
    fade_in_frames: int = 0
    release_start_age: int = -1
    release_frames: int = 0
    audible_frames: int = 0
    fade_out_frames: int = 0
    native_articulation: bool = False
    render_start_offset: int = 0
    native_sample_route: bool = False
    loop_start_frame: int = 0
    loop_end_frame: int = 0
    instance_group_id: int = -1
    instance_scope_id: int = -1
    start_frame: int = 0
    reverb_send: float = 0.0
    delay_send: float = 0.0
    chorus_send: float = 0.0
    equivalent_probe_key: tuple[int, int, float, int, bool] = field(
        default_factory=tuple,
        repr=False,
        compare=False,
    )


OUTPUT_LIMIT_THRESHOLD = 0.95


def soft_limit_in_place(
    audio: np.ndarray,
    threshold: float = OUTPUT_LIMIT_THRESHOLD,
    *,
    magnitude: np.ndarray | None = None,
    denominator: np.ndarray | None = None,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Protect the device output from harsh clipping while leaving normal levels untouched."""
    if audio.size == 0:
        return audio
    if (
        magnitude is None
        or denominator is None
        or mask is None
        or magnitude.shape != audio.shape
        or denominator.shape != audio.shape
        or mask.shape != audio.shape
    ):
        magnitude = np.empty_like(audio, dtype=np.float32)
        denominator = np.empty_like(audio, dtype=np.float32)
        mask = np.empty(audio.shape, dtype=np.bool_)
    np.abs(audio, out=magnitude)
    np.greater(magnitude, threshold, out=mask)
    if bool(np.any(mask)):
        np.subtract(magnitude, threshold, out=magnitude, where=mask)
        np.divide(
            magnitude,
            max(1.0e-6, 1.0 - threshold),
            out=denominator,
            where=mask,
        )
        np.add(denominator, 1.0, out=denominator, where=mask)
        np.divide(
            magnitude,
            denominator,
            out=magnitude,
            where=mask,
        )
        np.add(magnitude, threshold, out=magnitude, where=mask)
        np.copysign(magnitude, audio, out=magnitude)
        np.copyto(audio, magnitude, where=mask)
    return audio


def select_wwise_zone(
    banks: dict[str, list[dict]], instrument_id: int, pitch: int, velocity: int, ntype: int = 0,
    synth_mode: str = "basic",
    variant_index: int = 0,
) -> tuple[str, dict] | None:
    """Select the Wwise zone used by the Python preview player."""
    selected = select_wwise_zone_variants(
        banks,
        instrument_id,
        pitch,
        velocity,
        ntype,
        synth_mode,
    )
    if not selected:
        return None
    bank, variants = selected
    return bank, variants[int(variant_index) % len(variants)]


def select_wwise_zone_variants(
    banks: dict[str, list[dict]],
    instrument_id: int,
    pitch: int,
    velocity: int,
    ntype: int = 0,
    synth_mode: str = "basic",
) -> tuple[str, tuple[dict, ...]] | None:
    """Resolve the game Event and MIDI zone before container rotation."""
    bank = bank_for_instrument(instrument_id, synth_mode)
    if not bank or bank not in banks:
        return None
    route_ntype = preview_route_ntype(instrument_id, ntype)
    resolved_pitch = resolve_bdo_pitch(
        instrument_id,
        pitch,
        ntype,
    )
    variants = select_zone_variants(
        banks[bank],
        resolved_pitch,
        velocity,
        route_ntype,
        bank=bank,
    )
    if not variants:
        return None
    return bank, variants


class _AudioOutputWorker(QObject):
    """Owns QAudioSink and mixing cadence outside the GUI thread."""

    def __init__(
        self,
        engine: "BdoRealtimeAudioEngine",
        *,
        render_block_frames: int = AUDIO_RENDER_BLOCK_FRAMES,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.render_block_frames = max(1, int(render_block_frames))
        self.sink: QAudioSink | None = None
        self.output: QIODevice | None = None
        self.timer: QTimer | None = None
        self.target_frames = 0
        self.low_water_frames = 0
        self.pending_pcm = b""
        self.suspended = False
        self.resetting = False
        self.suppress_underrun_until_write = False

    @Slot()
    def open(self) -> None:
        try:
            device = QMediaDevices.defaultAudioOutput()
            if not device.id():
                raise AudioEngineError("没有可用的系统音频输出设备")
            audio_format = choose_output_audio_format(device)
            self.engine._set_output_format(audio_format)
            self.sink = QAudioSink(device, audio_format, self)
            # Keep enough headroom for Qt timer jitter without making piano-key
            # audition feel detached from the pointer. Voice hand-off happens
            # inside the mixer, so this queue is never reset for each key.
            self.sink.setBufferSize(max(
                self.engine._frame_bytes * self.render_block_frames,
                self.engine._sample_rate * self.engine._frame_bytes * AUDIO_BUFFER_MS // 1000,
            ))
            self.sink.stateChanged.connect(self._on_sink_state_changed)
            # QAudioSink may publish Idle immediately after start(), before
            # the first timer pump has supplied PCM. This is startup state,
            # not an underrun; clear the suppression on the first accepted
            # write just like the reset path does.
            self.suppress_underrun_until_write = True
            self.output = self.sink.start()
            if self.output is None:
                raise AudioEngineError("无法打开系统音频输出")
            self.suspended = False
            self.engine._complete_output_reset(
                self.engine._output_reset_snapshot()
            )
            self.timer = QTimer(self)
            self.engine._set_buffer_frames(self.sink.bufferSize() // self.engine._frame_bytes)
            self.target_frames = max(
                self.render_block_frames,
                min(
                    self.engine._buffer_frames,
                    round(
                        self.engine._sample_rate
                        * AUDIO_NOMINAL_QUEUE_MS
                        / 1000.0
                    ),
                ),
            )
            self.low_water_frames = max(
                0,
                self.target_frames - AUDIO_MIN_RENDER_FRAMES,
            )
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.setInterval(2)
            self.timer.timeout.connect(self.pump)
            self.timer.start()
        except Exception as exc:
            self.engine.last_error = str(exc)
        finally:
            self.engine._output_ready.set()

    @Slot()
    def close(self) -> None:
        if self.timer:
            self.timer.stop()
        self.pending_pcm = b""
        if self.sink:
            self.sink.stop()
        self.engine._set_output_latency_frames(0)
        self.thread().quit()

    @Slot()
    def suspend_output(self) -> None:
        """Freeze the device queue and the already-rendered pending PCM."""
        if self.sink is not None and not self.suspended:
            self.sink.suspend()
        self.suspended = True

    @Slot()
    def resume_output(self) -> None:
        """Continue the preserved device queue without retriggering voices."""
        if self.sink is None:
            return
        if self.suspended:
            self.sink.resume()
            self.suspended = False
        self.pump()

    @Slot()
    def reset_output(self) -> None:
        """Discard stale queued PCM for stop-like operations and seeking."""
        reset_serial = self.engine._output_reset_snapshot()
        self.pending_pcm = b""
        self.engine._set_output_latency_frames(0)
        if self.sink is None:
            self.output = None
            self.engine._complete_output_reset(reset_serial)
            self.suspended = not self.engine._playing
            return
        self.resetting = True
        self.suppress_underrun_until_write = True
        self.sink.reset()
        self.output = self.sink.start()
        if self.output is None:
            self.engine.last_error = "无法重新打开系统音频输出"
            self.engine._stop_after_output_error()
            self.engine._complete_output_reset(reset_serial)
            self.resetting = False
            return
        self.engine._complete_output_reset(reset_serial)
        self.suspended = not self.engine._playing
        if self.suspended:
            self.sink.suspend()
        self.resetting = False

    def _write_pending(self) -> bool:
        """Flush rendered PCM completely before advancing the mixer timeline."""
        if not self.pending_pcm or self.output is None:
            return not self.pending_pcm
        written = int(self.output.write(self.pending_pcm))
        if written < 0:
            self.engine.last_error = "系统音频输出写入失败"
            self.engine._stop_after_output_error()
            return False
        if written:
            self.pending_pcm = self.pending_pcm[written:]
            self.suppress_underrun_until_write = False
        return not self.pending_pcm

    def _refill_frame_count(self, free_frames: int) -> int:
        free = max(0, int(free_frames))
        queued = max(0, self.engine._buffer_frames - free)
        active_voices, render_load, underruns = (
            self.engine._render_pressure_snapshot()
        )
        target_frames = self.target_frames
        low_water_frames = self.low_water_frames
        if active_voices >= DENSE_REFILL_VOICE_THRESHOLD:
            # Do not enlarge sparse audition latency.  Once the interpolation
            # pool is dense, use the physical 128 ms sink headroom so a single
            # scheduler/OS spike cannot drain the queue while a block renders.
            target_ratio = (
                AUDIO_PRESSURE_REFILL_TARGET_RATIO
                if render_load >= AUDIO_RENDER_PRESSURE_THRESHOLD or underruns
                else AUDIO_REFILL_TARGET_RATIO
            )
            target_frames = max(
                target_frames,
                round(
                    self.engine._buffer_frames
                    * target_ratio
                ),
            )
            low_water_frames = max(
                low_water_frames,
                target_frames - AUDIO_MIN_RENDER_FRAMES,
            )
        if queued > low_water_frames:
            return 0
        needed = max(0, target_frames - queued)
        minimum = (
            self.render_block_frames
            if active_voices >= DENSE_REFILL_VOICE_THRESHOLD
            else AUDIO_MIN_RENDER_FRAMES
        )
        return min(
            self.render_block_frames,
            max(minimum, needed),
            free,
        )

    def _publish_output_latency(self) -> None:
        """Expose frames rendered ahead of the device presentation head."""

        if self.sink is None:
            self.engine._set_output_latency_frames(0)
            return
        bytes_free = getattr(self.sink, "bytesFree", None)
        if not callable(bytes_free):
            # Lightweight lifecycle tests and a backend being torn down may
            # expose only the state/reset surface, not queue telemetry.
            return
        free_frames = max(0, bytes_free()) // self.engine._frame_bytes
        queued_frames = max(0, self.engine._buffer_frames - free_frames)
        pending_frames = len(self.pending_pcm) // self.engine._frame_bytes
        self.engine._set_output_latency_frames(
            queued_frames + pending_frames
        )

    @Slot()
    def pump(self) -> None:
        if (
            self.suspended
            or self.sink is None
            or self.output is None
        ):
            return
        self._publish_output_latency()
        if not self.engine._playing:
            return
        if self.sink.state() == QAudio.State.StoppedState:
            self.engine.last_error = f"系统音频输出已停止：{self.sink.error()}"
            self.engine._stop_after_output_error()
            return
        if not self._write_pending():
            self._publish_output_latency()
            return
        free_frames = max(0, self.sink.bytesFree()) // self.engine._frame_bytes
        # Refill from the low watermark to the high watermark.  Rendering the
        # tiny 2 ms timer deficit for every voice costs more CPU than the audio
        # it produces; a minimum quantum amortises the per-voice NumPy calls.
        frames = self._refill_frame_count(free_frames)
        if frames:
            self.pending_pcm = self.engine._read_pcm(frames * self.engine._frame_bytes)
            self._write_pending()
        self._publish_output_latency()

    @Slot(QAudio.State)
    def _on_sink_state_changed(self, state: QAudio.State) -> None:
        if (
            not self.resetting
            and not self.suppress_underrun_until_write
            and state in {QAudio.State.IdleState, QAudio.State.StoppedState}
            and self.engine._playing
        ):
            self.engine._record_underrun()


class BdoRealtimeAudioEngine(QObject):
    """Editable Python module that powers BDO real-time editor preview."""

    output_stop_requested = Signal()
    output_suspend_requested = Signal()
    output_resume_requested = Signal()
    output_reset_requested = Signal()

    def __init__(self, parent: QObject | None, source_config: dict[str, str]) -> None:
        super().__init__(parent)
        self.source_config = dict(source_config)
        self._lock = threading.RLock()
        self._events: list[_Event] = []
        self._event_frames = np.empty(0, dtype=np.int64)
        self._max_event_tail_frames = 0
        self._voices: list[_Voice] = []
        self._last_voice_prune_frame: int | None = None
        self._event_index = 0
        self._frame = 0
        self._duration_frames = 0
        self._playing = False
        # Transport state cannot be inferred from ``_events``: a stopped engine
        # intentionally retains its prepared events so Play can start again.
        self._paused = False
        self._cache_bytes = 0
        self._preload_loaded = 0
        self._preload_total = 0
        self._load_generation = 0
        self._buffer_frames = 0
        # Mixer frames are produced ahead of the actual device presentation
        # head. UI playheads subtract this bounded queue so dense multitrack
        # playback follows what the user hears instead of the refill cursor.
        self._output_latency_frames = 0
        self._underruns = 0
        self._voice_steals = 0
        self._render_times_ms: deque[float] = deque(maxlen=240)
        self._render_loads: deque[float] = deque(maxlen=240)
        self._unverified: list[str] = []
        self._cache: dict[tuple[str, int], _Sample] = {}
        self._output_thread: QThread | None = None
        self._output_worker: _AudioOutputWorker | None = None
        self._output_ready = threading.Event()
        self._output_reset_serial = 0
        self._output_reset_completed_serial = 0
        # One coordinator preserves project ordering; independent WAV reads and
        # float conversion run in a bounded pool so a cold cache no longer
        # stalls on hundreds of serial disk reads.
        self._decode_workers = min(8, max(4, (os.cpu_count() or 4) // 2))
        self._executor_lock = threading.Lock()
        self._loader: ThreadPoolExecutor | None = None
        self._decode_pool: ThreadPoolExecutor | None = None
        self._load_future: Future[tuple[list[_Event], dict[tuple[str, int], _Sample], int, list[str], int]] | None = None
        self._load_cancel_event: threading.Event | None = None
        self._format: QAudioFormat | None = None
        self._sample_rate = 48_000
        self._frame_bytes = 4
        self._mix_buffer = np.empty((0, 2), dtype=np.float32)
        self._group_mix_buffer = np.empty((0, 2), dtype=np.float32)
        self._effect_reverb_input = np.empty((0, 2), dtype=np.float32)
        self._effect_delay_input = np.empty((0, 2), dtype=np.float32)
        self._effect_chorus_input = np.empty((0, 2), dtype=np.float32)
        self._effect_route_scratch = np.empty((0, 2), dtype=np.float32)
        self._preview_effects = PreviewEffectProcessor(self._sample_rate)
        self._timeline_buffer = np.empty(0, dtype=np.float32)
        self._voice_a = np.empty((0, 2), dtype=np.float32)
        self._voice_b = np.empty((0, 2), dtype=np.float32)
        self._voice_positions = np.empty(0, dtype=np.float32)
        self._voice_indices = np.empty(0, dtype=np.intp)
        self._voice_loop_positions = np.empty(0, dtype=np.float32)
        self._voice_loop_mask = np.empty(0, dtype=np.bool_)
        self._batch_positions = np.empty((LINEAR_VOICE_BATCH_SIZE, 0), dtype=np.float32)
        self._batch_indices = np.empty((LINEAR_VOICE_BATCH_SIZE, 0), dtype=np.intp)
        self._batch_loop_positions = np.empty((LINEAR_VOICE_BATCH_SIZE, 0), dtype=np.float32)
        self._batch_loop_mask = np.empty((LINEAR_VOICE_BATCH_SIZE, 0), dtype=np.bool_)
        self._batch_a = np.empty((LINEAR_VOICE_BATCH_SIZE, 0, 2), dtype=np.float32)
        self._batch_b = np.empty((LINEAR_VOICE_BATCH_SIZE, 0, 2), dtype=np.float32)
        self._batch_starts = np.empty(LINEAR_VOICE_BATCH_SIZE, dtype=np.float32)
        self._batch_ratios = np.empty(LINEAR_VOICE_BATCH_SIZE, dtype=np.float32)
        self._batch_gains = np.empty(LINEAR_VOICE_BATCH_SIZE, dtype=np.float32)
        self._batch_arena_offsets = np.empty(
            LINEAR_VOICE_BATCH_SIZE,
            dtype=np.intp,
        )
        self._batch_last_indices = np.empty(
            LINEAR_VOICE_BATCH_SIZE,
            dtype=np.intp,
        )
        self._batch_voice_refs: list[_Voice | None] = [
            None
        ] * LINEAR_VOICE_BATCH_SIZE
        self._batch_bucket_samples: list[_Sample | None] = [
            None
        ] * LINEAR_VOICE_BUCKET_SLOTS
        self._batch_bucket_loop_starts = np.empty(
            LINEAR_VOICE_BUCKET_SLOTS,
            dtype=np.int32,
        )
        self._batch_bucket_loop_ends = np.empty(
            LINEAR_VOICE_BUCKET_SLOTS,
            dtype=np.int32,
        )
        self._batch_bucket_counts = np.zeros(
            LINEAR_VOICE_BUCKET_SLOTS,
            dtype=np.uint8,
        )
        self._batch_bucket_voices: list[_Voice | None] = [
            None
        ] * (LINEAR_VOICE_BUCKET_SLOTS * LINEAR_VOICE_BATCH_SIZE)
        self._batch_used_slots = np.empty(MAX_VOICES, dtype=np.intp)
        self._equivalent_probe_keys: set[
            tuple[int, int, float, int, bool]
        ] = set()
        self._master_envelope = np.empty(0, dtype=np.float32)
        self._articulation_envelope = np.empty(0, dtype=np.float32)
        self._articulation_scratch = np.empty(0, dtype=np.float32)
        self._limiter_magnitude = np.empty((0, 2), dtype=np.float32)
        self._limiter_denominator = np.empty((0, 2), dtype=np.float32)
        self._limiter_mask = np.empty((0, 2), dtype=np.bool_)
        self._pcm_i16 = np.empty((0, 2), dtype="<i2")
        self._master_gain = 1.0
        self._meter_render_phase = 0
        self._capture_track_peaks = True
        self._track_meter_ids: list[int] = []
        self._track_peaks = np.empty(0, dtype=np.float32)
        self._track_block_peaks = np.empty(0, dtype=np.float32)
        self._sample_arena: np.ndarray | None = None
        self.last_error = ""

    @staticmethod
    def _source_identity(source_config: dict[str, str]) -> tuple[str, str]:
        def normalized(key: str) -> str:
            value = str(source_config.get(key, "") or "").strip()
            return os.path.normcase(os.path.abspath(value)) if value else ""

        return normalized("sample_pack"), normalized("audio_root")

    def set_source_config(self, source_config: dict[str, str]) -> None:
        """Switch sources without reusing decoded samples from the old root."""

        next_config = dict(source_config)
        with self._lock:
            source_changed = self._source_identity(
                self.source_config
            ) != self._source_identity(next_config)
            self.source_config = next_config
            if source_changed:
                # Events and active voices retain direct references while a
                # stopped/replacement project starts with a clean source cache.
                self._cache = {}
                self._cache_bytes = 0
                self._sample_arena = None

    def available(self) -> bool:
        return bool(QMediaDevices.defaultAudioOutput().id())

    @property
    def status(self) -> AudioStatus:
        return self.get_status()

    def start(self) -> None:
        if self._output_thread and self._output_thread.isRunning():
            return
        self.last_error = ""
        self._output_ready.clear()
        self._output_thread = QThread()
        self._output_worker = _AudioOutputWorker(self)
        self._output_worker.moveToThread(self._output_thread)
        self._output_thread.started.connect(self._output_worker.open)
        self.output_stop_requested.connect(self._output_worker.close, Qt.ConnectionType.QueuedConnection)
        self.output_suspend_requested.connect(
            self._output_worker.suspend_output,
            Qt.ConnectionType.QueuedConnection,
        )
        self.output_resume_requested.connect(
            self._output_worker.resume_output,
            Qt.ConnectionType.QueuedConnection,
        )
        self.output_reset_requested.connect(
            self._output_worker.reset_output,
            Qt.ConnectionType.QueuedConnection,
        )
        self._output_thread.finished.connect(self._output_worker.deleteLater)
        self._output_thread.start()
        if not self._output_ready.wait(3.0):
            self.stop()
            raise AudioEngineError("音频输出线程启动超时")
        if self.last_error:
            self.stop()
            raise AudioEngineError(self.last_error)

    def _set_output_format(self, audio_format: QAudioFormat) -> None:
        with self._lock:
            self._format = audio_format
            self._sample_rate = audio_format.sampleRate()
            self._frame_bytes = 8 if audio_format.sampleFormat() == QAudioFormat.SampleFormat.Float else 4
            previous_effects = self._preview_effects
            self._preview_effects = PreviewEffectProcessor(self._sample_rate)
            self._preview_effects.configure(
                previous_effects.settings,
                reverb_send=previous_effects.reverb_enabled,
                delay_send=previous_effects.delay_enabled,
                chorus_send=previous_effects.chorus_enabled,
            )
            # The worker never requests more than this quantum. Allocate the
            # fixed mixer tiles while opening the device, not on the first
            # audible callback where allocator jitter can clip the attack.
            self._ensure_render_buffers(AUDIO_RENDER_BLOCK_FRAMES)

    def _set_buffer_frames(self, frames: int) -> None:
        with self._lock:
            self._buffer_frames = max(0, frames)

    def _set_output_latency_frames(self, frames: int) -> None:
        with self._lock:
            self._output_latency_frames = max(0, int(frames))

    def _record_underrun(self) -> None:
        with self._lock:
            self._underruns += 1

    def _active_voice_count_snapshot(self) -> int:
        """Return the bounded pool size without racing GUI-thread transport calls."""
        with self._lock:
            return len(self._voices)

    def _render_pressure_snapshot(self) -> tuple[int, float, int]:
        """Snapshot bounded queue inputs under the transport lock."""

        with self._lock:
            return (
                len(self._voices),
                float(self._render_loads[-1]) if self._render_loads else 0.0,
                int(self._underruns),
            )

    def _stop_after_output_error(self) -> None:
        """Publish a terminal transport state from the audio worker thread."""
        with self._lock:
            self._playing = False
            self._paused = False

    def _mark_output_reset_pending_locked(self) -> None:
        self._output_reset_serial += 1

    def _output_reset_snapshot(self) -> int:
        with self._lock:
            return self._output_reset_serial

    def _complete_output_reset(self, serial: int) -> None:
        with self._lock:
            self._output_reset_completed_serial = max(
                self._output_reset_completed_serial,
                int(serial),
            )

    def stop(self) -> None:
        self.cancel_loading()
        with self._lock:
            self._playing = False
            self._paused = False
            self._voices.clear()
            self._last_voice_prune_frame = None
            self._frame = 0
            self._output_latency_frames = 0
            self._event_index = 0
            self._master_gain = 1.0
            self._track_peaks.fill(0.0)
            self._track_block_peaks.fill(0.0)
        if self._output_thread and self._output_thread.isRunning():
            self.output_stop_requested.emit()
            self._output_thread.wait(1000)
        self._output_worker = None
        self._output_thread = None
        # ``stop`` is also the final lifecycle hook used by the main window.
        # Pools are recreated lazily, so stopping releases their threads without
        # preventing this engine instance from being played again.
        self._shutdown_preload_executors()

    def _ensure_preload_executors(
        self,
    ) -> tuple[ThreadPoolExecutor, ThreadPoolExecutor]:
        """Return live preload pools, recreating them after a previous stop."""
        with self._executor_lock:
            if self._loader is None:
                self._loader = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="bdo-project-loader",
                )
            if self._decode_pool is None:
                self._decode_pool = ThreadPoolExecutor(
                    max_workers=self._decode_workers,
                    thread_name_prefix="bdo-wav-cache",
                )
            return self._loader, self._decode_pool

    def _shutdown_preload_executors(self) -> None:
        """Release preload threads without waiting on cooperatively cancelled I/O."""
        with self._executor_lock:
            loader, decode_pool = self._loader, self._decode_pool
            self._loader = None
            self._decode_pool = None
        if loader is not None:
            loader.shutdown(wait=False, cancel_futures=True)
        if decode_pool is not None:
            decode_pool.shutdown(wait=False, cancel_futures=True)

    def clear_playback(self) -> None:
        """Silence and invalidate current material without reopening the audio device."""
        self.cancel_loading()
        with self._lock:
            self._playing = False
            self._paused = False
            self._events = []
            self._event_frames = np.empty(0, dtype=np.int64)
            self._max_event_tail_frames = 0
            self._voices.clear()
            self._last_voice_prune_frame = None
            self._event_index = 0
            self._frame = 0
            self._output_latency_frames = 0
            self._duration_frames = 0
            self._master_gain = 1.0
            self._voice_steals = 0
            self._render_times_ms.clear()
            self._render_loads.clear()
            self._track_meter_ids = []
            self._track_peaks = np.empty(0, dtype=np.float32)
            self._track_block_peaks = np.empty(0, dtype=np.float32)
            self._preview_effects.reset()
            self._mark_output_reset_pending_locked()
        if self._output_thread and self._output_thread.isRunning():
            self.output_reset_requested.emit()
    def load_project(
        self,
        tracks: list[Any],
        map_path: str | Path,
        start_ms: float,
        reverb: int = 0,
        delay: int = 0,
        chorus: tuple[int, int, int] | None = None,
        cache_limit_bytes: int = 768 * 1024 * 1024,
    ) -> dict[str, Any]:
        self.start()
        self.cancel_loading()
        self._ensure_preload_executors()
        prepared = self._prepare_project(
            tracks, map_path, start_ms, reverb, delay, chorus, cache_limit_bytes
        )
        return self._commit_project(*prepared, start_ms=start_ms)

    def load_project_async(
        self,
        tracks: list[Any],
        map_path: str | Path,
        start_ms: float,
        reverb: int = 0,
        delay: int = 0,
        chorus: tuple[int, int, int] | None = None,
        cache_limit_bytes: int = 768 * 1024 * 1024,
    ) -> None:
        """Begin a coordinated, multi-thread WAV cache preload off the GUI."""
        self.start()
        with self._lock:
            previous_cancel = self._load_cancel_event
            previous_future = self._load_future
            if previous_cancel is not None:
                previous_cancel.set()
            self._load_generation += 1
            generation = self._load_generation
            cancel_event = threading.Event()
            self._load_cancel_event = cancel_event
            self._preload_loaded = 0
            self._preload_total = 0
        if previous_future is not None and not previous_future.done():
            previous_future.cancel()
        loader, _decode_pool = self._ensure_preload_executors()
        future = loader.submit(
            self._prepare_project,
            list(tracks), map_path, start_ms, reverb, delay, chorus, cache_limit_bytes,
            generation, cancel_event,
        )
        with self._lock:
            if generation == self._load_generation:
                self._load_future = future
            else:
                cancel_event.set()
                future.cancel()

    def load_procedural_project_async(
        self,
        tracks: list[Any],
        start_ms: float,
        reverb: int = 0,
        delay: int = 0,
        chorus: tuple[int, int, int] | None = None,
    ) -> None:
        """Preload a clearly labelled generic MIDI fallback off the GUI thread.

        This path is intentionally not a BDO timbre emulation.  It keeps pitch,
        timing, velocity, track volume, and basic articulation useful on a
        first run where private game samples are unavailable.
        """

        self.start()
        with self._lock:
            previous_cancel = self._load_cancel_event
            previous_future = self._load_future
            if previous_cancel is not None:
                previous_cancel.set()
            self._load_generation += 1
            generation = self._load_generation
            cancel_event = threading.Event()
            self._load_cancel_event = cancel_event
            self._preload_loaded = 0
            self._preload_total = 0
        if previous_future is not None and not previous_future.done():
            previous_future.cancel()
        loader, _decode_pool = self._ensure_preload_executors()
        future = loader.submit(
            self._prepare_procedural_project,
            list(tracks),
            start_ms,
            reverb,
            delay,
            chorus,
            generation,
            cancel_event,
        )
        with self._lock:
            if generation == self._load_generation:
                self._load_future = future
            else:
                cancel_event.set()
                future.cancel()

    def finish_loading(self, start_ms: float) -> dict[str, Any] | None:
        """Commit a completed asynchronous preload; returns ``None`` while loading."""
        future = self._load_future
        if future is None:
            return None
        if not future.done():
            return None
        with self._lock:
            if self._load_future is not future:
                return None
            self._load_future = None
            self._load_cancel_event = None
        try:
            prepared = future.result()
        except (CancelledError, _LoadCancelled):
            return None
        except AudioEngineError:
            raise
        except Exception as exc:
            raise AudioEngineError(f"游戏音源预取失败：{exc}") from exc
        return self._commit_project(*prepared, start_ms=start_ms)

    def finish_audition_loading(self) -> dict[str, Any] | None:
        """Hand a prepared key audition to the live mixer without stopping output.

        The previous key keeps sounding while its replacement is decoded. Once
        ready, old voices receive a short release and the new key a short attack;
        the device stream remains continuous, avoiding reset-induced gaps.
        """
        future = self._load_future
        if future is None or not future.done():
            return None
        with self._lock:
            if self._load_future is not future:
                return None
            self._load_future = None
            self._load_cancel_event = None
        try:
            events, cache, cache_bytes, unverified, duration = future.result()
        except (CancelledError, _LoadCancelled):
            return None
        except AudioEngineError:
            raise
        except Exception as exc:
            raise AudioEngineError(f"游戏音源预取失败：{exc}") from exc

        fade_frames = max(1, round(self._sample_rate * AUDITION_CROSSFADE_MS / 1000.0))
        with self._lock:
            self._last_voice_prune_frame = None
            for voice in self._voices:
                voice.release_start_age = voice.age_frames
                voice.release_frames = fade_frames

            self._events = events
            self._event_frames = np.fromiter(
                (event.frame for event in events), dtype=np.int64, count=len(events)
            )
            self._max_event_tail_frames = max(
                (self._event_audible_frames(event) for event in events),
                default=0,
            )
            self._event_index = 0
            self._frame = 0
            self._configure_preview_effects(events)
            self._duration_frames = max(
                duration + self._preview_effects.tail_frames(),
                fade_frames,
            )
            self._cache = cache
            self._cache_bytes = cache_bytes
            self._sample_arena = self._shared_sample_arena(cache)
            self._preload_loaded = self._preload_total
            self._unverified = unverified

            meter_slots = max((event.track_slot for event in events), default=-1) + 1
            self._track_meter_ids = [-1] * meter_slots
            for event in events:
                if event.track_slot >= 0:
                    self._track_meter_ids[event.track_slot] = event.track_id
            self._track_peaks = np.zeros(meter_slots, dtype=np.float32)
            self._track_block_peaks = np.zeros(meter_slots, dtype=np.float32)

            while self._event_index < len(events) and events[self._event_index].frame <= 0:
                self._start_event(events[self._event_index], fade_in_frames=fade_frames)
                self._event_index += 1
            self._playing = bool(self._voices or self._event_index < len(events))
            self._paused = False

        if self._playing and self._output_thread and self._output_thread.isRunning():
            self.output_resume_requested.emit()
        return {
            "events": len(events), "samples": len(cache),
            "cache_bytes": cache_bytes, "unverified": list(unverified),
            "duration_ms": self._duration_frames * 1000.0 / self._sample_rate,
        }

    def is_loading(self) -> bool:
        return bool(self._load_future and not self._load_future.done())

    def cancel_loading(self) -> None:
        """Invalidate an in-flight preload so its result can never be committed."""
        with self._lock:
            self._load_generation += 1
            future = self._load_future
            cancel_event = self._load_cancel_event
            self._load_future = None
            self._load_cancel_event = None
            self._preload_loaded = 0
            self._preload_total = 0
        if cancel_event is not None:
            cancel_event.set()
        if future is not None and not future.done():
            future.cancel()

    def _procedural_sample(
        self,
        instrument_id: int,
        *,
        percussion: bool,
        percussion_pitch: int = 60,
    ) -> _Sample:
        """Build one bounded immutable, license-clean fallback timbre.

        The renderer is deliberately deterministic and generated entirely in
        memory.  Instrument families use different harmonic/envelope profiles,
        while BDO drum pieces 48..64 receive distinct one-shot voices.  This is
        substantially more useful than the former four-wave oscillator, but it
        remains a generic preview rather than evidence of BDO game timbre.
        """

        rate = max(8_000, int(self._sample_rate))
        family = self._procedural_instrument_family(instrument_id)
        one_shot = percussion or family in {"piano", "pluck", "harp", "handpan"}
        duration_seconds = 1.4 if percussion else (2.0 if one_shot else 1.0)
        frames = max(2, round(rate * duration_seconds))
        time_axis = np.arange(frames, dtype=np.float32) / np.float32(rate)
        if percussion:
            pitch = max(0, min(127, int(percussion_pitch)))
            rng = np.random.default_rng(
                0xBD0000 + int(instrument_id) * 257 + pitch
            )
            noise = rng.standard_normal(frames).astype(np.float32)
            if instrument_id == 0x05 or pitch >= 61:
                # Deterministic high-passed noise gives cymbals and the upper
                # drum-set pieces a bright, short metallic wash.
                bright = noise - np.concatenate((noise[:1], noise[:-1]))
                envelope = np.exp(-time_axis * np.float32(5.2))
                mono = bright * envelope * np.float32(0.085)
            elif pitch <= 48:
                frequency = np.float32(58.0 + max(0, pitch - 35) * 1.5)
                phase = time_axis * frequency * np.float32(2.0 * math.pi)
                envelope = np.exp(-time_axis * np.float32(10.0))
                mono = (
                    np.sin(phase) * np.float32(0.22)
                    + noise * np.float32(0.025)
                ) * envelope
            elif pitch <= 51:
                phase = time_axis * np.float32(185.0 * 2.0 * math.pi)
                envelope = np.exp(-time_axis * np.float32(13.0))
                mono = (
                    noise * np.float32(0.13)
                    + np.sin(phase) * np.float32(0.055)
                ) * envelope
            else:
                frequency = np.float32(105.0 + (pitch - 52) * 15.0)
                phase = time_axis * frequency * np.float32(2.0 * math.pi)
                envelope = np.exp(-time_axis * np.float32(8.0))
                mono = (
                    np.sin(phase) * np.float32(0.17)
                    + np.sin(phase * np.float32(1.51)) * np.float32(0.045)
                    + noise * np.float32(0.018)
                ) * envelope
        else:
            radians = time_axis * np.float32(440.0 * 2.0 * math.pi)
            profiles: dict[str, tuple[tuple[float, ...], float, float]] = {
                "piano": ((1.0, 0.62, 0.34, 0.19, 0.10, 0.055), 0.006, 2.4),
                "pluck": ((1.0, 0.48, 0.31, 0.20, 0.12, 0.07), 0.003, 3.2),
                "harp": ((1.0, 0.38, 0.22, 0.12, 0.07), 0.004, 2.6),
                "handpan": ((1.0, 0.18, 0.36, 0.08, 0.16), 0.004, 1.8),
                "strings": ((1.0, 0.52, 0.30, 0.19, 0.11, 0.07), 0.055, 0.0),
                "woodwind": ((1.0, 0.13, 0.08, 0.035), 0.035, 0.0),
                "clarinet": ((1.0, 0.03, 0.31, 0.02, 0.12), 0.040, 0.0),
                "brass": ((1.0, 0.45, 0.25, 0.13, 0.07), 0.045, 0.0),
                "bass": ((1.0, 0.40, 0.18, 0.08), 0.018, 0.0),
                "synth": ((1.0, 0.50, 0.28, 0.16, 0.09), 0.018, 0.0),
            }
            partials, attack_seconds, decay_rate = profiles[family]
            mono = np.zeros(frames, dtype=np.float32)
            for harmonic, amplitude in enumerate(partials, start=1):
                phase_offset = np.float32(
                    (instrument_id % 7) * harmonic * 0.037
                )
                mono += np.sin(
                    radians * np.float32(harmonic) + phase_offset
                ) * np.float32(amplitude)
            if family == "synth":
                mono = np.tanh(mono * np.float32(1.35))
            if attack_seconds > 0.0:
                attack = np.minimum(
                    np.float32(1.0),
                    time_axis / np.float32(attack_seconds),
                )
                # A short cosine-shaped attack avoids clicks without allocating
                # or processing anything in the real-time callback.
                attack = np.sin(attack * np.float32(math.pi / 2.0))
                mono *= attack
            if decay_rate > 0.0:
                mono *= np.exp(-time_axis * np.float32(decay_rate))
            peak = max(1e-6, float(np.max(np.abs(mono))))
            mono *= np.float32(0.19 / peak)
        pcm = np.empty((frames, 2), dtype=np.float32)
        # Small fixed family-dependent stereo shading keeps the mix readable
        # without chorus state or callback allocations.
        stereo_bias = np.float32(((int(instrument_id) % 5) - 2) * 0.012)
        pcm[:, 0] = mono * (np.float32(1.0) - stereo_bias)
        pcm[:, 1] = mono * (np.float32(1.0) + stereo_bias)
        pcm.setflags(write=False)
        return _Sample(pcm=pcm, rate=rate, frames=frames, active_frames=frames)

    @staticmethod
    def _procedural_instrument_family(instrument_id: int) -> str:
        instrument = int(instrument_id)
        if instrument in {0x07, 0x11}:
            return "piano"
        if instrument in {0x00, 0x0A, 0x24, 0x25, 0x26}:
            return "pluck"
        if instrument in {0x06, 0x10}:
            return "harp"
        if instrument == 0x13:
            return "handpan"
        if instrument in {0x08, 0x12}:
            return "strings"
        if instrument in {0x01, 0x02, 0x0B}:
            return "woodwind"
        if instrument == 0x27:
            return "clarinet"
        if instrument == 0x28:
            return "brass"
        if instrument in {0x0E, 0x0F}:
            return "bass"
        return "synth"

    def _prepare_procedural_project(
        self,
        tracks: list[Any],
        start_ms: float,
        reverb: int,
        delay: int,
        chorus: tuple[int, int, int] | None,
        load_generation: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[_Event], dict[tuple[str, int], _Sample], int, list[str], int]:
        """Create generic waveforms and events without filesystem access."""

        del start_ms
        self._raise_if_preload_cancelled(cancel_event)
        cache: dict[tuple[str, int], _Sample] = {}
        events: list[_Event] = []
        duration = 0
        rate = max(8_000, int(self._sample_rate))
        release_frames = max(1, round(rate * 0.08))
        master_settings = PreviewEffectSettings.from_legacy(
            reverb,
            delay,
            chorus,
        )
        has_track_effect_sends = False
        for track_slot, track in enumerate(tracks):
            self._raise_if_preload_cancelled(cancel_event)
            instrument_id = int(getattr(track, "bdo_instrument_id", 0))
            percussion = bool(getattr(track, "is_percussion", False)) or (
                instrument_id in {0x04, 0x05, 0x0D}
            )
            family = self._procedural_instrument_family(instrument_id)
            melodic_key = ("procedural", instrument_id)
            sample = cache.get(melodic_key) if not percussion else None
            if not percussion and sample is None:
                sample = self._procedural_sample(
                    instrument_id, percussion=False
                )
                cache[melodic_key] = sample
            track_id = int(getattr(track, "track_id", track_slot))
            track_gain = track_volume_preview_gain(
                getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
            )
            if instrument_supports_composer_effects(instrument_id):
                try:
                    track_sends, _track_master = decode_track_effects(
                        getattr(track, "bdo_track_settings", (0,) * 8)
                    )
                    reverb_send = preview_send_gain(track_sends.reverb)
                    delay_send = preview_send_gain(track_sends.delay)
                    chorus_send = preview_send_gain(track_sends.chorus)
                except ValueError:
                    reverb_send = delay_send = chorus_send = 0.0
            else:
                # Preserve unsupported/imported bytes for export, but do not
                # claim that the game's beginner instruments route AuxSend.
                reverb_send = delay_send = chorus_send = 0.0
            has_track_effect_sends = has_track_effect_sends or any((
                reverb_send,
                delay_send,
                chorus_send,
            ))
            duration_scale = 1.0
            for note_index, note in enumerate(project_track_notes(track)):
                if note_index % 256 == 0:
                    self._raise_if_preload_cancelled(cancel_event)
                frame = round(
                    max(0.0, float(getattr(note, "start", 0.0)))
                    * rate
                    / 1000.0
                )
                note_duration = max(
                    1,
                    round(
                        max(1.0, float(getattr(note, "dur", 0.0)))
                        * max(0.01, duration_scale)
                        * rate
                        / 1000.0
                    ),
                )
                ntype = int(
                    getattr(note, "ntype", 0)
                    or getattr(track, "articulation_type", 0)
                    or 0
                )
                if percussion:
                    percussion_pitch = max(
                        0, min(127, int(getattr(note, "pitch", 60)))
                    )
                    percussion_key = (
                        "procedural",
                        0x10000 | (instrument_id << 8) | percussion_pitch,
                    )
                    sample = cache.get(percussion_key)
                    if sample is None:
                        sample = self._procedural_sample(
                            instrument_id,
                            percussion=True,
                            percussion_pitch=percussion_pitch,
                        )
                        cache[percussion_key] = sample
                    ratio = 1.0
                    audible_frames = max(
                        note_duration,
                        min(sample.frames, round(rate * 0.18)),
                    )
                    audible_frames = min(audible_frames, sample.frames)
                    fade_out_frames = min(release_frames, audible_frames)
                    loop_start = loop_end = 0
                else:
                    assert sample is not None
                    pitch = max(0, min(127, int(getattr(note, "pitch", 69))))
                    ratio = max(0.125, min(8.0, 2.0 ** ((pitch - 69) / 12.0)))
                    if family in {"piano", "pluck", "harp", "handpan"}:
                        audible_frames = min(
                            note_duration + release_frames,
                            max(1, round(sample.frames / ratio)),
                        )
                        loop_start = loop_end = 0
                    else:
                        audible_frames = note_duration + release_frames
                        loop_start = round(rate * 0.20)
                        loop_end = round(rate * 0.80)
                    fade_out_frames = release_frames
                velocity = max(
                    0,
                    min(127, round(float(getattr(note, "vel", 96)))),
                )
                events.append(_Event(
                    frame=frame,
                    sample=sample,
                    ratio=ratio,
                    gain=velocity / 127.0 * track_gain,
                    duration_frames=note_duration,
                    instrument_id=instrument_id,
                    ntype=ntype,
                    track_slot=track_slot,
                    track_id=track_id,
                    audible_frames=audible_frames,
                    fade_out_frames=fade_out_frames,
                    native_articulation=False,
                    native_sample_route=False,
                    loop_start_frame=loop_start,
                    loop_end_frame=loop_end,
                    reverb_send=reverb_send,
                    delay_send=delay_send,
                    chorus_send=chorus_send,
                    reverb_time=master_settings.reverb_time,
                    delay_feedback=master_settings.delay_feedback,
                    chorus_feedback=master_settings.chorus_feedback,
                    chorus_lfo_depth=master_settings.chorus_lfo_depth,
                    chorus_lfo_frequency=(
                        master_settings.chorus_lfo_frequency
                    ),
                ))
                duration = max(duration, frame + audible_frames)
        events.sort(key=lambda event: event.frame)
        cache_bytes = sum(sample.pcm.nbytes for sample in cache.values())
        if load_generation is not None:
            with self._lock:
                if load_generation == self._load_generation:
                    self._preload_total = len(cache)
                    self._preload_loaded = len(cache)
        unverified = [
            "generic MIDI fallback: not BDO game audio or verified game DSP"
        ]
        if has_track_effect_sends:
            unverified.append(
                "reverb/delay/chorus preview: bounded local approximation; "
                "not calibrated against game Wwise DSP"
            )
        return events, cache, cache_bytes, unverified, duration

    def _prepare_project(
        self,
        tracks: list[Any],
        map_path: str | Path,
        start_ms: float,
        reverb: int,
        delay: int,
        chorus: tuple[int, int, int] | None,
        cache_limit_bytes: int,
        load_generation: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[_Event], dict[tuple[str, int], _Sample], int, list[str], int]:
        self._raise_if_preload_cancelled(cancel_event)
        if cancel_event is None:
            self._ensure_preload_executors()
        mapping_file = Path(map_path).resolve()
        mapping_stat = mapping_file.stat()
        payload = _cached_mapping_payload(
            str(mapping_file),
            mapping_stat.st_mtime_ns,
            mapping_stat.st_size,
        )
        self._raise_if_preload_cancelled(cancel_event)
        banks: dict[str, list[dict]] = payload.get("banks", {})
        cache: dict[tuple[str, int], _Sample] = {}
        events: list[_Event] = []
        unverified: set[str] = set()
        has_track_effect_sends = False
        master_settings = PreviewEffectSettings.from_legacy(
            reverb,
            delay,
            chorus,
        )
        duration = 0
        # Resolve all note→zone relationships first.  Decoding is deduplicated
        # by Wwise source ID and happens concurrently below.
        resolved: list[
            tuple[
                Any, int, int, int, int, str, dict, tuple[str, int],
                float, int, int, float, float, float, float,
            ]
        ] = []
        selection_requests: list[
            tuple[
                float, int, int, Any, int, int, int, int, str,
                tuple[dict, ...], float, int, float, float, float, float,
            ]
        ] = []
        source_candidates: dict[
            tuple[str, int],
            tuple[Path, Path],
        ] = {}
        zone_cache: dict[
            tuple[int, str, int, int, int],
            tuple[str, tuple[dict, ...]] | None,
        ] = {}
        for track_slot, track in enumerate(tracks):
            self._raise_if_preload_cancelled(cancel_event)
            track_id = int(getattr(track, "track_id", track_slot))
            track_preview_gain = track_volume_preview_gain(
                getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
            )
            instrument_id = int(track.bdo_instrument_id)
            if instrument_supports_composer_effects(instrument_id):
                try:
                    track_sends, _track_master = decode_track_effects(
                        getattr(track, "bdo_track_settings", (0,) * 8)
                    )
                    reverb_send = preview_send_gain(track_sends.reverb)
                    delay_send = preview_send_gain(track_sends.delay)
                    chorus_send = preview_send_gain(track_sends.chorus)
                    has_track_effect_sends = has_track_effect_sends or any((
                        reverb_send,
                        delay_send,
                        chorus_send,
                    ))
                except ValueError:
                    reverb_send = delay_send = chorus_send = 0.0
                    unverified.add(
                        f"track {track_id}: invalid effect settings; preview ignored them"
                    )
            else:
                reverb_send = delay_send = chorus_send = 0.0
            synth_mode = str(getattr(track, "marnian_synth_mode", "basic") or "basic")
            bank = bank_for_instrument(instrument_id, synth_mode)
            if not bank or bank not in banks:
                unverified.add(f"0x{instrument_id:02x}: 未绑定已命名 BNK")
                continue
            if instrument_id in MARNIAN_SYNTH_WAVEFORM_BY_ID:
                unverified.add(
                    f"0x{instrument_id:02x}/{synth_mode}: provisional synth routing; game A/B required"
                )
            for note_index, note in enumerate(project_track_notes(track)):
                if note_index % 256 == 0:
                    self._raise_if_preload_cancelled(cancel_event)
                velocity = max(0, min(127, round(float(note.vel))))
                ntype = int(getattr(note, "ntype", 0) or track.articulation_type or 0)
                route_ntype = preview_route_ntype(instrument_id, ntype)
                pitch = resolve_bdo_pitch(
                    instrument_id,
                    int(note.pitch),
                    ntype,
                )
                zone_key = (instrument_id, synth_mode, int(note.pitch), velocity, ntype)
                if zone_key not in zone_cache:
                    zone_cache[zone_key] = select_wwise_zone_variants(
                        banks, instrument_id, int(note.pitch), velocity, ntype, synth_mode
                    )
                selected = zone_cache[zone_key]
                if not selected:
                    unverified.add(f"0x{instrument_id:02x}: pitch {pitch} velocity {velocity} 无 Wwise zone")
                    continue
                selected_bank, variants = selected
                selection_requests.append((
                    float(getattr(note, "start", 0.0)),
                    track_slot,
                    note_index,
                    note,
                    velocity,
                    pitch,
                    instrument_id,
                    ntype,
                    selected_bank,
                    variants,
                    float(getattr(track, "duration_scale", 1.0)),
                    track_id,
                    track_preview_gain,
                    reverb_send,
                    delay_send,
                    chorus_send,
                ))

        # Wwise random/sequence state is global to the container.  Resolve
        # variants in musical time order so simultaneous notes across tracks
        # cannot depend on the order in which the UI happens to store tracks.
        container_rotation = WwiseContainerRotation()
        for (
            _start,
            track_slot,
            _note_index,
            note,
            velocity,
            pitch,
            instrument_id,
            ntype,
            bank,
            variants,
            duration_scale,
            track_id,
            track_preview_gain,
            reverb_send,
            delay_send,
            chorus_send,
        ) in sorted(
            selection_requests,
            key=lambda item: (item[0], item[1], item[2]),
        ):
            row = container_rotation.choose(bank, variants)
            if row is None:
                continue
            route_ntype = preview_route_ntype(instrument_id, ntype)
            native_sample_route = row_routes_ntype(row, route_ntype)
            # Synth Events select native source layers, while their Wwise
            # modulators/filters remain approximate in the Python preview.
            native_articulation = preview_has_native_articulation(
                instrument_id,
                row,
                route_ntype,
            )
            if ntype not in (0, 99):
                if native_sample_route:
                    unverified.add(
                        f"0x{instrument_id:02x}/type {ntype}: "
                        "游戏 Event 采样路由已匹配；父级 Wwise 效果仍为近似"
                    )
                else:
                    unverified.add(
                        f"0x{instrument_id:02x}/type {ntype}: "
                        "无独立游戏 Event，使用延音采样与近似 DSP"
                    )
            key = (bank, int(row["source_id"]))
            if key not in source_candidates:
                source_candidates.setdefault(
                    key,
                    (
                        Path(row["wav_path"]),
                        Path(self.source_config["audio_root"])
                        / "乐器_WAV"
                        / bank
                        / f"{row['source_id']}.wav",
                    ),
                )
            resolved.append((
                note, velocity, pitch, instrument_id, ntype, bank, row, key,
                duration_scale, track_slot, track_id, track_preview_gain,
                reverb_send, delay_send, chorus_send,
            ))

        sources = {
            key: primary if primary.is_file() else fallback
            for key, (primary, fallback) in source_candidates.items()
        }
        with self._lock:
            cache.update({key: self._cache[key] for key in sources if key in self._cache})
        if load_generation is not None:
            with self._lock:
                if load_generation == self._load_generation:
                    self._preload_total = len(sources)
                    self._preload_loaded = len(cache)
        cache_bytes = sum(sample.pcm.nbytes for sample in cache.values())
        missing_sources = [(key, path) for key, path in sources.items() if key not in cache]
        futures: dict[tuple[str, int], Future[_Sample]] = {}
        next_source = 0
        completed = False

        def submit_until_full() -> None:
            nonlocal next_source
            while len(futures) < self._decode_workers and next_source < len(missing_sources):
                self._raise_if_preload_cancelled(cancel_event)
                key, path = missing_sources[next_source]
                next_source += 1
                with self._executor_lock:
                    decode_pool = self._decode_pool
                    if decode_pool is None:
                        raise _LoadCancelled()
                    if cancel_event is None:
                        futures[key] = decode_pool.submit(self._decode_wav, path)
                    else:
                        futures[key] = decode_pool.submit(
                            self._decode_wav,
                            path,
                            cancel_event,
                        )

        try:
            submit_until_full()
            # Consume in source order for deterministic errors and cache limits.
            # At most one worker-window is submitted, so abandoning a project
            # cannot leave hundreds of stale decodes ahead of the next request.
            for key, _path in missing_sources:
                future = futures[key]
                while True:
                    self._raise_if_preload_cancelled(cancel_event)
                    try:
                        sample = future.result(timeout=PRELOAD_CANCEL_POLL_SECONDS)
                        break
                    except FutureTimeoutError:
                        continue
                    except CancelledError as exc:
                        raise _LoadCancelled() from exc
                del futures[key]
                cache_bytes += sample.pcm.nbytes
                if cache_bytes > cache_limit_bytes:
                    raise AudioEngineError(f"项目预取样本超过 {cache_limit_bytes // 1024 // 1024} MiB 缓存上限")
                cache[key] = sample
                if load_generation is not None:
                    with self._lock:
                        if load_generation == self._load_generation:
                            self._preload_loaded += 1
                submit_until_full()
            completed = True
        finally:
            if not completed and cancel_event is not None:
                cancel_event.set()
            if not completed or (cancel_event is not None and cancel_event.is_set()):
                for future in futures.values():
                    future.cancel()

        self._raise_if_preload_cancelled(cancel_event)
        cache = self._pack_sample_cache(
            cache,
            cache_bytes,
            cancel_event=cancel_event,
        )
        for resolved_index, (
            note, velocity, pitch, _instrument_id, ntype, _bank, row, key,
            duration_scale, track_slot, track_id, track_preview_gain,
            reverb_send, delay_send, chorus_send,
        ) in enumerate(resolved):
            if resolved_index % 512 == 0:
                self._raise_if_preload_cancelled(cancel_event)
            sample = cache[key]
            ratio = (
                sample_pitch_ratio(row, pitch, bank=_bank)
                * sample.rate
                / self._sample_rate
            )
            frame = round(max(0.0, float(note.start)) * self._sample_rate / 1000.0)
            note_duration = max(
                1,
                round(
                    float(getattr(note, "dur", 0.0))
                    * duration_scale
                    * self._sample_rate / 1000.0
                ),
            )
            route_ntype = preview_route_ntype(
                _instrument_id,
                ntype,
            )
            native_sample_route = row_routes_ntype(row, route_ntype)
            native_articulation = preview_has_native_articulation(
                _instrument_id,
                row,
                route_ntype,
            )
            # Only legacy/fallback maps need the synthetic octave harmonic.
            # A native ntype-14 Event already selects the game's harmonic bank.
            preview_ratio = ratio * (
                2.0
                ** (
                    preview_pitch_offset_semitones(
                        ntype,
                        native_sample_route,
                    )
                    / 12.0
                )
            )
            loop_points = row_loop_points(row, sample.frames)
            active_source_frames = sample.active_frames or sample.frames
            lifecycle = voice_lifecycle(
                _instrument_id,
                ntype,
                note_duration,
                sample_output_frames(active_source_frames, preview_ratio),
                self._sample_rate,
                native_articulation=native_sample_route,
                sample_loops=loop_points is not None,
                release_ms=row_release_ms(row),
            )
            instance_limit = row_instance_limit(row)
            events.append(_Event(
                frame=frame,
                sample=sample,
                ratio=preview_ratio,
                gain=(
                    velocity
                    / 127.0
                    * track_preview_gain
                    * row_volume_gain(row)
                ),
                duration_frames=note_duration,
                instrument_id=_instrument_id,
                ntype=ntype,
                track_slot=track_slot,
                track_id=track_id,
                audible_frames=lifecycle.audible_frames,
                fade_out_frames=lifecycle.fade_out_frames,
                native_articulation=native_articulation,
                native_sample_route=native_sample_route,
                loop_start_frame=loop_points[0] if loop_points else 0,
                loop_end_frame=loop_points[1] if loop_points else 0,
                instance_group_id=(
                    instance_limit.group_id
                    if instance_limit.enforceable
                    else -1
                ),
                max_instances=(
                    instance_limit.max_instances
                    if instance_limit.enforceable
                    else 0
                ),
                kill_newest=instance_limit.kill_newest,
                instance_limit_global=instance_limit.global_scope,
                reverb_send=reverb_send,
                delay_send=delay_send,
                chorus_send=chorus_send,
                reverb_time=master_settings.reverb_time,
                delay_feedback=master_settings.delay_feedback,
                chorus_feedback=master_settings.chorus_feedback,
                chorus_lfo_depth=master_settings.chorus_lfo_depth,
                chorus_lfo_frequency=master_settings.chorus_lfo_frequency,
            ))
            duration = max(duration, frame + lifecycle.audible_frames)
        if has_track_effect_sends:
            unverified.add(
                "reverb/delay/chorus preview: bounded local approximation; "
                "not calibrated against game Wwise DSP"
            )
        events.sort(key=lambda item: item.frame)
        instance_release_frames = max(
            1,
            round(
                self._sample_rate
                * INSTANCE_LIMIT_RELEASE_MS
                / 1000.0
            ),
        )
        instance_plan = plan_instance_timeline(
            [
                InstanceTimelineItem(
                    start_frame=event.frame,
                    audible_frames=event.audible_frames,
                    group_id=event.instance_group_id,
                    scope_id=(
                        -1
                        if event.instance_limit_global
                        else event.track_id
                    ),
                    max_instances=event.max_instances,
                    kill_newest=event.kill_newest,
                )
                for event in events
            ],
            instance_release_frames,
        )
        planned_events: list[_Event] = []
        for index, event in enumerate(events):
            if not instance_plan.accepted[index]:
                continue
            if instance_plan.forced_release[index]:
                event.audible_frames = instance_plan.audible_frames[index]
                event.fade_out_frames = min(
                    event.audible_frames,
                    instance_release_frames,
                )
            # Prepared projects have one authoritative, deterministic timeline
            # plan. Clear the runtime policy after baking suppression/releases
            # into the event boundaries so _start_event cannot execute it a
            # second time (especially during seek reconstruction).
            event.instance_group_id = -1
            event.max_instances = 0
            event.kill_newest = False
            event.instance_limit_global = False
            planned_events.append(event)
        duration = max(
            (
                event.frame + self._event_audible_frames(event)
                for event in planned_events
            ),
            default=0,
        )
        return (
            planned_events,
            cache,
            cache_bytes,
            sorted(unverified),
            duration,
        )

    @staticmethod
    def _pack_sample_cache(
        cache: dict[tuple[str, int], _Sample],
        cache_bytes: int,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[tuple[str, int], _Sample]:
        """Pack a bounded decoded cache for cross-source interpolation tiles.

        The returned sample objects own views into one immutable arena.  Old
        cache objects are never mutated, because they may still be feeding the
        currently audible project while a replacement project preloads.
        """

        if BdoRealtimeAudioEngine._shared_sample_arena(cache) is not None:
            return cache
        if (
            len(cache) < 2
            or cache_bytes <= 0
            or cache_bytes > SAMPLE_ARENA_MAX_BYTES
        ):
            return cache
        total_frames = sum(max(0, int(sample.frames)) for sample in cache.values())
        if (
            total_frames <= 0
            or total_frames * 2 * np.dtype(np.float32).itemsize
            > SAMPLE_ARENA_MAX_BYTES
        ):
            return cache
        try:
            arena = np.empty((total_frames, 2), dtype=np.float32)
        except (MemoryError, ValueError):
            return cache
        packed: dict[tuple[str, int], _Sample] = {}
        offset = 0
        for key, sample in cache.items():
            BdoRealtimeAudioEngine._raise_if_preload_cancelled(cancel_event)
            frames = max(0, int(sample.frames))
            end = offset + frames
            np.copyto(arena[offset:end], sample.pcm[:frames])
            view = arena[offset:end]
            packed[key] = _Sample(
                pcm=view,
                rate=int(sample.rate),
                frames=frames,
                active_frames=int(sample.active_frames),
                arena_offset=offset,
                arena=arena,
            )
            offset = end
        return packed

    @staticmethod
    def _shared_sample_arena(
        cache: dict[tuple[str, int], _Sample],
    ) -> np.ndarray | None:
        arena: np.ndarray | None = None
        for sample in cache.values():
            candidate = sample.arena
            if candidate is None:
                return None
            if arena is None:
                arena = candidate
            elif candidate is not arena:
                return None
        return arena

    @staticmethod
    def _raise_if_preload_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _LoadCancelled()

    def _configure_preview_effects(self, events: list[_Event]) -> None:
        """Prepare the verified Aux topology and unverified local DSP curve."""

        if events:
            reference = events[0]
            settings = PreviewEffectSettings(
                reverb_time=int(getattr(reference, "reverb_time", 0)),
                delay_feedback=int(getattr(reference, "delay_feedback", 0)),
                chorus_feedback=int(getattr(reference, "chorus_feedback", 0)),
                chorus_lfo_depth=int(getattr(reference, "chorus_lfo_depth", 0)),
                chorus_lfo_frequency=int(
                    getattr(reference, "chorus_lfo_frequency", 0)
                ),
            )
        else:
            settings = PreviewEffectSettings()
        self._preview_effects.configure(
            settings,
            reverb_send=any(event.reverb_send > 0.0 for event in events),
            delay_send=any(event.delay_send > 0.0 for event in events),
            chorus_send=any(event.chorus_send > 0.0 for event in events),
        )

    def _commit_project(
        self,
        events: list[_Event],
        cache: dict[tuple[str, int], _Sample],
        cache_bytes: int,
        unverified: list[str],
        duration: int,
        *,
        start_ms: float,
    ) -> dict[str, Any]:
        with self._lock:
            self._configure_preview_effects(events)
            duration += self._preview_effects.tail_frames()
            self._events = events
            self._event_frames = np.fromiter((event.frame for event in events), dtype=np.int64, count=len(events))
            self._max_event_tail_frames = max(
                (self._event_audible_frames(event) for event in events),
                default=0,
            )
            self._voices = []
            self._event_index = 0
            self._frame = round(max(0.0, start_ms) * self._sample_rate / 1000.0)
            self._output_latency_frames = 0
            self._duration_frames = duration
            self._cache = cache
            self._cache_bytes = cache_bytes
            self._sample_arena = self._shared_sample_arena(cache)
            self._preload_loaded = self._preload_total
            self._underruns = 0
            self._voice_steals = 0
            self._master_gain = 1.0
            self._meter_render_phase = 0
            self._render_times_ms.clear()
            self._render_loads.clear()
            self._unverified = unverified
            meter_slots = max((event.track_slot for event in events), default=-1) + 1
            self._track_meter_ids = [-1] * meter_slots
            for event in events:
                if event.track_slot >= 0:
                    self._track_meter_ids[event.track_slot] = event.track_id
            self._track_peaks = np.zeros(meter_slots, dtype=np.float32)
            self._track_block_peaks = np.zeros(meter_slots, dtype=np.float32)
            self._seek_locked(self._frame)
            self._playing = False
            self._paused = False
            self._mark_output_reset_pending_locked()
        if self._output_thread and self._output_thread.isRunning():
            self.output_reset_requested.emit()
        return {
            "events": len(events),
            "samples": len(cache),
            "cache_bytes": cache_bytes,
            "unverified": self._unverified,
            "duration_ms": duration * 1000.0 / self._sample_rate,
        }

    @staticmethod
    def _decode_wav(
        path: Path,
        cancel_event: threading.Event | None = None,
    ) -> _Sample:
        BdoRealtimeAudioEngine._raise_if_preload_cancelled(cancel_event)
        try:
            with wave.open(str(path), "rb") as source:
                sample_width = source.getsampwidth()
                if sample_width not in {2, 3}:
                    raise AudioEngineError(
                        f"仅支持 16-bit/24-bit PCM WAV：{path}"
                    )
                channels = source.getnchannels()
                if channels < 1:
                    raise AudioEngineError(f"无效 WAV 声道数：{path}")
                rate = source.getframerate()
                remaining = source.getnframes()
                raw_bytes = bytearray()
                while remaining > 0:
                    BdoRealtimeAudioEngine._raise_if_preload_cancelled(cancel_event)
                    chunk_frames = min(WAV_DECODE_CHUNK_FRAMES, remaining)
                    chunk = source.readframes(chunk_frames)
                    if not chunk:
                        break
                    raw_bytes.extend(chunk)
                    remaining -= len(chunk) // (channels * sample_width)
        except (OSError, wave.Error) as exc:
            raise AudioEngineError(f"无法读取游戏 WAV：{path} ({exc})") from exc
        BdoRealtimeAudioEngine._raise_if_preload_cancelled(cancel_event)
        try:
            pcm = stereo_pcm(
                pcm_bytes_to_float32(raw_bytes, sample_width, channels)
            )
        except ValueError as exc:
            raise AudioEngineError(f"无效 WAV PCM 数据：{path}") from exc
        pcm, _gain = normalise_sample_loudness(pcm)
        active_frames = detect_active_signal_frames(pcm, rate)
        BdoRealtimeAudioEngine._raise_if_preload_cancelled(cancel_event)
        return _Sample(pcm, rate, len(pcm), active_frames)

    def play(self) -> None:
        self.start()
        with self._lock:
            self._playing = bool(self._events)
            self._paused = False
        if self._playing:
            self.output_resume_requested.emit()

    def pause(self) -> None:
        with self._lock:
            if self._playing:
                self._playing = False
                self._paused = True
        if self._output_thread and self._output_thread.isRunning():
            self.output_suspend_requested.emit()

    def seek(self, position_ms: float) -> None:
        with self._lock:
            self._master_gain = 1.0
            self._preview_effects.reset()
            self._seek_locked(round(max(0.0, position_ms) * self._sample_rate / 1000.0))
            self._output_latency_frames = 0
            self._mark_output_reset_pending_locked()
        if self._output_thread and self._output_thread.isRunning():
            self.output_reset_requested.emit()

    def _seek_locked(self, frame: int) -> None:
        self._frame = frame
        self._last_voice_prune_frame = None
        if len(self._event_frames) != len(self._events):
            self._event_frames = np.fromiter((event.frame for event in self._events), dtype=np.int64, count=len(self._events))
            self._max_event_tail_frames = max(
                (self._event_audible_frames(event) for event in self._events),
                default=0,
            )
        self._event_index = int(np.searchsorted(self._event_frames, frame, side="left"))
        self._voices = []
        earliest_frame = frame - self._max_event_tail_frames
        first_event = int(
            np.searchsorted(
                self._event_frames,
                earliest_frame,
                side="left",
            )
        )
        for event in self._events[first_event:self._event_index]:
            age_frames = max(0, frame - event.frame)
            if age_frames < self._event_audible_frames(event):
                self._start_event(event, age_frames)
        self._voices[:] = [
            voice
            for voice in self._voices
            if self._voice_is_alive_at_frame(voice, frame)
        ]

    @staticmethod
    def _event_audible_frames(event: _Event) -> int:
        explicit = int(getattr(event, "audible_frames", 0))
        if explicit > 0:
            return explicit
        sample = event.sample
        active_source_frames = int(getattr(sample, "active_frames", 0)) or sample.frames
        return sample_output_frames(active_source_frames, event.ratio)

    @staticmethod
    def _voice_audible_frames(voice: _Voice) -> int:
        explicit = int(getattr(voice, "audible_frames", 0))
        if explicit > 0:
            return explicit
        sample = voice.sample
        active_source_frames = int(getattr(sample, "active_frames", 0)) or sample.frames
        return sample_output_frames(active_source_frames, voice.ratio)

    def _start_voice(
        self, sample: _Sample, position: float, ratio: float, gain: float,
        duration_frames: int = 0, instrument_id: int = 0, ntype: int = 0,
        age_frames: int = 0, track_slot: int = -1, fade_in_frames: int = 0,
        audible_frames: int = 0, fade_out_frames: int = 0,
        native_articulation: bool = False,
        steal_delay_frames: int = 0,
        render_start_offset: int = 0,
        native_sample_route: bool = False,
        loop_start_frame: int = 0,
        loop_end_frame: int = 0,
        instance_group_id: int = -1,
        start_frame: int | None = None,
        scheduler_frame: int | None = None,
        instance_scope_id: int = -1,
        reverb_send: float = 0.0,
        delay_send: float = 0.0,
        chorus_send: float = 0.0,
    ) -> tuple[_Voice, tuple[_Voice, ...]]:
        del steal_delay_frames  # Kept for source compatibility with old callers.
        scheduled_at = (
            int(self._frame)
            if scheduler_frame is None
            else int(scheduler_frame)
        )
        voice_start = (
            scheduled_at - max(0, int(age_frames))
            if start_frame is None
            else int(start_frame)
        )
        retired: list[_Voice] | None = None
        # Expired voices are harmless until the block-end compaction.  Scanning
        # the whole pool for every onset turns a dense chord into O(events ×
        # voices) scheduler work, so prune only when the pool is about to apply
        # pressure. Instance limits independently ignore timeline-dead voices.
        if (
            len(self._voices) >= SOFT_VOICE_LIMIT
            and self._last_voice_prune_frame != scheduled_at
        ):
            active: list[_Voice] = []
            for existing in self._voices:
                if self._voice_is_alive_at_frame(existing, scheduled_at):
                    active.append(existing)
                else:
                    if retired is None:
                        retired = []
                    retired.append(existing)
            if retired:
                self._voices[:] = active
            self._last_voice_prune_frame = scheduled_at

        active_voices = len(self._voices)
        if active_voices >= SOFT_VOICE_LIMIT and self._voices:
            candidates = [
                voice
                for voice in self._voices
                if voice.release_start_age < 0
            ]
            if candidates:
                victim = min(
                    candidates,
                    key=lambda item: self._voice_steal_score_at_frame(
                        item,
                        scheduled_at,
                    ),
                )
                victim.release_start_age = max(
                    0,
                    scheduled_at - int(victim.start_frame),
                )
                victim.release_frames = max(
                    1,
                    round(
                        self._sample_rate
                        * VOICE_STEAL_RELEASE_MS
                        / 1000.0
                    ),
                )
                self._voice_steals += 1
        if len(self._voices) >= MAX_VOICES:
            quietest_index = min(
                range(len(self._voices)),
                key=lambda index: self._voice_steal_score_at_frame(
                    self._voices[index],
                    scheduled_at,
                ),
            )
            if retired is None:
                retired = []
            retired.append(self._voices.pop(quietest_index))
        valid_loop_start, valid_loop_end = self._normalise_loop_bounds(
            sample,
            loop_start_frame,
            loop_end_frame,
        )
        start_position = float(position)
        if valid_loop_end > valid_loop_start and start_position >= valid_loop_end:
            start_position = valid_loop_start + math.fmod(
                start_position - valid_loop_start,
                valid_loop_end - valid_loop_start,
            )
        voice = _Voice(
            sample=sample,
            position=start_position,
            ratio=ratio,
            gain=gain,
            duration_frames=duration_frames,
            instrument_id=instrument_id,
            ntype=ntype,
            age_frames=age_frames,
            track_slot=track_slot,
            fade_in_frames=fade_in_frames,
            audible_frames=audible_frames,
            fade_out_frames=fade_out_frames,
            native_articulation=native_articulation,
            render_start_offset=max(0, int(render_start_offset)),
            native_sample_route=native_sample_route,
            loop_start_frame=valid_loop_start,
            loop_end_frame=valid_loop_end,
            instance_group_id=instance_group_id,
            instance_scope_id=instance_scope_id,
            start_frame=voice_start,
            reverb_send=max(0.0, min(1.0, float(reverb_send))),
            delay_send=max(0.0, min(1.0, float(delay_send))),
            chorus_send=max(0.0, min(1.0, float(chorus_send))),
            equivalent_probe_key=(
                id(sample),
                voice_start,
                float(ratio),
                int(ntype),
                bool(native_articulation),
            ),
        )
        self._voices.append(voice)
        return voice, tuple(retired) if retired else ()

    @staticmethod
    def _normalise_loop_bounds(
        sample: _Sample,
        loop_start_frame: int,
        loop_end_frame: int,
    ) -> tuple[int, int]:
        start = max(0, int(loop_start_frame))
        end = min(int(sample.frames), int(loop_end_frame))
        if end - start < 2:
            return 0, 0
        return start, end

    def _voice_is_alive_at_frame(
        self,
        voice: _Voice,
        timeline_frame: int,
    ) -> bool:
        projected_age = max(
            0,
            int(timeline_frame) - int(getattr(voice, "start_frame", 0)),
        )
        release_start_age = int(
            getattr(voice, "release_start_age", -1)
        )
        release_frames = int(getattr(voice, "release_frames", 0))
        return (
            projected_age < self._voice_audible_frames(voice)
            and (
                release_start_age < 0
                or projected_age < release_start_age + release_frames
            )
        )

    def _voice_steal_score_at_frame(
        self,
        voice: _Voice,
        timeline_frame: int,
    ) -> float:
        projected_age = max(
            0,
            int(timeline_frame) - int(getattr(voice, "start_frame", 0)),
        )
        remaining = max(
            0,
            self._voice_audible_frames(voice) - projected_age,
        )
        horizon = max(1, round(self._sample_rate * 0.1))
        remaining_weight = min(1.0, remaining / horizon)
        release_weight = 0.2 if voice.release_start_age >= 0 else 1.0
        return max(0.0, float(voice.gain)) * remaining_weight * release_weight

    def _voice_steal_score(self, voice: _Voice) -> float:
        return self._voice_steal_score_at_frame(
            voice,
            int(getattr(voice, "start_frame", 0))
            + int(getattr(voice, "age_frames", 0)),
        )

    def _apply_instance_limit(
        self,
        event: _Event,
        scheduler_frame: int,
    ) -> bool:
        group_id = int(getattr(event, "instance_group_id", -1))
        limit = max(0, int(getattr(event, "max_instances", 0)))
        if group_id < 0 or limit <= 0:
            return True
        scope_id = (
            -1
            if bool(getattr(event, "instance_limit_global", False))
            else int(getattr(event, "track_id", -1))
        )
        matching = [
            voice
            for voice in self._voices
            if int(getattr(voice, "instance_group_id", -1)) == group_id
            and int(getattr(voice, "instance_scope_id", -1)) == scope_id
            and int(getattr(voice, "release_start_age", -1)) < 0
            and self._voice_is_alive_at_frame(voice, scheduler_frame)
        ]
        decision = decide_instance_limit(
            [int(getattr(voice, "start_frame", 0)) for voice in matching],
            limit,
            bool(getattr(event, "kill_newest", False)),
        )
        if not decision.accept_new:
            return False
        if not decision.victim_indices:
            return True
        release_frames = max(
            1,
            round(
                self._sample_rate
                * VOICE_STEAL_RELEASE_MS
                / 1000.0
            ),
        )
        for victim_index in decision.victim_indices:
            victim = matching[victim_index]
            victim.release_start_age = max(
                0,
                int(scheduler_frame)
                - int(getattr(victim, "start_frame", 0)),
            )
            victim.release_frames = release_frames
            self._voice_steals += 1
        return True

    def _start_event(
        self, event: _Event, age_frames: int = 0, fade_in_frames: int = 0,
        steal_delay_frames: int = 0,
        render_start_offset: int = 0,
    ) -> tuple[_Voice, ...]:
        if fade_in_frames <= 0:
            fade_in_frames = max(
                1, round(self._sample_rate * PLAYBACK_ATTACK_MS / 1000.0)
            )
        scheduler_frame = int(event.frame)
        instance_scope_id = (
            -1
            if bool(getattr(event, "instance_limit_global", False))
            else int(getattr(event, "track_id", -1))
        )
        if not self._apply_instance_limit(event, scheduler_frame):
            return ()
        _voice, displaced = self._start_voice(
            event.sample, age_frames * event.ratio, event.ratio, event.gain,
            event.duration_frames, event.instrument_id, event.ntype, age_frames,
            event.track_slot, fade_in_frames,
            self._event_audible_frames(event), event.fade_out_frames,
            event.native_articulation,
            steal_delay_frames,
            render_start_offset,
            event.native_sample_route,
            event.loop_start_frame,
            event.loop_end_frame,
            event.instance_group_id,
            event.frame,
            scheduler_frame,
            instance_scope_id,
            event.reverb_send,
            event.delay_send,
            event.chorus_send,
        )
        # Harp chord note types are Wwise-generated note stacks. Recreate the
        # audible chord while retaining the single serialized BDO note.
        intervals = preview_chord_intervals(
            event.ntype,
            native_articulation=event.native_articulation,
        )
        if not intervals:
            return displaced
        retired: list[_Voice] | None = list(displaced) if displaced else None
        for semitones in intervals:
            chord_ratio = event.ratio * (2.0 ** (semitones / 12.0))
            _voice, displaced = self._start_voice(
                event.sample, age_frames * chord_ratio,
                chord_ratio, event.gain * 0.52,
                event.duration_frames, event.instrument_id, 0, age_frames,
                event.track_slot, fade_in_frames,
                self._event_audible_frames(event), event.fade_out_frames,
                False,
                steal_delay_frames,
                render_start_offset,
                False,
                event.loop_start_frame,
                event.loop_end_frame,
                -1,
                event.frame,
                scheduler_frame,
                -1,
                event.reverb_send,
                event.delay_send,
                event.chorus_send,
            )
            if displaced:
                if retired is None:
                    retired = []
                retired.extend(displaced)
        return tuple(retired) if retired else ()

    def _read_pcm(self, max_bytes: int) -> bytes:
        frames = max(1, max_bytes // self._frame_bytes)
        started = time.perf_counter()
        with self._lock:
            if (
                self._output_reset_serial
                != self._output_reset_completed_serial
            ):
                return b""
            audio = self._render_locked(frames)
            if self._format and self._format.sampleFormat() == QAudioFormat.SampleFormat.Float:
                payload = audio.tobytes()
            else:
                np.clip(audio, -1.0, 1.0, out=audio)
                np.multiply(
                    audio,
                    32767.0,
                    out=self._pcm_i16[:frames],
                    casting="unsafe",
                )
                payload = self._pcm_i16[:frames].tobytes()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._render_times_ms.append(elapsed_ms)
            audio_budget_ms = frames * 1000.0 / max(1, self._sample_rate)
            self._render_loads.append(elapsed_ms / audio_budget_ms)
        return payload

    def _ensure_render_buffers(self, frames: int) -> None:
        if len(self._timeline_buffer) < frames:
            self._timeline_buffer = np.arange(frames, dtype=np.float32)
            self._voice_positions = np.empty(frames, dtype=np.float32)
            self._voice_indices = np.empty(frames, dtype=np.intp)
            self._voice_loop_positions = np.empty(frames, dtype=np.float32)
            self._voice_loop_mask = np.empty(frames, dtype=np.bool_)
            self._batch_positions = np.empty(
                (LINEAR_VOICE_BATCH_SIZE, frames),
                dtype=np.float32,
            )
            self._batch_indices = np.empty(
                (LINEAR_VOICE_BATCH_SIZE, frames),
                dtype=np.intp,
            )
            self._batch_loop_positions = np.empty(
                (LINEAR_VOICE_BATCH_SIZE, frames),
                dtype=np.float32,
            )
            self._batch_loop_mask = np.empty(
                (LINEAR_VOICE_BATCH_SIZE, frames),
                dtype=np.bool_,
            )
            self._batch_a = np.empty(
                (LINEAR_VOICE_BATCH_SIZE, frames, 2),
                dtype=np.float32,
            )
            self._batch_b = np.empty(
                (LINEAR_VOICE_BATCH_SIZE, frames, 2),
                dtype=np.float32,
            )
        if len(self._mix_buffer) < frames:
            self._mix_buffer = np.empty((frames, 2), dtype=np.float32)
            self._group_mix_buffer = np.empty((frames, 2), dtype=np.float32)
            self._effect_reverb_input = np.empty((frames, 2), dtype=np.float32)
            self._effect_delay_input = np.empty((frames, 2), dtype=np.float32)
            self._effect_chorus_input = np.empty((frames, 2), dtype=np.float32)
            self._effect_route_scratch = np.empty((frames, 2), dtype=np.float32)
            self._voice_a = np.empty((frames, 2), dtype=np.float32)
            self._voice_b = np.empty((frames, 2), dtype=np.float32)
            self._master_envelope = np.empty(frames, dtype=np.float32)
            self._articulation_envelope = np.empty(frames, dtype=np.float32)
            self._articulation_scratch = np.empty(frames, dtype=np.float32)
            self._limiter_magnitude = np.empty(
                (frames, 2),
                dtype=np.float32,
            )
            self._limiter_denominator = np.empty(
                (frames, 2),
                dtype=np.float32,
            )
            self._limiter_mask = np.empty(
                (frames, 2),
                dtype=np.bool_,
            )
            self._pcm_i16 = np.empty((frames, 2), dtype="<i2")

    def _accumulate_voice_pcm(
        self,
        output: np.ndarray,
        pcm: np.ndarray,
        active: int,
        voice: _Voice,
        effect_offset: int,
    ) -> None:
        """Route one prepared voice to dry output and fixed Aux input buses."""

        output[:active] += pcm[:active]
        self._accumulate_effect_pcm(
            pcm,
            active,
            float(getattr(voice, "reverb_send", 0.0)),
            float(getattr(voice, "delay_send", 0.0)),
            float(getattr(voice, "chorus_send", 0.0)),
            effect_offset,
        )

    def _accumulate_effect_pcm(
        self,
        pcm: np.ndarray,
        active: int,
        reverb_send: float,
        delay_send: float,
        chorus_send: float,
        effect_offset: int,
    ) -> None:
        """Accumulate one dry-independent signal into prepared Aux buses."""

        if not self._preview_effects.active:
            return
        start = max(0, int(effect_offset))
        end = min(len(self._effect_reverb_input), start + active)
        routed = end - start
        if routed <= 0:
            return
        scratch = self._effect_route_scratch[:routed]
        if self._preview_effects.reverb_enabled and reverb_send > 0.0:
            np.multiply(
                pcm[:routed],
                reverb_send,
                out=scratch,
            )
            self._effect_reverb_input[start:end] += scratch
        if self._preview_effects.delay_enabled and delay_send > 0.0:
            np.multiply(
                pcm[:routed],
                delay_send,
                out=scratch,
            )
            self._effect_delay_input[start:end] += scratch
        if self._preview_effects.chorus_enabled and chorus_send > 0.0:
            np.multiply(
                pcm[:routed],
                chorus_send,
                out=scratch,
            )
            self._effect_chorus_input[start:end] += scratch

    def _mix_single_voice(
        self,
        output: np.ndarray,
        length: int,
        voice: _Voice,
        effect_offset: int = 0,
    ) -> None:
        sample = voice.sample
        start = voice.position
        loop_start = int(getattr(voice, "loop_start_frame", 0))
        loop_end = int(getattr(voice, "loop_end_frame", 0))
        if (
            loop_start < 0
            or loop_end > sample.frames
            or loop_end - loop_start < 2
        ):
            loop_start = 0
            loop_end = 0
        has_loop = loop_end > loop_start
        if (
            sample.frames < 2
            or (not has_loop and start >= sample.frames - 1)
        ):
            return
        age_frames = int(getattr(voice, "age_frames", 0))
        remaining_audible = self._voice_audible_frames(voice) - age_frames
        active = min(length, max(0, remaining_audible))
        release_start_age = int(getattr(voice, "release_start_age", -1))
        release_frames = int(getattr(voice, "release_frames", 0))
        if release_start_age >= 0 and release_frames > 0:
            # The transition envelope is exactly zero after this endpoint; do
            # not keep interpolating and running articulation DSP for silence.
            active = min(
                active,
                max(
                    0,
                    release_start_age + release_frames - age_frames,
                ),
            )
        if not has_loop:
            active = min(
                active,
                max(
                    0,
                    math.ceil(
                        (sample.frames - 1 - start) / voice.ratio
                    ),
                ),
            )
        if active <= 0:
            return
        first = self._voice_a[:active]
        direct_loop_safe = (
            not has_loop
            or (
                start < loop_end
                and start + active <= loop_end
            )
        )
        if (
            voice.ratio == 1.0
            and start.is_integer()
            and direct_loop_safe
        ):
            offset = int(start)
            np.multiply(sample.pcm[offset:offset + active], voice.gain, out=first)
            self._apply_articulation_to_voice(first, active, voice)
            self._apply_voice_transition(first, active, voice)
            if self._capture_track_peaks:
                self._record_track_peak(
                    first,
                    int(getattr(voice, "track_slot", -1)),
                )
            self._accumulate_voice_pcm(
                output,
                first,
                active,
                voice,
                effect_offset,
            )
            return
        positions = self._voice_positions[:active]
        indices = self._voice_indices[:active]
        np.multiply(self._timeline_buffer[:active], voice.ratio, out=positions)
        positions += start
        if has_loop:
            wrapped = self._voice_loop_positions[:active]
            mask = self._voice_loop_mask[:active]
            np.greater_equal(positions, loop_end, out=mask)
            if bool(np.any(mask)):
                np.subtract(positions, loop_start, out=wrapped)
                np.remainder(
                    wrapped,
                    loop_end - loop_start,
                    out=wrapped,
                )
                wrapped += loop_start
                np.copyto(positions, wrapped, where=mask)
        np.copyto(indices, positions, casting="unsafe")
        # Float rounding can turn a position infinitesimally below the final
        # frame into ``frames - 1`` when truncated.  Interpolation needs both
        # base and base + 1, so clamp the base before either gather.
        np.clip(
            indices,
            0,
            (loop_end - 1) if has_loop else (sample.frames - 2),
            out=indices,
        )
        positions -= indices
        np.take(sample.pcm, indices, axis=0, out=first)
        indices += 1
        if has_loop:
            np.greater_equal(indices, loop_end, out=self._voice_loop_mask[:active])
            np.copyto(
                indices,
                loop_start,
                where=self._voice_loop_mask[:active],
            )
        np.take(sample.pcm, indices, axis=0, out=self._voice_b[:active])
        self._voice_b[:active] -= first
        self._voice_b[:active] *= positions[:, None]
        first += self._voice_b[:active]
        first *= voice.gain
        self._apply_articulation_to_voice(first, active, voice)
        self._apply_voice_transition(first, active, voice)
        if self._capture_track_peaks:
            self._record_track_peak(
                first,
                int(getattr(voice, "track_slot", -1)),
            )
        self._accumulate_voice_pcm(
            output,
            first,
            active,
            voice,
            effect_offset,
        )

    def _apply_voice_transition(self, pcm: np.ndarray, active: int, voice: _Voice) -> None:
        """Apply bounded, allocation-free attack/release ramps for key hand-off."""
        if active <= 0:
            return
        ages = self._voice_positions[:active]
        fade_in_frames = int(getattr(voice, "fade_in_frames", 0))
        age_frames = int(getattr(voice, "age_frames", 0))
        if fade_in_frames > 0 and age_frames < fade_in_frames:
            np.add(self._timeline_buffer[:active], age_frames + 1, out=ages)
            ages /= fade_in_frames
            np.clip(ages, 0.0, 1.0, out=ages)
            pcm *= ages[:, None]
        release_start_age = int(getattr(voice, "release_start_age", -1))
        release_frames = int(getattr(voice, "release_frames", 0))
        if release_start_age >= 0 and release_frames > 0:
            remaining = release_start_age + release_frames - age_frames
            np.subtract(remaining, self._timeline_buffer[:active], out=ages)
            ages /= release_frames
            np.clip(ages, 0.0, 1.0, out=ages)
            pcm *= ages[:, None]
        audible_frames = self._voice_audible_frames(voice)
        fade_out_frames = int(getattr(voice, "fade_out_frames", 0))
        fade_start_age = audible_frames - fade_out_frames
        if fade_out_frames > 0 and age_frames + active > fade_start_age:
            np.subtract(
                audible_frames - age_frames - 1,
                self._timeline_buffer[:active],
                out=ages,
            )
            ages /= fade_out_frames
            np.clip(ages, 0.0, 1.0, out=ages)
            pcm *= ages[:, None]

    def _record_track_peak(self, pcm: np.ndarray, track_slot: int, gain: float = 1.0) -> None:
        if (
            not self._capture_track_peaks
            or track_slot < 0
            or track_slot >= len(self._track_block_peaks)
            or pcm.size == 0
        ):
            return
        peak = max(float(pcm.max(initial=0.0)), -float(pcm.min(initial=0.0))) * abs(gain)
        self._record_track_peak_value(peak, track_slot)

    def _record_track_peak_value(self, peak: float, track_slot: int) -> None:
        """Accumulate an already measured peak without rescanning PCM."""
        if (
            not self._capture_track_peaks
            or track_slot < 0
            or track_slot >= len(self._track_block_peaks)
            or peak <= 0.0
        ):
            return
        self._track_block_peaks[track_slot] = min(
            1.0,
            float(self._track_block_peaks[track_slot]) + peak,
        )

    def _apply_articulation_to_voice(self, pcm: np.ndarray, active: int, voice: _Voice) -> None:
        ntype = int(getattr(voice, "ntype", 0))
        if (
            bool(getattr(voice, "native_articulation", False))
            or ntype in {0, 9, 10, 99}
            or active <= 0
        ):
            return
        ages = self._voice_positions[:active]
        np.add(self._timeline_buffer[:active], voice.age_frames, out=ages)
        apply_articulation_preview_in_place(
            pcm,
            int(getattr(voice, "instrument_id", 0)),
            ntype,
            ages,
            int(getattr(voice, "duration_frames", 0)),
            self._sample_rate,
            native_articulation=bool(
                getattr(voice, "native_articulation", False)
            ),
            envelope_out=self._articulation_envelope[:active],
            scratch=self._articulation_scratch[:active],
        )

    def _render_voice_span(
        self,
        output: np.ndarray,
        voice: _Voice,
        start_offset: int,
        end_offset: int,
    ) -> None:
        start = max(0, int(start_offset))
        end = min(len(output), max(start, int(end_offset)))
        length = end - start
        if length <= 0:
            return
        self._mix_single_voice(
            output[start:end],
            length,
            voice,
            effect_offset=start,
        )
        self._advance_voice_span(voice, length)

    def _advance_voice_span(self, voice: _Voice, length: int) -> None:
        """Advance one logical voice after its prepared PCM has been mixed."""
        if length <= 0:
            return
        voice.position += length * voice.ratio
        # _start_voice validates these once. Rechecking every active voice in
        # every block was measurable scheduler overhead in dense projects.
        loop_start = voice.loop_start_frame
        loop_end = voice.loop_end_frame
        if loop_end > loop_start and voice.position >= loop_end:
            voice.position = loop_start + math.fmod(
                voice.position - loop_start,
                loop_end - loop_start,
            )
        voice.age_frames += length

    def _linear_voice_batch_eligible(
        self,
        voice: _Voice,
        frames: int,
    ) -> bool:
        """Return whether a voice can enter an allocation-free linear tile.

        Voices that need an articulation or transition envelope stay on the
        scalar path.  This makes the tile exactly the same interpolation and
        gain operation as ``_mix_single_voice``; only NumPy dispatch is shared.
        """

        if frames <= 0 or voice.render_start_offset != 0:
            return False
        if (
            not math.isfinite(voice.position)
            or not math.isfinite(voice.ratio)
            or not math.isfinite(voice.gain)
            or voice.ratio <= 0.0
            or voice.sample.frames < 2
        ):
            return False
        if (
            not voice.native_articulation
            and voice.ntype not in {0, 9, 10, 99}
        ):
            return False
        if voice.fade_in_frames > 0 and voice.age_frames < voice.fade_in_frames:
            return False
        if voice.release_start_age >= 0:
            return False
        audible_frames = self._voice_audible_frames(voice)
        if voice.age_frames + frames > audible_frames:
            return False
        fade_start = audible_frames - voice.fade_out_frames
        if voice.fade_out_frames > 0 and voice.age_frames + frames > fade_start:
            return False

        loop_start = voice.loop_start_frame
        loop_end = voice.loop_end_frame
        direct_loop_safe = (
            loop_end <= loop_start
            or (
                voice.position < loop_end
                and voice.position + frames <= loop_end
            )
        )
        if (
            voice.ratio == 1.0
            and voice.position.is_integer()
            and direct_loop_safe
        ):
            # The scalar fast path is one contiguous multiply; constructing
            # interpolation indices for it would be a regression.
            return False
        if loop_end <= loop_start:
            final_position = voice.position + (frames - 1) * voice.ratio
            if final_position >= voice.sample.frames - 1:
                return False
        return True

    def _mix_linear_voice_batch(
        self,
        output: np.ndarray,
        voices: list[_Voice | None],
        count: int,
        frames: int,
    ) -> None:
        """Mix up to ``LINEAR_VOICE_BATCH_SIZE`` compatible voices together."""

        if count <= 0:
            return
        representative = voices[0]
        if representative is None:
            return
        sample = representative.sample
        loop_start = representative.loop_start_frame
        loop_end = representative.loop_end_frame
        arena = sample.arena
        use_shared_arena = (
            arena is not None
            and arena is self._sample_arena
            and loop_end <= loop_start
        )
        for index in range(count):
            voice = voices[index]
            if voice is None:
                continue
            self._batch_starts[index] = voice.position
            self._batch_ratios[index] = voice.ratio
            self._batch_gains[index] = voice.gain
            if use_shared_arena:
                voice_sample = voice.sample
                if (
                    voice_sample.arena is not arena
                    or voice.loop_end_frame > voice.loop_start_frame
                    or voice_sample.arena_offset < 0
                ):
                    use_shared_arena = False
                else:
                    self._batch_arena_offsets[index] = voice_sample.arena_offset
                    self._batch_last_indices[index] = voice_sample.frames - 2

        positions = self._batch_positions[:count, :frames]
        indices = self._batch_indices[:count, :frames]
        np.multiply(
            self._batch_ratios[:count, None],
            self._timeline_buffer[None, :frames],
            out=positions,
        )
        positions += self._batch_starts[:count, None]
        if loop_end > loop_start:
            wrapped = self._batch_loop_positions[:count, :frames]
            mask = self._batch_loop_mask[:count, :frames]
            np.greater_equal(positions, loop_end, out=mask)
            if bool(np.any(mask)):
                np.subtract(positions, loop_start, out=wrapped)
                np.remainder(
                    wrapped,
                    loop_end - loop_start,
                    out=wrapped,
                )
                wrapped += loop_start
                np.copyto(positions, wrapped, where=mask)

        np.copyto(indices, positions, casting="unsafe")
        if use_shared_arena:
            np.maximum(indices, 0, out=indices)
            np.minimum(
                indices,
                self._batch_last_indices[:count, None],
                out=indices,
            )
        else:
            np.clip(
                indices,
                0,
                (loop_end - 1) if loop_end > loop_start else (sample.frames - 2),
                out=indices,
            )
        positions -= indices
        if use_shared_arena:
            indices += self._batch_arena_offsets[:count, None]
        first = self._batch_a[:count, :frames]
        second = self._batch_b[:count, :frames]
        np.take(
            arena if use_shared_arena else sample.pcm,
            indices,
            axis=0,
            out=first,
        )
        indices += 1
        if loop_end > loop_start:
            mask = self._batch_loop_mask[:count, :frames]
            np.greater_equal(indices, loop_end, out=mask)
            np.copyto(indices, loop_start, where=mask)
        np.take(
            arena if use_shared_arena else sample.pcm,
            indices,
            axis=0,
            out=second,
        )
        second -= first
        second *= positions[:, :, None]
        first += second
        first *= self._batch_gains[:count, None, None]

        # A tile often contains voices from one track and therefore one Aux
        # route. Sum that route once when it is exactly shared; mixed routes
        # retain per-voice accumulation below. Logical lifecycle, meters and
        # instance-limit state remain independent in either case.
        shared_effect_route = self._preview_effects.active
        reverb_send = representative.reverb_send
        delay_send = representative.delay_send
        chorus_send = representative.chorus_send
        any_effect_send = (
            reverb_send > 0.0
            or delay_send > 0.0
            or chorus_send > 0.0
        )
        if shared_effect_route:
            for index in range(1, count):
                voice = voices[index]
                if voice is None:
                    shared_effect_route = False
                    continue
                any_effect_send = any_effect_send or (
                    voice.reverb_send > 0.0
                    or voice.delay_send > 0.0
                    or voice.chorus_send > 0.0
                )
                if (
                    voice.reverb_send != reverb_send
                    or voice.delay_send != delay_send
                    or voice.chorus_send != chorus_send
                ):
                    shared_effect_route = False
        shared_effect_route = shared_effect_route and any_effect_send
        grouped_pcm = self._group_mix_buffer[:frames]
        if shared_effect_route:
            grouped_pcm.fill(0.0)

        # Preserve scalar dry accumulation order and per-track peak semantics.
        for index in range(count):
            voice = voices[index]
            if voice is None:
                continue
            pcm = first[index]
            if self._capture_track_peaks:
                self._record_track_peak(pcm, voice.track_slot)
            output += pcm
            if shared_effect_route:
                grouped_pcm += pcm
            elif any_effect_send:
                self._accumulate_effect_pcm(
                    pcm,
                    frames,
                    voice.reverb_send,
                    voice.delay_send,
                    voice.chorus_send,
                    0,
                )
            self._advance_voice_span(voice, frames)
        if shared_effect_route:
            self._accumulate_effect_pcm(
                grouped_pcm,
                frames,
                reverb_send,
                delay_send,
                chorus_send,
                0,
            )

    def _flush_linear_voice_batch(
        self,
        output: np.ndarray,
        count: int,
        frames: int,
    ) -> None:
        if count >= LINEAR_VOICE_BATCH_THRESHOLD:
            self._mix_linear_voice_batch(
                output,
                self._batch_voice_refs,
                count,
                frames,
            )
        else:
            for index in range(count):
                voice = self._batch_voice_refs[index]
                if voice is not None:
                    self._render_voice_span(
                        output,
                        voice,
                        voice.render_start_offset,
                        frames,
                    )
        for index in range(count):
            self._batch_voice_refs[index] = None

    def _render_voice_sequence(
        self,
        output: np.ndarray,
        voices: list[_Voice],
        frames: int,
    ) -> None:
        """Render scalar voices, using fixed tiles for repeated sample sources."""

        if len(voices) < LINEAR_VOICE_BATCH_THRESHOLD:
            for voice in voices:
                self._render_voice_span(
                    output,
                    voice,
                    voice.render_start_offset,
                    frames,
                )
            return

        used_count = 0
        arena_count = 0
        slot_mask = LINEAR_VOICE_BUCKET_SLOTS - 1
        for voice in voices:
            if not self._linear_voice_batch_eligible(voice, frames):
                self._render_voice_span(
                    output,
                    voice,
                    voice.render_start_offset,
                    frames,
                )
                continue
            if (
                self._sample_arena is not None
                and voice.sample.arena is self._sample_arena
                and voice.sample.arena_offset >= 0
                and voice.loop_end_frame <= voice.loop_start_frame
            ):
                self._batch_voice_refs[arena_count] = voice
                arena_count += 1
                if arena_count == LINEAR_VOICE_BATCH_SIZE:
                    self._flush_linear_voice_batch(
                        output,
                        arena_count,
                        frames,
                    )
                    arena_count = 0
                continue
            slot = (
                (id(voice.sample) >> 4)
                ^ (voice.loop_start_frame * 1_000_003)
                ^ (voice.loop_end_frame * 97_409)
            ) & slot_mask
            while True:
                bucket_sample = self._batch_bucket_samples[slot]
                if bucket_sample is None:
                    self._batch_bucket_samples[slot] = voice.sample
                    self._batch_bucket_loop_starts[slot] = voice.loop_start_frame
                    self._batch_bucket_loop_ends[slot] = voice.loop_end_frame
                    self._batch_bucket_counts[slot] = 0
                    self._batch_used_slots[used_count] = slot
                    used_count += 1
                    break
                if (
                    bucket_sample is voice.sample
                    and int(self._batch_bucket_loop_starts[slot])
                    == voice.loop_start_frame
                    and int(self._batch_bucket_loop_ends[slot])
                    == voice.loop_end_frame
                ):
                    break
                slot = (slot + 1) & slot_mask

            count = int(self._batch_bucket_counts[slot])
            base = slot * LINEAR_VOICE_BATCH_SIZE
            self._batch_bucket_voices[base + count] = voice
            count += 1
            if count == LINEAR_VOICE_BATCH_SIZE:
                for index in range(count):
                    self._batch_voice_refs[index] = self._batch_bucket_voices[
                        base + index
                    ]
                    self._batch_bucket_voices[base + index] = None
                self._flush_linear_voice_batch(output, count, frames)
                count = 0
            self._batch_bucket_counts[slot] = count

        self._flush_linear_voice_batch(output, arena_count, frames)
        for used_index in range(used_count):
            slot = int(self._batch_used_slots[used_index])
            count = int(self._batch_bucket_counts[slot])
            base = slot * LINEAR_VOICE_BATCH_SIZE
            for index in range(count):
                self._batch_voice_refs[index] = self._batch_bucket_voices[
                    base + index
                ]
                self._batch_bucket_voices[base + index] = None
            self._flush_linear_voice_batch(output, count, frames)
            self._batch_bucket_counts[slot] = 0
            self._batch_bucket_samples[slot] = None

    @staticmethod
    def _equivalent_voice_mix_key(voice: _Voice) -> tuple | None:
        """Return an exact key only when gain aggregation is mathematically linear.

        Slap/brass fallback colour uses a per-voice tanh after gain, so those
        voices intentionally stay on the scalar path.  Logical voices are not
        merged: lifecycle, instance limits, stealing, meters and Seek state all
        continue to track every note independently.
        """

        if (
            not math.isfinite(float(voice.position))
            or not math.isfinite(float(voice.ratio))
            or not math.isfinite(float(voice.gain))
        ):
            return None
        if (
            not bool(getattr(voice, "native_articulation", False))
            and int(getattr(voice, "ntype", 0)) in {21, 22}
        ):
            return None
        return (
            id(voice.sample),
            float(voice.position),
            float(voice.ratio),
            int(getattr(voice, "duration_frames", 0)),
            int(getattr(voice, "instrument_id", 0)),
            int(getattr(voice, "ntype", 0)),
            int(getattr(voice, "age_frames", 0)),
            int(getattr(voice, "fade_in_frames", 0)),
            int(getattr(voice, "release_start_age", -1)),
            int(getattr(voice, "release_frames", 0)),
            int(getattr(voice, "audible_frames", 0)),
            int(getattr(voice, "fade_out_frames", 0)),
            bool(getattr(voice, "native_articulation", False)),
            int(getattr(voice, "render_start_offset", 0)),
            int(getattr(voice, "loop_start_frame", 0)),
            int(getattr(voice, "loop_end_frame", 0)),
        )

    def _render_equivalent_voice_group(
        self,
        output: np.ndarray,
        voices: list[_Voice],
        frames: int,
    ) -> None:
        """Interpolate one equivalent group once while retaining every voice."""

        representative = voices[0]
        start = max(0, int(representative.render_start_offset))
        end = max(start, min(len(output), int(frames)))
        length = end - start
        if length <= 0:
            return
        group_pcm = self._group_mix_buffer[:length]
        group_pcm.fill(0.0)
        original_gain = representative.gain
        original_track_slot = representative.track_slot
        original_reverb_send = representative.reverb_send
        original_delay_send = representative.delay_send
        original_chorus_send = representative.chorus_send
        representative.gain = 1.0
        representative.track_slot = -1
        representative.reverb_send = 0.0
        representative.delay_send = 0.0
        representative.chorus_send = 0.0
        try:
            self._mix_single_voice(group_pcm, length, representative)
        finally:
            representative.gain = original_gain
            representative.track_slot = original_track_slot
            representative.reverb_send = original_reverb_send
            representative.delay_send = original_delay_send
            representative.chorus_send = original_chorus_send

        if self._capture_track_peaks and group_pcm.size:
            unit_peak = max(
                float(group_pcm.max(initial=0.0)),
                -float(group_pcm.min(initial=0.0)),
            )
            if unit_peak > 0.0:
                for voice in voices:
                    self._record_track_peak_value(
                        unit_peak * abs(float(voice.gain)),
                        int(getattr(voice, "track_slot", -1)),
                    )
        total_gain = math.fsum(float(voice.gain) for voice in voices)
        self._accumulate_effect_pcm(
            group_pcm,
            length,
            math.fsum(
                float(voice.gain) * float(voice.reverb_send)
                for voice in voices
            ),
            math.fsum(
                float(voice.gain) * float(voice.delay_send)
                for voice in voices
            ),
            math.fsum(
                float(voice.gain) * float(voice.chorus_send)
                for voice in voices
            ),
            start,
        )
        group_pcm *= total_gain
        output[start:end] += group_pcm
        for voice in voices:
            self._advance_voice_span(voice, length)

    def _render_active_voice_pool(self, output: np.ndarray, frames: int) -> None:
        """Mix the bounded pool, grouping only exact linear equivalents."""

        equivalent_threshold = (
            EQUIVALENT_EFFECT_VOICE_GROUP_THRESHOLD
            if self._preview_effects.active
            else EQUIVALENT_VOICE_GROUP_THRESHOLD
        )
        if len(self._voices) < equivalent_threshold:
            self._render_voice_sequence(output, self._voices, frames)
            return

        # Most real projects have many active voices but no duplicate note at
        # the same onset.  A small coarse probe avoids constructing the full
        # render key and buckets in that common case; a hit is only permission
        # to run the exact-key pass below, never permission to combine voices.
        coarse_keys = self._equivalent_probe_keys
        coarse_keys.clear()
        has_equivalent_candidate = False
        for voice in self._voices:
            if voice.render_start_offset != 0:
                continue
            coarse_key = voice.equivalent_probe_key
            if coarse_key in coarse_keys:
                has_equivalent_candidate = True
                break
            coarse_keys.add(coarse_key)
        if not has_equivalent_candidate:
            coarse_keys.clear()
            self._render_voice_sequence(output, self._voices, frames)
            return
        coarse_keys.clear()

        groups: dict[tuple, list[_Voice]] = {}
        scalar_voices: list[_Voice] = []
        for voice in self._voices:
            key = self._equivalent_voice_mix_key(voice)
            if key is None:
                scalar_voices.append(voice)
                continue
            groups.setdefault(key, []).append(voice)
        for voices in groups.values():
            if len(voices) == 1:
                scalar_voices.append(voices[0])
            else:
                self._render_equivalent_voice_group(output, voices, frames)
        # A duplicate candidate should not force every unrelated singleton
        # back through per-voice NumPy interpolation.  Feed the remaining
        # voices through the normal bounded tile path after exact groups have
        # been collapsed.
        self._render_voice_sequence(output, scalar_voices, frames)

    def _voice_is_alive(self, voice: _Voice) -> bool:
        release_alive = (
            voice.release_start_age < 0
            or voice.age_frames
            < voice.release_start_age + voice.release_frames
        )
        loop_start = voice.loop_start_frame
        loop_end = voice.loop_end_frame
        sample_alive = (
            loop_end > loop_start
            or voice.position < voice.sample.frames - 1
        )
        return (
            sample_alive
            and release_alive
            and voice.age_frames < self._voice_audible_frames(voice)
        )

    def _apply_master_headroom(
        self,
        output: np.ndarray,
        frames: int,
    ) -> None:
        if frames <= 0 or output.size == 0:
            return
        raw_peak = max(
            float(output.max(initial=0.0)),
            -float(output.min(initial=0.0)),
        )
        target_gain = (
            min(1.0, MASTER_TARGET_PEAK / raw_peak)
            if raw_peak > 1.0e-9
            else 1.0
        )
        start_gain = float(self._master_gain)
        envelope = self._master_envelope[:frames]
        if target_gain < start_gain:
            attack_frames = min(
                frames,
                max(
                    1,
                    round(
                        self._sample_rate * MASTER_ATTACK_MS / 1000.0
                    ),
                ),
            )
            envelope.fill(target_gain)
            if attack_frames == 1:
                envelope[0] = target_gain
            else:
                np.multiply(
                    self._timeline_buffer[:attack_frames],
                    (target_gain - start_gain) / (attack_frames - 1),
                    out=envelope[:attack_frames],
                )
                envelope[:attack_frames] += start_gain
            end_gain = target_gain
        else:
            release_frames = max(
                1.0,
                self._sample_rate * MASTER_RELEASE_MS / 1000.0,
            )
            release_amount = 1.0 - math.exp(-frames / release_frames)
            end_gain = start_gain + (
                target_gain - start_gain
            ) * release_amount
            if frames == 1:
                envelope[0] = end_gain
            else:
                np.multiply(
                    self._timeline_buffer[:frames],
                    (end_gain - start_gain) / (frames - 1),
                    out=envelope,
                )
                envelope += start_gain
        output *= envelope[:, None]
        self._master_gain = max(0.0, min(1.0, float(end_gain)))

    def _render_locked(self, frames: int) -> np.ndarray:
        self._ensure_render_buffers(frames)
        output = self._mix_buffer[:frames]
        output.fill(0.0)
        if self._preview_effects.active:
            self._effect_reverb_input[:frames].fill(0.0)
            self._effect_delay_input[:frames].fill(0.0)
            self._effect_chorus_input[:frames].fill(0.0)
        if self._track_peaks.size:
            np.multiply(self._track_peaks, 0.82, out=self._track_peaks)
        self._capture_track_peaks = self._meter_render_phase == 0
        self._meter_render_phase = (
            self._meter_render_phase + 1
        ) % TRACK_METER_RENDER_INTERVAL
        if self._capture_track_peaks and self._track_block_peaks.size:
            self._track_block_peaks.fill(0.0)
        if not self._playing:
            return output
        block_start = self._frame
        block_end = block_start + frames
        for voice in self._voices:
            voice.render_start_offset = 0
        while (
            self._event_index < len(self._events)
            and self._events[self._event_index].frame <= block_end
        ):
            event = self._events[self._event_index]
            offset = max(0, min(frames, event.frame - block_start))
            event_age = max(0, block_start - event.frame)
            stolen = self._start_event(
                event,
                age_frames=event_age,
                steal_delay_frames=offset,
                render_start_offset=offset,
            )
            for voice in stolen:
                self._render_voice_span(
                    output,
                    voice,
                    voice.render_start_offset,
                    offset,
                )
            self._event_index += 1

        alive_count = 0
        self._render_active_voice_pool(output, frames)
        voice_count = len(self._voices)
        for voice_index in range(voice_count):
            voice = self._voices[voice_index]
            if self._voice_is_alive(voice):
                self._voices[alive_count] = voice
                alive_count += 1
        del self._voices[alive_count:]
        # The pool was compacted against the new timeline position. A seek or
        # the next block may revisit an equal numeric frame with different
        # voices, so no per-frame prune decision survives this boundary.
        self._last_voice_prune_frame = None
        self._frame = block_end
        if self._frame >= self._duration_frames and not self._voices:
            self._playing = False
            self._paused = False
        if self._capture_track_peaks and self._track_peaks.size:
            np.maximum(self._track_peaks, self._track_block_peaks, out=self._track_peaks)
        if self._preview_effects.active:
            self._preview_effects.process(
                output,
                self._effect_reverb_input,
                self._effect_delay_input,
                self._effect_chorus_input,
                frames,
            )
        self._apply_master_headroom(output, frames)
        soft_limit_in_place(
            output,
            magnitude=self._limiter_magnitude[:frames],
            denominator=self._limiter_denominator[:frames],
            mask=self._limiter_mask[:frames],
        )
        return output

    def get_status(self) -> AudioStatus:
        with self._lock:
            state = "playing" if self._playing else ("paused" if self._paused else "stopped")
            sample_rate = self._sample_rate
            frame = self._frame
            output_latency_frames = self._output_latency_frames
            duration_frames = self._duration_frames
            buffer_frames = self._buffer_frames
            cache_bytes = self._cache_bytes
            preload_loaded = self._preload_loaded
            preload_total = self._preload_total
            has_events = bool(self._events)
            underruns = self._underruns
            render_times = tuple(self._render_times_ms)
            render_loads = tuple(self._render_loads)
            active_voices = len(self._voices)
            voice_steals = self._voice_steals
            master_gain = self._master_gain
            unverified = list(self._unverified)
            track_meter_ids = tuple(self._track_meter_ids)
            track_peaks = self._track_peaks.copy()

        # Percentiles and presentation dictionaries do not guard mutable mixer
        # state, so keep them outside the callback's transport lock.
        ordered_times = sorted(render_times)
        render_p95 = (
            ordered_times[round((len(ordered_times) - 1) * 0.95)]
            if ordered_times
            else 0.0
        )
        ordered_loads = sorted(render_loads)
        render_p95_load = (
            ordered_loads[round((len(ordered_loads) - 1) * 0.95)]
            if ordered_loads
            else 0.0
        )
        audible_frame = max(0, frame - output_latency_frames)
        return AudioStatus(
            state=state,
            position_ms=audible_frame * 1000.0 / sample_rate,
            duration_ms=duration_frames * 1000.0 / sample_rate,
            sample_rate=sample_rate,
            buffer_frames=buffer_frames,
            cache_bytes=cache_bytes,
            preload_loaded=preload_loaded,
            preload_total=preload_total,
            preload_progress=(
                min(1.0, preload_loaded / preload_total)
                if preload_total
                else (1.0 if has_events else 0.0)
            ),
            underruns=underruns,
            render_p95_ms=render_p95,
            render_max_ms=max(ordered_times, default=0.0),
            render_p95_load=render_p95_load,
            active_voices=active_voices,
            voice_steals=voice_steals,
            master_gain=master_gain,
            unverified=unverified,
            track_levels={
                track_id: float(track_peaks[slot])
                for slot, track_id in enumerate(track_meter_ids)
                if track_id >= 0 and slot < len(track_peaks)
            },
        )
