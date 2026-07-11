"""Deterministic lyric-to-melody alignment and expression planning.

MIDI lyric events normally carry syllables rather than phonemes.  This module
therefore preserves explicit event boundaries and avoids inventing linguistic
syllabification.  Alignment is monotonic and supports one syllable spanning
several notes (melisma) as well as several syllables sharing a rhythmic note.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re


class LyricExpressionMode(StrEnum):
    AUTO = "auto"
    SYLLABIC = "syllabic"
    LEGATO = "legato"
    MELISMATIC = "melismatic"
    SPOKEN = "spoken"
    CALL_RESPONSE = "call_response"


@dataclass(frozen=True)
class LyricToken:
    text: str
    time: float | None
    source_index: int
    line_end: bool = False
    paragraph_end: bool = False
    word_end: bool = False


@dataclass(frozen=True)
class LyricAlignment:
    token_index: int
    note_indices: tuple[int, ...]
    confidence: float
    relation: str


@dataclass(frozen=True)
class LyricContext:
    mode: LyricExpressionMode
    primary_track_id: int | None
    tokens: tuple[LyricToken, ...]
    alignments: tuple[LyricAlignment, ...]
    confidence: float
    warnings: tuple[str, ...]


_PUNCTUATION = set("，。！？；：、,.!?;:")


def lyric_tokens(events: list[dict]) -> tuple[LyricToken, ...]:
    """Normalize preserved MIDI lyric/text events without guessing syllables."""
    result: list[LyricToken] = []
    for source_index, event in enumerate(events):
        if str(event.get("kind", "lyrics")) not in {"lyrics", "text"}:
            continue
        raw = str(event.get("text", ""))
        if not raw:
            continue
        line_end = "\r" in raw or "\n" in raw
        paragraph_end = "\n" in raw
        chunks = [part for part in re.split(r"([，。！？；：、,.!?;:])", raw.replace("\r", "").replace("\n", "")) if part]
        if not chunks:
            continue
        try:
            event_time = float(event["time"])
        except (KeyError, TypeError, ValueError):
            event_time = None
        for chunk_index, chunk in enumerate(chunks):
            if chunk in _PUNCTUATION:
                if result:
                    previous = result[-1]
                    result[-1] = LyricToken(
                        previous.text + chunk, previous.time, previous.source_index,
                        True, previous.paragraph_end or paragraph_end, True,
                    )
                continue
            stripped = chunk.strip()
            if not stripped:
                continue
            # One MIDI event is one authoritative syllable.  A text event that
            # contains a full phrase is split only at whitespace/Han characters.
            pieces = [stripped]
            if str(event.get("kind", "lyrics")) == "text" and (" " in stripped or len(stripped) > 8):
                pieces = re.findall(r"[\u3400-\u9fff]|[^\s\u3400-\u9fff]+", stripped)
            for piece_index, piece in enumerate(pieces):
                result.append(LyricToken(
                    piece, event_time, source_index,
                    line_end and chunk_index == len(chunks) - 1 and piece_index == len(pieces) - 1,
                    paragraph_end and chunk_index == len(chunks) - 1 and piece_index == len(pieces) - 1,
                    raw.endswith(" ") or piece_index < len(pieces) - 1 or piece[-1:] in _PUNCTUATION,
                ))
    return tuple(result)


def lyric_onset_match(notes: list, events: list[dict], beat_ms: float) -> float:
    """Return how well timestamped lyric syllables match a candidate melody."""
    starts = sorted({float(note.start) for note in notes})
    times = [token.time for token in lyric_tokens(events) if token.time is not None]
    if not starts or not times:
        return 0.0
    tolerance = max(45.0, beat_ms * .22)
    distances = [min(abs(start - time) for start in starts) for time in times]
    coverage = sum(distance <= tolerance for distance in distances) / len(distances)
    accuracy = sum(math.exp(-distance / tolerance) for distance in distances) / len(distances)
    return .65 * coverage + .35 * accuracy


def _effective_mode(mode: LyricExpressionMode, tokens: tuple[LyricToken, ...], notes: list) -> LyricExpressionMode:
    if mode != LyricExpressionMode.AUTO:
        return mode
    if not tokens or not notes:
        return LyricExpressionMode.SYLLABIC
    ratio = len(notes) / max(1, len(tokens))
    if ratio >= 1.45:
        return LyricExpressionMode.MELISMATIC
    if ratio <= .72:
        return LyricExpressionMode.SPOKEN
    return LyricExpressionMode.LEGATO


def align_lyrics(events: list[dict], notes: list, beat_ms: float,
                  mode: LyricExpressionMode | str = LyricExpressionMode.AUTO,
                  primary_track_id: int | None = None) -> LyricContext:
    """Monotonically align lyric tokens to melody notes using timed anchors.

    Existing timestamps dominate.  Untimed tokens are distributed in order;
    no lyric text or melody pitch is rewritten.
    """
    requested = LyricExpressionMode(mode)
    tokens = lyric_tokens(events)
    notes = sorted(notes, key=lambda note: (note.start, -note.pitch))
    effective = _effective_mode(requested, tokens, notes)
    warnings: list[str] = []
    if not tokens:
        return LyricContext(effective, primary_track_id, (), (), 0.0, ("MIDI 中没有可用的 Lyric/Text 事件",))
    if not notes:
        return LyricContext(effective, primary_track_id, tokens, (), 0.0, ("未找到可承载歌词的主旋律音符",))

    cursor = 0
    anchors: list[int] = []
    for token_index, token in enumerate(tokens):
        if token.time is not None:
            candidates = range(cursor, len(notes))
            index = min(candidates, key=lambda item: abs(float(notes[item].start) - token.time), default=len(notes) - 1)
        else:
            index = round(token_index * max(0, len(notes) - 1) / max(1, len(tokens) - 1))
            index = max(cursor, index)
        index = min(len(notes) - 1, index)
        anchors.append(index)
        cursor = index if effective == LyricExpressionMode.SPOKEN else min(len(notes) - 1, index + 1)

    alignments: list[LyricAlignment] = []
    tolerance = max(55.0, beat_ms * .25)
    for index, (token, anchor) in enumerate(zip(tokens, anchors)):
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else len(notes)
        note_indices = (anchor,)
        relation = "syllabic"
        if effective in {LyricExpressionMode.MELISMATIC, LyricExpressionMode.LEGATO} and next_anchor > anchor + 1:
            limit = 4 if effective == LyricExpressionMode.MELISMATIC else 2
            note_indices = tuple(range(anchor, min(next_anchor, anchor + limit)))
            relation = "melisma" if len(note_indices) > 1 else "syllabic"
        elif effective == LyricExpressionMode.SPOKEN and index and anchor == anchors[index - 1]:
            relation = "shared_note"
        distance = abs(float(notes[anchor].start) - token.time) if token.time is not None else tolerance * .55
        confidence = max(.15, min(1.0, math.exp(-distance / tolerance)))
        alignments.append(LyricAlignment(index, note_indices, confidence, relation))
    confidence = sum(item.confidence for item in alignments) / len(alignments)
    if confidence < .58:
        warnings.append("歌词与主旋律起点偏差较大；仅作为建议，不自动改写音高")
    if effective == LyricExpressionMode.CALL_RESPONSE:
        warnings.append("问答表达需要第二旋律轨；当前版本只规划分句，不自动迁移主旋律")
    return LyricContext(effective, primary_track_id, tokens, tuple(alignments), confidence, tuple(warnings))

