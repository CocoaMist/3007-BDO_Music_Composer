"""Conservative timbre grouping for the music-reference candidate layer.

The result is deliberately a display-only sidecar.  It never changes a
``TranscriptionCandidate`` and it does not claim that an anonymous cluster is
an instrument identity.  Optional instrument events may add a generic label,
but only after they agree with the existing note candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Callable, Mapping, Sequence

from bdo_music_composer.transcription.bdo_transcription_instruments import (
    TimbreFeatureProfile,
    VoiceGroup,
)


CancelCallback = Callable[[], bool]

REFERENCE_TIMBRE_PALETTE = (
    "#4AA3DF",
    "#E58B3A",
    "#56B870",
    "#C86DD7",
    "#E15B64",
    "#45B8AC",
    "#D4A72C",
    "#7B8CE8",
    "#C57B57",
    "#67A9CF",
    "#9D79BC",
    "#7AA457",
)
UNKNOWN_TIMBRE_COLOR = "#7B8492"
MAX_REFERENCE_TIMBRE_GROUPS = len(REFERENCE_TIMBRE_PALETTE)
MIN_PROVISIONAL_PROFILE_RELIABILITY = 0.16
MIN_RELIABLE_PROFILE_RELIABILITY = 0.34
MIN_DISTINCT_PROVISIONAL_RELIABILITY = 0.24
MAX_DISTINCT_PROVISIONAL_SEEDS = 4
PROVISIONAL_DISTINCTNESS_SIMILARITY = 0.58
REFERENCE_TIMBRE_MERGE_SIMILARITY = 0.73
REFERENCE_TIMBRE_CONTINUITY_SIMILARITY = 0.64
REFERENCE_TIMBRE_CONTINUITY_GAP_MS = 1_500.0
PREDICTIVE_FRAGMENT_GAP_MS = 1_200.0
PREDICTIVE_FRAGMENT_PITCH_GAP = 7


class ReferenceTimbreCancelled(RuntimeError):
    """Raised at deterministic cancellation boundaries."""


@dataclass(frozen=True, slots=True)
class ReferenceInstrumentEvent:
    """One generic instrument-labelled note emitted by an optional backend."""

    pitch: int
    start_ms: float
    duration_ms: float
    family: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        pitch = int(self.pitch)
        start_ms = float(self.start_ms)
        duration_ms = float(self.duration_ms)
        confidence = float(self.confidence)
        family = str(self.family).strip().casefold()
        if not 0 <= pitch <= 127:
            raise ValueError("instrument-event pitch must be within 0..127")
        if (
            not math.isfinite(start_ms)
            or not math.isfinite(duration_ms)
            or start_ms < 0.0
            or duration_ms <= 0.0
        ):
            raise ValueError("instrument-event time range is invalid")
        if not family:
            raise ValueError("instrument-event family is required")
        object.__setattr__(self, "pitch", pitch)
        object.__setattr__(self, "start_ms", start_ms)
        object.__setattr__(self, "duration_ms", duration_ms)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))


@dataclass(frozen=True, slots=True)
class ReferenceTimbreGroup:
    """One anonymous timbre cluster projected onto candidate IDs."""

    group_id: str
    candidate_ids: tuple[str, ...]
    start_audio_ms: float
    end_audio_ms: float
    confidence: float
    color: str
    label_family: str = ""
    label_confidence: float = 0.0
    label_source: str = ""
    candidate_confidences: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceTimbreAnalysis:
    """Immutable display sidecar bound to one transcription cache key."""

    cache_key: str
    groups: tuple[ReferenceTimbreGroup, ...]
    profiled_candidate_count: int
    label_backend: str = ""
    label_status: str = "disabled"
    evidence_stage: str = "acoustic"

    @property
    def labelled_group_count(self) -> int:
        return sum(bool(group.label_family) for group in self.groups)


def build_reference_timbre_analysis(
    *,
    cache_key: str,
    candidates: Sequence[object],
    voice_groups: Sequence[VoiceGroup],
    group_profiles: Mapping[str, TimbreFeatureProfile],
    candidate_profiles: Mapping[str, TimbreFeatureProfile] | None = None,
    instrument_events: Sequence[ReferenceInstrumentEvent] = (),
    label_backend: str = "",
    label_status: str = "disabled",
    cancelled: CancelCallback | None = None,
) -> ReferenceTimbreAnalysis:
    """Cluster reliable voice prototypes and conservatively attach labels.

    Initial voices provide temporal and pitch continuity.  Timbre prototypes
    may merge those voices only when every cross-pair agrees (complete-link),
    preventing one ambiguous phrase from chaining unrelated instruments.
    A single quality-acceptable prototype may establish a low-confidence
    provisional colour. Sparse groups with at least one usable candidate
    profile may inherit a cluster when the best match is both strong and
    unambiguous. Evidence-free or ambiguous groups stay neutral.
    """

    _check_cancelled(cancelled)
    candidate_by_id = {
        str(getattr(item, "candidate_id", "") or ""): item
        for item in candidates
        if str(getattr(item, "candidate_id", "") or "")
    }
    usable = [
        group
        for group in voice_groups
        if (
            (profile := group_profiles.get(group.group_id)) is not None
            and profile.sample_count >= 1
            and profile.reliability >= MIN_PROVISIONAL_PROFILE_RELIABILITY
        )
    ]
    ranked_usable = sorted(
        usable,
        key=lambda group: (
            group_profiles[group.group_id].sample_count,
            group_profiles[group.group_id].reliability,
            len(group.candidate_ids),
            -group.start_audio_ms,
            group.group_id,
        ),
        reverse=True,
    )
    seeds = [
        group
        for group in ranked_usable
        if (
            group_profiles[group.group_id].sample_count >= 2
            and group_profiles[group.group_id].reliability
            >= MIN_RELIABLE_PROFILE_RELIABILITY
        )
    ]
    seed_ids = {group.group_id for group in seeds}
    provisional_count = 0
    for group in ranked_usable:
        if group.group_id in seed_ids:
            continue
        profile = group_profiles[group.group_id]
        if not seeds:
            seeds.append(group)
            seed_ids.add(group.group_id)
            provisional_count += 1
            continue
        if (
            provisional_count >= MAX_DISTINCT_PROVISIONAL_SEEDS
            or profile.reliability
            < MIN_DISTINCT_PROVISIONAL_RELIABILITY
        ):
            continue
        nearest = max(
            _profile_similarity(
                profile,
                group_profiles[seed.group_id],
            )
            for seed in seeds
        )
        if nearest < PROVISIONAL_DISTINCTNESS_SIMILARITY:
            seeds.append(group)
            seed_ids.add(group.group_id)
            provisional_count += 1

    clusters: list[list[VoiceGroup]] = [[group] for group in seeds]
    while True:
        _check_cancelled(cancelled)
        best: tuple[float, str, int, int] | None = None
        for left_index in range(len(clusters)):
            for right_index in range(left_index + 1, len(clusters)):
                score = min(
                    _profile_similarity(
                        group_profiles[left.group_id],
                        group_profiles[right.group_id],
                    )
                    for left in clusters[left_index]
                    for right in clusters[right_index]
                )
                continuity = _clusters_have_temporal_continuity(
                    clusters[left_index],
                    clusters[right_index],
                )
                minimum_similarity = (
                    REFERENCE_TIMBRE_CONTINUITY_SIMILARITY
                    if continuity
                    else REFERENCE_TIMBRE_MERGE_SIMILARITY
                )
                if score < minimum_similarity:
                    continue
                tie_key = "|".join(
                    sorted(
                        group.group_id
                        for group in (
                            *clusters[left_index],
                            *clusters[right_index],
                        )
                    )
                )
                proposal = (score, tie_key, left_index, right_index)
                if best is None or proposal[:2] > best[:2]:
                    best = proposal
        if best is None:
            break
        _score, _key, left_index, right_index = best
        clusters[left_index] = sorted(
            (*clusters[left_index], *clusters[right_index]),
            key=lambda group: (
                group.start_audio_ms,
                group.end_audio_ms,
                group.group_id,
            ),
        )
        del clusters[right_index]

    # A reference overlay is a small review aid, not a clustering workbench.
    # Keep only the strongest bounded set and leave weaker prototypes neutral.
    clusters = sorted(
        clusters,
        key=lambda cluster: (
            sum(len(group.candidate_ids) for group in cluster),
            sum(
                group_profiles[group.group_id].sample_count
                for group in cluster
            ),
            sum(
                group_profiles[group.group_id].reliability
                for group in cluster
            ),
            -min(group.start_audio_ms for group in cluster),
            min(group.group_id for group in cluster),
        ),
        reverse=True,
    )[:MAX_REFERENCE_TIMBRE_GROUPS]

    core_group_ids = {
        group.group_id for cluster in clusters for group in cluster
    }
    candidate_profile_map = {
        str(candidate_id): profile
        for candidate_id, profile in (candidate_profiles or {}).items()
        if isinstance(profile, TimbreFeatureProfile)
    }
    propagated: list[dict[str, float]] = [
        {} for _cluster in clusters
    ]
    for group in sorted(
        voice_groups,
        key=lambda item: (
            item.start_audio_ms,
            item.end_audio_ms,
            item.group_id,
        ),
    ):
        _check_cancelled(cancelled)
        if group.group_id in core_group_ids:
            continue
        member_ids = tuple(
            candidate_id
            for candidate_id in group.candidate_ids
            if candidate_id in candidate_by_id
        )
        group_profile = group_profiles.get(group.group_id)
        candidate_evidence_profiles = tuple(
            candidate_profile_map[candidate_id]
            for candidate_id in member_ids
            if candidate_id in candidate_profile_map
        )
        evidence_profiles = tuple(
            profile
            for profile in (group_profile, *candidate_evidence_profiles)
            if profile is not None
        )
        if not member_ids or not evidence_profiles or not clusters:
            continue
        scored: list[tuple[float, int]] = []
        for cluster_index, cluster in enumerate(clusters):
            prototype_profiles = tuple(
                group_profiles[item.group_id] for item in cluster
            )
            evidence_scores = tuple(
                max(
                    _profile_similarity(profile, prototype)
                    for prototype in prototype_profiles
                )
                for profile in evidence_profiles
            )
            if group_profile is not None:
                primary_score = evidence_scores[0]
                secondary_scores = evidence_scores[1:]
                score = (
                    primary_score
                    if not secondary_scores
                    else (
                        0.75 * primary_score
                        + 0.25
                        * (sum(secondary_scores) / len(secondary_scores))
                    )
                )
            else:
                score = sum(evidence_scores) / len(evidence_scores)
            scored.append((score, cluster_index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, best_index = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        reliability = sum(
            profile.reliability for profile in evidence_profiles
        ) / len(evidence_profiles)
        confidence = best_score * (
            0.65 + 0.35 * math.sqrt(max(0.0, reliability))
        )
        if (
            best_score < 0.60
            or best_score - runner_up < 0.04
            or confidence < 0.42
        ):
            continue
        prototypes = tuple(
            group_profiles[item.group_id] for item in clusters[best_index]
        )
        for candidate_id in member_ids:
            profile = candidate_profile_map.get(candidate_id)
            candidate_confidence = confidence * 0.72
            if profile is not None:
                candidate_score = max(
                    _profile_similarity(profile, prototype)
                    for prototype in prototypes
                )
                candidate_confidence = min(
                    confidence,
                    candidate_score
                    * (
                        0.65
                        + 0.35
                        * math.sqrt(max(0.0, profile.reliability))
                    ),
                )
            propagated[best_index][candidate_id] = max(
                0.0,
                min(1.0, candidate_confidence),
            )

    label_votes = _candidate_label_votes(
        candidates,
        instrument_events,
        cancelled=cancelled,
    )
    used_colors: set[str] = set()
    output: list[ReferenceTimbreGroup] = []
    assigned_ids: set[str] = set()
    ordered_clusters = sorted(
        enumerate(clusters),
        key=lambda item: _cluster_sort_key(item[1]),
    )
    for cluster_index, cluster in ordered_clusters:
        _check_cancelled(cancelled)
        core_member_ids = tuple(
            dict.fromkeys(
                candidate_id
                for group in cluster
                for candidate_id in group.candidate_ids
                if candidate_id in candidate_by_id
            )
        )
        propagated_confidences = propagated[cluster_index]
        member_ids = tuple(
            dict.fromkeys((*core_member_ids, *propagated_confidences))
        )
        if not member_ids:
            continue
        assigned_ids.update(member_ids)
        profiles = [group_profiles[group.group_id] for group in cluster]
        cohesion = min(
            (
                _profile_similarity(left, right)
                for index, left in enumerate(profiles)
                for right in profiles[index + 1 :]
            ),
            default=1.0,
        )
        reliability = sum(profile.reliability for profile in profiles) / len(
            profiles
        )
        core_confidence = max(
            0.0,
            min(1.0, reliability * cohesion),
        )
        candidate_confidences = {
            candidate_id: core_confidence
            for candidate_id in core_member_ids
        }
        candidate_confidences.update(propagated_confidences)
        confidence = sum(candidate_confidences.values()) / max(
            1,
            len(candidate_confidences),
        )
        color = _stable_cluster_color(profiles, used_colors)
        used_colors.add(color)
        family, label_confidence = _group_label(member_ids, label_votes)
        canonical = "\n".join(sorted(member_ids)).encode("utf-8")
        output.append(
            ReferenceTimbreGroup(
                "timbre-" + hashlib.sha256(canonical).hexdigest()[:20],
                member_ids,
                min(
                    float(getattr(candidate_by_id[item], "start_ms", 0.0))
                    for item in member_ids
                ),
                max(
                    float(getattr(candidate_by_id[item], "start_ms", 0.0))
                    + float(
                        getattr(candidate_by_id[item], "duration_ms", 0.0)
                    )
                    for item in member_ids
                ),
                confidence,
                color,
                family,
                label_confidence,
                label_backend if family else "",
                tuple(sorted(candidate_confidences.items())),
            )
        )

    unknown_ids = tuple(
        candidate_id
        for candidate_id in candidate_by_id
        if candidate_id not in assigned_ids
    )
    if unknown_ids:
        starts = [
            float(getattr(candidate_by_id[item], "start_ms", 0.0))
            for item in unknown_ids
        ]
        ends = [
            float(getattr(candidate_by_id[item], "start_ms", 0.0))
            + float(getattr(candidate_by_id[item], "duration_ms", 0.0))
            for item in unknown_ids
        ]
        output.append(
            ReferenceTimbreGroup(
                "timbre-unknown",
                unknown_ids,
                min(starts, default=0.0),
                max(ends, default=0.0),
                0.0,
                UNKNOWN_TIMBRE_COLOR,
                candidate_confidences=tuple(
                    (candidate_id, 0.0) for candidate_id in unknown_ids
                ),
            )
        )
    output.sort(
        key=lambda group: (
            group.group_id == "timbre-unknown",
            group.start_audio_ms,
            group.group_id,
        )
    )
    return ReferenceTimbreAnalysis(
        str(cache_key),
        tuple(output),
        len(assigned_ids),
        str(label_backend),
        str(label_status),
    )


def build_reference_timbre_prediction(
    *,
    cache_key: str,
    candidates: Sequence[object],
    voice_groups: Sequence[VoiceGroup],
    cancelled: CancelCallback | None = None,
) -> ReferenceTimbreAnalysis:
    """Provide an explicitly provisional colour prediction before audio profiling.

    Time/pitch continuity can suggest source ownership from one short phrase,
    but it cannot establish an instrument identity.  The bounded prediction is
    therefore lower-confidence, covers every candidate, and is replaced by the
    acoustic analysis as soon as that worker completes.
    """

    _check_cancelled(cancelled)
    candidate_by_id = {
        str(getattr(item, "candidate_id", "") or ""): item
        for item in candidates
        if str(getattr(item, "candidate_id", "") or "")
    }
    structural_clusters = _predictive_voice_clusters(
        voice_groups,
        candidate_by_id,
    )
    ranked_clusters = sorted(
        structural_clusters,
        key=lambda cluster: (
            len(
                {
                    str(candidate_id)
                    for group in cluster
                    for candidate_id in group.candidate_ids
                    if str(candidate_id) in candidate_by_id
                }
            ),
            sum(float(group.confidence) for group in cluster) / len(cluster),
            -min(float(group.start_audio_ms) for group in cluster),
            min(str(group.group_id) for group in cluster),
        ),
        reverse=True,
    )[:MAX_REFERENCE_TIMBRE_GROUPS]
    output: list[ReferenceTimbreGroup] = []
    assigned_ids: set[str] = set()
    used_colors: set[str] = set()
    for cluster in sorted(
        ranked_clusters,
        key=lambda items: (
            min(float(item.start_audio_ms) for item in items),
            min(float(item.end_audio_ms) for item in items),
            min(str(item.group_id) for item in items),
        ),
    ):
        _check_cancelled(cancelled)
        member_ids = tuple(
            dict.fromkeys(
                str(candidate_id)
                for group in cluster
                for candidate_id in group.candidate_ids
                if str(candidate_id) in candidate_by_id
                and str(candidate_id) not in assigned_ids
            )
        )
        if not member_ids:
            continue
        support = min(1.0, math.sqrt(len(member_ids) / 4.0))
        group_confidence = sum(
            float(group.confidence)
            * max(1, len(tuple(group.candidate_ids)))
            for group in cluster
        ) / sum(max(1, len(tuple(group.candidate_ids))) for group in cluster)
        confidence = min(
            0.58,
            (0.18 + 0.40 * group_confidence)
            * (0.72 + 0.28 * support),
        )
        candidate_confidences = tuple(
            (
                candidate_id,
                min(
                    confidence,
                    confidence
                    * (
                        0.62
                        + 0.38
                        * max(
                            0.0,
                            min(
                                1.0,
                                float(
                                    getattr(
                                        candidate_by_id[candidate_id],
                                        "confidence",
                                        0.0,
                                    )
                                ),
                            ),
                        )
                    ),
                ),
            )
            for candidate_id in member_ids
        )
        group_id = (
            str(cluster[0].group_id)
            if len(cluster) == 1
            else "voice-"
            + hashlib.sha256(
                "\n".join(sorted(member_ids)).encode("utf-8")
            ).hexdigest()[:20]
        )
        color = _stable_prediction_color(group_id, used_colors)
        used_colors.add(color)
        output.append(
            ReferenceTimbreGroup(
                group_id,
                member_ids,
                min(
                    float(getattr(candidate_by_id[item], "start_ms", 0.0))
                    for item in member_ids
                ),
                max(
                    float(getattr(candidate_by_id[item], "start_ms", 0.0))
                    + float(
                        getattr(candidate_by_id[item], "duration_ms", 0.0)
                    )
                    for item in member_ids
                ),
                confidence,
                color,
                candidate_confidences=candidate_confidences,
            )
        )
        assigned_ids.update(member_ids)

    unknown_ids = tuple(
        candidate_id
        for candidate_id in candidate_by_id
        if candidate_id not in assigned_ids
    )
    if unknown_ids:
        output.append(
            ReferenceTimbreGroup(
                "timbre-unknown",
                unknown_ids,
                min(
                    float(getattr(candidate_by_id[item], "start_ms", 0.0))
                    for item in unknown_ids
                ),
                max(
                    float(getattr(candidate_by_id[item], "start_ms", 0.0))
                    + float(
                        getattr(candidate_by_id[item], "duration_ms", 0.0)
                    )
                    for item in unknown_ids
                ),
                0.0,
                UNKNOWN_TIMBRE_COLOR,
                candidate_confidences=tuple(
                    (candidate_id, 0.0) for candidate_id in unknown_ids
                ),
            )
        )
    return ReferenceTimbreAnalysis(
        str(cache_key),
        tuple(output),
        0,
        evidence_stage="predictive",
    )


def _predictive_voice_clusters(
    voice_groups: Sequence[VoiceGroup],
    candidate_by_id: Mapping[str, object],
) -> tuple[tuple[VoiceGroup, ...], ...]:
    """Join only adjacent, non-overlapping fragments of one likely voice.

    Voice extraction may split a continuous phrase at breaths or weak onsets.
    Treating every split as another instrument causes avoidable colour churn.
    Role, time, and pitch must all agree; simultaneous groups stay separate.
    """

    ordered = sorted(
        voice_groups,
        key=lambda group: (
            float(group.start_audio_ms),
            float(group.end_audio_ms),
            str(group.group_id),
        ),
    )
    clusters: list[list[VoiceGroup]] = []
    for group in ordered:
        if (
            clusters
            and _predictive_fragments_are_continuous(
                clusters[-1][-1],
                group,
                candidate_by_id,
            )
        ):
            clusters[-1].append(group)
        else:
            clusters.append([group])
    return tuple(tuple(cluster) for cluster in clusters)


def _predictive_fragments_are_continuous(
    left: VoiceGroup,
    right: VoiceGroup,
    candidate_by_id: Mapping[str, object],
) -> bool:
    if str(left.role) != str(right.role):
        return False
    gap_ms = float(right.start_audio_ms) - float(left.end_audio_ms)
    if gap_ms < 0.0 or gap_ms > PREDICTIVE_FRAGMENT_GAP_MS:
        return False
    left_pitches = sorted(
        int(getattr(candidate_by_id[candidate_id], "pitch", -1))
        for candidate_id in left.candidate_ids
        if candidate_id in candidate_by_id
    )
    right_pitches = sorted(
        int(getattr(candidate_by_id[candidate_id], "pitch", -1))
        for candidate_id in right.candidate_ids
        if candidate_id in candidate_by_id
    )
    if not left_pitches or not right_pitches:
        return False
    return (
        min(
            abs(left_pitch - right_pitch)
            for left_pitch in left_pitches
            for right_pitch in right_pitches
        )
        <= PREDICTIVE_FRAGMENT_PITCH_GAP
    )


def _stable_prediction_color(group_id: str, used_colors: set[str]) -> str:
    start = int.from_bytes(
        hashlib.sha256(str(group_id).encode("utf-8")).digest()[:2],
        "little",
    ) % len(REFERENCE_TIMBRE_PALETTE)
    for offset in range(len(REFERENCE_TIMBRE_PALETTE)):
        color = REFERENCE_TIMBRE_PALETTE[
            (start + offset) % len(REFERENCE_TIMBRE_PALETTE)
        ]
        if color not in used_colors:
            return color
    return REFERENCE_TIMBRE_PALETTE[start]


def merge_reference_timbre_evidence(
    acoustic: ReferenceTimbreAnalysis,
    prediction: ReferenceTimbreAnalysis | None,
) -> ReferenceTimbreAnalysis:
    """Keep acoustic groups authoritative and predict only their unknowns.

    Melody guidance must still be able to vote for candidates whose acoustic
    profile is under-evidenced.  Replacing the structural projection wholesale
    with an acoustic ``unknown`` group made that vote disappear as soon as the
    background worker completed.  This hybrid sidecar retains verified groups
    and fills only their uncovered candidate IDs with explicitly provisional
    structural groups.
    """

    if (
        prediction is None
        or prediction.cache_key != acoustic.cache_key
        or prediction.evidence_stage != "predictive"
    ):
        return acoustic

    acoustic_groups = tuple(acoustic.groups)
    verified = [
        group
        for group in acoustic_groups
        if group.group_id != "timbre-unknown"
    ]
    assigned = {
        candidate_id
        for group in verified
        for candidate_id in group.candidate_ids
    }
    used_group_ids = {group.group_id for group in verified}
    used_colors = {group.color for group in verified}
    supplements: list[ReferenceTimbreGroup] = []
    for group in prediction.groups:
        if group.group_id == "timbre-unknown":
            continue
        remaining_ids = tuple(
            candidate_id
            for candidate_id in group.candidate_ids
            if candidate_id not in assigned
        )
        if not remaining_ids:
            continue
        group_id = str(group.group_id)
        if group_id in used_group_ids:
            group_id = f"predictive-{group_id}"
        color = str(group.color)
        if color in used_colors:
            color = _stable_prediction_color(group_id, used_colors)
        confidence_by_id = dict(group.candidate_confidences)
        supplements.append(
            ReferenceTimbreGroup(
                group_id,
                remaining_ids,
                group.start_audio_ms,
                group.end_audio_ms,
                min(0.58, group.confidence),
                color,
                candidate_confidences=tuple(
                    (
                        candidate_id,
                        min(
                            0.58,
                            max(
                                0.0,
                                float(
                                    confidence_by_id.get(
                                        candidate_id,
                                        group.confidence,
                                    )
                                ),
                            ),
                        ),
                    )
                    for candidate_id in remaining_ids
                ),
            )
        )
        assigned.update(remaining_ids)
        used_group_ids.add(group_id)
        used_colors.add(color)

    all_ids = {
        candidate_id
        for analysis in (acoustic, prediction)
        for group in analysis.groups
        for candidate_id in group.candidate_ids
    }
    unknown_ids = tuple(sorted(all_ids.difference(assigned)))
    output = [*verified, *supplements]
    if unknown_ids:
        unknown_sources = tuple(
            group
            for analysis in (acoustic, prediction)
            for group in analysis.groups
            if set(group.candidate_ids).intersection(unknown_ids)
        )
        output.append(
            ReferenceTimbreGroup(
                "timbre-unknown",
                unknown_ids,
                min(
                    (group.start_audio_ms for group in unknown_sources),
                    default=0.0,
                ),
                max(
                    (group.end_audio_ms for group in unknown_sources),
                    default=0.0,
                ),
                0.0,
                UNKNOWN_TIMBRE_COLOR,
                candidate_confidences=tuple(
                    (candidate_id, 0.0) for candidate_id in unknown_ids
                ),
            )
        )
    output.sort(
        key=lambda group: (
            group.group_id == "timbre-unknown",
            group.start_audio_ms,
            group.group_id,
        )
    )
    return ReferenceTimbreAnalysis(
        acoustic.cache_key,
        tuple(output),
        acoustic.profiled_candidate_count,
        acoustic.label_backend,
        acoustic.label_status,
        "hybrid" if supplements else "acoustic",
    )


def _profile_similarity(
    left: TimbreFeatureProfile,
    right: TimbreFeatureProfile,
) -> float:
    left_values = dict(zip(left.feature_names, left.values))
    right_values = dict(zip(right.feature_names, right.values))
    names = sorted(set(left_values).intersection(right_values))
    if not names:
        return 0.0
    distances = []
    for name in names:
        left_value = float(left_values[name])
        right_value = float(right_values[name])
        scale = max(1.0, abs(left_value), abs(right_value))
        distances.append(min(1.0, abs(left_value - right_value) / scale) ** 2)
    raw = 1.0 - math.sqrt(sum(distances) / len(distances))
    reliability = math.sqrt(min(left.reliability, right.reliability))
    return max(0.0, min(1.0, raw * (0.70 + 0.30 * reliability)))


def _clusters_have_temporal_continuity(
    left: Sequence[VoiceGroup],
    right: Sequence[VoiceGroup],
) -> bool:
    """Return whether two moderately similar clusters touch in one role."""

    for left_group in left:
        for right_group in right:
            if left_group.role != right_group.role:
                continue
            if left_group.end_audio_ms < right_group.start_audio_ms:
                gap_ms = right_group.start_audio_ms - left_group.end_audio_ms
            elif right_group.end_audio_ms < left_group.start_audio_ms:
                gap_ms = left_group.start_audio_ms - right_group.end_audio_ms
            else:
                gap_ms = 0.0
            if gap_ms <= REFERENCE_TIMBRE_CONTINUITY_GAP_MS:
                return True
    return False


def _stable_cluster_color(
    profiles: Sequence[TimbreFeatureProfile],
    used_colors: set[str],
) -> str:
    signature = "|".join(sorted(profile.profile_key for profile in profiles))
    start = int(hashlib.sha256(signature.encode("ascii")).hexdigest()[:8], 16)
    for offset in range(len(REFERENCE_TIMBRE_PALETTE)):
        color = REFERENCE_TIMBRE_PALETTE[
            (start + offset) % len(REFERENCE_TIMBRE_PALETTE)
        ]
        if color not in used_colors:
            return color
    return REFERENCE_TIMBRE_PALETTE[start % len(REFERENCE_TIMBRE_PALETTE)]


def _cluster_sort_key(cluster: Sequence[VoiceGroup]) -> tuple[float, float, str]:
    return (
        min(group.start_audio_ms for group in cluster),
        min(group.end_audio_ms for group in cluster),
        min(group.group_id for group in cluster),
    )


def _candidate_label_votes(
    candidates: Sequence[object],
    events: Sequence[ReferenceInstrumentEvent],
    *,
    cancelled: CancelCallback | None = None,
) -> dict[str, tuple[str, float]]:
    by_pitch: dict[int, list[ReferenceInstrumentEvent]] = {}
    for event in events:
        by_pitch.setdefault(int(event.pitch), []).append(event)
    for values in by_pitch.values():
        values.sort(key=lambda event: (event.start_ms, event.family))
    votes: dict[str, tuple[str, float]] = {}
    for candidate in candidates:
        _check_cancelled(cancelled)
        candidate_id = str(getattr(candidate, "candidate_id", "") or "")
        if not candidate_id:
            continue
        start_ms = float(getattr(candidate, "start_ms", 0.0))
        duration_ms = max(1.0, float(getattr(candidate, "duration_ms", 0.0)))
        end_ms = start_ms + duration_ms
        pitch = int(getattr(candidate, "pitch", -1))
        proposals: list[tuple[float, str]] = []
        # Exact pitch is authoritative.  A one-semitone fallback is useful for
        # octave/pitch-head disagreement, but only when there is no usable
        # exact event and receives a substantial penalty.
        for pitch_delta, pitch_penalty in ((0, 1.0), (-1, 0.58), (1, 0.58)):
            local: list[tuple[float, str]] = []
            for event in by_pitch.get(pitch + pitch_delta, ()):
                if event.start_ms > end_ms + 120.0:
                    break
                event_end = event.start_ms + event.duration_ms
                overlap = max(
                    0.0,
                    min(end_ms, event_end) - max(start_ms, event.start_ms),
                )
                union = max(end_ms, event_end) - min(start_ms, event.start_ms)
                overlap_ratio = overlap / max(1.0, union)
                onset_score = max(
                    0.0, 1.0 - abs(start_ms - event.start_ms) / 160.0
                )
                score = (
                    event.confidence
                    * pitch_penalty
                    * (0.64 * onset_score + 0.36 * overlap_ratio)
                )
                if score >= (0.42 if pitch_delta == 0 else 0.48):
                    local.append((score, event.family))
            if pitch_delta == 0 and local:
                proposals = local
                break
            proposals.extend(local)
        proposals.sort(key=lambda item: (-item[0], item[1]))
        if proposals:
            best_score, best_family = proposals[0]
            competing = max(
                (
                    score
                    for score, family in proposals[1:]
                    if family != best_family
                ),
                default=0.0,
            )
            if best_score - competing >= 0.10:
                votes[candidate_id] = (best_family, best_score)
    return votes


def _group_label(
    candidate_ids: Sequence[str],
    votes: Mapping[str, tuple[str, float]],
) -> tuple[str, float]:
    totals: dict[str, float] = {}
    matched = 0
    for candidate_id in candidate_ids:
        vote = votes.get(candidate_id)
        if vote is None:
            continue
        family, confidence = vote
        totals[family] = totals.get(family, 0.0) + confidence
        matched += 1
    if not totals:
        return "", 0.0
    family, winning = max(totals.items(), key=lambda item: (item[1], item[0]))
    coverage = matched / max(1, len(candidate_ids))
    dominance = winning / max(1e-9, sum(totals.values()))
    mean_alignment = min(1.0, winning / max(1, matched))
    support = min(1.0, matched / 2.0)
    # Coverage is calibration evidence, not a linear punishment: a long group
    # can contain many unlabelled candidates while its labelled windows still
    # agree strongly.  Support shrinkage prevents one event from overclaiming.
    confidence = (
        mean_alignment
        * dominance
        * (0.55 + 0.45 * math.sqrt(coverage))
        * support
    )
    if matched < 2 or coverage < 0.24 or dominance < 0.62 or confidence < 0.30:
        return "", 0.0
    return family, max(0.0, min(1.0, confidence))


def _check_cancelled(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise ReferenceTimbreCancelled("reference timbre analysis cancelled")


__all__ = [
    "MAX_REFERENCE_TIMBRE_GROUPS",
    "MIN_PROVISIONAL_PROFILE_RELIABILITY",
    "REFERENCE_TIMBRE_PALETTE",
    "UNKNOWN_TIMBRE_COLOR",
    "ReferenceInstrumentEvent",
    "ReferenceTimbreAnalysis",
    "ReferenceTimbreCancelled",
    "ReferenceTimbreGroup",
    "build_reference_timbre_analysis",
    "build_reference_timbre_prediction",
    "merge_reference_timbre_evidence",
]
