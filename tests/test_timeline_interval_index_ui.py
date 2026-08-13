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
            assert track_index.overview_levels == ()

            # Dense visual summaries and velocity traces are view-owned
            # caches. Project loading must leave them lazy until the track is
            # actually painted.
            assert timeline.velocity_curve_overlay._velocity_traces == {}
            overview = timeline._visible_note_overview_bins(
                track,
                290_000.0,
                1_000.0,
                800.0,
            )
            assert overview
            assert timeline._track_note_indexes[id(track)].overview_levels
            assert timeline.velocity_curve_overlay._velocity_traces == {}
            assert timeline.velocity_curve_overlay.velocity_trace_points(
                track,
                290_000.0,
                291_000.0,
            )
            assert id(track) in timeline.velocity_curve_overlay._velocity_traces

            # Reference-audio alignment changes only affect the timeline
            # boundary. They must not rebuild every note index in the song.
            from PySide6.QtCore import QObject, Signal

            class Reference(QObject):
                changed = Signal()
                timeline_changed = Signal()
                audio_path = None
                waveform_loading = False
                duration_ms = 20_000.0
                project_end_ms = 320_000.0

            reference = Reference()
            interval_identity = id(
                timeline._track_note_indexes[id(track)].intervals
            )
            timeline.set_reference_audio(reference)
            assert timeline._timeline_end_ms() == 320_000.0
            assert timeline._timeline_row_count() == 2
            assert timeline._musical_track_count() == 1
            reference.project_end_ms = 330_000.0
            reference.timeline_changed.emit()
            assert timeline._timeline_end_ms() == 330_000.0
            assert id(
                timeline._track_note_indexes[id(track)].intervals
            ) == interval_identity

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

            # A musical-grid change updates the editable tail immediately;
            # it must not retain the duration calculated for the old BPM.
            reference.duration_ms = 0.0
            reference.project_end_ms = 0.0
            reference.timeline_changed.emit()
            tail_at_120 = timeline._timeline_end_ms()
            timeline.set_musical_grid(60, 4, 0.0)
            assert timeline._timeline_end_ms() > tail_at_120
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
            from bdo_music_composer.editor.arrangement_clip import project_track_notes
            expected = [
                note
                for note in project_track_notes(track)
                if (
                    note.start <= 150_010.0
                    and note.start + note.dur >= 149_990.0
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

            # Clip painting and static-cache keys must scale with the visible
            # range, not with every Clip in a long arrangement.
            from bdo_music_composer.editor.editor_models import ArrangementClipState

            class CountingClips(list):
                def __init__(self, values):
                    super().__init__(values)
                    self.iterations = 0

                def __iter__(self):
                    self.iterations += 1
                    return super().__iter__()

            clip_track = TrackState(2, [], 0, False, "clips", 0x12)
            clip_track.arrangement_clips = CountingClips([
                ArrangementClipState(
                    f"clip-{index}",
                    float(index * 100), float(index * 100 + 50),
                    float(index * 100), float(index * 100 + 50),
                )
                for index in range(12_000)
            ])
            timeline.set_tracks([clip_track])
            clip_track.arrangement_clips.iterations = 0
            visible_clips = timeline._visible_track_clips(
                clip_track, 590_000.0, 591_000.0
            )
            assert 0 < len(visible_clips) < 20
            assert (
                timeline._last_track_clip_query_inspections
                <= timeline.TRACK_CLIP_QUERY_BLOCK_SIZE * 2
            )
            timeline._static_timeline_key(
                grid_h=300.0,
                visible_start=590_000.0,
                visible_duration=1_000.0,
            )
            assert clip_track.arrangement_clips.iterations == 0

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
