from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(source: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )


class InstrumentEditorUiTests(unittest.TestCase):
    def test_canonical_and_imported_gm_drums_do_not_double_map(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from pyside_bdo_gui import (
                Note, TimelineCanvas, TrackState,
                track_uses_canonical_drum_lanes,
            )

            app = QApplication([])
            canonical = TrackState(
                1, [Note(62, 96, 0.0, 120.0, 99)], 0, True,
                "BDO drums", 0x0D, bdo_source_group_index=0,
            )
            imported = TrackState(
                2, [Note(36, 96, 0.0, 120.0, 0)], 0, True,
                "GM drums", 0x0D,
            )
            assert track_uses_canonical_drum_lanes(canonical)
            assert not track_uses_canonical_drum_lanes(imported)

            timeline = TimelineCanvas()
            timeline.set_tracks([canonical, imported])
            assert not timeline._note_has_conversion_problem(canonical, 62)
            assert timeline._note_has_conversion_problem(canonical, 65)
            assert not timeline._note_has_conversion_problem(imported, 36)
            assert timeline._note_has_conversion_problem(imported, 62)
            timeline.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_drum_editor_focuses_all_native_lanes_and_defaults_to_type_99(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from pyside_bdo_gui import (
                MidiNoteEditorDialog, MidiToBdoWindow, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(1, [], 0, True, "Drums", 0x0D)
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.show()
            app.processEvents()
            visible_rows = editor.visible_pitch_rows()
            visible_bottom = editor.canvas.pitch_top - visible_rows + 1
            assert editor.canonical_drum_lanes
            assert editor.canvas.pitch_top >= 64
            assert visible_bottom <= 48
            assert editor.current_articulation() == 99
            assert not editor.note_invalid(48)
            assert not editor.note_invalid(64)
            assert editor.note_invalid(47)
            assert editor.note_invalid(65)
            editor.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
