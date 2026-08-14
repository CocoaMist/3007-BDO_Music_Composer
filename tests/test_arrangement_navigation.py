from __future__ import annotations

import unittest

from bdo_music_composer.editor.arrangement_navigation import (
    neighboring_boundary,
    normalized_boundaries,
    timeline_grid_step_ms,
    viewport_for_range,
)


class ArrangementNavigationTests(unittest.TestCase):
    def test_grid_steps_match_quarter_beat_default(self) -> None:
        self.assertEqual(timeline_grid_step_ms(120), 125.0)
        self.assertEqual(timeline_grid_step_ms(120, coarse=True), 500.0)
        self.assertEqual(timeline_grid_step_ms(120, fine=True), 31.25)

    def test_boundaries_are_stable_and_navigation_clamps(self) -> None:
        values = normalized_boundaries((500.0, 0.0, 500.0, 250.0))
        self.assertEqual(values, (0.0, 250.0, 500.0))
        self.assertEqual(neighboring_boundary(values, 250.0, -1), 0.0)
        self.assertEqual(neighboring_boundary(values, 250.0, 1), 500.0)
        self.assertEqual(neighboring_boundary(values, 900.0, 1), 500.0)

    def test_viewport_fits_range_with_context_and_clamps(self) -> None:
        viewport = viewport_for_range(10_000.0, 4_000.0, 6_000.0)
        visible = 10_000.0 / viewport.zoom_factor
        self.assertLessEqual(viewport.start_ms, 4_000.0)
        self.assertGreaterEqual(viewport.start_ms + visible, 6_000.0)
        tail = viewport_for_range(10_000.0, 9_800.0, 10_000.0)
        self.assertGreaterEqual(tail.start_ms, 0.0)
        self.assertLessEqual(
            tail.start_ms + 10_000.0 / tail.zoom_factor,
            10_000.0 + 1e-6,
        )


if __name__ == "__main__":
    unittest.main()
