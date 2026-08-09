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
            from bdo_music_composer.editor.editor_models import (
                percussion_key_label_for_track,
            )

            app = QApplication([])
            canonical = TrackState(
                1, [Note(62, 96, 0.0, 120.0, 99), Note(65, 96, 120.0, 120.0, 99)], 0, True,
                "BDO drums", 0x0D, bdo_source_group_index=0,
            )
            imported = TrackState(
                2, [Note(36, 96, 0.0, 120.0, 0), Note(62, 96, 120.0, 120.0, 0)], 0, True,
                "GM drums", 0x0D,
            )
            assert track_uses_canonical_drum_lanes(canonical)
            assert not track_uses_canonical_drum_lanes(imported)
            assert percussion_key_label_for_track(canonical, 61) == "CymCrsh"
            assert percussion_key_label_for_track(imported, 36) == "Kick"
            assert percussion_key_label_for_track(imported, 42) == "Hi-Hat C"
            assert percussion_key_label_for_track(imported, 49) == "Crash 1"
            assert percussion_key_label_for_track(
                TrackState(3, [], 0, True, "Hand drum", 0x04), 60
            ) == "Bng1-Open"
            assert percussion_key_label_for_track(
                TrackState(3, [], 0, True, "Hand drum", 0x04), 78
            ) == "Cng2-Close"
            assert percussion_key_label_for_track(
                TrackState(4, [], 0, True, "Cymbals", 0x05), 71
            ) == "HIT"
            assert percussion_key_label_for_track(
                TrackState(5, [], 0, True, "Handpan", 0x13), 69
            ) == "A4"
            assert percussion_key_label_for_track(
                TrackState(6, [], 0, False, "Piano", 0x07), 60
            ) is None
            canonical_draft = TrackState(
                7,
                [Note(48, 96, 0.0, 120.0, 99), Note(65, 96, 120.0, 120.0, 99)],
                0,
                True,
                "Canonical draft with invalid pitch",
                0x0D,
            )
            assert track_uses_canonical_drum_lanes(canonical_draft)
            assert percussion_key_label_for_track(canonical_draft, 48) == "Kck"

            timeline = TimelineCanvas()
            timeline.set_tracks([canonical, imported])
            timeline.set_validation_notices({
                1: {"errors": ("bad",), "attentions": (), "invalid_note_keys": (timeline._validation_note_key(canonical.notes[1]),)},
                2: {"errors": ("bad",), "attentions": (), "invalid_note_keys": (timeline._validation_note_key(imported.notes[1]),)},
            })
            assert not timeline._note_has_conversion_problem(canonical, canonical.notes[0])
            assert timeline._note_has_conversion_problem(canonical, canonical.notes[1])
            assert not timeline._note_has_conversion_problem(imported, imported.notes[0])
            assert timeline._note_has_conversion_problem(imported, imported.notes[1])
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

    def test_track_context_menu_exposes_bounded_move_actions(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QMenu

            from bdo_music_composer.ui.main_window import TimelineCanvas, TrackState

            app = QApplication([])
            first = TrackState(1, [], 0, False, "first", 0x0B)
            middle = TrackState(2, [], 0, False, "middle", 0x0B)
            last = TrackState(3, [], 0, False, "last", 0x0B)
            timeline = TimelineCanvas()
            timeline.set_tracks([first, middle, last])
            requested = []
            timeline.move_track_requested.connect(
                lambda track, direction: requested.append((track, direction))
            )

            menu_states = []

            for track in (middle, first, last):
                menu = QMenu(timeline)
                move_up, move_down = timeline._add_track_move_actions(
                    menu,
                    track,
                )
                menu_states.append(
                    (move_up.isEnabled(), move_down.isEnabled())
                )
                if track is middle:
                    move_up.trigger()

            assert menu_states == [(True, True), (False, True), (True, False)]
            assert requested == [(middle, -1)]
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
            assert {widget.height() for widget in controls} == {26}
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
            from PySide6.QtCore import QPointF
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [Note(52, 96, 250.0, 900.0, 99)],
                0,
                True,
                "Drums",
                0x0D,
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            editor.show()
            app.processEvents()
            visible_rows = editor.visible_pitch_rows()
            visible_bottom = editor.canvas.pitch_top - visible_rows + 1
            assert editor.canonical_drum_lanes
            assert editor.uses_percussion_key_labels
            assert editor.uses_named_percussion_keys
            assert not hasattr(editor, "roll_mode_spec")
            assert editor.canvas.pitch_top >= 64
            assert visible_bottom <= 48
            assert editor.current_articulation() == 99
            assert editor.percussion_key_label(48) == "Kck · 底鼓"
            assert editor.percussion_key_label(64) == "SnrRollL · 小军鼓长滚奏"
            assert editor.note_block_label(48) == "Kck"
            assert editor.note_block_label(52) == "SnrFlam"
            assert editor.canvas.KEY_W == editor.canvas.NAMED_PERCUSSION_KEY_W == 138
            assert not editor.note_invalid(48)
            assert not editor.note_invalid(64)
            assert editor.note_invalid(47)
            assert editor.note_invalid(65)
            note = editor.canvas.notes[0]
            rect = editor.canvas.note_rect(note)
            assert abs(
                rect.width() - note.dur * editor.canvas.px_per_ms
            ) < 0.01
            assert editor.canvas.note_at(
                QPointF(rect.right() - 1, rect.center().y())
            ) == (0, "resize_right")
            assert editor.canvas.note_rect(
                note._replace(dur=1800.0)
            ).width() > rect.width()
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

    def test_imported_gm_drum_editor_uses_named_drum_lanes(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [
                    Note(36, 100, 0.0, 100.0, 0),
                    Note(49, 90, 250.0, 100.0, 0),
                    Note(62, 80, 500.0, 100.0, 0),
                ],
                0,
                True,
                "GM Drums",
                0x0D,
            )
            window.tracks = [track]
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            assert editor.uses_percussion_key_labels
            assert editor.uses_named_percussion_keys
            assert not editor.canonical_drum_lanes
            assert not hasattr(editor, "roll_mode_spec")
            assert editor.default_articulation_ntype == 0
            assert editor.percussion_key_label(36) == "Kick · 底鼓"
            assert editor.percussion_key_label(42) == "Hi-Hat C · 闭合踩镲"
            assert editor.percussion_key_label(49) == "Crash 1 · 碎音镲 1"
            assert editor.percussion_key_label(62) == "MIDI 62 · 未映射鼓键"
            assert editor.note_block_label(36) == "Kick"
            assert editor.note_block_label(49) == "Crash 1"
            assert editor.note_block_label(62) == "MIDI 62"
            assert editor.note_invalid(62)
            assert editor.canvas.KEY_W == editor.canvas.NAMED_PERCUSSION_KEY_W == 138
            assert "GM" not in editor.track_meta.text()
            short_rect = editor.canvas.note_rect(editor.canvas.notes[0])
            long_note = editor.canvas.notes[0]._replace(dur=2000.0)
            assert editor.canvas.note_rect(long_note).width() > short_rect.width()
            assert editor.canvas.note_at(short_rect.center()) == (0, "move")

            install_localizer(app, "en_US")
            assert editor.percussion_key_label(36) == "Kick · Kick"
            assert editor.percussion_key_label(42) == "Hi-Hat C · Closed hi-hat"
            assert editor.percussion_key_label(49) == "Crash 1 · Crash cymbal 1"
            assert editor.percussion_key_label(62) == "MIDI 62 · Unmapped drum key"
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

    def test_other_game_percussion_uses_piano_roll_blocks_and_key_names(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.main_window import (
                MidiNoteEditorDialog, MidiToBdoWindow, Note, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            for instrument_id, pitch, expected in (
                (0x04, 60, "Bng1-Open"),
                (0x04, 78, "Cng2-Close"),
                (0x05, 71, "HIT"),
                (0x13, 69, "A4"),
            ):
                track = TrackState(
                    instrument_id,
                    [Note(pitch, 96, 100.0, 800.0, 0)],
                    0,
                    True,
                    expected,
                    instrument_id,
                )
                window.tracks = [track]
                editor = MidiNoteEditorDialog(window, track, 120, 4)
                assert editor.uses_percussion_key_labels
                assert editor.uses_named_percussion_keys == (
                    instrument_id in {0x04, 0x05}
                )
                assert editor.percussion_key_label(pitch) == expected
                assert editor.note_block_label(pitch) == expected
                expected_key_width = (
                    editor.canvas.NAMED_PERCUSSION_KEY_W
                    if instrument_id in {0x04, 0x05}
                    else editor.canvas.PIANO_KEY_W
                )
                assert editor.canvas.KEY_W == expected_key_width
                rect = editor.canvas.note_rect(editor.canvas.notes[0])
                assert rect.width() == 800.0 * editor.canvas.px_per_ms
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
