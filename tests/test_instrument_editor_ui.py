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
    def test_game_legality_uses_verified_profile_not_wwise_sample_span(self) -> None:
        completed = _run_offscreen(
            """
            from bdo_music_composer.ui.main_window import (
                BDO_EDITOR_PITCH_RANGES,
                game_supported_pitches,
            )

            assert game_supported_pitches(0x04) == frozenset(
                {60, 65, 66, 67, 72, 73, 74, 77, 78, 79}
            )
            assert game_supported_pitches(0x05) == frozenset({60, 65, 71})
            assert game_supported_pitches(0x13) is None
            assert 0x13 not in BDO_EDITOR_PITCH_RANGES
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_canonical_and_imported_gm_drums_do_not_double_map(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
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

    def test_note_articulation_is_readable_grouped_and_can_return_to_normal(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [
                    Note(60, 127, 0.0, 240.0, 0),
                    Note(64, 112, 8.0, 240.0, 0),
                    Note(67, 96, 80.0, 240.0, 0),
                ],
                0,
                False,
                "Flute",
                0x0B,
                color="#ffd84f",
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.show()
            editor._set_top_inspector_mode("articulation")
            app.processEvents()
            previewed = []
            editor.audition_note = lambda note, force=False: previewed.append(
                (note.pitch, note.ntype, force)
            )

            assert editor.articulation_combo.itemData(0) == 0
            assert "普通" in editor.articulation_combo.itemText(0)
            assert 0 in editor.articulation_buttons
            assert 3 in editor.articulation_buttons

            editor.canvas.selected = {0}
            editor.refresh_fields()
            editor._choose_articulation(3)
            assert [note.ntype for note in editor.canvas.notes] == [3, 3, 0]
            assert previewed[-1] == (60, 3, False)

            # Clicking the already active technique releases it back to the
            # explicit ordinary entry, including all same-onset chord notes.
            editor.articulation_buttons[3].click()
            assert [note.ntype for note in editor.canvas.notes] == [0, 0, 0]
            assert editor.current_articulation() == 0
            assert previewed[-1] == (60, 0, False)
            editor.undo()
            assert [note.ntype for note in editor.canvas.notes] == [3, 3, 0]
            editor.redo()
            assert [note.ntype for note in editor.canvas.notes] == [0, 0, 0]

            # A dropdown-only technique must replace the stale quick-button
            # highlight with one aligned dynamic selection chip.
            editor.articulation_combo.setCurrentIndex(
                editor.articulation_combo.findData(4)
            )
            assert [note.ntype for note in editor.canvas.notes] == [4, 4, 0]
            assert not any(
                button.isChecked()
                for button in editor.articulation_buttons.values()
            )
            assert editor.articulation_overflow_button.isVisible()
            assert editor.articulation_overflow_button.isChecked()
            assert editor.articulation_overflow_button.property("ntype") == 4
            assert previewed[-1] == (60, 4, False)
            controls = [
                editor.articulation_combo,
                editor.articulation_preview_button,
                *editor.articulation_buttons.values(),
                editor.articulation_overflow_button,
            ]
            assert {widget.y() for widget in controls} == {0}
            assert {widget.height() for widget in controls} == {28}
            editor.articulation_preview_button.click()
            assert previewed[-1] == (60, 4, True)

            ordinary = editor.canvas._note_fill_color(
                Note(60, 127, 0.0, 240.0, 0)
            )
            technique = editor.canvas._note_fill_color(
                Note(60, 127, 0.0, 240.0, 3)
            )
            assert ordinary.name() != technique.name()
            assert ordinary.value() <= 158
            assert technique.value() <= 158
            assert editor.canvas._note_text_color(ordinary).isValid()

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

    def test_note_editor_blocks_native_articulation_outside_trigger_range(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [Note(44, 96, 0.0, 200.0, 0)],
                0,
                False,
                "Electric guitar",
                0x24,
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.canvas.selected = {0}
            editor.refresh_fields()
            editor._choose_articulation(25)
            assert editor.canvas.notes[0].ntype == 0
            assert editor.current_articulation() == 0
            toast = getattr(editor, "_global_toast", None)
            assert toast is not None
            assert "C2–G2" in toast.message.text()

            editor.canvas.notes[0] = editor.canvas.notes[0]._replace(pitch=36)
            editor.refresh_fields()
            editor._choose_articulation(25)
            assert editor.canvas.notes[0].ntype == 25

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

    def test_note_editor_migrates_legacy_track_articulation_before_export(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.export.export_workflow import freeze_export_tracks
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [
                    Note(60, 96, 0.0, 200.0, 0),
                    Note(64, 96, 100.0, 200.0, 0),
                ],
                0,
                False,
                "Flute",
                0x0B,
                articulation_type=3,
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            assert [note.ntype for note in editor.canvas.notes] == [3, 3]
            editor.canvas.selected = {0}
            editor.refresh_fields()
            editor._choose_articulation(0)
            report = editor.apply_notes()
            assert report is not None and report.project_changed
            assert track.articulation_type is None
            assert [note.ntype for note in track.notes] == [0, 3]
            snapshot = freeze_export_tracks([track])[0]
            assert snapshot.articulation_type is None
            assert [note.ntype for note in snapshot.notes] == [0, 3]

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

    def test_articulation_audition_passes_the_current_note_type_to_audio(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            class FakeAudio:
                def __init__(self):
                    self.loaded = []

                def load_project_async(self, tracks, *_args):
                    self.loaded.append(tracks[0].notes[0])

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [Note(60, 90, 0.0, 300.0, 0)],
                0,
                False,
                "Flute",
                0x0B,
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            real_audio = window.realtime_audio
            fake_audio = FakeAudio()
            window.realtime_audio = fake_audio
            window._realtime_preview_blockers = lambda _tracks: []

            editor.audition_note(
                Note(60, 90, 0.0, 300.0, 4),
                force=True,
            )
            assert len(fake_audio.loaded) == 1
            loaded = fake_audio.loaded[0]
            assert loaded.pitch == 60
            assert loaded.ntype == 4
            assert loaded.start == 0.0
            assert loaded.dur == 300.0
            assert "颤音小调" in editor.audition_note_name

            editor.audition_timer.stop()
            editor.audition_pending = False
            window.realtime_audio = real_audio
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

    def test_drum_editor_focuses_all_native_lanes_and_defaults_to_type_99(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
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
