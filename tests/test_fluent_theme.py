from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

from bdo_music_composer.ui.theme import main_window_style
from bdo_music_composer.ui.theme.fluent_theme import (
    POPUP_MENU_BACKGROUND,
    POPUP_MENU_DISABLED_TEXT,
    POPUP_MENU_SELECTED_BACKGROUND,
    POPUP_MENU_SELECTED_TEXT,
    POPUP_MENU_TEXT,
    build_fluent_stylesheet,
    preferred_widget_style,
)


ROOT = Path(__file__).resolve().parents[1]


def _relative_luminance(color: str) -> float:
    channels = []
    for offset in (1, 3, 5):
        value = int(color[offset:offset + 2], 16) / 255.0
        channels.append(
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
        )
    return (
        channels[0] * 0.2126
        + channels[1] * 0.7152
        + channels[2] * 0.0722
    )


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


class FluentThemeTests(unittest.TestCase):
    def test_prefers_newest_available_windows_style(self) -> None:
        self.assertEqual(
            preferred_widget_style(["Fusion", "windowsvista", "windows11"]),
            "windows11",
        )
        self.assertEqual(preferred_widget_style(["Fusion", "Windows"]), "Windows")
        self.assertEqual(preferred_widget_style(["Custom"]), None)

    def test_component_styles_follow_light_and_dark_palettes(self) -> None:
        dark = build_fluent_stylesheet("QWidget { background: #151515; }", True)
        light = build_fluent_stylesheet("QWidget { background: #151515; }", False)

        self.assertIn("background: #151515", dark)
        self.assertIn("background: #f4f4f4", light)
        self.assertIn("QFrame#TransportGroup", dark)
        self.assertIn("border-radius: 7px", light)
        release_style_source = inspect.getsource(main_window_style)
        release_dark = build_fluent_stylesheet(release_style_source, True)
        release_light = build_fluent_stylesheet(release_style_source, False)
        self.assertIn("QComboBox#ReleaseVersionSelector", release_dark)
        for retired_release_widget in (
            "ReleaseVersionList",
            "RemoteReleaseNotes",
            "ReleaseNotesSplitter",
        ):
            self.assertNotIn(retired_release_widget, release_dark)
        for dark_release_token in (
            "#3d3932",
            "#aaa39a",
            "#f0c66f",
            "#bcd5b5",
            "#ddd7cf",
            "#d8d3cc",
        ):
            with self.subTest(token=dark_release_token):
                self.assertIn(dark_release_token, release_dark)
                self.assertNotIn(dark_release_token, release_light)

    def test_popup_semantic_colors_meet_readability_gate(self) -> None:
        self.assertGreaterEqual(
            _contrast(POPUP_MENU_TEXT, POPUP_MENU_BACKGROUND),
            7.0,
        )
        self.assertGreaterEqual(
            _contrast(POPUP_MENU_DISABLED_TEXT, POPUP_MENU_BACKGROUND),
            4.5,
        )
        self.assertGreaterEqual(
            _contrast(
                POPUP_MENU_SELECTED_TEXT,
                POPUP_MENU_SELECTED_BACKGROUND,
            ),
            7.0,
        )

    def test_windows_popup_render_keeps_every_action_state_readable(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtGui import QImage, QPalette
            from PySide6.QtWidgets import QApplication, QMenu
            from bdo_music_composer.ui.theme.fluent_theme import (
                configure_widget_style,
            )

            app = QApplication([])
            configure_widget_style(app)
            configure_widget_style(app)
            assert app.property("bdoFixedDarkPopupTheme") is True
            assert app.styleSheet().count("bdo-fixed-dark-popup-theme-v1") == 1

            palette = app.palette()
            active_text = palette.color(
                QPalette.ColorGroup.Active,
                QPalette.ColorRole.Text,
            )
            disabled_text = palette.color(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Text,
            )
            assert active_text != disabled_text
            assert active_text.lightness() > disabled_text.lightness() >= 100

            menu = QMenu()
            enabled = menu.addAction("Edit notes")
            disabled = menu.addAction("Change instrument")
            disabled.setEnabled(False)
            submenu = menu.addMenu("String instruments")
            submenu.addAction("Acoustic guitar")
            checked = menu.addAction("Current preview source")
            checked.setCheckable(True)
            checked.setChecked(True)
            menu.setActiveAction(enabled)
            menu.ensurePolished()
            menu.resize(menu.sizeHint())
            menu.show()
            app.processEvents()

            image = menu.grab().toImage().convertToFormat(
                QImage.Format.Format_RGB32
            )

            def bright_pixels(action, threshold):
                rect = menu.actionGeometry(action).intersected(image.rect())
                count = 0
                for y in range(rect.top(), rect.bottom() + 1):
                    for x in range(rect.left(), rect.right() + 1):
                        color = image.pixelColor(x, y)
                        luminance = (
                            color.red() * 0.2126
                            + color.green() * 0.7152
                            + color.blue() * 0.0722
                        )
                        if luminance >= threshold:
                            count += 1
                return count

            assert bright_pixels(enabled, 180) >= 8
            assert bright_pixels(disabled, 100) >= 8
            assert bright_pixels(submenu.menuAction(), 180) >= 8
            assert bright_pixels(checked, 180) >= 8
            menu.close()
            """
        )
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_production_menus_cannot_install_local_stylesheets(self) -> None:
        violations: list[str] = []
        for path in ROOT.rglob("*.py"):
            relative = path.relative_to(ROOT)
            excluded_directories = {
                ".git",
                ".idea",
                ".venv",
                "__pycache__",
                "auto_save",
                "build",
                "dist",
                "out",
                "sample_cache",
                "tests",
            }
            if (
                any(part in excluded_directories for part in relative.parts)
                or relative
                == Path("bdo_music_composer/ui/theme/fluent_theme.py")
            ):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if not (
                    isinstance(function, ast.Attribute)
                    and function.attr == "setStyleSheet"
                ):
                    continue
                owner = ast.unparse(function.value).casefold()
                if "menu" in owner:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(
            violations,
            [],
            "QMenu styling must remain global in "
            "bdo_music_composer/ui/theme/fluent_theme.py",
        )


if __name__ == "__main__":
    unittest.main()
