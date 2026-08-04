from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceNoticesUiTests(unittest.TestCase):
    def test_source_identity_and_track_notices_are_actionable(self) -> None:
        script = textwrap.dedent(
            """
            from pathlib import Path
            import tempfile
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QMessageBox
            import bdo_music_composer.ui.main_window as gui
            from bdo_music_composer.ui.main_window import MidiToBdoWindow, Note, TrackState

            app = QApplication([])
            config_dir = tempfile.TemporaryDirectory()
            gui.CONFIG_PATH = Path(config_dir.name) / "config.json"
            window = MidiToBdoWindow()

            assert window.preview_source_badge.menu() is window.preview_source_menu
            assert set(window.preview_source_actions) == {"auto", "bdo", "generic"}
            assert window.preview_source_actions["auto"].isChecked()
            window._set_preview_source_mode("generic")
            assert window.audio_sources["preview_mode"] == "generic"
            assert window.preview_source_actions["generic"].isChecked()
            if window.realtime_audio.available():
                assert "MIDI" in window.preview_source_badge.text()
            else:
                assert window.preview_source_badge.text() == "无可用音频设备"

            window.char_name = "MIDI"
            window.owner_id = 0
            window._refresh_home_identity()
            logo = window.ensemble_capacity_badge
            assert not hasattr(window, "home_owner_id_button")
            assert logo.property("ownerIdMissing") is True
            assert "点击 Logo" in logo.toolTip()
            assert logo.size().width() == logo.size().height() == 36

            from unittest.mock import patch
            with (
                patch.object(
                    gui,
                    "prompt_for_owner_identity",
                    return_value=(456, "Hidden Shai"),
                ),
                patch.object(window, "_autosave_project") as autosave,
            ):
                logo.click()
            assert window.owner_id == 456
            assert window.char_name == "Hidden Shai"
            assert logo.property("ownerIdMissing") is False
            assert "Owner ID 已绑定" in logo.toolTip()
            assert "Hidden Shai" not in logo.toolTip()
            autosave.assert_called_once_with("owner id")
            saved_config = gui.load_config()
            assert saved_config["owner_identity"] == {
                "owner_id": 456,
                "character_name": "Hidden Shai",
            }

            # The local binding is used for a fresh session, while the
            # settings dialog offers an explicit, confirmed unlink operation.
            reloaded = MidiToBdoWindow()
            assert reloaded.owner_id == 456
            assert reloaded.char_name == "Hidden Shai"
            identity_dialog = gui.SettingsDialog(reloaded)
            assert identity_dialog.owner_clear_button.isEnabled()
            QMessageBox.question = lambda *_args, **_kwargs: QMessageBox.Yes
            identity_dialog._clear_owner_id()
            assert identity_dialog.owner_id == 0
            assert identity_dialog.owner_identity_changed
            assert not identity_dialog.owner_clear_button.isEnabled()
            identity_dialog.close()
            reloaded.close()
            app.processEvents()

            window.char_name = "Shai"
            window.owner_id = 123
            window._refresh_home_identity()
            assert logo.property("ownerIdMissing") is False
            assert "Shai" not in logo.toolTip()

            # Multi-track controls create a fresh lane and delete only the
            # selected lane after confirmation.
            window._create_new_project("Track lifecycle")
            initial_track = window.tracks[0]
            window._create_track(0x0B)
            created_track = window.tracks[-1]
            assert len(window.tracks) == 2
            assert created_track is not initial_track
            assert created_track.notes == []
            window._select_track(created_track)
            QMessageBox.question = lambda *_args, **_kwargs: QMessageBox.Yes
            window._delete_selected_track()
            assert window.tracks == [initial_track]

            # Reordering changes only the mixer-lane order. Stable IDs and
            # notes remain intact, and the selected lane stays selected.
            window._create_track(0x0B)
            middle_track = window.tracks[-1]
            window._create_track(0x0F)
            lower_track = window.tracks[-1]
            original_ids = [track.track_id for track in window.tracks]
            window._select_track(lower_track)
            window.timeline.move_track_requested.emit(lower_track, -1)
            assert window.tracks == [initial_track, lower_track, middle_track]
            assert [track.track_id for track in window.tracks] == [
                original_ids[0], original_ids[2], original_ids[1]
            ]
            assert window.selected_track is lower_track
            window.timeline.move_track_requested.emit(lower_track, 1)
            assert window.tracks == [initial_track, middle_track, lower_track]

            # The timeline's left-rail creation request is wired to the same
            # safe track factory as the toolbar menu.
            track_count = len(window.tracks)
            window.timeline.create_track_requested.emit(0x11)
            assert len(window.tracks) == track_count + 1
            assert window.tracks[-1].bdo_instrument_id == 0x11

            first = TrackState(
                1, [Note(60, 90, 0.0, 300.0, 0)], 0, False, "one", 0x0B
            )
            second = TrackState(
                2, [Note(64, 90, 400.0, 300.0, 0)], 0, False, "two", 0x0B
            )
            window.tracks = [first, second]
            window.timeline.set_tracks(window.tracks)
            toast_calls = []
            original_show_toast = window.show_toast
            def capture_toast(text, kind="info", duration_ms=2600):
                toast_calls.append((text, kind, duration_ms))
                return original_show_toast(text, kind, duration_ms)
            window.show_toast = capture_toast
            window._refresh_timeline_validation()
            assert not hasattr(window, "timeline_notice")
            assert len(toast_calls) == 1
            assert toast_calls[-1][1] == "warning"
            assert "琥珀色" in toast_calls[-1][0]
            first_signature = window._timeline_validation_toast_signature
            window._refresh_timeline_validation()
            assert len(toast_calls) == 1
            assert window._timeline_validation_toast_signature == first_signature
            for track_id in (1, 2):
                notice = window.timeline.track_validation_notices[track_id]
                assert not notice["errors"]
                assert notice["attentions"]
                assert "合并" in notice["attentions"][0]

            first.notes = [Note(1, 90, 0.0, 300.0, 0)]
            # Direct test mutation must cross the same explicit model-revision
            # boundary used by real editor commits.
            window._refresh_tracks()
            window._refresh_timeline_validation()
            assert len(toast_calls) == 2
            assert toast_calls[-1][1] == "error"
            assert "错误" in toast_calls[-1][0]
            assert window.timeline.track_validation_notices[1]["errors"]
            assert window.timeline.track_validation_notices[1]["attentions"]
            assert not window.timeline.track_validation_notices[2]["errors"]
            assert window.timeline.track_validation_notices[2]["attentions"]

            window.resize(1400, 900)
            window._show_workspace()
            window.show()
            app.processEvents()
            window.timeline.grab()
            badges = [
                (rect, action, track)
                for rect, action, track in window.timeline.hit_regions
                if action in {"validation_error", "validation_attention"}
            ]
            assert sum(action == "validation_error" for _, action, _ in badges) == 1
            assert sum(action == "validation_attention" for _, action, _ in badges) == 1
            assert all(
                track is not first
                for _rect, action, track in badges
                if action == "validation_attention"
            )

            window.timeline.validation_requested.disconnect(
                window._open_track_conversion_check
            )
            requests = []
            window.timeline.validation_requested.connect(requests.append)
            error_rect = next(
                rect for rect, action, _track in badges
                if action == "validation_error"
            )
            QTest.mouseMove(window.timeline, error_rect.center().toPoint())
            assert "导出错误" in window.timeline.toolTip()
            QTest.mouseClick(
                window.timeline,
                Qt.LeftButton,
                pos=error_rect.center().toPoint(),
            )
            assert requests and requests[0][0] is first
            assert requests[0][1] == "error"

            window.close()
            app.processEvents()
            config_dir.cleanup()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        with tempfile.TemporaryDirectory() as user_data_dir:
            env["BDO_USER_DATA_DIR"] = user_data_dir
            completed = subprocess.run(
                [sys.executable, "-c", script],
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


if __name__ == "__main__":
    unittest.main()
