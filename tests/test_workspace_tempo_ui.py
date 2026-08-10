from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceTempoUiTests(unittest.TestCase):
    def test_global_bpm_drives_workspace_autosave_sync_and_bdo_header(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox
            from bdo_codec import decode_score
            from bdo_music_composer.export.export_workflow import prepare_export
            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.ui.dialogs.application_settings_dialog import SettingsDialog
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            config_dir = tempfile.TemporaryDirectory()
            gui.CONFIG_PATH = Path(config_dir.name) / "config.json"
            window = MidiToBdoWindow()
            window.show()
            window._show_workspace()
            app.processEvents()

            assert window.global_bpm_label.text() == "BPM"
            assert window.global_bpm_label.accessibleName() == "全局 BPM"
            assert window.global_bpm_spin.minimum() == 1
            assert window.global_bpm_spin.maximum() == 200
            assert window.global_bpm_spin.value() == 120
            assert window.global_bpm_spin.width() == 84
            bpm_option = QStyleOptionSpinBox()
            window.global_bpm_spin.initStyleOption(bpm_option)
            bpm_edit_rect = window.global_bpm_spin.style().subControlRect(
                QStyle.CC_SpinBox,
                bpm_option,
                QStyle.SC_SpinBoxEditField,
                window.global_bpm_spin,
            )
            assert bpm_edit_rect.width() >= (
                window.global_bpm_spin.fontMetrics().horizontalAdvance("200") + 14
            )
            assert window.global_bpm_control.width() >= 188
            assert (
                window.global_bpm_spin.geometry().right()
                < window.reference_bpm_follow.geometry().left()
            )
            assert (
                window.reference_bpm_follow.geometry().right()
                <= window.global_bpm_control.contentsRect().right()
            )
            window.resize(1900, 900)
            app.processEvents()
            assert window.reference_bpm_follow.text() == "自动跟随"
            assert (
                window.global_bpm_spin.geometry().right()
                < window.reference_bpm_follow.geometry().left()
            )
            assert (
                window.reference_bpm_follow.geometry().right()
                <= window.global_bpm_control.contentsRect().right()
            )
            assert window.toolbar_multiplayer_sync_btn.accessibleName()
            assert not window.toolbar_multiplayer_sync_btn.isEnabled()
            assert "暂未开放" in window.toolbar_multiplayer_sync_btn.toolTip()
            assert window.reference_bpm_follow.isChecked()
            assert not window.reference_bpm_follow.isEnabled()

            window.tracks = [
                TrackState(1, [Note(60, 90, 0.0, 300.0, 0)], 0, False, "one", 0x0B)
            ]
            window.timeline.set_tracks(window.tracks)
            window.owner_id = 123
            window.char_name = "Tempo Test"
            window.output_name.setText("tempo-test")
            window.output_dir_path = config_dir.name
            window.game_music_dir_path = config_dir.name
            window.global_bpm_spin.setValue(156)

            with (
                patch.object(window, "_autosave_project") as autosave,
                patch.object(window, "_stop_preview") as stop_preview,
                patch.object(window, "show_toast") as show_toast,
            ):
                window._commit_global_bpm_from_control()

            assert window.bpm == 120
            assert window.bpm_override == 156
            assert window.timeline.bpm == 156
            assert window.global_bpm_spin.value() == 156
            assert window.timeline_meta.text() == "1 轨 · 4/4"
            stop_preview.assert_called_once_with(reset_playhead=False)
            autosave.assert_called_once_with("global bpm", immediate=True)
            assert show_toast.call_args.kwargs["kind"] == "success"

            request = window._build_params()
            document = decode_score(prepare_export(request).data)
            assert request.bpm == 120
            assert request.conversion.bpm_override == 156
            assert document.header.bpm == 156

            # Reliable cached onset evidence becomes the default project BPM.
            from types import SimpleNamespace
            window.reference_layer_settings["follow_reference_bpm"] = True
            window._reference_bpm_follow_pending = True
            estimate = SimpleNamespace(
                used_project_fallback=False,
                confidence=0.82,
                beat_count=32,
                tempo_drift_ratio=0.04,
                detected_bpm=98.4,
            )
            sidecar = SimpleNamespace(
                alignment=SimpleNamespace(estimate=estimate)
            )
            with (
                patch.object(window, "_autosave_project") as follow_autosave,
                patch.object(window, "_stop_preview"),
                patch.object(window, "show_toast"),
            ):
                assert window._consume_reference_bpm_follow_result(sidecar)
            assert window.bpm_override == 98
            assert window.timeline.bpm == 98
            follow_autosave.assert_called_once_with(
                "reference bpm follow", immediate=True
            )

            advanced = SettingsDialog(window)
            assert advanced.bpm_override.minimum() == 0
            assert advanced.bpm_override.maximum() == 200
            advanced.close()
            window.close()
            app.processEvents()
            config_dir.cleanup()
            """
        )
        self._run_offscreen(script)

    def test_multiplayer_panel_follows_global_bpm_without_own_tempo(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication
            from bdo_music_composer.ui.dialogs.multiplayer_sync_dialog import (
                MultiplayerSyncDialog,
            )

            app = QApplication([])
            dialog = MultiplayerSyncDialog(None, global_bpm=150, meter=4)
            dialog.show()
            app.processEvents()
            assert dialog.tempo_value.text() == "150 BPM · 4/4"
            assert dialog.beijing_time.text()
            assert dialog.width() >= 760
            assert dialog.height() >= 640
            assert dialog.connection_card.width() > 650
            assert dialog.protocol_card.width() > 650
            assert dialog.ip_address.text() == "127.0.0.1"
            assert dialog.ip_address.width() >= 360
            assert dialog.port.value() == 31307
            assert dialog.pin.maxLength() == 6
            assert dialog.countdown_seconds.value() == 10.0
            assert not dialog.create_button.isEnabled()
            assert not dialog.join_button.isEnabled()
            assert dialog.member_list.count() == 3

            dialog.room_role.setCurrentIndex(1)
            dialog.ip_address.setText("192.0.2.8")
            dialog.port.setValue(42000)
            dialog.pin.setText("123456")
            dialog.countdown_seconds.setValue(12.5)
            draft = dialog.room_draft()
            assert draft.role == "guest"
            assert draft.address == "192.0.2.8"
            assert draft.port == 42000
            assert draft.pin == "123456"
            assert draft.countdown_seconds == 12.5
            assert draft.global_bpm == 150
            assert draft.valid_endpoint
            dialog.close()
            app.processEvents()

            from bdo_music_composer.ui.i18n import install_localizer
            localizer = install_localizer(app, "en_US")
            for language in ("en_US", "ja_JP", "ko_KR", "zh_TW"):
                localizer.set_language(language)
                localized = MultiplayerSyncDialog(None, global_bpm=150, meter=4)
                localized.show()
                app.processEvents()
                assert localized.connection_card.width() > 650
                assert localized.ip_address.width() >= 360
                assert localized.network_quality.sizeHint().width() <= localized.protocol_card.width()
                localized.close()
                app.processEvents()
            """
        )
        self._run_offscreen(script)

    def test_latest_reference_audio_is_analyzed_after_cancelled_worker_exits(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.ui.main_window import MidiToBdoWindow

            class FakeWorker:
                def __init__(self):
                    self.cancelled = False

                def cancel(self):
                    self.cancelled = True

            app = QApplication([])
            config_dir = tempfile.TemporaryDirectory()
            gui.CONFIG_PATH = Path(config_dir.name) / "config.json"
            window = MidiToBdoWindow()
            old_worker = FakeWorker()
            window.reference_tempo_worker = old_worker
            window.reference_audio_path = "new-reference.wav"

            window._reference_bpm_audio_changed(window.reference_audio_path)
            assert old_worker.cancelled
            assert window._pending_reference_tempo_path == "new-reference.wav"

            with patch.object(window, "_start_reference_tempo_analysis") as start:
                window._reference_tempo_finished(old_worker)
                app.processEvents()
            start.assert_called_once_with("new-reference.wav")

            window.reference_tempo_worker = None
            window.close()
            app.processEvents()
            config_dir.cleanup()
            """
        )
        self._run_offscreen(script)

    def _run_offscreen(self, script: str) -> None:
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
