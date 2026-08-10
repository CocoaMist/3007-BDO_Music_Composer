"""Qt-free editor interval index for visible-range queries.

The index is immutable after construction.  Callers provide the effective
duration while building it, so viewport queries only compare stored start/end
values and cannot accidentally apply a display scale twice.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class IntervalQuery(Generic[T]):
    """Items intersecting a closed range and the work needed to find them."""

    items: tuple[T, ...]
    inspected_count: int


@dataclass(frozen=True, slots=True)
class IntervalIndex(Generic[T]):
    """Start-ordered intervals with block maxima for long-span lookback."""

    items: tuple[T, ...]
    starts: tuple[float, ...]
    ends: tuple[float, ...]
    max_duration: float
    maximum_end: float
    block_max_tree: tuple[float, ...]
    tree_base: int
    block_size: int

    @classmethod
    def build(
        cls,
        items: Iterable[T],
        *,
        start_of: Callable[[T], float],
        duration_of: Callable[[T], float],
        block_size: int = 128,
    ) -> "IntervalIndex[T]":
        """Build an index after applying each item's effective duration once."""

        if block_size <= 0:
            raise ValueError("block_size must be positive")

        measured = [
            (float(start_of(item)), float(duration_of(item)), item)
            for item in items
        ]
        measured.sort(key=lambda value: value[0])
        ordered = tuple(value[2] for value in measured)
        starts = tuple(value[0] for value in measured)
        durations = tuple(value[1] for value in measured)
        ends = tuple(
            start + duration
            for start, duration in zip(starts, durations)
        )
        max_duration = max(durations, default=0.0)
        maximum_end = max(ends, default=0.0)

        block_count = (len(ends) + block_size - 1) // block_size
        tree_base = (
            1
            if block_count <= 1
            else 1 << (block_count - 1).bit_length()
        )
        block_max_tree = [float("-inf")] * (tree_base * 2)
        for block_index in range(block_count):
            block_start = block_index * block_size
            block_stop = min(len(ends), block_start + block_size)
            block_max_tree[tree_base + block_index] = max(
                ends[block_start:block_stop],
                default=float("-inf"),
            )
        for node in range(tree_base - 1, 0, -1):
            block_max_tree[node] = max(
                block_max_tree[node * 2],
                block_max_tree[node * 2 + 1],
            )

        return cls(
            items=ordered,
            starts=starts,
            ends=ends,
            max_duration=max_duration,
            maximum_end=maximum_end,
            block_max_tree=tuple(block_max_tree),
            tree_base=tree_base,
            block_size=block_size,
        )

    def query_closed(self, start: float, end: float) -> IntervalQuery[T]:
        """Return intervals overlapping the viewport's inclusive boundaries.

        An item is returned when its stored start is at most ``end`` and its
        stored end is at least ``start``.
        """

        candidate_stop = bisect_right(self.starts, end)
        if candidate_stop <= 0:
            return IntervalQuery(items=(), inspected_count=0)

        last_block = (candidate_stop - 1) // self.block_size
        matching_blocks: list[int] = []
        stack = [(1, 0, self.tree_base)]
        while stack:
            node, node_start, node_stop = stack.pop()
            if (
                node_start > last_block
                or self.block_max_tree[node] < start
            ):
                continue
            if node_stop - node_start == 1:
                matching_blocks.append(node_start)
                continue
            midpoint = (node_start + node_stop) // 2
            stack.append((node * 2 + 1, midpoint, node_stop))
            stack.append((node * 2, node_start, midpoint))

        visible: list[T] = []
        inspected_count = 0
        for block_index in matching_blocks:
            block_start = block_index * self.block_size
            block_stop = min(
                candidate_stop,
                block_start + self.block_size,
            )
            inspected_count += block_stop - block_start
            for item_index in range(block_start, block_stop):
                if self.ends[item_index] >= start:
                    visible.append(self.items[item_index])
        return IntervalQuery(
            items=tuple(visible),
            inspected_count=inspected_count,
        )
