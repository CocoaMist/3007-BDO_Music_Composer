"""Game-inspired, accessible controls shared by the effect dialogs."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox,
    QDial,
    QFrame,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class GameEffectDial(QDial):
    """A lightweight Windows-safe dial with the composer's game visual language."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GameEffectDial")
        self.setRange(0, 100)
        self.setNotchesVisible(False)
        self.setWrapping(False)
        self.setTracking(True)
        self.setFixedSize(112, 112)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = min(self.width(), self.height()) / 2.0 - 7.0
        enabled = self.isEnabled()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(7, 8, 9, 120))
        painter.drawEllipse(center, radius, radius)
        painter.setBrush(QColor(71, 61, 46, 130 if enabled else 70))
        painter.drawEllipse(center, radius - 3.0, radius - 3.0)

        face_radius = radius - 7.0
        face = QRadialGradient(
            center.x() - face_radius * 0.28,
            center.y() - face_radius * 0.34,
            face_radius * 1.35,
        )
        if enabled:
            face.setColorAt(0.0, QColor("#53535b"))
            face.setColorAt(0.55, QColor("#34343a"))
            face.setColorAt(1.0, QColor("#1a1b1e"))
        else:
            face.setColorAt(0.0, QColor("#37373b"))
            face.setColorAt(1.0, QColor("#202124"))
        painter.setBrush(face)
        painter.drawEllipse(center, face_radius, face_radius)

        arc_rect = QRectF(
            center.x() - face_radius + 4.0,
            center.y() - face_radius + 4.0,
            (face_radius - 4.0) * 2.0,
            (face_radius - 4.0) * 2.0,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#17181b"), 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(arc_rect, 225 * 16, -270 * 16)

        ratio = (self.value() - self.minimum()) / max(
            1,
            self.maximum() - self.minimum(),
        )
        if ratio > 0.0:
            active = QLinearGradient(arc_rect.bottomLeft(), arc_rect.topRight())
            active.setColorAt(0.0, QColor("#8f6426"))
            active.setColorAt(1.0, QColor("#f0c76d"))
            painter.setPen(QPen(active, 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(arc_rect, 225 * 16, int(-270.0 * ratio * 16.0))

        for tick in range(11):
            tick_ratio = tick / 10.0
            angle = math.radians(135.0 + 270.0 * tick_ratio)
            outer = face_radius - 8.0
            inner = outer - (5.0 if tick in (0, 5, 10) else 3.0)
            color = QColor("#9b8562") if tick_ratio <= ratio and enabled else QColor("#4b4a48")
            painter.setPen(QPen(color, 1.2))
            painter.drawLine(
                QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner),
                QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer),
            )

        angle = math.radians(135.0 + 270.0 * ratio)
        painter.setPen(QPen(QColor("#f3eee4") if enabled else QColor("#77736d"), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(
            QPointF(center.x() + math.cos(angle) * 9.0, center.y() + math.sin(angle) * 9.0),
            QPointF(center.x() + math.cos(angle) * (face_radius - 13.0), center.y() + math.sin(angle) * (face_radius - 13.0)),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d8b66b") if enabled else QColor("#68645d"))
        painter.drawEllipse(center, 3.0, 3.0)


class EffectControlCard(QFrame):
    """A game-style rack slot backed by an exact numeric spin box."""

    def __init__(
        self,
        title: str,
        field: QSpinBox,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EffectControlCard")
        self.setProperty("uiRole", "effectControlCard")
        self.setMinimumWidth(132)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 11, 10, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        label = QLabel(title)
        label.setObjectName("EffectControlTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.dial = GameEffectDial(self)
        self.dial.setRange(field.minimum(), field.maximum())
        self.dial.setValue(field.value())
        self.dial.setEnabled(field.isEnabled())
        self.dial.setAccessibleName(field.accessibleName() or title)
        self.dial.setToolTip(field.toolTip())
        self.dial.valueChanged.connect(field.setValue)
        field.valueChanged.connect(self.dial.setValue)
        layout.addWidget(self.dial, alignment=Qt.AlignmentFlag.AlignHCenter)

        field.setParent(self)
        field.setProperty("uiRole", "effectValue")
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setFixedSize(88, 32)
        layout.addWidget(field, alignment=Qt.AlignmentFlag.AlignHCenter)

        scale = QLabel("0     100")
        scale.setObjectName("EffectControlScale")
        scale.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scale.setProperty("i18nSkip", True)
        layout.addWidget(scale)


class EffectModeCard(QFrame):
    """A special source-mode slot that belongs visually to the effect rack."""

    def __init__(
        self,
        title: str,
        selector: QComboBox,
        note: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EffectModeCard")
        self.setProperty("uiRole", "effectModeCard")
        self.setMinimumWidth(184)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 11, 10, 12)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        label = QLabel(title)
        label.setObjectName("EffectControlTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        emblem_stage = QWidget(self)
        emblem_stage.setObjectName("EffectModeStage")
        emblem_stage.setFixedSize(112, 112)
        emblem_layout = QVBoxLayout(emblem_stage)
        emblem_layout.setContentsMargins(0, 0, 0, 0)
        emblem_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emblem = QLabel("M")
        emblem.setObjectName("EffectModeEmblem")
        emblem.setProperty("i18nSkip", True)
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emblem.setFixedSize(92, 92)
        emblem_layout.addWidget(emblem)
        layout.addWidget(emblem_stage, alignment=Qt.AlignmentFlag.AlignHCenter)

        selector.setParent(self)
        selector.setObjectName("MarnianModeSelector")
        selector.setProperty("uiRole", "effectModeSelector")
        selector.setAccessibleName(title)
        selector.setToolTip(note)
        selector.setMinimumWidth(164)
        selector.setFixedHeight(32)
        layout.addWidget(selector, alignment=Qt.AlignmentFlag.AlignHCenter)

        hint = QLabel("SOURCE MODE")
        hint.setObjectName("EffectModeNote")
        hint.setProperty("i18nSkip", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setToolTip(note)
        layout.addWidget(hint)


__all__ = ["EffectControlCard", "EffectModeCard", "GameEffectDial"]
