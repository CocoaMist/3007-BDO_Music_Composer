"""Extensible optimization subsystem for BDO Music Composer.

The built-in algorithm remains the default. Additional algorithms can be
registered at application startup without changing callers of ``optimize_tracks``.
"""

from __future__ import annotations

from .builtin import (
    ArticulationSuggestion,
    EffectSuggestion,
    EnsembleSuggestion,
    OptimizationLevel,
    OptimizationResult,
    OptimizerConfig,
    TrackOptimizationReport,
    optimize_tracks as _run_builtin,
)
from .registry import (
    AlgorithmDescriptor,
    OptimizerAlgorithm,
    get_algorithm,
    list_algorithms,
    register_algorithm,
    unregister_algorithm,
)
from .plugin_api import (
    PLUGIN_API_VERSION,
    CreateTrack,
    DeleteNote,
    EffectChange,
    InsertNote,
    NoteSnapshot,
    OptimizationIntensity,
    OptimizationPreview,
    OptimizationRequest,
    PluginEnvironment,
    ReplaceTrackNotes,
    ReplaceNote,
    SetTrackInstrument,
    TrackSnapshot,
)

DEFAULT_ALGORITHM = "bdo-safe"

register_algorithm(
    DEFAULT_ALGORITHM,
    _run_builtin,
    title="BDO Safe Optimizer",
    description="Deterministic cleanup, expression, articulation, and game-safe arrangement pipeline.",
)


def optimize_tracks(
    tracks: list,
    bpm: int,
    supported_articulations: dict[int, list[tuple[int, str]]],
    config: OptimizerConfig | None = None,
    time_sig: int = 4,
    *,
    algorithm: str = DEFAULT_ALGORITHM,
) -> OptimizationResult:
    """Run the selected registered optimizer using the stable public contract."""
    runner = get_algorithm(algorithm).runner
    result = runner(tracks, bpm, supported_articulations, config, time_sig)
    if not isinstance(result, OptimizationResult):
        raise TypeError(
            f"optimization algorithm {algorithm!r} returned {type(result).__name__}; "
            "expected OptimizationResult"
        )
    return result


__all__ = [
    "AlgorithmDescriptor",
    "ArticulationSuggestion",
    "DEFAULT_ALGORITHM",
    "EffectSuggestion",
    "EnsembleSuggestion",
    "OptimizationLevel",
    "OptimizationResult",
    "OptimizerAlgorithm",
    "OptimizerConfig",
    "PLUGIN_API_VERSION",
    "CreateTrack",
    "DeleteNote",
    "EffectChange",
    "InsertNote",
    "NoteSnapshot",
    "OptimizationIntensity",
    "OptimizationPreview",
    "OptimizationRequest",
    "PluginEnvironment",
    "ReplaceTrackNotes",
    "ReplaceNote",
    "SetTrackInstrument",
    "TrackSnapshot",
    "TrackOptimizationReport",
    "get_algorithm",
    "list_algorithms",
    "optimize_tracks",
    "register_algorithm",
    "unregister_algorithm",
]
