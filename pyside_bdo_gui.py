#!/usr/bin/env python3
"""GarageBand-style PySide6 MIDI workspace for BDO music conversion."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from bisect import bisect_left, bisect_right
from functools import lru_cache
import faulthandler
import json
import math
import os
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
from project_paths import ASSETS_DIR, PROFILES_DIR, SAMPLE_PACK_CACHE_DIR, WWISE_MIDI_MAP_PATH
DEFAULT_OUTDIR = ROOT / "out" / "bdo"
DEFAULT_MIDI_DIR = ROOT / "samples"
CONFIG_PATH = ROOT / ".pyside_bdo_gui.json"
AUTO_SAVE_DIR = ROOT / "auto_save"
BDO_SAMPLE_MAP_PATH = WWISE_MIDI_MAP_PATH
AUDIO_VALIDATION_PATH = DEFAULT_OUTDIR / "bdo_audio_validation_matrix.json"
CRASH_LOG_PATH = DEFAULT_OUTDIR / "crash.log"
REFERENCE_AUDIO_RESYNC_THRESHOLD_MS = 1250.0
REFERENCE_AUDIO_RESYNC_COOLDOWN_S = 5.0
TIMELINE_BACKGROUND_IMAGE = ASSETS_DIR / "ui" / "timeline_background.png"
STARTUP_ART_IMAGE = ASSETS_DIR / "ui" / "loading_conductor_lineart.png"
TIMELINE_BACKGROUND_OPACITY = 0.24
DEFAULT_AUDIO_SOURCES = {
    "paz_root": os.environ.get("BDO_PAZ_ROOT", ""),
    "audio_root": os.environ.get("BDO_AUDIO_ROOT", ""),
    "sample_pack": "",
}


def append_crash_log(title: str, detail: str) -> None:
    try:
        CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CRASH_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}\n")
            file.write(detail.rstrip())
            file.write("\n")
    except Exception:
        pass


def install_crash_logging() -> None:
    try:
        CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fault_file = CRASH_LOG_PATH.open("a", encoding="utf-8")
        faulthandler.enable(file=fault_file, all_threads=True)
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


try:
    import mido
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
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
        QPushButton,
        QRadioButton,
        QScrollArea,
        QScrollBar,
        QSizePolicy,
        QSlider,
        QSpinBox,
        QStackedWidget,
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
    gm_program_name,
    gm_to_bdo_instrument,
    parse_midi,
)
from bdo_export import (  # noqa: E402
    MAX_NOTES_PER_INSTRUMENT,
    channel_groups_to_bdo,
    midi_to_bdo,
)
from optimization import OptimizerConfig  # noqa: E402
from optimization.plugin_api import InvalidOptimizationPreview, OptimizationIntensity  # noqa: E402
from optimization.plugin_host import (  # noqa: E402
    analyse_with_algorithm,
    discover_host_algorithms,
    optimizer_plugin_dir,
)
from bdo_profile import load_bdo_profile  # noqa: E402
from bdo_audio_research import sample_coverage_for_tracks  # noqa: E402
from bdo_score import compare_scores, encode_score, read_bdo_score, read_score  # noqa: E402
from bdo_codec import document_matches_logical_tracks, score_summary  # noqa: E402
from bdo_validation import ValidationContext, ValidationIssue, issues_report, validate_tracks  # noqa: E402
from project_schema import CURRENT_PROJECT_SCHEMA, migrate_project  # noqa: E402
from editor_commands import ProjectCommandStack, ProjectSnapshot  # noqa: E402
from bdo_sample_renderer import (  # noqa: E402
    sample_map_covers,
    sample_map_supported_pitches,
    sample_map_supports_note,
)
from bdo_realtime_audio import AudioEngineError, BdoRealtimeAudioEngine, bank_for_instrument  # noqa: E402
from bdo_transcription import (  # noqa: E402
    TranscriptionCancelled,
    TranscriptionCandidate,
    TranscriptionError,
    TranscriptionResult,
    transcribe_reference_audio,
)
from bdo_sample_pack import PACK_SUFFIX, SamplePackError, extract_sample_pack  # noqa: E402
from velocity_curve import apply_weighted_velocity_delta, velocity_time_points  # noqa: E402
from i18n import LANGUAGE_CHOICES, install_localizer, localizer, tr, trf  # noqa: E402
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


TRACK_COLORS = [
    "#d88c6f", "#8dbf67", "#6f9fd8", "#d8b66f", "#b887d8", "#70b8a8",
    "#d87592", "#91a7d8", "#c6d86f", "#d89f6f", "#8ed8ce", "#b9a0d8",
]

BDO_ARTICULATIONS = {
    0x0a: [
        (0, "延音"),
        (3, "向上滑动"),
        (12, "滑弦下降"),
        (13, "弱音"),
        (14, "泛音"),
        (15, "三连音"),
    ],
    0x0e: [
        (0, "延音"),
        (3, "向上滑动"),
        (12, "滑弦下降"),
        (13, "弱音"),
        (14, "泛音"),
        (16, "滑音"),
        (22, "拍弦"),
        (23, "滑音上升"),
        (24, "X-音符"),
    ],
    0x0f: [
        (0, "延音"),
        (3, "向上滑动"),
        (12, "滑弦下降"),
        (13, "弱音"),
        (14, "泛音"),
        (23, "滑音上升"),
    ],
    0x0b: [
        (0, "延音"),
        (1, "标签"),
        (2, "剪切"),
        (3, "向上滑动"),
        (4, "颤音小调"),
        (15, "三连音"),
    ],
    0x10: [
        (0, "延音"),
        (9, "大调和弦"),
        (10, "和弦小调"),
        (16, "滑音"),
    ],
    0x11: [
        (0, "延音"),
        (11, "延音踏板"),
    ],
    0x12: [
        (0, "延音"),
        (1, "标签"),
        (2, "剪切"),
        (3, "向上滑动"),
        (4, "颤音小调"),
        (5, "颤音大调"),
        (6, "颤音"),
        (7, "颤音 2"),
        (8, "大调颤音"),
    ],
    0x14: [
        (0, "延音"),
        (1, "标签"),
        (2, "剪切"),
        (3, "向上滑动"),
        (4, "颤音小调"),
        (5, "颤音大调"),
        (6, "颤音"),
        (7, "颤音 2"),
        (8, "颤音小调 2"),
        (17, "颤音 3"),
        (18, "大调颤音"),
        (19, "颤音 4"),
        (20, "维持滤波器"),
        (21, "滤波铜管"),
    ],
    0x18: [
        (0, "延音"),
        (1, "标签"),
        (2, "剪切"),
        (3, "向上滑动"),
        (4, "颤音小调"),
        (5, "颤音大调"),
        (6, "颤音"),
        (7, "颤音 2"),
        (8, "颤音小调 2"),
        (17, "颤音 3"),
        (18, "大调颤音"),
        (19, "颤音 4"),
    ],
    0x1c: [
        (0, "延音"),
        (1, "基本"),
    ],
    0x20: [
        (0, "延音"),
        (1, "基本"),
    ],
    0x27: [
        (0, "延音"),
        (4, "颤音小调"),
        (7, "颤音小调 2"),
        (8, "大调颤音"),
        (15, "三连音"),
        (26, "SusPiano"),
        (27, "SusMezzoForte"),
        (28, "SusForte"),
    ],
    0x28: [
        (0, "延音"),
        (3, "向上滑动"),
        (4, "颤音小调"),
        (12, "滑弦下降"),
        (26, "SusPiano"),
        (27, "SusMezzoForte"),
        (28, "SusForte"),
    ],
    0x24: [
        (0, "延音"),
        (6, "颤音"),
        (13, "弱音"),
        (14, "泛音"),
        (25, "FX(C2~G2)"),
    ],
    0x25: [
        (0, "延音"),
        (6, "颤音"),
        (13, "弱音"),
        (14, "泛音"),
        (25, "FX(C2~G2)"),
    ],
    0x26: [
        (0, "延音"),
        (6, "颤音"),
        (13, "弱音"),
        (14, "泛音"),
        (25, "FX(C2~G2)"),
    ],
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
    26: "弱力度持续音。适合竖笛/圆号长音，建议 velocity < 70。",
    27: "中力度持续音。适合竖笛/圆号长音，建议 velocity 70-99。",
    28: "强力度持续音。适合竖笛/圆号长音，建议 velocity >= 100。",
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
    if ntype is None:
        return "默认"
    for candidate, label in BDO_ARTICULATIONS.get(inst_id, []):
        if candidate == ntype:
            return f"{label} (type {ntype})"
    return f"type {ntype}"


def articulation_usage_hint(ntype: int | None) -> str:
    if ntype is None:
        return "未指定奏法，导出时保留普通音符。"
    return BDO_ARTICULATION_USAGE_HINTS.get(ntype, "该奏法的游戏内音色仍需人工验证。")


def add_instrument_submenus(menu: QMenu, current_id: int, instrument_names: dict[int, str]) -> None:
    used_ids: set[int] = set()
    for type_name, inst_ids in BDO_INSTRUMENT_MENU_GROUPS:
        type_menu = menu.addMenu(type_name)
        for inst_id in inst_ids:
            name = instrument_names.get(inst_id)
            if not name:
                continue
            used_ids.add(inst_id)
            # Menu hierarchy already identifies the family.  Show the concise
            # instrument name instead of repeating "新手专用：" etc.
            action = type_menu.addAction(name.rsplit("：", 1)[-1])
            action.setCheckable(True)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)

    other_ids = [inst_id for inst_id in instrument_names if inst_id not in used_ids]
    if other_ids:
        other_menu = menu.addMenu("其他")
        for inst_id in other_ids:
            action = other_menu.addAction(instrument_names[inst_id])
            action.setCheckable(True)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)


def gm_to_bdo_instrument_for_ui(program: int, is_percussion: bool) -> int:
    """Apply editor-specific GM mapping overrides before the shared fallback."""
    if is_percussion:
        return 0x0d
    if program in (24, 25):
        return 0x0a  # acoustic guitars
    if program in (26, 27, 28):
        return 0x24  # clean/jazz/muted electric guitar
    if program == 29:
        return 0x25  # overdriven electric guitar
    if program in (30, 31):
        return 0x26  # distorted electric guitar / harmonics
    if program == 32:
        return 0x0f  # acoustic bass
    if 33 <= program <= 39:
        return 0x0e  # electric/fretless/slap/synth bass
    if program in (46,):
        return 0x10  # orchestral harp
    if program == 47:
        return 0x0d  # timpani/percussion family
    if 80 <= program <= 87:
        return 0x0b  # synth lead family, conservative melodic fallback
    if 88 <= program <= 95:
        return 0x12  # synth pad family, sustained ensemble fallback
    if 96 <= program <= 103:
        return 0x11  # synth FX family, avoid crystal-like Marnian guesses
    return gm_to_bdo_instrument(program, is_percussion)


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
                display_name=BDO_INSTRUMENT_NAMES.get(serialized_id, f"BDO 乐器 0x{serialized_id:02X}"),
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


@lru_cache(maxsize=64)
def game_supported_pitches(instrument_id: int) -> frozenset[int] | None:
    """Exact game-sample keys when decoded, otherwise a verified editor range."""
    editor_range = BDO_EDITOR_PITCH_RANGES.get(instrument_id)
    if BDO_SAMPLE_MAP_PATH.is_file():
        try:
            pitches = sample_map_supported_pitches(BDO_SAMPLE_MAP_PATH, instrument_id)
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


def game_pitch_range_label(instrument_id: int) -> str:
    pitches = game_supported_pitches(instrument_id)
    if not pitches:
        return "游戏音域待验证"
    low, high = min(pitches), max(pitches)
    gap_count = high - low + 1 - len(pitches)
    suffix = f"（{gap_count} 个离散音）" if gap_count else ""
    return f"游戏 {note_name(low)}-{note_name(high)}{suffix}"


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
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def audio_source_config(config: dict) -> dict[str, str]:
    """Return persistent local source roots without copying game assets."""
    saved = config.get("audio_sources", {})
    return {key: str(saved.get(key) or value) for key, value in DEFAULT_AUDIO_SOURCES.items()}


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
        title = QLabel("正在打开曲谱工作台")
        title.setObjectName("StartupTitle")
        brand.addWidget(title)
        layout.addLayout(brand)

        activity = QHBoxLayout()
        activity.setSpacing(12)
        self.spinner = LoadingSpinner(34)
        activity.addWidget(self.spinner, alignment=Qt.AlignVCenter)
        status_group = QVBoxLayout()
        status_group.setSpacing(3)
        self.status_label = QLabel("正在启动音乐工作台…")
        self.status_label.setObjectName("StartupStatus")
        detail = QLabel("本地项目和游戏曲谱只在这台电脑上读取")
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
    toast.show_message(tr(text), kind=kind, duration_ms=duration_ms)
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

    def __init__(self) -> None:
        super().__init__()
        self.tracks: list[TrackState] = []
        self.hit_regions: list[tuple[QRectF, str, object]] = []
        self.reference_audio: ReferenceAudioController | None = None
        self.zoom_factor = 1.0
        self.view_start_ms = 0.0
        self.playhead_ms = 0.0
        self.buffer_progress = 0.0
        self.buffer_visible = False
        self.track_levels: dict[int, float] = {}
        self.grid_rect = QRectF()
        self.dragging_timeline = False
        self.last_drag_x = 0.0
        self.selected_track: TrackState | None = None
        self.conversion_transpose = 0
        self.background_pixmap = QPixmap(str(TIMELINE_BACKGROUND_IMAGE)) if TIMELINE_BACKGROUND_IMAGE.is_file() else QPixmap()
        self._scaled_background = QPixmap()
        self._scaled_background_size = QSize()
        self.track_scroll = QScrollBar(Qt.Vertical, self)
        self._track_note_indexes: dict[int, tuple[list[float], list, float, int, int]] = {}
        self._conversion_problem_cache: dict[tuple[int, int, int], bool] = {}
        self._timeline_end_cache = 1.0
        self.track_scroll.setObjectName("TimelineScroll")
        self.track_scroll.valueChanged.connect(self.update)
        self.setMinimumHeight(380)

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
            max_duration = max((float(note.dur) * track.duration_scale for note in ordered), default=0.0)
            pitch_min = min((note.pitch for note in ordered), default=0)
            pitch_max = max((note.pitch for note in ordered), default=0)
            self._track_note_indexes[id(track)] = (starts, ordered, max_duration, pitch_min, pitch_max)
            timeline_end = max(
                timeline_end,
                max((note.start + note.dur * track.duration_scale for note in ordered), default=0.0),
            )
        if self.reference_audio is not None:
            timeline_end = max(timeline_end, self.reference_audio.duration_ms)
        self._timeline_end_cache = timeline_end

    def _visible_track_notes(self, track: TrackState, start: float, end: float) -> list:
        ordered, lo, hi = self._visible_track_note_window(track, start, end)
        return ordered[lo:hi]

    def _visible_track_note_window(
        self, track: TrackState, start: float, end: float,
    ) -> tuple[list, int, int]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track), ([], [], 0.0, 0, 0))
        starts, ordered, max_duration, _pitch_min, _pitch_max = index
        lo = bisect_left(starts, start - max_duration)
        hi = bisect_right(starts, end)
        return ordered, lo, hi

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

    def _note_has_conversion_problem(self, track: TrackState, pitch: int) -> bool:
        cache_key = (int(track.bdo_instrument_id), int(pitch), self.conversion_transpose)
        cached = self._conversion_problem_cache.get(cache_key)
        if cached is not None:
            return cached
        if track.bdo_instrument_id == 0x0d:
            mapped_pitch = _GM_TO_BDO_DRUM.get(pitch)
            if mapped_pitch is None or mapped_pitch < BDO_DRUM_MIN or mapped_pitch > BDO_DRUM_MAX:
                result = True
            else:
                supported = game_supported_pitches(track.bdo_instrument_id)
                result = supported is not None and mapped_pitch not in supported
        else:
            converted_pitch = pitch + self.conversion_transpose
            supported = game_supported_pitches(track.bdo_instrument_id)
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
        self.playhead_ms = max(0.0, min(float(ms), self._timeline_end_ms()))
        if follow:
            visible_duration = self._visible_duration_ms()
            if self.playhead_ms < self.view_start_ms or self.playhead_ms > self.view_start_ms + visible_duration * 0.92:
                self.view_start_ms = self.playhead_ms - visible_duration * 0.18
                self._clamp_view()
        if self.view_start_ms != old_view_start:
            self.update()
            return
        new_rect = self._playhead_update_rect(self.playhead_ms)
        if old_rect is not None:
            self.update(old_rect)
        if new_rect is not None:
            self.update(new_rect)

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
        painter.fillRect(target, QColor(12, 14, 13, 116))

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
        total_seconds = visible_duration / 1000.0
        beat_seconds = 60.0 / max(1, 120)
        bar_seconds = beat_seconds * 4
        bars = max(4, min(24, math.ceil(total_seconds / bar_seconds) if total_seconds else 4))
        for i in range(bars + 1):
            x = grid_left + grid_w * i / bars
            if i < bars:
                shade = QColor(25, 25, 25, 80) if i % 2 else QColor(17, 17, 17, 64)
                painter.fillRect(QRectF(x, grid_top, grid_w / bars, grid_h), shade)
            is_major = i % 4 == 0
            painter.setPen(QPen(QColor("#3a3a3a" if is_major else "#292929"), 1))
            painter.drawLine(int(x), grid_top, int(x), grid_top + grid_h)
            if i < bars:
                painter.setPen(QColor("#8e8982" if is_major else "#5f5a54"))
                seconds = int((visible_start / 1000.0) + total_seconds * i / bars)
                label = str(i + 1) if bars <= 12 else f"{seconds // 60}:{seconds % 60:02d}"
                painter.drawText(int(x + 6), top + 22, label)
        painter.setPen(QColor("#a8a29e"))
        painter.drawText(left + 10, top + 22, "Tracks")
        return bars

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

            controls = [("M", "mute", 26), ("S", "solo", 26)]
            if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
                controls.append(("FX", "fx", 28))
            control_gap = 4.0
            controls_width = sum(width for _label, _action, width in controls)
            controls_width += control_gap * max(0, len(controls) - 1)
            control_x = left + header_w - 20.0 - controls_width
            control_y = y + (lane_h - 22.0) / 2.0
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
            inst_name = BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, "未知 BDO 乐器")
            cached_low, cached_high = self._track_pitch_bounds(track)
            cached_range = f"{note_name(cached_low)} - {note_name(cached_high)}" if track.notes else "-"
            metadata = f"{inst_name} · {track.note_count} 音符 · {cached_range}"
            metadata_font = painter.font()
            metadata_font.setPointSize(max(7, metadata_font.pointSize() - 1))
            painter.save()
            painter.setFont(metadata_font)
            painter.drawText(
                QRectF(left + 12, y + 31, header_w - 130, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(metadata, Qt.ElideRight, header_w - 136),
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
            first = max(0, bisect_left(controller.waveform_starts, visible_start) - 1)
            last = bisect_right(controller.waveform_starts, visible_end)
            center_y = waveform_rect.center().y()
            max_half_height = max(1.0, waveform_rect.height() / 2.0 - 3.0)
            bars: list[QRectF] = []
            for bucket_start, bucket_end, peak in controller.waveform[first:last]:
                x = waveform_rect.left() + (
                    (bucket_start - visible_start) / visible_duration
                ) * waveform_rect.width()
                width = max(
                    1.0,
                    ((bucket_end - bucket_start) / visible_duration) * waveform_rect.width(),
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

        position = float(controller.player.position())
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
        painter.drawText(left + 10, top + 22, f"TRACKS · {self._timeline_row_count()}")
        total_seconds = visible_duration / 1000.0
        for i in range(bars + 1):
            x = grid_left + grid_w * i / bars
            painter.setPen(QPen(QColor("#3a3a3a" if i % 4 == 0 else "#292929"), 1))
            painter.drawLine(int(x), top + 8, int(x), grid_top)
            if i < bars:
                painter.setPen(QColor("#8e8982" if i % 4 == 0 else "#5f5a54"))
                seconds = int((visible_start / 1000.0) + total_seconds * i / bars)
                label = str(i + 1) if bars <= 12 else f"{seconds // 60}:{seconds % 60:02d}"
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
            painter.drawText(area, Qt.AlignCenter, "导入 MIDI 后显示轨道与音符时间轴")
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
                if action == "mute":
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
        edit_notes_action = menu.addAction("编辑音符…")
        menu.addSeparator()
        optimize_action = menu.addAction("优化此轨道")
        menu.addSeparator()
        current_id = track.bdo_instrument_id
        title = menu.addAction("更换乐器")
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, current_id, BDO_INSTRUMENT_NAMES)
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

        title = QLabel(f"{track.display_name}\n{track.note_count} 音符 · {track.pitch_range}")
        title.setObjectName("TrackTitle")
        top.addWidget(title, stretch=1)

        self.mute_btn = PillButton("M")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedWidth(30)
        self.mute_btn.clicked.connect(self._update_mute)
        top.addWidget(self.mute_btn, alignment=Qt.AlignVCenter)

        self.solo_btn = PillButton("S")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedWidth(30)
        self.solo_btn.clicked.connect(self._update_solo)
        top.addWidget(self.solo_btn, alignment=Qt.AlignVCenter)

        if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
            fx = PillButton("FX")
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
        optimize_action = menu.addAction("优化此轨道")
        menu.addSeparator()
        current_id = self.track.bdo_instrument_id
        title = menu.addAction("更换乐器")
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, current_id, self.instrument_names)
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
        name = self.instrument_names.get(self.track.bdo_instrument_id, "未知 BDO 乐器")
        return f"{name} · {game_pitch_range_label(self.track.bdo_instrument_id)}"

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

    KEY_W = 86
    BLACK_KEY_X = 8
    BLACK_KEY_W = 48
    RULER_H = 31
    ROW_H = 20
    MIN_PITCH = 0
    MAX_PITCH = 127

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.notes: list = []
        self.ghost_notes: list = []
        self.transcription_candidates: list[TranscriptionCandidate] = []
        self.transcription_candidates_visible = False
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
        self._max_note_duration = 0.0
        self.content_end_ms = 0.0
        self._note_index_revision = 0
        self._visible_note_cache_key: tuple | None = None
        self._visible_note_cache: list[int] = []
        self._ghost_starts: list[float] = []
        self._ghost_max_duration = 0.0
        self._candidate_starts: list[float] = []
        self._candidate_max_duration = 0.0
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(480, 300)

    @property
    def beat_ms(self) -> float:
        return 60000.0 / max(1, self.editor.bpm)

    @property
    def px_per_ms(self) -> float:
        return self.px_per_beat / self.beat_ms

    def set_notes(self, notes: list, preserve_selection: bool = False) -> None:
        self.notes = list(notes)
        self.rebuild_note_index()
        if not preserve_selection:
            self.selected.clear()
        else:
            self.selected = {i for i in self.selected if i < len(self.notes)}
        self.update()

    def set_ghost_notes(self, notes: list) -> None:
        self.ghost_notes = sorted(list(notes), key=lambda note: float(note.start))
        self._ghost_starts = [float(note.start) for note in self.ghost_notes]
        self._ghost_max_duration = max((float(note.dur) for note in self.ghost_notes), default=0.0)
        self.update()

    def set_transcription_candidates(
        self,
        candidates: list[TranscriptionCandidate] | tuple[TranscriptionCandidate, ...],
        *,
        visible: bool = True,
    ) -> None:
        self.transcription_candidates = sorted(
            list(candidates),
            key=lambda candidate: (
                float(candidate.start_ms),
                int(candidate.pitch),
                float(candidate.duration_ms),
            ),
        )
        self._candidate_starts = [
            float(candidate.start_ms)
            for candidate in self.transcription_candidates
        ]
        self._candidate_max_duration = max(
            (
                float(candidate.duration_ms)
                for candidate in self.transcription_candidates
            ),
            default=0.0,
        )
        self.transcription_candidates_visible = bool(visible)
        self.rebuild_note_index()
        self.update()

    def set_transcription_candidates_visible(self, visible: bool) -> None:
        self.transcription_candidates_visible = bool(visible)
        self.rebuild_note_index()
        self.update()

    def set_preload_progress(self, progress: float, state: str = "loading") -> None:
        self.preload_progress = max(0.0, min(1.0, float(progress)))
        self.preload_state = state if state in {"idle", "loading", "ready"} else "idle"
        self.update()

    def rebuild_note_index(self) -> None:
        self._note_order = sorted(range(len(self.notes)), key=lambda index: self.notes[index].start)
        self._note_starts = [float(self.notes[index].start) for index in self._note_order]
        self._max_note_duration = max((float(note.dur) for note in self.notes), default=0.0)
        note_end = max(
            (float(note.start + note.dur) for note in self.notes),
            default=0.0,
        )
        candidate_end = (
            max(
                (
                    float(candidate.start_ms + candidate.duration_ms)
                    for candidate in self.transcription_candidates
                ),
                default=0.0,
            )
            if self.transcription_candidates_visible
            else 0.0
        )
        self.content_end_ms = max(note_end, candidate_end)
        self._note_index_revision += 1
        self._visible_note_cache_key = None
        self._visible_note_cache = []

    def visible_note_indices(self) -> list[int]:
        left = self.scroll_ms
        right = self.time_at(self.width())
        cache_key = (
            self._note_index_revision,
            round(left, 3),
            round(right, 3),
        )
        if cache_key == self._visible_note_cache_key:
            return self._visible_note_cache
        lo = bisect_left(self._note_starts, left - self._max_note_duration)
        hi = bisect_right(self._note_starts, right)
        self._visible_note_cache_key = cache_key
        self._visible_note_cache = self._note_order[lo:hi]
        return self._visible_note_cache

    def visible_ghost_notes(self) -> list:
        left = self.scroll_ms
        right = self.time_at(self.width())
        lo = bisect_left(self._ghost_starts, left - self._ghost_max_duration)
        hi = bisect_right(self._ghost_starts, right)
        return self.ghost_notes[lo:hi]

    def visible_transcription_candidates(self) -> list[TranscriptionCandidate]:
        if not self.transcription_candidates_visible:
            return []
        left = self.scroll_ms
        right = self.time_at(self.width())
        lo = bisect_left(
            self._candidate_starts,
            left - self._candidate_max_duration,
        )
        hi = bisect_right(self._candidate_starts, right)
        return self.transcription_candidates[lo:hi]

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

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        backdrop = QLinearGradient(0, 0, 0, self.height())
        backdrop.setColorAt(0.0, QColor("#1d1e21"))
        backdrop.setColorAt(1.0, QColor("#151619"))
        painter.fillRect(self.rect(), backdrop)
        grid = self.grid_rect()
        grid_backdrop = QLinearGradient(grid.topLeft(), grid.bottomLeft())
        grid_backdrop.setColorAt(0.0, QColor("#202125"))
        grid_backdrop.setColorAt(1.0, QColor("#1a1b1e"))
        painter.fillRect(grid, grid_backdrop)
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        for row in range(visible_rows + 1):
            pitch = self.pitch_top - row
            y = self.RULER_H + row * self.ROW_H
            black = pitch % 12 in (1, 3, 6, 8, 10)
            pressed = pitch == self.piano_pressed_pitch
            hovered = pitch == self.piano_hover_pitch
            painter.fillRect(QRectF(self.KEY_W, y, grid.width(), self.ROW_H), QColor(0, 0, 0, 11 if black else 2))
            if pitch % 12 == 0:
                painter.fillRect(QRectF(self.KEY_W, y, grid.width(), self.ROW_H), QColor(255, 255, 255, 5))
            painter.save()
            key_rect = QRectF(0, y, self.KEY_W, self.ROW_H)
            natural_gradient = QLinearGradient(key_rect.topLeft(), key_rect.topRight())
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
            painter.drawLine(1, y + 1, self.KEY_W - 2, y + 1)
            painter.setPen(QColor("#111311"))
            painter.drawLine(0, y + self.ROW_H - 1, self.KEY_W - 1, y + self.ROW_H - 1)

            key_font = painter.font()
            key_font.setPointSize(max(7, key_font.pointSize() - 2))
            key_font.setBold(black)
            painter.setFont(key_font)
            if black:
                black_rect = QRectF(
                    self.BLACK_KEY_X,
                    y + 3,
                    self.BLACK_KEY_W,
                    self.ROW_H - 6,
                )
                black_gradient = QLinearGradient(black_rect.topLeft(), black_rect.topRight())
                if pressed:
                    black_gradient.setColorAt(0.0, QColor("#3b2810"))
                    black_gradient.setColorAt(0.76, QColor("#65471d"))
                    black_gradient.setColorAt(1.0, QColor("#9b7030"))
                elif hovered:
                    black_gradient.setColorAt(0.0, QColor("#101311"))
                    black_gradient.setColorAt(0.76, QColor("#1d211e"))
                    black_gradient.setColorAt(1.0, QColor("#3a3d39"))
                else:
                    black_gradient.setColorAt(0.0, QColor("#090b0a"))
                    black_gradient.setColorAt(0.76, QColor("#111412"))
                    black_gradient.setColorAt(1.0, QColor("#292c29"))
                painter.fillRect(black_rect, black_gradient)
                painter.setPen(QColor("#050605"))
                painter.drawRect(black_rect)
                painter.setPen(QColor("#fff0ca" if pressed else "#d5d0c7"))
                painter.drawText(
                    black_rect.adjusted(4, 0, -4, 0),
                    Qt.AlignRight | Qt.AlignVCenter,
                    note_name(pitch),
                )
            else:
                painter.setPen(QColor("#fff0ca" if pressed else ("#d8d3ca" if pitch % 12 else "#f0d8a2")))
                painter.drawText(
                    key_rect.adjusted(4, 0, -6, 0),
                    Qt.AlignRight | Qt.AlignVCenter,
                    note_name(pitch),
                )
            painter.restore()
            painter.setPen(QColor("#17181a" if black else "#303135"))
            painter.drawLine(self.KEY_W, y, self.width(), y)
            if pitch % 12 == 0:
                painter.setPen(QColor(108, 109, 113, 70))
                painter.drawLine(self.KEY_W, y + self.ROW_H - 1, self.width(), y + self.ROW_H - 1)
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
        measure = math.floor(self.scroll_ms / measure_ms) * measure_ms
        measure_index = max(0, math.floor(measure / measure_ms))
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
        first = math.floor(self.scroll_ms / step_ms) * step_ms
        t = first
        while t <= right_ms + step_ms:
            x = self.x_at_time(t)
            beat_index = round(t / self.beat_ms)
            major = beat_index % max(1, self.editor.time_sig) == 0 and abs(t / self.beat_ms - beat_index) < .02
            painter.setPen(QPen(QColor("#45464a" if major else "#2d2e32"), 1))
            painter.drawLine(x, 0 if major else self.RULER_H, x, self.height())
            painter.drawLine(x, self.RULER_H - (8 if major else 5), x, self.RULER_H - 3)
            if major:
                painter.setPen(QColor("#c1b9ab"))
                painter.drawText(int(x + 4), 19, str(beat_index // max(1, self.editor.time_sig) + 1))
            t += step_ms
        if self.ghost_notes:
            for note in self.visible_ghost_notes():
                rect = self.note_rect(note)
                if not rect.intersects(grid):
                    continue
                painter.setBrush(QColor(118, 119, 124, 34))
                painter.setPen(QPen(QColor(151, 152, 157, 66), 1))
                painter.drawRect(rect)
        for candidate in self.visible_transcription_candidates():
            rect = self.note_rect(candidate)
            if not rect.intersects(grid):
                continue
            invalid = self.editor.note_invalid(candidate.pitch)
            confidence = max(0.0, min(1.0, float(candidate.confidence)))
            color = QColor("#d8645a" if invalid else "#55c4ba")
            fill = QColor(color)
            fill.setAlpha(28 + round(confidence * 92))
            outline = QColor(color)
            outline.setAlpha(115 + round(confidence * 120))
            painter.fillRect(rect, fill)
            painter.setPen(QPen(outline, 1.2, Qt.DashLine))
            painter.drawRect(rect)
            if rect.width() >= 42:
                painter.setPen(QColor("#f0eee8"))
                painter.drawText(
                    rect.adjusted(4, 0, -3, 0),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    f"{note_name(candidate.pitch)} · {confidence:.0%}",
                )
        for index in self.visible_note_indices():
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
            painter.save()
            painter.setClipRect(rect.adjusted(2, 1, -2, -1))
            label_font = painter.font()
            label_font.setPointSize(max(6, label_font.pointSize() - (2 if rect.width() < 34 else 1)))
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
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.position().x() >= self.KEY_W and event.position().y() < self.RULER_H:
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
            self.editor.audition_note(self.notes[index])
            return
        if not (mods & Qt.ControlModifier):
            self.selected.clear()
        raw_start = self.time_at(event.position().x())
        cursor_start = raw_start if mods & Qt.AltModifier or not self.editor.snap_box.isChecked() else self.editor.snap_time(raw_start)
        self.set_edit_cursor(cursor_start)
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
            if pos.x() < self.KEY_W:
                self.setCursor(Qt.PointingHandCursor)
            elif pos.y() < self.RULER_H:
                self.setCursor(Qt.SizeHorCursor)
            else:
                _index, mode = self.note_at(pos)
                if mode in ("resize_left", "resize_right"):
                    self.setCursor(Qt.SizeHorCursor)
                elif mode == "move":
                    self.setCursor(Qt.SizeAllCursor)
                else:
                    self.setCursor(Qt.CrossCursor if self.editor.draw_mode_button.isChecked() else Qt.ArrowCursor)
            return
        dx, dy = pos.x() - self.press_pos.x(), pos.y() - self.press_pos.y()
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
        if not self.piano_key_dragging and self.piano_hover_pitch is not None:
            self.piano_hover_pitch = None
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
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
            self.selected = set(range(len(self.notes)))
            self.selection_changed.emit(); self.update(); return
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

    def __init__(self, parent, track: TrackState, bpm: int, time_sig: int, transpose: int = 0) -> None:
        super().__init__(parent)
        self.setObjectName("MidiNoteEditorDialog")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.track, self.bpm, self.time_sig, self.transpose = track, int(bpm or 120), int(time_sig or 4), int(transpose)
        self.undo_stack: list[tuple[list, set[int]]] = []
        self.redo_stack: list[tuple[list, set[int]]] = []
        self.clipboard: list = []
        self.last_applied = list(track.notes)
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
        self.transcription_worker: TranscriptionAnalysisWorker | None = None
        self.transcription_generation = 0
        self.transcription_close_pending = False
        self.transcription_dialog_result_pending: int | None = None
        self.draft_reference_only = False
        self.default_note_velocity = 100
        self.last_note_duration_ms = 0.0
        self._invalid_pitch_cache: dict[int, bool] = {}
        self._invalid_note_count = 0
        self._hover_status_key: tuple[int, int] | None = None
        self.setWindowTitle(f"编辑音符 · {track.display_name}")
        self.setMinimumSize(920, 580)
        available = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        if available is None:
            self.resize(1440, 860)
        else:
            self.resize(
                max(self.minimumWidth(), min(1560, available.width() - 72)),
                max(self.minimumHeight(), min(960, available.height() - 72)),
            )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 10)
        root.setSpacing(8)

        def add_inset(widget: QWidget, object_name: str) -> None:
            shell = QWidget()
            shell.setObjectName(object_name)
            shell_layout = QHBoxLayout(shell)
            shell_layout.setContentsMargins(12, 0, 12, 0)
            shell_layout.setSpacing(0)
            shell_layout.addWidget(widget)
            root.addWidget(shell)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("EditorToolbar")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(15, 9, 12, 9)
        toolbar.setSpacing(9)
        title_block = QWidget()
        title_layout = QVBoxLayout(title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(1)
        instrument_name = BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, "未知乐器")
        eyebrow_text = "音块编辑器" if instrument_name in track.display_name else instrument_name
        eyebrow = QLabel(eyebrow_text)
        eyebrow.setObjectName("EditorEyebrow")
        title_layout.addWidget(eyebrow)
        title = QLabel(track.display_name)
        title.setObjectName("EditorTrackTitle")
        title_layout.addWidget(title)
        self.track_meta = QLabel()
        self.track_meta.setObjectName("EditorTrackMeta")
        title_layout.addWidget(self.track_meta)
        toolbar.addWidget(title_block)
        toolbar.addSpacing(10)
        transport_frame = QFrame()
        transport_frame.setObjectName("EditorTransport")
        transport = QHBoxLayout(transport_frame)
        transport.setContentsMargins(6, 4, 7, 4)
        transport.setSpacing(5)
        self.draft_play_button = PillButton("播放", "primary", FluentSymbol.PLAY)
        self.draft_play_button.clicked.connect(self.toggle_draft_playback)
        transport.addWidget(self.draft_play_button)
        self.draft_stop_button = PillButton("停止", "ghost", FluentSymbol.STOP)
        self.draft_stop_button.clicked.connect(self.stop_draft)
        transport.addWidget(self.draft_stop_button)
        self.loop_box = QCheckBox("循环")
        transport.addWidget(self.loop_box)
        self.playback_time_label = QLabel("0:00.000 / 0:00.000")
        self.playback_time_label.setObjectName("EditorTime")
        self.playback_time_label.setFixedWidth(152)
        transport.addWidget(self.playback_time_label)
        toolbar.addWidget(transport_frame)
        toolbar.addStretch(1)
        for label, callback in (("撤销", self.undo), ("重做", self.redo), ("删除", self.delete_selected)):
            icon = FluentSymbol.DELETE if label == "删除" else None
            button = PillButton(label, "ghost", icon)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        optimize_button = PillButton("优化此轨", "secondary", FluentSymbol.OPTIMIZE)
        optimize_button.clicked.connect(self.optimize_draft)
        toolbar.addWidget(optimize_button)
        toolbar.addSpacing(5)
        self.apply_button = PillButton("应用", "ghost")
        self.apply_button.clicked.connect(self.apply_notes)
        toolbar.addWidget(self.apply_button)
        self.cancel_button = PillButton("取消", "ghost")
        self.cancel_button.clicked.connect(self.reject)
        toolbar.addWidget(self.cancel_button)
        self.confirm_button = PillButton("确定", "convert")
        self.confirm_button.clicked.connect(self.accept_with_apply)
        toolbar.addWidget(self.confirm_button)
        add_inset(toolbar_frame, "EditorToolbarInset")

        inspector = QFrame()
        inspector.setObjectName("NoteInspectorTop")
        inspector.setFixedHeight(48)
        inspector_layout = QHBoxLayout(inspector)
        inspector_layout.setContentsMargins(8, 6, 8, 6)
        inspector_layout.setSpacing(7)
        self.draw_mode_button = PillButton("绘制 B", "ghost")
        self.draw_mode_button.setObjectName("DrawMode")
        self.draw_mode_button.setCheckable(True)
        self.draw_mode_button.setFixedHeight(30)
        self.draw_mode_button.setToolTip("绘制模式：拖动可同时设置音符长度与力度（B）")
        self.draw_mode_button.toggled.connect(self._toggle_draw_mode)
        inspector_layout.addWidget(self.draw_mode_button)
        self.note_mode_button = PillButton("音符属性", "ghost")
        self.note_mode_button.setObjectName("InspectorMode")
        self.note_mode_button.setFixedHeight(30)
        self.note_mode_button.setCheckable(True)
        self.note_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("note"))
        inspector_layout.addWidget(self.note_mode_button)
        self.articulation_mode_button = PillButton("奏法", "ghost")
        self.articulation_mode_button.setObjectName("InspectorMode")
        self.articulation_mode_button.setFixedHeight(30)
        self.articulation_mode_button.setCheckable(True)
        self.articulation_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("articulation"))
        inspector_layout.addWidget(self.articulation_mode_button)
        self.grid_mode_button = PillButton("网格", "ghost")
        self.grid_mode_button.setObjectName("InspectorMode")
        self.grid_mode_button.setFixedHeight(30)
        self.grid_mode_button.setCheckable(True)
        self.grid_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("grid"))
        inspector_layout.addWidget(self.grid_mode_button)
        self.velocity_toggle = PillButton("力度", "ghost", FluentSymbol.CURVE)
        self.velocity_toggle.setObjectName("VelocityToggle")
        self.velocity_toggle.setCheckable(True)
        self.velocity_toggle.setFixedHeight(30)
        self.velocity_toggle.setToolTip("显示力度曲线；拖动时间点会按距离影响周边点")
        self.velocity_toggle.toggled.connect(self._toggle_velocity_lane)
        inspector_layout.addWidget(self.velocity_toggle)

        self.note_controls = QWidget()
        note_layout = QHBoxLayout(self.note_controls)
        note_layout.setContentsMargins(3, 0, 0, 0)
        note_layout.setSpacing(7)
        self.selection_summary = QLabel("未选择音符")
        self.selection_summary.setObjectName("InspectorSelection")
        self.selection_summary.setWordWrap(False)
        self.selection_summary.setMinimumWidth(145)
        self.selection_summary.setMaximumWidth(190)
        note_layout.addWidget(self.selection_summary)
        self.pitch_edit = QLineEdit()
        self.start_edit = QLineEdit()
        self.duration_edit = QLineEdit()
        self.velocity_edit = QLineEdit()
        for label, widget, field in (("音高", self.pitch_edit, "pitch"), ("开始 ms", self.start_edit, "start"), ("时值 ms", self.duration_edit, "dur"), ("力度", self.velocity_edit, "vel")):
            widget.editingFinished.connect(lambda f=field, w=widget: self.apply_field(f, w.text()))
            widget.setFixedWidth(64 if field in ("pitch", "vel") else 72)
            group = QWidget()
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            field_label = QLabel(label)
            field_label.setObjectName("Muted")
            group_layout.addWidget(field_label)
            group_layout.addWidget(widget)
            note_layout.addWidget(group)

        self.articulation_combo = QComboBox()
        supported = BDO_ARTICULATIONS.get(track.bdo_instrument_id, [])
        known = {n for n, _ in supported}
        for ntype, label in supported:
            self.articulation_combo.addItem(label, ntype)
        for ntype in sorted({int(getattr(n, "ntype", 0)) for n in track.notes} - known):
            self.articulation_combo.addItem(f"未知奏法 type {ntype}", ntype)
        if self.articulation_combo.count() == 0:
            self.articulation_combo.addItem("普通", 0)
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
            button = QPushButton(label)
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
        self.snap_box = QCheckBox("吸附")
        self.snap_box.setChecked(True)
        grid_layout.addWidget(self.snap_box)
        self.note_preview_box = QCheckBox("点击试听")
        self.note_preview_box.setChecked(True)
        grid_layout.addWidget(self.note_preview_box)
        self.ghost_box = QCheckBox("其他轨道参考")
        self.ghost_box.setChecked(True)
        self.ghost_box.toggled.connect(self._toggle_ghost_notes)
        grid_layout.addWidget(self.ghost_box)
        grid_layout.addWidget(QLabel("量化"))
        self.quantize_combo = QComboBox()
        for label, divisor in (("1/4", 1), ("1/8", 2), ("1/16", 4), ("1/32", 8)):
            self.quantize_combo.addItem(label, divisor)
        self.quantize_combo.setCurrentIndex(2)
        self.quantize_combo.setFixedWidth(76)
        grid_layout.addWidget(self.quantize_combo)
        grid_layout.addWidget(QLabel("水平缩放"))
        self.editor_zoom = QSlider(Qt.Horizontal)
        self.editor_zoom.setRange(30, 320)
        self.editor_zoom.setValue(92)
        self.editor_zoom.setFixedWidth(150)
        self.editor_zoom.valueChanged.connect(self.set_zoom)
        grid_layout.addWidget(self.editor_zoom)
        grid_layout.addStretch(1)
        inspector_layout.addWidget(self.grid_controls, 1)
        add_inset(inspector, "EditorInspectorInset")
        self._set_top_inspector_mode("note")

        workspace = QFrame()
        workspace.setObjectName("EditorWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        roll = QGridLayout()
        roll.setContentsMargins(0, 0, 0, 0)
        roll.setSpacing(0)
        self.canvas = PianoRollCanvas(self)
        self.canvas.set_notes(list(track.notes))
        self.canvas.selection_changed.connect(self.refresh_fields)
        self.canvas.notes_changed.connect(self._notes_changed)
        self.canvas.hover_changed.connect(self._hover_changed)
        self.canvas.ruler_seek_requested.connect(self.seek_draft)
        self.pitch_scroll = QScrollBar(Qt.Vertical)
        self.pitch_scroll.setObjectName("PianoPitchScroll")
        self.pitch_scroll.setRange(0, 0)
        self.pitch_scroll.valueChanged.connect(self.set_pitch_scroll)
        self.time_scroll = QScrollBar(Qt.Horizontal)
        self.time_scroll.setObjectName("PianoTimeScroll")
        self.time_scroll.valueChanged.connect(self.set_time_scroll)
        roll.addWidget(self.canvas, 0, 0)
        roll.addWidget(self.pitch_scroll, 0, 1)
        roll.addWidget(self.time_scroll, 1, 0)
        scroll_corner = QWidget()
        scroll_corner.setObjectName("PianoScrollCorner")
        scroll_corner.setFixedSize(12, 12)
        roll.addWidget(scroll_corner, 1, 1)
        workspace_layout.addLayout(roll, 1)
        self.velocity_lane = VelocityLaneCanvas(self)
        self.velocity_lane.setVisible(False)
        workspace_layout.addWidget(self.velocity_lane)
        root.addWidget(workspace, 1)

        self.transcription_panel = QFrame()
        self.transcription_panel.setObjectName("TranscriptionPanel")
        self.transcription_panel.setFixedHeight(42)
        transcription_layout = QHBoxLayout(self.transcription_panel)
        transcription_layout.setContentsMargins(12, 5, 12, 5)
        transcription_layout.setSpacing(8)
        self.transcription_hint = QLabel(
            tr("识别结果仅作为候选，不会自动写入当前轨道")
        )
        self.transcription_hint.setObjectName("Muted")
        transcription_layout.addWidget(self.transcription_hint, 1)
        self.transcription_progress = QLabel(tr("尚未分析"))
        self.transcription_progress.setObjectName("Muted")
        self.transcription_progress.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.transcription_progress.setMinimumWidth(90)
        transcription_layout.addWidget(self.transcription_progress)
        self.transcription_analyze_button = PillButton(
            tr("分析参考音频"),
            "secondary",
        )
        self.transcription_analyze_button.setFixedHeight(28)
        self.transcription_analyze_button.clicked.connect(
            self._toggle_transcription_analysis
        )
        transcription_layout.addWidget(self.transcription_analyze_button)
        self.transcription_accept_button = PillButton(
            tr("写入草稿"),
            "primary",
        )
        self.transcription_accept_button.setFixedHeight(28)
        self.transcription_accept_button.setEnabled(False)
        self.transcription_accept_button.clicked.connect(
            self.accept_transcription_candidates
        )
        transcription_layout.addWidget(self.transcription_accept_button)
        self.transcription_clear_button = PillButton(tr("清除候选"), "ghost")
        self.transcription_clear_button.setFixedHeight(28)
        self.transcription_clear_button.setEnabled(False)
        self.transcription_clear_button.clicked.connect(
            self.clear_transcription_candidates
        )
        transcription_layout.addWidget(self.transcription_clear_button)
        self.transcription_panel.setVisible(False)
        add_inset(self.transcription_panel, "TranscriptionPanelInset")

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
        self.music_volume_slider.valueChanged.connect(self._set_editor_music_volume)
        footer_layout.addWidget(self.music_volume_slider)
        self.music_volume_value = QLabel(f"{initial_music_volume}%")
        self.music_volume_value.setObjectName("Muted")
        self.music_volume_value.setFixedWidth(38)
        footer_layout.addWidget(self.music_volume_value)
        self.transcription_mode_toggle = QCheckBox(tr("扒谱模式"))
        self.transcription_mode_toggle.setObjectName("TranscriptionModeToggle")
        self.transcription_mode_toggle.setToolTip(
            tr("开启参考音频分析与候选音符审阅")
        )
        self.transcription_mode_toggle.toggled.connect(
            self._set_transcription_mode_enabled
        )
        footer_layout.addWidget(self.transcription_mode_toggle)
        add_inset(footer, "EditorFooterInset")
        self._toggle_ghost_notes(True)
        self.finished.connect(lambda _result: self.stop_draft())
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.space_shortcut.setContext(Qt.WindowShortcut)
        self.space_shortcut.activated.connect(self.toggle_draft_playback)
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.refresh_fields()
        QTimer.singleShot(0, self.update_scrollbars)
        QTimer.singleShot(
            180,
            lambda: show_global_toast(
                self,
                "双击网格新建音符；按 B 切换绘制模式。",
            ),
        )

    def quantize_ms(self) -> float:
        return self.canvas.beat_ms / int(self.quantize_combo.currentData() or 4)

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
        self.canvas.set_transcription_candidates_visible(
            self.transcription_mode_enabled
        )
        if not self.transcription_mode_enabled:
            self._cancel_transcription_analysis()
        else:
            reference_audio = getattr(self.parent(), "reference_audio", None)
            if reference_audio is None or not reference_audio.audio_path:
                self.transcription_hint.setText(
                    tr("请先在主时间轴最下方载入 MP3/WAV 参考音频")
                )
            else:
                self.transcription_hint.setText(
                    tr("识别结果仅作为候选，不会自动写入当前轨道")
                )
        self.update_scrollbars()

    def _toggle_transcription_analysis(self) -> None:
        if self.transcription_worker is not None and self.transcription_worker.isRunning():
            self._cancel_transcription_analysis()
            return
        self.start_transcription_analysis()

    def start_transcription_analysis(self) -> None:
        reference_audio = getattr(self.parent(), "reference_audio", None)
        audio_path = str(getattr(reference_audio, "audio_path", "") or "")
        if not audio_path:
            QMessageBox.warning(
                self,
                tr("无法开始扒谱"),
                tr("请先在主时间轴最下方载入 MP3/WAV 参考音频"),
            )
            return
        if self.track.is_percussion:
            QMessageBox.warning(
                self,
                tr("当前轨道不适合自动扒谱"),
                tr("Basic Pitch 不识别游戏鼓件映射；请在旋律乐器轨道中审阅候选"),
            )
            return
        retained_playhead = self.playhead_ms
        self.stop_draft()
        self.set_draft_playhead(retained_playhead)
        self.transcription_generation += 1
        generation = self.transcription_generation
        worker = TranscriptionAnalysisWorker(audio_path, self)
        self.transcription_worker = worker
        worker.progress_changed.connect(
            lambda value, token=generation: self._transcription_progress_changed(
                token, value
            )
        )
        worker.succeeded.connect(
            lambda result, token=generation: self._transcription_succeeded(
                token, result
            )
        )
        worker.failed.connect(
            lambda message, token=generation: self._transcription_failed(
                token, message
            )
        )
        worker.cancelled.connect(
            lambda token=generation: self._transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._transcription_thread_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self.transcription_progress.setText("0%")
        self.transcription_hint.setText(
            tr("正在分析参考音频；为保证播放稳定，分析期间已停止试听")
        )
        self.transcription_analyze_button.setText(tr("取消分析"))
        self.transcription_accept_button.setEnabled(False)
        self.transcription_clear_button.setEnabled(
            bool(self.transcription_candidates)
        )
        self.draft_play_button.setEnabled(False)
        worker.start()

    def _cancel_transcription_analysis(self) -> None:
        worker = self.transcription_worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        self.transcription_progress.setText(tr("正在取消…"))
        self.transcription_analyze_button.setEnabled(False)

    def _transcription_progress_changed(self, generation: int, value: int) -> None:
        if generation != self.transcription_generation:
            return
        self.transcription_progress.setText(f"{max(0, min(100, int(value)))}%")

    def _finish_transcription_worker(self, generation: int) -> bool:
        if generation != self.transcription_generation:
            return False
        self.transcription_analyze_button.setEnabled(True)
        self.transcription_analyze_button.setText(tr("分析参考音频"))
        self.draft_play_button.setEnabled(True)
        return True

    def _transcription_thread_finished(
        self,
        generation: int,
        worker: "TranscriptionAnalysisWorker",
    ) -> None:
        if (
            generation == self.transcription_generation
            and self.transcription_worker is worker
        ):
            self.transcription_worker = None
            self.transcription_analyze_button.setEnabled(True)
            self.transcription_analyze_button.setText(tr("分析参考音频"))
            self.draft_play_button.setEnabled(True)
        if self.transcription_close_pending and self.transcription_worker is None:
            self.transcription_close_pending = False
            pending_result = self.transcription_dialog_result_pending
            self.transcription_dialog_result_pending = None
            if pending_result == QDialog.Accepted:
                QTimer.singleShot(0, lambda: QDialog.accept(self))
            elif pending_result == QDialog.Rejected:
                QTimer.singleShot(0, lambda: QDialog.reject(self))
            else:
                QTimer.singleShot(0, self.close)

    def _transcription_succeeded(
        self,
        generation: int,
        result: TranscriptionResult,
    ) -> None:
        if not self._finish_transcription_worker(generation):
            return
        self.transcription_result = result
        self.transcription_candidates = tuple(result.candidates)
        self.canvas.set_transcription_candidates(
            self.transcription_candidates,
            visible=self.transcription_mode_enabled,
        )
        count = len(self.transcription_candidates)
        self.transcription_progress.setText(
            trf("{count} 个候选", count=count)
        )
        self.transcription_hint.setText(
            tr("缓存结果已载入") if result.cache_hit
            else tr("分析完成；候选仍需手动写入草稿")
        )
        self.transcription_accept_button.setEnabled(count > 0)
        self.transcription_clear_button.setEnabled(count > 0)
        self.update_scrollbars()

    def _transcription_failed(self, generation: int, message: str) -> None:
        if not self._finish_transcription_worker(generation):
            return
        self.transcription_progress.setText(tr("分析失败"))
        self.transcription_hint.setText(tr("扒谱分析未改变任何正式音符"))
        QMessageBox.warning(self, tr("扒谱分析失败"), message)

    def _transcription_cancelled(self, generation: int) -> None:
        if not self._finish_transcription_worker(generation):
            return
        self.transcription_progress.setText(tr("已取消"))
        self.transcription_hint.setText(
            tr("识别结果仅作为候选，不会自动写入当前轨道")
        )

    def clear_transcription_candidates(self) -> None:
        self.transcription_candidates = ()
        self.transcription_result = None
        self.canvas.set_transcription_candidates(
            (),
            visible=self.transcription_mode_enabled,
        )
        self.transcription_progress.setText(tr("尚未分析"))
        self.transcription_accept_button.setEnabled(False)
        self.transcription_clear_button.setEnabled(False)
        self.transcription_hint.setText(
            tr("识别结果仅作为候选，不会自动写入当前轨道")
        )
        self.update_scrollbars()

    @staticmethod
    def _candidate_matches_note(
        candidate: TranscriptionCandidate,
        note,
        tolerance_ms: float,
    ) -> bool:
        return (
            int(candidate.pitch) == int(note.pitch)
            and abs(float(candidate.start_ms) - float(note.start)) <= tolerance_ms
            and abs(
                float(candidate.duration_ms) - float(note.dur)
            ) <= max(tolerance_ms, float(candidate.duration_ms) * 0.18)
        )

    def accept_transcription_candidates(self) -> None:
        if not self.transcription_candidates:
            return
        tolerance = max(35.0, self.quantize_ms() * 0.2)
        existing = list(self.canvas.notes)
        accepted: list = []
        invalid = 0
        duplicates = 0
        for candidate in self.transcription_candidates:
            if self.note_invalid(candidate.pitch):
                invalid += 1
                continue
            if any(
                self._candidate_matches_note(candidate, note, tolerance)
                for note in (*existing, *accepted)
            ):
                duplicates += 1
                continue
            accepted.append(
                Note(
                    max(0, min(127, int(candidate.pitch))),
                    max(1, min(127, int(candidate.velocity))),
                    max(0.0, float(candidate.start_ms)),
                    max(1.0, float(candidate.duration_ms)),
                    0,
                )
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

    def _toggle_ghost_notes(self, enabled: bool) -> None:
        parent = self.parent()
        if not enabled or not parent or not hasattr(parent, "tracks"):
            if hasattr(self, "canvas"):
                self.canvas.set_ghost_notes([])
            return
        notes = [
            note
            for item in parent.tracks
            if int(item.track_id) != int(self.track.track_id) and not item.muted
            for note in item.notes
        ]
        if hasattr(self, "canvas"):
            self.canvas.set_ghost_notes(notes)

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
            show_global_toast(self, "选择音符后即可批量应用奏法。")
        elif mode == "grid" and self.isVisible():
            show_global_toast(
                self,
                "双击新建 · Ctrl+拖动复制 · Alt 临时取消吸附 · Ctrl+D 复制",
            )

    def _toggle_draw_mode(self, enabled: bool) -> None:
        if hasattr(self, "canvas"):
            self.canvas.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
            self.canvas.update()
        if hasattr(self, "status"):
            show_global_toast(
                self,
                "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附"
                if enabled else "选择模式：双击新建，拖动空白框选，Ctrl+拖动复制"
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
                end = max(end, float(reference_audio.duration_ms))
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
                    QMessageBox.warning(self, "定位失败", str(exc))
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                reference_audio.set_position(self.playhead_ms)

    def poll_draft_playback(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            self.playback_timer.stop()
            return
        reference_audio = getattr(parent, "reference_audio", None)
        if self.draft_reference_only:
            if reference_audio is None or not reference_audio.audio_path:
                self.stop_draft()
                return
            position = float(reference_audio.player.position())
            self.set_draft_playhead(position, follow=True)
            if self.draft_playback_state == "paused":
                return
            duration = self.draft_duration_ms()
            if (
                not reference_audio.is_playing
                or (duration > 0 and position >= duration - 1)
            ):
                if self.loop_box.isChecked():
                    reference_audio.set_position(0.0)
                    reference_audio.play()
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
                    and reference_audio is not None
                    and reference_audio.audio_path
                ):
                    reference_audio.set_position(self.playhead_ms)
                    reference_audio.play()
            status = parent.realtime_audio.get_status()
            self.set_draft_playhead(status.position_ms, follow=self.draft_playback_state == "playing")
            if (
                self.transcription_mode_enabled
                and reference_audio is not None
                and reference_audio.audio_path
                and status.state == "playing"
                and not reference_audio.is_playing
            ):
                reference_audio.set_position(status.position_ms)
                reference_audio.play()
            if status.position_ms >= status.duration_ms - 1 and status.duration_ms > 0:
                if (
                    self.transcription_mode_enabled
                    and reference_audio is not None
                    and reference_audio.is_playing
                    and reference_audio.player.position()
                    < self.draft_duration_ms() - 1
                ):
                    self.draft_reference_only = True
                elif self.loop_box.isChecked():
                    self.seek_draft(0.0)
                    parent.realtime_audio.play()
                    if (
                        self.transcription_mode_enabled
                        and reference_audio is not None
                        and reference_audio.audio_path
                    ):
                        reference_audio.set_position(0.0)
                        reference_audio.play()
                else:
                    self.stop_draft()
            elif status.state == "paused" and self.draft_playback_state == "playing":
                self._set_draft_playback_state("paused")
        except AudioEngineError as exc:
            self.playback_timer.stop()
            parent.realtime_audio.cancel_loading()
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, "试听失败", str(exc))

    def set_zoom(self, value: int) -> None:
        if math.isclose(self.canvas.px_per_beat, float(value)):
            return
        self.canvas.px_per_beat = float(value)
        self.canvas.update()
        self.velocity_lane.update()
        self.update_scrollbars()

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
        if time_changed or pitch_changed:
            self.canvas.update()
        self.set_draft_playhead(self.playhead_ms)

    def visible_pitch_rows(self) -> int:
        grid_height = max(0, self.canvas.height() - self.canvas.RULER_H)
        return max(1, math.ceil(grid_height / self.canvas.ROW_H))

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
        self.status.setText(f"单轨优化完成 · 当前草稿 {len(self.canvas.notes)} 音符 · 点击应用或确定后写回")

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
        self.draft_play_button.setText(tr(labels.get(state, "播放")))
        self.draft_play_button.setEnabled(state != "loading")

    def play_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        draft_track = replace(self.track, notes=self.edited_notes(), muted=False, solo=False)
        blockers = parent._realtime_preview_blockers([draft_track])
        if blockers:
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                parent._stop_preview(reset_playhead=False)
                reference_audio.set_position(self.playhead_ms)
                reference_audio.play()
                self.draft_reference_only = True
                self._set_draft_playback_state("playing")
                self.playback_timer.start()
                self.status.setText(tr("仅播放参考音频"))
                return
            QMessageBox.warning(self, "无法试听", "当前轨道缺少可用的实时游戏音源：\n- " + "\n- ".join(blockers[:6]))
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
            QMessageBox.warning(self, "试听失败", str(exc))

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
            self.audition_stop_timer.start(700)
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
            if self.transcription_mode_enabled and reference_audio is not None:
                reference_audio.pause()
            self._set_draft_playback_state("paused")
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, "试听失败", str(exc))

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
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                reference_audio.set_position(self.playhead_ms)
                reference_audio.play()
            self._set_draft_playback_state("playing")
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, "试听失败", str(exc))

    def stop_draft(self) -> None:
        self.playback_timer.stop()
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        parent = self.parent()
        if parent and hasattr(parent, "realtime_audio"):
            try:
                parent.realtime_audio.stop()
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
        worker = self.transcription_worker
        if worker is not None and worker.isRunning():
            self.transcription_close_pending = True
            worker.cancel()
            self.transcription_progress.setText(tr("正在取消…"))
            self.transcription_analyze_button.setEnabled(False)
            self.draft_play_button.setEnabled(False)
            event.ignore()
            return
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        self.stop_draft()
        super().closeEvent(event)

    def _defer_dialog_result_for_transcription(self, result: int) -> bool:
        worker = self.transcription_worker
        if worker is None or not worker.isRunning():
            return False
        self.transcription_close_pending = True
        self.transcription_dialog_result_pending = int(result)
        worker.cancel()
        self.transcription_progress.setText(tr("正在取消…"))
        self.transcription_analyze_button.setEnabled(False)
        self.draft_play_button.setEnabled(False)
        return True

    def reject(self) -> None:
        if self._defer_dialog_result_for_transcription(QDialog.Rejected):
            return
        super().reject()

    def accept(self) -> None:
        if self._defer_dialog_result_for_transcription(QDialog.Accepted):
            return
        super().accept()

    def minimum_duration_ms(self) -> float:
        return max(1.0, self.quantize_ms() / 8.0)

    def default_note_duration(self) -> float:
        return self.last_note_duration_ms if self.last_note_duration_ms > 0 else self.quantize_ms()

    def snap_time(self, value: float) -> float:
        if not self.snap_box.isChecked():
            return max(0.0, value)
        q = self.quantize_ms()
        return max(0.0, round(value / q) * q)

    def current_articulation(self) -> int:
        return int(self.articulation_combo.currentData() or 0)

    def note_invalid(self, pitch: int) -> bool:
        pitch = int(pitch)
        cached = self._invalid_pitch_cache.get(pitch)
        if cached is not None:
            return cached
        if self.track.bdo_instrument_id == 0x0d:
            mapped = _GM_TO_BDO_DRUM.get(pitch)
            result = mapped is None or mapped < BDO_DRUM_MIN or mapped > BDO_DRUM_MAX
        else:
            supported = game_supported_pitches(self.track.bdo_instrument_id)
            converted = pitch + self.transpose
            result = converted not in supported if supported is not None else not (BDO_NOTE_MIN <= converted <= BDO_NOTE_MAX)
        self._invalid_pitch_cache[pitch] = result
        return result

    def _recalculate_invalid_note_count(self) -> None:
        self._invalid_note_count = sum(1 for note in self.canvas.notes if self.note_invalid(note.pitch))

    def snapshot(self) -> tuple[list, set[int]]:
        return list(self.canvas.notes), set(self.canvas.selected)

    def push_snapshot(self, notes=None, selected=None) -> None:
        self.undo_stack.append((list(self.canvas.notes if notes is None else notes), set(self.canvas.selected if selected is None else selected)))
        if len(self.undo_stack) > 200: self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, state) -> None:
        if self.draft_playback_state != "stopped":
            self.stop_draft()
        self.canvas.notes, self.canvas.selected = list(state[0]), set(state[1])
        self.canvas.rebuild_note_index()
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.canvas.update(); self.refresh_fields()

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
        warning = trf(" · 越界 {count}", count=self._invalid_note_count) if self._invalid_note_count else ""
        self.status.setText(trf(
            "已选 {selected} · 共 {total} 音符{position}{warning}",
            selected=len(self.canvas.selected), total=len(self.canvas.notes),
            position=pos, warning=warning,
        ))

    def _notes_changed(self) -> None:
        if self.draft_playback_state != "stopped":
            self.stop_draft()
        self.canvas.rebuild_note_index()
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.canvas.update(); self.velocity_lane.update(); self._update_status(); self.update_scrollbars()

    def _update_track_meta(self) -> None:
        if hasattr(self, "track_meta"):
            self.track_meta.setText(
                f"♫ {len(self.canvas.notes) if hasattr(self, 'canvas') else len(self.track.notes)}"
                f"   ·   {self.bpm} BPM   ·   {self.time_sig}/4"
            )

    def edited_notes(self) -> list:
        return sorted(self.canvas.notes, key=lambda n: (n.start, n.pitch, n.dur))

    def apply_notes(self) -> None:
        notes = self.edited_notes()
        self.last_applied = list(notes)
        self.notes_applied.emit(notes)

    def accept_with_apply(self) -> None:
        self.apply_notes(); self.accept()


class TrackFxDialog(QDialog):
    def __init__(self, parent: QWidget, track: TrackState) -> None:
        super().__init__(parent)
        self.setWindowTitle("玛勒尼斯音源")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.track = track

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, str(track.bdo_instrument_id)))
        title.setObjectName("TrackTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(form)

        is_marnian = track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
        self.marnian_mode: QComboBox | None = None
        if is_marnian:
            self.marnian_mode = QComboBox()
            for label, value in MARNIAN_SYNTH_MODES:
                self.marnian_mode.addItem(label, value)
            mode_index = self.marnian_mode.findData(track.marnian_synth_mode)
            self.marnian_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            form.addRow("玛勒尼斯音源", self.marnian_mode)

        if is_marnian:
            mode_hint = QLabel(
                "游戏轨道下拉框的默认值为 Basic。当前工程会保存此选择，"
                "非 Basic 的 BDO 序列化位置仍待游戏存档差分确认。"
            )
            mode_hint.setWordWrap(True)
            mode_hint.setObjectName("Muted")
            layout.addWidget(mode_hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_marnian_synth_mode(self) -> str:
        if self.marnian_mode is None:
            return "basic"
        return str(self.marnian_mode.currentData() or "basic")


class ReferenceAudioController(QObject):
    """Local MP3/WAV playback plus bounded waveform-envelope extraction."""

    file_changed = Signal(str)
    volume_changed = Signal(int)
    changed = Signal()
    timeline_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio_path: Path | None = None
        self.waveform: list[tuple[float, float, float]] = []
        self.waveform_starts: list[float] = []
        self.waveform_loading = False
        self._waveform_deferred_for_playback = False

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.5)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(lambda _position: self.changed.emit())
        self.player.durationChanged.connect(lambda _duration: self.timeline_changed.emit())
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
        self.player.stop()

    def set_position(self, milliseconds: float) -> None:
        self.player.setPosition(max(0, min(round(milliseconds), round(self.duration_ms))))

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


class TranscriptionAnalysisWorker(QThread):
    """Run optional Basic Pitch inference away from the GUI/audio threads."""

    progress_changed = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, audio_path: str | Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.audio_path = Path(audio_path)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = transcribe_reference_audio(
                self.audio_path,
                self.progress_changed.emit,
                self._cancelled.is_set,
            )
        except TranscriptionCancelled:
            self.cancelled.emit()
        except (TranscriptionError, OSError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"扒谱分析失败：{exc}")
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)


class OptimizerAnalysisWorker(QThread):
    """Run optimizer code away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, arguments: tuple, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.arguments = arguments

    def run(self) -> None:
        try:
            session = analyse_with_algorithm(*self.arguments)
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__, traceback.format_exc())
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
        self.analysis_worker: OptimizerAnalysisWorker | None = None
        scope_title = "单轨优化" if target_track_id is not None else "全局 MIDI 优化"
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
        selector.addWidget(QLabel("优化算法"), 0, 0)
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.currentIndexChanged.connect(self._algorithm_changed)
        selector.addWidget(self.algorithm_combo, 0, 1, 1, 3)
        self.open_plugins_button = QPushButton("算法包目录")
        self.open_plugins_button.clicked.connect(self._open_plugin_directory)
        selector.addWidget(self.open_plugins_button, 0, 4)
        self.refresh_plugins_button = QPushButton("刷新")
        self.refresh_plugins_button.clicked.connect(self._reload_algorithms)
        selector.addWidget(self.refresh_plugins_button, 0, 5)
        selector.addWidget(QLabel("优化强度"), 1, 0)
        self.intensity_combo = QComboBox()
        for label, value in self.INTENSITIES:
            self.intensity_combo.addItem(label, value.value)
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

        self.summary_label = QLabel("选择算法和强度，然后分析优化。")
        self.summary_label.setObjectName("OptimizerSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.analyse_button = QPushButton("分析优化")
        self.analyse_button.clicked.connect(self._analyse)
        action_row.addWidget(self.analyse_button)
        layout.addLayout(action_row)

        self.details_button = QPushButton("详细信息 ▸")
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
            scope_layout.addWidget(QLabel("允许写入的轨道"), 0, 0, 1, 2)
            for index, track in enumerate(self.source_tracks):
                box = QCheckBox(f"Track {track.track_id} · {track.display_name}")
                box.setChecked(True)
                box.stateChanged.connect(self._invalidate_preview)
                self.track_checks[int(track.track_id)] = box
                scope_layout.addWidget(box, 1 + index // 2, index % 2)
        else:
            track = next((item for item in self.source_tracks if int(item.track_id) == target_track_id), None)
            scope_layout.addWidget(QLabel(
                f"目标：Track {target_track_id} · {track.display_name if track else '未知轨道'}"
            ), 0, 0)
        details.addWidget(scope_card)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setObjectName("OptimizerReport")
        details.addWidget(self.report_text, stretch=1)
        layout.addWidget(self.details_container)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.button_box = buttons
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText("应用预览")
        self.apply_button.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
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
        for index, descriptor in enumerate(self.algorithms):
            self.algorithm_combo.addItem(descriptor.display_name, descriptor)
            if descriptor.algorithm_id == previous:
                selected_index = index
        if self.algorithms:
            self.algorithm_combo.setCurrentIndex(selected_index)
        self.algorithm_combo.blockSignals(False)
        self._algorithm_changed()

    def _algorithm_changed(self, _index: int = -1) -> None:
        descriptor = self._selected_algorithm()
        if descriptor is None:
            self.algorithm_description.setText("没有可用的优化算法。")
            self.capability_label.clear()
            self.analyse_button.setEnabled(False)
        else:
            prepass = " · 先运行游戏安全预处理" if descriptor.requires_safe_prepass else ""
            self.algorithm_description.setText(f"{descriptor.description}{prepass}")
            capabilities = "、".join(descriptor.capabilities) or "诊断"
            self.capability_label.setText(
                f"版本 {descriptor.version} · 能力：{capabilities} · 作用域：{'、'.join(descriptor.scopes)}"
            )
            self.analyse_button.setEnabled(True)
        self._invalidate_preview()

    def _invalidate_preview(self, _value: int = 0) -> None:
        self._update_scope_summary()
        self.session = None
        self._applied_result = None
        self.apply_button.setEnabled(False)
        self.summary_label.setText("设置已变化，请重新分析优化。")
        diagnostics = [f"算法包：{item}" for item in self.discovery_diagnostics]
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
        self.details_button.setText("详细信息 ▾" if visible else "详细信息 ▸")
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
            self.summary_label.setText("请至少选择一条允许写入的轨道。")
            return
        self._set_analysis_busy(True)
        self.summary_label.setText("正在分析优化…")
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
        preview = session.preview
        self.summary_label.setText(
            f"{preview.summary or '分析完成'} · 修改操作 {len(preview.operations)}"
        )
        lines = list(preview.details)
        lines.extend(f"诊断：{item}" for item in preview.diagnostics)
        lines.extend(f"算法包：{item}" for item in self.discovery_diagnostics)
        if not lines:
            lines.append("当前输入没有需要应用的修改。")
        self.report_text.setPlainText("\n".join(lines))
        self.apply_button.setEnabled(bool(preview.operations))

    def _analysis_failed(self, message: str, traceback_text: str) -> None:
        append_crash_log("Optimizer plugin analysis failed", traceback_text)
        self.session = None
        self.summary_label.setText(f"分析失败：{message}")
        self.report_text.setPlainText(
            f"算法未应用任何修改。请检查算法包，或切换到 BDO 游戏安全优化。\n\n{message}"
        )
        self.apply_button.setEnabled(False)

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
        self.setWindowTitle("转换检查")
        self.resize(1000, 700)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("转换检查")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        subtitle = QLabel("先处理阻断项，再逐条确认预期变化；双击问题可定位。")
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

        report_label = QLabel("导出摘要")
        report_label.setObjectName("SectionLabel")
        layout.addWidget(report_label)
        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setMaximumHeight(140)
        layout.addWidget(self.report_view)

        issue_heading = QHBoxLayout()
        issue_label = QLabel("问题与预期变化")
        issue_label.setObjectName("SectionLabel")
        issue_heading.addWidget(issue_label)
        issue_hint = QLabel("严重问题优先显示")
        issue_hint.setObjectName("Muted")
        issue_heading.addWidget(issue_hint)
        issue_heading.addStretch(1)
        layout.addLayout(issue_heading)
        self.issue_list = QListWidget()
        self.issue_list.setToolTip("双击问题可定位到对应轨道和音符")
        self.issue_list.itemDoubleClicked.connect(self._focus_issue)
        layout.addWidget(self.issue_list, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.fix_btn = buttons.addButton("修复可自动处理项", QDialogButtonBox.ActionRole)
        self.fix_btn.clicked.connect(self._apply_fixes)
        copy_btn = buttons.addButton("复制报告", QDialogButtonBox.ActionRole)
        copy_btn.clicked.connect(self._copy_report)
        compare_btn = buttons.addButton("比较 BDO 乐谱", QDialogButtonBox.ActionRole)
        compare_btn.clicked.connect(self._compare_scores)
        coverage_btn = buttons.addButton("样本覆盖", QDialogButtonBox.ActionRole)
        coverage_btn.clicked.connect(self._show_sample_coverage)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self.report)

    def _apply_fixes(self) -> None:
        message = self.parent_window._apply_conversion_check_fixes()
        self._refresh()
        QMessageBox.information(self, "转换检查", message)

    def _focus_issue(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.UserRole)
        if isinstance(issue, ValidationIssue):
            self.parent_window._focus_validation_issue(issue)

    def _compare_scores(self) -> None:
        first_default = str(getattr(self.parent_window, "last_export_path", "") or self.parent_window.last_output_dir)
        first, _filter = QFileDialog.getOpenFileName(self, "选择基准 BDO 乐谱", first_default, "BDO 乐谱 (*);;所有文件 (*.*)")
        if not first:
            return
        second, _filter = QFileDialog.getOpenFileName(self, "选择对比 BDO 乐谱", str(Path(first).parent), "BDO 乐谱 (*);;所有文件 (*.*)")
        if not second:
            return
        try:
            result = compare_scores(read_bdo_score(Path(first)), read_bdo_score(Path(second)))
        except Exception as exc:
            QMessageBox.warning(self, "谱面对比失败", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("BDO 谱面对比")
        dialog.resize(860, 560)
        body = QVBoxLayout(dialog)
        header = QLabel(f"基准：{Path(first).name}\n对比：{Path(second).name}")
        header.setWordWrap(True)
        body.addWidget(header)
        report = QTextEdit()
        report.setReadOnly(True)
        report.setPlainText(result.summary())
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
            QMessageBox.warning(self, "样本覆盖检查失败", str(exc))
            return
        lines = ["当前工程的 Wwise 键位/力度层映射覆盖（不代表 DSP 已通过游戏 A/B）：", ""]
        for track, item in zip(active, coverage):
            lines.append(
                f"Track {track.track_id} · {track.display_name}: "
                f"{item.covered_notes}/{item.total_notes} · {item.status}"
            )
            if item.missing_note_indices:
                lines.append(f"  缺失音符索引: {list(item.missing_note_indices[:24])}")
        QMessageBox.information(self, "样本覆盖", "\n".join(lines))

    def _refresh(self) -> None:
        analysis = self.parent_window._analyze_conversion()
        self.report = analysis["report"]
        self.report_view.setPlainText(self.report)
        self.issue_list.clear()
        severity_labels = {"error": "需处理", "warning": "需人工确认", "info": "变化说明"}
        for issue in analysis["issues"]:
            location = f"Track {issue.track_id}" if issue.track_id is not None else "全局"
            item = QListWidgetItem(f"[{severity_labels[issue.severity]}] {location} · {issue.message}")
            item.setData(Qt.UserRole, issue)
            if issue.severity == "error":
                item.setForeground(QColor("#ef7772"))
            elif issue.severity == "warning":
                item.setForeground(QColor("#e2b968"))
            self.issue_list.addItem(item)
        if self.issue_list.count() == 0:
            item = QListWidgetItem("未发现阻断项或待确认变化")
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
        self.status_card.setText(trf("状态\n{status}", status=tr(status)))
        self.issue_card.setText(trf("问题\n{count}", count=issue_count))
        self.warning_card.setText(trf("人工确认\n{count}", count=warning_count))
        transpose = analysis.get("suggested_transpose")
        fix_text = trf("可自动修复\n{count} 项", count=fixable_count)
        if transpose is not None:
            fix_text += trf(" · 移调 {transpose:+d}", transpose=transpose)
        self.fix_card.setText(fix_text)
        self.fix_btn.setEnabled(fixable_count > 0)


class SettingsDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("设置")
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
        title = QLabel("设置")
        title.setObjectName("SettingsTitle")
        subtitle = QLabel("导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。")
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
        form.addRow("界面语言", self.language)

        self.char_name = QLineEdit(parent.char_name)
        form.addRow("写入角色名", self.char_name)

        self.bpm_override = QSpinBox()
        self.bpm_override.setRange(0, 240)
        self.bpm_override.setSpecialValueText("使用 MIDI")
        self.bpm_override.setValue(parent.bpm_override or 0)
        form.addRow("BPM 覆盖", self.bpm_override)

        self.transpose = QSpinBox()
        self.transpose.setRange(-48, 48)
        self.transpose.setSuffix(" 半音")
        self.transpose.setValue(parent.transpose)
        form.addRow("移调", self.transpose)

        owner, owner_layout = self._section(
            "游戏编辑权限",
            "选择一份游戏内保存的曲谱，读取角色名和 Owner ID。",
        )
        general_page_layout.addWidget(owner)
        self.owner_id = parent.owner_id
        owner_row = QHBoxLayout()
        self.owner_load_button = PillButton("从游戏曲谱读取", "secondary")
        self.owner_load_button.setFixedWidth(124)
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
        self.apply_sustain = QCheckBox("读取并展开 MIDI sustain 踏板")
        self.apply_sustain.setChecked(parent.apply_sustain)
        parsing_layout.addWidget(self.apply_sustain)

        self.flatten_tempo = QCheckBox("忽略中途 tempo 变化，按主 BPM 拉平")
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
            "layered": QRadioButton("分层"),
            "stepped": QRadioButton("阶梯"),
            "rescale": QRadioButton("重映射"),
            "floor": QRadioButton("抬底"),
            "off": QRadioButton("禁用"),
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
        step_row.addWidget(QLabel("底"))
        step_row.addWidget(self.vel_step_base)
        step_row.addWidget(QLabel("步长"))
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
        range_row.addWidget(QLabel("最小"))
        range_row.addWidget(self.vel_min)
        range_row.addWidget(QLabel("最大"))
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
        self.audio_source = QLineEdit(parent.audio_sources.get("sample_pack", ""))
        self.audio_source.setReadOnly(True)
        audio_source_row = QWidget()
        audio_source_layout = QHBoxLayout(audio_source_row)
        audio_source_layout.setContentsMargins(0, 0, 0, 0)
        audio_source_layout.setSpacing(10)
        audio_source_layout.addWidget(self.audio_source, stretch=1)
        sample_pack_button = PillButton("选择音源包", "secondary")
        sample_pack_button.clicked.connect(self._browse_sample_pack)
        audio_source_layout.addWidget(sample_pack_button)
        audio_layout.addWidget(audio_source_row)

        effects, effects_layout = self._section(
            "MIDI 效果",
            "数值范围为 0–127；设为 0 即不写入对应效果。",
        )
        effect_grid = QGridLayout()
        effect_grid.setContentsMargins(0, 0, 0, 0)
        effect_grid.setHorizontalSpacing(10)
        effect_grid.setVerticalSpacing(10)
        for column in (1, 3, 5):
            effect_grid.setColumnStretch(column, 1)
        effects_layout.addLayout(effect_grid)
        audio_page_layout.addWidget(effects)
        self.reverb = QSpinBox()
        self.reverb.setRange(0, 127)
        self.reverb.setValue(parent.reverb)
        self.delay = QSpinBox()
        self.delay.setRange(0, 127)
        self.delay.setValue(parent.delay)
        effect_grid.addWidget(QLabel("混响"), 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        effect_grid.addWidget(self.reverb, 0, 1)
        effect_grid.addWidget(QLabel("延迟"), 0, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        effect_grid.addWidget(self.delay, 0, 3)

        self.chorus_feedback = QSpinBox()
        self.chorus_feedback.setRange(0, 127)
        self.chorus_feedback.setValue(parent.chorus[0] if parent.chorus else 0)
        self.chorus_depth = QSpinBox()
        self.chorus_depth.setRange(0, 127)
        self.chorus_depth.setValue(parent.chorus[1] if parent.chorus else 0)
        self.chorus_freq = QSpinBox()
        self.chorus_freq.setRange(0, 127)
        self.chorus_freq.setValue(parent.chorus[2] if parent.chorus else 0)
        for column, label, field in (
            (0, "合唱反馈", self.chorus_feedback),
            (2, "深度", self.chorus_depth),
            (4, "频率", self.chorus_freq),
        ):
            effect_grid.addWidget(QLabel(label), 1, column, alignment=Qt.AlignRight | Qt.AlignVCenter)
            effect_grid.addWidget(field, 1, column + 1)
        for field in (self.reverb, self.delay, self.chorus_feedback, self.chorus_depth, self.chorus_freq):
            field.setFixedWidth(92)
        general_page_layout.addStretch(1)
        midi_page_layout.addStretch(1)
        audio_page_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.setObjectName("SettingsButtons")
        buttons.button(QDialogButtonBox.Ok).setText("保存设置")
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.settings_nav.currentRowChanged.connect(self._show_page_tip)
        self._sync_velocity_controls()

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
        title = QLabel(title_text)
        title.setObjectName("SettingsSectionTitle")
        detail = QLabel(description)
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
        label = QLabel(label_text)
        label.setObjectName("SettingsFieldLabel")
        label.setFixedWidth(84)
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
            show_global_toast(self, "轨道 FX 中的奏法会写入支持的 BDO 乐器。")

    def _browse_sample_pack(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, tr("选择本地音源包"), self.audio_source.text(), f"BDO Sample Pack (*{PACK_SUFFIX})"
        )
        if selected:
            self.audio_source.setText(selected)

    def _refresh_owner_status(self, error: str = "") -> None:
        if error:
            self.owner_status.setText(error)
            self.owner_status.setProperty("ownerError", True)
        elif self.owner_id:
            self.owner_status.setText(trf("已读取 Owner ID：0x{owner_id:08x}", owner_id=self.owner_id))
            self.owner_status.setProperty("ownerError", False)
        else:
            self.owner_status.setText("未读取 Owner ID；导出的曲谱无法在游戏内编辑。")
            self.owner_status.setProperty("ownerError", False)
        self.owner_status.style().unpolish(self.owner_status)
        self.owner_status.style().polish(self.owner_status)

    def _load_owner_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择游戏内保存的曲谱文件",
            str(default_game_music_dir()),
            "黑色沙漠曲谱文件 (*);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            snapshot = read_bdo_score(Path(path), allow_trailing_data=True)
            owner_id = int(snapshot.owner_id)
            char_name = snapshot.character_name_1 or snapshot.character_name_2
            if owner_id == 0:
                self._refresh_owner_status("未读取到有效 Owner ID，请选择游戏内保存的曲谱。")
                return
        except ValueError:
            self._refresh_owner_status("文件无法读取；请使用游戏内保存的曲谱。")
            return
        except Exception as exc:
            self._refresh_owner_status(f"读取失败：{exc}")
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
        self.language = str(self.config.get("language", "zh_CN"))
        self.owner_id = 0
        self.source_format = "midi"
        self.bdo_source_snapshot = None
        self.bdo_source_document = None
        self.tracks: list[TrackState] = []
        self.lyric_events: list[dict] = []
        self.reference_audio_path = ""
        self.selected_track: TrackState | None = None
        self.bpm = 120
        self.time_sig = 4
        self.tempo_changes = 1
        self.worker: ConvertWorker | None = None
        self.preview_generation = 0
        self.audio_sources = audio_source_config(self.config)
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
        self.last_output_dir = DEFAULT_OUTDIR
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
        self.project_undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.project_undo_shortcut.activated.connect(self._undo_project)
        self.project_redo_shortcut = QShortcut(QKeySequence.Redo, self)
        self.project_redo_shortcut.activated.connect(self._redo_project)
        self._apply_style()
        self._sync_preview_state()

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
        workspace_layout.addWidget(self._build_timeline_panel(), stretch=1)
        workspace_layout.addWidget(self._build_inspector())
        self.page_stack.addWidget(self.home_page)
        self.page_stack.addWidget(self.workspace_page)
        root.addWidget(self.page_stack, stretch=1)
        self._refresh_home()
        self._set_home_toolbar_mode(True)

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(7)

        command_group = QFrame()
        command_group.setObjectName("CommandGroup")
        command_layout = QHBoxLayout(command_group)
        command_layout.setContentsMargins(2, 2, 2, 2)
        command_layout.setSpacing(1)

        home_btn = PillButton("主页", "secondary", FluentSymbol.HOME)
        home_btn.clicked.connect(self._show_home)
        command_layout.addWidget(home_btn)

        self.toolbar_new_project_btn = PillButton("新建项目", "secondary", FluentSymbol.PROJECT)
        self.toolbar_new_project_btn.clicked.connect(self._new_project)
        command_layout.addWidget(self.toolbar_new_project_btn)

        self.toolbar_import_btn = PillButton("导入 MIDI", "primary", FluentSymbol.OPEN)
        self.toolbar_import_btn.clicked.connect(self._browse_midi)
        command_layout.addWidget(self.toolbar_import_btn)

        self.toolbar_open_project_btn = PillButton("打开工程", "secondary", FluentSymbol.PROJECT)
        self.toolbar_open_project_btn.clicked.connect(self._open_project)
        command_layout.addWidget(self.toolbar_open_project_btn)

        self.toolbar_optimize_btn = PillButton("全局优化", "secondary", FluentSymbol.OPTIMIZE)
        self.toolbar_optimize_btn.clicked.connect(lambda: self._open_midi_optimizer(None))
        command_layout.addWidget(self.toolbar_optimize_btn)
        layout.addWidget(command_group)

        self.workspace_toolbar_separator = QFrame()
        self.workspace_toolbar_separator.setObjectName("ToolbarSeparator")
        self.workspace_toolbar_separator.setFrameShape(QFrame.VLine)
        layout.addWidget(self.workspace_toolbar_separator)

        self.file_label = QLabel("未导入 MIDI")
        self.file_label.setObjectName("ToolbarText")
        layout.addWidget(self.file_label)
        layout.addStretch(1)

        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText("曲谱名")
        self.output_name.setFixedWidth(170)
        self.output_name.editingFinished.connect(lambda: self._autosave_project("output name"))
        layout.addWidget(self.output_name)

        self.preview_source_badge = QLabel("游戏映射：检测中")
        self.preview_source_badge.setObjectName("ToolbarBadge")
        layout.addWidget(self.preview_source_badge)

        separator = QFrame()
        separator.setObjectName("ToolbarSeparator")
        separator.setFrameShape(QFrame.VLine)
        layout.addWidget(separator)

        utility_group = QFrame()
        utility_group.setObjectName("CommandGroup")
        utility_layout = QHBoxLayout(utility_group)
        utility_layout.setContentsMargins(2, 2, 2, 2)
        utility_layout.setSpacing(1)

        thanks_btn = PillButton("致谢", "secondary", FluentSymbol.INFO)
        thanks_btn.clicked.connect(self._show_acknowledgements)
        utility_layout.addWidget(thanks_btn)

        settings_btn = PillButton("设置", "secondary", FluentSymbol.SETTINGS)
        settings_btn.clicked.connect(self._open_settings)
        utility_layout.addWidget(settings_btn)
        layout.addWidget(utility_group)

        self.convert_button = PillButton("转换", "convert", FluentSymbol.EXPORT)
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
        title = QLabel("曲谱主页")
        title.setObjectName("HomeTitle")
        heading.addWidget(eyebrow)
        heading.addWidget(title)
        header.addLayout(heading)
        header.addStretch(1)
        new_btn = PillButton("新建项目", "primary", FluentSymbol.PROJECT)
        new_btn.setProperty("homeAction", True)
        new_btn.clicked.connect(self._new_project)
        header.addWidget(new_btn)
        import_btn = PillButton("导入 MIDI", "primary", FluentSymbol.OPEN)
        import_btn.setProperty("homeAction", True)
        import_btn.clicked.connect(self._browse_midi)
        header.addWidget(import_btn)
        open_btn = PillButton("打开工程", "secondary", FluentSymbol.PROJECT)
        open_btn.setProperty("homeAction", True)
        open_btn.clicked.connect(self._open_project)
        header.addWidget(open_btn)
        refresh_btn = PillButton("刷新", "ghost")
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
        title_label = QLabel(title)
        title_label.setObjectName("HomeCardTitle")
        count_label = QLabel("0")
        count_label.setObjectName("HomeCount")
        count_label.setAlignment(Qt.AlignCenter)
        card_header.addWidget(title_label)
        card_header.addWidget(count_label)
        card_header.addStretch(1)
        item_list = QListWidget()
        item_list.setObjectName("HomeList")
        item_list.setSpacing(2)
        action_button = PillButton(action, "ghost")
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
        self.show_toast("双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。")

    def _show_workspace(self) -> None:
        self.page_stack.setCurrentWidget(self.workspace_page)
        self._set_home_toolbar_mode(False)

    def _reference_audio_changed(self, path: str) -> None:
        self.reference_audio_path = path
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio", immediate=True)
        self._sync_preview_state()

    def _reference_volume_changed(self, _volume: int) -> None:
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio volume")

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
            self._clear_track_selection()
            self.reference_audio.set_audio_path(None, notify=False)
            self.reference_audio.set_volume_percent(50, notify=False)
            self.reference_audio_path = ""
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
            instrument_id = gm_to_bdo_instrument_for_ui(0, False)
            instrument_name = BDO_INSTRUMENT_NAMES.get(instrument_id, tr("未知 BDO 乐器"))
            self.tracks = [
                TrackState(
                    track_id=0,
                    notes=[],
                    gm_program=0,
                    is_percussion=False,
                    display_name=trf("新建轨道 1 · {instrument}", instrument=instrument_name.rsplit("：", 1)[-1]),
                    bdo_instrument_id=instrument_id,
                    color=TRACK_COLORS[0],
                    effect_settings_placeholder={
                        "track_effects_enabled": False,
                        "note_effects_reserved": True,
                    },
                )
            ]
            self.file_label.setText(trf("{project} · 空白项目", project=project_name))
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
        if kind == "project" and path.is_file():
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
        title = QLabel("轨道")
        title.setObjectName("PanelTitle")
        self.track_summary = QLabel("导入 MIDI 后显示轨道")
        self.track_summary.setObjectName("Muted")
        clear_solo = PillButton("清除 Solo", "ghost")
        clear_solo.clicked.connect(self._clear_solo)
        unmute = PillButton("取消静音", "ghost")
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
        header.setContentsMargins(12, 6, 12, 6)
        header.setSpacing(6)
        self.timeline_meta = QLabel("等待 MIDI")
        self.timeline_meta.setObjectName("TimelineMeta")
        fit_btn = PillButton("Fit", "ghost", FluentSymbol.FIT)
        fit_btn.setToolTip(tr("显示全部时间轴"))
        fit_btn.clicked.connect(self._fit_timeline)
        zoom_label = QLabel(tr("缩放"))
        zoom_label.setObjectName("TimelineControlLabel")
        self.timeline_zoom = QSlider(Qt.Horizontal)
        self.timeline_zoom.setRange(100, 800)
        self.timeline_zoom.setValue(100)
        self.timeline_zoom.setFixedWidth(104)
        self.timeline_zoom.setToolTip(tr("时间轴缩放"))
        pan_label = QLabel(tr("位置"))
        pan_label.setObjectName("TimelineControlLabel")
        self.timeline_pan = QSlider(Qt.Horizontal)
        self.timeline_pan.setRange(0, 1000)
        self.timeline_pan.setValue(0)
        self.timeline_pan.setFixedWidth(112)
        self.timeline_pan.setToolTip(tr("时间轴位置"))
        transport_group = QFrame()
        transport_group.setObjectName("TransportGroup")
        transport_layout = QHBoxLayout(transport_group)
        transport_layout.setContentsMargins(2, 2, 2, 2)
        transport_layout.setSpacing(1)
        self.play_button = PillButton("播放", "secondary", FluentSymbol.PLAY)
        self.play_button.clicked.connect(self._play_preview)
        self.pause_button = PillButton("暂停", "secondary", FluentSymbol.PAUSE)
        self.pause_button.clicked.connect(self._pause_preview)
        self.stop_button = PillButton("停止", "secondary", FluentSymbol.STOP)
        self.stop_button.clicked.connect(lambda: self._stop_preview(reset_playhead=True))
        transport_layout.addWidget(self.play_button)
        transport_layout.addWidget(self.pause_button)
        transport_layout.addWidget(self.stop_button)
        self.add_track_button = PillButton("新建轨道", "secondary", FluentSymbol.ADD_TRACK)
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

        # Hidden extension host for the upcoming transcription tools. Keeping
        # it outside the transport and view groups avoids reworking the bar.
        self.transcription_tools_slot = QFrame()
        self.transcription_tools_slot.setObjectName("TranscriptionToolsSlot")
        self.transcription_tools_slot.setVisible(False)
        header.addWidget(self.transcription_tools_slot)

        header.addWidget(zoom_label)
        header.addWidget(self.timeline_zoom)
        header.addWidget(pan_label)
        header.addWidget(self.timeline_pan)
        header.addWidget(fit_btn)
        layout.addWidget(controls)
        self.timeline = TimelineCanvas()
        self.timeline.setObjectName("TimelineCanvas")
        self.timeline.changed.connect(self._on_track_changed)
        self.timeline.track_state_changed.connect(self._on_track_filter_changed)
        self.timeline.instrument_changed.connect(self._on_track_instrument_changed)
        self.timeline.selected.connect(self._select_track)
        self.timeline.effects_requested.connect(self._show_effects_placeholder)
        self.timeline.midi_tools_requested.connect(self._open_midi_tool)
        self.timeline.note_editor_requested.connect(self._open_note_editor)
        self.timeline.seek_requested.connect(self._seek_preview)
        self.timeline_zoom.valueChanged.connect(self.timeline.set_zoom_percent)
        self.timeline_pan.valueChanged.connect(self.timeline.set_pan_percent)
        layout.addWidget(self.timeline, stretch=1)
        self.reference_audio = ReferenceAudioController(self)
        self.reference_audio.file_changed.connect(self._reference_audio_changed)
        self.reference_audio.volume_changed.connect(self._reference_volume_changed)
        self.reference_audio.player.playbackStateChanged.connect(
            self._reference_playback_state_changed
        )
        self.timeline.set_reference_audio(self.reference_audio)
        return workspace

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Inspector")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(0)

        # Async code can keep writing status without reserving permanent UI.
        self.status_label = QLabel("就绪", panel)
        self.status_label.setObjectName("Status")
        self.status_label.hide()

        self.inspector_text = QLabel("", panel)
        self.inspector_text.setObjectName("InspectorText")
        self.inspector_text.hide()

        output_row = QHBoxLayout()
        output_row.setSpacing(7)
        volume_label = QLabel("轨道音量")
        volume_label.setObjectName("Muted")
        output_row.addWidget(volume_label)

        self.selected_volume = QSlider(Qt.Horizontal)
        self.selected_volume.setRange(0, 127)
        self.selected_volume.setValue(70)
        self.selected_volume.setFixedWidth(90)
        self.selected_volume.setEnabled(False)
        self.selected_volume.valueChanged.connect(self._update_selected_volume)
        output_row.addWidget(self.selected_volume)

        self.selected_volume_label = QLabel("70")
        self.selected_volume_label.setObjectName("Muted")
        self.selected_volume_label.setFixedWidth(38)
        output_row.addWidget(self.selected_volume_label)

        output_row.addStretch(1)

        output_label = QLabel(tr("输出"))
        output_label.setObjectName("Muted")
        output_row.addWidget(output_label)
        self.out_dir = QLineEdit(str(DEFAULT_OUTDIR))
        self.out_dir.setPlaceholderText(tr("输出目录"))
        self.out_dir.setMinimumWidth(220)
        self.out_dir.setMaximumWidth(360)
        output_row.addWidget(self.out_dir, stretch=1)

        self.open_output_button = PillButton("打开", "secondary")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_output_dir)
        output_row.addWidget(self.open_output_button)
        layout.addLayout(output_row)
        return panel

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
            QLabel#TimelineMeta {
                color: #9f9991;
                padding: 0 5px;
            }
            QLabel#TimelineControlLabel {
                color: #77716a;
                font-size: 10px;
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
            QFrame#EditorToolbar {
                background: #1d1d1b;
                border: 1px solid #3b3730;
                border-bottom: 2px solid #57401e;
                border-radius: 7px;
            }
            QLabel#EditorEyebrow {
                color: #c58e3b;
                font-size: 9px;
                font-weight: 900;
                letter-spacing: 1px;
            }
            QLabel#EditorTrackTitle {
                color: #f5f1e9;
                font-size: 17px;
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
                padding: 5px 7px;
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
                min-height: 27px;
                padding: 2px 7px;
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
            "选择 MIDI 文件",
            str(DEFAULT_MIDI_DIR),
            "MIDI 文件 (*.mid *.midi);;所有文件 (*.*)",
        )
        if path:
            self._open_midi_path(Path(path))

    def _open_midi_path(self, path: Path) -> None:
        self.reference_audio.set_audio_path(None, notify=False)
        self.reference_audio.set_volume_percent(50, notify=False)
        self.reference_audio_path = ""
        self.midi_path = str(path)
        self.autosave_project_dir = None
        self.autosave_source_copy = None
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
            "MIDI 已载入。建议先点“转换检查”，确认音域、FX 和打击乐映射后再导出。",
            kind="warning",
            duration_ms=4200,
        )

    def _open_bdo_score_path(self, path: Path) -> None:
        self.reference_audio.set_audio_path(None, notify=False)
        self.reference_audio.set_volume_percent(50, notify=False)
        self.reference_audio_path = ""
        if not self._load_bdo_info(path):
            return
        self.autosave_project_dir = None
        self.autosave_source_copy = None
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
                raise ValueError("BDO score does not contain an instrument track")
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
            "打开自动保存工程",
            start_dir,
            "工程文件 (project.json);;JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if path:
            self._load_project(Path(path))

    def _project_snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot.capture(self.tracks, self.reverb, self.delay, self.chorus)

    def _push_project_snapshot(self) -> None:
        self.project_commands.push(self._project_snapshot())

    def _restore_project_snapshot(self, snapshot: ProjectSnapshot, action: str) -> None:
        self._stop_preview(reset_playhead=False)
        self.tracks = snapshot.restored_tracks()
        self.reverb, self.delay, self.chorus = snapshot.reverb, snapshot.delay, snapshot.chorus
        self.selected_track = None
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
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
            QMessageBox.warning(self, "打开工程失败", f"无法读取工程文件：{exc}")
            return

        source_format = str(payload.get("source_format") or "midi")
        if source_format not in {"midi", "bdo", "project"}:
            source_format = "midi"
        source_path = Path(payload.get("source_midi_path") or "")
        original_path = Path(payload.get("original_midi_path") or "")
        midi_path = source_path if source_path.is_file() else original_path
        if source_format != "project" and not midi_path.is_file():
            QMessageBox.warning(self, "打开工程失败", "工程里的源文件和自动保存副本都不存在。")
            return

        self.loading_project = True
        try:
            self.reference_audio.set_audio_path(None, notify=False)
            self.reference_audio.set_volume_percent(
                int(payload.get("reference_audio_volume", 50)),
                notify=False,
            )
            self.reference_audio_path = ""
            self.autosave_project_dir = project_path.parent
            self.autosave_source_copy = source_path if source_path.is_file() else None
            self.midi_path = "" if source_format == "project" else str(midi_path)
            project_name = str(payload.get("output_name") or project_path.parent.name)
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
                            gm_to_bdo_instrument_for_ui(0, False),
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
            saved_reference_audio = str(payload.get("reference_audio_path") or "")
            if saved_reference_audio and self.reference_audio.set_audio_path(
                saved_reference_audio,
                notify=False,
            ):
                self.reference_audio_path = self.reference_audio.audio_path
            self._refresh_tracks()
            self.timeline.set_tracks(self.tracks)
            self._reset_timeline_position()
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
            payload = {
                "schema_version": CURRENT_PROJECT_SCHEMA,
                "saved_at": saved_at,
                "reason": reason,
                "source_format": self.source_format,
                "original_midi_path": str(Path(self.midi_path)) if self.midi_path else "",
                "source_midi_path": str(self.autosave_source_copy or ""),
                "output_name": self.output_name.text().strip(),
                "owner_id": self.owner_id,
                "char_name": self.char_name,
                "bpm": self.bpm,
                "time_sig": self.time_sig,
                "tempo_changes": self.tempo_changes,
                "lyric_events": [dict(event) for event in self.lyric_events],
                "reference_audio_path": self.reference_audio_path,
                "reference_audio_volume": self.reference_audio.volume_percent,
                "conversion_settings": self._conversion_settings_payload(),
                "tracks": [self._track_state_payload(track) for track in self.tracks],
                "research": dict(self.research_metadata),
            }
            project_path = self.autosave_project_dir / "project.json"
            tmp_path = project_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(project_path)
            with (self.autosave_project_dir / "autosave.log").open("a", encoding="utf-8") as file:
                file.write(f"[{saved_at}] {reason}\n")
        except Exception as exc:
            append_crash_log("Autosave failed", traceback.format_exc())
            self.status_label.setText(trf("自动保存失败：{error}", error=exc))

    def _mark_conversion_check_dirty(self) -> None:
        self.conversion_check_dirty = True
        if hasattr(self, "conversion_check_btn"):
            self.conversion_check_btn.setToolTip("建议先做一次转换检查，确认音域、FX 和打击乐映射")
            self.check_blink_ticks = 0
            self.check_blink_timer.start(360)

    def _clear_conversion_check_dirty(self) -> None:
        self.conversion_check_dirty = False
        if hasattr(self, "conversion_check_btn"):
            self.check_blink_timer.stop()
            self.conversion_check_btn.setToolTip("检查音域、FX 和打击乐映射")
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
            QMessageBox.information(self, "转换检查", "请先导入 MIDI。")
            return
        self._clear_conversion_check_dirty()
        dialog = ConversionCheckDialog(self)
        dialog.exec()

    def _open_midi_tool(self, request) -> None:
        if isinstance(request, TrackState):
            self._open_midi_optimizer(int(request.track_id))
        else:
            self._open_midi_optimizer(None)

    def _open_note_editor(self, track: TrackState, selected_note_indices: tuple[int, ...] = ()) -> None:
        if track not in self.tracks:
            return
        dialog = MidiNoteEditorDialog(
            self,
            track,
            self.bpm_override or self.bpm,
            self.time_sig,
            self.transpose,
        )
        if selected_note_indices:
            dialog.canvas.selected = {
                index for index in selected_note_indices if 0 <= index < len(dialog.canvas.notes)
            }
            dialog.canvas.update()
            dialog.refresh_fields()

        def apply_notes(notes) -> None:
            self._push_project_snapshot()
            self._stop_preview(reset_playhead=False)
            track.notes = list(notes)
            track.notes_optimized = False
            self.timeline.set_tracks(self.tracks)
            self._select_track(track)
            self._on_track_changed()
            self._mark_conversion_check_dirty()
            self._autosave_project("note edit", immediate=True)
            self.status_label.setText(trf("已更新 {track} · {count} 音符", track=track.display_name, count=len(track.notes)))
            self.show_toast(
                "音符编辑已写回；转换前建议运行一次转换检查。",
                kind="success",
            )

        dialog.notes_applied.connect(apply_notes)
        dialog.exec()

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
            QMessageBox.information(self, "MIDI 优化", "请先导入 MIDI。")
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
        scope = f"Track {target_track_id}" if target_track_id is not None else "全局 MIDI"
        self.status_label.setText(trf("{scope} 已优化", scope=tr(scope)))
        effect_text = "，并应用游戏声音效果建议" if optimized_effects is not None else ""
        self.show_toast(trf(
            "已应用 {scope} 优化{effects}：建议再运行一次转换检查后导出。",
            scope=tr(scope), effects=tr(effect_text) if effect_text else "",
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
        structured_report = issues_report(issues)
        report = (
            f"BDO Profile: {BDO_PROFILE.profile_id} · {BDO_PROFILE.evidence.status}\n"
            f"时间差比较容差: 0.001 ms\n\n{structured_report}"
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
            instrument_names=BDO_INSTRUMENT_NAMES,
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
        suggested_transpose = analysis.get("suggested_transpose")
        if suggested_transpose is not None:
            self.transpose = int(suggested_transpose)
            fixed.append(f"全局移调设为 {self.transpose:+d}")
        cleared_fx = 0
        for track in self.tracks:
            if track.articulation_type is None:
                continue
            supported = {ntype for ntype, _label in BDO_ARTICULATIONS.get(track.bdo_instrument_id, [])}
            if track.articulation_type not in supported:
                track.articulation_type = None
                cleared_fx += 1
        if cleared_fx:
            fixed.append(f"清空 {cleared_fx} 条无效 FX")
        if fixed:
            self._on_track_changed()
            if self.selected_track:
                self._select_track(self.selected_track)
            self._autosave_project("conversion check fix", immediate=True)
            self.status_label.setText(tr("转换检查已修复"))
            return "已修复：" + "；".join(fixed)
        return "没有可自动修复的项目。未知打击乐、样本音域和需要拆轨的情况仍需人工处理。"

    def _show_acknowledgements(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("致谢")
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
        title = QLabel("致谢")
        title.setObjectName("ThanksTitle")
        header_layout.addWidget(title)
        subtitle = QLabel("感谢以下项目、作者与社区。")
        subtitle.setObjectName("ThanksSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        text_panel = QFrame()
        text_panel.setObjectName("ThanksTextPanel")
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(18, 16, 18, 16)
        text_layout.setSpacing(9)

        text_title = QLabel("项目、作者与社区")
        text_title.setObjectName("ThanksSectionLabel")
        text_layout.addWidget(text_title)

        thanks_text = QTextEdit()
        thanks_text.setObjectName("ThanksText")
        thanks_text.setReadOnly(True)
        thanks_body_color = "#d8d3cc" if self._system_uses_dark_theme() else "#45413d"
        thanks_heading_color = "#f0c66f" if self._system_uses_dark_theme() else "#8a5a00"
        thanks_text.setHtml(
            f"""
            <style>
                body {{ color: {thanks_body_color}; font-family: "Microsoft YaHei UI"; font-size: 11px; }}
                h2 {{ color: {thanks_heading_color}; font-size: 17px; margin-top: 14px; margin-bottom: 6px; }}
                p {{ margin: 7px 0; line-height: 145%; }}
                b {{ color: {thanks_heading_color}; }}
            </style>
            <h2>{tr("格式研究与早期启发")}</h2>
            <p>• <b>Bishop-R / midi-to-bdo</b></p>
            <p>• <b>Skyro468 / BDO-Music-Composer-Stuff</b></p>
            <p>• <b>iDevelopThings / bdo-data-extractor</b></p>

            <h2>{tr("开源基础")}</h2>
            <p>• <b>mido</b></p>
            <p>• <b>PySide6 / Qt</b></p>

            <h2>{tr("采样、验证与协作")}</h2>
            <p>• <b>{tr("BDO 原始采样映射")}</b></p>
            <p>• <b>CN Server · Rainbow Club / 彩虹乐队</b></p>
            <p>• <b>ChatGPT / OpenAI</b></p>
            <p>• <b>{tr("开源维护者、文档作者、测试者与社区玩家")}</b></p>
            """
        )
        text_layout.addWidget(thanks_text, stretch=1)
        layout.addWidget(text_panel, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        copy_button = buttons.addButton("复制致谢名单", QDialogButtonBox.ActionRole)
        copy_button.setProperty("kind", "secondary")
        copy_button.setToolTip("复制为纯文本，便于放入项目说明或发布页面")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(thanks_text.toPlainText().strip())
        )
        buttons.button(QDialogButtonBox.Ok).setText("关闭")
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
            name = "Drums · Channel 10" if is_perc else gm_program_name(gm_prog)
            self.tracks.append(
                TrackState(
                    track_id=index,
                    notes=notes,
                    gm_program=gm_prog,
                    is_percussion=is_perc,
                    display_name=name,
                    bdo_instrument_id=gm_to_bdo_instrument_for_ui(gm_prog, is_perc),
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
        if hasattr(self, "selected_volume"):
            self.selected_volume.blockSignals(True)
            self.selected_volume.setEnabled(False)
            self.selected_volume.setValue(70)
            self.selected_volume.blockSignals(False)
        if hasattr(self, "selected_volume_label"):
            self.selected_volume_label.setText("70")

    def _refresh_tracks(self) -> None:
        self.timeline.set_tracks(self.tracks)
        self._on_track_changed()

    def _on_track_changed(self) -> None:
        self.timeline.set_conversion_transpose(self.transpose)
        self.timeline.update()
        if hasattr(self, "timeline_meta"):
            rail = tr(chr(0x8F68))
            dot = chr(0x00B7)
            self.timeline_meta.setText(
                f"{len(self.tracks)} {rail} {dot} BPM {self.bpm} {dot} {self.time_sig}/4"
            )
        if hasattr(self, "timeline_pan"):
            self.timeline_pan.blockSignals(True)
            self.timeline_pan.setValue(self.timeline.pan_percent())
            self.timeline_pan.setEnabled(self.timeline.zoom_factor > 1.0)
            self.timeline_pan.blockSignals(False)

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
        self._on_preview_mapping_changed()

    def _show_new_track_menu(self) -> None:
        if self.source_format != "project" and not getattr(self, "midi_path", None):
            QMessageBox.information(self, "新建轨道", "请先导入 MIDI 或打开一个工程。")
            return
        menu = QMenu(self)
        title = menu.addAction("选择新轨道的 BDO 乐器")
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, -1, BDO_INSTRUMENT_NAMES)
        selected = menu.exec(self.add_track_button.mapToGlobal(self.add_track_button.rect().bottomLeft()))
        if selected is None or selected.data() is None:
            return
        self._create_track(int(selected.data()))

    def _create_track(self, instrument_id: int) -> None:
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        track_id = max((int(track.track_id) for track in self.tracks), default=-1) + 1
        instrument_name = BDO_INSTRUMENT_NAMES.get(instrument_id, f"乐器 {instrument_id}")
        track = TrackState(
            track_id=track_id,
            notes=[],
            gm_program=0,
            is_percussion=instrument_id == 0x0D,
            display_name=f"新建轨道 {track_id + 1} · {instrument_name.rsplit('：', 1)[-1]}",
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
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("create track", immediate=True)
        self.status_label.setText(trf("已新建 Track {track_id} · {instrument}", track_id=track_id, instrument=instrument_name))
        self.show_toast("空轨道已创建；双击轨道可进入音符编辑器添加音符。", kind="success")

    def _delete_selected_track(self) -> None:
        track = self.selected_track
        if track is None or track not in self.tracks:
            QMessageBox.information(self, "删除轨道", "请先在时间轴中选择要删除的轨道。")
            return
        answer = QMessageBox.question(
            self,
            "删除轨道",
            f"确定删除“{track.display_name}”及其中的 {track.note_count} 个音符吗？\n此操作可通过自动保存工程恢复。",
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
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("delete track", immediate=True)
        self.status_label.setText(trf("已删除 {track}", track=track.display_name))
        self.inspector_text.clear()
        self.show_toast("轨道已删除。请选择其他轨道，或新建一条空轨道。")

    def _select_track(self, track: TrackState) -> None:
        self.selected_track = track
        self.timeline.set_selected_track(track)
        self.inspector_text.setText(trf(
            "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation}",
            track=track.display_name, count=track.note_count, pitch_range=track.pitch_range,
            instrument=BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, track.bdo_instrument_id),
            articulation=tr(articulation_label(track.bdo_instrument_id, track.articulation_type)),
        ))
        self.selected_volume.blockSignals(True)
        self.selected_volume.setEnabled(True)
        self.selected_volume.setValue(int(track.bdo_track_volume))
        self.selected_volume.blockSignals(False)
        self.selected_volume_label.setText(str(int(track.bdo_track_volume)))
        self.timeline.update()

    def _update_selected_volume(self, value: int) -> None:
        if not self.selected_track:
            return
        self.selected_track.bdo_track_volume = int(value)
        self.selected_volume_label.setText(str(value))
        self._on_preview_mapping_changed()

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
        track.marnian_synth_mode = (
            dialog.selected_marnian_synth_mode()
            if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
            else "basic"
        )
        self.show_toast(
            f"{track.display_name} · {track.marnian_synth_mode}",
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
        self.play_button.setText(tr("播放" if can_play else "无法原声试听"))
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
            return ["没有可试听轨道"]
        if not BDO_SAMPLE_MAP_PATH.is_file():
            return ["缺少解包后的 BDO Wwise 映射"]
        if not self.audio_sources.get("audio_root") or not Path(self.audio_sources["audio_root"]).is_dir():
            return [f"BDO 音源目录不可用：{self.audio_sources['audio_root']}"]
        try:
            standard_ids = [
                track.bdo_instrument_id for track in tracks
                if track.bdo_instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS
            ]
            if standard_ids and not sample_map_covers(BDO_SAMPLE_MAP_PATH, standard_ids):
                return ["存在未绑定已命名游戏 BNK 的乐器"]
            banks = json.loads(BDO_SAMPLE_MAP_PATH.read_text(encoding="utf-8")).get("banks", {})
            for track in tracks:
                if track.bdo_instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
                    continue
                bank = bank_for_instrument(track.bdo_instrument_id, track.marnian_synth_mode)
                if not bank or not any(row.get("wav_exists") for row in banks.get(bank, [])):
                    return [f"{track.display_name} 缺少 {track.marnian_synth_mode} synth WAV"]
        except Exception as exc:
            return [f"无法读取游戏采样映射：{exc}"]
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
            return ["没有可试听轨道"]
        if not BDO_SAMPLE_MAP_PATH.is_file():
            return ["缺少解包后的 BDO Wwise 映射"]
        try:
            if not sample_map_covers(BDO_SAMPLE_MAP_PATH, [track.bdo_instrument_id for track in tracks]):
                return ["存在未绑定游戏 BNK 的乐器"]
            blockers: list[str] = []
            if self.reverb or self.delay or self.chorus:
                blockers.append("轨道效果（混响、延迟或合唱）尚未由离线 Wwise 渲染器复现")
            for track in tracks:
                if track.is_percussion and track.bdo_instrument_id != 0x0D:
                    blockers.append(f"{track.display_name} 使用独立打击乐，尚无完整 GM 逐音映射")
                    continue
                if track.articulation_type not in (None, 0):
                    blockers.append(f"{track.display_name} 使用轨道奏法 type {track.articulation_type}")
                for note in track.notes:
                    ntype = int(getattr(note, "ntype", 0))
                    if ntype not in (0, 99):
                        blockers.append(f"{track.display_name} 含音符奏法 type {ntype}")
                        break
                    velocity = max(1, min(127, round(note.vel * track.volume_scale)))
                    if not sample_map_supports_note(
                        BDO_SAMPLE_MAP_PATH,
                        track.bdo_instrument_id,
                        note.pitch,
                        velocity,
                    ):
                        blockers.append(f"{track.display_name} 含无对应游戏音源的键位或力度")
                        break
            return list(dict.fromkeys(blockers))
        except Exception as exc:
            return [f"无法读取游戏采样映射：{exc}"]

    def _stop_bdo_audio(self) -> None:
        # Kept as a compatibility shim for callers that previously stopped the
        # temporary-file preview player.
        if self.realtime_preview_active:
            try:
                self.realtime_audio.stop()
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
        tracks = selected_tracks(self.tracks)
        if not tracks:
            QMessageBox.warning(self, "没有可试听轨道", "当前没有可试听轨道，请取消静音或 Solo。")
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
                "无法原声试听",
                "当前工程缺少可用的实时游戏音源：\n- "
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
        if start_ms >= self.reference_audio.duration_ms - 1:
            start_ms = 0.0
            self.timeline.set_playhead(0.0)
        self.reference_audio.set_position(start_ms)
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
        drift = abs(float(self.reference_audio.player.position()) - position_ms)
        if force or (
            not self.reference_audio.is_playing
            and drift >= REFERENCE_AUDIO_RESYNC_THRESHOLD_MS
            and now - self.reference_last_resync_at >= REFERENCE_AUDIO_RESYNC_COOLDOWN_S
        ):
            self.reference_audio.set_position(position_ms)
            self.reference_last_resync_at = now
        if (
            play
            and not self.reference_audio.is_playing
            and position_ms < self.reference_audio.duration_ms
        ):
            self.reference_audio.play()
        elif not play and self.reference_audio.is_playing:
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
        QMessageBox.warning(self, "试听不可用", message)

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
        position = float(self.reference_audio.player.position())
        self.timeline.set_playhead(position, follow=True)
        if (
            self.reference_audio.duration_ms > 0
            and position >= self.reference_audio.duration_ms - 1
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

    def _open_settings(self) -> None:
        old_parse_settings = (self.apply_sustain, self.flatten_tempo)
        dialog = SettingsDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        selected_audio_source = dialog.audio_source.text().strip()
        sample_pack = ""
        audio_root = ""
        if selected_audio_source.lower().endswith(PACK_SUFFIX):
            sample_pack = selected_audio_source
            try:
                audio_root = str(extract_sample_pack(Path(sample_pack), SAMPLE_PACK_CACHE_DIR))
            except (OSError, SamplePackError) as exc:
                QMessageBox.warning(self, tr("音源包不可用"), str(exc))
                return
        elif selected_audio_source:
            QMessageBox.warning(self, tr("音源包不可用"), selected_audio_source)
            return

        self.char_name = dialog.char_name.text().strip() or "MIDI"
        self.language = str(dialog.language.currentData() or "zh_CN")
        self.owner_id = dialog.owner_id
        self.bpm_override = dialog.bpm_override.value() or None
        self.transpose = dialog.transpose.value()
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

        self.reverb = dialog.reverb.value()
        self.delay = dialog.delay.value()
        self.chorus = None
        if dialog.chorus_feedback.value() or dialog.chorus_depth.value() or dialog.chorus_freq.value():
            self.chorus = (
                dialog.chorus_feedback.value(),
                dialog.chorus_depth.value(),
                dialog.chorus_freq.value(),
            )

        self.audio_sources["sample_pack"] = sample_pack
        self.audio_sources["audio_root"] = audio_root
        self.realtime_audio.source_config = dict(self.audio_sources)
        self.config["audio_sources"] = dict(self.audio_sources)

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
        self._refresh_home()

        if (
            self.source_format == "midi"
            and getattr(self, "midi_path", None)
            and old_parse_settings != (self.apply_sustain, self.flatten_tempo)
        ):
            self._load_midi_info(self.midi_path)
        self.inspector_text.setText(
            f"转换设置：力度 {self.velocity_mode} · 移调 {self.transpose:+d} · "
            f"BPM {self.bpm_override or 'MIDI'} · 踏板 {'开' if self.apply_sustain else '关'}"
        )
        self._autosave_project("settings")

    def _build_params(self) -> dict:
        midi_path = getattr(self, "midi_path", "")
        if self.source_format != "project" and (not midi_path or not Path(midi_path).is_file()):
            raise ValueError("请选择有效的 MIDI 文件")
        active = selected_tracks(self.tracks)
        if not active:
            raise ValueError("没有可导出的轨道，请取消静音或 Solo 至少一条轨道")
        if not self.owner_id:
            raise ValueError("尚未读取有效 Owner ID。请在设置中选择一份游戏内保存的曲谱，否则导出文件无法在游戏内正常编辑。")
        denominator = (
            4
            if self.source_format in {"bdo", "project"}
            else source_time_signature_denominator(midi_path)
        )
        if denominator != 4:
            raise ValueError(
                f"当前 MIDI 拍号分母为 /{denominator}，但 BDO v9 曲谱只保存 /4 拍号。"
                "请先在 MIDI 软件中转换为等价的 /4 拍号后再导出，程序不会静默写入错误拍号。"
            )

        out_dir = Path(self.out_dir.text().strip() or DEFAULT_OUTDIR)
        out_name = self.output_name.text().strip() or (Path(midi_path).stem if midi_path else tr("未命名项目"))
        if any(ch in out_name for ch in '<>:"/\\|?*'):
            raise ValueError("曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*")
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
            settings = list(track.bdo_track_settings if len(track.bdo_track_settings) == 8 else (0,) * 8)
            settings[1] = int(self.reverb)
            settings[3] = int(self.delay)
            chorus = self.chorus or (0, 0, 0)
            settings[5:8] = [int(value) for value in chorus]
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
                "导出已阻止",
                f"转换检查仍有 {analysis['issue_count']} 项必须处理的问题。请先打开转换检查定位并修复。",
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
                "确认导出变化",
                f"检查发现 {len(confirmable)} 项需要确认的近似结果或预期变化。\n"
                "这些项目已在转换检查中列出。确认继续导出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            params = self._build_params()
        except Exception as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
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
        self.open_output_button.setEnabled(True)
        self.status_label.setText(tr("转换完成"))
        summary = dict(summary)
        extra = tr(" · 已复制到游戏目录") if installed else ""
        roundtrip_text = ""
        roundtrip_failed = False
        try:
            snapshot = read_bdo_score(Path(out_path))
            if snapshot.total_notes != int(summary["total_notes"]):
                raise ValueError(
                    f"回读音符数 {snapshot.total_notes} 与导出摘要 {summary['total_notes']} 不一致"
                )
            roundtrip_text = tr(" · BDO v9 结构回读通过")
        except Exception as exc:
            roundtrip_failed = True
            append_crash_log("Export round-trip verification failed", traceback.format_exc())
            roundtrip_text = trf(" · 回读检查失败：{error}", error=exc)
            self.status_label.setText(tr("转换完成（回读检查失败）"))
        result_text = trf(
            "已保存 {file} · {bytes} bytes · {instruments} 乐器 · {tracks} 轨 · {notes} 音符{extra}",
            file=Path(out_path).name, bytes=byte_count, instruments=summary["instruments"],
            tracks=summary["tracks"], notes=summary["total_notes"], extra=extra + roundtrip_text,
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
        append_crash_log("Convert failed", message)
        log_path = DEFAULT_OUTDIR / "last_convert_error.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(message, encoding="utf-8")
        except Exception:
            log_path = None
        brief = message.splitlines()[0] if message else "未知错误"
        detail = f"\n\n详细错误已写入：{log_path}" if log_path else ""
        QMessageBox.critical(self, "转换失败", f"{brief}{detail}")
        self.worker = None

    def _open_output_dir(self) -> None:
        self.last_output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.last_output_dir)

    def closeEvent(self, event) -> None:
        self.autosave_timer.stop()
        self._flush_autosave()
        self.reference_audio.set_audio_path(None, notify=False)
        self._stop_preview()
        self.realtime_audio.stop()
        super().closeEvent(event)


def main() -> int:
    install_crash_logging()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "OpenAI.BDOMusicComposer.1"
            )
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    install_localizer(app, str(load_config().get("language", "zh_CN")))
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
                "双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。"
            ),
        )
        result = app.exec()
        append_crash_log("Application exited", f"exit_code={result}")
        return result
    except BaseException as exc:
        startup.hide()
        append_crash_log("Fatal error in main()", f"{exc}\n\n{traceback.format_exc()}")
        QMessageBox.critical(None, "程序错误", f"程序发生错误，日志已写入：\n{CRASH_LOG_PATH}\n\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
