from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrackGroupUiTests(unittest.TestCase):
    def test_group_control_is_explicit_and_group_actions_are_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.ui.main_window import MidiToBdoWindow
                app = QApplication([]); window = MidiToBdoWindow()
                window.tracks = [
                    TrackState(i, [Note(60+i, 90, i*100, 80, 0)], 0, False, f"T{i}", 0x12)
                    for i in range(1, 4)
                ]
                window._refresh_tracks(); window._show_workspace()
                window.resize(1100, 720); window.show(); app.processEvents()
                window.timeline.repaint(); app.processEvents()
                actions = [action for _rect, action, _item in window.timeline.hit_regions]
                assert actions.count("group_select") == 1, actions
                assert actions.count("group_mute") == 1, actions
                assert actions.count("group_solo") == 1, actions
                assert len(window.timeline._arrangement_groups) == 1
                group_id = window.tracks[0].arrangement_group_id
                window._apply_arrangement_group_control(group_id, "mute")
                assert all(track.muted for track in window.tracks)
                assert len(window.project_commands._undo) == 1
                window._undo_project()
                assert not any(track.muted for track in window.tracks)
                window.autosave_timer.stop(); window.close(); app.processEvents()
                print("group-control-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=90, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("group-control-ok", result.stdout)

    def test_structure_refresh_auto_groups_and_instrument_change_reclassifies(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(Path(folder_name) / "data")
            script = textwrap.dedent(
                """
                from PySide6.QtWidgets import QApplication
                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                def track(track_id, instrument):
                    return TrackState(
                        track_id, [Note(60, 90, track_id * 100.0, 80.0, 0)],
                        0, False, f"Track {track_id}", instrument,
                    )

                app = QApplication([])
                window = MidiToBdoWindow()
                left, middle, right = track(1, 0x12), track(2, 0x11), track(3, 0x12)
                window.tracks = [left, middle, right]
                left.arrangement_group_id = "stale-singleton"
                middle.arrangement_group_id = "stale-other"
                window._refresh_tracks()
                assert [value.track_id for value in window.tracks] == [1, 3, 2]
                assert left.arrangement_group_id == right.arrangement_group_id
                assert not middle.arrangement_group_id
                right.bdo_instrument_id = 0x11
                window._on_track_instrument_changed(right, 0x12)
                assert not left.arrangement_group_id
                assert right.arrangement_group_id == middle.arrangement_group_id
                assert len(window.project_commands._undo) == 1
                window.autosave_timer.stop()
                window.close()
                app.processEvents()
                print("track-group-ui-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=90, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("track-group-ui-ok", result.stdout)

    def test_project_load_rebuilds_groups_instead_of_trusting_stale_ids(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(root / "data")
            project = root / "project.json"
            project.write_text(
                """{"schema_version":13,"path_policy":"project-relative-v1",
                "source_format":"project","output_name":"groups","bpm":120,
                "time_sig":4,"time_sig_denominator":4,"conversion_settings":{},
                "tracks":[
                {"track_id":1,"display_name":"A","gm_program":0,"is_percussion":false,"bdo_instrument_id":18,"arrangement_group_id":"old-a","notes":[[60,90,0,100,0]]},
                {"track_id":2,"display_name":"B","gm_program":0,"is_percussion":false,"bdo_instrument_id":17,"arrangement_group_id":"old-b","notes":[[61,90,0,100,0]]},
                {"track_id":3,"display_name":"C","gm_program":0,"is_percussion":false,"bdo_instrument_id":18,"arrangement_group_id":"old-c","notes":[[62,90,0,100,0]]}
                ]}""",
                encoding="utf-8",
            )
            script = textwrap.dedent(
                f"""
                from pathlib import Path
                from PySide6.QtWidgets import QApplication
                from bdo_music_composer.ui.main_window import MidiToBdoWindow
                app = QApplication([])
                window = MidiToBdoWindow()
                window._load_project(Path({str(project)!r}))
                assert [track.track_id for track in window.tracks] == [1, 3, 2]
                assert window.tracks[0].arrangement_group_id == window.tracks[1].arrangement_group_id
                assert not window.tracks[2].arrangement_group_id
                assert window._wait_for_autosave_idle()
                window.close(); app.processEvents()
                print("project-auto-group-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=environment,
                text=True, capture_output=True, timeout=90, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("project-auto-group-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
