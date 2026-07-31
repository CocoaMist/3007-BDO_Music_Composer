"""Packaged startup widgets isolated from main-window orchestration."""

from __future__ import annotations

from pathlib import Path
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from project_paths import ASSETS_DIR


STARTUP_ART_IMAGE = ASSETS_DIR / "ui" / "loading_conductor_lineart.png"


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
        self.setFixedSize(470, 734)
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
        painter.fillRect(self.rect(), QColor("#151515"))
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
        # Pull the bright sketch into the same dark tonal range as the home
        # page and utility dialogs so startup does not flash a white card.
        painter.fillRect(self.rect(), QColor(15, 15, 16, 54))
        shade = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        shade.setColorAt(0.0, QColor(24, 22, 19, 0))
        shade.setColorAt(0.62, QColor(18, 18, 19, 18))
        shade.setColorAt(1.0, QColor(15, 15, 16, 188))
        painter.fillRect(self.rect(), shade)


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
        self.setProperty("uiSurface", "startup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(470, 734)
        self._shown_at = time.monotonic()
        self._pending_window: QWidget | None = None
        self._finish_scheduled = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        card = QFrame()
        card.setObjectName("StartupSplashCard")
        card.setProperty("uiRole", "startupCanvas")
        outer.addWidget(card)
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self.artwork = StartupArtwork(STARTUP_ART_IMAGE)
        card_layout.addWidget(self.artwork, 0, 0)

        content = QFrame()
        content.setObjectName("StartupOverlay")
        content.setProperty("uiRole", "startupFooter")
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
                background: #151515;
                border: 1px solid #4a3b27;
                border-radius: 0;
            }
            QFrame#StartupOverlay {
                background: rgba(21, 21, 21, 238);
                border: 0;
                border-top: 1px solid #4a3b27;
                border-radius: 0;
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


__all__ = [
    "STARTUP_ART_IMAGE",
    "LoadingSpinner",
    "StartupArtwork",
    "StartupSplash",
]
