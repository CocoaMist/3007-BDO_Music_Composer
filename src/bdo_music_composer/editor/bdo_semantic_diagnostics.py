"""Read-only, explainable BDO authoring diagnostics and semantic diffs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from bdo_music_composer.editor.editor_models import BDO_DRUM_MAX, BDO_DRUM_MIN


MAX_BDO_NOTES_PER_PHYSICAL_TRACK = 730


@dataclass(frozen=True, slots=True)
class SemanticDiagnostic:
    code: str
    severity: str
    summary: str
    explanation: str
    track_id: int | None = None
    note_indices: tuple[int, ...] = ()
    confidence: float = 1.0
    evidence_status: str = "verified"
    suggestion: str = ""


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    added: int
    removed: int
    unchanged: int
    pitch_delta: Counter
    timing_changed: int
    velocity_changed: int
    articulation_changed: int


def _note_key(note: object) -> tuple[int, int, int, int, int]:
    return (
        int(getattr(note, "pitch", 0)),
        int(getattr(note, "vel", 0)),
        round(float(getattr(note, "start", 0.0)) * 1000),
        round(float(getattr(note, "dur", 0.0)) * 1000),
        int(getattr(note, "ntype", 0)),
    )


def semantic_diff(before: Iterable[object], after: Iterable[object]) -> SemanticDiff:
    """Compare two note projections without mutating or guessing identity."""

    left = Counter(_note_key(note) for note in before)
    right = Counter(_note_key(note) for note in after)
    common = left & right
    removed_values = list((left - common).elements())
    added_values = list((right - common).elements())
    pair_count = min(len(removed_values), len(added_values))
    timing_changed = velocity_changed = articulation_changed = 0
    pitch_delta: Counter[int] = Counter()
    for old, new in zip(removed_values[:pair_count], added_values[:pair_count]):
        pitch_delta[new[0] - old[0]] += 1
        timing_changed += int(old[2:4] != new[2:4])
        velocity_changed += int(old[1] != new[1])
        articulation_changed += int(old[4] != new[4])
    return SemanticDiff(
        added=sum((right - common).values()),
        removed=sum((left - common).values()),
        unchanged=sum(common.values()),
        pitch_delta=pitch_delta,
        timing_changed=timing_changed,
        velocity_changed=velocity_changed,
        articulation_changed=articulation_changed,
    )


def diagnose_bdo_authoring(tracks: Sequence[object]) -> tuple[SemanticDiagnostic, ...]:
    """Return deterministic advice; never rewrite the editor model."""

    diagnostics: list[SemanticDiagnostic] = []
    for track in tracks:
        track_id = int(getattr(track, "track_id", -1))
        notes = tuple(getattr(track, "notes", ()))
        if len(notes) > MAX_BDO_NOTES_PER_PHYSICAL_TRACK:
            pieces = (len(notes) + MAX_BDO_NOTES_PER_PHYSICAL_TRACK - 1) // MAX_BDO_NOTES_PER_PHYSICAL_TRACK
            diagnostics.append(SemanticDiagnostic(
                "physical-track-split",
                "info",
                f"Track will be serialized as {pieces} physical tracks.",
                "BDO v9 physical tracks contain at most 730 notes; export performs a deterministic split.",
                track_id,
                suggestion="Review phrase boundaries around each split point.",
            ))
        invalid_duration = tuple(
            index for index, note in enumerate(notes)
            if float(getattr(note, "dur", 0.0)) <= 0.0
        )
        if invalid_duration:
            diagnostics.append(SemanticDiagnostic(
                "non-positive-duration",
                "error",
                "Notes with non-positive duration cannot form a playable score.",
                "Duration must remain positive through preview, autosave, and BDO export.",
                track_id,
                invalid_duration,
                suggestion="Resize or remove the marked notes explicitly.",
            ))
        if bool(getattr(track, "is_percussion", False)) and int(
            getattr(track, "bdo_instrument_id", -1)
        ) == 0x0D:
            invalid_drums = tuple(
                index for index, note in enumerate(notes)
                if not BDO_DRUM_MIN <= int(getattr(note, "pitch", -1)) <= BDO_DRUM_MAX
                or int(getattr(note, "ntype", 0)) != 99
            )
            if invalid_drums:
                diagnostics.append(SemanticDiagnostic(
                    "non-canonical-drum-note",
                    "warning",
                    "Drum-set notes are outside canonical BDO lanes or articulation type.",
                    "Canonical drum-set export uses pitches 48–64 and ntype=99.",
                    track_id,
                    invalid_drums,
                    suggestion="Use Conversion Check to review the explicit drum mapping.",
                ))
        starts: Counter[int] = Counter(
            round(float(getattr(note, "start", 0.0))) for note in notes
        )
        peak_onset = max(starts.values(), default=0)
        if peak_onset >= 24:
            diagnostics.append(SemanticDiagnostic(
                "dense-onset-cluster",
                "info",
                f"A single millisecond contains {peak_onset} note onsets.",
                "Dense simultaneous attacks may increase preview voice pressure and reduce game clarity.",
                track_id,
                confidence=0.75,
                evidence_status="inferred",
                suggestion="Audition the passage before changing orchestration.",
            ))
    return tuple(diagnostics)


def semantic_readiness_score(diagnostics: Sequence[SemanticDiagnostic]) -> int:
    """Return an explainable 0–100 readiness indicator, not game A/B proof."""

    penalty = {"error": 25, "warning": 10, "info": 2}
    return max(0, 100 - sum(penalty[item.severity] for item in diagnostics))


__all__ = [
    "MAX_BDO_NOTES_PER_PHYSICAL_TRACK",
    "SemanticDiagnostic",
    "SemanticDiff",
    "diagnose_bdo_authoring",
    "semantic_diff",
    "semantic_readiness_score",
]
