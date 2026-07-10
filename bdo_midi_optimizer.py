#!/usr/bin/env python3
"""MIDI cleanup, phrasing, and BDO articulation suggestions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from bdo_articulation_profiles import profile_for
from bdo_music_theory import TheoryContext, analyse_music, is_non_chord_tone


@dataclass
class OptimizerConfig:
    optimize_blocks: bool = True
    polish_velocity: bool = True
    apply_articulations: bool = True
    soft_quantize: bool = True
    grid_division: int = 16
    quantize_strength: float = 0.65
    quantize_window_ms: float = 18.0
    min_melodic_duration_ms: float = 38.0
    min_drum_duration_ms: float = 28.0
    max_drum_duration_ms: float = 80.0
    overlap_gap_ms: float = 4.0
    legato_gap_ms: float = 45.0
    phrase_break_ms: float = 420.0
    max_auto_articulations_per_phrase: int = 3
    max_suggestions_per_phrase: int = 3
    min_notes_between_articulations: int = 2
    max_velocity: int = 121
    min_velocity: int = 24
    preserve_existing_dynamics: bool = True
    expressive_velocity_span: int = 18
    respect_manual_track_fx: bool = True
    analyse_music_theory: bool = True


@dataclass
class TrackOptimizationReport:
    track_id: int
    display_name: str
    before_notes: int
    after_notes: int
    duplicate_notes_removed: int = 0
    overlaps_trimmed: int = 0
    short_notes_extended: int = 0
    notes_quantized: int = 0
    velocities_changed: int = 0
    articulations_added: int = 0
    articulation_counts: dict[int, int] = field(default_factory=dict)
    suggestions: list["ArticulationSuggestion"] = field(default_factory=list)
    suggestions_only: int = 0
    articulation_candidates_skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(
            (
                self.duplicate_notes_removed,
                self.overlaps_trimmed,
                self.short_notes_extended,
                self.notes_quantized,
                self.velocities_changed,
                self.articulations_added,
            )
        )


@dataclass
class ArticulationSuggestion:
    """A conflict-resolved candidate shown in the optimizer preview."""

    note_indices: tuple[int, ...]
    ntype: int
    technique: str
    confidence: float
    evidence: str
    reason: str
    auto_applicable: bool
    applied: bool = False
    theory_context: str = ""


@dataclass(frozen=True)
class _Candidate:
    note_indices: tuple[int, ...]
    ntype: int
    confidence: float
    reason: str


@dataclass
class OptimizationResult:
    tracks: list
    reports: list[TrackOptimizationReport]

    @property
    def changed(self) -> bool:
        return any(report.changed for report in self.reports)

    def summary_text(self) -> str:
        lines = ["MIDI 优化报告"]
        total_removed = sum(r.duplicate_notes_removed for r in self.reports)
        total_trimmed = sum(r.overlaps_trimmed for r in self.reports)
        total_quantized = sum(r.notes_quantized for r in self.reports)
        total_velocity = sum(r.velocities_changed for r in self.reports)
        total_art = sum(r.articulations_added for r in self.reports)
        total_suggestions = sum(r.suggestions_only for r in self.reports)
        lines.append(
            f"总计：去重 {total_removed}，修重叠 {total_trimmed}，量化 {total_quantized}，"
            f"力度润色 {total_velocity}，奏法 {total_art}"
        )
        if total_suggestions:
            lines.append(f"仅建议奏法 {total_suggestions}（未写入工程）")
        lines.append("")
        for report in self.reports:
            status = "已优化" if report.changed else "无变化"
            lines.append(
                f"[{status}] Track {report.track_id}: {report.display_name} · "
                f"{report.before_notes}->{report.after_notes} notes"
            )
            detail = (
                f"  去重 {report.duplicate_notes_removed} · 重叠 {report.overlaps_trimmed} · "
                f"短音 {report.short_notes_extended} · 量化 {report.notes_quantized} · "
                f"力度 {report.velocities_changed} · 奏法 {report.articulations_added}"
            )
            lines.append(detail)
            if report.articulation_counts:
                counts = ", ".join(f"type {ntype}: {count}" for ntype, count in sorted(report.articulation_counts.items()))
                lines.append(f"  奏法分布：{counts}")
            if report.suggestions_only:
                lines.append(f"  仅建议 {report.suggestions_only} · 跳过候选 {report.articulation_candidates_skipped}")
            for suggestion in report.suggestions:
                state = "已加入预览" if suggestion.applied else "仅建议"
                theory = f" · {suggestion.theory_context}" if suggestion.theory_context else ""
                lines.append(
                    f"  - [{state}] {suggestion.technique} · {suggestion.confidence:.0%} · "
                    f"{suggestion.evidence} · {suggestion.reason}{theory}"
                )
            for warning in report.warnings:
                lines.append(f"  - {warning}")
        return "\n".join(lines)


def _replace_track(track, notes: list, notes_optimized: bool | None = None):
    return track.__class__(
        track_id=track.track_id,
        notes=notes,
        gm_program=track.gm_program,
        is_percussion=track.is_percussion,
        display_name=track.display_name,
        bdo_instrument_id=track.bdo_instrument_id,
        muted=track.muted,
        solo=track.solo,
        volume_scale=track.volume_scale,
        duration_scale=track.duration_scale,
        articulation_type=track.articulation_type,
        marnian_synth_mode=getattr(track, "marnian_synth_mode", "basic"),
        color=track.color,
        effect_settings_placeholder=dict(track.effect_settings_placeholder),
        notes_optimized=(
            bool(getattr(track, "notes_optimized", False))
            if notes_optimized is None
            else notes_optimized
        ),
    )


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _supports(supported: set[int], ntype: int) -> bool:
    return ntype in supported


def _beat_ms(bpm: int) -> float:
    return 60000.0 / max(1, min(240, int(bpm or 120)))


def _grid_ms(bpm: int, division: int) -> float:
    # division=16 means sixteenth notes.
    return _beat_ms(bpm) * 4.0 / max(1, division)


def _soft_quantize_start(start: float, grid: float, config: OptimizerConfig) -> tuple[float, bool]:
    if grid <= 0:
        return start, False
    target = round(start / grid) * grid
    delta = target - start
    if abs(delta) > config.quantize_window_ms:
        return start, False
    moved = start + delta * config.quantize_strength
    return max(0.0, moved), abs(moved - start) >= 0.5


def _note_groups_by_start(notes: Iterable, tolerance_ms: float = 12.0) -> dict[int, list]:
    groups: dict[int, list] = {}
    for note in notes:
        key = round(note.start / tolerance_ms)
        groups.setdefault(key, []).append(note)
    return groups


def _dedupe_notes(notes: list, report: TrackOptimizationReport) -> list:
    notes = sorted(notes, key=lambda n: (n.start, n.pitch, -n.vel, -n.dur))
    result = []
    seen: dict[tuple[int, int, int], object] = {}
    for note in notes:
        key = (round(note.start / 5.0), note.pitch, int(getattr(note, "ntype", 0)))
        existing = seen.get(key)
        if existing is None:
            seen[key] = note
            result.append(note)
            continue
        report.duplicate_notes_removed += 1
        if note.vel > existing.vel or note.dur > existing.dur:
            replacement = existing._replace(vel=max(existing.vel, note.vel), dur=max(existing.dur, note.dur))
            index = result.index(existing)
            result[index] = replacement
            seen[key] = replacement
    return sorted(result, key=lambda n: (n.start, n.pitch))


def _fix_timing(notes: list, is_percussion: bool, bpm: int, config: OptimizerConfig,
                report: TrackOptimizationReport) -> list:
    fixed = []
    min_dur = config.min_drum_duration_ms if is_percussion else config.min_melodic_duration_ms
    grid = _grid_ms(bpm, config.grid_division)

    for note in notes:
        start = float(note.start)
        if config.soft_quantize:
            start, moved = _soft_quantize_start(start, grid, config)
            if moved:
                report.notes_quantized += 1
        dur = float(note.dur)
        if dur < min_dur:
            dur = min_dur
            report.short_notes_extended += 1
        if is_percussion and dur > config.max_drum_duration_ms:
            dur = config.max_drum_duration_ms
        fixed.append(note._replace(start=start, dur=dur))

    if is_percussion:
        return sorted(fixed, key=lambda n: (n.start, n.pitch))

    by_pitch: dict[int, list] = {}
    for note in fixed:
        by_pitch.setdefault(note.pitch, []).append(note)

    replacements: dict[tuple[float, int, float], object] = {}
    for pitch_notes in by_pitch.values():
        pitch_notes.sort(key=lambda n: n.start)
        for current, nxt in zip(pitch_notes, pitch_notes[1:]):
            max_end = nxt.start - config.overlap_gap_ms
            if current.start + current.dur > max_end:
                new_dur = max(config.min_melodic_duration_ms, max_end - current.start)
                if new_dur < current.dur:
                    replacements[(current.start, current.pitch, current.dur)] = current._replace(dur=new_dur)
                    report.overlaps_trimmed += 1

    result = []
    for note in fixed:
        result.append(replacements.get((note.start, note.pitch, note.dur), note))

    result.sort(key=lambda n: (n.start, n.pitch))
    for idx, note in enumerate(result[:-1]):
        nxt = result[idx + 1]
        if nxt.pitch == note.pitch:
            continue
        gap = nxt.start - (note.start + note.dur)
        if 0 < gap <= config.legato_gap_ms and note.dur >= 120:
            result[idx] = note._replace(dur=max(note.dur, nxt.start - note.start - config.overlap_gap_ms))
    return result


def _polish_velocity(notes: list, is_percussion: bool, bpm: int, config: OptimizerConfig,
                     report: TrackOptimizationReport) -> list:
    if not notes:
        return notes
    beat = _beat_ms(bpm)
    source_span = max(note.vel for note in notes) - min(note.vel for note in notes)
    preserve_dynamics = config.preserve_existing_dynamics and source_span >= config.expressive_velocity_span
    chord_groups = _note_groups_by_start(notes)
    chord_sizes = {id(note): len(group) for group in chord_groups.values() for note in group}
    result = []
    for note in notes:
        old = int(note.vel)
        beat_pos = int(note.start // beat) % 4 if beat > 0 else 0
        factor = 1.0
        if preserve_dynamics:
            # A performance that already contains contrast is more valuable
            # than a generic beat-based curve. Keep it, only clarifying a bar
            # entrance very slightly.
            if beat_pos == 0:
                factor *= 1.02
        elif beat_pos == 0:
            factor *= 1.05
        elif beat_pos == 2:
            factor *= 1.025
        else:
            factor *= 0.965
        if is_percussion:
            if note.pitch in {35, 36, 48}:  # kick
                factor *= 1.08
            elif note.pitch in {38, 40, 49, 50}:  # snare
                factor *= 1.06
            elif note.pitch in {42, 44, 46, 54, 56, 58, 61, 62}:
                factor *= 0.88
        else:
            chord_size = chord_sizes.get(id(note), 1)
            if chord_size >= 4:
                factor *= 0.90
            elif chord_size >= 3:
                factor *= 0.94
            if note.dur >= 700:
                factor *= 0.96
            elif note.dur <= 100:
                factor *= 0.98
        new_vel = _clamp(round(old * factor), config.min_velocity, config.max_velocity)
        if new_vel != old:
            report.velocities_changed += 1
        result.append(note._replace(vel=new_vel))
    return result


def _onset_groups(notes: list, tolerance_ms: float = 12.0) -> list[list[int]]:
    groups: list[list[int]] = []
    for index, note in enumerate(notes):
        if groups and abs(note.start - notes[groups[-1][0]].start) <= tolerance_ms:
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def _phrase_numbers(notes: list, config: OptimizerConfig) -> list[int]:
    phrase, result, previous_end = 0, [], None
    for note in notes:
        if previous_end is not None and note.start - previous_end >= config.phrase_break_ms:
            phrase += 1
        result.append(phrase)
        previous_end = max(previous_end or 0.0, note.start + note.dur)
    return result


def _melodic_lines(notes: list, groups: list[list[int]], config: OptimizerConfig) -> list[list[int]]:
    """Conservatively connect singleton events into voice-leading lines.

    Chords terminate active lines: this prevents accompaniment tones from being
    mistaken for a melody continuation after a polyphonic event.
    """
    lines: list[list[int]] = []
    active: list[list[int]] = []
    for group in groups:
        if len(group) != 1:
            active = []
            continue
        index = group[0]
        note = notes[index]
        choices = []
        for line in active:
            previous = notes[line[-1]]
            gap = note.start - (previous.start + previous.dur)
            interval = abs(note.pitch - previous.pitch)
            if -600 <= gap <= config.phrase_break_ms and interval <= 12:
                choices.append((interval * 20 + abs(gap), line))
        if choices:
            line = min(choices, key=lambda item: item[0])[1]
            line.append(index)
        else:
            line = [index]
            lines.append(line)
            active.append(line)
        active = [candidate for candidate in active if note.start - notes[candidate[-1]].start <= config.phrase_break_ms]
    return lines


def _major_or_minor_chord(notes: list, group: list[int]) -> int:
    if len(group) < 3:
        return 0
    pitch_classes = {notes[index].pitch % 12 for index in group}
    for root in pitch_classes:
        if {root, (root + 4) % 12, (root + 7) % 12}.issubset(pitch_classes):
            return 9
        if {root, (root + 3) % 12, (root + 7) % 12}.issubset(pitch_classes):
            return 10
    return 0


def _add_candidate(candidates: list[_Candidate], indices: tuple[int, ...], ntype: int,
                   confidence: float, reason: str, supported: set[int]) -> None:
    if ntype in supported:
        candidates.append(_Candidate(indices, ntype, confidence, reason))


def _repeats_two_note_motif(notes: list, line: list[int], position: int, beat: float) -> bool:
    """Recognise a repeated two-note cell without mistaking free melody for a riff."""
    if position < 2 or position + 1 >= len(line):
        return False
    older, previous, current, nxt = (notes[line[item]] for item in (position - 2, position - 1, position, position + 1))
    old_interval = previous.pitch - older.pitch
    new_interval = nxt.pitch - current.pitch
    old_ioi = previous.start - older.start
    new_ioi = nxt.start - current.start
    return (
        old_interval == new_interval
        and 0 < old_ioi <= beat * 1.25
        and abs(old_ioi - new_ioi) <= max(18.0, beat * 0.10)
    )


def _candidates_for_line(notes: list, line: list[int], position: int, inst_id: int,
                         supported: set[int], bpm: int, theory: TheoryContext | None = None) -> list[_Candidate]:
    index = line[position]
    note = notes[index]
    previous = notes[line[position - 1]] if position else None
    nxt = notes[line[position + 1]] if position + 1 < len(line) else None
    after_next = notes[line[position + 2]] if position + 2 < len(line) else None
    beat = _beat_ms(bpm)
    candidates: list[_Candidate] = []
    if inst_id == 0x11 and nxt and note.dur >= 700 and nxt.start < note.start + note.dur - 40:
        _add_candidate(candidates, (index,), 11, 0.90, "长音跨入后续材料，适合踏板保持", supported)
    if inst_id in {0x27, 0x28} and note.dur >= 450:
        ntype = 26 if note.vel < 70 else 27 if note.vel < 100 else 28
        _add_candidate(candidates, (index,), ntype, 0.90, "管乐长音按力度分层", supported)
    if nxt:
        gap = nxt.start - (note.start + note.dur)
        interval = nxt.pitch - note.pitch
        if -20 <= gap <= min(80, beat * 0.22) and 1 <= interval <= 4:
            _add_candidate(candidates, (index,), 3, 0.91, "同声部小上行紧密连接", supported)
        if -20 <= gap <= min(80, beat * 0.22) and -4 <= interval <= -1:
            _add_candidate(candidates, (index,), 12, 0.91, "同声部小下行紧密连接", supported)
        returns = after_next and after_next.pitch == note.pitch and after_next.start - nxt.start <= 260
        if note.dur >= 450 and returns and abs(interval) == 1:
            _add_candidate(candidates, (index,), 4, 0.89, "长音含半音邻音往返", supported)
        if note.dur >= 450 and returns and abs(interval) == 2:
            _add_candidate(candidates, (index,), 5, 0.89, "长音含全音邻音往返", supported)
        ioi = max(1.0, nxt.start - note.start)
        detached = note.dur / ioi <= 0.42 and gap >= max(24.0, beat * 0.08)
        if detached:
            repeated = sum(notes[item].pitch == note.pitch for item in line[max(0, position - 2):position + 3]) >= 2
            motif = _repeats_two_note_motif(notes, line, position, beat)
            if inst_id in {0x0E, 0x24, 0x25, 0x26} and (repeated or motif):
                detail = "两音动机重复" if motif else "重复音"
                _add_candidate(candidates, (index,), 13, 0.88 + (0.04 if motif else 0.0), f"短促、分离且{detail}的节奏 riff", supported)
            else:
                _add_candidate(candidates, (index,), 2, 0.86, "短促且有可听间隔的同声部音", supported)
    if inst_id == 0x0E:
        if note.dur <= 90 and note.vel <= 58:
            _add_candidate(candidates, (index,), 24, 0.87, "极短弱力度贝斯填充", supported)
        if note.dur <= 180 and note.vel >= 104:
            _add_candidate(candidates, (index,), 22, 0.87, "高力度短时值贝斯重击", supported)
    if inst_id == 0x10 and position + 3 < len(line):
        run = [notes[item] for item in line[position:position + 4]]
        steps = [run[pos + 1].pitch - run[pos].pitch for pos in range(3)]
        spacings = [run[pos + 1].start - run[pos].start for pos in range(3)]
        if all(1 <= abs(step) <= 2 for step in steps) and len({step > 0 for step in steps}) == 1 and all(
            0 < spacing <= beat * 0.34 for spacing in spacings
        ):
            _add_candidate(candidates, (index,), 16, 0.72, "同向快速级进的竖琴滑奏候选", supported)
    nearby = [notes[item] for item in line[max(0, position - 1):position + 2]]
    if note.pitch >= 72 and note.dur >= 120 and all(abs(item.start - note.start) >= 240 for item in nearby if item is not note):
        _add_candidate(candidates, (index,), 14, 0.72, "高音区稀疏点缀", supported)
    if inst_id in {0x14, 0x18} and note.dur >= 700:
        _add_candidate(candidates, (index,), 20 if note.vel < 100 else 21, 0.70, "合成长音的音色候选", supported)
    if theory is None:
        return candidates
    role = theory.roles[index]
    strength = theory.beat_strengths[index]
    at_phrase_edge = position + 1 == len(line) or theory.phrase_numbers[index] != theory.phrase_numbers[line[position + 1]]
    adjusted = []
    for candidate in candidates:
        confidence = candidate.confidence
        suffix = []
        # Do not decorate a cadence-like/phrase-ending held tone or an unstable
        # non-chord tone as if it were a generic connected melody gesture.
        if at_phrase_edge and candidate.ntype in {3, 12, 4, 5, 16}:
            confidence -= 0.18
            suffix.append("句尾保守降级")
        if is_non_chord_tone(note, theory) and candidate.ntype in {3, 12, 4, 5}:
            confidence -= 0.10
            suffix.append("非和弦音降级")
        if role in {"bass_riff", "rhythm"} and candidate.ntype == 13:
            confidence += 0.04
            suffix.append("低音/节奏型匹配")
        if role != "melody" and candidate.ntype in {3, 12, 4, 5}:
            confidence -= 0.12
            suffix.append("非旋律角色降级")
        if strength >= 0.95 and candidate.ntype in {2, 13}:
            confidence += 0.02
            suffix.append("强拍支撑")
        if previous and nxt and candidate.ntype in {3, 12}:
            incoming = note.pitch - previous.pitch
            outgoing = nxt.pitch - note.pitch
            if incoming and outgoing and incoming * outgoing < 0:
                confidence -= 0.14
                suffix.append("旋律折返，滑音降级")
        adjusted.append(_Candidate(candidate.note_indices, candidate.ntype, max(0.0, min(1.0, confidence)),
                                   candidate.reason + ("；" + "，".join(suffix) if suffix else "")))
    return adjusted


def _apply_articulations(notes: list, supported: set[int], inst_id: int, manual_track_fx: int | None,
                         bpm: int, time_sig: int, config: OptimizerConfig, report: TrackOptimizationReport) -> list:
    if not notes or not supported:
        return notes
    if config.respect_manual_track_fx and manual_track_fx is not None:
        report.warnings.append("已设置轨道级 FX，保留手工选择且不生成自动奏法")
        return notes
    result = list(notes)
    groups = _onset_groups(notes)
    theory = analyse_music(notes, bpm, time_sig, config.phrase_break_ms) if config.analyse_music_theory else None
    phrases = list(theory.phrase_numbers) if theory else _phrase_numbers(notes, config)
    if theory and theory.tonal:
        report.warnings.append(f"乐理分析：{theory.key_root} {theory.key_mode} 调性置信度 {theory.tonal_confidence:.0%}")
    elif theory:
        report.warnings.append("乐理分析：调性不稳定，已降级为节拍、乐句与织体规则")
    candidates: list[_Candidate] = []
    locked_groups: set[tuple[int, ...]] = set()
    for group in groups:
        existing = {int(getattr(notes[index], "ntype", 0)) for index in group}
        if existing - {0}:
            locked_groups.add(tuple(group))
            for index in group:
                if int(getattr(notes[index], "ntype", 0)) not in supported:
                    result[index] = notes[index]._replace(ntype=0)
        elif inst_id == 0x10:
            ntype = _major_or_minor_chord(notes, group)
            if ntype:
                _add_candidate(candidates, tuple(group), ntype, 0.91, "明确的大/小三和弦块", supported)
    for line in _melodic_lines(notes, groups, config):
        for position, index in enumerate(line):
            if (index,) not in locked_groups:
                candidates.extend(_candidates_for_line(notes, line, position, inst_id, supported, bpm, theory))
    by_group: dict[tuple[int, ...], list[_Candidate]] = {}
    for candidate in candidates:
        by_group.setdefault(candidate.note_indices, []).append(candidate)
    phrase_counts: dict[int, int] = {}
    suggestion_counts: dict[int, int] = {}
    last_applied = -config.min_notes_between_articulations - 1
    for indices, options in sorted(by_group.items(), key=lambda item: notes[item[0][0]].start):
        candidate = max(options, key=lambda option: option.confidence)
        profile = profile_for(inst_id, candidate.ntype)
        if profile is None:
            report.articulation_candidates_skipped += 1
            continue
        # Profile metadata is evidence-backed musical knowledge, separate from
        # the BDO display label.  It can only lower confidence: a missing or
        # uncertain profile must never make an automatic edit more aggressive.
        confidence = candidate.confidence
        reason = candidate.reason
        if profile.preferred_range and any(
            not (profile.preferred_range[0] <= notes[index].pitch <= profile.preferred_range[1])
            for index in indices
        ):
            confidence -= 0.24
            reason += "；超出该奏法常用音区"
        if theory and theory.roles[indices[0]] in profile.forbidden_contexts:
            confidence -= 0.28
            reason += "；乐器资料标记为不适用于当前织体"
        if theory and profile.contexts:
            role = theory.roles[indices[0]]
            tags = {role}
            if candidate.ntype in {3, 12}:
                tags.add("connected")
            elif candidate.ntype in {4, 5, 6}:
                tags.add("ornament")
            elif candidate.ntype == 16:
                tags.add("scale_run")
            elif candidate.ntype in {26, 27, 28}:
                tags.add("sustain")
            elif candidate.ntype == 11:
                tags.add("harmony_hold")
            elif candidate.ntype == 14:
                tags.add("sparse")
            elif candidate.ntype == 22:
                tags.add("accent")
            if not tags.intersection(profile.contexts):
                confidence -= 0.12
                reason += "；与该奏法的演奏语境不完全匹配"
        if profile.change_cost == "high":
            confidence -= 0.04
        candidate = _Candidate(indices, candidate.ntype, max(0.0, confidence), reason)
        phrase = phrases[indices[0]]
        if suggestion_counts.get(phrase, 0) >= config.max_suggestions_per_phrase:
            report.articulation_candidates_skipped += 1
            continue
        game_verified = profile.auto_apply and profile.bdo_verified
        auto = (
            candidate.confidence >= 0.85
            and game_verified
            and phrase_counts.get(phrase, 0) < config.max_auto_articulations_per_phrase
            and indices[0] - last_applied > config.min_notes_between_articulations
        )
        context = ""
        if theory:
            index = indices[0]
            context = f"{theory.roles[index]} · {'强拍' if theory.beat_strengths[index] >= .95 else '弱拍'}"
            if theory.tonal:
                context += f" · {theory.key_mode} 调性"
        suggestion = ArticulationSuggestion(
            indices, candidate.ntype, profile.technique, candidate.confidence,
            str(profile.evidence), candidate.reason, game_verified, auto, context,
        )
        report.suggestions.append(suggestion)
        suggestion_counts[phrase] = suggestion_counts.get(phrase, 0) + 1
        if not auto:
            report.suggestions_only += 1
            continue
        for index in indices:
            result[index] = notes[index]._replace(ntype=candidate.ntype)
            report.articulations_added += 1
            report.articulation_counts[candidate.ntype] = report.articulation_counts.get(candidate.ntype, 0) + 1
        phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1
        last_applied = indices[0]
    return result


def optimize_tracks(tracks: list, bpm: int, supported_articulations: dict[int, list[tuple[int, str]]],
                    config: OptimizerConfig | None = None, time_sig: int = 4) -> OptimizationResult:
    config = config or OptimizerConfig()
    optimized_tracks = []
    reports = []
    for track in tracks:
        report = TrackOptimizationReport(
            track_id=track.track_id,
            display_name=track.display_name,
            before_notes=len(track.notes),
            after_notes=len(track.notes),
        )
        notes = sorted(track.notes, key=lambda note: (note.start, note.pitch, note.dur))
        if config.optimize_blocks:
            notes = _dedupe_notes(notes, report)
            notes = _fix_timing(notes, track.is_percussion or track.bdo_instrument_id == 0x0d, bpm, config, report)
        if config.polish_velocity:
            notes = _polish_velocity(notes, track.is_percussion or track.bdo_instrument_id == 0x0d, bpm, config, report)
        if config.apply_articulations and not (track.is_percussion or track.bdo_instrument_id == 0x0d):
            supported = {ntype for ntype, _label in supported_articulations.get(track.bdo_instrument_id, [])}
            notes = _apply_articulations(
                notes,
                supported,
                track.bdo_instrument_id,
                track.articulation_type,
                bpm,
                time_sig,
                config,
                report,
            )
        report.after_notes = len(notes)
        optimized_tracks.append(
            _replace_track(
                track,
                notes,
                notes_optimized=bool(getattr(track, "notes_optimized", False) or report.changed),
            )
        )
        reports.append(report)
    return OptimizationResult(optimized_tracks, reports)
