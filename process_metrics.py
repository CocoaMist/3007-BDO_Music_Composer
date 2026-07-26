"""Low-overhead process metrics for the desktop status strip.

Sampling is intentionally independent of Qt and the real-time audio callback.
CPU usage is normalized to the machine's logical CPU capacity, matching the
0..100 percent scale normally shown by Windows Task Manager for a process.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import time
from typing import Callable


@dataclass(frozen=True, slots=True)
class ProcessMetrics:
    cpu_percent: float
    working_set_bytes: int

    @property
    def working_set_mib(self) -> float:
        return self.working_set_bytes / (1024.0 * 1024.0)


def current_working_set_bytes() -> int:
    """Return current resident memory without an optional psutil dependency."""

    if sys.platform == "win32":
        size_t = ctypes.c_size_t

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = (
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", size_t),
                ("WorkingSetSize", size_t),
                ("QuotaPeakPagedPoolUsage", size_t),
                ("QuotaPagedPoolUsage", size_t),
                ("QuotaPeakNonPagedPoolUsage", size_t),
                ("QuotaNonPagedPoolUsage", size_t),
                ("PagefileUsage", size_t),
                ("PeakPagefileUsage", size_t),
            )

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        try:
            process = ctypes.windll.kernel32.GetCurrentProcess()
            success = ctypes.windll.psapi.GetProcessMemoryInfo(
                process,
                ctypes.byref(counters),
                counters.cb,
            )
        except (AttributeError, OSError):
            return 0
        return int(counters.WorkingSetSize) if success else 0

    statm = Path("/proc/self/statm")
    try:
        resident_pages = int(statm.read_text(encoding="ascii").split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError, AttributeError):
        pass

    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, OSError, ValueError):
        return 0


class ProcessMetricsSampler:
    """Delta sampler whose dependencies can be replaced in deterministic tests."""

    def __init__(
        self,
        *,
        wall_clock: Callable[[], float] = time.perf_counter,
        process_clock: Callable[[], float] = time.process_time,
        memory_reader: Callable[[], int] = current_working_set_bytes,
        logical_cpu_count: int | None = None,
    ) -> None:
        self._wall_clock = wall_clock
        self._process_clock = process_clock
        self._memory_reader = memory_reader
        self._logical_cpu_count = max(
            1,
            int(logical_cpu_count or os.cpu_count() or 1),
        )
        self._last_wall = float(self._wall_clock())
        self._last_process = float(self._process_clock())

    def sample(self) -> ProcessMetrics:
        wall = float(self._wall_clock())
        process = float(self._process_clock())
        wall_delta = max(0.0, wall - self._last_wall)
        process_delta = max(0.0, process - self._last_process)
        self._last_wall = wall
        self._last_process = process
        cpu_percent = (
            process_delta / wall_delta * 100.0 / self._logical_cpu_count
            if wall_delta > 1e-9
            else 0.0
        )
        return ProcessMetrics(
            max(0.0, min(100.0, cpu_percent)),
            max(0, int(self._memory_reader())),
        )


__all__ = [
    "ProcessMetrics",
    "ProcessMetricsSampler",
    "current_working_set_bytes",
]
