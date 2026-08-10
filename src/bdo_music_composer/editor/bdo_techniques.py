"""Real-instrument technique vocabulary independent of BDO note types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RealizationKind(StrEnum):
    NATIVE_BDO = "native_bdo"
    MIDI_APPROXIMATION = "midi_approximation"
    SUGGESTION_ONLY = "suggestion_only"


@dataclass(frozen=True)
class TechniqueProfile:
    technique_id: str
    name: str
    families: frozenset[str]
    contexts: tuple[str, ...]
    forbidden_contexts: tuple[str, ...] = ()
    source: str = ""
    scope: str = "attribute"
    midi_evidence: tuple[str, ...] = ()
    midi_realizations: tuple[str, ...] = ()
    midi2_classification: int | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditOperation:
    operation: str
    track_id: int
    note_indices: tuple[int, ...]
    payload: tuple[tuple[str, object], ...] = ()

    def value(self, key: str, default=None):
        return dict(self.payload).get(key, default)


@dataclass(frozen=True)
class TechniqueCandidate:
    track_id: int
    note_indices: tuple[int, ...]
    technique_id: str
    confidence: float
    reason: str
    realization: RealizationKind
    ntype: int | None = None
    edits: tuple[EditOperation, ...] = ()
    conflict_key: tuple = ()
    source: str = ""
    requires_confirmation: bool = False


class TriggerKind(StrEnum):
    KEYSWITCH = "keyswitch"
    CONTROL_CHANGE = "control_change"
    PROGRAM_CHANGE = "program_change"
    MIDI2_ATTRIBUTE = "midi2_attribute"


@dataclass(frozen=True)
class TechniqueTrigger:
    kind: TriggerKind
    number: int
    value: int | None = None
    channel: int | None = None


@dataclass(frozen=True)
class TechniqueMap:
    """Explicit adapter for one sample library/device, never a global truth."""
    map_id: str
    vendor: str
    product: str
    mappings: dict[str, tuple[TechniqueTrigger, ...]]

    @classmethod
    def from_dict(cls, payload: dict) -> "TechniqueMap":
        mappings: dict[str, tuple[TechniqueTrigger, ...]] = {}
        for technique_id, raw_triggers in dict(payload.get("mappings", {})).items():
            if technique_id not in TECHNIQUE_PROFILES:
                raise ValueError(f"Unknown technique_id: {technique_id}")
            triggers = []
            for raw in raw_triggers:
                kind = TriggerKind(str(raw["kind"]))
                number = int(raw["number"])
                value = None if raw.get("value") is None else int(raw["value"])
                channel = None if raw.get("channel") is None else int(raw["channel"])
                number_limit = 255 if kind == TriggerKind.MIDI2_ATTRIBUTE else 127
                value_limit = 65535 if kind == TriggerKind.MIDI2_ATTRIBUTE else 127
                if not 0 <= number <= number_limit:
                    raise ValueError(f"Trigger number out of range: {number}")
                if value is not None and not 0 <= value <= value_limit:
                    raise ValueError(f"Trigger value out of range: {value}")
                if channel is not None and not 0 <= channel <= 15:
                    raise ValueError(f"Trigger channel out of range: {channel}")
                triggers.append(TechniqueTrigger(kind, number, value, channel))
            mappings[str(technique_id)] = tuple(triggers)
        return cls(
            str(payload.get("map_id") or "custom"), str(payload.get("vendor") or ""),
            str(payload.get("product") or ""), mappings,
        )


PHILHARMONIA = "https://philharmonia.co.uk/resources/instruments/"
YAMAHA_GUITAR = "https://www.yamaha.com/en/musical_instrument_guide/electric_guitar/play/"
YAMAHA_BASS = "https://www.yamaha.com/en/musical_instrument_guide/electric_guitar/play/play005.html"
OPEN_ORCHESTRATION = "https://viva.pressbooks.pub/openmusictheory/chapter/core-principles-of-orchestration/"
MIDI_ORCHESTRAL_PROFILE = "https://midi.org/wp-content/uploads/2024/03/Orchestral-APE-Profile-Intro-Final.pdf"
DORICO_TECHNIQUES = "https://www.steinberg.help/r/dorico-se/6.1/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_playing_techniques_playing_techniques_r.html"
MIDI_MPE_PROFILE = "https://midi.org/midi-ci-profile-for-midi-polyphonic-expression"


TECHNIQUE_PROFILES = {
    profile.technique_id: profile for profile in (
        TechniqueProfile("legato", "连奏", frozenset({"strings", "wind", "brass", "synth"}), ("melody", "connected"), source=PHILHARMONIA),
        TechniqueProfile("detache", "分弓/分奏", frozenset({"strings"}), ("melody", "rhythm"), source=PHILHARMONIA),
        TechniqueProfile("staccato", "断奏/吐音", frozenset({"strings", "wind", "brass", "keys"}), ("rhythm", "detached"), ("cadence",), PHILHARMONIA),
        TechniqueProfile("spiccato", "跳弓", frozenset({"strings"}), ("light", "rhythm", "repeated"), source=PHILHARMONIA),
        TechniqueProfile("pizzicato", "拨弦", frozenset({"strings"}), ("rhythm", "bass"), source=PHILHARMONIA),
        TechniqueProfile("tremolo", "震音", frozenset({"strings", "guitar", "percussion", "synth"}), ("sustain", "crescendo"), source=PHILHARMONIA),
        TechniqueProfile("trill", "颤音", frozenset({"strings", "wind", "brass", "harp", "keys"}), ("ornament", "sustain"), ("chord",), PHILHARMONIA),
        TechniqueProfile("slide", "滑音/滑奏", frozenset({"strings", "guitar", "bass", "wind", "harp"}), ("connected", "transition"), ("chord",), YAMAHA_GUITAR),
        TechniqueProfile("bend", "弯音", frozenset({"guitar", "bass"}), ("melody", "sustain"), ("chord",), YAMAHA_GUITAR),
        TechniqueProfile("hammer_on", "击弦", frozenset({"guitar", "bass"}), ("connected", "ascending"), source=YAMAHA_GUITAR),
        TechniqueProfile("pull_off", "勾弦", frozenset({"guitar", "bass"}), ("connected", "descending"), source=YAMAHA_GUITAR),
        TechniqueProfile("palm_mute", "掌根闷音", frozenset({"guitar", "bass"}), ("riff", "rhythm"), ("melody",), YAMAHA_GUITAR),
        TechniqueProfile("harmonic", "泛音", frozenset({"strings", "guitar", "bass"}), ("sparse", "high"), ("dense",), YAMAHA_GUITAR),
        TechniqueProfile("slap_pop", "Slap/Pop", frozenset({"bass"}), ("funk", "accent", "rhythm"), source=YAMAHA_BASS),
        TechniqueProfile("ghost_note", "鬼音", frozenset({"bass", "drums", "hand_percussion"}), ("syncopation", "fill"), source=YAMAHA_BASS),
        TechniqueProfile("breath_phrase", "换气乐句", frozenset({"wind", "brass"}), ("phrase_boundary",), source=PHILHARMONIA),
        TechniqueProfile("harp_arpeggio", "竖琴琶音", frozenset({"harp"}), ("chord", "flowing"), source=PHILHARMONIA),
        TechniqueProfile("harp_gliss", "竖琴滑奏", frozenset({"harp"}), ("scale_run", "transition"), ("chromatic_dense",), PHILHARMONIA),
        TechniqueProfile("piano_pedal", "钢琴延音踏板", frozenset({"keys"}), ("harmony_hold", "cc64"), ("staccato",), PHILHARMONIA),
        TechniqueProfile("flam", "装饰击/Flam", frozenset({"drums", "hand_percussion"}), ("accent", "fill"), source=PHILHARMONIA),
        TechniqueProfile("roll", "滚奏", frozenset({"drums", "hand_percussion"}), ("sustain", "crescendo"), source=PHILHARMONIA),
        TechniqueProfile("cymbal_choke", "止镲", frozenset({"drums"}), ("accent", "stop"), source=PHILHARMONIA),
        TechniqueProfile("open_tone", "开放音", frozenset({"hand_percussion"}), ("pulse", "melody"), source=PHILHARMONIA),
        TechniqueProfile("synth_gate", "门限短音", frozenset({"synth"}), ("rhythm", "electronic"), source=OPEN_ORCHESTRATION),
        TechniqueProfile("synth_filter_sustain", "滤波持续音", frozenset({"synth"}), ("pad", "sustain"), source=OPEN_ORCHESTRATION),
    )
}


# Portable semantic vocabulary.  A technique may be represented by a duration,
# velocity or controller gesture, but vendor keyswitch notes are deliberately
# not assigned here: they belong to an explicit library adapter.
_EXTENDED_PROFILES = (
    TechniqueProfile("interval_trill", "音程颤音", frozenset({"strings", "wind", "brass", "harp", "keys"}),
                     ("ornament", "alternating_interval"), ("chord",), MIDI_ORCHESTRAL_PROFILE,
                     midi_evidence=("alternating_neighbor_notes",), midi_realizations=("note_pattern", "library_map"),
                     midi2_classification=0x14),
    TechniqueProfile("accent", "重音", frozenset({"strings", "wind", "brass", "keys", "guitar", "bass", "percussion"}),
                     ("attack", "strong_beat"), source=DORICO_TECHNIQUES, midi_evidence=("velocity_peak",), midi_realizations=("velocity",), midi2_classification=0x10),
    TechniqueProfile("marcato", "强重音/Marcato", frozenset({"strings", "wind", "brass", "keys"}),
                     ("accent", "detached"), source=DORICO_TECHNIQUES, midi_evidence=("velocity_peak", "short_gate"), midi_realizations=("velocity", "gate"), midi2_classification=0x12),
    TechniqueProfile("tenuto", "保持音/Tenuto", frozenset({"strings", "wind", "brass", "keys"}),
                     ("sustain", "connected"), source=DORICO_TECHNIQUES, midi_evidence=("long_gate",), midi_realizations=("gate",), midi2_classification=0x10),
    TechniqueProfile("staccatissimo", "极短断奏", frozenset({"strings", "wind", "brass", "keys"}),
                     ("very_short", "detached"), source=DORICO_TECHNIQUES, midi_evidence=("very_short_gate",), midi_realizations=("gate",), midi2_classification=0x12),
    TechniqueProfile("vibrato", "揉弦/气息颤音", frozenset({"strings", "wind", "brass", "guitar", "bass", "voice", "synth"}),
                     ("sustain", "expressive"), source=MIDI_MPE_PROFILE, midi_evidence=("pitchwheel_oscillation", "cc1", "channel_pressure"), midi_realizations=("pitch_bend", "cc1", "aftertouch"), midi2_classification=0x15),
    TechniqueProfile("non_vibrato", "无揉弦/Non-vibrato", frozenset({"strings", "wind", "brass", "voice"}),
                     ("sustain", "pure"), source=DORICO_TECHNIQUES, midi_evidence=("stable_pitch",), midi_realizations=("direction",), midi2_classification=0x11),
    TechniqueProfile("portamento", "连贯滑音/Portamento", frozenset({"strings", "wind", "brass", "voice", "synth"}),
                     ("transition", "connected"), ("chord",), MIDI_MPE_PROFILE, "direction", ("cc65", "cc5", "pitchwheel_ramp"), ("cc65", "cc5", "pitch_bend"), 0x15),
    TechniqueProfile("crescendo", "渐强", frozenset({"strings", "wind", "brass", "voice", "synth", "keys"}),
                     ("sustain", "phrase"), source=MIDI_ORCHESTRAL_PROFILE, scope="direction", midi_evidence=("cc11_rise", "cc1_rise", "velocity_rise"), midi_realizations=("cc11", "velocity_curve"), midi2_classification=0x15),
    TechniqueProfile("diminuendo", "渐弱", frozenset({"strings", "wind", "brass", "voice", "synth", "keys"}),
                     ("sustain", "phrase"), source=MIDI_ORCHESTRAL_PROFILE, scope="direction", midi_evidence=("cc11_fall", "velocity_fall"), midi_realizations=("cc11", "velocity_curve"), midi2_classification=0x15),
    TechniqueProfile("sforzando", "突强后回落/Sforzando", frozenset({"strings", "wind", "brass", "keys"}),
                     ("attack", "dynamic_gesture"), source=MIDI_ORCHESTRAL_PROFILE, midi_evidence=("velocity_peak", "cc11_fall"), midi_realizations=("velocity", "cc11"), midi2_classification=0x15),
    TechniqueProfile("sul_ponticello", "近琴码奏", frozenset({"strings"}), ("color", "sustain"), source=DORICO_TECHNIQUES,
                     scope="direction", midi_realizations=("library_map",), midi2_classification=0x11, aliases=("ponticello",)),
    TechniqueProfile("sul_tasto", "指板上奏", frozenset({"strings"}), ("color", "soft"), source=DORICO_TECHNIQUES,
                     scope="direction", midi_realizations=("library_map",), midi2_classification=0x11),
    TechniqueProfile("col_legno", "木杆击弦/Col legno", frozenset({"strings"}), ("percussive", "effect"), source=DORICO_TECHNIQUES,
                     midi_realizations=("library_map",), midi2_classification=0x17),
    TechniqueProfile("con_sordino", "加弱音器", frozenset({"strings", "brass"}), ("muted", "color"), source=DORICO_TECHNIQUES,
                     scope="direction", midi_realizations=("library_map",), midi2_classification=0x11, aliases=("mute",)),
    TechniqueProfile("bow_up", "上弓", frozenset({"strings"}), ("bow_direction",), source=DORICO_TECHNIQUES,
                     midi_realizations=("library_map",), midi2_classification=0x10),
    TechniqueProfile("bow_down", "下弓", frozenset({"strings"}), ("bow_direction", "accent"), source=DORICO_TECHNIQUES,
                     midi_realizations=("library_map",), midi2_classification=0x10),
    TechniqueProfile("double_tongue", "双吐", frozenset({"wind", "brass"}), ("fast_repeat", "articulated"), source=DORICO_TECHNIQUES,
                     midi_evidence=("fast_repeated_attacks",), midi_realizations=("repeated_notes", "library_map"), midi2_classification=0x13),
    TechniqueProfile("triple_tongue", "三吐", frozenset({"wind", "brass"}), ("triplet_repeat", "articulated"), source=DORICO_TECHNIQUES,
                     midi_evidence=("triplet_repeated_attacks",), midi_realizations=("repeated_notes", "library_map"), midi2_classification=0x13),
    TechniqueProfile("flutter_tongue", "花舌/Flutter tongue", frozenset({"wind", "brass"}), ("sustain", "rough"), source=DORICO_TECHNIQUES,
                     midi_evidence=("cc1_high", "channel_pressure"), midi_realizations=("library_map",), midi2_classification=0x13),
    TechniqueProfile("key_click", "按键声", frozenset({"wind"}), ("noise", "percussive"), source=DORICO_TECHNIQUES,
                     midi_realizations=("library_map",), midi2_classification=0x17),
    TechniqueProfile("whistle_tone", "哨音", frozenset({"wind"}), ("effect", "high"), source=DORICO_TECHNIQUES,
                     midi_realizations=("library_map",), midi2_classification=0x17),
    TechniqueProfile("growl", "吼音/Growl", frozenset({"wind", "brass", "voice"}), ("rough", "sustain"), source=DORICO_TECHNIQUES,
                     midi_evidence=("cc1_high", "pressure_high"), midi_realizations=("library_map", "aftertouch"), midi2_classification=0x17),
    TechniqueProfile("brass_stopped", "闭塞音/Stopped", frozenset({"brass"}), ("muted", "color"), source=DORICO_TECHNIQUES,
                     scope="direction", midi_realizations=("library_map",), midi2_classification=0x11),
    TechniqueProfile("brass_fall", "下坠音/Fall", frozenset({"brass", "wind"}), ("ending", "pitch_gesture"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_evidence=("pitchwheel_fall",), midi_realizations=("pitch_bend", "library_map"), midi2_classification=0x15),
    TechniqueProfile("brass_doit", "上扬音/Doit", frozenset({"brass", "wind"}), ("ending", "pitch_gesture"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_evidence=("pitchwheel_rise",), midi_realizations=("pitch_bend", "library_map"), midi2_classification=0x15),
    TechniqueProfile("scoop", "铲入音/Scoop", frozenset({"brass", "wind", "voice", "guitar"}), ("attack", "pitch_gesture"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_evidence=("pitchwheel_attack_rise",), midi_realizations=("pitch_bend", "library_map"), midi2_classification=0x15),
    TechniqueProfile("strum_up", "上扫弦", frozenset({"guitar"}), ("chord", "spread"), source=DORICO_TECHNIQUES,
                     midi_evidence=("ascending_rolled_chord",), midi_realizations=("onset_spread", "library_map"), midi2_classification=0x16),
    TechniqueProfile("strum_down", "下扫弦", frozenset({"guitar"}), ("chord", "spread"), source=DORICO_TECHNIQUES,
                     midi_evidence=("descending_rolled_chord",), midi_realizations=("onset_spread", "library_map"), midi2_classification=0x16),
    TechniqueProfile("tapping", "点弦/Tapping", frozenset({"guitar", "bass"}), ("fast", "legato"), source=YAMAHA_GUITAR,
                     midi_evidence=("fast_wide_legato",), midi_realizations=("library_map",), midi2_classification=0x16),
    TechniqueProfile("rake", "扫拨/Rake", frozenset({"guitar", "bass"}), ("accent", "spread"), source=YAMAHA_GUITAR,
                     midi_evidence=("muted_lead_in",), midi_realizations=("library_map",), midi2_classification=0x17),
    TechniqueProfile("sostenuto_pedal", "选择性延音踏板", frozenset({"keys"}), ("pedal", "sustain"), source=MIDI_ORCHESTRAL_PROFILE,
                     scope="direction", midi_evidence=("cc66",), midi_realizations=("cc66",), midi2_classification=0x10),
    TechniqueProfile("soft_pedal", "柔音踏板/Una corda", frozenset({"keys"}), ("pedal", "soft"), source=MIDI_ORCHESTRAL_PROFILE,
                     scope="direction", midi_evidence=("cc67",), midi_realizations=("cc67",), midi2_classification=0x11),
    TechniqueProfile("half_pedal", "半踏板", frozenset({"keys"}), ("pedal", "continuous"), source=MIDI_ORCHESTRAL_PROFILE,
                     scope="direction", midi_evidence=("cc64_partial",), midi_realizations=("cc64",), midi2_classification=0x10),
    TechniqueProfile("rim_shot", "边击/Rim shot", frozenset({"drums", "hand_percussion"}), ("accent", "rim"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_realizations=("drum_note_map",), midi2_classification=0x10),
    TechniqueProfile("cross_stick", "横槌/Cross stick", frozenset({"drums"}), ("rim", "soft"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_realizations=("drum_note_map",), midi2_classification=0x10),
    TechniqueProfile("brush", "鼓刷", frozenset({"drums"}), ("soft", "sweep"), source=DORICO_TECHNIQUES,
                     scope="direction", midi_realizations=("drum_note_map", "library_map"), midi2_classification=0x11),
    TechniqueProfile("hi_hat_open", "开镲", frozenset({"drums"}), ("open", "sustain"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_realizations=("drum_note_map",), midi2_classification=0x10),
    TechniqueProfile("hi_hat_closed", "闭镲", frozenset({"drums"}), ("closed", "short"), source=MIDI_ORCHESTRAL_PROFILE,
                     midi_realizations=("drum_note_map",), midi2_classification=0x12),
    TechniqueProfile("damp", "制音/闷止", frozenset({"percussion", "hand_percussion", "harp", "keys"}), ("stop", "short"), source=DORICO_TECHNIQUES,
                     midi_realizations=("short_gate", "library_map"), midi2_classification=0x12),
    TechniqueProfile("motor_tremolo", "马达颤音", frozenset({"percussion", "keys"}), ("vibraphone", "sustain"), source=DORICO_TECHNIQUES,
                     scope="direction", midi_realizations=("library_map",), midi2_classification=0x13),
    TechniqueProfile("arpeggiator", "琶音器", frozenset({"synth"}), ("pattern", "rhythm"), source=MIDI_ORCHESTRAL_PROFILE,
                     scope="direction", midi_evidence=("repeating_pitch_pattern",), midi_realizations=("note_pattern",), midi2_classification=0x16),
    TechniqueProfile("timbre_sweep", "音色/滤波扫频", frozenset({"synth"}), ("sustain", "timbre_gesture"), source=MIDI_MPE_PROFILE,
                     midi_evidence=("cc74_curve",), midi_realizations=("cc74", "per_note_timbre"), midi2_classification=0x15),
    TechniqueProfile("aftertouch_swell", "触后渐变", frozenset({"synth", "keys", "wind"}), ("sustain", "pressure_gesture"), source=MIDI_MPE_PROFILE,
                     midi_evidence=("channel_pressure", "poly_pressure"), midi_realizations=("aftertouch",), midi2_classification=0x15),
)

TECHNIQUE_PROFILES.update({profile.technique_id: profile for profile in _EXTENDED_PROFILES})


def instrument_family(instrument_id: int) -> str:
    if instrument_id in {0x08, 0x12, 0x0F}:
        return "strings"
    if instrument_id in {0x00, 0x0A, 0x24, 0x25, 0x26}:
        return "guitar"
    if instrument_id == 0x0E:
        return "bass"
    if instrument_id in {0x01, 0x02, 0x0B, 0x27}:
        return "wind"
    if instrument_id == 0x28:
        return "brass"
    if instrument_id in {0x06, 0x10}:
        return "harp"
    if instrument_id in {0x07, 0x11}:
        return "keys"
    if instrument_id in {0x14, 0x18, 0x1C, 0x20}:
        return "synth"
    if instrument_id == 0x0D:
        return "drums"
    if instrument_id in {0x04, 0x05, 0x13}:
        return "hand_percussion"
    return "other"
