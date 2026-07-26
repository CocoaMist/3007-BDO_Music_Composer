"""Build deterministic, read-only voice guides for transcription review.

The guide projection consumes decoded note candidates and the existing
semantic voice/harmony sidecars.  It never reads audio, mutates candidates or
creates formal editor notes.  Three levels of detail share one projection:

* overview: decimated phrase contours and chord spans;
* phrase: note plateaus and connectors for the primary voices;
* detail: the same skeleton plus lower-confidence/secondary branches.

All coordinates remain in audio-relative milliseconds.  The Qt canvas applies
the reference-audio offset only when painting or hit-testing.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from statistics import median
from typing import Iterable, Sequence


MELODY_LINE_VERSION = "transcription-voice-guides-v2"

PRIMARY_ROLE = "primary_melody"
BASS_ROLE = "bass"
HARMONY_ROLE = "harmony"
GUIDE_ROLES = frozenset({PRIMARY_ROLE, BASS_ROLE, HARMONY_ROLE})

NOTE_KIND = "note"
CONNECTOR_KIND = "connector"
CONTOUR_KIND = "contour"
CHORD_SPAN_KIND = "chord_span"
GUIDE_KINDS = frozenset(
    {NOTE_KIND, CONNECTOR_KIND, CONTOUR_KIND, CHORD_SPAN_KIND}
)

OVERVIEW_LOD = 0
PHRASE_LOD = 1
DETAIL_LOD = 2
CONFIDENCE_BUCKETS = 7

_PRIMARY_ROLES = frozenset(
    {"primary_melody", "secondary_melody", "melody", "primary", "secondary"}
)
_BASS_ROLES = frozenset({"bass", "low", "low_end"})
_HARMONY_ROLES = frozenset(
    {"harmony", "accompaniment", "chord", "pad", "rhythm"}
)
_PATH_BEAM_SIZE = 10
_MAX_HIT_SOURCE_IDS = 12


def _finite(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _clamp01(value: object) -> float:
    return max(0.0, min(1.0, _finite(value)))


def melody_line_confidence_bucket(value: object) -> int:
    """Quantize confidence so Qt can reuse a bounded set of pens."""

    return max(
        0,
        min(
            CONFIDENCE_BUCKETS,
            round(_clamp01(value) * CONFIDENCE_BUCKETS),
        ),
    )


def melody_line_width(value: object) -> float:
    """Encode confidence as an intentionally obvious thin-to-bold stroke."""

    return 0.65 + melody_line_confidence_bucket(value) * 0.55


def melody_line_lod(pixels_per_beat: object) -> int:
    """Return the semantic guide LOD for the current horizontal zoom."""

    value = max(0.0, _finite(pixels_per_beat))
    if value < 52.0:
        return OVERVIEW_LOD
    if value < 144.0:
        return PHRASE_LOD
    return DETAIL_LOD


def melody_line_kind_visible(
    kind: object,
    *,
    branch: bool,
    lod: int,
) -> bool:
    """Pure visibility policy shared by paint and hit-test paths."""

    normalized = str(kind or NOTE_KIND)
    if normalized not in GUIDE_KINDS:
        return False
    if lod <= OVERVIEW_LOD:
        return not branch and normalized in {CONTOUR_KIND, CHORD_SPAN_KIND}
    if normalized == CONTOUR_KIND:
        return False
    if branch and lod < DETAIL_LOD:
        return False
    return normalized in {NOTE_KIND, CONNECTOR_KIND, CHORD_SPAN_KIND}


def _role_family(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in _PRIMARY_ROLES:
        return PRIMARY_ROLE
    if normalized in _BASS_ROLES:
        return BASS_ROLE
    if normalized in _HARMONY_ROLES:
        return HARMONY_ROLE
    return ""


def _source_ids(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate_id = str(value or "")
        if not candidate_id or candidate_id in seen:
            continue
        result.append(candidate_id)
        seen.add(candidate_id)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class MelodyLineSegment:
    """One guide stroke in audio-time/piano-pitch coordinates."""

    role: str
    group_id: str
    start_audio_ms: float
    end_audio_ms: float
    start_pitch: float
    end_pitch: float
    confidence: float
    branch: bool = False
    kind: str = NOTE_KIND
    source_candidate_ids: tuple[str, ...] = ()
    label: str = ""

    def __post_init__(self) -> None:
        if self.role not in GUIDE_ROLES:
            raise ValueError("unsupported melody-line role")
        values = (
            self.start_audio_ms,
            self.end_audio_ms,
            self.start_pitch,
            self.end_pitch,
            self.confidence,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("melody-line values must be finite")
        if self.start_audio_ms < 0.0 or self.end_audio_ms < self.start_audio_ms:
            raise ValueError("invalid melody-line time range")
        if not 0.0 <= self.start_pitch <= 127.0:
            raise ValueError("invalid melody-line start pitch")
        if not 0.0 <= self.end_pitch <= 127.0:
            raise ValueError("invalid melody-line end pitch")
        kind = str(self.kind or NOTE_KIND)
        if kind not in GUIDE_KINDS:
            raise ValueError("unsupported melody-line kind")
        object.__setattr__(self, "group_id", str(self.group_id or "guide"))
        object.__setattr__(self, "confidence", _clamp01(self.confidence))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "source_candidate_ids",
            _source_ids(self.source_candidate_ids),
        )
        object.__setattr__(self, "label", str(self.label or ""))


@dataclass(frozen=True, slots=True)
class _Record:
    candidate_id: str
    pitch: int
    start_ms: float
    end_ms: float
    confidence: float


@dataclass(slots=True)
class _PathNode:
    score: float
    record: _Record
    previous: "_PathNode | None"


def _candidate_records(
    candidates: Sequence[object],
    candidate_ids: Sequence[str],
) -> tuple[_Record, ...]:
    records: list[_Record] = []
    used_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        start_ms = max(0.0, _finite(getattr(candidate, "start_ms", 0.0)))
        duration_ms = max(
            1.0,
            _finite(getattr(candidate, "duration_ms", 0.0), 1.0),
        )
        pitch = max(0, min(127, int(_finite(getattr(candidate, "pitch", 60), 60))))
        raw_id = (
            str(candidate_ids[index])
            if index < len(candidate_ids)
            else str(getattr(candidate, "candidate_id", "") or "")
        )
        candidate_id = raw_id or f"guide-candidate-{index:08d}"
        if candidate_id in used_ids:
            candidate_id = f"{candidate_id}#{index}"
        used_ids.add(candidate_id)
        records.append(
            _Record(
                candidate_id,
                pitch,
                start_ms,
                start_ms + duration_ms,
                _clamp01(getattr(candidate, "confidence", 0.0)),
            )
        )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.start_ms,
                item.pitch,
                item.end_ms,
                item.candidate_id,
            ),
        )
    )


def _bounded_source_records(records: Sequence[_Record]) -> tuple[str, ...]:
    return tuple(
        record.candidate_id
        for record in sorted(
            records,
            key=lambda item: (-item.confidence, item.start_ms, item.candidate_id),
        )[:_MAX_HIT_SOURCE_IDS]
    )


def _append_overview_contour(
    output: list[MelodyLineSegment],
    ordered: Sequence[_Record],
    *,
    role: str,
    group_id: str,
    group_weight: float,
    beat_ms: float,
    branch: bool,
) -> None:
    """Add a bounded, beat-decimated contour for zoomed-out inspection."""

    if not ordered:
        return
    bucket_ms = max(90.0, beat_ms * 0.5)
    maximum_gap = max(140.0, beat_ms * 1.5)
    phrases: list[list[_Record]] = [[]]
    for record in ordered:
        if (
            phrases[-1]
            and record.start_ms - phrases[-1][-1].end_ms > maximum_gap
        ):
            phrases.append([])
        phrases[-1].append(record)

    for phrase in phrases:
        buckets: list[list[_Record]] = []
        anchor = phrase[0].start_ms
        for record in phrase:
            bucket_index = int(max(0.0, record.start_ms - anchor) // bucket_ms)
            while len(buckets) <= bucket_index:
                buckets.append([])
            buckets[bucket_index].append(record)
        buckets = [bucket for bucket in buckets if bucket]
        points: list[tuple[float, float, float, tuple[str, ...]]] = []
        for bucket in buckets:
            weights = [0.25 + item.confidence for item in bucket]
            total = sum(weights)
            # Contour X positions represent onsets, not note midpoints.  A
            # song-long sustained candidate can begin in the first bucket
            # while its midpoint lies minutes after later buckets; midpoint
            # averaging would then create a backwards time segment.  Start
            # buckets are disjoint and ordered, so their weighted onsets are
            # strictly monotonic without weakening segment validation.
            center_ms = sum(
                item.start_ms * weight
                for item, weight in zip(bucket, weights)
            ) / total
            pitch = sum(
                item.pitch * weight for item, weight in zip(bucket, weights)
            ) / total
            confidence = _clamp01(
                (sum(item.confidence for item in bucket) / len(bucket))
                * group_weight
            )
            points.append(
                (center_ms, pitch, confidence, _bounded_source_records(bucket))
            )
        if len(points) == 1:
            center_ms, pitch, confidence, source_ids = points[0]
            output.append(
                MelodyLineSegment(
                    role,
                    group_id,
                    min(item.start_ms for item in phrase),
                    max(item.end_ms for item in phrase),
                    pitch,
                    pitch,
                    confidence,
                    branch,
                    CONTOUR_KIND,
                    source_ids,
                )
            )
            continue
        for previous, current in zip(points, points[1:]):
            output.append(
                MelodyLineSegment(
                    role,
                    group_id,
                    previous[0],
                    current[0],
                    previous[1],
                    current[1],
                    min(previous[2], current[2]),
                    branch,
                    CONTOUR_KIND,
                    _source_ids((*previous[3], *current[3])),
                )
            )


def _append_path_segments(
    output: list[MelodyLineSegment],
    records: Iterable[_Record],
    *,
    role: str,
    group_id: str,
    group_confidence: float,
    beat_ms: float,
    branch: bool,
) -> None:
    ordered = tuple(
        sorted(
            records,
            key=lambda item: (
                item.start_ms,
                item.pitch,
                item.end_ms,
                item.candidate_id,
            ),
        )
    )
    if not ordered:
        return
    group_weight = 0.55 + 0.45 * _clamp01(group_confidence)
    _append_overview_contour(
        output,
        ordered,
        role=role,
        group_id=group_id,
        group_weight=group_weight,
        beat_ms=beat_ms,
        branch=branch,
    )
    previous: _Record | None = None
    maximum_gap = max(140.0, float(beat_ms) * 1.5)
    for record in ordered:
        note_confidence = _clamp01(record.confidence * group_weight)
        output.append(
            MelodyLineSegment(
                role,
                group_id,
                record.start_ms,
                record.end_ms,
                float(record.pitch),
                float(record.pitch),
                note_confidence,
                branch,
                NOTE_KIND,
                (record.candidate_id,),
            )
        )
        if (
            previous is not None
            and record.start_ms >= previous.end_ms
            and record.start_ms - previous.end_ms <= maximum_gap
            and abs(record.pitch - previous.pitch) <= 24
        ):
            output.append(
                MelodyLineSegment(
                    role,
                    group_id,
                    previous.end_ms,
                    record.start_ms,
                    float(previous.pitch),
                    float(record.pitch),
                    min(
                        note_confidence,
                        _clamp01(previous.confidence * group_weight),
                    ),
                    branch,
                    CONNECTOR_KIND,
                    (previous.candidate_id, record.candidate_id),
                )
            )
        previous = record


def _segments_from_voice_groups(
    records: tuple[_Record, ...],
    voice_groups: Sequence[object],
    *,
    beat_ms: float,
) -> tuple[list[MelodyLineSegment], set[str], set[str]]:
    by_id = {record.candidate_id: record for record in records}
    prepared: list[
        tuple[str, str, str, float, float, float, tuple[_Record, ...]]
    ] = []
    for group in voice_groups:
        source_role = str(getattr(group, "role", "") or "")
        role = _role_family(source_role)
        if not role:
            continue
        members = tuple(
            by_id[candidate_id]
            for candidate_id in (
                str(value)
                for value in (getattr(group, "candidate_ids", ()) or ())
            )
            if candidate_id in by_id
        )
        if not members:
            continue
        prepared.append(
            (
                role,
                str(getattr(group, "group_id", "") or "voice"),
                source_role,
                _clamp01(getattr(group, "confidence", 0.0)),
                min(record.start_ms for record in members),
                max(record.end_ms for record in members),
                members,
            )
        )
    prepared.sort(key=lambda item: (item[0], item[4], item[5], item[1]))

    output: list[MelodyLineSegment] = []
    assigned: set[str] = set()
    represented_roles: set[str] = set()
    accepted_spans: dict[str, list[tuple[float, float, float]]] = {
        role: [] for role in GUIDE_ROLES
    }
    for (
        role,
        group_id,
        source_role,
        confidence,
        start_ms,
        end_ms,
        members,
    ) in prepared:
        branch = role == PRIMARY_ROLE and "secondary" in source_role.lower()
        if not branch:
            branch = any(
                min(end_ms, other_end) > max(start_ms, other_start)
                and other_confidence >= confidence
                for other_start, other_end, other_confidence in accepted_spans[role]
            )
        _append_path_segments(
            output,
            members,
            role=role,
            group_id=group_id,
            group_confidence=confidence,
            beat_ms=beat_ms,
            branch=branch,
        )
        accepted_spans[role].append((start_ms, end_ms, confidence))
        assigned.update(record.candidate_id for record in members)
        represented_roles.add(role)
    return output, assigned, represented_roles


def _harmony_intervals(quality: object) -> tuple[int, ...]:
    normalized = str(quality or "").strip().lower()
    return {
        "major": (0, 4, 7),
        "minor": (0, 3, 7),
        "dim": (0, 3, 6),
        "diminished": (0, 3, 6),
        "sus2": (0, 2, 7),
        "sus4": (0, 5, 7),
        "7": (0, 4, 7, 10),
        "dominant7": (0, 4, 7, 10),
        "maj7": (0, 4, 7, 11),
        "major7": (0, 4, 7, 11),
        "min7": (0, 3, 7, 10),
        "minor7": (0, 3, 7, 10),
    }.get(normalized, ())


def _harmony_segments(harmony_analysis: object | None) -> tuple[object, ...]:
    return tuple(
        sorted(
            (
                getattr(harmony_analysis, "chord_segments", ())
                or getattr(harmony_analysis, "segments", ())
                or ()
            ),
            key=lambda item: (
                _finite(getattr(item, "start_audio_ms", 0.0)),
                _finite(getattr(item, "end_audio_ms", 0.0)),
                str(getattr(item, "segment_id", "")),
            ),
        )
    )


def _chord_records(
    records: tuple[_Record, ...],
    harmony_analysis: object | None,
    excluded_ids: set[str],
) -> tuple[_Record, ...]:
    segments = _harmony_segments(harmony_analysis)
    if not segments:
        return ()
    starts = [_finite(getattr(item, "start_audio_ms", 0.0)) for item in segments]
    selected: list[_Record] = []
    for record in records:
        if record.candidate_id in excluded_ids:
            continue
        midpoint = (record.start_ms + record.end_ms) * 0.5
        index = bisect_right(starts, midpoint) - 1
        if index < 0:
            continue
        segment = segments[index]
        if midpoint >= _finite(getattr(segment, "end_audio_ms", 0.0)):
            continue
        root_pc = getattr(segment, "root_pc", None)
        if root_pc is None:
            continue
        intervals = _harmony_intervals(getattr(segment, "quality", ""))
        if intervals and (record.pitch - int(root_pc)) % 12 in intervals:
            selected.append(record)
    return tuple(selected)


def _chord_label(segment: object) -> str:
    root_pc = getattr(segment, "root_pc", None)
    if root_pc is None:
        return "N"
    roots = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    quality = str(getattr(segment, "quality", "") or "").strip().lower()
    suffix = {
        "major": "",
        "minor": "m",
        "dim": "dim",
        "diminished": "dim",
        "sus2": "sus2",
        "sus4": "sus4",
        "dominant7": "7",
        "major7": "maj7",
        "minor7": "m7",
    }.get(quality, quality)
    return f"{roots[int(root_pc) % 12]}{suffix}"


def _chord_span_segments(
    records: tuple[_Record, ...],
    harmony_analysis: object | None,
    excluded_ids: set[str],
) -> list[MelodyLineSegment]:
    output: list[MelodyLineSegment] = []
    for index, segment in enumerate(_harmony_segments(harmony_analysis)):
        start_ms = max(0.0, _finite(getattr(segment, "start_audio_ms", 0.0)))
        end_ms = max(start_ms, _finite(getattr(segment, "end_audio_ms", start_ms)))
        if end_ms <= start_ms or getattr(segment, "root_pc", None) is None:
            continue
        intervals = _harmony_intervals(getattr(segment, "quality", ""))
        if not intervals:
            continue
        supporting = [
            record
            for record in records
            if record.candidate_id not in excluded_ids
            and start_ms <= (record.start_ms + record.end_ms) * 0.5 < end_ms
            and (record.pitch - int(getattr(segment, "root_pc"))) % 12 in intervals
        ]
        if not supporting:
            continue
        center_pitch = float(median(record.pitch for record in supporting))
        evidence_confidence = sum(record.confidence for record in supporting) / len(supporting)
        segment_confidence = _clamp01(getattr(segment, "confidence", evidence_confidence))
        confidence = _clamp01(0.6 * segment_confidence + 0.4 * evidence_confidence)
        output.append(
            MelodyLineSegment(
                HARMONY_ROLE,
                str(getattr(segment, "segment_id", "") or f"chord-{index}"),
                start_ms,
                end_ms,
                center_pitch,
                center_pitch,
                confidence,
                False,
                CHORD_SPAN_KIND,
                _bounded_source_records(supporting),
                _chord_label(segment),
            )
        )
    return output


def _onset_clusters(records: Sequence[_Record], beat_ms: float) -> list[list[_Record]]:
    tolerance_ms = max(35.0, min(90.0, beat_ms * 0.10))
    clusters: list[list[_Record]] = []
    for record in records:
        if not clusters or record.start_ms - clusters[-1][0].start_ms > tolerance_ms:
            clusters.append([record])
        else:
            clusters[-1].append(record)
    return clusters


def _path_emission(
    record: _Record,
    *,
    beat_ms: float,
    preference: str,
    rank: float,
) -> float:
    if preference == "high":
        register_score = rank
    elif preference == "low":
        register_score = 1.0 - rank
    else:
        register_score = 1.0 - abs(rank - 0.5) * 2.0
    duration_score = min(1.0, (record.end_ms - record.start_ms) / max(1.0, beat_ms))
    return 2.3 * record.confidence + 0.7 * register_score + 0.25 * duration_score


def _path_transition(previous: _Record, current: _Record, beat_ms: float) -> float:
    leap = abs(current.pitch - previous.pitch)
    gap = max(0.0, current.start_ms - previous.end_ms)
    continuity = 0.55 - min(1.8, leap / 12.0 * 0.55)
    continuity -= min(1.2, gap / max(1.0, beat_ms) * 0.22)
    if leap <= 2:
        continuity += 0.18
    return continuity


def _select_continuity_path(
    clusters: Sequence[Sequence[_Record]],
    *,
    beat_ms: float,
    preference: str,
) -> tuple[_Record, ...]:
    """Use a bounded beam so dense chords do not create quadratic work."""

    active: list[_PathNode] = []
    for cluster in clusters:
        ordered = tuple(sorted(cluster, key=lambda item: (item.pitch, item.candidate_id)))
        if not ordered:
            continue
        nodes: list[_PathNode] = []
        rank_denominator = max(1, len(ordered) - 1)
        for rank_index, record in enumerate(ordered):
            emission = _path_emission(
                record,
                beat_ms=beat_ms,
                preference=preference,
                rank=rank_index / rank_denominator,
            )
            if not active:
                nodes.append(_PathNode(emission, record, None))
                continue
            previous: _PathNode | None = None
            previous_total = -math.inf
            previous_key: tuple[float, int, str] | None = None
            for candidate_node in active:
                transition = _path_transition(
                    candidate_node.record,
                    record,
                    beat_ms,
                )
                key = (
                    candidate_node.score + transition,
                    -abs(candidate_node.record.pitch - record.pitch),
                    candidate_node.record.candidate_id,
                )
                if previous_key is None or key > previous_key:
                    previous = candidate_node
                    previous_total = candidate_node.score + transition
                    previous_key = key
            assert previous is not None
            nodes.append(
                _PathNode(
                    previous_total + emission,
                    record,
                    previous,
                )
            )
        active = sorted(
            nodes,
            key=lambda node: (-node.score, node.record.pitch, node.record.candidate_id),
        )[:_PATH_BEAM_SIZE]
    if not active:
        return ()
    node = max(
        active,
        key=lambda item: (item.score, -item.record.pitch, item.record.candidate_id),
    )
    reversed_path: list[_Record] = []
    while node is not None:
        reversed_path.append(node.record)
        node = node.previous
    return tuple(reversed(reversed_path))


def _fallback_paths(
    records: tuple[_Record, ...],
    *,
    beat_ms: float,
    harmony_analysis: object | None,
) -> list[MelodyLineSegment]:
    if not records:
        return []
    clusters = _onset_clusters(records, beat_ms)
    primary = _select_continuity_path(
        clusters,
        beat_ms=beat_ms,
        preference="high",
    )
    cluster_index_by_candidate_id = {
        record.candidate_id: index
        for index, cluster in enumerate(clusters)
        for record in cluster
    }
    primary_by_cluster = {
        cluster_index_by_candidate_id[record.candidate_id]: record
        for record in primary
        if record.candidate_id in cluster_index_by_candidate_id
    }
    primary_ids = {record.candidate_id for record in primary}

    bass_clusters: list[list[_Record]] = []
    for index, cluster in enumerate(clusters):
        lead = primary_by_cluster.get(index)
        eligible = [
            record
            for record in cluster
            if record.candidate_id not in primary_ids
            and (lead is None or record.pitch <= lead.pitch - 5)
        ]
        if eligible:
            bass_clusters.append(eligible)
    bass = _select_continuity_path(
        bass_clusters,
        beat_ms=beat_ms,
        preference="low",
    )
    bass_ids = {record.candidate_id for record in bass}

    chord_ids = {
        item.candidate_id
        for item in _chord_records(records, harmony_analysis, set())
    }
    harmony_clusters: list[list[_Record]] = []
    for cluster in clusters:
        eligible = [
            record
            for record in cluster
            if record.candidate_id not in primary_ids
            and record.candidate_id not in bass_ids
            and (not chord_ids or record.candidate_id in chord_ids)
        ]
        if eligible:
            harmony_clusters.append(eligible)
    harmony = _select_continuity_path(
        harmony_clusters,
        beat_ms=beat_ms,
        preference="center",
    )
    harmony_ids = {record.candidate_id for record in harmony}

    branch_clusters: list[list[_Record]] = []
    for index, cluster in enumerate(clusters):
        lead = primary_by_cluster.get(index)
        if lead is None:
            continue
        eligible = [
            record
            for record in cluster
            if record.candidate_id not in primary_ids
            and record.candidate_id not in bass_ids
            and record.candidate_id not in harmony_ids
            and record.pitch >= lead.pitch - 7
            and record.confidence >= max(0.32, lead.confidence - 0.18)
        ]
        if eligible:
            branch_clusters.append(eligible)
    primary_branch = _select_continuity_path(
        branch_clusters,
        beat_ms=beat_ms,
        preference="high",
    )

    output: list[MelodyLineSegment] = []
    _append_path_segments(
        output,
        primary,
        role=PRIMARY_ROLE,
        group_id="fallback-primary",
        group_confidence=0.78,
        beat_ms=beat_ms,
        branch=False,
    )
    _append_path_segments(
        output,
        bass,
        role=BASS_ROLE,
        group_id="fallback-bass",
        group_confidence=0.70,
        beat_ms=beat_ms,
        branch=False,
    )
    _append_path_segments(
        output,
        harmony,
        role=HARMONY_ROLE,
        group_id="fallback-harmony",
        group_confidence=0.62,
        beat_ms=beat_ms,
        branch=False,
    )
    _append_path_segments(
        output,
        primary_branch,
        role=PRIMARY_ROLE,
        group_id="fallback-secondary",
        group_confidence=0.50,
        beat_ms=beat_ms,
        branch=True,
    )
    return output


def build_melody_line_segments(
    candidates: Sequence[object],
    candidate_ids: Sequence[str] = (),
    *,
    voice_groups: Sequence[object] = (),
    harmony_analysis: object | None = None,
    beat_ms: float = 500.0,
) -> tuple[MelodyLineSegment, ...]:
    """Return deterministic voice guides without changing review state.

    Semantic voice roles take precedence.  Before those sidecars are ready, a
    bounded continuity path exposes one lead, one available lower voice, one
    chord-support voice and an optional weak secondary branch.  Harmony
    analysis additionally contributes beat-aligned chord spans.
    """

    normalized_beat_ms = _finite(beat_ms, 500.0)
    if normalized_beat_ms <= 0.0:
        normalized_beat_ms = 500.0
    records = _candidate_records(tuple(candidates), tuple(candidate_ids))
    if not records:
        return ()

    output, assigned, represented_roles = _segments_from_voice_groups(
        records,
        tuple(voice_groups),
        beat_ms=normalized_beat_ms,
    )
    if not output:
        output = _fallback_paths(
            records,
            beat_ms=normalized_beat_ms,
            harmony_analysis=harmony_analysis,
        )
    elif HARMONY_ROLE not in represented_roles:
        chord_members = _chord_records(records, harmony_analysis, assigned)
        _append_path_segments(
            output,
            chord_members,
            role=HARMONY_ROLE,
            group_id="harmony-evidence",
            group_confidence=0.58,
            beat_ms=normalized_beat_ms,
            branch=False,
        )
    melodic_ids = {
        candidate_id
        for segment in output
        if segment.role in {PRIMARY_ROLE, BASS_ROLE}
        for candidate_id in segment.source_candidate_ids
    }
    output.extend(
        _chord_span_segments(records, harmony_analysis, melodic_ids)
    )

    return tuple(
        sorted(
            output,
            key=lambda item: (
                item.start_audio_ms,
                item.end_audio_ms,
                item.role,
                item.group_id,
                item.kind,
                item.start_pitch,
                item.end_pitch,
                item.branch,
                item.confidence,
                item.source_candidate_ids,
            ),
        )
    )


__all__ = [
    "BASS_ROLE",
    "CHORD_SPAN_KIND",
    "CONFIDENCE_BUCKETS",
    "CONNECTOR_KIND",
    "CONTOUR_KIND",
    "DETAIL_LOD",
    "GUIDE_KINDS",
    "GUIDE_ROLES",
    "HARMONY_ROLE",
    "MELODY_LINE_VERSION",
    "MelodyLineSegment",
    "NOTE_KIND",
    "OVERVIEW_LOD",
    "PHRASE_LOD",
    "PRIMARY_ROLE",
    "build_melody_line_segments",
    "melody_line_confidence_bucket",
    "melody_line_kind_visible",
    "melody_line_lod",
    "melody_line_width",
]
