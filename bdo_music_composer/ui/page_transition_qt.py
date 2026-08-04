"""Short snapshot crossfades for synchronous stacked-page navigation."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QStackedWidget,
    QWidget,
)


class StackedPageCrossfade(QObject):
    """Crossfade a synchronous page commit without delaying application state."""

    def __init__(self, stack: QStackedWidget) -> None:
        super().__init__(stack)
        self.stack = stack
        self._group: QParallelAnimationGroup | None = None
        self._overlay: QLabel | None = None

    @property
    def is_running(self) -> bool:
        return bool(
            self._group is not None
            and self._group.state() == QAbstractAnimation.State.Running
        )

    def capture_current_page(self) -> QPixmap | None:
        """Capture the visible page before its synchronous replacement."""

        self.finish()
        if not self.stack.isVisible() or self.stack.size().isEmpty():
            return None
        snapshot = self.stack.grab()
        return None if snapshot.isNull() else snapshot

    def fade_from(self, snapshot: QPixmap | None, target: QWidget) -> None:
        if snapshot is None or not self.stack.isVisible():
            return
        self.finish()
        overlay = QLabel(self.stack)
        overlay.setObjectName("MainPageTransitionOverlay")
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay.setGeometry(self.stack.rect())
        overlay.setPixmap(snapshot)
        overlay.setScaledContents(True)
        overlay.show()
        overlay.raise_()

        outgoing_effect = QGraphicsOpacityEffect(overlay)
        outgoing_effect.setOpacity(1.0)
        overlay.setGraphicsEffect(outgoing_effect)

        # Keep the newly committed workspace fully rendered behind the frozen
        # outgoing snapshot. Applying an opacity effect to the live target
        # forces Qt to re-compose the entire editor subtree on every animation
        # tick, which is disproportionately expensive for dense timelines.
        if target.graphicsEffect() is not None:
            target.setGraphicsEffect(None)

        group = QParallelAnimationGroup(self)
        outgoing = QPropertyAnimation(outgoing_effect, b"opacity", group)
        outgoing.setDuration(180)
        outgoing.setStartValue(1.0)
        outgoing.setEndValue(0.0)
        outgoing.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(outgoing)

        self._group = group
        self._overlay = overlay
        group.finished.connect(lambda current=group: self._finished(current))
        group.start()

    def finish(self) -> None:
        group = self._group
        self._group = None
        if group is not None:
            group.stop()
            group.deleteLater()
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()

    def _finished(self, group: QParallelAnimationGroup) -> None:
        if group is self._group:
            self.finish()


__all__ = ["StackedPageCrossfade"]
