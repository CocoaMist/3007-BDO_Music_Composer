from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GuiModuleBoundaryTests(unittest.TestCase):
    def test_large_gui_reexports_extracted_dialogs_without_defining_them(self) -> None:
        import application_settings_dialog
        import acknowledgements_dialog
        import conversion_check_dialog
        import conversion_validation_controller
        import editor_models
        import midi_note_editor
        import model_revision
        import optimizer_dialog
        import piano_roll_canvas
        import preview_transport_controller
        import project_lifecycle_controller
        import pyside_bdo_gui
        import reference_audio_controller
        import timeline_canvas
        import track_settings_dialogs
        import transcription_workers
        import transcription_workspace_controller
        import ui_notifications

        expected = {
            "AcknowledgementsDialog": acknowledgements_dialog.AcknowledgementsDialog,
            "SettingsDialog": application_settings_dialog.SettingsDialog,
            "GameArtImportWorker": application_settings_dialog.GameArtImportWorker,
            "TrackPitchDialog": track_settings_dialogs.TrackPitchDialog,
            "TrackFxDialog": track_settings_dialogs.TrackFxDialog,
            "MasterEffectsDialog": track_settings_dialogs.MasterEffectsDialog,
            "TimelineCanvas": timeline_canvas.TimelineCanvas,
            "PianoRollCanvas": piano_roll_canvas.PianoRollCanvas,
            "VelocityLaneCanvas": piano_roll_canvas.VelocityLaneCanvas,
            "MidiNoteEditorDialog": midi_note_editor.MidiNoteEditorDialog,
            "ConversionCheckDialog": conversion_check_dialog.ConversionCheckDialog,
            "ConversionValidationController": conversion_validation_controller.ConversionValidationController,
            "ModelRevision": model_revision.ModelRevision,
            "MidiOptimizeDialog": optimizer_dialog.MidiOptimizeDialog,
            "OptimizerAnalysisWorker": optimizer_dialog.OptimizerAnalysisWorker,
            "ReferenceAudioController": reference_audio_controller.ReferenceAudioController,
            "PreviewPlayAction": preview_transport_controller.PreviewPlayAction,
            "PreviewTransportCoordinator": preview_transport_controller.PreviewTransportCoordinator,
            "ProjectLifecycleController": project_lifecycle_controller.ProjectLifecycleController,
            "TranscriptionAnalysisCoordinator": transcription_workspace_controller.TranscriptionAnalysisCoordinator,
            "TranscriptionReviewController": transcription_workspace_controller.TranscriptionReviewController,
            "TranscriptionAnalysisWorker": transcription_workers.TranscriptionAnalysisWorker,
            "TranscriptionRedecodeWorker": transcription_workers.TranscriptionRedecodeWorker,
            "TranscriptionCacheLoadWorker": transcription_workers.TranscriptionCacheLoadWorker,
            "TranscriptionAssistAnalysisWorker": transcription_workers.TranscriptionAssistAnalysisWorker,
            "SamplePackPrepareWorker": transcription_workers.SamplePackPrepareWorker,
            "GlobalToast": ui_notifications.GlobalToast,
            "TrackState": editor_models.TrackState,
            "GhostNoteProjection": editor_models.GhostNoteProjection,
        }
        source = (ROOT / "pyside_bdo_gui.py").read_text(encoding="utf-8-sig")
        defined_classes = {
            node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)
        }
        for name, implementation in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(pyside_bdo_gui, name), implementation)
                self.assertNotIn(name, defined_classes)

    def test_extracted_modules_do_not_import_main_gui(self) -> None:
        for filename in (
            "application_settings_dialog.py",
            "acknowledgements_dialog.py",
            "audio_source_settings.py",
            "conversion_check_dialog.py",
            "conversion_validation_controller.py",
            "crash_logging.py",
            "editor_articulation_data.py",
            "editor_models.py",
            "editor_ui_helpers.py",
            "main_window_style.py",
            "midi_note_editor.py",
            "model_revision.py",
            "optimizer_dialog.py",
            "piano_roll_canvas.py",
            "preview_transport_controller.py",
            "project_lifecycle_controller.py",
            "reference_audio_controller.py",
            "timeline_canvas.py",
            "track_settings_dialogs.py",
            "transcription_ui_helpers.py",
            "transcription_workers.py",
            "transcription_workspace_controller.py",
            "ui_controls.py",
            "ui_notifications.py",
        ):
            with self.subTest(filename=filename):
                tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
                imports = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imports.update(
                    node.module or ""
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                )
                self.assertNotIn("pyside_bdo_gui", imports)

    def test_main_gui_stays_below_orchestration_line_budget(self) -> None:
        source = (ROOT / "pyside_bdo_gui.py").read_text(encoding="utf-8-sig")
        self.assertLessEqual(len(source.splitlines()), 11_000)

    def test_audio_source_helpers_keep_compatibility_exports(self) -> None:
        import audio_source_settings
        import pyside_bdo_gui

        for name in (
            "audio_source_config",
            "classify_audio_source",
            "default_game_music_dir",
            "displayed_audio_source",
            "preview_source_mode",
        ):
            with self.subTest(name=name):
                self.assertIs(
                    getattr(pyside_bdo_gui, name),
                    getattr(audio_source_settings, name),
                )

    def test_transcription_scope_uses_session_index_not_canvas_privates(self) -> None:
        source = (ROOT / "midi_note_editor.py").read_text(encoding="utf-8")
        self.assertNotIn("canvas._candidate_starts", source)
        self.assertNotIn("canvas._transcription_candidate_ids", source)
        self.assertIn("session.eligible_candidate_ids(", source)


if __name__ == "__main__":
    unittest.main()
