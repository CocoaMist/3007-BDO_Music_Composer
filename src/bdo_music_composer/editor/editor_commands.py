"""Qt-free bounded undo snapshots for cross-dialog editor operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Sequence


def next_non_overlapping_paste_origin(
    existing_notes: Sequence[object],
    clipboard_notes: Sequence[object],
    requested_origin_ms: float,
    *,
    grid_step_ms: float | None,
    grid_origin_ms: float = 0.0,
) -> float:
    """Move a pasted note group right until same-pitch intervals are free.

    Clipboard note starts are relative to the copied group's first onset. The
    whole group moves as one unit, preserving its rhythm and chords. Touching
    interval boundaries are valid; only positive-duration overlap moves the
    group. The search is monotonic and clears at least one existing interval
    per pass, so it remains bounded for dense tracks.
    """

    if not clipboard_notes:
        return max(0.0, float(requested_origin_ms))
    step = (
        max(1e-6, float(grid_step_ms))
        if grid_step_ms is not None
        else None
    )
    grid_origin = float(grid_origin_ms)
    epsilon = 1e-6

    def snap_forward(value: float) -> float:
        if step is None:
            return max(0.0, float(value))
        grid_index = math.ceil(
            (float(value) - grid_origin - epsilon) / step
        )
        return max(0.0, grid_origin + grid_index * step)

    origin = snap_forward(max(0.0, float(requested_origin_ms)))
    intervals_by_pitch: dict[int, list[tuple[float, float]]] = {}
    for note in existing_notes:
        start = float(getattr(note, "start", 0.0))
        duration = max(0.0, float(getattr(note, "dur", 0.0)))
        if not math.isfinite(start) or not math.isfinite(duration):
            continue
        intervals_by_pitch.setdefault(
            int(getattr(note, "pitch", 0)),
            [],
        ).append((start, start + duration))
    for intervals in intervals_by_pitch.values():
        intervals.sort()

    maximum_passes = sum(len(value) for value in intervals_by_pitch.values()) + 1
    for _pass in range(maximum_passes):
        required_origin = origin
        for note in clipboard_notes:
            relative_start = float(getattr(note, "start", 0.0))
            duration = max(0.0, float(getattr(note, "dur", 0.0)))
            pasted_start = origin + relative_start
            pasted_end = pasted_start + duration
            for existing_start, existing_end in intervals_by_pitch.get(
                int(getattr(note, "pitch", 0)),
                (),
            ):
                if (
                    pasted_start < existing_end - epsilon
                    and pasted_end > existing_start + epsilon
                ):
                    required_origin = max(
                        required_origin,
                        existing_end - relative_start,
                    )
        if required_origin <= origin + epsilon:
            return origin
        origin = snap_forward(
            max(
                origin + (step if step is not None else epsilon),
                required_origin,
            )
        )
    return origin


@dataclass(frozen=True, slots=True)
class ProjectSnapshot:
    tracks: tuple[object, ...]
    reverb: int
    delay: int
    chorus: tuple[int, int, int] | None
    transcription_state: object | None = None
    transcription_assist_state: object | None = None
    conversion_settings: object | None = None
    pitch_transform_plan: object | None = None
    lyric_events: object | None = None
    timeline_markers: object | None = None
    arrangement_selection: object | None = None

    @classmethod
    def capture(cls, tracks: Sequence[object], reverb: int, delay: int,
                chorus: tuple[int, int, int] | None,
                transcription_state: object | None = None,
                transcription_assist_state: object | None = None,
                conversion_settings: object | None = None,
                pitch_transform_plan: object | None = None,
                 lyric_events: object | None = None,
                 timeline_markers: object | None = None,
                 arrangement_selection: object | None = None,
                ) -> "ProjectSnapshot":
        return cls(
            tuple(deepcopy(list(tracks))),
            int(reverb),
            int(delay),
            deepcopy(chorus),
            deepcopy(transcription_state),
            deepcopy(transcription_assist_state),
            deepcopy(conversion_settings),
            deepcopy(pitch_transform_plan),
            deepcopy(lyric_events),
            deepcopy(timeline_markers),
            deepcopy(arrangement_selection),
        )

    def restored_tracks(self) -> list:
        return deepcopy(list(self.tracks))

    def restored_transcription_state(self) -> object | None:
        return deepcopy(self.transcription_state)

    def restored_transcription_assist_state(self) -> object | None:
        return deepcopy(self.transcription_assist_state)

    def restored_conversion_settings(self) -> object | None:
        return deepcopy(self.conversion_settings)

    def restored_pitch_transform_plan(self) -> object | None:
        return deepcopy(self.pitch_transform_plan)

    def restored_lyric_events(self) -> object | None:
        return deepcopy(self.lyric_events)

    def restored_timeline_markers(self) -> object | None:
        return deepcopy(self.timeline_markers)

    def restored_arrangement_selection(self) -> object | None:
        return deepcopy(self.arrangement_selection)


class ProjectCommandStack:
    def __init__(self, limit: int = 50) -> None:
        self.limit = max(1, int(limit))
        self._undo: list[ProjectSnapshot] = []
        self._redo: list[ProjectSnapshot] = []

    def push(self, before: ProjectSnapshot) -> None:
        self._undo.append(before)
        del self._undo[:-self.limit]
        self._redo.clear()

    def undo(self, current: ProjectSnapshot) -> ProjectSnapshot | None:
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current: ProjectSnapshot) -> ProjectSnapshot | None:
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def checkpoint(
        self,
    ) -> tuple[tuple[ProjectSnapshot, ...], tuple[ProjectSnapshot, ...]]:
        """Freeze stack ownership for an application-level transaction."""

        return tuple(self._undo), tuple(self._redo)

    def restore_checkpoint(
        self,
        checkpoint: tuple[
            tuple[ProjectSnapshot, ...],
            tuple[ProjectSnapshot, ...],
        ],
    ) -> None:
        undo, redo = checkpoint
        self._undo = list(undo[-self.limit:])
        self._redo = list(redo)


__all__ = [
    "ProjectCommandStack",
    "ProjectSnapshot",
    "next_non_overlapping_paste_origin",
]
