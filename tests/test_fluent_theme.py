from __future__ import annotations

import unittest

from fluent_theme import build_fluent_stylesheet, preferred_widget_style


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


if __name__ == "__main__":
    unittest.main()
