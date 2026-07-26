"""Qt-free voice grouping and explainable BDO instrument suggestions.

This module deliberately consumes already decoded transcription candidates and
already extracted numeric timbre features.  It never opens audio/sample files,
which keeps it safe to call from a background worker without accidentally
moving disk or decoder work into the GUI or real-time audio paths.

The output is advisory.  A match is not permission to create a track or route a
candidate; the editor must keep that as an explicit user action.  Long-running
pure analysis entry points accept a cooperative ``cancelled`` callback so a
closing editor does not need to wait for every group/instrument pair.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from statistics import median
from typing import Callable, Iterable, Mapping, Protocol, Sequence


INSTRUMENT_ANALYSIS_VERSION = "bdo-instrument-assist-v2"
DEFAULT_ONSET_TOLERANCE_MS = 35.0
DEFAULT_PHRASE_GAP_BEATS = 1.5
NO_TIMBRE_CONFIDENCE_CAP = 0.45
SEMANTIC_FOLD_ONSET_TOLERANCE_MS = 80.0
SEMANTIC_FOLD_MIN_OVERLAP_RATIO = 0.75

_TRACK_ROLES = frozenset(
    {
        "primary_melody",
        "secondary_melody",
        "harmony",
        "bass",
        "rhythm",
        "percussion",
        "pad",
        "ornament",
        "fx",
    }
)
_ROLE_ALIASES = {
    "melody": "primary_melody",
    "primary": "primary_melody",
    "secondary": "secondary_melody",
    "accompaniment": "harmony",
    "chord": "harmony",
    "drums": "percussion",
    "drum": "percussion",
    "effect": "fx",
}
_MELODIC_ROLES = frozenset({"primary_melody", "secondary_melody"})
_SUSTAINED_ROLES = frozenset({"harmony", "pad"})

CancelCallback = Callable[[], bool]


class InstrumentAnalysisCancelled(RuntimeError):
    """Raised when a background instrument-analysis job is cancelled."""


def _check_cancelled(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise InstrumentAnalysisCancelled("instrument analysis cancelled")


class CandidateLike(Protocol):
    """Minimum candidate surface needed by the pure analysis functions."""

    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float
    candidate_id: str


class ManualVoiceGroupLike(Protocol):
    group_id: str
    candidate_ids: Sequence[str]
    start_audio_ms: float
    end_audio_ms: float
    role: str
    orphaned: bool


@dataclass(frozen=True, slots=True)
class VoiceGroup:
    group_id: str
    candidate_ids: tuple[str, ...]
    start_audio_ms: float
    end_audio_ms: float
    role: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.group_id or not self.candidate_ids:
            raise ValueError("a voice group requires stable identifiers")
        if not math.isfinite(self.start_audio_ms) or not math.isfinite(self.end_audio_ms):
            raise ValueError("voice group times must be finite")
        if self.start_audio_ms < 0.0 or self.end_audio_ms < self.start_audio_ms:
            raise ValueError("invalid voice group time range")
        object.__setattr__(self, "candidate_ids", tuple(str(item) for item in self.candidate_ids))
        object.__setattr__(self, "role", normalize_track_role(self.role))
        object.__setattr__(self, "confidence", _clamp01(self.confidence))


@dataclass(frozen=True, slots=True)
class BdoInstrumentMatch:
    instrument_id: int
    total_score: float
    pitch_coverage: float
    timbre_score: float | None
    role_score: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_id", int(self.instrument_id))
        object.__setattr__(self, "total_score", _clamp01(self.total_score))
        object.__setattr__(self, "pitch_coverage", _clamp01(self.pitch_coverage))
        if self.timbre_score is not None:
            object.__setattr__(self, "timbre_score", _clamp01(self.timbre_score))
        object.__setattr__(self, "role_score", _clamp01(self.role_score))
        object.__setattr__(self, "reasons", tuple(str(item) for item in self.reasons))


@dataclass(frozen=True, slots=True)
class InstrumentMatchAnalysis:
    cache_key: str
    sample_profile_key: str
    groups: tuple[VoiceGroup, ...]
    matches: tuple[tuple[str, tuple[BdoInstrumentMatch, ...]], ...]

    def matches_for_group(self, group_id: str) -> tuple[BdoInstrumentMatch, ...]:
        for current_group_id, values in self.matches:
            if current_group_id == group_id:
                return values
        return ()


@dataclass(frozen=True, slots=True)
class TimbreFeatureProfile:
    """A path-free centroid of consistently normalized audio features.

    Feature extraction (MFCC, spectral contrast, centroid, rolloff, flatness,
    attack/decay, and any calibration) belongs to a background audio worker.
    This value only carries finite numbers and a content-derived key.
    """

    profile_key: str
    feature_names: tuple[str, ...]
    values: tuple[float, ...]
    sample_count: int
    reliability: float = 1.0

    def __post_init__(self) -> None:
        if not self.profile_key:
            raise ValueError("profile_key is required")
        if not self.feature_names or len(self.feature_names) != len(self.values):
            raise ValueError("timbre feature names and values must align")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("timbre feature names must be unique")
        if not all(math.isfinite(float(value)) for value in self.values):
            raise ValueError("timbre features must be finite")
        if int(self.sample_count) <= 0:
            raise ValueError("sample_count must be positive")
        object.__setattr__(self, "feature_names", tuple(str(item) for item in self.feature_names))
        object.__setattr__(self, "values", tuple(float(item) for item in self.values))
        object.__setattr__(self, "sample_count", int(self.sample_count))
        object.__setattr__(self, "reliability", _clamp01(self.reliability))


@dataclass(frozen=True, slots=True)
class BdoInstrumentDescriptor:
    """Caller-supplied, evidence-labelled constraints for one BDO instrument."""

    instrument_id: int
    pitch_min: int | None = None
    pitch_max: int | None = None
    available_pitches: frozenset[int] = frozenset()
    preferred_roles: frozenset[str] = frozenset()
    articulation_profile: str = "versatile"
    is_percussion: bool = False
    timbre_evidence_approved: bool = True

    def __post_init__(self) -> None:
        pitch_min = int(self.pitch_min) if self.pitch_min is not None else None
        pitch_max = int(self.pitch_max) if self.pitch_max is not None else None
        if pitch_min is not None and pitch_max is not None and pitch_min > pitch_max:
            raise ValueError("pitch_min must not exceed pitch_max")
        pitches = frozenset(int(item) for item in self.available_pitches)
        if pitch_min is not None:
            pitches = frozenset(item for item in pitches if item >= pitch_min)
        if pitch_max is not None:
            pitches = frozenset(item for item in pitches if item <= pitch_max)
        roles = frozenset(normalize_track_role(item) for item in self.preferred_roles)
        articulation = str(self.articulation_profile).strip().casefold()
        articulation = {"sustained": "sustain", "long": "sustain"}.get(
            articulation, articulation
        )
        if articulation not in {"short", "sustain", "versatile"}:
            raise ValueError(f"unsupported articulation profile: {articulation}")
        object.__setattr__(self, "instrument_id", int(self.instrument_id))
        object.__setattr__(self, "pitch_min", pitch_min)
        object.__setattr__(self, "pitch_max", pitch_max)
        object.__setattr__(self, "available_pitches", pitches)
        object.__setattr__(self, "preferred_roles", roles)
        object.__setattr__(self, "articulation_profile", articulation)
        object.__setattr__(self, "is_percussion", bool(self.is_percussion))
        object.__setattr__(
            self, "timbre_evidence_approved", bool(self.timbre_evidence_approved)
        )

    def supports_pitch(self, pitch: int) -> bool:
        value = int(pitch)
        if self.available_pitches:
            return value in self.available_pitches
        if self.pitch_min is None or self.pitch_max is None:
            return False
        return self.pitch_min <= value <= self.pitch_max


@dataclass(frozen=True, slots=True)
class _CandidateRecord:
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


@dataclass(slots=True)
class _VoiceState:
    serial: int
    records: list[_CandidateRecord]

    @property
    def last(self) -> _CandidateRecord:
        return self.records[-1]


@dataclass(frozen=True, slots=True)
class _GroupStats:
    group: VoiceGroup
    median_pitch: float
    average_duration_ms: float
    notes_per_beat: float


def normalize_track_role(role: object) -> str:
    """Return a stable string compatible with :class:`TrackRole` values."""

    raw = getattr(role, "value", role)
    value = str(raw).strip().casefold().replace("-", "_").replace(" ", "_")
    value = _ROLE_ALIASES.get(value, value)
    if value not in _TRACK_ROLES:
        raise ValueError(f"unsupported track role: {raw}")
    return value


def build_timbre_feature_profile(
    feature_samples: Iterable[Mapping[str, float]],
    *,
    reliability: float = 1.0,
    max_samples: int = 32,
    cancelled: CancelCallback | None = None,
) -> TimbreFeatureProfile:
    """Summarize pre-extracted feature mappings without reading any files.

    The worker that decoded the audio should provide consistently normalized
    feature names.  At most ``max_samples`` deterministic representatives are
    used.  The returned key is derived from numeric content and cannot expose a
    source filename.
    """

    if max_samples <= 0:
        raise ValueError("max_samples must be positive")
    _check_cancelled(cancelled)
    cleaned: list[dict[str, float]] = []
    for sample in feature_samples:
        _check_cancelled(cancelled)
        values = {
            str(name): float(value)
            for name, value in sample.items()
            if str(name) and math.isfinite(float(value))
        }
        if values:
            cleaned.append(values)
    if not cleaned:
        raise ValueError("at least one finite feature sample is required")
    _check_cancelled(cancelled)
    common_names = set(cleaned[0])
    for values in cleaned[1:]:
        _check_cancelled(cancelled)
        common_names.intersection_update(values)
    if not common_names:
        raise ValueError("feature samples have no common dimensions")
    _check_cancelled(cancelled)
    names = tuple(sorted(common_names))
    rows = sorted(tuple(values[name] for name in names) for values in cleaned)[:max_samples]
    _check_cancelled(cancelled)
    centroid = tuple(float(median(column)) for column in zip(*rows))
    canonical = json.dumps(
        {"names": names, "values": centroid, "count": len(rows)},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    profile_key = hashlib.sha256(canonical).hexdigest()[:24]
    return TimbreFeatureProfile(
        profile_key,
        names,
        centroid,
        len(rows),
        reliability,
    )


def group_voice_candidates(
    candidates: Sequence[CandidateLike],
    *,
    beat_ms: float,
    onset_tolerance_ms: float = DEFAULT_ONSET_TOLERANCE_MS,
    phrase_gap_beats: float = DEFAULT_PHRASE_GAP_BEATS,
    max_pitch_leap: int = 24,
    cancelled: CancelCallback | None = None,
) -> tuple[VoiceGroup, ...]:
    """Assign candidates to deterministic monophonic phrase/voice groups."""

    if not math.isfinite(float(beat_ms)) or beat_ms <= 0.0:
        raise ValueError("beat_ms must be positive and finite")
    if not math.isfinite(float(onset_tolerance_ms)) or onset_tolerance_ms < 0.0:
        raise ValueError("onset_tolerance_ms must be finite and non-negative")
    if not math.isfinite(float(phrase_gap_beats)) or phrase_gap_beats <= 0.0:
        raise ValueError("phrase_gap_beats must be positive and finite")
    if max_pitch_leap <= 0:
        raise ValueError("max_pitch_leap must be positive")

    _check_cancelled(cancelled)
    records = _fold_overlapping_same_pitch_records(
        _prepare_candidates(candidates, cancelled=cancelled),
        cancelled=cancelled,
    )
    if not records:
        return ()
    onset_clusters = _onset_clusters(
        records,
        float(onset_tolerance_ms),
        cancelled=cancelled,
    )
    phrase_gap_ms = float(beat_ms) * float(phrase_gap_beats)
    active_states: list[_VoiceState] = []
    completed_states: list[_VoiceState] = []
    next_serial = 0

    for cluster in onset_clusters:
        _check_cancelled(cancelled)
        cluster_start = cluster[0].start_ms
        still_active: list[_VoiceState] = []
        for state in active_states:
            _check_cancelled(cancelled)
            if cluster_start - state.last.end_ms > phrase_gap_ms:
                completed_states.append(state)
            else:
                still_active.append(state)
        active_states = still_active
        # Each state may receive at most one member of a simultaneous onset
        # cluster, so vertical chords never collapse into one voice.
        pairs: list[tuple[float, int, int]] = []
        for record_index, record in enumerate(cluster):
            _check_cancelled(cancelled)
            for state_index, state in enumerate(active_states):
                _check_cancelled(cancelled)
                cost = _voice_connection_cost(
                    state.last,
                    record,
                    beat_ms=float(beat_ms),
                    phrase_gap_ms=phrase_gap_ms,
                    max_pitch_leap=int(max_pitch_leap),
                )
                if cost is not None:
                    pairs.append((cost, record_index, state_index))
        pairs.sort(
            key=lambda item: (
                item[0],
                cluster[item[1]].pitch,
                active_states[item[2]].last.pitch,
                active_states[item[2]].serial,
                cluster[item[1]].candidate_id,
            )
        )
        assigned_records: set[int] = set()
        assigned_states: set[int] = set()
        for _cost, record_index, state_index in pairs:
            _check_cancelled(cancelled)
            if record_index in assigned_records or state_index in assigned_states:
                continue
            active_states[state_index].records.append(cluster[record_index])
            assigned_records.add(record_index)
            assigned_states.add(state_index)
        for record_index, record in enumerate(cluster):
            _check_cancelled(cancelled)
            if record_index in assigned_records:
                continue
            active_states.append(_VoiceState(next_serial, [record]))
            next_serial += 1

    completed_states.extend(active_states)
    _check_cancelled(cancelled)
    stats = tuple(
        _voice_state_stats(state, float(beat_ms)) for state in completed_states
    )
    _check_cancelled(cancelled)
    groups = _infer_group_roles(stats, float(beat_ms))
    return tuple(
        sorted(
            groups,
            key=lambda item: (
                item.start_audio_ms,
                item.end_audio_ms,
                item.group_id,
            ),
        )
    )


def overlay_manual_voice_groups(
    automatic_groups: Sequence[VoiceGroup],
    candidates: Sequence[CandidateLike],
    reviews: Sequence[ManualVoiceGroupLike],
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[VoiceGroup, ...]:
    """Overlay exact-current manual groups without dropping residual notes.

    Reviews containing stale or missing candidate IDs are ignored here so the
    caller can re-anchor them against the untouched automatic groups.  Valid
    manual groups remove only their own candidates; any remaining candidates
    from an automatic group stay visible in a deterministic residual group.
    """

    _check_cancelled(cancelled)
    records = _prepare_candidates(candidates, cancelled=cancelled)
    records_by_id = {
        record.candidate_id: record for record in records
    }
    assigned: set[str] = set()
    manual_groups: list[VoiceGroup] = []
    ordered_reviews = sorted(
        reviews,
        key=lambda review: (
            float(getattr(review, "start_audio_ms", 0.0)),
            float(getattr(review, "end_audio_ms", 0.0)),
            str(getattr(review, "group_id", "")),
        ),
    )
    for review in ordered_reviews:
        _check_cancelled(cancelled)
        if bool(getattr(review, "orphaned", False)):
            continue
        requested_ids = tuple(
            dict.fromkeys(
                str(candidate_id)
                for candidate_id in getattr(
                    review, "candidate_ids", ()
                )
            )
        )
        if (
            not requested_ids
            or any(
                candidate_id not in records_by_id
                for candidate_id in requested_ids
            )
            or assigned.intersection(requested_ids)
        ):
            continue
        members = [records_by_id[item] for item in requested_ids]
        start_ms = float(getattr(review, "start_audio_ms", 0.0))
        end_ms = float(getattr(review, "end_audio_ms", 0.0))
        if (
            not math.isfinite(start_ms)
            or not math.isfinite(end_ms)
            or start_ms < 0.0
            or end_ms <= start_ms
        ):
            start_ms = min(item.start_ms for item in members)
            end_ms = max(item.end_ms for item in members)
        manual_groups.append(
            VoiceGroup(
                str(getattr(review, "group_id", "")),
                requested_ids,
                start_ms,
                end_ms,
                str(getattr(review, "role", "harmony")),
                1.0,
            )
        )
        assigned.update(requested_ids)

    residual_groups: list[VoiceGroup] = []
    for group in automatic_groups:
        _check_cancelled(cancelled)
        remaining_ids = tuple(
            candidate_id
            for candidate_id in group.candidate_ids
            if candidate_id in records_by_id
            and candidate_id not in assigned
        )
        if not remaining_ids:
            continue
        if remaining_ids == group.candidate_ids:
            residual_groups.append(group)
            continue
        members = [records_by_id[item] for item in remaining_ids]
        canonical = "\n".join(sorted(remaining_ids)).encode("utf-8")
        residual_groups.append(
            VoiceGroup(
                "voice-" + hashlib.sha256(canonical).hexdigest()[:20],
                remaining_ids,
                min(item.start_ms for item in members),
                max(item.end_ms for item in members),
                group.role,
                min(
                    group.confidence,
                    sum(item.confidence for item in members)
                    / len(members),
                ),
            )
        )
    return tuple(
        sorted(
            (*residual_groups, *manual_groups),
            key=lambda group: (
                group.start_audio_ms,
                group.end_audio_ms,
                group.group_id,
            ),
        )
    )


def refine_voice_groups_by_timbre(
    groups: Sequence[VoiceGroup],
    candidates: Sequence[CandidateLike],
    candidate_timbre_profiles: Mapping[str, TimbreFeatureProfile],
    *,
    change_threshold: float = 0.28,
    min_profiled_members_per_side: int = 2,
    min_side_cohesion: float = 0.68,
    cancelled: CancelCallback | None = None,
) -> tuple[VoiceGroup, ...]:
    """Split a phrase once when segment evidence shows a stable timbre change.

    Temporal/pitch continuity establishes the initial voice.  This second
    stage requires at least two reliable, path-free segment profiles on both
    sides of a boundary; sparse or unstable evidence leaves the phrase intact.
    It detects a change only and never claims an instrument identity.
    """

    threshold = float(change_threshold)
    minimum = int(min_profiled_members_per_side)
    cohesion_floor = float(min_side_cohesion)
    if not math.isfinite(threshold) or not 0.0 < threshold <= 1.0:
        raise ValueError("change_threshold must be finite within (0, 1]")
    if minimum < 2:
        raise ValueError("min_profiled_members_per_side must be at least two")
    if not math.isfinite(cohesion_floor) or not 0.0 < cohesion_floor <= 1.0:
        raise ValueError("min_side_cohesion must be finite within (0, 1]")
    _check_cancelled(cancelled)
    records = _prepare_candidates(candidates, cancelled=cancelled)
    by_id = {record.candidate_id: record for record in records}
    profiles = {
        str(candidate_id): profile
        for candidate_id, profile in candidate_timbre_profiles.items()
        if isinstance(profile, TimbreFeatureProfile)
        and profile.reliability >= 0.35
    }
    refined: list[VoiceGroup] = []
    for group in groups:
        _check_cancelled(cancelled)
        members = [
            by_id[candidate_id]
            for candidate_id in group.candidate_ids
            if candidate_id in by_id
        ]
        members.sort(
            key=lambda item: (
                item.start_ms,
                item.pitch,
                item.candidate_id,
            )
        )
        profiled = [
            (record, profiles[record.candidate_id])
            for record in members
            if record.candidate_id in profiles
        ]
        if len(profiled) < minimum * 2:
            refined.append(group)
            continue
        best: tuple[float, float, int] | None = None
        for split_index in range(
            minimum,
            len(profiled) - minimum + 1,
        ):
            _check_cancelled(cancelled)
            left_values = tuple(
                profile for _record, profile in profiled[:split_index]
            )
            right_values = tuple(
                profile for _record, profile in profiled[split_index:]
            )
            left_profile = _combine_timbre_profiles(
                left_values,
                cancelled=cancelled,
            )
            right_profile = _combine_timbre_profiles(
                right_values,
                cancelled=cancelled,
            )
            side_cohesion = min(
                sum(
                    _timbre_similarity(profile, left_profile)
                    for profile in left_values
                )
                / len(left_values),
                sum(
                    _timbre_similarity(profile, right_profile)
                    for profile in right_values
                )
                / len(right_values),
            )
            if side_cohesion < cohesion_floor:
                continue
            change = (
                1.0 - _timbre_similarity(left_profile, right_profile)
            ) * min(
                left_profile.reliability,
                right_profile.reliability,
            ) * side_cohesion
            boundary_ms = (
                profiled[split_index - 1][0].start_ms
                + profiled[split_index][0].start_ms
            ) * 0.5
            score = (change, -boundary_ms, split_index)
            if best is None or score > best:
                best = score
        if best is None or best[0] < threshold:
            refined.append(group)
            continue
        split_index = best[2]
        boundary_ms = (
            profiled[split_index - 1][0].start_ms
            + profiled[split_index][0].start_ms
        ) * 0.5
        partitions = (
            tuple(
                record for record in members
                if record.start_ms < boundary_ms
            ),
            tuple(
                record for record in members
                if record.start_ms >= boundary_ms
            ),
        )
        if any(not partition for partition in partitions):
            refined.append(group)
            continue
        for partition in partitions:
            ids = tuple(record.candidate_id for record in partition)
            canonical = "\n".join(sorted(ids)).encode("utf-8")
            refined.append(
                VoiceGroup(
                    "voice-" + hashlib.sha256(canonical).hexdigest()[:20],
                    ids,
                    min(record.start_ms for record in partition),
                    max(record.end_ms for record in partition),
                    group.role,
                    min(
                        group.confidence,
                        sum(record.confidence for record in partition)
                        / len(partition),
                    ),
                )
            )
    return tuple(
        sorted(
            refined,
            key=lambda item: (
                item.start_audio_ms,
                item.end_audio_ms,
                item.group_id,
            ),
        )
    )


# Descriptive alias for callers that do not expose "voice" in their UI.
group_transcription_candidates = group_voice_candidates


def match_bdo_instruments(
    groups: Sequence[VoiceGroup],
    candidates: Sequence[CandidateLike],
    instruments: Sequence[BdoInstrumentDescriptor],
    *,
    group_timbre_profiles: Mapping[str, TimbreFeatureProfile] | None = None,
    instrument_timbre_profiles: Mapping[int, TimbreFeatureProfile] | None = None,
    group_pitch_timbre_profiles: Mapping[
        str,
        Mapping[int, TimbreFeatureProfile],
    ] | None = None,
    instrument_pitch_timbre_profiles: Mapping[
        int,
        Mapping[int, TimbreFeatureProfile],
    ] | None = None,
    sample_profile_key: str = "",
    pitch_offset: int = 0,
    beat_ms: float = 500.0,
    top_k: int = 3,
    cancelled: CancelCallback | None = None,
) -> InstrumentMatchAnalysis:
    """Return deterministic, explainable Top-K matches for every voice group.

    With compatible timbre evidence the total uses the locked weights
    ``50/25/15/10`` for timbre/pitch/role/articulation.  Without it the same
    pitch/role/articulation terms are retained and the result is capped at
    ``0.45`` so range-only suggestions cannot look verified.  Per-pitch maps
    may be supplied explicitly or attached as ``pitch_profiles`` to the two
    compatibility mappings.  ``pitch_offset`` is the global export transpose:
    source-audio profiles stay keyed by the detected pitch, while BDO range
    checks and local game-sample profiles use the resulting exported pitch.
    """

    if not math.isfinite(float(beat_ms)) or beat_ms <= 0.0:
        raise ValueError("beat_ms must be positive and finite")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    pitch_offset = _normalise_pitch_offset(pitch_offset)
    _check_cancelled(cancelled)
    records = _prepare_candidates(candidates, cancelled=cancelled)
    by_id = {record.candidate_id: record for record in records}
    descriptors_by_id: dict[int, BdoInstrumentDescriptor] = {}
    for descriptor in instruments:
        _check_cancelled(cancelled)
        if descriptor.instrument_id in descriptors_by_id:
            raise ValueError(f"duplicate instrument id: {descriptor.instrument_id}")
        descriptors_by_id[descriptor.instrument_id] = descriptor
    descriptors = tuple(
        descriptors_by_id[key] for key in sorted(descriptors_by_id)
    )
    implicit_group_pitch_profiles = getattr(
        group_timbre_profiles,
        "pitch_profiles",
        {},
    )
    implicit_instrument_pitch_profiles = getattr(
        instrument_timbre_profiles,
        "pitch_profiles",
        {},
    )
    group_timbres = dict(group_timbre_profiles or {})
    instrument_timbres = {
        int(key): value for key, value in (instrument_timbre_profiles or {}).items()
    }
    group_pitch_timbres = _normalise_group_pitch_profiles(
        implicit_group_pitch_profiles,
    )
    group_pitch_timbres.update(
        _normalise_group_pitch_profiles(
            group_pitch_timbre_profiles or {},
        )
    )
    instrument_pitch_timbres = _normalise_instrument_pitch_profiles(
        implicit_instrument_pitch_profiles,
    )
    instrument_pitch_timbres.update(
        _normalise_instrument_pitch_profiles(
            instrument_pitch_timbre_profiles or {},
        )
    )
    safe_sample_key = _sample_profile_cache_key(
        sample_profile_key,
        instrument_timbres,
        instrument_pitch_timbres,
        cancelled=cancelled,
    )
    ordered_groups = tuple(
        sorted(groups, key=lambda item: (item.start_audio_ms, item.group_id))
    )
    match_rows: list[tuple[str, tuple[BdoInstrumentMatch, ...]]] = []
    for group in ordered_groups:
        _check_cancelled(cancelled)
        group_records = tuple(
            by_id[candidate_id]
            for candidate_id in group.candidate_ids
            if candidate_id in by_id
        )
        ranked: list[BdoInstrumentMatch] = []
        if group_records:
            group_articulation = _group_articulation(group_records, float(beat_ms))
            group_timbre = group_timbres.get(group.group_id)
            group_pitch_timbre = group_pitch_timbres.get(
                group.group_id,
                {},
            )
            for descriptor in descriptors:
                _check_cancelled(cancelled)
                if descriptor.is_percussion != (group.role == "percussion"):
                    continue
                supported_count = sum(
                    descriptor.supports_pitch(
                        record.pitch + pitch_offset
                    )
                    for record in group_records
                )
                pitch_coverage = supported_count / len(group_records)
                if pitch_coverage <= 0.0:
                    continue
                role_score = _role_affinity(group.role, descriptor.preferred_roles)
                articulation_score = _articulation_affinity(
                    group_articulation, descriptor.articulation_profile
                )
                instrument_timbre = instrument_timbres.get(descriptor.instrument_id)
                instrument_pitch_timbre = instrument_pitch_timbres.get(
                    descriptor.instrument_id,
                    {},
                )
                timbre_score: float | None = None
                timbre_reason = "timbre:no_local_evidence"
                if (
                    descriptor.timbre_evidence_approved
                ):
                    pitch_profiles_available = bool(
                        group_pitch_timbre or instrument_pitch_timbre
                    )
                    timbre_score, timbre_reason = (
                        _pitch_aware_timbre_similarity(
                            group_records,
                            group_pitch_timbre,
                            instrument_pitch_timbre,
                            pitch_offset=pitch_offset,
                            cancelled=cancelled,
                        )
                    )
                    if (
                        timbre_score is None
                        and not pitch_profiles_available
                        and group_timbre is not None
                        and instrument_timbre is not None
                        and group_timbre.reliability >= 0.35
                        and instrument_timbre.reliability >= 0.35
                    ):
                        timbre_score = _timbre_similarity(
                            group_timbre,
                            instrument_timbre,
                        )
                        timbre_reason = f"timbre:{timbre_score:.3f}"
                base_score = (
                    0.25 * pitch_coverage
                    + 0.15 * role_score
                    + 0.10 * articulation_score
                )
                if timbre_score is None:
                    total_score = min(NO_TIMBRE_CONFIDENCE_CAP, base_score)
                else:
                    total_score = 0.50 * timbre_score + base_score
                reasons = (
                    f"pitch:{supported_count}/{len(group_records)}",
                    f"role:{group.role}:{role_score:.3f}",
                    f"articulation:{group_articulation}:{articulation_score:.3f}",
                    f"pitch_offset:{pitch_offset:+d}",
                    (
                        timbre_reason
                    ),
                )
                ranked.append(
                    BdoInstrumentMatch(
                        descriptor.instrument_id,
                        total_score,
                        pitch_coverage,
                        timbre_score,
                        role_score,
                        reasons,
                    )
                )
        _check_cancelled(cancelled)
        ranked.sort(
            key=lambda item: (
                -item.total_score,
                -item.pitch_coverage,
                -item.role_score,
                item.instrument_id,
            )
        )
        match_rows.append((group.group_id, tuple(ranked[:top_k])))

    _check_cancelled(cancelled)
    cache_key = _analysis_cache_key(
        ordered_groups,
        records,
        descriptors,
        group_timbres,
        instrument_timbres,
        group_pitch_timbres,
        instrument_pitch_timbres,
        safe_sample_key,
        pitch_offset,
        float(beat_ms),
        int(top_k),
        cancelled=cancelled,
    )
    return InstrumentMatchAnalysis(
        cache_key,
        safe_sample_key,
        ordered_groups,
        tuple(match_rows),
    )


def analyse_instrument_matches(
    candidates: Sequence[CandidateLike],
    instruments: Sequence[BdoInstrumentDescriptor],
    *,
    beat_ms: float,
    group_timbre_profiles: Mapping[str, TimbreFeatureProfile] | None = None,
    instrument_timbre_profiles: Mapping[int, TimbreFeatureProfile] | None = None,
    group_pitch_timbre_profiles: Mapping[
        str,
        Mapping[int, TimbreFeatureProfile],
    ] | None = None,
    instrument_pitch_timbre_profiles: Mapping[
        int,
        Mapping[int, TimbreFeatureProfile],
    ] | None = None,
    sample_profile_key: str = "",
    pitch_offset: int = 0,
    top_k: int = 3,
    cancelled: CancelCallback | None = None,
) -> InstrumentMatchAnalysis:
    """Convenience boundary for a background worker's complete pure analysis."""

    groups = group_voice_candidates(
        candidates,
        beat_ms=beat_ms,
        cancelled=cancelled,
    )
    return match_bdo_instruments(
        groups,
        candidates,
        instruments,
        group_timbre_profiles=group_timbre_profiles,
        instrument_timbre_profiles=instrument_timbre_profiles,
        group_pitch_timbre_profiles=group_pitch_timbre_profiles,
        instrument_pitch_timbre_profiles=instrument_pitch_timbre_profiles,
        sample_profile_key=sample_profile_key,
        pitch_offset=pitch_offset,
        beat_ms=beat_ms,
        top_k=top_k,
        cancelled=cancelled,
    )


def _prepare_candidates(
    candidates: Sequence[CandidateLike],
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[_CandidateRecord, ...]:
    raw: list[tuple[str, int, float, float, float]] = []
    for candidate in candidates:
        _check_cancelled(cancelled)
        pitch = int(candidate.pitch)
        start_ms = float(candidate.start_ms)
        duration_ms = float(candidate.duration_ms)
        confidence = float(candidate.confidence)
        if (
            not math.isfinite(start_ms)
            or not math.isfinite(duration_ms)
            or not math.isfinite(confidence)
            or start_ms < 0.0
            or duration_ms <= 0.0
        ):
            continue
        supplied_id = str(getattr(candidate, "candidate_id", "") or "")
        if not supplied_id:
            canonical = (
                f"{pitch}|{start_ms:.6f}|{duration_ms:.6f}|"
                f"{_clamp01(confidence):.6f}"
            ).encode("ascii")
            supplied_id = hashlib.sha256(canonical).hexdigest()[:24]
        raw.append(
            (
                supplied_id,
                pitch,
                start_ms,
                duration_ms,
                _clamp01(confidence),
            )
        )
    raw.sort(key=lambda item: (item[2], item[1], item[3], item[4], item[0]))
    occurrences: dict[str, int] = {}
    records: list[_CandidateRecord] = []
    for supplied_id, pitch, start_ms, duration_ms, confidence in raw:
        _check_cancelled(cancelled)
        ordinal = occurrences.get(supplied_id, 0) + 1
        occurrences[supplied_id] = ordinal
        candidate_id = supplied_id if ordinal == 1 else f"{supplied_id}~{ordinal}"
        records.append(
            _CandidateRecord(
                candidate_id,
                pitch,
                start_ms,
                duration_ms,
                confidence,
            )
        )
    return tuple(records)


def _fold_overlapping_same_pitch_records(
    records: Sequence[_CandidateRecord],
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[_CandidateRecord, ...]:
    """Keep one semantic primary for near-identical decoded alternatives.

    Basic Pitch redecodes can retain several hypotheses for the same sounding
    event.  They remain available to the review UI, but feeding every
    alternative into monophonic voice assignment creates artificial voices and
    contaminates instrument matching.  This uses the same deterministic
    overlap/onset rule as the piano-roll visual fold.
    """

    by_pitch: dict[int, list[_CandidateRecord]] = {}
    for record in records:
        _check_cancelled(cancelled)
        by_pitch.setdefault(record.pitch, []).append(record)
    primaries: list[_CandidateRecord] = []
    for pitch in sorted(by_pitch):
        _check_cancelled(cancelled)
        ordered = sorted(
            by_pitch[pitch],
            key=lambda item: (
                item.start_ms,
                item.duration_ms,
                item.candidate_id,
            ),
        )
        clusters: list[list[_CandidateRecord]] = []
        cluster_start = 0.0
        cluster_end = 0.0
        cluster_max_duration = 0.0
        for record in ordered:
            _check_cancelled(cancelled)
            if not clusters:
                clusters.append([record])
                cluster_start = record.start_ms
                cluster_end = record.end_ms
                cluster_max_duration = record.duration_ms
                continue
            overlap_ms = max(
                0.0,
                min(cluster_end, record.end_ms)
                - max(cluster_start, record.start_ms),
            )
            minimum_duration = min(
                cluster_max_duration,
                record.duration_ms,
            )
            first = clusters[-1][0]
            if (
                minimum_duration > 0.0
                and overlap_ms / minimum_duration
                >= SEMANTIC_FOLD_MIN_OVERLAP_RATIO
                and abs(record.start_ms - first.start_ms)
                <= SEMANTIC_FOLD_ONSET_TOLERANCE_MS
            ):
                clusters[-1].append(record)
                cluster_start = min(cluster_start, record.start_ms)
                cluster_end = max(cluster_end, record.end_ms)
                cluster_max_duration = max(
                    cluster_max_duration,
                    record.duration_ms,
                )
            else:
                clusters.append([record])
                cluster_start = record.start_ms
                cluster_end = record.end_ms
                cluster_max_duration = record.duration_ms
        for cluster in clusters:
            _check_cancelled(cancelled)
            primaries.append(
                max(
                    cluster,
                    key=lambda item: (
                        item.confidence,
                        item.duration_ms,
                        -item.start_ms,
                        item.candidate_id,
                    ),
                )
            )
    return tuple(
        sorted(
            primaries,
            key=lambda item: (
                item.start_ms,
                item.pitch,
                item.duration_ms,
                item.candidate_id,
            ),
        )
    )


def _onset_clusters(
    records: Sequence[_CandidateRecord],
    tolerance_ms: float,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[tuple[_CandidateRecord, ...], ...]:
    clusters: list[list[_CandidateRecord]] = []
    cluster_start = 0.0
    for record in records:
        _check_cancelled(cancelled)
        if not clusters or record.start_ms - cluster_start > tolerance_ms:
            clusters.append([record])
            cluster_start = record.start_ms
        else:
            clusters[-1].append(record)
    return tuple(
        tuple(sorted(cluster, key=lambda item: (item.pitch, item.candidate_id)))
        for cluster in clusters
    )


def _voice_connection_cost(
    previous: _CandidateRecord,
    current: _CandidateRecord,
    *,
    beat_ms: float,
    phrase_gap_ms: float,
    max_pitch_leap: int,
) -> float | None:
    silence_ms = max(0.0, current.start_ms - previous.end_ms)
    if silence_ms > phrase_gap_ms:
        return None
    pitch_leap = abs(current.pitch - previous.pitch)
    if pitch_leap > max_pitch_leap:
        return None
    overlap_ms = max(0.0, previous.end_ms - current.start_ms)
    permitted_overlap = max(
        80.0, 0.35 * min(previous.duration_ms, current.duration_ms)
    )
    if overlap_ms > permitted_overlap:
        return None
    return (
        pitch_leap / 12.0
        + silence_ms / beat_ms
        + 1.5 * overlap_ms / max(1.0, permitted_overlap)
    )


def _voice_state_stats(state: _VoiceState, beat_ms: float) -> _GroupStats:
    records = tuple(state.records)
    candidate_ids = tuple(record.candidate_id for record in records)
    canonical = "\n".join(sorted(candidate_ids)).encode("utf-8")
    group_id = "voice-" + hashlib.sha256(canonical).hexdigest()[:20]
    pitches = [record.pitch for record in records]
    durations = [record.duration_ms for record in records]
    confidences = [record.confidence for record in records]
    leaps = [
        abs(current.pitch - previous.pitch)
        for previous, current in zip(records, records[1:])
    ]
    continuity = 1.0
    if leaps:
        continuity = max(
            0.6,
            1.0 - sum(max(0, leap - 7) for leap in leaps) / (36.0 * len(leaps)),
        )
    confidence = (sum(confidences) / len(confidences)) * continuity
    start_ms = records[0].start_ms
    end_ms = max(record.end_ms for record in records)
    span_beats = max(1.0, (end_ms - start_ms) / beat_ms)
    group = VoiceGroup(
        group_id,
        candidate_ids,
        start_ms,
        end_ms,
        "ornament",
        confidence,
    )
    return _GroupStats(
        group,
        float(median(pitches)),
        sum(durations) / len(durations),
        len(records) / span_beats,
    )


def _infer_group_roles(
    stats: Sequence[_GroupStats], beat_ms: float
) -> tuple[VoiceGroup, ...]:
    if not stats:
        return ()
    median_pitches = [item.median_pitch for item in stats]
    overall_median = float(median(median_pitches))
    top_register = max(median_pitches)
    bottom_register = min(median_pitches)
    result: list[VoiceGroup] = []
    for item in stats:
        role = "harmony"
        separated_bass = (
            len(stats) > 1
            and item.median_pitch == bottom_register
            and (
                item.median_pitch <= 52.0
                or item.median_pitch <= overall_median - 7.0
            )
        )
        if separated_bass:
            role = "bass"
        elif (
            item.notes_per_beat >= 2.5
            and item.average_duration_ms <= 0.45 * beat_ms
        ):
            role = "rhythm"
        elif (
            item.average_duration_ms >= 1.5 * beat_ms
            and item.median_pitch < top_register - 3.0
        ):
            role = "pad"
        elif item.median_pitch >= top_register - 3.0:
            role = "primary_melody"
        elif item.median_pitch >= top_register - 9.0:
            role = "secondary_melody"
        elif item.median_pitch > overall_median + 5.0:
            role = "ornament"
        result.append(replace(item.group, role=role))
    return tuple(result)


def _role_affinity(role: str, preferred_roles: frozenset[str]) -> float:
    if not preferred_roles:
        return 0.55
    if role in preferred_roles:
        return 1.0
    if role in _MELODIC_ROLES and preferred_roles.intersection(_MELODIC_ROLES):
        return 0.82
    if role in _SUSTAINED_ROLES and preferred_roles.intersection(_SUSTAINED_ROLES):
        return 0.78
    if role == "ornament" and preferred_roles.intersection(_MELODIC_ROLES):
        return 0.62
    if role == "rhythm" and "bass" in preferred_roles:
        return 0.45
    return 0.20


def _group_articulation(
    records: Sequence[_CandidateRecord], beat_ms: float
) -> str:
    average_duration = sum(item.duration_ms for item in records) / len(records)
    if average_duration <= 0.5 * beat_ms:
        return "short"
    if average_duration >= 1.25 * beat_ms:
        return "sustain"
    return "versatile"


def _articulation_affinity(group_profile: str, instrument_profile: str) -> float:
    if group_profile == instrument_profile:
        return 1.0
    if instrument_profile == "versatile":
        return 0.85
    if group_profile == "versatile":
        return 0.72
    return 0.35


def _timbre_similarity(
    left: TimbreFeatureProfile, right: TimbreFeatureProfile
) -> float:
    left_values = dict(zip(left.feature_names, left.values))
    right_values = dict(zip(right.feature_names, right.values))
    names = sorted(set(left_values).intersection(right_values))
    if not names:
        return 0.0
    squared_distance = 0.0
    for name in names:
        left_value = left_values[name]
        right_value = right_values[name]
        scale = max(1.0, abs(left_value), abs(right_value))
        distance = min(1.0, abs(left_value - right_value) / scale)
        squared_distance += distance * distance
    similarity = 1.0 - math.sqrt(squared_distance / len(names))
    reliability = min(left.reliability, right.reliability)
    return _clamp01(similarity * reliability)


def _combine_timbre_profiles(
    profiles: Sequence[TimbreFeatureProfile],
    *,
    cancelled: CancelCallback | None = None,
) -> TimbreFeatureProfile:
    _check_cancelled(cancelled)
    if not profiles:
        raise ValueError("at least one timbre profile is required")
    rows = [
        dict(zip(profile.feature_names, profile.values))
        for profile in profiles
    ]
    reliability = sum(profile.reliability for profile in profiles) / len(
        profiles
    )
    return build_timbre_feature_profile(
        rows,
        reliability=reliability,
        max_samples=len(rows),
        cancelled=cancelled,
    )


def _normalise_group_pitch_profiles(
    values: object,
) -> dict[str, dict[int, TimbreFeatureProfile]]:
    if not isinstance(values, Mapping):
        return {}
    result: dict[str, dict[int, TimbreFeatureProfile]] = {}
    for raw_group_id, raw_profiles in values.items():
        if not isinstance(raw_profiles, Mapping):
            continue
        profiles: dict[int, TimbreFeatureProfile] = {}
        for raw_pitch, profile in raw_profiles.items():
            try:
                pitch = int(raw_pitch)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                isinstance(profile, TimbreFeatureProfile)
                and 0 <= pitch <= 127
            ):
                profiles[pitch] = profile
        if profiles:
            result[str(raw_group_id)] = profiles
    return result


def _normalise_instrument_pitch_profiles(
    values: object,
) -> dict[int, dict[int, TimbreFeatureProfile]]:
    if not isinstance(values, Mapping):
        return {}
    result: dict[int, dict[int, TimbreFeatureProfile]] = {}
    for raw_instrument_id, raw_profiles in values.items():
        if not isinstance(raw_profiles, Mapping):
            continue
        try:
            instrument_id = int(raw_instrument_id)
        except (TypeError, ValueError, OverflowError):
            continue
        profiles: dict[int, TimbreFeatureProfile] = {}
        for raw_pitch, profile in raw_profiles.items():
            try:
                pitch = int(raw_pitch)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                isinstance(profile, TimbreFeatureProfile)
                and 0 <= pitch <= 127
            ):
                profiles[pitch] = profile
        if profiles:
            result[instrument_id] = profiles
    return result


def _pitch_aware_timbre_similarity(
    records: Sequence[_CandidateRecord],
    group_profiles: Mapping[int, TimbreFeatureProfile],
    instrument_profiles: Mapping[int, TimbreFeatureProfile],
    *,
    pitch_offset: int = 0,
    cancelled: CancelCallback | None = None,
) -> tuple[float | None, str]:
    """Compare source-pitch reference evidence to exported-pitch game evidence.

    Timbre shifts materially across a wide instrument range.  Treating a
    distant root sample as if it represented the requested pitch can dominate
    the locked 50% timbre channel, so the group lookup deliberately stays at
    the detected source pitch while the game profile lookup applies the global
    export offset. Sparse/non-matching evidence falls back to the visible
    ``no_local_evidence`` confidence cap.
    """

    if not group_profiles or not instrument_profiles:
        return None, "timbre:no_local_evidence"
    weights_by_pitch: dict[int, float] = {}
    for record in records:
        _check_cancelled(cancelled)
        weights_by_pitch[record.pitch] = (
            weights_by_pitch.get(record.pitch, 0.0)
            + max(0.05, record.confidence)
        )
    total_weight = sum(weights_by_pitch.values())
    matched_weight = 0.0
    weighted_similarity = 0.0
    exact_matches = 0
    for pitch in sorted(weights_by_pitch):
        _check_cancelled(cancelled)
        group_profile = group_profiles.get(pitch)
        if group_profile is None or group_profile.reliability < 0.35:
            continue
        instrument_profile = instrument_profiles.get(
            pitch + pitch_offset
        )
        if instrument_profile is None:
            continue
        if instrument_profile.reliability < 0.35:
            continue
        weight = weights_by_pitch[pitch]
        weighted_similarity += (
            weight
            * _timbre_similarity(group_profile, instrument_profile)
        )
        matched_weight += weight
        exact_matches += 1
    if matched_weight <= 0.0:
        return None, "timbre:no_local_evidence"
    evidence_coverage = matched_weight / max(1e-9, total_weight)
    if evidence_coverage < 0.50:
        return None, "timbre:insufficient_exact_pitch_evidence"
    score = (
        weighted_similarity
        / matched_weight
        * (0.75 + 0.25 * evidence_coverage)
    )
    reason = (
        f"timbre:pitch:{score:.3f}:"
        f"exact={exact_matches}:"
        f"coverage={evidence_coverage:.3f}"
    )
    return _clamp01(score), reason


def _sample_profile_cache_key(
    caller_key: str,
    profiles: Mapping[int, TimbreFeatureProfile],
    pitch_profiles: Mapping[
        int,
        Mapping[int, TimbreFeatureProfile],
    ],
    *,
    cancelled: CancelCallback | None = None,
) -> str:
    _check_cancelled(cancelled)
    if not profiles and not pitch_profiles:
        return "none"
    payload = {
        "caller_key_hash": hashlib.sha256(str(caller_key).encode("utf-8")).hexdigest(),
        "profiles": [
            (
                int(instrument_id),
                profile.profile_key,
                profile.feature_names,
                profile.values,
                profile.sample_count,
                profile.reliability,
            )
            for instrument_id, profile in sorted(profiles.items())
        ],
        "pitch_profiles": [
            (
                int(instrument_id),
                int(root_note),
                profile.profile_key,
                profile.feature_names,
                profile.values,
                profile.sample_count,
                profile.reliability,
            )
            for instrument_id, values in sorted(pitch_profiles.items())
            for root_note, profile in sorted(values.items())
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    _check_cancelled(cancelled)
    return hashlib.sha256(encoded).hexdigest()[:24]


def _analysis_cache_key(
    groups: Sequence[VoiceGroup],
    records: Sequence[_CandidateRecord],
    descriptors: Sequence[BdoInstrumentDescriptor],
    group_timbres: Mapping[str, TimbreFeatureProfile],
    instrument_timbres: Mapping[int, TimbreFeatureProfile],
    group_pitch_timbres: Mapping[
        str,
        Mapping[int, TimbreFeatureProfile],
    ],
    instrument_pitch_timbres: Mapping[
        int,
        Mapping[int, TimbreFeatureProfile],
    ],
    sample_profile_key: str,
    pitch_offset: int,
    beat_ms: float,
    top_k: int,
    *,
    cancelled: CancelCallback | None = None,
) -> str:
    _check_cancelled(cancelled)
    payload = {
        "version": INSTRUMENT_ANALYSIS_VERSION,
        "pitch_offset": pitch_offset,
        "beat_ms": beat_ms,
        "top_k": top_k,
        "sample_profile_key": sample_profile_key,
        "groups": [
            (
                item.group_id,
                item.candidate_ids,
                item.start_audio_ms,
                item.end_audio_ms,
                item.role,
                item.confidence,
            )
            for item in groups
        ],
        "candidates": [
            (
                item.candidate_id,
                item.pitch,
                item.start_ms,
                item.duration_ms,
                item.confidence,
            )
            for item in records
        ],
        "instruments": [
            (
                item.instrument_id,
                item.pitch_min,
                item.pitch_max,
                sorted(item.available_pitches),
                sorted(item.preferred_roles),
                item.articulation_profile,
                item.is_percussion,
                item.timbre_evidence_approved,
            )
            for item in descriptors
        ],
        "group_timbres": sorted(
            (key, value.profile_key, value.reliability)
            for key, value in group_timbres.items()
        ),
        "instrument_timbres": sorted(
            (key, value.profile_key, value.reliability)
            for key, value in instrument_timbres.items()
        ),
        "group_pitch_timbres": sorted(
            (
                group_id,
                int(pitch),
                profile.profile_key,
                profile.reliability,
            )
            for group_id, values in group_pitch_timbres.items()
            for pitch, profile in values.items()
        ),
        "instrument_pitch_timbres": sorted(
            (
                int(instrument_id),
                int(pitch),
                profile.profile_key,
                profile.reliability,
            )
            for instrument_id, values in instrument_pitch_timbres.items()
            for pitch, profile in values.items()
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    _check_cancelled(cancelled)
    return hashlib.sha256(encoded).hexdigest()[:24]


def _normalise_pitch_offset(value: object) -> int:
    """Return one bounded integral export transpose for deterministic matching."""

    if isinstance(value, bool):
        raise ValueError("pitch_offset must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("pitch_offset must be an integer") from exc
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("pitch_offset must be an integer") from exc
    if not math.isfinite(numeric) or numeric != result:
        raise ValueError("pitch_offset must be an integer")
    if not -127 <= result <= 127:
        raise ValueError("pitch_offset must be within -127..127")
    return result


def _clamp01(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("score/confidence must be finite")
    return max(0.0, min(1.0, number))


__all__ = [
    "BdoInstrumentDescriptor",
    "BdoInstrumentMatch",
    "CancelCallback",
    "CandidateLike",
    "DEFAULT_ONSET_TOLERANCE_MS",
    "DEFAULT_PHRASE_GAP_BEATS",
    "INSTRUMENT_ANALYSIS_VERSION",
    "InstrumentAnalysisCancelled",
    "InstrumentMatchAnalysis",
    "NO_TIMBRE_CONFIDENCE_CAP",
    "TimbreFeatureProfile",
    "VoiceGroup",
    "analyse_instrument_matches",
    "build_timbre_feature_profile",
    "group_transcription_candidates",
    "group_voice_candidates",
    "match_bdo_instruments",
    "normalize_track_role",
    "overlay_manual_voice_groups",
    "refine_voice_groups_by_timbre",
]
