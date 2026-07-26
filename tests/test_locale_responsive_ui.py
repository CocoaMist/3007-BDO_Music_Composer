from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocaleResponsiveUiTests(unittest.TestCase):
    def test_supported_locales_fit_and_preserve_dynamic_music_text(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication, QFrame, QLabel, QListWidget

            from i18n import install_localizer, tr, trf
            from pyside_bdo_gui import (
                MidiNoteEditorDialog,
                MidiToBdoWindow,
                Note,
                SettingsDialog,
                TrackState,
            )

            app = QApplication([])
            translations = install_localizer(app, "zh_CN")
            window = MidiToBdoWindow()
            window.resize(1160, 720)
            window._show_workspace()
            window.show()

            # These values intentionally collide with English UI source words.
            # File, project and track data must remain opaque to the localizer.
            window.file_label.setProperty("i18nSkipText", True)
            window.file_label.setProperty("i18nSkip", True)
            window.file_label.setText("Open")
            home_list = window.findChild(QListWidget, "HomeList")
            assert home_list is not None
            home_list.clear()
            home_list.addItem("Play")

            track = TrackState(
                1,
                [Note(60, 96, 0, 400, 0)],
                0,
                False,
                "Play",
                0x0B,
            )
            window.tracks = [track]
            window._on_track_changed()
            editor = MidiNoteEditorDialog(window, track, 120, 4)
            window.active_transcription_editor = editor
            editor.resize(920, 680)
            editor.show()
            editor.transcription_panel.set_copy_targets([(2, "Play")])
            settings = SettingsDialog(window)
            settings.resize(760, 680)
            settings.show()
            app.processEvents()

            translations.set_language("en_US")
            window._set_transcription_status(
                tr("载入参考音频后可开始整首分析")
            )
            cached_statuses = {
                "zh_CN": "载入参考音频后可开始整首分析",
                "en_US": "Load reference audio to analyze the full song",
                "ja_JP": "参照オーディオを読み込むと全曲解析を開始できます",
                "ko_KR": "참조 오디오를 불러오면 전체 곡 분석을 시작할 수 있습니다",
            }

            toolbar = window.findChild(QFrame, "Toolbar")
            timeline_bar = window.findChild(QFrame, "TimelineControlBar")
            editor_toolbar = editor.findChild(QFrame, "EditorToolbar")
            inspector = editor.findChild(QFrame, "NoteInspectorTop")
            subtitle = settings.settings_subtitle
            assert all(
                item is not None
                for item in (
                    toolbar,
                    timeline_bar,
                    editor_toolbar,
                    inspector,
                    subtitle,
                )
            )
            assert subtitle.wordWrap()
            assert settings.settings_nav.property("i18nTranslateItems") is True
            assert (
                editor.transcription_panel.assist_panel.harmony_summary.segment_combo.property(
                    "i18nSkipItems"
                )
                is True
            )

            for language in ("zh_CN", "en_US", "ja_JP", "ko_KR"):
                translations.set_language(language)
                window.resize(1160, 720)
                window._apply_responsive_density()
                editor.resize(920, 680)
                # Re-run density after the locale event to exercise every
                # translated label against the supported minimum width.
                editor._editor_controls_compact = None
                editor._apply_editor_responsive_density()
                app.processEvents()
                window._refresh_transcription_workspace()
                editor.transcription_panel.set_copy_targets([(2, "Play")])
                assert (
                    editor.transcription_panel.status_label.text()
                    == cached_statuses[language]
                )

                assert toolbar.minimumSizeHint().width() <= window.width()
                assert timeline_bar.minimumSizeHint().width() <= window.width()
                assert editor.minimumSizeHint().width() <= editor.width()
                assert editor_toolbar.minimumSizeHint().width() <= editor.width()
                assert inspector.minimumSizeHint().width() <= editor.width()
                assert window.file_label.text() == "Open"
                assert window.file_label.toolTip() == "Open"
                assert window.timeline_meta.text() == trf(
                    "{count} 轨 · BPM {bpm} · {meter}/4",
                    count=1,
                    bpm=window.bpm_override or window.bpm,
                    meter=window.time_sig,
                )
                assert home_list.item(0).text() == "Play"
                assert "Play" in editor.windowTitle()
                assert editor.findChild(QLabel, "EditorTrackTitle").text() == "Play"
                assert (
                    editor.transcription_panel.copy_to_track_menu.actions()[0].text()
                    == "Play"
                )

                for button in (
                    window.toolbar_home_btn,
                    window.pause_button,
                    editor.draft_play_button,
                    editor.cancel_button,
                    editor.note_mode_button,
                ):
                    assert button.toolTip()
                    assert button.accessibleName()
                assert editor.music_volume_slider.accessibleName()
                assert editor.ghost_opacity_slider.accessibleName()

                # Mid-sized windows must not switch back to verbose rails
                # before the complete translated row actually fits.
                window.resize(1500, 720)
                window._apply_responsive_density()
                editor.resize(1400, 680)
                editor._editor_controls_compact = None
                editor._apply_editor_responsive_density()
                app.processEvents()
                assert window.minimumSizeHint().width() <= window.width()
                assert editor.minimumSizeHint().width() <= editor.width()

            editor._set_draft_playback_state("paused")
            assert editor.draft_play_button.text() == ""
            assert editor.draft_play_button.toolTip()
            assert all(not label.isVisible() for label in editor.note_field_labels)

            settings.close()
            editor.close()
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
            timeout=40,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
