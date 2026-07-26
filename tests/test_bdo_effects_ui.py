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
            for field in (reverb, delay, chorus):
                assert (field.minimum(), field.maximum()) == (0, 100)
                assert field.value() == 100

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

    def test_settings_master_effects_preserve_unedited_raw_values(self) -> None:
        self._run_offscreen(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_track_effects import MasterEffects
            from pyside_bdo_gui import MidiToBdoWindow, SettingsDialog

            app = QApplication([])
            window = MidiToBdoWindow()
            window.reverb = 201
            window.delay = 202
            window.chorus = (203, 204, 205)
            dialog = SettingsDialog(window)
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

    def test_realtime_marks_track_aux_sends_as_unsimulated(self) -> None:
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
                _events, _cache, _bytes, unverified, _duration = (
                    engine._prepare_project(
                        [track], map_path, 0, 0, 0, None, 1024 * 1024
                    )
                )
                assert (
                    "per-track reverb/delay/chorus sends: exported; "
                    "local DSP not simulated"
                ) in unverified
                engine.stop()
            app.quit()
            """
        )


if __name__ == "__main__":
    unittest.main()
