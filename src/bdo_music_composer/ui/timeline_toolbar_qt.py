"""Compact popup groups for the multitrack timeline command bar."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QMenu, QWidget,
    QWidgetAction,
)

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.ui_controls import PillButton
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol


def build_arrangement_tool_buttons(
    parent: QWidget,
) -> tuple[QFrame, PillButton, PillButton, PillButton, QButtonGroup]:
    """Build compact icon-only Select/Razor controls for Track/Clip editing."""

    select = PillButton("", "ghost", FluentSymbol.SELECT)
    select.setCheckable(True)
    select.setChecked(True)
    select.setFixedSize(34, 30)
    select.setToolTip(tr("选择工具：移动或裁剪片段"))
    select.setAccessibleName(tr("选择工具"))
    razor = PillButton("", "ghost", FluentSymbol.RAZOR)
    razor.setCheckable(True)
    razor.setFixedSize(34, 30)
    razor.setToolTip(tr("剃刀工具：单击片段进行切分"))
    razor.setAccessibleName(tr("剃刀工具"))
    snap = PillButton(tr("吸附"), "ghost", FluentSymbol.MAGNET)
    snap.setObjectName("TimelineSnapToggle")
    snap.setCheckable(True)
    snap.setChecked(True)
    snap.setFixedHeight(30)
    snap.setMinimumWidth(66)
    snap.toggled.connect(
        lambda checked: _sync_snap_toggle_presentation(snap, checked)
    )
    _sync_snap_toggle_presentation(snap, snap.isChecked())
    group = QButtonGroup(parent)
    group.setExclusive(True)
    group.addButton(select, 0)
    group.addButton(razor, 1)
    tool_panel = QFrame(parent)
    tool_panel.setObjectName("CommandGroup")
    tool_layout = QHBoxLayout(tool_panel)
    tool_layout.setContentsMargins(2, 1, 2, 1)
    tool_layout.setSpacing(2)
    tool_layout.addWidget(select)
    tool_layout.addWidget(razor)
    return tool_panel, select, razor, snap, group


def _sync_snap_toggle_presentation(
    button: PillButton,
    checked: bool,
) -> None:
    """Expose snap as a persistent, visually explicit two-state control."""

    active = bool(checked)
    button.setProperty("snapActive", active)
    if active:
        button.setToolTip(tr(
            "自动吸附已激活：移动或裁切片段时自动对齐；再次点击关闭（Alt 临时关闭）"
        ))
        button.setAccessibleName(tr("自动吸附已激活"))
    else:
        button.setToolTip(tr(
            "自动吸附未激活：移动和裁切片段时不会自动对齐；点击开启"
        ))
        button.setAccessibleName(tr("自动吸附未激活"))
    button.style().unpolish(button)
    button.style().polish(button)


def build_timeline_popup_buttons(
    parent: QWidget,
    global_gain_control: QWidget,
    zoom_label: QWidget,
    zoom_control: QWidget,
    pan_label: QWidget,
    pan_control: QWidget,
    fit_button: QWidget,
) -> tuple[PillButton, PillButton]:
    """Move lower-frequency sliders into two keyboard-accessible popups."""

    mix_button = PillButton(tr("力度"), "ghost")
    mix_button.setToolTip(tr("全局力度基数"))
    mix_menu = QMenu(mix_button)
    mix_action = QWidgetAction(mix_menu)
    mix_action.setDefaultWidget(global_gain_control)
    mix_menu.addAction(mix_action)
    mix_button.setMenu(mix_menu)

    view_button = PillButton(tr("视图"), "ghost")
    view_button.setToolTip(tr("时间轴视图"))
    view_menu = QMenu(view_button)
    view_panel = QFrame(view_menu)
    view_panel.setObjectName("TimelineViewPopup")
    layout = QGridLayout(view_panel)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(8)
    layout.addWidget(zoom_label, 0, 0)
    layout.addWidget(zoom_control, 0, 1)
    layout.addWidget(pan_label, 1, 0)
    layout.addWidget(pan_control, 1, 1)
    layout.addWidget(fit_button, 2, 0, 1, 2)
    view_action = QWidgetAction(view_menu)
    view_action.setDefaultWidget(view_panel)
    view_menu.addAction(view_action)
    view_button.setMenu(view_menu)
    return mix_button, view_button
