"""Lightweight transcription controls for the existing note editor.

These widgets deliberately do not own a transcription session, analysis
worker, transport, or piano roll.  The host ``MidiNoteEditorDialog`` remains
the source of view geometry and the main window remains the source of
transcription state.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import math
from typing import Iterable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from i18n import defer_tr, tr, trf, trfv, tr_joinv, trv


def _responsive_control_width(
    widget: QWidget,
    minimum: int,
    maximum: int,
) -> None:
    """Prefer translated content width but retain the compact two-row rail."""

    widget.setMinimumWidth(int(minimum))
    widget.setMaximumWidth(int(maximum))
    widget.setSizePolicy(
        QSizePolicy.Policy.Preferred,
        QSizePolicy.Policy.Fixed,
    )


def _value(item: object, name: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


_PITCH_CLASS_NAMES = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)


def _pitch_class_name(value: object) -> str:
    try:
        return _PITCH_CLASS_NAMES[int(value) % 12]
    except (TypeError, ValueError):
        return "—"


_VOICE_ROLE_SOURCES = {
    "primary_melody": "主旋律",
    "secondary_melody": "第二旋律",
    "harmony": "和声",
    "bass": "低音",
    "rhythm": "节奏",
    "percussion": "打击乐",
    "pad": "铺底",
    "ornament": "装饰",
    "fx": "效果",
}


def voice_role_source_label(value: object) -> str:
    return _VOICE_ROLE_SOURCES.get(str(value or ""), "声部")


def voice_role_label(value: object) -> str:
    return tr(voice_role_source_label(value))


def _as_percent(value: object) -> int:
    score = max(0.0, _finite_float(value))
    if score <= 1.0:
        score *= 100.0
    return min(100, round(score))


def _sequence(value: object) -> tuple[object, ...]:
    if value is None or isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return ()


class TranscriptionWaveformLane(QWidget):
    """A 72-pixel reference waveform aligned to an existing piano roll.

    The lane reads ``KEY_W``, ``scroll_ms`` and ``px_per_ms`` from ``canvas``
    at paint time.  It only paints the waveform buckets intersecting that
    viewport, using the reference controller's precomputed
    ``waveform_starts`` index.
    """

    seek_requested = Signal(float)

    HEIGHT = 72
    _MAX_BUCKETS_PER_PIXEL = 2

    def __init__(self, canvas: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionWaveformLane")
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(320)
        self.setMouseTracking(True)
        self._canvas = canvas
        self._reference_audio: object | None = None
        self._source_connections: list[tuple[object, object]] = []
        self._fallback_audio_offset_ms = 0.0
        self._playhead_ms: float | None = None
        self._time_range: tuple[float, float] | None = None

    @property
    def reference_audio(self) -> object | None:
        return self._reference_audio

    @property
    def playhead_ms(self) -> float:
        if self._playhead_ms is not None:
            return self._playhead_ms
        return _finite_float(getattr(self._canvas, "playhead_ms", 0.0))

    @property
    def time_range(self) -> tuple[float, float] | None:
        return self._time_range

    def sizeHint(self) -> QSize:
        return QSize(720, self.HEIGHT)

    def set_reference_audio(self, controller: object | None) -> None:
        if controller is self._reference_audio:
            self.update()
            return
        self._disconnect_reference_audio()
        self._reference_audio = controller
        if controller is not None:
            for signal_name in (
                "changed",
                "timeline_changed",
                "file_changed",
                "offset_changed",
            ):
                signal = getattr(controller, signal_name, None)
                if signal is None or not hasattr(signal, "connect"):
                    continue
                slot = self._reference_audio_changed
                try:
                    signal.connect(slot)
                except (RuntimeError, TypeError):
                    continue
                self._source_connections.append((signal, slot))
        self.update()

    def release_reference_audio(self) -> None:
        """Detach controller signals without affecting playback or decoding."""
        self._disconnect_reference_audio()
        self._reference_audio = None
        self.update()

    def _disconnect_reference_audio(self) -> None:
        for signal, slot in self._source_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._source_connections.clear()

    def _reference_audio_changed(self, *_args: object) -> None:
        self.update()

    def set_audio_offset_ms(self, offset_ms: float) -> None:
        """Set the conversion fallback used by controller-free test adapters."""
        normalized = _finite_float(offset_ms)
        if math.isclose(
            normalized,
            self._fallback_audio_offset_ms,
            abs_tol=0.001,
        ):
            return
        self._fallback_audio_offset_ms = normalized
        self.update()

    def set_playhead_ms(self, playhead_ms: float | None) -> None:
        normalized = (
            None if playhead_ms is None else _finite_float(playhead_ms)
        )
        if normalized == self._playhead_ms:
            return
        old_playhead = self.playhead_ms
        self._playhead_ms = normalized
        key_width, view_start, _view_end, px_per_ms = (
            self._view_geometry()
        )
        for position in (old_playhead, self.playhead_ms):
            x = key_width + (position - view_start) * px_per_ms
            if key_width - 3.0 <= x <= self.width() + 3.0:
                self.update(
                    QRectF(
                        x - 3.0,
                        0.0,
                        7.0,
                        float(self.height()),
                    ).toAlignedRect()
                )

    def set_time_range(
        self,
        time_range: tuple[float, float] | None,
    ) -> None:
        normalized: tuple[float, float] | None = None
        if time_range is not None:
            start = _finite_float(time_range[0])
            end = _finite_float(time_range[1])
            if end > start:
                normalized = (start, end)
        if normalized == self._time_range:
            return
        self._time_range = normalized
        self.update()

    def refresh(self) -> None:
        self.update()

    def _view_geometry(self) -> tuple[float, float, float, float]:
        key_width = max(0.0, _finite_float(getattr(self._canvas, "KEY_W", 0.0)))
        view_start = _finite_float(getattr(self._canvas, "scroll_ms", 0.0))
        px_per_ms = max(
            1e-9,
            _finite_float(getattr(self._canvas, "px_per_ms", 0.0), 1e-9),
        )
        drawable_width = max(0.0, float(self.width()) - key_width)
        view_end = view_start + drawable_width / px_per_ms
        return key_width, view_start, view_end, px_per_ms

    def _project_to_audio(self, project_ms: float) -> float:
        converter = getattr(self._reference_audio, "project_to_audio", None)
        if callable(converter):
            try:
                return _finite_float(converter(project_ms))
            except (RuntimeError, TypeError, ValueError):
                pass
        return project_ms - self._fallback_audio_offset_ms

    def _audio_to_project(self, audio_ms: float) -> float:
        converter = getattr(self._reference_audio, "audio_to_project", None)
        if callable(converter):
            try:
                return _finite_float(converter(audio_ms))
            except (RuntimeError, TypeError, ValueError):
                pass
        return audio_ms + self._fallback_audio_offset_ms

    def _visible_waveform(
        self,
        view_start: float,
        view_end: float,
    ) -> Sequence[object]:
        controller = self._reference_audio
        waveform = _value(controller, "waveform", ()) if controller else ()
        starts = (
            _value(controller, "waveform_starts", ()) if controller else ()
        )
        if not waveform or not starts:
            return ()
        audio_start = self._project_to_audio(view_start)
        audio_end = self._project_to_audio(view_end)
        if audio_end < audio_start:
            audio_start, audio_end = audio_end, audio_start
        first = max(0, bisect_left(starts, audio_start) - 1)
        last = min(len(waveform), bisect_right(starts, audio_end))
        if last <= first:
            return ()
        return waveform[first:last]

    @staticmethod
    def _bucket_parts(bucket: object) -> tuple[float, float, float] | None:
        try:
            start, end, peak = bucket  # type: ignore[misc]
        except (TypeError, ValueError):
            return None
        start_ms = _finite_float(start)
        end_ms = _finite_float(end)
        amplitude = max(0.0, min(1.0, _finite_float(peak)))
        if end_ms <= start_ms:
            return None
        return start_ms, end_ms, amplitude

    def _iter_paint_buckets(
        self,
        visible: Sequence[object],
        waveform_width: float,
    ) -> Iterable[tuple[float, float, float]]:
        max_bars = max(
            1,
            round(waveform_width) * self._MAX_BUCKETS_PER_PIXEL,
        )
        stride = max(1, math.ceil(len(visible) / max_bars))
        if stride == 1:
            for bucket in visible:
                parts = self._bucket_parts(bucket)
                if parts is not None:
                    yield parts
            return
        for index in range(0, len(visible), stride):
            group = visible[index : index + stride]
            valid = [
                parts
                for parts in map(self._bucket_parts, group)
                if parts is not None
            ]
            if not valid:
                continue
            yield (
                valid[0][0],
                valid[-1][1],
                max(item[2] for item in valid),
            )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        key_width, view_start, view_end, px_per_ms = self._view_geometry()
        full = QRectF(self.rect())
        header = QRectF(0.0, 0.0, key_width, full.height())
        waveform_rect = QRectF(
            key_width,
            0.0,
            max(0.0, full.width() - key_width),
            full.height(),
        )

        painter.fillRect(full, QColor("#171817"))
        painter.fillRect(header, QColor("#252320"))
        painter.fillRect(QRectF(0.0, 0.0, 4.0, full.height()), QColor("#d39a42"))
        painter.setPen(QPen(QColor("#4c463b"), 1))
        painter.drawLine(
            QPointF(key_width, 0.0),
            QPointF(key_width, full.height()),
        )
        painter.drawLine(
            QPointF(0.0, full.height() - 1.0),
            QPointF(full.width(), full.height() - 1.0),
        )

        painter.setPen(QColor("#f3f1ea"))
        painter.drawText(
            QRectF(9.0, 7.0, max(0.0, key_width - 14.0), 20.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            tr("参考音频"),
        )
        controller = self._reference_audio
        audio_path = str(_value(controller, "audio_path", "") or "")
        loading = bool(_value(controller, "waveform_loading", False))
        display_name = str(
            _value(controller, "display_name", "") or tr("未载入参考音频")
        )
        painter.setPen(QColor("#aaa39b"))
        painter.drawText(
            QRectF(9.0, 31.0, max(0.0, key_width - 14.0), 30.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(
                tr("正在分析波形…") if loading else display_name,
                Qt.ElideMiddle,
                max(1, round(key_width - 14.0)),
            ),
        )

        painter.save()
        painter.setClipRect(waveform_rect)
        if self._time_range is not None:
            range_start, range_end = self._time_range
            start_x = key_width + (range_start - view_start) * px_per_ms
            end_x = key_width + (range_end - view_start) * px_per_ms
            selection = QRectF(
                min(start_x, end_x),
                0.0,
                abs(end_x - start_x),
                full.height(),
            ).intersected(waveform_rect)
            painter.fillRect(selection, QColor(245, 165, 36, 24))
            painter.setPen(QPen(QColor("#f5a524"), 1))
            painter.drawLine(
                QPointF(start_x, 0.0),
                QPointF(start_x, full.height()),
            )
            painter.drawLine(
                QPointF(end_x, 0.0),
                QPointF(end_x, full.height()),
            )

        damage = _event.rect()
        damage_left = max(
            waveform_rect.left(),
            float(damage.left()) - 1.0,
        )
        damage_right = min(
            waveform_rect.right(),
            float(damage.right()) + 1.0,
        )
        if damage_right <= damage_left:
            visible = ()
        else:
            waveform_view_start = max(
                view_start,
                view_start
                + (damage_left - key_width) / px_per_ms,
            )
            waveform_view_end = min(
                view_end,
                view_start
                + (damage_right - key_width) / px_per_ms,
            )
            visible = self._visible_waveform(
                waveform_view_start,
                waveform_view_end,
            )
        if visible:
            center = waveform_rect.center().y()
            half = max(2.0, waveform_rect.height() / 2.0 - 8.0)
            bars: list[QRectF] = []
            for audio_start, audio_end, peak in self._iter_paint_buckets(
                visible,
                waveform_rect.width(),
            ):
                project_start = self._audio_to_project(audio_start)
                project_end = self._audio_to_project(audio_end)
                if project_end < view_start or project_start > view_end:
                    continue
                x = key_width + (project_start - view_start) * px_per_ms
                width = max(1.0, (project_end - project_start) * px_per_ms)
                amplitude = max(1.0, peak * half)
                bars.append(
                    QRectF(x, center - amplitude, width, amplitude * 2.0)
                )
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#d7a34c"))
            if bars:
                painter.drawRects(bars)
        else:
            painter.setPen(QColor("#817665"))
            placeholder = (
                tr("正在分析波形…")
                if loading
                else tr("载入 MP3/WAV 后显示波形")
            )
            painter.drawText(waveform_rect, Qt.AlignCenter, placeholder)

        playhead_x = key_width + (self.playhead_ms - view_start) * px_per_ms
        if waveform_rect.left() <= playhead_x <= waveform_rect.right():
            painter.fillRect(
                QRectF(
                    playhead_x,
                    waveform_rect.top(),
                    1.5,
                    waveform_rect.height(),
                ),
                QColor("#f4e3bd"),
            )
        painter.restore()

        if not audio_path:
            painter.fillRect(waveform_rect, QColor(0, 0, 0, 18))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            key_width, view_start, _view_end, px_per_ms = (
                self._view_geometry()
            )
            if event.position().x() >= key_width:
                target = max(
                    0.0,
                    view_start
                    + (event.position().x() - key_width) / px_per_ms,
                )
                self.set_playhead_ms(target)
                self.seek_requested.emit(target)
                event.accept()
                return
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:
        self.release_reference_audio()
        super().closeEvent(event)


class _ElidedStatusLabel(QLabel):
    """Keep detailed status accessible while drawing a compact one-line rail."""

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(260, hint.width()), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(96, hint.width()), hint.height())

    def setText(self, text: str) -> None:
        value = str(text)
        super().setText(value)
        self.setToolTip(value)

    def paintEvent(self, event: QPaintEvent) -> None:
        text = self.text()
        rect = self.contentsRect()
        if self.fontMetrics().horizontalAdvance(text) <= rect.width():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(
            self.palette().color(QPalette.ColorRole.WindowText)
        )
        painter.drawText(
            rect,
            self.alignment(),
            self.fontMetrics().elidedText(
                text,
                Qt.TextElideMode.ElideRight,
                max(0, rect.width()),
            ),
        )


class TranscriptionHarmonySummary(QWidget):
    """Compact, model-agnostic key and chord summary.

    The host owns editing and persistence.  This widget only renders objects
    exposing the planned harmony attributes and emits intent signals.
    """

    key_edit_requested = Signal(object)
    key_lock_requested = Signal(bool)
    chord_edit_requested = Signal(str)
    chord_lock_requested = Signal(str, bool)
    chord_split_requested = Signal(str)
    chord_merge_next_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionHarmonySummary")
        self._analysis: object | None = None
        self._global_key: object | None = None
        self._segments: tuple[object, ...] = ()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 4)
        layout.setSpacing(5)

        layout.addWidget(QLabel(tr("主调"), self))
        self.key_label = QLabel("—", self)
        self.key_label.setObjectName("TranscriptionKeySummary")
        self.key_label.setMinimumWidth(92)
        layout.addWidget(self.key_label)
        self.key_edit_button = QPushButton(tr("编辑"), self)
        self.key_edit_button.clicked.connect(self._emit_key_edit)
        layout.addWidget(self.key_edit_button)
        self.key_lock_checkbox = QCheckBox(tr("锁定"), self)
        self.key_lock_checkbox.toggled.connect(self.key_lock_requested)
        layout.addWidget(self.key_lock_checkbox)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.VLine)
        separator.setObjectName("Muted")
        layout.addWidget(separator)

        layout.addWidget(QLabel(tr("和弦段"), self))
        self.segment_combo = QComboBox(self)
        # Chord/time summaries are analysis data, not UI source strings.
        self.segment_combo.setProperty("i18nSkipItems", True)
        self.segment_combo.setMinimumWidth(190)
        self.segment_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.segment_combo.setMinimumContentsLength(18)
        self.segment_combo.currentIndexChanged.connect(
            self._segment_changed,
        )
        layout.addWidget(self.segment_combo, 1)
        self.conflict_label = QLabel(tr("无冲突"), self)
        self.conflict_label.setObjectName("Muted")
        layout.addWidget(self.conflict_label)
        self.chord_edit_button = QPushButton(tr("编辑段"), self)
        self.chord_edit_button.clicked.connect(self._emit_chord_edit)
        layout.addWidget(self.chord_edit_button)
        self.chord_split_button = QPushButton(tr("拆分"), self)
        self.chord_split_button.clicked.connect(self._emit_chord_split)
        layout.addWidget(self.chord_split_button)
        self.chord_merge_button = QPushButton(tr("合并下一段"), self)
        self.chord_merge_button.clicked.connect(
            self._emit_chord_merge_next
        )
        layout.addWidget(self.chord_merge_button)
        self.chord_lock_checkbox = QCheckBox(tr("锁定"), self)
        self.chord_lock_checkbox.toggled.connect(self._emit_chord_lock)
        layout.addWidget(self.chord_lock_checkbox)
        self.clear()

    @property
    def analysis(self) -> object | None:
        return self._analysis

    @property
    def current_segment_id(self) -> str:
        data = self.segment_combo.currentData()
        return "" if data is None else str(data)

    def clear(self) -> None:
        self.set_harmony(None)

    def set_harmony(self, analysis: object | None) -> None:
        """Render a ``HarmonyAnalysis``-like object or mapping."""
        self._analysis = analysis
        self._global_key = _value(analysis, "global_key") if analysis else None
        self._segments = _sequence(
            _value(analysis, "chord_segments", ()) if analysis else ()
        )
        conflicts = _sequence(
            _value(analysis, "conflicts", ()) if analysis else ()
        )

        if self._global_key is None:
            self.key_label.setText("—")
            self.key_label.setToolTip("")
        else:
            self.key_label.setText(self._format_key(self._global_key))
            alternatives = _sequence(
                _value(self._global_key, "alternatives", ())
            )
            self.key_label.setToolTip(
                trf(
                    "备选：{alternatives}",
                    alternatives=" · ".join(
                        self._format_key(item, include_confidence=False)
                        for item in alternatives[:3]
                    ),
                )
                if alternatives
                else ""
            )

        key_locked = bool(
            _value(
                analysis,
                "key_locked",
                _value(self._global_key, "locked", False),
            )
        )
        blocked = self.key_lock_checkbox.blockSignals(True)
        self.key_lock_checkbox.setChecked(key_locked)
        self.key_lock_checkbox.blockSignals(blocked)

        previous_id = self.current_segment_id
        blocked = self.segment_combo.blockSignals(True)
        self.segment_combo.clear()
        for segment in self._segments:
            segment_id = str(_value(segment, "segment_id", ""))
            self.segment_combo.addItem(
                self._format_segment(segment),
                segment_id,
            )
        if previous_id:
            index = self.segment_combo.findData(previous_id)
            if index >= 0:
                self.segment_combo.setCurrentIndex(index)
        self.segment_combo.blockSignals(blocked)

        self.conflict_label.setText(
            trf("{count} 个冲突", count=len(conflicts))
            if conflicts
            else tr("无冲突")
        )
        self.conflict_label.setProperty("warning", bool(conflicts))
        available = self._global_key is not None
        segment_available = bool(self._segments)
        self.key_edit_button.setEnabled(available)
        self.key_lock_checkbox.setEnabled(available)
        self.segment_combo.setEnabled(segment_available)
        self.chord_edit_button.setEnabled(segment_available)
        self.chord_split_button.setEnabled(segment_available)
        self.chord_lock_checkbox.setEnabled(segment_available)
        self._segment_changed(self.segment_combo.currentIndex())

    def set_current_segment(self, segment_id: object) -> None:
        index = self.segment_combo.findData(str(segment_id))
        if index >= 0:
            self.segment_combo.setCurrentIndex(index)

    @staticmethod
    def _format_key(
        key: object,
        *,
        include_confidence: bool = True,
    ) -> str:
        explicit = str(_value(key, "display_label", "") or "")
        if explicit:
            label = explicit
        else:
            root = _pitch_class_name(_value(key, "root_pc"))
            mode = str(_value(key, "mode", "") or "")
            label = f"{root} {mode}".strip()
        if include_confidence:
            label += f"  {_as_percent(_value(key, 'confidence'))}%"
        return label

    @staticmethod
    def _format_segment(segment: object) -> str:
        explicit = str(_value(segment, "display_label", "") or "")
        if explicit:
            chord = explicit
        else:
            root_pc = _value(segment, "root_pc")
            root = _pitch_class_name(root_pc)
            quality = str(_value(segment, "quality", "") or "")
            chord = "N" if quality.upper() == "N" or root == "—" else (
                f"{root} {quality}".strip()
            )
            bass_pc = _value(segment, "bass_pc")
            if bass_pc is not None:
                bass = _pitch_class_name(bass_pc)
                if bass != "—" and bass != root:
                    chord += f"/{bass}"
        start = _finite_float(_value(segment, "start_audio_ms"))
        end = _finite_float(_value(segment, "end_audio_ms"))
        span = f"{start / 1000.0:.1f}–{end / 1000.0:.1f}s"
        return (
            f"{chord}  ·  {span}  ·  "
            f"{_as_percent(_value(segment, 'confidence'))}%"
        )

    def _segment_changed(self, index: int) -> None:
        segment = (
            self._segments[index]
            if 0 <= index < len(self._segments)
            else None
        )
        blocked = self.chord_lock_checkbox.blockSignals(True)
        self.chord_lock_checkbox.setChecked(
            bool(_value(segment, "locked", False))
        )
        self.chord_lock_checkbox.blockSignals(blocked)
        self.chord_merge_button.setEnabled(
            segment is not None and index + 1 < len(self._segments)
        )

    def _emit_key_edit(self) -> None:
        if self._global_key is not None:
            self.key_edit_requested.emit(self._global_key)

    def _emit_chord_edit(self) -> None:
        segment_id = self.current_segment_id
        if segment_id:
            self.chord_edit_requested.emit(segment_id)

    def _emit_chord_lock(self, locked: bool) -> None:
        segment_id = self.current_segment_id
        if segment_id:
            self.chord_lock_requested.emit(segment_id, bool(locked))

    def _emit_chord_split(self) -> None:
        segment_id = self.current_segment_id
        if segment_id:
            self.chord_split_requested.emit(segment_id)

    def _emit_chord_merge_next(self) -> None:
        segment_id = self.current_segment_id
        if segment_id:
            self.chord_merge_next_requested.emit(segment_id)


class TranscriptionPhraseReviewControls(QWidget):
    """Navigation-only controls that reuse the host's existing A–B loop."""

    previous_phrase_requested = Signal()
    next_phrase_requested = Signal()
    loop_phrase_requested = Signal(bool)
    review_queue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionPhraseReviewControls")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 3, 7, 3)
        layout.setSpacing(5)

        self.previous_button = QPushButton(tr("上一乐句"), self)
        self.previous_button.clicked.connect(self.previous_phrase_requested)
        layout.addWidget(self.previous_button)
        self.next_button = QPushButton(tr("下一乐句"), self)
        self.next_button.clicked.connect(self.next_phrase_requested)
        layout.addWidget(self.next_button)
        self.loop_button = QToolButton(self)
        self.loop_button.setText(tr("循环当前乐句"))
        self.loop_button.setCheckable(True)
        self.loop_button.toggled.connect(self.loop_phrase_requested)
        layout.addWidget(self.loop_button)
        self.phrase_label = QLabel(tr("尚无乐句"), self)
        self.phrase_label.setObjectName("Muted")
        layout.addWidget(self.phrase_label)
        layout.addStretch(1)
        self.review_queue_button = QPushButton(tr("待审 0"), self)
        self.review_queue_button.clicked.connect(self.review_queue_requested)
        layout.addWidget(self.review_queue_button)
        self.set_state()

    def set_state(
        self,
        *,
        index: int = -1,
        total: int = 0,
        loop_enabled: bool = False,
        review_count: int = 0,
    ) -> None:
        total = max(0, int(total))
        index = max(-1, min(int(index), total - 1))
        has_phrase = total > 0 and index >= 0
        self.previous_button.setEnabled(has_phrase and index > 0)
        self.next_button.setEnabled(has_phrase and index + 1 < total)
        self.loop_button.setEnabled(has_phrase)
        blocked = self.loop_button.blockSignals(True)
        self.loop_button.setChecked(bool(loop_enabled and has_phrase))
        self.loop_button.blockSignals(blocked)
        self.phrase_label.setText(
            trf("乐句 {current}/{total}", current=index + 1, total=total)
            if has_phrase
            else tr("尚无乐句")
        )
        review_count = max(0, int(review_count))
        self.review_queue_button.setText(
            trf("待审 {count}", count=review_count)
        )
        self.review_queue_button.setEnabled(review_count > 0)


class _InstrumentMatchCard(QFrame):
    selected = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._match: object | None = None
        self.setObjectName("TranscriptionInstrumentMatchCard")
        self.setProperty("selected", False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)
        self.select_button = QToolButton(self)
        self.select_button.setCheckable(True)
        self.select_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.select_button.clicked.connect(
            lambda: self.selected.emit(self._index)
        )
        layout.addWidget(self.select_button)
        self.coverage_label = QLabel("", self)
        self.coverage_label.setObjectName("Muted")
        layout.addWidget(self.coverage_label)
        self.reason_label = QLabel("", self)
        self.reason_label.setObjectName("Muted")
        self.reason_label.setWordWrap(False)
        layout.addWidget(self.reason_label)
        self.warning_label = QLabel("", self)
        self.warning_label.setObjectName("Warning")
        self.warning_label.setWordWrap(False)
        layout.addWidget(self.warning_label)
        self.hide()

    @property
    def match(self) -> object | None:
        return self._match

    def set_match(self, match: object | None) -> None:
        self._match = match
        if match is None:
            self.hide()
            return
        instrument_id = int(_value(match, "instrument_id", -1))
        name = _value(
            match,
            "instrument_name",
            trfv("BDO 乐器 {instrument_id}", instrument_id=instrument_id),
        )
        score = _as_percent(_value(match, "total_score"))
        coverage = _as_percent(_value(match, "pitch_coverage"))
        self.select_button.setText(trf(
            "{instrument}  {score}%",
            instrument=name,
            score=score,
        ))
        self.coverage_label.setText(
            trf("音域覆盖 {coverage}%", coverage=coverage)
        )
        reasons = _sequence(_value(match, "reasons", ()))
        warnings = _sequence(
            _value(match, "warnings", _value(match, "limitations", ()))
        )
        summary = (
            tr_joinv(reasons[:2], " · ")
            if reasons
            else trv("等待匹配理由")
        )
        self.reason_label.setText(trf("{summary}", summary=summary))
        self.warning_label.setText(
            trf("可能不适合：{reason}", reason=warnings[0])
            if warnings
            else tr("未发现明显硬性冲突")
        )
        tooltip_parts = (*reasons, *warnings)
        self.setToolTip(trf(
            "{details}",
            details=tr_joinv(tooltip_parts, "\n"),
        ))
        self.show()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        blocked = self.select_button.blockSignals(True)
        self.select_button.setChecked(bool(selected))
        self.select_button.blockSignals(blocked)
        self.style().unpolish(self)
        self.style().polish(self)


class TranscriptionInstrumentMatches(QWidget):
    """Top-three BDO suggestions for one host-selected voice group."""

    confirm_match_requested = Signal(object, int)
    stage_existing_track_requested = Signal(object, int)
    new_track_requested = Signal(object, int)
    audition_source_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionInstrumentMatches")
        self._voice_group: object | None = None
        self._matches: tuple[object, ...] = ()
        self._selected_index = -1
        self._confirmed_instrument_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 4, 7, 5)
        root.setSpacing(4)
        heading = QHBoxLayout()
        self.group_label = QLabel(tr("未选择声部组"), self)
        self.group_label.setObjectName("TranscriptionVoiceGroupSummary")
        heading.addWidget(self.group_label)
        heading.addStretch(1)
        heading.addWidget(QLabel(tr("试听源"), self))
        self.source_combo = QComboBox(self)
        self.source_combo.addItem(tr("工程 + 原音"), "combined")
        self.source_combo.addItem(tr("原音"), "original")
        self.source_combo.addItem(tr("游戏候选 A"), "candidate_a")
        self.source_combo.addItem(tr("游戏候选 B"), "candidate_b")
        self.source_combo.currentIndexChanged.connect(
            self._source_changed,
        )
        heading.addWidget(self.source_combo)
        root.addLayout(heading)

        cards = QHBoxLayout()
        cards.setSpacing(5)
        self.cards = tuple(
            _InstrumentMatchCard(index, self) for index in range(3)
        )
        for card in self.cards:
            card.selected.connect(self._select_index)
            cards.addWidget(card, 1)
        root.addLayout(cards)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.confirm_button = QPushButton(tr("确认匹配"), self)
        self.confirm_button.clicked.connect(self._confirm)
        actions.addWidget(self.confirm_button)
        self.stage_button = QPushButton(tr("暂存到现有轨"), self)
        self.stage_button.clicked.connect(self._stage)
        actions.addWidget(self.stage_button)
        self.new_track_button = QPushButton(tr("新建该乐器轨"), self)
        self.new_track_button.clicked.connect(self._new_track)
        actions.addWidget(self.new_track_button)
        root.addLayout(actions)
        self.clear()

    @property
    def voice_group(self) -> object | None:
        return self._voice_group

    @property
    def matches(self) -> tuple[object, ...]:
        return self._matches

    @property
    def selected_match(self) -> object | None:
        if 0 <= self._selected_index < len(self._matches):
            return self._matches[self._selected_index]
        return None

    def clear(self) -> None:
        self.set_matches(None, ())

    def set_matches(
        self,
        voice_group: object | None,
        matches: Iterable[object],
        *,
        confirmed_instrument_id: int | None = None,
    ) -> None:
        self._voice_group = voice_group
        self._matches = tuple(matches)[:3]
        self._confirmed_instrument_id = (
            None
            if confirmed_instrument_id is None
            else int(confirmed_instrument_id)
        )
        group_id = _value(voice_group, "group_id", "")
        role = trv(voice_role_source_label(_value(voice_group, "role", "")))
        confirmed_outside_top_three = (
            voice_group is not None
            and self._confirmed_instrument_id is not None
            and all(
                int(_value(match, "instrument_id", -1))
                != self._confirmed_instrument_id
                for match in self._matches
            )
        )
        if voice_group is None:
            self.group_label.setText(tr("未选择声部组"))
        elif confirmed_outside_top_three:
            self.group_label.setText(trf(
                "声部 {group_id} · {role} · 已确认 0x{instrument_id:02X}（不在当前 Top-3）",
                group_id=group_id,
                role=role,
                instrument_id=self._confirmed_instrument_id,
            ))
        else:
            self.group_label.setText(trf(
                "声部 {group_id} · {role}",
                group_id=group_id,
                role=role,
            ))
        for index, card in enumerate(self.cards):
            card.set_match(
                self._matches[index]
                if index < len(self._matches)
                else None
            )
        confirmed_index = next(
            (
                index
                for index, match in enumerate(self._matches)
                if confirmed_instrument_id is not None
                and int(_value(match, "instrument_id", -1))
                == int(confirmed_instrument_id)
            ),
            -1,
        )
        self._select_index(
            confirmed_index
            if confirmed_index >= 0
            else (0 if self._matches else -1)
        )
        available = voice_group is not None and bool(self._matches)
        for source, minimum_matches in (
            ("candidate_a", 1),
            ("candidate_b", 2),
        ):
            index = self.source_combo.findData(source)
            item = self.source_combo.model().item(index)
            if item is not None:
                item.setEnabled(
                    voice_group is not None
                    and len(self._matches) >= minimum_matches
                )
        if (
            self.source_combo.currentData()
            in {"candidate_a", "candidate_b"}
            and not available
        ):
            self.source_combo.setCurrentIndex(
                self.source_combo.findData("combined")
            )
        self.source_combo.setEnabled(True)
        self.confirm_button.setEnabled(available)
        self.stage_button.setEnabled(available)
        self.new_track_button.setEnabled(available)
        self._refresh_confirm_button()

    def _select_index(self, index: int) -> None:
        self._selected_index = (
            index if 0 <= index < len(self._matches) else -1
        )
        for card_index, card in enumerate(self.cards):
            card.set_selected(card_index == self._selected_index)
        self._refresh_confirm_button()

    def _refresh_confirm_button(self) -> None:
        match = self.selected_match
        selected_id = (
            int(_value(match, "instrument_id", -1))
            if match is not None
            else -1
        )
        self.confirm_button.setText(
            tr("已确认匹配")
            if (
                self._confirmed_instrument_id is not None
                and selected_id == self._confirmed_instrument_id
            )
            else tr("确认匹配")
        )

    def _selection_identity(self) -> tuple[object, int] | None:
        match = self.selected_match
        if self._voice_group is None or match is None:
            return None
        group_id = _value(self._voice_group, "group_id", "")
        try:
            instrument_id = int(_value(match, "instrument_id", -1))
        except (TypeError, ValueError):
            return None
        if instrument_id < 0:
            return None
        return group_id, instrument_id

    def _confirm(self) -> None:
        identity = self._selection_identity()
        if identity is not None:
            self.confirm_match_requested.emit(*identity)

    def _stage(self) -> None:
        identity = self._selection_identity()
        if identity is not None:
            self.stage_existing_track_requested.emit(*identity)

    def _new_track(self) -> None:
        identity = self._selection_identity()
        if identity is not None:
            self.new_track_requested.emit(*identity)

    def _source_changed(self, _index: int) -> None:
        source = self.source_combo.currentData()
        if source is not None:
            self.audition_source_changed.emit(str(source))


class TranscriptionAssistPanel(QFrame):
    """Embeddable semantic-review UI with no session, worker or transport."""

    key_edit_requested = Signal(object)
    key_lock_requested = Signal(bool)
    chord_edit_requested = Signal(str)
    chord_lock_requested = Signal(str, bool)
    chord_split_requested = Signal(str)
    chord_merge_next_requested = Signal(str)
    previous_phrase_requested = Signal()
    next_phrase_requested = Signal()
    loop_phrase_requested = Signal(bool)
    review_queue_requested = Signal()
    confirm_match_requested = Signal(object, int)
    stage_existing_track_requested = Signal(object, int)
    new_track_requested = Signal(object, int)
    audition_source_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionAssistPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.phrase_controls = TranscriptionPhraseReviewControls(self)
        self.harmony_summary = TranscriptionHarmonySummary(self)
        self.instrument_matches = TranscriptionInstrumentMatches(self)
        root.addWidget(self.phrase_controls)
        root.addWidget(self.harmony_summary)
        root.addWidget(self.instrument_matches)

        self.harmony_summary.key_edit_requested.connect(
            self.key_edit_requested
        )
        self.harmony_summary.key_lock_requested.connect(
            self.key_lock_requested
        )
        self.harmony_summary.chord_edit_requested.connect(
            self.chord_edit_requested
        )
        self.harmony_summary.chord_lock_requested.connect(
            self.chord_lock_requested
        )
        self.harmony_summary.chord_split_requested.connect(
            self.chord_split_requested
        )
        self.harmony_summary.chord_merge_next_requested.connect(
            self.chord_merge_next_requested
        )
        self.phrase_controls.previous_phrase_requested.connect(
            self.previous_phrase_requested
        )
        self.phrase_controls.next_phrase_requested.connect(
            self.next_phrase_requested
        )
        self.phrase_controls.loop_phrase_requested.connect(
            self.loop_phrase_requested
        )
        self.phrase_controls.review_queue_requested.connect(
            self.review_queue_requested
        )
        self.instrument_matches.confirm_match_requested.connect(
            self.confirm_match_requested
        )
        self.instrument_matches.stage_existing_track_requested.connect(
            self.stage_existing_track_requested
        )
        self.instrument_matches.new_track_requested.connect(
            self.new_track_requested
        )
        self.instrument_matches.audition_source_changed.connect(
            self.audition_source_changed
        )

    def set_harmony(self, analysis: object | None) -> None:
        self.harmony_summary.set_harmony(analysis)

    def set_phrase_state(self, **state: object) -> None:
        self.phrase_controls.set_state(
            index=int(state.get("index", -1)),
            total=int(state.get("total", 0)),
            loop_enabled=bool(state.get("loop_enabled", False)),
            review_count=int(state.get("review_count", 0)),
        )

    def set_voice_group_matches(
        self,
        voice_group: object | None,
        matches: Iterable[object],
        *,
        confirmed_instrument_id: int | None = None,
    ) -> None:
        self.instrument_matches.set_matches(
            voice_group,
            matches,
            confirmed_instrument_id=confirmed_instrument_id,
        )

    def clear(self) -> None:
        self.harmony_summary.clear()
        self.phrase_controls.set_state()
        self.instrument_matches.clear()


class TranscriptionEditorPanel(QWidget):
    """Signal-only analysis and review controls for ``MidiNoteEditorDialog``."""

    load_audio_requested = Signal()
    unload_audio_requested = Signal()
    analyze_requested = Signal()
    redecode_requested = Signal()
    analysis_mode_changed = Signal(str)
    sensitivity_changed = Signal(str)
    cleanup_profile_changed = Signal(str)
    confidence_changed = Signal(float)
    show_rejected_changed = Signal(bool)
    show_suppressed_changed = Signal(bool)
    select_fragments_requested = Signal()
    frame_visibility_changed = Signal(bool)
    onset_visibility_changed = Signal(bool)
    contour_visibility_changed = Signal(bool)
    melody_lines_visibility_changed = Signal(bool)
    melody_line_roles_changed = Signal(object)
    spectrogram_visibility_changed = Signal(bool)
    reference_background_opacity_changed = Signal(float)
    evidence_layers_changed = Signal(object)
    align_audio_requested = Signal()
    beat_origin_requested = Signal()
    clear_range_requested = Signal()
    review_undo_requested = Signal()
    review_redo_requested = Signal()
    reject_requested = Signal()
    restore_requested = Signal()
    write_current_track_requested = Signal()
    copy_to_track_requested = Signal(int)
    clear_staging_requested = Signal()
    diagnostic_evidence_expanded_changed = Signal(bool)
    assist_expanded_changed = Signal(bool)
    key_edit_requested = Signal(object)
    key_lock_requested = Signal(bool)
    chord_edit_requested = Signal(str)
    chord_lock_requested = Signal(str, bool)
    chord_split_requested = Signal(str)
    chord_merge_next_requested = Signal(str)
    previous_phrase_requested = Signal()
    next_phrase_requested = Signal()
    loop_phrase_requested = Signal(bool)
    review_queue_requested = Signal()
    confirm_match_requested = Signal(object, int)
    stage_existing_track_requested = Signal(object, int)
    new_track_requested = Signal(object, int)
    audition_source_changed = Signal(str)

    SENSITIVITIES = (
        ("保守", "conservative"),
        ("平衡", "balanced"),
        ("敏感", "sensitive"),
    )
    ANALYSIS_MODES = (
        ("标准/独奏", "standard"),
        ("混音增强", "mixed_enhanced"),
    )
    CLEANUP_PROFILES = (
        ("保留", "preserve"),
        ("平衡 β", "balanced"),
        ("干净 β", "clean"),
    )
    CLEANUP_PROFILE_TOOLTIPS = {
        "preserve": "安全默认：保留碎音，仅排序并清除完全重复候选。",
        "balanced": (
            "实验性：自动合并明确的同音伪分裂；"
            "尚未通过留出集验证。"
        ),
        "clean": (
            "实验性：在平衡档基础上隐藏高疑似误检；"
            "尚未通过留出集验证，可用“显示已隐藏碎音”审阅。"
        ),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionEditorPanel")
        self._audio_loaded = False
        self._analysis_available = True
        self._analysis_unavailable_reason = ""
        self._analysis_busy = False
        self._range_available = False
        self._staging_locked = False
        self._copy_allowed = False
        self._assist_available = False
        self._melody_lines_available = False
        self._suspected_fragment_count = 0
        self._idle_status = trv("载入参考音频后可开始整首分析")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.analysis_bar = QFrame(self)
        self.analysis_bar.setObjectName("TranscriptionAnalysisBar")
        analysis = QGridLayout(self.analysis_bar)
        analysis.setContentsMargins(8, 5, 8, 5)
        analysis.setHorizontalSpacing(6)
        analysis.setVerticalSpacing(4)

        self.audio_button = QPushButton(tr("载入"), self.analysis_bar)
        self.audio_button.setObjectName("TranscriptionAudioButton")
        _responsive_control_width(self.audio_button, 64, 104)
        self.audio_button.clicked.connect(self._audio_button_clicked)
        analysis.addWidget(self.audio_button, 0, 0)

        self.analyze_button = QPushButton(tr("全曲"), self.analysis_bar)
        self.analyze_button.setObjectName("TranscriptionAnalyzeButton")
        self.analyze_button.setProperty("kind", "primary")
        self.analyze_button.setAccessibleName(tr("分析整首"))
        _responsive_control_width(self.analyze_button, 64, 104)
        self.analyze_button.clicked.connect(self.analyze_requested)
        analysis.addWidget(self.analyze_button, 0, 1)

        self.redecode_button = QPushButton(
            "A–B",
            self.analysis_bar,
        )
        self.redecode_button.setAccessibleName(tr("重新分析区间"))
        _responsive_control_width(self.redecode_button, 58, 92)
        self.redecode_button.clicked.connect(self.redecode_requested)
        analysis.addWidget(self.redecode_button, 0, 2)

        self.analysis_mode_combo = QComboBox(self.analysis_bar)
        self.analysis_mode_combo.setObjectName(
            "TranscriptionAnalysisModeCombo"
        )
        for label, value in self.ANALYSIS_MODES:
            self.analysis_mode_combo.addItem(tr(label), value)
        self.analysis_mode_combo.setMinimumContentsLength(7)
        _responsive_control_width(self.analysis_mode_combo, 136, 188)
        self.analysis_mode_combo.currentIndexChanged.connect(
            self._analysis_mode_changed,
        )
        analysis.addWidget(self.analysis_mode_combo, 0, 3)

        self.sensitivity_combo = QComboBox(self.analysis_bar)
        for label, value in self.SENSITIVITIES:
            self.sensitivity_combo.addItem(tr(label), value)
        self.sensitivity_combo.setMinimumContentsLength(4)
        _responsive_control_width(self.sensitivity_combo, 90, 124)
        self.sensitivity_combo.setCurrentIndex(1)
        self.sensitivity_combo.currentIndexChanged.connect(
            self._sensitivity_changed,
        )
        analysis.addWidget(self.sensitivity_combo, 0, 4)

        self.cleanup_profile_group = QFrame(self.analysis_bar)
        self.cleanup_profile_group.setObjectName("FragmentProfileGroup")
        cleanup = QHBoxLayout(self.cleanup_profile_group)
        cleanup.setContentsMargins(2, 0, 2, 0)
        cleanup.setSpacing(3)
        self.cleanup_profile_mark = QLabel("◇", self.cleanup_profile_group)
        self.cleanup_profile_mark.setObjectName("FragmentProfileMark")
        self.cleanup_profile_mark.setForegroundRole(
            QPalette.ColorRole.Link
        )
        cleanup.addWidget(self.cleanup_profile_mark)
        self.cleanup_profile_caption = QLabel(
            tr("碎音"),
            self.cleanup_profile_group,
        )
        self.cleanup_profile_caption.setObjectName("FragmentProfileCaption")
        self.cleanup_profile_caption.setForegroundRole(
            QPalette.ColorRole.Link
        )
        self.cleanup_profile_caption.setMaximumWidth(96)
        cleanup.addWidget(self.cleanup_profile_caption)

        self.cleanup_profile_combo = QComboBox(self.cleanup_profile_group)
        self.cleanup_profile_combo.setObjectName(
            "TranscriptionCleanupProfileCombo"
        )
        for label, value in self.CLEANUP_PROFILES:
            self.cleanup_profile_combo.addItem(tr(label), value)
            item_index = self.cleanup_profile_combo.count() - 1
            self.cleanup_profile_combo.setItemData(
                item_index,
                tr(self.CLEANUP_PROFILE_TOOLTIPS[value]),
                Qt.ToolTipRole,
            )
        self.cleanup_profile_combo.setCurrentIndex(
            self.cleanup_profile_combo.findData("preserve")
        )
        self.cleanup_profile_combo.setMinimumContentsLength(5)
        _responsive_control_width(self.cleanup_profile_combo, 96, 132)
        self.cleanup_profile_combo.setToolTip(
            tr(
                "独立于灵敏度。已有分析时，切换档位只从缓存证据"
                "重新解码，不再次运行模型。平衡/干净必须由用户"
                "显式启用，且尚未通过留出集验证；请审阅后再应用。"
            )
        )
        self.cleanup_profile_combo.currentIndexChanged.connect(
            self._cleanup_profile_changed,
        )
        self.cleanup_profile_caption.setBuddy(
            self.cleanup_profile_combo
        )
        cleanup.addWidget(self.cleanup_profile_combo)
        analysis.addWidget(self.cleanup_profile_group, 0, 5)
        self._refresh_cleanup_profile_cue()

        confidence_caption = QLabel(
            tr("弱显"),
            self.analysis_bar,
        )
        confidence_caption.setToolTip(
            tr("只调整低置信候选的透明度，不隐藏或禁用候选。")
        )
        confidence_caption.setMaximumWidth(42)
        analysis.addWidget(confidence_caption, 0, 6)
        self.confidence_slider = QSlider(Qt.Horizontal, self.analysis_bar)
        self.confidence_slider.setRange(0, 100)
        self.confidence_slider.setValue(30)
        self.confidence_slider.setFixedWidth(88)
        self.confidence_slider.setAccessibleName(
            tr("低置信候选透明度")
        )
        self.confidence_slider.setToolTip(confidence_caption.toolTip())
        self.confidence_slider.valueChanged.connect(
            self._confidence_slider_changed,
        )
        confidence_caption.setBuddy(self.confidence_slider)
        analysis.addWidget(self.confidence_slider, 0, 7)
        self.confidence_label = QLabel("30%", self.analysis_bar)
        self.confidence_label.setFixedWidth(40)
        analysis.addWidget(self.confidence_label, 0, 8)
        analysis.setColumnStretch(9, 1)

        self.melody_lines_button = QToolButton(self.analysis_bar)
        self.melody_lines_button.setObjectName(
            "TranscriptionMelodyLinesButton"
        )
        self.melody_lines_button.setText(tr("旋律线"))
        self.melody_lines_button.setAccessibleName(tr("旋律线辅助"))
        self.melody_lines_button.setToolTip(tr("分析后显示旋律线"))
        _responsive_control_width(self.melody_lines_button, 78, 132)
        self.melody_lines_button.setCheckable(True)
        self.melody_lines_button.setChecked(True)
        self.melody_lines_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self.melody_line_menu = QMenu(self.melody_lines_button)
        self._melody_role_actions = {}
        for role, label in (
            ("primary_melody", "主旋律"),
            ("bass", "低音"),
            ("harmony", "和声/和弦"),
        ):
            action = self.melody_line_menu.addAction(tr(label))
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(
                lambda checked, current_role=role: (
                    self._melody_role_toggled(current_role, checked)
                )
            )
            self._melody_role_actions[role] = action
        self.melody_lines_button.setMenu(self.melody_line_menu)

        self.diagnostic_toggle_button = QToolButton(self.analysis_bar)
        self.diagnostic_toggle_button.setText(tr("证据"))
        self.diagnostic_toggle_button.setAccessibleName(tr("诊断证据"))
        self.diagnostic_toggle_button.setToolTip(tr("诊断证据"))
        _responsive_control_width(self.diagnostic_toggle_button, 72, 104)
        self.diagnostic_toggle_button.setCheckable(True)
        self.diagnostic_toggle_button.setArrowType(Qt.RightArrow)
        self.diagnostic_toggle_button.toggled.connect(
            self.set_diagnostic_evidence_expanded,
        )
        self.frame_checkbox = QCheckBox("Frame", self.analysis_bar)
        _responsive_control_width(self.frame_checkbox, 64, 96)
        self.onset_checkbox = QCheckBox("Onset", self.analysis_bar)
        _responsive_control_width(self.onset_checkbox, 68, 104)
        self.contour_checkbox = QCheckBox("Contour", self.analysis_bar)
        _responsive_control_width(self.contour_checkbox, 88, 128)
        self.contour_checkbox.setToolTip(
            tr("默认关闭细粒度音高轮廓证据")
        )
        self.spectrogram_checkbox = QCheckBox(
            tr("声谱"),
            self.analysis_bar,
        )
        self.spectrogram_checkbox.setAccessibleName(tr("原始声谱图"))
        self.spectrogram_checkbox.setToolTip(tr("原始声谱图（诊断）"))
        _responsive_control_width(self.spectrogram_checkbox, 64, 104)
        self.spectrogram_checkbox.setChecked(False)
        self.reference_opacity_button = QToolButton(self.analysis_bar)
        self.reference_opacity_button.setObjectName(
            "TranscriptionReferenceOpacityButton"
        )
        self.reference_opacity_button.setText(tr("背景"))
        self.reference_opacity_button.setToolTip(
            tr("旋律线、Frame、Onset、Contour 与声谱透明度")
        )
        _responsive_control_width(self.reference_opacity_button, 64, 104)
        self.reference_opacity_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.reference_opacity_menu = QMenu(self.reference_opacity_button)
        self.reference_opacity_popup = QWidget(
            self.reference_opacity_menu
        )
        reference_opacity_layout = QHBoxLayout(
            self.reference_opacity_popup
        )
        reference_opacity_layout.setContentsMargins(8, 5, 8, 5)
        reference_opacity_layout.setSpacing(6)
        self.reference_opacity_caption = QLabel(
            tr("背景"),
            self.reference_opacity_popup,
        )
        self.reference_opacity_caption.setToolTip(
            tr("旋律线、Frame、Onset、Contour 与声谱透明度")
        )
        _responsive_control_width(self.reference_opacity_caption, 36, 104)
        self.reference_opacity_slider = QSlider(
            Qt.Horizontal,
            self.reference_opacity_popup,
        )
        self.reference_opacity_slider.setObjectName(
            "TranscriptionReferenceOpacitySlider"
        )
        self.reference_opacity_slider.setRange(0, 100)
        self.reference_opacity_slider.setValue(60)
        self.reference_opacity_slider.setFixedWidth(112)
        self.reference_opacity_slider.setToolTip(
            self.reference_opacity_caption.toolTip()
        )
        self.reference_opacity_slider.setAccessibleName(
            tr("参考背景透明度")
        )
        self.reference_opacity_caption.setBuddy(
            self.reference_opacity_slider
        )
        self.reference_opacity_label = QLabel(
            "60%",
            self.reference_opacity_popup,
        )
        self.reference_opacity_label.setFixedWidth(38)
        reference_opacity_layout.addWidget(self.reference_opacity_caption)
        reference_opacity_layout.addWidget(self.reference_opacity_slider)
        reference_opacity_layout.addWidget(self.reference_opacity_label)
        reference_opacity_action = QWidgetAction(
            self.reference_opacity_menu
        )
        reference_opacity_action.setDefaultWidget(
            self.reference_opacity_popup
        )
        self.reference_opacity_menu.addAction(reference_opacity_action)
        self.reference_opacity_button.setMenu(self.reference_opacity_menu)
        self.show_rejected_checkbox = QCheckBox(
            tr("拒绝项"),
            self.analysis_bar,
        )
        self.show_rejected_checkbox.setAccessibleName(tr("仅已拒绝"))
        self.show_rejected_checkbox.setToolTip(tr("仅已拒绝"))
        _responsive_control_width(self.show_rejected_checkbox, 92, 120)
        self.show_suppressed_checkbox = QCheckBox(
            tr("隐藏项"),
            self.analysis_bar,
        )
        self.show_suppressed_checkbox.setAccessibleName(
            tr("显示已隐藏碎音")
        )
        _responsive_control_width(self.show_suppressed_checkbox, 72, 104)
        self.show_suppressed_checkbox.setToolTip(
            tr(
                "显示干净档自动隐藏的候选供审阅；切换到平衡或保留"
                "可恢复全部隐藏项，隐藏项不会写入正式轨道。"
            )
        )
        self.guide_tools_bar = QFrame(self.analysis_bar)
        self.guide_tools_bar.setObjectName("TranscriptionGuideToolsBar")
        guide_tools = QHBoxLayout(self.guide_tools_bar)
        guide_tools.setContentsMargins(0, 0, 0, 0)
        guide_tools.setSpacing(6)
        guide_tools.addWidget(self.melody_lines_button)
        guide_tools.addWidget(self.diagnostic_toggle_button)
        guide_tools.addWidget(self.frame_checkbox)
        guide_tools.addWidget(self.onset_checkbox)
        guide_tools.addWidget(self.contour_checkbox)
        guide_tools.addWidget(self.spectrogram_checkbox)
        guide_tools.addWidget(self.reference_opacity_button)
        guide_tools.addWidget(self.show_rejected_checkbox)
        guide_tools.addWidget(self.show_suppressed_checkbox)
        guide_tools.addStretch(1)

        self.align_audio_button = QPushButton(
            tr("对齐"),
            self.analysis_bar,
        )
        self.align_audio_button.setAccessibleName(
            tr("音频位置对齐播放头")
        )
        self.align_audio_button.setToolTip(
            tr("音频位置对齐播放头")
        )
        _responsive_control_width(self.align_audio_button, 60, 92)
        self.align_audio_button.clicked.connect(self.align_audio_requested)
        guide_tools.addWidget(self.align_audio_button)
        self.beat_origin_button = QPushButton(
            tr("定拍"),
            self.analysis_bar,
        )
        self.beat_origin_button.setAccessibleName(
            tr("将播放头设为第一拍")
        )
        self.beat_origin_button.setToolTip(
            tr("将播放头设为第一拍")
        )
        _responsive_control_width(self.beat_origin_button, 56, 88)
        self.beat_origin_button.clicked.connect(self.beat_origin_requested)
        guide_tools.addWidget(self.beat_origin_button)
        self.clear_range_button = QPushButton(
            tr("清除 A–B"),
            self.analysis_bar,
        )
        _responsive_control_width(self.clear_range_button, 60, 112)
        self.clear_range_button.clicked.connect(self.clear_range_requested)
        guide_tools.addWidget(self.clear_range_button)
        analysis.addWidget(self.guide_tools_bar, 1, 0, 1, 10)
        root.addWidget(self.analysis_bar)

        self.review_bar = QFrame(self)
        self.review_bar.setObjectName("TranscriptionReviewBar")
        review = QHBoxLayout(self.review_bar)
        review.setContentsMargins(8, 5, 8, 5)
        review.setSpacing(6)

        self.review_undo_button = QPushButton(
            "↶",
            self.review_bar,
        )
        self.review_undo_button.setFixedWidth(34)
        self.review_undo_button.setAccessibleName(tr("审阅撤销"))
        self.review_undo_button.setToolTip(tr("审阅撤销"))
        self.review_undo_button.clicked.connect(self.review_undo_requested)
        self.review_redo_button = QPushButton(
            "↷",
            self.review_bar,
        )
        self.review_redo_button.setFixedWidth(34)
        self.review_redo_button.setAccessibleName(tr("审阅重做"))
        self.review_redo_button.setToolTip(tr("审阅重做"))
        self.review_redo_button.clicked.connect(self.review_redo_requested)
        self.reject_button = QPushButton(tr("拒绝"), self.review_bar)
        _responsive_control_width(self.reject_button, 64, 96)
        self.reject_button.clicked.connect(self.reject_requested)
        self.restore_button = QPushButton(tr("恢复"), self.review_bar)
        _responsive_control_width(self.restore_button, 64, 104)
        self.restore_button.clicked.connect(self.restore_requested)
        self.select_fragments_button = QPushButton(
            tr("碎音"),
            self.review_bar,
        )
        self.select_fragments_button.setObjectName(
            "FragmentReviewButton"
        )
        self.select_fragments_button.setAccessibleName(
            tr("选择疑似碎音")
        )
        self.select_fragments_button.setToolTip(
            tr("选择疑似碎音")
        )
        _responsive_control_width(self.select_fragments_button, 96, 128)
        self.select_fragments_button.clicked.connect(
            self.select_fragments_requested,
        )
        review.addWidget(self.review_undo_button)
        review.addWidget(self.review_redo_button)
        review.addWidget(self.reject_button)
        review.addWidget(self.restore_button)
        review.addWidget(self.select_fragments_button)
        self.assist_toggle_button = QToolButton(self.review_bar)
        self.assist_toggle_button.setText(tr("和声/配器"))
        self.assist_toggle_button.setAccessibleName(
            tr("和声与乐器建议")
        )
        self.assist_toggle_button.setToolTip(
            tr("和声与乐器建议")
        )
        self.assist_toggle_button.setMaximumWidth(128)
        self.assist_toggle_button.setCheckable(True)
        self.assist_toggle_button.setArrowType(Qt.RightArrow)
        self.assist_toggle_button.toggled.connect(
            self.set_assist_expanded,
        )
        self.assist_toggle_button.hide()
        review.addWidget(self.assist_toggle_button)

        self.status_label = _ElidedStatusLabel(
            str(self._idle_status),
            self.review_bar,
        )
        self.status_label.setText(str(self._idle_status))
        self.status_label.setObjectName("Muted")
        self.status_label.setMinimumWidth(96)
        review.addWidget(self.status_label, 1)

        self.staging_label = QLabel(
            trf("暂存 {count}", count=0),
            self.review_bar,
        )
        self.staging_label.setObjectName("Muted")
        _responsive_control_width(self.staging_label, 72, 120)
        review.addWidget(self.staging_label)
        self.clear_staging_button = QPushButton(
            tr("清空"),
            self.review_bar,
        )
        self.clear_staging_button.setAccessibleName(
            tr("清除暂存")
        )
        self.clear_staging_button.setToolTip(tr("清除暂存"))
        _responsive_control_width(self.clear_staging_button, 64, 96)
        self.clear_staging_button.clicked.connect(
            self.clear_staging_requested,
        )
        review.addWidget(self.clear_staging_button)
        self.write_current_track_button = QPushButton(
            tr("写入本轨"),
            self.review_bar,
        )
        self.write_current_track_button.setAccessibleName(
            tr("写入当前轨草稿")
        )
        self.write_current_track_button.setToolTip(
            tr("写入当前轨草稿")
        )
        _responsive_control_width(self.write_current_track_button, 96, 136)
        self.write_current_track_button.setProperty("kind", "primary")
        self.write_current_track_button.clicked.connect(
            self.write_current_track_requested,
        )
        review.addWidget(self.write_current_track_button)

        self.copy_to_track_button = QToolButton(self.review_bar)
        self.copy_to_track_button.setText(tr("复制到…"))
        self.copy_to_track_button.setAccessibleName(
            tr("复制到其他轨")
        )
        self.copy_to_track_button.setToolTip(tr("复制到其他轨"))
        _responsive_control_width(self.copy_to_track_button, 96, 136)
        self.copy_to_track_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.copy_to_track_menu = QMenu(self.copy_to_track_button)
        self.copy_to_track_button.setMenu(self.copy_to_track_menu)
        review.addWidget(self.copy_to_track_button)
        root.addWidget(self.review_bar)

        self.assist_panel = TranscriptionAssistPanel(self)
        self.assist_panel.hide()
        root.addWidget(self.assist_panel)

        self.frame_checkbox.toggled.connect(
            self.frame_visibility_changed,
        )
        self.onset_checkbox.toggled.connect(
            self.onset_visibility_changed,
        )
        self.contour_checkbox.toggled.connect(
            self.contour_visibility_changed,
        )
        self.melody_lines_button.toggled.connect(
            self.melody_lines_visibility_changed,
        )
        self.spectrogram_checkbox.toggled.connect(
            self.spectrogram_visibility_changed,
        )
        self.reference_opacity_slider.valueChanged.connect(
            self._reference_opacity_slider_changed,
        )
        for checkbox in (
            self.frame_checkbox,
            self.onset_checkbox,
            self.contour_checkbox,
        ):
            checkbox.toggled.connect(self._evidence_layers_toggled)
        self.show_rejected_checkbox.toggled.connect(
            self.show_rejected_changed,
        )
        self.show_suppressed_checkbox.toggled.connect(
            self.show_suppressed_changed,
        )
        self._forward_assist_signals()
        self.set_diagnostic_evidence_expanded(False)
        self.set_action_state(
            write_enabled=False,
            copy_enabled=False,
            rejected_count=0,
            can_undo=False,
            can_redo=False,
            staging_count=0,
        )
        self.set_fragment_state()
        self._refresh_analysis_controls()

    def _forward_assist_signals(self) -> None:
        forwards = (
            (self.assist_panel.key_edit_requested, self.key_edit_requested),
            (self.assist_panel.key_lock_requested, self.key_lock_requested),
            (
                self.assist_panel.chord_edit_requested,
                self.chord_edit_requested,
            ),
            (
                self.assist_panel.chord_lock_requested,
                self.chord_lock_requested,
            ),
            (
                self.assist_panel.chord_split_requested,
                self.chord_split_requested,
            ),
            (
                self.assist_panel.chord_merge_next_requested,
                self.chord_merge_next_requested,
            ),
            (
                self.assist_panel.previous_phrase_requested,
                self.previous_phrase_requested,
            ),
            (
                self.assist_panel.next_phrase_requested,
                self.next_phrase_requested,
            ),
            (
                self.assist_panel.loop_phrase_requested,
                self.loop_phrase_requested,
            ),
            (
                self.assist_panel.review_queue_requested,
                self.review_queue_requested,
            ),
            (
                self.assist_panel.confirm_match_requested,
                self.confirm_match_requested,
            ),
            (
                self.assist_panel.stage_existing_track_requested,
                self.stage_existing_track_requested,
            ),
            (
                self.assist_panel.new_track_requested,
                self.new_track_requested,
            ),
            (
                self.assist_panel.audition_source_changed,
                self.audition_source_changed,
            ),
        )
        for source, destination in forwards:
            source.connect(destination)

    def set_diagnostic_evidence_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        blocked = self.diagnostic_toggle_button.blockSignals(True)
        self.diagnostic_toggle_button.setChecked(expanded)
        self.diagnostic_toggle_button.blockSignals(blocked)
        self.diagnostic_toggle_button.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow
        )
        self.frame_checkbox.setVisible(expanded)
        self.onset_checkbox.setVisible(expanded)
        self.contour_checkbox.setVisible(expanded)
        self.spectrogram_checkbox.setVisible(expanded)
        self.diagnostic_evidence_expanded_changed.emit(expanded)

    def set_assist_available(self, available: bool) -> None:
        self._assist_available = bool(available)
        self.assist_toggle_button.setVisible(self._assist_available)
        if not self._assist_available:
            self.set_assist_expanded(False)

    def set_assist_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded and self._assist_available)
        blocked = self.assist_toggle_button.blockSignals(True)
        self.assist_toggle_button.setChecked(expanded)
        self.assist_toggle_button.blockSignals(blocked)
        self.assist_toggle_button.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow
        )
        self.assist_panel.setVisible(expanded)
        self.assist_expanded_changed.emit(expanded)

    def set_harmony_analysis(self, analysis: object | None) -> None:
        self.assist_panel.set_harmony(analysis)
        if analysis is not None:
            self.set_assist_available(True)

    def set_phrase_state(
        self,
        *,
        index: int = -1,
        total: int = 0,
        loop_enabled: bool = False,
        review_count: int = 0,
    ) -> None:
        self.assist_panel.set_phrase_state(
            index=index,
            total=total,
            loop_enabled=loop_enabled,
            review_count=review_count,
        )
        if total > 0 or review_count > 0:
            self.set_assist_available(True)

    def set_voice_group_matches(
        self,
        voice_group: object | None,
        matches: Iterable[object],
        *,
        confirmed_instrument_id: int | None = None,
    ) -> None:
        normalized = tuple(matches)
        self.assist_panel.set_voice_group_matches(
            voice_group,
            normalized,
            confirmed_instrument_id=confirmed_instrument_id,
        )
        if voice_group is not None or normalized:
            self.set_assist_available(True)

    def clear_voice_group_matches(self) -> None:
        self.assist_panel.instrument_matches.clear()

    def clear_assist_state(self) -> None:
        self.assist_panel.clear()

    @property
    def sensitivity(self) -> str:
        return str(self.sensitivity_combo.currentData() or "balanced")

    @property
    def cleanup_profile(self) -> str:
        return str(
            self.cleanup_profile_combo.currentData() or "preserve"
        )

    @property
    def analysis_mode(self) -> str:
        return str(self.analysis_mode_combo.currentData() or "standard")

    @property
    def confidence_floor(self) -> float:
        return self.confidence_slider.value() / 100.0

    @property
    def reference_background_opacity(self) -> float:
        return self.reference_opacity_slider.value() / 100.0

    @property
    def visible_evidence_layers(self) -> frozenset[str]:
        layers: set[str] = set()
        if self.frame_checkbox.isChecked():
            layers.add("frame")
        if self.onset_checkbox.isChecked():
            layers.add("onset")
        if self.contour_checkbox.isChecked():
            layers.add("contour")
        return frozenset(layers)

    @property
    def spectrogram_visible(self) -> bool:
        return self.spectrogram_checkbox.isChecked()

    @property
    def melody_lines_visible(self) -> bool:
        return self.melody_lines_button.isChecked()

    @property
    def melody_line_roles(self) -> frozenset[str]:
        return frozenset(
            role
            for role, action in self._melody_role_actions.items()
            if action.isChecked()
        )

    def _melody_role_toggled(self, role: str, checked: bool) -> None:
        if not checked and not self.melody_line_roles:
            action = self._melody_role_actions.get(str(role))
            if action is not None:
                blocked = action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(blocked)
            return
        self.melody_line_roles_changed.emit(self.melody_line_roles)

    def _audio_button_clicked(self) -> None:
        if self._audio_loaded:
            self.unload_audio_requested.emit()
        else:
            self.load_audio_requested.emit()

    def _sensitivity_changed(self, _index: int) -> None:
        self.sensitivity_changed.emit(self.sensitivity)

    def _cleanup_profile_changed(self, _index: int) -> None:
        self._refresh_cleanup_profile_cue()
        self.cleanup_profile_changed.emit(self.cleanup_profile)

    def _refresh_cleanup_profile_cue(self) -> None:
        experimental = self.cleanup_profile != "preserve"
        self.cleanup_profile_mark.setText("◆" if experimental else "◇")
        index = self.cleanup_profile_combo.currentIndex()
        detail = self.cleanup_profile_combo.itemData(
            index,
            Qt.ItemDataRole.ToolTipRole,
        )
        self.cleanup_profile_mark.setToolTip(str(detail or ""))
        self.cleanup_profile_group.setProperty(
            "experimental",
            experimental,
        )

    def _analysis_mode_changed(self, _index: int) -> None:
        self.analysis_mode_changed.emit(self.analysis_mode)

    def _confidence_slider_changed(self, value: int) -> None:
        self.confidence_label.setText(f"{int(value)}%")
        self.confidence_changed.emit(value / 100.0)

    def _reference_opacity_slider_changed(self, value: int) -> None:
        self.reference_opacity_label.setText(f"{int(value)}%")
        self.reference_background_opacity_changed.emit(value / 100.0)

    def _evidence_layers_toggled(self, _checked: bool) -> None:
        self.evidence_layers_changed.emit(self.visible_evidence_layers)

    def set_audio_loaded(
        self,
        loaded: bool,
        *,
        display_name: str = "",
    ) -> None:
        self._audio_loaded = bool(loaded)
        self.audio_button.setText(tr("卸载") if loaded else tr("载入"))
        self.audio_button.setProperty("i18nSkipToolTip", bool(loaded))
        self.audio_button.setToolTip(display_name if loaded else "")
        self._refresh_analysis_controls()

    def set_sensitivity(self, value: str) -> None:
        index = self.sensitivity_combo.findData(str(value))
        if index < 0 or index == self.sensitivity_combo.currentIndex():
            return
        blocked = self.sensitivity_combo.blockSignals(True)
        self.sensitivity_combo.setCurrentIndex(index)
        self.sensitivity_combo.blockSignals(blocked)

    def set_cleanup_profile(self, value: str) -> None:
        index = self.cleanup_profile_combo.findData(str(value))
        if (
            index < 0
            or index == self.cleanup_profile_combo.currentIndex()
        ):
            return
        blocked = self.cleanup_profile_combo.blockSignals(True)
        self.cleanup_profile_combo.setCurrentIndex(index)
        self.cleanup_profile_combo.blockSignals(blocked)
        self._refresh_cleanup_profile_cue()

    def set_fragment_state(
        self,
        *,
        suspected_count: int = 0,
    ) -> None:
        self._suspected_fragment_count = max(
            0,
            int(suspected_count),
        )
        self.select_fragments_button.setEnabled(
            self._suspected_fragment_count > 0
            and not self._analysis_busy
        )
        self.select_fragments_button.setText(
            trf(
                "碎音 {count}",
                count=self._suspected_fragment_count,
            )
            if self._suspected_fragment_count
            else tr("碎音")
        )
        self.select_fragments_button.setProperty(
            "hasFragments",
            self._suspected_fragment_count > 0,
        )

    def set_analysis_mode(self, value: str) -> None:
        index = self.analysis_mode_combo.findData(str(value))
        if index < 0 or index == self.analysis_mode_combo.currentIndex():
            return
        blocked = self.analysis_mode_combo.blockSignals(True)
        self.analysis_mode_combo.setCurrentIndex(index)
        self.analysis_mode_combo.blockSignals(blocked)

    def set_confidence_floor(self, value: float) -> None:
        normalized = max(0.0, min(1.0, _finite_float(value)))
        slider_value = round(normalized * 100.0)
        blocked = self.confidence_slider.blockSignals(True)
        self.confidence_slider.setValue(slider_value)
        self.confidence_slider.blockSignals(blocked)
        self.confidence_label.setText(f"{slider_value}%")

    def set_reference_background_opacity(self, value: float) -> None:
        normalized = max(0.0, min(1.0, _finite_float(value, 0.6)))
        slider_value = round(normalized * 100.0)
        blocked = self.reference_opacity_slider.blockSignals(True)
        self.reference_opacity_slider.setValue(slider_value)
        self.reference_opacity_slider.blockSignals(blocked)
        self.reference_opacity_label.setText(f"{slider_value}%")

    def set_evidence_layers(self, layers: Iterable[str]) -> None:
        visible = {str(layer) for layer in layers}
        for checkbox, name in (
            (self.frame_checkbox, "frame"),
            (self.onset_checkbox, "onset"),
            (self.contour_checkbox, "contour"),
        ):
            blocked = checkbox.blockSignals(True)
            checkbox.setChecked(name in visible)
            checkbox.blockSignals(blocked)
        if visible:
            self.set_diagnostic_evidence_expanded(True)

    def set_spectrogram_visible(self, visible: bool) -> None:
        blocked = self.spectrogram_checkbox.blockSignals(True)
        self.spectrogram_checkbox.setChecked(bool(visible))
        self.spectrogram_checkbox.blockSignals(blocked)

    def set_melody_lines_visible(self, visible: bool) -> None:
        blocked = self.melody_lines_button.blockSignals(True)
        self.melody_lines_button.setChecked(bool(visible))
        self.melody_lines_button.blockSignals(blocked)

    def set_melody_line_roles(self, roles: Iterable[str]) -> None:
        normalized = {
            str(role)
            for role in roles
            if str(role) in self._melody_role_actions
        }
        if not normalized:
            normalized = {"primary_melody"}
        for role, action in self._melody_role_actions.items():
            blocked = action.blockSignals(True)
            action.setChecked(role in normalized)
            action.blockSignals(blocked)

    def set_melody_lines_available(self, available: bool) -> None:
        self._melody_lines_available = bool(available)
        self._refresh_analysis_controls()

    def set_range_available(self, available: bool) -> None:
        self._range_available = bool(available)
        self._refresh_analysis_controls()

    def set_staging_locked(self, locked: bool) -> None:
        """Lock actions that can invalidate local candidate staging."""
        self._staging_locked = bool(locked)
        self._refresh_analysis_controls()

    def set_analysis_available(
        self,
        available: bool,
        reason: object = "",
    ) -> None:
        self._analysis_available = bool(available)
        self._analysis_unavailable_reason = defer_tr(reason) if reason else ""
        self.analyze_button.setToolTip(
            "" if available else str(self._analysis_unavailable_reason)
        )
        if not self._analysis_busy:
            self.status_label.setText(self._effective_idle_status())
        self._refresh_analysis_controls()

    def set_analysis_busy(
        self,
        busy: bool,
        progress: int | None = None,
    ) -> None:
        self._analysis_busy = bool(busy)
        if busy:
            self.status_label.setText(
                tr("正在分析参考音频…")
                if progress is None
                else trf(
                    "正在分析参考音频 · {progress}%",
                    progress=max(0, min(100, int(progress))),
                )
            )
        else:
            self.status_label.setText(self._effective_idle_status())
        self._refresh_analysis_controls()

    def set_status(self, text: object) -> None:
        self._idle_status = defer_tr(text)
        if not self._analysis_busy:
            self.status_label.setText(self._effective_idle_status())

    def _effective_idle_status(self) -> str:
        """Keep a disabled backend's reason visible instead of looking stuck."""
        if (
            not self._analysis_available
            and self._analysis_unavailable_reason
        ):
            return str(self._analysis_unavailable_reason)
        return str(self._idle_status)

    def retranslate_dynamic_content(self) -> None:
        """Re-render cached idle/backend messages in the active locale."""

        for index in range(self.cleanup_profile_combo.count()):
            profile = str(self.cleanup_profile_combo.itemData(index) or "")
            tooltip_source = self.CLEANUP_PROFILE_TOOLTIPS.get(profile)
            if tooltip_source is not None:
                self.cleanup_profile_combo.setItemData(
                    index,
                    tr(tooltip_source),
                    Qt.ItemDataRole.ToolTipRole,
                )
        self._refresh_cleanup_profile_cue()
        if not self._analysis_busy:
            self.status_label.setText(self._effective_idle_status())
        self._refresh_analysis_controls()

    def set_action_state(
        self,
        *,
        write_enabled: bool,
        copy_enabled: bool | None = None,
        reject_enabled: bool | None = None,
        rejected_count: int = 0,
        can_undo: bool = False,
        can_redo: bool = False,
        staging_count: int = 0,
    ) -> None:
        self.write_current_track_button.setEnabled(bool(write_enabled))
        self._copy_allowed = bool(
            write_enabled if copy_enabled is None else copy_enabled
        )
        self.copy_to_track_button.setEnabled(
            self._copy_allowed
            and bool(self.copy_to_track_menu.actions())
        )
        self.reject_button.setEnabled(
            bool(write_enabled if reject_enabled is None else reject_enabled)
        )
        self.restore_button.setEnabled(int(rejected_count) > 0)
        self.review_undo_button.setEnabled(bool(can_undo))
        self.review_redo_button.setEnabled(bool(can_redo))
        count = max(0, int(staging_count))
        self.clear_staging_button.setEnabled(count > 0)
        self.staging_label.setText(trf("暂存 {count}", count=count))
        self.staging_label.setToolTip(
            trf("已暂存 {count} 个候选", count=count)
            if count
            else tr("未暂存候选")
        )

    def set_copy_targets(
        self,
        targets: Iterable[object],
        *,
        current_track_id: int | None = None,
        include_current: bool = False,
    ) -> None:
        """Populate the explicit-copy menu with legal melodic destinations."""
        self.copy_to_track_menu.clear()
        normalized: list[tuple[int, str]] = []
        for target in targets:
            if isinstance(target, tuple) and len(target) >= 2:
                raw_id, raw_label = target[0], target[1]
                is_percussion = False
                instrument_id = -1
            else:
                raw_id = _value(target, "track_id", -1)
                raw_label = _value(
                    target,
                    "display_name",
                    tr("轨道 ") + str(raw_id),
                )
                is_percussion = bool(
                    _value(target, "is_percussion", False)
                )
                instrument_id = int(
                    _value(target, "bdo_instrument_id", -1)
                )
            try:
                track_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if (
                track_id < 0
                or (
                    track_id == current_track_id
                    and not include_current
                )
                or is_percussion
                or instrument_id == 0x0D
            ):
                continue
            normalized.append((track_id, str(raw_label)))

        for track_id, label in sorted(
            normalized,
            key=lambda item: (item[1].casefold(), item[0]),
        ):
            action = self.copy_to_track_menu.addAction(label)
            # Track names are project-owned data.  A name such as "Play" must
            # not be reverse-mapped to a fixed UI source during live switching.
            action.setProperty("i18nSkipText", True)
            action.setData(track_id)
            action.triggered.connect(
                lambda _checked=False, target=track_id: (
                    self.copy_to_track_requested.emit(target)
                )
            )
        self.copy_to_track_button.setEnabled(
            self._copy_allowed
            and bool(self.copy_to_track_menu.actions())
        )

    def _refresh_analysis_controls(self) -> None:
        invalidating_enabled = (
            not self._analysis_busy and not self._staging_locked
        )
        self.audio_button.setEnabled(invalidating_enabled)
        self.analyze_button.setEnabled(
            invalidating_enabled
            and self._analysis_available
            and self._audio_loaded
        )
        self.redecode_button.setEnabled(
            invalidating_enabled
            and self._analysis_available
            and self._audio_loaded
            and self._range_available
        )
        self.sensitivity_combo.setEnabled(invalidating_enabled)
        self.cleanup_profile_combo.setEnabled(invalidating_enabled)
        self.analysis_mode_combo.setEnabled(invalidating_enabled)
        self.select_fragments_button.setEnabled(
            self._suspected_fragment_count > 0
            and not self._analysis_busy
        )
        self.align_audio_button.setEnabled(
            invalidating_enabled and self._audio_loaded
        )
        melody_lines_enabled = (
            self._audio_loaded
            and self._melody_lines_available
            and not self._analysis_busy
        )
        self.melody_lines_button.setEnabled(melody_lines_enabled)
        self.melody_lines_button.setToolTip(
            tr("主旋律 · 低音 · 和弦；线粗表示置信度；点击线定位候选")
            if melody_lines_enabled
            else tr("分析后显示旋律线")
        )
        self.spectrogram_checkbox.setEnabled(
            self._audio_loaded and not self._analysis_busy
        )
        self.beat_origin_button.setEnabled(not self._analysis_busy)
        self.clear_range_button.setEnabled(self._range_available)
        if not self._analysis_available:
            disabled_reason = str(self._analysis_unavailable_reason)
        elif self._analysis_busy:
            disabled_reason = tr("正在分析参考音频…")
        elif self._staging_locked:
            disabled_reason = tr(
                "请先应用、撤销或清除本次暂存，再更换音频或重新分析。"
            )
        elif not self._audio_loaded:
            disabled_reason = tr("请先载入 MP3/WAV 参考音频")
        else:
            disabled_reason = ""
        self.analyze_button.setToolTip(
            disabled_reason or tr("分析整首")
        )
        self.redecode_button.setToolTip(
            disabled_reason or tr("重新分析区间")
        )


__all__ = [
    "TranscriptionAssistPanel",
    "TranscriptionEditorPanel",
    "TranscriptionHarmonySummary",
    "TranscriptionInstrumentMatches",
    "TranscriptionPhraseReviewControls",
    "TranscriptionWaveformLane",
    "voice_role_label",
    "voice_role_source_label",
]
