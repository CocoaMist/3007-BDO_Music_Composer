"""Reusable packaged Qt controls shared by editor surfaces."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from .theme.fluent_theme import FluentSymbol, fluent_icon_size, set_fluent_symbol


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
