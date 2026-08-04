"""Black Desert instrument facts and General MIDI mapping policy."""

from __future__ import annotations

from collections.abc import Callable


BDO_INSTRUMENTS = {
    "beginner_guitar": 0x00,
    "beginner_flute": 0x01,
    "beginner_recorder": 0x02,
    "hand_drum": 0x04,
    "cymbals": 0x05,
    "beginner_harp": 0x06,
    "beginner_piano": 0x07,
    "beginner_violin": 0x08,
    "guitar": 0x0A,
    "flute": 0x0B,
    "drum_set": 0x0D,
    "marnibass": 0x0E,
    "contrabass": 0x0F,
    "harp": 0x10,
    "piano": 0x11,
    "violin": 0x12,
    "handpan": 0x13,
    "marnian_wavy": 0x14,
    "marnian_illusion": 0x18,
    "marnian_secret": 0x1C,
    "marnian_sandwich": 0x20,
    "eguitar_silver": 0x24,
    "eguitar_highway": 0x25,
    "eguitar_hexe": 0x26,
    "clarinet": 0x27,
    "horn": 0x28,
}

BDO_INSTRUMENT_NAMES = {
    0x00: "新手专用：吉他",
    0x01: "新手专用：长笛",
    0x02: "新手专用：笛子",
    0x04: "新手专用：手鼓",
    0x05: "新手专用：钹",
    0x06: "新手专用：竖琴",
    0x07: "新手专用：钢琴",
    0x08: "新手专用：小提琴",
    0x0A: "弗洛凯斯特拉：原声吉他",
    0x0B: "弗洛凯斯特拉：长笛",
    0x0D: "弗洛凯斯特拉：架子鼓套装",
    0x0E: "玛尔尼贝斯",
    0x0F: "弗洛凯斯特拉：低音提琴",
    0x10: "弗洛凯斯特拉：竖琴",
    0x11: "弗洛凯斯特拉：钢琴",
    0x12: "弗洛凯斯特拉：小提琴",
    0x13: "弗洛凯斯特拉：手碟",
    0x14: "玛勒尼斯：玛勒尼恩 - 波纹行星",
    0x18: "玛勒尼斯：玛勒尼恩 - 幻象树",
    0x1C: "玛勒尼斯：玛勒尼恩 - 秘密笔记",
    0x20: "玛勒尼斯：玛勒尼恩 - 三明治",
    0x24: "玛勒尼斯：电吉他 - 银色水波",
    0x25: "玛勒尼斯：电吉他 - 高速路",
    0x26: "玛勒尼斯：电吉他 - 赫克赛格莱姆",
    0x27: "弗洛凯斯特拉：单簧管",
    0x28: "弗洛凯斯特拉：圆号",
}

BDO_ENSEMBLE_PLAYER_LIMIT = 5
MARNIAN_SYNTH_INSTRUMENT_IDS = frozenset({0x14, 0x18, 0x1C, 0x20})
MARNIAN_SYNTH_MODE_OFFSETS = {
    "basic": 0,
    "stereo": 1,
    "super": 2,
    "superoct": 3,
}

# The current game guide exposes the shared Effector/AuxSend authoring path for
# Florchestra and Marnian instruments.  Beginner instruments still carry the
# same eight wire bytes and must round-trip losslessly, but those bytes are not
# evidence that the game authoring UI applies the buses to them.
BDO_EFFECT_CAPABLE_INSTRUMENT_IDS = frozenset(
    instrument_id
    for instrument_id in BDO_INSTRUMENT_NAMES
    if instrument_id not in {0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08}
)


def performance_instrument_id(serialized_id: int) -> int:
    """Map a wire ID to the physical instrument selected by a performer."""

    numeric_id = int(serialized_id)
    for base_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
        if base_id <= numeric_id <= base_id + 3:
            return base_id
    return numeric_id


def instrument_supports_composer_effects(instrument_id: int) -> bool:
    """Return whether current game authoring exposes Effector/AuxSend.

    Marnian mode IDs are serialized as base plus ``0..3``; capability belongs
    to the physical performance instrument, not to an individual sound mode.
    Unknown and beginner IDs fail closed while their wire settings remain
    available to the codec for lossless preservation.
    """

    return (
        performance_instrument_id(int(instrument_id))
        in BDO_EFFECT_CAPABLE_INSTRUMENT_IDS
    )


def unique_performance_instrument_ids(instrument_ids) -> tuple[int, ...]:
    """Preserve score order while collapsing sound modes of one instrument."""

    result: list[int] = []
    seen: set[int] = set()
    for raw_id in instrument_ids:
        instrument_id = performance_instrument_id(int(raw_id))
        if instrument_id not in seen:
            seen.add(instrument_id)
            result.append(instrument_id)
    return tuple(result)


InstrumentNameTranslator = Callable[[str], str]


def localized_bdo_instrument_name(
    instrument_id: int,
    translate: InstrumentNameTranslator,
) -> str:
    """Translate one fixed BDO catalog name without touching user music data.

    The canonical Chinese label is the exact-source localization key. Unknown
    IDs use a language-neutral fallback and are not passed to ``translate``.
    Callers remain responsible for leaving imported track names unchanged.
    """

    numeric_id = int(instrument_id)
    source_name = BDO_INSTRUMENT_NAMES.get(numeric_id)
    if source_name is None:
        if 0 <= numeric_id <= 0xFF:
            return f"BDO 0x{numeric_id:02X}"
        return f"BDO {numeric_id}"
    return translate(source_name)


def localized_bdo_instrument_names(
    translate: InstrumentNameTranslator,
) -> dict[int, str]:
    """Return a deterministic localized copy of the fixed instrument map."""

    return {
        instrument_id: localized_bdo_instrument_name(instrument_id, translate)
        for instrument_id in BDO_INSTRUMENT_NAMES
    }


DEFAULT_INSTRUMENT = BDO_INSTRUMENTS["piano"]
BDO_NOTE_MIN = 12
BDO_NOTE_MAX = 119

GM_PROGRAM_NAMES = (
    "原声大钢琴", "明亮原声钢琴", "电钢琴", "酒吧钢琴", "电钢琴 1", "电钢琴 2", "羽管键琴", "击弦古钢琴",
    "钢片琴", "钟琴", "音乐盒", "颤音琴", "马林巴", "木琴", "管钟", "扬琴",
    "拉杆风琴", "打击风琴", "摇滚风琴", "教堂风琴", "簧风琴", "手风琴", "口琴", "探戈手风琴",
    "原声吉他（尼龙弦）", "原声吉他（钢弦）", "电吉他（爵士）", "电吉他（清音）",
    "电吉他（闷音）", "过载吉他", "失真吉他", "吉他泛音",
    "原声贝斯", "电贝斯（指弹）", "电贝斯（拨片）", "无品贝斯", "击弦贝斯 1", "击弦贝斯 2", "合成贝斯 1", "合成贝斯 2",
    "小提琴", "中提琴", "大提琴", "低音提琴", "颤音弦乐", "拨奏弦乐", "管弦竖琴", "定音鼓",
    "弦乐合奏 1", "弦乐合奏 2", "合成弦乐 1", "合成弦乐 2", "人声合唱 Aah", "人声 Ooh", "合成合唱", "管弦乐打击",
    "小号", "长号", "大号", "弱音小号", "法国号", "铜管组", "合成铜管 1", "合成铜管 2",
    "高音萨克斯", "中音萨克斯", "次中音萨克斯", "上低音萨克斯", "双簧管", "英国管", "巴松管", "单簧管",
    "短笛", "长笛", "竖笛", "排箫", "瓶笛", "尺八", "口哨", "陶笛",
    "合成主音 1（方波）", "合成主音 2（锯齿波）", "合成主音 3（汽笛）", "合成主音 4（吹管）",
    "合成主音 5（锐音）", "合成主音 6（人声）", "合成主音 7（五度）", "合成主音 8（贝斯+主音）",
    "合成音色 1（新时代）", "合成音色 2（温暖）", "合成音色 3（复合）", "合成音色 4（合唱）",
    "合成音色 5（弓弦）", "合成音色 6（金属）", "合成音色 7（光环）", "合成音色 8（扫频）",
    "音效 1（雨）", "音效 2（配乐）", "音效 3（水晶）", "音效 4（氛围）",
    "音效 5（明亮）", "音效 6（精灵）", "音效 7（回声）", "音效 8（科幻）",
    "西塔琴", "班卓琴", "三味线", "古筝", "卡林巴", "风笛", "民谣小提琴", "唢呐",
    "铃铛", "阿哥哥铃", "钢鼓", "木鱼", "太鼓", "旋律鼓", "合成鼓", "反向钹",
    "吉他品噪", "呼吸声", "海浪声", "鸟鸣", "电话铃", "直升机", "掌声", "枪声",
)

_PROGRAM_FAMILIES = (
    (24, "piano"),
    (32, "guitar"),
    (40, "contrabass"),
    (42, "violin"),
    (44, "contrabass"),
    (47, "harp"),
    (48, "drum_set"),
    (56, "violin"),
    (64, "horn"),
    (72, "clarinet"),
    (88, "flute"),
    (96, "violin"),
    (104, "piano"),
    (112, "handpan"),
    (120, "hand_drum"),
    (128, "piano"),
)

_GM_TO_BDO_DRUM = {
    35: 48, 36: 48, 37: 49, 38: 50, 39: 50, 40: 50,
    41: 53, 42: 54, 43: 55, 44: 56, 45: 57, 46: 58,
    47: 59, 48: 60, 49: 61, 50: 60, 51: 62, 52: 61,
    53: 62, 54: 61, 55: 61, 56: 51, 57: 61, 58: 51,
    59: 62, 60: 63, 61: 64,
}


def gm_program_name(program: int) -> str:
    return GM_PROGRAM_NAMES[program] if 0 <= program < 128 else f"Program {program}"


def localized_gm_program_name(
    program: int,
    translate: InstrumentNameTranslator,
) -> str:
    """Localize a generated GM fallback once, before it becomes project data."""

    numeric_program = int(program)
    if 0 <= numeric_program < len(GM_PROGRAM_NAMES):
        return translate(GM_PROGRAM_NAMES[numeric_program])
    return f"GM Program {numeric_program}"


def gm_to_bdo_instrument(program: int, is_percussion: bool = False) -> int:
    if is_percussion:
        return BDO_INSTRUMENTS["drum_set"]
    explicit = {
        24: "guitar", 25: "guitar",
        26: "eguitar_silver", 27: "eguitar_silver", 28: "eguitar_silver",
        29: "eguitar_highway", 30: "eguitar_hexe", 31: "eguitar_hexe",
        32: "contrabass", 46: "harp", 47: "drum_set",
    }
    if program in explicit:
        return BDO_INSTRUMENTS[explicit[program]]
    if 33 <= program <= 39:
        return BDO_INSTRUMENTS["marnibass"]
    for upper_bound, instrument_name in _PROGRAM_FAMILIES:
        if program < upper_bound:
            return BDO_INSTRUMENTS[instrument_name]
    return DEFAULT_INSTRUMENT


__all__ = [
    "BDO_EFFECT_CAPABLE_INSTRUMENT_IDS", "BDO_ENSEMBLE_PLAYER_LIMIT",
    "BDO_INSTRUMENTS", "BDO_INSTRUMENT_NAMES",
    "BDO_NOTE_MIN", "BDO_NOTE_MAX", "MARNIAN_SYNTH_INSTRUMENT_IDS",
    "MARNIAN_SYNTH_MODE_OFFSETS",
    "GM_PROGRAM_NAMES",
    "InstrumentNameTranslator", "instrument_supports_composer_effects",
    "localized_bdo_instrument_name",
    "localized_bdo_instrument_names", "localized_gm_program_name",
    "DEFAULT_INSTRUMENT", "_GM_TO_BDO_DRUM", "gm_program_name",
    "gm_to_bdo_instrument", "performance_instrument_id",
    "unique_performance_instrument_ids",
]
