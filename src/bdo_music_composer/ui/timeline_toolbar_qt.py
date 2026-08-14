"""Compact popup groups for the multitrack timeline command bar."""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QMenu, QWidget,
    QWidgetAction,
)

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.ui_controls import PillButton
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol


class TimelineViewButtons(NamedTuple):
    fit_width: PillButton
    fit_tracks: PillButton
    reset_layout: PillButton
    fold_groups: PillButton
    expand_groups: PillButton


def apply_arrangement_tool_toggle(
    timeline,
    marquee: PillButton,
    select: PillButton,
    razor: PillButton,
    tool: str,
    checked: bool,
) -> None:
    """Publish the one explicit tool selected by the exclusive group."""

    if checked:
        timeline.set_arrangement_tool(tool)


def bind_arrangement_tool_buttons(
    timeline, marquee: PillButton, select: PillButton, razor: PillButton
) -> None:
    """Bind explicit Marquee, Move/Resize and Razor tool states."""

    marquee.toggled.connect(lambda checked: apply_arrangement_tool_toggle(
        timeline, marquee, select, razor, "marquee", checked
    ))
    select.toggled.connect(lambda checked: apply_arrangement_tool_toggle(
        timeline, marquee, select, razor, "select", checked
    ))
    razor.toggled.connect(lambda checked: apply_arrangement_tool_toggle(
        timeline, marquee, select, razor, "razor", checked
    ))


def build_arrangement_tool_buttons(
    parent: QWidget,
) -> tuple[QFrame, PillButton, PillButton, PillButton, PillButton, QButtonGroup]:
    """Build explicit Marquee/Move-resize/Razor controls for the timeline."""

    marquee = PillButton("", "ghost", FluentSymbol.MARQUEE)
    marquee.setObjectName("TimelineToolButton")
    marquee.setCheckable(True)
    marquee.setFixedSize(34, 30)
    marquee.setToolTip(tr(
        "框选工具：拖动框选多个片段；所选片段只在片段编辑状态下移动"
    ))
    marquee.setAccessibleName(tr("框选工具"))
    select = PillButton("", "ghost", FluentSymbol.SELECT)
    select.setObjectName("TimelineToolButton")
    select.setCheckable(True)
    select.setChecked(True)
    select.setFixedSize(34, 30)
    select.setToolTip(tr(
        "移动/调整音块：拖动主体移动，拖动右边界改变编辑区域"
    ))
    select.setAccessibleName(tr("移动/调整音块"))
    razor = PillButton("", "ghost", FluentSymbol.RAZOR)
    razor.setObjectName("TimelineToolButton")
    razor.setCheckable(True)
    razor.setFixedSize(34, 30)
    razor.setToolTip(tr("剃刀工具：单击片段进行切分；再次点击关闭"))
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
    # One tool is always active; Select is the default editing state.
    group.setExclusive(True)
    group.addButton(marquee, 0)
    group.addButton(select, 1)
    group.addButton(razor, 2)
    tool_panel = QFrame(parent)
    tool_panel.setObjectName("CommandGroup")
    tool_layout = QHBoxLayout(tool_panel)
    tool_layout.setContentsMargins(2, 1, 2, 1)
    tool_layout.setSpacing(2)
    tool_layout.addWidget(marquee)
    tool_layout.addWidget(select)
    tool_layout.addWidget(razor)
    return tool_panel, marquee, select, razor, snap, group


def build_timeline_view_buttons(
    parent: QWidget,
) -> TimelineViewButtons:
    """Build and bind the lower-frequency timeline layout commands."""

    fit_width = PillButton(tr("适配宽度 W"), "ghost", FluentSymbol.FIT)
    fit_width.setToolTip(tr("显示整首歌曲并回到时间轴起点（W）"))
    fit_width.setAccessibleName(tr("适配整首歌曲宽度"))
    fit_width.clicked.connect(parent._fit_timeline)
    fit_tracks = PillButton(tr("适配轨道 H"), "ghost")
    fit_tracks.setToolTip(tr("让当前轨道尽量填满可用高度（H）"))
    fit_tracks.setAccessibleName(tr("适配全部轨道高度"))
    fit_tracks.clicked.connect(lambda: parent.timeline.fit_track_rows())
    reset_layout = PillButton(tr("恢复标准布局"), "ghost")
    reset_layout.setToolTip(tr(
        "恢复标准轨头宽度、轨道高度和参考音频高度"
    ))
    reset_layout.clicked.connect(lambda: parent.timeline.reset_layout_metrics())
    fold_groups = PillButton(tr("折叠所有组"), "ghost")
    fold_groups.clicked.connect(
        lambda: parent.timeline.set_all_groups_collapsed(True)
    )
    expand_groups = PillButton(tr("展开所有组"), "ghost")
    expand_groups.clicked.connect(
        lambda: parent.timeline.set_all_groups_collapsed(False)
    )
    return TimelineViewButtons(
        fit_width, fit_tracks, reset_layout, fold_groups, expand_groups
    )


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
    fit_tracks_button: QWidget,
    reset_layout_button: QWidget,
    fold_groups_button: QWidget,
    expand_groups_button: QWidget,
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
    layout.addWidget(fit_button, 2, 0)
    layout.addWidget(fit_tracks_button, 2, 1)
    layout.addWidget(reset_layout_button, 3, 0, 1, 2)
    layout.addWidget(fold_groups_button, 4, 0)
    layout.addWidget(expand_groups_button, 4, 1)
    view_action = QWidgetAction(view_menu)
    view_action.setDefaultWidget(view_panel)
    view_menu.addAction(view_action)
    view_menu.addSeparator()
    shortcut_action = view_menu.addAction(tr("时间轴快捷键…"))
    shortcut_action.setShortcut(QKeySequence("F1"))
    shortcut_action.triggered.connect(
        lambda: parent.timeline.show_shortcut_help()
    )
    view_button.setMenu(view_menu)
    return mix_button, view_button
