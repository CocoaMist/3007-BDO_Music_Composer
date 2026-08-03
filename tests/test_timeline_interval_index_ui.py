from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TimelineIntervalIndexUiTests(unittest.TestCase):
    def test_song_long_note_does_not_widen_every_later_viewport(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import Note, TimelineCanvas, TrackState

            app = QApplication([])
            notes = [
                Note(60, 90, 0.0, 300_000.0, 0),
                *[
                    Note(40 + index % 48, 80, float(index * 25), 10.0, 0)
                    for index in range(1, 12_000)
                ],
            ]
            track = TrackState(1, notes, 0, False, "dense", 0x0B)
            timeline = TimelineCanvas()
            timeline.set_tracks([track])
            track_index = timeline._track_note_indexes[id(track)]
            assert not isinstance(track_index, tuple)
            assert track_index.intervals.ends[0] == 300_000.0

            left = 290_000.0
            right = 291_000.0
            ordered, first, last = timeline._visible_track_note_window(
                track,
                left,
                right,
            )
            actual = ordered[first:last]
            expected = [
                note
                for note in sorted(notes, key=lambda item: item.start)
                if note.start <= right and note.start + note.dur >= left
            ]

            assert actual == expected
            assert notes[0] in actual
            assert 1 < len(actual) < 100
            assert (
                timeline._last_track_note_query_inspections
                <= timeline.TRACK_NOTE_QUERY_BLOCK_SIZE * 3
            )

            # Duration scaling is part of timeline visibility and index
            # rebuilding; it must not be applied a second time by the query.
            track.duration_scale = 0.5
            timeline.set_tracks([track])
            ordered, first, last = timeline._visible_track_note_window(
                track,
                149_990.0,
                150_010.0,
            )
            actual = ordered[first:last]
            expected = [
                note
                for note in sorted(notes, key=lambda item: item.start)
                if (
                    note.start <= 150_010.0
                    and note.start + note.dur * track.duration_scale >= 149_990.0
                )
            ]
            assert actual == expected

            # The detailed editor uses a separate interval index.  It must
            # retain an overlapping song-long note without returning every
            # early short note for a late viewport; ghost notes follow the
            # same rule.
            from PySide6.QtWidgets import QWidget
            from bdo_music_composer.ui.main_window import PianoRollCanvas

            class Editor(QWidget):
                bpm = 120
                time_sig = 4
                beat_origin_ms = 0.0
                transcription_mode_enabled = False

                def quantize_ms(self):
                    return 125.0

            editor = Editor()
            roll = PianoRollCanvas(editor)
            roll.set_notes(notes)
            roll.set_ghost_notes(notes)
            indices = roll.visible_note_indices(290_000.0, 291_000.0)
            visible_notes = [roll.notes[index] for index in indices]
            visible_ghosts = roll.visible_ghost_notes(290_000.0, 291_000.0)
            assert notes[0] in visible_notes
            assert len(visible_notes) < 100
            assert len(visible_ghosts) < 100
            assert any(note.start >= 290_000.0 for note in visible_notes)
            roll.close()
            editor.close()

            timeline.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
