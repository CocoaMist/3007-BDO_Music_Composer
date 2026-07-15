"""Structured, location-aware validation of editor tracks before BDO export."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from bdo_profile import BdoProfile


SEVERITIES = ("error", "warning", "info")


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

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid validation severity: {self.severity}")


@dataclass(frozen=True, slots=True)
class ValidationContext:
    transpose: int
    active_track_ids: frozenset[int]
    instrument_names: Mapping[int, str]
    gm_drum_map: Mapping[int, int]
    serialize_instrument: Callable[[object], int]
    sample_only_percussion_ids: frozenset[int] = frozenset()
    velocity_mode: str = "preserve"
    effects: tuple[int, int, tuple[int, int, int] | None] = (0, 0, None)


def _evidence(profile: BdoProfile, instrument_id: int) -> tuple[str, str]:
    rule = profile.instruments.get(instrument_id)
    evidence = rule.evidence if rule is not None else profile.evidence
    return evidence.source, evidence.status


def validate_tracks(
    tracks: Sequence[object],
    profile: BdoProfile,
    context: ValidationContext,
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    merged: dict[int, list[object]] = {}
    for track in tracks:
        track_id = int(track.track_id)
        instrument_id = int(track.bdo_instrument_id)
        serialized_id = int(context.serialize_instrument(track))
        evidence, status = _evidence(profile, instrument_id)
        notes = list(track.notes)
        if track_id not in context.active_track_ids:
            issues.append(ValidationIssue(
                "track.excluded", "info", "当前轨道因 Mute/Solo 状态不参与导出。",
                track_id, evidence=evidence, evidence_status=status,
            ))
            continue
        merged.setdefault(serialized_id, []).append(track)

        if instrument_id not in profile.instruments:
            issues.append(ValidationIssue(
                "instrument.unknown", "error", f"未知 BDO 乐器 ID 0x{instrument_id:02X}。",
                track_id, evidence=profile.evidence.source,
                evidence_status=profile.evidence.status,
            ))

        if instrument_id == profile.drum_instrument_id:
            unknown = tuple(
                index for index, note in enumerate(notes)
                if not (
                    int(note.ntype) == 99
                    and profile.drum_pitch_min <= int(note.pitch) <= profile.drum_pitch_max
                )
                and int(note.pitch) not in context.gm_drum_map
            )
            if unknown:
                pitches = sorted({int(notes[index].pitch) for index in unknown})
                issues.append(ValidationIssue(
                    "drum.unmapped", "error",
                    f"{len(unknown)} 个 GM 打击乐音符没有 BDO 映射：{pitches[:12]}。",
                    track_id, unknown, evidence, status,
                ))
            mapped = tuple(
                index for index, note in enumerate(notes)
                if int(note.pitch) in context.gm_drum_map
                and not (
                    int(note.ntype) == 99
                    and profile.drum_pitch_min <= int(note.pitch) <= profile.drum_pitch_max
                )
            )
            if mapped:
                issues.append(ValidationIssue(
                    "drum.remap", "info",
                    f"导出会把 {len(mapped)} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。",
                    track_id, mapped, evidence, status,
                ))
        elif bool(track.is_percussion):
            issues.append(ValidationIssue(
                "percussion.unverified_mapping", "warning",
                "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。",
                track_id, tuple(range(len(notes))), evidence, status,
            ))
        else:
            shifted = [int(note.pitch) + context.transpose for note in notes]
            broad_invalid = tuple(
                index for index, pitch in enumerate(shifted)
                if pitch < 12 or pitch > 119
            )
            if broad_invalid:
                issues.append(ValidationIssue(
                    "pitch.wire_clamp", "error",
                    f"{len(broad_invalid)} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。",
                    track_id, broad_invalid, evidence, status,
                ))
            rule = profile.instruments.get(instrument_id)
            if rule is None or (rule.pitch_min is None and not rule.allowed_pitches):
                issues.append(ValidationIssue(
                    "pitch.range_unverified", "warning",
                    "当前乐器缺少经过验证的完整游戏音域。",
                    track_id, tuple(range(len(notes))), evidence, status,
                ))
            elif rule is not None:
                unsupported = tuple(
                    index for index, pitch in enumerate(shifted)
                    if rule.supports_pitch(pitch) is False
                )
                if unsupported:
                    issues.append(ValidationIssue(
                        "pitch.instrument_unsupported", "error",
                        f"{len(unsupported)} 个音符不在当前乐器的已知游戏音域内。",
                        track_id, unsupported, evidence, status,
                    ))

        if context.transpose and notes and instrument_id != profile.drum_instrument_id:
            issues.append(ValidationIssue(
                "export.transpose", "info",
                f"导出会将此轨道全部音符移调 {context.transpose:+d} 半音。",
                track_id, tuple(range(len(notes))), evidence, status,
            ))
        duration_scale = float(getattr(track, "duration_scale", 1.0))
        if notes and abs(duration_scale - 1.0) > 1e-9:
            issues.append(ValidationIssue(
                "export.duration_scale", "info",
                f"导出会将此轨道音符时值乘以 {duration_scale:.3g}。",
                track_id, tuple(range(len(notes))), evidence, status,
            ))
        volume_scale = float(getattr(track, "volume_scale", 1.0))
        if notes and abs(volume_scale - 1.0) > 1e-9:
            issues.append(ValidationIssue(
                "export.velocity_scale", "info",
                f"导出会将此轨道力度乘以 {volume_scale:.3g}。",
                track_id, tuple(range(len(notes))), evidence, status,
            ))
        articulation = getattr(track, "articulation_type", None)
        rule = profile.instruments.get(instrument_id)
        if articulation is not None and (rule is None or int(articulation) not in rule.articulations):
            issues.append(ValidationIssue(
                "articulation.unsupported", "error",
                f"FX type {articulation} 不属于当前乐器。",
                track_id, tuple(range(len(notes))), evidence, status, "clear_track_articulation",
            ))
        elif articulation is not None and notes:
            issues.append(ValidationIssue(
                "export.track_articulation", "info",
                f"导出会把此轨道全部音符设为 FX type {articulation}。",
                track_id, tuple(range(len(notes))), evidence, status,
            ))
        if instrument_id in context.sample_only_percussion_ids and notes:
            issues.append(ValidationIssue(
                "percussion.sample_only", "warning",
                "该乐器当前只有样本键位证据，完整音域仍待游戏验证。",
                track_id, tuple(range(len(notes))), evidence, status,
            ))

    for instrument_id, sources in sorted(merged.items()):
        count = sum(len(track.notes) for track in sources)
        source_names = ", ".join(str(track.display_name) for track in sources)
        if len(sources) > 1:
            issues.append(ValidationIssue(
                "tracks.merge", "info",
                f"导出会把 {len(sources)} 条轨道按乐器 0x{instrument_id:02X} 合并：{source_names}。",
                evidence=profile.evidence.source,
                evidence_status=profile.evidence.status,
            ))
        if count > profile.note_limit_per_instrument:
            issues.append(ValidationIssue(
                "capacity.instrument", "error",
                f"乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过上限 {profile.note_limit_per_instrument}；导出会丢弃尾部音符。",
                evidence=profile.evidence.source,
                evidence_status=profile.evidence.status,
            ))
    active_note_count = sum(
        len(track.notes) for track in tracks if int(track.track_id) in context.active_track_ids
    )
    if active_note_count and context.velocity_mode != "preserve":
        issues.append(ValidationIssue(
            "export.velocity_mode", "info",
            f"导出会使用 {context.velocity_mode} 力度处理模式修改活动音符。",
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
        ))
    if any((context.effects[0], context.effects[1], context.effects[2])):
        issues.append(ValidationIssue(
            "export.global_effects", "info",
            f"导出会写入全局效果：reverb={context.effects[0]}, delay={context.effects[1]}, chorus={context.effects[2]}。",
            evidence=profile.evidence.source,
            evidence_status=profile.evidence.status,
        ))
    return tuple(issues)


def issues_report(issues: Sequence[ValidationIssue]) -> str:
    labels = {"error": "需处理", "warning": "需人工确认", "info": "变化说明"}
    lines = []
    for issue in issues:
        location = f"Track {issue.track_id}" if issue.track_id is not None else "全局"
        notes = f" · {len(issue.note_indices)} notes" if issue.note_indices else ""
        lines.append(f"[{labels[issue.severity]}] {location}{notes} · {issue.message}")
        if issue.evidence:
            lines.append(f"  证据({issue.evidence_status}): {issue.evidence}")
    return "\n".join(lines)


__all__ = ["ValidationContext", "ValidationIssue", "issues_report", "validate_tracks"]
