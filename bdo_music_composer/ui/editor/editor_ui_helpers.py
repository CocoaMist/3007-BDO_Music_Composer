"""Shared Qt presentation policies for packaged editor widgets."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu

from bdo_music_composer.ui.i18n import tr


TRACK_COLORS = (
    "#d88c6f", "#8dbf67", "#6f9fd8", "#d8b66f", "#b887d8", "#70b8a8",
    "#d87592", "#91a7d8", "#c6d86f", "#d89f6f", "#8ed8ce", "#b9a0d8",
)


BDO_DYNAMIC_ARTICULATION_COLORS = {
    0: "#4f9d69", 1: "#8e7cc3", 2: "#c27c4a", 3: "#2f9ea8",
    4: "#756bb1", 5: "#d27a9c", 6: "#4c78a8", 7: "#f28e2b",
    8: "#59a14f", 9: "#b6992d", 10: "#9c6ade", 11: "#e36f47",
    12: "#248f8d", 13: "#7b6a58", 14: "#76b7b2", 15: "#edc948",
    16: "#af7aa1", 17: "#ff9da7", 18: "#86bcb6", 19: "#d4a6c8",
    20: "#499894", 21: "#e15759", 22: "#bc7c2f", 23: "#3a86c8",
    24: "#6b7280", 25: "#cf4b83", 26: "#5b90c9", 27: "#d9ae59",
    28: "#d96658",
}

BDO_INSTRUMENT_MENU_GROUPS = (
    ("管乐器", (0x01, 0x02, 0x0B, 0x27, 0x28)),
    ("弦乐器", (0x00, 0x06, 0x08, 0x0A, 0x0E, 0x0F, 0x10, 0x12, 0x24, 0x25, 0x26)),
    ("键盘乐器", (0x07, 0x11, 0x14, 0x18, 0x1C, 0x20)),
    ("打击乐器", (0x04, 0x05, 0x0D, 0x13)),
)


def articulation_color(ntype: int | None) -> str:
    """Return a stable color for known and future game articulation types."""

    value = int(ntype or 0)
    known = BDO_DYNAMIC_ARTICULATION_COLORS.get(value)
    if known:
        return known
    hue = (value * 137 + 29) % 360
    return QColor.fromHsv(hue, 165, 205).name()


def add_instrument_submenus(
    menu: QMenu,
    current_id: int,
    instrument_names: dict[int, str],
) -> None:
    used_ids: set[int] = set()
    for type_name, instrument_ids in BDO_INSTRUMENT_MENU_GROUPS:
        type_menu = menu.addMenu(tr(type_name))
        for instrument_id in instrument_ids:
            name = instrument_names.get(instrument_id)
            if not name:
                continue
            used_ids.add(instrument_id)
            action = type_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(instrument_id == current_id)
            action.setData(instrument_id)
    remaining = [value for value in instrument_names if value not in used_ids]
    if remaining:
        other_menu = menu.addMenu(tr("其他"))
        for instrument_id in remaining:
            action = other_menu.addAction(instrument_names[instrument_id])
            action.setCheckable(True)
            action.setChecked(instrument_id == current_id)
            action.setData(instrument_id)
