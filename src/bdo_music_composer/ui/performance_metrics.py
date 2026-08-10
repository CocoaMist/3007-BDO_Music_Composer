"""Bounded, Qt-free interaction and event-loop performance metrics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import time


def _percentile(values: tuple[float, ...], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[round((len(ordered) - 1) * fraction)])


@dataclass(frozen=True, slots=True)
class UiPerformanceSnapshot:
    input_samples: int
    input_to_paint_p50_ms: float
    input_to_paint_p95_ms: float
    input_to_paint_p99_ms: float
    input_to_paint_max_ms: float
    heartbeat_samples: int
    heartbeat_p95_ms: float
    heartbeat_max_ms: float
    stall_count: int
    stall_threshold_ms: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "input_samples": self.input_samples,
            "input_to_paint_p50_ms": self.input_to_paint_p50_ms,
            "input_to_paint_p95_ms": self.input_to_paint_p95_ms,
            "input_to_paint_p99_ms": self.input_to_paint_p99_ms,
            "input_to_paint_max_ms": self.input_to_paint_max_ms,
            "heartbeat_samples": self.heartbeat_samples,
            "heartbeat_p95_ms": self.heartbeat_p95_ms,
            "heartbeat_max_ms": self.heartbeat_max_ms,
            "stall_count": self.stall_count,
            "stall_threshold_ms": self.stall_threshold_ms,
        }


class UiPerformanceRecorder:
    """Keep a bounded diagnostic window without retaining input content."""

    def __init__(
        self,
        *,
        capacity: int = 2_048,
        stall_threshold_ms: float = 32.0,
    ) -> None:
        self._latencies_ms: deque[float] = deque(maxlen=max(16, int(capacity)))
        self._heartbeats_ms: deque[float] = deque(maxlen=max(16, int(capacity)))
        self._pending_input_ns: int | None = None
        self._last_heartbeat_ns: int | None = None
        self._stall_count = 0
        self._stall_threshold_ms = max(1.0, float(stall_threshold_ms))

    def note_input(self, timestamp_ns: int | None = None) -> None:
        stamp = time.perf_counter_ns() if timestamp_ns is None else int(timestamp_ns)
        if self._pending_input_ns is None:
            self._pending_input_ns = stamp

    def reset_interaction_window(self, timestamp_ns: int | None = None) -> None:
        """Start a post-startup measurement window with no inherited stall."""

        self._latencies_ms.clear()
        self._heartbeats_ms.clear()
        self._pending_input_ns = None
        self._stall_count = 0
        self._last_heartbeat_ns = (
            time.perf_counter_ns() if timestamp_ns is None else int(timestamp_ns)
        )

    def note_paint_complete(self, timestamp_ns: int | None = None) -> float | None:
        if self._pending_input_ns is None:
            return None
        stamp = time.perf_counter_ns() if timestamp_ns is None else int(timestamp_ns)
        latency_ms = max(0.0, (stamp - self._pending_input_ns) / 1_000_000.0)
        self._pending_input_ns = None
        if math.isfinite(latency_ms):
            self._latencies_ms.append(latency_ms)
            return latency_ms
        return None

    def heartbeat(self, timestamp_ns: int | None = None) -> float | None:
        stamp = time.perf_counter_ns() if timestamp_ns is None else int(timestamp_ns)
        previous = self._last_heartbeat_ns
        self._last_heartbeat_ns = stamp
        if previous is None:
            return None
        interval_ms = max(0.0, (stamp - previous) / 1_000_000.0)
        if not math.isfinite(interval_ms):
            return None
        self._heartbeats_ms.append(interval_ms)
        if interval_ms > self._stall_threshold_ms:
            self._stall_count += 1
        return interval_ms

    def snapshot(self) -> UiPerformanceSnapshot:
        latencies = tuple(self._latencies_ms)
        heartbeats = tuple(self._heartbeats_ms)
        return UiPerformanceSnapshot(
            input_samples=len(latencies),
            input_to_paint_p50_ms=_percentile(latencies, 0.50),
            input_to_paint_p95_ms=_percentile(latencies, 0.95),
            input_to_paint_p99_ms=_percentile(latencies, 0.99),
            input_to_paint_max_ms=max(latencies, default=0.0),
            heartbeat_samples=len(heartbeats),
            heartbeat_p95_ms=_percentile(heartbeats, 0.95),
            heartbeat_max_ms=max(heartbeats, default=0.0),
            stall_count=self._stall_count,
            stall_threshold_ms=self._stall_threshold_ms,
        )


__all__ = [
    "UiPerformanceRecorder",
    "UiPerformanceSnapshot",
]
