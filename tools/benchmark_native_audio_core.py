#!/usr/bin/env python3
"""Benchmark the optional original C++ mixer with a bounded projected plan."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_music_composer.audio.native_audio_core import (  # noqa: E402
    NativeAudioCore,
    NativePlaybackEventV1,
)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)] if ordered else 0.0


def benchmark_native_audio_core(
    *,
    voices: int,
    unique_samples: int,
    sample_rate: int,
    block_frames: int,
    blocks: int,
) -> dict[str, object]:
    voice_count = max(1, min(256, int(voices)))
    sample_count = max(1, min(voice_count, int(unique_samples)))
    frames = max(2, int(block_frames))
    sample_frames = max(4_096, frames * 4)
    phase = np.arange(sample_frames, dtype=np.float32)
    samples = [
        np.column_stack((
            np.sin(
                phase * (2.0 * math.pi * (110.0 + index * 7.0) / sample_rate),
                dtype=np.float32,
            ) * 0.01,
            np.sin(
                phase * (2.0 * math.pi * (111.0 + index * 7.0) / sample_rate),
                dtype=np.float32,
            ) * 0.01,
        ))
        for index in range(sample_count)
    ]
    duration_frames = frames * (max(1, int(blocks)) + 2)
    gain = 0.7 / math.sqrt(voice_count)
    events = [
        NativePlaybackEventV1(
            0,
            index % sample_count,
            2.0 ** (((index % 25) - 12) / 12.0),
            gain,
            duration_frames,
            0,
            sample_frames,
        )
        for index in range(voice_count)
    ]
    times: list[float] = []
    with NativeAudioCore(sample_rate, max_voices=256) as core:
        started = time.perf_counter()
        core.load_plan(samples, events)
        prepare_ms = (time.perf_counter() - started) * 1_000.0
        core.render(frames)
        for _ in range(max(1, int(blocks))):
            started = time.perf_counter()
            core.render(frames)
            times.append((time.perf_counter() - started) * 1_000.0)
        steals = core.voice_steals
        active_voices = core.active_voices
    budget_ms = frames * 1_000.0 / sample_rate
    return {
        "voices": voice_count,
        "unique_samples": sample_count,
        "sample_rate": sample_rate,
        "block_frames": frames,
        "blocks": max(1, int(blocks)),
        "block_budget_ms": budget_ms,
        "prepare_ms": prepare_ms,
        "render_p50_ms": statistics.median(times),
        "render_p95_ms": _percentile(times, 0.95),
        "render_p99_ms": _percentile(times, 0.99),
        "render_p999_ms": _percentile(times, 0.999),
        "render_max_ms": max(times, default=0.0),
        "render_p99_load": _percentile(times, 0.99) / budget_ms,
        "active_voices": active_voices,
        "voice_steals": steals,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "abi": 1,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", type=int, default=176)
    parser.add_argument("--unique-samples", type=int, default=32)
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--block-frames", type=int, default=256)
    parser.add_argument("--blocks", type=int, default=1_000)
    args = parser.parse_args()
    result = benchmark_native_audio_core(
        voices=args.voices,
        unique_samples=args.unique_samples,
        sample_rate=max(1, args.sample_rate),
        block_frames=max(2, args.block_frames),
        blocks=max(1, args.blocks),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
