"""Inline free-point velocity-envelope editing for the multitrack timeline."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from typing import Sequence

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.velocity_curve import (
    VelocityEnvelopePoint,
    apply_velocity_level_envelope,
    velocity_envelope_points_from_notes,
    velocity_envelope_samples,
    velocity_time_points,
)
from bdo_music_composer.ui.i18n import tr, trf


@dataclass(frozen=True, slots=True)
class _CurveContext:
    track: TrackState
    region: QRectF
    start_ms: float
    end_ms: float
    note_indices: tuple[int, ...]
    scope_source: str


@dataclass(slots=True)
class _CurveSession:
    track: TrackState
    baseline_notes: tuple[object, ...]
    start_ms: float
    end_ms: float
    note_indices: tuple[int, ...]
    scope_source: str
    points: list[VelocityEnvelopePoint]
    active_point: int = 0
    active_control: str = "point"


@dataclass(frozen=True, slots=True)
class _VelocityTraceIndex:
    starts: tuple[float, ...]
    points: tuple[tuple[float, float], ...]


class TimelineVelocityCurveOverlay(QObject):
    """Paint and edit one exact, non-destructive point envelope."""

    commit_requested = Signal(object, object)
    MIN_VELOCITY = 0.0
    MAX_VELOCITY = 127.0
    POINT_RADIUS = 5.5
    MIN_POINT_GAP = 0.002
    MAX_POINTS = 64

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self._session: _CurveSession | None = None
        self._context: _CurveContext | None = None
        self._geometry: QRectF | None = None
        self._hit_regions: list[tuple[QRectF, str]] = []
        self._dragging_point: int | None = None
        self._dragging_weight: tuple[int, str] | None = None
        self._note_onsets: dict[int, tuple[tuple[float, int], ...]] = {}
        self._velocity_traces: dict[int, _VelocityTraceIndex] = {}
        self._target_cache_key: tuple[object, ...] | None = None
        self._target_cache_value: _CurveContext | None = None

    @property
    def active(self) -> bool:
        return self._session is not None

    @property
    def points(self) -> tuple[VelocityEnvelopePoint, ...]:
        session = self._session
        return tuple(session.points) if session is not None else ()

    def begin_frame(self) -> None:
        self._hit_regions.clear()
        self._context = None
        self._geometry = None

    def synchronize_tracks(self, tracks: Sequence[TrackState]) -> None:
        self._note_onsets = {}
        self._velocity_traces = {}
        self._target_cache_key = None
        self._target_cache_value = None
        session = self._session
        if session is not None and not any(
            track is session.track for track in tracks
        ):
            self.cancel()

    def _ensure_track_index(self, track: TrackState) -> None:
        track_key = id(track)
        if track_key in self._note_onsets:
            return
        onsets = tuple(
            sorted(
                (float(note.start), index)
                for index, note in enumerate(track.notes)
            )
        )
        self._note_onsets[track_key] = onsets
        velocity_groups: dict[float, list[float]] = {}
        for onset, index in onsets:
            key = round(onset, 3)
            group = velocity_groups.setdefault(key, [0.0, 0.0])
            group[0] += float(track.notes[index].vel)
            group[1] += 1.0
        points = tuple(
            (onset, total / count)
            for onset, (total, count) in velocity_groups.items()
        )
        self._velocity_traces[track_key] = _VelocityTraceIndex(
            starts=tuple(onset for onset, _velocity in points),
            points=points,
        )

    def selected_track_changed(self, track: TrackState | None) -> None:
        if self._session is not None and track is not self._session.track:
            self.cancel()

    def _indices_between(
        self,
        track: TrackState,
        start_ms: float,
        end_ms: float,
    ) -> tuple[int, ...]:
        self._ensure_track_index(track)
        onsets = self._note_onsets.get(id(track), ())
        lower = bisect_left(onsets, (float(start_ms), -1))
        upper = bisect_right(onsets, (float(end_ms), len(track.notes)))
        return tuple(index for _onset, index in onsets[lower:upper])

    def _target_context(
        self,
        track: TrackState,
        region: QRectF,
        visible_start: float,
        visible_duration: float,
        selected_range: tuple[float, float] | None,
    ) -> _CurveContext:
        cache_key = (
            id(track),
            float(visible_start),
            float(visible_duration),
            selected_range,
        )
        if (
            cache_key == self._target_cache_key
            and self._target_cache_value is not None
        ):
            return replace(self._target_cache_value, region=QRectF(region))
        visible_end = visible_start + visible_duration
        visible_indices = self._indices_between(track, visible_start, visible_end)
        if visible_indices:
            visible_onsets = [float(track.notes[index].start) for index in visible_indices]
            start_ms, end_ms = min(visible_onsets), max(visible_onsets)
        else:
            start_ms, end_ms = visible_start, visible_end
        scope_source = "当前可见区"
        selected_indices: tuple[int, ...] = ()
        if selected_range is not None and selected_range[1] - selected_range[0] > 0.5:
            selected_indices = self._indices_between(
                track,
                selected_range[0],
                selected_range[1],
            )
            if selected_indices:
                start_ms, end_ms = selected_range
                scope_source = "A–B 区间"
        note_indices = selected_indices if scope_source == "A–B 区间" else visible_indices
        context = _CurveContext(
            track,
            QRectF(region),
            float(start_ms),
            float(end_ms),
            note_indices,
            scope_source,
        )
        self._target_cache_key = cache_key
        self._target_cache_value = context
        return context

    def paint_selected_track(
        self,
        painter: QPainter,
        track: TrackState,
        region: QRectF,
        visible_start: float,
        visible_duration: float,
        selected_range: tuple[float, float] | None,
    ) -> None:
        self._context = self._target_context(
            track,
            region,
            visible_start,
            visible_duration,
            selected_range,
        )
        session = self._session
        if session is None or session.track is not track:
            return
        geometry = region.adjusted(8.0, 5.0, -8.0, -5.0)
        self._paint_session(painter, geometry, session)
        self._paint_inline_actions(painter, region, session)

    def velocity_trace_points(
        self,
        track: TrackState,
        start_ms: float,
        end_ms: float,
    ) -> tuple[tuple[float, float], ...]:
        """Return the visible onset averages directly from authoritative Note.vel."""

        self._ensure_track_index(track)
        trace = self._velocity_traces.get(id(track))
        if trace is None:
            indices = self._indices_between(track, start_ms, end_ms)[:2600]
            return tuple(
                (onset, average)
                for onset, _indices, average in velocity_time_points(
                    track.notes,
                    indices,
                )
            )
        lower = bisect_left(trace.starts, float(start_ms))
        upper = bisect_right(trace.starts, float(end_ms))
        return trace.points[lower:upper]

    @staticmethod
    def _bounded_velocity_trace(
        points: tuple[tuple[float, float], ...],
        start_ms: float,
        duration_ms: float,
        max_points: int,
    ) -> tuple[tuple[float, float], ...]:
        """Average sub-pixel onsets into a bounded visual-only trace."""

        limit = max(2, int(max_points))
        if len(points) <= limit:
            return points
        bins: dict[int, list[float]] = {}
        span = max(1.0, float(duration_ms))
        for onset, velocity in points:
            bucket = max(
                0,
                min(
                    limit - 1,
                    int((onset - float(start_ms)) / span * limit),
                ),
            )
            aggregate = bins.setdefault(bucket, [0.0, 0.0, 0.0])
            aggregate[0] += onset
            aggregate[1] += velocity
            aggregate[2] += 1.0
        return tuple(
            (onset_total / count, velocity_total / count)
            for onset_total, velocity_total, count in bins.values()
        )

    def paint_velocity_trace(
        self,
        painter: QPainter,
        track: TrackState,
        region: QRectF,
        visible_start: float,
        visible_duration: float,
        active: bool,
    ) -> None:
        """Draw the current editor velocity values on their original track row."""

        points = self.velocity_trace_points(
            track,
            visible_start,
            visible_start + visible_duration,
        )
        if not points:
            return
        geometry = region.adjusted(5.0, 5.0, -5.0, -5.0)
        points = self._bounded_velocity_trace(
            points,
            visible_start,
            visible_duration,
            max(64, int(geometry.width() / 12.0)),
        )
        path = QPainterPath()
        screens: list[QPointF] = []
        for onset, velocity in points:
            x = geometry.left() + (
                (onset - visible_start) / max(1.0, visible_duration)
            ) * geometry.width()
            y = geometry.bottom() - velocity / 127.0 * geometry.height()
            screens.append(QPointF(x, y))
        path.moveTo(screens[0])
        for point in screens[1:]:
            path.lineTo(point)
        painter.save()
        painter.setClipRect(region)
        color = QColor("#bca76b" if active else "#77715f")
        color.setAlpha(126 if active else 62)
        painter.setPen(QPen(color, 1.15, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        stride = max(1, len(screens) // 32)
        for point in screens[::stride]:
            painter.drawEllipse(
                QRectF(point.x() - 1.5, point.y() - 1.5, 3.0, 3.0)
            )
        painter.restore()

    def _paint_inline_actions(
        self,
        painter: QPainter,
        region: QRectF,
        session: _CurveSession,
    ) -> None:
        apply_rect = QRectF(region.right() - 98.0, region.top() + 4.0, 42.0, 21.0)
        cancel_rect = QRectF(region.right() - 50.0, region.top() + 4.0, 42.0, 21.0)
        painter.save()
        for rect, label, action, accent in (
            (apply_rect, tr("应用"), "apply", True),
            (cancel_rect, tr("取消"), "cancel", False),
        ):
            painter.setBrush(QColor("#806526" if accent else "#292b2c"))
            painter.setPen(QPen(QColor("#d4ae4f" if accent else "#55595a"), 1.0))
            painter.drawRoundedRect(rect, 4.0, 4.0)
            painter.setPen(QColor("#fff0c8" if accent else "#d4d2cc"))
            painter.drawText(rect, Qt.AlignCenter, label)
            self._hit_regions.append((rect, action))
        point = session.points[session.active_point]
        detail = trf(
            "力度 {velocity:.0f} · 左 {left:.0f}% · 右 {right:.0f}%",
            velocity=point.velocity,
            left=point.left_weight * 100.0,
            right=point.right_weight * 100.0,
        )
        detail_rect = QRectF(
            max(region.left() + 6.0, apply_rect.left() - 190.0),
            region.top() + 4.0,
            max(0.0, apply_rect.left() - region.left() - 12.0),
            21.0,
        )
        painter.setPen(QColor("#9ccfc6"))
        painter.drawText(
            detail_rect,
            Qt.AlignRight | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(
                detail,
                Qt.ElideLeft,
                max(0, int(detail_rect.width())),
            ),
        )
        painter.restore()

    def _screen_point(
        self,
        geometry: QRectF,
        point: VelocityEnvelopePoint,
    ) -> QPointF:
        velocity_position = (
            max(self.MIN_VELOCITY, min(self.MAX_VELOCITY, point.velocity))
            - self.MIN_VELOCITY
        ) / (self.MAX_VELOCITY - self.MIN_VELOCITY)
        return QPointF(
            geometry.left() + point.time * geometry.width(),
            geometry.bottom() - velocity_position * geometry.height(),
        )

    def _paint_session(
        self,
        painter: QPainter,
        geometry: QRectF,
        session: _CurveSession,
    ) -> None:
        self._geometry = geometry
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(geometry.adjusted(-10.0, -10.0, 10.0, 10.0))
        painter.fillRect(geometry, QColor(20, 28, 27, 72))
        sample_count = max(32, min(240, round(geometry.width() / 3.0)))
        samples = velocity_envelope_samples(session.points, sample_count)
        path = QPainterPath(
            self._screen_point(
                geometry,
                VelocityEnvelopePoint(0.0, samples[0]),
            )
        )
        for index, gain in enumerate(samples[1:], start=1):
            path.lineTo(
                self._screen_point(
                    geometry,
                    VelocityEnvelopePoint(index / (sample_count - 1), gain),
                )
            )
        painter.setPen(QPen(QColor(17, 20, 20, 210), 5.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#e3c86f"), 2.2, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(path)
        screens = [self._screen_point(geometry, point) for point in session.points]
        for index, point in enumerate(session.points):
            screen = screens[index]
            sides = ("left", "right") if index == session.active_point else ()
            for side in sides:
                neighbor = index - 1 if side == "left" else index + 1
                if not 0 <= neighbor < len(session.points):
                    continue
                weight = point.left_weight if side == "left" else point.right_weight
                interval = abs(screens[neighbor].x() - screen.x())
                direction = -1.0 if side == "left" else 1.0
                weight_point = QPointF(
                    screen.x() + direction * interval * weight,
                    screen.y(),
                )
                active_weight = (
                    session.active_point == index
                    and session.active_control == f"{side}_weight"
                )
                painter.setPen(
                    QPen(
                        QColor("#75c9bd" if active_weight else "#667876"),
                        1.2,
                    )
                )
                painter.drawLine(screen, weight_point)
                weight_rect = QRectF(
                    weight_point.x() - 4.0,
                    weight_point.y() - 4.0,
                    8.0,
                    8.0,
                )
                painter.setBrush(
                    QColor("#91ded2" if active_weight else "#465c59")
                )
                painter.setPen(
                    QPen(
                        QColor("#b7eee6" if active_weight else "#7d9692"),
                        1.0,
                    )
                )
                painter.drawRect(weight_rect)
                self._hit_regions.append(
                    (
                        weight_rect.adjusted(-4.0, -4.0, 4.0, 4.0),
                        f"weight:{index}:{side}",
                    )
                )
            radius = self.POINT_RADIUS + (1.5 if index == session.active_point else 0.0)
            handle = QRectF(
                screen.x() - radius,
                screen.y() - radius,
                radius * 2.0,
                radius * 2.0,
            )
            painter.setBrush(QColor("#f3dfa0" if index in (0, len(session.points) - 1) else "#79c9bd"))
            painter.setPen(QPen(QColor("#17191a"), 1.5))
            painter.drawEllipse(handle)
            self._hit_regions.append((handle.adjusted(-3, -3, 3, 3), f"point:{index}"))
        painter.restore()

    def _activate(self) -> None:
        context = self._context
        if context is None or not context.note_indices:
            return
        self._session = _CurveSession(
            context.track,
            tuple(context.track.notes),
            context.start_ms,
            context.end_ms,
            context.note_indices,
            context.scope_source,
            list(
                velocity_envelope_points_from_notes(
                    context.track.notes,
                    context.note_indices,
                    start_ms=context.start_ms,
                    end_ms=context.end_ms,
                    max_points=self.MAX_POINTS,
                )
            ),
        )
        self.canvas.setFocus(Qt.MouseFocusReason)
        self.canvas.setToolTip(
            tr("单击创建节点；拖动节点精调；拖动左右手柄改变权重；右键删除中间节点")
        )
        self.canvas.update()

    def cancel(self) -> None:
        self._session = None
        self._dragging_point = None
        self._dragging_weight = None
        self._geometry = None
        self.canvas.unsetCursor()
        self.canvas.setToolTip(tr(self.canvas.KEYBOARD_SHORTCUT_HINT))
        self.canvas.update()

    def apply(self) -> None:
        session = self._session
        if session is None:
            return
        changed_notes = apply_velocity_level_envelope(
            session.baseline_notes,
            session.note_indices,
            session.points,
            start_ms=session.start_ms,
            end_ms=session.end_ms,
        )
        track = session.track
        self.cancel()
        if changed_notes != list(session.baseline_notes):
            self.commit_requested.emit(track, changed_notes)

    def _velocity_for_y(self, geometry: QRectF, y: float) -> float:
        position = max(
            0.0,
            min(1.0, (geometry.bottom() - y) / max(1.0, geometry.height())),
        )
        return round(
            self.MIN_VELOCITY
            + position * (self.MAX_VELOCITY - self.MIN_VELOCITY),
            1,
        )

    def _time_for_x(self, geometry: QRectF, x: float) -> float:
        return round(
            max(0.0, min(1.0, (x - geometry.left()) / max(1.0, geometry.width()))),
            5,
        )

    def _delete_point(self, index: int) -> bool:
        session = self._session
        if session is None or index <= 0 or index >= len(session.points) - 1:
            return False
        del session.points[index]
        session.active_point = min(index, len(session.points) - 1)
        session.active_control = "point"
        self._dragging_point = None
        self._dragging_weight = None
        self.canvas.update()
        return True

    def _add_point(self, position: QPointF) -> bool:
        session = self._session
        geometry = self._geometry
        if (
            session is None
            or geometry is None
            or not geometry.contains(position)
            or len(session.points) >= self.MAX_POINTS
        ):
            return False
        point = VelocityEnvelopePoint(
            self._time_for_x(geometry, position.x()),
            self._velocity_for_y(geometry, position.y()),
        )
        if point.time <= 0.0 or point.time >= 1.0:
            return False
        insertion = bisect_left([item.time for item in session.points], point.time)
        if (
            abs(session.points[insertion - 1].time - point.time) < self.MIN_POINT_GAP
            or abs(session.points[insertion].time - point.time) < self.MIN_POINT_GAP
        ):
            return False
        session.points.insert(insertion, point)
        session.active_point = insertion
        session.active_control = "point"
        self._dragging_point = insertion
        self.canvas.setCursor(Qt.ClosedHandCursor)
        self.canvas.update()
        return True

    def mouse_press(self, position: QPointF, button: Qt.MouseButton) -> bool:
        for rect, action in reversed(self._hit_regions):
            if not rect.contains(position):
                continue
            if action == "apply" and button == Qt.LeftButton:
                self.apply()
                return True
            if action == "cancel" and button == Qt.LeftButton:
                self.cancel()
                return True
            if action.startswith("weight:") and self._session is not None:
                _prefix, index_text, side = action.split(":", 2)
                if button == Qt.LeftButton:
                    index = int(index_text)
                    self._dragging_weight = (index, side)
                    self._dragging_point = None
                    self._session.active_point = index
                    self._session.active_control = f"{side}_weight"
                    self.canvas.setCursor(Qt.SizeHorCursor)
                    self.canvas.update()
                    return True
            if action.startswith("point:") and self._session is not None:
                index = int(action.partition(":")[2])
                if button == Qt.RightButton:
                    self._delete_point(index)
                    return True
                if button == Qt.LeftButton:
                    self._dragging_point = index
                    self._dragging_weight = None
                    self._session.active_point = index
                    self._session.active_control = "point"
                    self.canvas.setCursor(Qt.ClosedHandCursor)
                    self.canvas.update()
                    return True
        if (
            self._session is not None
            and self._geometry is not None
            and self._geometry.contains(position)
        ):
            if button == Qt.LeftButton:
                self._add_point(position)
            return True
        return False

    def mouse_move(self, position: QPointF) -> bool:
        session = self._session
        geometry = self._geometry
        if session is not None and geometry is not None and self._dragging_weight:
            index, side = self._dragging_weight
            point = session.points[index]
            cursor_time = self._time_for_x(geometry, position.x())
            if side == "left" and index > 0:
                interval = point.time - session.points[index - 1].time
                weight = (point.time - cursor_time) / max(1e-9, interval)
                session.points[index] = replace(
                    point,
                    left_weight=round(max(0.02, min(0.95, weight)), 5),
                )
            elif side == "right" and index < len(session.points) - 1:
                interval = session.points[index + 1].time - point.time
                weight = (cursor_time - point.time) / max(1e-9, interval)
                session.points[index] = replace(
                    point,
                    right_weight=round(max(0.02, min(0.95, weight)), 5),
                )
            self.canvas.update()
            return True
        index = self._dragging_point
        if session is None or geometry is None or index is None:
            return False
        current = session.points[index]
        time_position = current.time
        if 0 < index < len(session.points) - 1:
            lower = session.points[index - 1].time + self.MIN_POINT_GAP
            upper = session.points[index + 1].time - self.MIN_POINT_GAP
            time_position = max(
                lower,
                min(upper, self._time_for_x(geometry, position.x())),
            )
        session.points[index] = replace(
            current,
            time=round(time_position, 5),
            velocity=self._velocity_for_y(geometry, position.y()),
        )
        self.canvas.update()
        return True

    def mouse_release(self, button: Qt.MouseButton) -> bool:
        if button != Qt.LeftButton or (
            self._dragging_point is None and self._dragging_weight is None
        ):
            return False
        self._dragging_point = None
        self._dragging_weight = None
        self.canvas.unsetCursor()
        self.canvas.update()
        return True

    def key_press(self, event) -> bool:
        session = self._session
        if session is None:
            return False
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.apply()
            return True
        if event.key() == Qt.Key_Escape:
            self.cancel()
            return True
        if event.key() == Qt.Key_Tab:
            controls: list[tuple[int, str]] = []
            for index in range(len(session.points)):
                controls.append((index, "point"))
                if index > 0:
                    controls.append((index, "left_weight"))
                if index < len(session.points) - 1:
                    controls.append((index, "right_weight"))
            current = (session.active_point, session.active_control)
            current_index = controls.index(current) if current in controls else 0
            direction = -1 if event.modifiers() & Qt.ShiftModifier else 1
            session.active_point, session.active_control = controls[
                (current_index + direction) % len(controls)
            ]
            self.canvas.update()
            return True
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_point(session.active_point)
            return True
        if event.key() not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            return False
        fine = bool(event.modifiers() & Qt.ShiftModifier)
        velocity_step = 0.1 if fine else 1.0
        time_step = 0.0005 if fine else 0.005
        index = session.active_point
        point = session.points[index]
        if session.active_control in {"left_weight", "right_weight"}:
            if event.key() not in (Qt.Key_Left, Qt.Key_Right):
                return True
            weight_step = 0.002 if fine else 0.01
            delta = weight_step if event.key() == Qt.Key_Right else -weight_step
            field = session.active_control
            session.points[index] = replace(
                point,
                **{
                    field: round(
                        max(0.02, min(0.95, getattr(point, field) + delta)),
                        5,
                    )
                },
            )
            self.canvas.update()
            return True
        velocity = point.velocity
        time_position = point.time
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            velocity += velocity_step if event.key() == Qt.Key_Up else -velocity_step
        elif 0 < index < len(session.points) - 1:
            delta = time_step if event.key() == Qt.Key_Right else -time_step
            time_position = max(
                session.points[index - 1].time + self.MIN_POINT_GAP,
                min(
                    session.points[index + 1].time - self.MIN_POINT_GAP,
                    time_position + delta,
                ),
            )
        session.points[index] = replace(
            point,
            time=round(max(0.0, min(1.0, time_position)), 5),
            velocity=round(
                max(self.MIN_VELOCITY, min(self.MAX_VELOCITY, velocity)),
                1,
            ),
        )
        self.canvas.update()
        return True


__all__ = ["TimelineVelocityCurveOverlay"]
