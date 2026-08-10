"""Deterministic, bounded decoding for rhythm-aware note boundaries.

The decoder consumes already-reduced candidate features.  It performs no
audio I/O, model inference, editor mutation, or background scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Literal, Sequence


RHYTHM_DECODE_VERSION = "rhythm-boundary-decode-v1"
RHYTHM_DECODE_CHUNK_SIZE = 256

RhythmBoundaryState = Literal[
    "KEEP_SINGLE",
    "MERGE_CONTINUATION",
    "KEEP_REATTACK",
    "SUPPRESS_EXTRA",
]

CancelCallback = Callable[[], bool]

_STATE_PRIORITY: dict[RhythmBoundaryState, int] = {
    "KEEP_SINGLE": 0,
    "KEEP_REATTACK": 0,
    "MERGE_CONTINUATION": 1,
    "SUPPRESS_EXTRA": 2,
}


class RhythmDecodeCancelled(RuntimeError):
    pass


def _finite(value: object, field_name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be finite") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _bounded(value: object, field_name: str) -> float:
    numeric = _finite(value, field_name)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must be in [0, 1]")
    return numeric


def _cancel_if_requested(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise RhythmDecodeCancelled()


@dataclass(frozen=True, slots=True)
class RhythmDecodeConfig:
    """Conservative fixed weights for diagnostic proposal decoding."""

    decision_margin: float = 0.08
    merge_min_score: float = 0.62
    suppress_min_score: float = 0.68
    merge_max_gap_beats: float = 0.125
    merge_min_gap_beats: float = -0.05
    merge_min_boundary_continuity: float = 0.55
    merge_max_onset_support: float = 0.48
    suppress_max_candidate_confidence: float = 0.35
    suppress_max_onset_support: float = 0.30
    suppress_max_duration_beats: float = 0.125
    suppress_min_grid_distance_beats: float = 0.10

    def __post_init__(self) -> None:
        for field_name in (
            "decision_margin",
            "merge_min_score",
            "suppress_min_score",
            "merge_min_boundary_continuity",
            "merge_max_onset_support",
            "suppress_max_candidate_confidence",
            "suppress_max_onset_support",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name),
            )
        for field_name in (
            "merge_max_gap_beats",
            "suppress_max_duration_beats",
            "suppress_min_grid_distance_beats",
        ):
            numeric = _finite(getattr(self, field_name), field_name)
            if numeric < 0.0:
                raise ValueError(f"{field_name} must be non-negative")
            object.__setattr__(self, field_name, numeric)
        minimum_gap = _finite(
            self.merge_min_gap_beats,
            "merge_min_gap_beats",
        )
        if minimum_gap > self.merge_max_gap_beats:
            raise ValueError("merge gap bounds are reversed")
        object.__setattr__(self, "merge_min_gap_beats", minimum_gap)


@dataclass(frozen=True, slots=True)
class RhythmBoundaryObservation:
    """One candidate plus its bounded relationship to the previous pitch peer."""

    candidate_id: str
    previous_candidate_id: str | None
    candidate_confidence: float
    duration_beats: float
    grid_distance_beats: float
    onset_support: float
    boundary_continuity: float
    contour_stability: float
    chord_support: float
    voice_continuity: float
    inter_onset_fit: float
    gap_beats: float | None
    regular_repeat: bool = False

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id or "")
        previous = (
            None
            if self.previous_candidate_id is None
            else str(self.previous_candidate_id or "")
        )
        if not candidate_id or len(candidate_id) > 256:
            raise ValueError("candidate_id is required")
        if previous is not None and (not previous or len(previous) > 256):
            raise ValueError("previous_candidate_id is invalid")
        if previous == candidate_id:
            raise ValueError("a candidate cannot follow itself")
        for field_name in (
            "candidate_confidence",
            "onset_support",
            "boundary_continuity",
            "contour_stability",
            "chord_support",
            "voice_continuity",
            "inter_onset_fit",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name),
            )
        duration = _finite(self.duration_beats, "duration_beats")
        distance = _finite(self.grid_distance_beats, "grid_distance_beats")
        if duration <= 0.0 or distance < 0.0:
            raise ValueError("duration must be positive and grid distance non-negative")
        gap = None if self.gap_beats is None else _finite(self.gap_beats, "gap_beats")
        if (previous is None) != (gap is None):
            raise ValueError("gap_beats and previous_candidate_id must appear together")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "previous_candidate_id", previous)
        object.__setattr__(self, "duration_beats", duration)
        object.__setattr__(self, "grid_distance_beats", distance)
        object.__setattr__(self, "gap_beats", gap)
        object.__setattr__(self, "regular_repeat", bool(self.regular_repeat))


@dataclass(frozen=True, slots=True)
class RhythmDecodeDecision:
    candidate_id: str
    previous_candidate_id: str | None
    state: RhythmBoundaryState
    score: float
    alternative_score: float
    reason_codes: tuple[str, ...]

    @property
    def confidence(self) -> float:
        margin = max(0.0, self.score - self.alternative_score)
        return min(0.95, max(0.50, 0.50 + margin * 0.75))


@dataclass(frozen=True, slots=True)
class RhythmDecodePath:
    decisions: tuple[RhythmDecodeDecision, ...]
    total_score: float
    version: str = RHYTHM_DECODE_VERSION


@dataclass(frozen=True, slots=True)
class _PathNode:
    total_score: float
    previous_state: RhythmBoundaryState | None
    local_score: float
    alternative_score: float
    reasons: tuple[str, ...]


def _keep_score(item: RhythmBoundaryObservation) -> float:
    grid_fit = max(0.0, 1.0 - item.grid_distance_beats / 0.125)
    if item.previous_candidate_id is None:
        return min(
            1.0,
            0.40
            + 0.25 * item.candidate_confidence
            + 0.15 * item.onset_support
            + 0.10 * item.contour_stability
            + 0.05 * max(item.chord_support, item.voice_continuity)
            + 0.05 * grid_fit,
        )
    return min(
        1.0,
        0.35
        + 0.25 * item.onset_support
        + 0.15 * item.candidate_confidence
        + 0.10 * item.inter_onset_fit
        + 0.08 * grid_fit
        + 0.04 * item.chord_support
        + 0.03 * item.voice_continuity
        + (0.08 if item.regular_repeat else 0.0),
    )


def _merge_score(item: RhythmBoundaryObservation) -> float:
    assert item.gap_beats is not None
    gap_fit = max(
        0.0,
        1.0 - max(0.0, item.gap_beats) / 0.125,
    )
    return max(
        0.0,
        min(
            1.0,
            0.05
            + 0.32 * item.boundary_continuity
            + 0.18 * (1.0 - item.onset_support)
            + 0.15 * item.contour_stability
            + 0.12 * item.inter_onset_fit
            + 0.08 * gap_fit
            + 0.10 * item.candidate_confidence
            - 0.18 * item.chord_support
            - (0.30 if item.regular_repeat else 0.0),
        ),
    )


def _suppress_score(item: RhythmBoundaryObservation) -> float:
    off_grid = min(1.0, item.grid_distance_beats / 0.125)
    shortness = max(0.0, 1.0 - item.duration_beats / 0.125)
    return max(
        0.0,
        min(
            1.0,
            0.02
            + 0.24 * (1.0 - item.candidate_confidence)
            + 0.22 * (1.0 - item.onset_support)
            + 0.16 * (1.0 - item.contour_stability)
            + 0.16 * off_grid
            + 0.12 * shortness
            + 0.08 * (1.0 - item.voice_continuity)
            - 0.20 * item.chord_support,
        ),
    )


def _local_options(
    item: RhythmBoundaryObservation,
    config: RhythmDecodeConfig,
) -> dict[RhythmBoundaryState, tuple[float, float, tuple[str, ...]]]:
    keep_state: RhythmBoundaryState = (
        "KEEP_SINGLE"
        if item.previous_candidate_id is None
        else "KEEP_REATTACK"
    )
    keep = _keep_score(item)
    output = {
        keep_state: (
            keep,
            0.0,
            (
                "acoustic_note_support",
                "protected_single_or_reattack",
            ),
        )
    }

    if item.previous_candidate_id is not None and item.gap_beats is not None:
        merge = _merge_score(item)
        merge_legal = (
            config.merge_min_gap_beats
            <= item.gap_beats
            <= config.merge_max_gap_beats
            and item.boundary_continuity
            >= config.merge_min_boundary_continuity
            and item.onset_support <= config.merge_max_onset_support
            and item.chord_support <= 0.01
            and not item.regular_repeat
            and merge >= config.merge_min_score
            and merge >= keep + config.decision_margin
        )
        if merge_legal:
            output["MERGE_CONTINUATION"] = (
                merge,
                keep,
                (
                    "same_pitch_boundary",
                    "continuous_frame_support",
                    "weak_reattack_evidence",
                    "rhythmic_interval_support",
                    "structured_path_selected",
                ),
            )

    suppress = _suppress_score(item)
    suppress_legal = (
        item.candidate_confidence
        <= config.suppress_max_candidate_confidence
        and item.onset_support <= config.suppress_max_onset_support
        and item.duration_beats <= config.suppress_max_duration_beats
        and item.grid_distance_beats
        >= config.suppress_min_grid_distance_beats
        and item.chord_support <= 0.01
        and item.voice_continuity <= 0.20
        and suppress >= config.suppress_min_score
        and suppress >= keep + config.decision_margin
    )
    if suppress_legal:
        output["SUPPRESS_EXTRA"] = (
            suppress,
            keep,
            (
                "weak_acoustic_evidence",
                "short_activation",
                "off_grid_under_trusted_project_grid",
                "no_chord_or_voice_support",
                "structured_path_selected",
            ),
        )
    return output


def _better_node(
    candidate: _PathNode,
    current: _PathNode | None,
) -> bool:
    if current is None:
        return True
    if not math.isclose(
        candidate.total_score,
        current.total_score,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        return candidate.total_score > current.total_score
    candidate_previous = candidate.previous_state
    current_previous = current.previous_state
    if candidate_previous is None:
        return current_previous is not None
    if current_previous is None:
        return False
    return (
        _STATE_PRIORITY[candidate_previous],
        candidate_previous,
    ) < (
        _STATE_PRIORITY[current_previous],
        current_previous,
    )


def decode_rhythm_boundaries(
    observations: Sequence[RhythmBoundaryObservation],
    *,
    config: RhythmDecodeConfig | None = None,
    cancelled: CancelCallback | None = None,
) -> RhythmDecodePath:
    """Decode one ordered same-pitch sequence with deterministic tie-breaking."""

    settings = config or RhythmDecodeConfig()
    items = tuple(observations)
    if not items:
        return RhythmDecodePath(decisions=(), total_score=0.0)
    seen: set[str] = set()
    for index, item in enumerate(items):
        if index % RHYTHM_DECODE_CHUNK_SIZE == 0:
            _cancel_if_requested(cancelled)
        if item.candidate_id in seen:
            raise ValueError("candidate ids must be unique within a decode path")
        expected_previous = None if index == 0 else items[index - 1].candidate_id
        if item.previous_candidate_id != expected_previous:
            raise ValueError("observations must form one ordered pitch path")
        seen.add(item.candidate_id)

    layers: list[dict[RhythmBoundaryState, _PathNode]] = []
    previous_layer: dict[RhythmBoundaryState, _PathNode] = {}
    for index, item in enumerate(items):
        if index % RHYTHM_DECODE_CHUNK_SIZE == 0:
            _cancel_if_requested(cancelled)
        options = _local_options(item, settings)
        layer: dict[RhythmBoundaryState, _PathNode] = {}
        if not previous_layer:
            for state, (score, alternative, reasons) in options.items():
                layer[state] = _PathNode(
                    total_score=score,
                    previous_state=None,
                    local_score=score,
                    alternative_score=alternative,
                    reasons=reasons,
                )
        else:
            for state, (score, alternative, reasons) in options.items():
                for previous_state, previous_node in previous_layer.items():
                    if (
                        state == "MERGE_CONTINUATION"
                        and previous_state == "SUPPRESS_EXTRA"
                    ):
                        continue
                    node = _PathNode(
                        total_score=previous_node.total_score + score,
                        previous_state=previous_state,
                        local_score=score,
                        alternative_score=alternative,
                        reasons=reasons,
                    )
                    if _better_node(node, layer.get(state)):
                        layer[state] = node
        if not layer:
            raise ValueError("rhythm decode produced no legal state")
        layers.append(layer)
        previous_layer = layer

    final_state = min(
        previous_layer,
        key=lambda state: (
            -previous_layer[state].total_score,
            _STATE_PRIORITY[state],
            state,
        ),
    )
    total_score = previous_layer[final_state].total_score
    states: list[RhythmBoundaryState] = [final_state]
    for index in range(len(items) - 1, 0, -1):
        previous_state = layers[index][states[-1]].previous_state
        if previous_state is None:
            raise ValueError("rhythm decode path is incomplete")
        states.append(previous_state)
    states.reverse()

    decisions = tuple(
        RhythmDecodeDecision(
            candidate_id=item.candidate_id,
            previous_candidate_id=item.previous_candidate_id,
            state=state,
            score=layers[index][state].local_score,
            alternative_score=layers[index][state].alternative_score,
            reason_codes=layers[index][state].reasons,
        )
        for index, (item, state) in enumerate(zip(items, states))
    )
    _cancel_if_requested(cancelled)
    return RhythmDecodePath(decisions=decisions, total_score=total_score)


__all__ = [
    "RHYTHM_DECODE_CHUNK_SIZE",
    "RHYTHM_DECODE_VERSION",
    "RhythmBoundaryObservation",
    "RhythmBoundaryState",
    "RhythmDecodeCancelled",
    "RhythmDecodeConfig",
    "RhythmDecodeDecision",
    "RhythmDecodePath",
    "decode_rhythm_boundaries",
]
