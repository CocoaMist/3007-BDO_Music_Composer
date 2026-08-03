from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImportTransactionTests(unittest.TestCase):
    def test_invalid_source_does_not_replace_the_open_project(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            temp_dir = Path(folder_name)
            invalid_midi = temp_dir / "broken.mid"
            invalid_midi.write_bytes(b"not a midi")
            invalid_bdo = temp_dir / "broken.bdo"
            invalid_bdo.write_bytes(b"not a score")
            invalid_project = temp_dir / "broken-project.json"
            invalid_project.write_text(
                """{
                  "schema_version": 11,
                  "path_policy": "project-relative-v1",
                  "source_format": "project",
                  "tracks": [{
                    "track_id": 1,
                    "bdo_track_settings": ["not-a-byte"],
                    "notes": []
                  }]
                }""",
                encoding="utf-8",
            )
            invalid_metadata_project = temp_dir / "bad-metadata-project.json"
            invalid_metadata_project.write_text(
                """{
                  "schema_version": 11,
                  "path_policy": "project-relative-v1",
                  "source_format": "project",
                  "owner_id": "not-an-owner-id",
                  "tracks": [{
                    "track_id": 2,
                    "bdo_track_settings": [0,0,0,0,0,0,0,0],
                    "notes": [[64, 88, 0.0, 100.0, 0]]
                  }]
                }""",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["BDO_USER_DATA_DIR"] = str(temp_dir / "user-data")
            script = textwrap.dedent(
                f"""
                import json
                from pathlib import Path
                from unittest.mock import patch

                from PySide6.QtWidgets import QApplication

                from bdo_midi import Note
                from bdo_music_composer.editor.editor_models import TrackState
                import bdo_music_composer.ui.main_window as gui

                app = QApplication([])
                window = gui.MidiToBdoWindow()
                track = TrackState(
                    track_id=41,
                    notes=[Note(60, 73, 12.0, 345.0, 0)],
                    gm_program=0,
                    is_percussion=False,
                    display_name="edited lane",
                    bdo_instrument_id=0x0B,
                    bdo_track_volume=83,
                    bdo_track_settings=(4, 1, 5, 2, 6, 3, 7, 8),
                )
                window.tracks = [track]
                window.midi_path = "existing-source.mid"
                window.source_format = "project"
                window.project_id = "existing-project"
                window.output_name.setText("keep-me")
                window._refresh_tracks()
                window._push_project_snapshot()
                undo_count = len(window.project_commands._undo)

                window._open_midi_path(Path({str(invalid_midi)!r}))
                assert window.tracks == [track]
                assert window.tracks[0].notes == [Note(60, 73, 12.0, 345.0, 0)]
                assert window.tracks[0].bdo_track_volume == 83
                assert window.midi_path == "existing-source.mid"
                assert window.source_format == "project"
                assert window.project_id == "existing-project"
                assert window.output_name.text() == "keep-me"
                assert len(window.project_commands._undo) == undo_count

                with patch.object(gui.QMessageBox, "warning"):
                    window._open_bdo_score_path(Path({str(invalid_bdo)!r}))
                assert window.tracks == [track]
                assert window.midi_path == "existing-source.mid"
                assert window.project_id == "existing-project"
                assert len(window.project_commands._undo) == undo_count

                with patch.object(gui.QMessageBox, "warning"):
                    window._load_project(Path({str(invalid_project)!r}))
                assert window.tracks == [track]
                assert window.midi_path == "existing-source.mid"
                assert window.project_id == "existing-project"
                assert len(window.project_commands._undo) == undo_count

                # Metadata is prepared before the first UI mutation too.
                with patch.object(gui.QMessageBox, "warning"):
                    window._load_project(Path({str(invalid_metadata_project)!r}))
                assert window.tracks == [track]
                assert window.midi_path == "existing-source.mid"
                assert window.source_format == "project"
                assert window.project_id == "existing-project"
                assert window.output_name.text() == "keep-me"
                assert len(window.project_commands._undo) == undo_count

                window.close()
                app.processEvents()
                app.quit()
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
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

    def test_project_snapshot_is_authoritative_when_midi_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            temp_dir = Path(folder_name)
            project_dir = temp_dir / "saved-project"
            project_dir.mkdir()
            project_path = project_dir / "project.json"
            project_path.write_text(
                """{
                  "schema_version": 11,
                  "path_policy": "project-relative-v1",
                  "source_format": "midi",
                  "source_midi_path": "deleted-source.mid",
                  "output_name": "snapshot-authority",
                  "bpm": 137,
                  "time_sig": 3,
                  "time_sig_denominator": 4,
                  "conversion_settings": {
                    "transpose": 0,
                    "velocity_mode": "preserve"
                  },
                  "tracks": [
                    {
                      "track_id": 7,
                      "display_name": "kept edit",
                      "gm_program": 0,
                      "is_percussion": false,
                      "bdo_instrument_id": 11,
                      "bdo_track_volume": 91,
                      "bdo_track_settings": [8,7,6,5,4,3,2,1],
                      "volume_scale": 1.0,
                      "duration_scale": 1.0,
                      "notes": [[72, 0, 123.0, 456.0, 11]]
                    },
                    {
                      "track_id": 99,
                      "display_name": "user-created lane",
                      "gm_program": 12,
                      "is_percussion": false,
                      "bdo_instrument_id": 12,
                      "bdo_track_volume": 64,
                      "bdo_track_settings": [0,0,0,0,0,0,0,0],
                      "volume_scale": 1.0,
                      "duration_scale": 1.0,
                      "notes": [[55, 88, 0.0, 100.0, 0]]
                    }
                  ]
                }""",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["BDO_USER_DATA_DIR"] = str(temp_dir / "user-data")
            script = textwrap.dedent(
                f"""
                import json
                from pathlib import Path
                from PySide6.QtWidgets import QApplication
                import bdo_music_composer.ui.main_window as gui

                app = QApplication([])
                window = gui.MidiToBdoWindow()
                window.owner_id = 999
                window.char_name = "previous-project"
                window._load_project(Path({str(project_path)!r}))
                assert [track.track_id for track in window.tracks] == [7, 99]
                assert [track.display_name for track in window.tracks] == [
                    "kept edit", "user-created lane"
                ]
                assert window.tracks[0].notes[0].vel == 0
                assert window.tracks[0].notes[0].ntype == 11
                assert window.tracks[0].bdo_track_volume == 91
                assert window.tracks[0].bdo_track_settings == (8,7,6,5,4,3,2,1)
                assert window.midi_path == ""
                assert window.time_sig_denominator == 4
                assert window.owner_id == 0
                assert window.char_name == ""
                assert window._wait_for_autosave_idle()
                saved = json.loads(
                    Path({str(project_path)!r}).read_text(encoding="utf-8")
                )
                assert saved["time_sig_denominator"] == 4
                assert [item["track_id"] for item in saved["tracks"]] == [7, 99]
                window.close()
                app.processEvents()
                app.quit()
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
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
