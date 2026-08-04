from __future__ import annotations

import unittest
from collections import namedtuple

from bdo_music_composer.editor.velocity_curve import (
    VelocityEnvelopePoint,
    apply_velocity_level_envelope,
    apply_velocity_curve,
    apply_weighted_velocity_delta,
    normalize_velocity_envelope_points,
    velocity_curve_progress,
    velocity_envelope_points_from_notes,
    velocity_envelope_value,
    velocity_neighbor_weight,
    velocity_time_points,
)


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


class VelocityCurveTests(unittest.TestCase):
    def test_free_points_are_sorted_clamped_and_deduplicated(self) -> None:
        points = normalize_velocity_envelope_points(
            (
                VelocityEnvelopePoint(0.75, 140.0),
                VelocityEnvelopePoint(-1.0, -20.0),
                VelocityEnvelopePoint(0.75, 125.0),
                VelocityEnvelopePoint(2.0, 500.0),
            )
        )
        self.assertEqual(
            points,
            (
                VelocityEnvelopePoint(0.0, 0.0),
                VelocityEnvelopePoint(0.75, 125.0),
                VelocityEnvelopePoint(1.0, 127.0),
            ),
        )

    def test_shape_preserving_interpolation_passes_points_without_overshoot(self) -> None:
        points = (
            VelocityEnvelopePoint(0.0, 70.0),
            VelocityEnvelopePoint(0.25, 120.0),
            VelocityEnvelopePoint(0.6, 55.0),
            VelocityEnvelopePoint(1.0, 110.0),
        )
        for point in points:
            self.assertAlmostEqual(
                velocity_envelope_value(point.time, points),
                point.velocity,
                places=8,
            )
        for left, right in zip(points, points[1:]):
            values = [
                velocity_envelope_value(
                    left.time + (right.time - left.time) * step / 20.0,
                    points,
                )
                for step in range(21)
            ]
            self.assertGreaterEqual(min(values), min(left.velocity, right.velocity))
            self.assertLessEqual(max(values), max(left.velocity, right.velocity))

    def test_each_side_weight_changes_only_the_adjacent_segment(self) -> None:
        light = (
            VelocityEnvelopePoint(0.0, 50.0, right_weight=0.05),
            VelocityEnvelopePoint(0.5, 115.0, left_weight=0.2, right_weight=0.2),
            VelocityEnvelopePoint(1.0, 80.0, left_weight=0.2),
        )
        heavy = (
            VelocityEnvelopePoint(0.0, 50.0, right_weight=0.9),
            VelocityEnvelopePoint(0.5, 115.0, left_weight=0.2, right_weight=0.2),
            VelocityEnvelopePoint(1.0, 80.0, left_weight=0.2),
        )
        self.assertNotAlmostEqual(
            velocity_envelope_value(0.2, light),
            velocity_envelope_value(0.2, heavy),
        )
        self.assertAlmostEqual(
            velocity_envelope_value(0.75, light),
            velocity_envelope_value(0.75, heavy),
        )
        for points in (light, heavy):
            first_segment = [
                velocity_envelope_value(step / 20.0 * 0.5, points)
                for step in range(21)
            ]
            self.assertGreaterEqual(min(first_segment), 50.0)
            self.assertLessEqual(max(first_segment), 115.0)

    def test_point_envelope_uses_explicit_time_window_and_preserves_chords(self) -> None:
        notes = [
            Note(60, 40, 0.0, 100.0, 0),
            Note(64, 80, 0.0, 100.0, 0),
            Note(67, 60, 500.0, 100.0, 0),
            Note(69, 60, 1000.0, 100.0, 0),
        ]
        points = (
            VelocityEnvelopePoint(0.0, 50.0),
            VelocityEnvelopePoint(0.5, 100.0),
            VelocityEnvelopePoint(1.0, 150.0),
        )
        changed = apply_velocity_level_envelope(
            notes,
            range(4),
            points,
            start_ms=0.0,
            end_ms=1000.0,
        )
        self.assertEqual([note.vel for note in changed], [33, 67, 100, 127])
        self.assertEqual(changed[1].vel, changed[0].vel * 2 + 1)

    def test_point_envelope_is_deterministic_and_clamped(self) -> None:
        notes = [
            Note(60, 100, 0.0, 100.0, 0),
            Note(62, 100, 1000.0, 100.0, 0),
        ]
        points = (
            VelocityEnvelopePoint(0.0, -20.0),
            VelocityEnvelopePoint(1.0, 500.0),
        )
        first = apply_velocity_level_envelope(notes, range(2), points)
        second = apply_velocity_level_envelope(notes, range(2), points)
        self.assertEqual(first, second)
        self.assertEqual([note.vel for note in first], [0, 127])

    def test_envelope_is_initialized_from_authoritative_note_velocities(self) -> None:
        notes = [
            Note(60, 40, 0.0, 100.0, 0),
            Note(64, 80, 0.0, 100.0, 0),
            Note(67, 90, 500.0, 100.0, 0),
            Note(69, 110, 1000.0, 100.0, 0),
        ]

        points = velocity_envelope_points_from_notes(
            notes,
            range(4),
            start_ms=0.0,
            end_ms=1000.0,
        )

        self.assertEqual(
            [(point.time, point.velocity) for point in points],
            [(0.0, 60.0), (0.5, 90.0), (1.0, 110.0)],
        )

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

    def test_zero_velocity_is_preserved_and_is_the_lower_clamp(self) -> None:
        notes = [
            Note(60, 0, 0.0, 100.0, 0),
            Note(62, 3, 500.0, 100.0, 0),
        ]

        curved = apply_velocity_curve(notes, {0}, 100, 100, "linear")
        lowered = apply_weighted_velocity_delta(
            notes,
            center_ms=500.0,
            delta=-20.0,
            radius_ms=100.0,
        )

        self.assertEqual(curved[0].vel, 0)
        self.assertEqual(lowered[1].vel, 0)


if __name__ == "__main__":
    unittest.main()
