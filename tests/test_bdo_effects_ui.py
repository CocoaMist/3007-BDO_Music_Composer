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

            from pyside_bdo_gui import TrackFxDialog, TrackState

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

    def test_every_instrument_row_exposes_the_track_fx_editor(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from pyside_bdo_gui import TimelineCanvas, TrackState

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

    def test_track_fx_commit_marks_conversion_check_dirty(self) -> None:
        self._run_offscreen(
            """
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QDialog

            from pyside_bdo_gui import MidiToBdoWindow, TrackState

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

            with patch("pyside_bdo_gui.TrackFxDialog") as dialog_type:
                dialog = dialog_type.return_value
                dialog.exec.return_value = QDialog.Accepted
                dialog.selected_marnian_synth_mode.return_value = "basic"
                dialog.selected_track_settings.return_value = (
                    41, 21, 42, 23, 43, 24, 25, 26
                )
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

    def test_master_effects_dialog_preserves_unedited_raw_values(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication, QSpinBox

            from bdo_track_effects import MasterEffects
            from pyside_bdo_gui import (
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

            from bdo_track_effects import MasterEffects
            from pyside_bdo_gui import MidiToBdoWindow, TrackState

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

            from bdo_track_effects import MasterEffects
            from pyside_bdo_gui import MidiToBdoWindow

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

            from pyside_bdo_gui import MidiToBdoWindow, Note, TrackState

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

            from bdo_realtime_audio import BdoRealtimeAudioEngine, _Sample

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


if __name__ == "__main__":
    unittest.main()
