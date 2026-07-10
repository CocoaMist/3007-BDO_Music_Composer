#!/usr/bin/env python3
"""GarageBand-style PySide6 MIDI workspace for BDO music conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from project_paths import ASSETS_DIR, WWISE_MIDI_MAP_PATH
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"
DEFAULT_OUTDIR = ROOT / "out" / "bdo"
DEFAULT_MIDI_DIR = ROOT / "samples"
CONFIG_PATH = ROOT / ".pyside_bdo_gui.json"
AUTO_SAVE_DIR = ROOT / "auto_save"
BDO_SAMPLE_MAP_PATH = WWISE_MIDI_MAP_PATH
AUDIO_VALIDATION_PATH = DEFAULT_OUTDIR / "bdo_audio_validation_matrix.json"
CRASH_LOG_PATH = DEFAULT_OUTDIR / "crash.log"
TIMELINE_BACKGROUND_IMAGE = ASSETS_DIR / "ui" / "timeline_background.png"
TIMELINE_BACKGROUND_OPACITY = 0.24
DEFAULT_AUDIO_SOURCES = {
    "paz_root": r"F:\缓存\Paz",
    "audio_root": r"F:\缓存\BDO音源",
}

sys.path.insert(0, str(TOOL_DIR))


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
    from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPushButton,
        QRadioButton,
        QScrollArea,
        QScrollBar,
        QSlider,
        QSpinBox,
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

from midi2bdo import (  # noqa: E402
    BDO_INSTRUMENT_NAMES,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    MAX_NOTES_PER_INSTRUMENT,
    Note,
    _GM_TO_BDO_DRUM,
    channel_groups_to_bdo,
    extract_owner_id,
    gm_program_name,
    gm_to_bdo_instrument,
    midi_to_bdo,
    parse_midi,
)
from bdo_midi_optimizer import OptimizerConfig, optimize_tracks  # noqa: E402
from bdo_sample_renderer import (  # noqa: E402
    sample_map_covers,
    sample_map_supported_pitches,
    sample_map_supports_note,
)
from bdo_realtime_audio import AudioEngineError, BdoRealtimeAudioEngine, bank_for_instrument  # noqa: E402


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
    26: "#5b90c9",  # SusPiano / light
    27: "#d9ae59",  # SusMezzoForte / medium
    28: "#d96658",  # SusForte / strong
}

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
    """More detailed UI-side GM to BDO mapping; does not alter midi-to-bdo."""
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
    notes_optimized: bool = False

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


def note_name(midi_note: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = midi_note // 12 - 1
    return f"{names[midi_note % 12]}{octave}"


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


def latest_autosave_project() -> Path | None:
    if not AUTO_SAVE_DIR.is_dir():
        return None
    projects = [path for path in AUTO_SAVE_DIR.glob("*/project.json") if path.is_file()]
    if not projects:
        return None
    return max(projects, key=lambda path: path.stat().st_mtime)


def selected_tracks(tracks: list[TrackState]) -> list[TrackState]:
    solo_tracks = [track for track in tracks if track.solo]
    return solo_tracks if solo_tracks else [track for track in tracks if not track.muted]


def build_filtered_midi(tracks: list[TrackState], bpm: int, time_sig: int, out_path: Path) -> None:
    mid = mido.MidiFile(ticks_per_beat=480)
    tempo = mido.bpm2tempo(max(1, min(240, bpm or 120)))
    numerator = max(1, min(32, int(time_sig or 4)))
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=numerator, denominator=4, time=0))
    meta.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(meta)

    def ms_to_ticks(ms: float) -> int:
        return max(0, round(mido.second2tick(ms / 1000.0, mid.ticks_per_beat, tempo)))

    for out_index, track_state in enumerate(tracks):
        channel = 9 if track_state.is_percussion else min(out_index, 8)
        events: list[tuple[int, int, object]] = []
        if not track_state.is_percussion:
            events.append((0, 0, mido.Message("program_change", channel=channel, program=track_state.gm_program)))
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
    def __init__(self, text: str, kind: str = "secondary") -> None:
        super().__init__(text)
        self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)


class ThanksShareSquare(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ThanksShareSquare")
        self.setFixedSize(280, 280)
        self.items = [
            ("游戏采样映射", 48, "#9fc79a"),
            ("midi-to-bdo", 22, "#82aa9b"),
            ("BDO 解码资料", 14, "#779a73"),
            ("mido", 8, "#b0cfaa"),
            ("PySide6", 4, "#66845f"),
            ("ChatGPT", 4, "#c0d8bb"),
        ]
        self.labels: list[QLabel] = []
        for name, percent, color in self.items:
            label = QLabel(f"{name}\n{percent}%", self)
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            label.setStyleSheet(
                f"background: {color}; color: #102010; border: 1px solid #182018; "
                'border-radius: 5px; font-family: "Microsoft YaHei UI"; '
                "font-size: 10px; font-weight: 800; padding: 4px;"
            )
            self.labels.append(label)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        side = min(self.width(), self.height())
        chart = QRectF((self.width() - side) / 2 + 8, (self.height() - side) / 2 + 8, side - 16, side - 16)
        gap = 5
        left_w = chart.width() * 0.58
        right_w = chart.width() - left_w - gap
        left_x = chart.left()
        right_x = left_x + left_w + gap
        left_top_h = chart.height() * 0.68
        right_row_h = (chart.height() - gap * 3) / 4

        rects = [
            QRectF(left_x, chart.top(), left_w, left_top_h),
            QRectF(left_x, chart.top() + left_top_h + gap, left_w, chart.height() - left_top_h - gap),
            QRectF(right_x, chart.top(), right_w, right_row_h),
            QRectF(right_x, chart.top() + (right_row_h + gap), right_w, right_row_h),
            QRectF(right_x, chart.top() + (right_row_h + gap) * 2, right_w, right_row_h),
            QRectF(right_x, chart.top() + (right_row_h + gap) * 3, right_w, right_row_h),
        ]
        for label, rect in zip(self.labels, rects):
            label.setGeometry(int(rect.left()), int(rect.top()), int(rect.width()), int(rect.height()))


class TimelineCanvas(QWidget):
    changed = Signal()
    track_state_changed = Signal()
    instrument_changed = Signal(object)
    selected = Signal(object)
    effects_requested = Signal(object)
    midi_tools_requested = Signal(str)
    seek_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.tracks: list[TrackState] = []
        self.hit_regions: list[tuple[QRectF, str, TrackState]] = []
        self.zoom_factor = 1.0
        self.view_start_ms = 0.0
        self.playhead_ms = 0.0
        self.grid_rect = QRectF()
        self.dragging_timeline = False
        self.last_drag_x = 0.0
        self.selected_track: TrackState | None = None
        self.conversion_transpose = 0
        self.background_pixmap = QPixmap(str(TIMELINE_BACKGROUND_IMAGE)) if TIMELINE_BACKGROUND_IMAGE.is_file() else QPixmap()
        self.track_scroll = QScrollBar(Qt.Vertical, self)
        self.track_scroll.setObjectName("TimelineScroll")
        self.track_scroll.valueChanged.connect(self.update)
        self.setMinimumHeight(380)

    def set_tracks(self, tracks: list[TrackState]) -> None:
        self.tracks = tracks
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self.setMinimumHeight(380)
        self._update_track_scrollbar()
        self.update()

    def set_selected_track(self, track: TrackState | None) -> None:
        self.selected_track = track
        self.update()

    def set_conversion_transpose(self, semitones: int) -> None:
        self.conversion_transpose = int(semitones)

    def _note_has_conversion_problem(self, track: TrackState, pitch: int) -> bool:
        if track.bdo_instrument_id == 0x0d:
            mapped_pitch = _GM_TO_BDO_DRUM.get(pitch)
            if mapped_pitch is None or mapped_pitch < BDO_DRUM_MIN or mapped_pitch > BDO_DRUM_MAX:
                return True
            supported = game_supported_pitches(track.bdo_instrument_id)
            return supported is not None and mapped_pitch not in supported
        converted_pitch = pitch + self.conversion_transpose
        supported = game_supported_pitches(track.bdo_instrument_id)
        if supported is not None:
            return converted_pitch not in supported
        return converted_pitch < BDO_NOTE_MIN or converted_pitch > BDO_NOTE_MAX

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_track_scrollbar()

    def _lane_height(self) -> int:
        return 58

    def _timeline_layout_metrics(self) -> tuple[QRectF, int, int, int]:
        area = self.rect().adjusted(14, 12, -14, -14)
        header_w = 286
        ruler_h = 34
        lane_h = self._lane_height()
        return area, header_w, ruler_h, lane_h

    def _update_track_scrollbar(self) -> None:
        if not hasattr(self, "track_scroll"):
            return
        area, _header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        grid_top = area.top() + ruler_h
        grid_h = max(80, area.bottom() - grid_top)
        content_h = lane_h * len(self.tracks)
        max_scroll = max(0, content_h - grid_h)
        self.track_scroll.setGeometry(int(area.right() - 10), int(grid_top), 10, int(grid_h))
        self.track_scroll.setRange(0, int(max_scroll))
        self.track_scroll.setPageStep(int(grid_h))
        self.track_scroll.setSingleStep(lane_h)
        self.track_scroll.setVisible(max_scroll > 0)

    def set_playhead(self, ms: float, follow: bool = False) -> None:
        self.playhead_ms = max(0.0, min(float(ms), self._timeline_end_ms()))
        if follow:
            visible_duration = self._visible_duration_ms()
            if self.playhead_ms < self.view_start_ms or self.playhead_ms > self.view_start_ms + visible_duration * 0.92:
                self.view_start_ms = self.playhead_ms - visible_duration * 0.18
                self._clamp_view()
        self.update()

    def set_zoom_percent(self, value: int) -> None:
        old_duration = self._visible_duration_ms()
        center = self.view_start_ms + old_duration / 2
        self.zoom_factor = max(1.0, min(8.0, value / 100.0))
        self.view_start_ms = center - self._visible_duration_ms() / 2
        self._clamp_view()
        self.update()
        self.changed.emit()

    def set_pan_percent(self, value: int) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        self.view_start_ms = max_start * max(0, min(1000, value)) / 1000.0
        self._clamp_view()
        self.update()
        self.changed.emit()

    def pan_percent(self) -> int:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        if max_start <= 0:
            return 0
        return round(self.view_start_ms / max_start * 1000)

    def _timeline_end_ms(self) -> float:
        return max((track.end_ms for track in self.tracks), default=1.0) or 1.0

    def _visible_duration_ms(self) -> float:
        return max(1.0, self._timeline_end_ms() / self.zoom_factor)

    def _clamp_view(self) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        self.view_start_ms = max(0.0, min(self.view_start_ms, max_start))

    def _paint_canvas_background(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor("#141615"))
        if self.background_pixmap.isNull():
            return
        target = QRectF(self.rect())
        scaled = self.background_pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) / 2
        y = (self.height() - scaled.height()) / 2
        painter.save()
        painter.setOpacity(TIMELINE_BACKGROUND_OPACITY)
        painter.drawPixmap(int(x), int(y), scaled)
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
        tracks_clip: QRectF,
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
        painter.save()
        painter.setClipRect(tracks_clip)
        for row, track in enumerate(self.tracks):
            y = grid_top + row * lane_h - scroll_y
            if y + lane_h < grid_top or y > grid_top + grid_h:
                continue
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

            button_y = y + 8
            for label, action, bx in (
                ("-", "shorten", left + header_w - 170),
                ("+", "lengthen", left + header_w - 138),
                ("M", "mute", left + header_w - 104),
                ("S", "solo", left + header_w - 70),
                ("FX", "fx", left + header_w - 36),
            ):
                rect = QRectF(bx, button_y, 28, 24)
                if action == "fx":
                    rect = QRectF(bx - 2, button_y, 32, 24)
                checked = (action == "mute" and track.muted) or (action == "solo" and track.solo)
                painter.fillRect(rect, QColor("#5d451e" if checked else "#2b2b2b"))
                painter.setPen(QPen(QColor("#d9a441" if checked else "#484848"), 1))
                painter.drawRect(rect)
                painter.setPen(QColor("#f3f1ea" if active else "#8a847d"))
                painter.drawText(rect, Qt.AlignCenter, label)
                self.hit_regions.append((rect, action, track))
            painter.save()
            small_font = painter.font()
            small_font.setPointSize(max(7, small_font.pointSize() - 2))
            painter.setFont(small_font)
            painter.setPen(QColor("#8f8981" if active else "#5f5a54"))
            painter.drawText(
                QRectF(left + header_w - 78, y + lane_h - 22, 68, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                f"{round(track.duration_scale * 100)}%",
            )
            painter.restore()

            accent = QColor(track.color)
            accent.setAlpha(230 if active else 75)
            region_rect = QRectF(grid_left + 12, y + 12, grid_w - 24, lane_h - 24)
            region_bg = QColor(track.color)
            region_bg.setAlpha(42 if active else 16)
            painter.setBrush(region_bg)
            painter.setPen(QPen(QColor(track.color), 1))
            painter.drawRect(region_rect)

            if track.notes:
                pitch_min = min(note.pitch for note in track.notes)
                pitch_max = max(note.pitch for note in track.notes)
                pitch_span = max(1, pitch_max - pitch_min)
                painter.save()
                painter.setClipRect(region_rect)
                for note in track.notes[:2600]:
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
                        painter.setBrush(QColor("#d94a4a"))
                        painter.setPen(QPen(QColor("#ffb1a8"), 1))
                    else:
                        dynamic_color = BDO_DYNAMIC_ARTICULATION_COLORS.get(
                            int(getattr(note, "ntype", 0))
                        )
                        painter.setBrush(QColor(dynamic_color) if dynamic_color else accent)
                        painter.setPen(Qt.NoPen)
                    painter.drawRect(note_rect)
                painter.restore()

            painter.setPen(QColor("#f3f1ea" if active else "#8a847d"))
            painter.drawText(left + 12, y + 22, track.display_name[:18])
            painter.setPen(QColor("#a8a29e" if active else "#69645f"))
            inst_name = BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, "未知 BDO 乐器")
            painter.drawText(
                left + 12,
                y + 43,
                f"{inst_name} · {track.note_count} 音符 · {track.pitch_range}",
            )
        painter.restore()

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
        painter.drawText(left + 10, top + 22, "Tracks")
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
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_canvas_background(painter)
        self.hit_regions = []

        self._update_track_scrollbar()
        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        if not self.tracks:
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
        tracks_clip = QRectF(left, grid_top, header_w + grid_w, grid_h)
        bars = self._paint_grid_ruler(
            painter, left, top, grid_left, grid_top, grid_w, grid_h, visible_start, visible_duration
        )
        play_x = self._paint_playhead(
            painter, top, grid_left, grid_top, grid_w, grid_h,
            visible_start, visible_duration, visible_end, grid_h
        )
        self._paint_track_rows(
            painter, tracks_clip, left, grid_left, grid_top, header_w, grid_w, grid_h,
            lane_h, visible_start, visible_duration, visible_end
        )
        self._paint_ruler_overlay(
            painter, area, left, top, grid_left, grid_top, grid_w, grid_h,
            ruler_h, bars, visible_start, visible_duration, play_x
        )

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() == Qt.RightButton:
            for rect, _action, track in reversed(self.hit_regions):
                if rect.contains(pos):
                    self.selected_track = track
                    self.selected.emit(track)
                    self._show_instrument_menu(track, event.globalPosition().toPoint())
                    self.update()
                    return
            super().mousePressEvent(event)
            return
        for rect, action, track in reversed(self.hit_regions):
            if rect.contains(pos):
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
                elif action == "shorten":
                    track.duration_scale = max(0.25, round((track.duration_scale - 0.05) * 100) / 100)
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "lengthen":
                    track.duration_scale = min(2.0, round((track.duration_scale + 0.05) * 100) / 100)
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
        optimize_action = menu.addAction("修复和优化的轨道")
        menu.addSeparator()
        current_id = track.bdo_instrument_id
        title = menu.addAction("更换乐器")
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, current_id, BDO_INSTRUMENT_NAMES)
        selected = menu.exec(global_pos)
        if selected is None:
            return
        if selected is optimize_action:
            self.midi_tools_requested.emit("optimize")
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == track.bdo_instrument_id:
            return
        track.bdo_instrument_id = int(inst_id)
        self.changed.emit()
        self.instrument_changed.emit(track)
        self.update()

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
    midi_tools_requested = Signal(str)

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
        top.addWidget(self.mute_btn)

        self.solo_btn = PillButton("S")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedWidth(30)
        self.solo_btn.clicked.connect(self._update_solo)
        top.addWidget(self.solo_btn)

        fx = PillButton("FX")
        fx.setFixedWidth(34)
        fx.clicked.connect(lambda: self.effects_requested.emit(self.track))
        top.addWidget(fx)

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
        optimize_action = menu.addAction("修复和优化的轨道")
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
            self.midi_tools_requested.emit("optimize")
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
                    idx: track.bdo_instrument_id
                    for idx, track in enumerate(direct_tracks)
                }
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

            installed_path = ""
            if params["install"]:
                game_dir = Path(params["game_dir"])
                game_dir.mkdir(parents=True, exist_ok=True)
                installed = game_dir / out_path.name
                shutil.copy2(out_path, installed)
                installed_path = str(installed)

            self.conversion_finished.emit(str(out_path), len(bdo_data), summary, installed_path)
        except BaseException as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
        finally:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass


class TrackFxDialog(QDialog):
    def __init__(self, parent: QWidget, track: TrackState) -> None:
        super().__init__(parent)
        self.setWindowTitle("轨道 FX")
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

        self.articulation = QComboBox()
        self.articulation.addItem("默认", None)
        self.articulation.setItemData(0, articulation_usage_hint(None), Qt.ToolTipRole)
        for ntype, label in BDO_ARTICULATIONS.get(track.bdo_instrument_id, []):
            self.articulation.addItem(f"{label} (type {ntype})", ntype)
            self.articulation.setItemData(
                self.articulation.count() - 1,
                articulation_usage_hint(ntype),
                Qt.ToolTipRole,
            )
        current_index = self.articulation.findData(track.articulation_type)
        self.articulation.setCurrentIndex(current_index if current_index >= 0 else 0)
        self.articulation.setEnabled(bool(BDO_ARTICULATIONS.get(track.bdo_instrument_id)))
        form.addRow("奏法", self.articulation)

        is_marnian = track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
        self.marnian_mode: QComboBox | None = None
        if is_marnian:
            self.marnian_mode = QComboBox()
            for label, value in MARNIAN_SYNTH_MODES:
                self.marnian_mode.addItem(label, value)
            mode_index = self.marnian_mode.findData(track.marnian_synth_mode)
            self.marnian_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            form.addRow("玛勒尼斯音源", self.marnian_mode)

        if not BDO_ARTICULATIONS.get(track.bdo_instrument_id):
            self.articulation_hint = QLabel("当前乐器暂未收录奏法。")
        else:
            self.articulation_hint = QLabel("")
        self.articulation_hint.setWordWrap(True)
        self.articulation_hint.setObjectName("Muted")
        layout.addWidget(self.articulation_hint)
        if is_marnian:
            mode_hint = QLabel(
                "游戏轨道下拉框的默认值为 Basic。该模式独立于上方的音符奏法；"
                "当前工程会保存此选择，非 Basic 的 BDO 序列化位置仍待游戏存档差分确认。"
            )
            mode_hint.setWordWrap(True)
            mode_hint.setObjectName("Muted")
            layout.addWidget(mode_hint)
        self.articulation.currentIndexChanged.connect(self._update_articulation_hint)
        self._update_articulation_hint()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_articulation(self) -> int | None:
        return self.articulation.currentData()

    def selected_marnian_synth_mode(self) -> str:
        if self.marnian_mode is None:
            return "basic"
        return str(self.marnian_mode.currentData() or "basic")

    def _update_articulation_hint(self) -> None:
        if not self.articulation.isEnabled():
            return
        ntype = self.articulation.currentData()
        self.articulation_hint.setText(
            f"{articulation_usage_hint(ntype)} 此设置会把该轨导出为同一种 BDO 奏法。"
        )


class MidiOptimizeDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.optimization_result = None
        self.setWindowTitle("修复和优化的轨道")
        self.resize(760, 540)
        self.setMinimumSize(680, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("OptimizerHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 13, 16, 13)
        header_layout.setSpacing(3)
        title = QLabel("修复和优化的轨道")
        title.setObjectName("OptimizerTitle")
        subtitle = QLabel("先预览，再应用。仅修复当前工程中的轨道，不改写原始 MIDI 文件。")
        subtitle.setObjectName("Muted")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        options_card = QFrame()
        options_card.setObjectName("OptimizerOptions")
        options = QGridLayout(options_card)
        options.setContentsMargins(14, 10, 14, 10)
        options.setHorizontalSpacing(18)
        options.setVerticalSpacing(6)
        self.block_check = QCheckBox("修复音块")
        self.block_check.setChecked(True)
        self.velocity_check = QCheckBox("平衡力度")
        self.velocity_check.setChecked(True)
        self.articulation_check = QCheckBox("分析奏法")
        self.articulation_check.setChecked(True)
        self.theory_check = QCheckBox("乐理分析（保守）")
        self.theory_check.setChecked(True)
        self.quantize_check = QCheckBox("柔性对齐")
        self.quantize_check.setChecked(True)
        for index, box in enumerate((self.block_check, self.velocity_check, self.quantize_check, self.articulation_check, self.theory_check)):
            box.stateChanged.connect(self._refresh_report)
            options.addWidget(box, index // 3, index % 3)
        layout.addWidget(options_card)

        hint = QLabel(
            "保守模式会保留和弦、手工奏法和原始动态；奏法只显示建议，未通过游戏 A/B 验证前不会写入。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("OptimizerSummary")
        layout.addWidget(self.summary_label)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setObjectName("OptimizerReport")
        layout.addWidget(self.report_text, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText("应用到轨道")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_report()

    def _config(self) -> OptimizerConfig:
        return OptimizerConfig(
            optimize_blocks=self.block_check.isChecked(),
            polish_velocity=self.velocity_check.isChecked(),
            apply_articulations=self.articulation_check.isChecked(),
            analyse_music_theory=self.theory_check.isChecked(),
            soft_quantize=self.quantize_check.isChecked(),
        )

    def _refresh_report(self) -> None:
        self.optimization_result = optimize_tracks(
            self.parent_window.tracks,
            self.parent_window.bpm_override or self.parent_window.bpm,
            BDO_ARTICULATIONS,
            self._config(),
            self.parent_window.time_sig,
        )
        reports = self.optimization_result.reports
        changed = sum(report.changed for report in reports)
        suggestions = sum(report.suggestions_only for report in reports)
        self.summary_label.setText(f"{len(reports)} 条轨道 · {changed} 条将修复 · {suggestions} 条奏法建议")
        self.report_text.setPlainText(self.optimization_result.summary_text())

    def optimized_tracks(self) -> list[TrackState]:
        if self.optimization_result is None:
            self._refresh_report()
        return self.optimization_result.tracks


class ConversionCheckDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.report = ""
        self.setWindowTitle("转换检查")
        self.resize(980, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("转换检查")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

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

        self.report_view = QTextEdit()
        self.report_view.setReadOnly(True)
        layout.addWidget(self.report_view, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.fix_btn = buttons.addButton("修复可自动处理项", QDialogButtonBox.ActionRole)
        self.fix_btn.clicked.connect(self._apply_fixes)
        copy_btn = buttons.addButton("复制报告", QDialogButtonBox.ActionRole)
        copy_btn.clicked.connect(self._copy_report)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self.report)

    def _apply_fixes(self) -> None:
        message = self.parent_window._apply_conversion_check_fixes()
        self._refresh()
        QMessageBox.information(self, "转换检查", message)

    def _refresh(self) -> None:
        analysis = self.parent_window._analyze_conversion()
        self.report = analysis["report"]
        self.report_view.setPlainText(self.report)
        issue_count = analysis["issue_count"]
        warning_count = analysis["warning_count"]
        fixable_count = analysis["fixable_count"]
        if issue_count:
            status = "需处理"
        elif warning_count:
            status = "需人工确认"
        else:
            status = "可转换"
        self.status_card.setText(f"状态\n{status}")
        self.issue_card.setText(f"问题\n{issue_count}")
        self.warning_card.setText(f"人工确认\n{warning_count}")
        transpose = analysis.get("suggested_transpose")
        fix_text = f"可自动修复\n{fixable_count} 项"
        if transpose is not None:
            fix_text += f" · 移调 {transpose:+d}"
        self.fix_card.setText(fix_text)
        self.fix_btn.setEnabled(fixable_count > 0)


class SettingsDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("转换设置")
        self.setModal(True)
        self.resize(620, 660)
        self.setMinimumSize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 16)
        header_layout.setSpacing(3)
        title = QLabel("转换设置")
        title.setObjectName("SettingsTitle")
        subtitle = QLabel("调整导出规则与 MIDI 效果。未启用的选项不会影响当前工程。")
        subtitle.setObjectName("Muted")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("SettingsBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 16, 18, 18)
        body_layout.setSpacing(12)
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

        general, general_layout = self._section(
            "基础导出",
            "角色名会写入乐谱；BPM 与移调会在导出时应用。",
        )
        form = self._form_layout()
        general_layout.addLayout(form)
        body_layout.addWidget(general)

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
            "与 midi-to-bdo 相同：选择一份游戏内保存的单音符曲谱，读取角色名和 Owner ID。",
        )
        body_layout.addWidget(owner)
        self.owner_id = parent.owner_id
        owner_row = QHBoxLayout()
        self.owner_load_button = PillButton("从游戏曲谱读取", "secondary")
        self.owner_load_button.clicked.connect(self._load_owner_id)
        self.owner_status = QLabel()
        self.owner_status.setObjectName("OwnerStatus")
        self.owner_status.setWordWrap(True)
        owner_row.addWidget(self.owner_load_button)
        owner_row.addWidget(self.owner_status, stretch=1)
        owner_layout.addLayout(owner_row)
        self._refresh_owner_status()

        parsing, parsing_layout = self._section(
            "MIDI 解析",
            "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。",
        )
        body_layout.addWidget(parsing)
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
        body_layout.addWidget(velocity)
        modes = QFrame()
        modes.setObjectName("SettingsModeRow")
        modes_layout = QGridLayout(modes)
        modes_layout.setContentsMargins(0, 0, 0, 0)
        modes_layout.setColumnStretch(0, 1)
        modes_layout.setColumnStretch(1, 1)
        modes_layout.setColumnStretch(2, 1)
        vel_layout.setSpacing(9)
        self.vel_radios: dict[str, QRadioButton] = {
            "layered": QRadioButton("分层"),
            "stepped": QRadioButton("阶梯"),
            "rescale": QRadioButton("重映射"),
            "floor": QRadioButton("抬底"),
            "off": QRadioButton("关闭"),
        }
        for col, (mode, radio) in enumerate(self.vel_radios.items()):
            radio.setChecked(parent.velocity_mode == mode)
            radio.toggled.connect(self._sync_velocity_controls)
            modes_layout.addWidget(radio, col // 3, col % 3)
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
        vel_layout.addLayout(self._labeled_row("阶梯参数", step_row))

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
        vel_layout.addLayout(self._labeled_row("重映射范围", range_row))

        self.vel_floor = QSpinBox()
        self.vel_floor.setRange(0, 127)
        self.vel_floor.setValue(parent.vel_floor or 36)
        floor_row = QHBoxLayout()
        floor_row.addWidget(self.vel_floor)
        floor_row.addStretch(1)
        vel_layout.addLayout(self._labeled_row("抬底值", floor_row))

        effects, effects_layout = self._section(
            "MIDI 效果",
            "数值范围为 0–127；设为 0 即不写入对应效果。",
        )
        effect_form = self._form_layout()
        effects_layout.addLayout(effect_form)
        body_layout.addWidget(effects)
        self.reverb = QSpinBox()
        self.reverb.setRange(0, 127)
        self.reverb.setValue(parent.reverb)
        self.delay = QSpinBox()
        self.delay.setRange(0, 127)
        self.delay.setValue(parent.delay)
        effect_row = QHBoxLayout()
        effect_row.addWidget(QLabel("混响"))
        effect_row.addWidget(self.reverb)
        effect_row.addWidget(QLabel("延迟"))
        effect_row.addWidget(self.delay)
        effect_form.addRow("混响 / 延迟", effect_row)

        self.chorus_feedback = QSpinBox()
        self.chorus_feedback.setRange(0, 127)
        self.chorus_feedback.setValue(parent.chorus[0] if parent.chorus else 0)
        self.chorus_depth = QSpinBox()
        self.chorus_depth.setRange(0, 127)
        self.chorus_depth.setValue(parent.chorus[1] if parent.chorus else 0)
        self.chorus_freq = QSpinBox()
        self.chorus_freq.setRange(0, 127)
        self.chorus_freq.setValue(parent.chorus[2] if parent.chorus else 0)
        chorus_row = QHBoxLayout()
        chorus_row.addWidget(QLabel("反馈"))
        chorus_row.addWidget(self.chorus_feedback)
        chorus_row.addWidget(QLabel("深度"))
        chorus_row.addWidget(self.chorus_depth)
        chorus_row.addWidget(QLabel("频率"))
        chorus_row.addWidget(self.chorus_freq)
        effect_form.addRow("合唱", chorus_row)
        note = QLabel("轨道 FX 中的奏法会写入支持的 BDO 乐器。")
        note.setObjectName("SettingsFootnote")
        body_layout.addWidget(note)
        body_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.setObjectName("SettingsButtons")
        buttons.button(QDialogButtonBox.Ok).setText("保存设置")
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_velocity_controls()

    @staticmethod
    def _section(title_text: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("SettingsSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(9)
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

    def _refresh_owner_status(self, error: str = "") -> None:
        if error:
            self.owner_status.setText(error)
            self.owner_status.setProperty("ownerError", True)
        elif self.owner_id:
            self.owner_status.setText(f"已读取 Owner ID：0x{self.owner_id:08x}")
            self.owner_status.setProperty("ownerError", False)
        else:
            self.owner_status.setText("未读取 Owner ID；导出的曲谱无法在游戏内编辑。")
            self.owner_status.setProperty("ownerError", False)
        self.owner_status.style().unpolish(self.owner_status)
        self.owner_status.style().polish(self.owner_status)

    def _load_owner_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择游戏内保存的单音符曲谱文件",
            str(default_game_music_dir()),
            "黑色沙漠曲谱文件 (*);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            owner_id, char_name = extract_owner_id(path)
            if owner_id == 0:
                self._refresh_owner_status("未读取到有效 Owner ID，请选择游戏内保存的单音符曲谱。")
                return
        except ValueError:
            self._refresh_owner_status("文件无法读取；请使用游戏内保存的单音符曲谱。")
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


class MidiToBdoWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BDO MIDI Arranger")
        self.resize(1360, 820)
        self.setMinimumSize(1160, 720)

        self.config = load_config()
        self.owner_id = 0
        self.tracks: list[TrackState] = []
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
        # The mixer owns its own thread.  Updating the piano-roll at 10 FPS is
        # visually smooth enough while leaving the GUI event loop responsive on
        # dense projects.
        self.realtime_status_timer.setInterval(100)
        self.realtime_status_timer.timeout.connect(self._poll_realtime_audio_status)
        self.last_output_dir = DEFAULT_OUTDIR
        self.autosave_project_dir: Path | None = None
        self.autosave_source_copy: Path | None = None
        self.loading_project = False
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
        self._apply_style()
        latest_project = latest_autosave_project()
        if latest_project:
            self.status_label.setText("发现自动保存工程")
            self.inspector_text.setText(f"发现自动保存工程：{latest_project} · 可点打开工程恢复")
        self._sync_preview_state()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        root.addWidget(self._build_toolbar())

        root.addWidget(self._build_timeline_panel(), stretch=1)

        root.addWidget(self._build_inspector())

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(7)

        import_btn = PillButton("导入 MIDI", "primary")
        import_btn.clicked.connect(self._browse_midi)
        layout.addWidget(import_btn)

        open_project_btn = PillButton("打开工程", "secondary")
        open_project_btn.clicked.connect(self._open_project)
        layout.addWidget(open_project_btn)

        self.file_label = QLabel("未导入 MIDI")
        self.file_label.setObjectName("ToolbarText")
        layout.addWidget(self.file_label, stretch=1)

        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText("曲谱名")
        self.output_name.setFixedWidth(170)
        self.output_name.editingFinished.connect(lambda: self._autosave_project("output name"))
        layout.addWidget(self.output_name)

        self.preview_source_badge = QLabel("游戏映射：检测中")
        self.preview_source_badge.setObjectName("ToolbarBadge")
        layout.addWidget(self.preview_source_badge)

        thanks_btn = PillButton("致谢", "secondary")
        thanks_btn.clicked.connect(self._show_acknowledgements)
        layout.addWidget(thanks_btn)

        settings_btn = PillButton("设置", "secondary")
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)

        self.convert_button = PillButton("转换", "convert")
        self.convert_button.clicked.connect(self._convert)
        layout.addWidget(self.convert_button)
        return bar

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
        scroll.viewport().setObjectName("TrackViewport")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.track_container)
        layout.addWidget(scroll, stretch=1)
        return panel

    def _build_timeline_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title = QLabel("时间轴")
        title.setObjectName("PanelTitle")
        self.timeline_meta = QLabel("等待 MIDI")
        self.timeline_meta.setObjectName("Muted")
        clear_solo = PillButton("清除 Solo", "ghost")
        clear_solo.clicked.connect(self._clear_solo)
        unmute = PillButton("取消静音", "ghost")
        unmute.clicked.connect(self._unmute_all)
        fit_btn = PillButton("Fit", "ghost")
        fit_btn.clicked.connect(self._fit_timeline)
        zoom_label = QLabel("Zoom")
        zoom_label.setObjectName("Muted")
        self.timeline_zoom = QSlider(Qt.Horizontal)
        self.timeline_zoom.setRange(100, 800)
        self.timeline_zoom.setValue(100)
        self.timeline_zoom.setFixedWidth(120)
        pan_label = QLabel("Pan")
        pan_label.setObjectName("Muted")
        self.timeline_pan = QSlider(Qt.Horizontal)
        self.timeline_pan.setRange(0, 1000)
        self.timeline_pan.setValue(0)
        self.timeline_pan.setFixedWidth(150)
        self.play_button = PillButton("播放", "secondary")
        self.play_button.clicked.connect(self._play_preview)
        self.pause_button = PillButton("暂停", "secondary")
        self.pause_button.clicked.connect(self._pause_preview)
        self.stop_button = PillButton("停止", "secondary")
        self.stop_button.clicked.connect(lambda: self._stop_preview(reset_playhead=True))
        header.addWidget(title)
        header.addWidget(self.timeline_meta, stretch=1)
        header.addWidget(self.play_button)
        header.addWidget(self.pause_button)
        header.addWidget(self.stop_button)
        header.addWidget(zoom_label)
        header.addWidget(self.timeline_zoom)
        header.addWidget(pan_label)
        header.addWidget(self.timeline_pan)
        header.addWidget(fit_btn)
        header.addWidget(clear_solo)
        header.addWidget(unmute)
        layout.addLayout(header)
        self.timeline = TimelineCanvas()
        self.timeline.changed.connect(self._on_track_changed)
        self.timeline.track_state_changed.connect(self._on_track_filter_changed)
        self.timeline.instrument_changed.connect(self._on_track_instrument_changed)
        self.timeline.selected.connect(self._select_track)
        self.timeline.effects_requested.connect(self._show_effects_placeholder)
        self.timeline.midi_tools_requested.connect(self._open_midi_tool)
        self.timeline.seek_requested.connect(self._seek_preview)
        self.timeline_zoom.valueChanged.connect(self.timeline.set_zoom_percent)
        self.timeline_pan.valueChanged.connect(self.timeline.set_pan_percent)
        layout.addWidget(self.timeline, stretch=1)
        return panel

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Inspector")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("Status")
        layout.addWidget(self.status_label)

        self.inspector_text = QLabel("选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。")
        self.inspector_text.setObjectName("InspectorText")
        layout.addWidget(self.inspector_text, stretch=1)

        self.selected_volume = QSlider(Qt.Horizontal)
        self.selected_volume.setRange(10, 200)
        self.selected_volume.setValue(100)
        self.selected_volume.setFixedWidth(90)
        self.selected_volume.setEnabled(False)
        self.selected_volume.valueChanged.connect(self._update_selected_volume)
        layout.addWidget(self.selected_volume)

        self.selected_volume_label = QLabel("100%")
        self.selected_volume_label.setObjectName("Muted")
        self.selected_volume_label.setFixedWidth(38)
        layout.addWidget(self.selected_volume_label)

        self.install_check = QCheckBox("复制到游戏目录")
        layout.addWidget(self.install_check)

        self.open_output_button = PillButton("打开输出目录", "secondary")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_output_dir)
        layout.addWidget(self.open_output_button)

        self.out_dir = QLineEdit(str(DEFAULT_OUTDIR))
        self.out_dir.setFixedWidth(300)
        layout.addWidget(self.out_dir)
        return panel

    def _apply_style(self) -> None:
        QApplication.instance().setStyle("Fusion")
        self.setFont(QFont("Microsoft YaHei UI", 9))
        self.setStyleSheet(
            """
            QWidget#Root { background: #151515; color: #f3f1ea; }
            QDialog#SettingsDialog {
                background: #191919;
                color: #f3f1ea;
            }
            QFrame#SettingsHeader {
                background: #22211f;
                border-bottom: 1px solid #3b3935;
            }
            QWidget#SettingsBody { background: #191919; }
            QLabel#SettingsTitle {
                color: #f3f1ea;
                font-size: 20px;
                font-weight: 900;
            }
            QFrame#SettingsSection {
                background: #222222;
                border: 1px solid #373737;
                border-radius: 5px;
            }
            QLabel#SettingsSectionTitle {
                color: #e8c47b;
                font-size: 13px;
                font-weight: 900;
            }
            QLabel#SettingsFieldLabel { color: #c7c0b8; }
            QLabel#OwnerStatus { color: #bdb6ad; }
            QLabel#OwnerStatus[ownerError="true"] { color: #e06c62; }
            QLabel#SettingsFootnote {
                color: #9b958e;
                padding: 1px 2px;
            }
            QFrame#SettingsModeRow { background: transparent; border: 0; }
            QDialog#SettingsDialog QSpinBox {
                min-height: 25px;
                padding: 2px 6px;
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
                background: #202020;
                border-top: 1px solid #383838;
                padding: 12px 18px;
            }
            QDialog#ThanksDialog { background: #181818; color: #f3f1ea; }
            QFrame#Toolbar, QFrame#Panel, QFrame#Inspector {
                background: #222222;
                border: 1px solid #343434;
                border-radius: 4px;
            }
            QLabel#PanelTitle {
                color: #f3f1ea;
                font-size: 15px;
                font-weight: 800;
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
            QLabel#ToolbarText, QLabel#InspectorText { color: #c7c0b8; }
            QLabel#Muted { color: #a8a29e; }
            QLabel#ThanksTitle {
                color: #a8c8a0;
                font-size: 24px;
                font-weight: 900;
            }
            QLabel#ThanksSubtitle {
                color: #d8d3cc;
                font-size: 12px;
                line-height: 140%;
            }
            QFrame#ThanksChartPanel, QFrame#ThanksTextPanel {
                background: #1d211d;
                border: 1px solid #3b4939;
                border-radius: 8px;
            }
            QLabel#ThanksSectionLabel {
                color: #d9ead3;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#ThanksMutedNote {
                color: #a8b5a4;
                font-size: 11px;
                line-height: 135%;
            }
            QLabel#ThanksFooter {
                color: #a8a29e;
                background: #202020;
                border: 1px solid #343434;
                border-radius: 6px;
                padding: 8px 10px;
            }
            QTextEdit#ThanksText {
                background: #171b17;
                border: 1px solid #313d30;
                border-radius: 6px;
                color: #d8d3cc;
                padding: 10px 12px;
            }
            QWidget#ThanksShareSquare {
                background: #111511;
                border: 2px solid #d9ead3;
            }
            QLabel#Status {
                color: #f5a524;
                font-weight: 800;
            }
            QLabel#ToolbarBadge {
                background: #1f1f1f;
                border: 1px solid #313131;
                border-radius: 3px;
                padding: 5px 9px;
                color: #d8d3cc;
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
                color: #6f6a65;
                background: #232323;
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
            QScrollBar#TimelineScroll:vertical {
                background: #1b1b1b;
                width: 10px;
                border: 0;
            }
            QScrollBar#TimelineScroll::handle:vertical {
                background: #4a4640;
                min-height: 36px;
                border-radius: 2px;
            }
            QScrollBar#TimelineScroll::add-line:vertical,
            QScrollBar#TimelineScroll::sub-line:vertical {
                height: 0;
                background: transparent;
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
        )

    def _browse_midi(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 MIDI 文件",
            str(DEFAULT_MIDI_DIR),
            "MIDI 文件 (*.mid *.midi);;所有文件 (*.*)",
        )
        if path:
            self.midi_path = path
            self.autosave_project_dir = None
            self.autosave_source_copy = None
            self.file_label.setText(Path(path).name)
            self.output_name.setText(Path(path).stem)
            self._load_midi_info(path)
            self._autosave_project("import midi", immediate=True)
            self._mark_conversion_check_dirty()
            self.status_label.setText("建议转换检查")
            self.inspector_text.setText("MIDI 已载入。建议先点“转换检查”，确认音域、FX 和打击乐映射后再导出。")

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

    def _load_project(self, project_path: Path) -> None:
        try:
            payload = json.loads(project_path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "打开工程失败", f"无法读取工程文件：{exc}")
            return

        source_path = Path(payload.get("source_midi_path") or "")
        original_path = Path(payload.get("original_midi_path") or "")
        midi_path = source_path if source_path.is_file() else original_path
        if not midi_path.is_file():
            QMessageBox.warning(self, "打开工程失败", "工程里的 MIDI 原文件和自动保存副本都不存在。")
            return

        self.loading_project = True
        try:
            self.autosave_project_dir = project_path.parent
            self.autosave_source_copy = source_path if source_path.is_file() else None
            self.midi_path = str(midi_path)
            self.file_label.setText(midi_path.name)
            self.output_name.setText(payload.get("output_name") or midi_path.stem)
            self.owner_id = int(payload.get("owner_id") or self.owner_id or 0)
            self.char_name = payload.get("char_name") or self.char_name
            self._apply_conversion_settings(payload.get("conversion_settings", {}))
            self._load_midi_info(str(midi_path))
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
                art = item.get("articulation_type")
                track.articulation_type = int(art) if art is not None else None
                mode = str(item.get("marnian_synth_mode", "basic"))
                track.marnian_synth_mode = mode if mode in {value for _label, value in MARNIAN_SYNTH_MODES} else "basic"
                track.notes_optimized = bool(item.get("notes_optimized", False))
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
            self._refresh_tracks()
            self.timeline.set_tracks(self.tracks)
            self._reset_timeline_position()
            self.status_label.setText("工程已恢复")
            self.inspector_text.setText(f"已恢复自动保存工程：{project_path}")
            self._sync_preview_state()
        finally:
            self.loading_project = False
        self._autosave_project("restore project", immediate=True)
        self._mark_conversion_check_dirty()

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
            "articulation_type": track.articulation_type,
            "marnian_synth_mode": track.marnian_synth_mode,
            "notes_optimized": track.notes_optimized,
            "notes": [
                [
                    int(note.pitch),
                    int(note.vel),
                    round(float(note.start), 3),
                    round(float(note.dur), 3),
                    int(getattr(note, "ntype", 0)),
                ]
                for note in track.notes
            ],
        }

    def _ensure_autosave_project(self) -> None:
        midi_path = Path(getattr(self, "midi_path", "") or "")
        if not midi_path.is_file():
            return
        if self.autosave_project_dir is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self.autosave_project_dir = AUTO_SAVE_DIR / f"{safe_filename(midi_path.stem)}_{stamp}"
        self.autosave_project_dir.mkdir(parents=True, exist_ok=True)
        source_name = f"source{midi_path.suffix or '.mid'}"
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
        if self.loading_project or not getattr(self, "midi_path", None) or not self.tracks:
            return
        try:
            self._ensure_autosave_project()
            if self.autosave_project_dir is None:
                return
            saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
            payload = {
                "version": 1,
                "saved_at": saved_at,
                "reason": reason,
                "original_midi_path": str(Path(self.midi_path)),
                "source_midi_path": str(self.autosave_source_copy or ""),
                "output_name": self.output_name.text().strip(),
                "owner_id": self.owner_id,
                "char_name": self.char_name,
                "bpm": self.bpm,
                "time_sig": self.time_sig,
                "tempo_changes": self.tempo_changes,
                "conversion_settings": self._conversion_settings_payload(),
                "tracks": [self._track_state_payload(track) for track in self.tracks],
            }
            project_path = self.autosave_project_dir / "project.json"
            tmp_path = project_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(project_path)
            with (self.autosave_project_dir / "autosave.log").open("a", encoding="utf-8") as file:
                file.write(f"[{saved_at}] {reason}\n")
        except Exception as exc:
            append_crash_log("Autosave failed", traceback.format_exc())
            self.status_label.setText(f"自动保存失败：{exc}")

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

    def _open_midi_tool(self, tool: str) -> None:
        if tool == "optimize":
            self._open_midi_optimizer()
        elif tool == "repair":
            self._open_midi_optimizer()

    def _open_midi_optimizer(self) -> None:
        if not self.tracks:
            QMessageBox.information(self, "修复和优化的轨道", "请先导入 MIDI。")
            return
        dialog = MidiOptimizeDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._stop_preview(reset_playhead=False)
        self.tracks = dialog.optimized_tracks()
        self.selected_track = None
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
        self._on_track_changed()
        self._mark_conversion_check_dirty()
        self._autosave_project("midi optimize", immediate=True)
        self.status_label.setText("轨道已修复并优化")
        self.inspector_text.setText("已应用轨道修复和优化：建议再运行一次转换检查后导出。")

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

    def _transpose_recommendation(self, low: int, high: int) -> str:
        if low >= BDO_NOTE_MIN and high <= BDO_NOTE_MAX:
            return "无需移调"
        if high - low > BDO_NOTE_MAX - BDO_NOTE_MIN:
            return "无单一移调可完全容纳，建议拆轨或换乐器"
        min_shift = BDO_NOTE_MIN - low if low < BDO_NOTE_MIN else 0
        max_shift = BDO_NOTE_MAX - high if high > BDO_NOTE_MAX else 0
        shift = min_shift or max_shift
        octave_shift = int(math.ceil(shift / 12) * 12) if shift > 0 else int(math.floor(shift / 12) * 12)
        if octave_shift == 0:
            octave_shift = shift
        return f"建议移调 {octave_shift:+d}（最小 {shift:+d}）"

    def _analyze_conversion(self) -> dict:
        report = self._build_conversion_check_report()
        issue_count = report.count("[需处理]")
        warning_count = report.count("[需人工确认]")
        invalid_fx = 0
        for track in self.tracks:
            if track.articulation_type is None:
                continue
            supported = {ntype for ntype, _label in BDO_ARTICULATIONS.get(track.bdo_instrument_id, [])}
            if track.articulation_type not in supported:
                invalid_fx += 1
        suggested_transpose = self._suggest_global_transpose()
        fixable_count = invalid_fx + (1 if suggested_transpose is not None else 0)
        return {
            "report": report,
            "issue_count": issue_count,
            "warning_count": warning_count,
            "invalid_fx": invalid_fx,
            "suggested_transpose": suggested_transpose,
            "fixable_count": fixable_count,
        }

    def _apply_conversion_check_fixes(self) -> str:
        analysis = self._analyze_conversion()
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
            self.status_label.setText("转换检查已修复")
            return "已修复：" + "；".join(fixed)
        return "没有可自动修复的项目。未知打击乐、样本音域和需要拆轨的情况仍需人工处理。"

    def _build_conversion_check_report(self) -> str:
        lines = [
            "BDO MIDI 转换检查",
            f"文件: {Path(getattr(self, 'midi_path', '')).name}",
            f"全局移调: {self.transpose:+d} 半音 · BPM: {self.bpm_override or self.bpm} · 轨道: {len(self.tracks)}",
            "定义: 100% 转换 = 不裁剪/折返音高、不丢音符、不使用未知 FX、不落到未知打击乐 pitch。",
            "",
        ]
        active = selected_tracks(self.tracks)
        active_ids = {track.track_id for track in active}
        merged_counts: dict[int, int] = {}
        merged_sources: dict[int, list[str]] = {}
        for track in active:
            merged_counts[track.bdo_instrument_id] = merged_counts.get(track.bdo_instrument_id, 0) + len(track.notes)
            merged_sources.setdefault(track.bdo_instrument_id, []).append(track.display_name)

        for track in self.tracks:
            issues: list[str] = []
            warnings: list[str] = []
            status = "OK"
            inst_name = BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, str(track.bdo_instrument_id))
            pitches = [note.pitch for note in track.notes]
            midi_range = "-" if not pitches else f"{note_name(min(pitches))}-{note_name(max(pitches))}"
            converted_range = "-"
            if track.track_id not in active_ids:
                warnings.append("当前不参与导出（Mute/Solo 过滤）")

            if track.bdo_instrument_id == 0x0d:
                mapped = [_GM_TO_BDO_DRUM.get(pitch) for pitch in pitches]
                known = [pitch for pitch in mapped if pitch is not None]
                unknown = sorted(set(pitch for pitch, mapped_pitch in zip(pitches, mapped) if mapped_pitch is None))
                if known:
                    converted_range = f"{min(known)}-{max(known)}"
                if unknown:
                    issues.append(
                        "未知 GM 打击乐: "
                        + ", ".join(f"{pitch} {note_name(pitch)}" for pitch in unknown[:12])
                        + (" ..." if len(unknown) > 12 else "")
                    )
                supported = game_supported_pitches(track.bdo_instrument_id)
                illegal = sorted(
                    {
                        pitch
                        for pitch in known
                        if pitch < BDO_DRUM_MIN
                        or pitch > BDO_DRUM_MAX
                        or (supported is not None and pitch not in supported)
                    }
                )
                if illegal:
                    issues.append(f"映射后没有对应游戏架子鼓音源: {illegal}")
                if 37 in pitches and _GM_TO_BDO_DRUM.get(37) == 49:
                    warnings.append("GM 37 Side Stick 会映射到 49 SnrSide")
            elif track.is_percussion:
                warnings.append("独立打击乐尚无 GM 到该乐器的完整逐音映射，不能标记为 1:1")
            else:
                shifted = [pitch + self.transpose for pitch in pitches]
                if shifted:
                    converted_range = f"{note_name(min(shifted))}-{note_name(max(shifted))}"
                    out_count = sum(1 for pitch in shifted if pitch < BDO_NOTE_MIN or pitch > BDO_NOTE_MAX)
                    if out_count:
                        issues.append(
                            f"{out_count} 个音符超出 C1-C8({BDO_NOTE_MIN}-{BDO_NOTE_MAX}); "
                            f"{self._transpose_recommendation(min(shifted), max(shifted))}"
                        )
                    supported = game_supported_pitches(track.bdo_instrument_id)
                    if supported is None:
                        warnings.append("当前乐器未找到可核验的游戏采样键位，不能标记为 1:1")
                    else:
                        unsupported = [pitch for pitch in shifted if pitch not in supported]
                        if unsupported:
                            issues.append(
                                f"{len(unsupported)} 个音符超出 {game_pitch_range_label(track.bdo_instrument_id)}；"
                                "时间轴已标红，游戏可能无声"
                            )
                if track.bdo_instrument_id in BDO_SAMPLE_ONLY_PERCUSSION and pitches:
                    warnings.append("该独立打击/手碟乐器目前只有样本音高，完整音域需人工验证")

            if track.articulation_type is not None:
                supported = {ntype for ntype, _label in BDO_ARTICULATIONS.get(track.bdo_instrument_id, [])}
                if track.articulation_type not in supported:
                    issues.append(f"FX type {track.articulation_type} 不属于当前乐器，建议清空 FX 或换乐器")

            if issues:
                status = "需处理"
            elif warnings:
                status = "需人工确认"

            lines.append(
                f"[{status}] Track {track.track_id}: {track.display_name} -> {inst_name} · "
                f"{len(track.notes)} notes · MIDI {midi_range} · 转换后 {converted_range} · 问题 {len(issues)}"
            )
            for issue in issues:
                lines.append(f"  - {issue}")
            for warning in warnings:
                lines.append(f"  - {warning}")

        lines.append("")
        lines.append("合并与容量检查")
        for inst_id, sources in sorted(merged_sources.items()):
            inst_name = BDO_INSTRUMENT_NAMES.get(inst_id, str(inst_id))
            if len(sources) > 1:
                lines.append(f"- 导出会按乐器合并: {inst_name} <= {', '.join(sources)}")
            count = merged_counts.get(inst_id, 0)
            if count > MAX_NOTES_PER_INSTRUMENT:
                lines.append(f"- 需处理: {inst_name} 合并后 {count} notes，超过 {MAX_NOTES_PER_INSTRUMENT}，导出会丢弃尾部音符")
        lines.append("- 架子鼓有效 pitch: 48-64，包含 63 SnrRollS / 64 SnrRollL。")
        lines.append("- 红色音块 = 转换后音高不在该乐器解包 Wwise 的触发键位内，不能承诺游戏发声。")
        lines.append("- 手鼓、钹、手碟暂不自动拆分；缺完整 GM 映射时报告为需人工验证。")
        return "\n".join(lines)

    def _show_acknowledgements(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("致谢")
        dialog.resize(820, 560)
        dialog.setObjectName("ThanksDialog")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("小小致谢")
        title.setObjectName("ThanksTitle")
        layout.addWidget(title)

        subtitle = QLabel("这些可爱的项目和工具一起撑起了转换、试听、界面和开发协作。")
        subtitle.setObjectName("ThanksSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(16)
        layout.addLayout(body, stretch=1)

        chart_panel = QFrame()
        chart_panel.setObjectName("ThanksChartPanel")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(14, 14, 14, 14)
        chart_layout.setSpacing(10)

        chart_title = QLabel("当前贡献占比")
        chart_title.setObjectName("ThanksSectionLabel")
        chart_layout.addWidget(chart_title)

        share_square = ThanksShareSquare()
        chart_layout.addWidget(share_square, alignment=Qt.AlignCenter)

        chart_note = QLabel("按当前代码里真正承担功能的部分粗略估算。Python 和 PySide6 / Qt 不计入。")
        chart_note.setObjectName("ThanksMutedNote")
        chart_note.setWordWrap(True)
        chart_layout.addWidget(chart_note)
        chart_layout.addStretch(1)
        body.addWidget(chart_panel)

        text_panel = QFrame()
        text_panel.setObjectName("ThanksTextPanel")
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(12, 12, 12, 12)
        text_layout.setSpacing(8)

        text_title = QLabel("致谢名单")
        text_title.setObjectName("ThanksSectionLabel")
        text_layout.addWidget(text_title)

        thanks_text = QTextEdit()
        thanks_text.setObjectName("ThanksText")
        thanks_text.setReadOnly(True)
        thanks_text.setHtml(
            """
            <style>
                body { color: #d8d3cc; font-family: "Microsoft YaHei UI"; font-size: 11px; }
                h2 { color: #a8c8a0; font-size: 18px; margin-top: 10px; margin-bottom: 5px; }
                p { margin: 4px 0; line-height: 130%; }
                b { color: #d9ead3; }
            </style>
            <h2>MIDI 与游戏采样试听</h2>
            <p><b>mido</b>：把 MIDI 音符一颗颗读出来、写回去。</p>
            <p><b>BDO 原始采样映射</b>：试听只使用从游戏提取并验证过的键位映射。</p>

            <h2>GitHub 开源项目</h2>
            <p><b>Bishop-R / midi-to-bdo</b>：感谢 midi-to-bdo 作者，提供 MIDI 转黑色沙漠曲谱格式的核心基础。</p>
            <p><b>Skyro468 / BDO-Music-Composer-Stuff</b>：感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。</p>

            <h2>AI 另一个小角落</h2>
            <p><b>ChatGPT / OpenAI</b>：在旁边递思路、改文案、一起收拾代码。</p>

            <h2>还有大家</h2>
            <p>谢谢开源维护者、文档作者、issue 讨论者、测试者，以及每一个愿意分享经验的人。</p>
            """
        )
        text_layout.addWidget(thanks_text, stretch=1)
        body.addWidget(text_panel, stretch=1)

        footer = QLabel("谢谢每一个把工具、文档和经验分享出来的人。")
        footer.setObjectName("ThanksFooter")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _load_midi_info(self, path: str) -> None:
        self._stop_preview()
        self._clear_track_selection()
        try:
            bpm, tsig, groups, tempo_changes = parse_midi(
                path,
                apply_sustain=self.apply_sustain,
                flatten_tempo=self.flatten_tempo,
            )
        except Exception as exc:
            self.tracks = []
            self.timeline.set_tracks([])
            self._refresh_tracks()
            self.status_label.setText("载入失败")
            self.inspector_text.setText(f"MIDI 载入失败：{exc}")
            return

        self.bpm = bpm
        self.time_sig = tsig
        self.tempo_changes = tempo_changes
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
                )
            )
        self._refresh_tracks()
        self.timeline.set_tracks(self.tracks)
        self._reset_timeline_position()
        self._on_track_changed()
        self.status_label.setText("MIDI 已载入")
        self._show_project_summary()
        self._sync_preview_state()

    def _clear_track_selection(self) -> None:
        self.selected_track = None
        if hasattr(self, "timeline"):
            self.timeline.set_selected_track(None)
        if hasattr(self, "selected_volume"):
            self.selected_volume.blockSignals(True)
            self.selected_volume.setEnabled(False)
            self.selected_volume.setValue(100)
            self.selected_volume.blockSignals(False)
        if hasattr(self, "selected_volume_label"):
            self.selected_volume_label.setText("100%")

    def _refresh_tracks(self) -> None:
        self.timeline.set_tracks(self.tracks)
        self._on_track_changed()

    def _on_track_changed(self) -> None:
        self.timeline.set_conversion_transpose(self.transpose)
        self.timeline.update()
        active = selected_tracks(self.tracks)
        solo = sum(1 for track in self.tracks if track.solo)
        muted = sum(1 for track in self.tracks if track.muted)
        total_blocks = sum(1 for track in self.tracks if track.note_count > 0)
        active_blocks = sum(1 for track in active if track.note_count > 0)
        if hasattr(self, "timeline_meta"):
            rail = chr(0x8F68)
            current = chr(0x5F53) + chr(0x524D)
            blocks_label = chr(0x5757)
            dot = chr(0x00B7)
            self.timeline_meta.setText(
                f"{len(self.tracks)} {rail} {dot} {current} {len(active)} {rail} {dot} "
                f"{blocks_label} {active_blocks}/{total_blocks} {dot} Solo {solo} {dot} Mute {muted} {dot} "
                f"BPM {self.bpm} {dot} {self.time_sig}/4"
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

    def _select_track(self, track: TrackState) -> None:
        self.selected_track = track
        self.timeline.set_selected_track(track)
        self.inspector_text.setText(
            f"{track.display_name} · {track.note_count} 音符 · {track.pitch_range} · "
            f"BDO: {BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, track.bdo_instrument_id)} · "
            f"FX: {articulation_label(track.bdo_instrument_id, track.articulation_type)} · 右键轨道更换乐器"
        )
        self.selected_volume.blockSignals(True)
        self.selected_volume.setEnabled(True)
        self.selected_volume.setValue(round(track.volume_scale * 100))
        self.selected_volume.blockSignals(False)
        self.selected_volume_label.setText(f"{round(track.volume_scale * 100)}%")
        self.timeline.update()

    def _update_selected_volume(self, value: int) -> None:
        if not self.selected_track:
            return
        self.selected_track.volume_scale = value / 100.0
        self.selected_volume_label.setText(f"{value}%")
        self._on_preview_mapping_changed()

    def _show_project_summary(self) -> None:
        notes = [note for track in self.tracks for note in track.notes]
        end_ms = max((track.end_ms for track in self.tracks), default=0.0)
        minutes, seconds = divmod(int(end_ms / 1000), 60)
        pitch = "-"
        if notes:
            pitch = f"{note_name(min(n.pitch for n in notes))} - {note_name(max(n.pitch for n in notes))}"
        self.inspector_text.setText(
            f"{Path(getattr(self, 'midi_path', '')).name} · {len(self.tracks)} 轨 · "
            f"{len(notes)} 音符 · {minutes}m {seconds:02d}s · {pitch}"
        )

    def _show_effects_placeholder(self, track: TrackState) -> None:
        self.selected_track = track
        dialog = TrackFxDialog(self, track)
        if dialog.exec() != QDialog.Accepted:
            return
        track.articulation_type = dialog.selected_articulation()
        track.marnian_synth_mode = (
            dialog.selected_marnian_synth_mode()
            if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
            else "basic"
        )
        self.inspector_text.setText(
            f"FX：{track.display_name} · "
            f"{articulation_label(track.bdo_instrument_id, track.articulation_type)}"
            + (f" · {track.marnian_synth_mode}" if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS else "")
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
        running = self.realtime_preview_active
        paused = running and self.realtime_audio.status.state != "playing"
        self.play_button.setEnabled(has_bdo_samples and bool(self.tracks) and (not running or paused))
        self.play_button.setText("播放" if has_bdo_samples else "无法原声试听")
        if hasattr(self, "preview_source_badge"):
            if preview_blockers:
                self.preview_source_badge.setText("无法原声还原")
            elif not self.realtime_audio.available():
                self.preview_source_badge.setText("无可用音频设备")
            elif self.realtime_audio.status.cache_misses:
                self.preview_source_badge.setText("等待预取")
            elif self.realtime_validation_state == "verified":
                self.preview_source_badge.setText("原声已验证")
            else:
                # Wwise samples are exact; DSP remains explicitly unverified until A/B calibration.
                self.preview_source_badge.setText("原声近似" if self.realtime_audio.status.unverified else "原声近似（待 A/B 验证）")
        self.pause_button.setEnabled(running and not paused)
        self.stop_button.setEnabled(running)

    def _can_preview_with_bdo_samples(self, tracks: list[TrackState]) -> bool:
        return not self._realtime_preview_blockers(tracks)

    def _realtime_preview_blockers(self, tracks: list[TrackState]) -> list[str]:
        if not tracks:
            return ["没有可试听轨道"]
        if not BDO_SAMPLE_MAP_PATH.is_file():
            return ["缺少解包后的 BDO Wwise 映射"]
        if not Path(self.audio_sources["audio_root"]).is_dir():
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
            self.status_label.setText("正在准备游戏音源…")
            return
        if self.realtime_preview_active:
            try:
                self.realtime_audio.play()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
            self.status_label.setText("试听播放")
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
        blockers = self._realtime_preview_blockers(tracks)
        if blockers:
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
        self.realtime_status_timer.start()
        self.status_label.setText("正在准备游戏音源…")
        self._sync_preview_state()

    def _pause_preview(self) -> None:
        if self.realtime_preview_active:
            try:
                self.realtime_audio.pause()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
            self.status_label.setText("试听暂停")
            self._sync_preview_state()

    def _stop_preview(self, reset_playhead: bool = False) -> None:
        self.preview_generation += 1
        self._stop_bdo_audio()
        self.realtime_preview_active = False
        self.realtime_preview_loading = False
        self.realtime_preview_tracks = []
        self.realtime_status_timer.stop()
        if reset_playhead and hasattr(self, "timeline"):
            self._reset_timeline_position()
        if hasattr(self, "status_label"):
            self.status_label.setText("就绪")
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
                result = self.realtime_audio.finish_loading(self.realtime_preview_start_ms)
                if result is None:
                    return
                self.realtime_preview_loading = False
                details = result.get("unverified", [])
                self.realtime_validation_state = self._validation_state(self.realtime_preview_tracks, details)
                self.realtime_audio.play()
                self.status_label.setText("BDO 实时原声试听" if not details else f"BDO 实时试听（{len(details)} 项待验证）")
            status = self.realtime_audio.get_status()
        except AudioEngineError as exc:
            self.realtime_status_timer.stop()
            self.realtime_preview_active = False
            self.status_label.setText("实时音频引擎已停止")
            self.realtime_audio.last_error = str(exc)
            self._sync_preview_state()
            return
        self.timeline.set_playhead(status.position_ms, follow=True)
        if status.underruns:
            self.status_label.setText(
                f"BDO 实时试听缓冲不足 {status.underruns} 次 · 混音 P95 {status.render_p95_ms:.1f} ms"
            )
        if status.state == "stopped" or (status.position_ms >= status.duration_ms and status.duration_ms > 0):
            self.realtime_preview_active = False
            self.realtime_status_timer.stop()
            if self.realtime_audio.last_error:
                self.status_label.setText(f"音频输出停止：{self.realtime_audio.last_error}")
        self._sync_preview_state()

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
        self._sync_preview_state()

    def _open_settings(self) -> None:
        old_parse_settings = (self.apply_sustain, self.flatten_tempo)
        dialog = SettingsDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        self.char_name = dialog.char_name.text().strip() or "MIDI"
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

        if getattr(self, "midi_path", None) and old_parse_settings != (self.apply_sustain, self.flatten_tempo):
            self._load_midi_info(self.midi_path)
        self.inspector_text.setText(
            f"转换设置：力度 {self.velocity_mode} · 移调 {self.transpose:+d} · "
            f"BPM {self.bpm_override or 'MIDI'} · 踏板 {'开' if self.apply_sustain else '关'}"
        )
        self._autosave_project("settings")

    def _build_params(self) -> dict:
        midi_path = getattr(self, "midi_path", "")
        if not midi_path or not Path(midi_path).is_file():
            raise ValueError("请选择有效的 MIDI 文件")
        active = selected_tracks(self.tracks)
        if not active:
            raise ValueError("没有可导出的轨道，请取消静音或 Solo 至少一条轨道")

        out_dir = Path(self.out_dir.text().strip() or DEFAULT_OUTDIR)
        out_name = self.output_name.text().strip() or Path(midi_path).stem
        if any(ch in out_name for ch in '<>:"/\\|?*'):
            raise ValueError("曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*")
        out_path = out_dir / out_name

        has_duration_edits = any(not math.isclose(t.duration_scale, 1.0) for t in self.tracks)
        has_note_articulations = any(
            any(getattr(note, "ntype", 0) for note in track.notes)
            for track in active
        )
        has_optimized_notes = any(track.notes_optimized for track in active)
        full_export = (
            not has_duration_edits
            and len(active) == len(self.tracks)
            and all(not t.muted and not t.solo for t in self.tracks)
        )
        # Optimized notes live in the editor model.  Rebuild a temporary MIDI
        # and use midi_to_bdo's normal parser/writer path for compatibility.
        filtered_tracks = None if full_export and not has_optimized_notes else active
        export_tracks = self.tracks if filtered_tracks is None else active
        instrument_map = {idx: track.bdo_instrument_id for idx, track in enumerate(export_tracks)}
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
        return {
            "midi_path": midi_path,
            "filtered_tracks": filtered_tracks,
            "direct_tracks": active if has_note_articulations and not has_optimized_notes else None,
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
            "install": self.install_check.isChecked(),
            "game_dir": str(default_game_music_dir()),
        }

    def _convert(self) -> None:
        try:
            params = self._build_params()
        except Exception as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        self._stop_preview()
        self.convert_button.setEnabled(False)
        self.status_label.setText("正在转换...")
        self.worker = ConvertWorker(params)
        self.worker.conversion_finished.connect(self._on_convert_finished)
        self.worker.failed.connect(self._on_convert_failed)
        self.worker.start()

    def _on_convert_finished(self, out_path: str, byte_count: int, summary: object, installed: str) -> None:
        self.convert_button.setEnabled(True)
        self.last_output_dir = Path(out_path).parent
        self.open_output_button.setEnabled(True)
        self.status_label.setText("转换完成")
        summary = dict(summary)
        extra = f" · 已复制到游戏目录" if installed else ""
        self.inspector_text.setText(
            f"已保存 {Path(out_path).name} · {byte_count} bytes · "
            f"{summary['instruments']} 乐器 · {summary['tracks']} 轨 · {summary['total_notes']} 音符{extra}"
        )
        self._autosave_project("convert finished", immediate=True)
        self.worker = None

    def _on_convert_failed(self, message: str) -> None:
        self.convert_button.setEnabled(True)
        self.status_label.setText("转换失败")
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
        self._stop_preview()
        self.realtime_audio.stop()
        super().closeEvent(event)


def main() -> int:
    install_crash_logging()
    app = QApplication(sys.argv)
    try:
        window = MidiToBdoWindow()
        window.show()
        result = app.exec()
        append_crash_log("Application exited", f"exit_code={result}")
        return result
    except BaseException as exc:
        append_crash_log("Fatal error in main()", f"{exc}\n\n{traceback.format_exc()}")
        QMessageBox.critical(None, "程序错误", f"程序发生错误，日志已写入：\n{CRASH_LOG_PATH}\n\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
