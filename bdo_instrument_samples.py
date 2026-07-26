"""Canonical BDO instrument-to-Wwise-bank routing.

Keep this module independent of Qt and audio decoding so real-time preview,
offline rendering, validation, and audit tools cannot drift into separate
instrument tables.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from bdo_midi import _GM_TO_BDO_DRUM as GM_TO_BDO_DRUM


ROW_VOLUME_DB_MIN = -96.0
ROW_VOLUME_DB_MAX = 24.0
ROW_RELEASE_MS_MAX = 60_000.0


BDO_BANK_BY_ID = {
    0x00: "midi_instrument_00_acousticguitar",
    0x01: "midi_instrument_01_flute",
    0x02: "midi_instrument_02_recorder",
    0x04: "midi_instrument_04_handdrum",
    0x05: "midi_instrument_05_piatticymbals",
    0x06: "midi_instrument_06_harp",
    0x07: "midi_instrument_07_piano",
    0x08: "midi_instrument_08_violin",
    0x0A: "midi_instrument_10_proguitar",
    0x0B: "midi_instrument_11_proflute",
    0x0D: "midi_instrument_13_prodrumset",
    0x0E: "midi_instrument_14_probasselectric",
    0x0F: "midi_instrument_15_probasscontra",
    0x10: "midi_instrument_16_proharp",
    0x11: "midi_instrument_17_propiano",
    0x12: "midi_instrument_18_proviolin",
    0x13: "midi_instrument_19_propandrum",
    0x24: "midi_instrument_24_proguitarelectricclean",
    0x25: "midi_instrument_25_proguitarelectricdrive",
    0x26: "midi_instrument_26_proguitarelectricdist",
    0x27: "midi_instrument_27_proclarinet",
    0x28: "midi_instrument_28_prohorn",
}

# The waveform-family pairing still requires game-capture A/B verification, but
# every consumer must use the same provisional 4x4 routing in the meantime.
MARNIAN_SYNTH_WAVEFORM_BY_ID = {
    0x14: "saw",
    0x18: "sine",
    0x1C: "square",
    0x20: "triangle",
}
MARNIAN_SYNTH_MODES = ("basic", "stereo", "super", "superoct")
PERCUSSION_EVENT_INSTRUMENT_IDS = frozenset({0x04, 0x05, 0x0D, 0x13})


@dataclass(frozen=True)
class WwiseInstanceLimit:
    """One scalar runtime-safe instance limit recovered from HIRC lineage."""

    group_id: int = -1
    max_instances: int = 0
    kill_newest: bool = False
    global_scope: bool = False
    use_virtual_behavior: bool = False

    @property
    def enforceable(self) -> bool:
        return (
            self.group_id >= 0
            and self.max_instances > 0
            and not self.use_virtual_behavior
        )


class WwiseContainerRotation:
    """Deterministic preview state for Wwise random/sequence containers.

    Game playback is random but many instrument containers declare
    AvoidRepeat=1.  Preview rotates the recovered child list, which preserves
    that no-immediate-repeat behavior while keeping renders reproducible.
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}

    def choose(self, bank: str, variants: tuple[dict, ...]) -> dict | None:
        if not variants:
            return None
        first = variants[0]
        group_id = int(
            first.get("selection_group_id")
            or first.get("sound_id")
            or first["source_id"]
        )
        key = (str(bank), group_id)
        index = self._counts.get(key, 0)
        self._counts[key] = index + 1
        return variants[index % len(variants)]


def _row_ntypes(row: dict) -> tuple[int, ...]:
    """Return the game Event routes attached to one mapping row."""
    values = row.get("route_ntypes", ())
    if isinstance(values, (int, str)):
        values = (values,)
    result: list[int] = []
    for value in values or ():
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(result)


def row_routes_ntype(row: dict, ntype: int) -> bool:
    """Whether a row belongs to the exact game Event for this note type."""
    return int(ntype) in _row_ntypes(row)


def preview_has_native_articulation(
    instrument_id: int,
    row: dict,
    route_ntype: int,
) -> bool:
    """Whether the selected source fully replaces fallback preview DSP.

    Marnian Events select native sample layers, but their recovered maps do not
    yet describe the parent modulators and filters.  Keep those layers on the
    shared approximate DSP path until game A/B evidence can replace it.
    """

    return (
        row_routes_ntype(row, route_ntype)
        and int(instrument_id) not in MARNIAN_SYNTH_WAVEFORM_BY_ID
    )


def preview_route_ntype(instrument_id: int, ntype: int) -> int:
    """Resolve Wwise's shared percussion Event without changing score data.

    The hand drum, cymbals, drum set, and handpan banks expose their ordinary
    playable layer as Event ``_99``.  Editor notes outside the canonical drum
    set may still carry the neutral wire value ``0``; preview must route those
    notes to Event 99 without mutating the serialized Note.
    """

    value = int(ntype)
    if (
        int(instrument_id) in PERCUSSION_EVENT_INSTRUMENT_IDS
        and value in {0, 99}
    ):
        return 99
    return value


def preview_pitch_offset_semitones(
    ntype: int,
    native_articulation: bool,
) -> int:
    """Return only the pitch effect not already encoded by a game sample route."""
    return 12 if int(ntype) == 14 and not native_articulation else 0


def sample_pitch_ratio(row: dict, target_pitch: int | float) -> float:
    """Return Wwise root-note transposition including static Pitch metadata.

    Ranged Pitch is represented by its midpoint for deterministic preview.
    The recovered cymbal range is symmetric, while static contra-bass offsets
    remain audible and consistent in real-time and offline paths.
    """
    random_midpoint = (
        float(row.get("pitch_random_min_cents", 0.0))
        + float(row.get("pitch_random_max_cents", 0.0))
    ) / 2.0
    cents = (
        (float(target_pitch) - float(row["root_note"])) * 100.0
        + float(row.get("pitch_cents", 0.0))
        + random_midpoint
    )
    ratio = 2.0 ** (cents / 1_200.0)
    return ratio if math.isfinite(ratio) and ratio > 0.0 else 1.0


def _finite_float(value: object, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def row_instance_limit(row: dict) -> WwiseInstanceLimit:
    """Resolve current scalar instance metadata with old-map compatibility.

    New maps expose the effective lineage limit through ``instance_*`` fields.
    An explicit scalar value of zero is authoritative: it may represent an
    ambiguous nested lineage retained only in ``instance_limits`` and must not
    accidentally fall through to a selection-container guess.  Older maps that
    predate those scalar fields retain their former ``selection_*`` behavior.
    """

    has_scalar = any(
        key in row
        for key in (
            "instance_group_id",
            "instance_limit_group_id",
            "max_instances",
        )
    )
    if has_scalar:
        group_value = row.get(
            "instance_group_id",
            row.get("instance_limit_group_id", -1),
        )
        limit_value = row.get("max_instances", 0)
        kill_newest = _truthy(row.get("kill_newest", False))
        global_scope = _truthy(
            row.get("instance_limit_global", False)
        )
        use_virtual = _truthy(
            row.get("instance_use_virtual_behavior", False)
        )
    else:
        group_value = row.get("selection_group_id", -1)
        limit_value = row.get("selection_max_instances", 0)
        kill_newest = _truthy(
            row.get("selection_kill_newest", False)
        )
        global_scope = _truthy(row.get("selection_global", False))
        use_virtual = False
    try:
        group_id = int(group_value)
    except (TypeError, ValueError, OverflowError):
        group_id = -1
    try:
        max_instances = max(0, int(limit_value or 0))
    except (TypeError, ValueError, OverflowError):
        max_instances = 0
    if group_id < 0 or max_instances <= 0:
        return WwiseInstanceLimit()
    return WwiseInstanceLimit(
        group_id=group_id,
        max_instances=max_instances,
        kill_newest=kill_newest,
        global_scope=global_scope,
        use_virtual_behavior=use_virtual,
    )


def row_volume_gain(row: dict) -> float:
    """Return one safe linear gain from recovered Wwise Volume metadata.

    Wwise stores Volume in decibels.  Mapping files are external evidence and
    may be old or malformed, so invalid values retain unity gain and extreme
    values are bounded before exponentiation.  This helper is shared by the
    offline and real-time paths to keep their relative instrument levels equal.
    """

    volume_db = _finite_float(row.get("volume_db", 0.0), 0.0)
    volume_db = max(ROW_VOLUME_DB_MIN, min(ROW_VOLUME_DB_MAX, volume_db))
    return 10.0 ** (volume_db / 20.0)


def row_sample_loops(row: dict) -> bool:
    """Whether a mapping row declares a repeating source region."""

    value = row.get("sample_loops", row.get("loop_enabled", False))
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "loop"}
    return bool(value)


def row_release_ms(row: dict) -> float | None:
    """Return a bounded source release time, or ``None`` when unspecified."""

    value = row.get("release_ms", row.get("release_time_ms"))
    if value is None:
        return None
    try:
        release = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(release):
        return None
    return max(0.0, min(ROW_RELEASE_MS_MAX, release))


def row_loop_bounds(
    row: dict,
    sample_frames: int,
    *,
    source_sample_rate: int | None = None,
    output_sample_rate: int | None = None,
) -> tuple[int, int] | None:
    """Return a validated, end-exclusive loop region in decoded PCM frames.

    Mapping loop offsets are source-frame offsets.  Offline rendering may
    decode to a different rate, so callers can request a deterministic scale
    into their decoded buffer.  A looping row without explicit offsets repeats
    the complete source.  Invalid or empty regions fail closed as non-looping.
    """

    frames = max(0, int(sample_frames))
    if not row_sample_loops(row) or frames <= 0:
        return None

    start_value = row.get("loop_start_frame")
    end_value = row.get("loop_end_frame")
    regions = row.get("sample_loop_regions")
    if (
        (start_value is None or end_value is None)
        and isinstance(regions, (list, tuple))
        and regions
        and isinstance(regions[0], dict)
    ):
        start_value = regions[0].get("start_frame", start_value)
        end_value = regions[0].get("end_frame", end_value)
    if start_value is None:
        start_value = row.get(
            "loop_start",
            row.get("loop_start_sample", 0),
        )
    if end_value is None:
        end_value = row.get("loop_end", row.get("loop_end_sample"))
    has_explicit_end = end_value is not None
    start = round(_finite_float(start_value, 0.0))
    end = (
        round(_finite_float(end_value, float(frames)))
        if end_value is not None
        else frames
    )

    source_rate = max(0, int(source_sample_rate or 0))
    output_rate = max(0, int(output_sample_rate or 0))
    if source_rate > 0 and output_rate > 0 and source_rate != output_rate:
        scale = output_rate / source_rate
        start = round(start * scale)
        if has_explicit_end:
            end = round(end * scale)

    start = max(0, min(frames - 1, start))
    end = max(0, min(frames, end))
    return (start, end) if end > start else None


# Compatibility name used by the real-time engine; loop ends are exclusive.
row_loop_points = row_loop_bounds


def select_zone_variants(
    rows: list[dict] | tuple[dict, ...],
    pitch: int,
    velocity: int,
    ntype: int = 0,
) -> tuple[dict, ...]:
    """Select one game MIDI zone and return its random-container variants.

    Wwise resolves these banks in three stages: Event/articulation route,
    key-and-velocity zone, then Random/Sequence Container child.  Older maps
    do not carry route metadata, so they retain the previous all-row behavior.
    """
    usable = [row for row in rows if row.get("wav_exists", True)]
    routed = [row for row in usable if _row_ntypes(row)]
    if routed:
        route_rows = [row for row in routed if int(ntype) in _row_ntypes(row)]
        if not route_rows and int(ntype) != 0:
            route_rows = [row for row in routed if 0 in _row_ntypes(row)]
        if route_rows:
            usable = route_rows
        else:
            # A bank with verified routes must not fall through into a
            # different articulation merely because the requested route is
            # absent. Unrouted rows are kept only as a compatibility fallback.
            usable = [row for row in usable if not _row_ntypes(row)]

    matches = [
        row
        for row in usable
        if int(row["key_min"]) <= int(pitch) <= int(row["key_max"])
        and int(row["velocity_min"]) <= int(velocity) <= int(row["velocity_max"])
    ]
    if not matches:
        return ()

    groups: dict[int, list[dict]] = {}
    for row in matches:
        group_id = int(
            row.get("selection_group_id")
            or row.get("sound_id")
            or row["source_id"]
        )
        groups.setdefault(group_id, []).append(row)

    def group_score(item: tuple[int, list[dict]]) -> tuple[float, float, int]:
        group_id, group_rows = item
        root_distance = min(
            abs(int(pitch) - int(row["root_note"])) for row in group_rows
        )
        velocity_distance = min(
            abs(
                int(velocity)
                - (
                    int(row["velocity_min"])
                    + int(row["velocity_max"])
                )
                / 2.0
            )
            for row in group_rows
        )
        return root_distance, velocity_distance, group_id

    _group_id, selected_group = min(groups.items(), key=group_score)
    return tuple(sorted(
        selected_group,
        key=lambda item: (
            _finite_float(item.get("playlist_index"), float(2**31 - 1)),
            int(item["source_id"]),
            int(item.get("sound_id", 0)),
        ),
    ))


def select_zone_row(
    rows: list[dict] | tuple[dict, ...],
    pitch: int,
    velocity: int,
    ntype: int = 0,
    variant_index: int = 0,
) -> dict | None:
    """Return a deterministic child from the selected Wwise container."""
    variants = select_zone_variants(rows, pitch, velocity, ntype)
    if not variants:
        return None
    return variants[int(variant_index) % len(variants)]


def bank_for_instrument(
    instrument_id: int, synth_mode: str = "basic"
) -> str | None:
    """Return the one Wwise bank selected by an editor instrument/mode pair."""
    waveform = MARNIAN_SYNTH_WAVEFORM_BY_ID.get(int(instrument_id))
    if waveform:
        mode = synth_mode if synth_mode in MARNIAN_SYNTH_MODES else "basic"
        return f"midi_instrument_synth_{waveform}_{mode}"
    return BDO_BANK_BY_ID.get(int(instrument_id))


def banks_for_instrument(instrument_id: int) -> tuple[str, ...]:
    """Return every selectable bank for one logical editor instrument."""
    waveform = MARNIAN_SYNTH_WAVEFORM_BY_ID.get(int(instrument_id))
    if waveform:
        return tuple(
            f"midi_instrument_synth_{waveform}_{mode}"
            for mode in MARNIAN_SYNTH_MODES
        )
    bank = BDO_BANK_BY_ID.get(int(instrument_id))
    return (bank,) if bank else ()


def marnian_synth_matrix() -> dict[int, dict[str, str]]:
    """Return the four source-mode banks for each Marnian instrument."""
    return {
        instrument_id: {
            mode: bank_for_instrument(instrument_id, mode) or ""
            for mode in MARNIAN_SYNTH_MODES
        }
        for instrument_id in sorted(MARNIAN_SYNTH_WAVEFORM_BY_ID)
    }


def resolve_bdo_pitch(instrument_id: int, pitch: int, ntype: int = 0) -> int:
    """Resolve imported GM drums while preserving canonical BDO drum notes."""
    if int(instrument_id) != 0x0D:
        return int(pitch)
    if int(ntype) == 99 and 48 <= int(pitch) <= 64:
        return int(pitch)
    return GM_TO_BDO_DRUM.get(int(pitch), 48)
