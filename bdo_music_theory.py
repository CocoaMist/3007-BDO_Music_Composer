"""Conservative, explainable music-theory features for MIDI articulation.

The analyser intentionally does not rewrite pitches or harmony.  It returns
confidence-tagged context that callers may use to *reduce* unsafe articulation
choices, or to explain a suggestion in the preview.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from types import SimpleNamespace
from typing import Protocol

from bdo_lyrics import lyric_onset_match


_MAJOR = {0, 2, 4, 5, 7, 9, 11}
_MINOR = {0, 2, 3, 5, 7, 8, 10}


@dataclass(frozen=True)
class HarmonyWindow:
    start: float
    pitch_classes: frozenset[int]
    root: int | None = None
    quality: str | None = None


@dataclass(frozen=True)
class TheoryContext:
    bpm: int
    time_sig: int
    beat_ms: float
    key_root: int | None
    key_mode: str | None
    tonal_confidence: float
    phrase_numbers: tuple[int, ...]
    beat_strengths: tuple[float, ...]
    roles: tuple[str, ...]
    harmony: tuple[HarmonyWindow, ...]

    @property
    def tonal(self) -> bool:
        return self.tonal_confidence >= 0.72 and self.key_root is not None


class TrackRole(StrEnum):
    PRIMARY_MELODY = "primary_melody"
    SECONDARY_MELODY = "secondary_melody"
    HARMONY = "harmony"
    BASS = "bass"
    RHYTHM = "rhythm"
    PERCUSSION = "percussion"
    PAD = "pad"
    ORNAMENT = "ornament"
    FX = "fx"


@dataclass(frozen=True)
class StyleTag:
    name: str
    confidence: float
    source: str = "rules"


@dataclass(frozen=True)
class SongContext:
    """Cross-track musical evidence shared by scoped optimizers."""

    bpm: int
    time_sig: int
    beat_ms: float
    key_root: int | None
    key_mode: str | None
    tonal_confidence: float
    harmony: tuple[HarmonyWindow, ...]
    phrase_boundaries: tuple[float, ...]
    track_roles: dict[int, TrackRole]
    segment_roles: dict[int, tuple[TrackRole, ...]]
    track_contexts: dict[int, TheoryContext]
    styles: tuple[StyleTag, ...]
    syncopation: float
    swing_ratio: float

    @property
    def tonal(self) -> bool:
        return self.tonal_confidence >= 0.72 and self.key_root is not None


class ContextClassifier(Protocol):
    """Optional model boundary; it may provide priors, never edit notes."""

    def classify(self, tracks: list, context: SongContext) -> dict: ...


def _beat_strength(start: float, beat_ms: float, time_sig: int) -> float:
    if beat_ms <= 0:
        return 0.5
    beat = int(round(start / beat_ms)) % max(1, time_sig)
    if beat == 0:
        return 1.0
    if time_sig >= 4 and beat == 2:
        return 0.72
    return 0.42


def _infer_key(notes: list) -> tuple[int | None, str | None, float]:
    if len(notes) < 5:
        return None, None, 0.0
    weights = Counter()
    for note in notes:
        weights[note.pitch % 12] += max(1.0, min(float(note.dur), 1600.0) / 120.0)
    total = sum(weights.values())
    if not total:
        return None, None, 0.0
    scored: list[tuple[float, int, str]] = []
    for root in range(12):
        for mode, scale in (("major", _MAJOR), ("minor", _MINOR)):
            in_scale = sum(value for pc, value in weights.items() if (pc - root) % 12 in scale)
            tonic_bonus = weights[root] * 0.18
            scored.append(((in_scale / total) + tonic_bonus / total, root, mode))
    best, root, mode = max(scored)
    # Require most of the weighted material to agree with one diatonic scale.
    confidence = min(1.0, max(0.0, (best - 0.60) / 0.38))
    return (root, mode, confidence) if confidence >= 0.72 else (None, None, confidence)


def _phrase_numbers(notes: list, phrase_break_ms: float) -> tuple[int, ...]:
    phrase, result, previous_end = 0, [], None
    for note in notes:
        if previous_end is not None and note.start - previous_end >= phrase_break_ms:
            phrase += 1
        result.append(phrase)
        previous_end = max(previous_end or 0.0, note.start + note.dur)
    return tuple(result)


def _roles(notes: list, beat_ms: float) -> tuple[str, ...]:
    """Classify event role conservatively; chord events are accompaniment."""
    result = []
    for index, note in enumerate(notes):
        same_onset = sum(abs(other.start - note.start) <= 12.0 for other in notes)
        if same_onset >= 2:
            result.append("chord")
            continue
        nearby = notes[max(0, index - 2):index + 3]
        repeated = sum(item.pitch == note.pitch for item in nearby) >= 2
        ioi = (notes[index + 1].start - note.start) if index + 1 < len(notes) else beat_ms
        if note.pitch < 48 and repeated and ioi <= beat_ms * 1.2:
            result.append("bass_riff")
        elif note.dur <= beat_ms * 0.35 and repeated:
            result.append("rhythm")
        else:
            result.append("melody")
    return tuple(result)


def _harmony_windows(notes: list) -> tuple[HarmonyWindow, ...]:
    """Analyse vertical harmony including notes sustained from earlier attacks."""
    windows = []
    starts = []
    for note in sorted(notes, key=lambda item: (item.start, item.pitch)):
        if not starts or abs(float(note.start) - starts[-1]) > 12.0:
            starts.append(float(note.start))
    for start in starts:
        group = [note for note in notes if float(note.start) <= start + 12.0 < float(note.start + note.dur)]
        pcs = frozenset(note.pitch % 12 for note in group)
        root, quality = None, None
        if len(pcs) >= 3:
            bass_pc = min(group, key=lambda note: note.pitch).pitch % 12
            for candidate in (bass_pc, *(pc for pc in sorted(pcs) if pc != bass_pc)):
                patterns = (
                    ("major7", {0, 4, 7, 11}), ("dominant7", {0, 4, 7, 10}),
                    ("minor7", {0, 3, 7, 10}), ("half_diminished7", {0, 3, 6, 10}),
                    ("major", {0, 4, 7}), ("minor", {0, 3, 7}),
                    ("diminished", {0, 3, 6}), ("sus4", {0, 5, 7}),
                )
                match = next((name for name, intervals in patterns if {
                    (candidate + interval) % 12 for interval in intervals
                }.issubset(pcs)), None)
                if match:
                    root, quality = candidate, match
                    break
        windows.append(HarmonyWindow(start, pcs, root, quality))
    return tuple(windows)


def analyse_music(notes: list, bpm: int, time_sig: int, phrase_break_ms: float) -> TheoryContext:
    beat_ms = 60000.0 / max(1, min(240, int(bpm or 120)))
    time_sig = max(1, min(32, int(time_sig or 4)))
    root, mode, confidence = _infer_key(notes)
    return TheoryContext(
        bpm=int(bpm), time_sig=time_sig, beat_ms=beat_ms,
        key_root=root, key_mode=mode, tonal_confidence=confidence,
        phrase_numbers=_phrase_numbers(notes, phrase_break_ms),
        beat_strengths=tuple(_beat_strength(note.start, beat_ms, time_sig) for note in notes),
        roles=_roles(notes, beat_ms), harmony=_harmony_windows(notes),
    )


def is_non_chord_tone(note, context: TheoryContext) -> bool:
    """Return true only for a tonal note outside a simultaneous chord window."""
    if not context.tonal:
        return False
    window = next((item for item in context.harmony if abs(item.start - note.start) <= 12.0), None)
    return bool(window and window.root is not None and note.pitch % 12 not in window.pitch_classes)


def _track_features(track, beat_ms: float) -> dict[str, float]:
    notes = sorted(track.notes, key=lambda item: (item.start, item.pitch))
    if not notes:
        return {"pitch": 60.0, "density": 0.0, "polyphony": 0.0, "duration": 0.0,
                "short": 0.0, "variety": 0.0, "span": 0.0}
    groups: list[list] = []
    for note in notes:
        if groups and abs(note.start - groups[-1][0].start) <= 12.0:
            groups[-1].append(note)
        else:
            groups.append([note])
    end = max(note.start + note.dur for note in notes)
    return {
        "pitch": sum(note.pitch for note in notes) / len(notes),
        "density": len(notes) / max(1.0, end / max(1.0, beat_ms)),
        "polyphony": sum(len(group) > 1 for group in groups) / max(1, len(groups)),
        "duration": sum(note.dur for note in notes) / len(notes),
        "short": sum(note.dur <= beat_ms * .35 for note in notes) / len(notes),
        "variety": len({note.pitch for note in notes}) / len(notes),
        "span": float(max(note.pitch for note in notes) - min(note.pitch for note in notes)),
    }


def _assign_track_roles(tracks: list, beat_ms: float, lyric_events: list[dict] | None = None) -> dict[int, TrackRole]:
    roles: dict[int, TrackRole] = {}
    melodic = []
    for track in tracks:
        track_id = int(track.track_id)
        if not track.notes:
            roles[track_id] = TrackRole.ORNAMENT
            continue
        features = _track_features(track, beat_ms)
        instrument_id = int(getattr(track, "bdo_instrument_id", -1))
        if bool(getattr(track, "is_percussion", False)) or instrument_id in {0x04, 0x05, 0x0D, 0x13}:
            roles[track_id] = TrackRole.PERCUSSION
        elif instrument_id in {0x24, 0x25, 0x26} and track.notes and all(
            36 <= note.pitch <= 43 and int(getattr(note, "ntype", 0)) == 25 for note in track.notes
        ):
            roles[track_id] = TrackRole.FX
        elif features["pitch"] < 49 and features["polyphony"] < .18:
            roles[track_id] = TrackRole.BASS
        elif features["polyphony"] >= .32:
            roles[track_id] = TrackRole.HARMONY
        elif features["duration"] >= beat_ms * 1.35 and features["density"] <= 1.1:
            roles[track_id] = TrackRole.PAD
        elif features["short"] >= .68 and features["variety"] <= .45:
            roles[track_id] = TrackRole.RHYTHM
        else:
            lyric_match = lyric_onset_match(track.notes, lyric_events or [], beat_ms)
            score = (
                features["pitch"] * .015 + features["variety"] + min(features["span"], 24) * .015
                + lyric_match * 2.4 - features["polyphony"] * .8
            )
            melodic.append((score, track_id))
    melodic.sort(reverse=True)
    if melodic:
        roles[melodic[0][1]] = TrackRole.PRIMARY_MELODY
        for _score, track_id in melodic[1:2]:
            roles[track_id] = TrackRole.SECONDARY_MELODY
        for _score, track_id in melodic[2:]:
            roles[track_id] = TrackRole.ORNAMENT
    return roles


def _rhythmic_features(notes: list, beat_ms: float) -> tuple[float, float]:
    if len(notes) < 4 or beat_ms <= 0:
        return 0.0, 1.0
    starts = sorted({round(float(note.start), 3) for note in notes})
    offbeats = 0
    swing_pairs = []
    for start in starts:
        phase = (start % beat_ms) / beat_ms
        nearest = min(abs(phase - point) for point in (0.0, .25, .5, .75, 1.0))
        offbeats += nearest > .07
    for left, middle, right in zip(starts, starts[1:], starts[2:]):
        a, b = middle - left, right - middle
        if 0 < a + b <= beat_ms * 1.15 and min(a, b) > 0:
            ratio = max(a, b) / min(a, b)
            if 1.25 <= ratio <= 3.2:
                swing_pairs.append(ratio)
    return offbeats / max(1, len(starts)), (sum(swing_pairs) / len(swing_pairs) if swing_pairs else 1.0)


def _style_tags(tracks: list, roles: dict[int, TrackRole], syncopation: float,
                swing_ratio: float, override: tuple[str, ...]) -> tuple[StyleTag, ...]:
    if override:
        return tuple(StyleTag(name, 1.0, "manual") for name in override)
    instrument_ids = {int(getattr(track, "bdo_instrument_id", -1)) for track in tracks}
    scores = Counter()
    if instrument_ids & {0x08, 0x0B, 0x0F, 0x10, 0x12, 0x27, 0x28}:
        scores["orchestral"] += .48
    if instrument_ids & {0x24, 0x25, 0x26}:
        scores["rock"] += .62
    if instrument_ids & {0x14, 0x18, 0x1C, 0x20}:
        scores["electronic"] += .65
    if TrackRole.PERCUSSION in roles.values() and TrackRole.BASS in roles.values():
        scores["rhythm_section"] += .45
    if swing_ratio >= 1.45:
        scores["jazz_swing"] += min(.82, .4 + (swing_ratio - 1.0) * .25)
    if syncopation >= .28 and TrackRole.BASS in roles.values():
        scores["funk"] += min(.78, .35 + syncopation)
    avg_duration = [float(note.dur) for track in tracks for note in track.notes]
    if avg_duration and sum(avg_duration) / len(avg_duration) >= 700:
        scores["ambient"] += .48
    if not scores:
        scores["neutral"] = .5
    return tuple(StyleTag(name, min(1.0, score)) for name, score in scores.most_common(3))


def analyse_song(tracks: list, bpm: int, time_sig: int, phrase_break_ms: float = 420.0,
                 style_override: tuple[str, ...] = (), classifier: ContextClassifier | None = None,
                 lyric_events: list[dict] | None = None) -> SongContext:
    """Build deterministic cross-track context, optionally enriched by model priors."""
    beat_ms = 60000.0 / max(1, min(240, int(bpm or 120)))
    all_notes = sorted(
        [note for track in tracks if not getattr(track, "is_percussion", False) for note in track.notes],
        key=lambda note: (note.start, note.pitch),
    )
    global_theory = analyse_music(all_notes, bpm, time_sig, phrase_break_ms)
    contexts = {
        int(track.track_id): analyse_music(sorted(track.notes, key=lambda n: (n.start, n.pitch)), bpm, time_sig, phrase_break_ms)
        for track in tracks
    }
    roles = _assign_track_roles(tracks, beat_ms, lyric_events)
    rhythmic_notes = [note for track in tracks for note in track.notes]
    syncopation, swing_ratio = _rhythmic_features(rhythmic_notes, beat_ms)
    boundaries = []
    previous_end = None
    for note in all_notes:
        if previous_end is not None and note.start - previous_end >= phrase_break_ms:
            boundaries.append(float(note.start))
        previous_end = max(previous_end or 0.0, note.start + note.dur)
    song_end = max((note.start + note.dur for track in tracks for note in track.notes), default=0.0)
    edges = (0.0, *boundaries, song_end + 1.0)
    segment_roles: dict[int, list[TrackRole]] = {int(track.track_id): [] for track in tracks}
    for start, end in zip(edges, edges[1:]):
        proxies = [SimpleNamespace(
            track_id=int(track.track_id),
            notes=[note for note in track.notes if start <= note.start < end],
            is_percussion=bool(getattr(track, "is_percussion", False)),
            bdo_instrument_id=int(getattr(track, "bdo_instrument_id", -1)),
        ) for track in tracks]
        local_lyrics = [event for event in lyric_events or [] if start <= float(event.get("time", 0.0)) < end]
        local_roles = _assign_track_roles(proxies, beat_ms, local_lyrics)
        for track in tracks:
            track_id = int(track.track_id)
            segment_roles[track_id].append(local_roles.get(track_id, roles.get(track_id, TrackRole.ORNAMENT)))
    context = SongContext(
        int(bpm), int(time_sig), beat_ms, global_theory.key_root, global_theory.key_mode,
        global_theory.tonal_confidence, global_theory.harmony, tuple(boundaries), roles,
        {track_id: tuple(items) for track_id, items in segment_roles.items()}, contexts,
        _style_tags(tracks, roles, syncopation, swing_ratio, style_override), syncopation, swing_ratio,
    )
    if classifier is None:
        return context
    try:
        priors = classifier.classify(tracks, context) or {}
        role_priors = priors.get("roles", {})
        style_priors = priors.get("styles", {})
        merged_roles = dict(context.track_roles)
        for track_id, item in role_priors.items():
            label, confidence = item if isinstance(item, (tuple, list)) else (item, 0.0)
            if float(confidence) >= .78:
                try:
                    merged_roles[int(track_id)] = TrackRole(str(label))
                except ValueError:
                    pass
        merged_styles = list(context.styles)
        merged_styles.extend(
            StyleTag(str(name), float(confidence), "model")
            for name, confidence in style_priors.items() if float(confidence) >= .72
        )
        return SongContext(
            context.bpm, context.time_sig, context.beat_ms, context.key_root, context.key_mode,
            context.tonal_confidence, context.harmony, context.phrase_boundaries, merged_roles,
            context.segment_roles, context.track_contexts,
            tuple(sorted(merged_styles, key=lambda tag: tag.confidence, reverse=True)[:3]),
            context.syncopation, context.swing_ratio,
        )
    except Exception:
        return context
