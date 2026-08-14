from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(script: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class UiAccessibilityAndDisclosureTests(unittest.TestCase):
    def test_timeline_has_keyboard_equivalents_and_accessible_state(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.main_window import Note, TimelineCanvas, TrackState

            app = QApplication([])
            localizer = install_localizer(app, "zh_CN")
            canvas = TimelineCanvas()
            tracks = [
                TrackState(
                    index,
                    [Note(60, 90, 0.0, 100.0, 0)],
                    0,
                    False,
                    f"track-{index}",
                    0x0B,
                )
                for index in range(20)
            ]
            canvas.resize(1000, 420)
            canvas.set_tracks(tracks)
            canvas.show()
            canvas.setFocus()
            app.processEvents()

            assert canvas.focusPolicy() == Qt.StrongFocus
            assert canvas.accessibleName() == "轨道时间轴"
            assert "方向键导航" in canvas.accessibleDescription()
            assert "Enter" in canvas.toolTip()

            selected = []
            state_changes = []
            volume_changes = []
            effects = []
            editors = []
            canvas.selected.connect(lambda track: selected.append(track.track_id))
            canvas.track_state_changed.connect(
                lambda: state_changes.append(True)
            )
            canvas.game_volume_committed.connect(
                lambda track, previous, current: volume_changes.append(
                    (track.track_id, previous, current)
                )
            )
            canvas.effects_requested.connect(
                lambda track: effects.append(track.track_id)
            )
            canvas.note_editor_requested.connect(
                lambda track: editors.append(track.track_id)
            )

            QTest.keyClick(canvas, Qt.Key_Down)
            QTest.keyClick(canvas, Qt.Key_Down)
            assert canvas.selected_track is tracks[1]
            assert selected[-2:] == [0, 1]
            assert "track-1" in canvas.accessibleDescription()

            QTest.keyClick(canvas, Qt.Key_M)
            QTest.keyClick(canvas, Qt.Key_S)
            assert tracks[1].muted and tracks[1].solo
            assert len(state_changes) == 2
            QTest.keyClick(canvas, Qt.Key_F)
            QTest.keyClick(canvas, Qt.Key_Return)
            assert effects == [1]
            assert editors == [1]

            QTest.keyClick(canvas, Qt.Key_Right, Qt.AltModifier)
            QTest.keyClick(
                canvas, Qt.Key_Right,
                Qt.AltModifier | Qt.ShiftModifier,
            )
            assert tracks[1].bdo_track_volume == 76
            QTest.keyClick(
                canvas, Qt.Key_Left,
                Qt.AltModifier | Qt.ShiftModifier,
            )
            assert tracks[1].bdo_track_volume == 71
            assert len(state_changes) == 2
            assert volume_changes == [
                (1, 70, 71),
                (1, 71, 76),
                (1, 76, 71),
            ]
            assert "音量 71" in canvas.accessibleDescription()

            QTest.keyClick(canvas, Qt.Key_End)
            assert canvas.selected_track is tracks[-1]
            assert canvas.track_scroll.value() > 0
            QTest.keyClick(canvas, Qt.Key_Home)
            assert canvas.selected_track is tracks[0]
            assert canvas.track_scroll.value() == 0

            localizer.set_language("en_US")
            app.processEvents()
            assert canvas.accessibleName() == "Track timeline"
            assert "arrows navigate" in canvas.accessibleDescription()
            assert "track-0" in canvas.accessibleDescription()

            canvas.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_transcription_practical_surface_removes_expert_disclosure(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication, QWidget

            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.transcription.transcription_editor_qt import TranscriptionEditorPanel

            app = QApplication([])
            localizer = install_localizer(app, "zh_CN")
            panel = TranscriptionEditorPanel()
            panel.resize(920, panel.sizeHint().height())
            panel.show()
            app.processEvents()

            assert panel.workspace_title_label.text() == "音频扒谱"
            assert panel.audio_button.accessibleName()
            assert panel.analyze_button.accessibleName() == "分析"
            assert not panel.advanced_toggle_button.isVisible()
            assert not panel.advanced_panel.isVisible()
            assert not panel.redecode_button.isVisible()
            assert not hasattr(panel, "assist_toggle_button")
            assert not panel.review_tools_toggle_button.isVisible()
            assert not hasattr(panel, "assist_panel")

            panel.set_audio_loaded(True, display_name="reference.wav")
            panel.set_range_available(True)
            panel.set_assist_available(True)
            panel.set_advanced_controls_expanded(True)
            app.processEvents()
            assert panel.audio_button.isVisible()
            assert panel.remove_audio_button.isVisible()
            assert panel.analyze_button.isVisible()
            assert not panel.advanced_controls_expanded
            assert not panel.redecode_button.isVisible()
            assert not hasattr(panel, "assist_toggle_button")

            visible_widgets = [
                widget
                for widget in panel.findChildren(QWidget)
                if widget.isVisible()
            ]
            focusable_widgets = [
                widget
                for widget in visible_widgets
                if widget.focusPolicy() != Qt.NoFocus
            ]
            assert len(visible_widgets) <= 24, len(visible_widgets)
            assert len(focusable_widgets) <= 16, len(focusable_widgets)

            localizer.set_language("en_US")
            app.processEvents()
            assert panel.workspace_title_label.text() == "Audio Transcription"
            assert panel.analyze_button.text() == "Analyze"

            panel.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def _obsolete_test_transcription_advanced_controls_are_progressively_disclosed(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication, QWidget

            from bdo_music_composer.ui.i18n import install_localizer
            from bdo_music_composer.ui.transcription.transcription_editor_qt import TranscriptionEditorPanel

            app = QApplication([])
            localizer = install_localizer(app, "zh_CN")
            panel = TranscriptionEditorPanel()
            panel.resize(920, panel.sizeHint().height())
            panel.show()
            app.processEvents()

            advanced = (
                panel.analysis_mode_combo,
                panel.sensitivity_combo,
                panel.cleanup_profile_group,
            )
            assert not panel.advanced_controls_expanded
            assert panel.advanced_toggle_button.isVisible()
            assert panel.advanced_toggle_button.text() == "高级"
            assert all(not widget.isVisible() for widget in advanced)
            assert panel.audio_button.isVisible()
            assert panel.analyze_button.isVisible()
            assert not panel.redecode_button.isVisible()
            assert panel.workspace_title_label.isVisible()
            assert not panel.review_context_label.isVisible()
            assert not panel.advanced_panel.isVisible()
            assert not panel.guide_tools_bar.isVisible()
            assert not panel.review_more_bar.isVisible()
            assert not panel.melody_lines_button.isVisible()
            assert not panel.diagnostic_toggle_button.isVisible()
            assert not panel.show_rejected_checkbox.isVisible()
            assert not panel.show_suppressed_checkbox.isVisible()
            assert not panel.write_current_track_button.isVisible()

            visible_widgets = [
                widget
                for widget in panel.findChildren(QWidget)
                if widget.isVisible()
            ]
            focusable_widgets = [
                widget
                for widget in visible_widgets
                if widget.focusPolicy() != Qt.NoFocus
            ]
            assert len(visible_widgets) <= 22, len(visible_widgets)
            assert len(focusable_widgets) <= 16, len(focusable_widgets)

            states = []
            panel.advanced_controls_expanded_changed.connect(states.append)
            panel.advanced_toggle_button.click()
            app.processEvents()
            assert panel.advanced_controls_expanded
            assert all(widget.isVisible() for widget in advanced)
            assert not panel.guide_tools_bar.isVisible()
            assert not panel.candidate_tools_bar.isVisible()
            assert not panel.alignment_tools_bar.isVisible()
            # Candidate tuning lives behind the clearly labelled arrow rather
            # than consuming another permanent command row.
            assert not panel.confidence_slider.isVisible()
            assert not panel.candidate_opacity_slider.isVisible()
            assert not panel.show_rejected_checkbox.isVisible()
            assert not panel.show_suppressed_checkbox.isVisible()
            assert panel.advanced_panel.isVisible()
            assert not panel.review_more_bar.isVisible()
            assert states == [True]

            panel.set_audio_loaded(True, display_name="reference.wav")
            assert panel.guide_tools_bar.isVisible()
            assert panel.alignment_tools_bar.isVisible()
            assert panel.melody_lines_button.isVisible()
            assert panel.diagnostic_toggle_button.isVisible()
            panel.set_range_available(True)
            assert panel.redecode_button.isVisible()
            panel.set_action_state(
                write_enabled=True,
                reject_enabled=True,
                can_undo=True,
                candidate_count=3,
            )
            assert panel.candidate_tools_bar.isVisible()
            assert panel.review_context_label.isVisible()
            assert panel.write_current_track_button.isVisible()
            assert panel.reject_button.isVisible()
            assert panel.review_tools_toggle_button.isVisible()
            panel.review_tools_toggle_button.click()
            assert panel.review_tools_expanded
            assert panel.review_more_bar.isVisible()
            panel.review_tools_toggle_button.click()
            assert not panel.review_more_bar.isVisible()

            panel.diagnostic_toggle_button.click()
            assert panel.frame_checkbox.isVisible()
            assert panel.onset_checkbox.isVisible()
            assert panel.contour_checkbox.isVisible()
            assert panel.spectrogram_checkbox.isVisible()
            panel.advanced_toggle_button.click()
            assert not panel.advanced_controls_expanded
            assert all(not widget.isVisible() for widget in advanced)
            assert not panel.frame_checkbox.isVisible()
            assert states == [True, False]

            localizer.set_language("en_US")
            app.processEvents()
            assert panel.advanced_toggle_button.text() == "Advanced"
            assert (
                panel.advanced_toggle_button.accessibleName()
                == "Advanced transcription options"
            )

            panel.close()
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
