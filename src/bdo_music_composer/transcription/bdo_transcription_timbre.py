"""Local-only BDO sample timbre feature extraction and cache.

This module is intentionally Qt-free.  :func:`load_or_build_timbre_profile_index`
opens and decodes audio files and **must only be called from a background
worker**.  It must never run from a paint event or the real-time audio callback.

Paths are transient implementation details: neither the returned index nor its
cache manifest contains the sample-map path, the audio-root path, or individual
sample paths.  The persisted identity is derived from content hashes.  Public
worker entry points accept an optional cooperative ``cancelled`` callback and
raise :class:`TimbreAnalysisCancelled` at file/decode/feature boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import json
import math
import os
from pathlib import Path, PurePath
import re
from typing import Callable, Mapping, Sequence

from bdo_music_composer.transcription.bdo_transcription_instruments import (
    CandidateLike,
    InstrumentAnalysisCancelled,
    TimbreFeatureProfile,
    VoiceGroup,
    build_timbre_feature_profile,
)


TIMBRE_FEATURE_VERSION = "bdo-local-timbre-v1"
TIMBRE_PITCH_PROFILE_VERSION = "bdo-local-pitch-profile-v1"
TIMBRE_CACHE_FORMAT = 1
MAX_SAMPLES_PER_INSTRUMENT = 32
PROFILE_INDEX_MEMORY_LIMIT = 16 * 1024 * 1024
MAX_CACHE_MANIFEST_BYTES = 16 * 1024 * 1024
ANALYSIS_SAMPLE_RATE = 22_050
ANALYSIS_MAX_DURATION_SECONDS = 8.0
MARNIAN_INSTRUMENT_IDS = frozenset({0x14, 0x18, 0x1C, 0x20})
MARNIAN_TIMBRE_RELIABILITY_CAP = 0.34
MAX_GROUP_SEGMENTS = 8
GROUP_ONSET_TOLERANCE_MS = 35.0
DEFAULT_MIN_TARGET_PITCH_RATIO = 0.08

_REGULAR_BANK_RE = re.compile(r"^midi_instrument_(\d{1,3})_[a-z0-9_]+$")
_SAFE_BANK_RE = re.compile(r"^[A-Za-z0-9_]+$")
_HEX_KEY_RE = re.compile(r"^[0-9a-f]{24,64}$")
_MARNIAN_BANK_IDS = {
    "saw": 0x14,
    "sine": 0x18,
    "square": 0x1C,
    "triangle": 0x20,
}
_EXTRACTION_FEATURE_NAMES = tuple(
    [f"mfcc_{index:02d}" for index in range(1, 14)]
    + [f"spectral_contrast_{index:02d}" for index in range(7)]
    + [
        "spectral_centroid_hz",
        "spectral_rolloff_85_hz",
        "spectral_flatness",
        "attack_ms",
        "decay_ms",
    ]
)
_FEATURE_NAMES = tuple(sorted(_EXTRACTION_FEATURE_NAMES))


class TimbreProfileError(ValueError):
    """Raised when a sample map or profile cache cannot be trusted."""


CancelCallback = Callable[[], bool]


class TimbreAnalysisCancelled(InstrumentAnalysisCancelled):
    """Raised when local timbre decoding or feature analysis is cancelled."""


def _check_cancelled(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise TimbreAnalysisCancelled("timbre analysis cancelled")


class PitchAwareProfileMap(dict):
    """Profile mapping with bounded per-pitch and per-segment evidence."""

    def __init__(
        self,
        profiles: Mapping[object, TimbreFeatureProfile],
        pitch_profiles: Mapping[
            object,
            Mapping[int, TimbreFeatureProfile],
        ],
        candidate_profiles: Mapping[
            str,
            TimbreFeatureProfile,
        ] | None = None,
    ) -> None:
        super().__init__(profiles)
        self.pitch_profiles = {
            key: {
                int(pitch): profile
                for pitch, profile in sorted(
                    values.items(),
                    key=lambda item: int(item[0]),
                )
            }
            for key, values in pitch_profiles.items()
        }
        self.candidate_profiles = {
            str(candidate_id): profile
            for candidate_id, profile in sorted(
                (candidate_profiles or {}).items(),
                key=lambda item: str(item[0]),
            )
            if isinstance(profile, TimbreFeatureProfile)
        }


@dataclass(frozen=True, slots=True)
class FramePitchEvidence:
    """In-memory, frame-aligned pitch evidence for contamination checks.

    ``values`` must be shaped ``(frame_count, pitch_bins)`` and ``times_ms``
    must contain the corresponding original-audio times.  The value may wrap a
    validated numpy memmap owned by the caller, but this module never persists
    it or derives a filesystem path from it.
    """

    times_ms: object
    values: object
    midi_min: int = 21
    bins_per_semitone: int = 1


@dataclass(frozen=True, slots=True)
class TimbreProfileIndex:
    """Bounded, path-free instrument profile index suitable for matching."""

    cache_key: str
    profiles: tuple[tuple[int, TimbreFeatureProfile], ...]
    estimated_size_bytes: int
    skipped_sample_count: int = 0
    cache_hit: bool = False
    pitch_profiles: tuple[
        tuple[int, int, TimbreFeatureProfile],
        ...,
    ] = ()

    def __post_init__(self) -> None:
        if not _HEX_KEY_RE.fullmatch(str(self.cache_key)):
            raise TimbreProfileError("invalid timbre profile cache key")
        ordered = tuple(sorted(self.profiles, key=lambda item: int(item[0])))
        if ordered != self.profiles:
            raise TimbreProfileError("instrument profiles must be sorted")
        ids = tuple(int(item[0]) for item in ordered)
        if len(ids) != len(set(ids)):
            raise TimbreProfileError("duplicate instrument profile")
        if any(instrument_id < 0 or instrument_id > 255 for instrument_id in ids):
            raise TimbreProfileError("invalid instrument id")
        ordered_pitch_profiles = tuple(
            sorted(
                self.pitch_profiles,
                key=lambda item: (int(item[0]), int(item[1])),
            )
        )
        if ordered_pitch_profiles != self.pitch_profiles:
            raise TimbreProfileError("pitch profiles must be sorted")
        pitch_keys = tuple(
            (int(instrument_id), int(root_note))
            for instrument_id, root_note, _profile in ordered_pitch_profiles
        )
        if len(pitch_keys) != len(set(pitch_keys)):
            raise TimbreProfileError("duplicate instrument pitch profile")
        if any(
            instrument_id < 0
            or instrument_id > 255
            or root_note < 0
            or root_note > 127
            or instrument_id not in ids
            for instrument_id, root_note in pitch_keys
        ):
            raise TimbreProfileError("invalid instrument pitch profile")
        pitch_profile_counts: dict[int, int] = {}
        pitch_sample_counts: dict[int, int] = {}
        for instrument_id, _root_note, profile in ordered_pitch_profiles:
            pitch_profile_counts[instrument_id] = (
                pitch_profile_counts.get(instrument_id, 0) + 1
            )
            pitch_sample_counts[instrument_id] = (
                pitch_sample_counts.get(instrument_id, 0)
                + profile.sample_count
            )
        if any(
            count > MAX_SAMPLES_PER_INSTRUMENT
            for count in pitch_profile_counts.values()
        ) or any(
            count > MAX_SAMPLES_PER_INSTRUMENT
            for count in pitch_sample_counts.values()
        ):
            raise TimbreProfileError(
                "instrument pitch profiles exceed sample limit"
            )
        measured = estimate_profile_index_bytes(
            ordered,
            ordered_pitch_profiles,
        )
        if int(self.estimated_size_bytes) != measured:
            raise TimbreProfileError("incorrect profile index size estimate")
        if measured > PROFILE_INDEX_MEMORY_LIMIT:
            raise TimbreProfileError("timbre profile index exceeds memory limit")
        if int(self.skipped_sample_count) < 0:
            raise TimbreProfileError("invalid skipped sample count")
        object.__setattr__(self, "estimated_size_bytes", measured)
        object.__setattr__(self, "skipped_sample_count", int(self.skipped_sample_count))
        object.__setattr__(self, "cache_hit", bool(self.cache_hit))
        object.__setattr__(self, "pitch_profiles", ordered_pitch_profiles)

    @property
    def sample_profile_key(self) -> str:
        return self.cache_key

    def as_mapping(self) -> PitchAwareProfileMap:
        nested: dict[int, dict[int, TimbreFeatureProfile]] = {}
        for instrument_id, root_note, profile in self.pitch_profiles:
            nested.setdefault(instrument_id, {})[root_note] = profile
        return PitchAwareProfileMap(
            {
                instrument_id: profile
                for instrument_id, profile in self.profiles
            },
            nested,
        )

    def profile_for_instrument(
        self, instrument_id: int
    ) -> TimbreFeatureProfile | None:
        wanted = int(instrument_id)
        for current_id, profile in self.profiles:
            if current_id == wanted:
                return profile
        return None

    def nearest_pitch_profile(
        self,
        instrument_id: int,
        pitch: int,
    ) -> tuple[int, TimbreFeatureProfile] | None:
        wanted_id = int(instrument_id)
        wanted_pitch = int(pitch)
        values = [
            (root_note, profile)
            for current_id, root_note, profile in self.pitch_profiles
            if current_id == wanted_id
        ]
        if not values:
            return None
        return min(
            values,
            key=lambda item: (
                abs(item[0] - wanted_pitch),
                item[0],
            ),
        )


@dataclass(frozen=True, slots=True)
class _SampleRef:
    instrument_id: int
    bank: str
    source_id: str
    root_note: int
    velocity_midpoint: float
    path: Path


@dataclass(frozen=True, slots=True)
class _CandidateSegment:
    serial: int
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float
    confidence: float

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


@dataclass(slots=True)
class _Contamination:
    onset_competitors: int = 0
    overlap_load: float = 0.0
    hard_dense: bool = False


def default_timbre_cache_dir() -> Path:
    """Return a user-writable Local AppData cache location."""

    override = os.environ.get("BDO_TIMBRE_CACHE")
    if override:
        return Path(override).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BDO Music Composer" / "timbre_cache"
    return (
        Path.home()
        / "AppData"
        / "Local"
        / "BDO Music Composer"
        / "timbre_cache"
    )


def load_or_build_timbre_profile_index(
    sample_map_path: str | Path,
    audio_root: str | Path,
    *,
    cache_dir: str | Path | None = None,
    max_samples_per_instrument: int = MAX_SAMPLES_PER_INSTRUMENT,
    cancelled: CancelCallback | None = None,
) -> TimbreProfileIndex:
    """Load or extract local BDO instrument timbre profiles.

    This function performs JSON/file I/O, WAV decoding, librosa analysis, and
    scipy envelope smoothing.  Call it from a bounded background worker only.
    No audio content or source path is returned or persisted.  The index keeps
    both a compatibility centroid per instrument and bounded profiles keyed by
    the local sample's root pitch.
    """

    limit = int(max_samples_per_instrument)
    if limit <= 0 or limit > MAX_SAMPLES_PER_INSTRUMENT:
        raise ValueError(
            f"max_samples_per_instrument must be within 1..{MAX_SAMPLES_PER_INSTRUMENT}"
        )
    _check_cancelled(cancelled)
    map_path = Path(sample_map_path)
    root = Path(audio_root)
    payload, map_digest = _read_sample_map(
        map_path,
        cancelled=cancelled,
    )
    selected = _select_representative_samples(
        payload,
        root,
        limit,
        cancelled=cancelled,
    )
    pack_fingerprint = _sample_pack_fingerprint(
        map_digest,
        selected,
        cancelled=cancelled,
    )
    _check_cancelled(cancelled)
    cache_key = hashlib.sha256(
        (
            f"{TIMBRE_FEATURE_VERSION}|{TIMBRE_PITCH_PROFILE_VERSION}|"
            f"{pack_fingerprint}|"
            f"{ANALYSIS_SAMPLE_RATE}|{ANALYSIS_MAX_DURATION_SECONDS:.3f}|{limit}"
        ).encode("ascii")
    ).hexdigest()[:32]
    cache_root = (
        Path(cache_dir) if cache_dir is not None else default_timbre_cache_dir()
    )
    cached = load_cached_timbre_profile_index(
        cache_key,
        cache_dir=cache_root,
        cancelled=cancelled,
    )
    if cached is not None:
        return TimbreProfileIndex(
            cache_key=cached.cache_key,
            profiles=cached.profiles,
            estimated_size_bytes=cached.estimated_size_bytes,
            skipped_sample_count=cached.skipped_sample_count,
            cache_hit=True,
            pitch_profiles=cached.pitch_profiles,
        )

    profiles: list[tuple[int, TimbreFeatureProfile]] = []
    pitch_profiles: list[tuple[int, int, TimbreFeatureProfile]] = []
    skipped = 0
    for instrument_id, refs in selected:
        _check_cancelled(cancelled)
        rows: list[Mapping[str, float]] = []
        rows_by_pitch: dict[int, list[Mapping[str, float]]] = {}
        for ref in refs:
            _check_cancelled(cancelled)
            try:
                if cancelled is None:
                    features = _extract_file_features(ref.path)
                else:
                    features = _extract_file_features(
                        ref.path,
                        cancelled=cancelled,
                    )
                _check_cancelled(cancelled)
                rows.append(features)
                rows_by_pitch.setdefault(ref.root_note, []).append(features)
            except TimbreAnalysisCancelled:
                raise
            except Exception:
                # A single malformed or unsupported local sample must not
                # poison every other instrument.  The count is path-free.
                skipped += 1
        if not rows:
            continue
        _check_cancelled(cancelled)
        reliability = _profile_reliability(instrument_id, len(rows))
        profile = build_timbre_feature_profile(
            rows,
            reliability=reliability,
            max_samples=limit,
            cancelled=cancelled,
        )
        profiles.append((instrument_id, profile))
        for root_note in sorted(rows_by_pitch):
            _check_cancelled(cancelled)
            root_rows = rows_by_pitch[root_note]
            pitch_profiles.append(
                (
                    instrument_id,
                    root_note,
                    build_timbre_feature_profile(
                        root_rows,
                        reliability=_profile_reliability(
                            instrument_id,
                            len(root_rows),
                        ),
                        max_samples=limit,
                        cancelled=cancelled,
                    ),
                )
            )

    _check_cancelled(cancelled)
    ordered = tuple(sorted(profiles, key=lambda item: item[0]))
    ordered_pitch_profiles = tuple(
        sorted(
            pitch_profiles,
            key=lambda item: (item[0], item[1]),
        )
    )
    index = TimbreProfileIndex(
        cache_key=cache_key,
        profiles=ordered,
        estimated_size_bytes=estimate_profile_index_bytes(
            ordered,
            ordered_pitch_profiles,
        ),
        skipped_sample_count=skipped,
        cache_hit=False,
        pitch_profiles=ordered_pitch_profiles,
    )
    _store_timbre_profile_index(
        index,
        pack_fingerprint=pack_fingerprint,
        cache_dir=cache_root,
        max_samples_per_instrument=limit,
        cancelled=cancelled,
    )
    return index


# Shorter aliases for worker implementations and callers.
build_timbre_profile_index = load_or_build_timbre_profile_index
load_or_build_bdo_timbre_profiles = load_or_build_timbre_profile_index


def extract_group_timbre_profiles(
    reference_audio_path: str | Path,
    candidates: Sequence[CandidateLike],
    groups: Sequence[VoiceGroup],
    *,
    frame_evidence: FramePitchEvidence | Mapping[str, object] | None = None,
    max_segments_per_group: int = MAX_GROUP_SEGMENTS,
    min_target_pitch_ratio: float = DEFAULT_MIN_TARGET_PITCH_RATIO,
    cancelled: CancelCallback | None = None,
) -> dict[str, TimbreFeatureProfile]:
    """Extract path-free timbre profiles from low-contamination group segments.

    This worker-only function decodes the reference audio exactly once and
    never caches source audio, clips, or paths.  Each voice group contributes
    at most eight deterministic candidate segments.  Simultaneous/densely
    overlapping notes are rejected or down-weighted.  When validated Basic
    Pitch ``frame`` evidence is supplied, a segment whose target-pitch energy
    share is below ``min_target_pitch_ratio`` is rejected.

    ``frame_evidence`` accepts :class:`FramePitchEvidence` or a mapping with
    ``times_ms``, ``values`` (``frame`` is accepted as an alias), ``midi_min``,
    and ``bins_per_semitone``.  It must already be in memory; this function
    never resolves an evidence filename.  The returned dict-compatible mapping
    exposes its per-pitch rows through ``result.pitch_profiles``.
    """

    segment_limit = int(max_segments_per_group)
    if segment_limit <= 0 or segment_limit > MAX_GROUP_SEGMENTS:
        raise ValueError(
            f"max_segments_per_group must be within 1..{MAX_GROUP_SEGMENTS}"
        )
    pitch_ratio_floor = float(min_target_pitch_ratio)
    if (
        not math.isfinite(pitch_ratio_floor)
        or pitch_ratio_floor < 0.0
        or pitch_ratio_floor >= 1.0
    ):
        raise ValueError("min_target_pitch_ratio must be finite within [0, 1)")

    _check_cancelled(cancelled)
    records = _prepare_candidate_segments(
        candidates,
        cancelled=cancelled,
    )
    if not records or not groups:
        return {}
    by_id = {record.candidate_id: record for record in records}
    contamination = _candidate_contamination(
        records,
        cancelled=cancelled,
    )
    evidence = _prepare_frame_evidence(
        frame_evidence,
        cancelled=cancelled,
    )
    audio, sample_rate = _load_reference_audio(
        reference_audio_path,
        cancelled=cancelled,
    )
    _check_cancelled(cancelled)
    audio_duration_ms = 1000.0 * len(audio) / sample_rate

    profiles: dict[str, TimbreFeatureProfile] = {}
    pitch_profiles: dict[
        str,
        dict[int, TimbreFeatureProfile],
    ] = {}
    candidate_profiles: dict[str, TimbreFeatureProfile] = {}
    ordered_groups = sorted(
        groups,
        key=lambda item: (
            float(item.start_audio_ms),
            float(item.end_audio_ms),
            str(item.group_id),
        ),
    )
    for group in ordered_groups:
        _check_cancelled(cancelled)
        ranked: list[
            tuple[
                float,
                float,
                float,
                float,
                int,
                str,
                _CandidateSegment,
            ]
        ] = []
        for candidate_id in group.candidate_ids:
            _check_cancelled(cancelled)
            record = by_id.get(str(candidate_id))
            if record is None:
                continue
            pollution = contamination[record.serial]
            if pollution.hard_dense or pollution.onset_competitors >= 2:
                continue
            if record.start_ms >= audio_duration_ms or record.end_ms <= 0.0:
                continue
            overlap_penalty = min(
                1.0,
                0.28 * pollution.onset_competitors
                + 0.18 * pollution.overlap_load,
            )
            evidence_ratio: float | None = None
            evidence_density = 0.0
            if evidence is not None:
                _check_cancelled(cancelled)
                evidence_ratio, evidence_density = _segment_pitch_evidence(
                    evidence, record
                )
                if (
                    evidence_ratio is not None
                    and evidence_ratio < pitch_ratio_floor
                ):
                    continue
                if evidence_density >= 7.0:
                    continue
                overlap_penalty = min(
                    1.0,
                    overlap_penalty + max(0.0, evidence_density - 1.0) * 0.055,
                )
            evidence_quality = 0.82
            if evidence_ratio is not None:
                evidence_quality = min(
                    1.0,
                    0.40
                    + 0.60
                    * max(
                        0.0,
                        (evidence_ratio - pitch_ratio_floor)
                        / max(1e-9, 0.45 - pitch_ratio_floor),
                    ),
                )
            quality = (
                record.confidence
                * max(0.0, 1.0 - overlap_penalty)
                * evidence_quality
            )
            if quality < 0.12:
                continue
            ranked.append(
                (
                    -quality,
                    overlap_penalty,
                    -(evidence_ratio if evidence_ratio is not None else -1.0),
                    record.start_ms,
                    record.pitch,
                    record.candidate_id,
                    record,
                )
            )
        ranked.sort(key=lambda item: item[:-1])
        selected = ranked[:segment_limit]
        feature_rows: list[Mapping[str, float]] = []
        qualities: list[float] = []
        pitch_feature_rows: dict[
            int,
            list[Mapping[str, float]],
        ] = {}
        pitch_qualities: dict[int, list[float]] = {}
        for rank in selected:
            _check_cancelled(cancelled)
            record = rank[-1]
            clip_start_ms = max(0.0, record.start_ms - 20.0)
            clip_end_ms = min(
                audio_duration_ms,
                record.start_ms + min(record.duration_ms, 4000.0) + 120.0,
            )
            start_frame = max(0, round(clip_start_ms * sample_rate / 1000.0))
            end_frame = min(
                len(audio), round(clip_end_ms * sample_rate / 1000.0)
            )
            if end_frame - start_frame < 64:
                continue
            try:
                clip = audio[start_frame:end_frame]
                if cancelled is None:
                    features = _extract_signal_features(clip, sample_rate)
                else:
                    features = _extract_signal_features(
                        clip,
                        sample_rate,
                        cancelled=cancelled,
                    )
                _check_cancelled(cancelled)
                feature_rows.append(features)
                quality = -float(rank[0])
                qualities.append(quality)
                pitch_feature_rows.setdefault(record.pitch, []).append(features)
                pitch_qualities.setdefault(record.pitch, []).append(quality)
                candidate_profiles[record.candidate_id] = (
                    build_timbre_feature_profile(
                        (features,),
                        reliability=min(0.90, quality),
                        max_samples=1,
                        cancelled=cancelled,
                    )
                )
            except TimbreAnalysisCancelled:
                raise
            except Exception:
                # Keep errors local and path-free.  Other segments/groups remain
                # usable if one decoder window is numerically unsuitable.
                continue
        if not feature_rows:
            continue
        average_quality = sum(qualities) / len(qualities)
        sample_factor = min(
            0.90,
            0.45 + 0.45 * math.sqrt(len(feature_rows) / MAX_GROUP_SEGMENTS),
        )
        reliability = min(1.0, sample_factor * average_quality)
        if evidence is None:
            reliability = min(0.60, reliability)
        _check_cancelled(cancelled)
        profiles[str(group.group_id)] = build_timbre_feature_profile(
            feature_rows,
            reliability=reliability,
            max_samples=segment_limit,
            cancelled=cancelled,
        )
        group_pitch_profiles: dict[int, TimbreFeatureProfile] = {}
        for pitch in sorted(pitch_feature_rows):
            _check_cancelled(cancelled)
            rows_for_pitch = pitch_feature_rows[pitch]
            quality_for_pitch = (
                sum(pitch_qualities[pitch])
                / len(pitch_qualities[pitch])
            )
            pitch_sample_factor = min(
                0.90,
                0.45
                + 0.45
                * math.sqrt(
                    len(rows_for_pitch) / MAX_GROUP_SEGMENTS
                ),
            )
            pitch_reliability = min(
                1.0,
                pitch_sample_factor * quality_for_pitch,
            )
            if evidence is None:
                pitch_reliability = min(0.60, pitch_reliability)
            group_pitch_profiles[pitch] = build_timbre_feature_profile(
                rows_for_pitch,
                reliability=pitch_reliability,
                max_samples=segment_limit,
                cancelled=cancelled,
            )
        if group_pitch_profiles:
            pitch_profiles[str(group.group_id)] = group_pitch_profiles
    _check_cancelled(cancelled)
    return PitchAwareProfileMap(
        profiles,
        pitch_profiles,
        candidate_profiles,
    )


def remap_group_timbre_profiles(
    profile_map: Mapping[str, TimbreFeatureProfile],
    candidates: Sequence[CandidateLike],
    groups: Sequence[VoiceGroup],
    *,
    cancelled: CancelCallback | None = None,
) -> PitchAwareProfileMap:
    """Aggregate already-decoded segment features for refined voice groups."""

    _check_cancelled(cancelled)
    candidate_profiles = {
        str(candidate_id): profile
        for candidate_id, profile in getattr(
            profile_map,
            "candidate_profiles",
            {},
        ).items()
        if isinstance(profile, TimbreFeatureProfile)
    }
    pitch_by_id = {
        str(getattr(candidate, "candidate_id", "") or ""): int(
            candidate.pitch
        )
        for candidate in candidates
        if str(getattr(candidate, "candidate_id", "") or "")
    }
    profiles: dict[str, TimbreFeatureProfile] = {}
    pitch_profiles: dict[str, dict[int, TimbreFeatureProfile]] = {}
    for group in groups:
        _check_cancelled(cancelled)
        selected = [
            candidate_profiles[candidate_id]
            for candidate_id in group.candidate_ids
            if candidate_id in candidate_profiles
        ][:MAX_GROUP_SEGMENTS]
        if not selected:
            continue
        rows = [
            dict(zip(profile.feature_names, profile.values))
            for profile in selected
        ]
        reliability = sum(
            profile.reliability for profile in selected
        ) / len(selected)
        profiles[group.group_id] = build_timbre_feature_profile(
            rows,
            reliability=reliability,
            max_samples=MAX_GROUP_SEGMENTS,
            cancelled=cancelled,
        )
        by_pitch: dict[int, list[TimbreFeatureProfile]] = {}
        for candidate_id in group.candidate_ids:
            profile = candidate_profiles.get(candidate_id)
            pitch = pitch_by_id.get(candidate_id)
            if profile is not None and pitch is not None:
                by_pitch.setdefault(pitch, []).append(profile)
        group_pitch_profiles: dict[int, TimbreFeatureProfile] = {}
        for pitch, values in sorted(by_pitch.items()):
            _check_cancelled(cancelled)
            pitch_rows = [
                dict(zip(profile.feature_names, profile.values))
                for profile in values[:MAX_GROUP_SEGMENTS]
            ]
            pitch_reliability = sum(
                profile.reliability
                for profile in values[:MAX_GROUP_SEGMENTS]
            ) / min(len(values), MAX_GROUP_SEGMENTS)
            group_pitch_profiles[pitch] = build_timbre_feature_profile(
                pitch_rows,
                reliability=pitch_reliability,
                max_samples=MAX_GROUP_SEGMENTS,
                cancelled=cancelled,
            )
        if group_pitch_profiles:
            pitch_profiles[group.group_id] = group_pitch_profiles
    return PitchAwareProfileMap(
        profiles,
        pitch_profiles,
        candidate_profiles,
    )


def load_cached_timbre_profile_index(
    cache_key: str,
    *,
    cache_dir: str | Path | None = None,
    cancelled: CancelCallback | None = None,
) -> TimbreProfileIndex | None:
    """Validate and load one cache entry, returning ``None`` fail-closed."""

    _check_cancelled(cancelled)
    key = str(cache_key)
    if not _HEX_KEY_RE.fullmatch(key):
        return None
    root = Path(cache_dir) if cache_dir is not None else default_timbre_cache_dir()
    manifest_path = root / key / "manifest.json"
    try:
        raw = manifest_path.read_bytes()
        _check_cancelled(cancelled)
        if len(raw) > MAX_CACHE_MANIFEST_BYTES:
            return None
        payload = json.loads(raw.decode("utf-8"))
        _check_cancelled(cancelled)
        if not isinstance(payload, dict):
            return None
        checksum = str(payload.get("payload_sha256", ""))
        body = dict(payload)
        body.pop("payload_sha256", None)
        if not _HEX_KEY_RE.fullmatch(checksum):
            return None
        if hashlib.sha256(_canonical_json(body)).hexdigest() != checksum:
            return None
        if (
            body.get("format") != TIMBRE_CACHE_FORMAT
            or body.get("feature_version") != TIMBRE_FEATURE_VERSION
            or body.get("pitch_profile_version")
            != TIMBRE_PITCH_PROFILE_VERSION
            or body.get("cache_key") != key
            or not _HEX_KEY_RE.fullmatch(str(body.get("sample_pack_fingerprint", "")))
        ):
            return None
        records = body.get("profiles")
        if not isinstance(records, list) or len(records) > 512:
            return None
        profiles: list[tuple[int, TimbreFeatureProfile]] = []
        for record in records:
            _check_cancelled(cancelled)
            if not isinstance(record, dict) or set(record) != {
                "instrument_id",
                "profile_key",
                "feature_names",
                "values",
                "sample_count",
                "reliability",
            }:
                return None
            instrument_id = int(record["instrument_id"])
            names = tuple(str(name) for name in record["feature_names"])
            values = tuple(float(value) for value in record["values"])
            sample_count = int(record["sample_count"])
            reliability = float(record["reliability"])
            if names != _FEATURE_NAMES:
                return None
            if sample_count <= 0 or sample_count > MAX_SAMPLES_PER_INSTRUMENT:
                return None
            if instrument_id in MARNIAN_INSTRUMENT_IDS:
                if reliability > MARNIAN_TIMBRE_RELIABILITY_CAP:
                    return None
            elif not 0.0 <= reliability <= 1.0:
                return None
            profile = TimbreFeatureProfile(
                str(record["profile_key"]),
                names,
                values,
                sample_count,
                reliability,
            )
            profiles.append((instrument_id, profile))
        ordered = tuple(sorted(profiles, key=lambda item: item[0]))
        if tuple(profiles) != ordered:
            return None
        pitch_records = body.get("pitch_profiles")
        if not isinstance(pitch_records, list) or len(pitch_records) > 16384:
            return None
        if int(body.get("pitch_profile_count", -1)) != len(pitch_records):
            return None
        profile_ids = {item[0] for item in ordered}
        pitch_profiles: list[
            tuple[int, int, TimbreFeatureProfile]
        ] = []
        for record in pitch_records:
            _check_cancelled(cancelled)
            if not isinstance(record, dict) or set(record) != {
                "instrument_id",
                "root_note",
                "profile_key",
                "feature_names",
                "values",
                "sample_count",
                "reliability",
            }:
                return None
            instrument_id = int(record["instrument_id"])
            root_note = int(record["root_note"])
            names = tuple(str(name) for name in record["feature_names"])
            values = tuple(float(value) for value in record["values"])
            sample_count = int(record["sample_count"])
            reliability = float(record["reliability"])
            if (
                instrument_id not in profile_ids
                or root_note < 0
                or root_note > 127
                or names != _FEATURE_NAMES
                or sample_count <= 0
                or sample_count > MAX_SAMPLES_PER_INSTRUMENT
            ):
                return None
            if instrument_id in MARNIAN_INSTRUMENT_IDS:
                if reliability > MARNIAN_TIMBRE_RELIABILITY_CAP:
                    return None
            elif not 0.0 <= reliability <= 1.0:
                return None
            pitch_profiles.append(
                (
                    instrument_id,
                    root_note,
                    TimbreFeatureProfile(
                        str(record["profile_key"]),
                        names,
                        values,
                        sample_count,
                        reliability,
                    ),
                )
            )
        ordered_pitch_profiles = tuple(
            sorted(
                pitch_profiles,
                key=lambda item: (item[0], item[1]),
            )
        )
        if tuple(pitch_profiles) != ordered_pitch_profiles:
            return None
        pitch_profile_counts: dict[int, int] = {}
        pitch_sample_counts: dict[int, int] = {}
        for instrument_id, _root_note, profile in ordered_pitch_profiles:
            pitch_profile_counts[instrument_id] = (
                pitch_profile_counts.get(instrument_id, 0) + 1
            )
            pitch_sample_counts[instrument_id] = (
                pitch_sample_counts.get(instrument_id, 0)
                + profile.sample_count
            )
        if any(
            count > MAX_SAMPLES_PER_INSTRUMENT
            for count in pitch_profile_counts.values()
        ) or any(
            count > MAX_SAMPLES_PER_INSTRUMENT
            for count in pitch_sample_counts.values()
        ):
            return None
        estimated = estimate_profile_index_bytes(
            ordered,
            ordered_pitch_profiles,
        )
        if int(body.get("estimated_size_bytes", -1)) != estimated:
            return None
        if int(body.get("profile_count", -1)) != len(ordered):
            return None
        skipped = int(body.get("skipped_sample_count", -1))
        _check_cancelled(cancelled)
        return TimbreProfileIndex(
            cache_key=key,
            profiles=ordered,
            estimated_size_bytes=estimated,
            skipped_sample_count=skipped,
            cache_hit=True,
            pitch_profiles=ordered_pitch_profiles,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def estimate_profile_index_bytes(
    profiles: Sequence[tuple[int, TimbreFeatureProfile]],
    pitch_profiles: Sequence[
        tuple[int, int, TimbreFeatureProfile]
    ] = (),
) -> int:
    """Conservatively estimate resident bytes without importing numpy."""

    total = 256
    for instrument_id, profile in profiles:
        total += 96 + 32  # tuple/dict slot and integer/profile references
        total += len(str(int(instrument_id)))
        total += len(profile.profile_key.encode("utf-8"))
        total += 8 * len(profile.values)
        total += sum(49 + len(name.encode("utf-8")) for name in profile.feature_names)
    for instrument_id, root_note, profile in pitch_profiles:
        total += 112 + len(str(int(instrument_id))) + len(str(int(root_note)))
        total += len(profile.profile_key.encode("utf-8"))
        total += 8 * len(profile.values)
        total += sum(
            49 + len(name.encode("utf-8"))
            for name in profile.feature_names
        )
    return int(total)


def _prepare_candidate_segments(
    candidates: Sequence[CandidateLike],
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[_CandidateSegment, ...]:
    prepared: list[tuple[str, int, float, float, float]] = []
    for candidate in candidates:
        _check_cancelled(cancelled)
        try:
            pitch = int(candidate.pitch)
            start_ms = float(candidate.start_ms)
            duration_ms = float(candidate.duration_ms)
            confidence = float(candidate.confidence)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if (
            pitch < 0
            or pitch > 127
            or not math.isfinite(start_ms)
            or not math.isfinite(duration_ms)
            or not math.isfinite(confidence)
            or start_ms < 0.0
            or duration_ms <= 0.0
        ):
            continue
        candidate_id = str(getattr(candidate, "candidate_id", "") or "")
        if not candidate_id:
            candidate_id = hashlib.sha256(
                (
                    f"{pitch}|{start_ms:.6f}|{duration_ms:.6f}|"
                    f"{confidence:.6f}"
                ).encode("ascii")
            ).hexdigest()[:24]
        prepared.append(
            (
                candidate_id,
                pitch,
                start_ms,
                duration_ms,
                max(0.0, min(1.0, confidence)),
            )
        )
    prepared.sort(key=lambda item: (item[2], item[1], item[3], item[0]))
    records: list[_CandidateSegment] = []
    seen_ids: set[str] = set()
    for candidate_id, pitch, start_ms, duration_ms, confidence in prepared:
        _check_cancelled(cancelled)
        # VoiceGroup membership uses stable candidate ids, so conflicting
        # duplicates cannot be disambiguated safely.  Keep the deterministic
        # earliest record instead of silently attaching both.
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        records.append(
            _CandidateSegment(
                len(records),
                candidate_id,
                pitch,
                start_ms,
                duration_ms,
                confidence,
            )
        )
    return tuple(records)


def _candidate_contamination(
    records: Sequence[_CandidateSegment],
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[_Contamination, ...]:
    """Measure overlap in one sweep, bounding dense-polyphony work."""

    metrics = [_Contamination() for _item in records]
    active: dict[int, _CandidateSegment] = {}
    ends: list[tuple[float, int]] = []
    dense_active = False
    for current in records:
        _check_cancelled(cancelled)
        while ends and ends[0][0] <= current.start_ms:
            _end_ms, serial = heapq.heappop(ends)
            active.pop(serial, None)
        if len(active) >= 64:
            metrics[current.serial].hard_dense = True
            if not dense_active:
                # Mark the first saturated active set once.  Later arrivals are
                # individually marked without quadratic pair enumeration.
                for serial in active:
                    _check_cancelled(cancelled)
                    metrics[serial].hard_dense = True
                dense_active = True
        else:
            dense_active = False
            for previous in active.values():
                _check_cancelled(cancelled)
                if previous.pitch == current.pitch:
                    continue
                overlap_ms = min(previous.end_ms, current.end_ms) - current.start_ms
                if overlap_ms <= 0.0:
                    continue
                metrics[previous.serial].overlap_load += min(
                    1.0, overlap_ms / previous.duration_ms
                )
                metrics[current.serial].overlap_load += min(
                    1.0, overlap_ms / current.duration_ms
                )
                if (
                    abs(previous.start_ms - current.start_ms)
                    <= GROUP_ONSET_TOLERANCE_MS
                ):
                    metrics[previous.serial].onset_competitors += 1
                    metrics[current.serial].onset_competitors += 1
        active[current.serial] = current
        heapq.heappush(ends, (current.end_ms, current.serial))
    for metric in metrics:
        _check_cancelled(cancelled)
        if metric.overlap_load >= 2.5:
            metric.hard_dense = True
    return tuple(metrics)


def _prepare_frame_evidence(
    value: FramePitchEvidence | Mapping[str, object] | None,
    *,
    cancelled: CancelCallback | None = None,
) -> FramePitchEvidence | None:
    _check_cancelled(cancelled)
    if value is None:
        return None
    if isinstance(value, FramePitchEvidence):
        raw = value
    elif isinstance(value, Mapping):
        frame_values = value.get("values", value.get("frame"))
        raw = FramePitchEvidence(
            value.get("times_ms"),
            frame_values,
            int(value.get("midi_min", 21)),
            int(value.get("bins_per_semitone", 1)),
        )
    else:
        raise TypeError("frame_evidence must be FramePitchEvidence or a mapping")
    import numpy as np

    _check_cancelled(cancelled)
    times = np.asarray(raw.times_ms, dtype=np.float64)
    matrix = np.asarray(raw.values)
    midi_min = int(raw.midi_min)
    bins_per_semitone = int(raw.bins_per_semitone)
    if (
        times.ndim != 1
        or matrix.ndim != 2
        or matrix.shape[0] != times.size
        or times.size == 0
        or bins_per_semitone <= 0
        or matrix.shape[1] % bins_per_semitone != 0
        or not np.all(np.isfinite(times))
        or not np.all(np.isfinite(matrix))
        or np.any(np.diff(times) <= 0.0)
        or np.any(matrix < 0.0)
    ):
        raise TimbreProfileError("invalid in-memory frame evidence")
    _check_cancelled(cancelled)
    return FramePitchEvidence(
        times,
        matrix,
        midi_min,
        bins_per_semitone,
    )


def _segment_pitch_evidence(
    evidence: FramePitchEvidence,
    record: _CandidateSegment,
) -> tuple[float | None, float]:
    import numpy as np

    times = np.asarray(evidence.times_ms)
    matrix = np.asarray(evidence.values)
    left = int(np.searchsorted(times, record.start_ms, side="left"))
    right = int(np.searchsorted(times, record.end_ms, side="right"))
    if right <= left:
        return None, 0.0
    pitch_offset = record.pitch - int(evidence.midi_min)
    bins_per_semitone = int(evidence.bins_per_semitone)
    first_bin = pitch_offset * bins_per_semitone
    last_bin = first_bin + bins_per_semitone
    if first_bin < 0 or last_bin > matrix.shape[1]:
        return 0.0, float("inf")
    window = np.asarray(matrix[left:right], dtype=np.float64)
    total = np.sum(window, axis=1)
    target = np.sum(window[:, first_bin:last_bin], axis=1)
    usable = total > 1e-9
    if not np.any(usable):
        return 0.0, 0.0
    ratio = float(np.median(target[usable] / total[usable]))
    # Basic Pitch frame activations are bounded probabilities.  Counting bins
    # above both an absolute floor and a fraction of the target avoids treating
    # a low noise floor as dozens of active voices.
    target_per_frame = np.maximum(target[:, None] * 0.25, 0.10)
    density = float(np.median(np.sum(window >= target_per_frame, axis=1)))
    return max(0.0, min(1.0, ratio)), max(0.0, density)


def _load_reference_audio(
    path: str | Path,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[object, int]:
    import librosa  # type: ignore[import-not-found]
    import numpy as np

    _check_cancelled(cancelled)
    try:
        signal, sample_rate = librosa.load(
            str(Path(path)),
            sr=ANALYSIS_SAMPLE_RATE,
            mono=True,
            dtype=np.float32,
        )
    except Exception as exc:
        raise TimbreProfileError("unable to decode local reference audio") from exc
    _check_cancelled(cancelled)
    audio = np.asarray(signal, dtype=np.float32)
    if (
        audio.ndim != 1
        or audio.size < 64
        or not np.all(np.isfinite(audio))
    ):
        raise TimbreProfileError("reference audio contains no usable samples")
    _check_cancelled(cancelled)
    return np.ascontiguousarray(audio), int(sample_rate)


def _read_sample_map(
    path: Path,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[dict, str]:
    _check_cancelled(cancelled)
    try:
        raw = path.read_bytes()
        _check_cancelled(cancelled)
        if len(raw) > 64 * 1024 * 1024:
            raise TimbreProfileError("sample map is too large")
        payload = json.loads(raw.decode("utf-8"))
    except TimbreProfileError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TimbreProfileError("unable to read local sample map") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("banks"), dict):
        raise TimbreProfileError("invalid local sample map")
    return payload, hashlib.sha256(raw).hexdigest()


def _select_representative_samples(
    payload: Mapping[str, object],
    audio_root: Path,
    limit: int,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[tuple[int, tuple[_SampleRef, ...]], ...]:
    _check_cancelled(cancelled)
    banks = payload.get("banks")
    if not isinstance(banks, Mapping):
        raise TimbreProfileError("invalid local sample map")
    grouped: dict[int, dict[tuple[str, str], _SampleRef]] = {}
    for raw_bank, raw_rows in sorted(banks.items(), key=lambda item: str(item[0])):
        _check_cancelled(cancelled)
        bank = str(raw_bank)
        instrument_id = _instrument_id_from_bank(bank)
        if instrument_id is None or not isinstance(raw_rows, list):
            continue
        if not _SAFE_BANK_RE.fullmatch(bank):
            continue
        for row in raw_rows:
            _check_cancelled(cancelled)
            if not isinstance(row, Mapping):
                continue
            source_id = _safe_source_id(row.get("source_id"))
            if source_id is None:
                continue
            path = _resolve_sample_path(audio_root, bank, source_id, row)
            if path is None:
                continue
            try:
                root_note = max(0, min(127, int(row.get("root_note", 60))))
                velocity_min = max(0, min(127, int(row.get("velocity_min", 0))))
                velocity_max = max(
                    velocity_min, min(127, int(row.get("velocity_max", 127)))
                )
            except (TypeError, ValueError, OverflowError):
                continue
            ref = _SampleRef(
                instrument_id,
                bank,
                source_id,
                root_note,
                (velocity_min + velocity_max) / 2.0,
                path,
            )
            grouped.setdefault(instrument_id, {}).setdefault((bank, source_id), ref)

    result: list[tuple[int, tuple[_SampleRef, ...]]] = []
    for instrument_id in sorted(grouped):
        _check_cancelled(cancelled)
        refs = sorted(
            grouped[instrument_id].values(),
            key=lambda item: (
                item.root_note,
                item.velocity_midpoint,
                item.bank,
                item.source_id,
            ),
        )
        selected = _evenly_spaced_representatives(refs, limit)
        if selected:
            result.append((instrument_id, selected))
    return tuple(result)


def _evenly_spaced_representatives(
    refs: Sequence[_SampleRef], limit: int
) -> tuple[_SampleRef, ...]:
    if len(refs) <= limit:
        return tuple(refs)
    if limit == 1:
        return (refs[(len(refs) - 1) // 2],)
    indices = {
        round(index * (len(refs) - 1) / (limit - 1))
        for index in range(limit)
    }
    # Rounding is monotonic here, but fill deterministically if a very small
    # input/limit combination ever yields duplicate indices.
    if len(indices) < limit:
        indices.update(index for index in range(len(refs)) if len(indices) < limit)
    return tuple(refs[index] for index in sorted(indices)[:limit])


def _instrument_id_from_bank(bank: str) -> int | None:
    regular = _REGULAR_BANK_RE.fullmatch(bank)
    if regular:
        value = int(regular.group(1), 10)
        return value if 0 <= value <= 255 else None
    prefix = "midi_instrument_synth_"
    if bank.startswith(prefix):
        remainder = bank[len(prefix) :]
        waveform = remainder.split("_", 1)[0]
        return _MARNIAN_BANK_IDS.get(waveform)
    return None


def _safe_source_id(value: object) -> str | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0:
        return None
    return str(number)


def _resolve_sample_path(
    audio_root: Path,
    bank: str,
    source_id: str,
    row: Mapping[str, object],
) -> Path | None:
    try:
        root = audio_root.resolve(strict=True)
    except OSError:
        return None
    if not root.is_dir():
        return None
    wav_roots = [root]
    if root.name != "乐器_WAV":
        wav_roots.insert(0, root / "乐器_WAV")
    candidates: list[tuple[Path, Path]] = [
        (wav_root, wav_root / bank / f"{source_id}.wav")
        for wav_root in wav_roots
    ]
    raw_relative = str(row.get("wav_path", "") or "")
    if raw_relative:
        relative = PurePath(raw_relative)
        if (
            not relative.is_absolute()
            and ".." not in relative.parts
            and relative.suffix.casefold() == ".wav"
        ):
            candidates.extend((wav_root, wav_root / relative) for wav_root in wav_roots)
    for allowed_root, candidate in candidates:
        try:
            allowed = allowed_root.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(allowed)
        except (OSError, ValueError):
            continue
        if resolved.is_file() and resolved.suffix.casefold() == ".wav":
            return resolved
    return None


def _sample_pack_fingerprint(
    map_digest: str,
    selected: Sequence[tuple[int, Sequence[_SampleRef]]],
    *,
    cancelled: CancelCallback | None = None,
) -> str:
    _check_cancelled(cancelled)
    digest = hashlib.sha256()
    digest.update(TIMBRE_FEATURE_VERSION.encode("ascii"))
    digest.update(map_digest.encode("ascii"))
    for instrument_id, refs in selected:
        _check_cancelled(cancelled)
        for ref in refs:
            _check_cancelled(cancelled)
            digest.update(
                (
                    f"{instrument_id}|{ref.bank}|{ref.source_id}|"
                    f"{ref.root_note}|{ref.velocity_midpoint:.3f}|"
                ).encode("ascii")
            )
            file_digest = hashlib.sha256()
            with ref.path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    _check_cancelled(cancelled)
                    file_digest.update(block)
            _check_cancelled(cancelled)
            digest.update(file_digest.digest())
    _check_cancelled(cancelled)
    return digest.hexdigest()


def _profile_reliability(instrument_id: int, sample_count: int) -> float:
    evidence = min(1.0, 0.45 + 0.55 * math.sqrt(max(1, sample_count) / 8.0))
    if instrument_id in MARNIAN_INSTRUMENT_IDS:
        # Preview bank pairing is provisional until it has game A/B evidence.
        return min(MARNIAN_TIMBRE_RELIABILITY_CAP, evidence)
    return evidence


def _extract_file_features(
    path: Path,
    *,
    cancelled: CancelCallback | None = None,
) -> dict[str, float]:
    """Decode one local WAV and calculate a finite, fixed-shape feature row."""

    import librosa  # type: ignore[import-not-found]
    import numpy as np

    _check_cancelled(cancelled)
    signal, sample_rate = librosa.load(
        str(path),
        sr=ANALYSIS_SAMPLE_RATE,
        mono=True,
        duration=ANALYSIS_MAX_DURATION_SECONDS,
        dtype=np.float32,
    )
    _check_cancelled(cancelled)
    return _extract_signal_features(
        signal,
        int(sample_rate),
        cancelled=cancelled,
    )


def _extract_signal_features(
    signal: object,
    sample_rate: int,
    *,
    cancelled: CancelCallback | None = None,
) -> dict[str, float]:
    """Calculate the same fixed-shape features for one in-memory audio clip."""

    # These heavy imports stay behind worker-only functions so importing the
    # application or ordinary UI tests never initializes their runtimes.
    import librosa  # type: ignore[import-not-found]
    import numpy as np
    from scipy.ndimage import gaussian_filter1d  # type: ignore[import-not-found]

    _check_cancelled(cancelled)
    y = np.asarray(signal, dtype=np.float32)
    if y.size < 64 or not np.all(np.isfinite(y)):
        raise TimbreProfileError("sample contains no usable audio")
    y, _trim = librosa.effects.trim(y, top_db=60)
    _check_cancelled(cancelled)
    if y.size < 64:
        raise TimbreProfileError("sample contains no usable audio")
    peak = float(np.max(np.abs(y)))
    if not math.isfinite(peak) or peak <= 1e-7:
        raise TimbreProfileError("sample contains no usable audio")
    y = np.ascontiguousarray(y / peak, dtype=np.float32)
    sample_rate = int(sample_rate)
    if sample_rate <= 0:
        raise TimbreProfileError("sample rate must be positive")
    n_fft = 2048
    if y.size < n_fft:
        y = np.pad(y, (0, n_fft - y.size))
    hop_length = 256

    _check_cancelled(cancelled)
    mfcc = librosa.feature.mfcc(
        y=y,
        sr=sample_rate,
        n_mfcc=13,
        n_fft=n_fft,
        hop_length=hop_length,
    )
    _check_cancelled(cancelled)
    contrast = librosa.feature.spectral_contrast(
        y=y,
        sr=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
        n_bands=6,
    )
    _check_cancelled(cancelled)
    centroid = librosa.feature.spectral_centroid(
        y=y,
        sr=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
    )
    _check_cancelled(cancelled)
    rolloff = librosa.feature.spectral_rolloff(
        y=y,
        sr=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
        roll_percent=0.85,
    )
    _check_cancelled(cancelled)
    flatness = librosa.feature.spectral_flatness(
        y=y,
        n_fft=n_fft,
        hop_length=hop_length,
    )
    _check_cancelled(cancelled)
    rms = librosa.feature.rms(
        y=y,
        frame_length=n_fft,
        hop_length=hop_length,
    )[0]
    _check_cancelled(cancelled)
    attack_ms, decay_ms = _attack_decay_ms(
        np.asarray(rms, dtype=np.float64),
        int(sample_rate),
        hop_length,
        gaussian_filter1d,
    )
    values = (
        *[float(np.median(row)) for row in mfcc],
        *[float(np.median(row)) for row in contrast],
        float(np.median(centroid)),
        float(np.median(rolloff)),
        float(np.median(flatness)),
        attack_ms,
        decay_ms,
    )
    if len(values) != len(_EXTRACTION_FEATURE_NAMES) or not all(
        math.isfinite(value) for value in values
    ):
        raise TimbreProfileError("sample produced invalid timbre features")
    _check_cancelled(cancelled)
    unordered = dict(zip(_EXTRACTION_FEATURE_NAMES, values, strict=True))
    return {name: unordered[name] for name in _FEATURE_NAMES}


def _attack_decay_ms(
    rms: object,
    sample_rate: int,
    hop_length: int,
    gaussian_filter: object,
) -> tuple[float, float]:
    # Kept separate for deterministic unit tests without importing scipy.
    import numpy as np

    envelope = np.asarray(rms, dtype=np.float64)
    if envelope.size == 0:
        return 0.0, 0.0
    envelope = np.asarray(gaussian_filter(envelope, sigma=1.0), dtype=np.float64)
    peak_index = int(np.argmax(envelope))
    peak = float(envelope[peak_index])
    if not math.isfinite(peak) or peak <= 1e-12:
        return 0.0, 0.0
    before = np.flatnonzero(envelope[: peak_index + 1] >= peak * 0.10)
    attack_start = int(before[0]) if before.size else peak_index
    after = np.flatnonzero(envelope[peak_index:] <= peak / math.e)
    decay_end = (
        peak_index + int(after[0]) if after.size else max(peak_index, len(envelope) - 1)
    )
    frame_ms = 1000.0 * hop_length / sample_rate
    return (
        max(0.0, (peak_index - attack_start) * frame_ms),
        max(0.0, (decay_end - peak_index) * frame_ms),
    )


def _store_timbre_profile_index(
    index: TimbreProfileIndex,
    *,
    pack_fingerprint: str,
    cache_dir: Path,
    max_samples_per_instrument: int,
    cancelled: CancelCallback | None = None,
) -> None:
    _check_cancelled(cancelled)
    profiles = [
        {
            "instrument_id": instrument_id,
            "profile_key": profile.profile_key,
            "feature_names": list(profile.feature_names),
            "values": list(profile.values),
            "sample_count": profile.sample_count,
            "reliability": profile.reliability,
        }
        for instrument_id, profile in index.profiles
    ]
    pitch_profiles = [
        {
            "instrument_id": instrument_id,
            "root_note": root_note,
            "profile_key": profile.profile_key,
            "feature_names": list(profile.feature_names),
            "values": list(profile.values),
            "sample_count": profile.sample_count,
            "reliability": profile.reliability,
        }
        for instrument_id, root_note, profile in index.pitch_profiles
    ]
    body = {
        "format": TIMBRE_CACHE_FORMAT,
        "feature_version": TIMBRE_FEATURE_VERSION,
        "pitch_profile_version": TIMBRE_PITCH_PROFILE_VERSION,
        "cache_key": index.cache_key,
        "sample_pack_fingerprint": pack_fingerprint,
        "max_samples_per_instrument": int(max_samples_per_instrument),
        "profile_count": len(profiles),
        "pitch_profile_count": len(pitch_profiles),
        "estimated_size_bytes": index.estimated_size_bytes,
        "skipped_sample_count": index.skipped_sample_count,
        "profiles": profiles,
        "pitch_profiles": pitch_profiles,
    }
    payload = dict(body)
    payload["payload_sha256"] = hashlib.sha256(_canonical_json(body)).hexdigest()
    _check_cancelled(cancelled)
    target_dir = cache_dir / index.cache_key
    target_dir.mkdir(parents=True, exist_ok=True)
    temporary = target_dir / f".manifest.{os.getpid()}.tmp"
    manifest = target_dir / "manifest.json"
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    try:
        _check_cancelled(cancelled)
        with temporary.open("wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        _check_cancelled(cancelled)
        os.replace(temporary, manifest)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


__all__ = [
    "ANALYSIS_MAX_DURATION_SECONDS",
    "ANALYSIS_SAMPLE_RATE",
    "CancelCallback",
    "DEFAULT_MIN_TARGET_PITCH_RATIO",
    "FramePitchEvidence",
    "GROUP_ONSET_TOLERANCE_MS",
    "MAX_GROUP_SEGMENTS",
    "MAX_CACHE_MANIFEST_BYTES",
    "MAX_SAMPLES_PER_INSTRUMENT",
    "MARNIAN_INSTRUMENT_IDS",
    "MARNIAN_TIMBRE_RELIABILITY_CAP",
    "PitchAwareProfileMap",
    "PROFILE_INDEX_MEMORY_LIMIT",
    "TIMBRE_FEATURE_VERSION",
    "TIMBRE_PITCH_PROFILE_VERSION",
    "TimbreAnalysisCancelled",
    "TimbreProfileError",
    "TimbreProfileIndex",
    "build_timbre_profile_index",
    "default_timbre_cache_dir",
    "estimate_profile_index_bytes",
    "extract_group_timbre_profiles",
    "load_cached_timbre_profile_index",
    "load_or_build_bdo_timbre_profiles",
    "load_or_build_timbre_profile_index",
    "remap_group_timbre_profiles",
]
