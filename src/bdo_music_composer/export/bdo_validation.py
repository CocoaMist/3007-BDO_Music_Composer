"""Structured, location-aware validation of editor tracks before BDO export."""

from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Callable, Mapping, Sequence

from bdo_music_composer.editor.pitch_transform import (
    PitchTransformPlan,
    track_uses_percussion_pitch_semantics,
)
from bdo_music_composer.editor.arrangement_clip import project_track_notes
from bdo_music_composer.editor.bdo_instrument_adaptation import (
    articulation_supports_pitch,
)

from bdo_music_composer.core.bdo_profile import BdoProfile
from bdo_common.bdo_track_effects import (
    DEFAULT_TRACK_VOLUME,
    GAME_PERCENT_MAX,
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
    raw_track_settings,
)
from bdo_music_composer.core.conversion_settings import VELOCITY_MODE_PRESERVE


SEVERITIES = ("error", "warning", "info")
MessageValue = str | int | float | tuple[int, ...]
MessageValues = tuple[tuple[str, MessageValue], ...]
Translator = Callable[[str], str]
FormatTranslator = Callable[..., str]

_EVIDENCE_STATUS_SOURCES = {
    "verified": "已验证",
    "inferred": "推断",
    "approximate": "近似",
}


def _template_fields(template: str) -> frozenset[str]:
    return frozenset(
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(template)
        if field_name
    )


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    track_id: int | None = None
    note_indices: tuple[int, ...] = ()
    evidence: str = ""
    evidence_status: str = "inferred"
    fix_id: str | None = None
    message_template: str = ""
    message_values: MessageValues = ()
    # Group-level issues such as same-instrument merge/capacity conflicts do
    # not have one primary track.  Preserve their exact lane membership so UI
    # surfaces can mark every affected track without parsing display names.
    related_track_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid validation severity: {self.severity}")
        if self.message_template:
            fields = _template_fields(self.message_template)
            names = tuple(name for name, _value in self.message_values)
            if len(names) != len(set(names)):
                raise ValueError("duplicate validation message value")
            if fields != frozenset(names):
                raise ValueError(
                    "validation message placeholders do not match values: "
                    f"{sorted(fields)} != {sorted(names)}"
                )


def _issue(
    code: str,
    severity: str,
    template: str,
    *,
    values: Mapping[str, MessageValue] | None = None,
    track_id: int | None = None,
    note_indices: tuple[int, ...] = (),
    evidence: str = "",
    evidence_status: str = "inferred",
    fix_id: str | None = None,
    related_track_ids: tuple[int, ...] = (),
) -> ValidationIssue:
    """Build an issue whose Chinese message remains backward compatible.

    ``message_template`` is the stable source-language localization key.  Only
    its named placeholders carry track names or numeric runtime values, so a UI
    can translate the fixed text without translating user or game evidence.
    """

    message_values: MessageValues = tuple((values or {}).items())
    message = template.format(**dict(message_values))
    return ValidationIssue(
        code,
        severity,
        message,
        track_id,
        note_indices,
        evidence,
        evidence_status,
        fix_id,
        template,
        message_values,
        tuple(int(track_id) for track_id in related_track_ids),
    )


def localized_validation_message(
    issue: ValidationIssue,
    translate: Translator | None = None,
    *,
    format_translate: FormatTranslator | None = None,
) -> str:
    """Render one validation issue in the caller's locale.

    ``translate`` receives only stable source text.  Runtime values are applied
    afterwards and are never passed through translation.  ``format_translate``
    accepts the same ``(template, **values)`` shape as :func:`i18n.trf` and is
    provided for UI callers that already expose that boundary.  Legacy issues
    without a structured template continue to translate their ``message``.
    """

    template = issue.message_template or issue.message
    values = dict(issue.message_values)
    if format_translate is not None:
        try:
            return str(format_translate(template, **values))
        except (IndexError, KeyError, TypeError, ValueError):
            return issue.message
    translated = translate(template) if translate is not None else template
    if _template_fields(translated) != _template_fields(template):
        return issue.message
    try:
        return translated.format(**values)
    except (IndexError, KeyError, TypeError, ValueError):
        return issue.message


def localized_evidence_status(
    status: str,
    translate: Translator | None = None,
) -> str:
    """Localize a host-owned evidence enum while preserving unknown values."""

    source = _EVIDENCE_STATUS_SOURCES.get(status)
    if source is None:
        return status
    return translate(source) if translate is not None else source


def evidence_status_source(status: str) -> str | None:
    """Return the fixed source key for a known evidence-status enum."""

    return _EVIDENCE_STATUS_SOURCES.get(status)


@dataclass(frozen=True, slots=True)
class ValidationContext:
    transpose: int
    active_track_ids: frozenset[int]
    instrument_names: Mapping[int, str]
    gm_drum_map: Mapping[int, int]
    serialize_instrument: Callable[[object], int]
    sample_only_percussion_ids: frozenset[int] = frozenset()
    velocity_mode: str = VELOCITY_MODE_PRESERVE
    effects: tuple[int, int, tuple[int, int, int] | None] = (0, 0, None)
    pitch_plan: PitchTransformPlan | None = None

    def effective_transpose(
        self,
        track: object,
        *,
        drum_instrument_id: int = 0x0D,
    ) -> int:
        if self.pitch_plan is None:
            return (
                0
                if track_uses_percussion_pitch_semantics(
                    track,
                    drum_instrument_id=drum_instrument_id,
                )
                else int(self.transpose)
            )
        return self.pitch_plan.effective_track_semitones(
            track,
            drum_instrument_id=drum_instrument_id,
        )


def _evidence(profile: BdoProfile, instrument_id: int) -> tuple[str, str]:
    rule = profile.instruments.get(instrument_id)
    evidence = rule.evidence if rule is not None else profile.evidence
    return evidence.source, evidence.status


@dataclass(frozen=True, slots=True)
class _TrackValidationInput:
    track: object
    track_id: int
    instrument_id: int
    effective_transpose: int
    serialized_id: int
    evidence: str
    evidence_status: str
    notes: tuple[object, ...]


def _track_validation_input(
    track: object,
    profile: BdoProfile,
    context: ValidationContext,
) -> _TrackValidationInput:
    """Freeze the track facts shared by the ordered validation passes."""

    track_id = int(track.track_id)
    instrument_id = int(track.bdo_instrument_id)
    effective_transpose = context.effective_transpose(
        track,
        drum_instrument_id=profile.drum_instrument_id,
    )
    serialized_id = int(context.serialize_instrument(track))
    evidence, evidence_status = _evidence(profile, instrument_id)
    notes = project_track_notes(track)
    return _TrackValidationInput(
        track=track,
        track_id=track_id,
        instrument_id=instrument_id,
        effective_transpose=effective_transpose,
        serialized_id=serialized_id,
        evidence=evidence,
        evidence_status=evidence_status,
        notes=notes,
    )


def _validate_track_scope(
    item: _TrackValidationInput,
    context: ValidationContext,
) -> list[ValidationIssue]:
    if item.track_id in context.active_track_ids:
        return []
    return [
        _issue(
            "track.excluded",
            "info",
            "当前轨道因 Mute/Solo 状态不参与导出。",
            track_id=item.track_id,
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        )
    ]


def _validate_track_basics(
    item: _TrackValidationInput,
    profile: BdoProfile,
) -> list[ValidationIssue]:
    """Validate one active track's instrument and raw mixer fields."""

    issues: list[ValidationIssue] = []
    track = item.track
    try:
        game_volume = int(
            getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
        )
    except (TypeError, ValueError, OverflowError):
        game_volume = -1
    if not 0 <= game_volume <= 255:
        issues.append(_issue(
            "track.volume_wire_range", "error",
            "轨道游戏音量不是有效的 v9 字节。",
            track_id=item.track_id, evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    elif game_volume > GAME_PERCENT_MAX:
        issues.append(_issue(
            "track.volume_legacy_range", "warning",
            "轨道音量 {volume} 超过当前游戏编辑范围 0–100；"
            "未编辑时会原样保留。",
            values={"volume": game_volume},
            track_id=item.track_id, evidence=item.evidence,
            evidence_status="verified",
        ))

    try:
        raw_settings = raw_track_settings(
            getattr(track, "bdo_track_settings", (0,) * 8)
        )
    except ValueError:
        raw_settings = None
        issues.append(_issue(
            "track.effects_wire_shape", "error",
            "轨道效果设置不是有效的 8 字节 v9 数据。",
            track_id=item.track_id, evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    if raw_settings is not None:
        legacy_sends = tuple(
            raw_settings[index]
            for index in (
                TRACK_REVERB_SEND_INDEX,
                TRACK_DELAY_SEND_INDEX,
                TRACK_CHORUS_SEND_INDEX,
            )
            if raw_settings[index] > GAME_PERCENT_MAX
        )
        if legacy_sends:
            issues.append(_issue(
                "track.effects_legacy_range", "warning",
                "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；"
                "未编辑项会原样保留。",
                track_id=item.track_id, evidence=item.evidence,
                evidence_status="inferred",
            ))

    if item.instrument_id not in profile.instruments:
        issues.append(_issue(
            "instrument.unknown", "error",
            "未知 BDO 乐器 ID 0x{instrument_id:02X}。",
            values={"instrument_id": item.instrument_id},
            track_id=item.track_id,
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
        ))
    return issues


def _validate_drum_pitch_rules(
    item: _TrackValidationInput,
    profile: BdoProfile,
    context: ValidationContext,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    notes = item.notes
    unknown = tuple(
        index for index, note in enumerate(notes)
        if not (
            int(note.ntype) == 99
            and profile.drum_pitch_min
            <= int(note.pitch)
            <= profile.drum_pitch_max
        )
        and int(note.pitch) not in context.gm_drum_map
    )
    if unknown:
        pitches = sorted({int(notes[index].pitch) for index in unknown})
        issues.append(_issue(
            "drum.unmapped", "error",
            "{count} 个 GM 打击乐音符没有 BDO 映射：{pitches}。",
            values={"count": len(unknown), "pitches": str(pitches[:12])},
            track_id=item.track_id, note_indices=unknown,
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    mapped = tuple(
        index for index, note in enumerate(notes)
        if int(note.pitch) in context.gm_drum_map
        and not (
            int(note.ntype) == 99
            and profile.drum_pitch_min
            <= int(note.pitch)
            <= profile.drum_pitch_max
        )
    )
    if mapped:
        issues.append(_issue(
            "drum.remap", "info",
            "导出会把 {count} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。",
            values={"count": len(mapped)},
            track_id=item.track_id, note_indices=mapped,
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    return issues


def _validate_melodic_pitch_rules(
    item: _TrackValidationInput,
    profile: BdoProfile,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    shifted = [
        int(note.pitch) + item.effective_transpose for note in item.notes
    ]
    broad_invalid = tuple(
        index for index, pitch in enumerate(shifted)
        if pitch < 12 or pitch > 119
    )
    if broad_invalid:
        issues.append(_issue(
            "pitch.wire_clamp", "error",
            "{count} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。",
            values={"count": len(broad_invalid)},
            track_id=item.track_id, note_indices=broad_invalid,
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    rule = profile.instruments.get(item.instrument_id)
    if (
        rule is None
        or rule.evidence.status != "verified"
        or (rule.pitch_min is None and not rule.allowed_pitches)
    ):
        issues.append(_issue(
            "pitch.range_unverified", "warning",
            "当前乐器缺少经过验证的完整游戏音域。",
            track_id=item.track_id,
            note_indices=tuple(range(len(item.notes))),
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    elif rule is not None:
        unsupported = tuple(
            index for index, pitch in enumerate(shifted)
            if rule.supports_pitch(pitch) is False
        )
        if unsupported:
            issues.append(_issue(
                "pitch.instrument_unsupported", "error",
                "{count} 个音符不在当前乐器的已知游戏音域内。",
                values={"count": len(unsupported)},
                track_id=item.track_id, note_indices=unsupported,
                evidence=item.evidence,
                evidence_status=item.evidence_status,
            ))
    return issues


def _validate_track_pitch_rules(
    item: _TrackValidationInput,
    profile: BdoProfile,
    context: ValidationContext,
) -> list[ValidationIssue]:
    """Validate percussion mapping and melodic game-range constraints."""

    if item.instrument_id == profile.drum_instrument_id:
        return _validate_drum_pitch_rules(item, profile, context)
    if bool(item.track.is_percussion):
        return [
            _issue(
                "percussion.unverified_mapping", "warning",
                "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。",
                track_id=item.track_id,
                note_indices=tuple(range(len(item.notes))),
                evidence=item.evidence,
                evidence_status=item.evidence_status,
            )
        ]
    return _validate_melodic_pitch_rules(item, profile)


def _validate_track_export_transforms(
    item: _TrackValidationInput,
    profile: BdoProfile,
) -> list[ValidationIssue]:
    """Describe or reject deferred note transformations on one track."""

    issues: list[ValidationIssue] = []
    track = item.track
    notes = item.notes
    if (
        item.effective_transpose
        and notes
        and not bool(track.is_percussion)
        and item.instrument_id != profile.drum_instrument_id
    ):
        issues.append(_issue(
            "export.transpose", "info",
            "导出会将此轨道全部音符移调 {transpose:+d} 半音。",
            values={"transpose": item.effective_transpose},
            track_id=item.track_id,
            note_indices=tuple(range(len(notes))),
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    duration_scale = float(getattr(track, "duration_scale", 1.0))
    if notes and abs(duration_scale - 1.0) > 1e-9:
        issues.append(_issue(
            "export.duration_scale", "info",
            "导出会将此轨道音符时值乘以 {duration_scale:.3g}。",
            values={"duration_scale": duration_scale},
            track_id=item.track_id,
            note_indices=tuple(range(len(notes))),
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    volume_scale = float(getattr(track, "volume_scale", 1.0))
    if notes and abs(volume_scale - 1.0) > 1e-9:
        issues.append(_issue(
            "export.velocity_scale", "error",
            "此轨道仍含旧版隐藏力度倍率 {volume_scale:.3g}；请先将它写入音符力度。",
            values={"volume_scale": volume_scale},
            track_id=item.track_id,
            note_indices=tuple(range(len(notes))),
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    return issues


def _unrouted_articulation_indices(
    item: _TrackValidationInput,
    articulation: int,
    *,
    track_wide: bool,
) -> tuple[int, ...]:
    return tuple(
        index
        for index, note in enumerate(item.notes)
        if (track_wide or int(note.ntype) == int(articulation))
        and not articulation_supports_pitch(
            item.instrument_id,
            int(articulation),
            int(note.pitch),
        )
    )


def _unrouted_articulation_issue(
    item: _TrackValidationInput,
    articulation: int,
    note_indices: tuple[int, ...],
    *,
    fix_id: str | None = None,
) -> ValidationIssue:
    return _issue(
        "articulation.pitch_unsupported", "error",
        "FX type {articulation} 在当前乐器的 {count} 个音高上没有游戏路由。",
        values={"articulation": articulation, "count": len(note_indices)},
        track_id=item.track_id,
        note_indices=note_indices,
        evidence=item.evidence,
        evidence_status=item.evidence_status,
        fix_id=fix_id,
    )


def _validate_track_articulations(
    item: _TrackValidationInput,
    profile: BdoProfile,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    articulation = getattr(item.track, "articulation_type", None)
    rule = profile.instruments.get(item.instrument_id)
    track_articulation_valid = articulation is not None and not (
        rule is None or int(articulation) not in rule.articulations
    )
    if (
        articulation is not None
        and not track_articulation_valid
    ):
        issues.append(_issue(
            "articulation.unsupported", "error",
            "FX type {articulation} 不属于当前乐器。",
            values={"articulation": int(articulation)},
            track_id=item.track_id,
            note_indices=tuple(range(len(item.notes))),
            evidence=item.evidence,
            evidence_status=item.evidence_status,
            fix_id="clear_track_articulation",
        ))
    elif track_articulation_valid and item.notes:
        unsupported_pitches = _unrouted_articulation_indices(
            item,
            int(articulation),
            track_wide=True,
        )
        if unsupported_pitches:
            issues.append(_unrouted_articulation_issue(
                item,
                int(articulation),
                unsupported_pitches,
                fix_id="clear_track_articulation",
            ))
        else:
            issues.append(_issue(
                "export.track_articulation", "info",
                "导出会把此轨道全部音符设为 FX type {articulation}。",
                values={"articulation": int(articulation)},
                track_id=item.track_id,
                note_indices=tuple(range(len(item.notes))),
                evidence=item.evidence,
                evidence_status=item.evidence_status,
            ))
    if articulation is None and rule is not None:
        unsupported_note_types = sorted({
            int(note.ntype)
            for note in item.notes
            if int(note.ntype) not in rule.articulations
        })
        for note_type in unsupported_note_types:
            note_indices = tuple(
                index
                for index, note in enumerate(item.notes)
                if int(note.ntype) == note_type
            )
            issues.append(_issue(
                "articulation.note_unsupported", "error",
                "FX type {articulation} 不属于当前乐器。",
                values={"articulation": note_type},
                track_id=item.track_id,
                note_indices=note_indices,
                evidence=item.evidence,
                evidence_status=item.evidence_status,
            ))
        partial_route_types = sorted({
            int(note.ntype)
            for note in item.notes
            if int(note.ntype) in rule.articulations
            and not articulation_supports_pitch(
                item.instrument_id,
                int(note.ntype),
                int(note.pitch),
            )
        })
        for note_type in partial_route_types:
            note_indices = _unrouted_articulation_indices(
                item,
                note_type,
                track_wide=False,
            )
            issues.append(_unrouted_articulation_issue(
                item,
                note_type,
                note_indices,
            ))
    return issues


def _validate_track_notes_and_articulation(
    item: _TrackValidationInput,
    profile: BdoProfile,
    context: ValidationContext,
) -> list[ValidationIssue]:
    issues = _validate_track_pitch_rules(item, profile, context)
    issues.extend(_validate_track_export_transforms(item, profile))
    issues.extend(_validate_track_articulations(item, profile))
    if (
        item.instrument_id in context.sample_only_percussion_ids
        and item.notes
    ):
        issues.append(_issue(
            "percussion.sample_only", "warning",
            "该乐器当前只有样本键位证据，完整音域仍待游戏验证。",
            track_id=item.track_id,
            note_indices=tuple(range(len(item.notes))),
            evidence=item.evidence,
            evidence_status=item.evidence_status,
        ))
    return issues


@dataclass(frozen=True, slots=True)
class _MergedInstrumentInput:
    instrument_id: int
    sources: tuple[object, ...]
    note_count: int
    source_names: str
    source_track_ids: tuple[int, ...]


def _merged_instrument_input(
    instrument_id: int,
    sources: Sequence[object],
) -> _MergedInstrumentInput:
    stable_sources = tuple(sources)
    return _MergedInstrumentInput(
        instrument_id=instrument_id,
        sources=stable_sources,
        note_count=sum(len(track.notes) for track in stable_sources),
        source_names=", ".join(
            str(track.display_name) for track in stable_sources
        ),
        source_track_ids=tuple(
            int(track.track_id) for track in stable_sources
        ),
    )


def _validate_same_instrument_group(
    group: _MergedInstrumentInput,
    profile: BdoProfile,
) -> list[ValidationIssue]:
    """Validate merge visibility and shared Volume/Aux ownership."""

    if len(group.sources) <= 1:
        return []
    issues = [
        _issue(
            "tracks.merge", "info",
            "导出会把 {track_count} 条轨道按乐器 0x{instrument_id:02X} 合并：{track_names}。",
            values={
                "track_count": len(group.sources),
                "instrument_id": group.instrument_id,
                "track_names": group.source_names,
            },
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
            related_track_ids=group.source_track_ids,
        )
    ]
    volumes: set[int] = set()
    for track in group.sources:
        try:
            volumes.add(int(getattr(
                track,
                "bdo_track_volume",
                DEFAULT_TRACK_VOLUME,
            )))
        except (TypeError, ValueError, OverflowError):
            continue
    if len(volumes) > 1:
        issues.append(_issue(
            "tracks.volume_conflict", "error",
            "同一游戏乐器的 {track_count} 条轨道使用了不同音量；"
            "游戏只保存一个乐器音量，请先统一。",
            values={"track_count": len(group.sources)},
            evidence=profile.evidence.source,
            evidence_status="verified",
            related_track_ids=group.source_track_ids,
        ))
    send_values: set[tuple[int, int, int]] = set()
    for track in group.sources:
        try:
            settings = raw_track_settings(
                getattr(track, "bdo_track_settings", (0,) * 8)
            )
        except ValueError:
            continue
        send_values.add((
            settings[TRACK_REVERB_SEND_INDEX],
            settings[TRACK_DELAY_SEND_INDEX],
            settings[TRACK_CHORUS_SEND_INDEX],
        ))
    if len(send_values) > 1:
        issues.append(_issue(
            "tracks.effects_conflict", "error",
            "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；"
            "游戏只保存一组发送量，请先统一。",
            values={"track_count": len(group.sources)},
            evidence=profile.evidence.source,
            evidence_status="inferred",
            related_track_ids=group.source_track_ids,
        ))
    return issues


def _validate_instrument_capacity(
    group: _MergedInstrumentInput,
    profile: BdoProfile,
) -> list[ValidationIssue]:
    """Validate the merged note capacity for one serialized instrument."""

    capacity_policy = profile.limit_policy("notes_per_instrument")
    if group.note_count <= capacity_policy.value:
        return []
    if capacity_policy.is_hard:
        severity = "error"
        template = (
            "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，"
            "超过已验证上限 {limit}。"
        )
    else:
        severity = "warning"
        template = (
            "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，"
            "超过工具保守审阅阈值 {limit}；"
            "导出器不会因此截断，但游戏实际 noteCount 由账号能力运行时下发，"
            "请在游戏内确认。"
        )
    return [
        _issue(
            "capacity.instrument",
            severity,
            template,
            values={
                "instrument_id": group.instrument_id,
                "count": group.note_count,
                "limit": capacity_policy.value,
            },
            evidence=capacity_policy.evidence.source,
            evidence_status=capacity_policy.evidence.status,
            related_track_ids=group.source_track_ids,
        )
    ]


def _validate_score_export_settings(
    tracks: Sequence[object],
    profile: BdoProfile,
    context: ValidationContext,
) -> list[ValidationIssue]:
    """Validate score-wide velocity policy and master-effect bytes."""

    issues: list[ValidationIssue] = []
    active_note_count = sum(
        len(track.notes)
        for track in tracks
        if int(track.track_id) in context.active_track_ids
    )
    if (
        active_note_count
        and context.velocity_mode != VELOCITY_MODE_PRESERVE
    ):
        issues.append(_issue(
            "export.velocity_mode", "info",
            "导出会使用 {velocity_mode} 力度处理模式修改活动音符。",
            values={"velocity_mode": context.velocity_mode},
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
        ))
    if any((context.effects[0], context.effects[1], context.effects[2])):
        issues.append(_issue(
            "export.global_effects", "info",
            "导出会写入全局效果：reverb={reverb}, delay={delay}, chorus={chorus}。",
            values={
                "reverb": context.effects[0],
                "delay": context.effects[1],
                "chorus": str(context.effects[2]),
            },
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
        ))
    chorus_values = context.effects[2] or (0, 0, 0)
    try:
        master_values = tuple(
            int(value)
            for value in (context.effects[0], context.effects[1], *chorus_values)
        )
    except (TypeError, ValueError, OverflowError):
        master_values = (-1,)
    if any(value < 0 or value > 255 for value in master_values):
        issues.append(_issue(
            "export.global_effects_wire_range", "error",
            "主效果包含无效的 v9 字节。",
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
        ))
    elif any(value > GAME_PERCENT_MAX for value in master_values):
        issues.append(_issue(
            "export.global_effects_legacy_range", "warning",
            "主效果含超过当前游戏编辑范围 0–100 的导入值；"
            "未编辑项会原样保留。",
            evidence=profile.evidence.source,
            evidence_status="inferred",
        ))
    return issues


def validate_tracks(
    tracks: Sequence[object],
    profile: BdoProfile,
    context: ValidationContext,
) -> tuple[ValidationIssue, ...]:
    """Validate tracks in stable track, instrument-group, then score order."""

    issues: list[ValidationIssue] = []
    merged: dict[int, list[object]] = {}
    for track in tracks:
        item = _track_validation_input(track, profile, context)
        scope_issues = _validate_track_scope(item, context)
        if scope_issues:
            issues.extend(scope_issues)
            continue
        merged.setdefault(item.serialized_id, []).append(track)
        issues.extend(_validate_track_basics(item, profile))
        issues.extend(
            _validate_track_notes_and_articulation(item, profile, context)
        )

    for instrument_id, sources in sorted(merged.items()):
        group = _merged_instrument_input(instrument_id, sources)
        issues.extend(_validate_same_instrument_group(group, profile))
        issues.extend(_validate_instrument_capacity(group, profile))
    issues.extend(_validate_score_export_settings(tracks, profile, context))
    return tuple(issues)


def issues_report(
    issues: Sequence[ValidationIssue],
    *,
    translate: Translator | None = None,
    format_translate: FormatTranslator | None = None,
) -> str:
    """Create a text report, optionally localizing fixed labels and messages.

    With no translator this intentionally preserves the historical Chinese
    report shape.  Track names and evidence strings are runtime data and are
    interpolated after translation without modification.
    """

    labels = {"error": "需处理", "warning": "需人工确认", "info": "变化说明"}
    if translate is None and format_translate is None:
        lines = []
        for issue in issues:
            location = f"Track {issue.track_id}" if issue.track_id is not None else "全局"
            notes = f" · {len(issue.note_indices)} notes" if issue.note_indices else ""
            lines.append(f"[{labels[issue.severity]}] {location}{notes} · {issue.message}")
            if issue.evidence:
                lines.append(f"  证据({issue.evidence_status}): {issue.evidence}")
        return "\n".join(lines)

    def render(template: str, **values: MessageValue) -> str:
        if format_translate is not None:
            try:
                return str(format_translate(template, **values))
            except (IndexError, KeyError, TypeError, ValueError):
                return template.format(**values)
        translated = translate(template) if translate is not None else template
        if _template_fields(translated) != _template_fields(template):
            translated = template
        try:
            return translated.format(**values)
        except (IndexError, KeyError, TypeError, ValueError):
            return template.format(**values)

    lines = []
    for issue in issues:
        severity = render(labels[issue.severity])
        location = (
            render("轨道 {track_id}", track_id=issue.track_id)
            if issue.track_id is not None
            else render("全局")
        )
        notes = (
            " · " + render("{count} 个音符", count=len(issue.note_indices))
            if issue.note_indices
            else ""
        )
        message = localized_validation_message(
            issue,
            translate,
            format_translate=format_translate,
        )
        lines.append(f"[{severity}] {location}{notes} · {message}")
        if issue.evidence:
            status = localized_evidence_status(issue.evidence_status, render)
            lines.append(render(
                "  证据（{status}）：{evidence}",
                status=status,
                evidence=issue.evidence,
            ))
    return "\n".join(lines)


__all__ = [
    "ValidationContext",
    "ValidationIssue",
    "evidence_status_source",
    "issues_report",
    "localized_evidence_status",
    "localized_validation_message",
    "validate_tracks",
]
