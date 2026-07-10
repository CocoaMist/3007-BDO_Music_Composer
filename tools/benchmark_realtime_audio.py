#!/usr/bin/env python3
"""Exercise the in-process Python BDO audio module with up to 256 voices."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import namedtuple
from pathlib import Path

from PySide6.QtCore import QCoreApplication


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bdo_realtime_audio import BdoRealtimeAudioEngine  # noqa: E402
from project_paths import WWISE_MIDI_MAP_PATH  # noqa: E402


Note = namedtuple("Note", "pitch vel start dur ntype")
Track = namedtuple("Track", "track_id bdo_instrument_id is_percussion volume_scale duration_scale articulation_type notes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30.0, help="use 1800 for the 30-minute acceptance run")
    parser.add_argument("--voices", type=int, default=256)
    args = parser.parse_args()
    app = QCoreApplication.instance() or QCoreApplication([])
    notes = [Note(48 + (index % 36), 96, (index // 16) * 120, 1000, 0) for index in range(max(1, min(256, args.voices)))]
    track = Track(1, 0x0A, False, 0.7, 1.0, None, notes)
    engine = BdoRealtimeAudioEngine(None, {"paz_root": r"F:\缓存\Paz", "audio_root": r"F:\缓存\BDO音源"})
    seeks = []
    try:
        started = time.perf_counter()
        engine.load_project([track], WWISE_MIDI_MAP_PATH, 0)
        engine.play()
        cold_start_ms = (time.perf_counter() - started) * 1000
        engine.pause()
        warmed = time.perf_counter()
        engine.play()
        warm_start_ms = (time.perf_counter() - warmed) * 1000
        deadline = time.monotonic() + args.seconds
        next_seek = time.monotonic()
        period = 256 / engine.get_status().sample_rate
        while time.monotonic() < deadline:
            # Mirrors Qt's pull request for one 256-frame Int16 stereo block.
            block_started = time.perf_counter()
            engine._read_pcm(256 * 4)
            if time.monotonic() >= next_seek:
                began = time.perf_counter()
                engine.seek(300.0 if int(time.monotonic() * 2) % 2 else 50.0)
                seeks.append((time.perf_counter() - began) * 1000)
                next_seek += 0.5
            app.processEvents()
            time.sleep(max(0.0, period - (time.perf_counter() - block_started)))
        status = engine.get_status()
    finally:
        engine.stop()
    print(json.dumps({
        "voices": len(notes), "seconds": args.seconds, "cold_prepare_ms": cold_start_ms,
        "warm_start_ms": warm_start_ms,
        "seek_p95_ms": sorted(seeks)[max(0, round((len(seeks) - 1) * 0.95))] if seeks else None,
        "buffer_frames": status.buffer_frames,
        "cache_bytes": status.cache_bytes,
        "underruns": status.underruns,
        "render_p95_ms": status.render_p95_ms,
        "render_max_ms": status.render_max_ms,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
