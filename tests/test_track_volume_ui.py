from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrackVolumeUiTests(unittest.TestCase):
    def test_track_context_velocity_base_changes_only_requested_track(self) -> None:
        script = textwrap.dedent(
            """
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QDialog, QMenu

            from bdo_music_composer.ui.dialogs.track_settings_dialogs import TrackVelocityBaseDialog
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            target = TrackState(
                1,
                [Note(60, 20, 0.0, 100.0, 0), Note(62, 50, 100.0, 100.0, 0), Note(64, 80, 200.0, 100.0, 0)],
                0, False, "target", 0x0B, bdo_track_volume=70,
                bdo_source_note_records=(
                    (60, 20, 0.0, 100.0, 0, 10),
                    (62, 50, 100.0, 100.0, 0, 70),
                    (64, 80, 200.0, 100.0, 0, 80),
                ),
            )
            other = TrackState(
                2, [Note(67, 30, 0.0, 100.0, 0), Note(69, 60, 100.0, 100.0, 0)],
                0, False, "other", 0x0C, bdo_track_volume=55,
            )
            window.tracks = [target, other]
            window.timeline.set_tracks(window.tracks)
            window._autosave_project = lambda *args, **kwargs: None

            dialog = TrackVelocityBaseDialog(window, target)
            assert dialog.velocity_base.minimum() == -127
            assert dialog.velocity_base.maximum() == 127
            dialog.close()

            requested = []
            window.timeline.velocity_base_requested.disconnect(
                window._show_track_velocity_base_dialog
            )
            window.timeline.velocity_base_requested.connect(requested.append)
            menu = QMenu(window.timeline)
            action = window.timeline._add_velocity_base_action(menu, target)
            assert action.text() == "轨道力度基数…"
            action.trigger()
            assert requested == [target]

            class AcceptedDialog:
                def __init__(self, _parent, _track): pass
                def exec(self): return QDialog.Accepted
                def selected_velocity_base(self): return 100
                def equalize_enabled(self): return True

            with patch(
                "bdo_music_composer.ui.main_window.TrackVelocityBaseDialog",
                AcceptedDialog,
            ):
                window._show_track_velocity_base_dialog(target)

            assert [note.vel for note in target.notes] == [85, 106, 127]
            assert [record[5] for record in target.bdo_source_note_records] == [78, 120, 127]
            assert [note.vel for note in other.notes] == [30, 60]
            assert [target.bdo_track_volume, other.bdo_track_volume] == [70, 55]

            window._undo_project()
            assert [note.vel for note in window.tracks[0].notes] == [20, 50, 80]
            assert [record[5] for record in window.tracks[0].bdo_source_note_records] == [10, 70, 80]
            assert [note.vel for note in window.tracks[1].notes] == [30, 60]
            window.close()
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
            timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_equalize_toggle_rebuilds_from_original_velocity_baseline(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [
                    Note(60, 20, 0.0, 100.0, 0),
                    Note(62, 50, 100.0, 100.0, 0),
                    Note(64, 80, 200.0, 100.0, 0),
                ],
                0,
                False,
                "toggle",
                0x0B,
                bdo_source_note_records=(
                    (60, 20, 0.0, 100.0, 0, 10),
                    (62, 50, 100.0, 100.0, 0, 70),
                    (64, 80, 200.0, 100.0, 0, 80),
                ),
            )
            window.tracks = [track]
            window.timeline.set_tracks(window.tracks)
            window._autosave_project = lambda *args, **kwargs: None
            window._sync_toolbar_global_gain()

            # Base +100 without normalization uses ordinary 0..127 clipping.
            window._begin_toolbar_global_gain_drag()
            window.toolbar_global_gain.setValue(100)
            window._commit_toolbar_global_gain()
            assert [note.vel for note in track.notes] == [120, 127, 127]
            assert [record[5] for record in track.bdo_source_note_records] == [110, 127, 127]

            # A real checkbox click must discard the clipped working result and
            # rebuild B normalization from the untouched original A/B values.
            window.toolbar_global_gain_equalize.click()
            assert window.toolbar_global_gain_equalize.isChecked()
            assert [note.vel for note in track.notes] == [85, 106, 127]
            assert [record[5] for record in track.bdo_source_note_records] == [78, 120, 127]

            # Cancelling normalization restores the exact unchecked effect for
            # the same +100 base, rather than accumulating from normalized data.
            window.toolbar_global_gain_equalize.click()
            assert not window.toolbar_global_gain_equalize.isChecked()
            assert [note.vel for note in track.notes] == [120, 127, 127]
            assert [record[5] for record in track.bdo_source_note_records] == [110, 127, 127]

            # Neutral base always restores the original MIDI/BDO velocity pair.
            window.toolbar_global_gain_value.setValue(0)
            window._commit_toolbar_global_gain_input()
            assert [note.vel for note in track.notes] == [20, 50, 80]
            assert [record[5] for record in track.bdo_source_note_records] == [10, 70, 80]
            window.close()
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
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_global_base_gain_scales_notes_without_touching_track_volume(self) -> None:
        script = textwrap.dedent(
            """
            import tempfile
            from pathlib import Path

            from PySide6.QtWidgets import QApplication

            from bdo_codec import decode_score
            from bdo_music_composer.core.conversion_settings import ConversionSettings
            from bdo_music_composer.editor.pitch_transform import PitchTransformPlan
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState
            from bdo_music_composer.export.export_workflow import (
                ExportRequest, freeze_export_tracks, prepare_export,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            source = TrackState(
                1, [Note(60, 30, 0.0, 100.0, 0), Note(64, 60, 100.0, 100.0, 0)],
                0, False, "source", 0x0B, bdo_track_volume=70,
                bdo_source_note_records=(
                    (60, 30, 0.0, 100.0, 0, 20),
                    (64, 60, 100.0, 100.0, 0, 40),
                ),
            )
            peer = TrackState(
                2, [Note(64, 90, 100.0, 100.0, 0)], 0, False, "peer", 0x0B,
                bdo_track_volume=70,
            )
            other = TrackState(
                3, [Note(67, 110, 200.0, 100.0, 0)], 0, False, "other", 0x0C,
                bdo_track_volume=55,
            )
            window.tracks = [source, peer, other]
            window.timeline.set_tracks(window.tracks)
            original_velocities = [[note.vel for note in track.notes] for track in window.tracks]
            window._on_preview_mapping_changed = lambda: None
            window._autosave_project = lambda *args, **kwargs: None

            # This is a score-wide control and does not require row selection.
            window._sync_toolbar_global_gain()
            assert window.toolbar_global_gain.isEnabled()
            assert window.toolbar_global_gain.value() == 0
            assert window.toolbar_global_gain_value.value() == 0
            assert (window.toolbar_global_gain.minimum(), window.toolbar_global_gain.maximum()) == (-127, 127)
            assert (window.toolbar_global_gain_value.minimum(), window.toolbar_global_gain_value.maximum()) == (-127, 127)

            window._select_track(source)
            assert window.toolbar_global_gain_group.parent() is not None
            assert window.toolbar_global_gain.isEnabled()
            assert window.toolbar_global_gain.value() == 0
            assert window.toolbar_global_gain_value.value() == 0
            assert window.toolbar_global_gain.width() == 220
            assert window.toolbar_global_gain_label.text() == "全局力度基数"
            window.toolbar_global_gain_equalize.setChecked(True)

            window._begin_toolbar_global_gain_drag()
            window.toolbar_global_gain.setValue(100)
            assert [[note.vel for note in track.notes] for track in window.tracks] == [[79, 97], [115], [127]]
            assert [record[5] for record in window.tracks[0].bdo_source_note_records] == [73, 85]
            assert [track.bdo_track_volume for track in window.tracks] == [70, 70, 55]
            window._commit_toolbar_global_gain()

            assert [track.bdo_track_volume for track in window.tracks] == [70, 70, 55]
            assert window.toolbar_global_gain.value() == 100
            assert [[note.vel for note in track.notes] for track in window.tracks] == [[79, 97], [115], [127]]

            # Returning to zero always rebuilds from the immutable MIDI/BDO
            # baseline, even after an extreme mapping reached 127.
            window.toolbar_global_gain_value.setValue(0)
            window._commit_toolbar_global_gain_input()
            assert window.toolbar_global_gain.value() == 0
            assert [[note.vel for note in track.notes] for track in window.tracks] == original_velocities
            assert [record[5] for record in source.bdo_source_note_records] == [20, 40]

            # The numeric base is absolute and always reads the same baseline.
            window.toolbar_global_gain_value.setValue(120)
            window._commit_toolbar_global_gain_input()
            assert window.toolbar_global_gain.value() == 120
            assert [[note.vel for note in track.notes] for track in window.tracks] == [[83, 99], [116], [127]]
            assert [record[5] for record in source.bdo_source_note_records] == [77, 88]
            assert [track.bdo_track_volume for track in window.tracks] == [70, 70, 55]
            exported = freeze_export_tracks(window.tracks)
            assert [track.bdo_track_volume for track in exported] == [70, 70, 55]
            assert [[note.vel for note in track.notes] for track in exported] == [[83, 99], [116], [127]]

            # Exercise the real v9 encoder and decoder.  The materialized Base
            # percentage must survive binary export while mixer Volume stays
            # independent and every note keeps the same pairwise difference.
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                request = ExportRequest(
                    direct_tracks=exported,
                    bpm=120,
                    time_signature=4,
                    out_path=root / "global-base.bdo",
                    character_name="Global Base",
                    owner_id=123,
                    conversion=ConversionSettings(),
                    pitch_plan=PitchTransformPlan(0),
                    reverb=0,
                    delay=0,
                    chorus=None,
                    game_dir=root / "game",
                    track_volumes=((0, 70), (1, 70), (2, 55)),
                )
                prepared = prepare_export(request)
                document = decode_score(prepared.data)
            exported_notes = sorted(
                (
                    note.start_ms,
                    note.pitch,
                    note.velocity_a,
                    note.velocity_b,
                )
                for group in document.groups
                for physical_track in group.tracks
                for note in physical_track.notes
            )
            assert [item[2] for item in exported_notes] == [83, 99, 116, 127]
            assert [item[3] for item in exported_notes] == [77, 88, 116, 127]
            assert [item[2] for item in exported_notes] == sorted(item[2] for item in exported_notes)
            active_volumes = sorted(
                physical_track.volume
                for group in document.groups
                for physical_track in group.tracks
                if physical_track.notes
            )
            assert active_volumes == [55, 70]
            window._undo_project()
            assert [track.bdo_track_volume for track in window.tracks] == [70, 70, 55]
            assert [[note.vel for note in track.notes] for track in window.tracks] == original_velocities
            assert [record[5] for record in window.tracks[0].bdo_source_note_records] == [20, 40]
            window._undo_project()
            assert [[note.vel for note in track.notes] for track in window.tracks] == [[79, 97], [115], [127]]
            assert [record[5] for record in window.tracks[0].bdo_source_note_records] == [73, 85]
            window._undo_project()
            assert [[note.vel for note in track.notes] for track in window.tracks] == original_velocities
            assert [record[5] for record in window.tracks[0].bdo_source_note_records] == [20, 40]
            window.close()
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
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_game_volume_commit_updates_the_shared_instrument_and_undoes_once(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            source = TrackState(
                1, [], 0, False, "source", 0x0B, bdo_track_volume=90
            )
            same_instrument = TrackState(
                2, [], 0, False, "same", 0x0B, bdo_track_volume=70
            )
            other_instrument = TrackState(
                3, [], 0, False, "other", 0x0C, bdo_track_volume=55
            )
            window.tracks = [source, same_instrument, other_instrument]
            autosaves = []
            window._autosave_project = (
                lambda reason, immediate=False: autosaves.append(
                    (reason, immediate)
                )
            )

            # Timeline painting has already applied the source value when the
            # typed commit signal reaches the main window.
            source.bdo_track_volume = 42
            window._on_game_instrument_volume_committed(source, 90, 42)
            assert [track.bdo_track_volume for track in window.tracks] == [
                42, 42, 55
            ]
            assert autosaves == [("game instrument volume", False)]

            window._undo_project()
            assert [track.bdo_track_volume for track in window.tracks] == [
                90, 70, 55
            ]
            assert autosaves[-1] == ("project undo", True)
            window.close()
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
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_painted_game_volume_control_is_bounded_and_preserves_raw_imports(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QSlider

            from bdo_music_composer.ui.main_window import Note, TimelineCanvas, TrackState

            app = QApplication([])
            canvas = TimelineCanvas()
            canvas.resize(820, 400)
            # Raw score bytes above the game's authoring limit remain intact
            # until the user deliberately edits the row control.
            track = TrackState(
                3,
                [Note(60, 90, 0.0, 500.0, 0)],
                0,
                False,
                "lead",
                0x0B,
                bdo_track_volume=118,
            )
            canvas.set_tracks([track])
            canvas.show()
            app.processEvents()
            assert track.bdo_track_volume == 118
            assert canvas.findChildren(QSlider) == []
            volume_regions = [
                rect for rect, action, item in canvas.hit_regions
                if action == "track_volume" and item is track
            ]
            assert len(volume_regions) == 1
            rect = volume_regions[0]
            assert rect.width() == 50
            changes = []
            canvas.game_volume_committed.connect(
                lambda _track, previous, current: changes.append(
                    (previous, current)
                )
            )
            target = QPoint(
                round(rect.left() + rect.width() * 0.75),
                round(rect.center().y()),
            )
            QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, target)
            QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, target)
            app.processEvents()
            assert 74 <= track.bdo_track_volume <= 76
            assert changes == [(118, track.bdo_track_volume)]
            assert canvas._track_volume_from_position(rect, rect.left() - 50) == 0
            assert canvas._track_volume_from_position(rect, rect.right() + 50) == 100
            assert TrackState(4, [], 0, False, "default", 0x0B).bdo_track_volume == 70
            canvas.close()
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
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_output_controls_live_in_settings_not_bottom_bar(self) -> None:
        script = textwrap.dedent(
            """
            import tempfile
            from pathlib import Path

            from PySide6.QtWidgets import QApplication, QFrame, QWidget

            from bdo_music_composer.ui.main_window import (
                MidiToBdoWindow, Note, SettingsDialog, TrackState,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            window._show_workspace()
            window.show()
            app.processEvents()
            assert window.findChild(QFrame, "Inspector") is None
            assert window.findChild(QFrame, "PerformanceStrip") is not None
            assert window.workspace_page.layout().count() == 2
            assert not hasattr(window, "selected_volume")
            assert not hasattr(window, "open_output_button")
            settings = SettingsDialog(window)
            assert settings.output_dir.objectName() == "OutputDirectoryEdit"
            assert settings.findChild(QWidget, "BrowseOutputDirectoryButton") is not None
            assert settings.findChild(QWidget, "OpenOutputDirectoryButton") is not None
            settings.close()
            with tempfile.TemporaryDirectory() as temp:
                window.output_dir_path = temp
                window.output_name.setText("volume-ui-test")
                window.source_format = "project"
                window.owner_id = 1
                window.tracks = [
                    TrackState(
                        0,
                        [Note(60, 90, 0.0, 200.0, 0)],
                        0,
                        False,
                        "lead",
                        0x0B,
                    )
                ]
                params = window._build_params()
                assert Path(params["out_path"]).parent == Path(temp)
            window.close()
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
            timeout=45,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
