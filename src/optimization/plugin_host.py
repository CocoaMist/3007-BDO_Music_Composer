"""Uniform orchestration for the built-in optimizer and .bdoopt plugins."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from . import OptimizationLevel, OptimizerConfig, optimize_tracks
from .builtin import OptimizationResult, OptimizationTextSpec
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


class HostOptimizationError(InvalidOptimizationPreview):
    """Marks validation and loader failures owned by the application host."""


class PluginOptimizationError(RuntimeError):
    """Keeps plugin exception text opaque at the worker/UI boundary."""


_BUILTIN_CAPABILITY_SOURCES = {
    "note_cleanup": "修复音块",
    "velocity": "力度",
    "quantize": "量化",
    "articulation": "奏法",
    "humanization": "轻微自然化",
    "effects": "声音效果",
}
_BUILTIN_SCOPE_SOURCES = {
    "global": "全局",
    "single_track": "单轨",
}


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

    def localized_display_name(
        self,
        translate: Callable[[str], str] | None = None,
        *,
        format_translate: Callable[..., str] | None = None,
    ) -> str:
        if self.algorithm_id != BUILTIN_SAFE_ID:
            return self.display_name
        return OptimizationTextSpec.create(self.display_name).render(
            translate,
            format_translate=format_translate,
        )

    def localized_description(
        self,
        translate: Callable[[str], str] | None = None,
        *,
        format_translate: Callable[..., str] | None = None,
    ) -> str:
        if self.algorithm_id != BUILTIN_SAFE_ID:
            return self.description
        return OptimizationTextSpec.create(self.description).render(
            translate,
            format_translate=format_translate,
        )

    def localized_capabilities(
        self,
        translate: Callable[[str], str] | None = None,
        *,
        format_translate: Callable[..., str] | None = None,
    ) -> tuple[str, ...]:
        if self.algorithm_id != BUILTIN_SAFE_ID:
            return self.capabilities
        return tuple(
            OptimizationTextSpec.create(
                _BUILTIN_CAPABILITY_SOURCES.get(value, value)
            ).render(translate, format_translate=format_translate)
            for value in self.capabilities
        )

    def localized_scopes(
        self,
        translate: Callable[[str], str] | None = None,
        *,
        format_translate: Callable[..., str] | None = None,
    ) -> tuple[str, ...]:
        if self.algorithm_id != BUILTIN_SAFE_ID:
            return self.scopes
        return tuple(
            OptimizationTextSpec.create(
                _BUILTIN_SCOPE_SOURCES.get(value, value)
            ).render(translate, format_translate=format_translate)
            for value in self.scopes
        )


@dataclass(frozen=True)
class OptimizationSession:
    descriptor: HostAlgorithmDescriptor
    original_fingerprint: str
    base_tracks: list
    request: OptimizationRequest
    preview: OptimizationPreview
    builtin_result: OptimizationResult | None = None
    host_diagnostic_specs: tuple[OptimizationTextSpec, ...] = ()

    def apply(self, current_tracks: Sequence[object]) -> tuple[list, EffectChange | None]:
        if tracks_fingerprint(current_tracks) != self.original_fingerprint:
            raise InvalidOptimizationPreview("the editor changed after analysis; analyse again")
        return apply_preview(self.base_tracks, self.request, self.preview)

    def localized_preview(
        self,
        translate: Callable[[str], str] | None = None,
        *,
        format_translate: Callable[..., str] | None = None,
    ) -> OptimizationPreview:
        """Render only host-owned preview text in the active UI locale.

        External plugin identity, summary, details and diagnostics remain
        byte-for-byte plugin output.  Host compatibility diagnostics are kept
        as specs so they can still follow the UI locale.  Operations and the
        source fingerprint are never rebuilt or localized.
        """

        if translate is None and format_translate is None:
            return self.preview
        host_count = len(self.host_diagnostic_specs)
        plugin_diagnostics = (
            self.preview.diagnostics[:-host_count]
            if host_count
            else self.preview.diagnostics
        )
        diagnostics = plugin_diagnostics + tuple(
            spec.render(translate, format_translate=format_translate)
            for spec in self.host_diagnostic_specs
        )
        if self.builtin_result is None:
            if diagnostics == self.preview.diagnostics:
                return self.preview
            return replace(self.preview, diagnostics=diagnostics)
        return replace(
            self.preview,
            summary=self.builtin_result.simple_summary_text(
                translate,
                format_translate=format_translate,
            ),
            details=tuple(self.builtin_result.summary_text(
                translate,
                format_translate=format_translate,
            ).splitlines()),
            diagnostics=diagnostics,
        )


@dataclass(frozen=True, slots=True)
class HostAlgorithmDiscovery:
    algorithms: tuple[HostAlgorithmDescriptor, ...]
    diagnostics: tuple[str, ...]


def _source_compatibility_diagnostic_specs(
    request: OptimizationRequest,
) -> tuple[OptimizationTextSpec, ...]:
    """Describe imported game-map issues without treating them as plugin failures."""

    pitch_issues = 0
    drum_issues = 0
    articulation_issues = 0
    for track in request.tracks:
        if track.track_id not in request.target_track_ids:
            continue
        supported = request.supported_pitches.get(track.instrument_id)
        valid_ntypes = {
            0,
            *(ntype for ntype, _label in request.supported_articulations.get(track.instrument_id, ())),
        }
        for note in track.notes:
            pitch_issues += int(bool(supported and note.pitch not in supported))
            drum_issues += int(
                track.is_percussion and (not 48 <= note.pitch <= 64 or note.ntype != 99)
            )
            articulation_issues += int(not track.is_percussion and note.ntype not in valid_ntypes)
    diagnostics: list[OptimizationTextSpec] = []
    if pitch_issues:
        diagnostics.append(OptimizationTextSpec.create(
            "输入已有 {count} 个音符超出当前乐器映射；"
            "优化仅保留，不会新增，请在转换检查中处理。",
            {"count": pitch_issues},
        ))
    if drum_issues:
        diagnostics.append(OptimizationTextSpec.create(
            "输入已有 {count} 个鼓音尚未规范为 BDO 48–64/type 99；"
            "优化仅保留，请在转换检查中处理。",
            {"count": drum_issues},
        ))
    if articulation_issues:
        diagnostics.append(OptimizationTextSpec.create(
            "输入已有 {count} 个未验证奏法；优化会保护人工值，不会复制或新增。",
            {"count": articulation_issues},
        ))
    return tuple(diagnostics)


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
) -> tuple[OptimizationResult, OptimizationRequest, OptimizationPreview]:
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
    return result, request, preview


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
        raise HostOptimizationError(
            f"{descriptor.display_name} does not support {scope} optimization"
        )
    try:
        original_fingerprint = tracks_fingerprint(tracks)
        safe_config = builtin_config_for_intensity(base_config, intensity)
    except Exception as exc:
        raise HostOptimizationError(str(exc) or type(exc).__name__) from exc
    if descriptor.algorithm_id == BUILTIN_SAFE_ID:
        try:
            result, request, preview = _builtin_preview(
                tracks, bpm, time_sig, supported_articulations, safe_config,
                intensity, scope, valid_instrument_ids,
            )
            diagnostic_specs = _source_compatibility_diagnostic_specs(request)
            preview = replace(
                preview,
                diagnostics=preview.diagnostics + tuple(
                    spec.source_text() for spec in diagnostic_specs
                ),
            )
        except Exception as exc:
            raise HostOptimizationError(str(exc) or type(exc).__name__) from exc
        return OptimizationSession(
            descriptor,
            original_fingerprint,
            list(tracks),
            request,
            preview,
            replace(result, tracks=[]),
            diagnostic_specs,
        )

    try:
        base_tracks = list(tracks)
        if descriptor.requires_safe_prepass:
            safe_result = optimize_tracks(
                base_tracks, bpm, supported_articulations, safe_config, time_sig
            )
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
    except Exception as exc:
        raise HostOptimizationError(str(exc) or type(exc).__name__) from exc

    # Never trust the exception class chosen by third-party code as provenance:
    # a plugin could import and raise HostOptimizationError itself. Normalize
    # every exception crossing the plugin call boundary to an opaque marker.
    try:
        preview = plugin.analyse(request, environment)
    except Exception as exc:
        raise PluginOptimizationError(str(exc) or type(exc).__name__) from exc
    try:
        if not isinstance(preview, OptimizationPreview):
            raise TypeError("optimizer plugin returned an incompatible preview object")
        if (
            preview.algorithm_id != descriptor.algorithm_id
            or preview.algorithm_version != descriptor.version
        ):
            raise InvalidOptimizationPreview(
                "preview algorithm identity does not match manifest"
            )
        diagnostic_specs = _source_compatibility_diagnostic_specs(request)
        preview = replace(
            preview,
            diagnostics=preview.diagnostics + tuple(
                spec.source_text() for spec in diagnostic_specs
            ),
        )
        validate_preview(request, preview)
    except Exception as exc:
        raise HostOptimizationError(str(exc) or type(exc).__name__) from exc
    return OptimizationSession(
        descriptor,
        original_fingerprint,
        base_tracks,
        request,
        preview,
        host_diagnostic_specs=diagnostic_specs,
    )


__all__ = [
    "BUILTIN_SAFE_ID",
    "HostAlgorithmDescriptor",
    "HostAlgorithmDiscovery",
    "HostOptimizationError",
    "OptimizationSession",
    "analyse_with_algorithm",
    "builtin_config_for_intensity",
    "discover_host_algorithms",
    "optimizer_plugin_dir",
]
