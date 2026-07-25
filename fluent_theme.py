"""Native-first Fluent styling helpers for the Qt Widgets interface.

The application keeps its music workspaces custom-painted, while ordinary
controls use the newest native Windows style available.  The QSS layer is
therefore limited to BDO branding and the shared component hierarchy.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QApplication, QStyleFactory, QWidget


WINDOWS_STYLE_PRIORITY = ("windows11", "windowsvista", "windows", "fusion")


def preferred_widget_style(available_styles: list[str]) -> str | None:
    available = {key.casefold(): key for key in available_styles}
    for candidate in WINDOWS_STYLE_PRIORITY:
        if candidate in available:
            return available[candidate]
    return None


def configure_widget_style(app: QApplication) -> str:
    """Select the best installed Windows-like style and return its key."""

    selected = preferred_widget_style(QStyleFactory.keys())
    if selected is not None:
        app.setStyle(selected)
    else:
        selected = app.style().objectName()
    apply_fixed_dark_palette(app)
    return selected


def apply_fixed_dark_palette(app: QApplication) -> None:
    """Keep the workstation dark regardless of the operating-system theme."""

    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#151515",
        QPalette.ColorRole.WindowText: "#f3f1ea",
        QPalette.ColorRole.Base: "#1e1e1e",
        QPalette.ColorRole.AlternateBase: "#262626",
        QPalette.ColorRole.ToolTipBase: "#262626",
        QPalette.ColorRole.ToolTipText: "#f3f1ea",
        QPalette.ColorRole.Text: "#f3f1ea",
        QPalette.ColorRole.Button: "#2b2b2b",
        QPalette.ColorRole.ButtonText: "#f3f1ea",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: "#b97b20",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#f0c66f",
        QPalette.ColorRole.PlaceholderText: "#8d8780",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setProperty("bdoFixedDarkTheme", True)


def system_uses_dark_theme(app: QApplication | None = None) -> bool:
    app = app or QApplication.instance()
    if app is None:
        return False
    if app.property("bdoFixedDarkTheme"):
        return True
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


class FluentSymbol(str, Enum):
    HOME = "home"
    OPEN = "open"
    PROJECT = "project"
    OPTIMIZE = "optimize"
    INFO = "info"
    SETTINGS = "settings"
    EXPORT = "export"
    FIT = "fit"
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    ADD_TRACK = "add_track"
    DELETE = "delete"
    CURVE = "curve"


def _draw_fluent_symbol(symbol: FluentSymbol, color: str, size: int = 16) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size / 16.0
    pen = QPen(QColor(color), 1.5 * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        painter.drawLine(round(x1 * scale), round(y1 * scale), round(x2 * scale), round(y2 * scale))

    def rect(x: float, y: float, width: float, height: float) -> None:
        painter.drawRoundedRect(
            round(x * scale), round(y * scale), round(width * scale), round(height * scale),
            1.2 * scale, 1.2 * scale,
        )

    if symbol == FluentSymbol.HOME:
        painter.drawPolyline([
            _point(2.5, 7.5, scale), _point(8, 2.8, scale), _point(13.5, 7.5, scale),
        ])
        painter.drawPolyline([
            _point(4, 6.5, scale), _point(4, 13, scale), _point(12, 13, scale),
            _point(12, 6.5, scale),
        ])
        line(7, 13, 7, 9.5)
        line(7, 9.5, 9.5, 9.5)
        line(9.5, 9.5, 9.5, 13)
    elif symbol in {FluentSymbol.OPEN, FluentSymbol.PROJECT}:
        painter.drawPolyline([
            _point(2, 5, scale), _point(6, 5, scale), _point(7.5, 3.5, scale),
            _point(13.5, 3.5, scale), _point(13.5, 12.5, scale), _point(2, 12.5, scale),
            _point(2, 5, scale),
        ])
        if symbol == FluentSymbol.OPEN:
            line(8, 7, 8, 11)
            line(6, 9, 10, 9)
    elif symbol == FluentSymbol.OPTIMIZE:
        painter.drawArc(round(2 * scale), round(2 * scale), round(12 * scale), round(12 * scale), 35 * 16, 255 * 16)
        line(11.5, 2.5, 14, 3)
        line(14, 3, 13.2, 5.4)
    elif symbol == FluentSymbol.INFO:
        painter.drawEllipse(round(2.5 * scale), round(2.5 * scale), round(11 * scale), round(11 * scale))
        line(8, 7, 8, 11)
        painter.setBrush(QColor(color))
        painter.drawEllipse(round(7.3 * scale), round(4.5 * scale), round(1.4 * scale), round(1.4 * scale))
    elif symbol == FluentSymbol.SETTINGS:
        for y, knob in ((4, 6), (8, 10), (12, 5)):
            line(2.5, y, 13.5, y)
            painter.setBrush(QColor(color))
            painter.drawEllipse(round((knob - 1) * scale), round((y - 1) * scale), round(2 * scale), round(2 * scale))
            painter.setBrush(Qt.BrushStyle.NoBrush)
    elif symbol == FluentSymbol.EXPORT:
        rect(3, 2.5, 10, 11)
        line(8, 4.5, 8, 10)
        line(5.8, 7.8, 8, 10)
        line(10.2, 7.8, 8, 10)
    elif symbol == FluentSymbol.FIT:
        line(2.5, 6, 2.5, 2.5)
        line(2.5, 2.5, 6, 2.5)
        line(10, 2.5, 13.5, 2.5)
        line(13.5, 2.5, 13.5, 6)
        line(2.5, 10, 2.5, 13.5)
        line(2.5, 13.5, 6, 13.5)
        line(10, 13.5, 13.5, 13.5)
        line(13.5, 13.5, 13.5, 10)
    elif symbol == FluentSymbol.PLAY:
        painter.setBrush(QColor(color))
        painter.drawPolygon([_point(5, 3.5, scale), _point(12.5, 8, scale), _point(5, 12.5, scale)])
    elif symbol == FluentSymbol.PAUSE:
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(round(4 * scale), round(3.5 * scale), round(2.5 * scale), round(9 * scale), scale, scale)
        painter.drawRoundedRect(round(9.5 * scale), round(3.5 * scale), round(2.5 * scale), round(9 * scale), scale, scale)
    elif symbol == FluentSymbol.STOP:
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(round(4 * scale), round(4 * scale), round(8 * scale), round(8 * scale), scale, scale)
    elif symbol == FluentSymbol.ADD_TRACK:
        line(2.5, 4.5, 9, 4.5); line(2.5, 8, 8, 8); line(2.5, 11.5, 7, 11.5)
        line(11.5, 8, 11.5, 13); line(9, 10.5, 14, 10.5)
    elif symbol == FluentSymbol.DELETE:
        rect(4, 4.5, 8, 9)
        line(3, 4.5, 13, 4.5); line(6, 2.5, 10, 2.5)
        line(6.5, 7, 6.5, 11); line(9.5, 7, 9.5, 11)
    elif symbol == FluentSymbol.CURVE:
        painter.drawPolyline([
            _point(2.0, 11.5, scale),
            _point(5.0, 8.5, scale),
            _point(8.0, 9.5, scale),
            _point(11.0, 4.5, scale),
            _point(14.0, 6.0, scale),
        ])
        painter.setBrush(QColor(color))
        for x, y in ((2.0, 11.5), (5.0, 8.5), (8.0, 9.5), (11.0, 4.5), (14.0, 6.0)):
            painter.drawEllipse(
                round((x - 0.9) * scale),
                round((y - 0.9) * scale),
                round(1.8 * scale),
                round(1.8 * scale),
            )

    painter.end()
    return pixmap


def _point(x: float, y: float, scale: float):
    return QPoint(round(x * scale), round(y * scale))


def set_fluent_symbol(button: QAbstractButton, symbol: FluentSymbol) -> None:
    button.setProperty("fluentSymbol", symbol.value)
    button.setIconSize(fluent_icon_size())
    color = "#d8d3cc" if system_uses_dark_theme() else "#4b4742"
    if button.property("kind") == "convert":
        color = "#1b1305"
    button.setIcon(QIcon(_draw_fluent_symbol(symbol, color)))


def refresh_fluent_icons(root: QWidget, dark: bool) -> None:
    for button in root.findChildren(QAbstractButton):
        value = button.property("fluentSymbol")
        if not value:
            continue
        color = "#d8d3cc" if dark else "#4b4742"
        if button.property("kind") == "convert":
            color = "#1b1305"
        button.setIcon(QIcon(_draw_fluent_symbol(FluentSymbol(value), color)))


def fluent_icon_size() -> QSize:
    return QSize(16, 16)


# The legacy stylesheet used dark colors as its source language.  Keeping the
# light mapping here makes theme policy independent from the main window and is
# an intermediate step toward fully semantic color tokens.
LIGHT_COLOR_REPLACEMENTS = {
    "#151515": "#f4f4f4", "#181818": "#f7f7f7", "#202020": "#ffffff",
    "#1f1f1f": "#fafafa", "#1d1d1d": "#f0f0f0", "#222222": "#ffffff",
    "#201f1c": "#fffaf0", "#1b201b": "#f4f8f3", "#20251f": "#edf4eb",
    "#2b362a": "#e2eddf", "#151915": "#ffffff", "#111511": "#f4f8f3",
    "#262626": "#ffffff", "#1a1a1a": "#eeeeee", "#1e1e1e": "#ffffff",
    "#2b2b2b": "#f6f6f6", "#343434": "#e7e7e7", "#302a20": "#fff4df",
    "#232323": "#e5e5e5", "#1b1b1b": "#ededed", "#3a3a3a": "#c9c9c9",
    "#333130": "#d7d3ce", "#3b3935": "#d2cec8", "#393735": "#d5d1cb",
    "#353332": "#d9d5cf", "#3d3932": "#d3c9b8", "#3b4939": "#c4d2c1",
    "#40503e": "#b8cab4", "#536a50": "#9ab294", "#313d30": "#c8d4c5",
    "#313131": "#d4d4d4", "#3f3a33": "#d4c8b8", "#363636": "#d0d0d0",
    "#404040": "#c8c8c8", "#55504a": "#aaa39b", "#4a4640": "#aaa49c",
    "#56504a": "#9f9890", "#6a6259": "#8f877e", "#55514b": "#aaa49d",
    "#46423d": "#c8c3bd", "#3a3834": "#ccc8c2", "#383531": "#d0cbc4",
    "#2c2b29": "#dedbd7", "#34322f": "#d1cdc7", "#191919": "#ffffff",
    "#4a391f": "#ffe3ae", "#f3f1ea": "#202020", "#ddd7cf": "#2b2b2b",
    "#c7c0b8": "#4b4742", "#bdb6ad": "#55504a", "#aaa39a": "#66605a",
    "#e5dfd6": "#292724", "#d6d1c9": "#3f3b36", "#a8a29e": "#68625d",
    "#d9ead3": "#31552d", "#d8d3cc": "#45413d", "#bcd5b5": "#3f6639",
    "#a8b5a4": "#5d6e59", "#c9c2ba": "#514c47", "#6f6a65": "#92908d",
    "#f0c66f": "#8a5a00", "#d6b675": "#74500d", "#8f6b2e": "#d89a28",
    "#5d451e": "#ffe0a3", "#e4c17c": "#80550c", "#d9d3ca": "#3e3a35",
    "#fff3d6": "#3b2a12", "#8d8780": "#8a867f",
}


FLUENT_COMPONENT_QSS = """
    QFrame#CommandGroup, QFrame#TransportGroup {
        background: #1a1a1a;
        border: 1px solid #353332;
        border-radius: 7px;
    }
    QFrame#InfoBar {
        background: #201f1c;
        border: 1px solid #3d3932;
        border-left: 3px solid #f5a524;
        border-radius: 6px;
    }
    QPushButton {
        min-height: 26px;
        border-radius: 5px;
    }
    QPushButton[kind="primary"] { font-weight: 700; }
    QPushButton[kind="secondary"] { background: transparent; }
    QPushButton[kind="secondary"]:hover { background: #343434; }
    QPushButton[kind="convert"] { border-radius: 6px; }
    QLineEdit, QComboBox, QTextEdit, QListWidget { border-radius: 5px; }
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
        border-bottom: 2px solid #f5a524;
    }
    QFrame#SettingsSection, QFrame#OptimizerOptions,
    QFrame#EditorToolbar, QFrame#EditorFooter, QFrame#NoteInspectorTop {
        border-radius: 9px;
    }
"""


def build_fluent_stylesheet(base_stylesheet: str, dark: bool) -> str:
    stylesheet = base_stylesheet + FLUENT_COMPONENT_QSS
    if dark:
        return stylesheet
    for dark_color, light_color in LIGHT_COLOR_REPLACEMENTS.items():
        stylesheet = stylesheet.replace(dark_color, light_color)
    return stylesheet
