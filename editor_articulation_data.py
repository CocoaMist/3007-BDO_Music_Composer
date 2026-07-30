"""Shared editor-facing articulation catalog and usage guidance."""

from __future__ import annotations

from bdo_instrument_adaptation import articulation_pairs_by_instrument
from i18n import trfv, trv


BDO_ARTICULATIONS = {
    instrument_id: list(pairs)
    for instrument_id, pairs in articulation_pairs_by_instrument().items()
}

BDO_ARTICULATION_USAGE_HINTS = {
    0: "默认延音。适合旋律线、长音、和声铺底；不确定时优先保留。",
    1: "强调或游戏内标记型奏法。实际音色仍需验证，建议只在人工确认后使用。",
    2: "短促断奏。适合短音、明显断开的节奏型或跳音。",
    3: "向上滑入。适合后接更高音、间隔 1-4 半音且连接较紧的音。",
    4: "半音邻音颤动。适合长音或邻音来回装饰。",
    5: "全音邻音颤动。适合长音或全音邻音装饰。",
    6: "颤音/抖音。适合长音、快速同音重复或需要持续变化的音色。",
    7: "颤音变体。具体 BDO 音色需继续验证，建议先作为人工候选。",
    8: "大调颤音变体。适合全音邻音装饰，具体音色需验证。",
    9: "大调和弦。适合明确的大三和弦竖琴块，不适合单音旋律。",
    10: "小调和弦。适合明确的小三和弦竖琴块，不适合单音旋律。",
    11: "钢琴延音踏板。适合 MIDI CC64、和声保持、同和弦重叠延续。",
    12: "向下滑弦。适合后接更低音、间隔 1-4 半音的吉他/贝斯收尾。",
    13: "弱音。适合吉他/贝斯短促伴奏、切分节奏、低到中等力度重复音。",
    14: "泛音。适合高音区稀疏点缀或空灵音色，不适合整轨密集套用。",
    15: "三连音。适合一拍内三等分的局部节奏或三连音装饰。",
    16: "滑音。适合竖琴扫弦、贝斯滑奏或快速连续跨音程装饰。",
    17: "颤音变体。具体 BDO 音色需继续验证，建议先作为人工候选。",
    18: "大调颤音。适合全音邻音装饰或明亮颤动长音。",
    19: "颤音变体。具体 BDO 音色需继续验证，建议先作为人工候选。",
    20: "维持滤波器。适合玛勒尼恩合成铺底、长音和持续纹理，需人工验证。",
    21: "滤波铜管。适合明亮、高力度或铜管感合成长音，需人工验证。",
    22: "拍弦。适合贝斯高力度短音、funk 节奏或八度跳进。",
    23: "滑音上升。适合贝斯/低音提琴上行滑入目标音。",
    24: "X-音符。适合贝斯极短鬼音、死音或节奏填充，不保证明确音高。",
    25: "电吉他 FX 触发。只适合 C2-G2 特效触发音，不应自动套到普通旋律。",
    26: "弱力度持续音。适合单簧管/圆号长音，建议 velocity < 70。",
    27: "中力度持续音。适合单簧管/圆号长音，建议 velocity 70-99。",
    28: "强力度持续音。适合单簧管/圆号长音，建议 velocity >= 100。",
}


def articulation_display_value(inst_id: int, ntype: int | None) -> object:
    if ntype is None:
        return trv("默认")
    for candidate, label in BDO_ARTICULATIONS.get(inst_id, []):
        if candidate == ntype:
            return trfv(
                "{label} (type {ntype})",
                label=trv(label),
                ntype=ntype,
            )
    return f"type {ntype}"
