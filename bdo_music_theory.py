"""Conservative, explainable music-theory features for MIDI articulation.

The analyser intentionally does not rewrite pitches or harmony.  It returns
confidence-tagged context that callers may use to *reduce* unsafe articulation
choices, or to explain a suggestion in the preview.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


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
    windows = []
    groups: list[list] = []
    for note in notes:
        if groups and abs(note.start - groups[-1][0].start) <= 12.0:
            groups[-1].append(note)
        else:
            groups.append([note])
    for group in groups:
        pcs = frozenset(note.pitch % 12 for note in group)
        root, quality = None, None
        if len(pcs) >= 3:
            for candidate in pcs:
                if {candidate, (candidate + 4) % 12, (candidate + 7) % 12}.issubset(pcs):
                    root, quality = candidate, "major"
                    break
                if {candidate, (candidate + 3) % 12, (candidate + 7) % 12}.issubset(pcs):
                    root, quality = candidate, "minor"
                    break
        windows.append(HarmonyWindow(group[0].start, pcs, root, quality))
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
