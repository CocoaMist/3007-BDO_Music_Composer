"""Shortcut HUD anchored over the packaged piano-roll canvas."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from bdo_music_composer.ui.i18n import tr
from .editor_shortcuts import (
    DRAW_CONTEXT,
    EDITOR_GESTURE_SPECS,
    EDITOR_SHORTCUT_SPECS,
    EditorShortcutSpec,
    GLOBAL_SCOPE,
    HELP_GROUP_SOURCES,
    HUD_CONTEXT_COPY,
    SELECT_CONTEXT,
    SELECTION_CONTEXT,
)


class _ShortcutRow(QFrame):
    """One aligned shortcut/action pair inside the translucent HUD."""

    _KEY_WIDTH = 118

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutHudRow")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self.key_label = QLabel()
        self.key_label.setObjectName("ShortcutHudKey")
        self.key_label.setFixedWidth(self._KEY_WIDTH)
        self.key_label.setAlignment(Qt.AlignCenter)
        self.key_label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self.key_label)

        self.action_label = QLabel()
        self.action_label.setObjectName("ShortcutHudAction")
        self.action_label.setWordWrap(False)
        self.action_label.setTextInteractionFlags(Qt.NoTextInteraction)
        layout.addWidget(self.action_label, stretch=1)

    def set_copy(self, key_source: str, action_source: str) -> None:
        self.key_label.setText(tr(key_source))
        self.action_label.setText(tr(action_source))


class EditorShortcutHud(QFrame):
    """Show real editor commands without taking focus or mouse input."""

    SELECT_CONTEXT = SELECT_CONTEXT
    SELECTION_CONTEXT = SELECTION_CONTEXT
    DRAW_CONTEXT = DRAW_CONTEXT

    _MIN_WIDTH = 270
    _MAX_WIDTH = 390
    _EDGE_MARGIN = 10

    def __init__(self, canvas: QWidget) -> None:
        super().__init__(canvas)
        self._canvas = canvas
        self._context = self.SELECT_CONTEXT
        self._shortcut_active = bool(canvas.hasFocus())
        self._user_visible = False
        self.setObjectName("EditorShortcutHud")
        self.setProperty("hudMode", self._context)
        self.setProperty("shortcutActive", self._shortcut_active)
        self.setProperty("visualWeight", "quiet")
        self.setProperty("surfaceTreatment", "translucent")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName(tr("音符编辑器快捷键提示"))

        root = QVBoxLayout(self)
        root.setContentsMargins(9, 7, 9, 7)
        root.setSpacing(4)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("ShortcutHudMode")
        root.addWidget(self.mode_label)

        row_count = max(
            len(rows) for _mode_source, rows in HUD_CONTEXT_COPY.values()
        )
        self.shortcut_rows = tuple(
            _ShortcutRow(self) for _index in range(row_count)
        )
        for row in self.shortcut_rows:
            root.addWidget(row)

        canvas.installEventFilter(self)
        application = QApplication.instance()
        if application is not None:
            application.focusChanged.connect(self._focus_changed)
        self._refresh_copy()
        self.hide()
        self._schedule_reposition()

    @property
    def context(self) -> str:
        return self._context

    @property
    def user_visible(self) -> bool:
        return self._user_visible

    def set_user_visible(self, visible: bool) -> None:
        self._user_visible = bool(visible)
        self.reposition()

    def set_context(self, context: str) -> None:
        if context not in HUD_CONTEXT_COPY:
            raise ValueError(f"unknown editor shortcut HUD context: {context}")
        if context == self._context:
            return
        self._context = context
        self.setProperty("hudMode", context)
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_copy()
        self._schedule_reposition()

    def _refresh_copy(self) -> None:
        mode_source, copy_rows = HUD_CONTEXT_COPY[self._context]
        mode_text = tr(mode_source)
        if not self._shortcut_active:
            mode_text = f"{mode_text} · {tr('点击画布启用')}"
        self.mode_label.setText(mode_text)
        description_lines: list[str] = []
        for index, row in enumerate(self.shortcut_rows):
            if index >= len(copy_rows):
                row.hide()
                continue
            key_source, action_source = copy_rows[index]
            row.set_copy(key_source, action_source)
            row.show()
            description_lines.append(
                f"{tr(key_source)}：{tr(action_source)}"
            )
        self.setAccessibleDescription(
            "\n".join((mode_text, *description_lines))
        )

    @property
    def shortcut_active(self) -> bool:
        return self._shortcut_active

    def _focus_changed(self, _previous: QWidget | None, current: QWidget | None) -> None:
        active = current is self._canvas
        if active == self._shortcut_active:
            return
        self._shortcut_active = active
        self.setProperty("shortcutActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_copy()

    def retranslate_dynamic_content(self) -> None:
        """Refresh contextual copy after an in-place language switch."""

        self._refresh_copy()
        self._schedule_reposition()

    def _schedule_reposition(self) -> None:
        QTimer.singleShot(0, self._reposition_if_valid)

    def _reposition_if_valid(self) -> None:
        if not isValid(self) or not isValid(self._canvas):
            return
        self.reposition()

    def reposition(self) -> None:
        """Keep the HUD inside the editable grid and below the time ruler."""

        if not self._user_visible:
            self.hide()
            return

        canvas_width = self._canvas.width()
        key_width = int(getattr(self._canvas, "KEY_W", 0))
        available_width = canvas_width - key_width - self._EDGE_MARGIN * 2
        if available_width < self._MIN_WIDTH:
            self.hide()
            return

        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.layout().activate()
        natural_width = self.sizeHint().width()
        width = max(
            self._MIN_WIDTH,
            min(self._MAX_WIDTH, available_width, natural_width),
        )
        self.setFixedWidth(width)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
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
            self._schedule_reposition()
        return super().eventFilter(watched, event)


class EditorShortcutHelpDialog(QDialog):
    """Complete, registry-backed shortcut reference for the note editor."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("EditorShortcutHelpDialog")
        self.setWindowTitle(tr("音符编辑器快捷键"))
        self.setMinimumSize(620, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel(tr("音符编辑器快捷键"))
        title.setObjectName("ShortcutHelpTitle")
        root.addWidget(title)
        scope_note = QLabel(
            tr(
                "音块快捷键仅在钢琴卷帘画布获得焦点时生效；输入框保留文本编辑快捷键。F1 可随时打开本面板。"
            )
        )
        scope_note.setObjectName("ShortcutHelpScopeNote")
        scope_note.setWordWrap(True)
        root.addWidget(scope_note)

        scroll = QScrollArea()
        scroll.setObjectName("ShortcutHelpScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("ShortcutHelpContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 8, 2)
        content_layout.setSpacing(10)
        self.shortcut_rows: list[tuple[QLabel, QLabel]] = []

        entries = (*EDITOR_SHORTCUT_SPECS, *EDITOR_GESTURE_SPECS)
        for group_source in HELP_GROUP_SOURCES:
            group = QFrame()
            group.setObjectName("ShortcutHelpGroup")
            grid = QGridLayout(group)
            grid.setContentsMargins(10, 8, 10, 9)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(5)
            heading = QLabel(tr(group_source))
            heading.setObjectName("ShortcutHelpGroupTitle")
            grid.addWidget(heading, 0, 0, 1, 2)
            row = 1
            for entry in entries:
                if entry.group_source != group_source:
                    continue
                key_label = QLabel(tr(entry.key_source))
                key_label.setObjectName("ShortcutHelpKey")
                if (
                    isinstance(entry, EditorShortcutSpec)
                    and entry.scope == GLOBAL_SCOPE
                ):
                    action_text = (
                        f"{tr(entry.action_source)} · {tr('全窗口生效')}"
                    )
                else:
                    action_text = tr(entry.action_source)
                action_label = QLabel(action_text)
                action_label.setObjectName("ShortcutHelpAction")
                action_label.setWordWrap(True)
                grid.addWidget(key_label, row, 0)
                grid.addWidget(action_label, row, 1)
                self.shortcut_rows.append((key_label, action_label))
                row += 1
            content_layout.addWidget(group)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        close_button = QPushButton(tr("关闭"))
        close_button.setObjectName("ShortcutHelpClose")
        close_button.clicked.connect(self.close)
        root.addWidget(close_button, 0, Qt.AlignRight)
