"""Pure editor guidance derived from the checked-in BDO game profile.

This module deliberately separates three different facts which used to be
easy for UI code to conflate:

* a pitch accepted by verified game-score evidence;
* a pitch for which the recovered Wwise bank has a preview zone; and
* a pitch range which is convenient to show when an editor opens.

Only the first fact may be used as a hard validity check.  The recommended
range and Wwise coverage are display/preview hints and must never repitch,
delete, clamp, or otherwise rewrite a :class:`bdo_midi.Note`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from bdo_music_composer.editor.bdo_articulation_profiles import profile_for
from bdo_music_composer.audio.bdo_instrument_samples import bank_for_instrument, preview_route_ntype
from bdo_midi import BDO_INSTRUMENT_NAMES, BDO_NOTE_MAX, BDO_NOTE_MIN
from bdo_music_composer.core.bdo_profile import BdoProfile, InstrumentRule, load_bdo_profile
from bdo_music_composer.core.project_paths import PROFILES_DIR, WWISE_MIDI_MAP_PATH


INSTRUMENT_ADAPTATION_VERSION = "bdo-instrument-adaptation-v1"
DEFAULT_PROFILE_PATH = PROFILES_DIR / "bdo_global_v9.json"


class GameInstrumentFamily(StrEnum):
    """Stable IDs matching the game's four composition instrument tabs."""

    WIND = "wind"
    STRINGS = "strings"
    KEYS = "keys"
    PERCUSSION = "percussion"


class ArrangementRole(StrEnum):
    MELODY = "melody"
    BASS = "bass"
    CHORD = "chord"
    HARMONY = "harmony"
    RHYTHM = "rhythm"
    PERCUSSION = "percussion"
    ARPEGGIO = "arpeggio"


class RouteEvidence(StrEnum):
    """What the checked-in Wwise structure proves about one note route."""

    FULL = "wwise_full_range"
    PARTIAL = "wwise_partial_range"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DrumLane:
    pitch: int
    label: str
    evidence_status: str = "verified"


@dataclass(frozen=True, slots=True)
class ArticulationAdaptation:
    """One declared BDO ntype and its non-authoritative preview evidence."""

    ntype: int
    label: str
    native_route_pitches: frozenset[int]
    route_evidence: RouteEvidence
    audible_behavior_verified: bool
    auto_apply_allowed: bool

    def native_preview_supports(self, pitch: int) -> bool | None:
        """Return Wwise-zone support, or ``None`` when route data is unknown."""

        if self.route_evidence is RouteEvidence.UNKNOWN:
            return None
        return int(pitch) in self.native_route_pitches


@dataclass(frozen=True, slots=True)
class InstrumentEditorAdaptation:
    """Read-only guidance for one logical editor instrument.

    ``legal_pitches`` is ``None`` when the profile is not backed by verified
    game-score evidence.  In that case callers must not reject a note merely
    because it falls outside ``recommended_pitches`` or ``preview_pitches``.
    """

    instrument_id: int
    display_name: str
    family: GameInstrumentFamily
    primary_role: ArrangementRole
    roles: tuple[ArrangementRole, ...]
    visual_key: str
    legal_pitches: frozenset[int] | None
    legal_pitch_evidence_status: str
    legal_pitch_evidence_source: str
    preview_pitches: frozenset[int]
    recommended_pitches: frozenset[int]
    recommended_visible_range: tuple[int, int]
    compress_invalid_pitches: bool
    drum_lanes: tuple[DrumLane, ...]
    default_ntype: int
    articulations: tuple[ArticulationAdaptation, ...]
    role_evidence_status: str = "inferred"

    def legal_pitch_support(self, pitch: int) -> bool | None:
        """Return game legality without treating sample coverage as a rule."""

        if self.legal_pitches is None:
            return None
        return int(pitch) in self.legal_pitches

    def preview_pitch_support(self, pitch: int) -> bool | None:
        """Return structural Wwise coverage, or ``None`` without a mapping."""

        if not self.preview_pitches:
            return None
        return int(pitch) in self.preview_pitches

    def should_render_pitch_row(self, pitch: int) -> bool:
        """Whether a piano-roll row may be retained in a compressed view.

        Unknown/approximate ranges always remain visible.  Consequently this
        helper is incapable of hiding a potentially legal note.
        """

        support = self.legal_pitch_support(pitch)
        return not self.compress_invalid_pitches or support is not False

    def drum_lane_label(self, pitch: int) -> str | None:
        value = int(pitch)
        return next(
            (lane.label for lane in self.drum_lanes if lane.pitch == value),
            None,
        )


@dataclass(frozen=True, slots=True)
class GameDraftAdaptationReport:
    """Read-only game-fit report for one editable draft.

    The 730-note value is a physical v9 track-chunk boundary.  Crossing it is
    reported as automatic publication splitting, never as a song quota or a
    reason to delete notes.
    """

    instrument_id: int
    note_count: int
    track_chunk_limit: int
    track_chunk_count: int
    invalid_pitch_indices: tuple[int, ...]
    unsupported_articulation_indices: tuple[int, ...]
    invalid_timing_indices: tuple[int, ...]
    invalid_velocity_indices: tuple[int, ...]
    pitch_evidence_known: bool

    @property
    def blocking_issue_count(self) -> int:
        return sum(
            len(indices)
            for indices in (
                self.invalid_pitch_indices,
                self.unsupported_articulation_indices,
                self.invalid_timing_indices,
                self.invalid_velocity_indices,
            )
        )

    @property
    def ready(self) -> bool:
        return self.blocking_issue_count == 0


@dataclass(frozen=True, slots=True)
class _InstrumentSemantics:
    family: GameInstrumentFamily
    primary_role: ArrangementRole
    roles: tuple[ArrangementRole, ...]
    visual_key: str


def _semantics(
    family: GameInstrumentFamily,
    primary: ArrangementRole,
    visual_key: str,
    *secondary: ArrangementRole,
) -> _InstrumentSemantics:
    roles = tuple(dict.fromkeys((primary, *secondary)))
    return _InstrumentSemantics(family, primary, roles, visual_key)


# Functional roles are arrangement suggestions, not source-instrument
# recognition.  The stable visual keys resolve only to app-owned or explicitly
# user-configured artwork; they are intentionally not game-asset paths.
_INSTRUMENT_SEMANTICS: Mapping[int, _InstrumentSemantics] = {
    0x00: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.guitar.acoustic", ArrangementRole.MELODY, ArrangementRole.RHYTHM),
    0x01: _semantics(GameInstrumentFamily.WIND, ArrangementRole.MELODY, "wind.flute"),
    0x02: _semantics(GameInstrumentFamily.WIND, ArrangementRole.MELODY, "wind.recorder"),
    0x04: _semantics(GameInstrumentFamily.PERCUSSION, ArrangementRole.PERCUSSION, "percussion.hand_drum", ArrangementRole.RHYTHM),
    0x05: _semantics(GameInstrumentFamily.PERCUSSION, ArrangementRole.PERCUSSION, "percussion.cymbals", ArrangementRole.RHYTHM),
    0x06: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.harp", ArrangementRole.ARPEGGIO, ArrangementRole.MELODY),
    0x07: _semantics(GameInstrumentFamily.KEYS, ArrangementRole.CHORD, "keys.piano", ArrangementRole.MELODY, ArrangementRole.HARMONY),
    0x08: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.MELODY, "strings.violin", ArrangementRole.HARMONY),
    0x0A: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.guitar.acoustic.pro", ArrangementRole.MELODY, ArrangementRole.RHYTHM),
    0x0B: _semantics(GameInstrumentFamily.WIND, ArrangementRole.MELODY, "wind.flute.pro", ArrangementRole.HARMONY),
    0x0D: _semantics(GameInstrumentFamily.PERCUSSION, ArrangementRole.PERCUSSION, "percussion.drum_set", ArrangementRole.RHYTHM),
    0x0E: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.BASS, "strings.bass.electric", ArrangementRole.RHYTHM),
    0x0F: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.BASS, "strings.contrabass", ArrangementRole.HARMONY),
    0x10: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.harp.pro", ArrangementRole.ARPEGGIO, ArrangementRole.MELODY),
    0x11: _semantics(GameInstrumentFamily.KEYS, ArrangementRole.CHORD, "keys.piano.pro", ArrangementRole.MELODY, ArrangementRole.HARMONY),
    0x12: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.MELODY, "strings.violin.pro", ArrangementRole.HARMONY),
    0x13: _semantics(GameInstrumentFamily.PERCUSSION, ArrangementRole.MELODY, "percussion.handpan", ArrangementRole.PERCUSSION, ArrangementRole.RHYTHM),
    0x14: _semantics(GameInstrumentFamily.KEYS, ArrangementRole.MELODY, "keys.synth.saw", ArrangementRole.CHORD, ArrangementRole.BASS),
    0x18: _semantics(GameInstrumentFamily.KEYS, ArrangementRole.MELODY, "keys.synth.sine", ArrangementRole.CHORD, ArrangementRole.BASS),
    0x1C: _semantics(GameInstrumentFamily.KEYS, ArrangementRole.MELODY, "keys.synth.square", ArrangementRole.CHORD, ArrangementRole.BASS),
    0x20: _semantics(GameInstrumentFamily.KEYS, ArrangementRole.MELODY, "keys.synth.triangle", ArrangementRole.CHORD, ArrangementRole.BASS),
    0x24: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.guitar.electric.clean", ArrangementRole.MELODY, ArrangementRole.RHYTHM),
    0x25: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.guitar.electric.drive", ArrangementRole.MELODY, ArrangementRole.RHYTHM),
    0x26: _semantics(GameInstrumentFamily.STRINGS, ArrangementRole.CHORD, "strings.guitar.electric.distortion", ArrangementRole.MELODY, ArrangementRole.RHYTHM),
    0x27: _semantics(GameInstrumentFamily.WIND, ArrangementRole.MELODY, "wind.clarinet", ArrangementRole.HARMONY),
    0x28: _semantics(GameInstrumentFamily.WIND, ArrangementRole.HARMONY, "wind.horn", ArrangementRole.MELODY, ArrangementRole.CHORD),
}


_ADVANCED_ARTICULATIONS: Mapping[int, tuple[tuple[int, str], ...]] = {
    0x0A: ((0, "延音"), (3, "向上滑动"), (12, "滑弦下降"), (13, "弱音"), (14, "泛音"), (15, "三连音")),
    0x0E: ((0, "延音"), (3, "向上滑动"), (12, "滑弦下降"), (13, "弱音"), (14, "泛音"), (16, "滑音"), (22, "拍弦"), (23, "滑音上升"), (24, "X-音符")),
    0x0F: ((0, "延音"), (3, "向上滑动"), (12, "滑弦下降"), (13, "弱音"), (14, "泛音"), (23, "滑音上升")),
    0x0B: ((0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (15, "三连音")),
    0x10: ((0, "延音"), (9, "大调和弦"), (10, "和弦小调"), (16, "滑音")),
    0x11: ((0, "延音"), (11, "延音踏板")),
    0x12: ((0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (5, "颤音大调"), (6, "颤音"), (7, "颤音 2"), (8, "大调颤音")),
    0x14: ((0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (5, "颤音大调"), (6, "颤音"), (7, "颤音 2"), (8, "颤音小调 2"), (17, "颤音 3"), (18, "大调颤音"), (19, "颤音 4"), (20, "维持滤波器"), (21, "滤波铜管")),
    0x18: ((0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (5, "颤音大调"), (6, "颤音"), (7, "颤音 2"), (8, "颤音小调 2"), (17, "颤音 3"), (18, "大调颤音"), (19, "颤音 4")),
    0x1C: ((0, "延音"), (1, "基本")),
    0x20: ((0, "延音"), (1, "基本")),
    0x24: ((0, "延音"), (6, "颤音"), (13, "弱音"), (14, "泛音"), (25, "FX(C2~G2)")),
    0x25: ((0, "延音"), (6, "颤音"), (13, "弱音"), (14, "泛音"), (25, "FX(C2~G2)")),
    0x26: ((0, "延音"), (6, "颤音"), (13, "弱音"), (14, "泛音"), (25, "FX(C2~G2)")),
    0x27: ((0, "延音"), (4, "颤音小调"), (7, "颤音小调 2"), (8, "大调颤音"), (15, "三连音"), (26, "SusPiano"), (27, "SusMezzoForte"), (28, "SusForte")),
    0x28: ((0, "延音"), (3, "向上滑动"), (4, "颤音小调"), (12, "滑弦下降"), (26, "SusPiano"), (27, "SusMezzoForte"), (28, "SusForte")),
}


_DRUM_SET_LANES = (
    DrumLane(48, "Kck"),
    DrumLane(49, "SnrSide"),
    DrumLane(50, "SnrHit"),
    DrumLane(51, "RimShot"),
    DrumLane(52, "SnrFlam"),
    DrumLane(53, "Tom1"),
    DrumLane(54, "HihatC"),
    DrumLane(55, "Tom2"),
    DrumLane(56, "HatPdl"),
    DrumLane(57, "Tom3"),
    DrumLane(58, "HihatO"),
    DrumLane(59, "Tom4"),
    DrumLane(60, "Tom5"),
    DrumLane(61, "CymCrsh"),
    DrumLane(62, "CymRide"),
    DrumLane(63, "SnrRollS"),
    DrumLane(64, "SnrRollL"),
)


# These are native Event trigger ranges recovered from the reviewed Wwise
# banks, not general instrument ranges.  Outside them the game bank exposes no
# source for the requested articulation, so an editor must not create the
# otherwise wire-valid but silent/misrouted combination.
_ARTICULATION_TRIGGER_PITCHES: Mapping[tuple[int, int], frozenset[int]] = {
    (0x24, 25): frozenset(range(36, 44)),
    (0x25, 25): frozenset(range(36, 44)),
    (0x26, 25): frozenset(range(36, 44)),
    (0x28, 3): frozenset(range(24, 73)),
}


def articulation_trigger_pitches(
    instrument_id: int,
    ntype: int,
) -> frozenset[int] | None:
    """Return a strict native Event range, or ``None`` when unrestricted.

    ``None`` deliberately means that no narrower trigger range is declared;
    callers must continue to apply the instrument's normal legality rules.
    """

    return _ARTICULATION_TRIGGER_PITCHES.get(
        (int(instrument_id), int(ntype))
    )


def articulation_supports_pitch(
    instrument_id: int,
    ntype: int,
    pitch: int,
) -> bool:
    """Whether one articulation may be authored at the requested pitch."""

    trigger_pitches = articulation_trigger_pitches(instrument_id, ntype)
    return trigger_pitches is None or int(pitch) in trigger_pitches


def articulation_pairs_by_instrument() -> dict[int, tuple[tuple[int, str], ...]]:
    """Return the canonical editor articulation menu without Qt objects."""

    result: dict[int, tuple[tuple[int, str], ...]] = {}
    for instrument_id in BDO_INSTRUMENT_NAMES:
        if instrument_id == 0x0D:
            result[instrument_id] = ((99, "打击乐"),)
        else:
            result[instrument_id] = _ADVANCED_ARTICULATIONS.get(
                instrument_id,
                ((0, "延音"),),
            )
    return result


def _verified_legal_pitches(rule: InstrumentRule | None) -> frozenset[int] | None:
    if rule is None or rule.evidence.status != "verified":
        return None
    if rule.allowed_pitches:
        return frozenset(
            pitch
            for pitch in rule.allowed_pitches
            if BDO_NOTE_MIN <= pitch <= BDO_NOTE_MAX
        )
    if rule.pitch_min is None or rule.pitch_max is None:
        return None
    low = max(BDO_NOTE_MIN, int(rule.pitch_min))
    high = min(BDO_NOTE_MAX, int(rule.pitch_max))
    return frozenset(range(low, high + 1)) if high >= low else frozenset()


def _profile_recommended_pitches(
    rule: InstrumentRule | None,
) -> frozenset[int]:
    """Return a visual hint from verified *or* approximate profile fields.

    Approximate profile ranges remain guidance only because
    ``_verified_legal_pitches`` deliberately returns ``None`` for them.
    """

    if rule is None:
        return frozenset()
    if rule.allowed_pitches:
        return frozenset(
            pitch
            for pitch in rule.allowed_pitches
            if BDO_NOTE_MIN <= pitch <= BDO_NOTE_MAX
        )
    if rule.pitch_min is None or rule.pitch_max is None:
        return frozenset()
    low = max(BDO_NOTE_MIN, int(rule.pitch_min))
    high = min(BDO_NOTE_MAX, int(rule.pitch_max))
    return frozenset(range(low, high + 1)) if high >= low else frozenset()


def _load_wwise_banks(path: Path | None) -> dict[str, tuple[dict, ...]]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_banks = payload.get("banks", {})
    if not isinstance(raw_banks, dict):
        raise ValueError("Wwise mapping has no banks object")
    return {
        str(bank): tuple(row for row in rows if isinstance(row, dict))
        for bank, rows in raw_banks.items()
        if isinstance(rows, list)
    }


def _zone_pitches(rows: tuple[dict, ...], ntype: int | None = None) -> frozenset[int]:
    pitches: set[int] = set()
    for row in rows:
        if ntype is not None:
            raw_routes = row.get("route_ntypes", ())
            if isinstance(raw_routes, (str, int)):
                raw_routes = (raw_routes,)
            try:
                routes = {int(item) for item in raw_routes or ()}
            except (TypeError, ValueError, OverflowError):
                continue
            if int(ntype) not in routes:
                continue
        try:
            low = max(0, int(row["key_min"]))
            high = min(127, int(row["key_max"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if high >= low:
            pitches.update(range(low, high + 1))
    return frozenset(pitches)


def _route_evidence(
    route_pitches: frozenset[int],
    reference_pitches: frozenset[int],
) -> RouteEvidence:
    if not route_pitches:
        return RouteEvidence.UNKNOWN
    if reference_pitches and reference_pitches.issubset(route_pitches):
        return RouteEvidence.FULL
    return RouteEvidence.PARTIAL


def _visible_range(pitches: frozenset[int]) -> tuple[int, int]:
    if not pitches:
        return BDO_NOTE_MIN, BDO_NOTE_MAX
    return min(pitches), max(pitches)


def build_instrument_editor_adaptations(
    profile: BdoProfile,
    *,
    wwise_banks: Mapping[str, tuple[dict, ...]] | None = None,
    synth_mode: str = "basic",
) -> dict[int, InstrumentEditorAdaptation]:
    """Build deterministic guidance without mutating notes or editor state."""

    banks = dict(wwise_banks or {})
    articulation_pairs = articulation_pairs_by_instrument()
    result: dict[int, InstrumentEditorAdaptation] = {}
    for instrument_id, display_name in BDO_INSTRUMENT_NAMES.items():
        semantics = _INSTRUMENT_SEMANTICS[instrument_id]
        rule = profile.instruments.get(instrument_id)
        legal_pitches = _verified_legal_pitches(rule)
        bank = bank_for_instrument(instrument_id, synth_mode)
        rows = tuple(banks.get(bank or "", ()))
        preview_pitches = _zone_pitches(rows)
        # Verified score legality always wins.  Wwise coverage is only the
        # opening focus when legality is unknown/approximate.
        recommended_pitches = (
            legal_pitches
            or _profile_recommended_pitches(rule)
            or preview_pitches
        )
        if not recommended_pitches:
            recommended_pitches = frozenset(range(BDO_NOTE_MIN, BDO_NOTE_MAX + 1))

        articulations: list[ArticulationAdaptation] = []
        for ntype, label in articulation_pairs[instrument_id]:
            routed_ntype = preview_route_ntype(instrument_id, ntype)
            native_pitches = _zone_pitches(rows, routed_ntype)
            evidence = _route_evidence(native_pitches, recommended_pitches)
            musical_profile = profile_for(instrument_id, ntype)
            behavior_verified = bool(
                musical_profile is not None and musical_profile.bdo_verified
            )
            articulations.append(ArticulationAdaptation(
                int(ntype),
                str(label),
                native_pitches,
                evidence,
                behavior_verified,
                bool(
                    behavior_verified
                    and musical_profile is not None
                    and musical_profile.auto_apply
                ),
            ))

        is_canonical_drum_set = instrument_id == profile.drum_instrument_id == 0x0D
        result[instrument_id] = InstrumentEditorAdaptation(
            instrument_id=instrument_id,
            display_name=display_name,
            family=semantics.family,
            primary_role=semantics.primary_role,
            roles=semantics.roles,
            visual_key=semantics.visual_key,
            legal_pitches=legal_pitches,
            legal_pitch_evidence_status=(
                rule.evidence.status if rule is not None else "unknown"
            ),
            legal_pitch_evidence_source=(
                rule.evidence.source if rule is not None else ""
            ),
            preview_pitches=preview_pitches,
            recommended_pitches=recommended_pitches,
            recommended_visible_range=_visible_range(recommended_pitches),
            # Only the game-saved, canonical 48-64 drum set is safe to
            # compress. Sample-only percussion remains fully scrollable.
            compress_invalid_pitches=bool(
                is_canonical_drum_set and legal_pitches is not None
            ),
            drum_lanes=_DRUM_SET_LANES if is_canonical_drum_set else (),
            default_ntype=99 if is_canonical_drum_set else 0,
            articulations=tuple(articulations),
        )
    return result


def load_instrument_editor_adaptations(
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    *,
    wwise_mapping_path: str | Path | None = WWISE_MIDI_MAP_PATH,
    synth_mode: str = "basic",
) -> dict[int, InstrumentEditorAdaptation]:
    """Load the portable profile/mapping and return immutable adaptations."""

    profile = load_bdo_profile(Path(profile_path))
    banks = _load_wwise_banks(
        None if wwise_mapping_path is None else Path(wwise_mapping_path)
    )
    return build_instrument_editor_adaptations(
        profile,
        wwise_banks=banks,
        synth_mode=synth_mode,
    )


@lru_cache(maxsize=4)
def instrument_editor_adaptations(
    synth_mode: str = "basic",
) -> Mapping[int, InstrumentEditorAdaptation]:
    """Return full Wwise-backed adaptations for workers and audit tools.

    This parses the multi-megabyte checked-in Wwise mapping on the first call.
    GUI construction/painting must use ``instrument_editor_display_*`` below.
    """

    return MappingProxyType(
        load_instrument_editor_adaptations(synth_mode=synth_mode)
    )


def instrument_editor_adaptation(
    instrument_id: int,
    synth_mode: str = "basic",
) -> InstrumentEditorAdaptation | None:
    return instrument_editor_adaptations(synth_mode).get(int(instrument_id))


@lru_cache(maxsize=1)
def instrument_editor_display_adaptations(
) -> Mapping[int, InstrumentEditorAdaptation]:
    """Return the lightweight profile-only set for synchronous UI use.

    The result contains family/role/visual keys, profile-guided visible ranges,
    canonical drum rows and declared ntypes.  Wwise route/preview fields remain
    empty/unknown until a background caller requests the full API.
    """

    return MappingProxyType(load_instrument_editor_adaptations(
        wwise_mapping_path=None,
    ))


def instrument_editor_display_adaptation(
    instrument_id: int,
) -> InstrumentEditorAdaptation | None:
    """Return one profile-only display adaptation without large JSON I/O."""

    return instrument_editor_display_adaptations().get(int(instrument_id))


def assess_game_draft(
    instrument_id: int,
    notes: Iterable[object],
) -> GameDraftAdaptationReport:
    """Inspect a draft without rewriting, dropping, or repitching notes."""

    normalized_notes = tuple(notes)
    adaptation = instrument_editor_display_adaptation(int(instrument_id))
    legal_pitches = (
        adaptation.legal_pitches if adaptation is not None else None
    )
    supported_ntypes = (
        {int(item.ntype) for item in adaptation.articulations}
        if adaptation is not None
        else set()
    )
    invalid_pitch_indices: list[int] = []
    unsupported_articulation_indices: list[int] = []
    invalid_timing_indices: list[int] = []
    invalid_velocity_indices: list[int] = []
    for index, note in enumerate(normalized_notes):
        pitch_value: int | None = None
        try:
            pitch_value = int(getattr(note, "pitch"))
        except (TypeError, ValueError, AttributeError, OverflowError):
            invalid_pitch_indices.append(index)
        else:
            if not BDO_NOTE_MIN <= pitch_value <= BDO_NOTE_MAX or (
                legal_pitches is not None and pitch_value not in legal_pitches
            ):
                invalid_pitch_indices.append(index)

        try:
            ntype = int(getattr(note, "ntype", 0))
        except (TypeError, ValueError, OverflowError):
            unsupported_articulation_indices.append(index)
        else:
            if (
                supported_ntypes and ntype not in supported_ntypes
            ) or (
                pitch_value is not None
                and not articulation_supports_pitch(
                    instrument_id,
                    ntype,
                    pitch_value,
                )
            ):
                unsupported_articulation_indices.append(index)

        try:
            start = float(getattr(note, "start"))
            duration = float(getattr(note, "dur"))
        except (TypeError, ValueError, AttributeError, OverflowError):
            invalid_timing_indices.append(index)
        else:
            if (
                not math.isfinite(start)
                or not math.isfinite(duration)
                or start < 0.0
                or duration <= 0.0
            ):
                invalid_timing_indices.append(index)

        try:
            velocity = int(getattr(note, "vel"))
        except (TypeError, ValueError, AttributeError, OverflowError):
            invalid_velocity_indices.append(index)
        else:
            if not 0 <= velocity <= 127:
                invalid_velocity_indices.append(index)

    chunk_limit = load_bdo_profile(DEFAULT_PROFILE_PATH).note_limit_per_track
    note_count = len(normalized_notes)
    chunk_count = (
        math.ceil(note_count / chunk_limit) if note_count else 0
    )
    return GameDraftAdaptationReport(
        instrument_id=int(instrument_id),
        note_count=note_count,
        track_chunk_limit=int(chunk_limit),
        track_chunk_count=int(chunk_count),
        invalid_pitch_indices=tuple(invalid_pitch_indices),
        unsupported_articulation_indices=tuple(
            unsupported_articulation_indices
        ),
        invalid_timing_indices=tuple(invalid_timing_indices),
        invalid_velocity_indices=tuple(invalid_velocity_indices),
        pitch_evidence_known=legal_pitches is not None,
    )


__all__ = [
    "ArrangementRole",
    "ArticulationAdaptation",
    "DrumLane",
    "GameDraftAdaptationReport",
    "GameInstrumentFamily",
    "INSTRUMENT_ADAPTATION_VERSION",
    "InstrumentEditorAdaptation",
    "RouteEvidence",
    "assess_game_draft",
    "articulation_pairs_by_instrument",
    "articulation_supports_pitch",
    "articulation_trigger_pitches",
    "build_instrument_editor_adaptations",
    "instrument_editor_adaptation",
    "instrument_editor_adaptations",
    "instrument_editor_display_adaptation",
    "instrument_editor_display_adaptations",
    "load_instrument_editor_adaptations",
]
