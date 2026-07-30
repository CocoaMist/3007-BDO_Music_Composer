"""Reusable top-level toast notification for Qt editor surfaces."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)


class GlobalToast(QFrame):
    """One non-blocking message surface shared by each top-level window."""

    COLORS = {
        "info": "#f0c66f",
        "success": "#8fcf9d",
        "warning": "#f5a524",
        "error": "#ef8178",
    }
    MARKERS = {
        "info": "i",
        "success": "✓",
        "warning": "!",
        "error": "×",
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("GlobalToast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumWidth(270)
        self.setMaximumWidth(620)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 16, 8)
        layout.setSpacing(9)
        self.marker = QLabel(self.MARKERS["info"])
        self.marker.setObjectName("ToastMarker")
        self.marker.setFixedSize(20, 20)
        self.marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.marker, 0, Qt.AlignmentFlag.AlignVCenter)
        self.message = QLabel()
        self.message.setObjectName("ToastMessage")
        self.message.setWordWrap(True)
        self.message.setMaximumWidth(540)
        layout.addWidget(self.message, stretch=1)

        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._animation_finished)
        self._animation_phase = ""
        self._hold_duration_ms = 2600
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.fade_out)
        self._apply_kind_style("info")
        parent.installEventFilter(self)
        self.hide()

    def _apply_kind_style(self, kind: str) -> None:
        color = self.COLORS[kind]
        self.setProperty("toastKind", kind)
        self.setStyleSheet(
            f"""
            QFrame#GlobalToast {{
                background: rgba(20, 22, 21, 242);
                border: 0;
                border-left: 3px solid {color};
                border-bottom: 1px solid #453a2b;
                border-radius: 1px;
            }}
            QLabel#ToastMessage {{
                color: #e8e2d8;
                background: transparent;
                border: 0;
                font-family: "Microsoft YaHei UI";
                font-size: 11px;
                font-weight: 600;
            }}
            QLabel#ToastMarker {{
                color: {color};
                background: rgba(0, 0, 0, 48);
                border: 1px solid {color};
                border-radius: 2px;
                font-family: "Microsoft YaHei UI";
                font-size: 10px;
                font-weight: 900;
            }}
            """
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parent() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            QTimer.singleShot(0, self._reposition)
        return super().eventFilter(watched, event)

    def show_message(self, text: str, kind: str = "info", duration_ms: int = 2600) -> None:
        if not text:
            return
        resolved_kind = kind if kind in self.COLORS else "info"
        self.animation.stop()
        self.hold_timer.stop()
        self._apply_kind_style(resolved_kind)
        self.marker.setText(self.MARKERS[resolved_kind])
        self.message.setText(text)
        self.message.ensurePolished()
        parent = self.parentWidget()
        available_width = min(
            540,
            max(220, (parent.width() - 110) if parent is not None else 540),
        )
        natural_width = self.message.fontMetrics().horizontalAdvance(text) + 4
        self.message.setFixedWidth(
            max(220, min(available_width, natural_width))
        )
        self.setAccessibleName(text)
        self.opacity.setOpacity(0.0)
        self.show()
        self.adjustSize()
        self._reposition()
        self.raise_()
        self.animation.setDuration(170)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self._animation_phase = "in"
        self._hold_duration_ms = max(0, duration_ms)
        self.animation.start()

    def fade_out(self) -> None:
        self.animation.stop()
        self.animation.setDuration(260)
        self.animation.setStartValue(self.opacity.opacity())
        self.animation.setEndValue(0.0)
        self._animation_phase = "out"
        self.animation.start()

    def _animation_finished(self) -> None:
        if self._animation_phase == "in":
            self.hold_timer.start(self._hold_duration_ms)
        elif self._animation_phase == "out":
            self.hide()
        self._animation_phase = ""

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return
        x = max(16, (parent.width() - self.width()) // 2)
        if parent.objectName() == "MidiNoteEditorDialog":
            workspace = parent.findChild(QFrame, "EditorWorkspace")
            y = (workspace.geometry().top() + 12) if workspace is not None else 148
        elif parent.objectName() == "SettingsDialog":
            content = parent.findChild(QWidget, "SettingsContent")
            y = (content.geometry().top() + 12) if content is not None else 84
        else:
            toolbar = parent.findChild(QFrame, "Toolbar")
            if toolbar is not None:
                toolbar_top = toolbar.mapTo(parent, toolbar.rect().topLeft()).y()
                y = toolbar_top + toolbar.height() + 8
            else:
                y = 16
        self.move(x, y)

def show_global_toast(
    host: QWidget,
    text: str,
    kind: str = "info",
    duration_ms: int = 2600,
) -> GlobalToast:
    top_level = host.window()
    toast = getattr(top_level, "_global_toast", None)
    if not isinstance(toast, GlobalToast):
        toast = GlobalToast(top_level)
        setattr(top_level, "_global_toast", toast)
    # Callers translate fixed copy before it reaches this dynamic display
    # boundary.  Re-translating here could corrupt a filename or track name
    # that happens to equal a catalog value such as "Play".
    toast.show_message(text, kind=kind, duration_ms=duration_ms)
    return toast
