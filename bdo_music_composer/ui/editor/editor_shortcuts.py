"""Single source of truth for piano-roll shortcuts and gesture help."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt


SELECT_CONTEXT = "select"
SELECTION_CONTEXT = "selection"
DRAW_CONTEXT = "draw"
GLOBAL_SCOPE = "global"
CANVAS_SCOPE = "canvas"

_EDITOR_MODIFIERS = (
    Qt.ControlModifier
    | Qt.AltModifier
    | Qt.ShiftModifier
    | Qt.MetaModifier
)


@dataclass(frozen=True, slots=True)
class EditorShortcutSpec:
    """One keyboard command with stable help and dispatch metadata."""

    command: str
    keys: tuple[Qt.Key, ...]
    modifiers: Qt.KeyboardModifier
    key_source: str
    action_source: str
    group_source: str
    scope: str = CANVAS_SCOPE
    requires_selection: bool = False

    def matches(self, key: int, modifiers: Qt.KeyboardModifier) -> bool:
        return key in self.keys and (modifiers & _EDITOR_MODIFIERS) == self.modifiers


@dataclass(frozen=True, slots=True)
class EditorGestureSpec:
    """One mouse/wheel gesture shown by the complete help panel."""

    key_source: str
    action_source: str
    group_source: str


EDITOR_SHORTCUT_SPECS = (
    EditorShortcutSpec(
        "show_shortcuts",
        (Qt.Key_F1,),
        Qt.NoModifier,
        "F1",
        "打开完整快捷键",
        "基础操作",
        GLOBAL_SCOPE,
    ),
    EditorShortcutSpec(
        "play_pause",
        (Qt.Key_Space,),
        Qt.NoModifier,
        "Space",
        "播放或暂停",
        "基础操作",
    ),
    EditorShortcutSpec(
        "select_all",
        (Qt.Key_A,),
        Qt.ControlModifier,
        "Ctrl+A",
        "选择全部音符",
        "基础操作",
    ),
    EditorShortcutSpec(
        "toggle_draw",
        (Qt.Key_B,),
        Qt.NoModifier,
        "B",
        "切换绘制模式",
        "画布模式与选择",
    ),
    EditorShortcutSpec(
        "exit_draw",
        (Qt.Key_Escape,),
        Qt.NoModifier,
        "Esc",
        "退出绘制或清除候选选择",
        "画布模式与选择",
    ),
    EditorShortcutSpec(
        "nudge_time",
        (Qt.Key_Left, Qt.Key_Right),
        Qt.NoModifier,
        "← / →",
        "按网格移动时间",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "nudge_time_fine",
        (Qt.Key_Left, Qt.Key_Right),
        Qt.AltModifier,
        "Alt+← / →",
        "精细移动时间（网格的 1/8）",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "resize_duration",
        (Qt.Key_Left, Qt.Key_Right),
        Qt.ShiftModifier,
        "Shift+← / →",
        "调整音符时值",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "resize_duration_fine",
        (Qt.Key_Left, Qt.Key_Right),
        Qt.ShiftModifier | Qt.AltModifier,
        "Alt+Shift+← / →",
        "精细调整音符时值",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "nudge_pitch",
        (Qt.Key_Up, Qt.Key_Down),
        Qt.NoModifier,
        "↑ / ↓",
        "移动一个半音",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "transpose_octave",
        (Qt.Key_Up, Qt.Key_Down),
        Qt.ShiftModifier,
        "Shift+↑ / ↓",
        "移动一个八度",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "adjust_velocity",
        (Qt.Key_Up, Qt.Key_Down),
        Qt.ControlModifier,
        "Ctrl+↑ / ↓",
        "力度增减 1",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "adjust_velocity_coarse",
        (Qt.Key_Up, Qt.Key_Down),
        Qt.ControlModifier | Qt.ShiftModifier,
        "Ctrl+Shift+↑ / ↓",
        "力度增减 8",
        "音块移动与缩放",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "duplicate",
        (Qt.Key_D,),
        Qt.ControlModifier,
        "Ctrl+D",
        "向后复制所选音符",
        "剪贴板与历史",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "copy",
        (Qt.Key_C,),
        Qt.ControlModifier,
        "Ctrl+C",
        "复制所选音符",
        "剪贴板与历史",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "cut",
        (Qt.Key_X,),
        Qt.ControlModifier,
        "Ctrl+X",
        "剪切所选音符",
        "剪贴板与历史",
        requires_selection=True,
    ),
    EditorShortcutSpec(
        "paste",
        (Qt.Key_V,),
        Qt.ControlModifier,
        "Ctrl+V",
        "在编辑光标处粘贴；同音高重叠时移至最近空位",
        "剪贴板与历史",
    ),
    EditorShortcutSpec(
        "undo",
        (Qt.Key_Z,),
        Qt.ControlModifier,
        "Ctrl+Z",
        "撤销音符编辑",
        "剪贴板与历史",
    ),
    EditorShortcutSpec(
        "redo",
        (Qt.Key_Y,),
        Qt.ControlModifier,
        "Ctrl+Y",
        "重做音符编辑",
        "剪贴板与历史",
    ),
    EditorShortcutSpec(
        "redo",
        (Qt.Key_Z,),
        Qt.ControlModifier | Qt.ShiftModifier,
        "Ctrl+Shift+Z",
        "重做音符编辑",
        "剪贴板与历史",
    ),
    EditorShortcutSpec(
        "delete",
        (Qt.Key_Delete, Qt.Key_Backspace),
        Qt.NoModifier,
        "Del / Backspace",
        "删除所选音符（可撤销）",
        "剪贴板与历史",
        requires_selection=True,
    ),
)


EDITOR_GESTURE_SPECS = (
    EditorGestureSpec("双击空白", "新建音符", "画布模式与选择"),
    EditorGestureSpec("拖动空白", "框选音符", "画布模式与选择"),
    EditorGestureSpec("Ctrl+点击 / 框选", "切换或追加选择", "画布模式与选择"),
    EditorGestureSpec("Shift+点击", "连续选择音符", "画布模式与选择"),
    EditorGestureSpec("拖动音块", "移动音符", "鼠标与视图"),
    EditorGestureSpec("拖动音块边缘", "调整音符时值", "鼠标与视图"),
    EditorGestureSpec("Ctrl+拖动音块", "复制并移动音符", "鼠标与视图"),
    EditorGestureSpec("Alt+拖动", "临时取消吸附", "鼠标与视图"),
    EditorGestureSpec("右键音块", "立即删除音符（可撤销）", "鼠标与视图"),
    EditorGestureSpec("滚轮", "纵向浏览音高", "鼠标与视图"),
    EditorGestureSpec("Shift+滚轮", "横向滚动时间", "鼠标与视图"),
    EditorGestureSpec("Ctrl+滚轮", "缩放时间", "鼠标与视图"),
    EditorGestureSpec("Alt+滚轮", "调整音块高度", "鼠标与视图"),
    EditorGestureSpec("触控板双指滑动", "平移时间与音高", "鼠标与视图"),
)


HUD_CONTEXT_COPY = {
    SELECT_CONTEXT: (
        "选择模式",
        (
            ("双击", "新建音符"),
            ("B", "切换绘制模式"),
            ("Ctrl+拖动", "复制音符"),
            ("Space", "播放或暂停"),
        ),
    ),
    SELECTION_CONTEXT: (
        "已选音符",
        (
            ("←/→ · ↑/↓", "时间 · 音高"),
            ("Shift+方向键", "时值 · 八度"),
            ("Ctrl+↑/↓ · Ctrl+D", "力度 · 复制"),
            ("Del / 右键", "删除（可撤销）"),
        ),
    ),
    DRAW_CONTEXT: (
        "绘制模式",
        (
            ("拖动", "设置长度和力度"),
            ("Alt", "临时取消吸附"),
            ("B / Esc", "退出绘制模式"),
            ("F1", "打开完整快捷键"),
        ),
    ),
}

HELP_GROUP_SOURCES = (
    "基础操作",
    "画布模式与选择",
    "音块移动与缩放",
    "剪贴板与历史",
    "鼠标与视图",
)


def resolve_editor_key_command(
    key: int,
    modifiers: Qt.KeyboardModifier,
    *,
    has_selection: bool,
) -> str | None:
    """Resolve one key event without duplicating modifier rules in the canvas."""

    for spec in EDITOR_SHORTCUT_SPECS:
        if spec.scope != CANVAS_SCOPE or not spec.matches(key, modifiers):
            continue
        if spec.requires_selection and not has_selection:
            return None
        return spec.command
    return None


def editor_shortcut_spec(command: str) -> EditorShortcutSpec:
    """Return the unique primary shortcut spec for a named command."""

    for spec in EDITOR_SHORTCUT_SPECS:
        if spec.command == command:
            return spec
    raise KeyError(command)
