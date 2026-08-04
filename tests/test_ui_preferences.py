from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from bdo_music_composer.app.ui_preferences import (
    DEFAULT_UI_PREFERENCES,
    normalize_ui_preferences,
    store_ui_preferences,
)


ROOT = Path(__file__).resolve().parents[1]


class UiPreferenceModelTests(unittest.TestCase):
    def test_normalization_bounds_and_preserves_supported_choices(self) -> None:
        result = normalize_ui_preferences({
            "workspace": {
                "timeline_zoom_percent": 9_999,
                "timeline_pan_percent": 450,
                "reference_volume_percent": -5,
                "timeline_loop_enabled": True,
            },
            "editor": {
                "horizontal_zoom": 333,
                "note_row_height": 31.5,
                "quantize_divisor": 4,
                "velocity_mode": "point",
                "velocity_scope": "selection",
            },
            "transcription": {
                "confidence_percent": 66,
                "rhythm_profile": "strict_1_64",
            },
        })
        self.assertEqual(result["workspace"]["timeline_zoom_percent"], 800)
        self.assertEqual(result["workspace"]["timeline_pan_percent"], 450)
        self.assertEqual(result["workspace"]["reference_volume_percent"], 0)
        self.assertTrue(result["workspace"]["timeline_loop_enabled"])
        self.assertEqual(result["editor"]["horizontal_zoom"], 333)
        self.assertEqual(result["editor"]["note_row_height"], 31.5)
        self.assertEqual(result["editor"]["quantize_divisor"], 4)
        self.assertEqual(result["editor"]["velocity_mode"], "point")
        self.assertEqual(result["editor"]["velocity_scope"], "selection")
        self.assertEqual(result["transcription"]["confidence_percent"], 66)
        self.assertEqual(result["transcription"]["rhythm_profile"], "strict_1_64")

    def test_store_keeps_unrelated_application_configuration(self) -> None:
        config = {"language": "ja_JP", "future": {"kept": True}}
        stored = store_ui_preferences(config, DEFAULT_UI_PREFERENCES)
        self.assertIs(config["ui_preferences"], stored)
        self.assertEqual(config["language"], "ja_JP")
        self.assertEqual(config["future"], {"kept": True})


class UiPreferenceQtRoundTripTests(unittest.TestCase):
    def test_workspace_and_editor_controls_survive_reopen(self) -> None:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["BDO_TEST_UI_PREFERENCES"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent(
                    r"""
                    from pathlib import Path
                    import tempfile
                    from unittest.mock import patch

                    from PySide6.QtWidgets import QApplication
                    from bdo_midi import Note
                    import bdo_music_composer.ui.main_window as gui

                    root = Path(tempfile.mkdtemp())
                    config_path = root / "settings.json"
                    app = QApplication([])
                    with patch.object(gui, "CONFIG_PATH", config_path):
                        window = gui.MidiToBdoWindow()
                        window.timeline_zoom.setValue(275)
                        window.timeline_pan.setValue(420)
                        window.timeline_loop_box.setChecked(True)
                        window.reference_audio.set_volume_percent(37)
                        track = gui.TrackState(
                            1, [Note(60, 90, 0.0, 500.0, 0)],
                            0, False, "track", 0x0B,
                        )
                        window.tracks = [track]
                        editor = gui.MidiNoteEditorDialog(window, track, 120, 4)
                        editor.editor_zoom.setValue(333)
                        editor.canvas.ROW_H = 31.5
                        editor.quantize_combo.setCurrentIndex(
                            editor.quantize_combo.findData(4)
                        )
                        editor.snap_box.setChecked(False)
                        editor.note_preview_box.setChecked(False)
                        editor.draw_mode_button.setChecked(True)
                        editor._set_top_inspector_mode("grid")
                        editor.loop_box.setChecked(True)
                        editor.velocity_toggle.setChecked(True)
                        editor._set_velocity_mode("point")
                        editor.velocity_radius_combo.setCurrentIndex(
                            editor.velocity_radius_combo.findData(4.0)
                        )
                        editor.velocity_scope_combo.setCurrentIndex(
                            editor.velocity_scope_combo.findData("selection")
                        )
                        panel = editor.transcription_panel
                        panel.set_confidence_floor(0.66)
                        panel.show_rejected_checkbox.setChecked(True)
                        panel.show_suppressed_checkbox.setChecked(True)
                        panel.rhythm_projection_checkbox.setChecked(False)
                        panel.rhythm_profile_combo.setCurrentIndex(
                            panel.rhythm_profile_combo.findData("strict_1_64")
                        )
                        editor.ui_preference_binding.flush()
                        window.ui_preference_binding.flush()
                        editor.close(); window.close(); app.processEvents()

                        restored = gui.MidiToBdoWindow()
                        assert restored.timeline_zoom.value() == 275
                        assert restored.timeline_pan.value() == 420
                        assert restored.timeline_loop_box.isChecked()
                        assert restored.reference_audio.volume_percent == 37
                        restored.tracks = [track]
                        reopened = gui.MidiNoteEditorDialog(
                            restored, track, 120, 4
                        )
                        assert reopened.editor_zoom.value() == 333
                        assert abs(reopened.canvas.ROW_H - 31.5) < 0.01
                        assert reopened.quantize_combo.currentData() == 4
                        assert not reopened.snap_box.isChecked()
                        assert not reopened.note_preview_box.isChecked()
                        assert reopened.draw_mode_button.isChecked()
                        assert reopened.grid_mode_button.isChecked()
                        assert reopened.loop_box.isChecked()
                        assert reopened.velocity_toggle.isChecked()
                        assert reopened.velocity_lane.edit_mode == "point"
                        assert reopened.velocity_lane.influence_beats == 4.0
                        assert reopened.velocity_lane.scope_mode == "selection"
                        panel = reopened.transcription_panel
                        assert panel.confidence_floor == 0.66
                        assert panel.show_rejected_checkbox.isChecked()
                        assert panel.show_suppressed_checkbox.isChecked()
                        assert not panel.rhythm_projection_checkbox.isChecked()
                        assert panel.rhythm_alignment_profile == "strict_1_64"
                        reopened.close(); restored.close()
                        app.processEvents(); app.quit()
                    """
                ),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
