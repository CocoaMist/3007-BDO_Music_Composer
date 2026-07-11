#!/usr/bin/env python3
"""MIDI cleanup, phrasing, and BDO articulation suggestions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Iterable

from bdo_articulation_profiles import profile_for
from bdo_lyrics import LyricContext, LyricExpressionMode, align_lyrics
from bdo_music_theory import ContextClassifier, SongContext, TheoryContext, TrackRole, analyse_music, analyse_song, is_non_chord_tone
from bdo_techniques import EditOperation, RealizationKind, TECHNIQUE_PROFILES, TechniqueCandidate, instrument_family


class OptimizationLevel(StrEnum):
    SAFE = "safe"
    EXPRESSIVE = "expressive"
    ARRANGE = "arrange"


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
    level: OptimizationLevel = OptimizationLevel.SAFE
    target_track_ids: frozenset[int] | None = None
    style_override: tuple[str, ...] = ()
    context_classifier: ContextClassifier | None = None
    supported_pitches: dict[int, frozenset[int]] = field(default_factory=dict)
    allow_track_creation: bool = True
    confirmed_melody_phrases: frozenset[int] = frozenset()
    beam_width: int = 8
    max_notes_per_instrument: int = 10000
    verified_articulations: frozenset[tuple[int, int]] = frozenset()
    lyric_events: list[dict] = field(default_factory=list)
    lyric_mode: LyricExpressionMode = LyricExpressionMode.AUTO
    game_safe_only: bool = True
    humanize: bool = True
    humanize_timing_ms: float = 12.0
    humanize_velocity: int = 6
    optimize_effects: bool = True
    current_reverb: int = 0
    current_delay: int = 0
    current_chorus: tuple[int, int, int] | None = None
    allow_global_effect_write: bool = False


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
    role: str = ""
    technique_candidates: list[TechniqueCandidate] = field(default_factory=list)
    ensemble_issues: list[str] = field(default_factory=list)
    notes_added: int = 0
    humanized_notes: int = 0
    scope: str = "修改"

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
                self.notes_added,
                self.humanized_notes,
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
    technique_id: str = ""
    realization: str = "suggestion_only"
    source: str = ""


@dataclass(frozen=True)
class _Candidate:
    note_indices: tuple[int, ...]
    ntype: int
    confidence: float
    reason: str


@dataclass(frozen=True)
class EffectSuggestion:
    current_reverb: int
    current_delay: int
    current_chorus: tuple[int, int, int] | None
    suggested_reverb: int
    suggested_delay: int
    suggested_chorus: tuple[int, int, int] | None
    confidence: float
    reasons: tuple[str, ...]
    writable: bool = False

    @property
    def changed(self) -> bool:
        return (
            self.current_reverb != self.suggested_reverb
            or self.current_delay != self.suggested_delay
            or self.current_chorus != self.suggested_chorus
        )


@dataclass(frozen=True)
class EnsembleSuggestion:
    priority: int
    message: str
    track_ids: tuple[int, ...] = ()


@dataclass
class OptimizationResult:
    tracks: list
    reports: list[TrackOptimizationReport]
    song_context: SongContext | None = None
    arrangement_changes: list[str] = field(default_factory=list)
    lyric_context: LyricContext | None = None
    effect_suggestion: EffectSuggestion | None = None
    ensemble_suggestions: list[EnsembleSuggestion] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (
            bool(self.arrangement_changes)
            or any(report.changed for report in self.reports)
            or bool(self.effect_suggestion and self.effect_suggestion.writable and self.effect_suggestion.changed)
        )

    def simple_summary_text(self) -> str:
        articulations = sum(report.articulations_added for report in self.reports)
        humanized = sum(report.humanized_notes for report in self.reports)
        lines = [f"奏法 {articulations} 处 · 轻微自然化 {humanized} 个音符"]
        if self.effect_suggestion:
            effect = self.effect_suggestion
            chorus_before = effect.current_chorus or (0, 0, 0)
            chorus_after = effect.suggested_chorus or (0, 0, 0)
            lines.append(
                f"效果：混响 {effect.current_reverb}→{effect.suggested_reverb} · "
                f"延迟 {effect.current_delay}→{effect.suggested_delay} · "
                f"合唱 {chorus_before}→{chorus_after}"
            )
        for suggestion in self.ensemble_suggestions[:3]:
            lines.append(f"注意：{suggestion.message}")
        return "\n".join(lines)

    def summary_text(self) -> str:
        lines = ["MIDI 优化报告"]
        total_removed = sum(r.duplicate_notes_removed for r in self.reports)
        total_trimmed = sum(r.overlaps_trimmed for r in self.reports)
        total_quantized = sum(r.notes_quantized for r in self.reports)
        total_velocity = sum(r.velocities_changed for r in self.reports)
        total_art = sum(r.articulations_added for r in self.reports)
        total_suggestions = sum(r.suggestions_only for r in self.reports)
        total_added = sum(r.notes_added for r in self.reports)
        total_humanized = sum(r.humanized_notes for r in self.reports)
        lines.append(
            f"总计：去重 {total_removed}，修重叠 {total_trimmed}，量化 {total_quantized}，"
            f"力度润色 {total_velocity}，奏法 {total_art}，新增/拆分音 {total_added}"
        )
        if self.song_context:
            styles = "、".join(f"{tag.name} {tag.confidence:.0%}" for tag in self.song_context.styles)
            tonal = (
                f"{self.song_context.key_root} {self.song_context.key_mode} {self.song_context.tonal_confidence:.0%}"
                if self.song_context.tonal else "调性不稳定"
            )
            lines.append(f"全曲上下文：{tonal} · 风格 {styles or 'neutral'}")
        if self.lyric_context:
            lyric = self.lyric_context
            lines.append(
                f"歌词：{len(lyric.tokens)} 个音节/文本单元 · {len(lyric.alignments)} 个对齐 · "
                f"{lyric.mode.value} · 置信度 {lyric.confidence:.0%}"
            )
            lines.extend(f"  - {warning}" for warning in lyric.warnings)
        lines.append(f"游戏安全自然化：{total_humanized} 个音符")
        if self.effect_suggestion:
            effect = self.effect_suggestion
            lines.append(
                f"游戏效果：Reverb {effect.current_reverb}->{effect.suggested_reverb} · "
                f"Delay {effect.current_delay}->{effect.suggested_delay} · "
                f"Chorus {effect.current_chorus or (0, 0, 0)}->{effect.suggested_chorus or (0, 0, 0)} · "
                f"置信度 {effect.confidence:.0%}"
            )
            lines.extend(f"  - {reason}" for reason in effect.reasons)
        for suggestion in self.ensemble_suggestions:
            lines.append(f"  - 配器建议：{suggestion.message}")
        if total_suggestions:
            lines.append(f"仅建议奏法 {total_suggestions}（未写入工程）")
        lines.append("")
        for report in self.reports:
            status = "已优化" if report.changed else "无变化"
            lines.append(
                f"[{status}/{report.scope}] Track {report.track_id}: {report.display_name} · "
                f"{report.before_notes}->{report.after_notes} notes"
            )
            if report.role:
                lines.append(f"  角色：{report.role}")
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
            for issue in report.ensemble_issues:
                lines.append(f"  - 配器：{issue}")
            for candidate in report.technique_candidates:
                state = {
                    RealizationKind.NATIVE_BDO: "BDO 原生",
                    RealizationKind.MIDI_APPROXIMATION: "MIDI 近似",
                    RealizationKind.SUGGESTION_ONLY: "仅建议",
                }[candidate.realization]
                profile = TECHNIQUE_PROFILES[candidate.technique_id]
                lines.append(
                    f"  - 技法 {profile.name} · {candidate.confidence:.0%} · {state} · {candidate.reason}"
                )
        for change in self.arrangement_changes:
            lines.append(f"[编配] {change}")
        return "\n".join(lines)


def _replace_track(track, notes: list, notes_optimized: bool | None = None,
                   state_updates: dict | None = None):
    effect_state = dict(track.effect_settings_placeholder)
    effect_state.update(state_updates or {})
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
        effect_settings_placeholder=effect_state,
        performance_controls=list(getattr(track, "performance_controls", [])),
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
                if not config.game_safe_only and int(getattr(notes[index], "ntype", 0)) not in supported:
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
        game_verified = profile.auto_apply and (
            profile.bdo_verified or (inst_id, candidate.ntype) in config.verified_articulations
        )
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


def _native_ntype(inst_id: int, technique_id: str, note, nxt, supported: set[int]) -> int | None:
    mapping = {
        "staccato": 2,
        "palm_mute": 13,
        "harmonic": 14,
        "slap_pop": 22,
        "ghost_note": 24,
        "harp_gliss": 16,
        "piano_pedal": 11,
        "synth_filter_sustain": 20 if int(getattr(note, "vel", 80)) < 100 else 21,
    }
    if technique_id == "slide" and nxt is not None:
        mapping[technique_id] = 3 if nxt.pitch > note.pitch else 12
    if technique_id == "trill" and nxt is not None:
        mapping[technique_id] = 4 if abs(nxt.pitch - note.pitch) == 1 else 5
    ntype = mapping.get(technique_id)
    return ntype if ntype in supported else None


def _candidate(track_id: int, indices: tuple[int, ...], technique_id: str, confidence: float,
               reason: str, inst_id: int, notes: list, supported: set[int],
               midi_edits: tuple[EditOperation, ...] = (), requires_confirmation: bool = False) -> TechniqueCandidate:
    first = notes[indices[0]]
    nxt = notes[indices[-1] + 1] if indices[-1] + 1 < len(notes) else None
    ntype = _native_ntype(inst_id, technique_id, first, nxt, supported)
    profile = profile_for(inst_id, ntype) if ntype is not None else None
    if profile is not None and profile.bdo_verified:
        realization = RealizationKind.NATIVE_BDO
    elif midi_edits:
        realization = RealizationKind.MIDI_APPROXIMATION
    else:
        realization = RealizationKind.SUGGESTION_ONLY
    conflict_group = {
        "vibrato": "pitch_gesture", "portamento": "pitch_gesture", "brass_fall": "pitch_gesture",
        "brass_doit": "pitch_gesture", "scoop": "pitch_gesture",
        "crescendo": "dynamic_gesture", "diminuendo": "dynamic_gesture", "sforzando": "dynamic_gesture",
        "piano_pedal": "pedal", "half_pedal": "pedal", "sostenuto_pedal": "pedal",
        "soft_pedal": "soft_pedal", "timbre_sweep": "timbre", "aftertouch_swell": "pressure",
    }.get(technique_id, "attack_articulation")
    return TechniqueCandidate(
        track_id, indices, technique_id, max(0.0, min(1.0, confidence)), reason, realization,
        ntype, midi_edits, (track_id, indices[0], conflict_group), TECHNIQUE_PROFILES[technique_id].source,
        requires_confirmation,
    )


def _detect_performance_techniques(track, notes: list, family: str, supported: set[int]) -> list[TechniqueCandidate]:
    """Infer semantic technique evidence from preserved MIDI performance data."""
    if not notes:
        return []
    track_id, inst_id = int(track.track_id), int(track.bdo_instrument_id)
    events = list(getattr(track, "performance_controls", []))
    controls = [item for item in events if str(item.get("kind", "control_change")) == "control_change"]
    pitch = sorted([item for item in events if item.get("kind") == "pitchwheel"], key=lambda x: float(x.get("time", 0)))
    pressure = [item for item in events if item.get("kind") in {"aftertouch", "polytouch"}]
    result: list[TechniqueCandidate] = []

    def cc(number: int) -> list[dict]:
        return sorted([item for item in controls if int(item.get("control", -1)) == number],
                      key=lambda item: float(item.get("time", 0)))

    if family == "keys":
        if any(0 < int(item.get("value", 0)) < 64 for item in cc(64)):
            result.append(_candidate(track_id, (0,), "half_pedal", .97, "检测到连续 CC64 半踏板区间", inst_id, notes, supported))
        if any(int(item.get("value", 0)) >= 64 for item in cc(66)):
            result.append(_candidate(track_id, (0,), "sostenuto_pedal", .98, "检测到 CC66 选择性延音踏板", inst_id, notes, supported))
        if any(int(item.get("value", 0)) >= 64 for item in cc(67)):
            result.append(_candidate(track_id, (0,), "soft_pedal", .98, "检测到 CC67 柔音踏板", inst_id, notes, supported))
    pitch_values = [int(item.get("pitch", 0)) for item in pitch]
    if family in {"strings", "wind", "brass", "guitar", "bass", "synth"} and pitch_values:
        if len(pitch_values) >= 4 and max(pitch_values) - min(pitch_values) >= 350:
            changes = sum((b - a) * (c - b) < 0 for a, b, c in zip(pitch_values, pitch_values[1:], pitch_values[2:]))
            if changes >= 2:
                result.append(_candidate(track_id, (0,), "vibrato", .94, "Pitch Bend 曲线反复换向", inst_id, notes, supported))
        if max(abs(value) for value in pitch_values) >= 700:
            final = pitch_values[-1]
            if family in {"brass", "wind"} and abs(final) > 500:
                technique = "brass_doit" if final > 0 else "brass_fall"
            elif family in {"guitar", "bass"}:
                technique = "bend"
            else:
                technique = "portamento"
            result.append(_candidate(track_id, (len(notes) - 1,), technique, .9,
                                     "检测到显著 Pitch Bend 音高手势", inst_id, notes, supported))
        if any(int(item.get("value", 0)) >= 64 for item in cc(65)):
            result.append(_candidate(track_id, (0,), "portamento", .98, "检测到 CC65 Portamento 开关", inst_id, notes, supported))
    expression = cc(11)
    if len(expression) >= 2:
        delta = int(expression[-1].get("value", 0)) - int(expression[0].get("value", 0))
        if abs(delta) >= 14:
            technique = "crescendo" if delta > 0 else "diminuendo"
            result.append(_candidate(track_id, (0,), technique, min(.98, .78 + abs(delta) / 180),
                                     f"CC11 表情曲线净变化 {delta:+d}", inst_id, notes, supported))
    timbre = cc(74)
    if family == "synth" and len(timbre) >= 2:
        spread = max(int(item.get("value", 0)) for item in timbre) - min(int(item.get("value", 0)) for item in timbre)
        if spread >= 12:
            result.append(_candidate(track_id, (0,), "timbre_sweep", min(.98, .8 + spread / 200),
                                     "检测到 CC74 音色/滤波曲线", inst_id, notes, supported))
    if pressure and family in {"synth", "keys", "wind"}:
        peak = max(int(item.get("value", 0)) for item in pressure)
        if peak >= 24:
            result.append(_candidate(track_id, (0,), "aftertouch_swell", min(.98, .72 + peak / 220),
                                     "检测到 Channel/Poly Aftertouch 压力表情", inst_id, notes, supported))
    return result


def _detect_real_techniques(track, notes: list, role: TrackRole, supported: set[int],
                            beat: float) -> list[TechniqueCandidate]:
    track_id = int(track.track_id)
    inst_id = int(track.bdo_instrument_id)
    family = instrument_family(inst_id)
    candidates: list[TechniqueCandidate] = []
    controls = list(getattr(track, "performance_controls", []))
    candidates.extend(_detect_performance_techniques(track, notes, family, supported))
    if family == "keys" and any(int(item.get("control", -1)) == 64 and int(item.get("value", 0)) >= 64 for item in controls):
        if notes:
            candidates.append(_candidate(track_id, (0,), "piano_pedal", .98, "检测到原始 MIDI CC64 踏板事件", inst_id, notes, supported))
    for index, note in enumerate(notes):
        nxt = notes[index + 1] if index + 1 < len(notes) else None
        gap = (nxt.start - (note.start + note.dur)) if nxt else beat
        ioi = (nxt.start - note.start) if nxt else beat
        detached = nxt is not None and note.dur / max(1.0, ioi) <= .45 and gap >= beat * .06
        gate_ratio = note.dur / max(1.0, ioi)
        median_velocity = sorted(int(item.vel) for item in notes)[len(notes) // 2]
        if nxt and -.08 * beat <= gap <= .06 * beat and family in {"strings", "wind", "brass", "synth"}:
            candidates.append(_candidate(track_id, (index,), "legato", .86, "相邻音无可听断点且声部连续", inst_id, notes, supported))
        if nxt and .78 <= gate_ratio <= .98 and gap >= 0 and family in {"strings", "wind", "brass", "keys"}:
            candidates.append(_candidate(track_id, (index,), "tenuto", .8, "接近完整拍值并保持清晰换音", inst_id, notes, supported))
        if detached and gate_ratio <= .22 and family in {"strings", "wind", "brass", "keys"}:
            candidates.append(_candidate(track_id, (index,), "staccatissimo", .9, "门限短于相邻音间隔的 22%", inst_id, notes, supported))
        if int(note.vel) >= median_velocity + 18 and family != "synth":
            technique = "marcato" if detached else "accent"
            candidates.append(_candidate(track_id, (index,), technique,
                                         min(.96, .78 + (int(note.vel) - median_velocity) / 120),
                                         "局部力度峰值形成明确起音强调", inst_id, notes, supported))
        if detached and family in {"strings", "wind", "brass", "keys"}:
            technique = "spiccato" if family == "strings" and note.dur <= beat * .28 else "staccato"
            candidates.append(_candidate(track_id, (index,), technique, .82, "短时值且与下一音存在可听间隔", inst_id, notes, supported))
        if nxt and family in {"guitar", "bass", "strings", "wind", "brass"}:
            interval = nxt.pitch - note.pitch
            if -20 <= gap <= beat * .18 and 1 <= abs(interval) <= 4:
                technique = "hammer_on" if family in {"guitar", "bass"} and interval > 0 else (
                    "pull_off" if family in {"guitar", "bass"} else "slide"
                )
                candidates.append(_candidate(track_id, (index,), technique, .84, "小音程紧密连接形成方向性手势", inst_id, notes, supported))
        if family in {"guitar", "bass"} and detached and note.pitch < 64:
            candidates.append(_candidate(track_id, (index,), "palm_mute", .84, "低中音区分离节奏型", inst_id, notes, supported))
        if family == "bass" and note.dur <= beat * .36 and note.vel >= 104:
            candidates.append(_candidate(track_id, (index,), "slap_pop", .88, "贝斯高力度短音重击", inst_id, notes, supported))
        if family in {"bass", "drums", "hand_percussion"} and note.dur <= beat * .25 and note.vel <= 55:
            candidates.append(_candidate(track_id, (index,), "ghost_note", .85, "极短弱力度节奏填充", inst_id, notes, supported))
        if family in {"strings", "synth"} and note.dur >= beat * 1.7:
            pieces = min(4, max(2, round(note.dur / max(90.0, beat * .25))))
            edit = EditOperation("split_repeat", track_id, (index,), (("pieces", pieces),))
            candidates.append(_candidate(
                track_id, (index,), "tremolo", .78, "持续音可用同音重复形成震音纹理", inst_id,
                notes, supported, (edit,), role == TrackRole.PRIMARY_MELODY,
            ))
        if family in {"wind", "brass"} and nxt and gap >= beat * .55:
            candidates.append(_candidate(track_id, (index,), "breath_phrase", .9, "长间隔构成自然换气边界", inst_id, notes, supported))
        if family == "synth" and note.dur >= beat * 1.4:
            candidates.append(_candidate(track_id, (index,), "synth_filter_sustain", .76, "合成长音持续纹理", inst_id, notes, supported))
    if family == "harp":
        groups = _onset_groups(notes)
        for group in groups:
            if len(group) >= 3:
                candidates.append(_candidate(track_id, tuple(group), "harp_arpeggio", .82, "同拍和弦适合竖琴分解或琶音化", inst_id, notes, supported))
        for index in range(max(0, len(notes) - 3)):
            run = notes[index:index + 4]
            steps = [run[pos + 1].pitch - run[pos].pitch for pos in range(3)]
            if all(1 <= abs(step) <= 2 for step in steps) and len({step > 0 for step in steps}) == 1:
                candidates.append(_candidate(track_id, (index,), "harp_gliss", .78, "连续同向级进形成滑奏候选", inst_id, notes, supported))
    if family == "guitar":
        for index in range(max(0, len(notes) - 2)):
            group = notes[index:index + 3]
            if group[-1].start - group[0].start <= 85 and len({item.pitch for item in group}) == 3:
                steps = [group[pos + 1].pitch - group[pos].pitch for pos in range(2)]
                if all(step > 0 for step in steps) or all(step < 0 for step in steps):
                    technique = "strum_up" if steps[0] > 0 else "strum_down"
                    candidates.append(_candidate(track_id, tuple(range(index, index + 3)), technique, .9,
                                                 "和弦音在短窗口内按音高方向依次起音", inst_id, notes, supported))
    if family in {"wind", "brass"}:
        for index in range(max(0, len(notes) - 3)):
            run = notes[index:index + 4]
            intervals = [run[pos + 1].start - run[pos].start for pos in range(3)]
            if max(intervals, default=beat) <= beat * .28 and len({item.pitch for item in run}) <= 2:
                candidates.append(_candidate(track_id, tuple(range(index, index + 4)), "double_tongue", .86,
                                             "快速重复起音符合多吐音型", inst_id, notes, supported))
    if family in {"drums", "hand_percussion"}:
        for index in range(len(notes) - 1):
            if notes[index].pitch == notes[index + 1].pitch and 0 < notes[index + 1].start - notes[index].start <= 45:
                candidates.append(_candidate(track_id, (index, index + 1), "flam", .86, "同鼓件极短双击形成 Flam", inst_id, notes, supported))
        for index in range(max(0, len(notes) - 3)):
            run = notes[index:index + 4]
            if len({item.pitch for item in run}) == 1 and run[-1].start - run[0].start <= beat:
                candidates.append(_candidate(track_id, tuple(range(index, index + 4)), "roll", .9, "同鼓件一拍内快速重复", inst_id, notes, supported))
    return candidates


def _beam_select(candidates: list[TechniqueCandidate], width: int) -> list[TechniqueCandidate]:
    states: list[tuple[float, tuple[TechniqueCandidate, ...], frozenset[tuple]]] = [(0.0, (), frozenset())]
    for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
        expanded = list(states)
        for score, chosen, conflicts in states:
            if candidate.conflict_key in conflicts:
                continue
            expanded.append((score + candidate.confidence, chosen + (candidate,), conflicts | {candidate.conflict_key}))
        states = sorted(expanded, key=lambda item: item[0], reverse=True)[:max(1, width)]
    return list(states[0][1])


def _mark_verified_candidates(candidates: list[TechniqueCandidate], inst_id: int,
                              config: OptimizerConfig) -> list[TechniqueCandidate]:
    return [
        replace(candidate, realization=RealizationKind.NATIVE_BDO)
        if candidate.ntype is not None and (inst_id, candidate.ntype) in config.verified_articulations
        else candidate
        for candidate in candidates
    ]


def _apply_technique_edits(notes: list, selected: list[TechniqueCandidate], level: OptimizationLevel,
                           role: TrackRole, config: OptimizerConfig, report: TrackOptimizationReport,
                           manual_track_fx: int | None = None) -> list:
    if manual_track_fx is not None and config.respect_manual_track_fx:
        return notes
    native_replacements: dict[int, object] = {}
    replacements: dict[int, list] = {}
    for candidate in selected:
        if candidate.realization == RealizationKind.NATIVE_BDO and candidate.ntype is not None and candidate.confidence >= .85:
            onset = notes[candidate.note_indices[0]].start
            same_onset = tuple(index for index, note in enumerate(notes) if abs(note.start - onset) <= 12.0)
            if any(int(getattr(notes[index], "ntype", 0)) != 0 for index in same_onset):
                continue
            for index in same_onset:
                native_replacements[index] = notes[index]._replace(ntype=candidate.ntype)
                report.articulations_added += 1
                report.articulation_counts[candidate.ntype] = report.articulation_counts.get(candidate.ntype, 0) + 1
            continue
        if level == OptimizationLevel.SAFE:
            continue
        if candidate.realization != RealizationKind.MIDI_APPROXIMATION:
            continue
        if candidate.requires_confirmation and role == TrackRole.PRIMARY_MELODY:
            continue
        for edit in candidate.edits:
            if edit.operation != "split_repeat":
                continue
            index = edit.note_indices[0]
            note = notes[index]
            pieces = max(2, min(4, int(edit.value("pieces", 2))))
            unit = note.dur / pieces
            generated = []
            for piece in range(pieces):
                generated.append(note._replace(
                    start=note.start + piece * unit,
                    dur=max(20.0, unit * .86),
                    vel=max(1, min(127, note.vel + (4 if piece % 2 == 0 else -3))),
                ))
            replacements[index] = generated
            report.notes_added += pieces - 1
    if not replacements and not native_replacements:
        return notes
    result = []
    for index, note in enumerate(notes):
        if index in replacements:
            result.extend(replacements[index])
        else:
            result.append(native_replacements.get(index, note))
    return sorted(result, key=lambda item: (item.start, item.pitch))


def _ensemble_issues(track, tracks: list, role: TrackRole) -> list[str]:
    if not track.notes or role == TrackRole.PERCUSSION:
        return []
    issues = []
    low, high = min(note.pitch for note in track.notes), max(note.pitch for note in track.notes)
    avg = sum(note.pitch for note in track.notes) / len(track.notes)
    for other in tracks:
        if other is track or not other.notes or getattr(other, "is_percussion", False):
            continue
        other_low, other_high = min(note.pitch for note in other.notes), max(note.pitch for note in other.notes)
        overlap = max(0, min(high, other_high) - max(low, other_low) + 1)
        union = max(high, other_high) - min(low, other_low) + 1
        onset_keys = {(round(note.start / 12), note.pitch) for note in track.notes}
        other_keys = {(round(note.start / 12), note.pitch) for note in other.notes}
        doubling = len(onset_keys & other_keys) / max(1, min(len(onset_keys), len(other_keys)))
        if overlap / max(1, union) >= .7 and doubling < .2:
            issues.append(f"与 {other.display_name} 音区高度重叠，存在织体遮蔽风险")
        if doubling >= .45:
            issues.append(f"与 {other.display_name} 存在明显同度加倍，作为配器层保留")
    if role == TrackRole.BASS:
        melodies = [other for other in tracks if other.notes and sum(n.pitch for n in other.notes) / len(other.notes) < avg]
        if melodies:
            issues.append("低音平均音区高于其他旋律层，可能发生声部交叉")
    return list(dict.fromkeys(issues))


def _role_balance(notes: list, role: TrackRole, report: TrackOptimizationReport) -> list:
    if role not in {TrackRole.PRIMARY_MELODY, TrackRole.HARMONY, TrackRole.PAD}:
        return notes
    delta = 3 if role == TrackRole.PRIMARY_MELODY else -4
    result = []
    for note in notes:
        new_vel = _clamp(int(note.vel) + delta, 1, 127)
        result.append(note._replace(vel=new_vel))
        report.velocities_changed += new_vel != note.vel
    return result


def _already_humanized(notes: list, beat: float) -> bool:
    if len(notes) < 5 or beat <= 0:
        return False
    grid = beat / 4.0
    deviations = [float(note.start) - round(float(note.start) / grid) * grid for note in notes]
    expressive = [value for value in deviations if 2.5 <= abs(value) <= min(42.0, grid * .34)]
    buckets = {round(value / 2.0) for value in expressive}
    return len(expressive) / len(notes) >= .35 and len(buckets) >= 3


def _humanize_notes(track, notes: list, role: TrackRole, bpm: int, config: OptimizerConfig,
                    report: TrackOptimizationReport) -> tuple[list, bool]:
    """Apply stable, restrained timing/velocity variation without breaking chords."""
    if not config.humanize or not notes:
        return notes, False
    if bool(getattr(track, "effect_settings_placeholder", {}).get("game_safe_humanized")):
        report.warnings.append("已应用过轻微自然化，本次保持不变")
        return notes, False
    beat = _beat_ms(bpm)
    if _already_humanized(notes, beat):
        report.warnings.append("检测到已有人工微时差，跳过自动自然化")
        return notes, False
    groups = _onset_groups(notes)
    result = list(notes)
    source_span = max(int(note.vel) for note in notes) - min(int(note.vel) for note in notes)
    previous_start = -1.0
    changed = 0
    for group_pos, indices in enumerate(groups):
        anchor = float(notes[indices[0]].start)
        next_start = float(notes[groups[group_pos + 1][0]].start) if group_pos + 1 < len(groups) else None
        phase = anchor % beat if beat else 0.0
        strong = min(phase, abs(beat - phase)) <= 18.0
        phrase_end = next_start is None or next_start - max(
            float(notes[index].start + notes[index].dur) for index in indices
        ) >= config.phrase_break_ms
        anchored = strong or phrase_end or role == TrackRole.BASS or bool(getattr(track, "is_percussion", False))
        timing_limit = min(float(config.humanize_timing_ms), 3.0 if strong else 4.0 if anchored else 12.0)
        signature = (
            (int(track.track_id) + 1) * 1000003 + round(anchor * 10) * 9176
            + sum(int(notes[index].pitch) for index in indices) * 131 + len(indices) * 37
        ) & 0x7FFFFFFF
        timing_unit = ((((signature * 1103515245 + 12345) >> 16) & 0x7FFF) / 16383.5) - 1.0
        velocity_unit = (((((signature ^ 0x5BD1E995) * 1103515245 + 12345) >> 16) & 0x7FFF) / 16383.5) - 1.0
        offset = round(timing_unit * timing_limit, 3)
        proposed = max(0.0, anchor + offset)
        if previous_start >= 0:
            proposed = max(previous_start + 1.0, proposed)
        if next_start is not None:
            proposed = min(next_start - 1.0, proposed)
        if proposed < 0 or (next_start is not None and proposed >= next_start):
            proposed = anchor
        offset = proposed - anchor
        has_expression_curve = any(
            str(event.get("kind", "control_change")) == "control_change"
            and int(event.get("control", -1)) in {1, 11}
            for event in getattr(track, "performance_controls", [])
        )
        velocity_limit = 0 if source_span >= config.expressive_velocity_span or has_expression_curve else min(
            int(config.humanize_velocity), 2 if anchored else 6
        )
        velocity_delta = round(velocity_unit * velocity_limit)
        for index in indices:
            note = notes[index]
            new_start = max(0.0, float(note.start) + offset)
            new_velocity = _clamp(int(note.vel) + velocity_delta, config.min_velocity, config.max_velocity)
            result[index] = note._replace(start=new_start, vel=new_velocity)
            if abs(new_start - float(note.start)) >= .5 or new_velocity != int(note.vel):
                changed += 1
        previous_start = proposed
    report.humanized_notes += changed
    return sorted(result, key=lambda note: (note.start, note.pitch)), changed > 0


def _nearest(value: float, choices: tuple[int, ...]) -> int:
    return min(choices, key=lambda choice: (abs(choice - value), choice))


def _suggest_effects(tracks: list, context: SongContext, config: OptimizerConfig) -> EffectSuggestion:
    current_reverb = _clamp(int(config.current_reverb), 0, 127)
    current_delay = _clamp(int(config.current_delay), 0, 127)
    current_chorus = tuple(_clamp(int(value), 0, 127) for value in config.current_chorus) if config.current_chorus else None
    notes = [note for track in tracks for note in track.notes]
    if not notes or not config.optimize_effects:
        return EffectSuggestion(
            current_reverb, current_delay, current_chorus,
            current_reverb, current_delay, current_chorus, 1.0,
            ("声音效果优化已关闭" if notes else "工程没有可分析音符",),
            config.allow_global_effect_write,
        )
    end = max(float(note.start + note.dur) for note in notes)
    beats = max(1.0, end / max(1.0, context.beat_ms))
    density = len(notes) / beats
    long_ratio = sum(float(note.dur) >= context.beat_ms * 1.2 for note in notes) / len(notes)
    families = {instrument_family(int(track.bdo_instrument_id)) for track in tracks if track.notes}
    styles = {tag.name for tag in context.styles}
    rhythm_heavy = TrackRole.PERCUSSION in context.track_roles.values() and TrackRole.BASS in context.track_roles.values()
    reasons = []

    reverb_target = 16.0 + long_ratio * 22.0
    if "ambient" in styles:
        reverb_target += 16
        reasons.append("氛围和长音织体允许更宽的混响")
    elif "orchestral" in styles:
        reverb_target += 9
        reasons.append("管弦配置使用适度空间感")
    if density >= 3.2 or rhythm_heavy:
        reverb_target -= 9
        reasons.append("低音与节奏密度较高，抑制混响混浊")
    reverb = _nearest(max(0.0, min(64.0, reverb_target)), (0, 8, 16, 24, 32, 40, 48, 56, 64))

    delay_target = 0.0
    if density <= 1.5 and TrackRole.PRIMARY_MELODY in context.track_roles.values():
        delay_target += 14
        reasons.append("旋律较稀疏，可使用少量延迟")
    if styles & {"electronic", "ambient"}:
        delay_target += 10
    if density >= 2.6 or context.syncopation >= .32:
        delay_target -= 10
    delay = _nearest(max(0.0, min(40.0, delay_target)), (0, 8, 16, 24, 32, 40))

    color_families = len(families & {"strings", "synth", "guitar"})
    if color_families == 0 or families.issubset({"bass", "drums", "hand_percussion"}):
        chorus = None
        reasons.append("当前配器不需要全局合唱扩宽")
    elif density >= 3.4 or rhythm_heavy:
        chorus = (8, 16, 24)
        reasons.append("使用轻合唱，避免低频与鼓组失焦")
    elif "ambient" in styles or "electronic" in styles:
        chorus = (14, 32, 38)
        reasons.append("合成器或氛围织体适合中等合唱深度")
    else:
        chorus = (10, 22, 30)
    confidence = min(.94, .68 + min(.18, len(notes) / 500.0) + (.06 if context.styles else 0.0))
    return EffectSuggestion(
        current_reverb, current_delay, current_chorus, reverb, delay, chorus,
        confidence, tuple(dict.fromkeys(reasons))[:3], config.allow_global_effect_write,
    )


def _collect_ensemble_suggestions(tracks: list, context: SongContext,
                                  reports: list[TrackOptimizationReport]) -> list[EnsembleSuggestion]:
    suggestions: list[EnsembleSuggestion] = []
    seen = set()
    for report in reports:
        for issue in report.ensemble_issues:
            if issue not in seen:
                seen.add(issue)
                suggestions.append(EnsembleSuggestion(70, issue, (report.track_id,)))
    melody = next((track for track in tracks if context.track_roles.get(int(track.track_id)) == TrackRole.PRIMARY_MELODY), None)
    bass = next((track for track in tracks if context.track_roles.get(int(track.track_id)) == TrackRole.BASS), None)
    drums = next((track for track in tracks if context.track_roles.get(int(track.track_id)) == TrackRole.PERCUSSION), None)
    low_tracks = [track for track in tracks if sum(note.pitch < 48 for note in track.notes) >= max(2, len(track.notes) * .35)]
    if len(low_tracks) >= 3:
        suggestions.append(EnsembleSuggestion(
            95, "低音区同时活跃的乐器过多；建议让非低音角色减少低区音符或短时留白",
            tuple(int(track.track_id) for track in low_tracks),
        ))
    if melody and melody.notes:
        melody_starts = {round(float(note.start) / 24.0) for note in melody.notes}
        melody_low, melody_high = min(note.pitch for note in melody.notes), max(note.pitch for note in melody.notes)
        for track in tracks:
            if track is melody or not track.notes or context.track_roles.get(int(track.track_id)) in {TrackRole.BASS, TrackRole.PERCUSSION}:
                continue
            starts = {round(float(note.start) / 24.0) for note in track.notes}
            rhythm_overlap = len(starts & melody_starts) / max(1, min(len(starts), len(melody_starts)))
            register_overlap = sum(melody_low - 3 <= note.pitch <= melody_high + 3 for note in track.notes) / len(track.notes)
            if rhythm_overlap >= .55 and register_overlap >= .45:
                suggestions.append(EnsembleSuggestion(
                    90, f"{track.display_name} 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音",
                    (int(melody.track_id), int(track.track_id)),
                ))
    if bass and drums and bass.notes and drums.notes:
        kick_starts = [float(note.start) for note in drums.notes if note.pitch in {35, 36, 48}]
        if kick_starts:
            aligned = sum(any(abs(float(note.start) - start) <= 45.0 for start in kick_starts) for note in bass.notes)
            if aligned / len(bass.notes) < .3:
                suggestions.append(EnsembleSuggestion(
                    82, "鼓与贝斯的主要起音联系较弱；建议在段落重拍建立少量共同锚点",
                    (int(bass.track_id), int(drums.track_id)),
                ))
    return sorted(suggestions, key=lambda item: (-item.priority, item.track_ids, item.message))[:3]


def _create_arrangement_double(tracks: list, context: SongContext, config: OptimizerConfig,
                               target_ids: set[int]) -> tuple[list, list[str]]:
    if config.level != OptimizationLevel.ARRANGE or not config.allow_track_creation:
        return tracks, []
    melody = next((track for track in tracks if context.track_roles.get(int(track.track_id)) == TrackRole.PRIMARY_MELODY), None)
    if melody is None or int(melody.track_id) not in target_ids or not melody.notes:
        return tracks, []
    family = instrument_family(int(melody.bdo_instrument_id))
    preferred = {
        "strings": (0x0B, 0x27, 0x28), "guitar": (0x27, 0x0B, 0x12),
        "bass": (0x12, 0x28), "wind": (0x12, 0x10), "brass": (0x12, 0x0B),
        "keys": (0x0B, 0x12, 0x27), "synth": (0x12, 0x0B, 0x28),
    }.get(family, ())
    used = {int(track.bdo_instrument_id) for track in tracks}
    options: list[tuple[float, int, int]] = []
    for preference, candidate_inst in enumerate(preferred):
        if candidate_inst in used:
            continue
        supported = config.supported_pitches.get(candidate_inst)
        for shift in (12, 0, -12):
            if not all(0 <= note.pitch + shift <= 127 for note in melody.notes):
                continue
            if supported and not all(note.pitch + shift in supported for note in melody.notes):
                continue
            merged_count = sum(
                len(track.notes) for track in tracks
                if int(getattr(track, "bdo_instrument_id", -1)) == candidate_inst
            )
            if merged_count + len(melody.notes) > config.max_notes_per_instrument:
                continue
            contrast = 0.25 if instrument_family(candidate_inst) != family else 0.0
            register = 0.18 if shift else 0.05
            options.append((1.0 - preference * .08 + contrast + register, candidate_inst, shift))
    if not options:
        return tracks, []
    _score, target_inst, shift = max(options)
    new_notes = [note._replace(pitch=note.pitch + shift, vel=max(1, round(note.vel * .76)), ntype=0) for note in melody.notes]
    new_id = max((int(track.track_id) for track in tracks), default=-1) + 1
    new_track = melody.__class__(
        track_id=new_id, notes=new_notes, gm_program=melody.gm_program, is_percussion=False,
        display_name=f"{melody.display_name} · 自动八度加倍", bdo_instrument_id=target_inst,
        muted=False, solo=False, volume_scale=1.0, duration_scale=1.0, articulation_type=None,
        marnian_synth_mode="basic", color=melody.color,
        effect_settings_placeholder={"generated_by": "arrangement"},
        performance_controls=[], notes_optimized=True,
    )
    return tracks + [new_track], [f"新增 Track {new_id}，以乐器 0x{target_inst:02X} 对主旋律作{shift:+d}半音加倍"]


def _arrange_existing_voicing(tracks: list, context: SongContext, config: OptimizerConfig,
                              target_ids: set[int]) -> tuple[list, list[str]]:
    """Resolve severe register collisions without rewriting melodic anchors."""
    if config.level != OptimizationLevel.ARRANGE:
        return tracks, []
    melody = next((track for track in tracks if context.track_roles.get(int(track.track_id)) == TrackRole.PRIMARY_MELODY), None)
    if melody is None or not melody.notes:
        return tracks, []
    melody_low = min(note.pitch for note in melody.notes)
    melody_high = max(note.pitch for note in melody.notes)
    bass_tracks = [track for track in tracks if context.track_roles.get(int(track.track_id)) == TrackRole.BASS and track.notes]
    bass_high = max((max(note.pitch for note in track.notes) for track in bass_tracks), default=23)
    result, changes = [], []
    for track in tracks:
        track_id = int(track.track_id)
        role = context.track_roles.get(track_id, TrackRole.ORNAMENT)
        if track_id not in target_ids or role not in {TrackRole.HARMONY, TrackRole.PAD, TrackRole.SECONDARY_MELODY} or not track.notes:
            result.append(track)
            continue
        low, high = min(note.pitch for note in track.notes), max(note.pitch for note in track.notes)
        overlap = max(0, min(high, melody_high) - max(low, melody_low) + 1)
        union = max(high, melody_high) - min(low, melody_low) + 1
        if overlap / max(1, union) < .42:
            result.append(track)
            continue
        supported = config.supported_pitches.get(int(track.bdo_instrument_id))
        options = []
        for shift in (-12, 12):
            shifted = [note.pitch + shift for note in track.notes]
            if min(shifted) <= bass_high + 3 or not all(0 <= pitch <= 127 for pitch in shifted):
                continue
            if supported and not all(pitch in supported for pitch in shifted):
                continue
            shifted_overlap = max(0, min(max(shifted), melody_high) - max(min(shifted), melody_low) + 1)
            options.append((shifted_overlap, abs((sum(shifted) / len(shifted)) - (melody_low + melody_high) / 2), shift))
        if not options:
            result.append(track)
            continue
        _new_overlap, _distance, shift = min(options, key=lambda item: (item[0], -item[1]))
        shifted_notes = [note._replace(pitch=note.pitch + shift) for note in track.notes]
        result.append(_replace_track(track, shifted_notes, notes_optimized=True))
        changes.append(f"Track {track_id}（{role}）整体移调 {shift:+d} 半音，减少与主旋律的音区遮蔽")
    return result, changes


def _apply_lyric_expression(notes: list, lyric: LyricContext, level: OptimizationLevel,
                            report: TrackOptimizationReport) -> list:
    """Shape vocal phrasing while protecting melody pitches and note count."""
    if level == OptimizationLevel.SAFE or not lyric.alignments:
        return notes
    result = list(notes)
    if lyric.mode in {LyricExpressionMode.LEGATO, LyricExpressionMode.MELISMATIC}:
        changed = 0
        for alignment in lyric.alignments:
            for note_index in alignment.note_indices[:-1] or alignment.note_indices:
                if note_index + 1 >= len(result):
                    continue
                note, following = result[note_index], result[note_index + 1]
                target = max(note.dur, following.start - note.start - 4.0)
                target = min(target, max(note.dur, note.dur * 1.35))
                if target >= note.dur + 3.0:
                    result[note_index] = note._replace(dur=target)
                    changed += 1
        if changed:
            report.warnings.append(f"歌词连续表达：延长 {changed} 个主旋律音的衔接，未改变音高或音符数")
    elif lyric.mode == LyricExpressionMode.SPOKEN:
        changed = 0
        for alignment in lyric.alignments:
            if alignment.relation != "shared_note":
                continue
            note_index = alignment.note_indices[0]
            if note_index + 1 >= len(result):
                continue
            note, following = result[note_index], result[note_index + 1]
            target = min(note.dur, max(35.0, (following.start - note.start) * .68))
            if target <= note.dur - 3.0:
                result[note_index] = note._replace(dur=target)
                changed += 1
        if changed:
            report.warnings.append(f"歌词节奏念唱：收短 {changed} 个共享音，保留旋律音高")
    return result


def _lyric_masking_issue(track, all_tracks: list, role: TrackRole, lyric: LyricContext | None) -> str | None:
    if not lyric or role in {TrackRole.PRIMARY_MELODY, TrackRole.PERCUSSION, TrackRole.BASS} or not track.notes:
        return None
    primary = next((item for item in all_tracks if int(item.track_id) == lyric.primary_track_id), None)
    if primary is None or not primary.notes:
        return None
    melody_low, melody_high = min(n.pitch for n in primary.notes), max(n.pitch for n in primary.notes)
    overlap = sum(melody_low - 3 <= note.pitch <= melody_high + 3 for note in track.notes) / len(track.notes)
    lyric_times = [token.time for token in lyric.tokens if token.time is not None]
    if not lyric_times:
        return None
    competing = sum(any(abs(note.start - time) <= 45.0 for time in lyric_times) for note in track.notes) / len(track.notes)
    if overlap >= .45 and competing >= .35:
        return "歌词密集处与主旋律同音区、同起点竞争；建议错开节奏、降力度或短时留白"
    return None


def optimize_tracks(tracks: list, bpm: int, supported_articulations: dict[int, list[tuple[int, str]]],
                    config: OptimizerConfig | None = None, time_sig: int = 4) -> OptimizationResult:
    config = config or OptimizerConfig()
    config.level = OptimizationLevel(config.level)
    # An explicitly requested legacy expressive/arrange level remains an
    # internal compatibility opt-out.  The normal GUI only submits SAFE.
    if config.level != OptimizationLevel.SAFE:
        config.game_safe_only = False
    if config.game_safe_only:
        config.level = OptimizationLevel.SAFE
        config.allow_track_creation = False
    song_context = analyse_song(
        tracks, bpm, time_sig, config.phrase_break_ms, config.style_override, config.context_classifier,
        config.lyric_events,
    )
    primary = next((track for track in tracks if song_context.track_roles.get(int(track.track_id)) == TrackRole.PRIMARY_MELODY), None)
    lyric_context = align_lyrics(
        config.lyric_events,
        list(primary.notes) if primary else [],
        song_context.beat_ms,
        config.lyric_mode,
        int(primary.track_id) if primary else None,
    ) if config.lyric_events else None
    target_ids = (
        {int(track.track_id) for track in tracks}
        if config.target_track_ids is None else set(config.target_track_ids)
    )
    merged_counts: dict[int, int] = {}
    for item in tracks:
        instrument_id = int(item.bdo_instrument_id)
        merged_counts[instrument_id] = merged_counts.get(instrument_id, 0) + len(item.notes)
    optimized_tracks = []
    reports = []
    for track in tracks:
        track_id = int(track.track_id)
        role = song_context.track_roles.get(track_id, TrackRole.ORNAMENT)
        targeted = track_id in target_ids
        report = TrackOptimizationReport(
            track_id=track_id,
            display_name=track.display_name,
            before_notes=len(track.notes),
            after_notes=len(track.notes),
            role=str(role),
            scope="修改" if targeted else "只读上下文",
        )
        notes = sorted(track.notes, key=lambda note: (note.start, note.pitch, note.dur))
        original_pitch_multiset = sorted(int(note.pitch) for note in notes)
        original_note_count = len(notes)
        was_humanized = False
        supported = {ntype for ntype, _label in supported_articulations.get(track.bdo_instrument_id, [])}
        report.ensemble_issues = _ensemble_issues(track, tracks, role)
        masking = _lyric_masking_issue(track, tracks, role, lyric_context)
        if masking:
            report.ensemble_issues.append(masking)
        supported_pitch_set = config.supported_pitches.get(int(track.bdo_instrument_id))
        if supported_pitch_set:
            outside = sum(note.pitch not in supported_pitch_set for note in notes)
            if outside:
                report.warnings.append(f"{outside} 个音超出目标乐器的游戏/采样键位，未自动夹音")
        if merged_counts.get(int(track.bdo_instrument_id), 0) > config.max_notes_per_instrument:
            report.warnings.append("相同 BDO 乐器合并后超过 10000 音符，自动编曲不会继续加倍")
        if int(track.bdo_instrument_id) in {0x24, 0x25, 0x26}:
            invalid_fx = sum(
                int(getattr(note, "ntype", 0)) == 25 and not 36 <= note.pitch <= 43 for note in notes
            )
            if invalid_fx:
                report.warnings.append(f"{invalid_fx} 个电吉他 FX 音不在 C2-G2 触发区")
        for group in _onset_groups(notes):
            ntypes = {int(getattr(notes[index], "ntype", 0)) for index in group}
            if len(ntypes) > 1:
                report.warnings.append("检测到同拍多奏法；保留人工内容并要求导出前确认")
                break
        if not targeted:
            report.technique_candidates = _mark_verified_candidates(_detect_real_techniques(
                track, notes, role, supported, _beat_ms(bpm)
            ), int(track.bdo_instrument_id), config)
            optimized_tracks.append(track)
            reports.append(report)
            continue
        if config.optimize_blocks and not config.game_safe_only:
            notes = _dedupe_notes(notes, report)
            notes = _fix_timing(notes, track.is_percussion or track.bdo_instrument_id == 0x0d, bpm, config, report)
        if config.polish_velocity:
            source_span = max((int(note.vel) for note in notes), default=0) - min((int(note.vel) for note in notes), default=0)
            has_expression_curve = any(
                str(event.get("kind", "control_change")) == "control_change"
                and int(event.get("control", -1)) in {1, 11}
                for event in getattr(track, "performance_controls", [])
            )
            if config.game_safe_only and (source_span >= config.expressive_velocity_span or has_expression_curve):
                report.warnings.append("检测到已有力度/表情曲线，保持原力度")
            else:
                notes = _polish_velocity(notes, track.is_percussion or track.bdo_instrument_id == 0x0d, bpm, config, report)
                if not (track.is_percussion or track.bdo_instrument_id == 0x0d):
                    notes = _role_balance(notes, role, report)
        if config.game_safe_only:
            notes, was_humanized = _humanize_notes(track, notes, role, bpm, config, report)
        report.technique_candidates = _mark_verified_candidates(_detect_real_techniques(
            track, notes, role, supported, _beat_ms(bpm)
        ), int(track.bdo_instrument_id), config)
        if config.apply_articulations and not (track.is_percussion or track.bdo_instrument_id == 0x0d):
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
        selected = _beam_select(report.technique_candidates, config.beam_width)
        notes = _apply_technique_edits(
            notes, selected, config.level, role, config, report, track.articulation_type
        )
        if lyric_context and role == TrackRole.PRIMARY_MELODY:
            local_lyrics = align_lyrics(
                config.lyric_events, notes, song_context.beat_ms, config.lyric_mode, track_id
            )
            notes = _apply_lyric_expression(notes, local_lyrics, config.level, report)
        if config.game_safe_only and (
            len(notes) != original_note_count
            or sorted(int(note.pitch) for note in notes) != original_pitch_multiset
        ):
            report.warnings.append("游戏安全约束阻止了音符数量或音高变化，已回退本轨")
            notes = sorted(track.notes, key=lambda note: (note.start, note.pitch, note.dur))
            report.notes_added = 0
            report.duplicate_notes_removed = 0
            report.humanized_notes = 0
            was_humanized = False
        report.after_notes = len(notes)
        optimized_tracks.append(
            _replace_track(
                track,
                notes,
                notes_optimized=bool(getattr(track, "notes_optimized", False) or report.changed),
                state_updates={"game_safe_humanized": True} if was_humanized else None,
            )
        )
        reports.append(report)
    optimized_tracks, voicing_changes = _arrange_existing_voicing(optimized_tracks, song_context, config, target_ids)
    optimized_tracks, doubling_changes = _create_arrangement_double(optimized_tracks, song_context, config, target_ids)
    arrangement_changes = voicing_changes + doubling_changes
    if len(optimized_tracks) > len(reports):
        for track in optimized_tracks[len(reports):]:
            reports.append(TrackOptimizationReport(
                track_id=int(track.track_id), display_name=track.display_name,
                before_notes=0, after_notes=len(track.notes), role=str(TrackRole.SECONDARY_MELODY),
                notes_added=len(track.notes), scope="自动编曲新增",
            ))
    effect_suggestion = _suggest_effects(tracks, song_context, config)
    ensemble_suggestions = _collect_ensemble_suggestions(tracks, song_context, reports)
    return OptimizationResult(
        tracks=optimized_tracks,
        reports=reports,
        song_context=song_context,
        arrangement_changes=arrangement_changes,
        lyric_context=lyric_context,
        effect_suggestion=effect_suggestion,
        ensemble_suggestions=ensemble_suggestions,
    )
