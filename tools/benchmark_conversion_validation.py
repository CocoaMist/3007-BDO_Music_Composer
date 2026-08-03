#!/usr/bin/env python3
"""Benchmark cold validation and revision-scoped snapshot reuse."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_midi import Note  # noqa: E402
from bdo_music_composer.core.bdo_profile import load_bdo_profile  # noqa: E402
from bdo_music_composer.export.bdo_validation import ValidationContext, validate_tracks  # noqa: E402
from bdo_music_composer.app.conversion_validation_controller import (  # noqa: E402
    ConversionValidationController,
)
from bdo_music_composer.editor.editor_models import TrackState  # noqa: E402
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan  # noqa: E402
from bdo_music_composer.core.project_paths import PROFILES_DIR  # noqa: E402


INSTRUMENT_ID = 0x0B


def _tracks(note_count: int, track_count: int = 4) -> list[TrackState]:
    tracks: list[TrackState] = []
    remaining = max(1, int(note_count))
    for track_id in range(max(1, int(track_count))):
        count = remaining // (track_count - track_id)
        remaining -= count
        notes = [
            Note(60, 90, float(index) * 125.0, 100.0, 0)
            for index in range(count)
        ]
        tracks.append(
            TrackState(
                track_id,
                notes,
                0,
                False,
                f"track-{track_id}",
                INSTRUMENT_ID,
            )
        )
    return tracks


def benchmark(
    sizes: tuple[int, ...],
    *,
    cached_iterations: int,
) -> dict[str, object]:
    profile = load_bdo_profile(PROFILES_DIR / "bdo_global_v9.json")
    controller = ConversionValidationController(validate_tracks)
    results: dict[str, object] = {}
    for revision, size in enumerate(sizes, start=1):
        tracks = _tracks(size)
        context = ValidationContext(
            transpose=0,
            active_track_ids=frozenset(track.track_id for track in tracks),
            instrument_names={INSTRUMENT_ID: "Test instrument"},
            gm_drum_map={},
            serialize_instrument=lambda track: int(track.bdo_instrument_id),
            pitch_plan=PitchTransformPlan(),
        )
        started = time.perf_counter()
        snapshot = controller.snapshot(
            revision=revision,
            scope_key="source",
            tracks=tracks,
            profile=profile,
            context=context,
        )
        cold_ms = (time.perf_counter() - started) * 1000.0

        cached_us: list[float] = []
        reused = True
        for _ in range(max(1, cached_iterations)):
            started = time.perf_counter()
            current = controller.snapshot(
                revision=revision,
                scope_key="source",
                tracks=tracks,
                profile=profile,
                context=context,
            )
            cached_us.append((time.perf_counter() - started) * 1_000_000.0)
            reused = reused and current is snapshot
        results[str(size)] = {
            "cold_ms": cold_ms,
            "cached_median_us": statistics.median(cached_us),
            "cached_max_us": max(cached_us),
            "issue_count": len(snapshot.issues),
            "snapshot_reused": reused,
        }
    return {
        "sizes": list(sizes),
        "cached_iterations": max(1, cached_iterations),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="10000,50000,100000")
    parser.add_argument("--cached-iterations", type=int, default=100)
    args = parser.parse_args()
    sizes = tuple(
        int(item.strip())
        for item in str(args.sizes).split(",")
        if item.strip()
    )
    if not sizes or any(size <= 0 for size in sizes):
        parser.error("--sizes must contain positive integers")
    result = benchmark(
        sizes,
        cached_iterations=max(1, args.cached_iterations),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
