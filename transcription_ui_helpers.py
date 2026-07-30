"""Shared localization helpers for transcription UI surfaces."""

from __future__ import annotations

from bdo_transcription import TranscriptionResult
from i18n import trv


def transcription_cleanup_ui_labels(
    profile: str,
    report: object | None,
) -> tuple[object, object]:
    normalized = str(profile)
    profile_source = {
        "preserve": "保留（安全默认）",
        "balanced": "平衡（实验）",
        "clean": "干净（实验）",
    }.get(normalized)
    profile_label = trv(profile_source) if profile_source is not None else normalized
    if normalized == "preserve":
        return profile_label, trv("安全默认")
    if bool(getattr(report, "automatic_actions_enabled", False)):
        return profile_label, trv("实验性自动整理，未通过留出集验证")
    return profile_label, trv("实验性档位，等待缓存重解码")
