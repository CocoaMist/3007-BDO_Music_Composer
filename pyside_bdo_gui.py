#!/usr/bin/env python3
"""GarageBand-style PySide6 MIDI workspace for BDO music conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"
DEFAULT_OUTDIR = ROOT / "out" / "bdo"
DEFAULT_MIDI_DIR = ROOT / "samples"
CONFIG_PATH = ROOT / ".pyside_bdo_gui.json"
DEFAULT_SOUNDFONT = ROOT / "assets" / "soundfonts" / "GeneralUser_GS_FluidSynth_v1.44.sf2"
FLUIDSYNTH_ROOT = ROOT / "assets" / "fluidsynth"

sys.path.insert(0, str(TOOL_DIR))


def configure_fluidsynth_runtime() -> Path | None:
    """Make bundled FluidSynth DLLs visible to pyfluidsynth on Windows."""
    if os.name != "nt" or not FLUIDSYNTH_ROOT.exists():
        return None
    dlls = sorted(FLUIDSYNTH_ROOT.rglob("libfluidsynth-*.dll"))
    if not dlls:
        dlls = sorted(FLUIDSYNTH_ROOT.rglob("fluidsynth*.dll"))
    if not dlls:
        return None
    bin_dir = dlls[0].parent
    try:
        os.add_dll_directory(str(bin_dir))
    except (AttributeError, OSError):
        pass
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    return bin_dir


FLUIDSYNTH_BIN = configure_fluidsynth_runtime()

try:
    import mido
    from PySide6.QtCore import QRectF, Qt, QThread, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
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
    extract_owner_id,
    gm_program_name,
    gm_to_bdo_instrument,
    midi_to_bdo,
    parse_midi,
)


TRACK_COLORS = [
    "#d88c6f", "#8dbf67", "#6f9fd8", "#d8b66f", "#b887d8", "#70b8a8",
    "#d87592", "#91a7d8", "#c6d86f", "#d89f6f", "#8ed8ce", "#b9a0d8",
]

# BDO has no public SoundFont. These are General MIDI approximations for preview.
# Sources describe Florchestra as acoustic instruments, Marnian as mystical/synth
# instruments, and Marni electric guitars as clean/drive/heavy-distortion variants.
BDO_PREVIEW_PROGRAMS = {
    0x00: 24,  # beginner guitar / nylon guitar
    0x01: 73,  # beginner flute
    0x02: 74,  # recorder
    0x04: 116,  # hand drum / taiko-style drum fallback
    0x05: 119,  # cymbals / reverse-cymbal fallback
    0x06: 46,  # harp
    0x07: 0,   # piano
    0x08: 40,  # violin
    0x0a: 25,  # Florchestra acoustic guitar / steel guitar
    0x0b: 73,  # Florchestra flute
    0x0d: 0,   # drum set uses channel 10
    0x0e: 38,  # Marnibass / synth bass
    0x0f: 43,  # contrabass / double bass
    0x10: 46,  # harp
    0x11: 0,   # piano
    0x12: 40,  # violin
    0x13: 11,  # handpan / vibraphone-like metallic resonance
    0x14: 89,  # Marnian wavy planet / warm synth pad
    0x18: 81,  # Marnian illusion tree / saw lead
    0x1c: 98,  # Marnian secret note / crystal FX
    0x20: 87,  # Marnian sandwich / bass+lead synth
    0x24: 27,  # electric guitar: clean
    0x25: 29,  # electric guitar: overdrive/highway
    0x26: 30,  # electric guitar: distortion/hexe
    0x27: 71,  # clarinet
    0x28: 60,  # french horn
}


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
    if program in (47, 112, 113, 114, 115, 116, 117, 118, 119):
        return 0x0d  # timpani/percussion family
    if 80 <= program <= 87:
        return 0x18  # synth lead family, closer to Marnian tone colors
    if 88 <= program <= 95:
        return 0x14  # synth pad family
    if 96 <= program <= 103:
        return 0x1c  # synth FX family
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
    color: str = "#d88c6f"
    effect_settings_placeholder: dict = field(default_factory=dict)

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


def find_owner_id_file(game_dir: Path, max_files: int = 200) -> tuple[Path, int, str]:
    if not game_dir.is_dir():
        raise FileNotFoundError(f"游戏曲谱目录不存在：{game_dir}")
    files = [path for path in game_dir.iterdir() if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    saw_small_file = False
    last_error = ""
    for path in files[:max_files]:
        try:
            if path.stat().st_size > 516:
                continue
            saw_small_file = True
            owner_id, char_name = extract_owner_id(path)
            if owner_id:
                return path, owner_id, char_name
            last_error = f"{path.name} 没有 Owner ID"
        except Exception as exc:
            last_error = f"{path.name}: {exc}"
    if not saw_small_file:
        raise ValueError("没有找到可读取 ID 的小型曲谱文件，请先在游戏里保存一个单音符曲谱")
    raise ValueError(last_error or "没有读取到有效 Owner ID")


def selected_tracks(tracks: list[TrackState]) -> list[TrackState]:
    solo_tracks = [track for track in tracks if track.solo]
    return solo_tracks if solo_tracks else [track for track in tracks if not track.muted]


def build_filtered_midi(tracks: list[TrackState], bpm: int, out_path: Path) -> None:
    mid = mido.MidiFile(ticks_per_beat=480)
    tempo = mido.bpm2tempo(max(1, min(240, bpm or 120)))
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
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
            ("midi-to-bdo", 40, "#9fc79a"),
            ("BDO 解码资料", 18, "#82aa9b"),
            ("FluidSynth", 16, "#779a73"),
            ("mido", 10, "#b0cfaa"),
            ("GeneralUser GS", 8, "#66845f"),
            ("ChatGPT", 8, "#c0d8bb"),
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
    seek_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.tracks: list[TrackState] = []
        self.hit_regions: list[tuple[QRectF, str, TrackState]] = []
        self.zoom_factor = 1.0
        self.view_start_ms = 0.0
        self.playhead_ms = 0.0
        self.grid_rect = QRectF()
        self.overview_rect = QRectF()
        self.overview_handle_rect = QRectF()
        self.dragging_overview = False
        self.dragging_timeline = False
        self.last_drag_x = 0.0
        self.selected_track: TrackState | None = None
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_track_scrollbar()

    def _lane_height(self) -> int:
        return 58

    def _timeline_layout_metrics(self) -> tuple[QRectF, int, int, int, int]:
        area = self.rect().adjusted(14, 12, -14, -14)
        header_w = 286
        ruler_h = 34
        overview_h = 24
        lane_h = self._lane_height()
        return area, header_w, ruler_h, overview_h, lane_h

    def _update_track_scrollbar(self) -> None:
        if not hasattr(self, "track_scroll"):
            return
        area, _header_w, ruler_h, overview_h, lane_h = self._timeline_layout_metrics()
        grid_top = area.top() + ruler_h
        grid_h = max(80, area.bottom() - grid_top - overview_h)
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

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#171717"))
        self.hit_regions = []

        self._update_track_scrollbar()
        area, header_w, ruler_h, overview_h, lane_h = self._timeline_layout_metrics()
        if not self.tracks:
            painter.setPen(QColor("#8d8780"))
            painter.drawText(area, Qt.AlignCenter, "导入 MIDI 后显示轨道与音符时间轴")
            return

        max_end = self._timeline_end_ms()
        visible_start = self.view_start_ms
        visible_duration = self._visible_duration_ms()
        visible_end = visible_start + visible_duration
        left = area.left()
        top = area.top()
        grid_left = left + header_w
        grid_top = top + ruler_h
        scrollbar_w = 14 if self.track_scroll.isVisible() else 0
        grid_w = max(120, area.width() - header_w - scrollbar_w)
        grid_h = max(80, area.bottom() - grid_top - overview_h)
        self.grid_rect = QRectF(grid_left, top, grid_w, grid_h + ruler_h)
        overview_top = grid_top + grid_h + 4

        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor("#202020"))
        tracks_clip = QRectF(left, grid_top, header_w + grid_w, grid_h)
        timeline_clip = QRectF(grid_left, grid_top, grid_w, grid_h)
        painter.fillRect(QRectF(left, grid_top, header_w, grid_h), QColor("#1d1d1d"))
        painter.fillRect(timeline_clip, QColor("#151515"))
        painter.setPen(QPen(QColor("#343434"), 1))
        painter.drawLine(grid_left, top, grid_left, area.bottom())
        painter.drawLine(left, grid_top, area.right(), grid_top)
        painter.drawLine(left, overview_top - 4, area.right(), overview_top - 4)

        total_seconds = visible_duration / 1000.0
        beat_seconds = 60.0 / max(1, 120)
        bar_seconds = beat_seconds * 4
        bars = max(4, min(24, math.ceil(total_seconds / bar_seconds) if total_seconds else 4))

        for i in range(bars + 1):
            x = grid_left + grid_w * i / bars
            if i < bars:
                shade = QColor("#191919" if i % 2 else "#171717")
                painter.fillRect(QRectF(x, grid_top, grid_w / bars, grid_h), shade)
            is_major = i % 4 == 0
            painter.setPen(QPen(QColor("#3a3a3a" if is_major else "#292929"), 1))
            painter.drawLine(int(x), grid_top, int(x), overview_top - 5)
            if i < bars:
                painter.setPen(QColor("#8e8982" if is_major else "#5f5a54"))
                seconds = int((visible_start / 1000.0) + total_seconds * i / bars)
                label = str(i + 1) if bars <= 12 else f"{seconds // 60}:{seconds % 60:02d}"
                painter.drawText(int(x + 6), top + 22, label)

        painter.setPen(QColor("#a8a29e"))
        painter.drawText(left + 10, top + 22, "Tracks")

        play_x = None
        if visible_start <= self.playhead_ms <= visible_end:
            play_x = grid_left + ((self.playhead_ms - visible_start) / visible_duration) * grid_w
            painter.fillRect(QRectF(play_x, grid_top, 2, grid_h), QColor("#f5a524"))
            marker = QPainterPath()
            marker.moveTo(play_x - 5, top + 1)
            marker.lineTo(play_x + 7, top + 1)
            marker.lineTo(play_x + 1, top + 9)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#f5a524"))

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
            lane_color = QColor("#202020" if row % 2 else "#1c1c1c")
            if not active:
                lane_color = QColor("#171717")
            if focused:
                lane_color = QColor("#2a2419" if active else "#211d17")
            painter.setBrush(lane_color)
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(grid_left, y, grid_w, lane_h))
            painter.fillRect(
                QRectF(left, y, header_w, lane_h),
                QColor("#30281a" if focused else ("#222222" if active else "#191919")),
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
                painter.setBrush(accent)
                for note in track.notes[:2600]:
                    scaled_dur = note.dur * track.duration_scale
                    note_end = note.start + scaled_dur
                    if note_end < visible_start or note.start > visible_end:
                        continue
                    x = region_rect.left() + ((note.start - visible_start) / visible_duration) * region_rect.width()
                    w = max(2.5, (scaled_dur / visible_duration) * region_rect.width())
                    pitch_pos = (note.pitch - pitch_min) / pitch_span
                    note_y = region_rect.top() + 6 + (1.0 - pitch_pos) * (region_rect.height() - 14)
                    painter.drawRect(QRectF(x, note_y, w, 3.5))
                painter.restore()

            painter.setPen(QColor("#f3f1ea" if active else "#8a847d"))
            painter.drawText(left + 12, y + 22, track.display_name[:18])
            painter.setPen(QColor("#a8a29e" if active else "#69645f"))
            inst_name = BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, str(track.bdo_instrument_id))
            painter.drawText(left + 12, y + 43, f"{track.note_count} notes · {track.pitch_range} · {inst_name[:12]}")
        painter.restore()

        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor("#202020"))
        painter.setPen(QColor("#a8a29e"))
        painter.drawText(left + 10, top + 22, "Tracks")
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
        painter.drawLine(grid_left, top, grid_left, overview_top - 4)
        painter.drawLine(left, grid_top, grid_left + grid_w, grid_top)
        painter.drawLine(left, overview_top - 4, grid_left + grid_w, overview_top - 4)

        self.overview_rect = QRectF(grid_left, overview_top, grid_w, overview_h - 6)
        painter.fillRect(self.overview_rect, QColor("#202020"))
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.drawRect(self.overview_rect)
        for track in self.tracks:
            if not track.notes:
                continue
            mini_color = QColor(track.color)
            mini_color.setAlpha(120)
            painter.setBrush(mini_color)
            painter.setPen(Qt.NoPen)
            for note in track.notes[:1200]:
                x = grid_left + (note.start / max_end) * grid_w
                w = max(1.0, (note.dur * track.duration_scale / max_end) * grid_w)
                painter.drawRect(QRectF(x, overview_top + 5, w, 4))

        handle_x = grid_left + (visible_start / max_end) * grid_w
        handle_w = max(18.0, (visible_duration / max_end) * grid_w)
        handle = QRectF(handle_x, overview_top + 2, min(handle_w, grid_w - (handle_x - grid_left)), overview_h - 10)
        self.overview_handle_rect = handle
        painter.setBrush(QColor(245, 165, 36, 34))
        painter.setPen(QPen(QColor("#8f6b2e"), 1))
        painter.drawRect(handle)
        painter.setPen(QColor("#8e8982"))
        painter.drawText(left + 10, overview_top + 14, "Overview")

        overview_play_x = grid_left + (self.playhead_ms / max_end) * grid_w
        painter.fillRect(QRectF(overview_play_x, overview_top, 2, overview_h - 6), QColor("#f5a524"))

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
        if self.overview_handle_rect.contains(pos) or self.overview_rect.contains(pos):
            self.dragging_overview = True
            self._set_view_from_overview_x(pos.x())
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
        current_id = track.bdo_instrument_id
        for inst_id, name in BDO_INSTRUMENT_NAMES.items():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)
        selected = menu.exec(global_pos)
        if selected is None:
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
        if self.dragging_overview:
            self._set_view_from_overview_x(pos.x())
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
        self.dragging_overview = False
        self.dragging_timeline = False
        super().mouseReleaseEvent(event)

    def _set_view_from_overview_x(self, x: float) -> None:
        if self.overview_rect.width() <= 0:
            return
        handle_w = self.overview_handle_rect.width() if self.overview_handle_rect.isValid() else 0
        usable_w = max(1.0, self.overview_rect.width() - handle_w)
        rel = (x - self.overview_rect.left() - handle_w / 2) / usable_w
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        self.view_start_ms = max_start * max(0.0, min(1.0, rel))
        self._clamp_view()
        self.update()
        self.changed.emit()

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
        current_id = self.track.bdo_instrument_id
        for inst_id, name in self.instrument_names.items():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(inst_id == current_id)
            action.setData(inst_id)
        selected = menu.exec(event.globalPos())
        if selected is None:
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == self.track.bdo_instrument_id:
            return
        self.track.bdo_instrument_id = int(inst_id)
        self.instrument_label.setText(self._instrument_label_text())
        self.instrument_changed.emit(self.track)
        self.changed.emit()

    def _instrument_label_text(self) -> str:
        name = self.instrument_names.get(self.track.bdo_instrument_id, str(self.track.bdo_instrument_id))
        return f"{name} · 右键更换"

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
            if params["filtered_tracks"] is not None:
                fd, raw_temp_path = tempfile.mkstemp(suffix=".mid")
                os.close(fd)
                temp_path = Path(raw_temp_path)
                build_filtered_midi(params["filtered_tracks"], params["bpm_for_temp"], temp_path)
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


class PreviewWorker(QThread):
    failed = Signal(str)
    stopped = Signal()
    position_changed = Signal(float)

    def __init__(self, tracks: list[TrackState], soundfont_path: str, start_ms: float = 0.0):
        super().__init__()
        self.tracks = tracks
        self.soundfont_path = soundfont_path
        self.start_seconds = max(0.0, start_ms / 1000.0)
        self._stop = False
        self._paused = False
        self._pause_started = 0.0
        self._paused_total = 0.0

    def stop(self) -> None:
        self._stop = True

    def pause(self) -> None:
        if not self._paused:
            self._paused = True
            self._pause_started = time.monotonic()

    def resume(self) -> None:
        if self._paused:
            self._paused = False
            self._paused_total += time.monotonic() - self._pause_started
            self._pause_started = 0.0

    def run(self) -> None:
        try:
            import fluidsynth  # type: ignore
        except Exception as exc:
            self.failed.emit(f"无法加载 pyfluidsynth/FluidSynth：{exc}")
            return
        if not self.soundfont_path or not Path(self.soundfont_path).is_file():
            self.failed.emit("请先选择有效的 .sf2 SoundFont 音源")
            return

        synth = None
        audio_driver = None
        try:
            synth = fluidsynth.Synth()
            try:
                driver = "dsound" if os.name == "nt" else synth.get_setting("audio.driver")
                synth.setting("audio.driver", driver)
                audio_driver = fluidsynth.new_fluid_audio_driver(synth.settings, synth.synth)
            except Exception:
                synth.start()
            sfid = synth.sfload(self.soundfont_path)
            for idx, track in enumerate(self.tracks):
                channel = 9 if track.is_percussion or track.bdo_instrument_id == 0x0d else min(idx, 15)
                program = BDO_PREVIEW_PROGRAMS.get(track.bdo_instrument_id, track.gm_program)
                synth.program_select(channel, sfid, 128 if track.is_percussion or track.bdo_instrument_id == 0x0d else 0, program)

            events = []
            for idx, track in enumerate(self.tracks):
                channel = 9 if track.is_percussion or track.bdo_instrument_id == 0x0d else min(idx, 15)
                for note in track.notes:
                    velocity = max(1, min(127, round(note.vel * track.volume_scale)))
                    events.append((note.start / 1000.0, "on", channel, note.pitch, velocity))
                    events.append(((note.start + note.dur * track.duration_scale) / 1000.0, "off", channel, note.pitch, 0))
            events.sort(key=lambda item: item[0])

            started = time.monotonic()
            last_position_emit = 0.0
            for event_time, event_type, channel, pitch, velocity in events:
                if event_time < self.start_seconds:
                    continue
                while not self._stop:
                    if self._paused:
                        time.sleep(0.02)
                        continue
                    elapsed = self.start_seconds + time.monotonic() - started - self._paused_total
                    if elapsed - last_position_emit >= 0.04:
                        last_position_emit = elapsed
                        self.position_changed.emit(elapsed * 1000.0)
                    if elapsed >= event_time:
                        break
                    time.sleep(0.005)
                if self._stop:
                    break
                if event_type == "on":
                    synth.noteon(channel, pitch, velocity)
                else:
                    synth.noteoff(channel, pitch)
            self.position_changed.emit(max((event[0] for event in events), default=self.start_seconds) * 1000.0)
            time.sleep(0.2)
        except Exception as exc:
            self.failed.emit(f"试听失败：{exc}")
        finally:
            if synth is not None:
                try:
                    if audio_driver is not None:
                        fluidsynth.delete_fluid_audio_driver(audio_driver)
                    synth.delete()
                except Exception:
                    pass
            self.stopped.emit()


class SettingsDialog(QDialog):
    def __init__(self, parent: "MidiToBdoWindow") -> None:
        super().__init__(parent)
        self.setWindowTitle("转换设置")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        layout.addLayout(form)

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

        self.apply_sustain = QCheckBox("读取并展开 MIDI sustain 踏板")
        self.apply_sustain.setChecked(parent.apply_sustain)
        form.addRow("延音踏板", self.apply_sustain)

        self.flatten_tempo = QCheckBox("忽略中途 tempo 变化，按主 BPM 拉平")
        self.flatten_tempo.setChecked(parent.flatten_tempo)
        form.addRow("速度压平", self.flatten_tempo)

        vel_box = QFrame()
        vel_layout = QGridLayout(vel_box)
        vel_layout.setContentsMargins(0, 0, 0, 0)
        vel_layout.setHorizontalSpacing(12)
        vel_layout.setVerticalSpacing(6)
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
            vel_layout.addWidget(radio, 0, col)
        form.addRow("力度模式", vel_box)

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
        form.addRow("阶梯参数", step_row)

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
        form.addRow("重映射范围", range_row)

        self.vel_floor = QSpinBox()
        self.vel_floor.setRange(0, 127)
        self.vel_floor.setValue(parent.vel_floor or 36)
        form.addRow("抬底值", self.vel_floor)

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
        form.addRow("MIDI 效果", effect_row)

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
        form.addRow("合唱", chorus_row)

        hint = QLabel("这些是 midi-to-bdo 原有转换参数。FX 轨道效果仍只是预留，不写入 BDO。")
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_velocity_controls()

    def selected_velocity_mode(self) -> str:
        for mode, radio in self.vel_radios.items():
            if radio.isChecked():
                return mode
        return "layered"

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
        self.preview_worker: PreviewWorker | None = None
        self.preview_generation = 0
        self.last_output_dir = DEFAULT_OUTDIR
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
        self._try_auto_load_owner_id(show_errors=False)
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

        self.file_label = QLabel("未导入 MIDI")
        self.file_label.setObjectName("ToolbarText")
        layout.addWidget(self.file_label, stretch=1)

        self.output_name = QLineEdit()
        self.output_name.setPlaceholderText("曲谱名")
        self.output_name.setFixedWidth(170)
        layout.addWidget(self.output_name)

        self.owner_status = QLabel("Owner ID 未读取")
        self.owner_status.setObjectName("ToolbarBadge")
        layout.addWidget(self.owner_status)

        owner_btn = PillButton("Owner", "secondary")
        owner_btn.clicked.connect(lambda: self._try_auto_load_owner_id(show_errors=True))
        layout.addWidget(owner_btn)

        default_sf2 = str(DEFAULT_SOUNDFONT) if DEFAULT_SOUNDFONT.is_file() else ""
        self.soundfont_path = QLineEdit(self.config.get("soundfont_path", default_sf2))
        self.soundfont_path.setPlaceholderText("SoundFont .sf2")
        self.soundfont_path.setFixedWidth(140)
        layout.addWidget(self.soundfont_path)

        sf_btn = PillButton("音源", "secondary")
        sf_btn.clicked.connect(self._browse_soundfont)
        layout.addWidget(sf_btn)

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

        self.inspector_text = QLabel("选择轨道查看详情。右键轨道更换乐器。FX 为预留入口，当前不会写入 BDO 文件。")
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
            self.file_label.setText(Path(path).name)
            self.output_name.setText(Path(path).stem)
            self._load_midi_info(path)

    def _browse_soundfont(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 SoundFont 音源",
            str(ROOT),
            "SoundFont (*.sf2);;所有文件 (*.*)",
        )
        if path:
            self.soundfont_path.setText(path)
            self.config["soundfont_path"] = path
            save_config(self.config)
            self._sync_preview_state()

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
            <h2>MIDI 与试听</h2>
            <p><b>mido</b>：把 MIDI 音符一颗颗读出来、写回去。</p>
            <p><b>pyFluidSynth</b>：帮 Python 牵上线，让试听可以发出声音。</p>

            <h2>GitHub 开源项目</h2>
            <p><b>Bishop-R / midi-to-bdo</b>：感谢 midi-to-bdo 作者，提供 MIDI 转黑色沙漠曲谱格式的核心基础。</p>
            <p><b>Skyro468 / BDO-Music-Composer-Stuff</b>：感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。</p>
            <p><b>FluidSynth</b>：把 SoundFont 里的音色认真唱出来。</p>
            <p><b>GeneralUser GS FluidSynth</b>：提供内置预览音色，让试听不用空等。</p>

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

    def _load_owner_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择游戏内保存的单音符曲谱文件",
            str(default_game_music_dir()),
            "黑色沙漠曲谱文件 (*);;所有文件 (*.*)",
        )
        if path:
            self._set_owner_id_from_file(Path(path), "手动读取")

    def _set_owner_id_from_file(self, path: Path, source: str) -> None:
        try:
            owner_id, char_name = extract_owner_id(path)
        except Exception as exc:
            self.owner_status.setText(f"读取失败：{exc}")
            self.owner_id = 0
            return
        self.owner_id = owner_id
        if char_name:
            self.char_name = char_name
        self.owner_status.setText(f"{source}: 0x{owner_id:08x} · {char_name or '未知'}")

    def _try_auto_load_owner_id(self, show_errors: bool) -> None:
        try:
            path, owner_id, char_name = find_owner_id_file(default_game_music_dir())
        except Exception as exc:
            self.owner_id = 0
            self.owner_status.setText(f"Owner 获取失败")
            if show_errors:
                QMessageBox.warning(self, "自动获取失败", str(exc))
            return
        self.owner_id = owner_id
        if char_name:
            self.char_name = char_name
        self.owner_status.setText(f"Owner 0x{owner_id:08x} · {char_name or '未知'}")

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
    def _on_track_filter_changed(self) -> None:
        was_playing = bool(
            self.preview_worker
            and self.preview_worker.isRunning()
            and not self.preview_worker._paused
        )
        was_paused = bool(
            self.preview_worker
            and self.preview_worker.isRunning()
            and self.preview_worker._paused
        )
        current_ms = self.timeline.playhead_ms
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_generation += 1
            self.preview_worker.stop()
            self.preview_worker.wait(1500)
            self.preview_worker = None
        self._on_track_changed()
        if was_playing:
            self._start_preview_from(current_ms)
        elif was_paused:
            self.status_label.setText("试听暂停")
            self._sync_preview_state()

    def _on_preview_mapping_changed(self) -> None:
        was_playing = bool(
            self.preview_worker
            and self.preview_worker.isRunning()
            and not self.preview_worker._paused
        )
        was_paused = bool(
            self.preview_worker
            and self.preview_worker.isRunning()
            and self.preview_worker._paused
        )
        current_ms = self.timeline.playhead_ms
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_generation += 1
            self.preview_worker.stop()
            self.preview_worker.wait(1500)
            self.preview_worker = None
        self._on_track_changed()
        if was_playing:
            self._start_preview_from(current_ms)
        elif was_paused:
            self.status_label.setText("试听暂停")
            self._sync_preview_state()

    def _on_track_instrument_changed(self, track: TrackState) -> None:
        self._select_track(track)
        self._on_preview_mapping_changed()

    def _select_track(self, track: TrackState) -> None:
        self.selected_track = track
        self.timeline.set_selected_track(track)
        self.inspector_text.setText(
            f"{track.display_name} · {track.note_count} 音符 · {track.pitch_range} · "
            f"BDO: {BDO_INSTRUMENT_NAMES.get(track.bdo_instrument_id, track.bdo_instrument_id)} · 右键轨道更换乐器"
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
        self.inspector_text.setText(
            f"FX 预留：{track.display_name}。当前只保留轨道级/音符级效果入口，暂不写入 BDO 文件。"
        )

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
        has_sf2 = Path(self.soundfont_path.text()).is_file() if hasattr(self, "soundfont_path") else False
        running = bool(self.preview_worker and self.preview_worker.isRunning())
        paused = bool(running and self.preview_worker and self.preview_worker._paused)
        self.play_button.setEnabled(has_sf2 and bool(self.tracks) and (not running or paused))
        self.play_button.setText("播放" if has_sf2 else "选择音源后试听")
        self.pause_button.setEnabled(running and not paused)
        self.stop_button.setEnabled(running)

    def _play_preview(self) -> None:
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.resume()
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
        generation = self.preview_generation
        self.preview_worker = PreviewWorker(tracks, self.soundfont_path.text().strip(), start_ms=start_ms)
        self.preview_worker.failed.connect(lambda message, gen=generation: self._on_preview_failed(message, gen))
        self.preview_worker.stopped.connect(lambda gen=generation: self._on_preview_stopped(gen))
        self.preview_worker.position_changed.connect(lambda ms, gen=generation: self._on_preview_position(ms, gen))
        self.status_label.setText("试听播放")
        self.preview_worker.start()
        self._sync_preview_state()

    def _pause_preview(self) -> None:
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.pause()
            self.status_label.setText("试听暂停")
            self._sync_preview_state()

    def _stop_preview(self, reset_playhead: bool = False) -> None:
        self.preview_generation += 1
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.stop()
            self.preview_worker.wait(1500)
        self.preview_worker = None
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

    def _on_preview_stopped(self, generation: int | None = None) -> None:
        if generation is not None and generation != self.preview_generation:
            return
        self.preview_worker = None
        self._sync_preview_state()

    def _on_preview_position(self, ms: float, generation: int | None = None) -> None:
        if generation is not None and generation != self.preview_generation:
            return
        self.timeline.set_playhead(ms, follow=True)
        self._on_track_changed()

    def _seek_preview(self, ms: float) -> None:
        was_playing = bool(
            self.preview_worker
            and self.preview_worker.isRunning()
            and not self.preview_worker._paused
        )
        was_paused = bool(
            self.preview_worker
            and self.preview_worker.isRunning()
            and self.preview_worker._paused
        )
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_generation += 1
            self.preview_worker.stop()
            self.preview_worker.wait(1500)
            self.preview_worker = None
        self.timeline.set_playhead(ms, follow=True)
        if was_playing:
            self._start_preview_from(self.timeline.playhead_ms)
        elif was_paused:
            self.status_label.setText("试听暂停")
            self._sync_preview_state()

    def _open_settings(self) -> None:
        old_parse_settings = (self.apply_sustain, self.flatten_tempo)
        dialog = SettingsDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        self.char_name = dialog.char_name.text().strip() or "MIDI"
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
        full_export = (
            not has_duration_edits
            and len(active) == len(self.tracks)
            and all(not t.muted and not t.solo for t in self.tracks)
        )
        filtered_tracks = None if full_export else active
        export_tracks = self.tracks if filtered_tracks is None else active
        instrument_map = {idx: track.bdo_instrument_id for idx, track in enumerate(export_tracks)}
        vel_scales = {
            idx: track.volume_scale
            for idx, track in enumerate(export_tracks)
            if not math.isclose(track.volume_scale, 1.0)
        }
        return {
            "midi_path": midi_path,
            "filtered_tracks": filtered_tracks,
            "bpm_for_temp": self.bpm,
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
        self.worker = None

    def _on_convert_failed(self, message: str) -> None:
        self.convert_button.setEnabled(True)
        self.status_label.setText("转换失败")
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
        self._stop_preview()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MidiToBdoWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
