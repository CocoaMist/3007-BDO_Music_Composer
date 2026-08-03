from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConversionDefaultsUiTests(unittest.TestCase):
    def _run_offscreen(self, source: str) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "user-data")
            completed = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(source)],
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

    def test_new_scores_use_game_native_pitch_and_velocity_defaults(self) -> None:
        self._run_offscreen(
            """
            import json
            from pathlib import Path
            import tempfile

            import mido
            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as gui

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            assert window.bpm_override is None
            assert window.transpose == gui.DEFAULT_CONVERSION_TRANSPOSE == 0
            assert window.velocity_mode == "preserve"

            dialog = gui.SettingsDialog(window)
            assert dialog.bpm_override.value() == 0
            assert dialog.bpm_override.specialValueText() == "使用 MIDI"
            assert dialog.transpose.value() == 0
            assert dialog.selected_velocity_mode() == "preserve"
            dialog.close()

            # A new blank score must not inherit temporary settings from the
            # project that happened to be open immediately before it.
            window.bpm_override = 144
            window.transpose = 7
            window._create_new_project("Default Conversion")
            assert window.bpm_override is None
            assert window.transpose == 0
            assert window.velocity_mode == "preserve"
            assert window._wait_for_autosave_idle()
            project_path = next(
                gui.AUTO_SAVE_DIR.glob("Default Conversion_*/project.json")
            )
            payload = json.loads(project_path.read_text(encoding="utf-8"))
            assert payload["conversion_settings"]["bpm_override"] is None
            assert payload["conversion_settings"]["transpose"] == 0
            assert payload["conversion_settings"]["velocity_mode"] == "preserve"

            # Raw MIDI import is another new-score boundary and uses the same
            # defaults even after a neutral imported-score state.
            with tempfile.TemporaryDirectory() as midi_folder:
                midi_path = Path(midi_folder) / "source.mid"
                midi = mido.MidiFile(ticks_per_beat=480)
                track = mido.MidiTrack()
                midi.tracks.append(track)
                track.append(
                    mido.Message("note_on", note=60, velocity=90, time=0)
                )
                track.append(
                    mido.Message("note_off", note=60, velocity=0, time=480)
                )
                midi.save(midi_path)
                window.bpm_override = None
                window.transpose = 0
                window.velocity_mode = "off"
                window._open_midi_path(midi_path)
                assert window.bpm_override is None
                assert window.transpose == 0
                assert window.velocity_mode == "preserve"
                assert window._wait_for_autosave_idle()

            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_saved_preferences_win_and_legacy_projects_remain_neutral(self) -> None:
        self._run_offscreen(
            """
            import json

            from PySide6.QtWidgets import QApplication

            import bdo_music_composer.ui.main_window as gui

            gui.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            gui.CONFIG_PATH.write_text(
                json.dumps(
                    {
                        "conversion_settings": {
                            "bpm_override": 150,
                            "transpose": -12,
                            "velocity_mode": "floor",
                            "vel_floor": 44,
                        }
                    }
                ),
                encoding="utf-8",
            )

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            assert window.bpm_override == 150
            assert window.transpose == -12
            assert window.velocity_mode == "floor"
            assert window.vel_floor == 44

            window.bpm_override = None
            window.transpose = 0
            window._reset_new_score_conversion_defaults()
            assert window.bpm_override == 150
            assert window.transpose == -12
            # The saved velocity recipe belongs to MIDI import, not to an
            # empty authored score as a deferred export transform.
            assert window.velocity_mode == "preserve"
            assert window.vel_floor == 44

            # An incomplete legacy project is authoritative and must not
            # inherit unrelated application conversion preferences.
            window._apply_conversion_settings({"char_name": "legacy"})
            assert window.bpm_override is None
            assert window.transpose == 0
            assert window.velocity_mode == "preserve"

            snapshot = window._project_snapshot()
            window.transpose = 9
            window.velocity_mode = "off"
            window._restore_project_snapshot(snapshot, "project undo")
            assert window.transpose == 0
            assert window.velocity_mode == "preserve"

            window.close()
            app.processEvents()
            app.quit()
            """
        )


if __name__ == "__main__":
    unittest.main()
