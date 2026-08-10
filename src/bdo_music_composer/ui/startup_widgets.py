"""Short, state-honest reveal from the prepared home surface."""

from __future__ import annotations

import time

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    Property,
    QPropertyAnimation,
    QRect,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.ui.i18n import tr


class _LoadingSpinner(QWidget):
    """A restrained score-line pulse rather than a generic busy spinner."""

    def __init__(self, size: int = 42, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LoadingSpinner")
        self.setProperty("animationStyle", "scoreLine")
        self.setFixedSize(size, size)
        self._frame = 0
        self._complete = False
        self._timer = QTimer(self)
        self._timer.setInterval(65)
        self._timer.timeout.connect(self._advance)

    @property
    def frame(self) -> int:
        return self._frame

    def start(self) -> None:
        self._complete = False
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def complete(self) -> None:
        self._complete = True
        self.stop()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:
        self.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % 48
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_y = self.height() / 2.0
        left = 3.0
        right = self.width() - 3.0
        center_x = self.width() / 2.0

        painter.setPen(QPen(QColor(207, 171, 104, 70), 1.0))
        painter.drawLine(QPointF(left, center_y), QPointF(right, center_y))
        for ratio in (0.18, 0.34, 0.66, 0.82):
            x = left + (right - left) * ratio
            painter.drawLine(QPointF(x, center_y - 2.0), QPointF(x, center_y + 2.0))

        diamond = QPolygonF((
            QPointF(center_x, center_y - 4.0),
            QPointF(center_x + 4.0, center_y),
            QPointF(center_x, center_y + 4.0),
            QPointF(center_x - 4.0, center_y),
        ))
        if self._complete:
            painter.setPen(QPen(QColor(232, 198, 132, 225), 1.25))
            painter.drawLine(QPointF(left, center_y), QPointF(right, center_y))
            painter.setBrush(QColor(224, 180, 95, 230))
            painter.drawPolygon(diamond)
            return

        phase = self._frame / 47.0
        pulse_x = left + (right - left) * phase
        glow = QRadialGradient(QPointF(pulse_x, center_y), 9.0)
        glow.setColorAt(0.0, QColor(245, 207, 134, 105))
        glow.setColorAt(0.55, QColor(229, 178, 82, 36))
        glow.setColorAt(1.0, QColor(229, 178, 82, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(pulse_x, center_y), 9.0, 9.0)
        highlight = QLinearGradient(pulse_x - 8.0, 0.0, pulse_x + 8.0, 0.0)
        highlight.setColorAt(0.0, QColor(237, 195, 113, 0))
        highlight.setColorAt(0.5, QColor(246, 217, 159, 245))
        highlight.setColorAt(1.0, QColor(237, 195, 113, 0))
        painter.setPen(QPen(highlight, 1.6))
        painter.drawLine(
            QPointF(max(left, pulse_x - 8.0), center_y),
            QPointF(min(right, pulse_x + 8.0), center_y),
        )
        painter.setPen(QPen(QColor(197, 151, 70, 150), 1.0))
        painter.setBrush(QColor(30, 28, 24, 230))
        painter.drawPolygon(diamond)


class StartupReveal(QWidget):
    """Briefly dim the prepared home surface, then reveal it in place."""

    MINIMUM_VISIBLE_MS = 360
    READY_HOLD_MS = 120
    FADE_OUT_MS = 260

    finished = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("StartupReveal")
        self.setProperty("uiSurface", "startup")
        self.setProperty("revealStyle", "salonScore")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._shown_at = time.monotonic()
        self._finish_scheduled = False
        self._fade_opacity = 1.0
        self._fade_mode = "hold"
        self._target_window_geometry: QRect | None = None
        self._startup_surface = QPixmap()
        self._home_snapshot = QPixmap()
        self._fade_out_animation: QPropertyAnimation | None = None
        parent.installEventFilter(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addStretch(1)

        self.content = QFrame()
        self.content.setObjectName("StartupOverlay")
        self.content.setProperty("overlayMode", "textOnly")
        self.content.setMaximumWidth(560)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(34, 22, 34, 26)
        layout.setSpacing(7)

        eyebrow = QLabel("BDO MUSIC COMPOSER")
        eyebrow.setObjectName("StartupEyebrow")
        layout.addWidget(eyebrow)
        title = QLabel(tr("正在打开曲谱工作台"))
        title.setObjectName("StartupTitle")
        layout.addWidget(title)
        layout.addSpacing(2)

        activity = QHBoxLayout()
        activity.setSpacing(14)
        self.spinner = _LoadingSpinner(42)
        activity.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
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
        root.addWidget(self.content, alignment=Qt.AlignmentFlag.AlignLeft)

        self.setStyleSheet(
            """
            QWidget#StartupReveal { background: transparent; }
            QFrame#StartupOverlay {
                background: rgba(14, 14, 15, 178);
                border: 0;
                border-top: 1px solid rgba(191, 145, 66, 150);
            }
            QLabel#StartupEyebrow {
                color: #bd9557;
                font-family: "Segoe UI Semibold", "Microsoft YaHei UI";
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#StartupTitle {
                color: #eee6d8;
                font-family: "Microsoft YaHei UI", "Segoe UI";
                font-size: 17px;
                font-weight: 600;
            }
            QLabel#StartupStatus {
                color: #d8bd87;
                font-family: "Microsoft YaHei UI";
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#StartupDetail {
                color: #9e978c;
                font-family: "Microsoft YaHei UI";
                font-size: 9px;
            }
            """
        )
        self._content_opacity = QGraphicsOpacityEffect(self.content)
        self._content_opacity.setOpacity(1.0)
        self.content.setGraphicsEffect(self._content_opacity)
        self.setGeometry(parent.rect())

    @property
    def target_window_geometry(self) -> QRect | None:
        return (
            None
            if self._target_window_geometry is None
            else QRect(self._target_window_geometry)
        )

    @property
    def has_artwork(self) -> bool:
        return not self._home_snapshot.isNull()

    @property
    def fade_mode(self) -> str:
        return self._fade_mode

    def _get_fade_opacity(self) -> float:
        return self._fade_opacity

    def _set_fade_opacity(self, value: float) -> None:
        opacity = min(1.0, max(0.0, float(value)))
        if opacity == self._fade_opacity:
            return
        self._fade_opacity = opacity
        self._content_opacity.setOpacity(opacity)
        self.update()

    fadeOpacity = Property(float, _get_fade_opacity, _set_fade_opacity)

    def prepare_window(self) -> None:
        """Capture the final home geometry for a spatially continuous reveal."""

        window = self.parentWidget()
        if window is None:
            return
        screen = window.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        minimum = window.minimumSize()
        target = QRect(
            0,
            0,
            max(minimum.width(), min(window.width(), available.width())),
            max(minimum.height(), min(window.height(), available.height())),
        )
        target.moveCenter(available.center())
        self._target_window_geometry = target
        window.setGeometry(target)
        window.ensurePolished()
        if window.layout() is not None:
            window.layout().activate()

        central_widget = getattr(window, "centralWidget", lambda: None)()
        if central_widget is not None:
            central_widget.ensurePolished()
            if central_widget.layout() is not None:
                central_widget.layout().activate()
            snapshot = central_widget.grab()
            self._home_snapshot = self._scaled_surface(snapshot, target.size())

        self._startup_surface = self._render_startup_surface(
            self._home_snapshot,
            target.size(),
        )
        self.setGeometry(window.rect())

    @staticmethod
    def _scaled_surface(source: QPixmap, size) -> QPixmap:
        if source.isNull() or source.size() == size:
            return source
        return source.scaled(
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _render_startup_surface(self, home_snapshot: QPixmap, size) -> QPixmap:
        if home_snapshot.isNull():
            surface = QPixmap(size)
            surface.fill(QColor("#0d0e10"))
        else:
            surface = self._scaled_surface(home_snapshot, size).copy()

        painter = QPainter(surface)
        painter.fillRect(surface.rect(), QColor(9, 10, 11, 104))
        warmth = QRadialGradient(
            QPointF(size.width() * 0.19, size.height() * 0.74),
            max(size.width(), size.height()) * 0.66,
        )
        warmth.setColorAt(0.0, QColor(103, 72, 34, 34))
        warmth.setColorAt(0.48, QColor(49, 34, 20, 14))
        warmth.setColorAt(1.0, QColor(5, 6, 7, 0))
        painter.fillRect(surface.rect(), warmth)
        shade = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
        shade.setColorAt(0.0, QColor(12, 12, 13, 18))
        shade.setColorAt(0.58, QColor(12, 12, 13, 28))
        shade.setColorAt(0.82, QColor(9, 9, 10, 112))
        shade.setColorAt(1.0, QColor(7, 8, 9, 196))
        painter.fillRect(surface.rect(), shade)
        staff_left = size.width() * 0.48
        staff_right = size.width() * 0.94
        staff_top = size.height() * 0.78
        painter.setPen(QPen(QColor(205, 175, 116, 22), 1.0))
        for line in range(5):
            y = staff_top + line * 7.0
            painter.drawLine(QPointF(staff_left, y), QPointF(staff_right, y))
        painter.end()
        return surface

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        if not self._startup_surface.isNull():
            painter.setOpacity(self._fade_opacity)
            painter.drawPixmap(self.rect(), self._startup_surface)
        elif self._fade_opacity > 0.0:
            painter.fillRect(
                self.rect(),
                QColor(13, 14, 16, round(255 * self._fade_opacity)),
            )

    def showEvent(self, event) -> None:
        self._shown_at = time.monotonic()
        self._finish_scheduled = False
        self._fade_mode = "hold"
        self._set_fade_opacity(1.0)
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.spinner.start()
        self.raise_()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def hideEvent(self, event) -> None:
        self.spinner.stop()
        super().hideEvent(event)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def finish(self, minimum_visible_ms: int | None = None) -> None:
        if self._finish_scheduled:
            return
        self._finish_scheduled = True
        self.set_status(tr("准备完成"))
        self.spinner.complete()
        minimum = (
            self.MINIMUM_VISIBLE_MS
            if minimum_visible_ms is None
            else max(0, minimum_visible_ms)
        )
        elapsed = round((time.monotonic() - self._shown_at) * 1000.0)
        delay = max(self.READY_HOLD_MS, minimum - elapsed)
        QTimer.singleShot(delay, self._begin_fade_out)

    def abort(self) -> None:
        if self._fade_out_animation is not None:
            self._fade_out_animation.stop()
        self.hide()

    def _begin_fade_out(self) -> None:
        self._fade_mode = "out"
        animation = QPropertyAnimation(self, b"fadeOpacity", self)
        animation.setDuration(self.FADE_OUT_MS)
        animation.setStartValue(self._fade_opacity)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self._complete_reveal)
        self._fade_out_animation = animation
        animation.start()

    def _complete_reveal(self) -> None:
        self.hide()
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
            parent.raise_()
            parent.activateWindow()
        self._fade_out_animation = None
        self.finished.emit()


__all__ = ["StartupReveal"]
