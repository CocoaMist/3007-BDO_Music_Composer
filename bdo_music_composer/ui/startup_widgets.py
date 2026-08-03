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
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
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
    def __init__(self, size: int = 42, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LoadingSpinner")
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
        self._frame = (self._frame + 1) % 12
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._complete:
            pen = QPen(QColor(245, 165, 36, 235), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QColor(245, 165, 36, 20))
            inset = 5.0
            painter.drawEllipse(
                QPointF(self.width() / 2.0, self.height() / 2.0),
                self.width() / 2.0 - inset,
                self.height() / 2.0 - inset,
            )
            painter.drawLine(
                QPointF(self.width() * 0.28, self.height() * 0.52),
                QPointF(self.width() * 0.44, self.height() * 0.68),
            )
            painter.drawLine(
                QPointF(self.width() * 0.44, self.height() * 0.68),
                QPointF(self.width() * 0.74, self.height() * 0.34),
            )
            return
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
        self.content.setMaximumWidth(620)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(44, 22, 44, 40)
        layout.setSpacing(10)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        eyebrow = QLabel("BDO MUSIC COMPOSER")
        eyebrow.setObjectName("StartupEyebrow")
        brand.addWidget(eyebrow)
        title = QLabel(tr("正在打开曲谱工作台"))
        title.setObjectName("StartupTitle")
        brand.addWidget(title)
        brand.addStretch(1)
        layout.addLayout(brand)

        activity = QHBoxLayout()
        activity.setSpacing(14)
        self.spinner = _LoadingSpinner(34)
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
            QFrame#StartupOverlay { background: transparent; border: 0; }
            QLabel#StartupEyebrow {
                color: #d89b37;
                font-family: "Microsoft YaHei UI";
                font-size: 10px;
                font-weight: 900;
                letter-spacing: 2px;
            }
            QLabel#StartupTitle {
                color: #e1d9cb;
                font-family: "Microsoft YaHei UI";
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#StartupStatus {
                color: #f0c66f;
                font-family: "Microsoft YaHei UI";
                font-size: 14px;
                font-weight: 800;
            }
            QLabel#StartupDetail {
                color: #c5bdb0;
                font-family: "Microsoft YaHei UI";
                font-size: 10px;
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
        painter.fillRect(surface.rect(), QColor(9, 10, 11, 92))
        shade = QLinearGradient(0.0, 0.0, 0.0, float(size.height()))
        shade.setColorAt(0.0, QColor(12, 12, 13, 18))
        shade.setColorAt(0.58, QColor(12, 12, 13, 28))
        shade.setColorAt(0.82, QColor(9, 9, 10, 112))
        shade.setColorAt(1.0, QColor(7, 8, 9, 196))
        painter.fillRect(surface.rect(), shade)
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
