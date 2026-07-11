"""Evidence-backed articulation metadata for conservative MIDI optimization.

The profiles deliberately separate real-world technique evidence from the
reverse-engineered BDO ``ntype`` mapping.  A profile may be shown as a useful
suggestion without being eligible for automatic application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceLevel(StrEnum):
    VERIFIED = "已验证映射"
    COMMUNITY = "教程支持"
    INFERRED = "待游戏验证"


@dataclass(frozen=True)
class ArticulationProfile:
    instrument_ids: frozenset[int]
    ntype: int
    technique: str
    evidence: EvidenceLevel
    auto_apply: bool
    source: str
    contexts: tuple[str, ...] = ()
    forbidden_contexts: tuple[str, ...] = ()
    preferred_range: tuple[int, int] | None = None
    change_cost: str = "low"
    bdo_verified: bool = False


_SOURCE_STRINGS = "https://www.gamedev.net/articles/audio/music-and-sound-fx/a-brief-guide-to-orchestration-r2718/"
_SOURCE_GUITAR = "https://klang.io/blog/note-effect-notation/"
_SOURCE_HARP = "https://timbreandorchestration.org/isfee/extreme-orchestration/harp/scoring"
_SOURCE_PIANO = "https://piano.org/theory/guides/how-the-piano-works/"


PROFILES = (
    ArticulationProfile(frozenset({0x0A, 0x0E, 0x0F, 0x28}), 3, "向上滑动", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0A, 0x0E, 0x0F, 0x28}), 12, "向下滑动", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0A, 0x0E, 0x0F, 0x24, 0x25, 0x26}), 13, "弱音", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0A, 0x0E, 0x0F, 0x24, 0x25, 0x26}), 14, "泛音", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0E}), 22, "拍弦", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0E}), 23, "滑音上升", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0E}), 24, "X-音符", EvidenceLevel.VERIFIED, True, _SOURCE_GUITAR),
    ArticulationProfile(frozenset({0x0B, 0x12, 0x27, 0x28}), 2, "短促断奏", EvidenceLevel.VERIFIED, True, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x0B, 0x12, 0x27, 0x28}), 4, "半音颤音", EvidenceLevel.VERIFIED, True, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x12}), 5, "全音颤音", EvidenceLevel.VERIFIED, True, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x10}), 9, "大调和弦", EvidenceLevel.VERIFIED, True, _SOURCE_HARP),
    ArticulationProfile(frozenset({0x10}), 10, "小调和弦", EvidenceLevel.VERIFIED, True, _SOURCE_HARP),
    ArticulationProfile(frozenset({0x10}), 16, "滑音", EvidenceLevel.COMMUNITY, False, _SOURCE_HARP),
    ArticulationProfile(frozenset({0x11}), 11, "延音踏板", EvidenceLevel.VERIFIED, True, _SOURCE_PIANO),
    ArticulationProfile(frozenset({0x27, 0x28}), 26, "弱力度持续音", EvidenceLevel.VERIFIED, True, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x27, 0x28}), 27, "中力度持续音", EvidenceLevel.VERIFIED, True, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x27, 0x28}), 28, "强力度持续音", EvidenceLevel.VERIFIED, True, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x12, 0x24, 0x25, 0x26}), 6, "震音/颤音", EvidenceLevel.COMMUNITY, False, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x14}), 20, "维持滤波器", EvidenceLevel.INFERRED, False, _SOURCE_STRINGS),
    ArticulationProfile(frozenset({0x14}), 21, "滤波铜管", EvidenceLevel.INFERRED, False, _SOURCE_STRINGS),
)

# The compact entries above remain the BDO mapping source of truth.  This
# overlay records playable context separately so display labels never become
# algorithmic evidence.  Missing entries deliberately remain suggestion-only.
_MUSICAL_CONTEXT = {
    (0x0A, 3): (("melody", "connected"), ("chord", "cadence"), (40, 88), "medium"),
    (0x0A, 12): (("melody", "connected"), ("chord", "cadence"), (40, 88), "medium"),
    (0x0E, 13): (("bass_riff", "rhythm"), ("melody", "cadence"), (28, 62), "low"),
    (0x0E, 14): (("melody", "sparse"), ("chord",), (60, 100), "medium"),
    (0x0E, 22): (("bass_riff", "accent"), ("melody",), (28, 70), "medium"),
    (0x0B, 2): (("rhythm", "melody"), ("chord", "cadence"), (48, 96), "low"),
    (0x0B, 4): (("melody", "ornament"), ("chord",), (55, 100), "medium"),
    (0x12, 5): (("melody", "ornament"), ("chord",), (48, 96), "medium"),
    (0x10, 16): (("scale_run",), ("chord", "cadence"), (48, 100), "high"),
    (0x11, 11): (("harmony_hold",), ("staccato",), (21, 108), "low"),
    (0x27, 26): (("melody", "sustain"), ("phrase_boundary",), (48, 96), "medium"),
    (0x27, 27): (("melody", "sustain"), ("phrase_boundary",), (48, 96), "medium"),
    (0x27, 28): (("melody", "sustain"), ("phrase_boundary",), (48, 96), "medium"),
}

PROFILES = tuple(
    ArticulationProfile(
        profile.instrument_ids, profile.ntype, profile.technique, profile.evidence,
        profile.auto_apply, profile.source,
        *(next((_MUSICAL_CONTEXT[(instrument_id, profile.ntype)] for instrument_id in profile.instrument_ids
                if (instrument_id, profile.ntype) in _MUSICAL_CONTEXT), ((), (), None, "low"))),
        # A registered ntype mapping is not a game A/B validation.  The latter
        # must be recorded explicitly before generated note types are written.
        bdo_verified=False,
    )
    for profile in PROFILES
)

# Keep the registry exhaustive even where the game mapping is known but its
# audible behavior has not yet passed an A/B validation.  These entries are
# deliberately suggestion-only and never override a more specific profile.
_UNVERIFIED_NTYPES = {
    0x0A: (15,),
    0x0B: (1, 3, 15),
    0x0E: (16,),
    0x0F: (23,),
    0x12: (1, 3, 7, 8),
    0x14: (1, 2, 3, 4, 5, 6, 7, 8, 17, 18, 19),
    0x18: (1, 2, 3, 4, 5, 6, 7, 8, 17, 18, 19),
    0x1C: (1,),
    0x20: (1,),
    0x24: (25,),
    0x25: (25,),
    0x26: (25,),
    0x27: (7, 8, 15),
}
PROFILES += tuple(
    ArticulationProfile(frozenset({instrument_id}), ntype, "待验证奏法", EvidenceLevel.INFERRED, False, "游戏内 A/B 验证待补充")
    for instrument_id, ntypes in _UNVERIFIED_NTYPES.items()
    for ntype in ntypes
)


def profile_for(instrument_id: int, ntype: int) -> ArticulationProfile | None:
    for profile in PROFILES:
        if profile.ntype == ntype and instrument_id in profile.instrument_ids:
            return profile
    return None
