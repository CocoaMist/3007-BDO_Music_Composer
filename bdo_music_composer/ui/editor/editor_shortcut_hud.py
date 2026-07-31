"""Shortcut HUD anchored over the packaged piano-roll canvas."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from i18n import tr


class EditorShortcutHud(QFrame):
    """Show real editor commands without taking focus or mouse input."""

    SELECT_CONTEXT = "select"
    SELECTION_CONTEXT = "selection"
    DRAW_CONTEXT = "draw"

    _CONTEXT_COPY = {
        SELECT_CONTEXT: (
            "选择模式",
            "双击 新建 · B 绘制 · Ctrl+拖动 复制 · Space 播放",
        ),
        SELECTION_CONTEXT: (
            "已选音符",
            "方向键 移动 · Shift+←→ 时值 · Ctrl+↑↓ 力度 · Del 删除",
        ),
        DRAW_CONTEXT: (
            "绘制模式",
            "拖动 长度/力度 · Alt 取消吸附 · B/Esc 退出",
        ),
    }
    _MIN_WIDTH = 300
    _MAX_WIDTH = 520
    _EDGE_MARGIN = 10

    def __init__(self, canvas: QWidget) -> None:
        super().__init__(canvas)
        self._canvas = canvas
        self._context = self.SELECT_CONTEXT
        self.setObjectName("EditorShortcutHud")
        self.setProperty("hudMode", self._context)
        self.setProperty("visualWeight", "quiet")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName(tr("音符编辑器快捷键提示"))

        root = QHBoxLayout(self)
        root.setContentsMargins(9, 4, 9, 4)
        root.setSpacing(8)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("ShortcutHudMode")
        root.addWidget(self.mode_label)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("ShortcutHudHint")
        self.hint_label.setWordWrap(False)
        self.hint_label.setTextInteractionFlags(Qt.NoTextInteraction)
        root.addWidget(self.hint_label, stretch=1)

        canvas.installEventFilter(self)
        self._refresh_copy()
        self.show()
        QTimer.singleShot(0, self.reposition)

    @property
    def context(self) -> str:
        return self._context

    def set_context(self, context: str) -> None:
        if context not in self._CONTEXT_COPY:
            raise ValueError(f"unknown editor shortcut HUD context: {context}")
        if context == self._context:
            return
        self._context = context
        self.setProperty("hudMode", context)
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_copy()
        QTimer.singleShot(0, self.reposition)

    def _refresh_copy(self) -> None:
        mode_source, hint_source = self._CONTEXT_COPY[self._context]
        self.mode_label.setText(tr(mode_source))
        self.hint_label.setText(tr(hint_source))
        self.setAccessibleDescription(
            f"{tr(mode_source)}：{tr(hint_source)}"
        )

    def retranslate_dynamic_content(self) -> None:
        """Refresh contextual copy after an in-place language switch."""

        self._refresh_copy()
        QTimer.singleShot(0, self.reposition)

    def reposition(self) -> None:
        """Keep the HUD inside the editable grid and below the time ruler."""

        canvas_width = self._canvas.width()
        key_width = int(getattr(self._canvas, "KEY_W", 0))
        available_width = canvas_width - key_width - self._EDGE_MARGIN * 2
        if available_width < self._MIN_WIDTH:
            self.hide()
            return

        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.hint_label.setMaximumWidth(self._MAX_WIDTH)
        self.layout().activate()
        natural_width = self.layout().sizeHint().width()
        width = max(
            self._MIN_WIDTH,
            min(self._MAX_WIDTH, available_width, natural_width),
        )
        self.setFixedWidth(width)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.hint_label.setMaximumWidth(
            width - self.mode_label.sizeHint().width() - 26
        )
        self.layout().activate()
        self.setFixedHeight(self.sizeHint().height())

        ruler_height = int(getattr(self._canvas, "RULER_H", 0))
        x = max(
            key_width + self._EDGE_MARGIN,
            canvas_width - width - self._EDGE_MARGIN,
        )
        y = ruler_height + 8
        self.move(x, y)
        self.show()
        self.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._canvas and event.type() in {
            QEvent.Resize,
            QEvent.Show,
        }:
            QTimer.singleShot(0, self.reposition)
        return super().eventFilter(watched, event)
