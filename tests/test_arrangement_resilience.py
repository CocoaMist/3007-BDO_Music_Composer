from __future__ import annotations

import math
import time
import unittest

from bdo_music_composer.editor.arrangement_snap import (
    ArrangementSnapTarget,
    MAX_SNAP_TARGETS,
    align_overlapping_clip,
    build_occupied_clip_index,
    build_snap_index,
    normalize_snap_targets,
    snap_clip_start,
)
from bdo_music_composer.editor.timeline_markers import (
    MAX_MARKER_LABEL_CHARS,
    MAX_TIMELINE_MARKERS,
    normalize_timeline_markers,
)


class ArrangementResilienceTests(unittest.TestCase):
    def test_untrusted_marker_payload_is_bounded_and_sanitized(self) -> None:
        payload: list[object] = [None, 4, "bad", {"time_ms": math.nan}]
        payload.extend(
            {"id": f"marker-{i}\0hostile", "label": "name\0\n" + "x" * 200, "time_ms": float(i)}
            for i in range(20_000)
        )
        result = normalize_timeline_markers(payload)
        self.assertEqual(len(result), MAX_TIMELINE_MARKERS)
        self.assertTrue(all("\0" not in item["id"] for item in result))
        self.assertTrue(all("\0" not in item["label"] for item in result))
        self.assertTrue(all(len(item["label"]) <= MAX_MARKER_LABEL_CHARS for item in result))
        self.assertTrue(all(math.isfinite(float(item["time_ms"])) for item in result))

    def test_snap_target_flood_is_bounded_and_deterministic(self) -> None:
        targets = [ArrangementSnapTarget(float(i), "clip", "x" * 200) for i in range(20_000)]
        normalized = normalize_snap_targets(targets)
        self.assertEqual(len(normalized), MAX_SNAP_TARGETS)
        first = snap_clip_start(100.4, 20.0, normalized, tolerance_ms=1.0)
        self.assertEqual(first, snap_clip_start(100.4, 20.0, normalized, tolerance_ms=1.0))
        self.assertEqual(first.start_ms, 100.0)

    def test_marker_wins_even_when_clip_and_grid_are_closer(self) -> None:
        result = snap_clip_start(
            99.0, 0.0,
            (
                ArrangementSnapTarget(100.0, "clip", "track"),
                ArrangementSnapTarget(104.0, "marker", "chorus"),
            ),
            tolerance_ms=6.0, grid_ms=100.0,
        )
        self.assertEqual((result.kind, result.label), ("marker", "chorus"))
        self.assertEqual(result.start_ms, 104.0)

    def test_clip_wins_over_closer_grid_when_no_marker_is_in_range(self) -> None:
        result = snap_clip_start(
            99.0, 0.0,
            (ArrangementSnapTarget(104.0, "clip", "Track 2"),),
            tolerance_ms=6.0, grid_ms=100.0,
        )
        self.assertEqual((result.kind, result.label), ("clip", "Track 2"))
        self.assertEqual(result.start_ms, 104.0)

    def test_out_of_range_marker_does_not_block_clip(self) -> None:
        result = snap_clip_start(
            99.0, 0.0,
            (
                ArrangementSnapTarget(103.0, "clip", "Track 2"),
                ArrangementSnapTarget(120.0, "marker", "verse"),
            ),
            tolerance_ms=6.0, grid_ms=100.0,
        )
        self.assertEqual((result.kind, result.label), ("clip", "Track 2"))

    def test_marker_targets_are_not_starved_by_clip_target_limit(self) -> None:
        index = build_snap_index([
            *(
                ArrangementSnapTarget(float(i), "clip", str(i))
                for i in range(MAX_SNAP_TARGETS)
            ),
            ArrangementSnapTarget(50.5, "marker", "priority"),
        ])
        result = snap_clip_start(
            50.0, 0.0, index, tolerance_ms=1.0, grid_ms=1.0,
        )
        self.assertEqual((result.kind, result.label), ("marker", "priority"))

    def test_indexed_snap_stays_inside_pointer_move_budget(self) -> None:
        index = build_snap_index(
            ArrangementSnapTarget(float(i) * 13.0, "clip", str(i))
            for i in range(MAX_SNAP_TARGETS)
        )
        started = time.perf_counter()
        for offset in range(20_000):
            snap_clip_start(
                12_345.0 + (offset % 31), 800.0, index,
                tolerance_ms=20.0, grid_ms=125.0,
            )
        elapsed = time.perf_counter() - started
        # 20k pointer updates are intentionally far more than one gesture.
        # The former per-call full scan takes minutes at this target count.
        self.assertLess(elapsed, 1.0, elapsed)

    def test_overlapping_clip_aligns_to_nearest_free_boundary(self) -> None:
        occupied = build_occupied_clip_index(((100.0, 300.0), (500.0, 650.0)))
        aligned_left = align_overlapping_clip(80.0, 80.0, occupied)
        aligned_right = align_overlapping_clip(280.0, 100.0, occupied)
        self.assertEqual(aligned_left.start_ms, 20.0)
        self.assertEqual(aligned_left.target_ms, 100.0)
        self.assertEqual(aligned_right.start_ms, 300.0)
        self.assertEqual(aligned_right.target_ms, 300.0)


if __name__ == "__main__":
    unittest.main()
