#!/usr/bin/env python3
"""Benchmark the real-time mixer without accidentally double-driving it.

Offline mode is the deterministic default: it never opens QAudioSink and one
caller advances the mixer using the production low/high-water refill policy.
``--mode sink`` is an explicit device integration run; the QAudio worker is then
the only PCM producer and this process merely samples status.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import threading
import time
from collections import Counter, namedtuple
from pathlib import Path
from typing import Any

import numpy as np
import PySide6
from PySide6.QtCore import QCoreApplication


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_music_composer.audio.bdo_realtime_audio import (  # noqa: E402
    AUDIO_BUFFER_MS,
    AUDIO_MIN_RENDER_FRAMES,
    AUDIO_NOMINAL_QUEUE_MS,
    AUDIO_PRESSURE_REFILL_TARGET_RATIO,
    AUDIO_REFILL_TARGET_RATIO,
    AUDIO_RENDER_PRESSURE_THRESHOLD,
    AUDIO_RENDER_BLOCK_FRAMES,
    BANK_BY_ID,
    BdoRealtimeAudioEngine,
    DENSE_REFILL_VOICE_THRESHOLD,
    _AudioOutputWorker,
    _Event,
    _Sample,
)
from bdo_music_composer.core.project_paths import WWISE_MIDI_MAP_PATH  # noqa: E402


Note = namedtuple("Note", "pitch vel start dur ntype")
Track = namedtuple(
    "Track",
    "track_id bdo_instrument_id is_percussion volume_scale "
    "duration_scale articulation_type notes",
)

EFFECT_REVERB_SEND = 0.35
EFFECT_DELAY_SEND = 0.25
EFFECT_CHORUS_SEND = 0.20
EFFECT_AUTHORING_VALUE = 50


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def build_synthetic_engine(
    voices: int,
    seconds: float,
    sample_rate: int = 36_000,
    *,
    effect_preview: bool = False,
    unique_samples: int = 1,
) -> BdoRealtimeAudioEngine:
    """Create a device-free, loop-backed workload requiring no local samples."""
    voice_count = max(1, min(256, int(voices)))
    duration_frames = max(1, round(max(0.01, seconds) * sample_rate))
    sample_frames = 4_096
    phase = np.arange(sample_frames, dtype=np.float32)
    phase *= 2.0 * math.pi * 220.0 / sample_rate
    mono = np.sin(phase, dtype=np.float32) * 0.025
    sample_count = max(1, min(voice_count, int(unique_samples)))
    samples = tuple(
        _Sample(
            np.column_stack((mono * (1.0 - index * 0.001), mono)),
            sample_rate,
            sample_frames,
            sample_frames,
        )
        for index in range(sample_count)
    )
    gain = 0.7 / math.sqrt(voice_count)
    events = [
        _Event(
            frame=0,
            sample=samples[index % sample_count],
            ratio=2.0 ** (((index % 25) - 12) / 12.0),
            gain=gain,
            duration_frames=duration_frames,
            instrument_id=0x0A,
            track_slot=index % 16,
            track_id=index % 16,
            audible_frames=duration_frames,
            fade_out_frames=max(1, round(sample_rate * 0.012)),
            loop_start_frame=0,
            loop_end_frame=sample_frames,
            reverb_send=EFFECT_REVERB_SEND if effect_preview else 0.0,
            delay_send=EFFECT_DELAY_SEND if effect_preview else 0.0,
            chorus_send=EFFECT_CHORUS_SEND if effect_preview else 0.0,
            reverb_time=EFFECT_AUTHORING_VALUE if effect_preview else 0,
            delay_feedback=EFFECT_AUTHORING_VALUE if effect_preview else 0,
            chorus_feedback=EFFECT_AUTHORING_VALUE if effect_preview else 0,
            chorus_lfo_depth=EFFECT_AUTHORING_VALUE if effect_preview else 0,
            chorus_lfo_frequency=EFFECT_AUTHORING_VALUE if effect_preview else 0,
        )
        for index in range(voice_count)
    ]
    engine = BdoRealtimeAudioEngine(
        None,
        {"paz_root": "", "audio_root": ""},
    )
    with engine._lock:
        engine._sample_rate = sample_rate
        engine._frame_bytes = 4
        engine._events = events
        engine._event_frames = np.zeros(len(events), dtype=np.int64)
        engine._max_event_tail_frames = duration_frames
        engine._voices = []
        engine._event_index = 0
        engine._frame = 0
        engine._duration_frames = duration_frames
        engine._playing = True
        engine._paused = False
        engine._track_meter_ids = list(range(16))
        engine._track_peaks = np.zeros(16, dtype=np.float32)
        engine._track_block_peaks = np.zeros(16, dtype=np.float32)
        engine._configure_preview_effects(events)
    return engine


def enable_effect_preview(engine: BdoRealtimeAudioEngine) -> None:
    """Apply one stable, intentionally approximate all-effects workload."""

    with engine._lock:
        for event in engine._events:
            event.reverb_send = EFFECT_REVERB_SEND
            event.delay_send = EFFECT_DELAY_SEND
            event.chorus_send = EFFECT_CHORUS_SEND
            event.reverb_time = EFFECT_AUTHORING_VALUE
            event.delay_feedback = EFFECT_AUTHORING_VALUE
            event.chorus_feedback = EFFECT_AUTHORING_VALUE
            event.chorus_lfo_depth = EFFECT_AUTHORING_VALUE
            event.chorus_lfo_frequency = EFFECT_AUTHORING_VALUE
        engine._configure_preview_effects(engine._events)


def _configure_offline_worker(
    engine: BdoRealtimeAudioEngine,
    *,
    render_block_frames: int = AUDIO_RENDER_BLOCK_FRAMES,
) -> _AudioOutputWorker:
    """Mirror production buffer policy without constructing a QAudioSink."""
    engine._buffer_frames = max(
        render_block_frames,
        engine._sample_rate * AUDIO_BUFFER_MS // 1000,
    )
    worker = _AudioOutputWorker(
        engine,
        render_block_frames=render_block_frames,
    )
    worker.target_frames = max(
        render_block_frames,
        min(
            engine._buffer_frames,
            round(engine._sample_rate * AUDIO_NOMINAL_QUEUE_MS / 1000.0),
        ),
    )
    worker.low_water_frames = max(
        0,
        worker.target_frames - AUDIO_MIN_RENDER_FRAMES,
    )
    return worker


def run_offline_benchmark(
    engine: BdoRealtimeAudioEngine,
    seconds: float,
    *,
    seek_interval_s: float = 0.0,
    render_block_frames: int = AUDIO_RENDER_BLOCK_FRAMES,
) -> dict[str, Any]:
    """Run one deterministic mixer producer with production refill quanta."""
    worker = _configure_offline_worker(
        engine,
        render_block_frames=render_block_frames,
    )
    target_frames = max(1, round(max(0.01, seconds) * engine._sample_rate))
    rendered_frames = 0
    free_frames = engine._buffer_frames
    next_seek_frame = (
        max(1, round(seek_interval_s * engine._sample_rate))
        if seek_interval_s > 0.0
        else 0
    )
    seek_frames = next_seek_frame
    seek_count = 0
    seek_times: list[float] = []
    render_times: list[float] = []
    render_loads: list[float] = []
    block_counts: Counter[int] = Counter()
    peak_voices = len(engine._voices)
    started = time.perf_counter()

    while rendered_frames < target_frames and engine._playing:
        frames = worker._refill_frame_count(free_frames)
        if frames <= 0:
            # Advance the virtual device to the same low-water boundary that
            # wakes the production worker. No second mixer caller is involved.
            active_voices, render_load, underruns = (
                engine._render_pressure_snapshot()
            )
            low_water_frames = worker.low_water_frames
            if active_voices >= DENSE_REFILL_VOICE_THRESHOLD:
                target_ratio = (
                    AUDIO_PRESSURE_REFILL_TARGET_RATIO
                    if render_load >= AUDIO_RENDER_PRESSURE_THRESHOLD or underruns
                    else AUDIO_REFILL_TARGET_RATIO
                )
                dense_target = max(
                    worker.target_frames,
                    round(engine._buffer_frames * target_ratio),
                )
                low_water_frames = max(
                    low_water_frames,
                    dense_target - AUDIO_MIN_RENDER_FRAMES,
                )
            free_frames = engine._buffer_frames - low_water_frames
            continue
        block_started = time.perf_counter()
        engine._read_pcm(frames * engine._frame_bytes)
        elapsed_ms = (time.perf_counter() - block_started) * 1000.0
        render_times.append(elapsed_ms)
        render_loads.append(
            elapsed_ms / (frames * 1000.0 / engine._sample_rate)
        )
        block_counts[frames] += 1
        rendered_frames += frames
        peak_voices = max(peak_voices, engine._active_voice_count_snapshot())
        active_voices, render_load, underruns = (
            engine._render_pressure_snapshot()
        )
        low_water_frames = worker.low_water_frames
        if active_voices >= DENSE_REFILL_VOICE_THRESHOLD:
            target_ratio = (
                AUDIO_PRESSURE_REFILL_TARGET_RATIO
                if render_load >= AUDIO_RENDER_PRESSURE_THRESHOLD or underruns
                else AUDIO_REFILL_TARGET_RATIO
            )
            dense_target = max(
                worker.target_frames,
                round(engine._buffer_frames * target_ratio),
            )
            low_water_frames = max(
                low_water_frames,
                dense_target - AUDIO_MIN_RENDER_FRAMES,
            )
        free_frames = engine._buffer_frames - low_water_frames

        if next_seek_frame and rendered_frames >= seek_frames:
            duration_ms = engine._duration_frames * 1000.0 / engine._sample_rate
            target_ms = min(
                max(0.0, duration_ms - 1.0),
                duration_ms * (0.2 if seek_count % 2 == 0 else 0.6),
            )
            seek_started = time.perf_counter()
            engine.seek(target_ms)
            engine._complete_output_reset(engine._output_reset_snapshot())
            seek_times.append((time.perf_counter() - seek_started) * 1000.0)
            seek_frames += next_seek_frame
            seek_count += 1

    wall_seconds = time.perf_counter() - started
    status = engine.get_status()
    return {
        "mode": "offline",
        "simulated_seconds": rendered_frames / engine._sample_rate,
        "wall_seconds": wall_seconds,
        "realtime_factor": (
            rendered_frames / engine._sample_rate / wall_seconds
            if wall_seconds > 0.0
            else 0.0
        ),
        "sample_rate": engine._sample_rate,
        "render_block_frames": int(render_block_frames),
        "buffer_frames": engine._buffer_frames,
        "block_distribution": {
            str(frames): count
            for frames, count in sorted(block_counts.items())
        },
        "render_p50_ms": _percentile(render_times, 0.50),
        "render_p95_ms": _percentile(render_times, 0.95),
        "render_p99_ms": _percentile(render_times, 0.99),
        "render_p999_ms": _percentile(render_times, 0.999),
        "render_max_ms": max(render_times, default=0.0),
        "render_p95_load": _percentile(render_loads, 0.95),
        "render_p99_load": _percentile(render_loads, 0.99),
        "active_voices": status.active_voices,
        "active_voices_peak": peak_voices,
        "voice_steals": status.voice_steals,
        "seek_p95_ms": _percentile(seek_times, 0.95) if seek_times else None,
        "underruns": status.underruns,
    }


def _actual_track(voices: int) -> Track:
    notes = [
        Note(48 + (index % 36), 96, (index // 16) * 120, 1_000, 0)
        for index in range(max(1, min(256, voices)))
    ]
    return Track(1, 0x0A, False, 0.7, 1.0, None, notes)


def _actual_tracks(
    voices: int,
    seconds: float,
    workload: str,
) -> list[Track]:
    """Build either the legacy guitar case or a simultaneous game-bank mix."""

    if workload == "single":
        return [_actual_track(voices)]
    instrument_ids = sorted(BANK_BY_ID)
    requested = max(1, min(256, int(voices)))
    duration_ms = max(100, round(max(0.1, seconds) * 1000.0))
    notes_by_instrument: dict[int, list[Note]] = {
        instrument_id: [] for instrument_id in instrument_ids
    }
    for index in range(requested):
        instrument_id = instrument_ids[index % len(instrument_ids)]
        local_index = index // len(instrument_ids)
        notes_by_instrument[instrument_id].append(
            Note(
                48 + (local_index % 8),
                96,
                0,
                duration_ms,
                99 if instrument_id == 0x0D else 0,
            )
        )
    return [
        Track(
            track_index + 1,
            instrument_id,
            instrument_id == 0x0D,
            0.7,
            1.0,
            None,
            notes_by_instrument[instrument_id],
        )
        for track_index, instrument_id in enumerate(instrument_ids)
        if notes_by_instrument[instrument_id]
    ]


def _prepare_actual_offline(
    engine: BdoRealtimeAudioEngine,
    tracks: list[Track],
) -> float:
    engine._ensure_preload_executors()
    started = time.perf_counter()
    prepared = engine._prepare_project(
        tracks,
        WWISE_MIDI_MAP_PATH,
        0.0,
        0,
        0,
        None,
        768 * 1024 * 1024,
    )
    engine._commit_project(*prepared, start_ms=0.0)
    engine._complete_output_reset(engine._output_reset_snapshot())
    with engine._lock:
        engine._playing = bool(engine._events)
        engine._paused = False
    return (time.perf_counter() - started) * 1000.0


def run_sink_benchmark(
    engine: BdoRealtimeAudioEngine,
    seconds: float,
) -> dict[str, Any]:
    """Let the real QAudio worker be the sole timeline producer."""
    block_counts: Counter[int] = Counter()
    render_times: list[float] = []
    block_counts_lock = threading.Lock()
    original_read_pcm = engine._read_pcm

    def counted_read_pcm(max_bytes: int) -> bytes:
        started = time.perf_counter()
        with block_counts_lock:
            block_counts[max(1, max_bytes // engine._frame_bytes)] += 1
        payload = original_read_pcm(max_bytes)
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        with block_counts_lock:
            render_times.append(elapsed_ms)
        return payload

    engine._read_pcm = counted_read_pcm  # type: ignore[method-assign]
    engine.play()
    deadline = time.monotonic() + max(0.01, seconds)
    peak_voices = 0
    app = QCoreApplication.instance()
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        status = engine.get_status()
        peak_voices = max(peak_voices, status.active_voices)
        if status.state == "stopped":
            break
        time.sleep(0.005)
    status = engine.get_status()
    with block_counts_lock:
        block_distribution = {
            str(frames): count
            for frames, count in sorted(block_counts.items())
        }
        measured_render_times = tuple(render_times)
    return {
        "mode": "sink",
        "simulated_seconds": status.position_ms / 1000.0,
        "sample_rate": status.sample_rate,
        "buffer_frames": status.buffer_frames,
        "block_distribution": block_distribution,
        "render_p50_ms": _percentile(list(measured_render_times), 0.50),
        "render_p95_ms": _percentile(list(measured_render_times), 0.95),
        "render_p99_ms": _percentile(list(measured_render_times), 0.99),
        "render_p999_ms": _percentile(list(measured_render_times), 0.999),
        "render_max_ms": max(measured_render_times, default=status.render_max_ms),
        "render_p95_load": status.render_p95_load,
        "active_voices": status.active_voices,
        "active_voices_peak": peak_voices,
        "voice_steals": status.voice_steals,
        "seek_p95_ms": None,
        "underruns": status.underruns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--voices", type=int, default=256)
    parser.add_argument("--sample-rate", type=int, default=36_000)
    parser.add_argument(
        "--render-block-frames",
        type=int,
        default=AUDIO_RENDER_BLOCK_FRAMES,
        help="offline render quantum; use 128/256/512 for low-latency diagnostics",
    )
    parser.add_argument(
        "--synthetic-samples",
        type=int,
        default=1,
        help="number of distinct synthetic PCM sources distributed across voices",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "sink"),
        default="offline",
        help="offline is device-free; sink explicitly tests the real device",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="use built-in looped PCM and no local game-audio files",
    )
    parser.add_argument(
        "--seek-interval",
        type=float,
        default=0.0,
        help="offline-only simulated seconds between seek checks; 0 disables",
    )
    parser.add_argument(
        "--audio-root",
        default=os.environ.get("BDO_AUDIO_ROOT", ""),
        help="root containing 乐器_WAV; omitted defaults to synthetic input",
    )
    parser.add_argument(
        "--workload",
        choices=("single", "multitrack"),
        default="single",
        help="game-sample layout: legacy guitar notes or simultaneous banks",
    )
    parser.add_argument(
        "--disable-cross-source-arena",
        action="store_true",
        help="diagnostic baseline that keeps same-source tiles only",
    )
    parser.add_argument(
        "--effects",
        action="store_true",
        help="enable a stable local reverb/delay/chorus stress workload",
    )
    args = parser.parse_args()
    if args.effects and args.mode != "offline":
        parser.error("--effects currently requires --mode offline")
    app = QCoreApplication.instance() or QCoreApplication([])
    use_synthetic = args.synthetic or not args.audio_root
    tracks = _actual_tracks(args.voices, args.seconds, args.workload)
    prepare_ms = 0.0
    if use_synthetic:
        engine = build_synthetic_engine(
            args.voices,
            args.seconds,
            args.sample_rate,
            effect_preview=args.effects,
            unique_samples=args.synthetic_samples,
        )
    else:
        engine = BdoRealtimeAudioEngine(
            None,
            {"paz_root": "", "audio_root": args.audio_root},
        )
        if args.mode == "offline":
            engine._sample_rate = args.sample_rate
            prepare_ms = _prepare_actual_offline(engine, tracks)
            if args.disable_cross_source_arena:
                engine._sample_arena = None
        else:
            started = time.perf_counter()
            engine.load_project(
                tracks,
                WWISE_MIDI_MAP_PATH,
                0.0,
            )
            prepare_ms = (time.perf_counter() - started) * 1000.0

    if args.effects and not use_synthetic:
        enable_effect_preview(engine)

    try:
        if args.mode == "offline":
            result = run_offline_benchmark(
                engine,
                args.seconds,
                seek_interval_s=args.seek_interval,
                render_block_frames=max(1, args.render_block_frames),
            )
        else:
            result = run_sink_benchmark(engine, args.seconds)
    finally:
        engine.stop()
    result.update({
        "input": "synthetic" if use_synthetic else "game_samples",
        "workload": "synthetic" if use_synthetic else args.workload,
        "voices_requested": max(1, min(256, args.voices)),
        "prepare_ms": prepare_ms,
        "events_prepared": len(engine._events),
        "unique_samples": len({id(event.sample) for event in engine._events}),
        "cross_source_arena": bool(engine._sample_arena is not None),
        "effects": bool(args.effects),
        "effect_workload": (
            {
                "reverb_send": EFFECT_REVERB_SEND,
                "delay_send": EFFECT_DELAY_SEND,
                "chorus_send": EFFECT_CHORUS_SEND,
                "authoring_values": EFFECT_AUTHORING_VALUE,
            }
            if args.effects
            else None
        ),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pyside": PySide6.__version__,
            "numpy": np.__version__,
        },
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
