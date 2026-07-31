from __future__ import annotations

from dataclasses import dataclass
import unittest

from bdo_music_composer.editor.interval_index import IntervalIndex


@dataclass(frozen=True, slots=True)
class _Interval:
    name: str
    start: float
    duration: float
    pitch: int = 60


def _build(
    intervals: list[_Interval],
    *,
    duration_scale: float = 1.0,
    block_size: int = 4,
) -> IntervalIndex[_Interval]:
    return IntervalIndex.build(
        intervals,
        start_of=lambda item: item.start,
        duration_of=lambda item: item.duration * duration_scale,
        block_size=block_size,
    )


class IntervalIndexTests(unittest.TestCase):
    def test_build_evaluates_each_projection_once(self) -> None:
        values = [_Interval("a", 2.0, 3.0), _Interval("b", 1.0, 4.0)]
        start_calls: list[str] = []
        duration_calls: list[str] = []

        index = IntervalIndex.build(
            values,
            start_of=lambda item: (
                start_calls.append(item.name) or item.start
            ),
            duration_of=lambda item: (
                duration_calls.append(item.name) or item.duration
            ),
        )

        self.assertEqual(sorted(start_calls), ["a", "b"])
        self.assertEqual(sorted(duration_calls), ["a", "b"])
        self.assertEqual([item.name for item in index.items], ["b", "a"])

    def test_query_uses_closed_boundaries_and_stable_start_order(self) -> None:
        ending_at_left = _Interval("ending", 0.0, 10.0)
        starts_at_right_first = _Interval("first", 20.0, 1.0)
        starts_at_right_second = _Interval("second", 20.0, 2.0)
        outside = _Interval("outside", 21.0, 1.0)
        index = _build(
            [outside, starts_at_right_first, ending_at_left, starts_at_right_second]
        )

        result = index.query_closed(10.0, 20.0)

        self.assertEqual(
            result.items,
            (ending_at_left, starts_at_right_first, starts_at_right_second),
        )
        self.assertEqual(index.starts, (0.0, 20.0, 20.0, 21.0))

    def test_effective_duration_is_applied_only_when_building(self) -> None:
        note = _Interval("scaled", 0.0, 100.0)
        index = _build([note], duration_scale=0.5)

        self.assertEqual(index.ends, (50.0,))
        self.assertEqual(index.max_duration, 50.0)
        self.assertEqual(index.query_closed(50.0, 50.0).items, (note,))
        self.assertEqual(index.query_closed(50.01, 75.0).items, ())

    def test_long_interval_crosses_late_viewport_with_bounded_inspection(self) -> None:
        block_size = 128
        long_note = _Interval("long", 0.0, 300_000.0)
        notes = [
            long_note,
            *[
                _Interval(str(number), float(number * 25), 10.0)
                for number in range(1, 12_000)
            ],
        ]
        index = _build(notes, block_size=block_size)

        result = index.query_closed(290_000.0, 291_000.0)
        expected = tuple(
            note
            for note in notes
            if note.start <= 291_000.0
            and note.start + note.duration >= 290_000.0
        )

        self.assertEqual(result.items, expected)
        self.assertIn(long_note, result.items)
        self.assertLessEqual(result.inspected_count, block_size * 3)

    def test_empty_index_has_explicit_immutable_fields(self) -> None:
        index = _build([])

        self.assertEqual(index.items, ())
        self.assertEqual(index.starts, ())
        self.assertEqual(index.ends, ())
        self.assertEqual(index.maximum_end, 0.0)
        self.assertEqual(index.query_closed(0.0, 1.0).items, ())
        with self.assertRaises(AttributeError):
            index.block_size = 8  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
