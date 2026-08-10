from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BdoEffectsUiTests(unittest.TestCase):
    def _run_offscreen(self, source: str) -> None:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
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

    def test_track_fx_edits_only_authored_aux_send_bytes(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QSpinBox, QWidget

            from bdo_music_composer.ui.main_window import TrackFxDialog, TrackState

            app = QApplication([])
            parent = QWidget()
            raw = (111, 12, 122, 34, 133, 56, 78, 90)
            track = TrackState(
                1,
                [],
                0,
                False,
                "fx-test",
                0x0B,
                bdo_track_settings=raw,
            )
            dialog = TrackFxDialog(parent, track)
            reverb = dialog.findChild(QSpinBox, "TrackReverbSend")
            delay = dialog.findChild(QSpinBox, "TrackDelaySend")
            chorus = dialog.findChild(QSpinBox, "TrackChorusSend")
            assert reverb is not None
            assert delay is not None
            assert chorus is not None
            assert "共享混响" in reverb.toolTip()
            assert "回声总线" in delay.toolTip()
            assert "合唱/Flanger" in chorus.toolTip()
            for field in (reverb, delay, chorus):
                assert (field.minimum(), field.maximum()) == (0, 100)
                assert field.value() == 100
                assert "导入原值" in field.toolTip()

            # Merely opening the editor must not normalize imported wire bytes.
            assert dialog.selected_track_settings() == raw
            assert not dialog.track_effects_changed()

            # A single authoring operation owns one Aux byte only.  The other
            # two Aux sends and all five master bytes remain lossless.
            reverb.setValue(45)
            assert dialog.selected_track_settings() == (
                45, 12, 122, 34, 133, 56, 78, 90
            )
            assert dialog.track_effects_changed()

            # The three controls map exactly to indexes 0, 2, and 4.
            delay.setValue(46)
            chorus.setValue(47)
            assert dialog.selected_track_settings() == (
                45, 12, 46, 34, 47, 56, 78, 90
            )
            assert track.bdo_track_settings == raw
            dialog.close()
            parent.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_game_effect_controls_stay_synchronized_and_bounded(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QSpinBox, QWidget

            from bdo_common.bdo_track_effects import MasterEffects
            from bdo_music_composer.ui.dialogs.effect_controls_qt import (
                EffectControlCard,
                EffectModeCard,
                GameEffectDial,
            )
            from bdo_music_composer.ui.main_window import (
                MasterEffectsDialog,
                TrackFxDialog,
                TrackState,
            )

            app = QApplication([])
            parent = QWidget()
            track = TrackState(
                1, [], 0, False, "fx-test", 0x0B,
                bdo_track_settings=(10, 0, 20, 0, 30, 0, 0, 0),
            )
            track_dialog = TrackFxDialog(parent, track)
            track_cards = track_dialog.findChildren(EffectControlCard)
            track_dials = track_dialog.findChildren(GameEffectDial)
            assert track_dialog.objectName() == "TrackFxDialog"
            assert len(track_cards) == len(track_dials) == 3

            reverb = track_dialog.findChild(QSpinBox, "TrackReverbSend")
            assert reverb is not None
            reverb_card = next(card for card in track_cards if reverb.parent() is card)
            reverb_card.dial.setValue(42)
            assert reverb.value() == 42
            assert track_dialog.changed_send_indices() == frozenset({0})
            reverb.setValue(73)
            assert reverb_card.dial.value() == 73
            assert not reverb_card.dial.grab().isNull()

            master = MasterEffectsDialog(
                parent,
                MasterEffects(11, 22, 33, 44, 55),
            )
            assert len(master.findChildren(EffectControlCard)) == 5
            assert len(master.findChildren(GameEffectDial)) == 5
            assert master.minimumSizeHint().width() <= master.minimumWidth()
            assert master.minimumSizeHint().height() <= master.minimumHeight()

            beginner = TrackState(
                2, [], 0, False, "beginner", 0x00,
                bdo_track_settings=(10, 0, 20, 0, 30, 0, 0, 0),
            )
            unsupported = TrackFxDialog(parent, beginner)
            assert all(
                not dial.isEnabled()
                for dial in unsupported.findChildren(GameEffectDial)
            )

            marnian = TrackState(
                3, [], 0, False, "marnian", 0x14,
                bdo_track_settings=(10, 0, 20, 0, 30, 0, 0, 0),
                marnian_synth_mode="super",
            )
            marnian_dialog = TrackFxDialog(parent, marnian)
            mode_cards = marnian_dialog.findChildren(EffectModeCard)
            assert len(mode_cards) == 1
            assert marnian_dialog.marnian_mode is not None
            assert marnian_dialog.marnian_mode.parent() is mode_cards[0]
            assert marnian_dialog.marnian_mode.objectName() == "MarnianModeSelector"
            assert marnian_dialog.selected_marnian_synth_mode() == "super"
            marnian_dialog.show()
            app.processEvents()
            rack_cards = [
                *marnian_dialog.findChildren(EffectControlCard),
                *mode_cards,
            ]
            assert len(rack_cards) == 4
            assert len({card.geometry().y() for card in rack_cards}) == 1
            assert len({card.height() for card in rack_cards}) == 1
            marnian_dialog.marnian_mode.setCurrentIndex(
                marnian_dialog.marnian_mode.findData("superoct")
            )
            assert marnian_dialog.selected_marnian_synth_mode() == "superoct"

            marnian_dialog.close()
            unsupported.close()
            master.close()
            track_dialog.close()
            parent.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_every_instrument_row_exposes_the_track_fx_editor(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import TimelineCanvas, TrackState

            app = QApplication([])
            timeline = TimelineCanvas()
            track = TrackState(1, [], 0, False, "guitar", 0x0B)
            timeline.set_tracks([track])
            timeline.resize(820, 320)
            timeline.show()
            app.processEvents()
            fx_rect = next(
                rect for rect, action, target in timeline.hit_regions
                if action == "fx" and target is track
            )
            requested = []
            timeline.effects_requested.connect(requested.append)
            QTest.mouseClick(
                timeline,
                Qt.LeftButton,
                Qt.NoModifier,
                fx_rect.center().toPoint(),
            )
            app.processEvents()
            assert requested == [track]
            timeline.close()
            app.quit()
            """
        )

    def test_beginner_instrument_preserves_but_cannot_author_aux_sends(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QLabel, QSpinBox, QWidget

            from bdo_music_composer.ui.main_window import TrackFxDialog, TrackState

            app = QApplication([])
            parent = QWidget()
            raw = (61, 12, 62, 34, 63, 56, 78, 90)
            track = TrackState(
                1, [], 0, False, "beginner", 0x00,
                bdo_track_settings=raw,
            )
            dialog = TrackFxDialog(parent, track)
            fields = (
                dialog.findChild(QSpinBox, "TrackReverbSend"),
                dialog.findChild(QSpinBox, "TrackDelaySend"),
                dialog.findChild(QSpinBox, "TrackChorusSend"),
            )
            assert all(field is not None and not field.isEnabled() for field in fields)
            assert any(
                "不提供 Effector/AuxSend" in label.text()
                for label in dialog.findChildren(QLabel)
            )

            # Even programmatic changes cannot turn unsupported authoring into
            # a wire mutation; imported bytes remain available for round-trip.
            fields[0].setValue(10)
            assert dialog.selected_track_settings() == raw
            assert not dialog.track_effects_changed()
            assert dialog.changed_send_indices() == frozenset()
            dialog.close()
            parent.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_track_fx_commit_marks_conversion_check_dirty(self) -> None:
        self._run_offscreen(
            """
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QDialog

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            track = TrackState(
                1,
                [],
                0,
                False,
                "fx-commit",
                0x0B,
                bdo_track_settings=(0, 21, 0, 23, 0, 24, 25, 26),
            )
            window.tracks = [track]
            dirty_calls = []
            preview_calls = []
            window._mark_conversion_check_dirty = lambda: dirty_calls.append(True)
            window._on_preview_mapping_changed = lambda: preview_calls.append(True)

            with patch("bdo_music_composer.ui.main_window.TrackFxDialog") as dialog_type:
                dialog = dialog_type.return_value
                dialog.exec.return_value = QDialog.Accepted
                dialog.selected_marnian_synth_mode.return_value = "basic"
                dialog.selected_track_settings.return_value = (
                    41, 21, 42, 23, 43, 24, 25, 26
                )
                dialog.changed_send_indices.return_value = (0, 2, 4)
                window._show_effects_placeholder(track)

            assert track.bdo_track_settings == (
                41, 21, 42, 23, 43, 24, 25, 26
            )
            assert dirty_calls == [True]
            assert preview_calls == [True]
            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_track_fx_commit_patches_only_dirty_aux_on_same_instrument(self) -> None:
        self._run_offscreen(
            """
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QDialog

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            source = TrackState(
                1, [], 0, False, "source", 0x0B,
                bdo_track_settings=(10, 11, 20, 13, 30, 15, 16, 17),
            )
            peer = TrackState(
                2, [], 0, False, "peer", 0x0B,
                bdo_track_settings=(10, 91, 20, 93, 30, 95, 96, 97),
            )
            other = TrackState(
                3, [], 0, False, "other", 0x0C,
                bdo_track_settings=(40, 41, 42, 43, 44, 45, 46, 47),
            )
            window.tracks = [source, peer, other]
            window._on_preview_mapping_changed = lambda: None
            window._autosave_project = lambda *args, **kwargs: None

            with patch("bdo_music_composer.ui.main_window.TrackFxDialog") as dialog_type:
                dialog = dialog_type.return_value
                dialog.exec.return_value = QDialog.Accepted
                dialog.selected_marnian_synth_mode.return_value = "basic"
                dialog.selected_track_settings.return_value = (
                    10, 11, 44, 13, 30, 15, 16, 17
                )
                dialog.changed_send_indices.return_value = (2,)
                window._show_effects_placeholder(source)

            assert source.bdo_track_settings == (
                10, 11, 44, 13, 30, 15, 16, 17
            )
            assert peer.bdo_track_settings == (
                10, 91, 44, 93, 30, 95, 96, 97
            )
            assert other.bdo_track_settings == (
                40, 41, 42, 43, 44, 45, 46, 47
            )

            window._undo_project()
            assert window.tracks[0].bdo_track_settings == (
                10, 11, 20, 13, 30, 15, 16, 17
            )
            assert window.tracks[1].bdo_track_settings == (
                10, 91, 20, 93, 30, 95, 96, 97
            )
            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_master_effects_dialog_preserves_unedited_raw_values(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QSpinBox

            from bdo_common.bdo_track_effects import MasterEffects
            from bdo_music_composer.ui.main_window import (
                MasterEffectsDialog,
                MidiToBdoWindow,
                SettingsDialog,
            )

            app = QApplication([])
            window = MidiToBdoWindow()
            settings = SettingsDialog(window)
            assert settings.findChild(QSpinBox, "MasterReverbTime") is None
            assert settings.findChild(QSpinBox, "MasterDelayFeedback") is None
            settings.close()

            original = MasterEffects(201, 202, 203, 204, 205)
            dialog = MasterEffectsDialog(window, original)
            fields = (
                dialog.reverb,
                dialog.delay,
                dialog.chorus_feedback,
                dialog.chorus_depth,
                dialog.chorus_freq,
            )
            for field in fields:
                assert (field.minimum(), field.maximum()) == (0, 100)
                assert field.value() == 100
                assert "导入原值" in field.toolTip()
            assert "0.2–8.0 秒" in dialog.reverb.toolTip()
            assert "250 ms" in dialog.delay.toolTip()
            assert "梳状与旋动感" in dialog.chorus_feedback.toolTip()
            assert "摆动幅度" in dialog.chorus_depth.toolTip()
            assert "起伏速度" in dialog.chorus_freq.toolTip()

            # The visible authoring cap must not mutate legacy/imported bytes
            # just because the settings window was opened.
            assert dialog.selected_master_effects() == MasterEffects(
                201, 202, 203, 204, 205
            )

            # Editing one master parameter changes only that parameter.
            dialog.chorus_depth.setValue(42)
            assert dialog.selected_master_effects() == MasterEffects(
                201, 202, 203, 42, 205
            )

            dialog.reverb.setValue(1)
            dialog.delay.setValue(2)
            dialog.chorus_feedback.setValue(3)
            dialog.chorus_depth.setValue(4)
            dialog.chorus_freq.setValue(5)
            assert dialog.selected_master_effects() == MasterEffects(
                1, 2, 3, 4, 5
            )
            dialog.close()
            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_master_effect_commit_is_undoable_and_does_not_touch_track_sends(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_common.bdo_track_effects import MasterEffects
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            raw = (11, 21, 22, 23, 33, 24, 25, 26)
            window.tracks = [
                TrackState(
                    1,
                    [],
                    0,
                    False,
                    "isolated-fx",
                    0x0B,
                    bdo_track_settings=raw,
                )
            ]
            window.source_format = "project"
            window.reverb = 21
            window.delay = 23
            window.chorus = (24, 25, 26)
            preview_restarts = []
            autosaves = []
            window._restart_preview_after_timeline_change = (
                lambda: preview_restarts.append(True)
            )
            window._autosave_project = (
                lambda reason, immediate=False: autosaves.append(
                    (reason, immediate)
                )
            )

            selected = MasterEffects(1, 2, 3, 4, 5)
            assert window._apply_master_effects(selected)
            assert (window.reverb, window.delay, window.chorus) == (
                1, 2, (3, 4, 5)
            )
            assert window.tracks[0].bdo_track_settings == raw
            assert preview_restarts == [True]
            assert autosaves == [("master effects", False)]

            # Re-applying the same values is a no-op and creates no command.
            assert not window._apply_master_effects(selected)
            assert preview_restarts == [True]
            assert autosaves == [("master effects", False)]

            window._undo_project()
            assert (window.reverb, window.delay, window.chorus) == (
                21, 23, (24, 25, 26)
            )
            assert window.tracks[0].bdo_track_settings == raw
            assert autosaves[-1] == ("project undo", True)
            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_project_effect_defaults_do_not_leak_between_source_types(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_common.bdo_track_effects import MasterEffects
            from bdo_music_composer.ui.main_window import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            window.reverb = 91
            window.delay = 92
            window.chorus = (93, 94, 95)

            # Old MIDI/blank projects with no FX keys start neutral instead
            # of inheriting the previously open score.
            window._apply_conversion_settings(
                {"char_name": "legacy-midi"},
                default_master=MasterEffects(),
            )
            assert (window.reverb, window.delay, window.chorus) == (0, 0, None)

            # A legacy BDO-backed project keeps values read from its score
            # when its project metadata predates explicit master fields.
            imported = MasterEffects(11, 12, 13, 14, 15)
            window._apply_conversion_settings(
                {},
                default_master=imported,
            )
            assert (window.reverb, window.delay, window.chorus) == (
                11, 12, (13, 14, 15)
            )
            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_build_params_preserves_track_sends_and_broadcasts_master(self) -> None:
        self._run_offscreen(
            """
            import tempfile

            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            window = MidiToBdoWindow()
            first_raw = (11, 201, 22, 202, 33, 203, 204, 205)
            second_raw = (44, 91, 55, 92, 66, 93, 94, 95)
            first = TrackState(
                1,
                [Note(60, 90, 0.0, 200.0, 0)],
                0,
                False,
                "first",
                0x0B,
                bdo_track_settings=first_raw,
            )
            second = TrackState(
                2,
                [Note(64, 90, 200.0, 200.0, 0)],
                0,
                False,
                "second",
                0x0C,
                bdo_track_settings=second_raw,
            )
            window.tracks = [first, second]
            window.source_format = "project"
            window.owner_id = 1
            window.reverb = 9
            window.delay = 8
            window.chorus = (7, 6, 5)
            with tempfile.TemporaryDirectory() as folder:
                window.output_dir_path = folder
                window.output_name.setText("effects-test")
                params = window._build_params()

            assert params["track_settings_map"] == {
                0: (11, 9, 22, 8, 33, 7, 6, 5),
                1: (44, 9, 55, 8, 66, 7, 6, 5),
            }
            # Building export parameters is a projection, not an editor write.
            assert first.bdo_track_settings == first_raw
            assert second.bdo_track_settings == second_raw
            window.close()
            app.processEvents()
            app.quit()
            """
        )

    def test_realtime_routes_track_aux_sends_to_approximate_preview(self) -> None:
        self._run_offscreen(
            """
            import json
            import tempfile
            from pathlib import Path
            from types import SimpleNamespace

            import numpy as np
            from PySide6.QtCore import QCoreApplication

            from bdo_music_composer.audio.bdo_realtime_audio import BdoRealtimeAudioEngine, _Sample

            app = QCoreApplication([])
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                map_path = root / "map.json"
                bank = "midi_instrument_10_proguitar"
                map_path.write_text(
                    json.dumps({"banks": {bank: [{
                        "wav_exists": True,
                        "wav_path": str(root / "sample.wav"),
                        "source_id": 7,
                        "key_min": 0,
                        "key_max": 127,
                        "velocity_min": 0,
                        "velocity_max": 127,
                        "root_note": 60,
                    }]}}),
                    encoding="utf-8",
                )
                engine = BdoRealtimeAudioEngine(
                    None,
                    {"paz_root": "", "audio_root": str(root)},
                )
                engine._sample_rate = 48_000
                engine._cache[(bank, 7)] = _Sample(
                    np.ones((4_800, 2), dtype=np.float32),
                    48_000,
                    4_800,
                    4_800,
                )
                track = SimpleNamespace(
                    track_id=8,
                    bdo_instrument_id=0x0A,
                    marnian_synth_mode="basic",
                    bdo_track_volume=70,
                    bdo_track_settings=(25, 0, 0, 0, 0, 0, 0, 0),
                    volume_scale=1.0,
                    duration_scale=1.0,
                    articulation_type=None,
                    notes=[SimpleNamespace(
                        pitch=60,
                        vel=90,
                        start=0.0,
                        dur=100.0,
                        ntype=0,
                    )],
                )
                events, _cache, _bytes, unverified, duration = (
                    engine._prepare_project(
                        [track], map_path, 0, 0, 0, None, 1024 * 1024
                    )
                )
                assert len(events) == 1
                assert events[0].reverb_send == 0.25
                assert events[0].delay_send == 0.0
                assert events[0].chorus_send == 0.0
                assert (
                    "reverb/delay/chorus preview: bounded local approximation; "
                    "not calibrated against game Wwise DSP"
                ) in unverified
                committed = engine._commit_project(
                    events, _cache, _bytes, unverified, duration, start_ms=0
                )
                assert engine._preview_effects.reverb_enabled
                assert committed["duration_ms"] > duration * 1000 / 48_000
                engine.stop()
            app.quit()
            """
        )

    def test_beginner_instrument_aux_bytes_are_not_auditioned(self) -> None:
        self._run_offscreen(
            """
            from types import SimpleNamespace

            from PySide6.QtCore import QCoreApplication

            from bdo_music_composer.audio.bdo_realtime_audio import BdoRealtimeAudioEngine

            app = QCoreApplication([])
            engine = BdoRealtimeAudioEngine(
                None,
                {"paz_root": "", "audio_root": ""},
            )
            track = SimpleNamespace(
                track_id=1,
                bdo_instrument_id=0x00,
                bdo_track_volume=70,
                bdo_track_settings=(100, 0, 100, 0, 100, 0, 0, 0),
                duration_scale=1.0,
                articulation_type=None,
                notes=[SimpleNamespace(
                    pitch=60, vel=90, start=0.0, dur=100.0, ntype=0,
                )],
            )
            events, _cache, _bytes, _unverified, _duration = (
                engine._prepare_procedural_project([track], 0, 0, 0, None)
            )
            assert len(events) == 1
            assert events[0].reverb_send == 0.0
            assert events[0].delay_send == 0.0
            assert events[0].chorus_send == 0.0
            assert track.bdo_track_settings == (100, 0, 100, 0, 100, 0, 0, 0)
            engine.stop()
            app.quit()
            """
        )


if __name__ == "__main__":
    unittest.main()
