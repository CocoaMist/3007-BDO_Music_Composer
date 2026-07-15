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
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QIODevice, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices


class AudioEngineError(RuntimeError):
    pass


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
    unverified: list[str] = field(default_factory=list)


@dataclass
class _Sample:
    pcm: np.ndarray
    rate: int
    frames: int


@dataclass
class _Event:
    frame: int
    sample: _Sample
    ratio: float
    gain: float
    duration_frames: int = 0
    instrument_id: int = 0
    ntype: int = 0


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


BANK_BY_ID = {
    0x00: "midi_instrument_00_acousticguitar", 0x01: "midi_instrument_01_flute",
    0x02: "midi_instrument_02_recorder", 0x04: "midi_instrument_04_handdrum",
    0x05: "midi_instrument_05_piatticymbals", 0x06: "midi_instrument_06_harp",
    0x07: "midi_instrument_07_piano", 0x08: "midi_instrument_08_violin",
    0x0A: "midi_instrument_10_proguitar", 0x0B: "midi_instrument_11_proflute",
    0x0D: "midi_instrument_13_prodrumset", 0x0E: "midi_instrument_14_probasselectric",
    0x0F: "midi_instrument_15_probasscontra", 0x10: "midi_instrument_16_proharp",
    0x11: "midi_instrument_17_propiano", 0x12: "midi_instrument_18_proviolin",
    0x13: "midi_instrument_19_propandrum", 0x24: "midi_instrument_24_proguitarelectricclean",
    0x25: "midi_instrument_25_proguitarelectricdrive", 0x26: "midi_instrument_26_proguitarelectricdist",
    0x27: "midi_instrument_27_proclarinet", 0x28: "midi_instrument_28_prohorn",
}

# Provisional Marnian preview routing.  The game UI exposes four source modes
# per Marnian instrument; the waveform-family pairing is kept visibly
# unverified until it has game-capture A/B evidence.
MARNIAN_SYNTH_WAVEFORM_BY_ID = {
    0x14: "saw", 0x18: "sine", 0x1C: "square", 0x20: "triangle",
}
MARNIAN_SYNTH_MODES = frozenset({"basic", "stereo", "super", "superoct"})

# Preview loudness policy.  Wwise normally applies per-sound/bus gain that is
# not present in an extracted WAV.  Keep MIDI velocity as the musical dynamic,
# while bringing the raw samples into a conservative common range first.
SAMPLE_TARGET_RMS = 0.11       # about -19 dBFS on active sample frames
SAMPLE_PEAK_CEILING = 0.62     # headroom for chords and overlapping tails
SAMPLE_GAIN_MIN = 0.05
SAMPLE_GAIN_MAX = 4.00
OUTPUT_LIMIT_THRESHOLD = 0.82

GM_TO_BDO_DRUM = {
    35: 48, 36: 48, 37: 49, 38: 50, 39: 50, 40: 50, 41: 51, 42: 54,
    43: 53, 44: 56, 45: 55, 46: 58, 47: 57, 48: 60, 49: 61, 50: 60,
    51: 62, 52: 61, 53: 62, 54: 61, 55: 61, 56: 51, 57: 61, 58: 51,
    59: 62, 60: 63, 61: 64, 62: 61, 63: 63, 64: 64,
}


def resolve_bdo_pitch(instrument_id: int, pitch: int, ntype: int = 0) -> int:
    """Resolve imported GM drums without corrupting canonical game drum keys.

    BDO saves use canonical 48–64 keys with ntype 99. Imported GM MIDI uses
    ordinary GM pitches and is translated only before it has been serialized as a
    BDO drum note.
    """
    if instrument_id != 0x0D:
        return pitch
    if ntype == 99 and 48 <= pitch <= 64:
        return pitch
    return GM_TO_BDO_DRUM.get(pitch, pitch)


def bank_for_instrument(instrument_id: int, synth_mode: str = "basic") -> str | None:
    """Return the preview bank for an instrument and its source mode."""
    waveform = MARNIAN_SYNTH_WAVEFORM_BY_ID.get(instrument_id)
    if waveform:
        mode = synth_mode if synth_mode in MARNIAN_SYNTH_MODES else "basic"
        return f"midi_instrument_synth_{waveform}_{mode}"
    return BANK_BY_ID.get(instrument_id)


def marnian_synth_matrix() -> dict[int, dict[str, str]]:
    """Return the four source-mode banks for each Marnian instrument."""
    return {
        instrument_id: {
            mode: bank_for_instrument(instrument_id, mode)
            for mode in sorted(MARNIAN_SYNTH_MODES)
        }
        for instrument_id in sorted(MARNIAN_SYNTH_WAVEFORM_BY_ID)
    }


def normalise_sample_loudness(pcm: np.ndarray) -> tuple[np.ndarray, float]:
    """Return a level-matched sample and the applied gain.

    Silence and very quiet tails are excluded from the RMS measurement so a
    long release cannot make its attack unexpectedly loud.  Peak headroom is
    always enforced, and gain is bounded to avoid amplifying extraction noise.
    """
    if pcm.size == 0:
        return np.ascontiguousarray(pcm, dtype=np.float32), 1.0
    source = np.asarray(pcm, dtype=np.float32)
    frame_level = np.max(np.abs(source), axis=1)
    peak = float(frame_level.max(initial=0.0))
    if not math.isfinite(peak) or peak <= 1e-7:
        return np.ascontiguousarray(source, dtype=np.float32), 1.0
    active_floor = max(10.0 ** (-50.0 / 20.0), peak * 0.03)
    active = source[frame_level >= active_floor]
    rms = float(np.sqrt(np.mean(np.square(active, dtype=np.float64)))) if active.size else peak
    rms_gain = SAMPLE_TARGET_RMS / max(rms, 1e-7)
    peak_gain = SAMPLE_PEAK_CEILING / peak
    gain = max(SAMPLE_GAIN_MIN, min(SAMPLE_GAIN_MAX, rms_gain, peak_gain))
    matched = np.ascontiguousarray(source * gain, dtype=np.float32)
    return matched, gain


def soft_limit_in_place(audio: np.ndarray, threshold: float = OUTPUT_LIMIT_THRESHOLD) -> np.ndarray:
    """Protect the device output from harsh clipping while leaving normal levels untouched."""
    if audio.size == 0:
        return audio
    magnitude = np.abs(audio)
    hot = magnitude > threshold
    if np.any(hot):
        excess = magnitude[hot] - threshold
        compressed = threshold + excess / (1.0 + excess / (1.0 - threshold))
        audio[hot] = np.copysign(compressed, audio[hot])
    return audio


def articulation_preview_envelope(
    instrument_id: int, ntype: int, age_frames: np.ndarray, duration_frames: int, sample_rate: int,
) -> np.ndarray:
    """Build a cheap real-time envelope/modulator for a BDO note type.

    These curves make serialized articulations audible in Python preview. They
    are deliberately labelled approximate: the extracted mapping does not yet
    contain Wwise's note-type DSP graph.
    """
    age = np.asarray(age_frames, dtype=np.float32)
    duration = max(1, int(duration_frames) or sample_rate)
    phase = age / max(1.0, float(sample_rate))
    progress = np.clip(age / duration, 0.0, 1.0)
    envelope = np.ones_like(age, dtype=np.float32)

    # The two simple Marnian sources call type 1 "basic", not staccato.
    if ntype == 1 and instrument_id not in {0x1C, 0x20}:
        cutoff = max(1.0, duration * 0.55)
        envelope *= np.clip((cutoff - age) / max(1.0, sample_rate * 0.025), 0.0, 1.0)
    elif ntype == 2:
        cutoff = max(1.0, duration * 0.32)
        envelope *= np.clip((cutoff - age) / max(1.0, sample_rate * 0.012), 0.0, 1.0)
    elif ntype in {3, 23}:
        envelope *= 0.48 + 0.52 * np.minimum(1.0, progress * 3.0)
    elif ntype == 12:
        envelope *= 1.0 - 0.42 * progress
    elif ntype in {4, 5, 6, 7, 8, 17, 18, 19}:
        settings = {
            4: (5.0, 0.22), 5: (6.0, 0.24), 6: (5.5, 0.14), 7: (7.0, 0.18),
            8: (8.0, 0.22), 17: (9.0, 0.16), 18: (6.5, 0.28), 19: (11.0, 0.14),
        }
        frequency, depth = settings[ntype]
        envelope *= 1.0 - depth * 0.5 + depth * 0.5 * np.sin(2.0 * np.pi * frequency * phase)
    elif ntype == 13:
        envelope *= 0.58 * np.exp(-3.0 * progress)
    elif ntype == 14:
        envelope *= 0.70
    elif ntype == 15:
        pulse = np.mod(progress * 3.0, 1.0)
        envelope *= np.clip((0.84 - pulse) / 0.12, 0.0, 1.0)
    elif ntype == 16:
        envelope *= 0.55 + 0.45 * np.sin(np.pi * progress)
    elif ntype == 11:
        envelope *= 0.90 + 0.10 * np.minimum(1.0, progress * 1.5)
    elif ntype == 20:
        envelope *= 0.68 + 0.22 * np.sin(2.0 * np.pi * 1.3 * phase)
    elif ntype == 21:
        envelope *= 0.78 + 0.18 * np.sin(2.0 * np.pi * 2.1 * phase)
    elif ntype == 22:
        envelope *= 1.22 * np.exp(-5.5 * progress)
    elif ntype == 24:
        envelope *= np.clip((duration * 0.24 - age) / max(1.0, sample_rate * 0.015), 0.0, 1.0)
        envelope *= 0.55 + 0.45 * np.sign(np.sin(2.0 * np.pi * 38.0 * phase))
    elif ntype == 25:
        envelope *= 0.72 + 0.28 * np.sin(2.0 * np.pi * 13.0 * phase)
    elif ntype == 26:
        envelope *= 0.62
    elif ntype == 27:
        envelope *= 0.82
    elif ntype == 28:
        envelope *= 1.08
    return envelope


def select_wwise_zone(
    banks: dict[str, list[dict]], instrument_id: int, pitch: int, velocity: int, ntype: int = 0,
    synth_mode: str = "basic",
) -> tuple[str, dict] | None:
    """Select the Wwise zone used by the Python preview player."""
    bank = bank_for_instrument(instrument_id, synth_mode)
    if not bank or bank not in banks:
        return None
    resolved_pitch = resolve_bdo_pitch(instrument_id, pitch, ntype)
    matches = [
        row for row in banks[bank]
        if row.get("wav_exists")
        and int(row["key_min"]) <= resolved_pitch <= int(row["key_max"])
        and int(row["velocity_min"]) <= velocity <= int(row["velocity_max"])
    ]
    if not matches:
        return None
    return bank, min(matches, key=lambda item: (
        abs(resolved_pitch - int(item["root_note"])),
        abs(velocity - (int(item["velocity_min"]) + int(item["velocity_max"])) / 2),
        int(item["source_id"]),
    ))


class _AudioOutputWorker(QObject):
    """Owns QAudioSink and mixing cadence outside the GUI thread."""

    def __init__(self, engine: "BdoRealtimeAudioEngine") -> None:
        super().__init__()
        self.engine = engine
        self.sink: QAudioSink | None = None
        self.output: QIODevice | None = None
        self.timer: QTimer | None = None
        self.target_frames = 0

    @Slot()
    def open(self) -> None:
        try:
            device = QMediaDevices.defaultAudioOutput()
            if not device.id():
                raise AudioEngineError("没有可用的系统音频输出设备")
            requested = QAudioFormat()
            requested.setSampleRate(48_000)
            requested.setChannelCount(2)
            requested.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            audio_format = requested if device.isFormatSupported(requested) else device.preferredFormat()
            if audio_format.channelCount() != 2 or audio_format.sampleFormat() not in {
                QAudioFormat.SampleFormat.Int16, QAudioFormat.SampleFormat.Float,
            }:
                raise AudioEngineError("音频设备不支持双声道 Int16/Float PCM")
            self.engine._set_output_format(audio_format)
            self.sink = QAudioSink(device, audio_format, self)
            # A slightly deeper device queue absorbs Qt timer jitter and dense
            # chord bursts.  Decoding/mixing is still real time; only the
            # hardware queue grows from ~60 ms to ~120 ms.
            self.sink.setBufferSize(max(self.engine._frame_bytes * 1024, self.engine._sample_rate * self.engine._frame_bytes * 120 // 1000))
            self.sink.stateChanged.connect(self._on_sink_state_changed)
            self.output = self.sink.start()
            if self.output is None:
                raise AudioEngineError("无法打开系统音频输出")
            self.timer = QTimer(self)
            self.engine._set_buffer_frames(self.sink.bufferSize() // self.engine._frame_bytes)
            self.target_frames = max(1024, self.engine._buffer_frames * 7 // 8)
            self.timer.setInterval(3)
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
        if self.sink:
            self.sink.stop()
        self.thread().quit()

    @Slot()
    def pump(self) -> None:
        if not self.engine._playing or self.sink is None or self.output is None:
            return
        if self.sink.state() == QAudio.State.StoppedState:
            self.engine.last_error = f"系统音频输出已停止：{self.sink.error()}"
            self.engine._playing = False
            return
        free_frames = max(0, self.sink.bytesFree()) // self.engine._frame_bytes
        queued_frames = max(0, self.engine._buffer_frames - free_frames)
        # Refill in larger blocks after a scheduling hiccup, while retaining a
        # bounded render call so a dense project cannot monopolise the thread.
        frames = min(1024, max(0, self.target_frames - queued_frames), free_frames)
        if frames:
            self.output.write(self.engine._read_pcm(frames * self.engine._frame_bytes))

    @Slot(QAudio.State)
    def _on_sink_state_changed(self, state: QAudio.State) -> None:
        if state in {QAudio.State.IdleState, QAudio.State.StoppedState} and self.engine._playing:
            self.engine._record_underrun()


class BdoRealtimeAudioEngine(QObject):
    """Editable Python module that powers BDO real-time editor preview."""

    output_stop_requested = Signal()

    def __init__(self, parent: QObject | None, source_config: dict[str, str]) -> None:
        super().__init__(parent)
        self.source_config = dict(source_config)
        self._lock = threading.RLock()
        self._events: list[_Event] = []
        self._event_frames = np.empty(0, dtype=np.int64)
        self._max_event_tail_frames = 0
        self._voices: list[_Voice] = []
        self._event_index = 0
        self._frame = 0
        self._duration_frames = 0
        self._playing = False
        self._cache_bytes = 0
        self._preload_loaded = 0
        self._preload_total = 0
        self._load_generation = 0
        self._buffer_frames = 0
        self._underruns = 0
        self._render_times_ms: deque[float] = deque(maxlen=240)
        self._unverified: list[str] = []
        self._cache: dict[tuple[str, int], _Sample] = {}
        self._output_thread: QThread | None = None
        self._output_worker: _AudioOutputWorker | None = None
        self._output_ready = threading.Event()
        # One coordinator preserves project ordering; independent WAV reads and
        # float conversion run in a bounded pool so a cold cache no longer
        # stalls on hundreds of serial disk reads.
        self._loader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bdo-project-loader")
        self._decode_workers = min(4, max(2, (os.cpu_count() or 2) // 2))
        self._decode_pool = ThreadPoolExecutor(max_workers=self._decode_workers, thread_name_prefix="bdo-wav-cache")
        self._load_future: Future[tuple[list[_Event], dict[tuple[str, int], _Sample], int, list[str], int]] | None = None
        self._format: QAudioFormat | None = None
        self._sample_rate = 48_000
        self._frame_bytes = 4
        self._mix_buffer = np.empty((0, 2), dtype=np.float32)
        self._timeline_buffer = np.empty(0, dtype=np.float32)
        self._voice_a = np.empty((0, 2), dtype=np.float32)
        self._voice_b = np.empty((0, 2), dtype=np.float32)
        self._voice_positions = np.empty(0, dtype=np.float32)
        self._voice_indices = np.empty(0, dtype=np.intp)
        self.last_error = ""

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

    def _set_buffer_frames(self, frames: int) -> None:
        with self._lock:
            self._buffer_frames = max(0, frames)

    def _record_underrun(self) -> None:
        with self._lock:
            self._underruns += 1

    def stop(self) -> None:
        self.cancel_loading()
        with self._lock:
            self._playing = False
            self._voices.clear()
            self._frame = 0
            self._event_index = 0
        if self._output_thread and self._output_thread.isRunning():
            self.output_stop_requested.emit()
            self._output_thread.wait(1000)
        self._output_worker = None
        self._output_thread = None

    def clear_playback(self) -> None:
        """Silence and invalidate current material without reopening the audio device."""
        self.cancel_loading()
        with self._lock:
            self._playing = False
            self._events = []
            self._event_frames = np.empty(0, dtype=np.int64)
            self._max_event_tail_frames = 0
            self._voices.clear()
            self._event_index = 0
            self._frame = 0
            self._duration_frames = 0

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
        if self._load_future and not self._load_future.done():
            self._load_future.cancel()
        with self._lock:
            self._load_generation += 1
            generation = self._load_generation
            self._preload_loaded = 0
            self._preload_total = 0
        self._load_future = self._loader.submit(
            self._prepare_project,
            list(tracks), map_path, start_ms, reverb, delay, chorus, cache_limit_bytes,
            generation,
        )

    def finish_loading(self, start_ms: float) -> dict[str, Any] | None:
        """Commit a completed asynchronous preload; returns ``None`` while loading."""
        future = self._load_future
        if future is None:
            return None
        if not future.done():
            return None
        self._load_future = None
        try:
            prepared = future.result()
        except AudioEngineError:
            raise
        except Exception as exc:
            raise AudioEngineError(f"游戏音源预取失败：{exc}") from exc
        return self._commit_project(*prepared, start_ms=start_ms)

    def is_loading(self) -> bool:
        return bool(self._load_future and not self._load_future.done())

    def cancel_loading(self) -> None:
        """Invalidate an in-flight preload so its result can never be committed."""
        with self._lock:
            self._load_generation += 1
            future = self._load_future
            self._load_future = None
            self._preload_loaded = 0
            self._preload_total = 0
        if future is not None and not future.done():
            future.cancel()

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
    ) -> tuple[list[_Event], dict[tuple[str, int], _Sample], int, list[str], int]:
        payload = json.loads(Path(map_path).read_text(encoding="utf-8"))
        banks: dict[str, list[dict]] = payload.get("banks", {})
        cache: dict[tuple[str, int], _Sample] = {}
        events: list[_Event] = []
        unverified: list[str] = []
        duration = 0
        # Resolve all note→zone relationships first.  Decoding is deduplicated
        # by Wwise source ID and happens concurrently below.
        resolved: list[tuple[Any, int, int, int, str, dict, tuple[str, int], float]] = []
        sources: dict[tuple[str, int], Path] = {}
        for track in tracks:
            instrument_id = int(track.bdo_instrument_id)
            synth_mode = str(getattr(track, "marnian_synth_mode", "basic") or "basic")
            bank = bank_for_instrument(instrument_id, synth_mode)
            if not bank or bank not in banks:
                unverified.append(f"0x{instrument_id:02x}: 未绑定已命名 BNK")
                continue
            if instrument_id in MARNIAN_SYNTH_WAVEFORM_BY_ID:
                unverified.append(
                    f"0x{instrument_id:02x}/{synth_mode}: provisional synth routing; game A/B required"
                )
            for note in track.notes:
                velocity = max(1, min(127, round(float(note.vel) * track.volume_scale)))
                ntype = int(getattr(note, "ntype", 0) or track.articulation_type or 0)
                if ntype == 26:
                    velocity = min(velocity, 69)
                elif ntype == 27:
                    velocity = max(70, min(99, velocity))
                elif ntype == 28:
                    velocity = max(100, velocity)
                pitch = resolve_bdo_pitch(instrument_id, int(note.pitch), ntype)
                if ntype not in (0, 99):
                    unverified.append(
                        f"0x{instrument_id:02x}/type {ntype}: 已启用近似奏法 DSP；待游戏 A/B"
                    )
                selected = select_wwise_zone(
                    banks, instrument_id, int(note.pitch), velocity, ntype, synth_mode
                )
                if not selected:
                    unverified.append(f"0x{instrument_id:02x}: pitch {pitch} velocity {velocity} 无 Wwise zone")
                    continue
                bank, row = selected
                key = (bank, int(row["source_id"]))
                path = Path(row["wav_path"])
                if not path.is_file():
                    path = Path(self.source_config["audio_root"]) / "乐器_WAV" / bank / f"{row['source_id']}.wav"
                sources.setdefault(key, path)
                resolved.append((
                    note, velocity, pitch, instrument_id, bank, row, key,
                    float(getattr(track, "duration_scale", 1.0)),
                ))

        with self._lock:
            cache.update({key: self._cache[key] for key in sources if key in self._cache})
        futures = {
            key: self._decode_pool.submit(self._decode_wav, path)
            for key, path in sources.items()
            if key not in cache
        }
        if load_generation is not None:
            with self._lock:
                if load_generation == self._load_generation:
                    self._preload_total = len(sources)
                    self._preload_loaded = len(cache)
        cache_bytes = sum(sample.pcm.nbytes for sample in cache.values())
        # Consume in source order for deterministic errors and cache limits;
        # futures still execute in parallel while we prepare this result.
        for key in sources:
            if key in cache:
                continue
            sample = futures[key].result()
            cache_bytes += sample.pcm.nbytes
            if cache_bytes > cache_limit_bytes:
                raise AudioEngineError(f"项目预取样本超过 {cache_limit_bytes // 1024 // 1024} MiB 缓存上限")
            cache[key] = sample
            if load_generation is not None:
                with self._lock:
                    if load_generation == self._load_generation:
                        self._preload_loaded += 1

        for note, velocity, pitch, _instrument_id, _bank, row, key, duration_scale in resolved:
            sample = cache[key]
            ratio = 2.0 ** ((pitch - int(row["root_note"])) / 12.0) * sample.rate / self._sample_rate
            frame = round(max(0.0, float(note.start)) * self._sample_rate / 1000.0)
            note_duration = max(
                1,
                round(
                    float(getattr(note, "dur", 0.0))
                    * duration_scale
                    * self._sample_rate / 1000.0
                ),
            )
            # Harmonics are represented by an octave-emphasised source in the
            # approximate preview. The serialized pitch and ntype stay intact.
            preview_ratio = ratio * (2.0 if ntype == 14 else 1.0)
            events.append(_Event(
                frame, sample, preview_ratio, velocity / 127.0 * 0.72,
                note_duration, _instrument_id, ntype,
            ))
            duration = max(duration, frame + math.ceil(sample.frames / ratio))
        if reverb or delay or chorus and any(chorus):
            unverified.append("全局混响/延迟/合唱：待游戏 A/B 校准")
        events.sort(key=lambda item: item.frame)
        return events, cache, cache_bytes, sorted(set(unverified)), duration

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
            self._events = events
            self._event_frames = np.fromiter((event.frame for event in events), dtype=np.int64, count=len(events))
            self._max_event_tail_frames = max(
                (math.ceil(event.sample.frames / event.ratio) for event in events),
                default=0,
            )
            self._voices = []
            self._event_index = 0
            self._frame = round(max(0.0, start_ms) * self._sample_rate / 1000.0)
            self._duration_frames = duration
            self._cache = cache
            self._cache_bytes = cache_bytes
            self._preload_loaded = self._preload_total
            self._underruns = 0
            self._render_times_ms.clear()
            self._unverified = unverified
            self._seek_locked(self._frame)
        return {"events": len(events), "samples": len(cache), "cache_bytes": cache_bytes, "unverified": self._unverified}

    @staticmethod
    def _decode_wav(path: Path) -> _Sample:
        try:
            with wave.open(str(path), "rb") as source:
                if source.getsampwidth() != 2:
                    raise AudioEngineError(f"不支持非 16-bit WAV：{path}")
                channels = source.getnchannels()
                rate = source.getframerate()
                raw = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        except (OSError, wave.Error) as exc:
            raise AudioEngineError(f"无法读取游戏 WAV：{path} ({exc})") from exc
        if channels < 1:
            raise AudioEngineError(f"无效 WAV 声道数：{path}")
        raw = raw.reshape(-1, channels)
        if channels == 1:
            pcm = np.repeat(raw, 2, axis=1)
        else:
            pcm = raw[:, :2]
        pcm, _gain = normalise_sample_loudness(pcm)
        return _Sample(pcm, rate, len(pcm))

    def play(self) -> None:
        self.start()
        with self._lock:
            self._playing = bool(self._events)

    def pause(self) -> None:
        with self._lock:
            self._playing = False

    def seek(self, position_ms: float) -> None:
        with self._lock:
            self._seek_locked(round(max(0.0, position_ms) * self._sample_rate / 1000.0))

    def _seek_locked(self, frame: int) -> None:
        self._frame = frame
        if len(self._event_frames) != len(self._events):
            self._event_frames = np.fromiter((event.frame for event in self._events), dtype=np.int64, count=len(self._events))
            self._max_event_tail_frames = max(
                (math.ceil(event.sample.frames / event.ratio) for event in self._events),
                default=0,
            )
        self._event_index = int(np.searchsorted(self._event_frames, frame, side="left"))
        self._voices = []
        earliest_frame = frame - self._max_event_tail_frames
        for event in reversed(self._events[:self._event_index]):
            if event.frame < earliest_frame:
                break
            position = (frame - event.frame) * event.ratio
            if position < event.sample.frames:
                self._start_event(event, max(0, frame - event.frame))

    def _start_voice(
        self, sample: _Sample, position: float, ratio: float, gain: float,
        duration_frames: int = 0, instrument_id: int = 0, ntype: int = 0,
        age_frames: int = 0,
    ) -> None:
        if len(self._voices) >= 256:
            quietest_index = min(range(len(self._voices)), key=lambda index: self._voices[index].gain)
            self._voices.pop(quietest_index)
        self._voices.append(_Voice(
            sample, position, ratio, gain, duration_frames, instrument_id, ntype, age_frames
        ))

    def _start_event(self, event: _Event, age_frames: int = 0) -> None:
        self._start_voice(
            event.sample, age_frames * event.ratio, event.ratio, event.gain,
            event.duration_frames, event.instrument_id, event.ntype, age_frames,
        )
        # Harp chord note types are Wwise-generated note stacks. Recreate the
        # audible chord while retaining the single serialized BDO note.
        intervals = (4, 7) if event.ntype == 9 else ((3, 7) if event.ntype == 10 else ())
        for semitones in intervals:
            chord_ratio = event.ratio * (2.0 ** (semitones / 12.0))
            self._start_voice(
                event.sample, age_frames * chord_ratio,
                chord_ratio, event.gain * 0.52,
                event.duration_frames, event.instrument_id, 0, age_frames,
            )

    def _read_pcm(self, max_bytes: int) -> bytes:
        frames = max(1, max_bytes // self._frame_bytes)
        started = time.perf_counter()
        with self._lock:
            audio = self._render_locked(frames)
            if self._format and self._format.sampleFormat() == QAudioFormat.SampleFormat.Float:
                payload = np.ascontiguousarray(audio, dtype=np.float32).tobytes()
            else:
                payload = np.ascontiguousarray(np.clip(audio, -1.0, 1.0) * 32767, dtype="<i2").tobytes()
            self._render_times_ms.append((time.perf_counter() - started) * 1000.0)
        return payload

    def _ensure_render_buffers(self, frames: int) -> None:
        if len(self._timeline_buffer) < frames:
            self._timeline_buffer = np.arange(frames, dtype=np.float32)
            self._voice_positions = np.empty(frames, dtype=np.float32)
            self._voice_indices = np.empty(frames, dtype=np.intp)
        if len(self._mix_buffer) < frames:
            self._mix_buffer = np.empty((frames, 2), dtype=np.float32)
            self._voice_a = np.empty((frames, 2), dtype=np.float32)
            self._voice_b = np.empty((frames, 2), dtype=np.float32)

    def _mix_single_voice(self, output: np.ndarray, length: int, voice: _Voice) -> None:
        sample = voice.sample
        start = voice.position
        if sample.frames < 2 or start >= sample.frames - 1:
            return
        active = min(length, max(0, math.ceil((sample.frames - 1 - start) / voice.ratio)))
        if active <= 0:
            return
        first = self._voice_a[:active]
        if voice.ratio == 1.0 and start.is_integer():
            offset = int(start)
            np.multiply(sample.pcm[offset:offset + active], voice.gain, out=first)
            self._apply_articulation_to_voice(first, active, voice)
            output[:active] += first
            return
        positions = self._voice_positions[:active]
        indices = self._voice_indices[:active]
        np.multiply(self._timeline_buffer[:active], voice.ratio, out=positions)
        positions += start
        np.copyto(indices, positions, casting="unsafe")
        # Float rounding can turn a position infinitesimally below the final
        # frame into ``frames - 1`` when truncated.  Interpolation needs both
        # base and base + 1, so clamp the base before either gather.
        np.clip(indices, 0, sample.frames - 2, out=indices)
        positions -= indices
        np.take(sample.pcm, indices, axis=0, out=first)
        indices += 1
        np.take(sample.pcm, indices, axis=0, out=self._voice_b[:active])
        self._voice_b[:active] -= first
        self._voice_b[:active] *= positions[:, None]
        first += self._voice_b[:active]
        first *= voice.gain
        self._apply_articulation_to_voice(first, active, voice)
        output[:active] += first

    def _apply_articulation_to_voice(self, pcm: np.ndarray, active: int, voice: _Voice) -> None:
        ntype = int(getattr(voice, "ntype", 0))
        if ntype in {0, 9, 10, 99} or active <= 0:
            return
        ages = self._voice_positions[:active]
        np.add(self._timeline_buffer[:active], voice.age_frames, out=ages)
        envelope = articulation_preview_envelope(
            int(getattr(voice, "instrument_id", 0)), ntype, ages,
            int(getattr(voice, "duration_frames", 0)), self._sample_rate,
        )
        pcm *= envelope[:, None]
        # A gentle nonlinear colour distinguishes the brass/filter and slap
        # families without pretending to reproduce an unknown Wwise plug-in.
        if ntype in {21, 22}:
            np.tanh(pcm * 1.35, out=pcm)

    def _render_locked(self, frames: int) -> np.ndarray:
        self._ensure_render_buffers(frames)
        output = self._mix_buffer[:frames]
        output.fill(0.0)
        if not self._playing:
            return output
        written = 0
        while written < frames:
            next_event = self._events[self._event_index].frame if self._event_index < len(self._events) else None
            segment_end = frames if next_event is None else min(frames, max(written, next_event - self._frame + written))
            length = segment_end - written
            if length:
                timeline = self._timeline_buffer[:length]
                alive: list[_Voice] = []
                groups: dict[int, tuple[_Sample, list[_Voice]]] = {}
                for voice in self._voices:
                    groups.setdefault(id(voice.sample), (voice.sample, []))[1].append(voice)
                for sample, voices in groups.values():
                    if len(voices) <= 4 or any(voice.ntype not in {0, 99} for voice in voices):
                        # Small unisons are common and the vectorised branch
                        # used to allocate several 2-D/3-D temporaries per
                        # segment.  Reusing the single-voice buffers is faster
                        # and removes GC pressure for this hot case.
                        for voice in voices:
                            self._mix_single_voice(output[written:written + length], length, voice)
                            voice.position += length * voice.ratio
                            voice.age_frames += length
                            if voice.position < sample.frames - 1:
                                alive.append(voice)
                        continue
                    starts = np.asarray([voice.position for voice in voices], dtype=np.float32)
                    ratios = np.asarray([voice.ratio for voice in voices], dtype=np.float32)
                    gains = np.asarray([voice.gain for voice in voices], dtype=np.float32)
                    indices = starts[:, None] + ratios[:, None] * timeline[None, :]
                    valid = indices < sample.frames - 1
                    base = np.clip(indices.astype(np.int64), 0, sample.frames - 2)
                    fraction = (indices - base)[..., None].astype(np.float32)
                    first = sample.pcm[base]
                    second = sample.pcm[base + 1]
                    interpolated = first + (second - first) * fraction
                    interpolated *= valid[..., None]
                    output[written:written + length] += (interpolated * gains[:, None, None]).sum(axis=0)
                    for voice in voices:
                        voice.position += length * voice.ratio
                        voice.age_frames += length
                        if voice.position < sample.frames - 1:
                            alive.append(voice)
                self._voices = alive
                self._frame += length
                written += length
            while self._event_index < len(self._events) and self._events[self._event_index].frame <= self._frame:
                event = self._events[self._event_index]
                self._start_event(event)
                self._event_index += 1
            if length == 0 and next_event is None:
                break
        if self._frame >= self._duration_frames and not self._voices:
            self._playing = False
        soft_limit_in_place(output)
        return output

    def get_status(self) -> AudioStatus:
        with self._lock:
            state = "playing" if self._playing else ("paused" if self._events else "stopped")
            render_times = sorted(self._render_times_ms)
            render_p95 = render_times[round((len(render_times) - 1) * 0.95)] if render_times else 0.0
            return AudioStatus(
                state=state,
                position_ms=self._frame * 1000.0 / self._sample_rate,
                duration_ms=self._duration_frames * 1000.0 / self._sample_rate,
                sample_rate=self._sample_rate,
                buffer_frames=self._buffer_frames,
                cache_bytes=self._cache_bytes,
                preload_loaded=self._preload_loaded,
                preload_total=self._preload_total,
                preload_progress=(
                    min(1.0, self._preload_loaded / self._preload_total)
                    if self._preload_total else (1.0 if self._events else 0.0)
                ),
                underruns=self._underruns,
                render_p95_ms=render_p95,
                render_max_ms=max(render_times, default=0.0),
                unverified=list(self._unverified),
            )
