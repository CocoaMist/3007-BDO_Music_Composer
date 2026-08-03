#!/usr/bin/env python3
"""Benchmark indexed transcription-candidate review scope queries."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_music_composer.transcription.bdo_transcription_session import TranscriptionSession  # noqa: E402


@dataclass(frozen=True, slots=True)
class Candidate:
    pitch: int
    velocity: int
    start_ms: float
    duration_ms: float
    candidate_id: str


def _benchmark(size: int, iterations: int) -> dict[str, object]:
    candidates = tuple(
        Candidate(
            48 + index % 36,
            90,
            float(index * 10),
            80.0,
            f"candidate-{index}",
        )
        for index in range(size)
    )
    started = time.perf_counter()
    session = TranscriptionSession(candidates)
    index_build_ms = (time.perf_counter() - started) * 1_000.0

    target_index = size * 3 // 4
    offset_ms = 725.0
    project_start_ms = float(target_index * 10) + offset_ms
    session.set_region(project_start_ms, project_start_ms + 101.0)
    expected = session.eligible_candidate_ids(
        reference_audio_offset_ms=offset_ms
    )
    samples_us: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        result = session.eligible_candidate_ids(
            reference_audio_offset_ms=offset_ms
        )
        samples_us.append((time.perf_counter() - started) * 1_000_000.0)
        if result != expected:
            raise RuntimeError("candidate query became nondeterministic")

    return {
        "candidates": size,
        "index_build_ms": index_build_ms,
        "query_result_count": len(expected),
        "query_inspections": session.last_candidate_range_query_inspections,
        "query_median_us": statistics.median(samples_us),
        "query_max_us": max(samples_us, default=0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="10000,50000,100000")
    parser.add_argument("--iterations", type=int, default=500)
    args = parser.parse_args()
    try:
        sizes = tuple(
            max(1, int(value.strip()))
            for value in args.sizes.split(",")
            if value.strip()
        )
    except ValueError as exc:
        parser.error(f"invalid --sizes: {exc}")
    if not sizes:
        parser.error("--sizes must contain at least one positive integer")
    results = [
        _benchmark(size, max(1, int(args.iterations)))
        for size in sizes
    ]
    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
