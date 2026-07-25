from __future__ import annotations

import unittest
from collections import namedtuple

from velocity_curve import (
    apply_velocity_curve,
    apply_weighted_velocity_delta,
    velocity_curve_progress,
    velocity_neighbor_weight,
    velocity_time_points,
)


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


class VelocityCurveTests(unittest.TestCase):
    def test_linear_curve_preserves_relative_velocity_and_clamps(self) -> None:
        notes = [
            Note(60, 40, 0.0, 100.0, 0),
            Note(62, 80, 500.0, 100.0, 0),
            Note(64, 100, 1000.0, 100.0, 0),
        ]
        changed = apply_velocity_curve(notes, range(3), 50, 150, "linear")
        self.assertEqual([note.vel for note in changed], [20, 80, 127])
        self.assertEqual([note.pitch for note in changed], [60, 62, 64])
        self.assertEqual([note.start for note in changed], [0.0, 500.0, 1000.0])

    def test_curve_can_target_only_selected_notes(self) -> None:
        notes = [
            Note(60, 60, 0.0, 100.0, 0),
            Note(62, 60, 500.0, 100.0, 0),
            Note(64, 60, 1000.0, 100.0, 0),
        ]
        changed = apply_velocity_curve(notes, {0, 2}, 100, 50, "linear")
        self.assertEqual([note.vel for note in changed], [60, 60, 30])

    def test_supported_shapes_are_monotonic_and_bounded(self) -> None:
        for shape in ("linear", "smooth", "ease_in", "ease_out"):
            values = [velocity_curve_progress(index / 20.0, shape) for index in range(21)]
            self.assertEqual(values[0], 0.0)
            self.assertEqual(values[-1], 1.0)
            self.assertEqual(values, sorted(values))

    def test_unknown_shape_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            velocity_curve_progress(0.5, "broken")

    def test_time_points_group_chords_into_one_curve_point(self) -> None:
        notes = [
            Note(60, 60, 0.0, 100.0, 0),
            Note(64, 100, 0.0, 100.0, 0),
            Note(67, 80, 500.0, 100.0, 0),
        ]
        points = velocity_time_points(notes)
        self.assertEqual(points, [
            (0.0, (0, 1), 80.0),
            (500.0, (2,), 80.0),
        ])

    def test_dragged_point_uses_smooth_distance_weight(self) -> None:
        notes = [
            Note(60, 60, 0.0, 100.0, 0),
            Note(62, 60, 250.0, 100.0, 0),
            Note(64, 60, 500.0, 100.0, 0),
            Note(65, 60, 1000.0, 100.0, 0),
        ]
        changed = apply_weighted_velocity_delta(notes, 0.0, 40.0, 1000.0)
        self.assertEqual(changed[0].vel, 100)
        self.assertGreater(changed[1].vel, changed[2].vel)
        self.assertGreater(changed[2].vel, changed[3].vel)
        self.assertEqual(changed[3].vel, 60)
        self.assertEqual(velocity_neighbor_weight(0.0, 1000.0), 1.0)
        self.assertEqual(velocity_neighbor_weight(1000.0, 1000.0), 0.0)


if __name__ == "__main__":
    unittest.main()
