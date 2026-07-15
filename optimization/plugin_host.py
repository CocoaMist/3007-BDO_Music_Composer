"""Uniform orchestration for the built-in optimizer and .bdoopt plugins."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from . import OptimizationLevel, OptimizerConfig, optimize_tracks
from .plugin_api import (
    EffectChange,
    InvalidOptimizationPreview,
    OptimizationIntensity,
    OptimizationPreview,
    OptimizationRequest,
    apply_preview,
    build_request,
    preview_from_tracks,
    tracks_fingerprint,
    validate_preview,
)
from .plugin_loader import (
    BundleDiscovery,
    OptimizerBundleDescriptor,
    discover_optimizer_bundles,
    load_optimizer_bundle,
    optimizer_plugin_dir,
)


BUILTIN_SAFE_ID = "bdo-safe"
BUILTIN_SAFE_VERSION = "1"


@dataclass(frozen=True, slots=True)
class HostAlgorithmDescriptor:
    algorithm_id: str
    version: str
    display_name: str
    description: str
    scopes: tuple[str, ...]
    capabilities: tuple[str, ...]
    requires_safe_prepass: bool
    bundle: OptimizerBundleDescriptor | None = None


@dataclass(frozen=True)
class OptimizationSession:
    descriptor: HostAlgorithmDescriptor
    original_fingerprint: str
    base_tracks: list
    request: OptimizationRequest
    preview: OptimizationPreview

    def apply(self, current_tracks: Sequence[object]) -> tuple[list, EffectChange | None]:
        if tracks_fingerprint(current_tracks) != self.original_fingerprint:
            raise InvalidOptimizationPreview("the editor changed after analysis; analyse again")
        return apply_preview(self.base_tracks, self.request, self.preview)


@dataclass(frozen=True, slots=True)
class HostAlgorithmDiscovery:
    algorithms: tuple[HostAlgorithmDescriptor, ...]
    diagnostics: tuple[str, ...]


def discover_host_algorithms() -> HostAlgorithmDiscovery:
    discovery: BundleDiscovery = discover_optimizer_bundles()
    algorithms = [HostAlgorithmDescriptor(
        BUILTIN_SAFE_ID,
        BUILTIN_SAFE_VERSION,
        "BDO 游戏安全优化",
        "保持音符数量、音高集合、乐器映射和手动奏法的确定性安全优化。",
        ("global", "single_track"),
        ("note_cleanup", "velocity", "quantize", "articulation", "humanization", "effects"),
        False,
    )]
    algorithms.extend(HostAlgorithmDescriptor(
        item.manifest.plugin_id,
        item.manifest.version,
        item.manifest.display_name,
        item.manifest.description,
        item.manifest.scopes,
        item.manifest.capabilities,
        item.manifest.requires_safe_prepass,
        item,
    ) for item in discovery.bundles)
    return HostAlgorithmDiscovery(tuple(algorithms), discovery.diagnostics)


def builtin_config_for_intensity(base: OptimizerConfig, intensity: OptimizationIntensity) -> OptimizerConfig:
    common = dict(level=OptimizationLevel.SAFE, game_safe_only=True, allow_track_creation=False)
    if intensity is OptimizationIntensity.CONSERVATIVE:
        return replace(
            base,
            **common,
            apply_articulations=False,
            humanize=False,
            optimize_effects=False,
            allow_global_effect_write=False,
        )
    if intensity is OptimizationIntensity.DEEP:
        return replace(
            base,
            **common,
            optimize_blocks=True,
            polish_velocity=True,
            apply_articulations=True,
            analyse_music_theory=True,
            soft_quantize=True,
            humanize=True,
            humanize_timing_ms=18.0,
            humanize_velocity=8,
            optimize_effects=True,
        )
    return replace(
        base,
        **common,
        optimize_blocks=True,
        polish_velocity=True,
        apply_articulations=True,
        analyse_music_theory=True,
        soft_quantize=True,
        humanize=True,
        humanize_timing_ms=12.0,
        humanize_velocity=6,
        optimize_effects=True,
    )


def _builtin_preview(
    tracks: list,
    bpm: int,
    time_sig: int,
    supported_articulations: dict[int, list[tuple[int, str]]],
    config: OptimizerConfig,
    intensity: OptimizationIntensity,
    scope: str,
    valid_instrument_ids: frozenset[int] | None = None,
) -> tuple[list, OptimizationRequest, OptimizationPreview]:
    request = build_request(
        tracks, bpm, time_sig, config.target_track_ids or frozenset(), config.supported_pitches,
        supported_articulations, intensity,
        scope,
        valid_instrument_ids=valid_instrument_ids,
    )
    result = optimize_tracks(tracks, bpm, supported_articulations, config, time_sig)
    preview = preview_from_tracks(
        request,
        result.tracks,
        algorithm_id=BUILTIN_SAFE_ID,
        algorithm_version=BUILTIN_SAFE_VERSION,
        summary=result.simple_summary_text(),
        details=result.summary_text().splitlines(),
    )
    operations = list(preview.operations)
    effect = result.effect_suggestion
    if effect is not None and effect.writable and effect.changed:
        operations.append(EffectChange(
            effect.suggested_reverb, effect.suggested_delay, effect.suggested_chorus,
            "; ".join(effect.reasons),
        ))
        preview = replace(preview, operations=tuple(operations))
    validate_preview(request, preview)
    return result.tracks, request, preview


def analyse_with_algorithm(
    descriptor: HostAlgorithmDescriptor,
    tracks: list,
    bpm: int,
    time_sig: int,
    supported_articulations: dict[int, list[tuple[int, str]]],
    base_config: OptimizerConfig,
    intensity: OptimizationIntensity,
    scope: str,
    valid_instrument_ids: frozenset[int] | None = None,
) -> OptimizationSession:
    if scope not in descriptor.scopes:
        raise ValueError(f"{descriptor.display_name} does not support {scope} optimization")
    original_fingerprint = tracks_fingerprint(tracks)
    safe_config = builtin_config_for_intensity(base_config, intensity)
    if descriptor.algorithm_id == BUILTIN_SAFE_ID:
        _result_tracks, request, preview = _builtin_preview(
            tracks, bpm, time_sig, supported_articulations, safe_config, intensity, scope,
            valid_instrument_ids,
        )
        return OptimizationSession(descriptor, original_fingerprint, list(tracks), request, preview)

    base_tracks = list(tracks)
    if descriptor.requires_safe_prepass:
        safe_result = optimize_tracks(base_tracks, bpm, supported_articulations, safe_config, time_sig)
        base_tracks = safe_result.tracks
    request = build_request(
        base_tracks,
        bpm,
        time_sig,
        base_config.target_track_ids or frozenset(),
        base_config.supported_pitches,
        supported_articulations,
        intensity,
        scope,
        valid_instrument_ids=valid_instrument_ids,
    )
    if descriptor.bundle is None:
        raise RuntimeError("external algorithm descriptor has no bundle")
    plugin, environment = load_optimizer_bundle(descriptor.bundle)
    preview = plugin.analyse(request, environment)
    if not isinstance(preview, OptimizationPreview):
        raise TypeError("optimizer plugin returned an incompatible preview object")
    if preview.algorithm_id != descriptor.algorithm_id or preview.algorithm_version != descriptor.version:
        raise InvalidOptimizationPreview("preview algorithm identity does not match manifest")
    validate_preview(request, preview)
    return OptimizationSession(descriptor, original_fingerprint, base_tracks, request, preview)


__all__ = [
    "BUILTIN_SAFE_ID",
    "HostAlgorithmDescriptor",
    "HostAlgorithmDiscovery",
    "OptimizationSession",
    "analyse_with_algorithm",
    "builtin_config_for_intensity",
    "discover_host_algorithms",
    "optimizer_plugin_dir",
]
