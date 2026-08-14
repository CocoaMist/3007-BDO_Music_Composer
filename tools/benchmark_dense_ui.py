#!/usr/bin/env python3
"""Measure bounded dense-project timeline and piano-roll UI workloads.

The default offscreen run is reproducible and does not require a display.  Its
wall-clock values are diagnostic evidence, not unit-test pass thresholds; the
existing UI tests remain responsible for visible-range and cache invariants.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BDO_UI_PERF_DIAGNOSTICS", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import PySide6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from bdo_music_composer.ui.main_window import (  # noqa: E402
    MidiNoteEditorDialog,
    MidiToBdoWindow,
    Note,
    PianoRollCanvas,
    TimelineCanvas,
    TrackState,
)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def _timing_summary(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": statistics.median(values) if values else 0.0,
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values, default=0.0),
    }


def _measure(operation: Callable[[], Any], iterations: int) -> dict[str, float]:
    operation()
    values: list[float] = []
    for _ in range(max(1, iterations)):
        started = time.perf_counter()
        operation()
        values.append((time.perf_counter() - started) * 1000.0)
    return _timing_summary(values)


def _notes(count: int, *, step_ms: float, duration_ms: float) -> list[Note]:
    return [
        Note(40 + index % 48, 90, float(index) * step_ms, duration_ms, 0)
        for index in range(max(1, count))
    ]


class _EditorStub(QWidget):
    bpm = 120
    time_sig = 4
    beat_origin_ms = 0.0
    transcription_mode_enabled = False

    def quantize_ms(self) -> float:
        return 125.0


def benchmark_dense_ui(
    *,
    timeline_tracks: int,
    notes_per_track: int,
    piano_notes: int,
    ghost_notes: int,
    query_sizes: tuple[int, ...],
    iterations: int,
) -> dict[str, Any]:
    app = QApplication.instance() or QApplication([])
    timeline: TimelineCanvas | None = None
    window: MidiToBdoWindow | None = None
    dialog: MidiNoteEditorDialog | None = None
    try:
        tracks = [
            TrackState(
                track_id,
                _notes(notes_per_track, step_ms=125.0, duration_ms=100.0),
                0,
                False,
                f"track-{track_id}",
                0x0B,
            )
            for track_id in range(max(1, timeline_tracks))
        ]
        timeline = TimelineCanvas()
        timeline.resize(1_200, 500)
        started = time.perf_counter()
        timeline.set_tracks(tracks)
        timeline_index_ms = (time.perf_counter() - started) * 1000.0
        timeline.show()
        app.processEvents()
        timeline_paint = _measure(timeline.grab, iterations)
        for track in tracks:
            track.arrangement_group_id = "dense-benchmark-group"
        timeline.set_tracks(tracks)
        collapsed_started = time.perf_counter()
        timeline.set_all_groups_collapsed(True)
        app.processEvents()
        timeline.grab()
        collapsed_first_paint_ms = (
            time.perf_counter() - collapsed_started
        ) * 1000.0
        collapsed_group_paint = _measure(timeline.grab, iterations)
        timeline.set_all_groups_collapsed(False)
        app.processEvents()

        query_results: dict[str, Any] = {}
        for count in query_sizes:
            notes = _notes(count, step_ms=25.0, duration_ms=10.0)
            editor = _EditorStub()
            roll = PianoRollCanvas(editor)
            started = time.perf_counter()
            roll.set_notes(notes)
            index_ms = (time.perf_counter() - started) * 1000.0
            left = max(0.0, (count - 1_000) * 25.0)
            right = left + 1_000.0
            visible_count = 0

            def query() -> None:
                nonlocal visible_count
                visible_count = len(roll.visible_note_indices(left, right))

            query_results[str(count)] = {
                "index_build_ms": index_ms,
                "query": _measure(query, max(10, iterations * 5)),
                "visible_notes": visible_count,
            }
            roll.close()
            roll.deleteLater()
            editor.close()
            editor.deleteLater()
            QCoreApplication.sendPostedEvents(
                None,
                QEvent.Type.DeferredDelete,
            )

        dense_notes = _notes(piano_notes, step_ms=50.0, duration_ms=45.0)
        ghosts = _notes(ghost_notes, step_ms=70.0, duration_ms=55.0)
        dense = TrackState(10_000, dense_notes, 0, False, "dense", 0x0B)
        ghost = TrackState(10_001, ghosts, 0, False, "ghost", 0x0B)
        started = time.perf_counter()
        tracks[-1].notes = [
            *tracks[-1].notes[:-1],
            tracks[-1].notes[-1]._replace(vel=91),
        ]
        timeline.update_tracks({tracks[-1].track_id})
        single_track_update_ms = (time.perf_counter() - started) * 1000.0
        window_started = time.perf_counter()
        window = MidiToBdoWindow()
        window_construct_ms = (time.perf_counter() - window_started) * 1000.0
        first_frame_started = time.perf_counter()
        window.show()
        app.processEvents()
        first_frame_ms = (time.perf_counter() - first_frame_started) * 1000.0
        probe = window.ui_performance_probe
        if probe is not None:
            probe.begin_interaction_window()
            for _ in range(max(3, min(12, iterations))):
                probe.note_synthetic_input()
                window.update()
                app.processEvents()
        window.tracks = [dense, ghost]
        started = time.perf_counter()
        dialog = MidiNoteEditorDialog(window, dense, 120, 4)
        dialog_prepare_ms = (time.perf_counter() - started) * 1000.0
        dialog.resize(1_180, 720)
        dialog.canvas.set_ghost_notes(ghosts)
        dialog.show()
        app.processEvents()
        piano_paint = _measure(dialog.canvas.grab, iterations)

        return {
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "pyside": PySide6.__version__,
                "qt_platform": os.environ.get("QT_QPA_PLATFORM", ""),
                "device_pixel_ratio": float(dialog.devicePixelRatioF()),
                "screen_refresh_hz": float(
                    dialog.screen().refreshRate() if dialog.screen() else 0.0
                ),
            },
            "application": {
                "window_construct_ms": window_construct_ms,
                "first_frame_ms": first_frame_ms,
                "ui_performance": (
                    probe.recorder.snapshot().to_dict()
                    if probe is not None
                    else None
                ),
            },
            "timeline": {
                "tracks": len(tracks),
                "notes": sum(len(track.notes) for track in tracks),
                "index_build_ms": timeline_index_ms,
                "single_track_update_ms": single_track_update_ms,
                "single_track_rebuild_count": 1,
                "paint": timeline_paint,
                "collapsed_group": {
                    "member_tracks": len(tracks),
                    "first_paint_ms": collapsed_first_paint_ms,
                    "steady_paint": collapsed_group_paint,
                },
                "last_note_query_inspections": (
                    timeline._last_track_note_query_inspections
                ),
            },
            "piano_roll": {
                "notes": len(dense_notes),
                "ghost_notes": len(ghosts),
                "dialog_prepare_ms": dialog_prepare_ms,
                "paint": piano_paint,
                "visible_notes": len(dialog.canvas.visible_note_indices()),
                "visible_ghost_notes": len(dialog.canvas.visible_ghost_notes()),
                "queries": query_results,
            },
        }
    finally:
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(
                None,
                QEvent.Type.DeferredDelete,
            )
        if window is not None:
            if window.ui_performance_probe is not None:
                window.ui_performance_probe.shutdown()
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(
                None,
                QEvent.Type.DeferredDelete,
            )
        if timeline is not None:
            timeline.close()
            timeline.deleteLater()
            QCoreApplication.sendPostedEvents(
                None,
                QEvent.Type.DeferredDelete,
            )
        app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline-tracks", type=int, default=120)
    parser.add_argument("--notes-per-track", type=int, default=400)
    parser.add_argument("--piano-notes", type=int, default=12_000)
    parser.add_argument("--ghost-notes", type=int, default=8_000)
    parser.add_argument(
        "--query-sizes",
        default="12000,50000,100000",
        help="comma-separated piano-roll index/query sizes",
    )
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    try:
        query_sizes = tuple(
            max(1, int(value.strip()))
            for value in args.query_sizes.split(",")
            if value.strip()
        )
    except ValueError as exc:
        parser.error(f"invalid --query-sizes: {exc}")
    if not query_sizes:
        parser.error("--query-sizes must contain at least one positive integer")
    result = benchmark_dense_ui(
        timeline_tracks=max(1, args.timeline_tracks),
        notes_per_track=max(1, args.notes_per_track),
        piano_notes=max(1, args.piano_notes),
        ghost_notes=max(1, args.ghost_notes),
        query_sizes=query_sizes,
        iterations=max(1, args.iterations),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
