"""Independent editor-to-BDO v9 export consistency diagnostics.

The verifier deliberately rebuilds the game-representable expectation from a
frozen export request instead of trusting the export summary.  It compares
semantic fields after the intentional game transforms (instrument merging,
pitch projection, drum normalization and physical track splitting), then checks
the bytes published to the primary and optional game-directory destinations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
from typing import NamedTuple, Protocol, Sequence

from bdo_codec import (
    BDO_VERSION,
    BdoDocument,
    MAX_NOTES_PER_TRACK,
    NAME_FIELD_SIZE,
    decode_score,
    encode_score,
    validate_score,
)
from bdo_export import (
    BDO_BPM_MAX,
    BDO_BPM_MIN,
    DEFAULT_TRACK_VOLUME,
    document_matches_logical_tracks,
    make_track_settings,
)
from bdo_midi import (
    BDO_INSTRUMENTS,
    DEFAULT_INSTRUMENT,
    clamp_notes,
    map_drum_notes,
    normalize_drum_note_timing,
)
from game_score_model import serialized_game_instrument_id
from pitch_transform import (
    track_uses_percussion_pitch_semantics,
    transpose_notes,
)


EXPORT_TIME_TOLERANCE_MS = 0.001
MAX_REPORTED_ISSUES = 128
_DRUM_INSTRUMENT_ID = BDO_INSTRUMENTS["drum_set"]
_PRIVATE_PATHS = frozenset({
    "header.owner_id",
    "header.character_name_1",
    "header.character_name_2",
})


class ExportRequestView(Protocol):
    direct_tracks: Sequence[object]
    bpm: int
    time_signature: int
    character_name: str
    owner_id: int
    conversion: object
    pitch_plan: object
    reverb: int
    delay: int
    chorus: tuple[int, int, int] | None
    articulation_map: Sequence[tuple[int, int]]
    track_volumes: Sequence[tuple[int, int]]
    track_settings: Sequence[tuple[int, Sequence[int]]]
    velocity_b_maps: Sequence[tuple[int, Sequence[Sequence[object]]]]
    source_document: object | None


class _ProjectedNote(NamedTuple):
    pitch: int
    vel: int
    start: float
    dur: float
    ntype: int
    velocity_b: int


@dataclass(frozen=True, slots=True)
class ExpectedGameInstrument:
    instrument_id: int
    volume: int
    settings: tuple[int, ...]
    notes: tuple[_ProjectedNote, ...]
    physical_note_counts: tuple[int, ...]
    source_group_index: int | None = None


@dataclass(frozen=True, slots=True)
class ExportExpectation:
    version: int
    owner_id: int
    character_name: str
    bpm: int
    time_signature: int
    instruments: tuple[ExpectedGameInstrument, ...]
    preserves_source_groups: bool = False
    expected_source_bytes: bytes | None = None

    @property
    def total_notes(self) -> int:
        return sum(len(instrument.notes) for instrument in self.instruments)


@dataclass(frozen=True, slots=True)
class ExportVerificationIssue:
    stage: str
    code: str
    path: str
    expected: object
    actual: object


@dataclass(frozen=True, slots=True)
class ExportVerificationReport:
    issues: tuple[ExportVerificationIssue, ...]
    omitted_issue_count: int
    expected_note_count: int
    actual_note_count: int
    expected_instrument_count: int
    actual_instrument_count: int
    checked_stages: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.issues and not self.omitted_issue_count

    @property
    def issue_count(self) -> int:
        return len(self.issues) + self.omitted_issue_count

    def stage_checked(self, stage: str) -> bool:
        return str(stage) in self.checked_stages

    def stage_matches(self, stage: str) -> bool:
        name = str(stage)
        return (
            self.stage_checked(name)
            and not self.omitted_issue_count
            and not any(issue.stage == name for issue in self.issues)
        )


class ExportVerificationError(RuntimeError):
    """A prepared export disagrees with its frozen editor expectation."""

    def __init__(self, report: ExportVerificationReport) -> None:
        self.report = report
        super().__init__(format_export_verification_report(report, limit=8))


class _IssueCollector:
    def __init__(self) -> None:
        self.items: list[ExportVerificationIssue] = []
        self.omitted = 0

    def add(
        self,
        stage: str,
        code: str,
        path: str,
        expected: object,
        actual: object,
    ) -> None:
        if path in _PRIVATE_PATHS:
            expected = actual = "<redacted>"
        issue = ExportVerificationIssue(
            str(stage),
            str(code),
            str(path),
            expected,
            actual,
        )
        if len(self.items) < MAX_REPORTED_ISSUES:
            self.items.append(issue)
        else:
            self.omitted += 1

    def extend(self, report: ExportVerificationReport) -> None:
        for issue in report.issues:
            self.add(
                issue.stage,
                issue.code,
                issue.path,
                issue.expected,
                issue.actual,
            )
        self.omitted += report.omitted_issue_count


def _validate_editor_note(note: object, path: str) -> None:
    try:
        pitch = int(getattr(note, "pitch"))
        velocity = int(getattr(note, "vel"))
        start = float(getattr(note, "start"))
        duration = float(getattr(note, "dur"))
        note_type = int(getattr(note, "ntype"))
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{path} is not a valid editor note: {exc}") from None
    if not 0 <= pitch <= 127:
        raise ValueError(f"{path}.pitch must be between 0 and 127")
    if not 0 <= velocity <= 127:
        raise ValueError(f"{path}.vel must be between 0 and 127")
    if not 0 <= note_type <= 255:
        raise ValueError(f"{path}.ntype must be between 0 and 255")
    if not math.isfinite(start) or start < 0.0:
        raise ValueError(f"{path}.start must be finite and non-negative")
    if not math.isfinite(duration):
        raise ValueError(f"{path}.dur must be finite")


def _velocity_b_lookup(
    records: Sequence[Sequence[object]] | None,
) -> dict[tuple[int, int, float, float, int], list[int]]:
    lookup: dict[tuple[int, int, float, float, int], list[int]] = defaultdict(list)
    for record in records or ():
        if len(record) < 6:
            continue
        identity = (
            int(record[0]),
            int(record[1]),
            float(record[2]),
            float(record[3]),
            int(record[4]),
        )
        velocity_b = int(record[5])
        if not 0 <= velocity_b <= 127:
            raise ValueError("source velocity_b must be between 0 and 127")
        lookup[identity].append(velocity_b)
    return lookup


def _project_track_notes(
    request: ExportRequestView,
    track: object,
    track_index: int,
    velocity_b_records: Sequence[Sequence[object]] | None,
) -> tuple[_ProjectedNote, ...]:
    duration_scale = float(getattr(track, "duration_scale", 1.0))
    if not math.isfinite(duration_scale):
        raise ValueError(
            f"direct_tracks[{track_index}].duration_scale must be finite"
        )
    raw_notes = tuple(getattr(track, "notes", ()))
    for note_index, note in enumerate(raw_notes):
        _validate_editor_note(
            note,
            f"direct_tracks[{track_index}].notes[{note_index}]",
        )

    second_velocities = _velocity_b_lookup(velocity_b_records)
    bound_notes: list[_ProjectedNote] = []
    for note in raw_notes:
        identity = (
            int(note.pitch),
            int(note.vel),
            float(note.start),
            float(note.dur),
            int(note.ntype),
        )
        candidates = second_velocities.get(identity)
        velocity_b = candidates.pop(0) if candidates else int(note.vel)
        bound_notes.append(_ProjectedNote(*identity, velocity_b))

    percussion = track_uses_percussion_pitch_semantics(track)
    semitones = int(request.pitch_plan.effective_track_semitones(track))
    projected = (
        tuple(bound_notes)
        if percussion else transpose_notes(bound_notes, semitones)
    )
    projected = tuple(
        note._replace(dur=max(1.0, float(note.dur) * duration_scale))
        for note in projected
    )
    if percussion:
        transformed = list(map_drum_notes(projected))
    else:
        transformed = list(clamp_notes(projected))

    articulation = dict(request.articulation_map).get(track_index)
    if articulation is not None and not percussion:
        transformed = [
            note._replace(ntype=int(articulation))
            for note in transformed
        ]

    return tuple(transformed)


def _effective_track_volumes(request: ExportRequestView) -> dict[int, int]:
    requested = dict(request.track_volumes)
    return {
        index: int(requested.get(
            index,
            getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME),
        ))
        for index, track in enumerate(request.direct_tracks)
    }


def _effective_velocity_b_maps(
    request: ExportRequestView,
) -> dict[int, Sequence[Sequence[object]]]:
    requested = dict(request.velocity_b_maps)
    return {
        index: requested.get(
            index,
            tuple(getattr(track, "bdo_source_note_records", ())),
        )
        for index, track in enumerate(request.direct_tracks)
        if index in requested or getattr(track, "bdo_source_note_records", ())
    }


def _shared_mix_values(
    request: ExportRequestView,
) -> tuple[dict[int, int], dict[int, tuple[int, ...]]]:
    volume_by_track = _effective_track_volumes(request)
    settings_by_track = {
        int(index): tuple(int(value) for value in values)
        for index, values in request.track_settings
    }
    volumes: dict[int, int] = {}
    settings: dict[int, tuple[int, ...]] = {}
    for index, track in enumerate(request.direct_tracks):
        instrument_id = serialized_game_instrument_id(track)
        value = volume_by_track[index]
        if instrument_id in volumes and volumes[instrument_id] != value:
            raise ValueError(
                f"instrument 0x{instrument_id:02x} has conflicting volumes"
            )
        volumes[instrument_id] = value
        if index in settings_by_track:
            value = settings_by_track[index]
            if len(value) != 8 or any(not 0 <= item <= 255 for item in value):
                raise ValueError("track settings must contain exactly eight bytes")
            if instrument_id in settings and settings[instrument_id] != value:
                raise ValueError(
                    f"instrument 0x{instrument_id:02x} has conflicting settings"
                )
            settings[instrument_id] = value
    return volumes, settings


def _uses_lossless_source(request: ExportRequestView) -> bool:
    """Mirror only the export route decision, not its semantic comparison."""

    source_document = getattr(request, "source_document", None)
    if (
        source_document is None
        or not request.conversion.is_neutral_export_transform()
        or not request.pitch_plan.is_neutral(request.direct_tracks)
        or request.articulation_map
    ):
        return False
    settings_by_track = dict(request.track_settings)
    volume_by_track = _effective_track_volumes(request)
    velocity_b_by_track = _effective_velocity_b_maps(request)
    default_settings = tuple(
        make_track_settings(request.reverb, request.delay, request.chorus)
    )
    return document_matches_logical_tracks(
        source_document,
        request.direct_tracks,
        instrument_ids=[
            serialized_game_instrument_id(track)
            for track in request.direct_tracks
        ],
        track_settings=[
            settings_by_track.get(index, default_settings)
            for index in range(len(request.direct_tracks))
        ],
        owner_id=request.owner_id,
        character_name=request.character_name,
        bpm=request.bpm,
        time_signature=request.time_signature,
        track_volumes=[
            volume_by_track[index]
            for index in range(len(request.direct_tracks))
        ],
        velocity_b_records=[
            velocity_b_by_track.get(index)
            for index in range(len(request.direct_tracks))
        ],
        percussion_semantics=[
            track_uses_percussion_pitch_semantics(track)
            for track in request.direct_tracks
        ],
    )


def _source_group_expectations(
    request: ExportRequestView,
) -> tuple[ExpectedGameInstrument, ...]:
    source_document = request.source_document
    expected: list[ExpectedGameInstrument] = []
    for group_index, source_group in enumerate(source_document.groups):
        if not source_group.tracks:
            raise ValueError("lossless source group has no physical tracks")
        template = source_group.tracks[0]
        notes = tuple(
            _ProjectedNote(
                int(note.pitch),
                int(note.velocity_a),
                float(note.start_ms),
                float(note.duration_ms),
                int(note.ntype),
                int(note.velocity_b),
            )
            for physical in source_group.tracks
            for note in physical.notes
        )
        expected.append(ExpectedGameInstrument(
            int(template.instrument_id),
            int(template.volume),
            tuple(template.settings.values),
            notes,
            tuple(len(physical.notes) for physical in source_group.tracks),
            group_index,
        ))
    return tuple(expected)


def _canonical_physical_note_counts(note_count: int) -> tuple[int, ...]:
    count = max(0, int(note_count))
    if not count:
        return (0, 0)
    full_tracks, remainder = divmod(count, MAX_NOTES_PER_TRACK)
    counts = [MAX_NOTES_PER_TRACK] * full_tracks
    if remainder:
        counts.append(remainder)
    counts.append(0)
    return tuple(counts)


def _canonical_expectations(
    request: ExportRequestView,
    projected_tracks: Sequence[tuple[_ProjectedNote, ...]],
    default_settings: tuple[int, ...],
) -> tuple[ExpectedGameInstrument, ...]:
    notes_by_instrument: dict[int, list[_ProjectedNote]] = {}
    for track, projected in zip(request.direct_tracks, projected_tracks):
        if not projected:
            continue
        instrument_id = serialized_game_instrument_id(track)
        notes_by_instrument.setdefault(instrument_id, []).extend(projected)
    if _DRUM_INSTRUMENT_ID in notes_by_instrument:
        notes_by_instrument[_DRUM_INSTRUMENT_ID] = list(
            normalize_drum_note_timing(notes_by_instrument[_DRUM_INSTRUMENT_ID])
        )
    for notes in notes_by_instrument.values():
        notes.sort(key=lambda note: note.start)
    if not notes_by_instrument:
        notes_by_instrument[DEFAULT_INSTRUMENT] = []

    volumes, settings = _shared_mix_values(request)
    return tuple(
        ExpectedGameInstrument(
            instrument_id,
            int(volumes.get(instrument_id, DEFAULT_TRACK_VOLUME)),
            settings.get(instrument_id, default_settings),
            tuple(notes),
            _canonical_physical_note_counts(len(notes)),
        )
        for instrument_id, notes in notes_by_instrument.items()
    )


def _canonical_name_roundtrip(value: str) -> str:
    encoded = value[: NAME_FIELD_SIZE // 2].encode("utf-16-le")
    return encoded[:NAME_FIELD_SIZE].decode(
        "utf-16-le",
        errors="replace",
    ).rstrip("\x00")


def build_export_expectation(request: ExportRequestView) -> ExportExpectation:
    """Build an independent game-semantic expectation from frozen tracks."""

    transform = request.conversion.export_transform_parameters()
    if any(
        (
            transform.get("vel_range") is not None,
            bool(transform.get("vel_floor")),
            bool(transform.get("vel_step")),
            bool(transform.get("vel_layered")),
        )
    ):
        raise ValueError(
            "velocity transforms must be materialized before export verification"
        )
    preserves_source_groups = _uses_lossless_source(request)
    bpm = int(
        transform.get("bpm_override")
        if transform.get("bpm_override") is not None
        else request.bpm
    )
    if (
        not preserves_source_groups
        and not BDO_BPM_MIN <= bpm <= BDO_BPM_MAX
    ):
        raise ValueError(
            f"export BPM must be between {BDO_BPM_MIN} and {BDO_BPM_MAX}"
        )
    owner_id = int(request.owner_id)
    if not 0 <= owner_id <= 0xFFFFFFFF:
        raise ValueError("owner_id must fit in an unsigned 32-bit field")
    time_signature = int(request.time_signature)
    if (
        not preserves_source_groups
        and not 1 <= time_signature <= 255
    ):
        raise ValueError("time signature numerator must be between 1 and 255")
    if preserves_source_groups:
        instruments = _source_group_expectations(request)
        expected_source_bytes = encode_score(
            request.source_document,
            mode="lossless",
        )
    else:
        character_name = str(request.character_name)
        if _canonical_name_roundtrip(character_name) != character_name:
            raise ValueError(
                "character_name cannot be represented losslessly in the "
                f"{NAME_FIELD_SIZE}-byte BDO v9 name field"
            )
        velocity_b_by_track = _effective_velocity_b_maps(request)
        projected_tracks = [
            _project_track_notes(
                request,
                track,
                index,
                velocity_b_by_track.get(index),
            )
            for index, track in enumerate(request.direct_tracks)
        ]
        default_settings = tuple(
            make_track_settings(request.reverb, request.delay, request.chorus)
        )
        instruments = _canonical_expectations(
            request,
            projected_tracks,
            default_settings,
        )
        expected_source_bytes = None
    return ExportExpectation(
        BDO_VERSION,
        owner_id,
        str(request.character_name),
        bpm,
        time_signature,
        instruments,
        preserves_source_groups,
        expected_source_bytes,
    )


def _compare_value(
    collector: _IssueCollector,
    stage: str,
    code: str,
    path: str,
    expected: object,
    actual: object,
) -> None:
    if expected != actual:
        collector.add(stage, code, path, expected, actual)


def _compare_header(
    expectation: ExportExpectation,
    document: BdoDocument,
    collector: _IssueCollector,
    stage: str,
) -> None:
    fields = (
        ("version", expectation.version, document.version),
        ("header.owner_id", expectation.owner_id, document.header.owner_id),
        (
            "header.character_name_1",
            expectation.character_name,
            document.header.character_name_1,
        ),
        (
            "header.character_name_2",
            expectation.character_name,
            document.header.character_name_2,
        ),
        ("header.bpm", expectation.bpm, document.header.bpm),
        (
            "header.time_signature",
            expectation.time_signature,
            document.header.time_signature,
        ),
    )
    for path, expected, actual in fields:
        _compare_value(
            collector,
            stage,
            "header.field_mismatch",
            path,
            expected,
            actual,
        )


def _note_identity(note: object) -> tuple[int, int, int, int]:
    velocity_a = (
        int(getattr(note, "vel"))
        if hasattr(note, "vel")
        else int(getattr(note, "velocity_a"))
    )
    return (
        int(getattr(note, "pitch")),
        int(getattr(note, "ntype")),
        velocity_a,
        int(getattr(note, "velocity_b")),
    )


def _note_times(note: object) -> tuple[float, float]:
    start = (
        float(getattr(note, "start"))
        if hasattr(note, "start")
        else float(getattr(note, "start_ms"))
    )
    duration = (
        float(getattr(note, "dur"))
        if hasattr(note, "dur")
        else float(getattr(note, "duration_ms"))
    )
    return start, duration


def _identity_path(prefix: str, identity: tuple[int, int, int, int]) -> str:
    pitch, note_type, velocity_a, velocity_b = identity
    return (
        f"{prefix}.notes[pitch={pitch},ntype={note_type},"
        f"velocity_a={velocity_a},velocity_b={velocity_b}]"
    )


def _time_values_match(expected: float, actual: float) -> bool:
    if expected == actual:
        return True
    return (
        math.isfinite(expected)
        and math.isfinite(actual)
        and abs(expected - actual) <= EXPORT_TIME_TOLERANCE_MS
    )


def _note_times_match(expected: object, actual: object) -> bool:
    expected_start, expected_duration = _note_times(expected)
    actual_start, actual_duration = _note_times(actual)
    return (
        _time_values_match(expected_start, actual_start)
        and _time_values_match(expected_duration, actual_duration)
    )


def _maximum_tolerance_pairs(
    expected_notes: Sequence[object],
    actual_notes: Sequence[object],
) -> tuple[list[tuple[object, object]], list[object], list[object]]:
    """Find a deterministic maximum matching inside the time tolerance."""

    expected_order = sorted(range(len(expected_notes)), key=lambda i: (
        *_note_times(expected_notes[i]),
        i,
    ))
    actual_order = sorted(range(len(actual_notes)), key=lambda i: (
        *_note_times(actual_notes[i]),
        i,
    ))
    if len(expected_order) == len(actual_order):
        ordered_pairs = [
            (expected_notes[left], actual_notes[right])
            for left, right in zip(expected_order, actual_order)
        ]
        if all(_note_times_match(*pair) for pair in ordered_pairs):
            return ordered_pairs, [], []

    actual_rank = {index: rank for rank, index in enumerate(actual_order)}
    candidates = [
        sorted(
            (
                right for right, actual in enumerate(actual_notes)
                if _note_times_match(expected, actual)
            ),
            key=actual_rank.__getitem__,
        )
        for expected in expected_notes
    ]
    roots = sorted(expected_order, key=lambda i: (len(candidates[i]), i))
    match_left = [-1] * len(expected_notes)
    match_right = [-1] * len(actual_notes)
    for root in roots:
        _augment_time_matching(root, candidates, match_left, match_right)
    pairs = [
        (expected_notes[left], actual_notes[right])
        for left, right in enumerate(match_left)
        if right >= 0
    ]
    unmatched_expected = [
        expected_notes[index]
        for index, right in enumerate(match_left)
        if right < 0
    ]
    unmatched_actual = [
        actual_notes[index]
        for index, left in enumerate(match_right)
        if left < 0
    ]
    return pairs, unmatched_expected, unmatched_actual


def _augment_time_matching(
    root: int,
    candidates: Sequence[Sequence[int]],
    match_left: list[int],
    match_right: list[int],
) -> bool:
    """Add one augmenting path without recursion or order-based pairing."""

    queue = [root]
    seen_left = {root}
    parent_right: dict[int, int] = {}
    for left in queue:
        for right in candidates[left]:
            if right in parent_right:
                continue
            parent_right[right] = left
            paired_left = match_right[right]
            if paired_left < 0:
                while right >= 0:
                    path_left = parent_right[right]
                    previous_right = match_left[path_left]
                    match_left[path_left] = right
                    match_right[right] = path_left
                    right = previous_right
                return True
            if paired_left not in seen_left:
                seen_left.add(paired_left)
                queue.append(paired_left)
    return False


def _compare_note_lists(
    expected_notes: Sequence[_ProjectedNote],
    actual_notes: Sequence[object],
    collector: _IssueCollector,
    stage: str,
    prefix: str,
) -> None:
    _compare_value(
        collector,
        stage,
        "notes.count_mismatch",
        f"{prefix}.notes.length",
        len(expected_notes),
        len(actual_notes),
    )
    expected_by_identity: dict[
        tuple[int, int, int, int], list[object]
    ] = defaultdict(list)
    actual_by_identity: dict[
        tuple[int, int, int, int], list[object]
    ] = defaultdict(list)
    for note in expected_notes:
        expected_by_identity[_note_identity(note)].append(note)
    for note in actual_notes:
        actual_by_identity[_note_identity(note)].append(note)

    identities = sorted(set(expected_by_identity) | set(actual_by_identity))
    for identity in identities:
        expected_bucket = expected_by_identity.get(identity, [])
        actual_bucket = actual_by_identity.get(identity, [])
        identity_path = _identity_path(prefix, identity)
        _compare_value(
            collector,
            stage,
            "notes.identity_count_mismatch",
            f"{identity_path}.count",
            len(expected_bucket),
            len(actual_bucket),
        )
        _pairs, unmatched_expected, unmatched_actual = (
            _maximum_tolerance_pairs(expected_bucket, actual_bucket)
        )
        unmatched_expected.sort(key=_note_times)
        unmatched_actual.sort(key=_note_times)
        for note_index, (expected, actual) in enumerate(zip(
            unmatched_expected,
            unmatched_actual,
        )):
            note_path = f"{identity_path}[{note_index}]"
            expected_start, expected_duration = _note_times(expected)
            actual_start, actual_duration = _note_times(actual)
            for field, expected_value, actual_value in (
                ("start_ms", expected_start, actual_start),
                ("duration_ms", expected_duration, actual_duration),
            ):
                if not _time_values_match(expected_value, actual_value):
                    collector.add(
                        stage,
                        f"notes.{field}_mismatch",
                        f"{note_path}.{field}",
                        expected_value,
                        actual_value,
                    )


def _compare_expected_group(
    expected: ExpectedGameInstrument,
    group: object,
    collector: _IssueCollector,
    stage: str,
    prefix: str,
) -> None:
    tracks = tuple(group.tracks)
    fields = (
        (
            "instrument_mismatch",
            f"{prefix}.instrument_id",
            (expected.instrument_id,),
            tuple(sorted({int(track.instrument_id) for track in tracks})),
        ),
        (
            "volume_mismatch",
            f"{prefix}.volume",
            (expected.volume,),
            tuple(sorted({int(track.volume) for track in tracks})),
        ),
        (
            "settings_mismatch",
            f"{prefix}.settings",
            (expected.settings,),
            tuple(sorted({
                tuple(track.settings.values) for track in tracks
            })),
        ),
        (
            "physical_layout_mismatch",
            f"{prefix}.physical_note_counts",
            expected.physical_note_counts,
            tuple(len(track.notes) for track in tracks),
        ),
    )
    for code, path, expected_value, actual_value in fields:
        _compare_value(
            collector,
            stage,
            f"groups.{code}",
            path,
            expected_value,
            actual_value,
        )
    if len(tracks) == len(expected.physical_note_counts):
        offset = 0
        for track_index, (track, note_count) in enumerate(
            zip(tracks, expected.physical_note_counts)
        ):
            expected_chunk = expected.notes[offset:offset + note_count]
            offset += note_count
            _compare_note_lists(
                expected_chunk,
                track.notes,
                collector,
                stage,
                f"{prefix}.tracks[{track_index}]",
            )
    else:
        _compare_note_lists(
            expected.notes,
            [note for track in tracks for note in track.notes],
            collector,
            stage,
            prefix,
        )


def _compare_groups(
    expectation: ExportExpectation,
    document: BdoDocument,
    collector: _IssueCollector,
    stage: str,
) -> tuple[int, int]:
    _compare_value(
        collector,
        stage,
        "groups.count_mismatch",
        "groups.length",
        len(expectation.instruments),
        len(document.groups),
    )
    for expected_index, expected in enumerate(expectation.instruments):
        group_index = (
            int(expected.source_group_index)
            if expected.source_group_index is not None
            else expected_index
        )
        if not 0 <= group_index < len(document.groups):
            collector.add(
                stage,
                "groups.missing",
                f"groups[{group_index}]",
                "present",
                "missing",
            )
            continue
        _compare_expected_group(
            expected,
            document.groups[group_index],
            collector,
            stage,
            f"groups[{group_index}]",
        )
    return document.total_notes, len(document.groups)


def _compare_canonical_metadata(
    expectation: ExportExpectation,
    document: BdoDocument,
    collector: _IssueCollector,
    stage: str,
) -> None:
    if expectation.preserves_source_groups:
        return
    derived_tag = ",".join(
        str(instrument.instrument_id)
        for instrument in expectation.instruments
    )
    trailing_offset = getattr(document, "_trailing_offset", None)
    expected_trailing_length = (
        (-int(trailing_offset)) % 8
        if trailing_offset is not None else 0
    )
    fields = (
        (
            "wire.header_reserved",
            "header.reserved",
            b"\x00" * 4,
            document.header.reserved,
        ),
        (
            "wire.instrument_tag",
            "header.instrument_tag",
            derived_tag,
            document.header.instrument_tag,
        ),
        (
            "wire.header_padding",
            "header.padding",
            False,
            any(document.header.padding),
        ),
        (
            "wire.trailing_data",
            "trailing_data",
            (expected_trailing_length, False),
            (len(document.trailing_data), any(document.trailing_data)),
        ),
    )
    for code, path, expected, actual in fields:
        _compare_value(collector, stage, code, path, expected, actual)
    for group_index, group in enumerate(document.groups):
        for track_index, track in enumerate(group.tracks):
            if track.extra_data:
                collector.add(
                    stage,
                    "wire.track_extra_data",
                    f"groups[{group_index}].tracks[{track_index}].extra_data",
                    0,
                    len(track.extra_data),
                )


def _compare_canonical_note_order(
    expectation: ExportExpectation,
    document: BdoDocument,
    collector: _IssueCollector,
    stage: str,
) -> None:
    if expectation.preserves_source_groups:
        return
    for group_index, group in enumerate(document.groups):
        previous_start: float | None = None
        for track_index, track in enumerate(group.tracks):
            for note_index, note in enumerate(track.notes):
                start = float(note.start_ms)
                if (
                    previous_start is not None
                    and math.isfinite(previous_start)
                    and math.isfinite(start)
                    and start + EXPORT_TIME_TOLERANCE_MS < previous_start
                ):
                    collector.add(
                        stage,
                        "wire.note_order_invalid",
                        (
                            f"groups[{group_index}].tracks[{track_index}]"
                            f".notes[{note_index}].start_ms"
                        ),
                        "non-decreasing canonical start_ms order",
                        start,
                    )
                    break
                previous_start = start
            else:
                continue
            break


def verify_export_bytes(
    expectation: ExportExpectation,
    data: bytes,
    *,
    stage: str = "prepared",
) -> ExportVerificationReport:
    """Decode and compare one BDO byte sequence with an editor expectation."""

    collector = _IssueCollector()
    if (
        expectation.expected_source_bytes is not None
        and data != expectation.expected_source_bytes
    ):
        collector.add(
            stage,
            "wire.source_bytes_mismatch",
            "wire.source_reuse",
            _wire_fingerprint(expectation.expected_source_bytes),
            _wire_fingerprint(data),
        )
    try:
        document = decode_score(bytes(data))
    except Exception as exc:
        collector.add(
            stage,
            "wire.decode_failed",
            "wire",
            "decodable BDO v9",
            type(exc).__name__,
        )
        return ExportVerificationReport(
            tuple(collector.items),
            collector.omitted,
            expectation.total_notes,
            0,
            len(expectation.instruments),
            0,
            (stage,),
        )

    for issue in validate_score(document):
        if issue.severity == "error":
            collector.add(
                stage,
                f"wire.{issue.code}",
                issue.path,
                "valid BDO v9 structure",
                issue.code,
            )
    if not expectation.preserves_source_groups:
        for group_index, group in enumerate(document.groups):
            for track_index, track in enumerate(group.tracks):
                for note_index, note in enumerate(track.notes):
                    if (
                        not math.isfinite(float(note.start_ms))
                        or float(note.start_ms) < 0.0
                        or not math.isfinite(float(note.duration_ms))
                        or float(note.duration_ms) <= 0.0
                    ):
                        collector.add(
                            stage,
                            "wire.note_time_invalid",
                            (
                                f"groups[{group_index}].tracks[{track_index}]"
                                f".notes[{note_index}]"
                            ),
                            "finite non-negative start and positive duration",
                            (note.start_ms, note.duration_ms),
                        )
    _compare_header(expectation, document, collector, stage)
    _compare_canonical_metadata(expectation, document, collector, stage)
    _compare_canonical_note_order(expectation, document, collector, stage)
    actual_note_count, actual_instrument_count = _compare_groups(
        expectation,
        document,
        collector,
        stage,
    )
    return ExportVerificationReport(
        tuple(collector.items),
        collector.omitted,
        expectation.total_notes,
        actual_note_count,
        len(expectation.instruments),
        actual_instrument_count,
        (stage,),
    )


def _wire_fingerprint(data: bytes) -> str:
    return f"{len(data)} bytes sha256:{sha256(data).hexdigest()[:16]}"


def verify_published_export(
    expectation: ExportExpectation,
    prepared_data: bytes,
    primary_path: str | Path,
    installed_path: str | Path | None = None,
    *,
    prepared_report: ExportVerificationReport | None = None,
) -> ExportVerificationReport:
    """Verify prepared bytes, the primary file, and an optional game copy."""

    base_report = prepared_report or verify_export_bytes(
        expectation,
        prepared_data,
        stage="prepared",
    )
    collector = _IssueCollector()
    collector.extend(base_report)
    stages = list(base_report.checked_stages)
    actual_note_count = base_report.actual_note_count
    actual_instrument_count = base_report.actual_instrument_count

    primary_data: bytes | None = None
    try:
        primary_data = Path(primary_path).read_bytes()
    except Exception as exc:
        collector.add(
            "primary",
            "publication.primary_read_failed",
            "publication.primary",
            "readable primary file",
            type(exc).__name__,
        )
    stages.append("primary")
    if primary_data is not None:
        if primary_data != prepared_data:
            collector.add(
                "primary",
                "publication.primary_bytes_mismatch",
                "publication.primary",
                _wire_fingerprint(prepared_data),
                _wire_fingerprint(primary_data),
            )
        primary_report = verify_export_bytes(
            expectation,
            primary_data,
            stage="primary",
        )
        collector.extend(primary_report)
        actual_note_count = primary_report.actual_note_count
        actual_instrument_count = primary_report.actual_instrument_count

    if installed_path:
        stages.append("game_copy")
        try:
            game_data = Path(installed_path).read_bytes()
        except Exception as exc:
            collector.add(
                "game_copy",
                "publication.game_copy_read_failed",
                "publication.game_copy",
                "readable installed file",
                type(exc).__name__,
            )
        else:
            reference_data = primary_data if primary_data is not None else prepared_data
            if game_data != reference_data:
                collector.add(
                    "game_copy",
                    "publication.game_copy_bytes_mismatch",
                    "publication.game_copy",
                    _wire_fingerprint(reference_data),
                    _wire_fingerprint(game_data),
                )
            game_report = verify_export_bytes(
                expectation,
                game_data,
                stage="game_copy",
            )
            collector.extend(game_report)

    return ExportVerificationReport(
        tuple(collector.items),
        collector.omitted,
        expectation.total_notes,
        actual_note_count,
        len(expectation.instruments),
        actual_instrument_count,
        tuple(dict.fromkeys(stages)),
    )


def format_export_verification_report(
    report: ExportVerificationReport,
    *,
    limit: int = 20,
) -> str:
    """Return a bounded, path-free diagnostic suitable for the crash log."""

    if report.matches:
        return (
            "export verification passed: "
            f"{report.actual_instrument_count} instruments, "
            f"{report.actual_note_count} notes, "
            f"stages={','.join(report.checked_stages)}"
        )
    lines = [
        "export verification failed: "
        f"{report.issue_count} issue(s), stages={','.join(report.checked_stages)}"
    ]
    for issue in report.issues[: max(0, int(limit))]:
        lines.append(
            f"- [{issue.stage}] {issue.code} {issue.path}: "
            f"{issue.expected!r} -> {issue.actual!r}"
        )
    hidden = max(0, report.issue_count - min(len(report.issues), max(0, int(limit))))
    if hidden:
        lines.append(f"- ... {hidden} additional issue(s) omitted")
    return "\n".join(lines)


__all__ = [
    "EXPORT_TIME_TOLERANCE_MS",
    "ExpectedGameInstrument",
    "ExportExpectation",
    "ExportRequestView",
    "ExportVerificationError",
    "ExportVerificationIssue",
    "ExportVerificationReport",
    "build_export_expectation",
    "format_export_verification_report",
    "verify_export_bytes",
    "verify_published_export",
]
