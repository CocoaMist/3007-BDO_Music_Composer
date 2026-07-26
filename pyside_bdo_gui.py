#!/usr/bin/env python3
"""GarageBand-style PySide6 MIDI workspace for BDO music conversion."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from functools import lru_cache
from html import escape
import faulthandler
import hashlib
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
from pathlib import Path

import numpy as np

ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
from project_paths import (
    ASSETS_DIR,
    GAME_ART_CACHE_DIR,
    PROFILES_DIR,
    SAMPLE_PACK_CACHE_DIR,
    USER_DATA_DIR,
    WWISE_MIDI_MAP_PATH,
)
WRITABLE_ROOT = (
    USER_DATA_DIR
    if (
        getattr(sys, "frozen", False)
        or os.environ.get("BDO_STARTUP_SELF_TEST") == "1"
    )
    else ROOT
)
DEFAULT_OUTDIR = WRITABLE_ROOT / "out" / "bdo"
DEFAULT_MIDI_DIR = ROOT / "samples"
CONFIG_PATH = WRITABLE_ROOT / ".pyside_bdo_gui.json"
AUTO_SAVE_DIR = WRITABLE_ROOT / "auto_save"
EXAMPLE_PROJECTS_DIR = USER_DATA_DIR / "examples"
BDO_SAMPLE_MAP_PATH = WWISE_MIDI_MAP_PATH
AUDIO_VALIDATION_PATH = DEFAULT_OUTDIR / "bdo_audio_validation_matrix.json"
CRASH_LOG_PATH = DEFAULT_OUTDIR / "crash.log"
REFERENCE_AUDIO_RESYNC_THRESHOLD_MS = 1250.0
REFERENCE_AUDIO_RESYNC_COOLDOWN_S = 5.0
TIMELINE_BACKGROUND_IMAGE = ASSETS_DIR / "ui" / "timeline_background_v2.png"
STARTUP_ART_IMAGE = ASSETS_DIR / "ui" / "loading_conductor_lineart.png"
TIMELINE_BACKGROUND_OPACITY = 0.42
TRANSCRIPTION_REVIEW_QUEUE_LIMIT = 240
DEFAULT_AUDIO_SOURCES = {
    "paz_root": os.environ.get("BDO_PAZ_ROOT", ""),
    "audio_root": os.environ.get("BDO_AUDIO_ROOT", ""),
    "sample_pack": "",
}


def _session_candidate_annotations(
    result: TranscriptionResult | None,
) -> tuple[CandidateAnnotation, ...]:
    report = (
        result.postprocess_report
        if result is not None
        else None
    )
    if report is None:
        return ()
    return tuple(
        CandidateAnnotation(
            candidate_id=item.candidate_id,
            flags=frozenset(item.flags),
            lineage_ids=frozenset(item.lineage_ids),
            disposition=item.disposition,
        )
        for item in report.annotations
    )


def _transcription_cleanup_ui_labels(
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


def _sample_coverage_status_value(status: str) -> object:
    source = {
        "verified_zone": "全部覆盖",
        "partial": "部分覆盖",
        "unmapped": "未映射",
    }.get(str(status))
    return trv(source) if source is not None else str(status)


_OPTIMIZER_HOST_MESSAGE_SOURCES = {
    "optimizer input contains duplicate track IDs": "优化器输入包含重复轨道 ID",
    "optimizer target scope references an unknown track": "优化目标范围引用了未知轨道",
    "song exceeds the optimizer note limit": "曲目超过优化器音符上限",
    "song exceeds the optimizer beat limit": "曲目超过优化器节拍上限",
    "the editor changed after analysis; analyse again": "分析后工程已变化；请重新分析",
    "preview algorithm identity does not match manifest": "预览算法标识与清单不一致",
    "plugins may not remove complete source tracks": (
        "算法不得删除完整的源轨道"
    ),
    "note pitch, velocity, or ntype is outside the wire range": (
        "音符的音高、力度或 ntype 超出协议范围"
    ),
    "note timing must be finite, non-negative, and non-zero": (
        "音符时间必须有限、非负且时值不为零"
    ),
    "derived drum notes require BDO pitch 48..64 and ntype=99": (
        "派生鼓音必须使用 BDO 音高 48..64 和 ntype=99"
    ),
    "preview may not duplicate or invent unsupported manual articulations": (
        "预览不得复制或新增不受支持的手动奏法"
    ),
    "preview may not add noncanonical drum pitches or note types": (
        "预览不得新增非规范鼓音高或音符类型"
    ),
    "drum tracks must use the canonical BDO drum-set instrument": (
        "鼓轨必须使用规范的 BDO 架子鼓乐器"
    ),
    "whole-track and indexed note operations may not be mixed": (
        "不得混用整轨操作与按索引音符操作"
    ),
    "preview source fingerprint does not match its request": (
        "预览源指纹与请求不一致"
    ),
    "a preview may set each source instrument only once": (
        "预览对每个源乐器只能设置一次"
    ),
    "a preview may contain only one global effect change": (
        "预览最多只能包含一次全局效果修改"
    ),
    "single-track optimization may not write global effects": (
        "单轨优化不得写入全局效果"
    ),
    "effect values must be in [0, 127]": "效果值必须在 [0, 127] 范围内",
    "single-track optimization may not create tracks": (
        "单轨优化不得创建轨道"
    ),
    "derived tracks must contain at least one note": (
        "派生轨道必须至少包含一个音符"
    ),
    "derived track references an unknown source track": (
        "派生轨道引用了未知源轨道"
    ),
    "preview exceeds the host song-note limit": (
        "预览超过主程序的曲目音符上限"
    ),
    "cannot materialize notes without a host Note prototype": (
        "缺少主程序 Note 原型，无法生成音符"
    ),
    "cannot create a derived track without a source track": (
        "缺少源轨道，无法创建派生轨道"
    ),
    "bundle contains too many files": "算法包包含过多文件",
    "bundle expands beyond the 16 GiB limit": "算法包解压后超过 16 GiB 上限",
    "bundle is missing manifest.json": "算法包缺少 manifest.json",
    "manifest root must be an object": "算法包清单根节点必须是对象",
    "plugin_id must be a stable lowercase identifier": (
        "plugin_id 必须是稳定的小写标识符"
    ),
    "version must be a path-safe identifier": "version 必须是路径安全的标识符",
    "intensities and scopes must be arrays": "intensities 和 scopes 必须是数组",
    "capabilities must be an array": "capabilities 必须是数组",
    "requires_safe_prepass must be a boolean": (
        "requires_safe_prepass 必须是布尔值"
    ),
    "plugins must support conservative, balanced, and deep": (
        "算法必须支持 conservative、balanced 和 deep"
    ),
    "plugin scopes are invalid": "算法 scopes 无效",
    "entrypoint must use module:function": "entrypoint 必须使用 module:function 格式",
    "entrypoint contains an invalid Python identifier": (
        "entrypoint 包含无效的 Python 标识符"
    ),
    "display_name must not be empty": "display_name 不能为空",
    "bundle is missing payload/": "算法包缺少 payload/ 目录",
    "external algorithm descriptor has no bundle": "外部算法描述缺少算法包",
    "optimizer plugin returned an incompatible preview object": (
        "优化算法返回了不兼容的预览对象"
    ),
    "plugin object must provide analyse(request, environment)": (
        "算法对象必须提供 analyse(request, environment)"
    ),
    "duplicate plugin ID; all copies disabled": "算法 ID 重复；所有副本均已禁用",
}


def _optimizer_host_message_value(message: object) -> object:
    """Translate recognized host validation text, never plugin-owned output."""

    text = str(message)
    source = _OPTIMIZER_HOST_MESSAGE_SOURCES.get(text)
    if source is not None:
        return trv(source)
    prefixed_sources = (
        ("cannot read optimizer bundle: ", "无法读取优化算法包：{value}"),
        ("unsafe bundle path: ", "算法包包含不安全路径：{value}"),
        (
            "symbolic links are not allowed in bundles: ",
            "算法包不允许符号链接：{value}",
        ),
        ("manifest fields invalid; ", "算法包清单字段无效：{value}"),
        ("unsupported bundle schema: ", "不支持的算法包 schema：{value}"),
        ("unsupported optimizer API: ", "不支持的优化器 API：{value}"),
        ("entrypoint is not callable: ", "entrypoint 不可调用：{value}"),
        ("unknown BDO instrument ID: ", "未知 BDO 乐器 ID：{value}"),
        ("stale note replacement for track ", "轨道 {value} 的音符替换已过期"),
        ("insert index outside track ", "插入索引超出轨道 {value} 的范围"),
        ("note index outside track ", "音符索引超出轨道 {value} 的范围"),
        (
            "stale indexed note operation for track ",
            "轨道 {value} 的索引音符操作已过期",
        ),
        (
            "duplicate indexed note operation for track ",
            "轨道 {value} 存在重复的索引音符操作",
        ),
        (
            "operation writes outside target scope: ",
            "操作写入了目标范围外的轨道：{value}",
        ),
        (
            "stale instrument replacement for track ",
            "轨道 {value} 的乐器替换已过期",
        ),
    )
    for prefix, template in prefixed_sources:
        if text.startswith(prefix):
            return trfv(template, value=text[len(prefix):])
    infixed_sources = (
        (
            "pitch ",
            " is unsupported for BDO instrument ",
            "音高 {value} 不受 BDO 乐器 {instrument_id} 支持",
        ),
        (
            "ntype ",
            " is unsupported for BDO instrument ",
            "ntype {value} 不受 BDO 乐器 {instrument_id} 支持",
        ),
    )
    for prefix, separator, template in infixed_sources:
        if not text.startswith(prefix):
            continue
        value, found, instrument_id = text[len(prefix):].partition(separator)
        if found and value and instrument_id:
            return trfv(
                template,
                value=value,
                instrument_id=instrument_id,
            )
    return text


def _optimizer_diagnostic_value(message: object) -> object:
    text = str(message)
    item, separator, reason = text.partition(": ")
    if not separator:
        return _optimizer_host_message_value(text)
    reason_value = _optimizer_host_message_value(reason)
    if isinstance(reason_value, str) and reason_value == reason:
        return text
    return trfv("{item}: {reason}", item=item, reason=reason_value)


def _redact_log_paths(value: object) -> str:
    """Remove machine-local absolute paths before text reaches a log file."""

    text = str(value)
    text = re.sub(
        r'"(?:(?:[A-Za-z]:[\\/])|(?:\\\\))[^"\r\n]*"',
        '"<private-path>"',
        text,
    )
    text = re.sub(
        r"'(?:(?:[A-Za-z]:[\\/])|(?:\\\\))[^'\r\n]*'",
        "'<private-path>'",
        text,
    )
    return re.sub(
        r"(?<![A-Za-z0-9_])(?:(?:[A-Za-z]:[\\/])|(?:\\\\))[^\s,;)\]}]+",
        "<private-path>",
        text,
    )


def append_crash_log(title: str, detail: str) -> None:
    try:
        CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CRASH_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(
                f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"{_redact_log_paths(title)}\n"
            )
            file.write(_redact_log_paths(detail).rstrip())
            file.write("\n")
    except Exception:
        pass


def install_crash_logging() -> None:
    try:
        # Native fault dumps contain interpreter source paths and bypass the
        # redaction boundary, so keep them on the process stderr rather than
        # persisting them in the user-visible crash log.
        faulthandler.enable(all_threads=True)
    except Exception:
        pass

    def handle_exception(exc_type, exc, tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        append_crash_log("Unhandled exception", detail)
        sys.__excepthook__(exc_type, exc, tb)

    def handle_thread_exception(args) -> None:
        detail = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        append_crash_log(f"Unhandled thread exception: {args.thread.name if args.thread else 'unknown'}", detail)

    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception

    class _TranscriptionCrashLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                detail = self.format(record)
                append_crash_log("Transcription diagnostic", detail)
            except Exception:
                pass

    transcription_logger = logging.getLogger("bdo_transcription")
    if not any(
        getattr(handler, "_bdo_transcription_crash_handler", False)
        for handler in transcription_logger.handlers
    ):
        handler = _TranscriptionCrashLogHandler(logging.WARNING)
        handler._bdo_transcription_crash_handler = True
        handler.setFormatter(
            logging.Formatter(
                "%(levelname)s %(name)s: %(message)s"
            )
        )
        transcription_logger.addHandler(handler)


try:
    import mido
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QEventLoop,
        QObject,
        QPointF,
        QPropertyAnimation,
        QRectF,
        QSize,
        Qt,
        QThread,
        QTimer,
        QUrl,
        Signal,
    )
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QShortcut
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat, QAudioOutput, QMediaPlayer
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGraphicsOpacityEffect,
        QGridLayout,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressDialog,
        QPushButton,
        QRadioButton,
        QScrollArea,
        QScrollBar,
        QSizePolicy,
        QSlider,
        QSpinBox,
        QStackedWidget,
        QTextBrowser,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:
    raise SystemExit(
        "PySide6/mido is not installed.\n"
        "Install dependencies with:\n"
        "  .\\.venv\\Scripts\\python.exe -m pip install -r requirements-pyside.txt"
    ) from exc

from bdo_midi import (  # noqa: E402
    BDO_INSTRUMENT_NAMES,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    Note,
    _GM_TO_BDO_DRUM,
    gm_to_bdo_instrument,
    parse_midi,
)
from bdo_midi.instruments import (  # noqa: E402
    localized_bdo_instrument_name,
    localized_bdo_instrument_names,
    localized_gm_program_name,
)
from bdo_export import (  # noqa: E402
    MAX_NOTES_PER_INSTRUMENT,
    channel_groups_to_bdo,
    midi_to_bdo,
)
from optimization import OptimizerConfig  # noqa: E402
from optimization.plugin_api import InvalidOptimizationPreview, OptimizationIntensity  # noqa: E402
from optimization.plugin_host import (  # noqa: E402
    BUILTIN_SAFE_ID,
    HostOptimizationError,
    analyse_with_algorithm,
    discover_host_algorithms,
    optimizer_plugin_dir,
)
from bdo_profile import load_bdo_profile  # noqa: E402
from bdo_track_effects import (  # noqa: E402
    GAME_PERCENT_MAX,
    MASTER_CHORUS_FEEDBACK_INDEX,
    MASTER_CHORUS_LFO_DEPTH_INDEX,
    MASTER_CHORUS_LFO_FREQUENCY_INDEX,
    MASTER_DELAY_FEEDBACK_INDEX,
    MASTER_REVERB_TIME_INDEX,
    MasterEffects,
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
    raw_track_settings,
)
from bdo_instrument_adaptation import (  # noqa: E402
    articulation_pairs_by_instrument,
    instrument_editor_display_adaptation,
    instrument_editor_display_adaptations,
)
from bdo_instrument_lane_art_qt import (  # noqa: E402
    InstrumentLaneArtwork,
    instrument_header_background_rect,
    paint_instrument_header_background,
)
from bdo_audio_research import sample_coverage_for_tracks  # noqa: E402
from bdo_score import compare_scores, encode_score, read_bdo_score, read_score  # noqa: E402
from bdo_codec import document_matches_logical_tracks, score_summary  # noqa: E402
from bdo_validation import (  # noqa: E402
    ValidationContext,
    ValidationIssue,
    evidence_status_source,
    issues_report,
    localized_validation_message,
    validate_tracks,
)
from project_schema import (  # noqa: E402
    CURRENT_PROJECT_SCHEMA,
    DEFAULT_REFERENCE_LAYER_SETTINGS,
    migrate_project,
    normalize_reference_layer_settings,
    project_relative_file_reference,
    resolve_project_file_reference,
)
from editor_commands import ProjectCommandStack, ProjectSnapshot  # noqa: E402
from bdo_sample_renderer import (  # noqa: E402
    sample_map_covers,
    sample_map_supported_pitches,
    sample_map_supports_note,
)
from bdo_realtime_audio import AudioEngineError, BdoRealtimeAudioEngine, bank_for_instrument  # noqa: E402
from process_metrics import ProcessMetricsSampler  # noqa: E402
from tools.import_bdo_game_art import (  # noqa: E402
    GameArtImportError,
    import_game_instrument_art,
)
from bdo_transcription import (  # noqa: E402
    DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
    DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    POSTPROCESS_VERSION,
    TranscriptionCancelled,
    TranscriptionCandidate,
    TranscriptionError,
    TranscriptionResult,
    load_cached_transcription_result,
    load_transcription_evidence,
    load_transcription_frame_times,
    prune_transcription_workspaces,
    redecode_transcription_full,
    redecode_transcription_interval,
    transcription_audio_fingerprint,
    transcription_backend_quick_status,
    transcribe_reference_audio,
)
from bdo_transcription_harmony import (  # noqa: E402
    ChordSegment,
    HarmonyAnalysisCancelled,
    HarmonyAnalysis,
    KeyEstimate,
    analyse_harmony,
    apply_harmony_overrides,
    harmony_cache_key,
)
from bdo_transcription_instruments import (  # noqa: E402
    BdoInstrumentDescriptor,
    InstrumentAnalysisCancelled,
    InstrumentMatchAnalysis,
    VoiceGroup,
    group_voice_candidates,
    match_bdo_instruments,
    overlay_manual_voice_groups,
    refine_voice_groups_by_timbre,
)
from bdo_transcription_timbre import (  # noqa: E402
    FramePitchEvidence,
    TimbreProfileError,
    extract_group_timbre_profiles,
    load_or_build_timbre_profile_index,
    remap_group_timbre_profiles,
)
from bdo_transcription_assist import (  # noqa: E402
    KeyReviewOverride,
    LockedChordReview,
    ManualVoiceGroupReview,
    TranscriptionAssistReviewState,
    isolate_assist_review_for_audio,
    recover_assist_review,
    stable_assist_review_id,
)
from bdo_transcription_policy import CANDIDATE_NOTE_POLICY  # noqa: E402
from bdo_transcription_session import (  # noqa: E402
    CandidateAnnotation,
    CandidateRoute,
    TranscriptionEditorCommit,
    TranscriptionEditorCommitReport,
    TranscriptionSession,
    TranscriptionSessionState,
)
from bdo_transcription_evidence_qt import EvidenceTileController  # noqa: E402
from bdo_spectrogram_qt import SpectrogramTileController  # noqa: E402
from bdo_transcription_melody_lines import (  # noqa: E402
    BASS_ROLE as MELODY_LINE_BASS_ROLE,
    CHORD_SPAN_KIND as MELODY_LINE_CHORD_SPAN_KIND,
    CONFIDENCE_BUCKETS as MELODY_LINE_CONFIDENCE_BUCKETS,
    CONNECTOR_KIND as MELODY_LINE_CONNECTOR_KIND,
    CONTOUR_KIND as MELODY_LINE_CONTOUR_KIND,
    GUIDE_ROLES as MELODY_LINE_GUIDE_ROLES,
    HARMONY_ROLE as MELODY_LINE_HARMONY_ROLE,
    PRIMARY_ROLE as MELODY_LINE_PRIMARY_ROLE,
    MelodyLineSegment,
    build_melody_line_segments,
    melody_line_confidence_bucket,
    melody_line_kind_visible,
    melody_line_lod,
    melody_line_width,
)
from transcription_editor_qt import (  # noqa: E402
    TranscriptionEditorPanel,
    TranscriptionWaveformLane,
    voice_role_label,
    voice_role_source_label,
)
from bdo_sample_pack import (  # noqa: E402
    PACK_SUFFIX,
    SamplePackCancelled,
    SamplePackError,
    extract_sample_pack,
)
from velocity_curve import apply_weighted_velocity_delta, velocity_time_points  # noqa: E402
from i18n import (  # noqa: E402
    LANGUAGE_CHOICES,
    defer_tr,
    install_localizer,
    localizer,
    tr,
    trf,
    trfv,
    tr_joinv,
    trv,
)
from fluent_theme import (  # noqa: E402
    FluentSymbol,
    build_fluent_stylesheet,
    configure_widget_style,
    fluent_icon_size,
    refresh_fluent_icons,
    set_fluent_symbol,
    system_uses_dark_theme,
)
from version import __version__  # noqa: E402
from third_party_credits import (  # noqa: E402
    BASIC_PITCH_LICENSE_URL,
    BASIC_PITCH_MODEL_URL,
    BASIC_PITCH_NOTICE_URL,
    CREDIT_ENTRIES,
    CREDIT_SECTION_SOURCES,
    RESEARCH_CITATIONS,
)


TRACK_COLORS = [
    "#d88c6f", "#8dbf67", "#6f9fd8", "#d8b66f", "#b887d8", "#70b8a8",
    "#d87592", "#91a7d8", "#c6d86f", "#d89f6f", "#8ed8ce", "#b9a0d8",
]

# Full translated command rails need these widths in the widest supported
# locale.  Below them, icon/short-label controls retain every action and expose
# the complete wording through tooltips and accessibility names.
EDITOR_VERBOSE_CONTROLS_MIN_WIDTH = 1660
MAIN_VERBOSE_CONTROLS_MIN_WIDTH = 1840


def _ui_bdo_instrument_name(instrument_id: int) -> str:
    """Translate one fixed game-instrument label, never user music data."""

    return localized_bdo_instrument_name(int(instrument_id), tr)


def _ui_bdo_instrument_source(instrument_id: int) -> str:
    """Return only the fixed source key; unknown IDs remain neutral data."""

    numeric_id = int(instrument_id)
    return BDO_INSTRUMENT_NAMES.get(numeric_id, f"BDO 0x{numeric_id:02X}")


def _ui_bdo_instrument_names() -> dict[int, str]:
    return localized_bdo_instrument_names(tr)

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

BDO_DYNAMIC_ARTICULATION_COLORS = {
    0: "#4f9d69",   # sustain / normal
    1: "#8e7cc3",   # tag
    2: "#c27c4a",   # cut
    3: "#2f9ea8",   # slide up
    4: "#756bb1",   # minor trill
    5: "#d27a9c",
    6: "#4c78a8",
    7: "#f28e2b",
    8: "#59a14f",
    9: "#b6992d",   # major chord
    10: "#9c6ade",  # minor chord
    11: "#e36f47",
    12: "#248f8d",  # slide down
    13: "#7b6a58",  # mute
    14: "#76b7b2",  # harmonic
    15: "#edc948",  # triplet
    16: "#af7aa1",  # glissando
    17: "#ff9da7",
    18: "#86bcb6",
    19: "#d4a6c8",
    20: "#499894",
    21: "#e15759",
    22: "#bc7c2f",  # slap
    23: "#3a86c8",  # slide rise
    24: "#6b7280",  # X note
    25: "#cf4b83",  # electric guitar FX
    26: "#5b90c9",  # SusPiano / light
    27: "#d9ae59",  # SusMezzoForte / medium
    28: "#d96658",  # SusForte / strong
}


def articulation_color(ntype: int | None) -> str:
    """Return a stable color for known and future game articulation types."""
    value = int(ntype or 0)
    known = BDO_DYNAMIC_ARTICULATION_COLORS.get(value)
    if known:
        return known
    # Golden-angle hue spacing keeps unknown types stable and well separated.
    hue = (value * 137 + 29) % 360
    color = QColor.fromHsv(hue, 165, 205)
    return color.name()


def contrasting_text_color(color: str) -> str:
    value = QColor(color)
    luminance = 0.299 * value.red() + 0.587 * value.green() + 0.114 * value.blue()
    return "#161816" if luminance >= 150 else "#f7f4ec"

BDO_DRUM_PITCH_NAMES = {
    48: "Kck",
    49: "SnrSide",
    50: "SnrHit",
    51: "RimShot",
    52: "SnrFlam",
    53: "Tom1",
    54: "HihatC",
    55: "Tom2",
    56: "HatPdl",
    57: "Tom3",
    58: "HihatO",
    59: "Tom4",
    60: "Tom5",
    61: "CymCrsh",
    62: "CymRide",
    63: "SnrRollS",
    64: "SnrRollL",
}
BDO_DRUM_MIN = 48
BDO_DRUM_MAX = 64
BDO_SAMPLE_ONLY_PERCUSSION = {0x04, 0x05, 0x13}
MARNIAN_SYNTH_INSTRUMENT_IDS = {0x14, 0x18, 0x1C, 0x20}
MARNIAN_SYNTH_MODES = [
    ("单声道（Basic）", "basic"),
    ("双声（Stereo）", "stereo"),
    ("增强（Super）", "super"),
    ("超级增强（Super Octave）", "superoct"),
]
MARNIAN_SYNTH_MODE_OFFSETS = {
    "basic": 0,
    "stereo": 1,
    "super": 2,
    "superoct": 3,
}


def track_uses_canonical_drum_lanes(track: "TrackState") -> bool:
    """Distinguish BDO 48–64/type-99 notes from imported GM drum keys."""

    if int(track.bdo_instrument_id) != 0x0D:
        return False
    if track.bdo_source_group_index is not None:
        return True
    if not track.notes:
        # Empty tracks created in this BDO editor start in the game's native
        # 17-lane representation.  No existing note is rewritten here.
        return True
    return all(
        BDO_DRUM_MIN <= int(note.pitch) <= BDO_DRUM_MAX
        and int(getattr(note, "ntype", 0)) == 99
        for note in track.notes
    )


def serialized_bdo_instrument_id(track: "TrackState") -> int:
    """Resolve the actual game track ID, including Marnian source mode."""
    instrument_id = int(track.bdo_instrument_id)
    if instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
        return instrument_id
    return instrument_id + MARNIAN_SYNTH_MODE_OFFSETS.get(track.marnian_synth_mode, 0)


def source_time_signature_denominator(midi_path: str | Path) -> int:
    """Return the first MIDI meter denominator; BDO v9 only stores /4."""
    try:
        midi = mido.MidiFile(str(midi_path), clip=True)
        for midi_track in midi.tracks:
            for message in midi_track:
                if message.type == "time_signature":
                    return int(message.denominator)
    except (OSError, ValueError, TypeError):
        pass
    return 4

# Ranges recorded in the hand-authored ``list*`` in-game baseline scores. The
# effective GUI range is the intersection of these limits and Wwise MIDI zones.
BDO_EDITOR_PITCH_RANGES = {
    0x00: range(12, 120),
    0x01: range(12, 108),
    0x02: range(36, 84),
    0x06: range(36, 96),
    0x07: range(12, 108),
    0x08: range(36, 84),
    0x0A: range(36, 89),
    0x0B: range(48, 89),
    0x0D: range(48, 65),
    0x0E: range(28, 65),
    0x0F: range(28, 65),
    0x10: range(12, 91),
    0x11: range(12, 108),
    0x12: range(43, 89),
    0x13: range(45, 89),
    0x14: range(12, 101),
    0x18: range(12, 101),
    0x1C: range(12, 101),
    0x20: range(12, 101),
    0x24: range(24, 96),
    0x25: range(24, 96),
    0x26: range(24, 96),
    0x27: range(24, 96),
    0x28: range(24, 96),
}

# Keep the context menu focused on musical function.  The source/region
# prefixes remain useful in inspectors and exports, but are deliberately not a
# navigation level when choosing a replacement instrument.
BDO_INSTRUMENT_MENU_GROUPS = [
    # Match the game's own "增加乐器" tabs exactly.  Bass and electric guitars
    # appear under the in-game string family rather than as extra top levels.
    ("管乐器", [0x01, 0x02, 0x0B, 0x27, 0x28]),
    ("弦乐器", [0x00, 0x06, 0x08, 0x0A, 0x0E, 0x0F, 0x10, 0x12, 0x24, 0x25, 0x26]),
    ("键盘乐器", [0x07, 0x11, 0x14, 0x18, 0x1C, 0x20]),
    ("打击乐器", [0x04, 0x05, 0x0D, 0x13]),
]


def articulation_label(inst_id: int, ntype: int | None) -> str:
    return str(articulation_display_value(inst_id, ntype))


def articulation_display_value(inst_id: int, ntype: int | None) -> object:
    """Return a deferred fixed label suitable for nesting inside ``trf``."""

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


def articulation_usage_hint(ntype: int | None) -> str:
    if ntype is None:
        return tr("未指定奏法，导出时保留普通音符。")
    return tr(
        BDO_ARTICULATION_USAGE_HINTS.get(
            ntype,
            "该奏法的游戏内音色仍需人工验证。",
        )
    )


def add_instrument_submenus(menu: QMenu, current_id: int, instrument_names: dict[int, str]) -> None:
    used_ids: set[int] = set()
    for type_name, inst_ids in BDO_INSTRUMENT_MENU_GROUPS:
        type_menu = menu.addMenu(tr(type_name))
        for inst_id in inst_ids:
            name = instrument_names.get(inst_id)
            if not name:
                continue
            used_ids.add(inst_id)
            # Official regional names are opaque display values.  Do not parse
            # them with Chinese punctuation assumptions.
            action = type_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)

    other_ids = [inst_id for inst_id in instrument_names if inst_id not in used_ids]
    if other_ids:
        other_menu = menu.addMenu(tr("其他"))
        for inst_id in other_ids:
            action = other_menu.addAction(instrument_names[inst_id])
            action.setCheckable(True)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)


@dataclass
class TrackState:
    track_id: int
    notes: list
    gm_program: int
    is_percussion: bool
    display_name: str
    bdo_instrument_id: int
    muted: bool = False
    solo: bool = False
    volume_scale: float = 1.0
    duration_scale: float = 1.0
    articulation_type: int | None = None
    # The four Marnian instruments expose this separate sound-source selector
    # in the game.  It is deliberately not an ntype articulation.
    marnian_synth_mode: str = "basic"
    color: str = "#d88c6f"
    effect_settings_placeholder: dict = field(default_factory=dict)
    performance_controls: list[dict] = field(default_factory=list)
    notes_optimized: bool = False
    # Exact BDO wire fields. volume_scale remains a note-velocity transform;
    # this byte is the independent per-track game mixer value.
    bdo_track_volume: int = 70
    bdo_track_settings: tuple[int, ...] = (0,) * 8
    bdo_source_group_index: int | None = None
    bdo_source_note_records: tuple[tuple, ...] = ()

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def end_ms(self) -> float:
        return max((note.start + note.dur for note in self.notes), default=0.0)

    @property
    def pitch_range(self) -> str:
        if not self.notes:
            return "-"
        return f"{note_name(min(n.pitch for n in self.notes))} - {note_name(max(n.pitch for n in self.notes))}"


@dataclass(frozen=True, slots=True)
class GhostNoteProjection:
    """One formal note projected from another track without losing identity."""

    note: object
    track_id: int = -1
    instrument_id: int = -1
    color: str = "#77787c"

    @property
    def pitch(self) -> int:
        return int(self.note.pitch)

    @property
    def vel(self) -> int:
        return int(self.note.vel)

    @property
    def start(self) -> float:
        return float(self.note.start)

    @property
    def dur(self) -> float:
        return float(self.note.dur)

    @property
    def ntype(self) -> int:
        return int(self.note.ntype)


@dataclass(frozen=True)
class HomeEntry:
    kind: str
    label: str
    path: Path
    detail: str
    modified_at: float
    version_count: int = 1


def decode_marnian_instrument(instrument_id: int) -> tuple[int, str]:
    for base_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
        for mode, offset in MARNIAN_SYNTH_MODE_OFFSETS.items():
            if instrument_id == base_id + offset:
                return base_id, mode
    return instrument_id, "basic"


def track_states_from_bdo_score(snapshot) -> list[TrackState]:
    """Collapse physical 730-note BDO chunks into logical editor tracks."""
    grouped: dict[int, list] = {}
    for physical_track in snapshot.tracks:
        grouped.setdefault(int(physical_track.group_index), []).append(physical_track)
    states: list[TrackState] = []
    for track_id, group_index in enumerate(sorted(grouped)):
        physical_tracks = grouped[group_index]
        instrument_ids = {int(track.instrument_id) for track in physical_tracks}
        if len(instrument_ids) != 1:
            raise ValueError(f"BDO instrument group {group_index} contains mixed instrument IDs")
        serialized_id = instrument_ids.pop()
        instrument_id, marnian_mode = decode_marnian_instrument(serialized_id)
        notes = [
            Note(
                int(note.pitch),
                int(note.velocity_a),
                float(note.start_ms),
                float(note.duration_ms),
                int(note.ntype),
            )
            for track in physical_tracks
            for note in track.notes
        ]
        notes.sort(key=lambda note: (note.start, note.pitch, note.dur))
        first_track = physical_tracks[0]
        states.append(
            TrackState(
                track_id=track_id,
                notes=notes,
                gm_program=0,
                is_percussion=serialized_id == 0x0D,
                display_name=_ui_bdo_instrument_name(instrument_id),
                bdo_instrument_id=instrument_id,
                marnian_synth_mode=marnian_mode,
                color=TRACK_COLORS[track_id % len(TRACK_COLORS)],
                effect_settings_placeholder={
                    "source_format": "bdo_v9",
                    "track_volume": int(first_track.volume),
                    "track_settings": list(first_track.settings),
                    "physical_track_count": len(physical_tracks),
                    "velocity_pair_mismatches": sum(
                        note.velocity_a != note.velocity_b
                        for track in physical_tracks
                        for note in track.notes
                    ),
                },
                bdo_track_volume=int(first_track.volume),
                bdo_track_settings=tuple(int(value) for value in first_track.settings),
                bdo_source_group_index=int(group_index),
                bdo_source_note_records=tuple(
                    (
                        int(note.pitch), int(note.velocity_a), float(note.start_ms),
                        float(note.duration_ms), int(note.ntype), int(note.velocity_b),
                    )
                    for track in physical_tracks for note in track.notes
                ),
            )
        )
    return states


def _home_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def scan_game_scores(directory: Path, limit: int = 80) -> list[HomeEntry]:
    """List score files without parsing private data embedded in BDO scores."""
    if not directory.is_dir():
        return []
    entries: list[HomeEntry] = []
    try:
        candidates = [path for path in directory.iterdir() if path.is_file() and not path.name.startswith(".")]
    except OSError:
        return []
    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            HomeEntry("game", path.stem or path.name, path, _home_timestamp(stat.st_mtime), stat.st_mtime)
        )
    entries.sort(key=lambda item: item.modified_at, reverse=True)
    return entries[:limit]


def scan_local_projects(directory: Path, limit: int = 80) -> list[HomeEntry]:
    """Read only safe project metadata; Owner ID and character name stay private."""
    if not directory.is_dir():
        return []
    entries: list[HomeEntry] = []
    for path in directory.glob("*/project.json"):
        try:
            stat = path.stat()
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        label = str(payload.get("output_name") or path.parent.name).strip() or path.parent.name
        entries.append(HomeEntry("project", label, path, _home_timestamp(stat.st_mtime), stat.st_mtime))
    entries.sort(key=lambda item: item.modified_at, reverse=True)
    return entries[:limit]


def scan_example_projects(directory: Path, limit: int = 8) -> list[HomeEntry]:
    """Read small local manifests without loading full example projects."""

    if not directory.is_dir():
        return []
    entries: list[HomeEntry] = []
    for manifest_path in directory.glob("*/example.json"):
        try:
            if manifest_path.stat().st_size > 64 * 1024:
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_name = str(manifest.get("project") or "project.json")
            if Path(project_name).is_absolute() or Path(project_name).name != project_name:
                continue
            project_path = manifest_path.parent / project_name
            stat = project_path.stat()
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if not project_path.is_file():
            continue
        title = str(manifest.get("title") or manifest_path.parent.name).strip()
        manifest_source = str(manifest.get("source") or "").strip()
        source = manifest_source if manifest_source else trv("未知来源")
        entries.append(HomeEntry(
            "example",
            title,
            project_path,
            trf("示例 · 来源：{source}", source=source),
            stat.st_mtime,
        ))
    entries.sort(key=lambda item: (item.label.casefold(), str(item.path).casefold()))
    return entries[:limit]


def _home_project_group_key(label: str) -> str:
    """Return a display-oriented key for grouping repeated project snapshots."""
    normalized = unicodedata.normalize("NFKC", str(label)).strip().casefold()
    return " ".join(normalized.split())


def merge_home_project_entries(
    entries: list[HomeEntry], limit: int = 80,
) -> list[HomeEntry]:
    """Collapse duplicate paths and same-title snapshots without deleting files.

    A local project is preferred as the open target because it carries current
    editor state; a recent MIDI/BDO entry is used only when no project snapshot
    exists. The group timestamp still reflects the latest activity of any item.
    """
    by_path: dict[str, HomeEntry] = {}
    for entry in entries:
        try:
            path_key = str(entry.path.resolve()).casefold()
        except OSError:
            path_key = str(entry.path).casefold()
        existing = by_path.get(path_key)
        if existing is None or entry.modified_at >= existing.modified_at:
            by_path[path_key] = entry

    groups: dict[str, list[HomeEntry]] = {}
    for entry in by_path.values():
        key = _home_project_group_key(entry.label) or str(entry.path).casefold()
        groups.setdefault(key, []).append(entry)

    merged: list[HomeEntry] = []
    for members in groups.values():
        members.sort(key=lambda item: item.modified_at, reverse=True)
        projects = [item for item in members if item.kind == "project"]
        target = projects[0] if projects else members[0]
        latest_at = members[0].modified_at
        version_count = len(members)
        detail = _home_timestamp(latest_at)
        if version_count > 1:
            detail = trf("{time} · {count} 个版本", time=detail, count=version_count)
        merged.append(HomeEntry(
            target.kind,
            target.label,
            target.path,
            detail,
            latest_at,
            version_count,
        ))
    merged.sort(key=lambda item: item.modified_at, reverse=True)
    return merged[:limit]


def note_name(midi_note: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = midi_note // 12 - 1
    return f"{names[midi_note % 12]}{octave}"


@lru_cache(maxsize=96)
def game_supported_pitches(
    instrument_id: int, synth_mode: str = "basic"
) -> frozenset[int] | None:
    """Exact game-sample keys when decoded, otherwise a verified editor range."""
    editor_range = BDO_EDITOR_PITCH_RANGES.get(instrument_id)
    if BDO_SAMPLE_MAP_PATH.is_file():
        try:
            pitches = sample_map_supported_pitches(
                BDO_SAMPLE_MAP_PATH, instrument_id, synth_mode
            )
            if pitches:
                if editor_range is not None:
                    return pitches.intersection(editor_range)
                return pitches
        except Exception:
            pass
    return frozenset(editor_range) if editor_range is not None else None


BDO_PROFILE = load_bdo_profile(
    PROFILES_DIR / "bdo_global_v9.json",
    articulation_map=BDO_ARTICULATIONS,
    supported_pitch_map={
        instrument_id: pitches
        for instrument_id in BDO_EDITOR_PITCH_RANGES
        if (pitches := game_supported_pitches(instrument_id))
    },
)


def game_pitch_range_label(
    instrument_id: int, synth_mode: str = "basic"
) -> str:
    return str(game_pitch_range_value(instrument_id, synth_mode))


def game_pitch_range_value(
    instrument_id: int,
    synth_mode: str = "basic",
) -> object:
    """Return a live-switch-safe game-range label."""

    pitches = game_supported_pitches(instrument_id, synth_mode)
    if not pitches:
        return trv("游戏音域待验证")
    low, high = min(pitches), max(pitches)
    gap_count = high - low + 1 - len(pitches)
    if gap_count:
        return trfv(
            "游戏 {low}-{high}（缺少 {gap_count} 个音）",
            low=note_name(low),
            high=note_name(high),
            gap_count=gap_count,
        )
    return trfv(
        "游戏 {low}-{high}",
        low=note_name(low),
        high=note_name(high),
    )


def default_game_music_dir() -> Path:
    return Path.home() / "Documents" / "Black Desert" / "music"


def copy_export_to_game(out_path: Path, game_dir: Path) -> Path:
    """Install one exported score, tolerating an output already in the game folder."""
    game_dir.mkdir(parents=True, exist_ok=True)
    installed = game_dir / out_path.name
    try:
        same_file = out_path.resolve() == installed.resolve()
    except OSError:
        same_file = False
    if not same_file:
        shutil.copy2(out_path, installed)
    return installed


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def audio_source_config(config: dict) -> dict[str, str]:
    """Return persistent local source roots without copying game assets."""
    saved = config.get("audio_sources", {})
    return {key: str(saved.get(key) or value) for key, value in DEFAULT_AUDIO_SOURCES.items()}


def displayed_audio_source(source_config: dict[str, str]) -> str:
    """Return the one user-selected preview source without losing raw roots."""

    return str(
        source_config.get("sample_pack", "")
        or source_config.get("audio_root", "")
        or ""
    )


def classify_audio_source(value: str) -> tuple[str, str]:
    """Split a local preview source into ``(sample_pack, audio_root)``.

    The settings dialog historically displayed only the packed source.  Saving
    unrelated settings therefore erased a valid raw sample directory.  Keep a
    single compact field in the UI, but preserve the two runtime source kinds
    explicitly at this boundary.
    """

    selected = str(value or "").strip()
    if not selected:
        return "", ""
    if selected.casefold().endswith(PACK_SUFFIX.casefold()):
        return selected, ""
    candidate = Path(selected)
    if candidate.is_dir():
        return "", str(candidate.resolve())
    raise ValueError(selected)


def safe_filename(value: str, fallback: str = "project") -> str:
    cleaned = "".join(ch if ch not in '<>:"/\\|?*' and ord(ch) >= 32 else "_" for ch in value).strip(" ._")
    return cleaned[:80] or fallback


def selected_tracks(tracks: list[TrackState]) -> list[TrackState]:
    solo_tracks = [track for track in tracks if track.solo]
    return solo_tracks if solo_tracks else [track for track in tracks if not track.muted]


def build_filtered_midi(tracks: list[TrackState], bpm: int, time_sig: int, out_path: Path,
                        lyric_events: list[dict] | None = None) -> None:
    mid = mido.MidiFile(ticks_per_beat=480)
    tempo = mido.bpm2tempo(max(1, min(240, bpm or 120)))
    numerator = max(1, min(32, int(time_sig or 4)))
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=numerator, denominator=4, time=0))
    lyric_midi_events = []
    for event in lyric_events or []:
        kind = str(event.get("kind", "lyrics"))
        if kind not in {"lyrics", "text", "marker", "cue_marker"}:
            continue
        try:
            tick = max(0, round(mido.second2tick(
                float(event.get("time", 0.0)) / 1000.0, mid.ticks_per_beat, tempo
            )))
            message = mido.MetaMessage(kind, text=str(event.get("text", "")), time=0)
        except (TypeError, ValueError):
            continue
        lyric_midi_events.append((tick, message))
    last_meta_tick = 0
    for tick, message in sorted(lyric_midi_events, key=lambda item: item[0]):
        message.time = max(0, tick - last_meta_tick)
        meta.append(message)
        last_meta_tick = tick
    meta.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(meta)

    def ms_to_ticks(ms: float) -> int:
        return max(0, round(mido.second2tick(ms / 1000.0, mid.ticks_per_beat, tempo)))

    for out_index, track_state in enumerate(tracks):
        channel = 9 if track_state.is_percussion else min(out_index, 8)
        events: list[tuple[int, int, object]] = []
        if not track_state.is_percussion:
            events.append((0, 0, mido.Message("program_change", channel=channel, program=track_state.gm_program)))
        for control in track_state.performance_controls:
            kind = str(control.get("kind", "control_change"))
            try:
                tick = ms_to_ticks(float(control.get("time", 0.0)))
                if kind == "control_change":
                    message = mido.Message(
                        "control_change", channel=channel,
                        control=max(0, min(127, int(control["control"]))),
                        value=max(0, min(127, int(control["value"]))),
                    )
                elif kind == "pitchwheel":
                    message = mido.Message(
                        "pitchwheel", channel=channel,
                        pitch=max(-8192, min(8191, int(control["pitch"]))),
                    )
                elif kind == "aftertouch":
                    message = mido.Message(
                        "aftertouch", channel=channel,
                        value=max(0, min(127, int(control["value"]))),
                    )
                elif kind == "polytouch":
                    message = mido.Message(
                        "polytouch", channel=channel,
                        note=max(0, min(127, int(control["note"]))),
                        value=max(0, min(127, int(control["value"]))),
                    )
                else:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            events.append((tick, 1, message))
        for note in track_state.notes:
            start = ms_to_ticks(note.start)
            end = ms_to_ticks(note.start + max(1.0, note.dur * track_state.duration_scale))
            velocity = max(1, min(127, round(note.vel)))
            events.append((start, 1, mido.Message("note_on", channel=channel, note=note.pitch, velocity=velocity)))
            events.append((end, 0, mido.Message("note_off", channel=channel, note=note.pitch, velocity=0)))
        events.sort(key=lambda item: (item[0], item[1]))
        midi_track = mido.MidiTrack()
        last_tick = 0
        for tick, _order, message in events:
            message.time = max(0, tick - last_tick)
            midi_track.append(message)
            last_tick = tick
        midi_track.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(midi_track)
    mid.save(out_path)


class ElidedLabel(QLabel):
    """A one-line label that yields space without hiding its full value."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        maximum_hint_width: int = 240,
    ) -> None:
        super().__init__(text, parent)
        self.maximum_hint_width = max(40, int(maximum_hint_width))
        if text:
            self.setToolTip(text)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(self.maximum_hint_width, hint.width()), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(36, hint.width()), hint.height())

    def setText(self, text: str) -> None:
        value = str(text)
        super().setText(value)
        self.setToolTip(value)

    def paintEvent(self, event) -> None:
        rect = self.contentsRect()
        if self.fontMetrics().horizontalAdvance(self.text()) <= rect.width():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            rect,
            self.alignment(),
            self.fontMetrics().elidedText(
                self.text(), Qt.ElideRight, max(0, rect.width())
            ),
        )


class PillButton(QPushButton):
    def __init__(
        self,
        text: str,
        kind: str = "secondary",
        icon: FluentSymbol | None = None,
    ) -> None:
        super().__init__(text)
        self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)
        if icon is not None:
            set_fluent_symbol(self, icon)
            self.setIconSize(fluent_icon_size())


class LoadingSpinner(QWidget):
    """Small code-drawn indeterminate indicator with no image dependency."""

    def __init__(self, size: int = 42, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LoadingSpinner")
        self.setFixedSize(size, size)
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(65)
        self._timer.timeout.connect(self._advance)

    @property
    def frame(self) -> int:
        return self._frame

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:
        self.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % 12
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        radius = max(7.0, min(self.width(), self.height()) / 2.0 - 5.0)
        spoke = max(4.0, radius * 0.34)
        line_width = max(2.0, self.width() / 15.0)
        for index in range(12):
            distance = (index - self._frame) % 12
            alpha = max(38, 255 - distance * 19)
            pen = QPen(QColor(245, 165, 36, alpha), line_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(0.0, -radius),
                QPointF(0.0, -radius + spoke),
            )
            painter.rotate(30.0)


class StartupArtwork(QWidget):
    """Clipped cover rendering for the startup illustration."""

    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StartupArtwork")
        self.setFixedSize(454, 718)
        self._source = QPixmap(str(image_path))
        self._cover = QPixmap()
        self._refresh_cover()

    @property
    def has_artwork(self) -> bool:
        return not self._source.isNull()

    def _refresh_cover(self) -> None:
        if self._source.isNull():
            self._cover = QPixmap()
            return
        self._cover = self._source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(bounds, 7.0, 7.0)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QColor("#eee7da"))
        if not self._cover.isNull():
            source_x = max(0, (self._cover.width() - self.width()) // 2)
            source_y = max(0, (self._cover.height() - self.height()) // 2)
            painter.drawPixmap(
                self.rect(),
                self._cover,
                self._cover.rect().adjusted(
                    source_x,
                    source_y,
                    -source_x,
                    -source_y,
                ),
            )
        shade = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        shade.setColorAt(0.0, QColor(24, 22, 19, 0))
        shade.setColorAt(0.72, QColor(24, 22, 19, 0))
        shade.setColorAt(1.0, QColor(24, 22, 19, 118))
        painter.fillRect(self.rect(), shade)
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#7b5a2c"), 1.0))
        painter.drawRoundedRect(bounds, 7.0, 7.0)


class StartupSplash(QWidget):
    """Theme-aligned startup surface shown while the real window is built."""

    MINIMUM_VISIBLE_MS = 1500
    FADE_OUT_MS = 320

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("StartupSplash")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(470, 734)
        self._shown_at = time.monotonic()
        self._pending_window: QWidget | None = None
        self._finish_scheduled = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        card = QFrame()
        card.setObjectName("StartupSplashCard")
        outer.addWidget(card)
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self.artwork = StartupArtwork(STARTUP_ART_IMAGE)
        card_layout.addWidget(self.artwork, 0, 0)

        content = QFrame()
        content.setObjectName("StartupOverlay")
        content.setFixedWidth(self.artwork.width())
        layout = QVBoxLayout(content)
        layout.setContentsMargins(22, 15, 22, 17)
        layout.setSpacing(9)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        eyebrow = QLabel("BDO MUSIC COMPOSER")
        eyebrow.setObjectName("StartupEyebrow")
        brand.addWidget(eyebrow)
        brand.addStretch(1)
        title = QLabel(tr("正在打开曲谱工作台"))
        title.setObjectName("StartupTitle")
        brand.addWidget(title)
        layout.addLayout(brand)

        activity = QHBoxLayout()
        activity.setSpacing(12)
        self.spinner = LoadingSpinner(34)
        activity.addWidget(self.spinner, alignment=Qt.AlignVCenter)
        status_group = QVBoxLayout()
        status_group.setSpacing(3)
        self.status_label = QLabel(tr("正在启动音乐工作台…"))
        self.status_label.setObjectName("StartupStatus")
        detail = QLabel(tr("本地项目和游戏曲谱只在这台电脑上读取"))
        detail.setObjectName("StartupDetail")
        detail.setWordWrap(True)
        status_group.addWidget(self.status_label)
        status_group.addWidget(detail)
        activity.addLayout(status_group, stretch=1)
        layout.addLayout(activity)
        card_layout.addWidget(content, 0, 0, alignment=Qt.AlignBottom)

        self.setStyleSheet(
            """
            QWidget#StartupSplash { background: transparent; }
            QFrame#StartupSplashCard {
                background: #171614;
                border: 1px solid #5b4527;
                border-radius: 11px;
            }
            QFrame#StartupOverlay {
                background: rgba(20, 18, 15, 226);
                border: 0;
                border-top: 1px solid rgba(216, 155, 55, 120);
            }
            QLabel#StartupEyebrow {
                color: #d89b37;
                font-family: "Microsoft YaHei UI";
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 2px;
            }
            QLabel#StartupTitle {
                color: #d1c8b9;
                font-family: "Microsoft YaHei UI";
                font-size: 10px;
                font-weight: 700;
            }
            QLabel#StartupStatus {
                color: #f0c66f;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
                font-weight: 800;
            }
            QLabel#StartupDetail {
                color: #948e87;
                font-family: "Microsoft YaHei UI";
                font-size: 10px;
            }
            """
        )
        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity)
        self.fade_animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.fade_animation.setDuration(self.FADE_OUT_MS)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.fade_animation.finished.connect(self._complete_reveal)

    def showEvent(self, event) -> None:
        self._shown_at = time.monotonic()
        self._finish_scheduled = False
        self.opacity.setOpacity(1.0)
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(available.center() - self.rect().center())
        self.spinner.start()
        self.raise_()
        self.activateWindow()

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def finish(self, window: QWidget, minimum_visible_ms: int | None = None) -> None:
        if self._finish_scheduled:
            return
        self._finish_scheduled = True
        self._pending_window = window
        minimum = self.MINIMUM_VISIBLE_MS if minimum_visible_ms is None else max(0, minimum_visible_ms)
        elapsed = round((time.monotonic() - self._shown_at) * 1000.0)
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(max(0, minimum - elapsed), self._begin_reveal)

    def _begin_reveal(self) -> None:
        self.spinner.stop()
        self.raise_()
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.opacity.opacity())
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.start()

    def _complete_reveal(self) -> None:
        window = self._pending_window
        self.hide()
        self._pending_window = None
        if window is not None:
            window.raise_()
            window.activateWindow()


class GlobalToast(QFrame):
    """One non-blocking message surface shared by each top-level window."""

    COLORS = {
        "info": "#f0c66f",
        "success": "#8fcf9d",
        "warning": "#f5a524",
        "error": "#ef8178",
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("GlobalToast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumWidth(280)
        self.setMaximumWidth(540)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 10, 15, 10)
        layout.setSpacing(10)
        self.marker = QLabel("●")
        self.marker.setObjectName("ToastMarker")
        self.marker.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.marker)
        self.message = QLabel()
        self.message.setObjectName("ToastMessage")
        self.message.setWordWrap(True)
        self.message.setMaximumWidth(460)
        layout.addWidget(self.message, stretch=1)

        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._animation_finished)
        self._animation_phase = ""
        self._hold_duration_ms = 2600
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.fade_out)
        self.setStyleSheet(
            """
            QFrame#GlobalToast {
                background: #28241e;
                border: 1px solid #66502d;
                border-radius: 7px;
            }
            QLabel#ToastMessage {
                color: #f3eee6;
                font-family: "Microsoft YaHei UI";
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#ToastMarker {
                font-family: "Microsoft YaHei UI";
                font-size: 11px;
            }
            """
        )
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parent() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            QTimer.singleShot(0, self._reposition)
        return super().eventFilter(watched, event)

    def show_message(self, text: str, kind: str = "info", duration_ms: int = 2600) -> None:
        if not text:
            return
        self.animation.stop()
        self.hold_timer.stop()
        self.message.setText(text)
        self.marker.setStyleSheet(f"color: {self.COLORS.get(kind, self.COLORS['info'])};")
        self.opacity.setOpacity(0.0)
        self.show()
        self.adjustSize()
        self._reposition()
        self.raise_()
        self.animation.setDuration(170)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self._animation_phase = "in"
        self._hold_duration_ms = max(0, duration_ms)
        self.animation.start()

    def fade_out(self) -> None:
        self.animation.stop()
        self.animation.setDuration(260)
        self.animation.setStartValue(self.opacity.opacity())
        self.animation.setEndValue(0.0)
        self._animation_phase = "out"
        self.animation.start()

    def _animation_finished(self) -> None:
        if self._animation_phase == "in":
            self.hold_timer.start(self._hold_duration_ms)
        elif self._animation_phase == "out":
            self.hide()
        self._animation_phase = ""

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return
        x = max(16, (parent.width() - self.width()) // 2)
        if parent.objectName() == "MidiNoteEditorDialog":
            workspace = parent.findChild(QFrame, "EditorWorkspace")
            y = (workspace.geometry().top() + 12) if workspace is not None else 148
        elif parent.objectName() == "SettingsDialog":
            content = parent.findChild(QWidget, "SettingsContent")
            y = (content.geometry().top() + 12) if content is not None else 84
        else:
            y = 64 if parent.height() >= 180 else 16
        self.move(x, y)


def show_global_toast(
    host: QWidget,
    text: str,
    kind: str = "info",
    duration_ms: int = 2600,
) -> GlobalToast:
    top_level = host.window()
    toast = getattr(top_level, "_global_toast", None)
    if not isinstance(toast, GlobalToast):
        toast = GlobalToast(top_level)
        setattr(top_level, "_global_toast", toast)
    # Callers translate fixed copy before it reaches this dynamic display
    # boundary.  Re-translating here could corrupt a filename or track name
    # that happens to equal a catalog value such as "Play".
    toast.show_message(text, kind=kind, duration_ms=duration_ms)
    return toast


class TimelineCanvas(QWidget):
    changed = Signal()
    track_state_changed = Signal()
    instrument_changed = Signal(object)
    selected = Signal(object)
    effects_requested = Signal(object)
    midi_tools_requested = Signal(object)
    note_editor_requested = Signal(object)
    seek_requested = Signal(float)
    time_range_changed = Signal(object)
    playhead_changed = Signal(float)
    TRACK_NOTE_QUERY_BLOCK_SIZE = 128

    def __init__(self) -> None:
        super().__init__()
        self.tracks: list[TrackState] = []
        self.hit_regions: list[tuple[QRectF, str, object]] = []
        self.reference_audio: ReferenceAudioController | None = None
        self.zoom_factor = 1.0
        self.view_start_ms = 0.0
        self.playhead_ms = 0.0
        self.bpm = 120
        self.time_sig = 4
        self.beat_origin_ms = 0.0
        self.buffer_progress = 0.0
        self.buffer_visible = False
        self.track_levels: dict[int, float] = {}
        self.grid_rect = QRectF()
        self.dragging_timeline = False
        self.last_drag_x = 0.0
        self.range_start_ms: float | None = None
        self.range_end_ms: float | None = None
        self._range_drag_anchor_ms: float | None = None
        self._range_drag_mode = ""
        self._range_drag_moved = False
        self._volume_drag_track: TrackState | None = None
        self._volume_drag_rect = QRectF()
        self._volume_drag_initial = 70
        self.selected_track: TrackState | None = None
        self.conversion_transpose = 0
        self.background_pixmap = QPixmap(str(TIMELINE_BACKGROUND_IMAGE)) if TIMELINE_BACKGROUND_IMAGE.is_file() else QPixmap()
        self._scaled_background = QPixmap()
        self._scaled_background_size = QSize()
        self._instrument_adaptations = instrument_editor_display_adaptations()
        self.instrument_lane_art = InstrumentLaneArtwork()
        self.track_scroll = QScrollBar(Qt.Vertical, self)
        # Entries keep the original first five fields for the pitch/range
        # helpers, followed by exact ends and a block-max segment tree used by
        # interval viewport queries.
        self._track_note_indexes: dict[int, tuple] = {}
        self._last_track_note_query_inspections = 0
        self._conversion_problem_cache: dict[
            tuple[int, str, int, int, bool], bool
        ] = {}
        self._timeline_end_cache = 1.0
        self.track_scroll.setObjectName("TimelineScroll")
        self.track_scroll.valueChanged.connect(self.update)
        self.setMouseTracking(True)
        self.setMinimumHeight(380)

    def set_instrument_art_dir(self, directory: str | Path | None) -> int:
        """Preload optional user artwork; painting remains filesystem-free."""

        loaded = self.instrument_lane_art.reload(
            directory,
            {
                instrument_id: adaptation.visual_key
                for instrument_id, adaptation
                in self._instrument_adaptations.items()
            },
        )
        self.update()
        return loaded

    def set_tracks(self, tracks: list[TrackState]) -> None:
        self.tracks = tracks
        valid_track_ids = {int(track.track_id) for track in tracks}
        self.track_levels = {
            track_id: level for track_id, level in self.track_levels.items()
            if track_id in valid_track_ids
        }
        self._rebuild_track_indexes()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self.setMinimumHeight(380)
        self._update_track_scrollbar()
        self.update()

    def set_reference_audio(self, controller: "ReferenceAudioController") -> None:
        if self.reference_audio is controller:
            return
        if self.reference_audio is not None:
            try:
                self.reference_audio.changed.disconnect(self.update)
                self.reference_audio.timeline_changed.disconnect(self._reference_audio_updated)
            except (RuntimeError, TypeError):
                pass
        self.reference_audio = controller
        controller.changed.connect(self.update)
        controller.timeline_changed.connect(self._reference_audio_updated)
        self._reference_audio_updated()

    def _reference_audio_updated(self) -> None:
        self._rebuild_track_indexes()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self.update()

    def _timeline_row_count(self) -> int:
        return len(self.tracks) + (1 if self.reference_audio is not None else 0)

    def set_track_levels(self, levels: dict[int, float]) -> None:
        normalized = {
            int(track_id): max(0.0, min(1.0, float(level)))
            for track_id, level in levels.items()
        }
        if normalized == self.track_levels:
            return
        self.track_levels = normalized
        area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
        self.update(QRectF(
            area.left() + header_w - 18,
            area.top() + ruler_h,
            18,
            max(0.0, area.height() - ruler_h),
        ).toAlignedRect())

    def _rebuild_track_indexes(self) -> None:
        self._track_note_indexes = {}
        self._conversion_problem_cache.clear()
        timeline_end = 1.0
        for track in self.tracks:
            ordered = sorted(track.notes, key=lambda note: note.start)
            starts = [float(note.start) for note in ordered]
            scaled_durations = [
                float(note.dur) * track.duration_scale
                for note in ordered
            ]
            max_duration = max(scaled_durations, default=0.0)
            ends = [
                start + duration
                for start, duration in zip(starts, scaled_durations)
            ]
            block_size = self.TRACK_NOTE_QUERY_BLOCK_SIZE
            block_count = (len(ends) + block_size - 1) // block_size
            tree_base = 1 << max(0, (block_count - 1).bit_length())
            block_max_tree = [float("-inf")] * (tree_base * 2)
            for block_index in range(block_count):
                block_start = block_index * block_size
                block_stop = min(len(ends), block_start + block_size)
                block_max_tree[tree_base + block_index] = max(
                    ends[block_start:block_stop],
                    default=float("-inf"),
                )
            for node in range(tree_base - 1, 0, -1):
                block_max_tree[node] = max(
                    block_max_tree[node * 2],
                    block_max_tree[node * 2 + 1],
                )
            pitch_min = min((note.pitch for note in ordered), default=0)
            pitch_max = max((note.pitch for note in ordered), default=0)
            self._track_note_indexes[id(track)] = (
                starts,
                ordered,
                max_duration,
                pitch_min,
                pitch_max,
                ends,
                block_max_tree,
                tree_base,
            )
            timeline_end = max(
                timeline_end,
                max(ends, default=0.0),
            )
        if self.reference_audio is not None:
            timeline_end = max(timeline_end, self.reference_audio.project_end_ms)
        self._timeline_end_cache = timeline_end

    def _visible_track_notes(self, track: TrackState, start: float, end: float) -> list:
        ordered, lo, hi = self._visible_track_note_window(track, start, end)
        if lo == 0 and hi == len(ordered):
            return ordered
        return ordered[lo:hi]

    def _visible_track_note_window(
        self, track: TrackState, start: float, end: float,
    ) -> tuple[list, int, int]:
        self._last_track_note_query_inspections = 0
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(
                id(track),
                ([], [], 0.0, 0, 0, [], [float("-inf"), float("-inf")], 1),
            )
        (
            starts,
            ordered,
            _max_duration,
            _pitch_min,
            _pitch_max,
            ends,
            block_max_tree,
            tree_base,
        ) = index
        hi = bisect_right(starts, end)
        if hi <= 0:
            return [], 0, 0

        block_size = self.TRACK_NOTE_QUERY_BLOCK_SIZE
        last_block = (hi - 1) // block_size
        matching_blocks: list[int] = []
        # Prefix-range + maximum-end pruning is a small segment-tree query:
        # future blocks are discarded by range and old blocks whose notes have
        # all ended are discarded without inspecting individual notes.
        stack = [(1, 0, tree_base)]
        while stack:
            node, node_start, node_stop = stack.pop()
            if node_start > last_block or block_max_tree[node] < start:
                continue
            if node_stop - node_start == 1:
                matching_blocks.append(node_start)
                continue
            midpoint = (node_start + node_stop) // 2
            stack.append((node * 2 + 1, midpoint, node_stop))
            stack.append((node * 2, node_start, midpoint))

        visible: list = []
        for block_index in matching_blocks:
            block_start = block_index * block_size
            block_stop = min(hi, block_start + block_size)
            self._last_track_note_query_inspections += block_stop - block_start
            for note_index in range(block_start, block_stop):
                if ends[note_index] >= start:
                    visible.append(ordered[note_index])
        return visible, 0, len(visible)

    def _track_pitch_bounds(self, track: TrackState) -> tuple[int, int]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track), ([], [], 0.0, 0, 0))
        return index[3], index[4]

    def set_selected_track(self, track: TrackState | None) -> None:
        self.selected_track = track
        self.update()

    def set_conversion_transpose(self, semitones: int) -> None:
        semitones = int(semitones)
        if semitones == self.conversion_transpose:
            return
        self.conversion_transpose = semitones
        self._conversion_problem_cache.clear()
        self.update()

    def set_musical_grid(
        self,
        bpm: int,
        time_sig: int,
        beat_origin_ms: float,
    ) -> None:
        values = (
            max(1, int(bpm)),
            max(1, int(time_sig)),
            float(beat_origin_ms),
        )
        if values == (self.bpm, self.time_sig, self.beat_origin_ms):
            return
        self.bpm, self.time_sig, self.beat_origin_ms = values
        self.update()

    def _visible_musical_ticks(
        self,
        visible_start: float,
        visible_duration: float,
        grid_width: float,
    ) -> list[tuple[float, bool, str]]:
        beat_ms = 60000.0 / max(1, self.bpm)
        measure_ms = beat_ms * max(1, self.time_sig)
        beat_pixels = grid_width * beat_ms / max(1.0, visible_duration)
        factor = 1
        while beat_pixels * factor < 34.0:
            factor *= 2
        step_ms = beat_ms * factor
        first = self.beat_origin_ms + math.floor(
            (visible_start - self.beat_origin_ms) / step_ms
        ) * step_ms
        end = visible_start + visible_duration
        ticks: list[tuple[float, bool, str]] = []
        value = first
        for _index in range(514):
            if value > end + step_ms:
                break
            measure_position = (
                (value - self.beat_origin_ms) / measure_ms
            )
            nearest_measure = round(measure_position)
            is_major = abs(measure_position - nearest_measure) < 1e-4
            label = (
                str(nearest_measure + 1)
                if is_major
                else ""
            )
            ticks.append((value, is_major, label))
            value += step_ms
        return ticks

    def _note_has_conversion_problem(self, track: TrackState, pitch: int) -> bool:
        canonical_drum_lanes = track_uses_canonical_drum_lanes(track)
        cache_key = (
            int(track.bdo_instrument_id),
            str(track.marnian_synth_mode),
            int(pitch),
            self.conversion_transpose,
            canonical_drum_lanes,
        )
        cached = self._conversion_problem_cache.get(cache_key)
        if cached is not None:
            return cached
        if track.bdo_instrument_id == 0x0d:
            if canonical_drum_lanes:
                supported = game_supported_pitches(
                    track.bdo_instrument_id, track.marnian_synth_mode
                )
                result = not (
                    BDO_DRUM_MIN <= int(pitch) <= BDO_DRUM_MAX
                    and (supported is None or int(pitch) in supported)
                )
            else:
                mapped_pitch = _GM_TO_BDO_DRUM.get(pitch)
                if (
                    mapped_pitch is None
                    or mapped_pitch < BDO_DRUM_MIN
                    or mapped_pitch > BDO_DRUM_MAX
                ):
                    result = True
                else:
                    supported = game_supported_pitches(
                        track.bdo_instrument_id, track.marnian_synth_mode
                    )
                    result = (
                        supported is not None
                        and mapped_pitch not in supported
                    )
        else:
            converted_pitch = pitch + self.conversion_transpose
            supported = game_supported_pitches(
                track.bdo_instrument_id, track.marnian_synth_mode
            )
            if supported is not None:
                result = converted_pitch not in supported
            else:
                result = converted_pitch < BDO_NOTE_MIN or converted_pitch > BDO_NOTE_MAX
        self._conversion_problem_cache[cache_key] = result
        return result

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_scaled_background()
        self._update_track_scrollbar()

    def _refresh_scaled_background(self) -> None:
        if self.background_pixmap.isNull() or self.size().isEmpty():
            self._scaled_background = QPixmap()
            self._scaled_background_size = QSize()
            return
        if self._scaled_background_size == self.size():
            return
        self._scaled_background = self.background_pixmap.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
        )
        self._scaled_background_size = self.size()

    def _lane_height(self) -> int:
        return 58

    def _visible_track_row_range(self, grid_height: float) -> tuple[int, int]:
        lane_height = self._lane_height()
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        first_row = max(0, int(scroll_y // lane_height))
        last_row = min(
            len(self.tracks),
            int(math.ceil((scroll_y + grid_height) / lane_height)) + 1,
        )
        return first_row, last_row

    def _timeline_layout_metrics(self) -> tuple[QRectF, int, int, int]:
        # The workspace itself supplies separation from the fixed bars.  Keep
        # the painted track grid full-bleed inside it—no extra canvas gutter.
        area = QRectF(self.rect())
        # Enough room for readable two-line track metadata and compact actions.
        header_w = 320
        ruler_h = 34
        lane_h = self._lane_height()
        return area, header_w, ruler_h, lane_h

    def _update_track_scrollbar(self) -> None:
        if not hasattr(self, "track_scroll"):
            return
        area, _header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        grid_top = area.top() + ruler_h
        grid_h = max(80, area.bottom() - grid_top)
        instrument_view_h = max(
            0,
            grid_h - (lane_h if self.reference_audio is not None else 0),
        )
        content_h = lane_h * len(self.tracks)
        max_scroll = max(0, content_h - instrument_view_h)
        scrollbar_width = 12
        self.track_scroll.setGeometry(
            int(area.right() - scrollbar_width),
            int(grid_top),
            scrollbar_width,
            int(instrument_view_h),
        )
        self.track_scroll.setRange(0, int(max_scroll))
        self.track_scroll.setPageStep(int(instrument_view_h))
        self.track_scroll.setSingleStep(lane_h)
        self.track_scroll.setVisible(max_scroll > 0)

    def set_playhead(self, ms: float, follow: bool = False) -> None:
        old_rect = self._playhead_update_rect(self.playhead_ms)
        old_view_start = self.view_start_ms
        old_playhead = self.playhead_ms
        self.playhead_ms = max(0.0, min(float(ms), self._timeline_end_ms()))
        if follow:
            visible_duration = self._visible_duration_ms()
            if self.playhead_ms < self.view_start_ms or self.playhead_ms > self.view_start_ms + visible_duration * 0.92:
                self.view_start_ms = self.playhead_ms - visible_duration * 0.18
                self._clamp_view()
        if self.view_start_ms != old_view_start:
            self.update()
            if not math.isclose(old_playhead, self.playhead_ms, abs_tol=0.25):
                self.playhead_changed.emit(self.playhead_ms)
            return
        new_rect = self._playhead_update_rect(self.playhead_ms)
        if old_rect is not None:
            self.update(old_rect)
        if new_rect is not None:
            self.update(new_rect)
        if not math.isclose(old_playhead, self.playhead_ms, abs_tol=0.25):
            self.playhead_changed.emit(self.playhead_ms)

    @property
    def time_range(self) -> tuple[float, float] | None:
        if self.range_start_ms is None or self.range_end_ms is None:
            return None
        return (
            min(self.range_start_ms, self.range_end_ms),
            max(self.range_start_ms, self.range_end_ms),
        )

    def set_time_range(
        self,
        start_ms: float | None,
        end_ms: float | None,
        *,
        notify: bool = False,
    ) -> None:
        if start_ms is None or end_ms is None:
            changed = self.time_range is not None
            self.range_start_ms = None
            self.range_end_ms = None
        else:
            start = max(0.0, min(float(start_ms), self._timeline_end_ms()))
            end = max(0.0, min(float(end_ms), self._timeline_end_ms()))
            changed = self.time_range != (min(start, end), max(start, end))
            self.range_start_ms = min(start, end)
            self.range_end_ms = max(start, end)
        if changed:
            self.update()
            if notify:
                self.time_range_changed.emit(self.time_range)

    def _playhead_update_rect(self, position_ms: float):
        visible_duration = self._visible_duration_ms()
        if not self.view_start_ms <= position_ms <= self.view_start_ms + visible_duration:
            return None
        area, header_w, _ruler_h, _lane_h = self._timeline_layout_metrics()
        scrollbar_w = 14 if self.track_scroll.isVisible() else 0
        grid_w = max(120.0, area.width() - header_w - scrollbar_w)
        x = area.left() + header_w + (
            (position_ms - self.view_start_ms) / visible_duration
        ) * grid_w
        return QRectF(x - 9.0, area.top(), 19.0, area.height()).toAlignedRect()

    def set_buffer_progress(self, progress: float, visible: bool = True) -> None:
        progress = max(0.0, min(1.0, float(progress)))
        if self.buffer_progress == progress and self.buffer_visible == bool(visible):
            return
        self.buffer_progress = progress
        self.buffer_visible = bool(visible)
        self.update()

    def set_zoom_percent(self, value: int) -> None:
        new_zoom = max(1.0, min(8.0, value / 100.0))
        if math.isclose(new_zoom, self.zoom_factor):
            return
        old_duration = self._visible_duration_ms()
        center = self.view_start_ms + old_duration / 2
        self.zoom_factor = new_zoom
        self.view_start_ms = center - self._visible_duration_ms() / 2
        self._clamp_view()
        self.update()
        self.changed.emit()

    def set_pan_percent(self, value: int) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        new_start = max_start * max(0, min(1000, value)) / 1000.0
        if math.isclose(new_start, self.view_start_ms, abs_tol=0.5):
            return
        self.view_start_ms = new_start
        self._clamp_view()
        self.update()
        self.changed.emit()

    def pan_percent(self) -> int:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        if max_start <= 0:
            return 0
        return round(self.view_start_ms / max_start * 1000)

    def _timeline_end_ms(self) -> float:
        return self._timeline_end_cache

    def _visible_duration_ms(self) -> float:
        return max(1.0, self._timeline_end_ms() / self.zoom_factor)

    def _clamp_view(self) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        self.view_start_ms = max(0.0, min(self.view_start_ms, max_start))

    def _paint_canvas_background(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor("#141615"))
        if self.background_pixmap.isNull():
            return
        self._refresh_scaled_background()
        target = QRectF(self.rect())
        x = (self.width() - self._scaled_background.width()) / 2
        y = (self.height() - self._scaled_background.height()) / 2
        painter.save()
        painter.setOpacity(TIMELINE_BACKGROUND_OPACITY)
        painter.drawPixmap(int(x), int(y), self._scaled_background)
        painter.restore()
        painter.fillRect(target, QColor(12, 14, 13, 72))

    def _paint_timeline_shell(
        self,
        painter: QPainter,
        area: QRectF,
        header_w: int,
        ruler_h: int,
        grid_w: float,
        grid_h: float,
    ) -> tuple[float, float, float, float]:
        left = area.left()
        top = area.top()
        grid_left = left + header_w
        grid_top = top + ruler_h
        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor(32, 32, 32, 218))
        timeline_clip = QRectF(grid_left, grid_top, grid_w, grid_h)
        painter.fillRect(QRectF(left, grid_top, header_w, grid_h), QColor(29, 29, 29, 206))
        painter.fillRect(timeline_clip, QColor(21, 21, 21, 178))
        painter.setPen(QPen(QColor("#343434"), 1))
        painter.drawLine(grid_left, top, grid_left, area.bottom())
        painter.drawLine(left, grid_top, area.right(), grid_top)
        return left, top, grid_left, grid_top

    def _paint_grid_ruler(
        self,
        painter: QPainter,
        left: float,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
    ) -> int:
        measure_ms = (
            60000.0 / max(1, self.bpm) * max(1, self.time_sig)
        )
        first_measure = self.beat_origin_ms + math.floor(
            (visible_start - self.beat_origin_ms) / measure_ms
        ) * measure_ms
        measure = first_measure
        measure_index = math.floor(
            (measure - self.beat_origin_ms) / measure_ms
        )
        visible_end = visible_start + visible_duration
        while measure <= visible_end + measure_ms:
            next_measure = measure + measure_ms
            left_x = grid_left + (
                (measure - visible_start) / visible_duration
            ) * grid_w
            right_x = grid_left + (
                (next_measure - visible_start) / visible_duration
            ) * grid_w
            shade = (
                QColor(25, 25, 25, 80)
                if measure_index % 2
                else QColor(17, 17, 17, 64)
            )
            painter.fillRect(
                QRectF(
                    left_x,
                    grid_top,
                    right_x - left_x,
                    grid_h,
                ),
                shade,
            )
            measure = next_measure
            measure_index += 1
        ticks = self._visible_musical_ticks(
            visible_start,
            visible_duration,
            grid_w,
        )
        for value, is_major, label in ticks:
            x = grid_left + (
                (value - visible_start) / visible_duration
            ) * grid_w
            painter.setPen(QPen(QColor("#3a3a3a" if is_major else "#292929"), 1))
            painter.drawLine(int(x), grid_top, int(x), grid_top + grid_h)
            if label:
                painter.setPen(QColor("#8e8982" if is_major else "#5f5a54"))
                painter.drawText(int(x + 6), top + 22, label)
        painter.setPen(QColor("#a8a29e"))
        painter.drawText(left + 10, top + 22, tr("轨道"))
        return len(ticks)

    def _paint_playhead(
        self,
        painter: QPainter,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        height: float,
    ) -> float | None:
        if visible_start <= self.playhead_ms <= visible_end:
            play_x = grid_left + ((self.playhead_ms - visible_start) / visible_duration) * grid_w
            painter.fillRect(QRectF(play_x, grid_top, 2, height), QColor("#f5a524"))
            marker = QPainterPath()
            marker.moveTo(play_x - 5, top + 1)
            marker.lineTo(play_x + 7, top + 1)
            marker.lineTo(play_x + 1, top + 9)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#f5a524"))
            return play_x
        return None

    def _paint_time_range(
        self,
        painter: QPainter,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        selected = self.time_range
        if selected is None:
            return
        start, end = selected
        if end < visible_start or start > visible_end:
            return
        left_ms = max(start, visible_start)
        right_ms = min(end, visible_end)
        left_x = grid_left + (
            (left_ms - visible_start) / visible_duration
        ) * grid_w
        right_x = grid_left + (
            (right_ms - visible_start) / visible_duration
        ) * grid_w
        painter.fillRect(
            QRectF(left_x, grid_top, max(1.0, right_x - left_x), grid_h),
            QColor(85, 196, 186, 22),
        )
        for value in (start, end):
            if visible_start <= value <= visible_end:
                x = grid_left + (
                    (value - visible_start) / visible_duration
                ) * grid_w
                painter.fillRect(
                    QRectF(x - 1.0, top, 2.0, grid_h + (grid_top - top)),
                    QColor("#55c4ba"),
                )

    def _paint_track_rows(
        self,
        painter: QPainter,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        any_solo = any(track.solo for track in self.tracks)
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        instrument_grid_h = max(
            0.0,
            grid_h - (lane_h if self.reference_audio is not None else 0),
        )
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        painter.save()
        painter.setClipRect(QRectF(left, grid_top, header_w + grid_w, instrument_grid_h))
        for row in range(first_row, last_row):
            track = self.tracks[row]
            y = grid_top + row * lane_h - scroll_y
            active = not track.muted and (not any_solo or track.solo)
            focused = track is self.selected_track
            lane_color = QColor(32, 32, 32, 174) if row % 2 else QColor(28, 28, 28, 166)
            if not active:
                lane_color = QColor(23, 23, 23, 190)
            if focused:
                lane_color = QColor(42, 36, 25, 202) if active else QColor(33, 29, 23, 202)
            painter.setBrush(lane_color)
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(grid_left, y, grid_w, lane_h))
            painter.fillRect(
                QRectF(left, y, header_w, lane_h),
                QColor(48, 40, 26, 214) if focused else (QColor(34, 34, 34, 206) if active else QColor(25, 25, 25, 214)),
            )
            painter.fillRect(QRectF(left, y, 5, lane_h), QColor(track.color if active else "#4a4743"))
            if focused:
                painter.fillRect(QRectF(left, y, 5, lane_h), QColor("#f5a524"))
                painter.setPen(QPen(QColor("#d9a441"), 1))
                painter.drawRect(QRectF(left + 0.5, y + 0.5, header_w + grid_w - 1, lane_h - 1))
            painter.setPen(QPen(QColor("#2e2e2e"), 1))
            painter.drawLine(left, y + lane_h - 1, grid_left + grid_w, y + lane_h - 1)

            self.hit_regions.append((QRectF(left, y, header_w + grid_w, lane_h), "lane", track))
            row_rect = QRectF(left, y, header_w, lane_h)
            self.hit_regions.append((row_rect, "select", track))

            adaptation = self._instrument_adaptations.get(
                int(track.bdo_instrument_id)
            )
            header_background_rect = instrument_header_background_rect(
                row_rect
            )
            if adaptation is not None and not header_background_rect.isEmpty():
                paint_instrument_header_background(
                    painter,
                    header_background_rect,
                    visual_key=adaptation.visual_key,
                    accent=QColor(track.color),
                    pixmap=self.instrument_lane_art.pixmap_for(
                        int(track.bdo_instrument_id)
                    ),
                    active=active,
                )

            controls = [
                ("M", "mute", 26),
                ("S", "solo", 26),
                ("FX", "fx", 28),
            ]
            control_gap = 4.0
            controls_width = sum(width for _label, _action, width in controls)
            controls_width += control_gap * max(0, len(controls) - 1)
            control_x = left + header_w - 20.0 - controls_width
            control_y = y + 5.0
            for label, action, width in controls:
                rect = QRectF(control_x, control_y, width, 22)
                checked = (action == "mute" and track.muted) or (action == "solo" and track.solo)
                painter.fillRect(rect, QColor("#5d451e" if checked else "#2b2b2b"))
                painter.setPen(QPen(QColor("#d9a441" if checked else "#484848"), 1))
                painter.drawRect(rect)
                painter.setPen(QColor("#f3f1ea" if active else "#8a847d"))
                painter.drawText(rect, Qt.AlignCenter, label)
                self.hit_regions.append((rect, action, track))
                control_x += width + control_gap

            # This is the game's track-volume field, not the separate note-
            # velocity scale.  The official authoring UI clamps edits to
            # 0..100 (default 70), although imported score bytes may be above
            # 100.  Such raw values remain visible and untouched until the
            # user deliberately edits this slider.
            volume_label_rect = QRectF(left + header_w - 129, y + 34, 25, 16)
            volume_rect = QRectF(left + header_w - 101, y + 34, 50, 16)
            volume_value_rect = QRectF(left + header_w - 48, y + 34, 26, 16)
            painter.setPen(QColor("#8f8981" if active else "#625e59"))
            painter.drawText(volume_label_rect, Qt.AlignCenter, tr("音量"))
            painter.fillRect(volume_rect, QColor("#252525"))
            painter.setPen(QPen(QColor("#4b4945"), 1))
            painter.drawRect(volume_rect)
            raw_track_volume = int(track.bdo_track_volume)
            fill_width = max(
                0.0,
                (volume_rect.width() - 4.0)
                * max(0, min(100, raw_track_volume))
                / 100.0,
            )
            painter.fillRect(
                QRectF(
                    volume_rect.left() + 2.0,
                    volume_rect.top() + 5.0,
                    fill_width,
                    6.0,
                ),
                QColor("#d49a34" if active else "#665437"),
            )
            handle_x = volume_rect.left() + 2.0 + fill_width
            painter.fillRect(
                QRectF(handle_x - 1.0, volume_rect.top() + 3.0, 2.0, 10.0),
                QColor("#f5c158" if active else "#81735d"),
            )
            painter.setPen(
                QColor(
                    "#ef7772"
                    if not 0 <= raw_track_volume <= 100
                    else ("#d7c6a5" if active else "#77716a")
                )
            )
            painter.drawText(
                volume_value_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                str(raw_track_volume),
            )
            self.hit_regions.append((volume_rect, "track_volume", track))

            meter_level = self.track_levels.get(int(track.track_id), 0.0) if active else 0.0
            meter_rect = QRectF(left + header_w - 14, y + 7, 7, lane_h - 14)
            segment_count = 10
            segment_gap = 1.0
            segment_height = (meter_rect.height() - segment_gap * (segment_count - 1)) / segment_count
            lit_segments = min(segment_count, math.ceil(meter_level * segment_count))
            painter.setPen(Qt.NoPen)
            for segment in range(segment_count):
                segment_y = meter_rect.bottom() - (segment + 1) * segment_height - segment * segment_gap
                if segment < lit_segments:
                    color = "#d05c4f" if segment >= 9 else ("#d8a33f" if segment >= 7 else "#4fa36a")
                else:
                    color = "#30302e"
                painter.fillRect(QRectF(meter_rect.left(), segment_y, meter_rect.width(), segment_height), QColor(color))

            accent = QColor(track.color)
            accent.setAlpha(230 if active else 75)
            # No nested horizontal gutter: the colored note region shares the
            # grid's exact left/right edge, while retaining a little vertical
            # breathing room between adjacent lanes.
            region_rect = QRectF(grid_left, y + 7, grid_w, lane_h - 14)
            region_bg = QColor(track.color)
            region_bg.setAlpha(42 if active else 16)
            painter.setBrush(region_bg)
            painter.setPen(QPen(QColor(track.color), 1))
            painter.drawRect(region_rect)

            if track.notes:
                pitch_min, pitch_max = self._track_pitch_bounds(track)
                pitch_span = max(1, pitch_max - pitch_min)
                painter.save()
                painter.setClipRect(region_rect)
                rects_by_color: dict[str, list[QRectF]] = {}
                invalid_rects: list[QRectF] = []
                ordered, note_lo, note_hi = self._visible_track_note_window(
                    track, visible_start, visible_end,
                )
                for note_index in range(note_lo, min(note_hi, note_lo + 2600)):
                    note = ordered[note_index]
                    scaled_dur = note.dur * track.duration_scale
                    note_end = note.start + scaled_dur
                    if note_end < visible_start or note.start > visible_end:
                        continue
                    x = region_rect.left() + ((note.start - visible_start) / visible_duration) * region_rect.width()
                    w = max(2.5, (scaled_dur / visible_duration) * region_rect.width())
                    pitch_pos = (note.pitch - pitch_min) / pitch_span
                    note_y = region_rect.top() + 6 + (1.0 - pitch_pos) * (region_rect.height() - 14)
                    note_rect = QRectF(x, note_y, w, 4.5)
                    if self._note_has_conversion_problem(track, note.pitch):
                        invalid_rects.append(note_rect)
                    else:
                        dynamic_color = articulation_color(int(getattr(note, "ntype", 0)))
                        rects_by_color.setdefault(dynamic_color, []).append(note_rect)
                painter.setPen(Qt.NoPen)
                for color, rects in rects_by_color.items():
                    painter.setBrush(QColor(color))
                    painter.drawRects(rects)
                if invalid_rects:
                    painter.setBrush(QColor("#d94a4a"))
                    painter.setPen(QPen(QColor("#ffb1a8"), 1))
                    painter.drawRects(invalid_rects)
                painter.restore()

            painter.setPen(QColor("#f3f1ea" if active else "#8a847d"))
            painter.drawText(
                QRectF(left + 12, y + 5, header_w - 126, 22),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(track.display_name, Qt.ElideRight, header_w - 132),
            )
            painter.setPen(QColor("#a8a29e" if active else "#69645f"))
            inst_name = _ui_bdo_instrument_name(track.bdo_instrument_id)
            cached_low, cached_high = self._track_pitch_bounds(track)
            cached_range = f"{note_name(cached_low)} - {note_name(cached_high)}" if track.notes else "-"
            metadata = trf(
                "{instrument} · {count} 音符 · {range}",
                instrument=inst_name,
                count=track.note_count,
                range=cached_range,
            )
            metadata_font = painter.font()
            metadata_font.setPointSize(max(7, metadata_font.pointSize() - 1))
            painter.save()
            painter.setFont(metadata_font)
            metadata_left = left + 12.0
            metadata_right = left + header_w - 135.0
            metadata_width = max(0.0, metadata_right - metadata_left)
            painter.drawText(
                QRectF(metadata_left, y + 31, metadata_width, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(
                    metadata,
                    Qt.ElideRight,
                    max(0, int(metadata_width - 4.0)),
                ),
            )
            painter.restore()
        painter.restore()
        if self.reference_audio is not None:
            self._paint_reference_audio_row(
                painter,
                left,
                grid_left,
                grid_top,
                header_w,
                grid_w,
                grid_h,
                lane_h,
                visible_start,
                visible_duration,
                visible_end,
            )

    @staticmethod
    def _track_volume_from_position(rect: QRectF, x: float) -> int:
        if rect.width() <= 0:
            return 0
        ratio = max(0.0, min(1.0, (float(x) - rect.left()) / rect.width()))
        return max(0, min(100, round(ratio * 100.0)))

    def _set_track_volume_from_position(
        self,
        track: TrackState,
        rect: QRectF,
        x: float,
    ) -> bool:
        value = self._track_volume_from_position(rect, x)
        if int(track.bdo_track_volume) == value:
            return False
        track.bdo_track_volume = value
        self.update(rect.adjusted(-4.0, -3.0, 32.0, 3.0).toAlignedRect())
        return True

    def _paint_reference_audio_row(
        self,
        painter: QPainter,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        controller = self.reference_audio
        if controller is None:
            return
        y = grid_top + grid_h - lane_h
        accent = QColor("#d39a42")
        lane_rect = QRectF(left, y, header_w + grid_w, lane_h)
        header_rect = QRectF(left, y, header_w, lane_h)
        waveform_rect = QRectF(grid_left, y + 7, grid_w, lane_h - 14)

        painter.fillRect(QRectF(grid_left, y, grid_w, lane_h), QColor(29, 28, 27, 186))
        painter.fillRect(header_rect, QColor(37, 35, 32, 218))
        painter.fillRect(QRectF(left, y, 5, lane_h), accent)
        painter.setPen(QPen(QColor("#2e2e2e"), 1))
        painter.drawLine(left, y + lane_h - 1, grid_left + grid_w, y + lane_h - 1)
        self.hit_regions.append((lane_rect, "audio_lane", controller))

        button_specs = (
            ((tr("卸载"), "audio_unload", 44),)
            if controller.audio_path
            else ((tr("载入"), "audio_load", 44),)
        )
        gap = 4.0
        buttons_width = sum(width for _label, _action, width in button_specs)
        buttons_width += gap * max(0, len(button_specs) - 1)
        button_x = left + header_w - 13.0 - buttons_width
        button_y = y + 5.0
        for label, action, width in button_specs:
            rect = QRectF(button_x, button_y, width, 22)
            painter.fillRect(rect, QColor("#2b2b2b"))
            painter.setPen(QPen(QColor("#55504a"), 1))
            painter.drawRect(rect)
            painter.setPen(QColor("#f3f1ea"))
            painter.drawText(rect, Qt.AlignCenter, label)
            self.hit_regions.append((rect, action, controller))
            button_x += width + gap

        volume_specs = (
            ("−", "audio_volume_down", 24),
            (f"{controller.volume_percent}%", "audio_volume", 42),
            ("+", "audio_volume_up", 24),
        )
        volume_width = sum(width for _label, _action, width in volume_specs)
        volume_width += gap * max(0, len(volume_specs) - 1)
        volume_x = left + header_w - 13.0 - volume_width
        for label, action, width in volume_specs:
            rect = QRectF(volume_x, y + 32.0, width, 18)
            painter.fillRect(rect, QColor("#292826"))
            painter.setPen(QPen(QColor("#55504a"), 1))
            painter.drawRect(rect)
            painter.setPen(QColor("#d7c6a5" if action == "audio_volume" else "#f3f1ea"))
            painter.drawText(rect, Qt.AlignCenter, label)
            self.hit_regions.append((rect, action, controller))
            volume_x += width + gap

        text_width = max(40.0, header_w - buttons_width - 38.0)
        painter.setPen(QColor("#f3f1ea"))
        painter.drawText(
            QRectF(left + 12, y + 5, text_width, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            tr("参考音频"),
        )
        metadata = tr("正在分析波形…") if controller.waveform_loading else controller.display_name
        painter.setPen(QColor("#aaa39b"))
        metadata_width = max(40.0, header_w - volume_width - 38.0)
        painter.drawText(
            QRectF(left + 12, y + 31, metadata_width, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(metadata, Qt.ElideMiddle, int(metadata_width)),
        )

        waveform_bg = QColor("#d39a42")
        waveform_bg.setAlpha(24 if controller.audio_path else 12)
        painter.fillRect(waveform_rect, waveform_bg)
        painter.setPen(QPen(QColor("#775d35"), 1))
        painter.drawRect(waveform_rect)
        self.hit_regions.append((waveform_rect, "audio_waveform", controller))

        if controller.waveform:
            audio_visible_start = controller.project_to_audio(visible_start)
            audio_visible_end = controller.project_to_audio(visible_end)
            first = max(
                0,
                bisect_left(controller.waveform_starts, audio_visible_start) - 1,
            )
            last = bisect_right(controller.waveform_starts, audio_visible_end)
            center_y = waveform_rect.center().y()
            max_half_height = max(1.0, waveform_rect.height() / 2.0 - 3.0)
            bars: list[QRectF] = []
            for bucket_start, bucket_end, peak in controller.waveform[first:last]:
                project_start = controller.audio_to_project(bucket_start)
                project_end = controller.audio_to_project(bucket_end)
                x = waveform_rect.left() + (
                    (project_start - visible_start) / visible_duration
                ) * waveform_rect.width()
                width = max(
                    1.0,
                    ((project_end - project_start) / visible_duration)
                    * waveform_rect.width(),
                )
                half_height = max(1.0, min(1.0, peak) * max_half_height)
                bars.append(QRectF(x, center_y - half_height, width, half_height * 2.0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#d7a34c"))
            if bars:
                painter.drawRects(bars)
        else:
            painter.setPen(QColor("#817665"))
            placeholder = tr("正在分析波形…") if controller.waveform_loading else tr("载入 MP3/WAV 后显示波形")
            painter.drawText(waveform_rect, Qt.AlignCenter, placeholder)

        position = controller.project_position_ms
        if controller.audio_path and visible_start <= position <= visible_end:
            position_x = waveform_rect.left() + (
                (position - visible_start) / visible_duration
            ) * waveform_rect.width()
            painter.fillRect(
                QRectF(position_x, waveform_rect.top(), 1.5, waveform_rect.height()),
                QColor("#f4e3bd"),
            )

    def _paint_ruler_overlay(
        self,
        painter: QPainter,
        area: QRectF,
        left: float,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        ruler_h: int,
        bars: int,
        visible_start: float,
        visible_duration: float,
        play_x: float | None,
    ) -> None:
        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor(32, 32, 32, 224))
        painter.setPen(QColor("#a8a29e"))
        painter.drawText(
            left + 10,
            top + 22,
            trf("轨道 · {count}", count=self._timeline_row_count()),
        )
        for value, is_major, label in self._visible_musical_ticks(
            visible_start,
            visible_duration,
            grid_w,
        ):
            x = grid_left + (
                (value - visible_start) / visible_duration
            ) * grid_w
            painter.setPen(QPen(QColor("#3a3a3a" if is_major else "#292929"), 1))
            painter.drawLine(int(x), top + 8, int(x), grid_top)
            if label:
                painter.setPen(QColor("#8e8982" if is_major else "#5f5a54"))
                painter.drawText(int(x + 6), top + 22, label)
        if play_x is not None:
            painter.fillRect(QRectF(play_x, top, 2, ruler_h), QColor("#f5a524"))
            marker = QPainterPath()
            marker.moveTo(play_x - 5, top + 1)
            marker.lineTo(play_x + 7, top + 1)
            marker.lineTo(play_x + 1, top + 9)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#f5a524"))
        painter.setPen(QPen(QColor("#343434"), 1))
        painter.drawLine(grid_left, top, grid_left, grid_top + grid_h)
        painter.drawLine(left, grid_top, grid_left + grid_w, grid_top)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        self._paint_canvas_background(painter)
        self.hit_regions = []

        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        if self._timeline_row_count() <= 0:
            painter.setPen(QColor("#8d8780"))
            painter.drawText(
                area,
                Qt.AlignCenter,
                tr("导入 MIDI 后显示轨道与音符时间轴"),
            )
            return

        visible_start = self.view_start_ms
        visible_duration = self._visible_duration_ms()
        visible_end = visible_start + visible_duration
        scrollbar_w = 14 if self.track_scroll.isVisible() else 0
        grid_w = max(120, area.width() - header_w - scrollbar_w)
        grid_h = max(80, area.bottom() - (area.top() + ruler_h))
        left, top, grid_left, grid_top = self._paint_timeline_shell(
            painter, area, header_w, ruler_h, grid_w, grid_h
        )
        self.grid_rect = QRectF(grid_left, top, grid_w, grid_h + ruler_h)
        bars = self._paint_grid_ruler(
            painter, left, top, grid_left, grid_top, grid_w, grid_h, visible_start, visible_duration
        )
        play_x = self._paint_playhead(
            painter, top, grid_left, grid_top, grid_w, grid_h,
            visible_start, visible_duration, visible_end, grid_h
        )
        self._paint_track_rows(
            painter, left, grid_left, grid_top, header_w, grid_w, grid_h,
            lane_h, visible_start, visible_duration, visible_end
        )
        self._paint_time_range(
            painter,
            top,
            grid_left,
            grid_top,
            grid_w,
            grid_h,
            visible_start,
            visible_duration,
            visible_end,
        )
        self._paint_ruler_overlay(
            painter, area, left, top, grid_left, grid_top, grid_w, grid_h,
            ruler_h, bars, visible_start, visible_duration, play_x
        )
        if self.buffer_visible:
            buffer_y = grid_top - 3
            painter.fillRect(QRectF(grid_left, buffer_y, grid_w, 3), QColor("#30383a"))
            if self.buffer_progress > 0:
                painter.fillRect(
                    QRectF(grid_left, buffer_y, grid_w * self.buffer_progress, 3),
                    QColor("#55b8ad"),
                )

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() == Qt.RightButton:
            for rect, _action, track in reversed(self.hit_regions):
                if rect.contains(pos) and isinstance(track, TrackState):
                    self.selected_track = track
                    self.selected.emit(track)
                    self._show_instrument_menu(track, event.globalPosition().toPoint())
                    self.update()
                    return
            super().mousePressEvent(event)
            return
        for rect, action, track in reversed(self.hit_regions):
            if rect.contains(pos):
                if isinstance(track, ReferenceAudioController):
                    if action == "audio_load":
                        track.choose_audio(self)
                    elif action == "audio_unload":
                        track.set_audio_path(None)
                    elif action == "audio_volume_down":
                        track.set_volume_percent(track.volume_percent - 5)
                    elif action == "audio_volume_up":
                        track.set_volume_percent(track.volume_percent + 5)
                    elif action == "audio_volume":
                        return
                    elif action in ("audio_waveform", "audio_lane"):
                        if action == "audio_lane":
                            return
                        rel = max(
                            0.0,
                            min(1.0, (pos.x() - rect.left()) / max(1.0, rect.width())),
                        )
                        target = self.view_start_ms + rel * self._visible_duration_ms()
                        track.set_position(target)
                        self.set_playhead(target)
                        self.seek_requested.emit(self.playhead_ms)
                    self.update()
                    return
                if not isinstance(track, TrackState):
                    continue
                if action == "lane":
                    continue
                self.selected_track = track
                self.selected.emit(track)
                if action == "track_volume":
                    self._volume_drag_track = track
                    self._volume_drag_rect = QRectF(rect)
                    self._volume_drag_initial = int(track.bdo_track_volume)
                    self._set_track_volume_from_position(track, rect, pos.x())
                elif action == "mute":
                    track.muted = not track.muted
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "solo":
                    track.solo = not track.solo
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "fx":
                    self.effects_requested.emit(track)
                self.update()
                return
        area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
        ruler_rect = QRectF(
            area.left() + header_w,
            area.top(),
            max(0.0, area.width() - header_w),
            ruler_h,
        )
        if event.button() == Qt.LeftButton and ruler_rect.contains(pos):
            rel = max(
                0.0,
                min(
                    1.0,
                    (pos.x() - ruler_rect.left())
                    / max(1.0, ruler_rect.width()),
                ),
            )
            target = self.view_start_ms + rel * self._visible_duration_ms()
            selected = self.time_range
            handle_tolerance = self._visible_duration_ms() * 7.0 / max(
                1.0,
                ruler_rect.width(),
            )
            if selected and abs(target - selected[0]) <= handle_tolerance:
                self._range_drag_mode = "start"
                self._range_drag_anchor_ms = selected[1]
            elif selected and abs(target - selected[1]) <= handle_tolerance:
                self._range_drag_mode = "end"
                self._range_drag_anchor_ms = selected[0]
            else:
                self._range_drag_mode = "new"
                self._range_drag_anchor_ms = target
                self.set_time_range(target, target)
            self._range_drag_moved = False
            self.set_playhead(target)
            return
        if self.grid_rect.contains(pos):
            rel = max(0.0, min(1.0, (pos.x() - self.grid_rect.left()) / max(1.0, self.grid_rect.width())))
            target = self.view_start_ms + rel * self._visible_duration_ms()
            self.set_playhead(target)
            self.seek_requested.emit(self.playhead_ms)
            return
        if event.button() == Qt.LeftButton:
            self.dragging_timeline = True
            self.last_drag_x = pos.x()
            return
        super().mousePressEvent(event)

    def _show_instrument_menu(self, track: TrackState, global_pos) -> None:
        menu = QMenu(self)
        edit_notes_action = menu.addAction(tr("编辑音符…"))
        menu.addSeparator()
        optimize_action = menu.addAction(tr("优化此轨道"))
        menu.addSeparator()
        current_id = track.bdo_instrument_id
        title = menu.addAction(tr("更换乐器"))
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, current_id, _ui_bdo_instrument_names())
        selected = menu.exec(global_pos)
        if selected is None:
            return
        if selected is edit_notes_action:
            self.note_editor_requested.emit(track)
            return
        if selected is optimize_action:
            self.midi_tools_requested.emit(track)
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == track.bdo_instrument_id:
            return
        track.bdo_instrument_id = int(inst_id)
        self.changed.emit()
        self.instrument_changed.emit(track)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            for rect, action, track in reversed(self.hit_regions):
                if isinstance(track, ReferenceAudioController) and rect.contains(event.position()):
                    if action in ("audio_lane", "audio_waveform"):
                        if not track.audio_path:
                            track.choose_audio(self)
                        return
                if (
                    isinstance(track, TrackState)
                    and action in ("lane", "select")
                    and rect.contains(event.position())
                ):
                    self.selected_track = track
                    self.selected.emit(track)
                    self.note_editor_requested.emit(track)
                    self.update()
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._volume_drag_track is not None:
            self._set_track_volume_from_position(
                self._volume_drag_track,
                self._volume_drag_rect,
                pos.x(),
            )
            return
        if self._range_drag_anchor_ms is not None:
            area, header_w, _ruler_h, _lane_h = self._timeline_layout_metrics()
            grid_width = max(1.0, area.width() - header_w)
            rel = max(
                0.0,
                min(1.0, (pos.x() - (area.left() + header_w)) / grid_width),
            )
            target = self.view_start_ms + rel * self._visible_duration_ms()
            self._range_drag_moved = (
                self._range_drag_moved
                or abs(target - self._range_drag_anchor_ms)
                > self._visible_duration_ms() * 3.0 / grid_width
            )
            self.set_time_range(self._range_drag_anchor_ms, target)
            return
        if self.dragging_timeline:
            dx = pos.x() - self.last_drag_x
            self.last_drag_x = pos.x()
            if self.width() > 0:
                self.view_start_ms -= dx / max(1, self.width()) * self._visible_duration_ms()
                self._clamp_view()
                self.update()
                self.changed.emit()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._volume_drag_track is not None:
            changed = (
                int(self._volume_drag_track.bdo_track_volume)
                != self._volume_drag_initial
            )
            self._volume_drag_track = None
            self._volume_drag_rect = QRectF()
            if changed:
                self.changed.emit()
                self.track_state_changed.emit()
            return
        if self._range_drag_anchor_ms is not None:
            if not self._range_drag_moved:
                target = self._range_drag_anchor_ms
                self.set_time_range(None, None)
                self.set_playhead(target)
                self.seek_requested.emit(self.playhead_ms)
            else:
                self.time_range_changed.emit(self.time_range)
            self._range_drag_anchor_ms = None
            self._range_drag_mode = ""
            self._range_drag_moved = False
            return
        self.dragging_timeline = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        angle = event.angleDelta()
        delta = angle.x() or angle.y()
        if not delta:
            super().wheelEvent(event)
            return
        if event.modifiers() & Qt.ControlModifier:
            step = 1.12 if delta > 0 else 1 / 1.12
            center = self.view_start_ms + self._visible_duration_ms() / 2
            self.zoom_factor = max(1.0, min(8.0, self.zoom_factor * step))
            self.view_start_ms = center - self._visible_duration_ms() / 2
        elif angle.x() or (event.modifiers() & Qt.ShiftModifier):
            self.view_start_ms += (delta / 120.0) * self._visible_duration_ms() * 0.12
        else:
            if self.track_scroll.isVisible():
                self.track_scroll.setValue(self.track_scroll.value() - int(delta / 120.0 * self._lane_height()))
            else:
                self.view_start_ms += (delta / 120.0) * self._visible_duration_ms() * 0.12
        self._clamp_view()
        self.update()
        self.changed.emit()


class TrackCard(QWidget):
    changed = Signal()
    instrument_changed = Signal(object)
    selected = Signal(object)
    effects_requested = Signal(object)
    midi_tools_requested = Signal(object)

    def __init__(self, track: TrackState, instrument_names: dict[int, str]) -> None:
        super().__init__()
        self.track = track
        self.instrument_names = instrument_names
        self.name_to_id = {name: inst_id for inst_id, name in instrument_names.items()}
        self.setObjectName("TrackCard")
        self.setFixedHeight(78)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)

        color = QLabel()
        color.setFixedSize(6, 54)
        color.setStyleSheet(f"background:{track.color};")
        outer.addWidget(color)

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(5)
        outer.addLayout(stack, stretch=1)

        top = QHBoxLayout()
        top.setSpacing(6)
        stack.addLayout(top)

        title = QLabel(
            trf(
                "{track}\n{count} 音符 · {range}",
                track=track.display_name,
                count=track.note_count,
                range=track.pitch_range,
            )
        )
        title.setObjectName("TrackTitle")
        top.addWidget(title, stretch=1)

        self.mute_btn = PillButton("M")
        self.mute_btn.setToolTip(tr("静音"))
        self.mute_btn.setAccessibleName(tr("静音"))
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedWidth(30)
        self.mute_btn.clicked.connect(self._update_mute)
        top.addWidget(self.mute_btn, alignment=Qt.AlignVCenter)

        self.solo_btn = PillButton("S")
        self.solo_btn.setToolTip(tr("独奏"))
        self.solo_btn.setAccessibleName(tr("独奏"))
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedWidth(30)
        self.solo_btn.clicked.connect(self._update_solo)
        top.addWidget(self.solo_btn, alignment=Qt.AlignVCenter)

        if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
            fx = PillButton("FX")
            fx.setToolTip(tr("轨道 FX"))
            fx.setAccessibleName(tr("轨道 FX"))
            fx.setFixedWidth(34)
            fx.clicked.connect(lambda: self.effects_requested.emit(self.track))
            top.addWidget(fx, alignment=Qt.AlignVCenter)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        stack.addLayout(bottom)

        self.instrument_label = QLabel(self._instrument_label_text())
        self.instrument_label.setObjectName("Muted")
        bottom.addWidget(self.instrument_label, stretch=1)

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(10, 200)
        self.volume.setValue(100)
        self.volume.setFixedWidth(72)
        self.volume.setToolTip(tr("轨道音量"))
        self.volume.setAccessibleName(tr("轨道音量"))
        self.volume.valueChanged.connect(self._update_volume)
        bottom.addWidget(self.volume)

        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("Muted")
        self.volume_label.setFixedWidth(36)
        bottom.addWidget(self.volume_label)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.track)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.selected.emit(self.track)
        menu = QMenu(self)
        optimize_action = menu.addAction(tr("优化此轨道"))
        menu.addSeparator()
        current_id = self.track.bdo_instrument_id
        title = menu.addAction(tr("更换乐器"))
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, current_id, _ui_bdo_instrument_names())
        selected = menu.exec(event.globalPos())
        if selected is None:
            return
        if selected is optimize_action:
            self.midi_tools_requested.emit(self.track)
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == self.track.bdo_instrument_id:
            return
        self.track.bdo_instrument_id = int(inst_id)
        self.instrument_label.setText(self._instrument_label_text())
        self.instrument_changed.emit(self.track)
        self.changed.emit()

    def _instrument_label_text(self) -> str:
        return trf(
            "{instrument} · {range}",
            instrument=trv(_ui_bdo_instrument_source(
                self.track.bdo_instrument_id,
            )),
            range=game_pitch_range_value(
                self.track.bdo_instrument_id,
                self.track.marnian_synth_mode,
            ),
        )

    def _update_mute(self) -> None:
        self.track.muted = self.mute_btn.isChecked()
        self.changed.emit()

    def _update_solo(self) -> None:
        self.track.solo = self.solo_btn.isChecked()
        self.changed.emit()

    def _update_volume(self, value: int) -> None:
        self.track.volume_scale = value / 100.0
        self.volume_label.setText(f"{value}%")
        self.changed.emit()


class ConvertWorker(QThread):
    conversion_finished = Signal(str, int, object, str)
    failed = Signal(str)

    def __init__(self, params: dict):
        super().__init__()
        self.params = params

    def run(self) -> None:
        temp_path: Path | None = None
        try:
            params = self.params
            source_path = params["midi_path"]
            if params.get("direct_tracks") is not None:
                direct_tracks = params["direct_tracks"]
                channel_groups = [
                    (
                        [
                            note._replace(dur=max(1.0, note.dur * track.duration_scale))
                            for note in track.notes
                        ],
                        track.gm_program,
                        track.is_percussion,
                    )
                    for track in direct_tracks
                ]
                direct_instrument_map = {
                    idx: serialized_bdo_instrument_id(track)
                    for idx, track in enumerate(direct_tracks)
                }
                source_document = params.get("bdo_source_document")
                exact_source = bool(
                    source_document is not None
                    and params.get("bpm_override") is None
                    and not params.get("transpose")
                    and not params.get("vel_range")
                    and not params.get("vel_floor")
                    and not params.get("vel_step")
                    and not params.get("vel_layered")
                    and not params.get("articulation_map")
                    and document_matches_logical_tracks(
                        source_document,
                        direct_tracks,
                        instrument_ids=[direct_instrument_map[index] for index in range(len(direct_tracks))],
                        track_settings=[params["track_settings_map"][index] for index in range(len(direct_tracks))],
                        owner_id=params["owner_id"],
                        character_name=params["char_name"],
                        bpm=params["bpm_for_temp"],
                        time_signature=params["time_sig_for_temp"],
                    )
                )
                if exact_source:
                    bdo_data = encode_score(source_document, mode="lossless")
                    summary = score_summary(source_document)
                else:
                    bdo_data, summary = channel_groups_to_bdo(
                        params["bpm_for_temp"],
                        params["time_sig_for_temp"],
                        channel_groups,
                        bpm_override=params["bpm_override"],
                        char_name=params["char_name"],
                        vel_range=params["vel_range"],
                        vel_floor=params["vel_floor"],
                        vel_step=params["vel_step"],
                        vel_layered=params["vel_layered"],
                        transpose=params["transpose"],
                        owner_id=params["owner_id"],
                        instrument_map=direct_instrument_map,
                        reverb=params["reverb"],
                        delay=params["delay"],
                        chorus=params["chorus"],
                        vel_scales=params["vel_scales"],
                        articulation_map=params["articulation_map"],
                        preserve_note_types=True,
                        track_volumes=params.get("track_volumes"),
                        track_settings_map=params.get("track_settings_map"),
                        velocity_b_maps=params.get("velocity_b_maps"),
                    )
            else:
                if params["filtered_tracks"] is not None:
                    fd, raw_temp_path = tempfile.mkstemp(suffix=".mid")
                    os.close(fd)
                    temp_path = Path(raw_temp_path)
                    build_filtered_midi(
                        params["filtered_tracks"],
                        params["bpm_for_temp"],
                        params["time_sig_for_temp"],
                        temp_path,
                        params.get("lyric_events"),
                    )
                    source_path = str(temp_path)

                bdo_data, summary = midi_to_bdo(
                    source_path,
                    bpm_override=params["bpm_override"],
                    char_name=params["char_name"],
                    vel_range=params["vel_range"],
                    vel_floor=params["vel_floor"],
                    vel_step=params["vel_step"],
                    vel_layered=params["vel_layered"],
                    transpose=params["transpose"],
                    apply_sustain=params["apply_sustain"],
                    flatten_tempo=params["flatten_tempo"],
                    owner_id=params["owner_id"],
                    instrument_map=params["instrument_map"],
                    reverb=params["reverb"],
                    delay=params["delay"],
                    chorus=params["chorus"],
                    vel_scales=params["vel_scales"],
                    articulation_map=params["articulation_map"],
                )

            out_path = Path(params["out_path"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(bdo_data)

            installed_path = str(
                copy_export_to_game(out_path, Path(params["game_dir"]))
            )

            self.conversion_finished.emit(str(out_path), len(bdo_data), summary, installed_path)
        except BaseException as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
        finally:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass


class PianoRollCanvas(QWidget):
    """Compact, dependency-free piano roll used by the per-track note editor."""

    selection_changed = Signal()
    notes_changed = Signal()
    hover_changed = Signal(float, int)
    ruler_seek_requested = Signal(float)
    candidate_selection_changed = Signal(object)
    time_range_changed = Signal(object)
    chord_segment_clicked = Signal(str)
    voice_group_split_requested = Signal(str, float)
    voice_group_merge_requested = Signal(str, str)
    voice_group_color_requested = Signal(str, str)
    voice_group_role_requested = Signal(str, str)

    KEY_W = 86
    BLACK_KEY_X = 8
    BLACK_KEY_W = 48
    TIME_RULER_H = 31
    CHORD_H = 26
    RULER_H = TIME_RULER_H + CHORD_H
    ROW_H = 20
    MIN_PITCH = 0
    MAX_PITCH = 127
    # Start-sorted interval blocks keep viewport queries bounded even when one
    # sustained candidate spans most of the song.  A single global maximum
    # duration would otherwise pull every later candidate into the scan.
    CANDIDATE_QUERY_BLOCK_SIZE = 128

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.notes: list = []
        self.ghost_notes: list = []
        self._ghost_opacity = 0.70
        self.transcription_candidates: list[TranscriptionCandidate] = []
        self.transcription_candidates_visible = False
        self._transcription_candidate_ids: list[str] = []
        self._transcription_candidate_id_to_index: dict[str, int] = {}
        self._folded_candidate_primary: dict[str, str] = {}
        self._fold_alternative_counts: dict[str, int] = {}
        self._fold_alternative_rank: dict[str, int] = {}
        self._selected_candidate_ids: set[str] = set()
        self._rejected_candidate_ids: set[str] = set()
        self._pending_candidate_ids: set[str] = set()
        self._applied_candidate_ids: set[str] = set()
        self._invalid_candidate_ids: set[str] = set()
        self._duplicate_candidate_ids: set[str] = set()
        self._staged_candidate_ids: set[str] = set()
        self._fragment_candidate_ids: set[str] = set()
        self._suppressed_candidate_ids: set[str] = set()
        self._confidence_floor = 0.30
        self._show_rejected_only = False
        self._audio_offset_ms = 0.0
        self._evidence_descriptor = None
        self._show_contour_evidence = False
        # Clean review is the default.  Dense posterior layers remain
        # available as explicit diagnostic evidence instead of competing with
        # editable semantic note blocks.
        self._show_frame_evidence = False
        self._show_onset_evidence = False
        self._evidence = EvidenceTileController(self)
        self._evidence.tile_ready.connect(self._evidence_tile_ready)
        self._show_spectrogram = False
        self._reference_background_opacity = 0.60
        self._spectrogram_audio_path = ""
        self._spectrogram = SpectrogramTileController(self)
        self._spectrogram.tile_ready.connect(self._evidence_tile_ready)
        self._show_melody_lines = True
        self._melody_line_roles_visible = frozenset(
            MELODY_LINE_GUIDE_ROLES
        )
        self._melody_line_segments: tuple[MelodyLineSegment, ...] = ()
        self._melody_line_starts: list[float] = []
        self._melody_line_ends: list[float] = []
        self._melody_line_block_max_ends: list[float] = []
        self._melody_line_projection_key: tuple[object, ...] | None = None
        self._last_melody_line_query_inspections = 0
        self._candidate_group_colors: dict[str, str] = {}
        self._candidate_group_ids: dict[str, str] = {}
        self._candidate_chord_roles: dict[str, str] = {}
        self._voice_groups: tuple[object, ...] = ()
        self._assist_candidate_source_object: object | None = None
        self._assist_group_color_key: tuple[tuple[str, str], ...] = ()
        self._voice_group_outlines: tuple[
            tuple[str, float, float, int, int, str, str, float, int],
            ...,
        ] = ()
        self._voice_group_outline_starts: list[float] = []
        self._max_voice_group_duration = 0.0
        self._harmony_analysis: object | None = None
        self._harmony_segment_starts: list[float] = []
        self._max_harmony_segment_duration = 0.0
        self._hovered_candidate_id = ""
        self._candidate_marquee_origin: QPointF | None = None
        self._candidate_marquee_additive = False
        self._candidate_press_selected: set[str] = set()
        self._ruler_range_anchor: float | None = None
        self._ruler_range_endpoint = ""
        self._ruler_range_moved = False
        self._drag_time_range: tuple[float, float] | None = None
        self.selected: set[int] = set()
        self.anchor_index: int | None = None
        self.px_per_beat = 92.0
        self.scroll_ms = 0.0
        self.pitch_top = 84
        self.drag_mode = ""
        self.press_pos = QPointF()
        self.press_notes: list = []
        self.press_selected: set[int] = set()
        self.marquee = QRectF()
        self.creation_preview = None
        self.creation_anchor_ms = 0.0
        self.creation_anchor_pitch = 60
        self.edit_cursor_ms = 0.0
        self.ctrl_press_index: int | None = None
        self.clone_base_notes: list = []
        self.piano_key_dragging = False
        self.piano_pressed_pitch: int | None = None
        self.piano_hover_pitch: int | None = None
        self.playhead_ms = 0.0
        self.preload_progress = 0.0
        self.preload_state = "idle"
        self.dragging_playhead = False
        self._note_order: list[int] = []
        self._note_starts: list[float] = []
        self._note_ends: list[float] = []
        self._note_block_max_ends: list[float] = []
        self._max_note_duration = 0.0
        self._note_end_ms = 0.0
        self.content_end_ms = 0.0
        self._note_index_revision = 0
        self._visible_note_cache_key: tuple | None = None
        self._visible_note_cache: list[int] = []
        self._ghost_starts: list[float] = []
        self._ghost_ends: list[float] = []
        self._ghost_block_max_ends: list[float] = []
        self._ghost_max_duration = 0.0
        self._candidate_starts: list[float] = []
        self._candidate_ends: list[float] = []
        self._candidate_block_max_ends: list[float] = []
        self._last_candidate_query_inspections = 0
        self._candidate_end_audio_ms = 0.0
        self._candidate_id_set: frozenset[str] = frozenset()
        self._candidate_source_object: tuple[object, ...] | None = None
        self._review_projection_key: tuple | None = None
        self._background_cache_key: tuple | None = None
        self._background_cache = QPixmap()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(480, 300)

    @property
    def beat_ms(self) -> float:
        return 60000.0 / max(1, self.editor.bpm)

    @property
    def px_per_ms(self) -> float:
        return self.px_per_beat / self.beat_ms

    @property
    def transcription_time_range(self) -> tuple[float, float] | None:
        if not self.editor.transcription_mode_enabled:
            return None
        if self._ruler_range_anchor is not None and self._drag_time_range is not None:
            return self._drag_time_range
        session = getattr(self.editor.parent(), "transcription_session", None)
        state = getattr(session, "state", None)
        return getattr(state, "region", None)

    def set_notes(self, notes: list, preserve_selection: bool = False) -> None:
        self.notes = list(notes)
        self.rebuild_note_index()
        if not preserve_selection:
            self.selected.clear()
        else:
            self.selected = {i for i in self.selected if i < len(self.notes)}
        self.update()

    def set_ghost_notes(self, notes: list) -> None:
        projected = [
            note
            if isinstance(note, GhostNoteProjection)
            else GhostNoteProjection(note)
            for note in notes
        ]
        self.ghost_notes = sorted(
            projected,
            key=lambda note: (
                float(note.start),
                int(note.pitch),
                int(note.track_id),
            ),
        )
        self._ghost_starts = [float(note.start) for note in self.ghost_notes]
        self._ghost_ends = [
            float(note.start) + float(note.dur)
            for note in self.ghost_notes
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._ghost_block_max_ends = [
            max(self._ghost_ends[start : start + block_size])
            for start in range(0, len(self._ghost_ends), block_size)
        ]
        self._ghost_max_duration = max((float(note.dur) for note in self.ghost_notes), default=0.0)
        self.update()

    def set_ghost_opacity(self, opacity: float) -> None:
        try:
            normalized = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError, OverflowError):
            normalized = 0.70
        if not math.isfinite(normalized):
            normalized = 0.70
        if math.isclose(normalized, self._ghost_opacity, abs_tol=0.001):
            return
        self._ghost_opacity = normalized
        self.update()

    @staticmethod
    def _group_palette_color(group_id: str) -> str:
        if not group_id:
            return "#5baaa4"
        checksum = sum(
            (index + 1) * ord(character)
            for index, character in enumerate(str(group_id))
        )
        return TRACK_COLORS[checksum % len(TRACK_COLORS)]

    @staticmethod
    def _chord_intervals(quality: str) -> tuple[int, ...]:
        return {
            "major": (0, 4, 7),
            "minor": (0, 3, 7),
            "dim": (0, 3, 6),
            "diminished": (0, 3, 6),
            "sus2": (0, 2, 7),
            "sus4": (0, 5, 7),
            "maj7": (0, 4, 7, 11),
            "major7": (0, 4, 7, 11),
            "7": (0, 4, 7, 10),
            "dominant7": (0, 4, 7, 10),
            "min7": (0, 3, 7, 10),
            "minor7": (0, 3, 7, 10),
            "half_diminished7": (0, 3, 6, 10),
            "half-diminished7": (0, 3, 6, 10),
        }.get(str(quality), ())

    def set_transcription_assist_projection(
        self,
        *,
        voice_groups=(),
        harmony_analysis=None,
        group_colors: dict[str, str] | None = None,
    ) -> None:
        """Project Qt-free harmony/group sidecars into visible block styling."""

        groups = tuple(voice_groups or ())
        explicit_colors = dict(group_colors or {})
        color_key = tuple(
            sorted(
                (str(group_id), str(color))
                for group_id, color in explicit_colors.items()
            )
        )
        if (
            groups is self._voice_groups
            and harmony_analysis is self._harmony_analysis
            and self._candidate_source_object
            is self._assist_candidate_source_object
            and color_key == self._assist_group_color_key
        ):
            return
        candidate_groups: dict[str, str] = {}
        candidate_colors: dict[str, str] = {}
        for group in groups:
            group_id = str(getattr(group, "group_id", "") or "")
            color = str(
                explicit_colors.get(group_id)
                or getattr(group, "color", "")
                or self._group_palette_color(group_id)
            )
            for candidate_id in getattr(group, "candidate_ids", ()) or ():
                normalized = str(candidate_id)
                candidate_groups[normalized] = group_id
                candidate_colors[normalized] = color
        # Voice analysis intentionally receives only the primary of a folded
        # same-pitch hypothesis cluster.  Its alternatives remain reviewable
        # and inherit the primary block's phrase colour without becoming
        # artificial voices or additional timbre evidence.
        for alternative_id, primary_id in self._folded_candidate_primary.items():
            if primary_id in candidate_groups:
                candidate_groups.setdefault(
                    alternative_id,
                    candidate_groups[primary_id],
                )
                candidate_colors.setdefault(
                    alternative_id,
                    candidate_colors[primary_id],
                )

        chord_roles: dict[str, str] = {}
        segments = tuple(
            sorted(
                (
                    getattr(harmony_analysis, "chord_segments", ())
                    or getattr(harmony_analysis, "segments", ())
                    or ()
                ),
                key=lambda item: (
                    float(getattr(item, "start_audio_ms", 0.0)),
                    float(getattr(item, "end_audio_ms", 0.0)),
                    str(getattr(item, "segment_id", "")),
                ),
            )
        )
        if segments:
            segment_starts = [
                float(getattr(item, "start_audio_ms", 0.0))
                for item in segments
            ]
            for candidate_id, candidate in zip(
                self._transcription_candidate_ids,
                self.transcription_candidates,
            ):
                midpoint = (
                    float(candidate.start_ms)
                    + float(candidate.duration_ms) * 0.5
                )
                segment_index = bisect_right(segment_starts, midpoint) - 1
                segment = (
                    segments[segment_index]
                    if segment_index >= 0
                    and midpoint
                    < float(
                        getattr(
                            segments[segment_index],
                            "end_audio_ms",
                            0.0,
                        )
                    )
                    else None
                )
                root = getattr(segment, "root_pc", None)
                if segment is None or root is None:
                    continue
                intervals = self._chord_intervals(
                    str(getattr(segment, "quality", ""))
                )
                relative = (int(candidate.pitch) - int(root)) % 12
                role_names = ("root", "third", "fifth", "seventh")
                for index, interval in enumerate(intervals):
                    if relative == interval:
                        chord_roles[candidate_id] = role_names[
                            min(index, len(role_names) - 1)
                        ]
                        break

        projection = (
            groups,
            harmony_analysis,
            candidate_groups,
            candidate_colors,
            chord_roles,
        )
        current = (
            self._voice_groups,
            self._harmony_analysis,
            self._candidate_group_ids,
            self._candidate_group_colors,
            self._candidate_chord_roles,
        )
        if projection == current:
            return
        (
            self._voice_groups,
            self._harmony_analysis,
            self._candidate_group_ids,
            self._candidate_group_colors,
            self._candidate_chord_roles,
        ) = projection
        candidates_by_id = {
            candidate_id: candidate
            for candidate_id, candidate in zip(
                self._transcription_candidate_ids,
                self.transcription_candidates,
            )
        }
        outlines = []
        for group in groups:
            group_id = str(getattr(group, "group_id", "") or "")
            member_ids = tuple(
                str(candidate_id)
                for candidate_id in (
                    getattr(group, "candidate_ids", ()) or ()
                )
            )
            members = [
                candidates_by_id[candidate_id]
                for candidate_id in member_ids
                if candidate_id in candidates_by_id
            ]
            if not members:
                continue
            outlines.append(
                (
                    group_id,
                    float(getattr(group, "start_audio_ms", 0.0)),
                    float(getattr(group, "end_audio_ms", 0.0)),
                    min(int(candidate.pitch) for candidate in members),
                    max(int(candidate.pitch) for candidate in members),
                    str(getattr(group, "role", "") or ""),
                    candidate_colors.get(
                        member_ids[0],
                        self._group_palette_color(group_id),
                    ),
                    float(getattr(group, "confidence", 0.0)),
                    len(members),
                )
            )
        self._voice_group_outlines = tuple(
            sorted(outlines, key=lambda item: (item[1], item[2], item[0]))
        )
        self._voice_group_outline_starts = [
            item[1] for item in self._voice_group_outlines
        ]
        self._max_voice_group_duration = max(
            (item[2] - item[1] for item in self._voice_group_outlines),
            default=0.0,
        )
        self._harmony_segment_starts = [
            float(getattr(segment, "start_audio_ms", 0.0))
            for segment in segments
        ]
        self._max_harmony_segment_duration = max(
            (
                float(getattr(segment, "end_audio_ms", 0.0))
                - float(getattr(segment, "start_audio_ms", 0.0))
                for segment in segments
            ),
            default=0.0,
        )
        self._assist_candidate_source_object = self._candidate_source_object
        self._assist_group_color_key = color_key
        self._rebuild_melody_line_projection()
        self.update()

    def _rebuild_melody_line_projection(self) -> None:
        """Rebuild advisory paths outside ``paintEvent`` and audio callbacks."""

        candidate_values = tuple(self.transcription_candidates)
        candidate_ids = tuple(self._transcription_candidate_ids)
        try:
            group_revision: object = hash(self._voice_groups)
        except TypeError:
            group_revision = tuple(
                (
                    str(getattr(group, "group_id", "")),
                    tuple(getattr(group, "candidate_ids", ()) or ()),
                    str(getattr(group, "role", "")),
                    float(getattr(group, "confidence", 0.0)),
                )
                for group in self._voice_groups
            )
        projection_key = (
            len(candidate_values),
            hash(candidate_values),
            hash(candidate_ids),
            group_revision,
            id(self._harmony_analysis),
            round(self.beat_ms, 6),
        )
        if projection_key == self._melody_line_projection_key:
            return
        segments = build_melody_line_segments(
            candidate_values,
            candidate_ids,
            voice_groups=self._voice_groups,
            harmony_analysis=self._harmony_analysis,
            beat_ms=self.beat_ms,
        )
        self._melody_line_projection_key = projection_key
        self._melody_line_segments = segments
        self._melody_line_starts = [
            segment.start_audio_ms for segment in segments
        ]
        self._melody_line_ends = [
            segment.end_audio_ms for segment in segments
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._melody_line_block_max_ends = [
            max(self._melody_line_ends[start : start + block_size])
            for start in range(0, len(self._melody_line_ends), block_size)
        ]

    def set_transcription_candidates(
        self,
        candidates: list[TranscriptionCandidate] | tuple[TranscriptionCandidate, ...],
        *,
        visible: bool = True,
        candidate_id_resolver=None,
    ) -> None:
        parent = self.editor.parent()
        session = getattr(parent, "transcription_session", None)
        pairs = [
            (
                (
                    str(candidate_id_resolver(candidate))
                    if callable(candidate_id_resolver)
                    else (
                        session.candidate_id(candidate)
                        if session is not None
                        else str(
                            getattr(candidate, "candidate_id", "") or ""
                        )
                    )
                ),
                candidate,
            )
            for candidate in candidates
        ]
        pairs.sort(
            key=lambda pair: (
                float(pair[1].start_ms),
                int(pair[1].pitch),
                float(pair[1].duration_ms),
                pair[0],
            )
        )
        self._transcription_candidate_ids = [pair[0] for pair in pairs]
        self.transcription_candidates = [pair[1] for pair in pairs]
        self._transcription_candidate_id_to_index = {
            candidate_id: index
            for index, candidate_id in enumerate(
                self._transcription_candidate_ids
            )
        }
        by_pitch: dict[
            int, list[tuple[str, TranscriptionCandidate]]
        ] = defaultdict(list)
        for candidate_id, candidate in pairs:
            by_pitch[int(candidate.pitch)].append(
                (candidate_id, candidate)
            )
        folded_primary: dict[str, str] = {}
        alternative_counts: dict[str, int] = {}
        alternative_rank: dict[str, int] = {}
        for pitch_pairs in by_pitch.values():
            clusters: list[
                list[tuple[str, TranscriptionCandidate]]
            ] = []
            cluster_start = 0.0
            cluster_end = 0.0
            cluster_max_duration = 0.0
            for candidate_id, candidate in pitch_pairs:
                candidate_start = float(candidate.start_ms)
                candidate_duration = float(candidate.duration_ms)
                candidate_end = candidate_start + candidate_duration
                if not clusters:
                    clusters.append([(candidate_id, candidate)])
                    cluster_start = candidate_start
                    cluster_end = candidate_end
                    cluster_max_duration = candidate_duration
                    continue
                previous_cluster = clusters[-1]
                overlap_ms = max(
                    0.0,
                    min(cluster_end, candidate_end)
                    - max(cluster_start, candidate_start),
                )
                minimum_duration = min(
                    candidate_duration,
                    cluster_max_duration,
                )
                if (
                    minimum_duration > 0.0
                    and overlap_ms / minimum_duration >= 0.75
                    and abs(
                        candidate_start
                        - float(previous_cluster[0][1].start_ms)
                    )
                    <= 80.0
                ):
                    previous_cluster.append((candidate_id, candidate))
                    cluster_start = min(cluster_start, candidate_start)
                    cluster_end = max(cluster_end, candidate_end)
                    cluster_max_duration = max(
                        cluster_max_duration,
                        candidate_duration,
                    )
                else:
                    clusters.append([(candidate_id, candidate)])
                    cluster_start = candidate_start
                    cluster_end = candidate_end
                    cluster_max_duration = candidate_duration
            for cluster in clusters:
                if len(cluster) <= 1:
                    continue
                primary_id, _primary = max(
                    cluster,
                    key=lambda item: (
                        float(item[1].confidence),
                        float(item[1].duration_ms),
                        -float(item[1].start_ms),
                        item[0],
                    ),
                )
                alternative_counts[primary_id] = len(cluster) - 1
                ordered_alternatives = sorted(
                    (
                        (candidate_id, candidate)
                        for candidate_id, candidate in cluster
                        if candidate_id != primary_id
                    ),
                    key=lambda item: (
                        -float(item[1].confidence),
                        float(item[1].start_ms),
                        item[0],
                    ),
                )
                for rank, (candidate_id, _candidate) in enumerate(
                    ordered_alternatives,
                    start=1,
                ):
                    folded_primary[candidate_id] = primary_id
                    alternative_rank[candidate_id] = rank
        self._folded_candidate_primary = folded_primary
        self._fold_alternative_counts = alternative_counts
        self._fold_alternative_rank = alternative_rank
        self._candidate_source_object = None
        self._candidate_starts = [
            float(candidate.start_ms)
            for candidate in self.transcription_candidates
        ]
        self._candidate_ends = [
            float(candidate.start_ms) + float(candidate.duration_ms)
            for candidate in self.transcription_candidates
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._candidate_block_max_ends = [
            max(self._candidate_ends[start : start + block_size])
            for start in range(0, len(self._candidate_ends), block_size)
        ]
        self._candidate_end_audio_ms = max(
            self._candidate_ends,
            default=0.0,
        )
        self._candidate_id_set = frozenset(
            self._transcription_candidate_ids
        )
        self.transcription_candidates_visible = bool(visible)
        self._rebuild_melody_line_projection()
        self._recalculate_content_end()
        self.update()

    def set_transcription_review(
        self,
        candidates,
        candidate_id,
        *,
        selected_ids=(),
        rejected_ids=(),
        pending_routes=(),
        applied_routes=(),
        invalid_ids=(),
        duplicate_ids=(),
        staged_ids=(),
        fragment_ids=(),
        suppressed_ids=(),
        confidence_floor: float = 0.30,
        show_rejected_only: bool = False,
        audio_offset_ms: float = 0.0,
        visible: bool = True,
    ) -> None:
        candidate_values = tuple(candidates)
        source_changed = (
            candidate_values is not self._candidate_source_object
        )
        if source_changed:
            self.set_transcription_candidates(
                candidate_values,
                visible=visible,
                candidate_id_resolver=candidate_id,
            )
            self._candidate_source_object = candidate_values
        selected_values = frozenset(str(value) for value in selected_ids)
        rejected_values = frozenset(str(value) for value in rejected_ids)
        pending_values = frozenset(
            str(getattr(route, "candidate_id", ""))
            for route in pending_routes
            if int(getattr(route, "track_id", -1)) == int(self.editor.track.track_id)
        )
        applied_values = frozenset(
            str(getattr(route, "candidate_id", "")) for route in applied_routes
        )
        invalid_values = frozenset(str(value) for value in invalid_ids)
        duplicate_values = frozenset(
            str(value) for value in duplicate_ids
        )
        staged_values = frozenset(str(value) for value in staged_ids)
        fragment_values = frozenset(
            str(value) for value in fragment_ids
        )
        suppressed_values = frozenset(
            str(value) for value in suppressed_ids
        )
        normalized_confidence = max(
            0.0,
            min(1.0, float(confidence_floor)),
        )
        normalized_offset = float(audio_offset_ms)
        projection_key = (
            id(candidate_values),
            selected_values,
            rejected_values,
            pending_values,
            applied_values,
            invalid_values,
            duplicate_values,
            staged_values,
            fragment_values,
            suppressed_values,
            normalized_confidence,
            bool(show_rejected_only),
            round(normalized_offset, 6),
            bool(visible),
        )
        if (
            not source_changed
            and projection_key == self._review_projection_key
        ):
            return
        self._review_projection_key = projection_key
        self._selected_candidate_ids = set(
            selected_values.intersection(self._candidate_id_set)
        )
        self._rejected_candidate_ids = set(rejected_values)
        self._pending_candidate_ids = set(pending_values)
        self._applied_candidate_ids = set(applied_values)
        self._invalid_candidate_ids = set(invalid_values)
        self._duplicate_candidate_ids = set(duplicate_values)
        self._staged_candidate_ids = set(staged_values)
        self._fragment_candidate_ids = set(fragment_values)
        self._suppressed_candidate_ids = set(suppressed_values)
        self._confidence_floor = normalized_confidence
        self._show_rejected_only = bool(show_rejected_only)
        self._audio_offset_ms = normalized_offset
        self.transcription_candidates_visible = bool(visible)
        self._recalculate_content_end()
        self.update()

    @property
    def selected_candidate_ids(self) -> frozenset[str]:
        return frozenset(self._selected_candidate_ids)

    def set_evidence_descriptor(self, descriptor, *, audio_offset_ms: float = 0.0) -> None:
        self._evidence.close()
        self._evidence_descriptor = descriptor
        self._audio_offset_ms = float(audio_offset_ms)
        if descriptor is not None:
            self._evidence.begin_source(descriptor)
        self.update()

    def set_evidence_layers(
        self,
        *,
        frame: bool = True,
        onset: bool = True,
        contour: bool = False,
    ) -> None:
        normalized = (bool(frame), bool(onset), bool(contour))
        current = (
            self._show_frame_evidence,
            self._show_onset_evidence,
            self._show_contour_evidence,
        )
        if normalized == current:
            return
        (
            self._show_frame_evidence,
            self._show_onset_evidence,
            self._show_contour_evidence,
        ) = normalized
        self.update()

    def set_spectrogram_source(
        self,
        audio_path: str | Path | None,
        *,
        duration_ms: float = 0.0,
        audio_offset_ms: float = 0.0,
    ) -> None:
        """Attach an ephemeral reference source without changing project data."""

        previous_offset = self._audio_offset_ms
        self._audio_offset_ms = float(audio_offset_ms)
        normalized_path = str(audio_path or "")
        if not normalized_path:
            if self._spectrogram_audio_path:
                self._spectrogram.close()
                self._spectrogram_audio_path = ""
                self.update()
            return
        candidate = Path(normalized_path).expanduser().resolve(strict=False)
        source = self._spectrogram.source
        if source is not None and source.path == candidate:
            self._spectrogram.set_duration_ms(duration_ms)
            refreshed_source = self._spectrogram.source
            if (
                not math.isclose(
                    previous_offset,
                    self._audio_offset_ms,
                    abs_tol=0.001,
                )
                or refreshed_source != source
            ):
                # Duration discovery may cancel obsolete end tiles, while an
                # alignment edit repositions every ready tile.  Request a new
                # paint immediately instead of waiting for incidental input.
                self.update()
            return
        self._spectrogram.close()
        self._spectrogram_audio_path = ""
        try:
            self._spectrogram.begin_source(
                candidate,
                duration_ms=duration_ms,
            )
        except OSError:
            return
        self._spectrogram_audio_path = str(candidate)
        self.update()

    def set_spectrogram_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if normalized == self._show_spectrogram:
            return
        self._show_spectrogram = normalized
        if not normalized:
            self._spectrogram.cancel_pending()
        self.update()

    def set_reference_background_opacity(self, opacity: float) -> None:
        try:
            normalized = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError, OverflowError):
            normalized = 0.60
        if not math.isfinite(normalized):
            normalized = 0.60
        if math.isclose(
            normalized,
            self._reference_background_opacity,
            abs_tol=0.001,
        ):
            return
        self._reference_background_opacity = normalized
        self.update()

    def set_melody_lines_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if normalized == self._show_melody_lines:
            return
        self._show_melody_lines = normalized
        self.update()

    def set_melody_line_roles_visible(
        self,
        roles: Iterable[str],
    ) -> None:
        normalized = frozenset(
            str(role)
            for role in roles
            if str(role) in MELODY_LINE_GUIDE_ROLES
        )
        if not normalized:
            normalized = frozenset({MELODY_LINE_PRIMARY_ROLE})
        if normalized == self._melody_line_roles_visible:
            return
        self._melody_line_roles_visible = normalized
        self.update()

    @property
    def melody_lines_available(self) -> bool:
        return bool(self._melody_line_segments)

    @property
    def melody_line_roles_visible(self) -> frozenset[str]:
        return self._melody_line_roles_visible

    def release_transcription_evidence(self) -> None:
        self._evidence.close()
        self._evidence_descriptor = None
        self._spectrogram.close()
        self._spectrogram_audio_path = ""

    def set_transcription_candidates_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if normalized == self.transcription_candidates_visible:
            return
        self.transcription_candidates_visible = normalized
        self._recalculate_content_end()
        self.update()

    def set_preload_progress(self, progress: float, state: str = "loading") -> None:
        self.preload_progress = max(0.0, min(1.0, float(progress)))
        self.preload_state = state if state in {"idle", "loading", "ready"} else "idle"
        self.update()

    def rebuild_note_index(self) -> None:
        self._note_order = sorted(range(len(self.notes)), key=lambda index: self.notes[index].start)
        self._note_starts = [float(self.notes[index].start) for index in self._note_order]
        self._note_ends = [
            float(self.notes[index].start) + float(self.notes[index].dur)
            for index in self._note_order
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._note_block_max_ends = [
            max(self._note_ends[start : start + block_size])
            for start in range(0, len(self._note_ends), block_size)
        ]
        self._max_note_duration = max((float(note.dur) for note in self.notes), default=0.0)
        self._note_end_ms = max(
            (float(note.start + note.dur) for note in self.notes),
            default=0.0,
        )
        self._recalculate_content_end()
        self._note_index_revision += 1
        self._visible_note_cache_key = None
        self._visible_note_cache = []

    def _recalculate_content_end(self) -> None:
        candidate_end = (
            self._candidate_end_audio_ms + self._audio_offset_ms
            if self.transcription_candidates_visible
            else 0.0
        )
        self.content_end_ms = max(self._note_end_ms, candidate_end)

    def visible_note_indices(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list[int]:
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        explicit_range = left_ms is not None or right_ms is not None
        cache_key = (
            self._note_index_revision,
            round(left, 3),
            round(right, 3),
        )
        if not explicit_range and cache_key == self._visible_note_cache_key:
            return self._visible_note_cache
        hi = bisect_right(self._note_starts, right)
        # A single song-long note must not widen every later viewport to the
        # beginning of the track.  Block maximum ends retain that long note
        # while pruning blocks whose notes have all finished.
        query_left = left - 4.0 / max(1e-9, self.px_per_ms)
        visible: list[int] = []
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if self._note_block_max_ends[block_index] < query_left:
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            for ordered_index in range(start, stop):
                if self._note_ends[ordered_index] >= query_left:
                    visible.append(self._note_order[ordered_index])
        if explicit_range:
            return visible
        self._visible_note_cache_key = cache_key
        self._visible_note_cache = visible
        return visible

    def visible_ghost_notes(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list:
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        hi = bisect_right(self._ghost_starts, right)
        query_left = left - 4.0 / max(1e-9, self.px_per_ms)
        values: list = []
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if self._ghost_block_max_ends[block_index] < query_left:
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            values.extend(
                self.ghost_notes[index]
                for index in range(start, stop)
                if self._ghost_ends[index] >= query_left
            )
        return values

    def visible_transcription_candidates(self) -> list[TranscriptionCandidate]:
        return [candidate for _candidate_id, candidate in self._visible_candidate_pairs()]

    def visible_melody_line_segments(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list[MelodyLineSegment]:
        """Query only path blocks intersecting the project-time viewport."""

        self._last_melody_line_query_inspections = 0
        if not self._show_melody_lines or not self.transcription_candidates_visible:
            return []
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        audio_left = left - self._audio_offset_ms
        audio_right = right - self._audio_offset_ms
        hi = bisect_right(self._melody_line_starts, audio_right)
        query_left = audio_left - 2.0 / max(1e-9, self.px_per_ms)
        values: list[MelodyLineSegment] = []
        inspected = 0
        lod = melody_line_lod(self.px_per_beat)
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if self._melody_line_block_max_ends[block_index] < query_left:
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            inspected += stop - start
            for index in range(start, stop):
                segment = self._melody_line_segments[index]
                source_visible = any(
                    (
                        candidate_index :=
                        self._transcription_candidate_id_to_index.get(
                            candidate_id
                        )
                    )
                    is not None
                    and self._candidate_is_visible(
                        candidate_id,
                        self.transcription_candidates[candidate_index],
                    )
                    for candidate_id in segment.source_candidate_ids
                )
                if (
                    self._melody_line_ends[index] >= query_left
                    and segment.role in self._melody_line_roles_visible
                    and source_visible
                    and melody_line_kind_visible(
                        segment.kind,
                        branch=segment.branch,
                        lod=lod,
                    )
                ):
                    values.append(segment)
        self._last_melody_line_query_inspections = inspected
        return values

    def _melody_line_points(
        self,
        segment: MelodyLineSegment,
    ) -> tuple[QPointF, QPointF]:
        return (
            QPointF(
                self.x_at_time(
                    segment.start_audio_ms + self._audio_offset_ms
                ),
                self.RULER_H
                + (self.pitch_top - segment.start_pitch + 0.5)
                * self.ROW_H,
            ),
            QPointF(
                self.x_at_time(
                    segment.end_audio_ms + self._audio_offset_ms
                ),
                self.RULER_H
                + (self.pitch_top - segment.end_pitch + 0.5)
                * self.ROW_H,
            ),
        )

    def melody_guide_at(
        self,
        position: QPointF,
    ) -> MelodyLineSegment | None:
        """Hit-test visible guides without changing any formal editor note."""

        if (
            not self.editor.transcription_mode_enabled
            or position.x() < self.KEY_W
            or position.y() < self.RULER_H
        ):
            return None
        tolerance = 5.5
        center_ms = self.time_at(position.x())
        half_window_ms = tolerance / max(1e-9, self.px_per_ms)
        candidates = self.visible_melody_line_segments(
            center_ms - half_window_ms,
            center_ms + half_window_ms,
        )
        hits: list[tuple[float, float, bool, str, MelodyLineSegment]] = []
        for segment in candidates:
            if not segment.source_candidate_ids:
                continue
            start, end = self._melody_line_points(segment)
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared <= 1e-9:
                distance = math.hypot(
                    position.x() - start.x(),
                    position.y() - start.y(),
                )
            else:
                ratio = max(
                    0.0,
                    min(
                        1.0,
                        (
                            (position.x() - start.x()) * dx
                            + (position.y() - start.y()) * dy
                        )
                        / length_squared,
                    ),
                )
                distance = math.hypot(
                    position.x() - (start.x() + ratio * dx),
                    position.y() - (start.y() + ratio * dy),
                )
            hit_radius = max(
                tolerance,
                melody_line_width(segment.confidence) + 2.0,
            )
            if distance <= hit_radius:
                hits.append(
                    (
                        distance,
                        -segment.confidence,
                        segment.branch,
                        segment.group_id,
                        segment,
                    )
                )
        if not hits:
            return None
        return min(hits, key=lambda item: item[:4])[-1]

    def _candidate_is_visible(
        self, candidate_id: str, candidate: TranscriptionCandidate
    ) -> bool:
        rejected = candidate_id in self._rejected_candidate_ids
        if rejected != self._show_rejected_only:
            return False
        if candidate_id in self._applied_candidate_ids:
            return False
        if candidate_id in self._staged_candidate_ids:
            return False
        return True

    def _visible_candidate_pairs(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list[tuple[str, TranscriptionCandidate]]:
        self._last_candidate_query_inspections = 0
        if not self.transcription_candidates_visible:
            return []
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        audio_left = left - self._audio_offset_ms
        audio_right = right - self._audio_offset_ms
        hi = bisect_right(self._candidate_starts, audio_right)
        # Candidate rectangles have a four-pixel minimum width.  Expand the
        # logical left boundary by that amount so exact interval filtering
        # preserves the existing edge-paint and hit-test semantics.
        query_left = audio_left - 4.0 / max(1e-9, self.px_per_ms)
        values: list[tuple[str, TranscriptionCandidate]] = []
        inspected = 0
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if (
                self._candidate_block_max_ends[block_index]
                < query_left
            ):
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            inspected += stop - start
            for index in range(start, stop):
                if self._candidate_ends[index] < query_left:
                    continue
                candidate_id = self._transcription_candidate_ids[index]
                candidate = self.transcription_candidates[index]
                if self._candidate_is_visible(candidate_id, candidate):
                    values.append((candidate_id, candidate))
        self._last_candidate_query_inspections = inspected
        return values

    def candidate_rect(self, candidate: TranscriptionCandidate) -> QRectF:
        x = self.x_at_time(
            CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate,
                self._audio_offset_ms,
            )
        )
        y = self.RULER_H + (self.pitch_top - int(candidate.pitch)) * self.ROW_H
        return QRectF(
            x,
            y + 1,
            max(4.0, float(candidate.duration_ms) * self.px_per_ms),
            self.ROW_H - 2,
        )

    def _expanded_fold_primaries(self) -> set[str]:
        expanded = {
            self._folded_candidate_primary.get(candidate_id, candidate_id)
            for candidate_id in self._selected_candidate_ids
        }
        if self._hovered_candidate_id:
            expanded.add(
                self._folded_candidate_primary.get(
                    self._hovered_candidate_id,
                    self._hovered_candidate_id,
                )
            )
        return expanded

    def _candidate_display_rect(
        self,
        candidate_id: str,
        candidate: TranscriptionCandidate,
        *,
        expanded_primaries: set[str] | None = None,
    ) -> QRectF:
        """Fan a hovered/selected fold into individually inspectable lanes."""

        rect = self.candidate_rect(candidate)
        primary_id = self._folded_candidate_primary.get(
            candidate_id,
            candidate_id,
        )
        alternatives = self._fold_alternative_counts.get(primary_id, 0)
        expanded = (
            self._expanded_fold_primaries()
            if expanded_primaries is None
            else expanded_primaries
        )
        if alternatives <= 0 or primary_id not in expanded:
            return rect
        rank = (
            0
            if candidate_id == primary_id
            else self._fold_alternative_rank.get(candidate_id, 1)
        )
        lane_count = min(4, alternatives + 1)
        lane = min(rank, lane_count - 1)
        lane_height = max(4.0, rect.height() / lane_count)
        overflow_rank = max(0, rank - (lane_count - 1))
        return QRectF(
            rect.left() + overflow_rank * 4.0,
            rect.top() + lane * lane_height,
            max(4.0, rect.width() - overflow_rank * 4.0),
            max(3.0, lane_height - 1.0),
        )

    def candidate_at(self, pos: QPointF) -> str | None:
        if pos.x() < self.KEY_W or pos.y() < self.RULER_H:
            return None
        left_ms = self.time_at(pos.x() - 3.0)
        right_ms = self.time_at(pos.x() + 3.0)
        expanded_primaries = self._expanded_fold_primaries()
        for candidate_id, candidate in reversed(
            self._visible_candidate_pairs(left_ms, right_ms)
        ):
            if self._candidate_display_rect(
                candidate_id,
                candidate,
                expanded_primaries=expanded_primaries,
            ).adjusted(
                -2.0,
                -2.0,
                2.0,
                2.0,
            ).contains(pos):
                primary_id = self._folded_candidate_primary.get(candidate_id)
                if primary_id is not None and primary_id not in expanded_primaries:
                    return primary_id
                return candidate_id
        return None

    def _voice_group_for_candidate(
        self, candidate_id: str
    ) -> object | None:
        group_id = self._candidate_group_ids.get(str(candidate_id), "")
        if not group_id:
            return None
        return next(
            (
                group
                for group in self._voice_groups
                if str(getattr(group, "group_id", "")) == group_id
            ),
            None,
        )

    def _adjacent_voice_groups(
        self, group_id: str
    ) -> tuple[object, ...]:
        groups = tuple(
            sorted(
                self._voice_groups,
                key=lambda group: (
                    float(getattr(group, "start_audio_ms", 0.0)),
                    float(getattr(group, "end_audio_ms", 0.0)),
                    str(getattr(group, "group_id", "")),
                ),
            )
        )
        index = next(
            (
                index
                for index, group in enumerate(groups)
                if str(getattr(group, "group_id", "")) == str(group_id)
            ),
            None,
        )
        if index is None:
            return ()
        adjacent: list[object] = []
        if index > 0:
            adjacent.append(groups[index - 1])
        if index + 1 < len(groups):
            adjacent.append(groups[index + 1])
        return tuple(adjacent)

    def _show_voice_group_context_menu(
        self,
        event,
        candidate_id: str,
    ) -> bool:
        group = self._voice_group_for_candidate(candidate_id)
        if group is None:
            return False
        group_id = str(getattr(group, "group_id", "") or "")
        if not group_id:
            return False
        menu = QMenu(self)
        split_action = menu.addAction(tr("在播放头处分割声部"))
        split_audio_ms = (
            float(self.playhead_ms) - float(self._audio_offset_ms)
        )
        split_action.setEnabled(
            float(getattr(group, "start_audio_ms", 0.0))
            < split_audio_ms
            < float(getattr(group, "end_audio_ms", 0.0))
        )
        adjacent = self._adjacent_voice_groups(group_id)
        merge_menu = menu.addMenu(tr("与相邻声部合并"))
        for other in adjacent:
            other_id = str(getattr(other, "group_id", "") or "")
            role = trv(voice_role_source_label(getattr(other, "role", "")))
            start_s = (
                float(getattr(other, "start_audio_ms", 0.0)) / 1000.0
            )
            action = merge_menu.addAction(
                trf("{role} · {time:.1f}s", role=role, time=start_s)
            )
            action.setData(other_id)
        merge_menu.setEnabled(bool(adjacent))
        role_menu = menu.addMenu(tr("修改声部角色"))
        role_actions: dict[object, str] = {}
        for role_name in (
            "primary_melody",
            "secondary_melody",
            "harmony",
            "bass",
            "rhythm",
            "pad",
            "ornament",
            "fx",
        ):
            action = role_menu.addAction(voice_role_label(role_name))
            action.setData(role_name)
            role_actions[action] = role_name
        color_menu = menu.addMenu(tr("声部颜色"))
        color_actions: dict[object, str] = {}
        for color in TRACK_COLORS:
            action = color_menu.addAction("■")
            action.setForeground(QColor(color))
            action.setData(str(color))
            color_actions[action] = str(color)
        chosen = menu.exec(event.globalPosition().toPoint())
        if chosen is None:
            return True
        if chosen is split_action:
            self.voice_group_split_requested.emit(
                group_id, float(self.playhead_ms)
            )
            return True
        parent_menu = chosen.parent()
        if parent_menu is merge_menu:
            other_id = str(chosen.data() or "")
            if other_id:
                self.voice_group_merge_requested.emit(group_id, other_id)
            return True
        color = color_actions.get(chosen)
        if color:
            self.voice_group_color_requested.emit(group_id, color)
            return True
        role_name = role_actions.get(chosen)
        if role_name:
            self.voice_group_role_requested.emit(group_id, role_name)
        return True

    def set_playhead(self, ms: float) -> None:
        old_x = self.x_at_time(self.playhead_ms)
        self.playhead_ms = max(0.0, float(ms))
        new_x = self.x_at_time(self.playhead_ms)
        for x in (old_x, new_x):
            if self.KEY_W - 110 <= x <= self.width() + 110:
                self.update(QRectF(x - 110, 0, 220, self.height()).toAlignedRect())

    def set_edit_cursor(self, ms: float) -> None:
        old_x = self.x_at_time(self.edit_cursor_ms)
        self.edit_cursor_ms = max(0.0, float(ms))
        new_x = self.x_at_time(self.edit_cursor_ms)
        for x in (old_x, new_x):
            if self.KEY_W - 8 <= x <= self.width() + 8:
                self.update(QRectF(x - 8, self.RULER_H, 16, self.height() - self.RULER_H).toAlignedRect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self.editor, "update_scrollbars"):
            self.editor.update_scrollbars()

    def note_rect(self, note) -> QRectF:
        x = self.x_at_time(note.start)
        y = self.RULER_H + (self.pitch_top - note.pitch) * self.ROW_H
        return QRectF(x, y + 1, max(4.0, note.dur * self.px_per_ms), self.ROW_H - 2)

    def grid_rect(self) -> QRectF:
        # The scrollbars live in adjacent layout cells, outside this canvas.
        # Do not subtract their width a second time here.
        return QRectF(
            self.KEY_W,
            self.RULER_H,
            max(0.0, self.width() - self.KEY_W),
            max(0.0, self.height() - self.RULER_H),
        )

    def x_at_time(self, time_ms: float) -> float:
        return self.KEY_W + (float(time_ms) - self.scroll_ms) * self.px_per_ms

    def note_at(self, pos: QPointF) -> tuple[int | None, str]:
        if pos.x() < self.KEY_W or pos.y() < self.RULER_H:
            return None, ""
        for index in reversed(self.visible_note_indices()):
            rect = self.note_rect(self.notes[index])
            if rect.contains(pos):
                if abs(pos.x() - rect.left()) <= 5:
                    return index, "resize_left"
                if abs(pos.x() - rect.right()) <= 5:
                    return index, "resize_right"
                return index, "move"
        return None, ""

    def time_at(self, x: float) -> float:
        return max(0.0, self.scroll_ms + (x - self.KEY_W) / self.px_per_ms)

    def pitch_at(self, y: float) -> int:
        return max(0, min(127, self.pitch_top - int((y - self.RULER_H) // self.ROW_H)))

    def _roll_background(self) -> QPixmap:
        """Cache the time-independent piano bed and keyboard rendering."""

        canonical_drum_lanes = bool(
            getattr(self.editor, "canonical_drum_lanes", False)
        )
        instrument_adaptation = getattr(
            self.editor,
            "instrument_adaptation",
            None,
        )
        cache_key = (
            self.width(),
            self.height(),
            int(self.pitch_top),
            self.piano_pressed_pitch,
            self.piano_hover_pitch,
            canonical_drum_lanes,
            self.font().toString(),
            round(self.devicePixelRatioF(), 3),
        )
        if (
            cache_key == self._background_cache_key
            and not self._background_cache.isNull()
        ):
            return self._background_cache

        dpr = max(1.0, float(self.devicePixelRatioF()))
        background = QPixmap(
            QSize(
                max(1, round(self.width() * dpr)),
                max(1, round(self.height() * dpr)),
            )
        )
        background.setDevicePixelRatio(dpr)
        painter = QPainter(background)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        backdrop = QLinearGradient(0, 0, 0, self.height())
        backdrop.setColorAt(0.0, QColor("#1d1e21"))
        backdrop.setColorAt(1.0, QColor("#151619"))
        painter.fillRect(self.rect(), backdrop)
        grid = self.grid_rect()
        grid_backdrop = QLinearGradient(
            grid.topLeft(),
            grid.bottomLeft(),
        )
        grid_backdrop.setColorAt(0.0, QColor("#202125"))
        grid_backdrop.setColorAt(1.0, QColor("#1a1b1e"))
        painter.fillRect(grid, grid_backdrop)
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        for row in range(visible_rows + 1):
            pitch = self.pitch_top - row
            y = self.RULER_H + row * self.ROW_H
            drum_label = (
                instrument_adaptation.drum_lane_label(pitch)
                if (
                    canonical_drum_lanes
                    and instrument_adaptation is not None
                )
                else None
            )
            black = (
                False
                if canonical_drum_lanes
                else pitch % 12 in (1, 3, 6, 8, 10)
            )
            pressed = pitch == self.piano_pressed_pitch
            hovered = pitch == self.piano_hover_pitch
            painter.fillRect(
                QRectF(
                    self.KEY_W,
                    y,
                    grid.width(),
                    self.ROW_H,
                ),
                QColor(0, 0, 0, 11 if black else 2),
            )
            if pitch % 12 == 0:
                painter.fillRect(
                    QRectF(
                        self.KEY_W,
                        y,
                        grid.width(),
                        self.ROW_H,
                    ),
                    QColor(255, 255, 255, 5),
                )
            painter.save()
            key_rect = QRectF(0, y, self.KEY_W, self.ROW_H)
            natural_gradient = QLinearGradient(
                key_rect.topLeft(),
                key_rect.topRight(),
            )
            if pressed and not black:
                natural_gradient.setColorAt(0.0, QColor("#4a381e"))
                natural_gradient.setColorAt(0.72, QColor("#705326"))
                natural_gradient.setColorAt(1.0, QColor("#9a7332"))
            elif hovered and not black:
                natural_gradient.setColorAt(0.0, QColor("#292b29"))
                natural_gradient.setColorAt(0.72, QColor("#353735"))
                natural_gradient.setColorAt(1.0, QColor("#444642"))
            else:
                natural_gradient.setColorAt(0.0, QColor("#222422"))
                natural_gradient.setColorAt(0.72, QColor("#292b29"))
                natural_gradient.setColorAt(1.0, QColor("#333532"))
            if pitch % 12 == 0 and not pressed:
                natural_gradient.setColorAt(1.0, QColor("#3a3934"))
            painter.fillRect(key_rect, natural_gradient)
            painter.setPen(QColor("#3b3d39"))
            painter.drawLine(
                1,
                y + 1,
                self.KEY_W - 2,
                y + 1,
            )
            painter.setPen(QColor("#111311"))
            painter.drawLine(
                0,
                y + self.ROW_H - 1,
                self.KEY_W - 1,
                y + self.ROW_H - 1,
            )

            key_font = painter.font()
            key_font.setPointSize(
                max(7, key_font.pointSize() - 2)
            )
            key_font.setBold(black or drum_label is not None)
            painter.setFont(key_font)
            if black:
                black_rect = QRectF(
                    self.BLACK_KEY_X,
                    y + 3,
                    self.BLACK_KEY_W,
                    self.ROW_H - 6,
                )
                black_gradient = QLinearGradient(
                    black_rect.topLeft(),
                    black_rect.topRight(),
                )
                if pressed:
                    black_gradient.setColorAt(
                        0.0,
                        QColor("#3b2810"),
                    )
                    black_gradient.setColorAt(
                        0.76,
                        QColor("#65471d"),
                    )
                    black_gradient.setColorAt(
                        1.0,
                        QColor("#9b7030"),
                    )
                elif hovered:
                    black_gradient.setColorAt(
                        0.0,
                        QColor("#101311"),
                    )
                    black_gradient.setColorAt(
                        0.76,
                        QColor("#1d211e"),
                    )
                    black_gradient.setColorAt(
                        1.0,
                        QColor("#3a3d39"),
                    )
                else:
                    black_gradient.setColorAt(
                        0.0,
                        QColor("#090b0a"),
                    )
                    black_gradient.setColorAt(
                        0.76,
                        QColor("#111412"),
                    )
                    black_gradient.setColorAt(
                        1.0,
                        QColor("#292c29"),
                    )
                painter.fillRect(black_rect, black_gradient)
                painter.setPen(QColor("#050605"))
                painter.drawRect(black_rect)
                painter.setPen(
                    QColor(
                        "#fff0ca" if pressed else "#d5d0c7"
                    )
                )
                painter.drawText(
                    black_rect.adjusted(4, 0, -4, 0),
                    Qt.AlignRight | Qt.AlignVCenter,
                    drum_label or note_name(pitch),
                )
            else:
                painter.setPen(
                    QColor(
                        "#fff0ca"
                        if pressed
                        else (
                            "#d8d3ca"
                            if pitch % 12
                            else "#f0d8a2"
                        )
                    )
                )
                painter.drawText(
                    key_rect.adjusted(4, 0, -6, 0),
                    Qt.AlignRight | Qt.AlignVCenter,
                    drum_label or note_name(pitch),
                )
            painter.restore()
            painter.setPen(
                QColor("#17181a" if black else "#303135")
            )
            painter.drawLine(
                self.KEY_W,
                y,
                self.width(),
                y,
            )
            if pitch % 12 == 0:
                painter.setPen(QColor(108, 109, 113, 70))
                painter.drawLine(
                    self.KEY_W,
                    y + self.ROW_H - 1,
                    self.width(),
                    y + self.ROW_H - 1,
                )
        painter.end()
        self._background_cache_key = cache_key
        self._background_cache = background
        return background

    def _evidence_tile_rect(self, tile) -> QRectF:
        project_tile_start = (
            float(tile.time_start_ms) + self._audio_offset_ms
        )
        project_tile_end = (
            float(tile.time_end_ms) + self._audio_offset_ms
        )
        highest_pitch = float(tile.pitch_max_exclusive) - 1.0
        top = self.RULER_H + (
            float(self.pitch_top) - highest_pitch
        ) * self.ROW_H
        bottom = self.RULER_H + (
            float(self.pitch_top) - float(tile.pitch_min) + 1.0
        ) * self.ROW_H
        return QRectF(
            self.x_at_time(project_tile_start),
            top,
            max(
                1.0,
                self.x_at_time(project_tile_end)
                - self.x_at_time(project_tile_start),
            ),
            max(1.0, bottom - top),
        )

    def _evidence_tile_ready(self, tile) -> None:
        """Repaint only the completed tile instead of the full piano roll."""

        try:
            dirty = self._evidence_tile_rect(tile).intersected(
                self.grid_rect()
            )
        except (AttributeError, TypeError, ValueError):
            return
        if not dirty.isEmpty():
            self.update(dirty.adjusted(-1, -1, 1, 1).toAlignedRect())

    def _paint_transcription_evidence(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        descriptor = self._evidence_descriptor
        if (
            descriptor is None
            or not self.transcription_candidates_visible
            or self._reference_background_opacity <= 0.0
            or not (
                self._show_frame_evidence
                or self._show_onset_evidence
                or self._show_contour_evidence
            )
        ):
            return
        project_start = max(self.scroll_ms, float(paint_left_ms))
        project_end = min(
            self.time_at(self.width()),
            float(paint_right_ms),
        )
        if project_end <= project_start:
            return
        audio_start = project_start - self._audio_offset_ms
        audio_end = project_end - self._audio_offset_ms
        if audio_end <= 0.0:
            return
        visible_rows = max(
            1, math.ceil(max(0.0, grid.height()) / self.ROW_H)
        )
        pitch_max = max(
            self.MIN_PITCH, min(self.MAX_PITCH, int(self.pitch_top))
        )
        pitch_min = max(
            self.MIN_PITCH,
            min(pitch_max, pitch_max - visible_rows + 1),
        )
        layers = tuple(
            layer
            for layer, enabled in (
                ("frame", self._show_frame_evidence),
                ("onset", self._show_onset_evidence),
            )
            if enabled
        )
        tiles = self._evidence.request_visible(
            descriptor,
            start_ms=max(0.0, audio_start),
            end_ms=max(0.0, audio_end),
            pitch_min=pitch_min,
            pitch_max=pitch_max,
            pixels_per_ms=self.px_per_ms,
            layers=layers,
            include_contour=self._show_contour_evidence,
            update_viewport=(
                project_end - project_start
                >= (
                    self.time_at(self.width()) - self.scroll_ms
                )
                * 0.75
            ),
        )
        painter.save()
        painter.setClipRect(grid)
        painter.setOpacity(self._reference_background_opacity)
        for tile in tiles:
            target = self._evidence_tile_rect(tile)
            if target.intersects(grid):
                painter.drawImage(target, tile.image)
        painter.restore()

    def _paint_spectrogram_background(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        if (
            not self._show_spectrogram
            or not self._spectrogram_audio_path
            or not self.transcription_candidates_visible
            or self._reference_background_opacity <= 0.0
        ):
            return
        project_start = max(self.scroll_ms, float(paint_left_ms))
        project_end = min(
            self.time_at(self.width()),
            float(paint_right_ms),
        )
        if project_end <= project_start:
            return
        audio_start = project_start - self._audio_offset_ms
        audio_end = project_end - self._audio_offset_ms
        if audio_end <= 0.0:
            return
        visible_rows = max(
            1,
            math.ceil(max(0.0, grid.height()) / self.ROW_H),
        )
        pitch_max = max(
            self.MIN_PITCH,
            min(self.MAX_PITCH, int(self.pitch_top)),
        )
        pitch_min = max(
            self.MIN_PITCH,
            min(pitch_max, pitch_max - visible_rows + 1),
        )
        tiles = self._spectrogram.request_visible(
            start_ms=max(0.0, audio_start),
            end_ms=max(0.0, audio_end),
            pitch_min=pitch_min,
            pitch_max=pitch_max,
            pixels_per_ms=self.px_per_ms,
            update_viewport=(
                project_end - project_start
                >= (
                    self.time_at(self.width()) - self.scroll_ms
                )
                * 0.75
            ),
        )
        painter.save()
        painter.setClipRect(grid)
        painter.setOpacity(self._reference_background_opacity)
        for tile in tiles:
            target = self._evidence_tile_rect(tile)
            if target.intersects(grid):
                painter.drawImage(target, tile.image)
        painter.restore()

    def _paint_melody_lines(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        """Batch ready semantic paths; analysis never runs in this method."""

        if self._reference_background_opacity <= 0.0:
            return
        segments = self.visible_melody_line_segments(
            paint_left_ms,
            paint_right_ms,
        )
        if not segments:
            return
        paths: dict[tuple[str, int, bool, str], QPainterPath] = {}
        role_anchors: dict[str, tuple[QPointF, str]] = {}
        chord_labels: list[tuple[str, QPointF, float]] = []
        for segment in segments:
            confidence_bucket = melody_line_confidence_bucket(
                segment.confidence
            )
            key = (
                segment.role,
                confidence_bucket,
                bool(segment.branch),
                segment.kind,
            )
            path = paths.setdefault(key, QPainterPath())
            start, end = self._melody_line_points(segment)
            path.moveTo(start)
            path.lineTo(max(start.x() + 0.5, end.x()), end.y())
            if not segment.branch and (
                segment.role not in role_anchors
                or (
                    segment.kind == MELODY_LINE_CONNECTOR_KIND
                    and role_anchors[segment.role][1]
                    != MELODY_LINE_CONNECTOR_KIND
                )
            ):
                role_anchors[segment.role] = (start, segment.kind)
            if (
                segment.kind == MELODY_LINE_CHORD_SPAN_KIND
                and segment.label
                and end.x() - start.x() >= 34.0
            ):
                chord_labels.append(
                    (segment.label, start, segment.confidence)
                )

        colors = {
            MELODY_LINE_PRIMARY_ROLE: QColor("#f0b54d"),
            MELODY_LINE_BASS_ROLE: QColor("#54c3b9"),
            MELODY_LINE_HARMONY_ROLE: QColor("#a58bd5"),
        }
        painter.save()
        painter.setClipRect(grid)
        painter.setOpacity(self._reference_background_opacity)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        kind_order = {
            MELODY_LINE_CHORD_SPAN_KIND: 0,
            MELODY_LINE_CONTOUR_KIND: 1,
            MELODY_LINE_CONNECTOR_KIND: 2,
        }
        for (role, confidence_bucket, branch, kind), path in sorted(
            paths.items(),
            key=lambda item: (
                kind_order.get(item[0][3], 3),
                item[0][2],
                item[0][1],
                item[0][0],
            ),
        ):
            confidence = (
                confidence_bucket / MELODY_LINE_CONFIDENCE_BUCKETS
            )
            color = QColor(colors.get(role, QColor("#a9a49c")))
            if kind == MELODY_LINE_CHORD_SPAN_KIND:
                color.setAlpha(max(34, min(105, 40 + round(confidence * 65))))
                width = max(3.0, melody_line_width(confidence) * 1.55)
            else:
                color.setAlpha(
                    max(
                        45,
                        min(
                            220,
                            70
                            + round(confidence * 150)
                            - (18 if branch else 0),
                        ),
                    )
                )
                width = melody_line_width(confidence)
            pen = QPen(
                color,
                width,
                Qt.DashLine if branch else Qt.SolidLine,
            )
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        # Compact M/B/H badges make the three semantic layers identifiable
        # without adding another explanatory tile or permanent legend.
        badge_text = {
            MELODY_LINE_PRIMARY_ROLE: "M",
            MELODY_LINE_BASS_ROLE: "B",
            MELODY_LINE_HARMONY_ROLE: "H",
        }
        for role, (anchor, _kind) in sorted(role_anchors.items()):
            if not grid.top() <= anchor.y() <= grid.bottom():
                continue
            left = max(
                grid.left() + 3.0,
                min(grid.right() - 18.0, anchor.x() + 3.0),
            )
            rect = QRectF(left, anchor.y() - 8.0, 16.0, 16.0)
            color = QColor(colors.get(role, QColor("#a9a49c")))
            color.setAlpha(205)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.setPen(QColor("#171716"))
            painter.drawText(rect, Qt.AlignCenter, badge_text.get(role, "V"))

        if melody_line_lod(self.px_per_beat) <= 1:
            painter.setPen(QColor(224, 214, 239, 165))
            for label, anchor, confidence in chord_labels:
                if not grid.top() <= anchor.y() <= grid.bottom():
                    continue
                text_x = max(grid.left() + 22.0, anchor.x() + 5.0)
                painter.drawText(
                    QPointF(text_x, anchor.y() - 5.0),
                    f"{label} {round(confidence * 100)}%",
                )
        painter.restore()

    def _paint_unsupported_evidence_rows(
        self, painter: QPainter, grid: QRectF
    ) -> None:
        if not self.transcription_candidates_visible:
            return
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        painter.save()
        painter.setClipRect(
            QRectF(self.KEY_W - 4, grid.top(), 8, grid.height())
        )
        for row in range(visible_rows + 1):
            pitch = self.pitch_top - row
            if self.MIN_PITCH <= pitch <= self.MAX_PITCH and self.editor.note_invalid(pitch):
                y = self.RULER_H + row * self.ROW_H
                painter.fillRect(
                    QRectF(self.KEY_W - 3, y + 2, 3, self.ROW_H - 4),
                    QColor(216, 100, 90, 138),
                )
        painter.restore()

    def _visible_harmony_segments(
        self, project_start_ms: float, project_end_ms: float
    ) -> tuple[object, ...]:
        analysis = self._harmony_analysis
        segments = tuple(
            getattr(analysis, "chord_segments", ()) or ()
        )
        if not segments or not self._harmony_segment_starts:
            return ()
        audio_start = float(project_start_ms) - self._audio_offset_ms
        audio_end = float(project_end_ms) - self._audio_offset_ms
        first = max(
            0,
            bisect_left(
                self._harmony_segment_starts,
                audio_start - self._max_harmony_segment_duration,
            ),
        )
        last = bisect_right(self._harmony_segment_starts, audio_end)
        return tuple(
            segment
            for segment in segments[first:last]
            if float(getattr(segment, "end_audio_ms", 0.0))
            > audio_start
            and float(getattr(segment, "start_audio_ms", 0.0))
            < audio_end
        )

    def _chord_segment_at(self, position: QPointF) -> object | None:
        if (
            position.x() < self.KEY_W
            or position.y() < self.TIME_RULER_H
            or position.y() >= self.RULER_H
        ):
            return None
        project_ms = self.time_at(position.x())
        for segment in self._visible_harmony_segments(
            project_ms - 1.0, project_ms + 1.0
        ):
            start_ms = (
                float(getattr(segment, "start_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            end_ms = (
                float(getattr(segment, "end_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            if start_ms <= project_ms < end_ms:
                return segment
        return None

    @staticmethod
    def _roman_degree(
        root_pc: int | None,
        key: object | None,
        quality: str = "",
    ) -> str:
        if root_pc is None or key is None:
            return ""
        key_root = getattr(key, "root_pc", None)
        mode = str(getattr(key, "mode", "") or "")
        if key_root is None or mode not in {"major", "minor"}:
            return ""
        interval = (int(root_pc) - int(key_root)) % 12
        table = (
            {0: "I", 2: "II", 4: "III", 5: "IV", 7: "V", 9: "VI", 11: "VII"}
            if mode == "major"
            else {
                0: "I",
                2: "II",
                3: "III",
                5: "IV",
                7: "V",
                8: "VI",
                10: "VII",
            }
        )
        roman = table.get(interval, "·")
        if roman == "·":
            return roman
        if quality in {"minor", "min7", "dim", "half_diminished7"}:
            roman = roman.lower()
        if quality == "dim":
            roman += "°"
        elif quality == "half_diminished7":
            roman += "ø"
        return roman

    def _chord_display_label(
        self,
        root_pc: int | None,
        quality: str,
        bass_pc: int | None = None,
    ) -> str:
        if root_pc is None or quality == "N":
            return "N"
        suffix = {
            "major": "",
            "minor": "m",
            "dim": "°",
            "sus2": "sus2",
            "sus4": "sus4",
            "maj7": "maj7",
            "7": "7",
            "min7": "m7",
            "half_diminished7": "ø7",
        }.get(quality, quality)
        label = f"{self.editor._pitch_class_label(int(root_pc))}{suffix}"
        if bass_pc is not None and int(bass_pc) != int(root_pc):
            label += f"/{self.editor._pitch_class_label(int(bass_pc))}"
        return label

    def _paint_harmony_lane(
        self,
        painter: QPainter,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        lane = QRectF(
            self.KEY_W,
            self.TIME_RULER_H,
            max(0.0, self.width() - self.KEY_W),
            self.CHORD_H,
        )
        painter.fillRect(lane, QColor("#202124"))
        painter.setPen(QPen(QColor(83, 76, 63, 150), 1))
        painter.drawLine(
            lane.left(), lane.top(), lane.right(), lane.top()
        )
        painter.drawLine(
            lane.left(), lane.bottom(), lane.right(), lane.bottom()
        )
        analysis = self._harmony_analysis
        if analysis is None:
            return
        conflict_ids = {
            str(getattr(conflict, "segment_id", ""))
            for conflict in getattr(analysis, "conflicts", ())
        }
        global_key = getattr(analysis, "global_key", None)
        for segment in self._visible_harmony_segments(
            paint_left_ms, paint_right_ms
        ):
            start_project_ms = (
                float(getattr(segment, "start_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            end_project_ms = (
                float(getattr(segment, "end_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            left = self.x_at_time(start_project_ms)
            right = self.x_at_time(end_project_ms)
            rect = QRectF(
                left + 1,
                self.TIME_RULER_H + 2,
                max(1.0, right - left - 2),
                self.CHORD_H - 4,
            ).intersected(lane)
            confidence = max(
                0.0,
                min(1.0, float(getattr(segment, "confidence", 0.0))),
            )
            quality = str(getattr(segment, "quality", "N") or "N")
            root_pc = getattr(segment, "root_pc", None)
            fill = QColor(
                "#61533c" if quality != "N" else "#35363a"
            )
            fill.setAlpha(64 + round(confidence * 80))
            painter.fillRect(rect, fill)
            segment_id = str(getattr(segment, "segment_id", ""))
            border = (
                QColor("#df9b54")
                if segment_id in conflict_ids
                else QColor("#7d725f")
            )
            painter.setPen(
                QPen(
                    border,
                    1.5
                    if bool(getattr(segment, "locked", False))
                    else 1.0,
                )
            )
            painter.drawRect(rect)
            if rect.width() < 24:
                continue
            chord = self._chord_display_label(
                root_pc,
                quality,
                getattr(segment, "bass_pc", None),
            )
            roman = self._roman_degree(root_pc, global_key, quality)
            label = chord + (f" · {roman}" if roman else "")
            if segment_id in conflict_ids:
                label += " ?"
            if bool(getattr(segment, "locked", False)):
                label = "◆ " + label
            painter.setPen(
                QColor("#e8dfcf" if confidence >= 0.45 else "#b8ab98")
            )
            painter.drawText(
                rect.adjusted(5, 0, -3, 0),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )

    def _paint_transcription_candidates(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        """Paint clean semantic blocks using orthogonal visual channels."""

        if self.px_per_beat < 40.0:
            self._paint_voice_group_outlines(
                painter,
                grid,
                paint_left_ms,
                paint_right_ms,
            )

        groups: dict[
            tuple[bool, str, int, str, int, float, object],
            list[QRectF],
        ] = defaultdict(list)
        invalid_lines: list[tuple[QPointF, QPointF]] = []
        rejected_lines: list[tuple[QPointF, QPointF]] = []
        onset_caps: list[QRectF] = []
        pending_markers: list[QRectF] = []
        fragment_markers: list[QRectF] = []
        role_markers: dict[str, list[QRectF]] = defaultdict(list)
        labels: list[tuple[QRectF, int, float, str]] = []
        beat_width = float(self.px_per_beat)
        show_detail = beat_width > 160.0
        show_onsets = show_detail
        expanded_fold_primaries = self._expanded_fold_primaries()
        for candidate_id, candidate in self._visible_candidate_pairs(
            paint_left_ms,
            paint_right_ms,
        ):
            folded_primary = self._folded_candidate_primary.get(
                candidate_id
            )
            if (
                folded_primary is not None
                and folded_primary not in expanded_fold_primaries
                and candidate_id not in self._selected_candidate_ids
                and candidate_id not in self._rejected_candidate_ids
                and candidate_id not in self._pending_candidate_ids
                and candidate_id not in self._applied_candidate_ids
                and candidate_id not in self._invalid_candidate_ids
                and candidate_id not in self._duplicate_candidate_ids
                and candidate_id not in self._staged_candidate_ids
                and candidate_id not in self._fragment_candidate_ids
                and candidate_id not in self._suppressed_candidate_ids
            ):
                continue
            rect = self._candidate_display_rect(
                candidate_id,
                candidate,
                expanded_primaries=expanded_fold_primaries,
            )
            if not rect.intersects(grid):
                continue
            invalid = (
                candidate_id in self._invalid_candidate_ids
                or self.editor._candidate_invalid_for_current_track(candidate)
            )
            duplicate = candidate_id in self._duplicate_candidate_ids
            rejected = candidate_id in self._rejected_candidate_ids
            pending = candidate_id in self._pending_candidate_ids
            fragment = candidate_id in self._fragment_candidate_ids
            suppressed = candidate_id in self._suppressed_candidate_ids
            selected = candidate_id in self._selected_candidate_ids
            hovered = candidate_id == self._hovered_candidate_id
            confidence = max(
                0.0,
                min(1.0, float(candidate.confidence)),
            )
            color_name = self._candidate_group_colors.get(
                candidate_id,
                "#5baaa4",
            )
            opacity_confidence = round(confidence * 7.0) / 7.0
            # Confidence is an opacity channel only.  The slider controls how
            # strongly weak evidence remains visible; it never filters it.
            visible_confidence = (
                self._confidence_floor
                + opacity_confidence * (1.0 - self._confidence_floor)
            )
            fill_alpha = 34 + round(visible_confidence * 138)
            if rejected:
                fill_alpha = min(fill_alpha, 54)
            elif suppressed:
                fill_alpha = min(fill_alpha, 42)
            elif beat_width < 40.0:
                fill_alpha = min(fill_alpha, 104)

            if selected:
                outline_name = "#fff1c8"
            elif invalid:
                outline_name = "#e88479"
            elif duplicate:
                outline_name = "#99958e"
            elif pending:
                outline_name = "#8ae1d4"
            elif fragment:
                outline_name = "#e0a341"
            else:
                outline_name = color_name
            outline_alpha = 255 if selected else 118 + round(
                opacity_confidence * 108
            )
            line_style = (
                Qt.DashLine
                if rejected or fragment or suppressed
                else Qt.SolidLine
            )
            groups[
                (
                    selected,
                    color_name,
                    fill_alpha,
                    outline_name,
                    outline_alpha,
                    2.0 if selected or invalid else 1.2,
                    line_style,
                )
            ].append(rect)
            if invalid:
                invalid_lines.append(
                    (rect.topLeft(), rect.bottomRight())
                )
            if rejected:
                rejected_lines.append(
                    (
                        QPointF(rect.left(), rect.center().y()),
                        QPointF(rect.right(), rect.center().y()),
                    )
                )
            if show_onsets:
                onset_caps.append(
                    QRectF(
                        rect.left(),
                        rect.top() + 1,
                        min(2.0, rect.width()),
                        max(1.0, rect.height() - 2),
                    )
                )
            if pending:
                pending_markers.append(
                    QRectF(
                        max(rect.left(), rect.right() - 4),
                        rect.top() + 2,
                        3,
                        3,
                    )
                )
            if fragment:
                fragment_markers.append(
                    QRectF(
                        max(rect.left(), rect.right() - 4),
                        rect.top() + 1,
                        3,
                        3,
                    )
                )
            role = self._candidate_chord_roles.get(candidate_id, "")
            if show_detail and role and rect.width() >= 5:
                role_markers[role].append(
                    QRectF(
                        rect.left() + (2.0 if show_onsets else 0.0),
                        rect.top() + 2,
                        2,
                        max(1.0, rect.height() - 4),
                    )
                )
            if (
                rect.width() >= 42
                and (show_detail or selected or hovered)
            ):
                labels.append(
                    (rect, int(candidate.pitch), confidence, candidate_id)
                )

        # Selected blocks paint last so their neutral outline remains legible
        # without repurposing the instrument hue.
        for style, rects in sorted(
            groups.items(),
            key=lambda item: item[0][0],
        ):
            (
                _selected,
                color_name,
                fill_alpha,
                outline_name,
                outline_alpha,
                width,
                line_style,
            ) = style
            fill = QColor(color_name)
            fill.setAlpha(fill_alpha)
            outline = QColor(outline_name)
            outline.setAlpha(outline_alpha)
            painter.setBrush(fill)
            painter.setPen(QPen(outline, width, line_style))
            painter.drawRects(rects)

        if onset_caps:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(224, 170, 90, 210))
            painter.drawRects(onset_caps)
        role_colors = {
            "root": QColor("#e1b45b"),
            "third": QColor("#82a9d8"),
            "fifth": QColor("#79bcb0"),
            "seventh": QColor("#aa8bd2"),
        }
        painter.setPen(Qt.NoPen)
        for role, rects in role_markers.items():
            painter.setBrush(role_colors.get(role, QColor("#aaa59d")))
            painter.drawRects(rects)
        if pending_markers:
            painter.setBrush(QColor("#b9f0e7"))
            painter.drawRects(pending_markers)
        if fragment_markers:
            painter.setBrush(QColor("#f0ae42"))
            painter.drawRects(fragment_markers)
        if invalid_lines:
            painter.setPen(QPen(QColor("#e88479"), 1))
            for start, end in invalid_lines:
                painter.drawLine(start, end)
        if rejected_lines:
            painter.setPen(QPen(QColor(180, 138, 132, 190), 1))
            for start, end in rejected_lines:
                painter.drawLine(start, end)
        for rect, pitch, confidence, _candidate_id in labels:
            painter.setPen(QColor("#f0eee8"))
            alternatives = self._fold_alternative_counts.get(
                _candidate_id, 0
            )
            painter.drawText(
                rect.adjusted(6, 0, -3, 0),
                Qt.AlignLeft | Qt.AlignVCenter,
                (
                    f"{note_name(pitch)} · {confidence:.0%}"
                    + (f" · +{alternatives}" if alternatives else "")
                ),
            )

    def _paint_voice_group_outlines(
        self,
        painter: QPainter,
        grid: QRectF,
        project_start_ms: float,
        project_end_ms: float,
    ) -> None:
        if not self._voice_group_outlines:
            return
        audio_start = float(project_start_ms) - self._audio_offset_ms
        audio_end = float(project_end_ms) - self._audio_offset_ms
        first = max(
            0,
            bisect_left(
                self._voice_group_outline_starts,
                audio_start - self._max_voice_group_duration,
            ),
        )
        last = bisect_right(
            self._voice_group_outline_starts, audio_end
        )
        selected_group_ids = {
            group_id
            for candidate_id in self._selected_candidate_ids
            if (
                group_id := self._candidate_group_ids.get(candidate_id)
            )
        }
        for (
            group_id,
            start_audio_ms,
            end_audio_ms,
            pitch_min,
            pitch_max,
            role,
            color_name,
            confidence,
            note_count,
        ) in self._voice_group_outlines[first:last]:
            if end_audio_ms <= audio_start or start_audio_ms >= audio_end:
                continue
            left = self.x_at_time(
                start_audio_ms + self._audio_offset_ms
            )
            right = self.x_at_time(
                end_audio_ms + self._audio_offset_ms
            )
            top = (
                self.RULER_H
                + (self.pitch_top - pitch_max) * self.ROW_H
                + 3
            )
            bottom = (
                self.RULER_H
                + (self.pitch_top - pitch_min + 1) * self.ROW_H
                - 3
            )
            rect = QRectF(
                left,
                top,
                max(2.0, right - left),
                max(4.0, bottom - top),
            ).intersected(grid)
            if rect.isEmpty():
                continue
            color = QColor(color_name)
            span_beats = max(
                0.25,
                (end_audio_ms - start_audio_ms)
                / max(1.0, self.beat_ms),
            )
            density = min(1.0, note_count / (span_beats * 4.0))
            color.setAlpha(
                30 + round(55 * max(0.0, min(1.0, confidence)))
                + round(28 * density)
            )
            painter.fillRect(rect, color)
            group_selected = group_id in selected_group_ids
            outline = QColor("#fff1c8" if group_selected else color_name)
            outline.setAlpha(235 if group_selected else 155)
            painter.setPen(QPen(outline, 2.0 if group_selected else 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if rect.width() >= 54:
                painter.setPen(QColor("#d4cdc1"))
                painter.drawText(
                    rect.adjusted(5, 1, -4, -1),
                    Qt.AlignLeft | Qt.AlignTop,
                    trf(
                        "{role} · {count} 音",
                        role=trv(voice_role_source_label(role)),
                        count=note_count,
                    ),
                )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        # The roll is dominated by axis-aligned rectangles and one-pixel grid
        # lines.  Disabling antialiasing keeps dense 12k-note views within the
        # realtime repaint budget without changing their visual geometry.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.drawPixmap(0, 0, self._roll_background())
        grid = self.grid_rect()
        paint_rect = _event.rect()
        paint_left_ms = self.time_at(
            max(float(self.KEY_W), float(paint_rect.left()))
        )
        paint_right_ms = self.time_at(
            max(float(self.KEY_W), float(paint_rect.right()))
        )
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        self._paint_spectrogram_background(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        self._paint_transcription_evidence(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        self._paint_unsupported_evidence_rows(painter, grid)
        # Evidence sits below the editing grid.  Redraw horizontal guides after
        # the ready QImages so pitch rows remain legible at high intensity.
        for row in range(visible_rows + 1):
            pitch = self.pitch_top - row
            y = self.RULER_H + row * self.ROW_H
            painter.setPen(QColor("#17181a" if pitch % 12 in (1, 3, 6, 8, 10) else "#303135"))
            painter.drawLine(self.KEY_W, y, self.width(), y)
            if pitch % 12 == 0:
                painter.setPen(QColor(108, 109, 113, 70))
                painter.drawLine(
                    self.KEY_W,
                    y + self.ROW_H - 1,
                    self.width(),
                    y + self.ROW_H - 1,
                )
        painter.fillRect(QRectF(0, 0, self.width(), self.RULER_H), QColor("#242427"))
        painter.fillRect(QRectF(0, 0, self.KEY_W, self.RULER_H), QColor("#1c1c1e"))
        painter.fillRect(QRectF(self.KEY_W - 1, self.RULER_H, 1, grid.height()), QColor("#6f5227"))
        painter.fillRect(QRectF(self.KEY_W, self.RULER_H - 1, grid.width(), 1), QColor("#715522"))
        # Time-axis content must never paint over the fixed piano keyboard.
        # This matters after horizontal scrolling, when a long note's logical
        # rectangle can begin well to the left of the visible grid.
        painter.save()
        painter.setClipRect(QRectF(
            self.KEY_W, 0, max(0.0, self.width() - self.KEY_W), self.height()
        ))
        step_ms = self.editor.quantize_ms()
        measure_ms = self.beat_ms * max(1, self.editor.time_sig)
        beat_origin = float(getattr(self.editor, "beat_origin_ms", 0.0))
        measure = beat_origin + math.floor(
            (self.scroll_ms - beat_origin) / measure_ms
        ) * measure_ms
        measure_index = math.floor((measure - beat_origin) / measure_ms)
        right_ms = self.time_at(self.width())
        while measure <= right_ms + measure_ms:
            if measure_index % 2:
                left = self.x_at_time(measure)
                right = self.x_at_time(measure + measure_ms)
                painter.fillRect(
                    QRectF(left, self.RULER_H, right - left, grid.height()),
                    QColor(255, 255, 255, 4),
                )
            measure += measure_ms
            measure_index += 1
        first = beat_origin + math.floor(
            (self.scroll_ms - beat_origin) / step_ms
        ) * step_ms
        t = first
        while t <= right_ms + step_ms:
            x = self.x_at_time(t)
            beat_position = (t - beat_origin) / self.beat_ms
            beat_index = round(beat_position)
            major = (
                beat_index % max(1, self.editor.time_sig) == 0
                and abs(beat_position - beat_index) < .02
            )
            painter.setPen(QPen(QColor("#45464a" if major else "#2d2e32"), 1))
            painter.drawLine(x, 0 if major else self.RULER_H, x, self.height())
            painter.drawLine(
                x,
                self.TIME_RULER_H - (8 if major else 5),
                x,
                self.TIME_RULER_H - 3,
            )
            if major:
                painter.setPen(QColor("#c1b9ab"))
                painter.drawText(
                    int(x + 4),
                    19,
                    str(beat_index // max(1, self.editor.time_sig) + 1),
                )
            t += step_ms
        self._paint_harmony_lane(
            painter,
            paint_left_ms,
            paint_right_ms,
        )
        self._paint_melody_lines(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        transcription_range = self.transcription_time_range
        if transcription_range is not None:
            range_left = self.x_at_time(transcription_range[0])
            range_right = self.x_at_time(transcription_range[1])
            selection_rect = QRectF(
                min(range_left, range_right),
                self.RULER_H,
                abs(range_right - range_left),
                grid.height(),
            ).intersected(grid)
            painter.fillRect(selection_rect, QColor(245, 165, 36, 18))
            painter.setPen(QPen(QColor("#d69a3b"), 1))
            painter.drawLine(
                range_left,
                self.RULER_H,
                range_left,
                self.height(),
            )
            painter.drawLine(
                range_right,
                self.RULER_H,
                range_right,
                self.height(),
            )
        if self.ghost_notes and self._ghost_opacity > 0.0:
            painter.save()
            painter.setOpacity(self._ghost_opacity)
            for ghost in self.visible_ghost_notes(
                paint_left_ms,
                paint_right_ms,
            ):
                rect = self.note_rect(ghost)
                if not rect.intersects(grid):
                    continue
                fill = QColor(str(ghost.color))
                fill.setAlpha(30)
                outline = QColor(str(ghost.color))
                outline.setAlpha(62)
                painter.setBrush(fill)
                painter.setPen(QPen(outline, 1))
                painter.drawRect(rect)
            painter.restore()
        self._paint_transcription_candidates(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        for index in self.visible_note_indices(
            paint_left_ms,
            paint_right_ms,
        ):
            note = self.notes[index]
            rect = self.note_rect(note)
            if not rect.intersects(grid):
                continue
            color = articulation_color(int(getattr(note, "ntype", 0)))
            velocity = max(1, min(127, int(note.vel)))
            fill = QColor("#56575a").lighter(88 + round(velocity / 127.0 * 24))
            fill.setAlpha(235)
            if invalid := self.editor.note_invalid(note.pitch):
                fill = QColor("#714847")
            note_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            top_color = fill.lighter(112)
            bottom_color = fill.darker(108)
            note_gradient.setColorAt(0.0, top_color)
            note_gradient.setColorAt(1.0, bottom_color)
            painter.setBrush(note_gradient)
            painter.setPen(QPen(QColor("#ff625b" if invalid else ("#e5bd72" if index in self.selected else "#747579")), 2 if index in self.selected or invalid else 1))
            painter.drawRect(rect)
            if rect.width() >= 5:
                velocity_width = max(2.0, (rect.width() - 4.0) * velocity / 127.0)
                painter.fillRect(
                    QRectF(rect.left() + 2, rect.bottom() - 3, velocity_width, 2),
                    QColor("#d9cbb1" if index not in self.selected else "#f0cf8d"),
                )
                if int(getattr(note, "ntype", 0)) != 0:
                    technique_color = QColor(color)
                    technique_color.setAlpha(220)
                    painter.fillRect(QRectF(rect.left() + 1, rect.top() + 1, 3, rect.height() - 2), technique_color)
            if rect.width() >= 28:
                painter.save()
                painter.setClipRect(rect.adjusted(2, 1, -2, -1))
                label_font = painter.font()
                label_font.setPointSize(
                    max(
                        6,
                        label_font.pointSize()
                        - (2 if rect.width() < 34 else 1),
                    )
                )
                label_font.setBold(index in self.selected)
                painter.setFont(label_font)
                painter.setPen(QColor("#f3efe7"))
                painter.drawText(
                    rect.adjusted(5, 0, -2, 0),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    note_name(note.pitch),
                )
                painter.restore()
            if index in self.selected and rect.width() >= 12:
                handle = QColor("#fff4cf")
                painter.fillRect(QRectF(rect.left() + 1, rect.top() + 3, 3, max(4, rect.height() - 6)), handle)
                painter.fillRect(QRectF(rect.right() - 3, rect.top() + 3, 3, max(4, rect.height() - 6)), handle)
        edit_x = self.x_at_time(self.edit_cursor_ms)
        if self.KEY_W <= edit_x <= self.width():
            painter.setPen(QPen(QColor("#63c7bd"), 1, Qt.DashLine))
            painter.drawLine(edit_x, self.RULER_H, edit_x, self.height())
            marker = QPainterPath()
            marker.moveTo(edit_x - 5, self.RULER_H)
            marker.lineTo(edit_x + 5, self.RULER_H)
            marker.lineTo(edit_x, self.RULER_H + 7)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#63c7bd"))
        play_x = self.x_at_time(self.playhead_ms)
        if self.KEY_W - 1 <= play_x <= self.width():
            # Keep the zero-position cursor inside the grid instead of hiding it
            # under the piano-key/grid divider.
            play_x = max(self.KEY_W + 2.0, min(self.width() - 3.0, play_x))
            painter.fillRect(QRectF(play_x - 4, 0, 8, self.height()), QColor(245, 165, 36, 42))
            painter.fillRect(QRectF(play_x - 1.5, 0, 3, self.height()), QColor("#ffc247"))
            marker = QPainterPath()
            marker.moveTo(play_x - 8, 0)
            marker.lineTo(play_x + 8, 0)
            marker.lineTo(play_x, 12)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#ffc247"))
            time_text = self.editor.format_playback_time(self.playhead_ms)
            label_w = max(58, painter.fontMetrics().horizontalAdvance(time_text) + 10)
            label_x = min(self.width() - label_w - 3, max(self.KEY_W + 4, play_x + 7))
            label_rect = QRectF(label_x, 3, label_w, 20)
            painter.fillRect(label_rect, QColor(20, 20, 19, 225))
            painter.setPen(QPen(QColor("#ffc247"), 1))
            painter.drawRect(label_rect)
            painter.setPen(QColor("#fff4d6"))
            painter.drawText(label_rect, Qt.AlignCenter, time_text)
        if self.preload_state != "idle":
            cache_y = self.RULER_H - 3
            if self.preload_state == "loading":
                painter.fillRect(QRectF(grid.left(), cache_y, grid.width(), 3), QColor("#30383a"))
                painter.fillRect(
                    QRectF(grid.left(), cache_y, grid.width() * self.preload_progress, 3),
                    QColor("#55b8ad"),
                )
            else:
                painter.fillRect(QRectF(grid.left(), cache_y + 1, grid.width(), 1), QColor("#477a74"))
        if not self.marquee.isNull():
            painter.fillRect(self.marquee, QColor(245, 165, 36, 35))
            painter.setPen(QPen(QColor("#f5a524"), 1, Qt.DashLine))
            painter.drawRect(self.marquee)
        if self.creation_preview is not None:
            preview_rect = self.note_rect(self.creation_preview)
            painter.setBrush(QColor(245, 165, 36, 95))
            painter.setPen(QPen(QColor("#ffd27b"), 1, Qt.DashLine))
            painter.drawRect(preview_rect)
            painter.setPen(QColor("#fff4d6"))
            painter.drawText(
                preview_rect.adjusted(5, 0, -3, 0), Qt.AlignVCenter | Qt.AlignLeft,
                f"{note_name(self.creation_preview.pitch)} · v{self.creation_preview.vel}",
            )
        if (
            not self.notes
            and not self.visible_transcription_candidates()
            and self.creation_preview is None
        ):
            empty_rect = grid.adjusted(24, 24, -24, -24)
            title_font = painter.font()
            title_font.setPointSize(max(15, title_font.pointSize() + 5))
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#d7c39a"))
            painter.drawText(empty_rect.adjusted(0, -22, 0, 0), Qt.AlignCenter, tr("双击空白处，写下第一个音符"))
            hint_font = painter.font()
            hint_font.setPointSize(max(9, hint_font.pointSize() - 5))
            hint_font.setBold(False)
            painter.setFont(hint_font)
            painter.setPen(QColor("#817b71"))
            painter.drawText(empty_rect.adjusted(0, 24, 0, 0), Qt.AlignCenter, tr("按 B 进入绘制模式 · Space 播放"))
        painter.restore()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            index, _mode = self.note_at(event.position())
            if index is not None:
                self.editor.delete_note_at(index)
                event.accept()
                return
            if self.editor.transcription_mode_enabled:
                candidate_id = self.candidate_at(event.position())
                if (
                    candidate_id is not None
                    and self._show_voice_group_context_menu(
                        event, candidate_id
                    )
                ):
                    event.accept()
                    return
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and event.position().x() >= self.KEY_W
            and self.TIME_RULER_H
            <= event.position().y()
            < self.RULER_H
        ):
            segment = self._chord_segment_at(event.position())
            if segment is not None:
                segment_id = str(
                    getattr(segment, "segment_id", "") or ""
                )
                if segment_id:
                    self.chord_segment_clicked.emit(segment_id)
            else:
                self.ruler_seek_requested.emit(
                    self.time_at(event.position().x())
                )
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and event.position().x() >= self.KEY_W
            and event.position().y() < self.TIME_RULER_H
            and self.editor.transcription_mode_enabled
        ):
            anchor = self.time_at(event.position().x())
            self._ruler_range_anchor = anchor
            self._ruler_range_moved = False
            self._drag_time_range = self.transcription_time_range
            self._ruler_range_endpoint = ""
            current_range = self._drag_time_range
            if current_range is not None:
                threshold = 7.0
                if abs(event.position().x() - self.x_at_time(current_range[0])) <= threshold:
                    self._ruler_range_endpoint = "start"
                elif abs(event.position().x() - self.x_at_time(current_range[1])) <= threshold:
                    self._ruler_range_endpoint = "end"
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.position().x() >= self.KEY_W and event.position().y() < self.TIME_RULER_H:
            self.dragging_playhead = True
            seek_ms = self.time_at(event.position().x())
            self.set_edit_cursor(seek_ms)
            self.ruler_seek_requested.emit(seek_ms)
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.position().x() < self.KEY_W and event.position().y() >= self.RULER_H:
            pitch = self.pitch_at(event.position().y())
            self.piano_key_dragging = True
            self.piano_pressed_pitch = pitch
            self.piano_hover_pitch = pitch
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
            self.editor.audition_pitch(pitch)
            event.accept()
            return
        if event.button() != Qt.LeftButton or event.position().x() < self.KEY_W or event.position().y() < self.RULER_H:
            return super().mousePressEvent(event)
        self.setFocus()
        self.press_pos = event.position()
        self.press_notes = list(self.notes)
        self.press_selected = set(self.selected)
        self.ctrl_press_index = None
        self.clone_base_notes = []
        index, mode = self.note_at(event.position())
        mods = event.modifiers()
        if index is not None:
            if self._selected_candidate_ids:
                self._selected_candidate_ids.clear()
                self.candidate_selection_changed.emit(frozenset())
            touched = self.notes[index]
            self.editor.default_note_velocity = int(touched.vel)
            self.editor.last_note_duration_ms = float(touched.dur)
            self.set_edit_cursor(float(touched.start))
            if mods & Qt.ControlModifier:
                # Delay the toggle until release so a Ctrl-drag can clone the
                # current selection without first removing the grabbed note.
                self.ctrl_press_index = index
                self.drag_mode = "pending_clone"
            elif mods & Qt.ShiftModifier and self.anchor_index is not None:
                lo, hi = sorted((self.anchor_index, index))
                self.selected.update(range(lo, hi + 1))
                self.drag_mode = mode
            else:
                if index not in self.selected:
                    self.selected = {index}
                self.drag_mode = mode
            self.anchor_index = index
            self.selection_changed.emit()
            self.update()
            self.ruler_seek_requested.emit(
                self.time_at(event.position().x())
            )
            if self.editor.draft_playback_state == "stopped":
                self.editor.audition_note(self.notes[index])
            return
        if self.editor.transcription_mode_enabled and not self.editor.draw_mode_button.isChecked():
            candidate_id = self.candidate_at(event.position())
            additive = bool(mods & Qt.ControlModifier)
            if candidate_id is not None:
                selected = set(self._selected_candidate_ids) if additive else set()
                if additive and candidate_id in selected:
                    selected.remove(candidate_id)
                else:
                    selected.add(candidate_id)
                self._selected_candidate_ids = selected
                self.selected.clear()
                self.anchor_index = None
                self.candidate_selection_changed.emit(frozenset(selected))
                self.selection_changed.emit()
                self.update()
                self.ruler_seek_requested.emit(
                    self.time_at(event.position().x())
                )
                event.accept()
                return
            guide = self.melody_guide_at(event.position())
            if guide is not None:
                guide_ids = {
                    candidate_id
                    for candidate_id in guide.source_candidate_ids
                    if candidate_id in self._candidate_id_set
                }
                selected = (
                    set(self._selected_candidate_ids) if additive else set()
                )
                if additive and guide_ids and guide_ids.issubset(selected):
                    selected.difference_update(guide_ids)
                else:
                    selected.update(guide_ids)
                self._selected_candidate_ids = selected
                self.selected.clear()
                self.anchor_index = None
                self.candidate_selection_changed.emit(frozenset(selected))
                self.selection_changed.emit()
                raw_start = self.time_at(event.position().x())
                self.set_edit_cursor(raw_start)
                self.ruler_seek_requested.emit(raw_start)
                self.update()
                event.accept()
                return
            self._candidate_marquee_origin = event.position()
            self._candidate_marquee_additive = additive
            self._candidate_press_selected = set(self._selected_candidate_ids)
            self.marquee = QRectF(event.position(), event.position())
            self.drag_mode = "candidate_marquee_pending"
            if not additive:
                self._selected_candidate_ids.clear()
                self.candidate_selection_changed.emit(frozenset())
            self.selected.clear()
            self.anchor_index = None
            raw_start = self.time_at(event.position().x())
            cursor_start = (
                raw_start
                if mods & Qt.AltModifier or not self.editor.snap_box.isChecked()
                else self.editor.snap_time(raw_start)
            )
            self.set_edit_cursor(cursor_start)
            self.ruler_seek_requested.emit(raw_start)
            self.selection_changed.emit()
            self.update()
            event.accept()
            return
        if not (mods & Qt.ControlModifier):
            self.selected.clear()
        raw_start = self.time_at(event.position().x())
        cursor_start = raw_start if mods & Qt.AltModifier or not self.editor.snap_box.isChecked() else self.editor.snap_time(raw_start)
        self.set_edit_cursor(cursor_start)
        self.ruler_seek_requested.emit(raw_start)
        if self.editor.draw_mode_button.isChecked():
            self.creation_anchor_ms = cursor_start
            self.creation_anchor_pitch = self.pitch_at(event.position().y())
            self.creation_preview = Note(
                self.creation_anchor_pitch,
                self.editor.default_note_velocity,
                cursor_start,
                self.editor.default_note_duration(),
                self.editor.current_articulation(),
            )
            self.drag_mode = "draw_create"
        else:
            self.drag_mode = "pending_marquee"
        self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._ruler_range_anchor is not None and event.buttons() & Qt.LeftButton:
            target = self.time_at(pos.x())
            self._ruler_range_moved = self._ruler_range_moved or abs(
                self.x_at_time(target) - self.x_at_time(self._ruler_range_anchor)
            ) >= 3.0
            current_range = self._drag_time_range
            if self._ruler_range_endpoint and current_range is not None:
                start_ms, end_ms = current_range
                if self._ruler_range_endpoint == "start":
                    start_ms = target
                else:
                    end_ms = target
                start_ms, end_ms = sorted((start_ms, end_ms))
            else:
                start_ms, end_ms = sorted((self._ruler_range_anchor, target))
            self._drag_time_range = (
                (start_ms, end_ms) if end_ms > start_ms else None
            )
            self.update()
            event.accept()
            return
        if self.dragging_playhead and event.buttons() & Qt.LeftButton:
            self.ruler_seek_requested.emit(self.time_at(pos.x()))
            event.accept()
            return
        over_piano = pos.x() < self.KEY_W and pos.y() >= self.RULER_H
        hover_pitch = self.pitch_at(pos.y()) if over_piano else None
        if hover_pitch != self.piano_hover_pitch:
            self.piano_hover_pitch = hover_pitch
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
        if self.piano_key_dragging and event.buttons() & Qt.LeftButton:
            if hover_pitch is not None and hover_pitch != self.piano_pressed_pitch:
                self.piano_pressed_pitch = hover_pitch
                self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
                self.editor.audition_pitch(hover_pitch)
            event.accept()
            return
        self.hover_changed.emit(self.time_at(pos.x()), self.pitch_at(pos.y()))
        if not (event.buttons() & Qt.LeftButton):
            hovered_candidate_id = ""
            candidate_hit = None
            if (
                self.editor.transcription_mode_enabled
                and pos.x() >= self.KEY_W
                and pos.y() >= self.RULER_H
            ):
                candidate_hit = self.candidate_at(pos)
                if candidate_hit is not None:
                    hovered_candidate_id = candidate_hit
            guide_hit = (
                self.melody_guide_at(pos)
                if candidate_hit is None
                and not self.editor.draw_mode_button.isChecked()
                else None
            )
            if guide_hit is not None:
                self.setToolTip(
                    trf(
                        "{role}{branch_separator}{branch} · {confidence}% · {action}",
                        role=trv(voice_role_source_label(guide_hit.role)),
                        branch_separator=" · " if guide_hit.branch else "",
                        branch=trv("分支") if guide_hit.branch else "",
                        confidence=round(guide_hit.confidence * 100),
                        action=trv("点击定位候选"),
                    )
                )
            else:
                self.setToolTip("")
            if hovered_candidate_id != self._hovered_candidate_id:
                previous_id = self._hovered_candidate_id
                self._hovered_candidate_id = hovered_candidate_id
                for candidate_id in (previous_id, hovered_candidate_id):
                    candidate_index = self._transcription_candidate_id_to_index.get(
                        candidate_id
                    )
                    if candidate_index is not None:
                        self.update(
                            self.candidate_rect(
                                self.transcription_candidates[candidate_index]
                            )
                            .adjusted(-8.0, -4.0, 112.0, 4.0)
                            .toAlignedRect()
                        )
            if pos.x() < self.KEY_W:
                self.setCursor(Qt.PointingHandCursor)
            elif (
                self.TIME_RULER_H
                <= pos.y()
                < self.RULER_H
            ):
                self.setCursor(
                    Qt.PointingHandCursor
                    if self._chord_segment_at(pos) is not None
                    else Qt.ArrowCursor
                )
            elif pos.y() < self.TIME_RULER_H:
                self.setCursor(Qt.SizeHorCursor)
            else:
                _index, mode = self.note_at(pos)
                if mode in ("resize_left", "resize_right"):
                    self.setCursor(Qt.SizeHorCursor)
                elif mode == "move":
                    self.setCursor(Qt.SizeAllCursor)
                elif guide_hit is not None:
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.setCursor(Qt.CrossCursor if self.editor.draw_mode_button.isChecked() else Qt.ArrowCursor)
            return
        dx, dy = pos.x() - self.press_pos.x(), pos.y() - self.press_pos.y()
        if self.drag_mode in {"candidate_marquee_pending", "candidate_marquee"}:
            if (
                self._candidate_marquee_origin is not None
                and math.hypot(dx, dy) > 4
            ):
                self.drag_mode = "candidate_marquee"
            if (
                self.drag_mode == "candidate_marquee"
                and self._candidate_marquee_origin is not None
            ):
                self.marquee = QRectF(
                    self._candidate_marquee_origin, pos
                ).normalized()
                selected = (
                    set(self._candidate_press_selected)
                    if self._candidate_marquee_additive
                    else set()
                )
                marquee_left_ms = self.time_at(
                    max(float(self.KEY_W), self.marquee.left())
                )
                marquee_right_ms = self.time_at(
                    max(float(self.KEY_W), self.marquee.right())
                )
                for candidate_id, candidate in self._visible_candidate_pairs(
                    marquee_left_ms,
                    marquee_right_ms,
                ):
                    if self.candidate_rect(candidate).intersects(
                        self.marquee
                    ):
                        selected.add(candidate_id)
                if selected != self._selected_candidate_ids:
                    self._selected_candidate_ids = selected
                    self.candidate_selection_changed.emit(frozenset(selected))
                self.update()
            return
        if self.drag_mode == "draw_create" and self.creation_preview is not None:
            current = self.time_at(pos.x())
            snap = self.editor.snap_box.isChecked() and not (event.modifiers() & Qt.AltModifier)
            if snap:
                current = self.editor.snap_time(current)
            start = min(self.creation_anchor_ms, current)
            duration = max(self.editor.minimum_duration_ms(), abs(current - self.creation_anchor_ms))
            if abs(dx) < 4:
                start = self.creation_anchor_ms
                duration = self.editor.default_note_duration()
            velocity = max(1, min(127, self.editor.default_note_velocity - round(dy * 1.5)))
            self.creation_preview = self.creation_preview._replace(start=start, dur=duration, vel=velocity)
            self.update()
            return
        if self.drag_mode == "pending_clone" and math.hypot(dx, dy) > 4 and self.ctrl_press_index is not None:
            source_indices = (
                sorted(self.press_selected)
                if self.ctrl_press_index in self.press_selected
                else [self.ctrl_press_index]
            )
            self.clone_base_notes = [self.press_notes[index] for index in source_indices]
            first = len(self.press_notes)
            self.notes = list(self.press_notes) + list(self.clone_base_notes)
            self.selected = set(range(first, first + len(self.clone_base_notes)))
            self.anchor_index = first + source_indices.index(self.ctrl_press_index)
            self.drag_mode = "clone_move"
            self.selection_changed.emit()
        if self.drag_mode == "pending_marquee" and math.hypot(dx, dy) > 4:
            self.drag_mode = "marquee"
        if self.drag_mode == "marquee":
            self.marquee = QRectF(self.press_pos, pos).normalized()
            hits = {
                i for i in self.visible_note_indices()
                if self.note_rect(self.notes[i]).intersects(self.marquee)
            }
            selected = self.press_selected.union(hits) if event.modifiers() & Qt.ControlModifier else hits
            if selected != self.selected:
                self.selected = selected
                self.selection_changed.emit()
            self.update()
            return
        if self.drag_mode == "clone_move" and self.clone_base_notes:
            dt = dx / self.px_per_ms
            if self.editor.snap_box.isChecked() and not (event.modifiers() & Qt.AltModifier):
                q = self.editor.quantize_ms()
                dt = round(dt / q) * q
            dt = max(dt, -min(note.start for note in self.clone_base_notes))
            dp = -round(dy / self.ROW_H)
            self.notes = list(self.press_notes) + [
                note._replace(
                    start=note.start + dt,
                    pitch=max(0, min(127, note.pitch + dp)),
                )
                for note in self.clone_base_notes
            ]
            self.update()
            return
        if self.drag_mode not in ("move", "resize_left", "resize_right") or not self.selected:
            return
        dt = dx / self.px_per_ms
        if self.editor.snap_box.isChecked() and not (event.modifiers() & Qt.AltModifier):
            q = self.editor.quantize_ms()
            dt = round(dt / q) * q
        dp = -round(dy / self.ROW_H)
        changed = list(self.press_notes)
        minimum = self.editor.minimum_duration_ms()
        for i in self.selected:
            old = self.press_notes[i]
            if self.drag_mode == "move":
                changed[i] = old._replace(start=max(0.0, old.start + dt), pitch=max(0, min(127, old.pitch + dp)))
            elif self.drag_mode == "resize_right":
                anchor = self.press_notes[self.anchor_index] if self.anchor_index in self.selected else old
                factor = max(minimum / max(minimum, anchor.dur), (anchor.dur + dt) / max(minimum, anchor.dur))
                changed[i] = old._replace(dur=max(minimum, old.dur * factor))
            else:
                anchor = self.press_notes[self.anchor_index] if self.anchor_index in self.selected else old
                factor = max(minimum / max(minimum, anchor.dur), (anchor.dur - dt) / max(minimum, anchor.dur))
                new_dur = max(minimum, old.dur * factor)
                end = old.start + old.dur
                new_start = max(0.0, end - new_dur)
                changed[i] = old._replace(start=new_start, dur=end - new_start)
        self.notes = changed
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._ruler_range_anchor is not None:
            anchor = self._ruler_range_anchor
            if self._ruler_range_moved and self._drag_time_range is not None:
                self.time_range_changed.emit(self._drag_time_range)
            else:
                self.ruler_seek_requested.emit(anchor)
            self._ruler_range_anchor = None
            self._ruler_range_endpoint = ""
            self._ruler_range_moved = False
            self._drag_time_range = None
            self.update()
            event.accept()
            return
        if self.piano_key_dragging:
            self.piano_key_dragging = False
            self.piano_pressed_pitch = None
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
            event.accept()
            return
        if self.dragging_playhead:
            self.dragging_playhead = False
            event.accept()
            return
        if self.drag_mode in {"candidate_marquee_pending", "candidate_marquee"}:
            self._candidate_marquee_origin = None
            self._candidate_marquee_additive = False
            self._candidate_press_selected.clear()
            self.marquee = QRectF()
            self.drag_mode = ""
            self.update()
            event.accept()
            return
        if self.drag_mode == "draw_create" and self.creation_preview is not None:
            self.editor.push_snapshot()
            self.notes.append(self.creation_preview)
            self.selected = {len(self.notes) - 1}
            self.anchor_index = len(self.notes) - 1
            self.editor.default_note_velocity = self.creation_preview.vel
            self.editor.last_note_duration_ms = self.creation_preview.dur
            self.set_edit_cursor(self.creation_preview.start + self.creation_preview.dur)
            self.notes_changed.emit()
            self.selection_changed.emit()
            self.editor.audition_note(self.notes[-1])
        elif self.drag_mode == "pending_clone" and self.ctrl_press_index is not None:
            if self.ctrl_press_index in self.press_selected:
                self.selected.discard(self.ctrl_press_index)
            else:
                self.selected.add(self.ctrl_press_index)
            self.selection_changed.emit()
        elif self.drag_mode == "clone_move" and self.notes != self.press_notes:
            self.editor.push_snapshot(self.press_notes, self.press_selected)
            self.notes_changed.emit()
            if self.anchor_index is not None:
                self.editor.audition_note(self.notes[self.anchor_index])
        elif self.drag_mode in ("move", "resize_left", "resize_right") and self.notes != self.press_notes:
            self.editor.push_snapshot(self.press_notes, self.press_selected)
            self.notes_changed.emit()
            if self.drag_mode == "move" and self.anchor_index is not None:
                before = self.press_notes[self.anchor_index]
                after = self.notes[self.anchor_index]
                if before.pitch != after.pitch:
                    self.editor.audition_note(after)
        self.marquee = QRectF()
        self.creation_preview = None
        self.ctrl_press_index = None
        self.clone_base_notes = []
        self.drag_mode = ""
        self.update()

    def leaveEvent(self, event) -> None:
        self.setToolTip("")
        if self._hovered_candidate_id:
            candidate_index = self._transcription_candidate_id_to_index.get(
                self._hovered_candidate_id
            )
            self._hovered_candidate_id = ""
            if candidate_index is not None:
                self.update(
                    self.candidate_rect(
                        self.transcription_candidates[candidate_index]
                    )
                    .adjusted(-8.0, -4.0, 112.0, 4.0)
                    .toAlignedRect()
                )
        if not self.piano_key_dragging and self.piano_hover_pitch is not None:
            self.piano_hover_pitch = None
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if (
            self.editor.transcription_mode_enabled
            and event.button() == Qt.LeftButton
            and self.candidate_at(event.position()) is not None
        ):
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and not self.editor.draw_mode_button.isChecked()
            and event.position().x() >= self.KEY_W
            and event.position().y() >= self.RULER_H
            and self.note_at(event.position())[0] is None
        ):
            raw_start = self.time_at(event.position().x())
            start = (
                raw_start
                if event.modifiers() & Qt.AltModifier or not self.editor.snap_box.isChecked()
                else self.editor.snap_time(raw_start)
            )
            self.set_edit_cursor(start)
            self.editor.push_snapshot()
            self.notes.append(Note(
                self.pitch_at(event.position().y()),
                self.editor.default_note_velocity,
                start,
                self.editor.default_note_duration(),
                self.editor.current_articulation(),
            ))
            self.selected = {len(self.notes) - 1}
            self.anchor_index = len(self.notes) - 1
            self.set_edit_cursor(start + self.notes[-1].dur)
            self.drag_mode = ""
            self.notes_changed.emit()
            self.selection_changed.emit()
            self.editor.audition_note(self.notes[-1])
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)
        if event.modifiers() & Qt.ControlModifier:
            anchor_x = max(self.KEY_W, min(self.width(), event.position().x()))
            anchor_time = self.time_at(anchor_x)
            new_zoom = max(
                30.0,
                min(320.0, self.px_per_beat * (1.12 if delta > 0 else 1 / 1.12)),
            )
            self.px_per_beat = new_zoom
            self.scroll_ms = max(
                0.0,
                anchor_time - (anchor_x - self.KEY_W) / self.px_per_ms,
            )
            self.editor.editor_zoom.blockSignals(True)
            self.editor.editor_zoom.setValue(round(new_zoom))
            self.editor.editor_zoom.blockSignals(False)
        elif event.modifiers() & Qt.ShiftModifier:
            self.scroll_ms = max(0.0, self.scroll_ms - delta / 120 * self.beat_ms)
        else:
            pitch_min, pitch_max = self.editor.pitch_top_bounds()
            self.pitch_top = max(
                pitch_min,
                min(pitch_max, self.pitch_top + (3 if delta > 0 else -3)),
            )
        self.update()
        self.editor.update_scrollbars()
        event.accept()

    def keyPressEvent(self, event) -> None:
        mods, key = event.modifiers(), event.key()
        if key == Qt.Key_Escape and self._selected_candidate_ids:
            self._selected_candidate_ids.clear()
            self.candidate_selection_changed.emit(frozenset())
            self.update()
            event.accept()
            return
        if key == Qt.Key_B and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)):
            self.editor.draw_mode_button.toggle()
            return
        if key == Qt.Key_Escape and self.editor.draw_mode_button.isChecked():
            self.editor.draw_mode_button.setChecked(False)
            return
        if mods & Qt.ControlModifier and key == Qt.Key_D and self.selected:
            self.editor.duplicate_selected()
            return
        if mods & Qt.ControlModifier and key in (Qt.Key_Up, Qt.Key_Down) and self.selected:
            self.editor.push_snapshot()
            step = 8 if mods & Qt.ShiftModifier else 1
            delta = step if key == Qt.Key_Up else -step
            for index in self.selected:
                note = self.notes[index]
                self.notes[index] = note._replace(vel=max(1, min(127, note.vel + delta)))
            self.notes_changed.emit()
            self.selection_changed.emit()
            return
        if not (mods & Qt.ControlModifier) and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.selected:
            self.editor.push_snapshot()
            changed = list(self.notes)
            if key in (Qt.Key_Up, Qt.Key_Down):
                step = 12 if mods & Qt.ShiftModifier else 1
                delta = step if key == Qt.Key_Up else -step
                for index in self.selected:
                    changed[index] = changed[index]._replace(
                        pitch=max(0, min(127, changed[index].pitch + delta))
                    )
            else:
                step = max(1.0, self.editor.quantize_ms() / 8.0) if mods & Qt.AltModifier else self.editor.quantize_ms()
                delta = step if key == Qt.Key_Right else -step
                if mods & Qt.ShiftModifier:
                    for index in self.selected:
                        changed[index] = changed[index]._replace(
                            dur=max(self.editor.minimum_duration_ms(), changed[index].dur + delta)
                        )
                else:
                    delta = max(delta, -min(self.notes[index].start for index in self.selected))
                    for index in self.selected:
                        changed[index] = changed[index]._replace(start=changed[index].start + delta)
            self.notes = changed
            self.notes_changed.emit()
            self.selection_changed.emit()
            return
        if mods & Qt.ControlModifier and key == Qt.Key_A:
            self.editor.select_all_notes()
            event.accept()
            return
        if (mods & Qt.ControlModifier and key == Qt.Key_Y) or (mods & Qt.ControlModifier and mods & Qt.ShiftModifier and key == Qt.Key_Z):
            self.editor.redo(); return
        if mods & Qt.ControlModifier and key == Qt.Key_Z:
            self.editor.undo(); return
        if mods & Qt.ControlModifier and key == Qt.Key_C:
            self.editor.copy_selected(); return
        if mods & Qt.ControlModifier and key == Qt.Key_X:
            self.editor.copy_selected(); self.editor.delete_selected(); return
        if mods & Qt.ControlModifier and key == Qt.Key_V:
            self.editor.paste_notes(); return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.editor.delete_selected(); return
        super().keyPressEvent(event)


class VelocityLaneCanvas(QWidget):
    """Point-based velocity curve with time-distance neighbour weighting."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.before_notes: list = []
        self.before_selected: set[int] = set()
        self.active_point_time: float | None = None
        self.active_point_velocity = 0.0
        self.hover_velocity: int | None = None
        self.influence_beats = 2.0
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeVerCursor)
        self.setMinimumHeight(104)
        self.setMaximumHeight(144)
        self.setToolTip(
            tr("拖动曲线点调整力度；越近的时间点影响越大。滚轮调整影响范围。")
        )

    @property
    def influence_radius_ms(self) -> float:
        return max(self.editor.quantize_ms(), self.editor.canvas.beat_ms * self.influence_beats)

    def _velocity_at(self, y: float) -> int:
        usable = max(1.0, self.height() - 10.0)
        return max(1, min(127, round((1.0 - (y - 5.0) / usable) * 127)))

    def _y_for_velocity(self, velocity: float) -> float:
        bounded = max(1.0, min(127.0, float(velocity)))
        return 5.0 + (1.0 - bounded / 127.0) * max(1.0, self.height() - 10.0)

    def _visible_points(self) -> list[tuple[float, tuple[int, ...], float]]:
        return velocity_time_points(
            self.editor.canvas.notes,
            self.editor.canvas.visible_note_indices(),
        )

    def _point_for_index(self, index: int) -> tuple[float, tuple[int, ...], float]:
        note = self.editor.canvas.notes[index]
        onset = round(float(note.start), 3)
        indices = tuple(
            point_index
            for point_index, point_note in enumerate(self.editor.canvas.notes)
            if round(float(point_note.start), 3) == onset
        )
        velocity = sum(float(self.editor.canvas.notes[item].vel) for item in indices) / len(indices)
        return onset, indices, velocity

    def _bar_rect(self, index: int) -> QRectF:
        """Compatibility hit rectangle; the velocity lane now paints points."""
        onset, _indices, velocity = self._point_for_index(index)
        x = self.editor.canvas.x_at_time(onset)
        y = self._y_for_velocity(velocity)
        return QRectF(x - 6.0, y - 6.0, 12.0, 12.0)

    def _point_at(self, x: float) -> tuple[float, tuple[int, ...], float] | None:
        candidates = self._visible_points()
        if not candidates:
            return None
        nearest = min(
            candidates,
            key=lambda point: abs(self.editor.canvas.x_at_time(point[0]) - x),
        )
        if abs(self.editor.canvas.x_at_time(nearest[0]) - x) > 9.0:
            return None
        return nearest

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1a1b1e"))
        painter.fillRect(QRectF(0, 0, self.editor.canvas.KEY_W, self.height()), QColor("#242427"))
        for value in (32, 64, 96, 127):
            y = self._y_for_velocity(value)
            painter.setPen(QColor("#34353a" if value != 127 else "#4a4b50"))
            painter.drawLine(QPointF(self.editor.canvas.KEY_W, y), QPointF(self.width(), y))
            painter.setPen(QColor("#8d8b84"))
            painter.drawText(
                QRectF(3, y - 8, self.editor.canvas.KEY_W - 8, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                str(value),
            )

        painter.setPen(QColor("#9d8a67"))
        painter.drawText(
            QRectF(4, self.height() - 22, self.editor.canvas.KEY_W - 8, 18),
            Qt.AlignCenter,
            trf("影响 {beats:.1f} 拍", beats=self.influence_beats),
        )
        curve_rect = QRectF(
            self.editor.canvas.KEY_W,
            0,
            max(0.0, self.width() - self.editor.canvas.KEY_W),
            self.height(),
        )
        painter.save()
        painter.setClipRect(curve_rect)

        if self.active_point_time is not None:
            left = self.editor.canvas.x_at_time(
                self.active_point_time - self.influence_radius_ms
            )
            right = self.editor.canvas.x_at_time(
                self.active_point_time + self.influence_radius_ms
            )
            painter.fillRect(
                QRectF(left, 0, max(1.0, right - left), self.height()),
                QColor(213, 163, 78, 22),
            )

        points = self._visible_points()
        if points:
            path = QPainterPath()
            for point_index, (onset, _indices, velocity) in enumerate(points):
                x = self.editor.canvas.x_at_time(onset)
                y = self._y_for_velocity(velocity)
                if point_index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(QColor("#c79a50"), 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            for onset, indices, velocity in points:
                x = self.editor.canvas.x_at_time(onset)
                y = self._y_for_velocity(velocity)
                selected = any(index in self.editor.canvas.selected for index in indices)
                active = self.active_point_time is not None and math.isclose(
                    onset, self.active_point_time, abs_tol=0.001,
                )
                painter.setPen(QPen(QColor("#ffe1a3" if selected or active else "#9c8f7b"), 1))
                painter.setBrush(QColor("#e0aa50" if selected or active else "#66686d"))
                size = 10.0 if selected or active else 8.0
                painter.drawEllipse(QRectF(x - size / 2, y - size / 2, size, size))
        painter.restore()

        if self.hover_velocity is not None:
            y = self._y_for_velocity(self.hover_velocity)
            painter.setPen(QColor("#d9a441"))
            painter.drawLine(QPointF(self.editor.canvas.KEY_W, y), QPointF(self.width(), y))
            badge = QRectF(
                5,
                max(3.0, min(self.height() - 45.0, y - 11.0)),
                self.editor.canvas.KEY_W - 10,
                22,
            )
            painter.fillRect(badge, QColor("#5d451e"))
            painter.setPen(QColor("#fff2d2"))
            painter.drawText(badge, Qt.AlignCenter, str(self.hover_velocity))

    def _apply_drag(self, target_velocity: int) -> None:
        if self.active_point_time is None or not self.before_notes:
            return
        delta = float(target_velocity) - self.active_point_velocity
        self.editor.canvas.notes = apply_weighted_velocity_delta(
            self.before_notes,
            self.active_point_time,
            delta,
            self.influence_radius_ms,
        )
        self.editor.canvas.update()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        point = self._point_at(event.position().x())
        if point is None:
            return
        onset, indices, velocity = point
        self.before_notes = list(self.editor.canvas.notes)
        self.before_selected = set(self.editor.canvas.selected)
        self.active_point_time = onset
        self.active_point_velocity = velocity
        self.hover_velocity = self._velocity_at(event.position().y())
        self.editor.canvas.selected = set(indices)
        self.editor.canvas.selection_changed.emit()
        self._apply_drag(self.hover_velocity)

    def mouseMoveEvent(self, event) -> None:
        self.hover_velocity = self._velocity_at(event.position().y())
        if event.buttons() & Qt.LeftButton and self.active_point_time is not None:
            self._apply_drag(self.hover_velocity)
            return
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.before_notes
            and self.editor.canvas.notes != self.before_notes
        ):
            self.editor.push_snapshot(self.before_notes, self.before_selected)
            self.editor.canvas.notes_changed.emit()
        self.before_notes = []
        self.before_selected = set()
        self.active_point_time = None
        self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        self.influence_beats = max(
            0.5,
            min(8.0, self.influence_beats + (0.5 if delta > 0 else -0.5)),
        )
        self.editor.status.setText(
            trf("力度曲线影响范围：前后 {beats:.1f} 拍", beats=self.influence_beats)
        )
        self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        if self.active_point_time is None:
            self.hover_velocity = None
            self.update()
        super().leaveEvent(event)


class MidiNoteEditorDialog(QDialog):
    notes_applied = Signal(object)

    def __init__(
        self,
        parent,
        track: TrackState,
        bpm: int,
        time_sig: int,
        transpose: int = 0,
        *,
        transcription_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MidiNoteEditorDialog")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.track, self.bpm, self.time_sig, self.transpose = track, int(bpm or 120), int(time_sig or 4), int(transpose)
        self.instrument_adaptation = instrument_editor_display_adaptation(
            int(track.bdo_instrument_id)
        )
        self.canonical_drum_lanes = track_uses_canonical_drum_lanes(track)
        self._initial_pitch_focus_pending = True
        self.beat_origin_ms = float(getattr(parent, "beat_origin_ms", 0.0))
        self.undo_stack: list[
            tuple[
                list,
                set[int],
                set[CandidateRoute],
                set[CandidateRoute],
                dict[int, int],
                str,
                str,
            ]
        ] = []
        self.redo_stack: list[
            tuple[
                list,
                set[int],
                set[CandidateRoute],
                set[CandidateRoute],
                dict[int, int],
                str,
                str,
            ]
        ] = []
        self.clipboard: list = []
        self.last_applied = list(track.notes)
        self.staged_primary_routes: set[CandidateRoute] = set()
        self.staged_copy_routes: set[CandidateRoute] = set()
        self.staged_new_track_specs: dict[int, int] = {}
        self.staged_analysis_cache_key = ""
        self.staged_analysis_fingerprint = ""
        self._transcription_mode_requested = bool(transcription_mode)
        self._velocity_visible_before_transcription = False
        self.updating_fields = False
        self.draft_playback_state = "stopped"
        self.playhead_ms = 0.0
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(16)
        self.playback_timer.timeout.connect(self.poll_draft_playback)
        self.audition_timer = QTimer(self)
        self.audition_timer.setInterval(25)
        self.audition_timer.timeout.connect(self._poll_note_audition)
        self.audition_stop_timer = QTimer(self)
        self.audition_stop_timer.setSingleShot(True)
        self.audition_stop_timer.timeout.connect(self._stop_note_audition)
        self.audition_pending = False
        self.audition_note_name = ""
        self.transcription_mode_enabled = False
        self.transcription_candidates: tuple[TranscriptionCandidate, ...] = ()
        self.transcription_result: TranscriptionResult | None = None
        self.transcription_audition_source = "combined"
        self._spectrogram_reference_audio: object | None = None
        self._transcription_annotation_projection_cache = None
        self._transcription_display_projection_cache = None
        self._eligible_candidate_cache: tuple[
            tuple,
            tuple[str, ...],
        ] | None = None
        self.draft_reference_only = False
        self.default_note_velocity = 100
        self.last_note_duration_ms = 0.0
        self._invalid_pitch_cache: dict[int, bool] = {}
        self._invalid_note_count = 0
        self._hover_status_key: tuple[int, int] | None = None
        self.setWindowTitle(
            trf("编辑音符 · {track}", track=track.display_name)
        )
        self.setMinimumSize(920, 680)
        available = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        if available is None:
            self.resize(1440, 860)
        else:
            self.resize(
                max(self.minimumWidth(), min(1560, available.width() - 72)),
                max(self.minimumHeight(), min(960, available.height() - 72)),
            )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 6)
        root.setSpacing(4)

        def add_inset(widget: QWidget, object_name: str) -> None:
            shell = QWidget()
            shell.setObjectName(object_name)
            shell_layout = QHBoxLayout(shell)
            shell_layout.setContentsMargins(8, 0, 8, 0)
            shell_layout.setSpacing(0)
            shell_layout.addWidget(widget)
            root.addWidget(shell)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("EditorToolbar")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(10, 3, 8, 3)
        toolbar.setSpacing(6)
        self.editor_title_block = QWidget()
        title_layout = QVBoxLayout(self.editor_title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        instrument_name = _ui_bdo_instrument_name(track.bdo_instrument_id)
        title = ElidedLabel(track.display_name, maximum_hint_width=180)
        title.setObjectName("EditorTrackTitle")
        title.setProperty("i18nSkipText", True)
        title.setToolTip(instrument_name)
        title.setAccessibleDescription(instrument_name)
        title_layout.addWidget(title)
        self.track_meta = ElidedLabel(maximum_hint_width=210)
        self.track_meta.setObjectName("EditorTrackMeta")
        title_layout.addWidget(self.track_meta)
        toolbar.addWidget(self.editor_title_block)
        toolbar.addSpacing(10)
        self.editor_transport_frame = QFrame()
        self.editor_transport_frame.setObjectName("EditorTransport")
        transport = QHBoxLayout(self.editor_transport_frame)
        transport.setContentsMargins(4, 1, 5, 1)
        transport.setSpacing(4)
        self.draft_play_button = PillButton(tr("播放"), "primary", FluentSymbol.PLAY)
        self.draft_play_button.clicked.connect(self.toggle_draft_playback)
        transport.addWidget(self.draft_play_button)
        self.draft_stop_button = PillButton(tr("停止"), "ghost", FluentSymbol.STOP)
        self.draft_stop_button.clicked.connect(self.stop_draft)
        transport.addWidget(self.draft_stop_button)
        self.loop_box = QCheckBox(tr("循环"))
        transport.addWidget(self.loop_box)
        self.playback_time_label = QLabel("0:00.000 / 0:00.000")
        self.playback_time_label.setObjectName("EditorTime")
        self.playback_time_label.setFixedWidth(152)
        transport.addWidget(self.playback_time_label)
        toolbar.addWidget(self.editor_transport_frame)
        toolbar.addStretch(1)
        self.editor_toolbar_action_buttons: dict[str, PillButton] = {}
        for label, callback in (("撤销", self.undo), ("重做", self.redo), ("删除", self.delete_selected)):
            icon = FluentSymbol.DELETE if label == "删除" else None
            button = PillButton(tr(label), "ghost", icon)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.editor_toolbar_action_buttons[label] = button
        self.editor_optimize_button = PillButton(
            tr("优化此轨"),
            "secondary",
            FluentSymbol.OPTIMIZE,
        )
        self.editor_optimize_button.clicked.connect(self.optimize_draft)
        toolbar.addWidget(self.editor_optimize_button)
        toolbar.addSpacing(5)
        self.apply_button = PillButton(tr("应用"), "ghost")
        self.apply_button.clicked.connect(self.apply_notes)
        toolbar.addWidget(self.apply_button)
        self.cancel_button = PillButton(tr("取消"), "ghost")
        self.cancel_button.clicked.connect(self.reject)
        toolbar.addWidget(self.cancel_button)
        self.confirm_button = PillButton(tr("确定"), "convert")
        self.confirm_button.clicked.connect(self.accept_with_apply)
        toolbar.addWidget(self.confirm_button)
        add_inset(toolbar_frame, "EditorToolbarInset")

        inspector = QFrame()
        inspector.setObjectName("NoteInspectorTop")
        inspector.setFixedHeight(38)
        inspector_layout = QHBoxLayout(inspector)
        inspector_layout.setContentsMargins(6, 4, 6, 4)
        inspector_layout.setSpacing(5)
        self.draw_mode_button = PillButton(tr("绘制 B"), "ghost")
        self.draw_mode_button.setObjectName("DrawMode")
        self.draw_mode_button.setCheckable(True)
        self.draw_mode_button.setFixedHeight(28)
        self.draw_mode_button.setToolTip(
            tr("绘制模式：拖动可同时设置音符长度与力度（B）")
        )
        self.draw_mode_button.toggled.connect(self._toggle_draw_mode)
        inspector_layout.addWidget(self.draw_mode_button)
        self.note_mode_button = PillButton(tr("音符属性"), "ghost")
        self.note_mode_button.setObjectName("InspectorMode")
        self.note_mode_button.setFixedHeight(28)
        self.note_mode_button.setCheckable(True)
        self.note_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("note"))
        inspector_layout.addWidget(self.note_mode_button)
        self.articulation_mode_button = PillButton(tr("奏法"), "ghost")
        self.articulation_mode_button.setObjectName("InspectorMode")
        self.articulation_mode_button.setFixedHeight(28)
        self.articulation_mode_button.setCheckable(True)
        self.articulation_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("articulation"))
        inspector_layout.addWidget(self.articulation_mode_button)
        self.grid_mode_button = PillButton(tr("网格"), "ghost")
        self.grid_mode_button.setObjectName("InspectorMode")
        self.grid_mode_button.setFixedHeight(28)
        self.grid_mode_button.setCheckable(True)
        self.grid_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("grid"))
        inspector_layout.addWidget(self.grid_mode_button)
        self.velocity_toggle = PillButton(tr("力度"), "ghost", FluentSymbol.CURVE)
        self.velocity_toggle.setObjectName("VelocityToggle")
        self.velocity_toggle.setCheckable(True)
        self.velocity_toggle.setFixedHeight(28)
        self.velocity_toggle.setToolTip(
            tr("显示力度曲线；拖动时间点会按距离影响周边点")
        )
        self.velocity_toggle.toggled.connect(self._toggle_velocity_lane)
        inspector_layout.addWidget(self.velocity_toggle)

        self.note_controls = QWidget()
        note_layout = QHBoxLayout(self.note_controls)
        note_layout.setContentsMargins(3, 0, 0, 0)
        note_layout.setSpacing(7)
        self.selection_summary = QLabel(tr("未选择音符"))
        self.selection_summary.setObjectName("InspectorSelection")
        self.selection_summary.setWordWrap(False)
        self.selection_summary.setMinimumWidth(145)
        self.selection_summary.setMaximumWidth(190)
        note_layout.addWidget(self.selection_summary)
        self.pitch_edit = QLineEdit()
        self.start_edit = QLineEdit()
        self.duration_edit = QLineEdit()
        self.velocity_edit = QLineEdit()
        self.note_field_labels: list[QLabel] = []
        for label, widget, field in (("音高", self.pitch_edit, "pitch"), ("开始 ms", self.start_edit, "start"), ("时值 ms", self.duration_edit, "dur"), ("力度", self.velocity_edit, "vel")):
            widget.editingFinished.connect(lambda f=field, w=widget: self.apply_field(f, w.text()))
            widget.setFixedWidth(64 if field in ("pitch", "vel") else 72)
            group = QWidget()
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            field_label = QLabel(tr(label))
            field_label.setObjectName("Muted")
            field_label.setBuddy(widget)
            widget.setAccessibleName(tr(label))
            self.note_field_labels.append(field_label)
            group_layout.addWidget(field_label)
            group_layout.addWidget(widget)
            note_layout.addWidget(group)

        self.articulation_combo = QComboBox()
        supported = BDO_ARTICULATIONS.get(track.bdo_instrument_id, [])
        known = {n for n, _ in supported}
        for ntype, label in supported:
            self.articulation_combo.addItem(tr(label), ntype)
        for ntype in sorted({int(getattr(n, "ntype", 0)) for n in track.notes} - known):
            self.articulation_combo.addItem(
                trf("未知奏法 type {ntype}", ntype=ntype),
                ntype,
            )
        if self.articulation_combo.count() == 0:
            self.articulation_combo.addItem(tr("普通"), 0)
        if not track.notes and self.instrument_adaptation is not None:
            default_index = self.articulation_combo.findData(
                int(self.instrument_adaptation.default_ntype)
            )
            if default_index >= 0:
                self.articulation_combo.setCurrentIndex(default_index)
        self.articulation_combo.currentIndexChanged.connect(self.apply_articulation)
        note_layout.addStretch(1)
        inspector_layout.addWidget(self.note_controls, 1)

        self.articulation_controls = QWidget()
        articulation_layout = QHBoxLayout(self.articulation_controls)
        articulation_layout.setContentsMargins(3, 0, 0, 0)
        articulation_layout.setSpacing(6)
        self.articulation_combo.setObjectName("ArticulationCombo")
        self.articulation_combo.setMinimumWidth(145)
        articulation_layout.addWidget(self.articulation_combo)
        self.articulation_buttons: dict[int, QPushButton] = {}
        for ntype, label in supported:
            button = QPushButton(tr(label))
            button.setObjectName("ArticulationChip")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setProperty("ntype", ntype)
            button.clicked.connect(lambda _checked=False, value=ntype: self._choose_articulation(value))
            articulation_layout.addWidget(button)
            self.articulation_buttons[ntype] = button
        articulation_layout.addStretch(1)
        inspector_layout.addWidget(self.articulation_controls, 1)

        self.grid_controls = QWidget()
        grid_layout = QHBoxLayout(self.grid_controls)
        grid_layout.setContentsMargins(3, 0, 0, 0)
        grid_layout.setSpacing(12)
        self.snap_box = QCheckBox(tr("吸附"))
        self.snap_box.setChecked(True)
        grid_layout.addWidget(self.snap_box)
        self.note_preview_box = QCheckBox(tr("点击试听"))
        self.note_preview_box.setChecked(True)
        grid_layout.addWidget(self.note_preview_box)
        self.ghost_box = QCheckBox(tr("幽灵"))
        self.ghost_box.setAccessibleName(tr("其他轨道参考"))
        self.ghost_box.setChecked(True)
        self.ghost_box.toggled.connect(self._toggle_ghost_notes)
        grid_layout.addWidget(self.ghost_box)
        self.ghost_opacity_slider = QSlider(Qt.Horizontal)
        self.ghost_opacity_slider.setObjectName("GhostNoteOpacitySlider")
        self.ghost_opacity_slider.setRange(0, 100)
        self.ghost_opacity_slider.setValue(70)
        self.ghost_opacity_slider.setFixedWidth(72)
        self.ghost_opacity_slider.setToolTip(tr("幽灵音块透明度"))
        self.ghost_opacity_slider.setAccessibleName(
            tr("幽灵音块透明度")
        )
        self.ghost_opacity_slider.valueChanged.connect(
            self._ghost_opacity_changed
        )
        grid_layout.addWidget(self.ghost_opacity_slider)
        self.ghost_opacity_label = QLabel("70%")
        self.ghost_opacity_label.setFixedWidth(38)
        grid_layout.addWidget(self.ghost_opacity_label)
        grid_layout.addWidget(QLabel(tr("量化")))
        self.quantize_combo = QComboBox()
        for label, divisor in (
            ("1/4", 1),
            ("1/8", 2),
            ("1/16", 4),
            ("1/32", 8),
            ("1/64", 16),
        ):
            self.quantize_combo.addItem(label, divisor)
        self.quantize_combo.setCurrentIndex(2)
        self.quantize_combo.setFixedWidth(76)
        grid_layout.addWidget(self.quantize_combo)
        editor_zoom_label = QLabel(tr("水平缩放"))
        grid_layout.addWidget(editor_zoom_label)
        self.editor_zoom = QSlider(Qt.Horizontal)
        self.editor_zoom.setRange(30, 320)
        self.editor_zoom.setValue(92)
        self.editor_zoom.setFixedWidth(150)
        self.editor_zoom.setAccessibleName(tr("水平缩放"))
        editor_zoom_label.setBuddy(self.editor_zoom)
        self.editor_zoom.valueChanged.connect(self.set_zoom)
        grid_layout.addWidget(self.editor_zoom)
        grid_layout.addStretch(1)
        inspector_layout.addWidget(self.grid_controls, 1)
        add_inset(inspector, "EditorInspectorInset")
        self._set_top_inspector_mode("note")

        self.transcription_panel = TranscriptionEditorPanel(self)
        self.transcription_panel.setVisible(False)
        # Compatibility aliases keep the analysis-worker adapter small while
        # all visible controls now live in the embedded panel.
        self.transcription_hint = self.transcription_panel.status_label
        self.transcription_progress = self.transcription_panel.status_label
        self.transcription_analyze_button = self.transcription_panel.analyze_button
        self.transcription_accept_button = (
            self.transcription_panel.write_current_track_button
        )
        self.transcription_clear_button = (
            self.transcription_panel.clear_staging_button
        )
        self.transcription_panel.load_audio_requested.connect(
            self._load_reference_audio_from_editor
        )
        self.transcription_panel.unload_audio_requested.connect(
            self._unload_reference_audio_from_editor
        )
        self.transcription_panel.analyze_requested.connect(
            self.start_transcription_analysis
        )
        self.transcription_panel.redecode_requested.connect(
            self._redecode_transcription_range
        )
        self.transcription_panel.analysis_mode_changed.connect(
            self._transcription_analysis_mode_changed
        )
        self.transcription_panel.sensitivity_changed.connect(
            self._transcription_sensitivity_changed
        )
        self.transcription_panel.cleanup_profile_changed.connect(
            self._transcription_cleanup_profile_changed
        )
        self.transcription_panel.confidence_changed.connect(
            lambda _value: self._sync_shared_transcription_projection()
        )
        self.transcription_panel.show_rejected_changed.connect(
            lambda _value: self._sync_shared_transcription_projection()
        )
        self.transcription_panel.show_suppressed_changed.connect(
            lambda _value: self._sync_shared_transcription_projection()
        )
        self.transcription_panel.select_fragments_requested.connect(
            self._select_suspected_transcription_fragments
        )
        self.transcription_panel.evidence_layers_changed.connect(
            self._transcription_evidence_layers_changed
        )
        self.transcription_panel.melody_lines_visibility_changed.connect(
            self._transcription_melody_lines_visibility_changed
        )
        self.transcription_panel.melody_line_roles_changed.connect(
            self._transcription_melody_line_roles_changed
        )
        self.transcription_panel.spectrogram_visibility_changed.connect(
            self._transcription_spectrogram_visibility_changed
        )
        self.transcription_panel.reference_background_opacity_changed.connect(
            self._transcription_reference_background_opacity_changed
        )
        self.transcription_panel.align_audio_requested.connect(
            self._align_reference_audio_to_playhead
        )
        self.transcription_panel.beat_origin_requested.connect(
            self._set_playhead_as_beat_origin
        )
        self.transcription_panel.clear_range_requested.connect(
            self._clear_transcription_range
        )
        self.transcription_panel.review_undo_requested.connect(
            self._undo_transcription_review
        )
        self.transcription_panel.review_redo_requested.connect(
            self._redo_transcription_review
        )
        self.transcription_panel.reject_requested.connect(
            self._reject_transcription_candidates
        )
        self.transcription_panel.restore_requested.connect(
            self._restore_transcription_candidates
        )
        self.transcription_panel.write_current_track_requested.connect(
            self.accept_transcription_candidates
        )
        self.transcription_panel.copy_to_track_requested.connect(
            self._stage_transcription_copy
        )
        self.transcription_panel.clear_staging_requested.connect(
            self._clear_transcription_staging
        )
        self.transcription_panel.diagnostic_evidence_expanded_changed.connect(
            self._transcription_diagnostic_visibility_changed
        )
        self.transcription_panel.key_edit_requested.connect(
            self._edit_transcription_key
        )
        self.transcription_panel.key_lock_requested.connect(
            self._lock_transcription_key
        )
        self.transcription_panel.chord_edit_requested.connect(
            self._edit_transcription_chord
        )
        self.transcription_panel.chord_lock_requested.connect(
            self._lock_transcription_chord
        )
        self.transcription_panel.chord_split_requested.connect(
            self._split_transcription_chord
        )
        self.transcription_panel.chord_merge_next_requested.connect(
            self._merge_transcription_chord_with_next
        )
        self.transcription_panel.previous_phrase_requested.connect(
            lambda: self._navigate_transcription_phrase(-1)
        )
        self.transcription_panel.next_phrase_requested.connect(
            lambda: self._navigate_transcription_phrase(1)
        )
        self.transcription_panel.loop_phrase_requested.connect(
            self._loop_transcription_phrase
        )
        self.transcription_panel.review_queue_requested.connect(
            self._open_transcription_review_queue
        )
        self.transcription_panel.confirm_match_requested.connect(
            self._confirm_transcription_instrument_match
        )
        self.transcription_panel.stage_existing_track_requested.connect(
            self._stage_transcription_group_to_existing_track
        )
        self.transcription_panel.new_track_requested.connect(
            self._stage_transcription_group_to_new_track
        )
        self.transcription_panel.audition_source_changed.connect(
            self._set_transcription_audition_source
        )
        root.addWidget(self.transcription_panel)
        parent_config = getattr(parent, "config", {})
        if not isinstance(parent_config, dict):
            parent_config = {}
        reference_layer_settings = normalize_reference_layer_settings(
            getattr(parent, "reference_layer_settings", None)
        )
        if parent is not None:
            parent.reference_layer_settings = reference_layer_settings
        blocked = self.ghost_box.blockSignals(True)
        self.ghost_box.setChecked(
            bool(reference_layer_settings["ghost_visible"])
        )
        self.ghost_box.blockSignals(blocked)
        ghost_opacity_percent = int(
            reference_layer_settings["ghost_opacity_percent"]
        )
        blocked = self.ghost_opacity_slider.blockSignals(True)
        self.ghost_opacity_slider.setValue(ghost_opacity_percent)
        self.ghost_opacity_slider.blockSignals(blocked)
        self.ghost_opacity_label.setText(f"{ghost_opacity_percent}%")
        transcription_ui_config = (
            parent_config.get("transcription_ui", {})
            if isinstance(parent_config.get("transcription_ui", {}), dict)
            else {}
        )
        configured_layers = {
            layer
            for layer in ("frame", "onset", "contour")
            if bool(reference_layer_settings[f"{layer}_visible"])
        }
        self.transcription_panel.set_evidence_layers(configured_layers)
        self.transcription_panel.set_melody_lines_visible(
            bool(reference_layer_settings["melody_lines_visible"])
        )
        self.transcription_panel.set_spectrogram_visible(
            bool(reference_layer_settings["spectrogram_visible"])
        )
        self.transcription_panel.set_reference_background_opacity(
            int(reference_layer_settings["background_opacity_percent"])
            / 100.0
        )
        configured_guide_roles = transcription_ui_config.get(
            "melody_line_roles",
            tuple(MELODY_LINE_GUIDE_ROLES),
        )
        if isinstance(configured_guide_roles, (list, tuple, set)):
            self.transcription_panel.set_melody_line_roles(
                str(role) for role in configured_guide_roles
            )
        self.transcription_panel.set_diagnostic_evidence_expanded(
            bool(
                transcription_ui_config.get(
                    "diagnostic_evidence_expanded",
                    bool(configured_layers),
                )
            )
        )

        workspace = QFrame()
        workspace.setObjectName("EditorWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        roll = QGridLayout()
        roll.setContentsMargins(0, 0, 0, 0)
        roll.setSpacing(0)
        self.canvas = PianoRollCanvas(self)
        self.canvas.set_ghost_opacity(ghost_opacity_percent / 100.0)
        self.canvas.set_reference_background_opacity(
            int(reference_layer_settings["background_opacity_percent"])
            / 100.0
        )
        self.canvas.set_melody_line_roles_visible(
            self.transcription_panel.melody_line_roles
        )
        self.canvas.set_notes(list(track.notes))
        self.canvas.selection_changed.connect(self.refresh_fields)
        self.canvas.notes_changed.connect(self._notes_changed)
        self.canvas.hover_changed.connect(self._hover_changed)
        self.canvas.ruler_seek_requested.connect(self.seek_draft)
        self.canvas.candidate_selection_changed.connect(
            self._transcription_selection_changed
        )
        self.canvas.time_range_changed.connect(
            self._transcription_range_changed
        )
        self.canvas.chord_segment_clicked.connect(
            self._transcription_chord_segment_clicked
        )
        self.canvas.voice_group_split_requested.connect(
            self._split_transcription_voice_group
        )
        self.canvas.voice_group_merge_requested.connect(
            self._merge_transcription_voice_groups
        )
        self.canvas.voice_group_color_requested.connect(
            self._set_transcription_voice_group_color
        )
        self.canvas.voice_group_role_requested.connect(
            self._set_transcription_voice_group_role
        )
        self.pitch_scroll = QScrollBar(Qt.Vertical)
        self.pitch_scroll.setObjectName("PianoPitchScroll")
        self.pitch_scroll.setRange(0, 0)
        self.pitch_scroll.valueChanged.connect(self.set_pitch_scroll)
        self.time_scroll = QScrollBar(Qt.Horizontal)
        self.time_scroll.setObjectName("PianoTimeScroll")
        self.time_scroll.valueChanged.connect(self.set_time_scroll)
        roll.addWidget(self.canvas, 0, 0)
        roll.addWidget(self.pitch_scroll, 0, 1)
        workspace_layout.addLayout(roll, 1)
        self.transcription_waveform = TranscriptionWaveformLane(
            self.canvas, workspace
        )
        self.transcription_waveform.setVisible(False)
        self.transcription_waveform.seek_requested.connect(self.seek_draft)
        workspace_layout.addWidget(self.transcription_waveform)
        self.velocity_lane = VelocityLaneCanvas(self)
        self.velocity_lane.setVisible(False)
        workspace_layout.addWidget(self.velocity_lane)
        scroll_row = QHBoxLayout()
        scroll_row.setContentsMargins(0, 0, 0, 0)
        scroll_row.setSpacing(0)
        scroll_row.addWidget(self.time_scroll, 1)
        scroll_corner = QWidget()
        scroll_corner.setObjectName("PianoScrollCorner")
        scroll_corner.setFixedSize(12, 12)
        scroll_row.addWidget(scroll_corner)
        workspace_layout.addLayout(scroll_row)
        root.addWidget(workspace, 1)

        footer = QFrame()
        footer.setObjectName("EditorFooter")
        footer.setFixedHeight(31)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 3, 8, 3)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        footer_layout.addWidget(self.status, 1)
        music_volume_label = QLabel(tr("音乐音量"))
        music_volume_label.setObjectName("Muted")
        footer_layout.addWidget(music_volume_label)
        self.music_volume_slider = QSlider(Qt.Horizontal)
        self.music_volume_slider.setObjectName("EditorMusicVolume")
        self.music_volume_slider.setRange(0, 100)
        reference_audio = getattr(parent, "reference_audio", None)
        initial_music_volume = (
            int(reference_audio.volume_percent)
            if reference_audio is not None
            else 50
        )
        self.music_volume_slider.setValue(initial_music_volume)
        self.music_volume_slider.setFixedWidth(112)
        self.music_volume_slider.setToolTip(tr("调整参考音频音量"))
        self.music_volume_slider.setAccessibleName(tr("音乐音量"))
        music_volume_label.setBuddy(self.music_volume_slider)
        self.music_volume_slider.valueChanged.connect(self._set_editor_music_volume)
        footer_layout.addWidget(self.music_volume_slider)
        self.music_volume_value = QLabel(f"{initial_music_volume}%")
        self.music_volume_value.setObjectName("Muted")
        self.music_volume_value.setFixedWidth(38)
        footer_layout.addWidget(self.music_volume_value)
        self.transcription_mode_toggle = QCheckBox(tr("扒谱模式"))
        self.transcription_mode_toggle.setObjectName("TranscriptionModeToggle")
        self.transcription_mode_toggle.setToolTip(
            tr("在当前音符编辑器中显示分析证据、候选和参考波形")
        )
        self.transcription_mode_toggle.toggled.connect(
            self._set_transcription_mode_enabled
        )
        footer_layout.addWidget(self.transcription_mode_toggle)
        add_inset(footer, "EditorFooterInset")
        self._toggle_ghost_notes(self.ghost_box.isChecked())
        self.finished.connect(lambda _result: self.stop_draft())
        self.select_all_shortcut = QShortcut(QKeySequence.SelectAll, self)
        self.select_all_shortcut.setContext(Qt.WindowShortcut)
        self.select_all_shortcut.setAutoRepeat(False)
        self.select_all_shortcut.activated.connect(self.select_all_notes)
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.space_shortcut.setContext(Qt.WindowShortcut)
        self.space_shortcut.setAutoRepeat(False)
        self.space_shortcut.activated.connect(self.toggle_draft_playback)
        self._editor_event_filter_installed = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._editor_event_filter_installed = True
        self.finished.connect(
            lambda _result: self._remove_editor_event_filter()
        )
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.refresh_fields()
        self._apply_editor_responsive_density()
        QTimer.singleShot(0, self.update_scrollbars)
        QTimer.singleShot(
            180,
            lambda: show_global_toast(
                self,
                tr("双击网格新建音符；按 B 切换绘制模式。"),
            ),
        )
        if self._transcription_mode_requested:
            QTimer.singleShot(
                0, lambda: self.transcription_mode_toggle.setChecked(True)
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_editor_responsive_density()

    @staticmethod
    def _set_editor_compact_button(
        button: QPushButton,
        source_text: str,
        compact_text: str,
        compact: bool,
    ) -> None:
        full_text = tr(source_text)
        button.setToolTip(full_text)
        button.setAccessibleName(full_text)
        if compact:
            button.setText(compact_text)
            button.setFixedWidth(34)
        else:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setText(full_text)

    def _apply_editor_responsive_density(self) -> None:
        """Keep both editor command rows usable at the supported 920 px width."""

        if not hasattr(self, "editor_title_block"):
            return
        compact = self.width() < EDITOR_VERBOSE_CONTROLS_MIN_WIDTH
        if getattr(self, "_editor_controls_compact", None) == compact:
            return
        self._editor_controls_compact = compact

        self.editor_title_block.setMaximumWidth(150 if compact else 16777215)
        self._set_editor_compact_button(
            self.draft_play_button,
            "播放",
            "",
            compact,
        )
        self._set_editor_compact_button(
            self.draft_stop_button,
            "停止",
            "",
            compact,
        )
        self.loop_box.setToolTip(tr("循环"))
        self.loop_box.setAccessibleName(tr("循环"))
        self.loop_box.setText("" if compact else tr("循环"))
        self.playback_time_label.setFixedWidth(126 if compact else 152)

        for source, compact_text in (
            ("撤销", "↶"),
            ("重做", "↷"),
            ("删除", ""),
        ):
            self._set_editor_compact_button(
                self.editor_toolbar_action_buttons[source],
                source,
                compact_text,
                compact,
            )
        self._set_editor_compact_button(
            self.editor_optimize_button,
            "优化此轨",
            "",
            compact,
        )
        self._set_editor_compact_button(
            self.apply_button,
            "应用",
            "↵",
            compact,
        )
        self._set_editor_compact_button(
            self.cancel_button,
            "取消",
            "×",
            compact,
        )
        self._set_editor_compact_button(
            self.confirm_button,
            "确定",
            "✓",
            compact,
        )

        for button, source, compact_text in (
            (self.draw_mode_button, "绘制 B", "B"),
            (self.note_mode_button, "音符属性", "N"),
            (self.articulation_mode_button, "奏法", "T"),
            (self.grid_mode_button, "网格", "G"),
            (self.velocity_toggle, "力度", ""),
        ):
            self._set_editor_compact_button(
                button,
                source,
                compact_text,
                compact,
            )
        for label in self.note_field_labels:
            label.setVisible(not compact)
        self.selection_summary.setMinimumWidth(70 if compact else 145)
        self.selection_summary.setMaximumWidth(120 if compact else 190)
        self.editor_title_block.updateGeometry()
        self.editor_transport_frame.updateGeometry()

    def quantize_ms(self) -> float:
        return self.canvas.beat_ms / int(self.quantize_combo.currentData() or 4)

    def select_all_notes(self) -> None:
        """Select every editable draft note regardless of the focused control."""

        self.canvas.selected = set(range(len(self.canvas.notes)))
        self.canvas.anchor_index = 0 if self.canvas.notes else None
        self.canvas.selection_changed.emit()
        self.canvas.update()

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.KeyPress
            and self.isActiveWindow()
            and event.modifiers() == Qt.ControlModifier
            and event.key() == Qt.Key_A
        ):
            self.select_all_notes()
            event.accept()
            return True
        if (
            event.type() == QEvent.KeyPress
            and self.isActiveWindow()
            and event.modifiers() == Qt.NoModifier
            and event.key() == Qt.Key_Space
        ):
            if not event.isAutoRepeat():
                self.toggle_draft_playback()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _remove_editor_event_filter(self) -> None:
        if not self._editor_event_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._editor_event_filter_installed = False

    def _set_editor_music_volume(self, value: int) -> None:
        normalized = max(0, min(100, int(value)))
        self.music_volume_value.setText(f"{normalized}%")
        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is not None:
            reference_audio.set_volume_percent(normalized)

    def _set_transcription_mode_enabled(self, enabled: bool) -> None:
        if (
            self.transcription_mode_enabled
            and not enabled
            and self.draft_playback_state != "stopped"
        ):
            # stop_draft must still see transcription mode enabled so it also
            # stops the Qt reference player before the mode is switched off.
            self.stop_draft()
        self.transcription_mode_enabled = bool(enabled)
        self.transcription_panel.setVisible(self.transcription_mode_enabled)
        self.transcription_waveform.setVisible(self.transcription_mode_enabled)
        self.canvas.set_transcription_candidates_visible(
            self.transcription_mode_enabled
        )
        if self.transcription_mode_enabled:
            self._velocity_visible_before_transcription = (
                self.velocity_toggle.isChecked()
            )
            if self.velocity_toggle.isChecked():
                self.velocity_toggle.setChecked(False)
            self.velocity_toggle.setEnabled(False)
            self._sync_shared_transcription_projection()
        else:
            self.canvas.release_transcription_evidence()
            self.transcription_waveform.release_reference_audio()
            self.velocity_toggle.setEnabled(True)
            if self._velocity_visible_before_transcription:
                self.velocity_toggle.setChecked(True)
            self._velocity_visible_before_transcription = False
        self.update_scrollbars()

    def _toggle_transcription_analysis(self) -> None:
        parent_worker = getattr(
            self.parent(),
            "workspace_transcription_worker",
            None,
        )
        if parent_worker is not None and parent_worker.isRunning():
            self._cancel_transcription_analysis()
            return
        self.start_transcription_analysis()

    def _has_transcription_staging(self) -> bool:
        return bool(
            self.staged_primary_routes
            or self.staged_copy_routes
            or self.staged_new_track_specs
        )

    def _capture_staging_identity(self) -> None:
        if self.staged_analysis_cache_key or self.staged_analysis_fingerprint:
            return
        session = getattr(self.parent(), "transcription_session", None)
        state = getattr(session, "state", None)
        self.staged_analysis_cache_key = str(
            getattr(state, "cache_key", "") or ""
        )
        self.staged_analysis_fingerprint = str(
            getattr(state, "analysis_fingerprint", "") or ""
        )

    def _clear_staging_identity_if_empty(self) -> None:
        if self._has_transcription_staging():
            return
        self.staged_analysis_cache_key = ""
        self.staged_analysis_fingerprint = ""

    def _warn_staging_blocks_analysis(self) -> bool:
        if not self._has_transcription_staging():
            return False
        QMessageBox.warning(
            self,
            tr("存在未提交候选草稿"),
            tr("请先应用、撤销或清除本次暂存，再更换音频或重新分析。"),
        )
        return True

    # Public host-facing facade.  The main window must not reach through the
    # dialog into its panel/canvas implementation details.
    def has_transcription_staging(self) -> bool:
        return self._has_transcription_staging()

    def warn_transcription_staging_blocked(self) -> bool:
        return self._warn_staging_blocks_analysis()

    def eligible_transcription_candidate_ids(
        self,
        *,
        include_routed: bool = False,
    ) -> tuple[str, ...]:
        return self._eligible_transcription_candidate_ids(
            include_routed=include_routed
        )

    def refresh_transcription_projection(self) -> None:
        self._sync_shared_transcription_projection()

    def release_transcription_resources(self) -> None:
        self._bind_spectrogram_reference_audio(None)
        self.canvas.release_transcription_evidence()
        self.transcription_waveform.release_reference_audio()

    def _bind_spectrogram_reference_audio(self, controller: object | None) -> None:
        previous = self._spectrogram_reference_audio
        if previous is controller:
            return
        if previous is not None:
            signal = getattr(previous, "timeline_changed", None)
            if signal is not None:
                try:
                    signal.disconnect(self._refresh_canvas_spectrogram)
                except (RuntimeError, TypeError):
                    pass
        self._spectrogram_reference_audio = controller
        if controller is not None:
            signal = getattr(controller, "timeline_changed", None)
            if signal is not None:
                signal.connect(self._refresh_canvas_spectrogram)

    def _refresh_canvas_spectrogram(self, *_args) -> None:
        reference_audio = self._spectrogram_reference_audio
        has_audio = bool(
            reference_audio is not None
            and getattr(reference_audio, "audio_path", None)
        )
        self.canvas.set_spectrogram_source(
            reference_audio.audio_path if has_audio else None,
            duration_ms=(
                float(getattr(reference_audio, "duration_ms", 0.0) or 0.0)
                if has_audio
                else 0.0
            ),
            audio_offset_ms=(
                float(
                    getattr(
                        self.parent(),
                        "reference_audio_offset_ms",
                        getattr(reference_audio, "project_offset_ms", 0.0),
                    )
                    or 0.0
                )
                if reference_audio is not None
                else 0.0
            ),
        )

    def set_transcription_status(self, status: object) -> None:
        self.transcription_panel.set_status(status)

    def set_transcription_analysis_ui(
        self,
        busy: bool,
        progress: int | None = None,
        *,
        status: object | None = None,
        available: bool | None = None,
        unavailable_reason: object = "",
    ) -> None:
        if available is not None:
            self.transcription_panel.set_analysis_available(
                bool(available),
                unavailable_reason,
            )
        if status is not None:
            self.transcription_panel.set_status(status)
        self.transcription_panel.set_analysis_busy(busy, progress)
        self.draft_play_button.setEnabled(not bool(busy))

    def _load_reference_audio_from_editor(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is not None:
            reference_audio.choose_audio(self)

    def _unload_reference_audio_from_editor(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is not None:
            reference_audio.set_audio_path(None)

    def start_transcription_analysis(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        reference_audio = getattr(self.parent(), "reference_audio", None)
        audio_path = str(getattr(reference_audio, "audio_path", "") or "")
        if not audio_path:
            QMessageBox.warning(
                self,
                tr("无法开始扒谱"),
                tr("请先载入 MP3/WAV 参考音频"),
            )
            return
        if (
            self.track.is_percussion
            or int(self.track.bdo_instrument_id) == 0x0D
        ):
            QMessageBox.warning(
                self,
                tr("当前轨道不适合自动扒谱"),
                tr("Basic Pitch 不识别游戏鼓件映射；请在旋律乐器轨道中审阅候选"),
            )
            return
        retained_playhead = self.playhead_ms
        self.stop_draft()
        self.set_draft_playhead(retained_playhead)
        parent = self.parent()
        start_shared = getattr(
            parent,
            "_start_workspace_transcription_analysis",
            None,
        )
        if not callable(start_shared):
            QMessageBox.warning(
                self,
                tr("扒谱分析失败"),
                tr("主窗口扒谱会话不可用"),
            )
            return
        self.transcription_hint.setText(
            tr("正在使用主窗口扒谱会话分析；正式音符不会自动改变")
        )
        start_shared()

    def _transcription_annotation_projection(
        self,
        session,
        postprocess_report,
    ) -> tuple[dict[str, object], frozenset[str]]:
        """Return stable annotation/fragment projections for one evidence set."""

        session_annotations = session.annotations
        report_annotations = (
            tuple(postprocess_report.annotations)
            if postprocess_report is not None
            else ()
        )
        cached = self._transcription_annotation_projection_cache
        if (
            cached is not None
            and cached[0] is session
            and cached[1] is session_annotations
            and cached[2] is report_annotations
        ):
            return cached[3], cached[4]

        annotation_by_id = {
            item.candidate_id: item
            for item in session_annotations
        }
        annotation_by_id.update(
            {
                item.candidate_id: item
                for item in report_annotations
            }
        )
        fragment_ids = frozenset(
            candidate_id
            for candidate_id, annotation in annotation_by_id.items()
            if {
                "review_fragment",
                "pitch_flicker",
            }.intersection(annotation.flags)
        )
        self._transcription_annotation_projection_cache = (
            session,
            session_annotations,
            report_annotations,
            annotation_by_id,
            fragment_ids,
        )
        return annotation_by_id, fragment_ids

    def _transcription_display_projection(
        self,
        candidates: tuple[TranscriptionCandidate, ...],
        postprocess_report,
        *,
        show_suppressed: bool,
    ) -> tuple[
        tuple[TranscriptionCandidate, ...],
        frozenset[str],
    ]:
        """Return one identity-stable active/suppressed candidate projection."""

        suppressed_candidates = (
            tuple(postprocess_report.suppressed_candidates)
            if postprocess_report is not None and show_suppressed
            else ()
        )
        cached = self._transcription_display_projection_cache
        if (
            cached is not None
            and cached[0] is candidates
            and cached[1] is suppressed_candidates
            and cached[2] is bool(show_suppressed)
        ):
            return cached[3], cached[4]

        display_candidates = candidates + suppressed_candidates
        suppressed_ids = frozenset(
            candidate.candidate_id
            for candidate in suppressed_candidates
        )
        self._transcription_display_projection_cache = (
            candidates,
            suppressed_candidates,
            bool(show_suppressed),
            display_candidates,
            suppressed_ids,
        )
        return display_candidates, suppressed_ids

    def _sync_shared_transcription_projection(self) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return
        offset_ms = float(getattr(parent, "reference_audio_offset_ms", 0.0))
        self.transcription_candidates = tuple(session.candidates)
        self.transcription_result = getattr(
            parent,
            "transcription_result",
            None,
        )
        postprocess_report = (
            self.transcription_result.postprocess_report
            if self.transcription_result is not None
            else None
        )
        (
            display_candidates,
            suppressed_ids,
        ) = self._transcription_display_projection(
            self.transcription_candidates,
            postprocess_report,
            show_suppressed=(
                self.transcription_panel.show_suppressed_checkbox.isChecked()
            ),
        )
        _annotation_by_id, fragment_ids = (
            self._transcription_annotation_projection(
                session,
                postprocess_report,
            )
        )
        state = session.state
        tolerance = CANDIDATE_NOTE_POLICY.onset_tolerance_ms
        flag_cache_key = (
            id(session),
            id(self.transcription_candidates),
            int(self.canvas._note_index_revision),
            round(offset_ms, 6),
            int(self.track.bdo_instrument_id),
            int(self.transpose),
            round(tolerance, 6),
        )
        cached_flags = getattr(
            self,
            "_transcription_candidate_flag_cache",
            None,
        )
        if (
            cached_flags is not None
            and cached_flags[0] == flag_cache_key
        ):
            invalid_ids = cached_flags[1]
            duplicate_ids = cached_flags[2]
        else:
            invalid_values: set[str] = set()
            duplicate_values: set[str] = set()
            notes_by_pitch: dict[
                int,
                tuple[list[float], list[Note]],
            ] = {}
            grouped_notes: dict[int, list[Note]] = defaultdict(list)
            for note in self.canvas.notes:
                grouped_notes[int(note.pitch)].append(note)
            for pitch, notes in grouped_notes.items():
                ordered = sorted(notes, key=lambda note: float(note.start))
                notes_by_pitch[pitch] = (
                    [float(note.start) for note in ordered],
                    ordered,
                )
            for candidate in self.transcription_candidates:
                candidate_id = session.candidate_id(candidate)
                if self._candidate_invalid_for_current_track(candidate):
                    invalid_values.add(candidate_id)
                    continue
                starts, notes = notes_by_pitch.get(
                    int(candidate.pitch),
                    ([], []),
                )
                window_start, window_end = (
                    CANDIDATE_NOTE_POLICY.match_window(
                        candidate,
                        offset_ms,
                    )
                )
                first = bisect_left(starts, window_start)
                last = bisect_right(starts, window_end)
                if any(
                    CANDIDATE_NOTE_POLICY.matches_note(
                        candidate,
                        note,
                        offset_ms,
                    )
                    for note in notes[first:last]
                ):
                    duplicate_values.add(candidate_id)
            invalid_ids = frozenset(invalid_values)
            duplicate_ids = frozenset(duplicate_values)
            self._transcription_candidate_flag_cache = (
                flag_cache_key,
                invalid_ids,
                duplicate_ids,
            )

        staged_ids = {
            route.candidate_id
            for route in (*self.staged_primary_routes, *self.staged_copy_routes)
        }
        confidence_floor = self.transcription_panel.confidence_floor
        self.canvas.set_transcription_review(
            display_candidates,
            session.candidate_id,
            selected_ids=state.selected_candidate_ids,
            rejected_ids=state.rejected_candidate_ids,
            pending_routes=state.pending_routes,
            applied_routes=state.applied_routes,
            invalid_ids=invalid_ids,
            duplicate_ids=duplicate_ids,
            staged_ids=staged_ids,
            fragment_ids=fragment_ids,
            suppressed_ids=suppressed_ids,
            confidence_floor=confidence_floor,
            show_rejected_only=(
                self.transcription_panel.show_rejected_checkbox.isChecked()
            ),
            audio_offset_ms=offset_ms,
            visible=self.transcription_mode_enabled,
        )
        descriptor = (
            self.transcription_result.evidence_descriptor
            if self.transcription_result is not None
            else None
        )
        descriptor_key = str(getattr(descriptor, "cache_key", "") or "")
        if descriptor_key != getattr(self, "_canvas_evidence_cache_key", ""):
            self.canvas.set_evidence_descriptor(
                descriptor,
                audio_offset_ms=offset_ms,
            )
            self._canvas_evidence_cache_key = descriptor_key
        self._transcription_evidence_layers_changed(
            self.transcription_panel.visible_evidence_layers
        )

        reference_audio = getattr(parent, "reference_audio", None)
        has_audio = bool(
            reference_audio is not None and reference_audio.audio_path
        )
        self._bind_spectrogram_reference_audio(reference_audio)
        self._refresh_canvas_spectrogram()
        self.canvas.set_spectrogram_visible(
            self.transcription_panel.spectrogram_visible
        )
        self.canvas.set_melody_lines_visible(
            self.transcription_panel.melody_lines_visible
        )
        self.transcription_panel.set_audio_loaded(
            has_audio,
            display_name=(
                str(
                    getattr(
                        reference_audio,
                        "display_name",
                        Path(str(reference_audio.audio_path)).name,
                    )
                )
                if has_audio
                else ""
            ),
        )
        self.transcription_panel.set_melody_lines_available(
            self.canvas.melody_lines_available
        )
        self.transcription_panel.set_sensitivity(state.sensitivity)
        self.transcription_panel.set_analysis_mode(state.analysis_mode)
        self.transcription_panel.set_cleanup_profile(
            state.cleanup_profile
        )
        self.transcription_panel.set_range_available(state.region is not None)
        self.transcription_panel.set_staging_locked(
            self._has_transcription_staging()
        )
        available, reason = transcription_backend_quick_status()
        self.transcription_panel.set_analysis_available(available, reason)
        action_ids = set(self._eligible_transcription_candidate_ids())
        current_track_id = int(self.track.track_id)
        applied_elsewhere_ids = {
            route.candidate_id
            for route in state.applied_routes
            if int(route.track_id) != current_track_id
        }
        current_route_ids = {
            route.candidate_id
            for route in (*state.pending_routes, *state.applied_routes)
            if int(route.track_id) == current_track_id
        }
        include_current_copy = bool(
            action_ids.intersection(
                applied_elsewhere_ids.difference(current_route_ids)
            )
        )
        self.transcription_panel.set_copy_targets(
            getattr(parent, "tracks", ()),
            current_track_id=current_track_id,
            include_current=include_current_copy,
        )
        self.transcription_waveform.set_reference_audio(reference_audio)
        self.transcription_waveform.set_audio_offset_ms(offset_ms)
        self.transcription_waveform.set_time_range(state.region)
        self.transcription_waveform.set_playhead_ms(self.playhead_ms)
        harmony = getattr(parent, "harmony_analysis", None)
        instrument_analysis = getattr(
            parent, "instrument_match_analysis", None
        )
        groups = (
            tuple(instrument_analysis.groups)
            if instrument_analysis is not None
            else ()
        )
        matches_by_group = (
            dict(instrument_analysis.matches)
            if instrument_analysis is not None
            else {}
        )
        parent_config = getattr(parent, "config", {})
        transcription_ui_config = (
            parent_config.get("transcription_ui", {})
            if isinstance(parent_config, dict)
            and isinstance(
                parent_config.get("transcription_ui", {}), dict
            )
            else {}
        )
        voice_group_colors = transcription_ui_config.get(
            "voice_group_colors", {}
        )
        if not isinstance(voice_group_colors, dict):
            voice_group_colors = {}
        self.canvas.set_transcription_assist_projection(
            voice_groups=groups,
            harmony_analysis=harmony,
            group_colors=voice_group_colors,
        )
        assist_review = getattr(
            parent, "transcription_assist_review", None
        )
        confirmed_by_group = {
            str(item.group_id): int(item.confirmed_instrument_id)
            for item in (
                assist_review.active_voice_groups
                if assist_review is not None
                else ()
            )
            if item.confirmed_instrument_id is not None
        }
        key_review = (
            getattr(assist_review, "active_key_override", None)
            if assist_review is not None
            else None
        )
        harmony_panel_view = (
            {
                "global_key": harmony.global_key,
                "chord_segments": harmony.chord_segments,
                "conflicts": harmony.conflicts,
                "key_locked": bool(
                    key_review is not None and key_review.locked
                ),
            }
            if harmony is not None
            else None
        )
        self.transcription_panel.set_harmony_analysis(
            harmony_panel_view
        )
        active_group = (
            parent._active_voice_group()
            if instrument_analysis is not None
            and hasattr(parent, "_active_voice_group")
            else None
        )
        if active_group is not None:
            parent.active_voice_group_id = active_group.group_id
            matches = matches_by_group.get(active_group.group_id, ())
            match_views = []
            for match in matches:
                reasons = [
                    trfv(
                        "音域覆盖 {coverage}%",
                        coverage=round(match.pitch_coverage * 100),
                    ),
                    trfv(
                        "角色适配 {score}%",
                        score=round(match.role_score * 100),
                    ),
                ]
                warnings = []
                if match.pitch_coverage < 0.999:
                    warnings.append(
                        trfv(
                            "有 {percent}% 的候选超出该乐器可用音域",
                            percent=round(
                                (1.0 - match.pitch_coverage) * 100
                            ),
                        )
                    )
                if match.role_score < 0.50:
                    warnings.append(trv("该乐器与当前声部角色适配较弱"))
                if match.timbre_score is None:
                    warnings.append(trv("无本地音色证据"))
                    reasons.append(trv("按音域、角色和奏法排序"))
                else:
                    reasons.append(
                        trfv(
                            "本地音色相似 {score}%",
                            score=round(match.timbre_score * 100),
                        )
                    )
                match_views.append(
                    {
                        "instrument_id": match.instrument_id,
                        "instrument_name": trv(_ui_bdo_instrument_source(
                            match.instrument_id,
                        )),
                        "total_score": match.total_score,
                        "pitch_coverage": match.pitch_coverage,
                        "reasons": tuple(reasons),
                        "warnings": tuple(warnings),
                    }
                )
            self.transcription_panel.set_voice_group_matches(
                active_group,
                match_views,
                confirmed_instrument_id=confirmed_by_group.get(
                    active_group.group_id
                ),
            )
            group_index = next(
                (
                    index
                    for index, group in enumerate(groups)
                    if group.group_id == active_group.group_id
                ),
                -1,
            )
        else:
            self.transcription_panel.clear_voice_group_matches()
            group_index = -1
        low_harmony_count = (
            sum(
                segment.quality != "N"
                and float(segment.confidence) < 0.55
                for segment in harmony.chord_segments
            )
            + len(harmony.conflicts)
            if harmony is not None
            else 0
        )
        uncertain_instrument_count = (
            sum(
                (
                    group.group_id not in confirmed_by_group
                    or confirmed_by_group[group.group_id]
                    not in {
                        match.instrument_id
                        for match in matches_by_group.get(
                            group.group_id, ()
                        )
                    }
                )
                and (
                    not matches_by_group.get(group.group_id)
                    or matches_by_group[
                        group.group_id
                    ][0].timbre_score is None
                )
                for group in groups
            )
            if instrument_analysis is not None
            else 0
        )
        track_lookup = {
            int(track.track_id): track
            for track in getattr(parent, "tracks", ())
        }
        pending_problem_count = 0
        for route in state.pending_routes:
            candidate = session.candidate_for_id(route.candidate_id)
            target = track_lookup.get(int(route.track_id))
            if (
                candidate is None
                or target is None
                or parent._candidate_invalid_for_track(candidate, target)
            ):
                pending_problem_count += 1
        folded_duplicate_count = len(
            self.canvas._folded_candidate_primary
        )
        active_fragment_ids = {
            candidate_id
            for candidate_id in fragment_ids
            if session.candidate_for_id(candidate_id) is not None
        }
        review_count = (
            pending_problem_count
            + len(invalid_ids)
            + len(duplicate_ids)
            + folded_duplicate_count
            + len(active_fragment_ids)
            + low_harmony_count
            + uncertain_instrument_count
        )
        self.transcription_panel.set_phrase_state(
            index=group_index,
            total=len(groups),
            loop_enabled=bool(
                getattr(parent, "loop_current_voice_group", False)
            ),
            review_count=review_count,
        )
        self.transcription_panel.set_assist_available(
            harmony is not None or bool(groups)
        )
        self.transcription_panel.set_fragment_state(
            suspected_count=len(active_fragment_ids),
        )

        routable_ids = action_ids.difference(invalid_ids, duplicate_ids)
        applied_ids = {
            route.candidate_id for route in state.applied_routes
        }
        primary_ids = routable_ids.difference(applied_ids)
        copy_targets = [
            track
            for track in getattr(parent, "tracks", ())
            if (
                int(track.track_id) != current_track_id
                or include_current_copy
            )
            and not track.is_percussion
            and int(track.bdo_instrument_id) != 0x0D
        ]
        self.transcription_panel.set_action_state(
            write_enabled=bool(primary_ids)
            and not bool(
                getattr(parent, "transcription_analysis_busy", False)
            ),
            copy_enabled=bool(routable_ids and copy_targets)
            and not bool(
                getattr(parent, "transcription_analysis_busy", False)
            ),
            reject_enabled=bool(action_ids)
            and not bool(
                getattr(parent, "transcription_analysis_busy", False)
            ),
            rejected_count=len(state.rejected_candidate_ids),
            can_undo=bool(
                getattr(
                    parent,
                    "_can_undo_transcription_review",
                    lambda: session.commands.can_undo,
                )()
            ),
            can_redo=bool(
                getattr(
                    parent,
                    "_can_redo_transcription_review",
                    lambda: session.commands.can_redo,
                )()
            ),
            staging_count=len(
                set((*self.staged_primary_routes, *self.staged_copy_routes))
            ),
        )
        if self.transcription_candidates:
            merged_count = (
                postprocess_report.automatic_merge_count
                if postprocess_report is not None
                else 0
            )
            suppressed_count = (
                postprocess_report.suppressed_count
                if postprocess_report is not None
                else 0
            )
            profile_label, profile_state = (
                _transcription_cleanup_ui_labels(
                    state.cleanup_profile,
                    postprocess_report,
                )
            )
            self.transcription_panel.set_status(
                trf(
                    "{profile} · {profile_state} · "
                    "{count} 个候选 · 自动合并 {merged} · "
                    "疑似碎音 {suspected} · 已隐藏 {suppressed}",
                    profile=profile_label,
                    profile_state=profile_state,
                    count=len(self.transcription_candidates),
                    merged=merged_count,
                    suspected=len(active_fragment_ids),
                    suppressed=suppressed_count,
                )
            )
        elif has_audio:
            self.transcription_panel.set_status(tr("尚未分析"))
            self.transcription_panel.set_fragment_state()
        else:
            self.transcription_panel.set_status(
                tr("载入参考音频后可开始整首分析")
            )
            self.transcription_panel.set_fragment_state()
        self.update_scrollbars()

    def _eligible_transcription_candidate_ids(
        self, *, include_routed: bool = False
    ) -> tuple[str, ...]:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return ()
        state = session.state
        offset_ms = float(
            getattr(parent, "reference_audio_offset_ms", 0.0)
        )
        cache_key = (
            id(session),
            id(session.candidates),
            state.selected_candidate_ids,
            state.rejected_candidate_ids,
            state.region,
            () if include_routed else state.pending_routes,
            () if include_routed else state.applied_routes,
            round(offset_ms, 6),
            bool(include_routed),
        )
        cached = self._eligible_candidate_cache
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        if state.selected_candidate_ids:
            requested = state.selected_candidate_ids.difference(
                state.rejected_candidate_ids
            )
            selected: list[
                tuple[float, int, float, str]
            ] = []
            for candidate_id in requested:
                candidate = session.candidate_for_id(candidate_id)
                if candidate is None:
                    continue
                selected.append(
                    (
                        float(candidate.start_ms),
                        int(candidate.pitch),
                        float(candidate.duration_ms),
                        str(candidate_id),
                    )
                )
            selected.sort()
            result = tuple(item[3] for item in selected)
            self._eligible_candidate_cache = (cache_key, result)
            return result
        if state.region is None:
            self._eligible_candidate_cache = (cache_key, ())
            return ()
        routed = {
            route.candidate_id
            for route in (*state.pending_routes, *state.applied_routes)
        }
        start_ms, end_ms = state.region
        values: list[str] = []
        audio_start = float(start_ms) - offset_ms
        audio_end = float(end_ms) - offset_ms
        first = bisect_left(
            self.canvas._candidate_starts,
            audio_start,
        )
        last = bisect_left(
            self.canvas._candidate_starts,
            audio_end,
        )
        for index in range(first, last):
            candidate = self.canvas.transcription_candidates[index]
            candidate_id = self.canvas._transcription_candidate_ids[index]
            if candidate_id in state.rejected_candidate_ids:
                continue
            if not include_routed and candidate_id in routed:
                continue
            values.append(candidate_id)
        result = tuple(values)
        self._eligible_candidate_cache = (cache_key, result)
        return result

    def _cancel_transcription_analysis(self) -> None:
        worker = getattr(
            self.parent(),
            "workspace_transcription_worker",
            None,
        )
        if worker is None or not worker.isRunning():
            return
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()
        self.transcription_panel.set_status(tr("正在取消…"))
        self.transcription_panel.set_analysis_busy(True)

    def _candidate_invalid_for_current_track(
        self,
        candidate: TranscriptionCandidate,
    ) -> bool:
        parent = self.parent()
        if not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
            candidate,
            float(getattr(parent, "reference_audio_offset_ms", 0.0)),
        ):
            return True
        supported = game_supported_pitches(
            int(self.track.bdo_instrument_id),
            self.track.marnian_synth_mode,
        )
        return not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
            candidate.pitch,
            is_percussion=self.track.is_percussion,
            instrument_id=self.track.bdo_instrument_id,
            transpose=self.transpose,
            supported_pitches=supported,
        )

    def accept_transcription_candidates(self) -> None:
        if not self.transcription_candidates:
            return
        parent = self.parent()
        shared_session = getattr(parent, "transcription_session", None)
        if shared_session is None:
            return
        eligible_ids = set(self._eligible_transcription_candidate_ids())
        if not eligible_ids:
            self.transcription_hint.setText(
                tr("请先选择候选或设置 A–B 区间")
            )
            return
        accepted: list = []
        accepted_routes: set[CandidateRoute] = set()
        invalid = 0
        duplicates = 0
        notes_by_pitch: dict[int, tuple[list[float], list[Note]]] = {}
        grouped_notes: dict[int, list[Note]] = defaultdict(list)
        for note in self.canvas.notes:
            grouped_notes[int(note.pitch)].append(note)
        for pitch, notes in grouped_notes.items():
            ordered = sorted(notes, key=lambda note: float(note.start))
            notes_by_pitch[pitch] = (
                [float(note.start) for note in ordered],
                ordered,
            )
        already_applied = {
            route.candidate_id
            for route in shared_session.state.applied_routes
        }
        offset_ms = float(getattr(parent, "reference_audio_offset_ms", 0.0))
        for candidate in self.transcription_candidates:
            candidate_id = shared_session.candidate_id(candidate)
            if candidate_id not in eligible_ids:
                continue
            if candidate_id in already_applied:
                continue
            if self._candidate_invalid_for_current_track(candidate):
                invalid += 1
                continue
            starts, indexed_notes = notes_by_pitch.setdefault(
                int(candidate.pitch),
                ([], []),
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            if any(
                CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    note,
                    offset_ms,
                )
                for note in indexed_notes[first:last]
            ):
                duplicates += 1
                continue
            accepted_note = CANDIDATE_NOTE_POLICY.to_note(
                candidate,
                offset_ms,
            )
            accepted.append(accepted_note)
            insertion = bisect_right(starts, float(accepted_note.start))
            starts.insert(insertion, float(accepted_note.start))
            indexed_notes.insert(insertion, accepted_note)
            accepted_routes.add(
                CandidateRoute(candidate_id, int(self.track.track_id))
            )
        if not accepted:
            self.transcription_hint.setText(trf(
                "没有可写入候选 · 重复 {duplicates} · 越界 {invalid}",
                duplicates=duplicates,
                invalid=invalid,
            ))
            return
        self.push_snapshot()
        first = len(self.canvas.notes)
        self.canvas.notes.extend(accepted)
        self.staged_primary_routes.update(accepted_routes)
        self._capture_staging_identity()
        self.canvas.selected = set(range(first, len(self.canvas.notes)))
        self.canvas.anchor_index = first
        self._notes_changed()
        self.refresh_fields()
        self.transcription_hint.setText(trf(
            "已写入草稿 {accepted} 个 · 跳过重复 {duplicates} · 越界 {invalid}",
            accepted=len(accepted),
            duplicates=duplicates,
            invalid=invalid,
        ))
        self._sync_shared_transcription_projection()

    def _stage_transcription_copy(
        self,
        track_id: int,
        candidate_ids_override: Iterable[str] | None = None,
    ) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return
        target = next(
            (
                track
                for track in getattr(parent, "tracks", ())
                if int(track.track_id) == int(track_id)
            ),
            None,
        )
        if (
            target is None
            or target.is_percussion
            or int(target.bdo_instrument_id) == 0x0D
        ):
            self.transcription_panel.set_status(tr("目标轨道不可用"))
            return
        candidate_ids = (
            {
                str(candidate_id)
                for candidate_id in candidate_ids_override
            }
            if candidate_ids_override is not None
            else set(
                self._eligible_transcription_candidate_ids(
                    include_routed=True
                )
            )
        )
        # Voice-group/Top-3 actions pass an explicit candidate override and
        # therefore do not travel through the selected/A-B eligibility helper.
        # Keep rejection as an independent hard gate at the staging boundary.
        candidate_ids.difference_update(
            session.state.rejected_candidate_ids
        )
        if not candidate_ids:
            self.transcription_panel.set_status(
                tr("请先选择候选或设置 A–B 区间")
            )
            return
        supported = game_supported_pitches(
            int(target.bdo_instrument_id), target.marnian_synth_mode
        )
        routes: set[CandidateRoute] = set()
        candidates_by_id: dict[str, TranscriptionCandidate] = {}
        already_routed = set(
            (*session.state.pending_routes, *session.state.applied_routes)
        )
        for candidate in session.candidates:
            candidate_id = session.candidate_id(candidate)
            if candidate_id not in candidate_ids:
                continue
            invalid = (
                not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                    candidate,
                    float(
                        getattr(
                            parent,
                            "reference_audio_offset_ms",
                            0.0,
                        )
                    ),
                )
                or not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
                    candidate.pitch,
                    is_percussion=target.is_percussion,
                    instrument_id=target.bdo_instrument_id,
                    transpose=self.transpose,
                    supported_pitches=supported,
                )
            )
            if not invalid:
                route = CandidateRoute(candidate_id, int(track_id))
                if route not in already_routed:
                    routes.add(route)
                    candidates_by_id[candidate_id] = candidate
        routes.difference_update(self.staged_copy_routes)
        if not routes:
            self.transcription_panel.set_status(tr("没有可复制的候选"))
            return
        self.push_snapshot()
        first = len(self.canvas.notes)
        if int(track_id) == int(self.track.track_id):
            offset_ms = float(
                getattr(parent, "reference_audio_offset_ms", 0.0)
            )
            additions: list[Note] = []
            notes_by_pitch: dict[
                int,
                tuple[list[float], list[Note]],
            ] = {}
            grouped_notes: dict[int, list[Note]] = defaultdict(list)
            for note in self.canvas.notes:
                grouped_notes[int(note.pitch)].append(note)
            for pitch, notes in grouped_notes.items():
                ordered = sorted(
                    notes,
                    key=lambda note: float(note.start),
                )
                notes_by_pitch[pitch] = (
                    [float(note.start) for note in ordered],
                    ordered,
                )
            for route in sorted(routes):
                candidate = candidates_by_id[route.candidate_id]
                starts, indexed_notes = notes_by_pitch.setdefault(
                    int(candidate.pitch),
                    ([], []),
                )
                window_start, window_end = (
                    CANDIDATE_NOTE_POLICY.match_window(
                        candidate,
                        offset_ms,
                    )
                )
                first = bisect_left(starts, window_start)
                last = bisect_right(starts, window_end)
                if any(
                    CANDIDATE_NOTE_POLICY.matches_note(
                        candidate,
                        note,
                        offset_ms,
                    )
                    for note in indexed_notes[first:last]
                ):
                    continue
                addition = CANDIDATE_NOTE_POLICY.to_note(
                    candidate,
                    offset_ms,
                )
                additions.append(addition)
                insertion = bisect_right(
                    starts,
                    float(addition.start),
                )
                starts.insert(insertion, float(addition.start))
                indexed_notes.insert(insertion, addition)
            self.canvas.notes.extend(additions)
        self.staged_copy_routes.update(routes)
        self._capture_staging_identity()
        if len(self.canvas.notes) > first:
            self.canvas.selected = set(range(first, len(self.canvas.notes)))
            self.canvas.anchor_index = first
            self._notes_changed()
        self.transcription_panel.set_status(
            trf("已暂存 {count} 个候选", count=len(routes))
        )
        self._sync_shared_transcription_projection()

    def _voice_group_candidate_ids(
        self, group_id: str
    ) -> tuple[str, ...]:
        analysis = getattr(
            self.parent(), "instrument_match_analysis", None
        )
        if analysis is None:
            return ()
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        return () if group is None else tuple(group.candidate_ids)

    def _stage_voice_group_routes(
        self, group_id: str, track_id: int
    ) -> None:
        candidate_ids = self._voice_group_candidate_ids(group_id)
        if not candidate_ids:
            self.transcription_panel.set_status(tr("声部已失效"))
            return
        self._stage_transcription_copy(
            int(track_id),
            candidate_ids_override=candidate_ids,
        )

    def _stage_new_voice_group_track(
        self, group_id: str, instrument_id: int
    ) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        candidate_ids = set(self._voice_group_candidate_ids(group_id))
        if session is None or not candidate_ids:
            self.transcription_panel.set_status(tr("声部已失效"))
            return
        candidate_ids.difference_update(
            session.state.rejected_candidate_ids
        )
        if not candidate_ids:
            self.transcription_panel.set_status(tr("没有可复制的候选"))
            return
        if (
            int(instrument_id) not in BDO_INSTRUMENT_NAMES
            or int(instrument_id) in {0x04, 0x05, 0x0D}
        ):
            self.transcription_panel.set_status(tr("目标轨道不可用"))
            return
        reserved_ids = {
            int(track.track_id) for track in getattr(parent, "tracks", ())
        }.union(
            int(route.track_id)
            for route in (
                *session.state.pending_routes,
                *session.state.applied_routes,
                *self.staged_primary_routes,
                *self.staged_copy_routes,
            )
        ).union(self.staged_new_track_specs)
        new_track_id = max(reserved_ids, default=-1) + 1
        supported = game_supported_pitches(int(instrument_id))
        routes = {
            CandidateRoute(session.candidate_id(candidate), new_track_id)
            for candidate in session.candidates
            if session.candidate_id(candidate) in candidate_ids
            and CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                candidate,
                float(
                    getattr(
                        parent,
                        "reference_audio_offset_ms",
                        0.0,
                    )
                ),
            )
            and CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
                candidate.pitch,
                is_percussion=False,
                instrument_id=int(instrument_id),
                transpose=self.transpose,
                supported_pitches=supported,
            )
        }
        if not routes:
            self.transcription_panel.set_status(
                tr("该乐器音域内没有可暂存候选")
            )
            return
        self.push_snapshot()
        self.staged_new_track_specs[new_track_id] = int(instrument_id)
        self.staged_copy_routes.update(routes)
        self._capture_staging_identity()
        self.transcription_panel.set_status(
            trf(
                "已暂存新轨 · {instrument} · {count} 个候选",
                instrument=trv(_ui_bdo_instrument_source(int(instrument_id))),
                count=len(routes),
            )
        )
        self._sync_shared_transcription_projection()

    def _clear_transcription_staging(self) -> None:
        if not self._has_transcription_staging():
            return
        self.push_snapshot()
        self.staged_primary_routes.clear()
        self.staged_copy_routes.clear()
        self.staged_new_track_specs.clear()
        self._clear_staging_identity_if_empty()
        self.transcription_panel.set_status(
            tr("已清除本次暂存；草稿音符保留为手工编辑")
        )
        self._sync_shared_transcription_projection()

    def _transcription_selection_changed(self, candidate_ids) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return
        session.set_selection(candidate_ids)
        activate = getattr(
            parent, "_activate_voice_group_for_candidates", None
        )
        if callable(activate):
            activate(candidate_ids)
        autosave = getattr(parent, "_autosave_project", None)
        if callable(autosave):
            autosave("transcription selection")
        self._sync_shared_transcription_projection()

    def _transcription_range_changed(self, value) -> None:
        parent = self.parent()
        setter = getattr(parent, "_set_transcription_region", None)
        if callable(setter):
            setter(value)
        self._sync_shared_transcription_projection()

    def _clear_transcription_range(self) -> None:
        self._transcription_range_changed(None)

    def _update_reference_layer_settings(self, **updates: object) -> None:
        parent = self.parent()
        if parent is None:
            return
        previous = normalize_reference_layer_settings(
            getattr(parent, "reference_layer_settings", None)
        )
        merged = dict(previous)
        merged.update(updates)
        normalized = normalize_reference_layer_settings(merged)
        if normalized == previous:
            return
        parent.reference_layer_settings = normalized
        autosave = getattr(parent, "_autosave_project", None)
        if callable(autosave) and not bool(
            getattr(parent, "loading_project", False)
        ):
            autosave("reference layers")

    def _transcription_evidence_layers_changed(self, layers) -> None:
        visible = {str(layer) for layer in layers}
        self.canvas.set_evidence_layers(
            frame="frame" in visible,
            onset="onset" in visible,
            contour="contour" in visible,
        )
        self._update_reference_layer_settings(
            frame_visible="frame" in visible,
            onset_visible="onset" in visible,
            contour_visible="contour" in visible,
        )
        parent = self.parent()
        parent_config = getattr(parent, "config", None)
        if isinstance(parent_config, dict):
            ui_config = parent_config.setdefault("transcription_ui", {})
            if isinstance(ui_config, dict):
                ui_config["diagnostic_evidence_layers"] = sorted(visible)
                save_config(parent_config)

    def _transcription_spectrogram_visibility_changed(
        self,
        visible: bool,
    ) -> None:
        self.canvas.set_spectrogram_visible(bool(visible))
        self._update_reference_layer_settings(
            spectrogram_visible=bool(visible)
        )

    def _transcription_melody_lines_visibility_changed(
        self,
        visible: bool,
    ) -> None:
        self.canvas.set_melody_lines_visible(bool(visible))
        self._update_reference_layer_settings(
            melody_lines_visible=bool(visible)
        )

    def _transcription_reference_background_opacity_changed(
        self,
        opacity: float,
    ) -> None:
        normalized = max(0.0, min(1.0, float(opacity)))
        self.canvas.set_reference_background_opacity(normalized)
        self._update_reference_layer_settings(
            background_opacity_percent=round(normalized * 100.0)
        )

    def _transcription_melody_line_roles_changed(
        self,
        roles: object,
    ) -> None:
        normalized = (
            frozenset(str(role) for role in roles)
            if isinstance(roles, (set, frozenset, list, tuple))
            else frozenset()
        )
        self.canvas.set_melody_line_roles_visible(normalized)
        parent = self.parent()
        parent_config = getattr(parent, "config", None)
        if not isinstance(parent_config, dict):
            return
        ui_config = parent_config.setdefault("transcription_ui", {})
        if isinstance(ui_config, dict):
            ui_config["melody_line_roles"] = sorted(
                self.canvas.melody_line_roles_visible
            )
            save_config(parent_config)

    def _transcription_diagnostic_visibility_changed(
        self, expanded: bool
    ) -> None:
        parent = self.parent()
        parent_config = getattr(parent, "config", None)
        if not isinstance(parent_config, dict):
            return
        ui_config = parent_config.setdefault("transcription_ui", {})
        if isinstance(ui_config, dict):
            ui_config["diagnostic_evidence_expanded"] = bool(expanded)
            save_config(parent_config)

    @staticmethod
    def _pitch_class_label(root_pc: int | None) -> str:
        if root_pc is None:
            return "N"
        return (
            "C",
            "C♯",
            "D",
            "D♯",
            "E",
            "F",
            "F♯",
            "G",
            "G♯",
            "A",
            "A♯",
            "B",
        )[int(root_pc) % 12]

    def _edit_transcription_key(self, _current: object) -> None:
        parent = self.parent()
        harmony = getattr(parent, "harmony_analysis", None)
        if harmony is None:
            return
        options: list[tuple[str, int, str]] = []
        candidates = (
            harmony.global_key,
            *tuple(harmony.global_key.alternatives),
        )
        seen: set[tuple[int, str]] = set()
        for item in candidates:
            if item.root_pc is None or item.mode is None:
                continue
            identity = (int(item.root_pc), str(item.mode))
            if identity in seen:
                continue
            seen.add(identity)
            options.append(
                (
                    f"{self._pitch_class_label(identity[0])} {identity[1]}",
                    identity[0],
                    identity[1],
                )
            )
        for mode in ("major", "minor"):
            for root_pc in range(12):
                identity = (root_pc, mode)
                if identity not in seen:
                    options.append(
                        (
                            f"{self._pitch_class_label(root_pc)} {mode}",
                            root_pc,
                            mode,
                        )
                    )
        selected, accepted = QInputDialog.getItem(
            self,
            tr("编辑主调"),
            tr("选择或输入主调："),
            [item[0] for item in options],
            0,
            True,
        )
        if not accepted:
            return
        normalized = str(selected).strip().replace("#", "♯")
        match = next(
            (item for item in options if item[0] == normalized),
            None,
        )
        if match is None:
            parts = normalized.split()
            roots = {
                self._pitch_class_label(root_pc).casefold(): root_pc
                for root_pc in range(12)
            }
            if len(parts) != 2 or parts[0].casefold() not in roots:
                QMessageBox.warning(
                    self,
                    tr("无法识别主调"),
                    tr("请输入例如 C major 或 A minor。"),
                )
                return
            mode = parts[1].casefold()
            if mode not in {"major", "minor"}:
                QMessageBox.warning(
                    self,
                    tr("无法识别主调"),
                    tr("仅支持 major 或 minor。"),
                )
                return
            match = (normalized, roots[parts[0].casefold()], mode)
        parent._set_assist_key_override(
            match[1],
            match[2],
            manual=True,
            locked=self.transcription_panel.assist_panel.harmony_summary.key_lock_checkbox.isChecked(),
        )

    def _lock_transcription_key(self, locked: bool) -> None:
        parent = self.parent()
        harmony = getattr(parent, "harmony_analysis", None)
        if harmony is None or harmony.global_key.root_pc is None:
            return
        current_review = parent.transcription_assist_review.key_override
        if not locked and (
            current_review is None or not current_review.manual
        ):
            parent._clear_assist_key_override()
            return
        parent._set_assist_key_override(
            harmony.global_key.root_pc,
            harmony.global_key.mode,
            manual=bool(
                current_review is not None and current_review.manual
            ),
            locked=bool(locked),
        )

    def _harmony_segment(self, segment_id: str) -> ChordSegment | None:
        harmony = getattr(self.parent(), "harmony_analysis", None)
        if harmony is None:
            return None
        return next(
            (
                segment
                for segment in harmony.chord_segments
                if segment.segment_id == str(segment_id)
            ),
            None,
        )

    def _review_for_harmony_segment(
        self, segment: ChordSegment
    ) -> LockedChordReview | None:
        return next(
            (
                item
                for item in self.parent().transcription_assist_review.locked_chord_segments
                if item.segment_id == segment.segment_id
                or (
                    math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
            ),
            None,
        )

    def _transcription_chord_segment_clicked(
        self, segment_id: str
    ) -> None:
        self.transcription_panel.set_assist_expanded(True)
        self.transcription_panel.assist_panel.harmony_summary.set_current_segment(
            segment_id
        )

    def _split_transcription_voice_group(
        self, group_id: str, project_ms: float
    ) -> None:
        callback = getattr(
            self.parent(), "_split_transcription_voice_group", None
        )
        if callable(callback):
            callback(str(group_id), float(project_ms))

    def _merge_transcription_voice_groups(
        self, first_group_id: str, second_group_id: str
    ) -> None:
        callback = getattr(
            self.parent(), "_merge_transcription_voice_groups", None
        )
        if callable(callback):
            callback(str(first_group_id), str(second_group_id))

    def _set_transcription_voice_group_color(
        self, group_id: str, color: str
    ) -> None:
        callback = getattr(
            self.parent(), "_set_transcription_voice_group_color", None
        )
        if callable(callback):
            callback(str(group_id), str(color))

    def _set_transcription_voice_group_role(
        self, group_id: str, role: str
    ) -> None:
        callback = getattr(
            self.parent(), "_set_transcription_voice_group_role", None
        )
        if callable(callback):
            callback(str(group_id), str(role))

    def _edit_transcription_chord(self, segment_id: str) -> None:
        segment = self._harmony_segment(segment_id)
        if segment is None:
            return
        qualities = (
            "major",
            "minor",
            "dim",
            "sus2",
            "sus4",
            "maj7",
            "7",
            "min7",
            "half_diminished7",
        )
        options = ["N"] + [
            f"{self._pitch_class_label(root_pc)} {quality}"
            for root_pc in range(12)
            for quality in qualities
        ]
        current = (
            "N"
            if segment.quality == "N" or segment.root_pc is None
            else (
                f"{self._pitch_class_label(segment.root_pc)} "
                f"{segment.quality}"
            )
        )
        selected, accepted = QInputDialog.getItem(
            self,
            tr("编辑和弦段"),
            tr("选择和弦；不会自动改动音符："),
            options,
            max(0, options.index(current) if current in options else 0),
            False,
        )
        if not accepted:
            return
        if selected == "N":
            root_pc, quality, bass_pc = None, "N", None
        else:
            root_label, quality = str(selected).split(" ", 1)
            root_pc = next(
                index
                for index in range(12)
                if self._pitch_class_label(index) == root_label
            )
            bass_labels = [
                self._pitch_class_label(index) for index in range(12)
            ]
            bass_label, bass_ok = QInputDialog.getItem(
                self,
                tr("选择低音"),
                tr("选择转位低音："),
                bass_labels,
                root_pc,
                False,
            )
            if not bass_ok:
                return
            bass_pc = bass_labels.index(str(bass_label))
        self.parent()._set_assist_chord_review(
            segment,
            root_pc=root_pc,
            quality=quality,
            bass_pc=bass_pc,
            manual=True,
            locked=self.transcription_panel.assist_panel.harmony_summary.chord_lock_checkbox.isChecked(),
        )

    def _lock_transcription_chord(
        self, segment_id: str, locked: bool
    ) -> None:
        segment = self._harmony_segment(segment_id)
        if segment is None:
            return
        current_review = self._review_for_harmony_segment(segment)
        if not locked and (
            current_review is None or not current_review.manual
        ):
            self.parent()._remove_assist_chord_review(segment.segment_id)
            return
        self.parent()._set_assist_chord_review(
            segment,
            manual=bool(
                current_review is not None and current_review.manual
            ),
            locked=bool(locked),
        )

    def _split_transcription_chord(self, segment_id: str) -> None:
        segment = self._harmony_segment(segment_id)
        if segment is None:
            return
        callback = getattr(
            self.parent(), "_split_transcription_chord_segment", None
        )
        if callable(callback):
            callback(segment.segment_id, float(self.playhead_ms))

    def _merge_transcription_chord_with_next(
        self, segment_id: str
    ) -> None:
        harmony = getattr(self.parent(), "harmony_analysis", None)
        if harmony is None:
            return
        segments = tuple(harmony.chord_segments)
        index = next(
            (
                index
                for index, segment in enumerate(segments)
                if segment.segment_id == str(segment_id)
            ),
            -1,
        )
        if index < 0 or index + 1 >= len(segments):
            return
        first = segments[index]
        second = segments[index + 1]

        def label(segment: ChordSegment) -> str:
            if segment.root_pc is None or segment.quality == "N":
                return "N"
            return (
                f"{self._pitch_class_label(segment.root_pc)} "
                f"{segment.quality}"
            )

        options = (
            trf("保留当前段 · {chord}", chord=label(first)),
            trf("保留下一段 · {chord}", chord=label(second)),
        )
        selected, accepted = QInputDialog.getItem(
            self,
            tr("合并和弦段"),
            tr("选择合并后保留的和弦；不会自动改动音符："),
            options,
            0,
            False,
        )
        if not accepted:
            return
        retained = first if str(selected) == options[0] else second
        callback = getattr(
            self.parent(), "_merge_transcription_chord_segments", None
        )
        if callable(callback):
            callback(
                first.segment_id,
                second.segment_id,
                retained.segment_id,
            )

    def _navigate_transcription_phrase(self, direction: int) -> None:
        callback = getattr(self.parent(), "_navigate_voice_group", None)
        if callable(callback):
            callback(int(direction))

    def _loop_transcription_phrase(self, enabled: bool) -> None:
        callback = getattr(self.parent(), "_set_voice_group_loop", None)
        if callable(callback):
            callback(bool(enabled))

    def _open_transcription_review_queue(self) -> None:
        callback = getattr(
            self.parent(), "_open_transcription_review_queue", None
        )
        if callable(callback):
            callback()

    def _confirm_transcription_instrument_match(
        self, group_id: object, instrument_id: int
    ) -> None:
        callback = getattr(
            self.parent(), "_confirm_assist_instrument_match", None
        )
        if callable(callback):
            callback(str(group_id), int(instrument_id))

    def _stage_transcription_group_to_existing_track(
        self, group_id: object, instrument_id: int
    ) -> None:
        tracks = [
            track
            for track in getattr(self.parent(), "tracks", ())
            if not track.is_percussion
            and int(track.bdo_instrument_id) == int(instrument_id)
        ]
        if not tracks:
            QMessageBox.information(
                self,
                tr("没有匹配的现有轨"),
                tr("请使用“新建该乐器轨”，或先在主时间轴新建对应乐器。"),
            )
            return
        labels = [
            trf(
                "{track} · {instrument}",
                track=track.display_name,
                instrument=trv(_ui_bdo_instrument_source(track.bdo_instrument_id)),
            )
            for track in tracks
        ]
        label, accepted = QInputDialog.getItem(
            self,
            tr("暂存到现有轨"),
            tr("选择目标轨；Apply 前不会修改工程："),
            labels,
            0,
            False,
        )
        if not accepted:
            return
        target = tracks[labels.index(str(label))]
        self._stage_voice_group_routes(
            str(group_id),
            int(target.track_id),
        )

    def _stage_transcription_group_to_new_track(
        self, group_id: object, instrument_id: int
    ) -> None:
        QMessageBox.information(
            self,
            tr("新建乐器轨"),
            tr("该声部会在 Apply 时与音符一起原子新建轨道。"),
        )
        self._stage_new_voice_group_track(
            str(group_id),
            int(instrument_id),
        )

    def _set_transcription_audition_source(self, source: str) -> None:
        previous_state = self.draft_playback_state
        retained_playhead = float(self.playhead_ms)
        self.transcription_audition_source = str(source)
        if previous_state in {"playing", "paused", "loading"}:
            self.stop_draft()
            self.set_draft_playhead(retained_playhead, follow=True)
            if previous_state in {"playing", "loading"}:
                QTimer.singleShot(0, self.play_draft)
        labels = {
            "combined": "工程 + 原音",
            "original": "原音",
            "candidate_a": "游戏候选 A",
            "candidate_b": "游戏候选 B",
        }
        source_key = labels.get(str(source))
        self.transcription_panel.set_status(
            trf(
                "试听源：{source}；继续使用上方唯一播放控制。",
                source=(trv(source_key) if source_key is not None else str(source)),
            )
        )

    def _redecode_transcription_range(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        callback = getattr(
            self.parent(), "_redecode_transcription_range", None
        )
        if callable(callback):
            callback()

    def _transcription_sensitivity_changed(self, sensitivity: str) -> None:
        callback = getattr(
            self.parent(), "_transcription_sensitivity_changed", None
        )
        if callable(callback):
            callback(sensitivity)

    def _transcription_cleanup_profile_changed(
        self,
        cleanup_profile: str,
    ) -> None:
        callback = getattr(
            self.parent(),
            "_transcription_cleanup_profile_changed",
            None,
        )
        if callable(callback):
            callback(cleanup_profile)

    def _transcription_analysis_mode_changed(
        self, analysis_mode: str,
    ) -> None:
        if self._warn_staging_blocks_analysis():
            self.transcription_panel.set_analysis_mode(
                self.transcription_session.state.analysis_mode
            )
            return
        callback = getattr(
            self.parent(), "_transcription_analysis_mode_changed", None
        )
        if callable(callback):
            callback(analysis_mode)

    def _reject_transcription_candidates(self) -> None:
        callback = getattr(
            self.parent(), "_reject_transcription_candidates", None
        )
        if callable(callback):
            callback()

    def _restore_transcription_candidates(self) -> None:
        callback = getattr(
            self.parent(), "_restore_transcription_candidates", None
        )
        if callable(callback):
            callback()

    def _select_suspected_transcription_fragments(self) -> None:
        callback = getattr(
            self.parent(),
            "_select_suspected_transcription_fragments",
            None,
        )
        if callable(callback):
            callback()

    def _undo_transcription_review(self) -> None:
        callback = getattr(self.parent(), "_undo_transcription_review", None)
        if callable(callback):
            callback()

    def _redo_transcription_review(self) -> None:
        callback = getattr(self.parent(), "_redo_transcription_review", None)
        if callable(callback):
            callback()

    def _align_reference_audio_to_playhead(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        parent = self.parent()
        reference_audio = getattr(parent, "reference_audio", None)
        if reference_audio is None or not reference_audio.audio_path:
            self.transcription_panel.set_status(tr("请先载入参考音频。"))
            return
        audio_position = float(reference_audio.player.position())
        parent._set_reference_alignment(
            float(self.playhead_ms) - audio_position,
            float(getattr(parent, "beat_origin_ms", 0.0)),
            autosave=True,
        )
        self.beat_origin_ms = float(getattr(parent, "beat_origin_ms", 0.0))
        self._sync_shared_transcription_projection()

    def _set_playhead_as_beat_origin(self) -> None:
        parent = self.parent()
        parent._set_reference_alignment(
            float(getattr(parent, "reference_audio_offset_ms", 0.0)),
            float(self.playhead_ms),
            autosave=True,
        )
        self.beat_origin_ms = float(self.playhead_ms)
        self.canvas.update()
        self.transcription_panel.set_status(
            tr("第一拍锚点已更新；正式音符位置未移动。")
        )

    def _toggle_ghost_notes(self, enabled: bool) -> None:
        self.ghost_opacity_slider.setEnabled(bool(enabled))
        self._update_reference_layer_settings(
            ghost_visible=bool(enabled)
        )
        parent = self.parent()
        if not enabled or not parent or not hasattr(parent, "tracks"):
            if hasattr(self, "canvas"):
                self.canvas.set_ghost_notes([])
            return
        notes = [
            GhostNoteProjection(
                note=note,
                track_id=int(item.track_id),
                instrument_id=int(item.bdo_instrument_id),
                color=str(item.color),
            )
            for item in parent.tracks
            if int(item.track_id) != int(self.track.track_id) and not item.muted
            for note in item.notes
        ]
        if hasattr(self, "canvas"):
            self.canvas.set_ghost_notes(notes)

    def _ghost_opacity_changed(self, value: int) -> None:
        normalized = max(0, min(100, int(value)))
        self.ghost_opacity_label.setText(f"{normalized}%")
        if hasattr(self, "canvas"):
            self.canvas.set_ghost_opacity(normalized / 100.0)
        self._update_reference_layer_settings(
            ghost_opacity_percent=normalized
        )

    def _set_top_inspector_mode(self, mode: str) -> None:
        show_notes = mode == "note"
        show_articulation = mode == "articulation"
        self.note_controls.setVisible(show_notes)
        self.articulation_controls.setVisible(show_articulation)
        self.grid_controls.setVisible(mode == "grid")
        self.note_mode_button.setChecked(show_notes)
        self.articulation_mode_button.setChecked(show_articulation)
        self.grid_mode_button.setChecked(mode == "grid")
        if show_articulation and self.isVisible():
            show_global_toast(self, tr("选择音符后即可批量应用奏法。"))
        elif mode == "grid" and self.isVisible():
            show_global_toast(
                self,
                tr("双击新建 · Ctrl+拖动复制 · Alt 临时取消吸附 · Ctrl+D 复制"),
            )

    def _toggle_draw_mode(self, enabled: bool) -> None:
        if hasattr(self, "canvas"):
            self.canvas.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
            self.canvas.update()
        if hasattr(self, "status"):
            show_global_toast(
                self,
                tr("绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附")
                if enabled
                else tr("选择模式：双击新建，拖动空白框选，Ctrl+拖动复制")
            )
            self._update_status()

    def _toggle_velocity_lane(self, visible: bool) -> None:
        self.velocity_lane.setVisible(visible)
        QTimer.singleShot(0, self.update_scrollbars)

    def draft_duration_ms(self) -> float:
        end = (
            self.canvas.content_end_ms
            if hasattr(self, "canvas")
            else max((note.start + note.dur for note in self.track.notes), default=0.0)
        )
        if self.transcription_mode_enabled:
            reference_audio = getattr(self.parent(), "reference_audio", None)
            if reference_audio is not None:
                end = max(
                    end,
                    float(
                        getattr(
                            reference_audio,
                            "project_end_ms",
                            reference_audio.duration_ms,
                        )
                    ),
                )
        return max(self.canvas.beat_ms if hasattr(self, "canvas") else 60000.0 / max(1, self.bpm), end + 60000.0 / max(1, self.bpm))

    @staticmethod
    def format_playback_time(ms: float) -> str:
        ms = max(0, round(ms))
        minutes, remainder = divmod(ms, 60000)
        seconds, millis = divmod(remainder, 1000)
        return f"{minutes}:{seconds:02d}.{millis:03d}"

    def set_draft_playhead(self, ms: float, follow: bool = False) -> None:
        duration = self.draft_duration_ms()
        self.playhead_ms = max(0.0, min(float(ms), duration))
        if hasattr(self, "canvas"):
            self.canvas.set_playhead(self.playhead_ms)
        if hasattr(self, "transcription_waveform"):
            self.transcription_waveform.set_playhead_ms(self.playhead_ms)
        if hasattr(self, "playback_time_label"):
            self.playback_time_label.setText(
                f"{self.format_playback_time(self.playhead_ms)} / {self.format_playback_time(duration)}"
            )
        if follow and hasattr(self, "time_scroll"):
            visible_ms = max(1.0, (self.canvas.width() - self.canvas.KEY_W) / self.canvas.px_per_ms)
            left, right = self.canvas.scroll_ms, self.canvas.scroll_ms + visible_ms
            if self.playhead_ms < left + visible_ms * .08 or self.playhead_ms > right - visible_ms * .08:
                self.time_scroll.setValue(round(max(0.0, self.playhead_ms - visible_ms * .45)))

    def seek_draft(self, ms: float) -> None:
        self.set_draft_playhead(ms, follow=True)
        if self.draft_playback_state in ("playing", "paused"):
            parent = self.parent()
            if (
                parent
                and hasattr(parent, "realtime_audio")
                and not self.draft_reference_only
            ):
                try:
                    parent.realtime_audio.seek(self.playhead_ms)
                except AudioEngineError as exc:
                    self.stop_draft()
                    QMessageBox.warning(self, tr("定位失败"), str(exc))
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                self._sync_draft_reference_audio(
                    self.playhead_ms,
                    play=self.draft_playback_state == "playing",
                    force=True,
                )

    def _sync_draft_reference_audio(
        self,
        project_ms: float,
        *,
        play: bool,
        force: bool = False,
    ) -> bool:
        """Keep the editor reference stream on the shared project clock."""

        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is None or not reference_audio.audio_path:
            return False
        converter = getattr(reference_audio, "project_to_audio", None)
        duration_ms = float(getattr(reference_audio, "duration_ms", 0.0))
        inside_reference = True
        if callable(converter):
            audio_ms = float(converter(project_ms))
            inside_reference = (
                math.isfinite(audio_ms)
                and audio_ms >= 0.0
                and (duration_ms <= 0.0 or audio_ms < duration_ms)
            )
        is_playing = bool(reference_audio.is_playing)
        if not inside_reference:
            if is_playing:
                reference_audio.pause()
            return False
        if force:
            reference_audio.set_position(project_ms)
        if not play:
            if is_playing:
                reference_audio.pause()
            return False
        if not force and not is_playing:
            reference_audio.set_position(project_ms)
        if not is_playing:
            reference_audio.play()
        return True

    def _start_draft_reference_only(
        self,
        reference_audio: object,
        *,
        status_text: str,
    ) -> bool:
        """Start the shared reference transport without a zero-event clock."""

        if not getattr(reference_audio, "audio_path", ""):
            return False
        reference_start = max(
            0.0,
            float(getattr(reference_audio, "project_start_ms", 0.0)),
        )
        start_ms = max(float(self.playhead_ms), reference_start)
        duration_ms = float(getattr(reference_audio, "duration_ms", 0.0))
        reference_end = float(
            getattr(
                reference_audio,
                "project_end_ms",
                reference_start + duration_ms,
            )
        )
        if duration_ms > 0.0 and start_ms >= reference_end:
            start_ms = reference_start
        self.parent()._stop_preview(reset_playhead=False)
        self.set_draft_playhead(start_ms, follow=True)
        if not self._sync_draft_reference_audio(
            start_ms,
            play=True,
            force=True,
        ):
            return False
        self.draft_reference_only = True
        self._set_draft_playback_state("playing")
        self.playback_timer.start()
        self.status.setText(tr(status_text))
        return True

    def poll_draft_playback(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            self.playback_timer.stop()
            return
        reference_audio = getattr(parent, "reference_audio", None)
        shared_range = (
            getattr(
                getattr(parent, "transcription_session", None),
                "state",
                None,
            ).region
            if (
                self.transcription_mode_enabled
                and self.loop_box.isChecked()
                and getattr(
                    getattr(parent, "transcription_session", None),
                    "state",
                    None,
                )
                is not None
            )
            else None
        )
        if self.draft_reference_only:
            if reference_audio is None or not reference_audio.audio_path:
                self.stop_draft()
                return
            position = float(
                getattr(
                    reference_audio,
                    "project_position_ms",
                    reference_audio.player.position(),
                )
            )
            self.set_draft_playhead(position, follow=True)
            if self.draft_playback_state == "paused":
                return
            if shared_range is not None and position >= shared_range[1]:
                self._sync_draft_reference_audio(
                    shared_range[0],
                    play=True,
                    force=True,
                )
                self.set_draft_playhead(shared_range[0], follow=True)
                return
            duration = self.draft_duration_ms()
            if (
                not reference_audio.is_playing
                or (duration > 0 and position >= duration - 1)
            ):
                if self.loop_box.isChecked():
                    self._sync_draft_reference_audio(
                        0.0,
                        play=True,
                        force=True,
                    )
                else:
                    self.stop_draft()
            return
        try:
            if self.draft_playback_state == "loading":
                status = parent.realtime_audio.get_status()
                progress = status.preload_progress if status.preload_total else 0.0
                self.canvas.set_preload_progress(progress, "loading")
                self.status.setText(trf(
                    "正在准备游戏音源… {loaded}/{total}",
                    loaded=status.preload_loaded, total=status.preload_total,
                ))
                result = parent.realtime_audio.finish_loading(self.playhead_ms)
                if result is None:
                    return
                self.canvas.set_preload_progress(1.0, "ready")
                parent.realtime_audio.play()
                self._set_draft_playback_state("playing")
                self.status.setText(tr("游戏音源已缓存 · 开始试听"))
                if (
                    self.transcription_mode_enabled
                    and self.transcription_audition_source == "combined"
                    and reference_audio is not None
                    and reference_audio.audio_path
                ):
                    self._sync_draft_reference_audio(
                        self.playhead_ms,
                        play=True,
                        force=True,
                    )
            status = parent.realtime_audio.get_status()
            self.set_draft_playhead(status.position_ms, follow=self.draft_playback_state == "playing")
            if (
                shared_range is not None
                and status.state == "playing"
                and status.position_ms >= shared_range[1]
            ):
                self.seek_draft(shared_range[0])
                parent.realtime_audio.play()
                if (
                    self.transcription_audition_source == "combined"
                    and
                    reference_audio is not None
                    and reference_audio.audio_path
                ):
                    self._sync_draft_reference_audio(
                        shared_range[0],
                        play=True,
                        force=True,
                    )
                return
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source == "combined"
                and reference_audio is not None
                and reference_audio.audio_path
                and status.state == "playing"
            ):
                self._sync_draft_reference_audio(
                    status.position_ms,
                    play=True,
                )
            if status.position_ms >= status.duration_ms - 1 and status.duration_ms > 0:
                if (
                    self.transcription_mode_enabled
                    and self.transcription_audition_source == "combined"
                    and reference_audio is not None
                    and reference_audio.is_playing
                    and float(
                        getattr(
                            reference_audio,
                            "project_position_ms",
                            reference_audio.player.position(),
                        )
                    )
                    < self.draft_duration_ms() - 1
                ):
                    self.draft_reference_only = True
                elif self.loop_box.isChecked():
                    self.seek_draft(0.0)
                    parent.realtime_audio.play()
                    if (
                        self.transcription_mode_enabled
                        and self.transcription_audition_source == "combined"
                        and reference_audio is not None
                        and reference_audio.audio_path
                    ):
                        self._sync_draft_reference_audio(
                            0.0,
                            play=True,
                            force=True,
                        )
                else:
                    self.stop_draft()
            elif status.state == "paused" and self.draft_playback_state == "playing":
                self._set_draft_playback_state("paused")
        except AudioEngineError as exc:
            self.playback_timer.stop()
            parent.realtime_audio.cancel_loading()
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def set_zoom(self, value: int) -> None:
        if math.isclose(self.canvas.px_per_beat, float(value)):
            return
        self.canvas.px_per_beat = float(value)
        self.canvas.update()
        self.velocity_lane.update()
        self.transcription_waveform.refresh()
        self.update_scrollbars()

    def focus_transcription_time_range(
        self, start_ms: float, end_ms: float
    ) -> None:
        start_ms, end_ms = sorted((float(start_ms), float(end_ms)))
        duration_ms = max(self.canvas.beat_ms * 0.5, end_ms - start_ms)
        viewport_width = max(
            120.0, float(self.canvas.width() - self.canvas.KEY_W)
        )
        target_px_per_beat = max(
            30,
            min(
                320,
                round(
                    viewport_width
                    * self.canvas.beat_ms
                    / (duration_ms * 1.25)
                ),
            ),
        )
        self.editor_zoom.setValue(target_px_per_beat)
        visible_ms = viewport_width / max(
            1e-9, self.canvas.px_per_ms
        )
        centered_start = max(
            0.0,
            (start_ms + end_ms - visible_ms) * 0.5,
        )
        self.update_scrollbars()
        self.set_time_scroll(round(centered_start))

    def update_scrollbars(self) -> None:
        if not hasattr(self, "time_scroll"):
            return
        visible_ms = max(1.0, (self.canvas.width() - self.canvas.KEY_W) / self.canvas.px_per_ms)
        content_end = self.canvas.content_end_ms + self.canvas.beat_ms * 4
        maximum = max(0, round(content_end - visible_ms))
        scroll_ms = float(max(0, min(maximum, round(self.canvas.scroll_ms))))
        time_changed = not math.isclose(scroll_ms, self.canvas.scroll_ms, abs_tol=1e-6)
        self.canvas.scroll_ms = scroll_ms
        self.time_scroll.blockSignals(True)
        self.time_scroll.setRange(0, maximum)
        self.time_scroll.setPageStep(max(1, round(visible_ms)))
        self.time_scroll.setSingleStep(max(1, round(self.quantize_ms())))
        self.time_scroll.setValue(round(scroll_ms))
        self.time_scroll.blockSignals(False)

        if self._initial_pitch_focus_pending:
            self.canvas.pitch_top = self._recommended_initial_pitch_top()
            self._initial_pitch_focus_pending = False
        pitch_min, pitch_max = self.pitch_top_bounds()
        pitch_top = max(pitch_min, min(pitch_max, int(self.canvas.pitch_top)))
        pitch_changed = pitch_top != self.canvas.pitch_top
        self.canvas.pitch_top = pitch_top
        self.pitch_scroll.blockSignals(True)
        self.pitch_scroll.setRange(0, pitch_max - pitch_min)
        self.pitch_scroll.setPageStep(self.visible_pitch_rows())
        self.pitch_scroll.setSingleStep(1)
        # Scrollbar value grows downwards while MIDI pitches grow upwards.
        self.pitch_scroll.setValue(pitch_max - pitch_top)
        self.pitch_scroll.blockSignals(False)
        if time_changed:
            self.velocity_lane.update()
            self.transcription_waveform.refresh()
        if time_changed or pitch_changed:
            self.canvas.update()
        self.set_draft_playhead(self.playhead_ms)

    def visible_pitch_rows(self) -> int:
        grid_height = max(0, self.canvas.height() - self.canvas.RULER_H)
        return max(1, math.ceil(grid_height / self.canvas.ROW_H))

    def _recommended_initial_pitch_top(self) -> int:
        """Focus the first view without hiding or rewriting any pitch row."""

        visible_rows = min(
            self.canvas.MAX_PITCH - self.canvas.MIN_PITCH + 1,
            self.visible_pitch_rows(),
        )
        if self.canvas.notes:
            low = min(int(note.pitch) for note in self.canvas.notes)
            high = max(int(note.pitch) for note in self.canvas.notes)
            if high - low + 1 > max(1, visible_rows - 3):
                target = high + 1
            else:
                target = round((low + high + visible_rows - 1) / 2.0)
        elif self.instrument_adaptation is not None:
            low, high = self.instrument_adaptation.recommended_visible_range
            target = round((low + high + visible_rows - 1) / 2.0)
        else:
            target = 84
        minimum_top = self.canvas.MIN_PITCH + visible_rows - 1
        return max(
            minimum_top,
            min(self.canvas.MAX_PITCH, int(target)),
        )

    def pitch_top_bounds(self) -> tuple[int, int]:
        pitch_max = self.canvas.MAX_PITCH
        visible_rows = min(
            pitch_max - self.canvas.MIN_PITCH + 1,
            self.visible_pitch_rows(),
        )
        pitch_min = self.canvas.MIN_PITCH + visible_rows - 1
        return pitch_min, pitch_max

    def set_time_scroll(self, value: int) -> None:
        value = float(max(self.time_scroll.minimum(), min(self.time_scroll.maximum(), int(value))))
        if self.time_scroll.value() != round(value):
            self.time_scroll.blockSignals(True)
            self.time_scroll.setValue(round(value))
            self.time_scroll.blockSignals(False)
        if math.isclose(value, self.canvas.scroll_ms, abs_tol=1e-6):
            return
        self.canvas.scroll_ms = value
        self.canvas.update()
        self.velocity_lane.update()
        self.transcription_waveform.refresh()

    def set_pitch_scroll(self, value: int) -> None:
        pitch_min, pitch_max = self.pitch_top_bounds()
        scroll_value = max(0, min(pitch_max - pitch_min, int(value)))
        pitch_top = pitch_max - scroll_value
        if self.pitch_scroll.value() != scroll_value:
            self.pitch_scroll.blockSignals(True)
            self.pitch_scroll.setValue(scroll_value)
            self.pitch_scroll.blockSignals(False)
        if pitch_top == self.canvas.pitch_top:
            return
        self.canvas.pitch_top = pitch_top
        self.canvas.update()

    def optimize_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "tracks"):
            return
        draft_tracks = [
            replace(item, notes=self.edited_notes()) if int(item.track_id) == int(self.track.track_id) else item
            for item in parent.tracks
        ]
        dialog = MidiOptimizeDialog(parent, int(self.track.track_id), source_tracks=draft_tracks)
        if dialog.exec() != QDialog.Accepted:
            return
        optimized = next(
            (item for item in dialog.optimized_tracks() if int(item.track_id) == int(self.track.track_id)),
            None,
        )
        if optimized is None:
            return
        self.push_snapshot()
        self.canvas.notes = list(optimized.notes)
        self.canvas.selected.clear()
        self.canvas.anchor_index = None
        self._notes_changed()
        self.refresh_fields()
        self.update_scrollbars()
        self.status.setText(trf(
            "单轨优化完成 · 当前草稿 {count} 音符 · 点击应用或确定后写回",
            count=len(self.canvas.notes),
        ))

    def toggle_draft_playback(self) -> None:
        if self.draft_playback_state == "loading":
            return
        if self.draft_playback_state == "playing":
            self.pause_draft()
        elif self.draft_playback_state == "paused":
            self.resume_draft()
        else:
            self.play_draft()

    def _set_draft_playback_state(self, state: str) -> None:
        self.draft_playback_state = state
        labels = {"stopped": "播放", "loading": "准备中…", "playing": "暂停", "paused": "继续"}
        label = tr(labels.get(state, "播放"))
        self.draft_play_button.setToolTip(label)
        self.draft_play_button.setAccessibleName(label)
        self.draft_play_button.setText(
            "" if getattr(self, "_editor_controls_compact", False) else label
        )
        self.draft_play_button.setEnabled(state != "loading")

    def play_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        shared_range = (
            getattr(
                getattr(parent, "transcription_session", None),
                "state",
                None,
            ).region
            if (
                self.transcription_mode_enabled
                and self.loop_box.isChecked()
                and getattr(
                    getattr(parent, "transcription_session", None),
                    "state",
                    None,
                )
                is not None
            )
            else None
        )
        if (
            shared_range is not None
            and not shared_range[0] <= self.playhead_ms < shared_range[1]
        ):
            self.set_draft_playhead(shared_range[0], follow=True)
        reference_audio = getattr(parent, "reference_audio", None)
        if (
            self.transcription_mode_enabled
            and self.transcription_audition_source == "original"
            and reference_audio is not None
            and reference_audio.audio_path
        ):
            self._start_draft_reference_only(
                reference_audio,
                status_text="正在播放参考原音",
            )
            return
        draft_track = replace(
            self.track,
            notes=self.edited_notes(),
            muted=False,
            solo=False,
        )
        if (
            self.transcription_mode_enabled
            and self.transcription_audition_source
            in {"candidate_a", "candidate_b"}
        ):
            active_group = parent._active_voice_group()
            analysis = parent.instrument_match_analysis
            match_index = (
                0
                if self.transcription_audition_source == "candidate_a"
                else 1
            )
            matches = (
                analysis.matches_for_group(active_group.group_id)
                if analysis is not None and active_group is not None
                else ()
            )
            if active_group is None or match_index >= len(matches):
                self.transcription_panel.set_status(
                    tr("当前声部没有可试听的该候选")
                )
                return
            wanted_ids = set(active_group.candidate_ids)
            selected_instrument_id = int(
                matches[match_index].instrument_id
            )
            supported_pitches = game_supported_pitches(
                selected_instrument_id
            )
            audition_candidates = [
                candidate
                for candidate in parent.transcription_session.candidates
                if parent.transcription_session.candidate_id(candidate)
                in wanted_ids
            ]
            if (
                not audition_candidates
                or any(
                    (
                        not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                            candidate,
                            float(parent.reference_audio_offset_ms),
                        )
                        or not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
                            candidate.pitch,
                            is_percussion=False,
                            instrument_id=selected_instrument_id,
                            transpose=self.transpose,
                            supported_pitches=supported_pitches,
                        )
                    )
                    for candidate in audition_candidates
                )
            ):
                self.transcription_panel.set_status(
                    tr("游戏候选含移调后不可用的音高，已停止试听。")
                )
                return
            audition_notes = [
                CANDIDATE_NOTE_POLICY.to_note(
                    candidate,
                    float(parent.reference_audio_offset_ms),
                )._replace(
                    pitch=int(candidate.pitch) + int(self.transpose)
                )
                for candidate in audition_candidates
            ]
            draft_track = replace(
                self.track,
                notes=audition_notes,
                bdo_instrument_id=selected_instrument_id,
                display_name=_ui_bdo_instrument_name(selected_instrument_id),
                muted=False,
                solo=False,
            )
        if (
            self.transcription_mode_enabled
            and self.transcription_audition_source == "combined"
            and not draft_track.notes
            and reference_audio is not None
            and reference_audio.audio_path
        ):
            self._start_draft_reference_only(
                reference_audio,
                status_text="仅播放参考音频",
            )
            return
        blockers = parent._realtime_preview_blockers([draft_track])
        if blockers:
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"candidate_a", "candidate_b"}
            ):
                self.transcription_panel.set_status(
                    tr("游戏候选音源不可用；没有回退播放原音。")
                )
                return
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                self._start_draft_reference_only(
                    reference_audio,
                    status_text="仅播放参考音频",
                )
                return
            QMessageBox.warning(
                self,
                tr("无法试听"),
                tr("当前轨道缺少可用的实时游戏音源：")
                + "\n- "
                + "\n- ".join(blockers[:6]),
            )
            return
        try:
            parent._stop_preview(reset_playhead=False)
            self.draft_reference_only = False
            parent.realtime_audio.load_project_async(
                [draft_track], BDO_SAMPLE_MAP_PATH, self.playhead_ms, parent.reverb, parent.delay, parent.chorus
            )
            self.canvas.set_preload_progress(0.0, "loading")
            self._set_draft_playback_state("loading")
            self.status.setText(tr("正在准备游戏音源…"))
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def audition_note(self, note) -> None:
        """Asynchronously audition one editor note with the current game instrument."""
        if hasattr(self, "note_preview_box") and not self.note_preview_box.isChecked():
            return
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        audition_track = replace(
            self.track,
            notes=[note._replace(start=0.0, dur=max(180.0, min(650.0, float(note.dur))))],
            muted=False,
            solo=False,
        )
        if parent._realtime_preview_blockers([audition_track]):
            self.status.setText(tr("当前音符没有可用的游戏音源"))
            return
        try:
            if self.draft_playback_state != "stopped":
                self.stop_draft()
            elif getattr(parent, "realtime_preview_active", False) or getattr(parent, "realtime_preview_loading", False):
                parent._stop_preview(reset_playhead=False)
            self.audition_stop_timer.stop()
            self.audition_pending = True
            self.audition_note_name = note_name(note.pitch)
            parent.realtime_audio.load_project_async(
                [audition_track], BDO_SAMPLE_MAP_PATH, 0.0,
                parent.reverb, parent.delay, parent.chorus,
            )
            self.status.setText(trf("正在准备音符试听… {note}", note=self.audition_note_name))
            self.audition_timer.start()
        except AudioEngineError as exc:
            self.audition_pending = False
            self.audition_timer.stop()
            self.status.setText(trf("音符试听不可用：{message}", message=str(exc)))

    def audition_pitch(self, pitch: int) -> None:
        self.audition_note(Note(
            max(0, min(127, int(pitch))), self.default_note_velocity, 0.0,
            self.default_note_duration(), self.current_articulation(),
        ))

    def _poll_note_audition(self) -> None:
        if not self.audition_pending:
            self.audition_timer.stop()
            return
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            self.audition_pending = False
            self.audition_timer.stop()
            return
        try:
            result = parent.realtime_audio.finish_audition_loading()
            if result is None:
                return
            self.audition_pending = False
            self.audition_timer.stop()
            audible_ms = max(1.0, float(result.get("duration_ms", 1.0)))
            self.audition_stop_timer.start(max(1, math.ceil(audible_ms + 30.0)))
            self.status.setText(trf("试听 {note}", note=self.audition_note_name))
        except AudioEngineError as exc:
            self.audition_pending = False
            self.audition_timer.stop()
            self.status.setText(trf("音符试听不可用：{message}", message=str(exc)))

    def _stop_note_audition(self) -> None:
        parent = self.parent()
        if parent and hasattr(parent, "realtime_audio"):
            parent.realtime_audio.clear_playback()
        self.audition_pending = False
        self.audition_timer.stop()

    def pause_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        try:
            if not self.draft_reference_only:
                parent.realtime_audio.pause()
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
            ):
                reference_audio.pause()
            self._set_draft_playback_state("paused")
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def resume_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        try:
            if not self.draft_reference_only:
                parent.realtime_audio.play()
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                self._sync_draft_reference_audio(
                    self.playhead_ms,
                    play=True,
                    force=True,
                )
            self._set_draft_playback_state("playing")
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def stop_draft(self) -> None:
        self.playback_timer.stop()
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        parent = self.parent()
        if parent and hasattr(parent, "realtime_audio"):
            try:
                # The editor shares the main-window audio engine.  Transport
                # Stop must discard queued PCM without tearing down the output
                # thread and decode pools; application shutdown owns the full
                # engine stop.
                parent.realtime_audio.clear_playback()
            except AudioEngineError:
                pass
        reference_audio = getattr(parent, "reference_audio", None)
        if self.transcription_mode_enabled and reference_audio is not None:
            reference_audio.stop()
        self.draft_reference_only = False
        if hasattr(self, "draft_play_button"):
            self._set_draft_playback_state("stopped")
        if hasattr(self, "canvas"):
            self.canvas.set_preload_progress(0.0, "idle")
            self.set_draft_playhead(0.0)

    def closeEvent(self, event) -> None:
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        self.stop_draft()
        self.canvas.release_transcription_evidence()
        self.transcription_waveform.release_reference_audio()
        self._remove_editor_event_filter()
        super().closeEvent(event)

    def reject(self) -> None:
        super().reject()

    def accept(self) -> None:
        super().accept()

    def minimum_duration_ms(self) -> float:
        return max(1.0, self.quantize_ms() / 8.0)

    def default_note_duration(self) -> float:
        return self.last_note_duration_ms if self.last_note_duration_ms > 0 else self.quantize_ms()

    def snap_time(self, value: float) -> float:
        if not self.snap_box.isChecked():
            return max(0.0, value)
        q = self.quantize_ms()
        return max(
            0.0,
            self.beat_origin_ms
            + round((value - self.beat_origin_ms) / q) * q,
        )

    def current_articulation(self) -> int:
        return int(self.articulation_combo.currentData() or 0)

    def note_invalid(self, pitch: int) -> bool:
        pitch = int(pitch)
        cached = self._invalid_pitch_cache.get(pitch)
        if cached is not None:
            return cached
        if self.track.bdo_instrument_id == 0x0d:
            if self.canonical_drum_lanes:
                legal = (
                    self.instrument_adaptation.legal_pitches
                    if self.instrument_adaptation is not None
                    else frozenset(range(BDO_DRUM_MIN, BDO_DRUM_MAX + 1))
                )
                result = pitch not in legal
            else:
                mapped = _GM_TO_BDO_DRUM.get(pitch)
                result = (
                    mapped is None
                    or mapped < BDO_DRUM_MIN
                    or mapped > BDO_DRUM_MAX
                )
        else:
            supported = game_supported_pitches(
                self.track.bdo_instrument_id, self.track.marnian_synth_mode
            )
            converted = pitch + self.transpose
            result = converted not in supported if supported is not None else not (BDO_NOTE_MIN <= converted <= BDO_NOTE_MAX)
        self._invalid_pitch_cache[pitch] = result
        return result

    def _recalculate_invalid_note_count(self) -> None:
        self._invalid_note_count = sum(1 for note in self.canvas.notes if self.note_invalid(note.pitch))

    def snapshot(
        self,
    ) -> tuple[
        list,
        set[int],
        set[CandidateRoute],
        set[CandidateRoute],
        dict[int, int],
        str,
        str,
    ]:
        return (
            list(self.canvas.notes),
            set(self.canvas.selected),
            set(self.staged_primary_routes),
            set(self.staged_copy_routes),
            dict(self.staged_new_track_specs),
            self.staged_analysis_cache_key,
            self.staged_analysis_fingerprint,
        )

    def push_snapshot(self, notes=None, selected=None) -> None:
        self.undo_stack.append(
            (
                list(self.canvas.notes if notes is None else notes),
                set(self.canvas.selected if selected is None else selected),
                set(self.staged_primary_routes),
                set(self.staged_copy_routes),
                dict(self.staged_new_track_specs),
                self.staged_analysis_cache_key,
                self.staged_analysis_fingerprint,
            )
        )
        if len(self.undo_stack) > 200: self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, state) -> None:
        if self.draft_playback_state != "stopped":
            self.stop_draft()
        self.canvas.notes, self.canvas.selected = list(state[0]), set(state[1])
        self.staged_primary_routes = set(state[2]) if len(state) > 2 else set()
        self.staged_copy_routes = set(state[3]) if len(state) > 3 else set()
        has_track_specs = len(state) > 4 and isinstance(state[4], dict)
        self.staged_new_track_specs = (
            dict(state[4]) if has_track_specs else {}
        )
        cache_index = 5 if has_track_specs else 4
        fingerprint_index = 6 if has_track_specs else 5
        self.staged_analysis_cache_key = (
            str(state[cache_index]) if len(state) > cache_index else ""
        )
        self.staged_analysis_fingerprint = (
            str(state[fingerprint_index])
            if len(state) > fingerprint_index
            else ""
        )
        self._clear_staging_identity_if_empty()
        self.canvas.rebuild_note_index()
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.canvas.update(); self.refresh_fields()
        self._sync_shared_transcription_projection()

    def undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append(self.snapshot()); self._restore(self.undo_stack.pop())

    def redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append(self.snapshot()); self._restore(self.redo_stack.pop())

    def delete_selected(self) -> None:
        if not self.canvas.selected: return
        self.push_snapshot()
        self.canvas.notes = [n for i, n in enumerate(self.canvas.notes) if i not in self.canvas.selected]
        self.canvas.selected.clear(); self._notes_changed(); self.refresh_fields()

    def delete_note_at(self, index: int) -> None:
        if index < 0 or index >= len(self.canvas.notes):
            return
        self.push_snapshot()
        del self.canvas.notes[index]
        self.canvas.selected = {
            selected - 1 if selected > index else selected
            for selected in self.canvas.selected
            if selected != index
        }
        if self.canvas.anchor_index == index:
            self.canvas.anchor_index = None
        elif self.canvas.anchor_index is not None and self.canvas.anchor_index > index:
            self.canvas.anchor_index -= 1
        self._notes_changed()
        self.refresh_fields()

    def copy_selected(self) -> None:
        chosen = [self.canvas.notes[i] for i in sorted(self.canvas.selected)]
        if chosen:
            origin = min(n.start for n in chosen)
            self.clipboard = [n._replace(start=n.start - origin) for n in chosen]

    def paste_notes(self) -> None:
        if not self.clipboard: return
        self.push_snapshot()
        origin = self.snap_time(self.canvas.edit_cursor_ms)
        first = len(self.canvas.notes)
        self.canvas.notes.extend(n._replace(start=origin + n.start) for n in self.clipboard)
        self.canvas.selected = set(range(first, len(self.canvas.notes)))
        self.canvas.anchor_index = first
        self.canvas.set_edit_cursor(max(
            note.start + note.dur for note in self.canvas.notes[first:]
        ))
        self._notes_changed(); self.refresh_fields()

    def duplicate_selected(self) -> None:
        chosen = [self.canvas.notes[index] for index in sorted(self.canvas.selected)]
        if not chosen:
            return
        self.push_snapshot()
        start = min(note.start for note in chosen)
        end = max(note.start + note.dur for note in chosen)
        span = max(self.quantize_ms(), end - start)
        offset = math.ceil(span / self.quantize_ms()) * self.quantize_ms()
        first = len(self.canvas.notes)
        self.canvas.notes.extend(note._replace(start=note.start + offset) for note in chosen)
        self.canvas.selected = set(range(first, len(self.canvas.notes)))
        self.canvas.anchor_index = first
        self.canvas.set_edit_cursor(max(
            note.start + note.dur for note in self.canvas.notes[first:]
        ))
        self._notes_changed()
        self.refresh_fields()

    def apply_field(self, field: str, text: str) -> None:
        if self.updating_fields or not self.canvas.selected or text.strip() in ("", "—"): return
        try: value = float(text) if field in ("start", "dur") else int(text)
        except ValueError: self.refresh_fields(); return
        if field == "pitch": value = max(0, min(127, int(value)))
        elif field == "vel": value = max(1, min(127, int(value)))
        elif field == "start": value = max(0.0, float(value))
        else: value = max(self.minimum_duration_ms(), float(value))
        self.push_snapshot()
        for i in self.canvas.selected: self.canvas.notes[i] = self.canvas.notes[i]._replace(**{field: value})
        self._notes_changed(); self.refresh_fields()

    def _choose_articulation(self, ntype: int) -> None:
        index = self.articulation_combo.findData(ntype)
        if index < 0:
            return
        if index == self.articulation_combo.currentIndex():
            self.apply_articulation()
        else:
            self.articulation_combo.setCurrentIndex(index)

    def apply_articulation(self) -> None:
        if self.updating_fields or not self.canvas.selected: return
        value = self.current_articulation()
        if all(int(getattr(self.canvas.notes[i], "ntype", 0)) == value for i in self.canvas.selected): return
        self.push_snapshot()
        for i in self.canvas.selected: self.canvas.notes[i] = self.canvas.notes[i]._replace(ntype=value)
        self._notes_changed()
        self.refresh_fields()

    def refresh_fields(self) -> None:
        self.updating_fields = True
        chosen = [self.canvas.notes[i] for i in sorted(self.canvas.selected)]
        if not chosen:
            self.selection_summary.setText(tr("未选择音符"))
        elif len(chosen) == 1:
            note = chosen[0]
            self.selection_summary.setText(trf(
                "已选择 1 个音符 · {note} · {start} ms",
                note=note_name(note.pitch), start=f"{note.start:.0f}",
            ))
        else:
            self.selection_summary.setText(trf(
                "已选择 {count} 个音符 · 可批量修改共同属性", count=len(chosen)
            ))
        for widget, field in ((self.pitch_edit, "pitch"), (self.start_edit, "start"), (self.duration_edit, "dur"), (self.velocity_edit, "vel")):
            values = [getattr(n, field) for n in chosen]
            widget.setEnabled(bool(chosen)); widget.setText("" if not values else (str(round(values[0], 3)) if all(v == values[0] for v in values) else "—"))
        if chosen:
            types = {int(getattr(n, "ntype", 0)) for n in chosen}
            if len(types) == 1:
                index = self.articulation_combo.findData(next(iter(types)))
                if index >= 0: self.articulation_combo.setCurrentIndex(index)
        self.articulation_combo.setEnabled(bool(chosen))
        selected_type = next(iter(types)) if chosen and len(types) == 1 else None
        for ntype, button in self.articulation_buttons.items():
            button.setEnabled(bool(chosen))
            button.setChecked(ntype == selected_type)
        self.updating_fields = False
        self._update_status()

    def _hover_changed(self, ms: float, pitch: int) -> None:
        key = (int(ms // 25.0), int(pitch))
        if key == self._hover_status_key:
            return
        self._hover_status_key = key
        self._update_status(ms, pitch)

    def _update_status(self, ms: float = 0.0, pitch: int | None = None) -> None:
        pos = f" · {ms:.0f} ms · {note_name(pitch)}" if pitch is not None else ""
        warning = (
            trfv(" · 越界 {count}", count=self._invalid_note_count)
            if self._invalid_note_count
            else ""
        )
        self.status.setText(trf(
            "已选 {selected} · 共 {total} 音符{position}{warning}",
            selected=len(self.canvas.selected), total=len(self.canvas.notes),
            position=pos, warning=warning,
        ))

    def _notes_changed(self) -> None:
        if self.draft_playback_state != "stopped":
            self.stop_draft()
        self._reconcile_staged_primary_routes()
        self.canvas.rebuild_note_index()
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.canvas.update(); self.velocity_lane.update(); self._update_status(); self.update_scrollbars()
        if self.transcription_mode_enabled:
            self._sync_shared_transcription_projection()
            schedule = getattr(
                self.parent(),
                "_schedule_transcription_assist_refresh",
                None,
            )
            if callable(schedule):
                schedule()

    def _reconcile_staged_primary_routes(self) -> None:
        current_track_id = int(self.track.track_id)
        current_copy_routes = {
            route
            for route in self.staged_copy_routes
            if int(route.track_id) == current_track_id
        }
        current_routes = set(self.staged_primary_routes).union(
            current_copy_routes
        )
        if not current_routes:
            return
        session = getattr(self.parent(), "transcription_session", None)
        if session is None:
            self.staged_primary_routes.clear()
            self.staged_copy_routes.difference_update(current_copy_routes)
            self._clear_staging_identity_if_empty()
            return
        offset_ms = float(
            getattr(self.parent(), "reference_audio_offset_ms", 0.0)
        )
        unused_note_indices = set(range(len(self.canvas.notes)))
        notes_by_pitch: dict[
            int,
            tuple[list[float], list[int]],
        ] = {}
        grouped_indices: dict[int, list[int]] = defaultdict(list)
        for index, note in enumerate(self.canvas.notes):
            grouped_indices[int(note.pitch)].append(index)
        for pitch, indices in grouped_indices.items():
            ordered = sorted(
                indices,
                key=lambda index: float(
                    self.canvas.notes[index].start
                ),
            )
            notes_by_pitch[pitch] = (
                [
                    float(self.canvas.notes[index].start)
                    for index in ordered
                ],
                ordered,
            )
        survivors: set[CandidateRoute] = set()
        for route in sorted(current_routes):
            candidate = session.candidate_for_id(route.candidate_id)
            if candidate is None:
                continue
            starts, indices = notes_by_pitch.get(
                int(candidate.pitch),
                ([], []),
            )
            project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate,
                offset_ms,
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            matches = [
                index
                for index in indices[first:last]
                if index in unused_note_indices
                if CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    self.canvas.notes[index],
                    offset_ms,
                )
            ]
            if not matches:
                continue
            chosen = min(
                matches,
                key=lambda index: (
                    abs(
                        float(self.canvas.notes[index].start)
                        - project_start
                    ),
                    index,
                ),
            )
            unused_note_indices.remove(chosen)
            survivors.add(route)
        self.staged_primary_routes.intersection_update(survivors)
        self.staged_copy_routes.difference_update(current_copy_routes)
        self.staged_copy_routes.update(
            route
            for route in current_copy_routes
            if route in survivors
        )
        self._clear_staging_identity_if_empty()

    def _update_track_meta(self) -> None:
        if hasattr(self, "track_meta"):
            self.track_meta.setText(
                f"♫ {len(self.canvas.notes) if hasattr(self, 'canvas') else len(self.track.notes)}"
                f"   ·   {self.bpm} BPM   ·   {self.time_sig}/4"
            )

    def edited_notes(self) -> list:
        return sorted(self.canvas.notes, key=lambda n: (n.start, n.pitch, n.dur))

    def apply_notes(self) -> TranscriptionEditorCommitReport | None:
        notes = self.edited_notes()
        parent = self.parent()
        commit = getattr(parent, "_commit_note_editor", None)
        if callable(commit):
            state = getattr(
                getattr(parent, "transcription_session", None),
                "state",
                TranscriptionSessionState(),
            )
            request = TranscriptionEditorCommit(
                int(self.track.track_id),
                tuple(notes),
                tuple(self.staged_primary_routes),
                tuple(self.staged_copy_routes),
                (
                    self.staged_analysis_cache_key
                    if self._has_transcription_staging()
                    else str(getattr(state, "cache_key", "") or "")
                ),
                (
                    self.staged_analysis_fingerprint
                    if self._has_transcription_staging()
                    else str(
                        getattr(state, "analysis_fingerprint", "") or ""
                    )
                ),
                tuple(sorted(self.staged_new_track_specs.items())),
            )
            report = commit(request)
            if report is None:
                return None
            successful = set(report.applied_routes)
            self.staged_primary_routes.difference_update(successful)
            self.staged_copy_routes.difference_update(successful)
            staged_target_ids = {
                route.track_id for route in self.staged_copy_routes
            }
            self.staged_new_track_specs = {
                track_id: instrument_id
                for track_id, instrument_id
                in self.staged_new_track_specs.items()
                if track_id in staged_target_ids
            }
            self._clear_staging_identity_if_empty()
            self.last_applied = list(notes)
            self._sync_shared_transcription_projection()
            if report.unresolved_routes:
                self.transcription_panel.set_status(
                    trf(
                        "部分候选未提交 · 失效 {invalid} · 孤立 {orphaned}",
                        invalid=report.invalid_count,
                        orphaned=report.orphaned_count,
                    )
                )
            return report
        self.last_applied = list(notes)
        self.notes_applied.emit(notes)
        return TranscriptionEditorCommitReport(project_changed=True)

    def accept_with_apply(self) -> None:
        report = self.apply_notes()
        if report is not None and not report.unresolved_routes:
            self.accept()


class TrackFxDialog(QDialog):
    def __init__(self, parent: QWidget, track: TrackState) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("轨道 FX"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.track = track
        try:
            self._original_track_settings = raw_track_settings(
                track.bdo_track_settings
            )
        except ValueError:
            self._original_track_settings = (0,) * 8
        self._effect_dirty: set[int] = set()
        self._effect_fields: dict[int, QSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(_ui_bdo_instrument_name(track.bdo_instrument_id))
        title.setObjectName("TrackTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(form)

        for label, index, object_name in (
            ("混响发送", TRACK_REVERB_SEND_INDEX, "TrackReverbSend"),
            ("延迟发送", TRACK_DELAY_SEND_INDEX, "TrackDelaySend"),
            ("合唱发送", TRACK_CHORUS_SEND_INDEX, "TrackChorusSend"),
        ):
            field = QSpinBox()
            field.setObjectName(object_name)
            field.setRange(0, GAME_PERCENT_MAX)
            raw_value = int(self._original_track_settings[index])
            field.setValue(max(0, min(GAME_PERCENT_MAX, raw_value)))
            if raw_value > GAME_PERCENT_MAX:
                field.setToolTip(
                    trf(
                        "导入原值 {value}；修改后按 0–100 写入。",
                        value=raw_value,
                    )
                )
            field.valueChanged.connect(
                lambda _value, effect_index=index: self._effect_dirty.add(
                    effect_index
                )
            )
            self._effect_fields[index] = field
            form.addRow(label, field)

        is_marnian = track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
        self.marnian_mode: QComboBox | None = None
        if is_marnian:
            self.marnian_mode = QComboBox()
            for label, value in MARNIAN_SYNTH_MODES:
                self.marnian_mode.addItem(tr(label), value)
            mode_index = self.marnian_mode.findData(track.marnian_synth_mode)
            self.marnian_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            form.addRow(tr("音源模式"), self.marnian_mode)

        if is_marnian:
            mode_hint = QLabel(tr("Basic 默认；其他模式待验证"))
            mode_hint.setWordWrap(True)
            mode_hint.setObjectName("Muted")
            layout.addWidget(mode_hint)
        preview_hint = QLabel(tr("游戏参数 · 本地试听不模拟 FX"))
        preview_hint.setObjectName("Muted")
        layout.addWidget(preview_hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_marnian_synth_mode(self) -> str:
        if self.marnian_mode is None:
            return "basic"
        return str(self.marnian_mode.currentData() or "basic")

    def selected_track_settings(self) -> tuple[int, ...]:
        """Return edited Aux sends while preserving untouched wire bytes."""

        settings = list(self._original_track_settings)
        for index in self._effect_dirty:
            settings[index] = self._effect_fields[index].value()
        return tuple(settings)

    def track_effects_changed(self) -> bool:
        return bool(self._effect_dirty)


class ReferenceAudioController(QObject):
    """Local MP3/WAV playback plus bounded waveform-envelope extraction."""

    file_changed = Signal(str)
    volume_changed = Signal(int)
    offset_changed = Signal(float)
    changed = Signal()
    timeline_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio_path: Path | None = None
        self._project_offset_ms = 0.0
        self.waveform: list[tuple[float, float, float]] = []
        self.waveform_starts: list[float] = []
        self.waveform_loading = False
        self._waveform_deferred_for_playback = False
        self._pending_project_position_ms: float | None = None

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.5)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(lambda _position: self.changed.emit())
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._playback_error)

        self.decoder = QAudioDecoder(self)
        self.decoder.bufferReady.connect(self._read_waveform_buffer)
        self.decoder.finished.connect(self._waveform_finished)
        self.decoder.error.connect(self._waveform_error)

    @property
    def audio_path(self) -> str:
        return str(self._audio_path or "")

    @property
    def display_name(self) -> str:
        return self._audio_path.name if self._audio_path else tr("未载入参考音频")

    @property
    def duration_ms(self) -> float:
        waveform_end = self.waveform[-1][1] if self.waveform else 0.0
        return max(float(self.player.duration()), waveform_end)

    @property
    def project_offset_ms(self) -> float:
        """Project time occupied by audio frame zero."""
        return self._project_offset_ms

    @property
    def project_start_ms(self) -> float:
        return self._project_offset_ms

    @property
    def project_end_ms(self) -> float:
        return self._project_offset_ms + self.duration_ms

    @property
    def project_position_ms(self) -> float:
        return self.audio_to_project(float(self.player.position()))

    @property
    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def volume_percent(self) -> int:
        return round(self.audio_output.volume() * 100)

    def choose_audio(self, parent: QWidget) -> None:
        start = self._audio_path.parent if self._audio_path else Path.home()
        selected, _filter = QFileDialog.getOpenFileName(
            parent,
            tr("选择参考音频"),
            str(start),
            tr("音频文件 (*.mp3 *.wav);;所有文件 (*.*)"),
        )
        if selected:
            self.set_audio_path(Path(selected))

    def set_audio_path(self, path: str | Path | None, *, notify: bool = True) -> bool:
        candidate = Path(path) if path else None
        if candidate is None or not candidate.is_file() or candidate.suffix.lower() not in {".mp3", ".wav"}:
            if path:
                return False
            self.stop()
            self.decoder.stop()
            self.decoder.setSource(QUrl())
            self.player.setSource(QUrl())
            self._audio_path = None
            self._pending_project_position_ms = None
            self.waveform = []
            self.waveform_starts = []
            self.waveform_loading = False
            self._waveform_deferred_for_playback = False
            if notify:
                self.file_changed.emit("")
            self.timeline_changed.emit()
            self.changed.emit()
            return True

        self.stop()
        self.decoder.stop()
        self._audio_path = candidate.resolve()
        self._pending_project_position_ms = None
        source = QUrl.fromLocalFile(str(self._audio_path))
        self.player.setSource(source)
        self.waveform = []
        self.waveform_starts = []
        self.waveform_loading = True
        self._waveform_deferred_for_playback = False
        self.decoder.setSource(source)
        self.decoder.start()
        if notify:
            self.file_changed.emit(str(self._audio_path))
        self.timeline_changed.emit()
        self.changed.emit()
        return True

    def play(self) -> None:
        if self._audio_path is not None:
            # A second full-file decoder can starve the audible Media
            # Foundation stream on long files. Resume waveform work only after
            # playback pauses or stops.
            if self.waveform_loading and self.decoder.isDecoding():
                self.decoder.stop()
                self.waveform = []
                self.waveform_starts = []
                self._waveform_deferred_for_playback = True
            self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        self._pending_project_position_ms = None
        self.player.stop()

    def project_to_audio(self, project_ms: float) -> float:
        return float(project_ms) - self._project_offset_ms

    def audio_to_project(self, audio_ms: float) -> float:
        return float(audio_ms) + self._project_offset_ms

    def set_project_offset_ms(self, milliseconds: float, *, notify: bool = True) -> None:
        normalized = float(milliseconds)
        if not math.isfinite(normalized):
            return
        if math.isclose(normalized, self._project_offset_ms, abs_tol=0.001):
            return
        self._project_offset_ms = normalized
        if notify:
            self.offset_changed.emit(normalized)
        self.timeline_changed.emit()
        self.changed.emit()

    def set_position(self, milliseconds: float) -> None:
        """Seek with a project-time position.

        All UI callers operate on the shared project timeline. The underlying
        media player remains in source-audio time.
        """
        project_ms = float(milliseconds)
        if not math.isfinite(project_ms):
            return
        audio_ms = self.project_to_audio(project_ms)
        if not math.isfinite(audio_ms) or audio_ms < 0.0:
            self._pending_project_position_ms = None
            self.player.setPosition(0)
            return
        media_duration_ms = float(self.player.duration())
        if media_duration_ms <= 0.0:
            # QMediaPlayer may ignore seeks issued before metadata arrives.
            # Retain the project-clock request and reapply it on durationChanged.
            self._pending_project_position_ms = project_ms
            self.player.setPosition(max(0, round(audio_ms)))
            return
        self._pending_project_position_ms = None
        self.player.setPosition(
            max(0, min(round(audio_ms), round(media_duration_ms)))
        )

    def _apply_pending_position(self) -> None:
        pending = self._pending_project_position_ms
        if pending is None or float(self.player.duration()) <= 0.0:
            return
        self._pending_project_position_ms = None
        self.set_position(pending)

    def _duration_changed(self, _duration: int) -> None:
        self._apply_pending_position()
        self.timeline_changed.emit()

    def set_volume_percent(self, percent: int, *, notify: bool = True) -> None:
        normalized = max(0, min(100, int(percent)))
        if normalized == self.volume_percent:
            return
        self.audio_output.setVolume(normalized / 100.0)
        if notify:
            self.volume_changed.emit(normalized)
        self.changed.emit()

    def _read_waveform_buffer(self) -> None:
        buffer = self.decoder.read()
        if not buffer.isValid() or buffer.frameCount() <= 0:
            return
        audio_format = buffer.format()
        channels = max(1, audio_format.channelCount())
        sample_rate = max(1, audio_format.sampleRate())
        sample_format = audio_format.sampleFormat()
        raw = buffer.constData().cast("B")
        try:
            if sample_format == QAudioFormat.SampleFormat.UInt8:
                samples = np.frombuffer(raw, dtype=np.uint8)
                amplitudes = np.abs(samples.astype(np.float32) - 128.0) / 128.0
            elif sample_format == QAudioFormat.SampleFormat.Int16:
                samples = np.frombuffer(raw, dtype=np.int16)
                amplitudes = np.abs(samples.astype(np.float32)) / 32768.0
            elif sample_format == QAudioFormat.SampleFormat.Int32:
                samples = np.frombuffer(raw, dtype=np.int32)
                amplitudes = np.abs(samples.astype(np.float64)) / 2147483648.0
            elif sample_format == QAudioFormat.SampleFormat.Float:
                samples = np.frombuffer(raw, dtype=np.float32)
                amplitudes = np.abs(samples)
            else:
                return
        except (BufferError, TypeError, ValueError):
            return

        frame_count = len(amplitudes) // channels
        if frame_count <= 0:
            return
        frame_peaks = amplitudes[:frame_count * channels].reshape(frame_count, channels).max(axis=1)
        frames_per_bucket = max(1, sample_rate // 20)  # 50 ms envelope
        start_ms = max(0.0, float(buffer.startTime()) / 1000.0)
        offsets = np.arange(0, frame_count, frames_per_bucket, dtype=np.int64)
        bucket_peaks = np.maximum.reduceat(frame_peaks, offsets)
        ends = np.minimum(offsets + frames_per_bucket, frame_count)
        self.waveform.extend(
            (
                start_ms + float(offset) / sample_rate * 1000.0,
                start_ms + float(end) / sample_rate * 1000.0,
                min(1.0, float(peak)),
            )
            for offset, end, peak in zip(offsets, ends, bucket_peaks)
        )

    def _waveform_finished(self) -> None:
        self.waveform.sort(key=lambda item: item[0])
        self.waveform_starts = [item[0] for item in self.waveform]
        self.waveform_loading = False
        self._apply_pending_position()
        self.timeline_changed.emit()
        self.changed.emit()

    def _playback_state_changed(
        self, state: QMediaPlayer.PlaybackState,
    ) -> None:
        self.changed.emit()
        if (
            state != QMediaPlayer.PlaybackState.PlayingState
            and self._waveform_deferred_for_playback
            and self._audio_path is not None
        ):
            self._waveform_deferred_for_playback = False
            self.waveform_loading = True
            self.decoder.setSource(QUrl.fromLocalFile(str(self._audio_path)))
            self.decoder.start()
            self.changed.emit()

    def _waveform_error(self, _error: QAudioDecoder.Error) -> None:
        self.waveform_loading = False
        self.timeline_changed.emit()
        self.changed.emit()

    def _playback_error(self, _error: QMediaPlayer.Error, error_string: str) -> None:
        if error_string and isinstance(self.parent(), QWidget):
            show_global_toast(
                self.parent(),
                trf("参考音频无法播放：{error}", error=error_string),
                kind="warning",
                duration_ms=4200,
            )


@dataclass(frozen=True, slots=True)
class TranscriptionAssistAnalysisBundle:
    harmony: HarmonyAnalysis
    instrument_matches: InstrumentMatchAnalysis
    recovered_review: TranscriptionAssistReviewState | None = None
    timbre_profile_index: object | None = None
    group_timbre_profiles: object | None = None
    group_timbre_revision: str = ""


def _semantic_revision(values: tuple[object, ...], fields: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for value in values:
        for field_name in fields:
            field_value = getattr(value, field_name, "")
            if isinstance(field_value, float):
                field_value = round(field_value, 6)
            digest.update(str(field_value).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\n")
    return digest.hexdigest()[:24]


def _close_mapped_array(value: object | None) -> None:
    mmap = getattr(value, "_mmap", None)
    if mmap is not None:
        try:
            mmap.close()
        except (OSError, ValueError):
            pass


def _instrument_preferred_roles(instrument_id: int) -> frozenset[str]:
    if instrument_id in {0x0E, 0x0F}:
        return frozenset({"bass", "rhythm"})
    if instrument_id in {0x06, 0x10, 0x07, 0x11}:
        return frozenset({"harmony", "pad", "primary_melody"})
    if instrument_id in {0x08, 0x12, 0x01, 0x02, 0x0B, 0x27, 0x28}:
        return frozenset({"primary_melody", "secondary_melody", "harmony"})
    if instrument_id in {0x00, 0x0A, 0x24, 0x25, 0x26}:
        return frozenset({"primary_melody", "harmony", "rhythm"})
    if instrument_id == 0x13:
        return frozenset({"harmony", "rhythm", "ornament"})
    if instrument_id in {0x14, 0x18, 0x1C, 0x20}:
        return frozenset({"pad", "fx", "ornament"})
    return frozenset({"harmony"})


def _instrument_articulation_profile(instrument_id: int) -> str:
    if instrument_id in {0x01, 0x02, 0x08, 0x0B, 0x0F, 0x10, 0x12, 0x27, 0x28}:
        return "sustain"
    if instrument_id in {0x04, 0x05, 0x0D, 0x13}:
        return "short"
    return "versatile"


@lru_cache(maxsize=1)
def bdo_transcription_instrument_descriptors() -> tuple[BdoInstrumentDescriptor, ...]:
    """Build advisory descriptors from the same verified profile as export."""

    descriptors: list[BdoInstrumentDescriptor] = []
    for instrument_id, rule in sorted(BDO_PROFILE.instruments.items()):
        is_percussion = instrument_id in {0x04, 0x05, 0x0D}
        descriptors.append(
            BdoInstrumentDescriptor(
                instrument_id=instrument_id,
                pitch_min=rule.pitch_min,
                pitch_max=rule.pitch_max,
                available_pitches=rule.allowed_pitches,
                preferred_roles=_instrument_preferred_roles(instrument_id),
                articulation_profile=_instrument_articulation_profile(
                    instrument_id
                ),
                is_percussion=is_percussion,
                # Program-generated Marnian families remain range/role-only
                # until an explicit in-game A/B evidence profile exists.
                timbre_evidence_approved=instrument_id
                not in {0x14, 0x18, 0x1C, 0x20},
            )
        )
    return tuple(descriptors)


class TranscriptionAssistAnalysisWorker(QThread):
    """Derive harmony and voice/instrument suggestions off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        *,
        cache_key: str,
        candidates: tuple[object, ...],
        audio_time_notes: tuple[object, ...],
        descriptors: tuple[BdoInstrumentDescriptor, ...],
        bpm: float,
        time_signature: int,
        beat_origin_audio_ms: float,
        duration_ms: float | None,
        midi_min: int,
        reference_audio_path: str = "",
        sample_map_path: str | Path = "",
        audio_root: str | Path = "",
        manual_voice_groups: tuple[ManualVoiceGroupReview, ...] = (),
        audio_fingerprint: str = "",
        pitch_offset: int = 0,
        review_state: TranscriptionAssistReviewState | None = None,
        previous_candidates: tuple[object, ...] = (),
        reuse_instrument_matches: InstrumentMatchAnalysis | None = None,
        reuse_timbre_profile_index: object | None = None,
        reuse_group_timbre_profiles: object | None = None,
        reuse_group_timbre_revision: str = "",
        allow_review_recovery: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache_key = str(cache_key)
        self.candidates = tuple(candidates)
        self.audio_time_notes = tuple(audio_time_notes)
        self.descriptors = tuple(descriptors)
        self.bpm = float(bpm)
        self.time_signature = int(time_signature)
        self.beat_origin_audio_ms = float(beat_origin_audio_ms)
        self.duration_ms = (
            None if duration_ms is None else float(duration_ms)
        )
        self.midi_min = int(midi_min)
        self.reference_audio_path = str(reference_audio_path or "")
        self.sample_map_path = Path(sample_map_path) if sample_map_path else None
        self.audio_root = Path(audio_root) if audio_root else None
        self.manual_voice_groups = tuple(manual_voice_groups)
        self.audio_fingerprint = str(audio_fingerprint or "")
        self.pitch_offset = int(pitch_offset)
        self.review_state = (
            review_state
            if isinstance(review_state, TranscriptionAssistReviewState)
            else TranscriptionAssistReviewState()
        )
        self.previous_candidates = tuple(previous_candidates)
        self.reuse_instrument_matches = reuse_instrument_matches
        self.reuse_timbre_profile_index = reuse_timbre_profile_index
        self.reuse_group_timbre_profiles = reuse_group_timbre_profiles
        self.reuse_group_timbre_revision = str(
            reuse_group_timbre_revision or ""
        )
        self.allow_review_recovery = bool(allow_review_recovery)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        frame = None
        times = None
        try:
            frame = load_transcription_evidence(self.cache_key, "frame")
            times = load_transcription_frame_times(self.cache_key)
            if frame is None or times is None:
                raise TranscriptionError(
                    "扒谱证据缓存缺失或校验失败，无法生成和声建议。"
                )
            if self._cancelled.is_set():
                self.cancelled.emit()
                return
            candidate_revision = _semantic_revision(
                self.candidates,
                (
                    "candidate_id",
                    "pitch",
                    "start_ms",
                    "duration_ms",
                    "confidence",
                ),
            )
            note_revision = _semantic_revision(
                self.audio_time_notes,
                ("pitch", "start", "dur", "vel", "ntype"),
            )
            derived_cache_key = harmony_cache_key(
                self.cache_key,
                bpm=self.bpm,
                time_signature=self.time_signature,
                beat_origin_audio_ms=self.beat_origin_audio_ms,
                candidate_revision=candidate_revision,
                note_revision=note_revision,
            )
            harmony = analyse_harmony(
                frame,
                times,
                cache_key=derived_cache_key,
                bpm=self.bpm,
                beat_origin_audio_ms=self.beat_origin_audio_ms,
                midi_min=self.midi_min,
                duration_ms=self.duration_ms,
                symbolic_candidates=self.candidates,
                symbolic_notes=self.audio_time_notes,
                cancelled=self._cancelled.is_set,
            )
            if self._cancelled.is_set():
                self.cancelled.emit()
                return
            profile_index = self.reuse_timbre_profile_index
            group_profiles = self.reuse_group_timbre_profiles
            group_profile_revision = self.reuse_group_timbre_revision
            instrument_matches = self.reuse_instrument_matches
            if instrument_matches is None:
                groups = group_voice_candidates(
                    self.candidates,
                    beat_ms=60_000.0 / max(1.0, self.bpm),
                    cancelled=self._cancelled.is_set,
                )
                if self.manual_voice_groups:
                    groups = overlay_manual_voice_groups(
                        groups,
                        self.candidates,
                        self.manual_voice_groups,
                        cancelled=self._cancelled.is_set,
                    )
                wanted_group_revision = _semantic_revision(
                    tuple(groups),
                    (
                        "group_id",
                        "candidate_ids",
                        "start_audio_ms",
                        "end_audio_ms",
                        "role",
                    ),
                )
                wanted_group_revision = hashlib.sha256(
                    (
                        f"{self.audio_fingerprint}|"
                        f"{candidate_revision}|"
                        f"{wanted_group_revision}"
                    ).encode("utf-8")
                ).hexdigest()[:24]
                instrument_profiles = {}
                sample_profile_key = ""
                if (
                    self.reference_audio_path
                    and self.sample_map_path is not None
                    and self.sample_map_path.is_file()
                    and self.audio_root is not None
                    and self.audio_root.is_dir()
                    and not self._cancelled.is_set()
                ):
                    try:
                        if profile_index is None:
                            profile_index = (
                                load_or_build_timbre_profile_index(
                                    self.sample_map_path,
                                    self.audio_root,
                                    cancelled=self._cancelled.is_set,
                                )
                            )
                        instrument_profiles = profile_index.as_mapping()
                        sample_profile_key = (
                            profile_index.sample_profile_key
                        )
                        if (
                            group_profiles is None
                            or group_profile_revision
                            != wanted_group_revision
                        ):
                            group_profiles = (
                                extract_group_timbre_profiles(
                                    self.reference_audio_path,
                                    self.candidates,
                                    groups,
                                    frame_evidence=FramePitchEvidence(
                                        times,
                                        frame,
                                        self.midi_min,
                                        1,
                                    ),
                                    cancelled=self._cancelled.is_set,
                                )
                            )
                            group_profile_revision = (
                                wanted_group_revision
                            )
                    except (
                        OSError,
                        TypeError,
                        ValueError,
                        TimbreProfileError,
                    ):
                        # Local sample evidence is optional.  The deterministic
                        # range/role fallback remains available and visibly
                        # capped.
                        instrument_profiles = {}
                        group_profiles = {}
                        group_profile_revision = wanted_group_revision
                        sample_profile_key = ""
                else:
                    group_profiles = {}
                    group_profile_revision = wanted_group_revision
                candidate_timbres = getattr(
                    group_profiles,
                    "candidate_profiles",
                    {},
                )
                if candidate_timbres:
                    manual_group_ids = {
                        str(review.group_id)
                        for review in self.manual_voice_groups
                        if not bool(getattr(review, "orphaned", False))
                    }
                    fixed_groups = tuple(
                        group
                        for group in groups
                        if group.group_id in manual_group_ids
                    )
                    refinable_groups = tuple(
                        group
                        for group in groups
                        if group.group_id not in manual_group_ids
                    )
                    refined_groups = refine_voice_groups_by_timbre(
                        refinable_groups,
                        self.candidates,
                        candidate_timbres,
                        cancelled=self._cancelled.is_set,
                    )
                    if refined_groups != refinable_groups:
                        groups = tuple(
                            sorted(
                                (*fixed_groups, *refined_groups),
                                key=lambda group: (
                                    group.start_audio_ms,
                                    group.end_audio_ms,
                                    group.group_id,
                                ),
                            )
                        )
                        group_profiles = remap_group_timbre_profiles(
                            group_profiles,
                            self.candidates,
                            groups,
                            cancelled=self._cancelled.is_set,
                        )
                instrument_matches = match_bdo_instruments(
                    groups,
                    self.candidates,
                    self.descriptors,
                    group_timbre_profiles=group_profiles or {},
                    instrument_timbre_profiles=instrument_profiles,
                    sample_profile_key=sample_profile_key,
                    pitch_offset=self.pitch_offset,
                    beat_ms=60_000.0 / max(1.0, self.bpm),
                    top_k=3,
                    cancelled=self._cancelled.is_set,
                )
            previous_revision = _semantic_revision(
                self.previous_candidates,
                (
                    "candidate_id",
                    "pitch",
                    "start_ms",
                    "duration_ms",
                    "confidence",
                ),
            )
            candidate_revision_changed = bool(
                self.previous_candidates
            ) and previous_revision != candidate_revision
            current_group_ids = {
                group.group_id for group in instrument_matches.groups
            }
            review_group_ids = {
                item.group_id
                for item in self.review_state.active_voice_groups
            }
            needs_recovery = (
                self.audio_fingerprint
                != self.review_state.audio_fingerprint
                or self.review_state.has_orphaned_reviews
                or candidate_revision_changed
                or not review_group_ids.issubset(current_group_ids)
            )
            recovered_review = None
            if needs_recovery and self.allow_review_recovery:
                recovered_review = recover_assist_review(
                    self.review_state,
                    audio_fingerprint=self.audio_fingerprint,
                    old_candidates=self.previous_candidates,
                    new_candidates=self.candidates,
                    chord_segments=harmony.chord_segments,
                    voice_groups=instrument_matches.groups,
                    force_reanchor=(
                        candidate_revision_changed
                        and self.audio_fingerprint
                        == self.review_state.audio_fingerprint
                    ),
                    cancelled=self._cancelled.is_set,
                ).state
        except (HarmonyAnalysisCancelled, InstrumentAnalysisCancelled):
            self.cancelled.emit()
        except RuntimeError:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(
                    "语义分析失败；缓存或本地音色证据不可用。"
                )
        except TranscriptionError as exc:
            self.failed.emit(str(exc))
        except (OSError, TypeError, ValueError):
            # Do not surface cache/sample paths in UI state, logs, project
            # payloads, or packaged diagnostics.
            self.failed.emit(
                "语义分析失败；缓存或本地音色证据不可用。"
            )
        except Exception:
            self.failed.emit("语义分析失败；请重新分析整首。")
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(
                    TranscriptionAssistAnalysisBundle(
                        harmony,
                        instrument_matches,
                        recovered_review,
                        profile_index,
                        group_profiles,
                        group_profile_revision,
                    )
                )
        finally:
            _close_mapped_array(frame)
            _close_mapped_array(times)


class TranscriptionAnalysisWorker(QThread):
    """Run bundled Basic Pitch inference away from the GUI/audio threads."""

    progress_changed = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        audio_path: str | Path,
        parent: QObject | None = None,
        *,
        analysis_mode: str = DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
        sensitivity: str = "balanced",
        cleanup_profile: str = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    ) -> None:
        super().__init__(parent)
        self.audio_path = Path(audio_path)
        self.analysis_mode = str(analysis_mode)
        self.sensitivity = str(sensitivity)
        self.cleanup_profile = str(cleanup_profile)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = transcribe_reference_audio(
                self.audio_path,
                self.progress_changed.emit,
                self._cancelled.is_set,
                analysis_mode=self.analysis_mode,
                sensitivity=self.sensitivity,
                cleanup_profile=self.cleanup_profile,
            )
        except TranscriptionCancelled:
            self.cancelled.emit()
        except TranscriptionError as exc:
            append_crash_log(
                "Transcription analysis failed",
                traceback.format_exc(),
            )
            self.failed.emit(str(exc))
        except Exception:
            append_crash_log(
                "Transcription analysis failed",
                traceback.format_exc(),
            )
            self.failed.emit(tr("扒谱分析失败。"))
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)


class TranscriptionRedecodeWorker(QThread):
    """Decode one A–B range from cached evidence without running ONNX."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        cache_key: str,
        start_ms: float,
        end_ms: float,
        sensitivity: str,
        parent: QObject | None = None,
        *,
        cleanup_profile: str = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    ) -> None:
        super().__init__(parent)
        self.cache_key = str(cache_key)
        self.start_ms = float(start_ms)
        self.end_ms = float(end_ms)
        self.sensitivity = str(sensitivity)
        self.cleanup_profile = str(cleanup_profile)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = redecode_transcription_interval(
                self.cache_key,
                self.start_ms,
                self.end_ms,
                sensitivity=self.sensitivity,
                cleanup_profile=self.cleanup_profile,
                context_ms=500.0,
                cancelled=self._cancelled.is_set,
            )
        except TranscriptionCancelled:
            self.cancelled.emit()
        except TranscriptionError as exc:
            append_crash_log(
                "Transcription range decode failed",
                traceback.format_exc(),
            )
            self.failed.emit(str(exc))
        except Exception:
            append_crash_log(
                "Transcription range decode failed",
                traceback.format_exc(),
            )
            self.failed.emit(tr("区间重解码失败。"))
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)


class TranscriptionCacheLoadWorker(QThread):
    """Validate and restore a cached analysis away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        cache_key: str,
        parent: QObject | None = None,
        *,
        audio_path: str | Path = "",
        expected_audio_fingerprint: str = "",
        analysis_mode: str = DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
        sensitivity: str = "balanced",
        cleanup_profile: str = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    ) -> None:
        super().__init__(parent)
        self.cache_key = str(cache_key)
        self.audio_path = Path(audio_path) if audio_path else None
        self.expected_audio_fingerprint = str(
            expected_audio_fingerprint or ""
        )
        self.analysis_mode = str(analysis_mode)
        self.sensitivity = str(sensitivity)
        self.cleanup_profile = str(cleanup_profile)
        self.current_audio_fingerprint = ""
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            initial_audio_fingerprint = ""
            if self.audio_path is not None:
                try:
                    initial_audio_fingerprint = (
                        transcription_audio_fingerprint(
                            self.audio_path,
                            cancelled=self._cancelled.is_set,
                        )
                    )
                except OSError:
                    self.succeeded.emit(None)
                    return
                self.current_audio_fingerprint = initial_audio_fingerprint
                if (
                    self.expected_audio_fingerprint
                    and initial_audio_fingerprint
                    != self.expected_audio_fingerprint
                ):
                    self.succeeded.emit(None)
                    return
            expected = (
                initial_audio_fingerprint
                or self.expected_audio_fingerprint
                or None
            )
            result = load_cached_transcription_result(
                self.cache_key,
                expected_audio_fingerprint=expected,
                cancelled=self._cancelled.is_set,
            )
            if result is not None:
                descriptor = getattr(
                    result, "evidence_descriptor", None
                )
                if (
                    descriptor is not None
                    and descriptor.analysis_mode != self.analysis_mode
                ):
                    result = None
                elif (
                    descriptor is not None
                    and (
                        descriptor.decode_sensitivity != self.sensitivity
                        or descriptor.cleanup_profile
                        != self.cleanup_profile
                        or descriptor.postprocess_version
                        != POSTPROCESS_VERSION
                        or result.postprocess_report is None
                    )
                ):
                    result = redecode_transcription_full(
                        self.cache_key,
                        sensitivity=self.sensitivity,
                        cleanup_profile=self.cleanup_profile,
                        cancelled=self._cancelled.is_set,
                    )
            if self.audio_path is not None:
                try:
                    self.current_audio_fingerprint = (
                        transcription_audio_fingerprint(
                            self.audio_path,
                            cancelled=self._cancelled.is_set,
                        )
                    )
                except OSError:
                    self.succeeded.emit(None)
                    return
                if (
                    self.current_audio_fingerprint
                    != initial_audio_fingerprint
                ):
                    self.succeeded.emit(None)
                    return
        except TranscriptionCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)


class SamplePackPrepareWorker(QThread):
    """Hash, validate, and extract one local sample pack off the GUI thread."""

    progress_changed = Signal(int)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        pack_path: str | Path,
        cache_root: str | Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.pack_path = Path(pack_path)
        self.cache_root = Path(cache_root)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            audio_root = extract_sample_pack(
                self.pack_path,
                self.cache_root,
                progress=self.progress_changed.emit,
                cancelled=self._cancelled.is_set,
            )
        except SamplePackCancelled:
            self.cancelled.emit()
        except (OSError, SamplePackError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(str(audio_root))


class GameArtImportWorker(QThread):
    """Decrypt the allow-listed game sprite into a local cache off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paz_root: str | Path,
        cache_root: str | Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.paz_root = Path(paz_root)
        self.cache_root = Path(cache_root)

    def run(self) -> None:
        try:
            report = import_game_instrument_art(
                self.paz_root,
                self.cache_root,
            )
        except (OSError, GameArtImportError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.succeeded.emit(report)


class OptimizerAnalysisWorker(QThread):
    """Run optimizer code away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str, str, bool)

    def __init__(self, arguments: tuple, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.arguments = arguments

    def run(self) -> None:
        try:
            session = analyse_with_algorithm(*self.arguments)
        except Exception as exc:
            self.failed.emit(
                str(exc) or type(exc).__name__,
                traceback.format_exc(),
                isinstance(exc, HostOptimizationError),
            )
        else:
            self.succeeded.emit(session)


class MidiOptimizeDialog(QDialog):
    """Small host UI over the versioned optimizer-plugin contract."""

    INTENSITIES = (
        ("保守", OptimizationIntensity.CONSERVATIVE),
        ("均衡", OptimizationIntensity.BALANCED),
        ("深入", OptimizationIntensity.DEEP),
    )

    def __init__(self, parent: "MidiToBdoWindow", target_track_id: int | None = None,
                 source_tracks: list[TrackState] | None = None) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.target_track_id = target_track_id
        self.source_tracks = list(source_tracks) if source_tracks is not None else parent.tracks
        self.track_checks: dict[int, QCheckBox] = {}
        self.algorithms = ()
        self.discovery_diagnostics: tuple[str, ...] = ()
        self.session = None
        self._applied_result = None
        self._analysis_started_once = False
        self._analysis_error: tuple[str, bool, bool] | None = None
        self.analysis_worker: OptimizerAnalysisWorker | None = None
        scope_title = tr(
            "单轨优化" if target_track_id is not None else "全局 MIDI 优化"
        )
        self.setWindowTitle(scope_title)
        self.resize(760, 320)
        self.setMinimumSize(680, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        title = QLabel(scope_title)
        title.setObjectName("OptimizerTitle")
        layout.addWidget(title)

        selector_card = QFrame()
        selector_card.setObjectName("OptimizerOptions")
        selector = QGridLayout(selector_card)
        selector.setContentsMargins(14, 12, 14, 12)
        selector.setHorizontalSpacing(10)
        selector.addWidget(QLabel(tr("优化算法")), 0, 0)
        self.algorithm_combo = QComboBox()
        # Built-ins use catalog source keys; individual third-party rows are
        # skipped so a plugin name that happens to equal a UI word stays exact.
        self.algorithm_combo.currentIndexChanged.connect(self._algorithm_changed)
        selector.addWidget(self.algorithm_combo, 0, 1, 1, 3)
        self.open_plugins_button = QPushButton(tr("算法包目录"))
        self.open_plugins_button.clicked.connect(self._open_plugin_directory)
        selector.addWidget(self.open_plugins_button, 0, 4)
        self.refresh_plugins_button = QPushButton(tr("刷新"))
        self.refresh_plugins_button.clicked.connect(self._reload_algorithms)
        selector.addWidget(self.refresh_plugins_button, 0, 5)
        selector.addWidget(QLabel(tr("优化强度")), 1, 0)
        self.intensity_combo = QComboBox()
        for label, value in self.INTENSITIES:
            self.intensity_combo.addItem(tr(label), value.value)
        self.intensity_combo.setCurrentIndex(1)
        self.intensity_combo.currentIndexChanged.connect(self._invalidate_preview)
        selector.addWidget(self.intensity_combo, 1, 1, 1, 2)
        self.algorithm_description = QLabel()
        self.algorithm_description.setWordWrap(True)
        self.algorithm_description.setObjectName("Muted")
        selector.addWidget(self.algorithm_description, 2, 0, 1, 6)
        self.scope_summary_label = QLabel()
        self.scope_summary_label.setObjectName("Muted")
        selector.addWidget(self.scope_summary_label, 3, 0, 1, 6)
        layout.addWidget(selector_card)

        self.summary_label = QLabel(tr("选择算法和强度，然后分析优化。"))
        self.summary_label.setObjectName("OptimizerSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.analyse_button = QPushButton(tr("分析优化"))
        self.analyse_button.clicked.connect(self._analyse)
        action_row.addWidget(self.analyse_button)
        layout.addLayout(action_row)

        self.details_button = QPushButton(tr("详细信息 ▸"))
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_button)

        self.details_container = QWidget()
        details = QVBoxLayout(self.details_container)
        details.setContentsMargins(0, 0, 0, 0)
        self.capability_label = QLabel()
        self.capability_label.setWordWrap(True)
        self.capability_label.setObjectName("Muted")
        details.addWidget(self.capability_label)

        scope_card = QFrame()
        scope_card.setObjectName("OptimizerOptions")
        scope_layout = QGridLayout(scope_card)
        scope_layout.setContentsMargins(12, 8, 12, 8)
        if target_track_id is None:
            scope_layout.addWidget(QLabel(tr("允许写入的轨道")), 0, 0, 1, 2)
            for index, track in enumerate(self.source_tracks):
                box = QCheckBox(trf(
                    "轨道 {track_id} · {track}",
                    track_id=track.track_id,
                    track=track.display_name,
                ))
                box.setChecked(True)
                box.stateChanged.connect(self._invalidate_preview)
                self.track_checks[int(track.track_id)] = box
                scope_layout.addWidget(box, 1 + index // 2, index % 2)
        else:
            track = next((item for item in self.source_tracks if int(item.track_id) == target_track_id), None)
            target_name = track.display_name if track else trv("未知轨道")
            scope_layout.addWidget(QLabel(trf(
                "目标：Track {track_id} · {track}",
                track_id=target_track_id,
                track=target_name,
            )), 0, 0)
        details.addWidget(scope_card)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setObjectName("OptimizerReport")
        details.addWidget(self.report_text, stretch=1)
        layout.addWidget(self.details_container)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.button_box = buttons
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText(tr("应用预览"))
        self.apply_button.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._toggle_details(False)
        self._reload_algorithms()

    @property
    def scope(self) -> str:
        return "single_track" if self.target_track_id is not None else "global"

    def _target_track_ids(self) -> frozenset[int]:
        if self.target_track_id is not None:
            return frozenset({self.target_track_id})
        return frozenset(track_id for track_id, box in self.track_checks.items() if box.isChecked())

    def _selected_algorithm(self):
        return self.algorithm_combo.currentData()

    def _selected_intensity(self) -> OptimizationIntensity:
        return OptimizationIntensity(str(self.intensity_combo.currentData()))

    def _reload_algorithms(self) -> None:
        previous = getattr(self._selected_algorithm(), "algorithm_id", None)
        discovery = discover_host_algorithms()
        self.discovery_diagnostics = discovery.diagnostics
        self.algorithms = tuple(item for item in discovery.algorithms if self.scope in item.scopes)
        self.algorithm_combo.blockSignals(True)
        self.algorithm_combo.clear()
        selected_index = 0
        skipped_item_indexes: list[int] = []
        for index, descriptor in enumerate(self.algorithms):
            display_name = descriptor.localized_display_name(
                tr,
                format_translate=trf,
            )
            self.algorithm_combo.addItem(display_name, descriptor)
            if descriptor.algorithm_id != BUILTIN_SAFE_ID:
                skipped_item_indexes.append(index)
            if descriptor.algorithm_id == previous:
                selected_index = index
        if self.algorithms:
            self.algorithm_combo.setCurrentIndex(selected_index)
        self.algorithm_combo.setProperty(
            "i18nSkipItemIndexes",
            tuple(skipped_item_indexes),
        )
        self.algorithm_combo.blockSignals(False)
        self._algorithm_changed()

    def _algorithm_changed(self, _index: int = -1) -> None:
        descriptor = self._selected_algorithm()
        if descriptor is None:
            self.algorithm_description.setProperty("i18nSkipText", False)
            self.algorithm_description.setText(tr("没有可用的优化算法。"))
            self.capability_label.clear()
            self.analyse_button.setEnabled(False)
        else:
            builtin = descriptor.algorithm_id == BUILTIN_SAFE_ID
            self.algorithm_description.setProperty("i18nSkipText", False)
            prepass = (
                trv(" · 先运行游戏安全预处理")
                if descriptor.requires_safe_prepass
                else ""
            )
            description = (
                trv(descriptor.description)
                if builtin
                else descriptor.description
            )
            self.algorithm_description.setText(trf(
                "{description}{prepass}",
                description=description,
                prepass=prepass,
            ))
            capability_sources = descriptor.localized_capabilities()
            scope_sources = descriptor.localized_scopes()
            capabilities = (
                tr_joinv(
                    capability_sources,
                    translate_values=builtin,
                )
                if capability_sources
                else trv("诊断")
            )
            scopes = tr_joinv(scope_sources, translate_values=builtin)
            self.capability_label.setText(trf(
                "版本 {version} · 能力：{capabilities} · 作用域：{scopes}",
                version=descriptor.version,
                capabilities=capabilities,
                scopes=scopes,
            ))
            self.analyse_button.setEnabled(True)
        self._invalidate_preview()

    def _invalidate_preview(self, _value: int = 0) -> None:
        self._update_scope_summary()
        self.session = None
        self._applied_result = None
        self._analysis_error = None
        self.apply_button.setEnabled(False)
        self._render_idle_preview()

    def _render_idle_preview(self) -> None:
        if self._selected_algorithm() is None:
            self.summary_label.setText(tr("没有可用的优化算法。"))
        elif self.analysis_worker is not None:
            self.summary_label.setText(tr("正在分析优化…"))
        elif self._analysis_started_once:
            self.summary_label.setText(tr("设置已更新，点击分析优化刷新预览。"))
        else:
            self.summary_label.setText(tr("选择算法和强度，然后分析优化。"))
        diagnostics = [
            trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(item),
            )
            for item in self.discovery_diagnostics
        ]
        self.report_text.setPlainText("\n".join(diagnostics))

    def _update_scope_summary(self) -> None:
        if self.target_track_id is not None:
            self.scope_summary_label.setText(trf("作用轨道：Track {track_id}", track_id=self.target_track_id))
            return
        selected = len(self._target_track_ids())
        self.scope_summary_label.setText(trf(
            "作用轨道：{selected} / {total}", selected=selected, total=len(self.source_tracks)
        ))

    def _toggle_details(self, visible: bool) -> None:
        self.details_container.setVisible(visible)
        self.details_button.setText(
            tr("详细信息 ▾" if visible else "详细信息 ▸")
        )
        self.resize(760, 680 if visible else 320)

    def _base_config(self) -> OptimizerConfig:
        supported_pitches = {
            instrument_id: pitches
            for instrument_id in BDO_EDITOR_PITCH_RANGES
            if (pitches := game_supported_pitches(instrument_id))
        }
        verified_articulations = set()
        if AUDIO_VALIDATION_PATH.is_file():
            try:
                payload = json.loads(AUDIO_VALIDATION_PATH.read_text(encoding="utf-8"))
                verified_articulations = {
                    (int(cell["instrument_id"]), int(cell.get("ntype", 0)))
                    for cell in payload.get("cells", []) if cell.get("verification") == "verified"
                }
            except (OSError, ValueError, TypeError, KeyError):
                verified_articulations = set()
        return OptimizerConfig(
            target_track_ids=self._target_track_ids(),
            supported_pitches=supported_pitches,
            verified_articulations=frozenset(verified_articulations),
            lyric_events=[dict(event) for event in self.parent_window.lyric_events],
            current_reverb=self.parent_window.reverb,
            current_delay=self.parent_window.delay,
            current_chorus=self.parent_window.chorus,
            allow_global_effect_write=self.target_track_id is None,
        )

    def _analyse(self) -> None:
        if self.analysis_worker is not None:
            return
        descriptor = self._selected_algorithm()
        if descriptor is None:
            return
        if not self._target_track_ids():
            self.summary_label.setText(tr("请至少选择一条允许写入的轨道。"))
            return
        self._analysis_started_once = True
        self._set_analysis_busy(True)
        self.summary_label.setText(tr("正在分析优化…"))
        arguments = (
            descriptor,
            self.source_tracks,
            self.parent_window.bpm_override or self.parent_window.bpm,
            self.parent_window.time_sig,
            BDO_ARTICULATIONS,
            self._base_config(),
            self._selected_intensity(),
            self.scope,
            frozenset(BDO_INSTRUMENT_NAMES),
        )
        worker = OptimizerAnalysisWorker(arguments, self)
        self.analysis_worker = worker
        worker.succeeded.connect(self._analysis_succeeded)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(self._analysis_finished)
        worker.start()

    def _set_analysis_busy(self, busy: bool) -> None:
        self.analyse_button.setEnabled(not busy and self._selected_algorithm() is not None)
        self.algorithm_combo.setEnabled(not busy)
        self.intensity_combo.setEnabled(not busy)
        self.open_plugins_button.setEnabled(not busy)
        self.refresh_plugins_button.setEnabled(not busy)
        for box in self.track_checks.values():
            box.setEnabled(not busy)
        cancel_button = self.button_box.button(QDialogButtonBox.Cancel)
        cancel_button.setEnabled(not busy)

    def _analysis_succeeded(self, session: object) -> None:
        self.session = session
        self._analysis_error = None
        self._render_analysis_session()

    def _render_analysis_session(self) -> None:
        session = self.session
        if session is None:
            return
        preview = session.localized_preview(tr, format_translate=trf)
        preview_summary = preview.summary or tr("分析完成")
        self.summary_label.setText(trf(
            "{summary} · 修改操作 {count}",
            summary=preview_summary,
            count=len(preview.operations),
        ))
        lines = list(preview.details)
        lines.extend(trf("诊断：{item}", item=item) for item in preview.diagnostics)
        lines.extend(
            trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(item),
            )
            for item in self.discovery_diagnostics
        )
        if not lines:
            lines.append(tr("当前输入没有需要应用的修改。"))
        self.report_text.setPlainText("\n".join(lines))
        self.apply_button.setEnabled(bool(preview.operations))

    def _render_analysis_failure(self) -> None:
        if self._analysis_error is None:
            return
        message, builtin, host_owned = self._analysis_error
        message_value = (
            _optimizer_host_message_value(message)
            if host_owned
            else message
        )
        self.summary_label.setText(trf(
            "分析失败：{message}",
            message=message_value,
        ))
        guidance = (
            tr("安全优化未应用任何修改。请先运行转换检查；处理阻断项后再试。")
            if builtin
            else tr("算法未应用任何修改。请检查算法包，或切换到 BDO 游戏安全优化。")
        )
        self.report_text.setPlainText(f"{guidance}\n\n{message_value}")
        self.apply_button.setEnabled(False)

    def retranslate_dynamic_content(self) -> None:
        """Re-render structured preview text after a live locale switch."""

        self._update_scope_summary()
        if self.session is not None:
            self._render_analysis_session()
        elif self._analysis_error is not None:
            self._render_analysis_failure()
        else:
            self._render_idle_preview()

    def _analysis_failed(
        self,
        message: str,
        traceback_text: str,
        host_owned: bool = False,
    ) -> None:
        descriptor = self._selected_algorithm()
        builtin = descriptor is not None and descriptor.bundle is None
        append_crash_log(
            "Built-in optimizer analysis failed"
            if builtin
            else "Optimizer plugin analysis failed",
            traceback_text,
        )
        self.session = None
        self._analysis_error = (message, builtin, bool(host_owned))
        self._render_analysis_failure()

    def _analysis_finished(self) -> None:
        worker = self.analysis_worker
        self.analysis_worker = None
        self._set_analysis_busy(False)
        if worker is not None:
            worker.deleteLater()

    def reject(self) -> None:
        if self.analysis_worker is not None:
            return
        super().reject()

    def _open_plugin_directory(self) -> None:
        directory = optimizer_plugin_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def optimized_tracks(self) -> list[TrackState]:
        if self.session is None:
            raise InvalidOptimizationPreview("no analysed optimization preview is available")
        if self._applied_result is None:
            self._applied_result = self.session.apply(self.source_tracks)
        return self._applied_result[0]

    def optimized_effects(self) -> tuple[int, int, tuple[int, int, int] | None] | None:
        if self.session is None:
            return None
        if self._applied_result is None:
            self._applied_result = self.session.apply(self.source_tracks)
        effect = self._applied_result[1]
        if effect is None:
            return None
        return effect.reverb, effect.delay, effect.chorus


class ConversionCheckDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.report = ""
        self.setWindowTitle(tr("转换检查"))
        self.resize(1000, 700)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel(tr("转换检查"))
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        subtitle = QLabel(tr("先处理阻断项，再逐条确认预期变化；双击问题可定位。"))
        subtitle.setObjectName("Muted")
        title_row.addWidget(subtitle, stretch=1)
        layout.addLayout(title_row)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        layout.addLayout(summary)
        self.status_card = QLabel()
        self.issue_card = QLabel()
        self.warning_card = QLabel()
        self.fix_card = QLabel()
        for card in (self.status_card, self.issue_card, self.warning_card, self.fix_card):
            card.setObjectName("CheckCard")
            card.setMinimumHeight(46)
            card.setWordWrap(True)
            summary.addWidget(card, stretch=1)

        report_label = QLabel(tr("导出摘要"))
        report_label.setObjectName("SectionLabel")
        layout.addWidget(report_label)
        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setMaximumHeight(140)
        layout.addWidget(self.report_view)

        issue_heading = QHBoxLayout()
        issue_label = QLabel(tr("问题与预期变化"))
        issue_label.setObjectName("SectionLabel")
        issue_heading.addWidget(issue_label)
        issue_hint = QLabel(tr("严重问题优先显示"))
        issue_hint.setObjectName("Muted")
        issue_heading.addWidget(issue_hint)
        issue_heading.addStretch(1)
        layout.addLayout(issue_heading)
        self.issue_list = QListWidget()
        self.issue_list.setToolTip(tr("双击问题可定位到对应轨道和音符"))
        self.issue_list.itemDoubleClicked.connect(self._focus_issue)
        layout.addWidget(self.issue_list, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.fix_btn = buttons.addButton(tr("修复可自动处理项"), QDialogButtonBox.ActionRole)
        self.fix_btn.clicked.connect(self._apply_fixes)
        copy_btn = buttons.addButton(tr("复制报告"), QDialogButtonBox.ActionRole)
        copy_btn.clicked.connect(self._copy_report)
        compare_btn = buttons.addButton(tr("比较 BDO 乐谱"), QDialogButtonBox.ActionRole)
        compare_btn.clicked.connect(self._compare_scores)
        coverage_btn = buttons.addButton(tr("样本覆盖"), QDialogButtonBox.ActionRole)
        coverage_btn.clicked.connect(self._show_sample_coverage)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self.report)

    def _apply_fixes(self) -> None:
        message = self.parent_window._apply_conversion_check_fixes()
        self._refresh()
        QMessageBox.information(self, tr("转换检查"), message)

    def _focus_issue(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.UserRole)
        if isinstance(issue, ValidationIssue):
            self.parent_window._focus_validation_issue(issue)

    def _compare_scores(self) -> None:
        first_default = str(getattr(self.parent_window, "last_export_path", "") or self.parent_window.last_output_dir)
        first, _filter = QFileDialog.getOpenFileName(
            self,
            tr("选择基准 BDO 乐谱"),
            first_default,
            tr("BDO 乐谱 (*);;所有文件 (*.*)"),
        )
        if not first:
            return
        second, _filter = QFileDialog.getOpenFileName(
            self,
            tr("选择对比 BDO 乐谱"),
            str(Path(first).parent),
            tr("BDO 乐谱 (*);;所有文件 (*.*)"),
        )
        if not second:
            return
        try:
            result = compare_scores(read_bdo_score(Path(first)), read_bdo_score(Path(second)))
        except Exception as exc:
            QMessageBox.warning(self, tr("谱面对比失败"), str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("BDO 谱面对比"))
        dialog.resize(860, 560)
        body = QVBoxLayout(dialog)
        header = QLabel(trf(
            "基准：{first}\n对比：{second}",
            first=Path(first).name,
            second=Path(second).name,
        ))
        header.setWordWrap(True)
        body.addWidget(header)
        report = QTextEdit()
        report.setReadOnly(True)
        report.setPlainText(result.summary(tr, trf))
        body.addWidget(report, stretch=1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        body.addWidget(close)
        dialog.exec()

    def _show_sample_coverage(self) -> None:
        try:
            active = selected_tracks(self.parent_window.tracks)
            coverage = sample_coverage_for_tracks(active, BDO_SAMPLE_MAP_PATH)
        except Exception as exc:
            QMessageBox.warning(self, tr("样本覆盖检查失败"), str(exc))
            return
        lines = [tr("当前工程的 Wwise 键位/力度层映射覆盖（不代表 DSP 已通过游戏 A/B）："), ""]
        for track, item in zip(active, coverage):
            lines.append(trf(
                "轨道 {track_id} · {track}: {covered}/{total} · {status}",
                track_id=track.track_id,
                track=track.display_name,
                covered=item.covered_notes,
                total=item.total_notes,
                status=_sample_coverage_status_value(item.status),
            ))
            if item.missing_note_indices:
                lines.append(trf(
                    "  缺失音符索引: {indices}",
                    indices=list(item.missing_note_indices[:24]),
                ))
        QMessageBox.information(self, tr("样本覆盖"), "\n".join(lines))

    def _refresh(self) -> None:
        analysis = self.parent_window._analyze_conversion()
        self.report = analysis["report"]
        self.report_view.setPlainText(self.report)
        self.issue_list.clear()
        severity_labels = {
            "error": "需处理",
            "warning": "需人工确认",
            "info": "变化说明",
        }
        for issue in analysis["issues"]:
            location = (
                trfv("轨道 {track_id}", track_id=issue.track_id)
                if issue.track_id is not None
                else trv("全局")
            )
            item = QListWidgetItem(trf(
                "[{severity}] {location} · {message}",
                severity=trv(severity_labels[issue.severity]),
                location=location,
                message=localized_validation_message(
                    issue,
                    tr,
                    format_translate=trf,
                ),
            ))
            item.setData(Qt.UserRole, issue)
            if issue.severity == "error":
                item.setForeground(QColor("#ef7772"))
            elif issue.severity == "warning":
                item.setForeground(QColor("#e2b968"))
            self.issue_list.addItem(item)
        if self.issue_list.count() == 0:
            item = QListWidgetItem(tr("未发现阻断项或待确认变化"))
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QColor("#79c58a"))
            self.issue_list.addItem(item)
        issue_count = analysis["issue_count"]
        warning_count = analysis["warning_count"]
        fixable_count = analysis["fixable_count"]
        if issue_count:
            status = "需处理"
        elif warning_count:
            status = "需人工确认"
        else:
            status = "可转换"
        self.status_card.setText(trf("状态\n{status}", status=trv(status)))
        self.issue_card.setText(trf("问题\n{count}", count=issue_count))
        self.warning_card.setText(trf("人工确认\n{count}", count=warning_count))
        transpose = analysis.get("suggested_transpose")
        fix_text = trf("可自动修复\n{count} 项", count=fixable_count)
        if transpose is not None:
            fix_text += trf(" · 移调 {transpose:+d}", transpose=transpose)
        self.fix_card.setText(fix_text)
        self.fix_btn.setEnabled(fixable_count > 0)

    def retranslate_dynamic_content(self) -> None:
        """Regenerate the structured check report in the active locale."""

        self._refresh()


class SettingsDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.game_art_worker: GameArtImportWorker | None = None
        self._game_art_pending_paz_root = ""
        self.selected_paz_root = str(
            parent.audio_sources.get("paz_root", "") or ""
        )
        self.setObjectName("SettingsDialog")
        self.setWindowTitle(tr("设置"))
        self.setModal(True)
        self.resize(920, 680)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 16, 22, 14)
        header_layout.setSpacing(3)
        title = QLabel(tr("设置"))
        title.setObjectName("SettingsTitle")
        subtitle = QLabel(tr("导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。"))
        self.settings_subtitle = subtitle
        subtitle.setWordWrap(True)
        subtitle.setObjectName("Muted")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        content = QWidget()
        content.setObjectName("SettingsContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.settings_nav = QListWidget()
        self.settings_nav.setObjectName("SettingsNav")
        self.settings_nav.setProperty("i18nTranslateItems", True)
        self.settings_nav.setFixedWidth(150)
        self.settings_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_pages = QStackedWidget()
        self.settings_pages.setObjectName("SettingsPages")
        general_scroll, general_page_layout = self._settings_page(
            "SettingsScroll", "SettingsGeneralPage"
        )
        midi_scroll, midi_page_layout = self._settings_page(
            "SettingsMidiScroll", "SettingsMidiPage"
        )
        audio_scroll, audio_page_layout = self._settings_page(
            "SettingsAudioScroll", "SettingsAudioPage"
        )
        for label, page in (
            (tr("通用与导出"), general_scroll),
            (tr("MIDI 与力度"), midi_scroll),
            (tr("音源与效果"), audio_scroll),
        ):
            self.settings_nav.addItem(label)
            self.settings_pages.addWidget(page)
        self.settings_nav.currentRowChanged.connect(self.settings_pages.setCurrentIndex)
        self.settings_nav.setCurrentRow(0)
        content_layout.addWidget(self.settings_nav)
        content_layout.addWidget(self.settings_pages, stretch=1)
        layout.addWidget(content, stretch=1)

        general, general_layout = self._section(
            "基础导出",
            "角色名会写入乐谱；BPM 与移调会在导出时应用。",
        )
        form = self._form_layout()
        general_layout.addLayout(form)
        general_page_layout.addWidget(general)

        self.language = QComboBox()
        self.language.setProperty("i18nSkipItems", True)
        for code, label in LANGUAGE_CHOICES:
            self.language.addItem(tr(label), code)
        language_index = self.language.findData(parent.language)
        self.language.setCurrentIndex(language_index if language_index >= 0 else 0)
        form.addRow(tr("界面语言"), self.language)

        self.char_name = QLineEdit(parent.char_name)
        form.addRow(tr("写入角色名"), self.char_name)

        self.bpm_override = QSpinBox()
        self.bpm_override.setRange(0, 240)
        self.bpm_override.setSpecialValueText(tr("使用 MIDI"))
        self.bpm_override.setValue(parent.bpm_override or 0)
        form.addRow(tr("BPM 覆盖"), self.bpm_override)

        self.transpose = QSpinBox()
        self.transpose.setRange(-48, 48)
        self.transpose.setSuffix(tr(" 半音"))
        self.transpose.setValue(parent.transpose)
        form.addRow(tr("移调"), self.transpose)

        output, output_layout = self._section(
            "输出目录",
            "转换文件保存位置。",
        )
        general_page_layout.addWidget(output)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(6)
        self.output_dir = QLineEdit(parent.output_dir_path)
        self.output_dir.setObjectName("OutputDirectoryEdit")
        self.output_dir.setPlaceholderText(tr("输出目录"))
        output_row.addWidget(self.output_dir, stretch=1)
        browse_output = PillButton(tr("选择"), "secondary")
        browse_output.setObjectName("BrowseOutputDirectoryButton")
        browse_output.clicked.connect(self._browse_output_folder)
        output_row.addWidget(browse_output)
        open_output = PillButton(tr("打开"), "ghost")
        open_output.setObjectName("OpenOutputDirectoryButton")
        open_output.clicked.connect(self._open_output_folder)
        output_row.addWidget(open_output)
        output_layout.addLayout(output_row)

        owner, owner_layout = self._section(
            "游戏编辑权限",
            "选择一份游戏内保存的曲谱，读取角色名和 Owner ID。",
        )
        general_page_layout.addWidget(owner)
        self.owner_id = parent.owner_id
        owner_row = QHBoxLayout()
        self.owner_load_button = PillButton(tr("从游戏曲谱读取"), "secondary")
        self.owner_load_button.setMinimumWidth(124)
        self.owner_load_button.setMaximumWidth(220)
        self.owner_load_button.clicked.connect(self._load_owner_id)
        self.owner_status = QLabel()
        self.owner_status.setObjectName("OwnerStatus")
        self.owner_status.setWordWrap(True)
        self.owner_status.setMinimumWidth(0)
        self.owner_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        owner_row.addWidget(self.owner_load_button, alignment=Qt.AlignTop)
        owner_row.addWidget(self.owner_status, stretch=1)
        owner_layout.addLayout(owner_row)
        self._refresh_owner_status()

        parsing, parsing_layout = self._section(
            "MIDI 解析",
            "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。",
        )
        midi_page_layout.addWidget(parsing)
        self.apply_sustain = QCheckBox(tr("读取并展开 MIDI sustain 踏板"))
        self.apply_sustain.setChecked(parent.apply_sustain)
        parsing_layout.addWidget(self.apply_sustain)

        self.flatten_tempo = QCheckBox(tr("忽略中途 tempo 变化，按主 BPM 拉平"))
        self.flatten_tempo.setChecked(parent.flatten_tempo)
        parsing_layout.addWidget(self.flatten_tempo)

        velocity, vel_layout = self._section(
            "力度处理",
            "选择一种输出力度策略；下方仅显示当前策略需要的参数。",
        )
        midi_page_layout.addWidget(velocity)
        modes = QFrame()
        modes.setObjectName("SettingsModeRow")
        modes_layout = QGridLayout(modes)
        modes_layout.setContentsMargins(0, 0, 0, 0)
        for column in range(5):
            modes_layout.setColumnStretch(column, 1)
        vel_layout.setSpacing(9)
        self.vel_radios: dict[str, QRadioButton] = {
            "layered": QRadioButton(tr("分层")),
            "stepped": QRadioButton(tr("阶梯")),
            "rescale": QRadioButton(tr("重映射")),
            "floor": QRadioButton(tr("抬底")),
            "off": QRadioButton(tr("禁用")),
        }
        for column, (mode, radio) in enumerate(self.vel_radios.items()):
            radio.setChecked(parent.velocity_mode == mode)
            radio.toggled.connect(self._sync_velocity_controls)
            modes_layout.addWidget(radio, 0, column)
        vel_layout.addWidget(modes)

        self.vel_step_base = QSpinBox()
        self.vel_step_base.setRange(0, 127)
        step_base = parent.vel_step[0] if isinstance(parent.vel_step, tuple) else (parent.vel_floor or 36)
        step_size = parent.vel_step[1] if isinstance(parent.vel_step, tuple) else (parent.vel_step or 12)
        self.vel_step_base.setValue(step_base)
        self.vel_step = QSpinBox()
        self.vel_step.setRange(1, 64)
        self.vel_step.setValue(step_size)
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel(tr("底")))
        step_row.addWidget(self.vel_step_base)
        step_row.addWidget(QLabel(tr("步长")))
        step_row.addWidget(self.vel_step)
        self.vel_step_row = QWidget()
        self.vel_step_row.setLayout(self._labeled_row("阶梯参数", step_row))
        vel_layout.addWidget(self.vel_step_row)

        self.vel_min = QSpinBox()
        self.vel_min.setRange(1, 127)
        self.vel_min.setValue((parent.vel_range or (28, 112))[0])
        self.vel_max = QSpinBox()
        self.vel_max.setRange(1, 127)
        self.vel_max.setValue((parent.vel_range or (28, 112))[1])
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel(tr("最小")))
        range_row.addWidget(self.vel_min)
        range_row.addWidget(QLabel(tr("最大")))
        range_row.addWidget(self.vel_max)
        self.vel_range_row = QWidget()
        self.vel_range_row.setLayout(self._labeled_row("重映射范围", range_row))
        vel_layout.addWidget(self.vel_range_row)

        self.vel_floor = QSpinBox()
        self.vel_floor.setRange(0, 127)
        self.vel_floor.setValue(parent.vel_floor or 36)
        floor_row = QHBoxLayout()
        floor_row.addWidget(self.vel_floor)
        floor_row.addStretch(1)
        self.vel_floor_row = QWidget()
        self.vel_floor_row.setLayout(self._labeled_row("抬底值", floor_row))
        vel_layout.addWidget(self.vel_floor_row)

        audio, audio_layout = self._section(
            "本地音源包",
            "仅用于本机近似试听，不会写入曲谱，也不会上传。",
        )
        audio_page_layout.addWidget(audio)
        self.audio_source = QLineEdit(displayed_audio_source(parent.audio_sources))
        self.audio_source.setReadOnly(True)
        self.audio_source.setPlaceholderText(tr("未选择"))
        audio_source_row = QWidget()
        audio_source_layout = QHBoxLayout(audio_source_row)
        audio_source_layout.setContentsMargins(0, 0, 0, 0)
        audio_source_layout.setSpacing(6)
        audio_source_layout.addWidget(self.audio_source, stretch=1)
        sample_pack_button = PillButton(tr("音源包"), "secondary")
        sample_pack_button.setToolTip(tr("选择 .bdosamples 音源包"))
        sample_pack_button.clicked.connect(self._browse_sample_pack)
        audio_source_layout.addWidget(sample_pack_button)
        audio_folder_button = PillButton(tr("文件夹"), "secondary")
        audio_folder_button.setToolTip(tr("选择已准备好的本地 BDO 音源目录"))
        audio_folder_button.clicked.connect(self._browse_audio_folder)
        audio_source_layout.addWidget(audio_folder_button)
        clear_audio_button = PillButton(tr("清除"), "ghost")
        clear_audio_button.clicked.connect(self.audio_source.clear)
        audio_source_layout.addWidget(clear_audio_button)
        audio_layout.addWidget(audio_source_row)

        self.instrument_art_dir = QLineEdit(parent.instrument_art_dir)
        self.instrument_art_dir.setReadOnly(True)
        self.instrument_art_dir.setPlaceholderText(tr("内置原创图标"))
        art_source_row = QWidget()
        art_source_layout = QHBoxLayout(art_source_row)
        art_source_layout.setContentsMargins(0, 0, 0, 0)
        art_source_layout.setSpacing(6)
        art_source_layout.addWidget(self.instrument_art_dir, stretch=1)
        art_folder_button = PillButton(tr("轨道背景"), "secondary")
        art_folder_button.setToolTip(
            tr("选择本地乐器图片目录；未设置时使用内置原创图标")
        )
        art_folder_button.clicked.connect(self._browse_instrument_art_folder)
        art_source_layout.addWidget(art_folder_button)
        self.game_art_button = PillButton(tr("游戏图"), "secondary")
        self.game_art_button.setToolTip(
            tr("从本机游戏 PAZ 解密乐器图；只写入本地缓存")
        )
        self.game_art_button.clicked.connect(self._import_game_art)
        art_source_layout.addWidget(self.game_art_button)
        clear_art_button = PillButton(tr("清除"), "ghost")
        clear_art_button.clicked.connect(self.instrument_art_dir.clear)
        art_source_layout.addWidget(clear_art_button)
        audio_layout.addWidget(art_source_row)

        effects, effects_layout = self._section(
            "游戏主效果",
            "每轨发送在轨道 FX；本地试听不模拟。",
        )
        effect_grid = QGridLayout()
        effect_grid.setContentsMargins(0, 0, 0, 0)
        effect_grid.setHorizontalSpacing(10)
        effect_grid.setVerticalSpacing(10)
        for column in (1, 3, 5):
            effect_grid.setColumnStretch(column, 1)
        effects_layout.addLayout(effect_grid)
        audio_page_layout.addWidget(effects)
        try:
            self._master_effect_original = MasterEffects.from_legacy(
                parent.reverb,
                parent.delay,
                parent.chorus,
            )
        except (TypeError, ValueError):
            self._master_effect_original = MasterEffects()
        self._master_effect_dirty: set[str] = set()
        self._master_effect_fields: dict[str, QSpinBox] = {}

        def configure_master_field(
            field: QSpinBox,
            name: str,
            raw_value: int,
        ) -> None:
            field.setRange(0, GAME_PERCENT_MAX)
            field.setValue(max(0, min(GAME_PERCENT_MAX, int(raw_value))))
            if int(raw_value) > GAME_PERCENT_MAX:
                field.setToolTip(
                    trf(
                        "导入原值 {value}；修改后按 0–100 写入。",
                        value=int(raw_value),
                    )
                )
            field.valueChanged.connect(
                lambda _value, effect_name=name: self._master_effect_dirty.add(
                    effect_name
                )
            )
            self._master_effect_fields[name] = field

        self.reverb = QSpinBox()
        self.reverb.setObjectName("MasterReverbTime")
        configure_master_field(
            self.reverb,
            "reverb_time",
            self._master_effect_original.reverb_time,
        )
        self.delay = QSpinBox()
        self.delay.setObjectName("MasterDelayFeedback")
        configure_master_field(
            self.delay,
            "delay_feedback",
            self._master_effect_original.delay_feedback,
        )
        effect_grid.addWidget(QLabel(tr("混响时间")), 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        effect_grid.addWidget(self.reverb, 0, 1)
        effect_grid.addWidget(QLabel(tr("延迟反馈")), 0, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        effect_grid.addWidget(self.delay, 0, 3)

        self.chorus_feedback = QSpinBox()
        self.chorus_feedback.setObjectName("MasterChorusFeedback")
        configure_master_field(
            self.chorus_feedback,
            "chorus_feedback",
            self._master_effect_original.chorus_feedback,
        )
        self.chorus_depth = QSpinBox()
        self.chorus_depth.setObjectName("MasterChorusLfoDepth")
        configure_master_field(
            self.chorus_depth,
            "chorus_lfo_depth",
            self._master_effect_original.chorus_lfo_depth,
        )
        self.chorus_freq = QSpinBox()
        self.chorus_freq.setObjectName("MasterChorusLfoFrequency")
        configure_master_field(
            self.chorus_freq,
            "chorus_lfo_frequency",
            self._master_effect_original.chorus_lfo_frequency,
        )
        for column, label, field in (
            (0, "合唱反馈", self.chorus_feedback),
            (2, "LFO 深度", self.chorus_depth),
            (4, "LFO 频率", self.chorus_freq),
        ):
            effect_grid.addWidget(QLabel(tr(label)), 1, column, alignment=Qt.AlignRight | Qt.AlignVCenter)
            effect_grid.addWidget(field, 1, column + 1)
        for field in (self.reverb, self.delay, self.chorus_feedback, self.chorus_depth, self.chorus_freq):
            field.setFixedWidth(92)
        general_page_layout.addStretch(1)
        midi_page_layout.addStretch(1)
        audio_page_layout.addStretch(1)

        self.settings_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.settings_buttons.setObjectName("SettingsButtons")
        self.settings_buttons.button(QDialogButtonBox.Ok).setText(tr("保存设置"))
        self.settings_buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        self.settings_buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        self.settings_buttons.accepted.connect(self.accept)
        self.settings_buttons.rejected.connect(self.reject)
        layout.addWidget(self.settings_buttons)
        self.settings_nav.currentRowChanged.connect(self._show_page_tip)
        self._sync_velocity_controls()

    def selected_master_effects(self) -> MasterEffects:
        """Keep imported raw bytes until a specific authoring field changes."""

        values = {
            "reverb_time": self._master_effect_original.reverb_time,
            "delay_feedback": self._master_effect_original.delay_feedback,
            "chorus_feedback": self._master_effect_original.chorus_feedback,
            "chorus_lfo_depth": self._master_effect_original.chorus_lfo_depth,
            "chorus_lfo_frequency": (
                self._master_effect_original.chorus_lfo_frequency
            ),
        }
        for name in self._master_effect_dirty:
            values[name] = self._master_effect_fields[name].value()
        return MasterEffects(**values)

    @staticmethod
    def _settings_page(
        scroll_name: str,
        page_name: str,
    ) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName(scroll_name)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName(page_name)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(18, 16, 18, 20)
        page_layout.setSpacing(12)
        page_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(page)
        return scroll, page_layout

    @staticmethod
    def _section(title_text: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("SettingsSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 15)
        layout.setSpacing(8)
        # Grid rows take the height of their taller neighbour; keep each
        # section's own controls anchored directly below its description.
        layout.setAlignment(Qt.AlignTop)
        title = QLabel(tr(title_text))
        title.setObjectName("SettingsSectionTitle")
        detail = QLabel(tr(description))
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)
        return section, layout

    @staticmethod
    def _form_layout() -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        return form

    @staticmethod
    def _labeled_row(label_text: str, row: QHBoxLayout) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        label = QLabel(tr(label_text))
        label.setObjectName("SettingsFieldLabel")
        label.setMinimumWidth(84)
        label.setMaximumWidth(180)
        label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(label)
        layout.addLayout(row, stretch=1)
        return layout

    def selected_velocity_mode(self) -> str:
        for mode, radio in self.vel_radios.items():
            if radio.isChecked():
                return mode
        return "layered"

    def _show_page_tip(self, index: int) -> None:
        if index == 2 and self.isVisible():
            show_global_toast(
                self,
                tr("轨道 FX 中的奏法会写入支持的 BDO 乐器。"),
            )

    def _browse_output_folder(self) -> None:
        current = self.output_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择输出目录"),
            start,
        )
        if selected:
            self.output_dir.setText(selected)

    def _open_output_folder(self) -> None:
        directory = Path(self.output_dir.text().strip() or DEFAULT_OUTDIR)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("输出目录不可用"),
                str(exc),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _browse_sample_pack(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, tr("选择本地音源包"), self.audio_source.text(), f"BDO Sample Pack (*{PACK_SUFFIX})"
        )
        if selected:
            self.audio_source.setText(selected)

    def _browse_audio_folder(self) -> None:
        current = self.audio_source.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择本地音源目录"),
            start,
        )
        if selected:
            self.audio_source.setText(selected)

    def _browse_instrument_art_folder(self) -> None:
        current = self.instrument_art_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择乐器背景目录"),
            start,
        )
        if selected:
            self.instrument_art_dir.setText(selected)

    def _import_game_art(self) -> None:
        if self.game_art_worker is not None:
            return
        current = self.selected_paz_root.strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择游戏 PAZ 目录"),
            start,
        )
        if not selected:
            return
        self._game_art_pending_paz_root = selected
        worker = GameArtImportWorker(
            selected,
            GAME_ART_CACHE_DIR,
            self,
        )
        self.game_art_worker = worker
        self.game_art_button.setEnabled(False)
        self.game_art_button.setText(tr("解密中…"))
        for role in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
            button = self.settings_buttons.button(role)
            if button is not None:
                button.setEnabled(False)
        worker.succeeded.connect(self._game_art_import_succeeded)
        worker.failed.connect(self._game_art_import_failed)
        worker.finished.connect(self._game_art_import_finished)
        worker.start()

    def _game_art_import_succeeded(self, report: object) -> None:
        output_dir = str(getattr(report, "output_dir", "") or "")
        image_count = int(getattr(report, "image_count", 0) or 0)
        if output_dir:
            self.instrument_art_dir.setText(output_dir)
            self.selected_paz_root = self._game_art_pending_paz_root
        show_global_toast(
            self,
            trf("已解密 {count} 张游戏乐器图", count=image_count),
            kind="success",
        )

    def _game_art_import_failed(self, detail: str) -> None:
        QMessageBox.warning(
            self,
            tr("游戏图不可用"),
            trf("无法读取游戏乐器图：{detail}", detail=detail),
        )

    def _game_art_import_finished(self) -> None:
        worker = self.game_art_worker
        self.game_art_worker = None
        self._game_art_pending_paz_root = ""
        self.game_art_button.setText(tr("游戏图"))
        self.game_art_button.setEnabled(True)
        for role in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
            button = self.settings_buttons.button(role)
            if button is not None:
                button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def reject(self) -> None:
        if self.game_art_worker is not None:
            show_global_toast(self, tr("正在解密游戏图"))
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self.game_art_worker is not None:
            event.ignore()
            show_global_toast(self, tr("正在解密游戏图"))
            return
        super().closeEvent(event)

    def _refresh_owner_status(self, error: str = "") -> None:
        if error:
            self.owner_status.setText(error)
            self.owner_status.setProperty("ownerError", True)
        elif self.owner_id:
            self.owner_status.setText(trf("已读取 Owner ID：0x{owner_id:08x}", owner_id=self.owner_id))
            self.owner_status.setProperty("ownerError", False)
        else:
            self.owner_status.setText(
                tr("未读取 Owner ID；导出的曲谱无法在游戏内编辑。")
            )
            self.owner_status.setProperty("ownerError", False)
        self.owner_status.style().unpolish(self.owner_status)
        self.owner_status.style().polish(self.owner_status)

    def _load_owner_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择游戏内保存的曲谱文件"),
            str(default_game_music_dir()),
            tr("黑色沙漠曲谱文件 (*);;所有文件 (*.*)"),
        )
        if not path:
            return
        try:
            snapshot = read_bdo_score(Path(path), allow_trailing_data=True)
            owner_id = int(snapshot.owner_id)
            char_name = snapshot.character_name_1 or snapshot.character_name_2
            if owner_id == 0:
                self._refresh_owner_status(
                    tr("未读取到有效 Owner ID，请选择游戏内保存的曲谱。")
                )
                return
        except ValueError:
            self._refresh_owner_status(
                tr("文件无法读取；请使用游戏内保存的曲谱。")
            )
            return
        except Exception as exc:
            self._refresh_owner_status(trf("读取失败：{error}", error=exc))
            return
        self.owner_id = owner_id
        if char_name:
            self.char_name.setText(char_name)
        self._refresh_owner_status()

    def _sync_velocity_controls(self) -> None:
        mode = self.selected_velocity_mode()
        step_enabled = mode == "stepped"
        range_enabled = mode == "rescale"
        floor_enabled = mode in {"floor", "stepped"}
        for widget in (self.vel_step_base, self.vel_step):
            widget.setEnabled(step_enabled)
        for widget in (self.vel_min, self.vel_max):
            widget.setEnabled(range_enabled)
        self.vel_floor.setEnabled(floor_enabled)
        self.vel_step_row.setVisible(step_enabled)
        self.vel_range_row.setVisible(range_enabled)
        self.vel_floor_row.setVisible(floor_enabled)


class MidiToBdoWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            self.widget_style_name = configure_widget_style(app)
        else:
            self.widget_style_name = ""
        self.setWindowTitle(f"BDO Music Composer v{__version__}")
        self.resize(1360, 820)
        self.setMinimumSize(1160, 720)

        self.config = load_config()
        self.language = str(self.config.get("language", "auto"))
        self.owner_id = 0
        self.source_format = "midi"
        self.bdo_source_snapshot = None
        self.bdo_source_document = None
        self.tracks: list[TrackState] = []
        self.lyric_events: list[dict] = []
        self.reference_audio_path = ""
        self.reference_audio_relink_required = False
        self.reference_audio_offset_ms = 0.0
        self.beat_origin_ms = 0.0
        self.reference_layer_settings = normalize_reference_layer_settings(
            DEFAULT_REFERENCE_LAYER_SETTINGS
        )
        self.transcription_session = TranscriptionSession()
        self.transcription_result: TranscriptionResult | None = None
        self.workspace_transcription_worker: QThread | None = None
        self.workspace_transcription_generation = 0
        self._pending_transcription_cleanup_profile: (
            tuple[int, str, str] | None
        ) = None
        self.transcription_assist_worker: QThread | None = None
        self.sample_pack_worker: SamplePackPrepareWorker | None = None
        self.transcription_assist_generation = 0
        self.transcription_assist_restart_pending = False
        self.transcription_assist_restart_harmony_only = False
        self.transcription_assist_restart_allow_review_recovery = True
        self.automatic_harmony_analysis: HarmonyAnalysis | None = None
        self.automatic_instrument_match_analysis: InstrumentMatchAnalysis | None = None
        self.transcription_timbre_profile_index: object | None = None
        self.transcription_group_timbre_profiles: object | None = None
        self.transcription_group_timbre_revision = ""
        self.harmony_analysis: HarmonyAnalysis | None = None
        self.instrument_match_analysis: InstrumentMatchAnalysis | None = None
        self.transcription_assist_review = TranscriptionAssistReviewState()
        self.transcription_assist_previous_candidates: tuple[object, ...] = ()
        self.transcription_assist_review_undo: list[
            TranscriptionAssistReviewState
        ] = []
        self.transcription_assist_review_redo: list[
            TranscriptionAssistReviewState
        ] = []
        self.transcription_review_action_undo: list[str] = []
        self.transcription_review_action_redo: list[str] = []
        self.active_voice_group_id = ""
        self.loop_current_voice_group = False
        self.transcription_assist_refresh_timer = QTimer(self)
        self.transcription_assist_refresh_timer.setSingleShot(True)
        self.transcription_assist_refresh_timer.setInterval(320)
        self.transcription_assist_refresh_timer.timeout.connect(
            lambda: self._start_transcription_assist_analysis(
                harmony_only=True
            )
        )
        self.workspace_close_pending = False
        self.active_transcription_editor: MidiNoteEditorDialog | None = None
        self.transcription_analysis_busy = False
        self.transcription_analysis_progress: int | None = None
        self._transcription_ui_status_spec = trv(
            "载入参考音频后可开始整首分析"
        )
        self.transcription_ui_status = str(self._transcription_ui_status_spec)
        self.pending_transcription_review_payload: dict = {}
        self.selected_track: TrackState | None = None
        self.bpm = 120
        self.time_sig = 4
        self.tempo_changes = 1
        self.worker: ConvertWorker | None = None
        self.preview_generation = 0
        self.audio_sources = audio_source_config(self.config)
        self.instrument_art_dir = str(
            self.config.get("instrument_art_dir", "") or ""
        )
        self.config.setdefault("audio_sources", self.audio_sources)
        save_config(self.config)
        self.realtime_audio = BdoRealtimeAudioEngine(self, self.audio_sources)
        self.realtime_preview_active = False
        self.realtime_preview_loading = False
        self.realtime_preview_start_ms = 0.0
        self.realtime_preview_tracks = []
        self.realtime_validation_state = "approximate"
        self.realtime_status_timer = QTimer(self)
        # The mixer owns its own thread. A ~60 FPS playhead feels continuous,
        # while visible-range painting keeps dense projects responsive.
        self.realtime_status_timer.setInterval(16)
        self.realtime_status_timer.timeout.connect(self._poll_realtime_audio_status)
        self.reference_status_timer = QTimer(self)
        self.reference_status_timer.setInterval(16)
        self.reference_status_timer.timeout.connect(self._poll_reference_audio_status)
        self.reference_last_resync_at = 0.0
        self.last_reported_underruns = 0
        self.process_metrics_sampler = ProcessMetricsSampler()
        self.process_metrics_timer = QTimer(self)
        self.process_metrics_timer.setInterval(1000)
        self.process_metrics_timer.setTimerType(Qt.VeryCoarseTimer)
        self.process_metrics_timer.timeout.connect(self._update_process_metrics)
        self.output_dir_path = str(
            self.config.get("output_dir", "") or DEFAULT_OUTDIR
        )
        self.last_output_dir = Path(self.output_dir_path)
        self.autosave_project_dir: Path | None = None
        self.autosave_source_copy: Path | None = None
        self.loading_project = False
        self.research_metadata = {
            "profile_id": BDO_PROFILE.profile_id,
            "ab_experiments": [],
        }
        self.project_commands = ProjectCommandStack()
        self.conversion_check_dirty = False
        self.check_blink_timer = QTimer(self)
        self.check_blink_timer.timeout.connect(self._blink_conversion_check_button)
        self.check_blink_ticks = 0
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._flush_autosave)
        self.pending_autosave_reason = ""
        saved_settings = self.config.get("conversion_settings", {})
        self.char_name = saved_settings.get("char_name", "MIDI")
        self.bpm_override = saved_settings.get("bpm_override") or None
        self.transpose = int(saved_settings.get("transpose", 0))
        self.apply_sustain = bool(saved_settings.get("apply_sustain", True))
        self.flatten_tempo = bool(saved_settings.get("flatten_tempo", False))
        self.velocity_mode = saved_settings.get("velocity_mode", "layered")
        self.vel_range = tuple(saved_settings["vel_range"]) if saved_settings.get("vel_range") else None
        self.vel_floor = saved_settings.get("vel_floor")
        saved_vel_step = saved_settings.get("vel_step")
        self.vel_step = tuple(saved_vel_step) if isinstance(saved_vel_step, list) else saved_vel_step
        self.reverb = int(saved_settings.get("reverb", 0))
        self.delay = int(saved_settings.get("delay", 0))
        saved_chorus = saved_settings.get("chorus")
        if isinstance(saved_chorus, dict):
            self.chorus = (
                int(saved_chorus.get("feedback", 0)),
                int(saved_chorus.get("depth", 0)),
                int(saved_chorus.get("freq", 0)),
            )
        elif saved_chorus:
            self.chorus = tuple(saved_chorus)
        else:
            self.chorus = None

        self._build_ui()
        self._apply_responsive_density()
        self.project_undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.project_undo_shortcut.activated.connect(self._undo_project)
        self.project_redo_shortcut = QShortcut(QKeySequence.Redo, self)
        self.project_redo_shortcut.activated.connect(self._redo_project)
        self._apply_style()
        self._sync_preview_state()
        self._update_process_metrics()
        self.process_metrics_timer.start()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        # Fixed toolbar frames a full-bleed timeline workspace.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("MainPages")
        self.home_page = self._build_home_page()
        self.workspace_page = QWidget()
        self.workspace_page.setObjectName("WorkspacePage")
        workspace_layout = QVBoxLayout(self.workspace_page)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self._create_workspace_status_state()
        workspace_layout.addWidget(self._build_timeline_panel(), stretch=1)
        workspace_layout.addWidget(self._build_performance_strip())
        self.page_stack.addWidget(self.home_page)
        self.page_stack.addWidget(self.workspace_page)
        root.addWidget(self.page_stack, stretch=1)
        self._refresh_home()
        self._set_home_toolbar_mode(True)

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(5)

        command_group = QFrame()
        command_group.setObjectName("CommandGroup")
        command_layout = QHBoxLayout(command_group)
        command_layout.setContentsMargins(1, 1, 1, 1)
        command_layout.setSpacing(1)

        self.toolbar_home_btn = PillButton(tr("主页"), "secondary", FluentSymbol.HOME)
        self.toolbar_home_btn.clicked.connect(self._show_home)
        command_layout.addWidget(self.toolbar_home_btn)

        self.toolbar_new_project_btn = PillButton(tr("新建项目"), "secondary", FluentSymbol.PROJECT)
        self.toolbar_new_project_btn.clicked.connect(self._new_project)
        command_layout.addWidget(self.toolbar_new_project_btn)

        self.toolbar_import_btn = PillButton(tr("导入 MIDI"), "primary", FluentSymbol.OPEN)
        self.toolbar_import_btn.clicked.connect(self._browse_midi)
        command_layout.addWidget(self.toolbar_import_btn)

        self.toolbar_open_project_btn = PillButton(tr("打开工程"), "secondary", FluentSymbol.PROJECT)
        self.toolbar_open_project_btn.clicked.connect(self._open_project)
        command_layout.addWidget(self.toolbar_open_project_btn)

        self.toolbar_optimize_btn = PillButton(tr("全局优化"), "secondary", FluentSymbol.OPTIMIZE)
        self.toolbar_optimize_btn.clicked.connect(lambda: self._open_midi_optimizer(None))
        command_layout.addWidget(self.toolbar_optimize_btn)
        layout.addWidget(command_group)

        self.workspace_toolbar_separator = QFrame()
        self.workspace_toolbar_separator.setObjectName("ToolbarSeparator")
        self.workspace_toolbar_separator.setFrameShape(QFrame.VLine)
        layout.addWidget(self.workspace_toolbar_separator)

        self.file_label = ElidedLabel(
            tr("未导入 MIDI"), maximum_hint_width=180
        )
        self.file_label.setObjectName("ToolbarText")
        layout.addWidget(self.file_label)
        layout.addStretch(1)

        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText(tr("曲谱名"))
        self.output_name.setFixedWidth(170)
        self.output_name.editingFinished.connect(lambda: self._autosave_project("output name"))
        layout.addWidget(self.output_name)

        self.preview_source_badge = ElidedLabel(
            tr("游戏映射：检测中"), maximum_hint_width=210
        )
        self.preview_source_badge.setObjectName("ToolbarBadge")
        layout.addWidget(self.preview_source_badge)

        separator = QFrame()
        separator.setObjectName("ToolbarSeparator")
        separator.setFrameShape(QFrame.VLine)
        layout.addWidget(separator)

        utility_group = QFrame()
        utility_group.setObjectName("CommandGroup")
        utility_layout = QHBoxLayout(utility_group)
        utility_layout.setContentsMargins(1, 1, 1, 1)
        utility_layout.setSpacing(1)

        self.toolbar_thanks_btn = PillButton(tr("致谢"), "secondary", FluentSymbol.INFO)
        self.toolbar_thanks_btn.clicked.connect(self._show_acknowledgements)
        utility_layout.addWidget(self.toolbar_thanks_btn)

        self.toolbar_settings_btn = PillButton(tr("设置"), "secondary", FluentSymbol.SETTINGS)
        self.toolbar_settings_btn.clicked.connect(self._open_settings)
        utility_layout.addWidget(self.toolbar_settings_btn)
        layout.addWidget(utility_group)

        self.convert_button = PillButton(tr("转换"), "convert", FluentSymbol.EXPORT)
        self.convert_button.clicked.connect(self._convert)
        layout.addWidget(self.convert_button)
        return bar

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("HomePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("HomeHero")
        header = QHBoxLayout(hero)
        header.setContentsMargins(22, 17, 18, 17)
        header.setSpacing(18)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        eyebrow = QLabel("BDO MUSIC COMPOSER")
        eyebrow.setObjectName("HomeEyebrow")
        title = QLabel(tr("曲谱主页"))
        title.setObjectName("HomeTitle")
        heading.addWidget(eyebrow)
        heading.addWidget(title)
        header.addLayout(heading)
        header.addStretch(1)
        new_btn = PillButton(tr("新建项目"), "primary", FluentSymbol.PROJECT)
        new_btn.setProperty("homeAction", True)
        new_btn.clicked.connect(self._new_project)
        header.addWidget(new_btn)
        import_btn = PillButton(tr("导入 MIDI"), "primary", FluentSymbol.OPEN)
        import_btn.setProperty("homeAction", True)
        import_btn.clicked.connect(self._browse_midi)
        header.addWidget(import_btn)
        open_btn = PillButton(tr("打开工程"), "secondary", FluentSymbol.PROJECT)
        open_btn.setProperty("homeAction", True)
        open_btn.clicked.connect(self._open_project)
        header.addWidget(open_btn)
        refresh_btn = PillButton(tr("刷新"), "ghost")
        refresh_btn.setProperty("homeAction", True)
        refresh_btn.clicked.connect(self._refresh_home)
        header.addWidget(refresh_btn)
        layout.addWidget(hero)

        content = QHBoxLayout()
        content.setSpacing(0)
        game_card, self.game_score_list, game_footer, self.game_score_count = self._build_home_card(
            "游戏曲谱",
            "打开目录",
            "primary",
        )
        game_footer.clicked.connect(self._open_game_music_directory)
        content.addWidget(game_card, stretch=5)

        side = QWidget()
        side.setObjectName("HomeSideColumn")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(18, 0, 0, 0)
        side_layout.setSpacing(0)
        project_card, self.project_list, project_footer, self.project_count = self._build_home_card(
            "项目",
            "打开工程",
            "primary",
        )
        project_footer.clicked.connect(self._open_project)
        side_layout.addWidget(project_card, stretch=1)
        content.addWidget(side, stretch=4)
        layout.addLayout(content, stretch=1)

        self.game_score_list.itemDoubleClicked.connect(self._open_home_item)
        self.project_list.itemDoubleClicked.connect(self._open_home_item)
        return page

    def _build_home_card(
        self,
        title: str,
        action: str,
        density: str,
    ) -> tuple[QWidget, QListWidget, QPushButton, QLabel]:
        card = QFrame()
        card.setObjectName("HomeCard")
        card.setProperty("density", density)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 15, 16, 14)
        layout.setSpacing(8)
        card_header = QHBoxLayout()
        card_header.setSpacing(8)
        title_label = QLabel(tr(title))
        title_label.setObjectName("HomeCardTitle")
        count_label = QLabel("0")
        count_label.setObjectName("HomeCount")
        count_label.setAlignment(Qt.AlignCenter)
        card_header.addWidget(title_label)
        card_header.addWidget(count_label)
        card_header.addStretch(1)
        item_list = QListWidget()
        item_list.setObjectName("HomeList")
        item_list.setProperty("i18nSkipItems", True)
        item_list.setSpacing(2)
        action_button = PillButton(tr(action), "ghost")
        action_button.setProperty("homeAction", True)
        layout.addLayout(card_header)
        layout.addWidget(item_list, stretch=1)
        layout.addWidget(action_button, alignment=Qt.AlignLeft)
        return card, item_list, action_button, count_label

    @staticmethod
    def _add_home_entry(target: QListWidget, entry: HomeEntry) -> None:
        item = QListWidgetItem(f"{entry.label}\n{entry.detail}")
        item.setData(Qt.UserRole, {"kind": entry.kind, "path": str(entry.path), "label": entry.label})
        tooltip = str(entry.path)
        if entry.version_count > 1:
            tooltip += trf("\n已合并 {count} 个版本，双击打开最新工程", count=entry.version_count)
        item.setToolTip(tooltip)
        item.setSizeHint(QSize(0, 58))
        target.addItem(item)

    def _refresh_home(self) -> None:
        if not hasattr(self, "game_score_list"):
            return
        self.game_score_list.clear()
        self.project_list.clear()
        for entry in scan_game_scores(default_game_music_dir()):
            self._add_home_entry(self.game_score_list, entry)
        for entry in scan_example_projects(EXAMPLE_PROJECTS_DIR):
            self._add_home_entry(self.project_list, entry)
        project_entries = scan_local_projects(AUTO_SAVE_DIR, limit=400)
        for raw in self.config.get("recent_items", []):
            if not isinstance(raw, dict):
                continue
            path = Path(str(raw.get("path") or ""))
            kind = str(raw.get("kind") or "")
            if kind not in {"midi", "project", "bdo"} or not path.is_file():
                continue
            try:
                opened_at = float(raw.get("opened_at") or path.stat().st_mtime)
            except (OSError, TypeError, ValueError):
                continue
            label = str(raw.get("label") or path.stem)
            recent_entry = HomeEntry(kind, label, path, _home_timestamp(opened_at), opened_at)
            project_entries.append(recent_entry)
        for entry in merge_home_project_entries(project_entries):
            self._add_home_entry(
                self.project_list,
                entry,
            )
        self.game_score_count.setText(str(self.game_score_list.count()))
        self.project_count.setText(str(self.project_list.count()))
        if self.game_score_list.count() == 0:
            self.game_score_list.addItem(tr("未找到游戏曲谱"))
        if self.project_list.count() == 0:
            self.project_list.addItem(tr("暂无项目"))

    def _show_home(self) -> None:
        self._stop_preview(reset_playhead=False)
        self._refresh_home()
        self.page_stack.setCurrentWidget(self.home_page)
        self._set_home_toolbar_mode(True)
        self.show_toast(
            tr("双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。")
        )

    def _show_workspace(self) -> None:
        self.page_stack.setCurrentWidget(self.workspace_page)
        self._set_home_toolbar_mode(False)

    def _reference_audio_changed(self, path: str) -> None:
        previous_path = self.reference_audio_path
        review_state = self.transcription_session.state
        relinking_saved_audio = bool(
            self.reference_audio_relink_required
            and not previous_path
            and path
        )
        audio_changed = bool(
            previous_path != path
            and not self.loading_project
            and not relinking_saved_audio
            and (
                previous_path
                or review_state.cache_key
                or self.transcription_result is not None
            )
        )
        editor = self.active_transcription_editor
        if (
            audio_changed
            and editor is not None
            and editor.has_transcription_staging()
        ):
            QMessageBox.warning(
                editor,
                tr("存在未提交候选草稿"),
                tr("请先应用、撤销或清除本次暂存，再更换音频或重新分析。"),
            )
            QTimer.singleShot(
                0,
                lambda old_path=previous_path:
                self.reference_audio.set_audio_path(old_path),
            )
            return
        if audio_changed and review_state.pending_routes:
            answer = QMessageBox.question(
                self,
                tr("更换参考音频"),
                tr(
                    "当前仍有尚未应用的扒谱路由。更换或卸载音频会丢弃这些"
                    "审阅路由；已应用的正式音符不受影响。是否继续？"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                QTimer.singleShot(
                    0,
                    lambda old_path=previous_path:
                    self.reference_audio.set_audio_path(old_path),
                )
                return
        if audio_changed:
            # Invalidate queued success/failure callbacks before cancelling.
            # The worker pointer remains until its own finished signal so a
            # second analysis cannot start while the old thread is draining.
            self._rollback_cleanup_profile_transaction()
            self.workspace_transcription_generation += 1
            self.transcription_assist_generation += 1
            self.transcription_assist_restart_pending = False
            self.transcription_assist_restart_harmony_only = False
            self.transcription_assist_restart_allow_review_recovery = True
            if self.workspace_transcription_worker is not None:
                cancel = getattr(self.workspace_transcription_worker, "cancel", None)
                if callable(cancel):
                    cancel()
            if self.transcription_assist_worker is not None:
                cancel = getattr(self.transcription_assist_worker, "cancel", None)
                if callable(cancel):
                    cancel()
            if editor is not None:
                editor.release_transcription_resources()
            self.transcription_assist_previous_candidates = tuple(
                self.transcription_session.candidates
            )
            self.transcription_assist_review = (
                isolate_assist_review_for_audio(
                    self.transcription_assist_review,
                    "",
                )
            )
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.transcription_result = None
            self.transcription_session = TranscriptionSession(
                state=TranscriptionSessionState(
                    region=review_state.region,
                    analysis_mode=review_state.analysis_mode,
                    sensitivity=review_state.sensitivity,
                    cleanup_profile=review_state.cleanup_profile,
                )
            )
            self._clear_transcription_review_history()
        self.reference_audio_path = path
        self.reference_audio_relink_required = False
        self._refresh_transcription_workspace()
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio", immediate=True)
        if (
            relinking_saved_audio
            and review_state.cache_key
            and not self.transcription_session.candidates
            and self.workspace_transcription_worker is None
        ):
            # The cache worker validates the newly linked audio fingerprint
            # before restoring review state; relinking itself must not erase it.
            QTimer.singleShot(0, self._restore_cached_transcription)
        self._sync_preview_state()

    def _reference_volume_changed(self, _volume: int) -> None:
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio volume")

    def _reference_offset_changed(self, offset_ms: float) -> None:
        editor = self.active_transcription_editor
        if (
            editor is not None
            and editor.has_transcription_staging()
            and not math.isclose(
                float(offset_ms),
                float(self.reference_audio_offset_ms),
                abs_tol=0.001,
            )
        ):
            QMessageBox.warning(
                editor,
                tr("存在未提交候选草稿"),
                tr("请先应用、撤销或清除本次暂存，再修改音频对齐。"),
            )
            self.reference_audio.set_project_offset_ms(
                self.reference_audio_offset_ms,
                notify=False,
            )
            return
        self.reference_audio_offset_ms = float(offset_ms)
        self._refresh_transcription_workspace()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis(harmony_only=True)
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio offset")

    def _set_reference_alignment(
        self,
        offset_ms: float,
        beat_origin_ms: float,
        *,
        autosave: bool = False,
    ) -> None:
        self.reference_audio_offset_ms = float(offset_ms)
        self.beat_origin_ms = float(beat_origin_ms)
        self.reference_audio.set_project_offset_ms(
            self.reference_audio_offset_ms,
            notify=False,
        )
        if hasattr(self, "timeline"):
            self.timeline.set_musical_grid(
                self.bpm_override or self.bpm,
                self.time_sig,
                self.beat_origin_ms,
            )
        self._refresh_transcription_workspace()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis(harmony_only=True)
        if autosave and self.tracks and not self.loading_project:
            self._autosave_project("reference alignment", immediate=True)

    def _reference_playback_state_changed(
        self, state: QMediaPlayer.PlaybackState,
    ) -> None:
        if (
            state != QMediaPlayer.PlaybackState.PlayingState
            and not self.realtime_preview_active
        ):
            self.reference_status_timer.stop()
        self._sync_preview_state()

    def _set_home_toolbar_mode(self, home: bool) -> None:
        for widget in (
            self.toolbar_new_project_btn,
            self.toolbar_import_btn,
            self.toolbar_open_project_btn,
            self.toolbar_optimize_btn,
            self.workspace_toolbar_separator,
            self.file_label,
            self.output_name,
            self.preview_source_badge,
            self.convert_button,
        ):
            widget.setVisible(not home)
        self._apply_responsive_density()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toolbar_home_btn"):
            self._apply_responsive_density()

    @staticmethod
    def _set_responsive_icon_button(
        button: QPushButton,
        source_text: str,
        compact: bool,
    ) -> None:
        label = tr(source_text)
        button.setAccessibleName(label)
        button.setToolTip(label)
        if compact:
            button.setText("")
            button.setFixedWidth(34)
        else:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setText(label)

    def _apply_responsive_density(self) -> None:
        """Keep both command rails usable at the supported narrow width."""

        compact = self.width() < MAIN_VERBOSE_CONTROLS_MIN_WIDTH
        for button, source in (
            (self.toolbar_home_btn, "主页"),
            (self.toolbar_new_project_btn, "新建项目"),
            (self.toolbar_import_btn, "导入 MIDI"),
            (self.toolbar_open_project_btn, "打开工程"),
            (self.toolbar_optimize_btn, "全局优化"),
            (self.toolbar_thanks_btn, "致谢"),
            (self.toolbar_settings_btn, "设置"),
        ):
            self._set_responsive_icon_button(button, source, compact)

        if not hasattr(self, "play_button"):
            return
        self._timeline_controls_compact = compact
        for button, source in (
            (self.pause_button, "暂停"),
            (self.stop_button, "停止"),
            (self.add_track_button, "新建轨道"),
            (self.timeline_fit_btn, "显示全部时间轴"),
        ):
            self._set_responsive_icon_button(button, source, compact)
        self.timeline_loop_box.setAccessibleName(tr("循环区间"))
        self.timeline_loop_box.setText("" if compact else tr("循环区间"))
        self.timeline_zoom_label.setVisible(not compact)
        self.timeline_pan_label.setVisible(not compact)
        self.timeline_zoom.setFixedWidth(80 if compact else 104)
        self.timeline_pan.setFixedWidth(84 if compact else 112)
        self.transcription_entry_button.setText(
            tr("扒谱") if compact else tr("扒谱模式")
        )
        self._sync_preview_state()

    def _new_project(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            tr("新建项目"),
            tr("项目名称"),
            QLineEdit.Normal,
            tr("未命名项目"),
        )
        if accepted and name.strip():
            self._create_new_project(name)

    def _create_new_project(self, name: str) -> None:
        project_name = safe_filename(name.strip(), tr("未命名项目"))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        project_dir = AUTO_SAVE_DIR / f"{project_name}_{stamp}"
        suffix = 2
        while project_dir.exists():
            project_dir = AUTO_SAVE_DIR / f"{project_name}_{stamp}_{suffix}"
            suffix += 1

        self.loading_project = True
        try:
            self._stop_preview()
            self.project_commands.clear()
            if self.active_transcription_editor is not None:
                self.active_transcription_editor.release_transcription_resources()
            self.reference_layer_settings = normalize_reference_layer_settings(
                DEFAULT_REFERENCE_LAYER_SETTINGS
            )
            self.transcription_session = TranscriptionSession()
            self.transcription_result = None
            self.transcription_assist_review = (
                TranscriptionAssistReviewState()
            )
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self._clear_transcription_review_history()
            self._clear_track_selection()
            self.reference_audio.set_audio_path(None, notify=False)
            self.reference_audio.set_volume_percent(50, notify=False)
            self._set_reference_alignment(0.0, 0.0)
            self.reference_audio_path = ""
            self.reference_audio_relink_required = False
            self.source_format = "project"
            self.bdo_source_snapshot = None
            self.bdo_source_document = None
            self.midi_path = ""
            self.autosave_project_dir = project_dir
            self.autosave_source_copy = None
            self.owner_id = 0
            self.bpm = 120
            self.time_sig = 4
            self.tempo_changes = 1
            self.lyric_events = []
            self.bpm_override = None
            self.transpose = 0
            self.velocity_mode = "layered"
            self.vel_range = None
            self.vel_floor = None
            self.vel_step = None
            instrument_id = gm_to_bdo_instrument(0, False)
            instrument_name = _ui_bdo_instrument_name(instrument_id)
            self.tracks = [
                TrackState(
                    track_id=0,
                    notes=[],
                    gm_program=0,
                    is_percussion=False,
                    display_name=trf(
                        "新建轨道 {number} · {instrument}",
                        number=1,
                        instrument=instrument_name,
                    ),
                    bdo_instrument_id=instrument_id,
                    color=TRACK_COLORS[0],
                    effect_settings_placeholder={
                        "track_effects_enabled": False,
                        "note_effects_reserved": True,
                    },
                )
            ]
            self.file_label.setProperty("i18nSkip", False)
            self.file_label.setProperty("i18nSkipText", False)
            self.file_label.setText(
                trf("{project} · 空白项目", project=project_name)
            )
            self.output_name.setText(project_name)
            self._refresh_tracks()
            self._reset_timeline_position()
            self._select_track(self.tracks[0])
            self._sync_preview_state()
        finally:
            self.loading_project = False

        self._autosave_project("new project", immediate=True)
        self._mark_conversion_check_dirty()
        project_path = project_dir / "project.json"
        self._record_recent("project", project_path, project_name)
        self._show_workspace()
        self.status_label.setText(tr("空白项目已创建"))
        self.show_toast(
            tr("空白项目已创建；双击轨道即可添加音符。"),
            kind="success",
        )

    def show_toast(
        self,
        text: str,
        kind: str = "info",
        duration_ms: int = 2600,
    ) -> GlobalToast:
        return show_global_toast(self, text, kind=kind, duration_ms=duration_ms)

    def _open_game_music_directory(self) -> None:
        directory = default_game_music_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _open_home_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        path = Path(str(data.get("path") or ""))
        kind = str(data.get("kind") or "")
        if kind in {"project", "example"} and path.is_file():
            self._load_project(path)
        elif kind == "midi" and path.is_file():
            self._open_midi_path(path)
        elif kind in {"game", "bdo"} and path.is_file():
            self._open_bdo_score_path(path)

    def _record_recent(self, kind: str, path: Path, label: str) -> None:
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path)
        recent = [
            item for item in self.config.get("recent_items", [])
            if isinstance(item, dict) and str(item.get("path") or "").casefold() != normalized.casefold()
        ]
        recent.insert(0, {"kind": kind, "path": normalized, "label": label, "opened_at": time.time()})
        self.config["recent_items"] = recent[:12]
        save_config(self.config)

    def _build_tracks_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel(tr("轨道"))
        title.setObjectName("PanelTitle")
        self.track_summary = QLabel(tr("导入 MIDI 后显示轨道"))
        self.track_summary.setObjectName("Muted")
        clear_solo = PillButton(tr("清除 Solo"), "ghost")
        clear_solo.clicked.connect(self._clear_solo)
        unmute = PillButton(tr("取消静音"), "ghost")
        unmute.clicked.connect(self._unmute_all)
        header.addWidget(title)
        header.addWidget(self.track_summary, stretch=1)
        header.addWidget(clear_solo)
        header.addWidget(unmute)
        layout.addLayout(header)

        self.track_container = QWidget()
        self.track_container.setObjectName("TrackContainer")
        self.track_layout = QVBoxLayout(self.track_container)
        self.track_layout.setContentsMargins(0, 0, 0, 0)
        self.track_layout.setSpacing(6)
        self.track_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("TrackScroll")
        scroll.viewport().setObjectName("TrackViewport")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.track_container)
        layout.addWidget(scroll, stretch=1)
        return panel

    def _build_timeline_panel(self) -> QWidget:
        workspace = QWidget()
        workspace.setObjectName("TimelineWorkspace")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        controls = QFrame()
        controls.setObjectName("TimelineControlBar")
        header = QHBoxLayout(controls)
        header.setContentsMargins(10, 4, 10, 4)
        header.setSpacing(5)
        self.timeline_meta = ElidedLabel(
            tr("等待 MIDI"), maximum_hint_width=170
        )
        self.timeline_meta.setObjectName("TimelineMeta")
        self.timeline_fit_btn = PillButton(tr("全览"), "ghost", FluentSymbol.FIT)
        self.timeline_fit_btn.setToolTip(tr("显示全部时间轴"))
        self.timeline_fit_btn.setAccessibleName(tr("显示全部时间轴"))
        self.timeline_fit_btn.clicked.connect(self._fit_timeline)
        self.timeline_zoom_label = QLabel(tr("缩放"))
        self.timeline_zoom_label.setObjectName("TimelineControlLabel")
        self.timeline_zoom = QSlider(Qt.Horizontal)
        self.timeline_zoom.setRange(100, 800)
        self.timeline_zoom.setValue(100)
        self.timeline_zoom.setFixedWidth(104)
        self.timeline_zoom.setToolTip(tr("时间轴缩放"))
        self.timeline_zoom.setAccessibleName(tr("时间轴缩放"))
        self.timeline_zoom_label.setBuddy(self.timeline_zoom)
        self.timeline_pan_label = QLabel(tr("位置"))
        self.timeline_pan_label.setObjectName("TimelineControlLabel")
        self.timeline_pan = QSlider(Qt.Horizontal)
        self.timeline_pan.setRange(0, 1000)
        self.timeline_pan.setValue(0)
        self.timeline_pan.setFixedWidth(112)
        self.timeline_pan.setToolTip(tr("时间轴位置"))
        self.timeline_pan.setAccessibleName(tr("时间轴位置"))
        self.timeline_pan_label.setBuddy(self.timeline_pan)
        transport_group = QFrame()
        transport_group.setObjectName("TransportGroup")
        transport_layout = QHBoxLayout(transport_group)
        transport_layout.setContentsMargins(1, 1, 1, 1)
        transport_layout.setSpacing(1)
        self.play_button = PillButton(tr("播放"), "secondary", FluentSymbol.PLAY)
        self.play_button.clicked.connect(self._play_preview)
        self.pause_button = PillButton(tr("暂停"), "secondary", FluentSymbol.PAUSE)
        self.pause_button.clicked.connect(self._pause_preview)
        self.stop_button = PillButton(tr("停止"), "secondary", FluentSymbol.STOP)
        self.stop_button.clicked.connect(lambda: self._stop_preview(reset_playhead=True))
        self.timeline_loop_box = QCheckBox(tr("循环区间"))
        self.timeline_loop_box.setToolTip(tr("循环播放 A–B 时间区间"))
        transport_layout.addWidget(self.play_button)
        transport_layout.addWidget(self.pause_button)
        transport_layout.addWidget(self.stop_button)
        transport_layout.addWidget(self.timeline_loop_box)
        self.add_track_button = PillButton(tr("新建轨道"), "secondary", FluentSymbol.ADD_TRACK)
        self.add_track_button.clicked.connect(self._show_new_track_menu)
        self.track_actions_button = PillButton(tr("轨道"), "ghost")
        track_actions = QMenu(self.track_actions_button)
        delete_action = track_actions.addAction(tr("删除轨道"))
        delete_action.triggered.connect(self._delete_selected_track)
        track_actions.addSeparator()
        clear_solo_action = track_actions.addAction(tr("清除 Solo"))
        clear_solo_action.triggered.connect(self._clear_solo)
        unmute_action = track_actions.addAction(tr("取消静音"))
        unmute_action.triggered.connect(self._unmute_all)
        self.track_actions_button.setMenu(track_actions)

        header.addWidget(transport_group)
        header.addWidget(self.timeline_meta)
        separator = QFrame()
        separator.setObjectName("TimelineSeparator")
        separator.setFrameShape(QFrame.VLine)
        header.addWidget(separator)
        header.addWidget(self.add_track_button)
        header.addWidget(self.track_actions_button)
        header.addStretch(1)

        self.transcription_tools_slot = QFrame()
        self.transcription_tools_slot.setObjectName("TranscriptionToolsSlot")
        transcription_slot_layout = QHBoxLayout(self.transcription_tools_slot)
        transcription_slot_layout.setContentsMargins(0, 0, 0, 0)
        transcription_slot_layout.setSpacing(0)
        self.transcription_entry_button = PillButton(
            tr("扒谱模式"),
            "secondary",
        )
        self.transcription_entry_button.setObjectName("TranscriptionModeButton")
        self.transcription_entry_button.setToolTip(
            tr("在当前乐器轨的音符编辑器中打开完整扒谱模式")
        )
        self.transcription_entry_button.clicked.connect(
            self._open_transcription_mode
        )
        transcription_slot_layout.addWidget(self.transcription_entry_button)
        header.addWidget(self.transcription_tools_slot)

        header.addWidget(self.timeline_zoom_label)
        header.addWidget(self.timeline_zoom)
        header.addWidget(self.timeline_pan_label)
        header.addWidget(self.timeline_pan)
        header.addWidget(self.timeline_fit_btn)
        layout.addWidget(controls)
        self.timeline = TimelineCanvas()
        self.timeline.setObjectName("TimelineCanvas")
        self.timeline.set_instrument_art_dir(self.instrument_art_dir)
        self.timeline.changed.connect(self._on_track_changed)
        self.timeline.track_state_changed.connect(self._on_track_filter_changed)
        self.timeline.instrument_changed.connect(self._on_track_instrument_changed)
        self.timeline.selected.connect(self._select_track)
        self.timeline.effects_requested.connect(self._show_effects_placeholder)
        self.timeline.midi_tools_requested.connect(self._open_midi_tool)
        self.timeline.note_editor_requested.connect(self._open_note_editor)
        self.timeline.seek_requested.connect(self._seek_preview)
        self.timeline.time_range_changed.connect(self._timeline_range_changed)
        self.timeline_zoom.valueChanged.connect(self.timeline.set_zoom_percent)
        self.timeline_pan.valueChanged.connect(self.timeline.set_pan_percent)
        layout.addWidget(self.timeline, stretch=1)
        self.reference_audio = ReferenceAudioController(self)
        self.reference_audio.set_project_offset_ms(
            self.reference_audio_offset_ms,
            notify=False,
        )
        self.reference_audio.file_changed.connect(self._reference_audio_changed)
        self.reference_audio.volume_changed.connect(self._reference_volume_changed)
        self.reference_audio.offset_changed.connect(self._reference_offset_changed)
        self.reference_audio.player.playbackStateChanged.connect(
            self._reference_playback_state_changed
        )
        self.timeline.set_reference_audio(self.reference_audio)
        return workspace

    def _build_performance_strip(self) -> QWidget:
        """Compact process/audio telemetry below the multitrack timeline."""

        strip = QFrame()
        strip.setObjectName("PerformanceStrip")
        strip.setFixedHeight(25)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(14)
        caption = QLabel(tr("本程序"))
        caption.setObjectName("PerformanceCaption")
        self.process_cpu_label = QLabel("CPU --")
        self.process_cpu_label.setObjectName("PerformanceMetric")
        self.process_ram_label = QLabel("RAM --")
        self.process_ram_label.setObjectName("PerformanceMetric")
        self.audio_load_label = QLabel(tr("音频 --"))
        self.audio_load_label.setObjectName("PerformanceMetric")
        self.active_voice_label = QLabel(tr("声部 --"))
        self.active_voice_label.setObjectName("PerformanceMetric")
        tooltip = tr("当前 BDO Music Composer 进程；每秒低开销采样一次")
        for widget in (
            caption,
            self.process_cpu_label,
            self.process_ram_label,
            self.audio_load_label,
            self.active_voice_label,
        ):
            widget.setToolTip(tooltip)
        layout.addWidget(caption)
        layout.addWidget(self.process_cpu_label)
        layout.addWidget(self.process_ram_label)
        layout.addStretch(1)
        layout.addWidget(self.audio_load_label)
        layout.addWidget(self.active_voice_label)
        return strip

    def _update_process_metrics(self) -> None:
        if not hasattr(self, "process_cpu_label"):
            return
        metrics = self.process_metrics_sampler.sample()
        self.process_cpu_label.setText(f"CPU {metrics.cpu_percent:.1f}%")
        self.process_ram_label.setText(f"RAM {metrics.working_set_mib:.0f} MB")
        audio_load = 0.0
        active_voices = 0
        underruns = self.last_reported_underruns
        if self.realtime_preview_active:
            try:
                status = self.realtime_audio.get_status()
            except AudioEngineError:
                status = None
            if status is not None:
                audio_load = max(0.0, float(status.render_p95_load))
                active_voices = max(0, int(status.active_voices))
                underruns = max(underruns, int(status.underruns))
        self.audio_load_label.setText(
            trf("音频 {load:.0f}% · XRUN {count}", load=audio_load * 100.0, count=underruns)
        )
        self.active_voice_label.setText(trf("声部 {count}", count=active_voices))

    def _open_transcription_mode(self) -> None:
        melodic_tracks = [
            track
            for track in self.tracks
            if not track.is_percussion
            and int(track.bdo_instrument_id) != 0x0D
        ]
        if not melodic_tracks:
            QMessageBox.information(
                self,
                tr("扒谱模式"),
                tr("当前工程没有可用于扒谱的旋律乐器轨，请先新建乐器轨。"),
            )
            return
        target = (
            self.selected_track
            if self.selected_track in melodic_tracks
            else None
        )
        if target is None:
            labels = [
                (
                    f"{track.display_name}  [#{track.track_id} · "
                    f"{_ui_bdo_instrument_name(int(track.bdo_instrument_id))}]"
                )
                for track in melodic_tracks
            ]
            tracks_by_label = dict(zip(labels, melodic_tracks, strict=True))
            selected_label, accepted = QInputDialog.getItem(
                self,
                tr("选择扒谱目标轨"),
                tr("请选择要打开的旋律乐器轨："),
                labels,
                0,
                False,
            )
            if not accepted:
                return
            target = tracks_by_label.get(selected_label)
            if target is None:
                return
        self._open_note_editor(target, transcription_mode=True)

    def _transcription_target_track(self) -> TrackState | None:
        editor = self.active_transcription_editor
        target = editor.track if editor is not None else self.selected_track
        if (
            target in self.tracks
            and target is not None
            and not target.is_percussion
            and int(target.bdo_instrument_id) != 0x0D
        ):
            return target
        return None

    def _candidate_invalid_for_track(
        self,
        candidate: TranscriptionCandidate,
        track: TrackState | None,
    ) -> bool:
        if track is None:
            return True
        if not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
            candidate,
            self.reference_audio_offset_ms,
        ):
            return True
        supported = game_supported_pitches(
            int(track.bdo_instrument_id), track.marnian_synth_mode
        )
        return not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
            candidate.pitch,
            is_percussion=track.is_percussion,
            instrument_id=track.bdo_instrument_id,
            transpose=self.transpose,
            supported_pitches=supported,
        )

    def _transcription_candidate_flags(
        self,
    ) -> tuple[set[str], set[str]]:
        track = self._transcription_target_track()
        invalid: set[str] = set()
        duplicates: set[str] = set()
        notes_by_pitch: dict[int, tuple[list[float], list[Note]]] = {}
        if track is not None:
            grouped_notes: dict[int, list[Note]] = defaultdict(list)
            for note in track.notes:
                grouped_notes[int(note.pitch)].append(note)
            for pitch, notes in grouped_notes.items():
                ordered = sorted(notes, key=lambda note: float(note.start))
                notes_by_pitch[pitch] = (
                    [float(note.start) for note in ordered],
                    ordered,
                )
        for candidate in self.transcription_session.candidates:
            candidate_id = self.transcription_session.candidate_id(candidate)
            if self._candidate_invalid_for_track(candidate, track):
                invalid.add(candidate_id)
                continue
            starts, notes = notes_by_pitch.get(
                int(candidate.pitch),
                ([], []),
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                self.reference_audio_offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            if any(
                CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    note,
                    self.reference_audio_offset_ms,
                )
                for note in notes[first:last]
            ):
                duplicates.add(candidate_id)
        return invalid, duplicates

    def _refresh_transcription_workspace(self) -> None:
        """Refresh the only transcription view: the active note editor.

        The method name is retained as an internal compatibility seam while
        older callers are migrated.  It no longer owns or refreshes a main-page
        transcription workspace.
        """

        state = self.transcription_session.state
        self.timeline.set_time_range(
            *(state.region if state.region is not None else (None, None))
        )
        editor = self.active_transcription_editor
        if editor is None:
            return
        editor.beat_origin_ms = float(self.beat_origin_ms)
        editor.refresh_transcription_projection()
        editor.set_transcription_analysis_ui(
            self.transcription_analysis_busy,
            self.transcription_analysis_progress,
            status=self._transcription_ui_status_spec,
        )

    def _visible_region_candidate_ids(
        self,
        *,
        include_routed: bool = False,
    ) -> tuple[str, ...]:
        editor = self.active_transcription_editor
        if editor is not None:
            return editor.eligible_transcription_candidate_ids(
                include_routed=include_routed
            )
        state = self.transcription_session.state
        if state.selected_candidate_ids:
            selected = state.selected_candidate_ids.difference(
                state.rejected_candidate_ids
            )
            return tuple(
                self.transcription_session.candidate_id(candidate)
                for candidate in self.transcription_session.candidates
                if (
                    self.transcription_session.candidate_id(candidate)
                    in selected
                )
            )
        if state.region is None:
            return ()
        routed = {
            route.candidate_id
            for route in (*state.pending_routes, *state.applied_routes)
        }
        start_ms, end_ms = state.region
        values: list[str] = []
        for candidate in self.transcription_session.candidates:
            candidate_id = self.transcription_session.candidate_id(candidate)
            if candidate_id in state.rejected_candidate_ids:
                continue
            if not include_routed and candidate_id in routed:
                continue
            project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate,
                self.reference_audio_offset_ms,
            )
            if start_ms <= project_start < end_ms:
                values.append(candidate_id)
        return tuple(values)

    def _refresh_transcription_action_state(self) -> None:
        editor = self.active_transcription_editor
        if editor is not None:
            editor.refresh_transcription_projection()

    def _transcription_target_changed(self, track_id: int) -> None:
        target = next(
            (
                track
                for track in self.tracks
                if int(track.track_id) == int(track_id)
                and not track.is_percussion
                and int(track.bdo_instrument_id) != 0x0D
            ),
            None,
        )
        if target is not None:
            self._select_track(target)

    def _transcription_selection_changed(
        self, candidate_ids: Iterable[str],
    ) -> None:
        self.transcription_session.set_selection(candidate_ids)
        self._activate_voice_group_for_candidates(candidate_ids)
        self._refresh_transcription_workspace()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription selection")

    def _set_transcription_region(
        self, value: tuple[float, float] | None,
    ) -> None:
        if value is None:
            self.transcription_session.clear_region()
        else:
            self.transcription_session.set_region(value[0], value[1])
        region = self.transcription_session.state.region
        self.timeline.set_time_range(
            *(region if region is not None else (None, None))
        )
        editor = self.active_transcription_editor
        if editor is not None:
            editor.refresh_transcription_projection()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription A-B")

    def _timeline_range_changed(
        self, value: tuple[float, float] | None,
    ) -> None:
        self._set_transcription_region(value)

    def _workbench_range_changed(
        self, value: tuple[float, float] | None,
    ) -> None:
        self._set_transcription_region(value)

    def _workbench_view_changed(
        self, view: tuple[float, float],
    ) -> None:
        # Kept for source compatibility with pre-embedded callers.  The editor
        # now owns its own scroll/zoom and no longer drives the main timeline.
        del view

    def _transcription_sensitivity_changed(self, sensitivity: str) -> None:
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            editor.transcription_panel.set_sensitivity(
                self.transcription_session.state.sensitivity
            )
            return
        self.transcription_session.set_sensitivity(sensitivity)
        self._refresh_transcription_action_state()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription sensitivity")
        if (
            self.transcription_session.state.cache_key
            and self.workspace_transcription_worker is None
        ):
            self._stop_preview(reset_playhead=False)
            self._restore_cached_transcription()

    def _transcription_cleanup_profile_changed(
        self,
        cleanup_profile: str,
    ) -> None:
        previous = self.transcription_session.state.cleanup_profile
        requested = str(cleanup_profile)
        if requested == previous:
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            editor.transcription_panel.set_cleanup_profile(previous)
            return
        if self.workspace_transcription_worker is not None:
            if editor is not None:
                editor.transcription_panel.set_cleanup_profile(previous)
            return
        if self.transcription_session.state.cache_key:
            self._stop_preview(reset_playhead=False)
            profile_label = _transcription_cleanup_ui_labels(requested, None)[0]
            try:
                generation = self._restore_cached_transcription(
                    status=trf(
                        "正在按“{profile}”从缓存证据重新解码；"
                        "不会再次运行模型。",
                        profile=profile_label,
                    ),
                    cleanup_profile=requested,
                    rollback_cleanup_profile=previous,
                )
            except Exception:
                append_crash_log(
                    "Transcription cleanup profile switch failed",
                    traceback.format_exc(),
                )
                self._rollback_cleanup_profile_transaction()
                generation = None
                self._set_transcription_status(
                    tr("碎音处理切换失败；已恢复原档位。")
                )
            if generation is None and editor is not None:
                editor.transcription_panel.set_cleanup_profile(previous)
            return
        self.transcription_session.set_cleanup_profile(requested)
        self._refresh_transcription_action_state()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription fragment cleanup")
        if editor is not None:
            self._set_transcription_status(
                trf(
                    "已选择“{profile}”；下次分析将使用该档位。",
                    profile=_transcription_cleanup_ui_labels(requested, None)[0],
                )
            )

    def _select_suspected_transcription_fragments(self) -> None:
        state = self.transcription_session.state
        region = state.region
        selected: list[str] = []
        for candidate in self.transcription_session.candidates:
            candidate_id = self.transcription_session.candidate_id(
                candidate
            )
            annotation = self.transcription_session.annotation_for_id(
                candidate_id
            )
            if (
                annotation is None
                or not {
                    "review_fragment",
                    "pitch_flicker",
                }.intersection(annotation.flags)
                or candidate_id in state.rejected_candidate_ids
            ):
                continue
            if region is not None:
                project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
                    candidate,
                    self.reference_audio_offset_ms,
                )
                if not region[0] <= project_start < region[1]:
                    continue
            selected.append(candidate_id)
        self._transcription_selection_changed(selected)
        self._set_transcription_status(
            trf(
                "已选择 {count} 个疑似碎音候选",
                count=len(selected),
            )
        )

    def _transcription_analysis_mode_changed(
        self, analysis_mode: str,
    ) -> None:
        previous = self.transcription_session.state
        if str(analysis_mode) == previous.analysis_mode:
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            editor.transcription_panel.set_analysis_mode(
                previous.analysis_mode
            )
            return
        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        self.transcription_session = TranscriptionSession(
            state=TranscriptionSessionState(
                region=previous.region,
                analysis_mode=str(analysis_mode),
                sensitivity=previous.sensitivity,
                cleanup_profile=previous.cleanup_profile,
            )
        )
        self.transcription_result = None
        self.automatic_harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.harmony_analysis = None
        self.instrument_match_analysis = None
        self.transcription_group_timbre_profiles = None
        self.transcription_group_timbre_revision = ""
        self.transcription_assist_review = TranscriptionAssistReviewState()
        self.transcription_assist_review_undo.clear()
        self.transcription_assist_review_redo.clear()
        self._clear_transcription_review_history()
        if editor is not None:
            editor.release_transcription_resources()
        self._refresh_transcription_workspace()
        self._set_transcription_status(
            tr("识别模式已更改；请重新分析整首。")
        )
        if self.tracks and not self.loading_project:
            self._autosave_project(
                "transcription analysis mode",
                immediate=True,
            )

    def _route_transcription_candidates(self, copy: bool) -> None:
        # Persistent routing is intentionally disabled in embedded mode.
        # Candidate writes and copies are staged inside the open dialog.
        editor = self.active_transcription_editor
        if editor is None:
            return
        if copy:
            editor.set_transcription_status(
                tr("请从“显式复制到…”选择目标轨")
            )
        else:
            editor.accept_transcription_candidates()

    def _reject_transcription_candidates(self) -> None:
        candidate_ids = self._visible_region_candidate_ids()
        rejected = self.transcription_session.reject(candidate_ids)
        self._refresh_transcription_workspace()
        if rejected:
            self._record_transcription_review_action("session")
            self._autosave_project("transcription reject")
            self._set_transcription_status(
                trf("已拒绝 {count} 个候选", count=len(rejected))
            )

    def _restore_transcription_candidates(self) -> None:
        state = self.transcription_session.state
        selected = state.selected_candidate_ids.intersection(
            state.rejected_candidate_ids
        )
        if selected:
            candidate_ids = selected
        elif state.region is not None:
            start_ms, end_ms = state.region
            candidate_ids = {
                self.transcription_session.candidate_id(candidate)
                for candidate in self.transcription_session.candidates
                if (
                    self.transcription_session.candidate_id(candidate)
                    in state.rejected_candidate_ids
                    and start_ms
                    <= CANDIDATE_NOTE_POLICY.project_start_ms(
                        candidate,
                        self.reference_audio_offset_ms,
                    )
                    < end_ms
                )
            }
        else:
            candidate_ids = state.rejected_candidate_ids
        restored = self.transcription_session.restore_rejected(candidate_ids)
        self._refresh_transcription_workspace()
        if restored:
            self._record_transcription_review_action("session")
            self._autosave_project("transcription restore")
            self._set_transcription_status(
                trf("已恢复 {count} 个候选", count=len(restored))
            )

    def _undo_transcription_review(self) -> None:
        kind = (
            self.transcription_review_action_undo.pop()
            if self.transcription_review_action_undo
            else "session"
        )
        changed = False
        if kind == "assist":
            if self.transcription_assist_review_undo:
                self.transcription_assist_review_redo.append(
                    self.transcription_assist_review
                )
                self.transcription_assist_review = (
                    self.transcription_assist_review_undo.pop()
                )
                changed = True
        else:
            changed = self.transcription_session.undo()
        if not changed:
            return
        self.transcription_review_action_redo.append(kind)
        self._reapply_transcription_assist_review()
        self._refresh_transcription_workspace()
        self._start_transcription_assist_analysis()
        self._autosave_project(
            "transcription review undo",
            immediate=True,
        )

    def _redo_transcription_review(self) -> None:
        kind = (
            self.transcription_review_action_redo.pop()
            if self.transcription_review_action_redo
            else "session"
        )
        changed = False
        if kind == "assist":
            if self.transcription_assist_review_redo:
                self.transcription_assist_review_undo.append(
                    self.transcription_assist_review
                )
                self.transcription_assist_review = (
                    self.transcription_assist_review_redo.pop()
                )
                changed = True
        else:
            changed = self.transcription_session.redo()
        if not changed:
            return
        self.transcription_review_action_undo.append(kind)
        self._reapply_transcription_assist_review()
        self._refresh_transcription_workspace()
        self._start_transcription_assist_analysis()
        self._autosave_project(
            "transcription review redo",
            immediate=True,
        )

    def _align_reference_audio_to_playhead(self) -> None:
        if not self.reference_audio.audio_path:
            self.show_toast(tr("请先载入参考音频。"), kind="warning")
            return
        editor = self.active_transcription_editor
        playhead_ms = (
            float(editor.playhead_ms)
            if editor is not None
            else float(self.timeline.playhead_ms)
        )
        audio_position = float(self.reference_audio.player.position())
        offset = playhead_ms - audio_position
        self._set_reference_alignment(
            offset,
            self.beat_origin_ms,
            autosave=True,
        )
        self._refresh_transcription_workspace()
        self.show_toast(
            tr("当前音频位置已对齐到播放头。"),
            kind="success",
        )

    def _set_playhead_as_beat_origin(self) -> None:
        editor = self.active_transcription_editor
        playhead_ms = (
            float(editor.playhead_ms)
            if editor is not None
            else float(self.timeline.playhead_ms)
        )
        self._set_reference_alignment(
            self.reference_audio_offset_ms,
            playhead_ms,
            autosave=True,
        )
        self.show_toast(
            tr("第一拍锚点已更新；正式音符位置未移动。"),
            kind="success",
        )

    def _set_transcription_status(self, text: object) -> None:
        self._transcription_ui_status_spec = defer_tr(text)
        self.transcription_ui_status = str(self._transcription_ui_status_spec)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.set_transcription_status(self._transcription_ui_status_spec)

    def retranslate_dynamic_content(self) -> None:
        """Refresh cached status text without changing its string API."""

        self.transcription_ui_status = str(self._transcription_ui_status_spec)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.set_transcription_status(self._transcription_ui_status_spec)

    def _transcription_audio_time_notes(self) -> tuple[Note, ...]:
        """Snapshot current formal/draft notes once for background harmony."""

        draft_track_id = None
        draft_notes: tuple[Note, ...] = ()
        editor = self.active_transcription_editor
        if editor is not None:
            draft_track_id = int(editor.track.track_id)
            draft_notes = tuple(editor.canvas.notes)
        offset_ms = float(self.reference_audio_offset_ms)
        projected: list[Note] = []
        for track in self.tracks:
            if track.is_percussion or int(track.bdo_instrument_id) == 0x0D:
                continue
            notes = (
                draft_notes
                if draft_track_id is not None
                and int(track.track_id) == draft_track_id
                else tuple(track.notes)
            )
            for note in notes:
                projected.append(
                    note._replace(start=float(note.start) - offset_ms)
                )
        projected.sort(
            key=lambda note: (
                float(note.start),
                int(note.pitch),
                float(note.dur),
                int(note.vel),
                int(note.ntype),
            )
        )
        return tuple(projected)

    def _schedule_transcription_assist_refresh(self) -> None:
        """Debounce semantic recomputation after draft/formal note edits."""

        result = self.transcription_result
        descriptor = (
            result.evidence_descriptor if result is not None else None
        )
        if (
            descriptor is None
            or not descriptor.cache_key
            or self.workspace_close_pending
        ):
            return
        self.transcription_assist_refresh_timer.start()

    def _start_transcription_assist_analysis(
        self,
        *,
        harmony_only: bool = False,
        allow_review_recovery: bool = True,
    ) -> None:
        if self.workspace_close_pending:
            self.transcription_assist_restart_pending = False
            self.transcription_assist_restart_harmony_only = False
            self.transcription_assist_restart_allow_review_recovery = True
            return
        result = self.transcription_result
        descriptor = (
            result.evidence_descriptor if result is not None else None
        )
        if result is None or descriptor is None or not descriptor.cache_key:
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self._refresh_transcription_workspace()
            return
        if self.transcription_assist_worker is not None:
            if not self.transcription_assist_restart_pending:
                self.transcription_assist_restart_harmony_only = bool(
                    harmony_only
                )
                self.transcription_assist_restart_allow_review_recovery = (
                    bool(allow_review_recovery)
                )
            else:
                self.transcription_assist_restart_harmony_only = bool(
                    self.transcription_assist_restart_harmony_only
                    and harmony_only
                )
                self.transcription_assist_restart_allow_review_recovery = (
                    bool(
                        self.transcription_assist_restart_allow_review_recovery
                        and allow_review_recovery
                    )
                )
            self.transcription_assist_restart_pending = True
            cancel = getattr(self.transcription_assist_worker, "cancel", None)
            if callable(cancel):
                cancel()
            return
        self.transcription_assist_restart_pending = False
        self.transcription_assist_restart_harmony_only = False
        self.transcription_assist_restart_allow_review_recovery = True
        self.transcription_assist_generation += 1
        generation = self.transcription_assist_generation
        effective_bpm = float(max(1, self.bpm_override or self.bpm))
        worker = TranscriptionAssistAnalysisWorker(
            cache_key=descriptor.cache_key,
            candidates=tuple(self.transcription_session.candidates),
            audio_time_notes=self._transcription_audio_time_notes(),
            descriptors=bdo_transcription_instrument_descriptors(),
            bpm=effective_bpm,
            time_signature=max(1, int(self.time_sig)),
            beat_origin_audio_ms=(
                float(self.beat_origin_ms)
                - float(self.reference_audio_offset_ms)
            ),
            duration_ms=float(descriptor.duration_ms),
            midi_min=int(descriptor.midi_min),
            reference_audio_path=str(
                self.reference_audio.audio_path or ""
            ),
            sample_map_path=BDO_SAMPLE_MAP_PATH,
            audio_root=str(self.audio_sources.get("audio_root", "") or ""),
            manual_voice_groups=(
                self.transcription_assist_review.active_voice_groups
            ),
            audio_fingerprint=str(
                getattr(descriptor, "audio_fingerprint", "") or ""
            ),
            pitch_offset=int(self.transpose),
            review_state=self.transcription_assist_review,
            previous_candidates=(
                self.transcription_assist_previous_candidates
            ),
            reuse_instrument_matches=(
                self.automatic_instrument_match_analysis
                if harmony_only
                else None
            ),
            reuse_timbre_profile_index=(
                self.transcription_timbre_profile_index
            ),
            reuse_group_timbre_profiles=(
                self.transcription_group_timbre_profiles
            ),
            reuse_group_timbre_revision=(
                self.transcription_group_timbre_revision
            ),
            allow_review_recovery=allow_review_recovery,
            parent=self,
        )
        self.transcription_assist_worker = worker
        worker.succeeded.connect(
            lambda bundle, token=generation:
            self._transcription_assist_succeeded(token, bundle)
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._transcription_assist_failed(token, message)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._transcription_assist_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _transcription_assist_succeeded(
        self,
        generation: int,
        bundle: TranscriptionAssistAnalysisBundle,
    ) -> None:
        if generation != self.transcription_assist_generation:
            return
        self.automatic_harmony_analysis = bundle.harmony
        self.automatic_instrument_match_analysis = bundle.instrument_matches
        self.transcription_timbre_profile_index = (
            bundle.timbre_profile_index
        )
        self.transcription_group_timbre_profiles = (
            bundle.group_timbre_profiles
        )
        self.transcription_group_timbre_revision = (
            bundle.group_timbre_revision
        )
        previous_review = self.transcription_assist_review
        review = (
            bundle.recovered_review
            if bundle.recovered_review is not None
            else previous_review
        )
        self.transcription_assist_review = review
        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        key_review = review.active_key_override
        key_override = (
            KeyEstimate(
                key_review.root_pc,
                key_review.mode,
                1.0,
                (),
                "manual",
            )
            if key_review is not None
            else None
        )
        chord_overrides = tuple(
            ChordSegment(
                item.segment_id,
                item.start_audio_ms,
                item.end_audio_ms,
                item.root_pc,
                item.quality,
                item.bass_pc,
                1.0,
                (),
                "manual",
                bool(item.locked),
            )
            for item in review.active_chord_segments
        )
        self.harmony_analysis = apply_harmony_overrides(
            bundle.harmony,
            key_override=key_override,
            chord_overrides=chord_overrides,
        )
        group_reviews = {
            item.group_id: item for item in review.active_voice_groups
        }
        reviewed_groups = tuple(
            VoiceGroup(
                group.group_id,
                group_reviews[group.group_id].candidate_ids,
                group_reviews[group.group_id].start_audio_ms,
                group_reviews[group.group_id].end_audio_ms,
                group_reviews[group.group_id].role,
                group.confidence,
            )
            if group.group_id in group_reviews
            else group
            for group in bundle.instrument_matches.groups
        )
        self.instrument_match_analysis = replace(
            bundle.instrument_matches,
            groups=reviewed_groups,
        )
        group_ids = {
            group.group_id for group in reviewed_groups
        }
        if self.active_voice_group_id not in group_ids:
            self.active_voice_group_id = (
                reviewed_groups[0].group_id
                if reviewed_groups
                else ""
            )
        self._refresh_transcription_workspace()
        if (
            not self.loading_project
            and bundle.recovered_review is not None
            and review != previous_review
        ):
            self._autosave_project(
                "transcription assist review recovery",
                immediate=True,
            )

    def _reapply_transcription_assist_review(
        self, *, autosave_reason: str | None = None
    ) -> None:
        harmony = self.automatic_harmony_analysis
        matches = self.automatic_instrument_match_analysis
        if harmony is None or matches is None:
            return
        review = self.transcription_assist_review
        key_review = review.active_key_override
        key_override = (
            KeyEstimate(
                key_review.root_pc,
                key_review.mode,
                1.0,
                (),
                "manual",
            )
            if key_review is not None
            else None
        )
        chord_overrides = tuple(
            ChordSegment(
                item.segment_id,
                item.start_audio_ms,
                item.end_audio_ms,
                item.root_pc,
                item.quality,
                item.bass_pc,
                1.0,
                (),
                "manual",
                bool(item.locked),
            )
            for item in review.active_chord_segments
        )
        self.harmony_analysis = apply_harmony_overrides(
            harmony,
            key_override=key_override,
            chord_overrides=chord_overrides,
        )
        group_reviews = {
            item.group_id: item for item in review.active_voice_groups
        }
        groups = tuple(
            VoiceGroup(
                group.group_id,
                group_reviews[group.group_id].candidate_ids,
                group_reviews[group.group_id].start_audio_ms,
                group_reviews[group.group_id].end_audio_ms,
                group_reviews[group.group_id].role,
                group.confidence,
            )
            if group.group_id in group_reviews
            else group
            for group in matches.groups
        )
        self.instrument_match_analysis = replace(matches, groups=groups)
        self._refresh_transcription_workspace()
        if autosave_reason and not self.loading_project:
            self._autosave_project(autosave_reason, immediate=True)

    def _current_analysis_fingerprint(self) -> str:
        descriptor = (
            self.transcription_result.evidence_descriptor
            if self.transcription_result is not None
            else None
        )
        return str(
            getattr(descriptor, "audio_fingerprint", "") or ""
        )

    def _record_transcription_review_action(self, kind: str) -> None:
        value = str(kind)
        if value not in {"session", "assist"}:
            raise ValueError("unknown transcription review action")
        if value == "assist":
            self.transcription_session.commands.discard_redo()
        else:
            self.transcription_assist_review_redo.clear()
        self.transcription_review_action_undo.append(value)
        del self.transcription_review_action_undo[:-100]
        self.transcription_review_action_redo.clear()

    def _set_transcription_assist_review_state(
        self, state: TranscriptionAssistReviewState
    ) -> bool:
        if state == self.transcription_assist_review:
            return False
        self.transcription_assist_review_undo.append(
            self.transcription_assist_review
        )
        del self.transcription_assist_review_undo[:-100]
        self.transcription_assist_review_redo.clear()
        self.transcription_assist_review = state
        self._record_transcription_review_action("assist")
        return True

    def _clear_transcription_review_history(self) -> None:
        self.transcription_assist_review_undo.clear()
        self.transcription_assist_review_redo.clear()
        self.transcription_review_action_undo.clear()
        self.transcription_review_action_redo.clear()
        self.transcription_session.commands.clear()

    def _can_undo_transcription_review(self) -> bool:
        return bool(self.transcription_review_action_undo) or bool(
            self.transcription_session.commands.can_undo
        )

    def _can_redo_transcription_review(self) -> bool:
        return bool(self.transcription_review_action_redo) or bool(
            self.transcription_session.commands.can_redo
        )

    def _set_assist_key_override(
        self,
        root_pc: int,
        mode: str,
        *,
        manual: bool,
        locked: bool,
    ) -> None:
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                key_override=KeyReviewOverride(
                    int(root_pc),
                    str(mode),
                    manual=manual,
                    locked=locked,
                ),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription key review"
        )

    def _clear_assist_key_override(self) -> None:
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                key_override=None,
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription key unlock"
        )

    def _set_assist_chord_review(
        self,
        segment: ChordSegment,
        *,
        root_pc: int | None = None,
        quality: str | None = None,
        bass_pc: int | None = None,
        manual: bool,
        locked: bool,
    ) -> None:
        chosen_quality = str(quality or segment.quality)
        chosen_root = (
            segment.root_pc if root_pc is None else int(root_pc)
        )
        if chosen_quality == "N":
            chosen_root = None
            bass_pc = None
        candidate_ids = self._candidate_ids_for_audio_range(
            segment.start_audio_ms,
            segment.end_audio_ms,
        )
        existing = [
            item
            for item in self.transcription_assist_review.locked_chord_segments
            if not (
                item.segment_id == segment.segment_id
                or (
                    math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
            )
        ]
        existing.append(
            LockedChordReview(
                "",
                segment.segment_id,
                segment.start_audio_ms,
                segment.end_audio_ms,
                chosen_root,
                chosen_quality,
                segment.bass_pc if bass_pc is None else bass_pc,
                candidate_ids,
                manual=manual,
                locked=locked,
            )
        )
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                locked_chord_segments=tuple(existing),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription chord review"
        )

    def _candidate_ids_for_audio_range(
        self, start_audio_ms: float, end_audio_ms: float
    ) -> tuple[str, ...]:
        return tuple(
            self.transcription_session.candidate_id(candidate)
            for candidate in self.transcription_session.candidates
            if min(
                float(candidate.start_ms + candidate.duration_ms),
                float(end_audio_ms),
            )
            > max(
                float(candidate.start_ms),
                float(start_audio_ms),
            )
        )

    def _remove_assist_chord_review(self, segment_id: str) -> None:
        segment = next(
            (
                item
                for item in (
                    self.harmony_analysis.chord_segments
                    if self.harmony_analysis is not None
                    else ()
                )
                if item.segment_id == str(segment_id)
            ),
            None,
        )
        retained = tuple(
            item
            for item in self.transcription_assist_review.locked_chord_segments
            if not (
                item.segment_id == str(segment_id)
                or (
                    segment is not None
                    and math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
            )
        )
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                locked_chord_segments=retained,
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription chord unlock"
        )

    def _replace_assist_chord_reviews(
        self,
        removed_segments: Iterable[ChordSegment],
        additions: Iterable[LockedChordReview],
        *,
        reason: str,
    ) -> None:
        removed = tuple(removed_segments)
        retained = [
            item
            for item in self.transcription_assist_review.locked_chord_segments
            if not any(
                item.segment_id == segment.segment_id
                or (
                    math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
                for segment in removed
            )
        ]
        retained.extend(additions)
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                locked_chord_segments=tuple(retained),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason=reason
        )

    def _split_transcription_chord_segment(
        self, segment_id: str, project_ms: float
    ) -> None:
        harmony = self.harmony_analysis
        if harmony is None:
            return
        segment = next(
            (
                item
                for item in harmony.chord_segments
                if item.segment_id == str(segment_id)
            ),
            None,
        )
        if segment is None:
            return
        split_audio_ms = (
            float(project_ms) - float(self.reference_audio_offset_ms)
        )
        if not (
            segment.start_audio_ms + 1.0
            < split_audio_ms
            < segment.end_audio_ms - 1.0
        ):
            self.show_toast(
                tr("请先将播放头放在所选和弦段内部。"),
                kind="warning",
            )
            return
        left_id = stable_assist_review_id(
            "chord-segment",
            segment.segment_id,
            round(segment.start_audio_ms, 3),
            round(split_audio_ms, 3),
        )
        right_id = stable_assist_review_id(
            "chord-segment",
            segment.segment_id,
            round(split_audio_ms, 3),
            round(segment.end_audio_ms, 3),
        )
        additions = (
            LockedChordReview(
                "",
                left_id,
                segment.start_audio_ms,
                split_audio_ms,
                segment.root_pc,
                segment.quality,
                segment.bass_pc,
                self._candidate_ids_for_audio_range(
                    segment.start_audio_ms, split_audio_ms
                ),
                manual=True,
                locked=True,
            ),
            LockedChordReview(
                "",
                right_id,
                split_audio_ms,
                segment.end_audio_ms,
                segment.root_pc,
                segment.quality,
                segment.bass_pc,
                self._candidate_ids_for_audio_range(
                    split_audio_ms, segment.end_audio_ms
                ),
                manual=True,
                locked=True,
            ),
        )
        self._replace_assist_chord_reviews(
            (segment,),
            additions,
            reason="transcription chord split",
        )

    def _merge_transcription_chord_segments(
        self,
        first_segment_id: str,
        second_segment_id: str,
        retained_segment_id: str,
    ) -> None:
        harmony = self.harmony_analysis
        if harmony is None:
            return
        by_id = {
            segment.segment_id: segment
            for segment in harmony.chord_segments
        }
        first = by_id.get(str(first_segment_id))
        second = by_id.get(str(second_segment_id))
        retained = by_id.get(str(retained_segment_id))
        if (
            first is None
            or second is None
            or retained not in {first, second}
        ):
            return
        left, right = sorted(
            (first, second),
            key=lambda segment: (
                segment.start_audio_ms,
                segment.end_audio_ms,
            ),
        )
        if abs(left.end_audio_ms - right.start_audio_ms) > 1.0:
            self.show_toast(
                tr("只能合并相邻的和弦段。"),
                kind="warning",
            )
            return
        start_audio_ms = left.start_audio_ms
        end_audio_ms = right.end_audio_ms
        merged = LockedChordReview(
            "",
            stable_assist_review_id(
                "chord-segment",
                left.segment_id,
                right.segment_id,
                retained.root_pc,
                retained.quality,
            ),
            start_audio_ms,
            end_audio_ms,
            retained.root_pc,
            retained.quality,
            retained.bass_pc,
            self._candidate_ids_for_audio_range(
                start_audio_ms, end_audio_ms
            ),
            manual=True,
            locked=True,
        )
        self._replace_assist_chord_reviews(
            (first, second),
            (merged,),
            reason="transcription chord merge",
        )

    def _confirm_assist_instrument_match(
        self, group_id: str, instrument_id: int
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None:
            return
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        if group is None:
            return
        legal_matches = analysis.matches_for_group(group.group_id)
        if int(instrument_id) not in {
            int(match.instrument_id) for match in legal_matches
        }:
            self.show_toast(
                tr("该乐器不在当前声部的 Top-3 建议中。"),
                kind="warning",
            )
            return
        reviews = [
            item
            for item in self.transcription_assist_review.voice_groups
            if item.group_id != group.group_id
        ]
        reviews.append(
            ManualVoiceGroupReview(
                "",
                group.group_id,
                group.candidate_ids,
                group.start_audio_ms,
                group.end_audio_ms,
                group.role,
                int(instrument_id),
            )
        )
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                voice_groups=tuple(reviews),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription instrument confirmation"
        )
        self.show_toast(
            trf(
                "已确认声部的 BDO 乐器建议：{instrument}",
                instrument=trv(_ui_bdo_instrument_source(int(instrument_id))),
            ),
            kind="success",
        )

    def _replace_manual_voice_group_reviews(
        self,
        removed_group_ids: Iterable[str],
        additions: Iterable[ManualVoiceGroupReview],
        *,
        reason: str,
    ) -> None:
        removed = {str(group_id) for group_id in removed_group_ids}
        retained = [
            item
            for item in self.transcription_assist_review.voice_groups
            if item.group_id not in removed
        ]
        retained.extend(additions)
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                voice_groups=tuple(retained),
            ),
        )
        self._autosave_project(reason, immediate=True)
        self._start_transcription_assist_analysis()

    def _split_transcription_voice_group(
        self, group_id: str, project_ms: float
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None:
            return
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        if group is None:
            return
        split_audio_ms = float(project_ms) - float(
            self.reference_audio_offset_ms
        )
        candidates_by_id = {
            self.transcription_session.candidate_id(candidate): candidate
            for candidate in self.transcription_session.candidates
        }
        left_ids = tuple(
            candidate_id
            for candidate_id in group.candidate_ids
            if candidate_id in candidates_by_id
            and (
                float(candidates_by_id[candidate_id].start_ms)
                + float(candidates_by_id[candidate_id].duration_ms) * 0.5
            )
            < split_audio_ms
        )
        left_id_set = set(left_ids)
        right_ids = tuple(
            candidate_id
            for candidate_id in group.candidate_ids
            if candidate_id not in left_id_set
            and candidate_id in candidates_by_id
        )
        if not left_ids or not right_ids:
            self.show_toast(
                tr("播放头两侧必须都包含候选，才能分割声部。"),
                kind="warning",
            )
            return
        existing = next(
            (
                item
                for item in self.transcription_assist_review.voice_groups
                if item.group_id == group.group_id
            ),
            None,
        )
        confirmed = (
            existing.confirmed_instrument_id
            if existing is not None
            else None
        )
        left_group_id = stable_assist_review_id(
            "voice", tuple(sorted(left_ids))
        )
        right_group_id = stable_assist_review_id(
            "voice", tuple(sorted(right_ids))
        )
        additions = (
            ManualVoiceGroupReview(
                "",
                left_group_id,
                left_ids,
                group.start_audio_ms,
                split_audio_ms,
                group.role,
                confirmed,
            ),
            ManualVoiceGroupReview(
                "",
                right_group_id,
                right_ids,
                split_audio_ms,
                group.end_audio_ms,
                group.role,
                confirmed,
            ),
        )
        self._replace_manual_voice_group_reviews(
            (group.group_id,),
            additions,
            reason="transcription voice split",
        )

    def _merge_transcription_voice_groups(
        self, first_group_id: str, second_group_id: str
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None or first_group_id == second_group_id:
            return
        groups = {
            group.group_id: group for group in analysis.groups
        }
        first = groups.get(str(first_group_id))
        second = groups.get(str(second_group_id))
        if first is None or second is None:
            return
        candidate_ids = tuple(
            sorted(set(first.candidate_ids).union(second.candidate_ids))
        )
        reviews = {
            item.group_id: item
            for item in self.transcription_assist_review.voice_groups
        }
        confirmations = {
            review.confirmed_instrument_id
            for group_id in (first.group_id, second.group_id)
            if (review := reviews.get(group_id)) is not None
            and review.confirmed_instrument_id is not None
        }
        confirmed = (
            next(iter(confirmations)) if len(confirmations) == 1 else None
        )
        merged = ManualVoiceGroupReview(
            "",
            stable_assist_review_id("voice", candidate_ids),
            candidate_ids,
            min(first.start_audio_ms, second.start_audio_ms),
            max(first.end_audio_ms, second.end_audio_ms),
            first.role,
            confirmed,
        )
        self._replace_manual_voice_group_reviews(
            (first.group_id, second.group_id),
            (merged,),
            reason="transcription voice merge",
        )

    def _set_transcription_voice_group_color(
        self, group_id: str, color: str
    ) -> None:
        ui_config = self.config.setdefault("transcription_ui", {})
        if not isinstance(ui_config, dict):
            return
        colors = ui_config.setdefault("voice_group_colors", {})
        if not isinstance(colors, dict):
            colors = {}
            ui_config["voice_group_colors"] = colors
        colors[str(group_id)] = str(color)
        # Bound stale local-only color preferences.
        while len(colors) > 256:
            colors.pop(next(iter(colors)))
        save_config(self.config)
        self._refresh_transcription_workspace()

    def _set_transcription_voice_group_role(
        self, group_id: str, role: str
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None:
            return
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        if group is None:
            return
        existing = next(
            (
                item
                for item in self.transcription_assist_review.voice_groups
                if item.group_id == group.group_id
            ),
            None,
        )
        updated = ManualVoiceGroupReview(
            "",
            group.group_id,
            group.candidate_ids,
            group.start_audio_ms,
            group.end_audio_ms,
            str(role),
            (
                existing.confirmed_instrument_id
                if existing is not None
                else None
            ),
        )
        self._replace_manual_voice_group_reviews(
            (group.group_id,),
            (updated,),
            reason="transcription voice role",
        )

    def _transcription_assist_failed(
        self, generation: int, message: str
    ) -> None:
        if generation != self.transcription_assist_generation:
            return
        self.automatic_harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.harmony_analysis = None
        self.instrument_match_analysis = None
        append_crash_log("Transcription assist analysis failed", message)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_assist_available(False)

    def _transcription_assist_finished(
        self, generation: int, worker: QThread
    ) -> None:
        if self.transcription_assist_worker is not worker:
            return
        self.transcription_assist_worker = None
        if self.transcription_assist_restart_pending:
            harmony_only = self.transcription_assist_restart_harmony_only
            allow_review_recovery = (
                self.transcription_assist_restart_allow_review_recovery
            )
            self.transcription_assist_restart_pending = False
            self.transcription_assist_restart_harmony_only = False
            self.transcription_assist_restart_allow_review_recovery = True
            QTimer.singleShot(
                0,
                lambda value=harmony_only, recover=allow_review_recovery:
                self._start_transcription_assist_analysis(
                    harmony_only=value,
                    allow_review_recovery=recover,
                ),
            )
        elif self.workspace_close_pending:
            workspace_worker = self.workspace_transcription_worker
            if workspace_worker is None or not workspace_worker.isRunning():
                self.workspace_close_pending = False
                QTimer.singleShot(0, self.close)

    def _active_voice_group(self) -> VoiceGroup | None:
        analysis = self.instrument_match_analysis
        if analysis is None or not analysis.groups:
            return None
        for group in analysis.groups:
            if group.group_id == self.active_voice_group_id:
                return group
        selected = self.transcription_session.state.selected_candidate_ids
        if selected:
            matching = [
                group
                for group in analysis.groups
                if selected.intersection(group.candidate_ids)
            ]
            if matching:
                return min(
                    matching,
                    key=lambda group: (
                        group.start_audio_ms,
                        group.group_id,
                    ),
                )
        return analysis.groups[0]

    def _activate_voice_group_for_candidates(
        self, candidate_ids: Iterable[str]
    ) -> None:
        analysis = self.instrument_match_analysis
        selected = {str(item) for item in candidate_ids}
        if analysis is None or not selected:
            return
        matching = [
            group
            for group in analysis.groups
            if selected.intersection(group.candidate_ids)
        ]
        if matching:
            self.active_voice_group_id = min(
                matching,
                key=lambda group: (
                    group.start_audio_ms,
                    group.group_id,
                ),
            ).group_id

    def _set_active_voice_group(
        self,
        group: VoiceGroup,
        *,
        update_range: bool,
        focus: bool = True,
    ) -> None:
        self.active_voice_group_id = group.group_id
        if update_range:
            offset_ms = float(self.reference_audio_offset_ms)
            self._set_transcription_region(
                (
                    group.start_audio_ms + offset_ms,
                    group.end_audio_ms + offset_ms,
                )
            )
        editor = self.active_transcription_editor
        if editor is not None and focus:
            editor.focus_transcription_time_range(
                group.start_audio_ms
                + float(self.reference_audio_offset_ms),
                group.end_audio_ms
                + float(self.reference_audio_offset_ms),
            )
        self._refresh_transcription_workspace()

    def _navigate_voice_group(self, direction: int) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None or not analysis.groups:
            return
        groups = analysis.groups
        current = self._active_voice_group()
        current_index = (
            next(
                (
                    index
                    for index, group in enumerate(groups)
                    if current is not None
                    and group.group_id == current.group_id
                ),
                0,
            )
        )
        target_index = max(
            0,
            min(len(groups) - 1, current_index + int(direction)),
        )
        self._set_active_voice_group(
            groups[target_index],
            update_range=True,
        )

    def _set_voice_group_loop(self, enabled: bool) -> None:
        self.loop_current_voice_group = bool(enabled)
        group = self._active_voice_group()
        if enabled and group is not None:
            self._set_active_voice_group(group, update_range=True)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.loop_box.setChecked(bool(enabled and group is not None))
        self._refresh_transcription_workspace()

    def _open_transcription_review_queue(self) -> None:
        editor = self.active_transcription_editor
        if editor is None:
            return
        offset_ms = float(self.reference_audio_offset_ms)
        items: list[tuple[str, float, float, str]] = []
        queue_truncated = False

        def append_item(
            item: tuple[str, float, float, str],
        ) -> bool:
            nonlocal queue_truncated
            if len(items) >= TRANSCRIPTION_REVIEW_QUEUE_LIMIT:
                queue_truncated = True
                return False
            items.append(item)
            return True

        invalid_ids = set()
        duplicate_ids = set()
        tracks_by_id = {
            int(track.track_id): track for track in self.tracks
        }
        fallback_region = (
            self.transcription_session.state.region
            or (
                float(editor.playhead_ms),
                float(editor.playhead_ms) + float(editor.canvas.beat_ms),
            )
        )
        for route in self.transcription_session.state.pending_routes:
            candidate = self.transcription_session.candidate_for_id(
                route.candidate_id
            )
            target = tracks_by_id.get(int(route.track_id))
            orphaned = candidate is None or target is None
            invalid = (
                not orphaned
                and self._candidate_invalid_for_track(candidate, target)
            )
            if not orphaned and not invalid:
                continue
            if candidate is None:
                start_ms, end_ms = fallback_region
            else:
                start_ms = float(candidate.start_ms) + offset_ms
                end_ms = (
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms
                )
            if not append_item(
                (
                    trf(
                        "{state} · 轨道 {track_id}",
                        state=(
                            trv("孤立路由")
                            if orphaned
                            else trv("失效路由")
                        ),
                        track_id=int(route.track_id),
                    ),
                    start_ms,
                    end_ms,
                    "",
                )
            ):
                break
        cached_flags = getattr(
            editor, "_transcription_candidate_flag_cache", None
        )
        if cached_flags is not None:
            invalid_ids.update(cached_flags[1])
            duplicate_ids.update(cached_flags[2])
        for alternate_id, primary_id in (
            editor.canvas._folded_candidate_primary.items()
        ):
            duplicate_ids.add(alternate_id)
            duplicate_ids.add(primary_id)
        for candidate_id in sorted(invalid_ids):
            candidate = self.transcription_session.candidate_for_id(
                candidate_id
            )
            if candidate is None:
                continue
            if not append_item(
                (
                    trf(
                        "越界候选 · {note}",
                        note=note_name(int(candidate.pitch)),
                    ),
                    float(candidate.start_ms) + offset_ms,
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms,
                    "",
                )
            ):
                break
        for candidate_id in sorted(duplicate_ids.difference(invalid_ids)):
            candidate = self.transcription_session.candidate_for_id(
                candidate_id
            )
            if candidate is None:
                continue
            if not append_item(
                (
                    trf(
                        "重叠或重复 · {note}",
                        note=note_name(int(candidate.pitch)),
                    ),
                    float(candidate.start_ms) + offset_ms,
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms,
                    "",
                )
            ):
                break
        reviewed_fragment_ids = (
            invalid_ids
            | duplicate_ids
            | set(self.transcription_session.state.rejected_candidate_ids)
        )
        for annotation in self.transcription_session.annotations:
            if (
                annotation.candidate_id in reviewed_fragment_ids
                or not {
                    "review_fragment",
                    "pitch_flicker",
                }.intersection(annotation.flags)
            ):
                continue
            candidate = self.transcription_session.candidate_for_id(
                annotation.candidate_id
            )
            if candidate is None:
                continue
            if not append_item(
                (
                    trf(
                        "疑似碎音 · {note}",
                        note=note_name(int(candidate.pitch)),
                    ),
                    float(candidate.start_ms) + offset_ms,
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms,
                    "",
                )
            ):
                break
        harmony = self.harmony_analysis
        if harmony is not None:
            conflicts = {item.segment_id for item in harmony.conflicts}
            for segment in harmony.chord_segments:
                if (
                    segment.segment_id not in conflicts
                    and (
                        segment.quality == "N"
                        or float(segment.confidence) >= 0.55
                    )
                ):
                    continue
                if not append_item(
                    (
                        trf(
                            "和声不确定 · {chord}",
                            chord=(
                                "N"
                                if segment.root_pc is None
                                else (
                                    f"{editor._pitch_class_label(segment.root_pc)} "
                                    f"{segment.quality}"
                                )
                            ),
                        ),
                        segment.start_audio_ms + offset_ms,
                        segment.end_audio_ms + offset_ms,
                        "",
                    )
                ):
                    break
        analysis = self.instrument_match_analysis
        if analysis is not None:
            confirmed_group_ids = {
                item.group_id
                for item in self.transcription_assist_review.active_voice_groups
                if item.confirmed_instrument_id is not None
            }
            for group in analysis.groups:
                matches = analysis.matches_for_group(group.group_id)
                confirmed = next(
                    (
                        item.confirmed_instrument_id
                        for item in self.transcription_assist_review.active_voice_groups
                        if item.group_id == group.group_id
                    ),
                    None,
                )
                if (
                    group.group_id in confirmed_group_ids
                    and confirmed is not None
                    and int(confirmed)
                    in {match.instrument_id for match in matches}
                ):
                    continue
                if (
                    matches
                    and matches[0].timbre_score is not None
                    and matches[0].total_score >= 0.45
                ):
                    continue
                if not append_item(
                    (
                        trf(
                            "乐器匹配待确认 · {role}",
                            role=trv(voice_role_source_label(group.role)),
                        ),
                        group.start_audio_ms + offset_ms,
                        group.end_audio_ms + offset_ms,
                        group.group_id,
                    )
                ):
                    break
        if not items:
            self.show_toast(tr("当前没有待审项目。"), kind="success")
            return
        if queue_truncated:
            self.show_toast(
                trf(
                    "待审项目较多，当前只显示优先级最高的 {count} 项。",
                    count=TRANSCRIPTION_REVIEW_QUEUE_LIMIT,
                ),
                kind="warning",
            )
        labels = [
            f"{index + 1}. {label} · {start_ms / 1000.0:.1f}s"
            for index, (label, start_ms, _end_ms, _group_id)
            in enumerate(items)
        ]
        selected, accepted = QInputDialog.getItem(
            editor,
            tr("待审队列"),
            tr("选择后只定位并设置 A–B，不会自动选择或写入音符："),
            labels,
            0,
            False,
        )
        if not accepted:
            return
        selected_index = labels.index(str(selected))
        _label, start_ms, end_ms, group_id = items[selected_index]
        self._set_transcription_region((start_ms, end_ms))
        if group_id and analysis is not None:
            group = next(
                (
                    item
                    for item in analysis.groups
                    if item.group_id == group_id
                ),
                None,
            )
            if group is not None:
                self.active_voice_group_id = group.group_id
        editor.focus_transcription_time_range(start_ms, end_ms)
        self._refresh_transcription_workspace()

    def _set_transcription_analysis_state(
        self,
        busy: bool,
        progress: int | None = None,
        *,
        status: object | None = None,
    ) -> None:
        self.transcription_analysis_busy = bool(busy)
        self.transcription_analysis_progress = (
            None
            if progress is None
            else max(0, min(100, int(progress)))
        )
        if status is not None:
            self._transcription_ui_status_spec = defer_tr(status)
            self.transcription_ui_status = str(self._transcription_ui_status_spec)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.refresh_transcription_projection()
            editor.set_transcription_analysis_ui(
                self.transcription_analysis_busy,
                self.transcription_analysis_progress,
                status=self._transcription_ui_status_spec,
            )

    def _start_workspace_transcription_analysis(self) -> None:
        audio_path = self.reference_audio.audio_path
        if not audio_path:
            self.show_toast(
                tr("请先载入 MP3/WAV 参考音频。"),
                kind="warning",
            )
            return
        if self.workspace_transcription_worker is not None:
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            return
        available, reason = transcription_backend_quick_status()
        if not available:
            QMessageBox.warning(
                self,
                tr("无法开始扒谱"),
                str(defer_tr(reason)),
            )
            return
        self._stop_preview(reset_playhead=False)
        self.workspace_transcription_generation += 1
        generation = self.workspace_transcription_generation
        state = self.transcription_session.state
        worker = TranscriptionAnalysisWorker(
            audio_path,
            self,
            analysis_mode=state.analysis_mode,
            sensitivity=state.sensitivity,
            cleanup_profile=state.cleanup_profile,
        )
        self.workspace_transcription_worker = worker
        worker.progress_changed.connect(
            lambda value, token=generation:
            self._workspace_transcription_progress(token, value)
        )
        worker.succeeded.connect(
            lambda result, token=generation:
            self._workspace_transcription_succeeded(token, result, False)
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._workspace_transcription_failed(token, message)
        )
        worker.cancelled.connect(
            lambda token=generation:
            self._workspace_transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._workspace_transcription_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_analysis_state(
            True,
            0,
            status=tr("正在分析参考音频…"),
        )
        worker.start()

    def _redecode_transcription_range(self) -> None:
        state = self.transcription_session.state
        if (
            self.workspace_transcription_worker is not None
            or not state.cache_key
            or state.region is None
        ):
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            return
        start_ms, end_ms = state.region
        self._stop_preview(reset_playhead=False)
        self.workspace_transcription_generation += 1
        generation = self.workspace_transcription_generation
        worker = TranscriptionRedecodeWorker(
            state.cache_key,
            start_ms - self.reference_audio_offset_ms,
            end_ms - self.reference_audio_offset_ms,
            state.sensitivity,
            self,
            cleanup_profile=state.cleanup_profile,
        )
        self.workspace_transcription_worker = worker
        worker.succeeded.connect(
            lambda result, token=generation:
            self._workspace_transcription_succeeded(token, result, True)
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._workspace_transcription_failed(token, message)
        )
        worker.cancelled.connect(
            lambda token=generation:
            self._workspace_transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._workspace_transcription_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_analysis_state(
            True,
            status=tr("正在从缓存证据重新解码 A–B；不会再次运行模型。"),
        )
        worker.start()

    def _restore_cached_transcription(
        self,
        *,
        status: str | None = None,
        cleanup_profile: str | None = None,
        rollback_cleanup_profile: str | None = None,
    ) -> int | None:
        cache_key = self.transcription_session.state.cache_key
        if (
            not cache_key
            or self.workspace_transcription_worker is not None
            or self._pending_transcription_cleanup_profile is not None
        ):
            return None
        requested_cleanup_profile = str(
            cleanup_profile
            if cleanup_profile is not None
            else self.transcription_session.state.cleanup_profile
        )
        if requested_cleanup_profile not in {
            "preserve",
            "balanced",
            "clean",
        }:
            raise ValueError(
                "unknown transcription cleanup profile: "
                f"{requested_cleanup_profile}"
            )
        self.workspace_transcription_generation += 1
        generation = self.workspace_transcription_generation
        if rollback_cleanup_profile is not None:
            self._pending_transcription_cleanup_profile = (
                generation,
                str(rollback_cleanup_profile),
                requested_cleanup_profile,
            )
        worker = TranscriptionCacheLoadWorker(
            cache_key,
            self,
            audio_path=str(self.reference_audio.audio_path or ""),
            expected_audio_fingerprint=(
                self.transcription_session.state.analysis_fingerprint
            ),
            analysis_mode=self.transcription_session.state.analysis_mode,
            sensitivity=self.transcription_session.state.sensitivity,
            cleanup_profile=requested_cleanup_profile,
        )
        self.workspace_transcription_worker = worker
        worker.succeeded.connect(
            lambda result, token=generation, current=worker:
            self._workspace_transcription_succeeded(
                token,
                result,
                False,
                True,
                current.current_audio_fingerprint,
            )
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._workspace_transcription_failed(token, message, quiet=True)
        )
        worker.cancelled.connect(
            lambda token=generation:
            self._workspace_transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._workspace_transcription_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_analysis_state(
            True,
            status=(
                str(status)
                if status is not None
                else tr("正在校验并恢复扒谱缓存…")
            ),
        )
        try:
            worker.start()
        except Exception:
            if self.workspace_transcription_worker is worker:
                self.workspace_transcription_worker = None
            self._rollback_cleanup_profile_transaction(generation)
            worker.deleteLater()
            raise
        return generation

    def _cleanup_profile_transaction(
        self,
        generation: int,
    ) -> tuple[int, str, str] | None:
        pending = self._pending_transcription_cleanup_profile
        if pending is None or pending[0] != generation:
            return None
        return pending

    def _rollback_cleanup_profile_transaction(
        self,
        generation: int | None = None,
    ) -> bool:
        pending = self._pending_transcription_cleanup_profile
        if pending is None:
            return False
        if generation is not None and pending[0] != generation:
            return False
        _token, previous, _requested = pending
        self._pending_transcription_cleanup_profile = None
        self.transcription_session.set_cleanup_profile(previous)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_cleanup_profile(previous)
        self._refresh_transcription_action_state()
        return True

    def _commit_cleanup_profile_transaction(
        self,
        generation: int,
        result: TranscriptionResult,
    ) -> bool:
        pending = self._cleanup_profile_transaction(generation)
        if pending is None:
            return True
        _token, _previous, requested = pending
        report = result.postprocess_report
        descriptor = result.evidence_descriptor
        result_profile = str(
            report.profile
            if report is not None
            else descriptor.cleanup_profile
            if descriptor is not None
            else ""
        )
        if result_profile != requested:
            self._rollback_cleanup_profile_transaction(generation)
            return False
        self.transcription_session.set_cleanup_profile(requested)
        self._pending_transcription_cleanup_profile = None
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_cleanup_profile(requested)
        self._refresh_transcription_action_state()
        return True

    def _workspace_transcription_progress(
        self, generation: int, value: int,
    ) -> None:
        if generation == self.workspace_transcription_generation:
            self._set_transcription_analysis_state(True, value)

    def _workspace_transcription_succeeded(
        self,
        generation: int,
        result: TranscriptionResult | None,
        interval: bool,
        restoring: bool = False,
        restored_audio_fingerprint: str = "",
    ) -> None:
        if generation != self.workspace_transcription_generation:
            return
        previous = self.transcription_session.state
        saved_fingerprint = (
            previous.analysis_fingerprint
            or self.transcription_assist_review.audio_fingerprint
        )
        restore_identity_mismatch = bool(
            restoring
            and (
                (
                    restored_audio_fingerprint
                    and saved_fingerprint
                    and restored_audio_fingerprint != saved_fingerprint
                )
                or (
                    self.reference_audio.audio_path
                    and not restored_audio_fingerprint
                )
            )
        )
        if restore_identity_mismatch:
            self._rollback_cleanup_profile_transaction(generation)
            self.transcription_assist_previous_candidates = tuple(
                self.transcription_session.candidates
            )
            self.transcription_assist_review = isolate_assist_review_for_audio(
                self.transcription_assist_review,
                restored_audio_fingerprint,
            )
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.transcription_assist_review_undo.clear()
            self.transcription_assist_review_redo.clear()
            self.transcription_session = TranscriptionSession(
                state=TranscriptionSessionState(
                    region=previous.region,
                    analysis_mode=previous.analysis_mode,
                    sensitivity=previous.sensitivity,
                    cleanup_profile=previous.cleanup_profile,
                )
            )
            self.transcription_result = None
            self._clear_transcription_review_history()
            editor = self.active_transcription_editor
            if editor is not None:
                editor.release_transcription_resources()
            self._refresh_transcription_workspace()
            self._set_transcription_status(
                tr("参考音频已变化；旧审阅状态已隔离，请重新分析整首。")
            )
            if not self.loading_project:
                self._autosave_project(
                    "transcription audio identity changed",
                    immediate=True,
                )
            return
        if result is None:
            self._rollback_cleanup_profile_transaction(generation)
            self._set_transcription_status(
                tr("扒谱缓存不存在或校验失败；请重新分析整首。")
            )
            return
        if not self._commit_cleanup_profile_transaction(generation, result):
            self._set_transcription_status(
                tr("碎音处理切换失败；已恢复原档位。")
            )
            return
        previous = self.transcription_session.state
        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        descriptor = result.evidence_descriptor
        fingerprint = (
            descriptor.audio_fingerprint if descriptor is not None else ""
        )
        backend_id = descriptor.backend_id if descriptor is not None else ""
        annotations = _session_candidate_annotations(result)
        if interval:
            start_ms, end_ms = previous.region or (0.0, 0.0)
            replaced = self.transcription_session.replace_region_candidates(
                result.candidates,
                start_ms - self.reference_audio_offset_ms,
                end_ms - self.reference_audio_offset_ms,
                annotations=annotations,
            )
            if (
                replaced.added_candidate_ids
                or replaced.removed_candidate_ids
            ):
                self._record_transcription_review_action("session")
            self.transcription_result = TranscriptionResult(
                tuple(self.transcription_session.candidates),
                result.cache_key,
                result.evidence_layers,
                True,
                descriptor,
                result.postprocess_report,
            )
            fragment_report = result.postprocess_report
            profile_label, profile_state = (
                _transcription_cleanup_ui_labels(
                    (
                        fragment_report.profile
                        if fragment_report is not None
                        else previous.cleanup_profile
                    ),
                    fragment_report,
                )
            )
            self._set_transcription_status(
                trf(
                    "区间重解码完成 · {profile} · {profile_state} · "
                    "新增 {added} · 替换 {removed} · 保护 {protected} · "
                    "自动合并 {merged} · 疑似碎音 {suspected} · "
                    "已隐藏 {suppressed}",
                    profile=profile_label,
                    profile_state=profile_state,
                    added=len(replaced.added_candidate_ids),
                    removed=len(replaced.removed_candidate_ids),
                    protected=len(replaced.protected_candidate_ids),
                    merged=(
                        fragment_report.automatic_merge_count
                        if fragment_report is not None
                        else 0
                    ),
                    suspected=(
                        fragment_report.suspected_fragment_count
                        if fragment_report is not None
                        else 0
                    ),
                    suppressed=(
                        fragment_report.suppressed_count
                        if fragment_report is not None
                        else 0
                    ),
                )
            )
        else:
            project_candidates = tuple(result.candidates)
            same_analysis = bool(
                previous.cache_key
                and previous.cache_key == result.cache_key
            )
            if same_analysis:
                restored_state = previous
                replaced = self.transcription_session.replace_all_candidates(
                    project_candidates,
                    annotations=annotations,
                )
                if (
                    replaced.added_candidate_ids
                    or replaced.removed_candidate_ids
                ):
                    self._record_transcription_review_action("session")
            else:
                restored_state = TranscriptionSessionState(
                    cache_key=result.cache_key,
                    analysis_fingerprint=fingerprint,
                    region=previous.region,
                    analysis_mode=(
                        descriptor.analysis_mode
                        if descriptor is not None
                        else previous.analysis_mode
                    ),
                    sensitivity=(
                        descriptor.decode_sensitivity
                        if descriptor is not None
                        else previous.sensitivity
                    ),
                    cleanup_profile=(
                        descriptor.cleanup_profile
                        if descriptor is not None
                        else previous.cleanup_profile
                    ),
                )
                self.transcription_session = TranscriptionSession(
                    project_candidates,
                    cache_key=result.cache_key,
                    backend_id=backend_id,
                    analysis_fingerprint=fingerprint,
                    state=restored_state,
                    annotations=annotations,
                )
            project_candidates = tuple(
                self.transcription_session.candidates
            )
            self.transcription_result = TranscriptionResult(
                tuple(project_candidates),
                result.cache_key,
                result.evidence_layers,
                result.cache_hit,
                descriptor,
                result.postprocess_report,
            )
            fragment_report = result.postprocess_report
            profile_label, profile_state = (
                _transcription_cleanup_ui_labels(
                    (
                        fragment_report.profile
                        if fragment_report is not None
                        else self.transcription_session.state.cleanup_profile
                    ),
                    fragment_report,
                )
            )
            self._set_transcription_status(
                trf(
                    "{prefix}{profile} · {profile_state} · "
                    "{count} 个候选 · 自动合并 {merged} · "
                    "疑似碎音 {suspected} · 已隐藏 {suppressed}",
                    prefix=trv(
                        "已恢复缓存 · "
                        if restoring or result.cache_hit
                        else "分析完成 · "
                    ),
                    profile=profile_label,
                    profile_state=profile_state,
                    count=len(project_candidates),
                    merged=(
                        fragment_report.automatic_merge_count
                        if fragment_report is not None
                        else 0
                    ),
                    suspected=(
                        fragment_report.suspected_fragment_count
                        if fragment_report is not None
                        else 0
                    ),
                    suppressed=(
                        fragment_report.suppressed_count
                        if fragment_report is not None
                        else 0
                    ),
                )
            )
        self._refresh_transcription_workspace()
        self._start_transcription_assist_analysis()
        self._autosave_project(
            "transcription interval decode"
            if interval
            else "transcription analysis",
            immediate=True,
        )

    def _workspace_transcription_failed(
        self,
        generation: int,
        message: str,
        *,
        quiet: bool = False,
    ) -> None:
        if generation != self.workspace_transcription_generation:
            return
        cleanup_rolled_back = self._rollback_cleanup_profile_transaction(
            generation
        )
        self._set_transcription_status(
            tr("碎音处理切换失败；已恢复原档位。")
            if cleanup_rolled_back
            else
            tr("缓存无法恢复；请重新分析整首。")
            if quiet
            else tr("扒谱分析失败。")
        )
        if not quiet:
            QMessageBox.warning(self, tr("扒谱分析失败"), message)

    def _workspace_transcription_cancelled(self, generation: int) -> None:
        if generation == self.workspace_transcription_generation:
            cleanup_rolled_back = (
                self._rollback_cleanup_profile_transaction(generation)
            )
            self._set_transcription_status(
                tr("碎音处理切换已取消；已恢复原档位。")
                if cleanup_rolled_back
                else tr("扒谱分析已取消。")
            )

    def _workspace_transcription_finished(
        self,
        generation: int,
        worker: QThread,
    ) -> None:
        # Generation gates result validity; identity gates thread ownership.
        # A stale worker may finish after a new one has been installed and
        # must never clear that replacement.
        if self.workspace_transcription_worker is not worker:
            return
        self.workspace_transcription_worker = None
        orphaned_cleanup_switch = (
            self._rollback_cleanup_profile_transaction(generation)
        )
        available, reason = transcription_backend_quick_status()
        self._set_transcription_analysis_state(False)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.set_transcription_analysis_ui(
                False,
                status=self._transcription_ui_status_spec,
                available=available,
                unavailable_reason=(
                    reason if not available else ""
                ),
            )
        self._refresh_transcription_action_state()
        if not available:
            self._set_transcription_status(reason)
        elif not self.reference_audio.audio_path:
            self._set_transcription_status(
                tr("载入参考音频后可开始整首分析")
            )
        elif orphaned_cleanup_switch:
            self._set_transcription_status(
                tr("碎音处理切换失败；已恢复原档位。")
            )
        if self.workspace_close_pending:
            self.workspace_close_pending = False
            QTimer.singleShot(0, self.close)

    @staticmethod
    def _normalise_editor_draft(
        draft_notes: Iterable[object],
    ) -> tuple[Note, ...] | None:
        """Validate the editor wire shape without changing musical meaning."""

        normalised: list[Note] = []
        try:
            for value in draft_notes:
                pitch = int(getattr(value, "pitch"))
                velocity = int(getattr(value, "vel"))
                start = float(getattr(value, "start"))
                duration = float(getattr(value, "dur"))
                note_type = int(getattr(value, "ntype"))
                if (
                    not 0 <= pitch <= 127
                    or not 0 <= velocity <= 127
                    or not math.isfinite(start)
                    or not math.isfinite(duration)
                    or start < 0.0
                    or duration <= 0.0
                ):
                    return None
                normalised.append(
                    Note(pitch, velocity, start, duration, note_type)
                )
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        return tuple(
            sorted(
                normalised,
                key=lambda note: (
                    float(note.start),
                    int(note.pitch),
                    float(note.dur),
                    int(note.vel),
                    int(note.ntype),
                ),
            )
        )

    def _commit_note_editor(
        self,
        request: TranscriptionEditorCommit,
    ) -> TranscriptionEditorCommitReport | None:
        """Commit one complete note-editor draft and all staged routes.

        Preflight is intentionally side-effect free.  When anything changes,
        all affected tracks and the transcription sidecar are captured by one
        project snapshot and saved once.
        """

        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        existing_track_ids = set(tracks_by_id)
        current_track = tracks_by_id.get(int(request.current_track_id))
        draft_notes = self._normalise_editor_draft(request.draft_notes)
        if current_track is None or draft_notes is None:
            QMessageBox.warning(
                self,
                tr("无法应用音符编辑"),
                tr("目标轨道已经失效，或草稿包含无效音符。"),
            )
            return None
        state = self.transcription_session.state
        historical_track_ids = {
            int(route.track_id)
            for route in (*state.pending_routes, *state.applied_routes)
        }
        new_tracks_by_id: dict[int, TrackState] = {}
        failed_new_track_ids: set[int] = set()
        for track_id, instrument_id in request.new_track_specs:
            if (
                int(track_id) in existing_track_ids
                or int(track_id) in historical_track_ids
                or int(instrument_id) not in BDO_INSTRUMENT_NAMES
                or int(instrument_id) in {0x04, 0x05, 0x0D}
            ):
                failed_new_track_ids.add(int(track_id))
                continue
            instrument_name = _ui_bdo_instrument_name(int(instrument_id))
            new_track = TrackState(
                track_id=int(track_id),
                notes=[],
                gm_program=0,
                is_percussion=False,
                display_name=trf(
                    "扒谱：{instrument}",
                    instrument=instrument_name,
                ),
                bdo_instrument_id=int(instrument_id),
                color=TRACK_COLORS[
                    (len(self.tracks) + len(new_tracks_by_id))
                    % len(TRACK_COLORS)
                ],
            )
            new_tracks_by_id[int(track_id)] = new_track
            tracks_by_id[int(track_id)] = new_track

        old_pending = set(state.pending_routes)
        old_applied = set(state.applied_routes)
        local_routes = set(request.routes)
        all_routes = tuple(sorted(old_pending.union(local_routes)))
        local_identity_valid = (
            str(request.cache_key or "") == str(state.cache_key or "")
            and str(request.analysis_fingerprint or "")
            == str(state.analysis_fingerprint or "")
        )

        created: set[CandidateRoute] = set()
        satisfied: set[CandidateRoute] = set()
        invalid: set[CandidateRoute] = set()
        orphaned: set[CandidateRoute] = set()
        unresolved_local: set[CandidateRoute] = set()
        successful: set[CandidateRoute] = set()
        additions: dict[int, list[Note]] = defaultdict(list)
        unused_draft_indices = set(range(len(draft_notes)))
        # A rejected/invalid staged candidate must not cross the project
        # boundary merely because its generated Note is also present in the
        # complete current-track draft.  Exact pre-existing notes remain
        # protected; a modified candidate note that no longer matches is a
        # normal manual edit by design.
        baseline_note_counts = Counter(current_track.notes)
        nonbaseline_draft_indices: set[int] = set()
        for index, note in enumerate(draft_notes):
            if baseline_note_counts[note] > 0:
                baseline_note_counts[note] -= 1
            else:
                nonbaseline_draft_indices.add(index)
        blocked_draft_indices: set[int] = set()
        draft_by_pitch: dict[int, tuple[list[float], list[int]]] = {}
        grouped_draft_indices: dict[int, list[int]] = defaultdict(list)
        for index, note in enumerate(draft_notes):
            grouped_draft_indices[int(note.pitch)].append(index)
        for pitch, indices in grouped_draft_indices.items():
            ordered = sorted(
                indices,
                key=lambda index: float(draft_notes[index].start),
            )
            draft_by_pitch[pitch] = (
                [float(draft_notes[index].start) for index in ordered],
                ordered,
            )
        formal_by_track: dict[
            int,
            dict[int, tuple[list[float], list[Note]]],
        ] = {}

        def formal_index(
            track: TrackState,
        ) -> dict[int, tuple[list[float], list[Note]]]:
            track_id = int(track.track_id)
            cached = formal_by_track.get(track_id)
            if cached is not None:
                return cached
            grouped: dict[int, list[Note]] = defaultdict(list)
            for note in track.notes:
                grouped[int(note.pitch)].append(note)
            cached = {}
            for pitch, notes in grouped.items():
                ordered = sorted(
                    notes,
                    key=lambda note: float(note.start),
                )
                cached[pitch] = (
                    [float(note.start) for note in ordered],
                    ordered,
                )
            formal_by_track[track_id] = cached
            return cached

        def matching_formal_notes(
            candidate: TranscriptionCandidate,
            track: TrackState,
        ) -> list[Note]:
            starts, notes = formal_index(track).get(
                int(candidate.pitch),
                ([], []),
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                self.reference_audio_offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            return [
                note
                for note in notes[first:last]
                if CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    note,
                    self.reference_audio_offset_ms,
                )
            ]

        def best_draft_match(
            candidate: TranscriptionCandidate,
            *,
            allowed_indices: set[int] | None = None,
        ) -> int | None:
            starts, indices = draft_by_pitch.get(
                int(candidate.pitch),
                ([], []),
            )
            project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate,
                self.reference_audio_offset_ms,
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                self.reference_audio_offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            matches = [
                index
                for index in indices[first:last]
                if index in unused_draft_indices
                if allowed_indices is None or index in allowed_indices
                if CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    draft_notes[index],
                    self.reference_audio_offset_ms,
                )
            ]
            if not matches:
                return None
            return min(
                matches,
                key=lambda index: (
                    abs(float(draft_notes[index].start) - project_start),
                    abs(
                        float(draft_notes[index].dur)
                        - CANDIDATE_NOTE_POLICY.note_duration_ms(
                            candidate
                        )
                    ),
                    index,
                ),
            )

        def block_staged_current_draft_note(
            route: CandidateRoute,
            candidate: TranscriptionCandidate | None,
            *,
            is_local: bool,
        ) -> None:
            if (
                not is_local
                or candidate is None
                or int(route.track_id) != int(current_track.track_id)
            ):
                return
            match_index = best_draft_match(
                candidate,
                allowed_indices=nonbaseline_draft_indices,
            )
            if match_index is None:
                return
            blocked_draft_indices.add(match_index)
            unused_draft_indices.discard(match_index)
            nonbaseline_draft_indices.discard(match_index)

        for route in all_routes:
            is_local = route in local_routes
            candidate = self.transcription_session.candidate_for_id(
                route.candidate_id
            )
            if (
                candidate is not None
                and route.candidate_id in state.rejected_candidate_ids
            ):
                invalid.add(route)
                if is_local:
                    unresolved_local.add(route)
                    block_staged_current_draft_note(
                        route,
                        candidate,
                        is_local=True,
                    )
                continue
            if is_local and int(route.track_id) in failed_new_track_ids:
                invalid.add(route)
                unresolved_local.add(route)
                block_staged_current_draft_note(
                    route,
                    candidate,
                    is_local=True,
                )
                continue
            if route in old_applied:
                satisfied.add(route)
                successful.add(route)
                continue
            if is_local and not local_identity_valid:
                unresolved_local.add(route)
                block_staged_current_draft_note(
                    route,
                    candidate,
                    is_local=True,
                )
                continue
            target = tracks_by_id.get(int(route.track_id))
            if target is None or candidate is None:
                orphaned.add(route)
                if is_local:
                    unresolved_local.add(route)
                continue
            if self._candidate_invalid_for_track(candidate, target):
                invalid.add(route)
                if is_local:
                    unresolved_local.add(route)
                    block_staged_current_draft_note(
                        route,
                        candidate,
                        is_local=True,
                    )
                continue
            if int(target.track_id) == int(current_track.track_id):
                match_index = best_draft_match(candidate)
                if match_index is None:
                    if is_local:
                        unresolved_local.add(route)
                    continue
                unused_draft_indices.remove(match_index)
                if matching_formal_notes(candidate, current_track):
                    satisfied.add(route)
                else:
                    created.add(route)
                successful.add(route)
                continue
            target_additions = additions[int(target.track_id)]
            if matching_formal_notes(candidate, target):
                satisfied.add(route)
                successful.add(route)
                continue
            addition = CANDIDATE_NOTE_POLICY.to_note(
                candidate,
                self.reference_audio_offset_ms,
            )
            target_additions.append(addition)
            starts, notes = formal_index(target).setdefault(
                int(addition.pitch),
                ([], []),
            )
            insertion = bisect_right(starts, float(addition.start))
            starts.insert(insertion, float(addition.start))
            notes.insert(insertion, addition)
            created.add(route)
            successful.add(route)

        final_pending = old_pending.difference(successful)
        final_applied = old_applied.union(successful)
        committed_draft_notes = tuple(
            note
            for index, note in enumerate(draft_notes)
            if index not in blocked_draft_indices
        )
        final_notes_by_id: dict[int, tuple[Note, ...]] = {
            int(current_track.track_id): committed_draft_notes,
        }
        for track_id, new_notes in additions.items():
            track = tracks_by_id[track_id]
            final_notes_by_id[track_id] = tuple(
                sorted(
                    (*track.notes, *new_notes),
                    key=lambda note: (
                        float(note.start),
                        int(note.pitch),
                        float(note.dur),
                        int(note.vel),
                        int(note.ntype),
                    ),
                )
            )
        created_track_ids = {
            track_id
            for track_id in new_tracks_by_id
            if track_id in final_notes_by_id
            and bool(final_notes_by_id[track_id])
        }

        notes_changed = any(
            tuple(tracks_by_id[track_id].notes) != notes
            for track_id, notes in final_notes_by_id.items()
        )
        sidecar_changed = (
            final_pending != old_pending or final_applied != old_applied
        )
        project_changed = (
            notes_changed or sidecar_changed or bool(created_track_ids)
        )

        if project_changed:
            self._push_project_snapshot()
            self._stop_preview(reset_playhead=False)
            for track_id in sorted(created_track_ids):
                self.tracks.append(new_tracks_by_id[track_id])
            for track_id, notes in final_notes_by_id.items():
                track = tracks_by_id[track_id]
                if tuple(track.notes) == notes:
                    continue
                track.notes = list(notes)
                track.notes_optimized = False
            if sidecar_changed:
                self.transcription_session.commit_project_routes(
                    successful,
                    pending_routes=final_pending,
                )
            self.timeline.set_tracks(self.tracks)
            self._select_track(current_track)
            self._on_track_changed()
            self._mark_conversion_check_dirty()
            self._autosave_project(
                "transcription editor apply"
                if local_routes or successful
                else "note edit",
                immediate=True,
            )
            self.status_label.setText(
                trf(
                    "已更新 {track} · {count} 音符",
                    track=current_track.display_name,
                    count=len(current_track.notes),
                )
            )
            self.show_toast(
                tr("音符编辑已作为一个工程操作写入；可整批撤销。"),
                kind="success",
            )
            # Formal Apply crosses into the project undo boundary.  Review
            # history must not retain stale session snapshots behind it.
            self._clear_transcription_review_history()
            self._schedule_transcription_assist_refresh()

        report = TranscriptionEditorCommitReport(
            tuple(created),
            tuple(satisfied),
            tuple(invalid),
            tuple(orphaned),
            tuple(unresolved_local),
            project_changed,
        )
        self._set_transcription_status(
            trf(
                "已应用 {created} 个音符 · 已满足 {satisfied} · "
                "保留失效 {invalid} · 孤立 {orphaned}",
                created=report.created_count,
                satisfied=report.satisfied_count,
                invalid=report.invalid_count,
                orphaned=report.orphaned_count,
            )
        )
        return report

    def _create_workspace_status_state(self) -> None:
        """Keep legacy status sinks without reserving a visible bottom bar."""

        # Async paths still publish status and diagnostic summaries through
        # these labels.  Toasts are the visible surface; the labels remain
        # hidden state owned by the workspace for compatibility with those
        # paths and tests.
        self.status_label = QLabel(tr("就绪"), self.workspace_page)
        self.status_label.setObjectName("Status")
        self.status_label.hide()
        self.inspector_text = QLabel("", self.workspace_page)
        self.inspector_text.setObjectName("InspectorText")
        self.inspector_text.hide()

    def _apply_style(self) -> None:
        self.setFont(QFont("Microsoft YaHei UI", 9))
        style_sheet = """
            QWidget#Root { background: #151515; color: #f3f1ea; }
            QDialog QLabel { color: #ddd7cf; }
            QDialog#SettingsDialog {
                background: #151515;
                color: #f3f1ea;
            }
            QFrame#SettingsHeader {
                background: #191919;
                border: 0;
                border-bottom: 1px solid #4a3b27;
            }
            QWidget#SettingsContent {
                background: #151515;
                border: 0;
            }
            QStackedWidget#SettingsPages {
                background: #151515;
                border: 0;
            }
            QListWidget#SettingsNav {
                background: #181818;
                border: 0;
                border-right: 1px solid #302f2d;
                outline: 0;
                padding: 0;
            }
            QListWidget#SettingsNav::item {
                background: #181818;
                color: #aaa39a;
                border: 0;
                border-right: 1px solid #302f2d;
                min-height: 52px;
                padding: 0 18px;
                font-weight: 700;
            }
            QListWidget#SettingsNav::item:hover {
                background: #202020;
                color: #e5dfd6;
            }
            QListWidget#SettingsNav::item:selected {
                background: #25211b;
                color: #f0c66f;
                border-left: 3px solid #f5a524;
                border-right: 1px solid #4a3b27;
            }
            QWidget#SettingsGeneralPage, QWidget#SettingsMidiPage,
            QWidget#SettingsAudioPage {
                background: #151515;
            }
            QScrollArea#SettingsScroll, QScrollArea#SettingsMidiScroll,
            QScrollArea#SettingsAudioScroll {
                border: 0;
                background: #151515;
            }
            QScrollArea#SettingsScroll > QWidget > QWidget,
            QScrollArea#SettingsMidiScroll > QWidget > QWidget,
            QScrollArea#SettingsAudioScroll > QWidget > QWidget {
                background: #151515;
            }
            QDialog#SettingsDialog QLabel { color: #ddd7cf; }
            QLabel#SettingsTitle {
                color: #f3f1ea;
                font-size: 24px;
                font-weight: 900;
            }
            QFrame#SettingsSection {
                background: #1e1e1e;
                border: 1px solid #353332;
                border-radius: 7px;
            }
            QLabel#SettingsSectionTitle {
                color: #f0c66f;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#SettingsFieldLabel { color: #c7c0b8; }
            QLabel#OwnerStatus { color: #bdb6ad; }
            QLabel#OwnerStatus[ownerError="true"] { color: #e06c62; }
            QFrame#SettingsModeRow {
                background: #1a1a1a;
                border: 1px solid #34322f;
                border-radius: 6px;
                padding: 7px 9px;
            }
            QDialog#SettingsDialog QSpinBox {
                min-height: 27px;
                padding: 2px 7px;
            }
            QDialog#SettingsDialog QRadioButton { color: #ddd7cf; spacing: 7px; }
            QDialog#SettingsDialog QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 1px solid #6a6259;
                background: #1b1b1b;
            }
            QDialog#SettingsDialog QRadioButton::indicator:checked {
                background: #f5a524;
                border: 3px solid #f5a524;
            }
            QDialog#SettingsDialog QDialogButtonBox {
                background: #1b1b1b;
                border: 0;
                border-top: 1px solid #34322f;
                padding: 12px 18px;
            }
            QDialog#ThanksDialog { background: #151515; color: #f3f1ea; }
            QFrame#Panel {
                background: #222222;
                border: 1px solid #343434;
                border-radius: 4px;
            }
            QStackedWidget#MainPages, QWidget#WorkspacePage, QWidget#HomePage {
                background: #151515;
                border: 0;
            }
            QFrame#HomeHero {
                background: #191919;
                border: 0;
                border-bottom: 1px solid #4a3b27;
                border-radius: 0;
            }
            QLabel#HomeEyebrow {
                color: #c28b38;
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 2px;
            }
            QLabel#HomeTitle {
                color: #f3f1ea;
                font-size: 24px;
                font-weight: 900;
            }
            QFrame#HomeCard {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#HomeCard[density="primary"] {
                background: transparent;
                border: 0;
            }
            QWidget#HomeSideColumn {
                border: 0;
                border-left: 1px solid #383532;
            }
            QLabel#HomeCardTitle {
                color: #eee9e1;
                font-size: 16px;
                font-weight: 900;
            }
            QFrame#HomeCard[density="primary"] QLabel#HomeCardTitle {
                color: #f0c66f;
            }
            QLabel#HomeCount {
                min-width: 16px;
                color: #9f978d;
                background: transparent;
                border: 0;
                border-radius: 0;
                font-size: 10px;
                font-weight: 700;
            }
            QListWidget#HomeList {
                background: transparent;
                border: 0;
                border-radius: 7px;
                padding: 2px 0;
                outline: 0;
            }
            QListWidget#HomeList::item {
                color: #ddd7cf;
                background: transparent;
                border: 0;
                border-bottom: 1px solid #2b2a28;
                border-radius: 0;
                padding: 8px 10px;
            }
            QListWidget#HomeList::item:hover {
                background: #242321;
            }
            QListWidget#HomeList::item:selected {
                background: #382a18;
                border: 0;
                border-bottom: 1px solid #51402b;
                color: #fff1d1;
            }
            QWidget#HomePage QPushButton[homeAction="true"] {
                border-radius: 2px;
            }
            QListWidget#HomeList QScrollBar:vertical {
                width: 8px;
                background: transparent;
                margin: 2px 0;
            }
            QListWidget#HomeList QScrollBar::handle:vertical {
                min-height: 28px;
                background: #504a43;
                border-radius: 4px;
            }
            QListWidget#HomeList QScrollBar::add-line:vertical,
            QListWidget#HomeList QScrollBar::sub-line:vertical {
                height: 0;
            }
            QFrame#Toolbar {
                background: #202020;
                border: 0;
                border-bottom: 1px solid #393735;
                border-radius: 0;
            }
            QFrame#Toolbar QFrame#CommandGroup {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#Toolbar QPushButton, QFrame#Toolbar QLineEdit {
                border-radius: 2px;
                min-height: 24px;
                padding: 3px 8px;
            }
            QFrame#ToolbarSeparator {
                color: #46423d;
                max-width: 1px;
                margin: 3px 2px;
            }
            QFrame#Inspector {
                background: #202020;
                border: 0;
                border-top: 1px solid #393735;
                border-radius: 0;
            }
            QWidget#TimelineWorkspace, QWidget#TimelineCanvas {
                background: #151515;
                border: 0;
            }
            QFrame#TimelineControlBar {
                background: #1d1d1d;
                border: 0;
                border-bottom: 1px solid #353332;
                border-radius: 0;
            }
            QFrame#TimelineControlBar QPushButton {
                min-height: 24px;
                padding: 3px 8px;
            }
            QLabel#TimelineMeta {
                color: #9f9991;
                padding: 0 5px;
            }
            QLabel#TimelineControlLabel {
                color: #77716a;
                font-size: 10px;
            }
            QFrame#PerformanceStrip {
                background: #191919;
                border: 0;
                border-top: 1px solid #302e2b;
                border-radius: 0;
            }
            QLabel#PerformanceCaption {
                color: #7f7971;
                font-size: 9px;
                font-weight: 700;
            }
            QLabel#PerformanceMetric {
                color: #b8b0a6;
                font-size: 10px;
                font-family: Consolas, monospace;
            }
            QFrame#TimelineSeparator {
                color: #413d38;
                max-width: 1px;
                margin: 4px 3px;
            }
            QFrame#TranscriptionToolsSlot {
                background: transparent;
                border: 0;
            }
            QWidget#TranscriptionEditorPanel,
            QWidget#TranscriptionWaveformLane {
                background: #111313;
                border: 0;
            }
            QFrame#TranscriptionAnalysisBar, QFrame#TranscriptionReviewBar {
                background: #1d1f1f;
                border: 0;
                border-bottom: 1px solid #383733;
                border-radius: 0;
            }
            QFrame#TranscriptionReviewBar {
                border-top: 1px solid #383733;
                border-bottom: 0;
            }
            QFrame#TranscriptionAnalysisBar QPushButton,
            QFrame#TranscriptionReviewBar QPushButton,
            QFrame#TranscriptionReviewBar QToolButton {
                min-height: 27px;
                padding: 2px 9px;
                border-radius: 3px;
            }
            QFrame#EditorToolbar {
                background: #1d1d1b;
                border: 1px solid #3b3730;
                border-bottom: 2px solid #57401e;
                border-radius: 7px;
            }
            QFrame#EditorToolbar QPushButton {
                min-height: 22px;
                padding: 3px 8px;
            }
            QLabel#EditorTrackTitle {
                color: #f5f1e9;
                font-size: 15px;
                font-weight: 900;
            }
            QLabel#EditorTrackMeta {
                color: #8faaa0;
                font-size: 10px;
                font-family: Consolas, "Microsoft YaHei UI";
            }
            QFrame#EditorTransport {
                background: #171817;
                border: 1px solid #343833;
                border-radius: 7px;
            }
            QFrame#EditorWorkspace {
                background: #1a1b1e;
                border: 1px solid #3d3e42;
                border-radius: 6px;
            }
            QFrame#VelocityHeader {
                background: #202020;
                border: 0;
                border-top: 1px solid #353332;
                border-radius: 0;
                min-height: 32px;
                max-height: 32px;
            }
            QFrame#NoteInspectorTop {
                background: #202020;
                border: 1px solid #3d3932;
                border-radius: 5px;
            }
            QPushButton#InspectorMode:checked {
                background: #6f4b17;
                border-color: #dda03a;
                color: #fff2d2;
                font-weight: 800;
            }
            QPushButton#DrawMode:checked {
                background: #245943;
                border-color: #62b98b;
                color: #e6fff0;
                font-weight: 800;
            }
            QPushButton#VelocityToggle:checked {
                background: #284c49;
                border-color: #63c7bd;
                color: #e3fffb;
                font-weight: 800;
            }
            QLabel#InspectorSelection {
                background: #191919;
                border: 1px solid #383531;
                border-radius: 4px;
                color: #d9d3ca;
                padding: 3px 6px;
            }
            QFrame#NoteInspectorTop QLineEdit,
            QFrame#NoteInspectorTop QComboBox {
                min-height: 20px;
                padding: 3px 6px;
            }
            QComboBox#ArticulationCombo {
                border-color: #9b7533;
                color: #f0d39b;
                font-weight: 700;
            }
            QPushButton#ArticulationChip {
                background: #28251f;
                border: 1px solid #575044;
                border-radius: 4px;
                color: #d8d1c5;
                min-height: 23px;
                padding: 1px 6px;
            }
            QPushButton#ArticulationChip:hover { border-color: #b88939; color: #f3dfb4; }
            QPushButton#ArticulationChip:checked {
                background: #78541c;
                border-color: #e0a339;
                color: #fff4db;
                font-weight: 800;
            }
            QLabel#EditorTime {
                color: #e4c17c;
                font-family: Consolas, "Microsoft YaHei UI";
            }
            QFrame#EditorFooter {
                background: #202020;
                border: 1px solid #353332;
                border-radius: 5px;
                max-height: 31px;
            }
            QDialog#MidiNoteEditorDialog QFrame#EditorToolbar,
            QDialog#MidiNoteEditorDialog QFrame#EditorTransport,
            QDialog#MidiNoteEditorDialog QFrame#EditorWorkspace,
            QDialog#MidiNoteEditorDialog QFrame#NoteInspectorTop,
            QDialog#MidiNoteEditorDialog QFrame#EditorFooter,
            QDialog#MidiNoteEditorDialog QLabel#InspectorSelection,
            QDialog#MidiNoteEditorDialog QPushButton,
            QDialog#MidiNoteEditorDialog QLineEdit,
            QDialog#MidiNoteEditorDialog QComboBox {
                border-radius: 0;
            }
            QDialog#MidiNoteEditorDialog QScrollBar::handle {
                border-radius: 0;
            }
            QLabel#PanelTitle {
                color: #f3f1ea;
                font-size: 15px;
                font-weight: 800;
            }
            QLabel#SectionLabel {
                color: #e4c17c;
                font-size: 12px;
                font-weight: 800;
                padding-top: 2px;
            }
            QFrame#OptimizerHeader, QFrame#OptimizerOptions, QTextEdit#OptimizerReport {
                background: #201f1c;
                border: 1px solid #3d3932;
                border-radius: 9px;
            }
            QLabel#OptimizerTitle {
                color: #f5a524;
                font-size: 19px;
                font-weight: 900;
            }
            QLabel#OptimizerSummary {
                color: #d6b675;
                font-size: 12px;
                font-weight: 800;
                padding: 1px 2px;
            }
            QFrame#OptimizerOptions QCheckBox {
                color: #e5dfd6;
                min-width: 150px;
            }
            QTextEdit#OptimizerReport {
                padding: 7px;
                color: #d6d1c9;
                font-family: Consolas, "Microsoft YaHei UI";
                font-size: 11px;
            }
            QLabel#ToolbarText { color: #c7c0b8; }
            QLabel#Muted { color: #a8a29e; }
            QLabel#ThanksTitle {
                color: #f3f1ea;
                font-size: 23px;
                font-weight: 900;
            }
            QLabel#ThanksSubtitle {
                color: #aaa39a;
                font-size: 12px;
                line-height: 140%;
            }
            QFrame#ThanksTextPanel {
                background: #1e1e1e;
                border: 1px solid #353332;
                border-radius: 7px;
            }
            QFrame#ThanksHeader {
                background: #191919;
                border: 0;
                border-bottom: 1px solid #4a3b27;
                border-radius: 0;
            }
            QLabel#ThanksSectionLabel {
                color: #f0c66f;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#ThanksMutedNote {
                color: #aaa39a;
                font-size: 11px;
                line-height: 135%;
            }
            QTextEdit#ThanksText {
                background: #181818;
                border: 1px solid #34322f;
                border-radius: 5px;
                color: #d8d3cc;
                padding: 16px 18px;
            }
            QLabel#ToolbarBadge {
                background: #1f1f1f;
                border: 1px solid #313131;
                border-radius: 3px;
                padding: 5px 9px;
                color: #e5dfd6;
            }
            QLabel#CheckCard {
                background: #202020;
                border: 1px solid #3f3a33;
                border-radius: 4px;
                color: #f3f1ea;
                padding: 8px 10px;
                font-weight: 800;
            }
            QWidget#TrackCard {
                background: #262626;
                border: 1px solid #363636;
                border-radius: 3px;
            }
            QWidget#TrackContainer, QWidget#TrackViewport {
                background: #1a1a1a;
            }
            QLabel#TrackTitle {
                color: #f3f1ea;
                font-weight: 800;
            }
            QLineEdit, QComboBox, QTextEdit {
                background: #1e1e1e;
                border: 1px solid #3a3a3a;
                border-radius: 3px;
                color: #f3f1ea;
                padding: 6px 8px;
                selection-background-color: #8f6b2e;
            }
            QListWidget {
                background: #191919;
                border: 1px solid #3a3834;
                border-radius: 4px;
                color: #ddd7cf;
                outline: 0;
                padding: 4px;
            }
            QListWidget::item {
                border-bottom: 1px solid #2c2b29;
                padding: 8px 7px;
            }
            QListWidget::item:selected {
                background: #4a391f;
                color: #fff3d6;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border-color: #d9a441;
            }
            QPushButton {
                background: #2b2b2b;
                border: 1px solid #404040;
                border-radius: 3px;
                color: #f3f1ea;
                padding: 6px 10px;
            }
            QPushButton:hover { background: #343434; border-color: #55504a; }
            QPushButton:checked {
                background: #5d451e;
                border-color: #d9a441;
            }
            QPushButton[kind="primary"] {
                background: #302a20;
                border-color: #7a5a22;
            }
            QPushButton[kind="convert"] {
                background: #f5a524;
                color: #1b1305;
                border-color: #f5a524;
                font-weight: 900;
                min-width: 96px;
            }
            QPushButton[kind="ghost"] {
                background: transparent;
                border-color: #3a3a3a;
                color: #c9c2ba;
            }
            QPushButton:disabled {
                color: #8d8780;
                background: #232323;
                border-color: #34322f;
            }
            QCheckBox { color: #d8d3cc; spacing: 7px; }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border-radius: 2px;
                border: 1px solid #56504a;
                background: #1f1f1f;
            }
            QCheckBox::indicator:checked {
                background: #f5a524;
                border-color: #f7c36c;
            }
            QScrollArea {
                border: 0;
                background: transparent;
            }
            QWidget#PianoScrollCorner {
                background: #171918;
            }
            QScrollBar:vertical {
                background: #1b1b1b;
                width: 12px;
                margin: 1px;
                border: 0;
                border-left: 1px solid #2c2b29;
            }
            QScrollBar:horizontal {
                background: #1b1b1b;
                height: 12px;
                margin: 1px;
                border: 0;
                border-top: 1px solid #2c2b29;
            }
            QScrollBar::handle:vertical {
                background: #4a4640;
                min-height: 32px;
                border-radius: 4px;
                margin: 2px 1px;
            }
            QScrollBar::handle:horizontal {
                background: #4a4640;
                min-width: 32px;
                border-radius: 4px;
                margin: 1px 2px;
            }
            QScrollBar::handle:vertical:hover,
            QScrollBar::handle:horizontal:hover {
                background: #766b5e;
            }
            QScrollBar::handle:vertical:pressed,
            QScrollBar::handle:horizontal:pressed {
                background: #b27b25;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                subcontrol-origin: margin;
                background: transparent;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                subcontrol-origin: margin;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical,
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QAbstractScrollArea::corner { background: #1b1b1b; }
            QScrollBar#TimelineScroll:vertical,
            QScrollBar#PianoPitchScroll:vertical {
                background: #171918;
                border-left-color: #292c2a;
            }
            QScrollBar#PianoTimeScroll:horizontal {
                background: #171918;
                border-top-color: #292c2a;
            }
            QScrollBar#TimelineScroll::handle:vertical,
            QScrollBar#PianoPitchScroll::handle:vertical,
            QScrollBar#PianoTimeScroll::handle:horizontal {
                background: #626660;
            }
            QScrollBar#TimelineScroll::handle:vertical:hover,
            QScrollBar#PianoPitchScroll::handle:vertical:hover,
            QScrollBar#PianoTimeScroll::handle:horizontal:hover {
                background: #8b806f;
            }
            QScrollBar#TimelineScroll::handle:vertical:pressed,
            QScrollBar#PianoPitchScroll::handle:vertical:pressed,
            QScrollBar#PianoTimeScroll::handle:horizontal:pressed {
                background: #c58a2d;
            }
            QSlider::groove:horizontal {
                height: 5px;
                background: #3a3a3a;
                border-radius: 0px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 16px;
                margin: -6px 0;
                border-radius: 2px;
                background: #f5a524;
            }
            """
        dark = self._system_uses_dark_theme()
        self.setStyleSheet(build_fluent_stylesheet(style_sheet, dark))
        refresh_fluent_icons(self, dark)

    @staticmethod
    def _system_uses_dark_theme() -> bool:
        return system_uses_dark_theme()

    def _browse_midi(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择 MIDI 文件"),
            str(DEFAULT_MIDI_DIR),
            tr("MIDI 文件 (*.mid *.midi);;所有文件 (*.*)"),
        )
        if path:
            self._open_midi_path(Path(path))

    def _open_midi_path(self, path: Path) -> None:
        if self.active_transcription_editor is not None:
            self.active_transcription_editor.release_transcription_resources()
        self.reference_layer_settings = normalize_reference_layer_settings(
            DEFAULT_REFERENCE_LAYER_SETTINGS
        )
        self.transcription_session = TranscriptionSession()
        self.transcription_result = None
        self.reference_audio.set_audio_path(None, notify=False)
        self.reference_audio.set_volume_percent(50, notify=False)
        self._set_reference_alignment(0.0, 0.0)
        self.reference_audio_path = ""
        self.reference_audio_relink_required = False
        self.midi_path = str(path)
        self.autosave_project_dir = None
        self.autosave_source_copy = None
        self.file_label.setProperty("i18nSkip", True)
        self.file_label.setProperty("i18nSkipText", True)
        self.file_label.setText(path.name)
        self.output_name.setText(path.stem)
        if not self._load_midi_info(str(path)):
            return
        self._autosave_project("import midi", immediate=True)
        self._mark_conversion_check_dirty()
        self._record_recent("midi", path, path.stem)
        self._show_workspace()
        self.status_label.setText(tr("建议转换检查"))
        self.inspector_text.clear()
        self.show_toast(
            tr("MIDI 已载入。建议先点“转换检查”，确认音域、FX 和打击乐映射后再导出。"),
            kind="warning",
            duration_ms=4200,
        )

    def _open_bdo_score_path(self, path: Path) -> None:
        if self.active_transcription_editor is not None:
            self.active_transcription_editor.release_transcription_resources()
        self.reference_layer_settings = normalize_reference_layer_settings(
            DEFAULT_REFERENCE_LAYER_SETTINGS
        )
        self.transcription_session = TranscriptionSession()
        self.transcription_result = None
        self.reference_audio.set_audio_path(None, notify=False)
        self.reference_audio.set_volume_percent(50, notify=False)
        self._set_reference_alignment(0.0, 0.0)
        self.reference_audio_path = ""
        self.reference_audio_relink_required = False
        if not self._load_bdo_info(path):
            return
        self.autosave_project_dir = None
        self.autosave_source_copy = None
        self.file_label.setProperty("i18nSkip", True)
        self.file_label.setProperty("i18nSkipText", True)
        self.file_label.setText(path.name)
        self.output_name.setText(path.stem or path.name)
        self.midi_path = str(path)
        self._autosave_project("open bdo score", immediate=True)
        self._mark_conversion_check_dirty()
        self._record_recent("bdo", path, path.stem or path.name)
        self._show_workspace()

    def _load_bdo_info(self, path: Path) -> bool:
        try:
            document = read_score(path)
            snapshot = read_bdo_score(path, allow_trailing_data=True)
            tracks = track_states_from_bdo_score(snapshot)
            if not tracks:
                raise ValueError(tr("游戏曲谱不包含乐器轨道"))
        except Exception as exc:
            self.status_label.setText(tr("打开游戏曲谱失败"))
            self.inspector_text.setText(trf("无法读取游戏曲谱：{error}", error=exc))
            QMessageBox.warning(self, tr("打开游戏曲谱失败"), trf("无法读取游戏曲谱：{error}", error=exc))
            return False

        self._stop_preview()
        self.project_commands.clear()
        self._clear_track_selection()
        self.source_format = "bdo"
        self.bdo_source_snapshot = snapshot
        self.bdo_source_document = document
        self.bpm = int(snapshot.bpm)
        self.time_sig = int(snapshot.time_signature)
        self.tempo_changes = 1
        self.lyric_events = []
        self.owner_id = int(snapshot.owner_id)
        self.char_name = snapshot.character_name_1 or snapshot.character_name_2 or self.char_name
        self.bpm_override = None
        self.transpose = 0
        self.velocity_mode = "off"
        self.vel_range = None
        self.vel_floor = None
        self.vel_step = None
        settings = next((track.settings for track in snapshot.tracks if track.settings), ())
        if len(settings) >= 8:
            self.reverb = int(settings[1])
            self.delay = int(settings[3])
            chorus = (int(settings[5]), int(settings[6]), int(settings[7]))
            self.chorus = chorus if any(chorus) else None
        self.tracks = tracks
        self.selected_track = None
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
        self._reset_timeline_position()
        self._on_track_changed()
        self.status_label.setText(tr("游戏曲谱已打开"))
        self.inspector_text.setText(trf(
            "已打开游戏曲谱：{file} · {tracks} 轨 · {notes} 音符",
            file=path.name,
            tracks=len(self.tracks),
            notes=sum(len(track.notes) for track in self.tracks),
        ))
        self._sync_preview_state()
        return True

    def _open_project(self) -> None:
        start_dir = str(AUTO_SAVE_DIR if AUTO_SAVE_DIR.is_dir() else ROOT)
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("打开自动保存工程"),
            start_dir,
            tr("工程文件 (project.json);;JSON 文件 (*.json);;所有文件 (*.*)"),
        )
        if path:
            self._load_project(Path(path))

    def _project_snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot.capture(
            self.tracks,
            self.reverb,
            self.delay,
            self.chorus,
            self.transcription_session.to_payload(),
            self.transcription_assist_review.to_payload(),
        )

    def _push_project_snapshot(self) -> None:
        self.project_commands.push(self._project_snapshot())

    def _restore_project_snapshot(self, snapshot: ProjectSnapshot, action: str) -> None:
        self._stop_preview(reset_playhead=False)
        self.tracks = snapshot.restored_tracks()
        self.reverb, self.delay, self.chorus = snapshot.reverb, snapshot.delay, snapshot.chorus
        restored_review = snapshot.restored_transcription_state()
        if restored_review is not None:
            self.transcription_session = TranscriptionSession.from_payload(
                restored_review,
                self.transcription_session.candidates,
                backend_id=(
                    self.transcription_result.evidence_descriptor.backend_id
                    if self.transcription_result is not None
                    and self.transcription_result.evidence_descriptor is not None
                    else ""
                ),
            )
        allow_assist_review_recovery = True
        restored_assist = snapshot.restored_transcription_assist_state()
        if restored_assist is not None:
            restored_assist_review = (
                TranscriptionAssistReviewState.from_payload(restored_assist)
            )
            current_audio_fingerprint = self._current_analysis_fingerprint()
            assist_identity_matches = bool(
                current_audio_fingerprint
                and restored_assist_review.audio_fingerprint
                == current_audio_fingerprint
            )
            self.transcription_assist_review = (
                isolate_assist_review_for_audio(
                    restored_assist_review,
                    current_audio_fingerprint,
                )
            )
            if not assist_identity_matches:
                allow_assist_review_recovery = False
                # Project undo may restore a sidecar captured for reference
                # audio that is no longer loaded.  Do not let current-song
                # candidates masquerade as the old recovery anchors and
                # reactivate its key/chord/voice decisions.
                self.transcription_assist_previous_candidates = ()
        self._clear_transcription_review_history()
        self.selected_track = None
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
        self.timeline.set_time_range(
            *(
                self.transcription_session.state.region
                if self.transcription_session.state.region is not None
                else (None, None)
            )
        )
        self._refresh_transcription_workspace()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis(
                allow_review_recovery=allow_assist_review_recovery,
            )
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project(action, immediate=True)
        self.status_label.setText(tr("已撤销工程修改" if action == "project undo" else "已重做工程修改"))

    def _undo_project(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)) and not focus.isReadOnly():
            focus.undo()
            return
        snapshot = self.project_commands.undo(self._project_snapshot())
        if snapshot is not None:
            self._restore_project_snapshot(snapshot, "project undo")

    def _redo_project(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)) and not focus.isReadOnly():
            focus.redo()
            return
        snapshot = self.project_commands.redo(self._project_snapshot())
        if snapshot is not None:
            self._restore_project_snapshot(snapshot, "project redo")

    def _load_project(self, project_path: Path) -> None:
        try:
            payload = migrate_project(json.loads(project_path.read_text(encoding="utf-8")))
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("打开工程失败"),
                trf("无法读取工程文件：{error}", error=exc),
            )
            return

        source_format = str(payload.get("source_format") or "midi")
        if source_format not in {"midi", "bdo", "project"}:
            source_format = "midi"
        legacy_absolute_paths = (
            str(payload.get("path_policy") or "") != "project-relative-v1"
        )
        source_path = resolve_project_file_reference(
            project_path.parent,
            payload.get("source_midi_path"),
            allow_legacy_absolute=legacy_absolute_paths,
        )
        original_path = resolve_project_file_reference(
            project_path.parent,
            payload.get("original_midi_path"),
            allow_legacy_absolute=legacy_absolute_paths,
        )
        midi_path = (
            source_path
            if source_path is not None and source_path.is_file()
            else original_path
        )
        if source_format != "project" and (
            midi_path is None or not midi_path.is_file()
        ):
            QMessageBox.warning(
                self,
                tr("打开工程失败"),
                tr("工程里的源文件和自动保存副本都不存在。"),
            )
            return

        self.loading_project = True
        try:
            self.reference_audio.set_audio_path(None, notify=False)
            self.reference_audio.set_volume_percent(
                int(payload.get("reference_audio_volume", 50)),
                notify=False,
            )
            self._set_reference_alignment(
                float(payload.get("reference_audio_offset_ms", 0.0) or 0.0),
                float(payload.get("beat_origin_ms", 0.0) or 0.0),
            )
            self.reference_layer_settings = (
                normalize_reference_layer_settings(
                    payload.get("reference_layers")
                )
            )
            self.reference_audio_path = ""
            self.reference_audio_relink_required = False
            self.autosave_project_dir = project_path.parent
            self.autosave_source_copy = (
                source_path
                if source_path is not None and source_path.is_file()
                else None
            )
            self.midi_path = "" if source_format == "project" else str(midi_path)
            project_name = str(payload.get("output_name") or project_path.parent.name)
            self.file_label.setProperty(
                "i18nSkipText",
                source_format != "project",
            )
            self.file_label.setProperty(
                "i18nSkip",
                source_format != "project",
            )
            self.file_label.setText(
                trf("{project} · 空白项目", project=project_name)
                if source_format == "project"
                else midi_path.name
            )
            self.output_name.setText(project_name if source_format == "project" else (payload.get("output_name") or midi_path.stem))
            research = payload.get("research")
            if isinstance(research, dict):
                self.research_metadata = {
                    "profile_id": str(research.get("profile_id") or BDO_PROFILE.profile_id),
                    "ab_experiments": [
                        dict(item) for item in research.get("ab_experiments", []) if isinstance(item, dict)
                    ],
                }
            conversion_settings = payload.get("conversion_settings", {})
            if source_format == "bdo":
                if not self._load_bdo_info(midi_path):
                    return
                self._apply_conversion_settings(conversion_settings)
            elif source_format == "midi":
                self._apply_conversion_settings(conversion_settings)
                if not self._load_midi_info(str(midi_path)):
                    return
            else:
                self._stop_preview()
                self.project_commands.clear()
                self._clear_track_selection()
                self._apply_conversion_settings(conversion_settings)
                self.bdo_source_snapshot = None
                self.bdo_source_document = None
                self.bpm = int(payload.get("bpm") or 120)
                self.time_sig = int(payload.get("time_sig") or 4)
                self.tempo_changes = int(payload.get("tempo_changes") or 1)
                self.tracks = []
                for index, item in enumerate(payload.get("tracks", [])):
                    if not isinstance(item, dict) or item.get("track_id") is None:
                        continue
                    track_id = int(item["track_id"])
                    instrument_id = int(item.get("bdo_instrument_id", 0x0B))
                    self.tracks.append(
                        TrackState(
                            track_id=track_id,
                            notes=[],
                            gm_program=int(item.get("gm_program", 0)),
                            is_percussion=bool(item.get("is_percussion", False)),
                            display_name=str(item.get("display_name") or trf("新建轨道 {track_id}", track_id=track_id + 1)),
                            bdo_instrument_id=instrument_id,
                            color=TRACK_COLORS[index % len(TRACK_COLORS)],
                            effect_settings_placeholder={
                                "track_effects_enabled": False,
                                "note_effects_reserved": True,
                            },
                        )
                    )
                if not self.tracks:
                    self.tracks.append(
                        TrackState(
                            0,
                            [],
                            0,
                            False,
                            tr("新建轨道 1"),
                            gm_to_bdo_instrument(0, False),
                            color=TRACK_COLORS[0],
                        )
                    )
            self.source_format = source_format
            self.owner_id = int(payload.get("owner_id") or self.owner_id or 0)
            self.char_name = payload.get("char_name") or self.char_name
            saved_lyrics = payload.get("lyric_events")
            if isinstance(saved_lyrics, list):
                self.lyric_events = [dict(event) for event in saved_lyrics if isinstance(event, dict)]
            saved_tracks = {
                int(item.get("track_id")): item
                for item in payload.get("tracks", [])
                if isinstance(item, dict) and item.get("track_id") is not None
            }
            for track in self.tracks:
                item = saved_tracks.get(track.track_id)
                if not item:
                    continue
                track.bdo_instrument_id = int(item.get("bdo_instrument_id", track.bdo_instrument_id))
                track.muted = bool(item.get("muted", track.muted))
                track.solo = bool(item.get("solo", track.solo))
                track.volume_scale = float(item.get("volume_scale", track.volume_scale))
                track.duration_scale = float(item.get("duration_scale", track.duration_scale))
                track.bdo_track_volume = int(item.get("bdo_track_volume", track.bdo_track_volume))
                raw_settings = item.get("bdo_track_settings", track.bdo_track_settings)
                if isinstance(raw_settings, (list, tuple)) and len(raw_settings) == 8:
                    track.bdo_track_settings = tuple(int(value) for value in raw_settings)
                source_group = item.get("bdo_source_group_index", track.bdo_source_group_index)
                track.bdo_source_group_index = int(source_group) if source_group is not None else None
                raw_source_notes = item.get("bdo_source_note_records", track.bdo_source_note_records)
                if isinstance(raw_source_notes, (list, tuple)):
                    track.bdo_source_note_records = tuple(
                        tuple(record) for record in raw_source_notes
                        if isinstance(record, (list, tuple)) and len(record) >= 6
                    )
                art = item.get("articulation_type")
                track.articulation_type = int(art) if art is not None else None
                mode = str(item.get("marnian_synth_mode", "basic"))
                track.marnian_synth_mode = mode if mode in {value for _label, value in MARNIAN_SYNTH_MODES} else "basic"
                track.notes_optimized = bool(item.get("notes_optimized", False))
                saved_controls = item.get("performance_controls", [])
                if isinstance(saved_controls, list):
                    track.performance_controls = [
                        dict(control) for control in saved_controls if isinstance(control, dict)
                    ]
                saved_notes = item.get("notes")
                if isinstance(saved_notes, list):
                    restored_notes = []
                    for raw_note in saved_notes:
                        if not isinstance(raw_note, list) or len(raw_note) < 5:
                            continue
                        try:
                            restored_notes.append(
                                Note(
                                    int(raw_note[0]),
                                    int(raw_note[1]),
                                    float(raw_note[2]),
                                    float(raw_note[3]),
                                    int(raw_note[4]),
                                )
                            )
                        except (TypeError, ValueError):
                            continue
                    track.notes = restored_notes
            if self.active_transcription_editor is not None:
                self.active_transcription_editor.release_transcription_resources()
            self.transcription_result = None
            self.transcription_session = TranscriptionSession.from_payload(
                payload.get("transcription_review", {}),
            )
            self.transcription_assist_review = (
                TranscriptionAssistReviewState.from_payload(
                    payload.get("transcription_assist_review", {})
                )
            )
            self._clear_transcription_review_history()
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.transcription_assist_previous_candidates = ()
            saved_reference_audio = str(payload.get("reference_audio_path") or "")
            reference_audio_was_attached = bool(
                payload.get("reference_audio_attached", bool(saved_reference_audio))
            )
            saved_reference_path = resolve_project_file_reference(
                project_path.parent,
                saved_reference_audio,
                allow_legacy_absolute=legacy_absolute_paths,
            )
            reference_audio_restored = bool(
                saved_reference_path is not None
                and saved_reference_path.is_file()
                and self.reference_audio.set_audio_path(
                    saved_reference_path,
                    notify=False,
                )
            )
            if reference_audio_restored:
                self.reference_audio_path = self.reference_audio.audio_path
            self.reference_audio_relink_required = bool(
                reference_audio_was_attached and not reference_audio_restored
            )
            self._refresh_tracks()
            self.timeline.set_tracks(self.tracks)
            self._reset_timeline_position()
            self.timeline.set_time_range(
                *(
                    self.transcription_session.state.region
                    if self.transcription_session.state.region is not None
                    else (None, None)
                )
            )
            self._refresh_transcription_workspace()
            if reference_audio_was_attached and not reference_audio_restored:
                self.status_label.setText(
                    tr("工程已恢复；参考音频未随工程保存，请重新载入。")
                )
            else:
                self.status_label.setText(tr("工程已恢复"))
            self.inspector_text.setText(trf("已恢复自动保存工程：{project}", project=project_path))
            self._sync_preview_state()
        finally:
            self.loading_project = False
        self._autosave_project("restore project", immediate=True)
        self._mark_conversion_check_dirty()
        self._record_recent("project", project_path, self.output_name.text() or project_path.parent.name)
        self._show_workspace()

    def _apply_conversion_settings(self, settings: dict) -> None:
        if not isinstance(settings, dict):
            return
        self.char_name = settings.get("char_name", self.char_name)
        self.bpm_override = settings.get("bpm_override") or None
        self.transpose = int(settings.get("transpose", self.transpose))
        self.apply_sustain = bool(settings.get("apply_sustain", self.apply_sustain))
        self.flatten_tempo = bool(settings.get("flatten_tempo", self.flatten_tempo))
        self.velocity_mode = settings.get("velocity_mode", self.velocity_mode)
        self.vel_range = tuple(settings["vel_range"]) if settings.get("vel_range") else None
        self.vel_floor = settings.get("vel_floor")
        saved_vel_step = settings.get("vel_step")
        self.vel_step = tuple(saved_vel_step) if isinstance(saved_vel_step, list) else saved_vel_step
        self.reverb = int(settings.get("reverb", self.reverb))
        self.delay = int(settings.get("delay", self.delay))
        saved_chorus = settings.get("chorus")
        self.chorus = tuple(saved_chorus) if saved_chorus else None

    def _conversion_settings_payload(self) -> dict:
        return {
            "char_name": self.char_name,
            "bpm_override": self.bpm_override,
            "transpose": self.transpose,
            "apply_sustain": self.apply_sustain,
            "flatten_tempo": self.flatten_tempo,
            "velocity_mode": self.velocity_mode,
            "vel_range": list(self.vel_range) if self.vel_range else None,
            "vel_floor": self.vel_floor,
            "vel_step": list(self.vel_step) if isinstance(self.vel_step, tuple) else self.vel_step,
            "reverb": self.reverb,
            "delay": self.delay,
            "chorus": list(self.chorus) if self.chorus else None,
        }

    def _track_state_payload(self, track: TrackState) -> dict:
        return {
            "track_id": track.track_id,
            "gm_program": track.gm_program,
            "is_percussion": track.is_percussion,
            "display_name": track.display_name,
            "bdo_instrument_id": track.bdo_instrument_id,
            "muted": track.muted,
            "solo": track.solo,
            "volume_scale": track.volume_scale,
            "duration_scale": track.duration_scale,
            "bdo_track_volume": int(track.bdo_track_volume),
            "bdo_track_settings": list(track.bdo_track_settings),
            "bdo_source_group_index": track.bdo_source_group_index,
            "bdo_source_note_records": [list(record) for record in track.bdo_source_note_records],
            "articulation_type": track.articulation_type,
            "marnian_synth_mode": track.marnian_synth_mode,
            "notes_optimized": track.notes_optimized,
            "performance_controls": [dict(control) for control in track.performance_controls],
            "notes": [
                [
                    int(note.pitch),
                    int(note.vel),
                    float(note.start),
                    float(note.dur),
                    int(getattr(note, "ntype", 0)),
                ]
                for note in track.notes
            ],
        }

    def _ensure_autosave_project(self) -> None:
        midi_path = Path(getattr(self, "midi_path", "") or "")
        if self.source_format == "project":
            if self.autosave_project_dir is None:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                project_name = safe_filename(self.output_name.text().strip(), "project")
                self.autosave_project_dir = AUTO_SAVE_DIR / f"{project_name}_{stamp}"
            self.autosave_project_dir.mkdir(parents=True, exist_ok=True)
            self.autosave_source_copy = None
            return
        if not midi_path.is_file():
            return
        if self.autosave_project_dir is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self.autosave_project_dir = AUTO_SAVE_DIR / f"{safe_filename(midi_path.stem)}_{stamp}"
        self.autosave_project_dir.mkdir(parents=True, exist_ok=True)
        fallback_suffix = ".bdo" if self.source_format == "bdo" else ".mid"
        source_name = f"source{midi_path.suffix or fallback_suffix}"
        target = self.autosave_project_dir / source_name
        if (self.autosave_source_copy != target or not target.is_file()) and midi_path.resolve() != target.resolve():
            shutil.copy2(midi_path, target)
        self.autosave_source_copy = target

    def _autosave_project(self, reason: str, immediate: bool = False) -> None:
        if immediate:
            self.pending_autosave_reason = reason
            self.autosave_timer.stop()
            self._flush_autosave()
            return
        self.pending_autosave_reason = reason
        self.autosave_timer.start(700)

    def _flush_autosave(self) -> None:
        reason = self.pending_autosave_reason or "autosave"
        self.pending_autosave_reason = ""
        if (
            self.loading_project
            or not self.tracks
            or (self.source_format != "project" and not getattr(self, "midi_path", None))
        ):
            return
        try:
            self._ensure_autosave_project()
            if self.autosave_project_dir is None:
                return
            saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
            source_reference = project_relative_file_reference(
                self.autosave_project_dir,
                self.autosave_source_copy,
            )
            payload = {
                "schema_version": CURRENT_PROJECT_SCHEMA,
                "path_policy": "project-relative-v1",
                "saved_at": saved_at,
                "reason": reason,
                "source_format": self.source_format,
                # The source copy is recoverable inside the autosave directory.
                # External MIDI/BDO and reference-audio locations are runtime
                # choices and must not leak machine-local absolute paths.
                "original_midi_path": "",
                "source_midi_path": source_reference,
                "output_name": self.output_name.text().strip(),
                "owner_id": self.owner_id,
                "char_name": self.char_name,
                "bpm": self.bpm,
                "time_sig": self.time_sig,
                "tempo_changes": self.tempo_changes,
                "lyric_events": [dict(event) for event in self.lyric_events],
                "reference_audio_path": "",
                "reference_audio_attached": bool(
                    self.reference_audio_path
                    or self.reference_audio_relink_required
                ),
                "reference_audio_volume": self.reference_audio.volume_percent,
                "reference_audio_offset_ms": self.reference_audio_offset_ms,
                "beat_origin_ms": self.beat_origin_ms,
                "transcription_review": self.transcription_session.to_payload(),
                "transcription_assist_review": (
                    self.transcription_assist_review.to_payload()
                ),
                "reference_layers": normalize_reference_layer_settings(
                    self.reference_layer_settings
                ),
                "conversion_settings": self._conversion_settings_payload(),
                "tracks": [self._track_state_payload(track) for track in self.tracks],
                "research": dict(self.research_metadata),
            }
            project_path = self.autosave_project_dir / "project.json"
            tmp_path = project_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            tmp_path.replace(project_path)
            with (self.autosave_project_dir / "autosave.log").open("a", encoding="utf-8") as file:
                file.write(f"[{saved_at}] {reason}\n")
        except Exception as exc:
            append_crash_log("Autosave failed", traceback.format_exc())
            self.status_label.setText(trf("自动保存失败：{error}", error=exc))

    def _mark_conversion_check_dirty(self) -> None:
        self.conversion_check_dirty = True
        if hasattr(self, "conversion_check_btn"):
            self.conversion_check_btn.setToolTip(
                tr("建议先做一次转换检查，确认音域、FX 和打击乐映射")
            )
            self.check_blink_ticks = 0
            self.check_blink_timer.start(360)

    def _clear_conversion_check_dirty(self) -> None:
        self.conversion_check_dirty = False
        if hasattr(self, "conversion_check_btn"):
            self.check_blink_timer.stop()
            self.conversion_check_btn.setToolTip(
                tr("检查音域、FX 和打击乐映射")
            )
            self.conversion_check_btn.setProperty("kind", "secondary")
            self.conversion_check_btn.style().unpolish(self.conversion_check_btn)
            self.conversion_check_btn.style().polish(self.conversion_check_btn)

    def _blink_conversion_check_button(self) -> None:
        if not self.conversion_check_dirty or not hasattr(self, "conversion_check_btn"):
            self.check_blink_timer.stop()
            return
        self.check_blink_ticks += 1
        self.conversion_check_btn.setProperty("kind", "convert" if self.check_blink_ticks % 2 else "secondary")
        self.conversion_check_btn.style().unpolish(self.conversion_check_btn)
        self.conversion_check_btn.style().polish(self.conversion_check_btn)
        if self.check_blink_ticks >= 12:
            self.check_blink_timer.stop()
            self.conversion_check_btn.setProperty("kind", "convert")
            self.conversion_check_btn.style().unpolish(self.conversion_check_btn)
            self.conversion_check_btn.style().polish(self.conversion_check_btn)

    def _open_conversion_check(self) -> None:
        if not self.tracks:
            QMessageBox.information(self, tr("转换检查"), tr("请先导入 MIDI。"))
            return
        self._clear_conversion_check_dirty()
        dialog = ConversionCheckDialog(self)
        dialog.exec()

    def _open_midi_tool(self, request) -> None:
        if isinstance(request, TrackState):
            self._open_midi_optimizer(int(request.track_id))
        else:
            self._open_midi_optimizer(None)

    def _open_note_editor(
        self,
        track: TrackState,
        selected_note_indices: tuple[int, ...] = (),
        *,
        transcription_mode: bool = False,
    ) -> None:
        if track not in self.tracks:
            return
        dialog = MidiNoteEditorDialog(
            self,
            track,
            self.bpm_override or self.bpm,
            self.time_sig,
            self.transpose,
            transcription_mode=transcription_mode,
        )
        if selected_note_indices:
            dialog.canvas.selected = {
                index for index in selected_note_indices if 0 <= index < len(dialog.canvas.notes)
            }
            dialog.canvas.update()
            dialog.refresh_fields()
        self.active_transcription_editor = dialog
        self._refresh_transcription_workspace()
        if (
            transcription_mode
            and self.transcription_session.state.cache_key
            and not self.transcription_session.candidates
            and self.workspace_transcription_worker is None
        ):
            QTimer.singleShot(0, self._restore_cached_transcription)
        try:
            dialog.exec()
        finally:
            if self.active_transcription_editor is dialog:
                self.active_transcription_editor = None
            dialog.release_transcription_resources()
            if transcription_mode:
                # A cancelled dialog may have launched a harmony snapshot from
                # draft notes.  Recompute from formal tracks so discarded
                # notes cannot leak into the persistent semantic view.
                self._schedule_transcription_assist_refresh()

    def _focus_validation_issue(self, issue: ValidationIssue) -> None:
        if issue.track_id is None:
            return
        track = next((item for item in self.tracks if int(item.track_id) == issue.track_id), None)
        if track is None:
            return
        self._select_track(track)
        if issue.note_indices:
            self._open_note_editor(track, issue.note_indices)

    def _open_midi_optimizer(self, target_track_id: int | None = None) -> None:
        if not self.tracks:
            QMessageBox.information(self, tr("MIDI 优化"), tr("请先导入 MIDI。"))
            return
        dialog = MidiOptimizeDialog(self, target_track_id)
        if dialog.exec() != QDialog.Accepted:
            return
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.tracks = dialog.optimized_tracks()
        optimized_effects = dialog.optimized_effects()
        if optimized_effects is not None:
            self.reverb, self.delay, self.chorus = optimized_effects
        self.selected_track = None
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("midi optimize", immediate=True)
        self._schedule_transcription_assist_refresh()
        scope = (
            trfv("轨道 {track_id}", track_id=target_track_id)
            if target_track_id is not None
            else trv("全局 MIDI")
        )
        self.status_label.setText(trf("{scope} 已优化", scope=scope))
        effect_text = "，并应用游戏声音效果建议" if optimized_effects is not None else ""
        self.show_toast(trf(
            "已应用 {scope} 优化{effects}：建议再运行一次转换检查后导出。",
            scope=scope,
            effects=trv(effect_text) if effect_text else "",
        ), kind="success", duration_ms=3600)

    def _suggest_global_transpose(self) -> int | None:
        active = selected_tracks(self.tracks)
        pitches = [
            note.pitch
            for track in active
            if not track.is_percussion and track.bdo_instrument_id != 0x0d
            for note in track.notes
        ]
        if not pitches:
            return None
        low = min(pitches)
        high = max(pitches)
        if high - low > BDO_NOTE_MAX - BDO_NOTE_MIN:
            return None
        lower_bound = BDO_NOTE_MIN - low
        upper_bound = BDO_NOTE_MAX - high
        if lower_bound <= self.transpose <= upper_bound:
            return None
        if lower_bound <= 0 <= upper_bound:
            return 0
        return lower_bound if abs(lower_bound) <= abs(upper_bound) else upper_bound

    def _analyze_conversion(self) -> dict:
        issues = self._validation_issues()
        structured_report = issues_report(
            issues,
            translate=tr,
            format_translate=trf,
        )
        raw_evidence_status = BDO_PROFILE.evidence.status
        status_source = evidence_status_source(raw_evidence_status)
        report = trf(
            "BDO Profile: {profile} · {status}\n时间差比较容差: {tolerance} ms\n\n{report}",
            profile=BDO_PROFILE.profile_id,
            status=(
                trv(status_source)
                if status_source is not None
                else raw_evidence_status
            ),
            tolerance="0.001",
            report=structured_report,
        )
        issue_count = sum(item.severity == "error" for item in issues)
        warning_count = sum(item.severity == "warning" for item in issues)
        invalid_fx = sum(item.fix_id == "clear_track_articulation" for item in issues)
        suggested_transpose = self._suggest_global_transpose()
        fixable_count = invalid_fx + (1 if suggested_transpose is not None else 0)
        return {
            "report": report,
            "issues": issues,
            "issue_count": issue_count,
            "warning_count": warning_count,
            "invalid_fx": invalid_fx,
            "suggested_transpose": suggested_transpose,
            "fixable_count": fixable_count,
        }

    def _validation_issues(self) -> tuple[ValidationIssue, ...]:
        active_ids = frozenset(int(track.track_id) for track in selected_tracks(self.tracks))
        context = ValidationContext(
            transpose=int(self.transpose),
            active_track_ids=active_ids,
            instrument_names=_ui_bdo_instrument_names(),
            gm_drum_map=_GM_TO_BDO_DRUM,
            serialize_instrument=serialized_bdo_instrument_id,
            sample_only_percussion_ids=frozenset(BDO_SAMPLE_ONLY_PERCUSSION),
            velocity_mode=str(self.velocity_mode),
            effects=(int(self.reverb), int(self.delay), self.chorus),
        )
        return validate_tracks(self.tracks, BDO_PROFILE, context)

    def _apply_conversion_check_fixes(self) -> str:
        analysis = self._analyze_conversion()
        if analysis.get("fixable_count"):
            self._push_project_snapshot()
        fixed: list[str] = []
        transpose_changed = False
        suggested_transpose = analysis.get("suggested_transpose")
        if suggested_transpose is not None:
            transpose_changed = int(suggested_transpose) != int(
                self.transpose
            )
            self.transpose = int(suggested_transpose)
            fixed.append(
                trf("全局移调设为 {transpose:+d}", transpose=self.transpose)
            )
        cleared_fx = 0
        for track in self.tracks:
            if track.articulation_type is None:
                continue
            supported = {ntype for ntype, _label in BDO_ARTICULATIONS.get(track.bdo_instrument_id, [])}
            if track.articulation_type not in supported:
                track.articulation_type = None
                cleared_fx += 1
        if cleared_fx:
            fixed.append(trf("清空 {count} 条无效 FX", count=cleared_fx))
        if fixed:
            self._on_track_changed()
            if transpose_changed and self.transcription_result is not None:
                self.automatic_instrument_match_analysis = None
                self.instrument_match_analysis = None
                self._start_transcription_assist_analysis()
            if self.selected_track:
                self._select_track(self.selected_track)
            self._autosave_project("conversion check fix", immediate=True)
            self.status_label.setText(tr("转换检查已修复"))
            return tr("已修复：") + tr("；").join(fixed)
        return tr("没有可自动修复的项目。未知打击乐、样本音域和需要拆轨的情况仍需人工处理。")

    def _show_acknowledgements(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("致谢"))
        dialog.resize(860, 640)
        dialog.setMinimumSize(700, 520)
        dialog.setObjectName("ThanksDialog")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("ThanksHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        header_layout.setSpacing(4)
        title = QLabel(tr("致谢"))
        title.setObjectName("ThanksTitle")
        header_layout.addWidget(title)
        subtitle = QLabel(tr("感谢以下项目、作者与社区。"))
        subtitle.setObjectName("ThanksSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        text_panel = QFrame()
        text_panel.setObjectName("ThanksTextPanel")
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(18, 16, 18, 16)
        text_layout.setSpacing(9)

        text_title = QLabel(tr("项目、作者与社区"))
        text_title.setObjectName("ThanksSectionLabel")
        text_layout.addWidget(text_title)

        thanks_text = QTextBrowser()
        thanks_text.setObjectName("ThanksText")
        thanks_text.setReadOnly(True)
        thanks_text.setOpenExternalLinks(True)
        thanks_body_color = "#d8d3cc" if self._system_uses_dark_theme() else "#45413d"
        thanks_heading_color = "#f0c66f" if self._system_uses_dark_theme() else "#8a5a00"
        section_sources = dict(CREDIT_SECTION_SOURCES)
        credit_sections: list[str] = []
        for section_key, _source in CREDIT_SECTION_SOURCES:
            rows = []
            for entry in CREDIT_ENTRIES:
                if entry.section != section_key:
                    continue
                rows.append(
                    "<p class=\"credit\">"
                    f"<b>{escape(entry.name)}</b><br>"
                    f"{escape(tr('许可证'))}: "
                    f"{escape(tr(entry.license_label))}<br>"
                    f"<a href=\"{escape(entry.github_url)}\">"
                    f"{escape(entry.github_url)}</a>"
                    "</p>"
                )
            credit_sections.append(
                f"<h2>{escape(tr(section_sources[section_key]))}</h2>"
                + "".join(rows)
            )

        citation_rows = []
        for citation in RESEARCH_CITATIONS:
            citation_rows.append(
                "<p class=\"credit\">"
                f"<b>{escape(citation.name)}</b><br>"
                f"{escape(citation.citation)}<br>"
                f"<a href=\"{escape(citation.github_url)}\">"
                f"{escape(citation.github_url)}</a><br>"
                f"<a href=\"{escape(citation.publication_url)}\">"
                f"{escape(tr('论文'))}: {escape(citation.publication_url)}</a>"
                "</p>"
            )

        credits_html = "".join(credit_sections)
        citations_html = "".join(citation_rows)
        third_party_url = (
            "https://github.com/CocoaMist/3007-BDO_Music_Composer/"
            "blob/master/THIRD_PARTY_NOTICES.md"
        )
        thanks_text.setHtml(
            f"""
            <style>
                body {{ color: {thanks_body_color}; font-family: "Microsoft YaHei UI"; font-size: 11px; }}
                h2 {{ color: {thanks_heading_color}; font-size: 17px; margin-top: 14px; margin-bottom: 6px; }}
                p {{ margin: 7px 0; line-height: 145%; }}
                b {{ color: {thanks_heading_color}; }}
                a {{ color: #70aee8; text-decoration: none; }}
                .credit {{ margin-bottom: 11px; }}
            </style>
            <h2>{escape(tr("Basic Pitch 代码与模型许可"))}</h2>
            <p>{escape(tr("Basic Pitch 0.4.0 的代码、随包 nmp.onnx、LICENSE 与 NOTICE 位于同一官方发行树；未发现模型目录中的单独限制性许可证。按 Apache-2.0 再分发时必须附带 LICENSE 并保留 NOTICE。"))}</p>
            <p>
              <a href="{escape(BASIC_PITCH_MODEL_URL)}">nmp.onnx · GitHub</a><br>
              <a href="{escape(BASIC_PITCH_LICENSE_URL)}">LICENSE · GitHub</a><br>
              <a href="{escape(BASIC_PITCH_NOTICE_URL)}">NOTICE · GitHub</a>
            </p>

            {credits_html}

            <h2>{escape(tr("论文引用"))}</h2>
            {citations_html}

            <h2>{escape(tr("社区、测试与音乐交流"))}</h2>
            <p>• <b>CN Server · Rainbow Club / 彩虹乐队</b></p>
            <p>• <b>{tr("开源维护者、文档作者、测试者与社区玩家")}</b></p>
            <p>{escape(tr("本程序未内置 OpenAI API 或云端模型；OpenAI 仅列为开发协作致谢。"))}</p>

            <h2>{escape(tr("完整许可清单"))}</h2>
            <p>{escape(tr("这里是便于阅读的致谢；每次构建仍会生成并随 EXE 嵌入完整的依赖、许可证、NOTICE 与二进制哈希清单。"))}</p>
            <p><a href="{third_party_url}">{third_party_url}</a></p>
            """
        )
        text_layout.addWidget(thanks_text, stretch=1)
        layout.addWidget(text_panel, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        copy_button = buttons.addButton(tr("复制致谢名单"), QDialogButtonBox.ActionRole)
        copy_button.setProperty("kind", "secondary")
        copy_button.setToolTip(tr("复制为纯文本，便于放入项目说明或发布页面"))
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(thanks_text.toPlainText().strip())
        )
        buttons.button(QDialogButtonBox.Ok).setText(tr("关闭"))
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _load_midi_info(self, path: str) -> bool:
        self._stop_preview()
        self.project_commands.clear()
        self._clear_track_selection()
        try:
            bpm, tsig, groups, tempo_changes, controls, lyric_events = parse_midi(
                path,
                apply_sustain=self.apply_sustain,
                flatten_tempo=self.flatten_tempo,
                include_controls=True,
                include_lyrics=True,
            )
        except Exception as exc:
            self.tracks = []
            self.timeline.set_tracks([])
            self._refresh_tracks()
            self.status_label.setText(tr("载入失败"))
            self.inspector_text.setText(trf("MIDI 载入失败：{error}", error=exc))
            return False

        self.bpm = bpm
        self.source_format = "midi"
        self.bdo_source_snapshot = None
        self.bdo_source_document = None
        self.time_sig = tsig
        self.tempo_changes = tempo_changes
        self.lyric_events = lyric_events
        self.tracks = []
        for index, (notes, gm_prog, is_perc) in enumerate(groups):
            name = (
                tr("鼓组 · MIDI 通道 10")
                if is_perc
                else localized_gm_program_name(gm_prog, tr)
            )
            self.tracks.append(
                TrackState(
                    track_id=index,
                    notes=notes,
                    gm_program=gm_prog,
                    is_percussion=is_perc,
                    display_name=name,
                    bdo_instrument_id=gm_to_bdo_instrument(gm_prog, is_perc),
                    color=TRACK_COLORS[index % len(TRACK_COLORS)],
                    effect_settings_placeholder={
                        "track_effects_enabled": False,
                        "note_effects_reserved": True,
                    },
                    performance_controls=controls[index] if index < len(controls) else [],
                )
            )
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
        self._reset_timeline_position()
        self._on_track_changed()
        self.status_label.setText(tr("MIDI 已载入"))
        self._show_project_summary()
        self._sync_preview_state()
        return True

    def _clear_track_selection(self) -> None:
        self.selected_track = None
        if hasattr(self, "timeline"):
            self.timeline.set_selected_track(None)

    def _refresh_tracks(self) -> None:
        self.timeline.set_tracks(self.tracks)
        self._on_track_changed()
        self._refresh_transcription_workspace()

    def _on_track_changed(self) -> None:
        self.timeline.set_conversion_transpose(self.transpose)
        self.timeline.set_musical_grid(
            self.bpm_override or self.bpm,
            self.time_sig,
            self.beat_origin_ms,
        )
        self.timeline.update()
        if hasattr(self, "timeline_meta"):
            self.timeline_meta.setText(
                trf(
                    "{count} 轨 · BPM {bpm} · {meter}/4",
                    count=len(self.tracks),
                    bpm=self.bpm_override or self.bpm,
                    meter=self.time_sig,
                )
            )
        if hasattr(self, "timeline_pan"):
            self.timeline_pan.blockSignals(True)
            self.timeline_pan.setValue(self.timeline.pan_percent())
            self.timeline_pan.setEnabled(self.timeline.zoom_factor > 1.0)
            self.timeline_pan.blockSignals(False)
        self._refresh_transcription_workspace()

    def _restart_preview_after_timeline_change(self) -> None:
        was_playing = self.realtime_preview_active and self.realtime_audio.status.state == "playing"
        current_ms = self.timeline.playhead_ms
        if self.realtime_preview_active:
            self._stop_preview(reset_playhead=False)
        self._on_track_changed()
        if was_playing:
            self._start_preview_from(current_ms)

    def _on_track_filter_changed(self) -> None:
        self._restart_preview_after_timeline_change()
        self._autosave_project("track filter")

    def _on_preview_mapping_changed(self) -> None:
        self._restart_preview_after_timeline_change()
        self._autosave_project("track mapping")

    def _on_track_instrument_changed(self, track: TrackState) -> None:
        if track.bdo_instrument_id not in BDO_ARTICULATIONS:
            track.articulation_type = None
        if track.bdo_instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
            track.marnian_synth_mode = "basic"
        self._select_track(track)
        self._refresh_transcription_workspace()
        self._on_preview_mapping_changed()

    def _show_new_track_menu(self) -> None:
        if self.source_format != "project" and not getattr(self, "midi_path", None):
            QMessageBox.information(
                self,
                tr("新建轨道"),
                tr("请先导入 MIDI 或打开一个工程。"),
            )
            return
        menu = QMenu(self)
        title = menu.addAction(tr("选择新轨道的 BDO 乐器"))
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, -1, _ui_bdo_instrument_names())
        selected = menu.exec(self.add_track_button.mapToGlobal(self.add_track_button.rect().bottomLeft()))
        if selected is None or selected.data() is None:
            return
        self._create_track(int(selected.data()))

    def _reserved_track_ids(self) -> set[int]:
        """Return every ID that still has project or route-history meaning."""

        reserved = {int(track.track_id) for track in self.tracks}
        session = getattr(self, "transcription_session", None)
        state = getattr(session, "state", None)
        if state is not None:
            reserved.update(
                int(route.track_id)
                for route in (
                    *state.pending_routes,
                    *state.applied_routes,
                )
            )
        return reserved

    def _create_track(self, instrument_id: int) -> None:
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        track_id = max(self._reserved_track_ids(), default=-1) + 1
        instrument_name = _ui_bdo_instrument_name(instrument_id)
        track = TrackState(
            track_id=track_id,
            notes=[],
            gm_program=0,
            is_percussion=instrument_id == 0x0D,
            display_name=trf(
                "新建轨道 {number} · {instrument}",
                number=track_id + 1,
                instrument=instrument_name,
            ),
            bdo_instrument_id=instrument_id,
            color=TRACK_COLORS[track_id % len(TRACK_COLORS)],
            effect_settings_placeholder={
                "track_effects_enabled": False,
                "note_effects_reserved": True,
            },
        )
        self.tracks.append(track)
        self.timeline.set_tracks(self.tracks)
        self._select_track(track)
        self._refresh_transcription_workspace()
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("create track", immediate=True)
        self.status_label.setText(trf(
            "已新建 Track {track_id} · {instrument}",
            track_id=track_id,
            instrument=trv(_ui_bdo_instrument_source(instrument_id)),
        ))
        self.show_toast(
            tr("空轨道已创建；双击轨道可进入音符编辑器添加音符。"),
            kind="success",
        )

    def _delete_selected_track(self) -> None:
        track = self.selected_track
        if track is None or track not in self.tracks:
            QMessageBox.information(
                self,
                tr("删除轨道"),
                tr("请先在时间轴中选择要删除的轨道。"),
            )
            return
        answer = QMessageBox.question(
            self,
            tr("删除轨道"),
            trf(
                "确定删除“{track}”及其中的 {count} 个音符吗？\n此操作可通过自动保存工程恢复。",
                track=track.display_name,
                count=track.note_count,
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.tracks.remove(track)
        self._clear_track_selection()
        self.timeline.set_tracks(self.tracks)
        self._refresh_transcription_workspace()
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("delete track", immediate=True)
        if track.notes:
            self._schedule_transcription_assist_refresh()
        self.status_label.setText(trf("已删除 {track}", track=track.display_name))
        self.inspector_text.clear()
        self.show_toast(tr("轨道已删除。请选择其他轨道，或新建一条空轨道。"))

    def _select_track(self, track: TrackState) -> None:
        self.selected_track = track
        self.timeline.set_selected_track(track)
        self.inspector_text.setText(trf(
            "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation}",
            track=track.display_name, count=track.note_count, pitch_range=track.pitch_range,
            instrument=trv(_ui_bdo_instrument_source(track.bdo_instrument_id)),
            articulation=articulation_display_value(
                track.bdo_instrument_id,
                track.articulation_type,
            ),
        ))
        self.timeline.update()

    def _show_project_summary(self) -> None:
        notes = [note for track in self.tracks for note in track.notes]
        end_ms = max((track.end_ms for track in self.tracks), default=0.0)
        minutes, seconds = divmod(int(end_ms / 1000), 60)
        pitch = "-"
        if notes:
            pitch = f"{note_name(min(n.pitch for n in notes))} - {note_name(max(n.pitch for n in notes))}"
        self.inspector_text.setText(trf(
            "{file} · {tracks} 轨 · {notes} 音符 · {minutes}m {seconds:02d}s · {pitch}",
            file=Path(getattr(self, "midi_path", "")).name, tracks=len(self.tracks),
            notes=len(notes), minutes=minutes, seconds=seconds, pitch=pitch,
        ))

    def _show_effects_placeholder(self, track: TrackState) -> None:
        self.selected_track = track
        dialog = TrackFxDialog(self, track)
        if dialog.exec() != QDialog.Accepted:
            return
        selected_mode = (
            dialog.selected_marnian_synth_mode()
            if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
            else "basic"
        )
        selected_settings = dialog.selected_track_settings()
        if (
            selected_mode == track.marnian_synth_mode
            and selected_settings == tuple(track.bdo_track_settings)
        ):
            return
        self._push_project_snapshot()
        track.marnian_synth_mode = selected_mode
        track.bdo_track_settings = selected_settings
        self.show_toast(
            (
                f"{track.display_name} · FX "
                f"R{selected_settings[TRACK_REVERB_SEND_INDEX]} "
                f"D{selected_settings[TRACK_DELAY_SEND_INDEX]} "
                f"C{selected_settings[TRACK_CHORUS_SEND_INDEX]}"
            ),
            kind="success",
        )
        self._on_preview_mapping_changed()

    def _clear_solo(self) -> None:
        for track in self.tracks:
            track.solo = False
        self._refresh_tracks()
        self._on_track_filter_changed()

    def _unmute_all(self) -> None:
        for track in self.tracks:
            track.muted = False
        self._refresh_tracks()
        self._on_track_filter_changed()

    def _fit_timeline(self) -> None:
        self._reset_timeline_position()
        self._on_track_changed()

    def _reset_timeline_position(self) -> None:
        if not hasattr(self, "timeline"):
            return
        self.timeline.zoom_factor = 1.0
        self.timeline.view_start_ms = 0.0
        self.timeline.set_playhead(0.0, follow=True)
        if hasattr(self, "timeline_zoom"):
            self.timeline_zoom.blockSignals(True)
            self.timeline_zoom.setValue(100)
            self.timeline_zoom.blockSignals(False)
        if hasattr(self, "timeline_pan"):
            self.timeline_pan.blockSignals(True)
            self.timeline_pan.setValue(0)
            self.timeline_pan.setEnabled(False)
            self.timeline_pan.blockSignals(False)
        self.timeline.update()

    def _sync_preview_state(self) -> None:
        tracks = selected_tracks(self.tracks)
        preview_blockers = self._realtime_preview_blockers(tracks)
        has_bdo_samples = not preview_blockers
        has_reference = bool(self.reference_audio.audio_path)
        bdo_running = self.realtime_preview_active
        reference_state = self.reference_audio.player.playbackState()
        reference_running = reference_state != QMediaPlayer.PlaybackState.StoppedState
        running = bdo_running or reference_running
        paused = running and (
            (not bdo_running or self.realtime_audio.status.state != "playing")
            and not self.reference_audio.is_playing
        )
        can_play = (has_bdo_samples and bool(self.tracks)) or has_reference
        self.play_button.setEnabled(can_play and (not running or paused))
        play_label = tr("播放" if can_play else "无法原声试听")
        self.play_button.setAccessibleName(play_label)
        self.play_button.setToolTip(play_label)
        if getattr(self, "_timeline_controls_compact", False):
            self.play_button.setText("")
            self.play_button.setFixedWidth(34)
        else:
            self.play_button.setMinimumWidth(0)
            self.play_button.setMaximumWidth(16777215)
            self.play_button.setText(play_label)
        if hasattr(self, "preview_source_badge"):
            if preview_blockers:
                self.preview_source_badge.setText(tr("无法原声还原"))
            elif not self.realtime_audio.available():
                self.preview_source_badge.setText(tr("无可用音频设备"))
            elif self.realtime_audio.status.cache_misses:
                self.preview_source_badge.setText(tr("等待预取"))
            elif self.realtime_validation_state == "verified":
                self.preview_source_badge.setText(tr("原声已验证"))
            else:
                # Wwise samples are exact; DSP remains explicitly unverified until A/B calibration.
                self.preview_source_badge.setText(tr("原声近似" if self.realtime_audio.status.unverified else "原声近似（待 A/B 验证）"))
        self.pause_button.setEnabled(running and not paused)
        self.stop_button.setEnabled(running)

    def _can_preview_with_bdo_samples(self, tracks: list[TrackState]) -> bool:
        return not self._realtime_preview_blockers(tracks)

    def _realtime_preview_blockers(self, tracks: list[TrackState]) -> list[str]:
        if not tracks:
            return [tr("没有可试听轨道")]
        if not BDO_SAMPLE_MAP_PATH.is_file():
            return [tr("缺少解包后的 BDO Wwise 映射")]
        if not self.audio_sources.get("audio_root") or not Path(self.audio_sources["audio_root"]).is_dir():
            return [
                trf(
                    "BDO 音源目录不可用：{path}",
                    path=self.audio_sources["audio_root"],
                )
            ]
        try:
            standard_ids = [
                track.bdo_instrument_id for track in tracks
                if track.bdo_instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS
            ]
            if standard_ids and not sample_map_covers(BDO_SAMPLE_MAP_PATH, standard_ids):
                return [tr("存在未绑定已命名游戏 BNK 的乐器")]
            banks = json.loads(BDO_SAMPLE_MAP_PATH.read_text(encoding="utf-8")).get("banks", {})
            for track in tracks:
                if track.bdo_instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
                    continue
                bank = bank_for_instrument(track.bdo_instrument_id, track.marnian_synth_mode)
                if not bank or not any(row.get("wav_exists") for row in banks.get(bank, [])):
                    return [
                        trf(
                            "{track} 缺少 {mode} synth WAV",
                            track=track.display_name,
                            mode=track.marnian_synth_mode,
                        )
                    ]
        except Exception as exc:
            return [trf("无法读取游戏采样映射：{error}", error=exc)]
        return []

    @staticmethod
    def _validation_state(tracks: list[TrackState], unverified: list[str]) -> str:
        """Return verified only when every selected instrument/ntype A/B cell passed."""
        if unverified or not AUDIO_VALIDATION_PATH.is_file():
            return "approximate"
        try:
            payload = json.loads(AUDIO_VALIDATION_PATH.read_text(encoding="utf-8"))
            passed = {
                (int(cell["instrument_id"]), int(cell.get("ntype", 0)))
                for cell in payload.get("cells", [])
                if cell.get("verification") == "verified"
            }
        except (OSError, ValueError, TypeError, KeyError):
            return "approximate"
        required = {
            (track.bdo_instrument_id, int(getattr(note, "ntype", 0) or track.articulation_type or 0))
            for track in tracks for note in track.notes
        }
        return "verified" if required and required.issubset(passed) else "approximate"

    def _preview_blockers(self, tracks: list[TrackState]) -> list[str]:
        if not tracks:
            return [tr("没有可试听轨道")]
        if not BDO_SAMPLE_MAP_PATH.is_file():
            return [tr("缺少解包后的 BDO Wwise 映射")]
        try:
            missing_banks = [
                track.display_name
                for track in tracks
                if not sample_map_supported_pitches(
                    BDO_SAMPLE_MAP_PATH,
                    track.bdo_instrument_id,
                    track.marnian_synth_mode,
                )
            ]
            if missing_banks:
                return [tr("存在未绑定游戏 BNK 的乐器")]
            blockers: list[str] = []
            if self.reverb or self.delay or self.chorus:
                blockers.append(
                    tr("轨道效果（混响、延迟或合唱）尚未由离线 Wwise 渲染器复现")
                )
            for track in tracks:
                if track.is_percussion and track.bdo_instrument_id != 0x0D:
                    blockers.append(
                        trf(
                            "{track} 使用独立打击乐，尚无完整 GM 逐音映射",
                            track=track.display_name,
                        )
                    )
                    continue
                if track.articulation_type not in (None, 0):
                    blockers.append(
                        trf(
                            "{track} 使用轨道奏法 type {ntype}",
                            track=track.display_name,
                            ntype=track.articulation_type,
                        )
                    )
                for note in track.notes:
                    ntype = int(getattr(note, "ntype", 0))
                    if ntype not in (0, 99):
                        blockers.append(
                            trf(
                                "{track} 含音符奏法 type {ntype}",
                                track=track.display_name,
                                ntype=ntype,
                            )
                        )
                        break
                    velocity = max(1, min(127, round(note.vel * track.volume_scale)))
                    if not sample_map_supports_note(
                        BDO_SAMPLE_MAP_PATH,
                        track.bdo_instrument_id,
                        note.pitch,
                        velocity,
                        ntype,
                        track.marnian_synth_mode,
                    ):
                        blockers.append(
                            trf(
                                "{track} 含无对应游戏音源的键位或力度",
                                track=track.display_name,
                            )
                        )
                        break
            return list(dict.fromkeys(blockers))
        except Exception as exc:
            return [trf("无法读取游戏采样映射：{error}", error=exc)]

    def _stop_bdo_audio(self) -> None:
        # Kept as a compatibility shim for callers that previously stopped the
        # temporary-file preview player.
        if self.realtime_preview_active:
            try:
                # Ordinary transport Stop must discard queued PCM, but closing
                # the sink and decode pools here makes every subsequent play a
                # cold start.  ``closeEvent`` still calls the full engine stop.
                self.realtime_audio.clear_playback()
            except AudioEngineError:
                pass

    def _play_preview(self) -> None:
        if self.realtime_preview_loading:
            self.status_label.setText(tr("正在准备游戏音源…"))
            return
        if self.realtime_preview_active:
            try:
                self.realtime_audio.play()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
            self._sync_reference_to_position(
                self.realtime_audio.get_status().position_ms,
                play=True,
                force=True,
            )
            self.status_label.setText(tr("试听播放"))
            self._sync_preview_state()
            return
        self._start_preview_from(self.timeline.playhead_ms)

    def _start_preview_from(self, start_ms: float) -> None:
        loop_range = (
            self.timeline.time_range
            if self.timeline_loop_box.isChecked()
            else None
        )
        if loop_range is not None and not (
            loop_range[0] <= start_ms < loop_range[1]
        ):
            start_ms = loop_range[0]
            self.timeline.set_playhead(start_ms)
        tracks = selected_tracks(self.tracks)
        if not tracks:
            QMessageBox.warning(
                self,
                tr("没有可试听轨道"),
                tr("当前没有可试听轨道，请取消静音或 Solo。"),
            )
            return
        if start_ms >= self.timeline._timeline_end_ms() - 1:
            start_ms = 0.0
            self.timeline.set_playhead(0.0)
        self.preview_generation += 1
        self.last_reported_underruns = 0
        blockers = self._realtime_preview_blockers(tracks)
        if blockers:
            if self.reference_audio.audio_path:
                self._start_reference_audio_from(start_ms)
                return
            QMessageBox.warning(
                self,
                tr("无法原声试听"),
                tr("当前工程缺少可用的实时游戏音源：\n- ")
                + "\n- ".join(blockers[:6]),
            )
            self._sync_preview_state()
            return
        try:
            self.realtime_audio.start()
            self.realtime_audio.load_project_async(
                tracks, BDO_SAMPLE_MAP_PATH, start_ms, self.reverb, self.delay, self.chorus
            )
        except AudioEngineError as exc:
            self._on_preview_failed(str(exc))
            self._sync_preview_state()
            return
        self.realtime_preview_active = True
        self.realtime_preview_loading = True
        self.realtime_preview_start_ms = start_ms
        self.realtime_preview_tracks = tracks
        self.timeline.set_buffer_progress(0.0, True)
        self.realtime_status_timer.start()
        self.status_label.setText(tr("正在准备游戏音源…"))
        self._sync_preview_state()

    def _start_reference_audio_from(self, start_ms: float) -> None:
        if not self.reference_audio.audio_path:
            return
        if start_ms >= self.reference_audio.project_end_ms - 1:
            start_ms = 0.0
            self.timeline.set_playhead(0.0)
        if start_ms < self.reference_audio.project_start_ms:
            # With no BDO engine there is no project clock to advance through
            # leading silence, so begin at the first audible project frame.
            start_ms = max(0.0, self.reference_audio.project_start_ms)
            self.timeline.set_playhead(start_ms)
        self.reference_audio.set_position(start_ms)
        audio_position = self.reference_audio.project_to_audio(start_ms)
        if 0.0 <= audio_position < self.reference_audio.duration_ms:
            self.reference_audio.play()
            self.reference_status_timer.start()
        self.status_label.setText(tr("参考音频播放"))
        self._sync_preview_state()

    def _sync_reference_to_position(
        self,
        position_ms: float,
        *,
        play: bool,
        force: bool = False,
    ) -> None:
        if not self.reference_audio.audio_path:
            return
        now = time.monotonic()
        audio_position = self.reference_audio.project_to_audio(position_ms)
        inside_reference = 0.0 <= audio_position < self.reference_audio.duration_ms
        drift = abs(self.reference_audio.project_position_ms - position_ms)
        if force or (
            not self.reference_audio.is_playing
            and drift >= REFERENCE_AUDIO_RESYNC_THRESHOLD_MS
            and now - self.reference_last_resync_at >= REFERENCE_AUDIO_RESYNC_COOLDOWN_S
        ):
            self.reference_audio.set_position(position_ms)
            self.reference_last_resync_at = now
        if play and inside_reference and not self.reference_audio.is_playing:
            self.reference_audio.play()
        elif (not play or not inside_reference) and self.reference_audio.is_playing:
            self.reference_audio.pause()

    def _pause_preview(self) -> None:
        if self.realtime_preview_active:
            try:
                self.realtime_audio.pause()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
        self.reference_audio.pause()
        self.reference_status_timer.stop()
        self.status_label.setText(tr("试听暂停"))
        self._sync_preview_state()

    def _stop_preview(self, reset_playhead: bool = False) -> None:
        retained_position = self.timeline.playhead_ms if hasattr(self, "timeline") else 0.0
        self.preview_generation += 1
        self._stop_bdo_audio()
        self.reference_audio.stop()
        self.reference_status_timer.stop()
        self.realtime_preview_active = False
        self.realtime_preview_loading = False
        self.realtime_preview_tracks = []
        if hasattr(self, "timeline"):
            self.timeline.set_buffer_progress(0.0, False)
            self.timeline.set_track_levels({})
        self.realtime_status_timer.stop()
        if reset_playhead and hasattr(self, "timeline"):
            self._reset_timeline_position()
        elif self.reference_audio.audio_path:
            self.reference_audio.set_position(retained_position)
        if hasattr(self, "status_label"):
            self.status_label.setText(tr("就绪"))
        if hasattr(self, "play_button"):
            self._sync_preview_state()

    def _on_preview_failed(self, message: str, generation: int | None = None) -> None:
        if generation is not None and generation != self.preview_generation:
            return
        QMessageBox.warning(self, tr("试听不可用"), message)

    def _poll_realtime_audio_status(self) -> None:
        if not self.realtime_preview_active:
            return
        try:
            if self.realtime_preview_loading:
                preload_status = self.realtime_audio.get_status()
                self.timeline.set_buffer_progress(
                    preload_status.preload_progress if preload_status.preload_total else 0.0,
                    True,
                )
                result = self.realtime_audio.finish_loading(self.realtime_preview_start_ms)
                if result is None:
                    return
                self.realtime_preview_loading = False
                self.timeline.set_buffer_progress(1.0, True)
                details = result.get("unverified", [])
                self.realtime_validation_state = self._validation_state(self.realtime_preview_tracks, details)
                self.realtime_audio.play()
                self._sync_reference_to_position(
                    self.realtime_preview_start_ms,
                    play=True,
                    force=True,
                )
                self.status_label.setText(
                    tr("BDO 实时原声试听") if not details
                    else trf("BDO 实时试听（{count} 项待验证）", count=len(details))
                )
            status = self.realtime_audio.get_status()
        except AudioEngineError as exc:
            self.realtime_status_timer.stop()
            self.realtime_preview_active = False
            self.timeline.set_buffer_progress(0.0, False)
            self.timeline.set_track_levels({})
            self.status_label.setText(tr("实时音频引擎已停止"))
            self.realtime_audio.last_error = str(exc)
            self._sync_preview_state()
            return
        loop_range = (
            self.timeline.time_range
            if self.timeline_loop_box.isChecked()
            else None
        )
        if (
            loop_range is not None
            and status.state == "playing"
            and status.position_ms >= loop_range[1]
        ):
            try:
                self.realtime_audio.seek(loop_range[0])
                self.realtime_audio.play()
                self._sync_reference_to_position(
                    loop_range[0],
                    play=True,
                    force=True,
                )
                self.timeline.set_playhead(loop_range[0], follow=True)
                return
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
        self.timeline.set_playhead(status.position_ms, follow=True)
        self.timeline.set_track_levels(getattr(status, "track_levels", {}))
        if status.state == "playing":
            self._sync_reference_to_position(status.position_ms, play=True)
        if status.underruns > self.last_reported_underruns:
            self.last_reported_underruns = status.underruns
            self.status_label.setText(trf(
                "BDO 实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms",
                count=status.underruns, p95=status.render_p95_ms,
            ))
        if status.state == "stopped" or (status.position_ms >= status.duration_ms and status.duration_ms > 0):
            self.realtime_preview_active = False
            self.timeline.set_buffer_progress(0.0, False)
            self.timeline.set_track_levels({})
            self.realtime_status_timer.stop()
            if self.reference_audio.is_playing:
                self.reference_status_timer.start()
            if self.realtime_audio.last_error:
                self.status_label.setText(trf("音频输出停止：{error}", error=self.realtime_audio.last_error))
            self._sync_preview_state()

    def _poll_reference_audio_status(self) -> None:
        if self.realtime_preview_active:
            return
        if not self.reference_audio.is_playing:
            self.reference_status_timer.stop()
            self._sync_preview_state()
            return
        position = self.reference_audio.project_position_ms
        loop_range = (
            self.timeline.time_range
            if self.timeline_loop_box.isChecked()
            else None
        )
        if loop_range is not None and position >= loop_range[1]:
            self.reference_audio.set_position(loop_range[0])
            self.reference_audio.play()
            self.timeline.set_playhead(loop_range[0], follow=True)
            return
        self.timeline.set_playhead(position, follow=True)
        if (
            self.reference_audio.duration_ms > 0
            and position >= self.reference_audio.project_end_ms - 1
        ):
            self.reference_status_timer.stop()

    def _seek_preview(self, ms: float) -> None:
        was_playing = self.realtime_preview_active and self.realtime_audio.status.state == "playing"
        self.timeline.set_playhead(ms, follow=True)
        if self.realtime_preview_active:
            try:
                self.realtime_audio.seek(ms)
                if was_playing:
                    self.realtime_audio.play()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
        self.reference_audio.set_position(ms)
        self.reference_last_resync_at = time.monotonic()
        self._sync_preview_state()

    def _prepare_sample_pack(self, pack_path: str) -> str | None:
        """Prepare a local sample pack while keeping the Qt event loop live."""

        if self.sample_pack_worker is not None:
            return None
        progress_dialog = QProgressDialog(
            tr("正在校验并准备本地音源包…"),
            tr("取消"),
            0,
            100,
            self,
        )
        progress_dialog.setWindowTitle(tr("准备本地音源包"))
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)

        worker = SamplePackPrepareWorker(
            pack_path,
            SAMPLE_PACK_CACHE_DIR,
            self,
        )
        self.sample_pack_worker = worker
        loop = QEventLoop(self)
        outcome: dict[str, str | bool] = {
            "audio_root": "",
            "error": "",
            "cancelled": False,
        }

        def mark_success(audio_root: str) -> None:
            outcome["audio_root"] = str(audio_root)

        def mark_failure(message: str) -> None:
            outcome["error"] = str(message)

        def mark_cancelled() -> None:
            outcome["cancelled"] = True

        def request_cancel() -> None:
            progress_dialog.setLabelText(tr("正在取消…"))
            worker.cancel()

        worker.progress_changed.connect(progress_dialog.setValue)
        worker.succeeded.connect(mark_success)
        worker.failed.connect(mark_failure)
        worker.cancelled.connect(mark_cancelled)
        worker.finished.connect(loop.quit)
        progress_dialog.canceled.connect(request_cancel)
        worker.start()
        progress_dialog.show()
        loop.exec()
        progress_dialog.close()
        self.sample_pack_worker = None
        worker.deleteLater()

        if self.workspace_close_pending:
            self.workspace_close_pending = False
            QTimer.singleShot(0, self.close)
            return None
        if outcome["cancelled"]:
            return None
        if outcome["error"]:
            QMessageBox.warning(
                self,
                tr("音源包不可用"),
                str(outcome["error"]),
            )
            return None
        audio_root = str(outcome["audio_root"])
        return audio_root or None

    def _open_settings(self) -> None:
        old_parse_settings = (self.apply_sustain, self.flatten_tempo)
        old_effective_bpm = float(max(1, self.bpm_override or self.bpm))
        old_transpose = int(self.transpose)
        old_master_effects = MasterEffects.from_legacy(
            self.reverb,
            self.delay,
            self.chorus,
        )
        dialog = SettingsDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        selected_output_dir = Path(
            dialog.output_dir.text().strip() or DEFAULT_OUTDIR
        ).expanduser()
        if selected_output_dir.exists() and not selected_output_dir.is_dir():
            QMessageBox.warning(
                self,
                tr("输出目录不可用"),
                tr("请选择有效的输出目录。"),
            )
            return
        try:
            selected_output_dir = selected_output_dir.resolve()
        except OSError:
            pass

        selected_instrument_art_dir = dialog.instrument_art_dir.text().strip()
        if selected_instrument_art_dir:
            art_root = Path(selected_instrument_art_dir)
            if not art_root.is_dir():
                QMessageBox.warning(
                    self,
                    tr("背景目录不可用"),
                    tr("请选择有效的本地乐器图片目录。"),
                )
                return
            selected_instrument_art_dir = str(art_root.resolve())

        selected_audio_source = dialog.audio_source.text().strip()
        try:
            sample_pack, audio_root = classify_audio_source(
                selected_audio_source
            )
        except ValueError:
            QMessageBox.warning(
                self,
                tr("音源不可用"),
                tr("请选择 .bdosamples 音源包或本地音源文件夹。"),
            )
            return
        if sample_pack:
            prepared_root = self._prepare_sample_pack(sample_pack)
            if prepared_root is None:
                return
            audio_root = prepared_root

        self.char_name = dialog.char_name.text().strip() or "MIDI"
        self.language = str(dialog.language.currentData() or "auto")
        self.owner_id = dialog.owner_id
        self.bpm_override = dialog.bpm_override.value() or None
        self.transpose = dialog.transpose.value()
        effective_bpm_changed = not math.isclose(
            old_effective_bpm,
            float(max(1, self.bpm_override or self.bpm)),
            abs_tol=1e-9,
        )
        transpose_changed = old_transpose != int(self.transpose)
        self.apply_sustain = dialog.apply_sustain.isChecked()
        self.flatten_tempo = dialog.flatten_tempo.isChecked()
        self.velocity_mode = dialog.selected_velocity_mode()

        if self.velocity_mode == "rescale":
            low = min(dialog.vel_min.value(), dialog.vel_max.value())
            high = max(dialog.vel_min.value(), dialog.vel_max.value())
            self.vel_range = (low, high)
        else:
            self.vel_range = None

        self.vel_floor = dialog.vel_floor.value() if self.velocity_mode == "floor" else None
        self.vel_step = None
        if self.velocity_mode == "stepped":
            self.vel_floor = dialog.vel_step_base.value()
            self.vel_step = (dialog.vel_step_base.value(), dialog.vel_step.value())

        selected_master_effects = dialog.selected_master_effects()
        self.reverb, self.delay, self.chorus = (
            selected_master_effects.legacy_values()
        )
        master_effects_changed = selected_master_effects != old_master_effects

        old_sample_pack = str(self.audio_sources.get("sample_pack", "") or "")
        old_audio_root = str(self.audio_sources.get("audio_root", "") or "")
        sample_source_changed = (
            old_sample_pack != sample_pack or old_audio_root != audio_root
        )
        self.audio_sources["sample_pack"] = sample_pack
        self.audio_sources["audio_root"] = audio_root
        self.audio_sources["paz_root"] = dialog.selected_paz_root.strip()
        if sample_source_changed:
            # Sample timbre descriptors are scoped to one local pack.  Never
            # reuse them after a hot source change, otherwise Top-3 results
            # would silently describe the previous pack until restart.
            self.transcription_timbre_profile_index = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.automatic_instrument_match_analysis = None
            self.instrument_match_analysis = None
        if effective_bpm_changed:
            self.automatic_harmony_analysis = None
            self.harmony_analysis = None
        if effective_bpm_changed or transpose_changed:
            # BPM changes the beat-sized phrase gap and articulation scores;
            # transpose changes BDO range/sample-pitch matching.  Neither may
            # reuse a stale Top-3 result while the replacement worker runs.
            self.automatic_instrument_match_analysis = None
            self.instrument_match_analysis = None
        self.realtime_audio.source_config = dict(self.audio_sources)
        self.config["audio_sources"] = dict(self.audio_sources)
        self.output_dir_path = str(selected_output_dir)
        self.last_output_dir = selected_output_dir
        self.config["output_dir"] = self.output_dir_path
        self.instrument_art_dir = selected_instrument_art_dir
        self.config["instrument_art_dir"] = self.instrument_art_dir
        loaded_art_count = self.timeline.set_instrument_art_dir(
            self.instrument_art_dir
        )

        self.config["language"] = self.language
        self.config["conversion_settings"] = {
            "char_name": self.char_name,
            "bpm_override": self.bpm_override,
            "transpose": self.transpose,
            "apply_sustain": self.apply_sustain,
            "flatten_tempo": self.flatten_tempo,
            "velocity_mode": self.velocity_mode,
            "vel_range": list(self.vel_range) if self.vel_range else None,
            "vel_floor": self.vel_floor,
            "vel_step": self.vel_step,
            "reverb": self.reverb,
            "delay": self.delay,
            "chorus": list(self.chorus) if self.chorus else None,
        }
        save_config(self.config)
        active_localizer = localizer()
        if active_localizer is not None:
            active_localizer.set_language(self.language)
        self._apply_responsive_density()
        self._refresh_home()
        if master_effects_changed:
            self._restart_preview_after_timeline_change()
        elif effective_bpm_changed or transpose_changed:
            self._on_track_changed()
        if (
            self.source_format == "midi"
            and getattr(self, "midi_path", None)
            and old_parse_settings != (self.apply_sustain, self.flatten_tempo)
        ):
            self._load_midi_info(self.midi_path)
        if (
            self.transcription_result is not None
            and (
                sample_source_changed
                or effective_bpm_changed
                or transpose_changed
            )
        ):
            self._start_transcription_assist_analysis()
        velocity_source = {
            "layered": "分层",
            "stepped": "阶梯",
            "rescale": "重映射",
            "floor": "抬底",
            "off": "禁用",
        }.get(self.velocity_mode)
        velocity_label = (
            trv(velocity_source)
            if velocity_source is not None
            else str(self.velocity_mode)
        )
        self.inspector_text.setText(
            trf(
                "转换设置：力度 {velocity} · 移调 {transpose:+d} · BPM {bpm} · 踏板 {sustain}",
                velocity=velocity_label,
                transpose=self.transpose,
                bpm=self.bpm_override or "MIDI",
                sustain=trv("开" if self.apply_sustain else "关"),
            )
        )
        if self.instrument_art_dir:
            self.show_toast(
                trf("已载入 {count} 张轨道背景", count=loaded_art_count),
                kind="success" if loaded_art_count else "warning",
            )
        self._autosave_project("settings")

    def _build_params(self) -> dict:
        midi_path = getattr(self, "midi_path", "")
        if self.source_format != "project" and (not midi_path or not Path(midi_path).is_file()):
            raise ValueError(tr("请选择有效的 MIDI 文件"))
        active = selected_tracks(self.tracks)
        if not active:
            raise ValueError(tr("没有可导出的轨道，请取消静音或 Solo 至少一条轨道"))
        if not self.owner_id:
            raise ValueError(
                tr("尚未读取有效 Owner ID。请在设置中选择一份游戏内保存的曲谱，否则导出文件无法在游戏内正常编辑。")
            )
        denominator = (
            4
            if self.source_format in {"bdo", "project"}
            else source_time_signature_denominator(midi_path)
        )
        if denominator != 4:
            raise ValueError(
                trf(
                    "当前 MIDI 拍号分母为 /{denominator}，但 BDO v9 曲谱只保存 /4 拍号。请先在 MIDI 软件中转换为等价的 /4 拍号后再导出，程序不会静默写入错误拍号。",
                    denominator=denominator,
                )
            )

        out_dir = Path(self.output_dir_path or DEFAULT_OUTDIR)
        out_name = self.output_name.text().strip() or (Path(midi_path).stem if midi_path else tr("未命名项目"))
        if any(ch in out_name for ch in '<>:"/\\|?*'):
            raise ValueError(tr("曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*"))
        out_path = out_dir / out_name

        # The editor model is the single source of truth.  Re-reading the
        # imported MIDI here would silently discard manual note edits and new
        # tracks.  Marnian source modes occupy the three IDs following each
        # base waveform ID (basic + 0, stereo + 1, super + 2, superoct + 3).
        filtered_tracks = None
        export_tracks = active
        instrument_map = {
            idx: serialized_bdo_instrument_id(track)
            for idx, track in enumerate(export_tracks)
        }
        vel_scales = {
            idx: track.volume_scale
            for idx, track in enumerate(export_tracks)
            if not math.isclose(track.volume_scale, 1.0)
        }
        articulation_map = {
            idx: track.articulation_type
            for idx, track in enumerate(export_tracks)
            if track.articulation_type is not None
        }
        track_volumes = {
            idx: int(track.bdo_track_volume)
            for idx, track in enumerate(export_tracks)
        }
        track_settings_map = {}
        for idx, track in enumerate(export_tracks):
            try:
                settings = list(raw_track_settings(track.bdo_track_settings))
            except ValueError:
                settings = [0] * 8
            settings[MASTER_REVERB_TIME_INDEX] = int(self.reverb)
            settings[MASTER_DELAY_FEEDBACK_INDEX] = int(self.delay)
            chorus = self.chorus or (0, 0, 0)
            settings[MASTER_CHORUS_FEEDBACK_INDEX] = int(chorus[0])
            settings[MASTER_CHORUS_LFO_DEPTH_INDEX] = int(chorus[1])
            settings[MASTER_CHORUS_LFO_FREQUENCY_INDEX] = int(chorus[2])
            track_settings_map[idx] = tuple(settings)
        velocity_b_maps = {
            idx: tuple(track.bdo_source_note_records)
            for idx, track in enumerate(export_tracks)
            if track.bdo_source_note_records
        }
        return {
            "midi_path": midi_path,
            "filtered_tracks": filtered_tracks,
            "lyric_events": [dict(event) for event in self.lyric_events],
            "direct_tracks": active,
            "bpm_for_temp": self.bpm,
            "time_sig_for_temp": self.time_sig,
            "out_path": str(out_path),
            "char_name": self.char_name,
            "owner_id": self.owner_id,
            "instrument_map": instrument_map,
            "bpm_override": self.bpm_override,
            "vel_range": self.vel_range if self.velocity_mode == "rescale" else None,
            "vel_floor": self.vel_floor if self.velocity_mode in {"floor", "stepped"} else None,
            "vel_step": self.vel_step if self.velocity_mode == "stepped" else None,
            "vel_layered": self.velocity_mode == "layered",
            "transpose": self.transpose,
            "apply_sustain": self.apply_sustain,
            "flatten_tempo": self.flatten_tempo,
            "reverb": self.reverb,
            "delay": self.delay,
            "chorus": self.chorus,
            "vel_scales": vel_scales if vel_scales else None,
            "articulation_map": articulation_map if articulation_map else None,
            "track_volumes": track_volumes,
            "track_settings_map": track_settings_map,
            "velocity_b_maps": velocity_b_maps or None,
            "bdo_source_document": self.bdo_source_document if self.source_format == "bdo" else None,
            "game_dir": str(default_game_music_dir()),
        }

    def _convert(self) -> None:
        analysis = self._analyze_conversion()
        if analysis["issue_count"]:
            QMessageBox.warning(
                self,
                tr("导出已阻止"),
                trf(
                    "转换检查仍有 {count} 项必须处理的问题。请先打开转换检查定位并修复。",
                    count=analysis["issue_count"],
                ),
            )
            self._mark_conversion_check_dirty()
            return
        confirmable = [
            item for item in analysis["issues"]
            if item.severity == "warning" or item.code.startswith(("export.", "drum.remap", "tracks.merge"))
        ]
        if confirmable:
            answer = QMessageBox.question(
                self,
                tr("确认导出变化"),
                trf(
                    "检查发现 {count} 项需要确认的近似结果或预期变化。\n这些项目已在转换检查中列出。确认继续导出吗？",
                    count=len(confirmable),
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            params = self._build_params()
        except Exception as exc:
            QMessageBox.warning(self, tr("参数错误"), str(exc))
            return
        self._stop_preview()
        self.convert_button.setEnabled(False)
        self.status_label.setText(tr("正在转换..."))
        self.worker = ConvertWorker(params)
        self.worker.conversion_finished.connect(self._on_convert_finished)
        self.worker.failed.connect(self._on_convert_failed)
        self.worker.start()

    def _on_convert_finished(self, out_path: str, byte_count: int, summary: object, installed: str) -> None:
        self.convert_button.setEnabled(True)
        self.last_output_dir = Path(out_path).parent
        self.last_export_path = Path(out_path)
        self.status_label.setText(tr("转换完成"))
        summary = dict(summary)
        extra_parts: list[object] = []
        if installed:
            extra_parts.append(trv(" · 已复制到游戏目录"))
        roundtrip_failed = False
        roundtrip_error: object | None = None
        try:
            snapshot = read_bdo_score(Path(out_path))
            if snapshot.total_notes != int(summary["total_notes"]):
                roundtrip_error = trfv(
                    "回读音符数 {actual} 与导出摘要 {expected} 不一致",
                    actual=snapshot.total_notes,
                    expected=summary["total_notes"],
                )
        except Exception as exc:
            roundtrip_error = exc
            append_crash_log("Export round-trip verification failed", traceback.format_exc())
        if roundtrip_error is None:
            extra_parts.append(trv(" · BDO v9 结构回读通过"))
        else:
            roundtrip_failed = True
            extra_parts.append(trfv(
                " · 回读检查失败：{error}",
                error=roundtrip_error,
            ))
            self.status_label.setText(tr("转换完成（回读检查失败）"))
        result_text = trf(
            "已保存 {file} · {bytes} bytes · {instruments} 乐器 · {tracks} 轨 · {notes} 音符{extra}",
            file=Path(out_path).name, bytes=byte_count, instruments=summary["instruments"],
            tracks=summary["tracks"], notes=summary["total_notes"],
            extra=tr_joinv(extra_parts, separator=""),
        )
        self.inspector_text.setText(result_text)
        self.show_toast(
            result_text,
            kind="warning" if roundtrip_failed else "success",
            duration_ms=5200,
        )
        self._autosave_project("convert finished", immediate=True)
        self.worker = None

    def _on_convert_failed(self, message: str) -> None:
        self.convert_button.setEnabled(True)
        self.status_label.setText(tr("转换失败"))
        safe_message = _redact_log_paths(message)
        append_crash_log("Convert failed", safe_message)
        log_path = DEFAULT_OUTDIR / "last_convert_error.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(safe_message, encoding="utf-8")
        except Exception:
            log_path = None
        brief = (
            safe_message.splitlines()[0]
            if safe_message
            else tr("未知错误")
        )
        detail = (
            trf("\n\n详细错误已写入：{path}", path=log_path)
            if log_path
            else ""
        )
        QMessageBox.critical(self, tr("转换失败"), f"{brief}{detail}")
        self.worker = None

    def _open_output_dir(self) -> None:
        directory = Path(self.output_dir_path or self.last_output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def closeEvent(self, event) -> None:
        self.autosave_timer.stop()
        self.transcription_assist_refresh_timer.stop()
        self._flush_autosave()
        running_workers = [
            worker
            for worker in (
                self.workspace_transcription_worker,
                self.transcription_assist_worker,
                self.sample_pack_worker,
            )
            if worker is not None and worker.isRunning()
        ]
        if running_workers:
            self.transcription_assist_restart_pending = False
            self.transcription_assist_restart_harmony_only = False
            self.transcription_assist_restart_allow_review_recovery = True
            for worker in running_workers:
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
            self.workspace_close_pending = True
            event.ignore()
            return
        if self.active_transcription_editor is not None:
            self.active_transcription_editor.release_transcription_resources()
        self.reference_audio.set_audio_path(None, notify=False)
        self._stop_preview()
        self.realtime_audio.stop()
        super().closeEvent(event)


def main() -> int:
    install_crash_logging()
    prune_transcription_workspaces()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "OpenAI.BDOMusicComposer.1"
            )
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    install_localizer(app, str(load_config().get("language", "auto")))
    startup = StartupSplash()
    startup.show()
    app.processEvents()
    startup.set_status(tr("正在检查扩展组件…"))
    app.processEvents()
    plugin_discovery = discover_host_algorithms()
    if plugin_discovery.diagnostics:
        append_crash_log(
            "Optimizer bundle discovery",
            "\n".join(plugin_discovery.diagnostics),
        )
    icon_path = ASSETS_DIR / "icons" / "app_icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    try:
        startup.set_status(tr("正在载入界面与本地项目…"))
        app.processEvents()
        window = MidiToBdoWindow()
        window.show()
        startup.set_status(tr("准备完成"))
        startup.finish(window)
        QTimer.singleShot(
            StartupSplash.MINIMUM_VISIBLE_MS + StartupSplash.FADE_OUT_MS + 180,
            lambda: window.show_toast(
                tr("双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。")
            ),
        )
        result = app.exec()
        append_crash_log("Application exited", f"exit_code={result}")
        return result
    except BaseException as exc:
        startup.hide()
        append_crash_log("Fatal error in main()", f"{exc}\n\n{traceback.format_exc()}")
        QMessageBox.critical(
            None,
            tr("程序错误"),
            trf(
                "程序发生错误，日志已写入：\n{path}\n\n{error}",
                path=CRASH_LOG_PATH,
                error=exc,
            ),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
