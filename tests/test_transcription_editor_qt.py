from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _run_offscreen(
    script: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TranscriptionEditorQtTests(unittest.TestCase):
    def test_waveform_lane_uses_editor_geometry_and_visible_index(self) -> None:
        completed = _run_offscreen(
            """
            from PySide6.QtCore import QObject, Signal, QPoint, Qt
            from PySide6.QtGui import QImage, QPainter
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QWidget

            from transcription_editor_qt import TranscriptionWaveformLane

            class Canvas(QWidget):
                KEY_W = 86

                def __init__(self):
                    super().__init__()
                    self.scroll_ms = 1_000.0
                    self.px_per_ms = 0.1
                    self.playhead_ms = 1_500.0

            class Reference(QObject):
                changed = Signal()
                timeline_changed = Signal()
                file_changed = Signal(str)
                offset_changed = Signal(float)

                def __init__(self):
                    super().__init__()
                    self.audio_path = "reference.wav"
                    self.display_name = "reference.wav"
                    self.waveform_loading = False
                    self.waveform = [
                        (index * 50.0, (index + 1) * 50.0, 0.5)
                        for index in range(200)
                    ]
                    self.waveform_starts = [item[0] for item in self.waveform]

                def project_to_audio(self, project_ms):
                    return float(project_ms) - 500.0

                def audio_to_project(self, audio_ms):
                    return float(audio_ms) + 500.0

            app = QApplication([])
            canvas = Canvas()
            lane = TranscriptionWaveformLane(canvas)
            lane.resize(486, lane.HEIGHT)
            reference = Reference()
            lane.set_reference_audio(reference)
            lane.set_time_range((1_200.0, 2_000.0))
            lane.show()
            app.processEvents()

            assert lane.height() == 72
            # 400 pixels at 0.1 px/ms means the visible project interval is
            # 1,000..5,000 ms, or audio 500..4,500 ms after one offset.
            visible = lane._visible_waveform(1_000.0, 5_000.0)
            assert visible[0][0] <= 500.0
            assert visible[-1][0] <= 4_500.0
            assert len(visible) < len(reference.waveform)

            image = QImage(lane.size(), QImage.Format_ARGB32)
            image.fill(0)
            lane.render(image)
            assert not image.isNull()

            seeks = []
            lane.seek_requested.connect(seeks.append)
            QTest.mouseClick(lane, Qt.LeftButton, pos=QPoint(186, 30))
            assert seeks == [2_000.0]

            lane.release_reference_audio()
            assert lane.reference_audio is None
            lane.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_panel_exposes_actions_without_owning_session_or_worker(self) -> None:
        completed = _run_offscreen(
            """
            from types import SimpleNamespace

            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication

            from transcription_editor_qt import TranscriptionEditorPanel

            app = QApplication([])
            panel = TranscriptionEditorPanel()
            panel.resize(920, panel.sizeHint().height())
            panel.show()
            app.processEvents()

            assert not hasattr(panel, "session")
            assert not hasattr(panel, "worker")
            assert panel.analysis_mode == "standard"
            assert panel.sensitivity == "balanced"
            assert panel.cleanup_profile == "preserve"
            assert panel.analyze_button.text() == "全曲"
            assert panel.analyze_button.property("kind") == "primary"
            assert panel.redecode_button.text() == "A–B"
            assert panel.diagnostic_toggle_button.text() == "证据"
            assert panel.cleanup_profile_caption.text() == "碎音"
            assert panel.cleanup_profile_mark.text() == "◇"
            assert panel.cleanup_profile_combo.itemText(0) == "保留"
            assert panel.cleanup_profile_combo.itemText(1) == "平衡 β"
            assert panel.cleanup_profile_combo.itemText(2) == "干净 β"
            assert (
                panel.status_label.toolTip()
                == "载入参考音频后可开始整首分析"
            )
            assert "显式启用" in panel.cleanup_profile_combo.toolTip()
            assert "未通过留出集验证" in (
                panel.cleanup_profile_combo.itemData(
                    1,
                    Qt.ItemDataRole.ToolTipRole,
                )
            )
            assert panel.confidence_floor == 0.30
            assert panel.reference_background_opacity == 0.60
            assert panel.reference_opacity_caption.text() == "背景"
            assert panel.reference_opacity_label.text() == "60%"
            assert panel.visible_evidence_layers == frozenset()
            assert not panel.spectrogram_visible
            assert panel.spectrogram_checkbox.text() == "声谱"
            assert panel.spectrogram_checkbox.toolTip() == "原始声谱图（诊断）"
            assert not panel.spectrogram_checkbox.isVisible()
            assert not panel.spectrogram_checkbox.isEnabled()
            assert panel.melody_lines_visible
            assert panel.melody_lines_button.text() == "旋律线"
            assert panel.melody_lines_button.isVisible()
            assert not panel.melody_lines_button.isEnabled()
            assert panel.melody_lines_button.toolTip() == "分析后显示旋律线"
            assert panel.melody_line_roles == frozenset(
                {"primary_melody", "bass", "harmony"}
            )
            assert [
                action.text() for action in panel.melody_line_menu.actions()
            ] == ["主旋律", "低音", "和声/和弦"]
            assert not panel.diagnostic_toggle_button.isChecked()
            assert not panel.frame_checkbox.isVisible()
            assert not panel.onset_checkbox.isVisible()
            assert not panel.contour_checkbox.isVisible()

            signals = {
                "load": 0,
                "unload": 0,
                "analyze": 0,
                "clear_staging": 0,
                "confidence": [],
                "copy": [],
                "analysis_mode": [],
                "sensitivity": [],
                "cleanup_profile": [],
                "show_suppressed": [],
                "spectrogram": [],
                "melody_lines": [],
                "melody_roles": [],
                "reference_opacity": [],
                "select_fragments": 0,
            }
            panel.load_audio_requested.connect(
                lambda: signals.__setitem__("load", signals["load"] + 1)
            )
            panel.unload_audio_requested.connect(
                lambda: signals.__setitem__("unload", signals["unload"] + 1)
            )
            panel.analyze_requested.connect(
                lambda: signals.__setitem__(
                    "analyze",
                    signals["analyze"] + 1,
                )
            )
            panel.clear_staging_requested.connect(
                lambda: signals.__setitem__(
                    "clear_staging",
                    signals["clear_staging"] + 1,
                )
            )
            panel.confidence_changed.connect(signals["confidence"].append)
            panel.copy_to_track_requested.connect(signals["copy"].append)
            panel.analysis_mode_changed.connect(
                signals["analysis_mode"].append
            )
            panel.sensitivity_changed.connect(
                signals["sensitivity"].append
            )
            panel.cleanup_profile_changed.connect(
                signals["cleanup_profile"].append
            )
            panel.show_suppressed_changed.connect(
                signals["show_suppressed"].append
            )
            panel.spectrogram_visibility_changed.connect(
                signals["spectrogram"].append
            )
            panel.melody_lines_visibility_changed.connect(
                signals["melody_lines"].append
            )
            panel.melody_line_roles_changed.connect(
                signals["melody_roles"].append
            )
            panel.reference_background_opacity_changed.connect(
                signals["reference_opacity"].append
            )
            panel.select_fragments_requested.connect(
                lambda: signals.__setitem__(
                    "select_fragments",
                    signals["select_fragments"] + 1,
                )
            )

            panel.audio_button.click()
            assert signals["load"] == 1
            assert (
                panel.analyze_button.toolTip()
                == "请先载入 MP3/WAV 参考音频"
            )
            panel.set_audio_loaded(True, display_name="reference.wav")
            assert panel.audio_button.text() == "卸载"
            assert panel.spectrogram_checkbox.isEnabled()
            assert not panel.melody_lines_button.isEnabled()
            panel.set_melody_lines_available(True)
            assert panel.melody_lines_button.isEnabled()
            assert "线粗" in panel.melody_lines_button.toolTip()
            assert panel.analyze_button.isEnabled()
            assert panel.analyze_button.toolTip() == "分析整首"
            panel.audio_button.click()
            assert signals["unload"] == 1
            panel.analyze_button.click()
            assert signals["analyze"] == 1
            panel.set_analysis_mode("mixed_enhanced")
            assert panel.analysis_mode == "mixed_enhanced"
            assert signals["analysis_mode"] == []
            panel.analysis_mode_combo.setCurrentIndex(0)
            assert signals["analysis_mode"] == ["standard"]
            panel.sensitivity_combo.setCurrentIndex(0)
            assert panel.sensitivity == "conservative"
            assert panel.cleanup_profile == "preserve"
            assert signals["sensitivity"] == ["conservative"]
            panel.set_cleanup_profile("clean")
            assert panel.cleanup_profile == "clean"
            assert panel.sensitivity == "conservative"
            assert panel.cleanup_profile_mark.text() == "◆"
            assert panel.cleanup_profile_group.property("experimental")
            assert signals["cleanup_profile"] == []
            panel.cleanup_profile_combo.setCurrentIndex(0)
            assert panel.cleanup_profile == "preserve"
            assert panel.cleanup_profile_mark.text() == "◇"
            assert not panel.cleanup_profile_group.property("experimental")
            assert signals["cleanup_profile"] == ["preserve"]
            panel.show_suppressed_checkbox.setChecked(True)
            assert signals["show_suppressed"] == [True]
            panel.spectrogram_checkbox.setChecked(True)
            assert panel.spectrogram_visible
            assert signals["spectrogram"] == [True]
            panel.set_spectrogram_visible(False)
            assert not panel.spectrogram_visible
            assert signals["spectrogram"] == [True]
            panel.melody_lines_button.setChecked(False)
            assert not panel.melody_lines_visible
            assert signals["melody_lines"] == [False]
            panel.set_melody_lines_visible(True)
            assert panel.melody_lines_visible
            assert signals["melody_lines"] == [False]
            panel.reference_opacity_slider.setValue(42)
            assert panel.reference_background_opacity == 0.42
            assert panel.reference_opacity_label.text() == "42%"
            assert signals["reference_opacity"] == [0.42]
            panel.set_reference_background_opacity(0.75)
            assert panel.reference_background_opacity == 0.75
            assert panel.reference_opacity_label.text() == "75%"
            assert signals["reference_opacity"] == [0.42]
            panel._melody_role_actions["harmony"].setChecked(False)
            assert panel.melody_line_roles == frozenset(
                {"primary_melody", "bass"}
            )
            assert signals["melody_roles"] == [
                frozenset({"primary_melody", "bass"})
            ]
            panel.set_melody_line_roles({"harmony"})
            assert panel.melody_line_roles == frozenset({"harmony"})
            assert len(signals["melody_roles"]) == 1
            panel._melody_role_actions["harmony"].setChecked(False)
            assert panel.melody_line_roles == frozenset({"harmony"})
            assert not panel.select_fragments_button.isEnabled()
            panel.set_fragment_state(suspected_count=3)
            assert panel.select_fragments_button.isEnabled()
            assert panel.select_fragments_button.text() == "碎音 3"
            panel.select_fragments_button.click()
            assert signals["select_fragments"] == 1

            panel.set_range_available(True)
            assert panel.redecode_button.isEnabled()
            panel.set_staging_locked(True)
            assert not panel.audio_button.isEnabled()
            assert not panel.analyze_button.isEnabled()
            assert "清除本次暂存" in panel.analyze_button.toolTip()
            assert not panel.redecode_button.isEnabled()
            assert not panel.align_audio_button.isEnabled()
            assert not panel.analysis_mode_combo.isEnabled()
            assert not panel.sensitivity_combo.isEnabled()
            assert not panel.cleanup_profile_combo.isEnabled()
            assert panel.clear_range_button.isEnabled()
            assert panel.beat_origin_button.isEnabled()
            panel.set_staging_locked(False)

            panel.confidence_slider.setValue(75)
            assert signals["confidence"][-1] == 0.75
            panel.diagnostic_toggle_button.click()
            assert panel.frame_checkbox.isVisible()
            assert panel.onset_checkbox.isVisible()
            assert panel.contour_checkbox.isVisible()
            assert panel.spectrogram_checkbox.isVisible()
            panel.contour_checkbox.setChecked(True)
            assert panel.visible_evidence_layers == frozenset({"contour"})

            targets = [
                SimpleNamespace(
                    track_id=1,
                    display_name="Current",
                    is_percussion=False,
                    bdo_instrument_id=0x0B,
                ),
                SimpleNamespace(
                    track_id=2,
                    display_name="Other",
                    is_percussion=False,
                    bdo_instrument_id=0x0B,
                ),
                SimpleNamespace(
                    track_id=3,
                    display_name="Drums",
                    is_percussion=True,
                    bdo_instrument_id=0x0D,
                ),
            ]
            panel.set_copy_targets(targets, current_track_id=1)
            panel.set_action_state(
                write_enabled=True,
                copy_enabled=True,
                rejected_count=2,
                can_undo=True,
                can_redo=False,
                staging_count=3,
            )
            assert len(panel.copy_to_track_menu.actions()) == 1
            assert panel.copy_to_track_menu.actions()[0].property("i18nSkipText")
            assert panel.copy_to_track_button.isEnabled()
            assert panel.clear_staging_button.isEnabled()
            assert panel.staging_label.text() == "暂存 3"
            assert panel.staging_label.toolTip() == "已暂存 3 个候选"
            panel.copy_to_track_menu.actions()[0].trigger()
            assert signals["copy"] == [2]
            panel.clear_staging_button.click()
            assert signals["clear_staging"] == 1

            panel.set_analysis_busy(True, 42)
            assert "42%" in panel.status_label.text()
            assert not panel.analyze_button.isEnabled()
            assert panel.analyze_button.toolTip() == "正在分析参考音频…"
            panel.set_analysis_busy(False)
            panel.set_analysis_available(False, "backend unavailable")
            assert not panel.analyze_button.isEnabled()
            assert panel.status_label.text() == "backend unavailable"
            panel.set_status("尚未分析")
            assert panel.status_label.text() == "backend unavailable"
            assert panel.analyze_button.toolTip() == "backend unavailable"
            panel.set_analysis_available(True)
            assert panel.status_label.text() == "尚未分析"
            assert panel.status_label.toolTip() == "尚未分析"
            assert panel.analyze_button.isEnabled()

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

    def test_semantic_assist_is_collapsible_and_emits_host_intents(self) -> None:
        completed = _run_offscreen(
            """
            from types import SimpleNamespace

            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication

            from transcription_editor_qt import TranscriptionEditorPanel

            app = QApplication([])
            panel = TranscriptionEditorPanel()
            panel.resize(1180, panel.sizeHint().height())
            panel.show()
            app.processEvents()

            assert not hasattr(panel.assist_panel, "session")
            assert not hasattr(panel.assist_panel, "worker")
            assert not hasattr(panel.assist_panel, "transport")
            assert not panel.assist_toggle_button.isVisible()
            assert not panel.assist_panel.isVisible()
            harmony = panel.assist_panel.harmony_summary
            phrases = panel.assist_panel.phrase_controls
            matches = panel.assist_panel.instrument_matches
            assert not harmony.key_edit_button.isEnabled()
            assert not phrases.previous_button.isEnabled()
            assert not phrases.next_button.isEnabled()
            assert not phrases.loop_button.isEnabled()
            assert not phrases.review_queue_button.isEnabled()
            assert not matches.confirm_button.isEnabled()
            assert matches.source_combo.isEnabled()
            assert matches.source_combo.currentData() == "combined"
            assert not matches.source_combo.model().item(
                matches.source_combo.findData("candidate_a")
            ).isEnabled()

            events = {
                "key_edit": [],
                "key_lock": [],
                "chord_edit": [],
                "chord_lock": [],
                "previous": 0,
                "next": 0,
                "loop": [],
                "queue": 0,
                "confirm": [],
                "stage": [],
                "new": [],
                "source": [],
            }
            panel.key_edit_requested.connect(events["key_edit"].append)
            panel.key_lock_requested.connect(events["key_lock"].append)
            panel.chord_edit_requested.connect(events["chord_edit"].append)
            panel.chord_lock_requested.connect(
                lambda segment_id, locked: events["chord_lock"].append(
                    (segment_id, locked)
                )
            )
            panel.previous_phrase_requested.connect(
                lambda: events.__setitem__(
                    "previous", events["previous"] + 1
                )
            )
            panel.next_phrase_requested.connect(
                lambda: events.__setitem__("next", events["next"] + 1)
            )
            panel.loop_phrase_requested.connect(events["loop"].append)
            panel.review_queue_requested.connect(
                lambda: events.__setitem__("queue", events["queue"] + 1)
            )
            panel.confirm_match_requested.connect(
                lambda group_id, instrument_id: events["confirm"].append(
                    (group_id, instrument_id)
                )
            )
            panel.stage_existing_track_requested.connect(
                lambda group_id, instrument_id: events["stage"].append(
                    (group_id, instrument_id)
                )
            )
            panel.new_track_requested.connect(
                lambda group_id, instrument_id: events["new"].append(
                    (group_id, instrument_id)
                )
            )
            panel.audition_source_changed.connect(events["source"].append)

            key = SimpleNamespace(
                root_pc=0,
                mode="major",
                confidence=0.84,
                alternatives=(
                    SimpleNamespace(
                        root_pc=9,
                        mode="minor",
                        confidence=0.61,
                    ),
                ),
            )
            segment = SimpleNamespace(
                segment_id="chord-1",
                start_audio_ms=500.0,
                end_audio_ms=1500.0,
                root_pc=0,
                quality="major",
                bass_pc=0,
                confidence=0.91,
                locked=False,
            )
            analysis = SimpleNamespace(
                global_key=key,
                chord_segments=(segment,),
                conflicts=("audio-note disagreement",),
                key_locked=False,
            )
            panel.set_harmony_analysis(analysis)
            assert panel.assist_toggle_button.isVisible()
            assert not panel.assist_panel.isVisible()
            panel.set_assist_expanded(True)
            app.processEvents()
            assert panel.assist_panel.isVisible()
            assert "C major" in harmony.key_label.text()
            assert "1" in harmony.conflict_label.text()
            assert harmony.segment_combo.count() == 1
            harmony.key_edit_button.click()
            harmony.key_lock_checkbox.click()
            harmony.chord_edit_button.click()
            harmony.chord_lock_checkbox.click()
            assert events["key_edit"] == [key]
            assert events["key_lock"] == [True]
            assert events["chord_edit"] == ["chord-1"]
            assert events["chord_lock"] == [("chord-1", True)]

            panel.set_phrase_state(
                index=1,
                total=3,
                loop_enabled=False,
                review_count=4,
            )
            phrases.previous_button.click()
            phrases.next_button.click()
            phrases.loop_button.click()
            phrases.review_queue_button.click()
            assert events["previous"] == 1
            assert events["next"] == 1
            assert events["loop"] == [True]
            assert events["queue"] == 1
            assert "2/3" in phrases.phrase_label.text()

            group = {
                "group_id": "voice-a",
                "role": "melody",
            }
            suggestions = (
                {
                    "instrument_id": 11,
                    "instrument_name": "Flute",
                    "total_score": 0.88,
                    "pitch_coverage": 1.0,
                    "reasons": ("音域完整", "音色接近"),
                },
                {
                    "instrument_id": 5,
                    "instrument_name": "Violin",
                    "total_score": 0.76,
                    "pitch_coverage": 0.94,
                    "reasons": ("旋律适配",),
                },
                {
                    "instrument_id": 4,
                    "instrument_name": "Cello",
                    "total_score": 0.64,
                    "pitch_coverage": 0.71,
                    "reasons": ("持续音适配",),
                },
                {
                    "instrument_id": 99,
                    "instrument_name": "Must not render",
                    "total_score": 1.0,
                    "pitch_coverage": 1.0,
                },
            )
            panel.set_voice_group_matches(group, suggestions)
            assert len(matches.matches) == 3
            assert matches.cards[0].isVisible()
            assert matches.cards[1].isVisible()
            assert matches.cards[2].isVisible()
            assert matches.selected_match is suggestions[0]
            matches.confirm_button.click()
            matches.stage_button.click()
            matches.new_track_button.click()
            matches.source_combo.setCurrentIndex(
                matches.source_combo.findData("candidate_a")
            )
            assert events["confirm"] == [("voice-a", 11)]
            assert events["stage"] == [("voice-a", 11)]
            assert events["new"] == [("voice-a", 11)]
            assert events["source"] == ["candidate_a"]

            matches.cards[1].select_button.click()
            matches.confirm_button.click()
            assert events["confirm"][-1] == ("voice-a", 5)

            panel.clear_voice_group_matches()
            assert not matches.confirm_button.isEnabled()
            assert matches.source_combo.isEnabled()
            assert matches.source_combo.currentData() == "combined"
            assert all(not card.isVisible() for card in matches.cards)

            panel.set_assist_available(False)
            app.processEvents()
            assert not panel.assist_toggle_button.isVisible()
            assert not panel.assist_panel.isVisible()
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

    def test_compact_command_strip_fits_all_supported_locales(self) -> None:
        completed = _run_offscreen(
            """
            from types import SimpleNamespace

            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication

            from i18n import install_localizer, tr
            from transcription_editor_qt import TranscriptionEditorPanel

            app = QApplication([])
            localizer = install_localizer(app, "zh_CN")
            panel = TranscriptionEditorPanel()
            panel.resize(920, panel.sizeHint().height())
            panel.show()
            app.processEvents()

            panel.set_audio_loaded(True, display_name="Play")
            panel.set_harmony_analysis(SimpleNamespace(
                global_key=SimpleNamespace(
                    root_pc=0,
                    mode="major",
                    confidence=0.84,
                    alternatives=(SimpleNamespace(
                        root_pc=9,
                        mode="minor",
                        confidence=0.61,
                    ),),
                ),
                chord_segments=(),
                conflicts=(),
                key_locked=False,
            ))

            melody_labels = {
                "zh_CN": "旋律线",
                "zh_TW": "旋律線",
                "en_US": "Melody lines",
                "ja_JP": "メロディライン",
                "ko_KR": "멜로디 라인",
            }
            alternative_prefixes = {
                "zh_CN": "备选：",
                "zh_TW": "備選：",
                "en_US": "Alternatives:",
                "ja_JP": "候補：",
                "ko_KR": "대안:",
            }
            for language in ("zh_CN", "zh_TW", "en_US", "ja_JP", "ko_KR"):
                localizer.set_language(language)
                app.processEvents()
                for index in range(panel.cleanup_profile_combo.count()):
                    profile = panel.cleanup_profile_combo.itemData(index)
                    assert (
                        panel.cleanup_profile_combo.itemData(
                            index,
                            Qt.ItemDataRole.ToolTipRole,
                        )
                        == localizer.translate(
                            panel.CLEANUP_PROFILE_TOOLTIPS[profile]
                        )
                    )
                assert panel.melody_lines_button.text() == melody_labels[language]
                assert panel.audio_button.toolTip() == "Play"
                assert panel.assist_panel.harmony_summary.key_label.toolTip().startswith(
                    alternative_prefixes[language]
                )
                assert panel.minimumSizeHint().width() <= 920, (
                    language,
                    panel.minimumSizeHint().width(),
                )

            panel.set_diagnostic_evidence_expanded(True)
            for language in ("zh_CN", "zh_TW", "en_US", "ja_JP", "ko_KR"):
                localizer.set_language(language)
                app.processEvents()
                assert panel.minimumSizeHint().width() <= 920, (
                    language,
                    panel.minimumSizeHint().width(),
                )

            localizer.set_language("en_US")
            panel.set_audio_loaded(False)
            assert panel.analyze_button.text() == "Full"
            assert panel.cleanup_profile_caption.text() == "Fragments"
            assert panel.cleanup_profile_combo.itemText(0) == "Keep"
            assert panel.melody_lines_button.text() == "Melody lines"
            assert panel.spectrogram_checkbox.text() == "Spectrogram"
            assert (
                localizer.translate("原始声谱图")
                == "Raw spectrogram"
            )
            assert panel.analyze_button.toolTip() == "Load an MP3/WAV reference first"

            # Cached idle/backend messages must not write an old locale back
            # after a later control-state refresh.
            panel.set_status(tr("尚未分析"))
            localizer.set_language("ja_JP")
            panel.set_analysis_busy(False)
            assert panel.status_label.text() == "未解析"
            panel.set_analysis_available(
                False,
                tr("请先载入 MP3/WAV 参考音频"),
            )
            localizer.set_language("ko_KR")
            panel.set_analysis_busy(False)
            assert panel.status_label.text() == "먼저 MP3/WAV 참조 오디오를 불러오세요"
            assert panel.analyze_button.toolTip() == panel.status_label.text()
            panel.set_cleanup_profile("balanced")
            assert (
                panel.cleanup_profile_mark.toolTip()
                == localizer.translate(
                    panel.CLEANUP_PROFILE_TOOLTIPS["balanced"]
                )
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

    def test_canvas_paint_only_requests_aligned_ready_spectrogram_tiles(self) -> None:
        completed = _run_offscreen(
            """
            from unittest.mock import patch

            from PySide6.QtCore import QObject, Signal
            from PySide6.QtGui import QImage
            from PySide6.QtWidgets import QApplication, QWidget

            import pyside_bdo_gui

            requests = []

            class TileController(QObject):
                tile_ready = Signal(object)

                def __init__(self, parent=None):
                    super().__init__(parent)
                    self.source = None

                def request_visible(self, **kwargs):
                    requests.append(kwargs)
                    return ()

                def close(self):
                    self.source = None

                def cancel_pending(self):
                    pass

            class Editor(QWidget):
                bpm = 120
                time_sig = 4
                beat_origin_ms = 0.0
                transcription_mode_enabled = True

                def quantize_ms(self):
                    return 125.0

                def note_invalid(self, _pitch):
                    return False

                def _candidate_invalid_for_current_track(self, _candidate):
                    return False

                def format_playback_time(self, _position_ms):
                    return "0:00.000"

            app = QApplication([])
            editor = Editor()
            with patch.object(
                pyside_bdo_gui,
                "SpectrogramTileController",
                TileController,
            ):
                canvas = pyside_bdo_gui.PianoRollCanvas(editor)
            canvas.resize(700, 400)
            canvas.scroll_ms = 1_000.0
            canvas._audio_offset_ms = 250.0
            canvas._spectrogram_audio_path = "ephemeral-reference"
            canvas.transcription_candidates_visible = True
            canvas.set_spectrogram_visible(True)
            canvas.show()
            app.processEvents()
            requests.clear()

            image = QImage(canvas.size(), QImage.Format_ARGB32)
            image.fill(0)
            # Any FFT reaching paint is a hard regression.  The canvas should
            # only ask the asynchronous controller for ready/cache tiles.
            with patch(
                "numpy.fft.rfft",
                side_effect=AssertionError("FFT reached paintEvent"),
            ):
                canvas.render(image)
            assert requests
            request = requests[-1]
            assert abs(request["start_ms"] - 750.0) < 0.01
            assert request["end_ms"] > request["start_ms"]
            assert request["pixels_per_ms"] == canvas.px_per_ms
            assert request["pitch_min"] <= request["pitch_max"]

            canvas.set_spectrogram_visible(False)
            requests.clear()
            canvas.render(image)
            assert requests == []
            canvas.release_transcription_evidence()
            canvas.close()
            editor.close()
            app.processEvents()
            app.quit()
            """
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_melody_lines_are_precomputed_offset_aligned_and_viewport_indexed(
        self,
    ) -> None:
        completed = _run_offscreen(
            """
            from unittest.mock import patch

            from PySide6.QtCore import QPoint, QPointF, Qt
            from PySide6.QtGui import QImage
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QCheckBox, QToolButton, QWidget

            from bdo_transcription import TranscriptionCandidate
            from bdo_transcription_instruments import VoiceGroup
            from bdo_transcription_melody_lines import CONTOUR_KIND
            import pyside_bdo_gui

            class Editor(QWidget):
                bpm = 120
                time_sig = 4
                beat_origin_ms = 0.0
                transcription_mode_enabled = True

                def __init__(self):
                    super().__init__()
                    self.draw_mode_button = QToolButton(self)
                    self.draw_mode_button.setCheckable(True)
                    self.snap_box = QCheckBox(self)

                def quantize_ms(self):
                    return 125.0

                def note_invalid(self, _pitch):
                    return False

                def _candidate_invalid_for_current_track(self, _candidate):
                    return False

                def format_playback_time(self, _position_ms):
                    return "0:00.000"

            app = QApplication([])
            editor = Editor()
            canvas = pyside_bdo_gui.PianoRollCanvas(editor)
            canvas.resize(700, 400)
            canvas.pitch_top = 72
            candidates = tuple(
                TranscriptionCandidate(
                    60 + (index % 12),
                    90,
                    index * 250.0,
                    140.0,
                    0.2 + (index % 8) * 0.1,
                    candidate_id=f"candidate-{index}",
                )
                for index in range(2_000)
            )
            canvas.set_transcription_candidates(
                candidates,
                candidate_id_resolver=lambda item: item.candidate_id,
            )
            lead = VoiceGroup(
                "lead",
                tuple(item.candidate_id for item in candidates),
                0.0,
                500_000.0,
                "primary_melody",
                0.8,
            )
            canvas.set_transcription_assist_projection(
                voice_groups=(lead,),
            )
            assert canvas.melody_lines_available
            assert canvas._melody_line_segments

            canvas._audio_offset_ms = 500.0
            shifted = canvas.visible_melody_line_segments(500.0, 900.0)
            assert shifted
            assert min(item.start_audio_ms for item in shifted) <= 0.0
            assert canvas._last_melody_line_query_inspections < len(
                canvas._melody_line_segments
            )
            assert all(item.kind != CONTOUR_KIND for item in shifted)

            canvas.px_per_beat = 30.0
            overview = canvas.visible_melody_line_segments(500.0, 1_200.0)
            assert overview
            assert all(item.kind == CONTOUR_KIND for item in overview)
            assert len(overview) < len(
                canvas._melody_line_segments
            )
            canvas.set_melody_line_roles_visible({"bass"})
            assert canvas.visible_melody_line_segments(500.0, 1_200.0) == []
            canvas.set_melody_line_roles_visible({"primary_melody"})
            canvas.px_per_beat = 92.0

            connector_time_ms = 695.0
            connector_pitch = 60.5
            connector_position = QPointF(
                canvas.x_at_time(connector_time_ms),
                canvas.RULER_H
                + (canvas.pitch_top - connector_pitch + 0.5)
                * canvas.ROW_H,
            )
            guide = canvas.melody_guide_at(connector_position)
            assert guide is not None
            assert set(guide.source_candidate_ids) == {
                "candidate-0", "candidate-1"
            }
            selections = []
            canvas.candidate_selection_changed.connect(selections.append)

            canvas.show()
            app.processEvents()
            QTest.mouseClick(
                canvas,
                Qt.LeftButton,
                Qt.NoModifier,
                QPoint(round(connector_position.x()), round(connector_position.y())),
            )
            assert selections[-1] == frozenset(
                {"candidate-0", "candidate-1"}
            )
            assert canvas.notes == []
            canvas._rejected_candidate_ids.update(
                {"candidate-0", "candidate-1"}
            )
            assert canvas.melody_guide_at(connector_position) is None
            canvas._rejected_candidate_ids.clear()
            image = QImage(canvas.size(), QImage.Format_ARGB32)
            image.fill(0)
            # The semantic builder belongs to setter/review transitions only.
            with patch.object(
                pyside_bdo_gui,
                "build_melody_line_segments",
                side_effect=AssertionError("analysis reached paintEvent"),
            ):
                canvas.render(image)
                canvas.px_per_beat = 180.0
                canvas.render(image)
            assert not image.isNull()

            canvas.set_melody_lines_visible(False)
            assert canvas.visible_melody_line_segments(500.0, 900.0) == []
            canvas.close()
            editor.close()
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
