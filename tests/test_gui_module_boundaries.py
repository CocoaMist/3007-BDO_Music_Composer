from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"


class GuiModuleBoundaryTests(unittest.TestCase):
    def test_large_gui_reexports_extracted_dialogs_without_defining_them(self) -> None:
        from bdo_music_composer.app import conversion_validation_controller
        from bdo_music_composer.audio import preview_transport_controller
        from bdo_music_composer.editor import editor_models, model_revision
        from bdo_music_composer.project import project_lifecycle_controller
        from bdo_music_composer.transcription import (
            transcription_workspace_controller,
        )
        import bdo_music_composer.ui.dialogs.acknowledgements_dialog as acknowledgements_dialog
        import bdo_music_composer.ui.dialogs.application_settings_dialog as application_settings_dialog
        import bdo_music_composer.ui.dialogs.conversion_check_dialog as conversion_check_dialog
        import bdo_music_composer.ui.dialogs.optimizer_dialog as optimizer_dialog
        import bdo_music_composer.ui.dialogs.release_notes_dialog as release_notes_dialog
        import bdo_music_composer.ui.dialogs.track_settings_dialogs as track_settings_dialogs
        import bdo_music_composer.ui.theme.main_window_style as main_window_style
        from bdo_music_composer.ui import (
            home_widgets,
            startup_widgets,
            transcription_rhythm_diagnostic,
            ui_notifications,
        )
        import bdo_music_composer.ui.editor.midi_note_editor as midi_note_editor
        import bdo_music_composer.ui.editor.piano_roll_canvas as piano_roll_canvas
        import bdo_music_composer.ui.main_window as pyside_bdo_gui
        import bdo_music_composer.audio.reference_audio_controller as reference_audio_controller
        import bdo_music_composer.ui.editor.timeline_canvas as timeline_canvas
        import bdo_music_composer.ui.transcription.transcription_workers as transcription_workers

        expected = {
            "AcknowledgementsDialog": acknowledgements_dialog.AcknowledgementsDialog,
            "ReleaseNotesDialog": release_notes_dialog.ReleaseNotesDialog,
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
            "MainWindowStyleMixin": main_window_style.MainWindowStyleMixin,
            "TranscriptionRhythmDiagnosticMixin": transcription_rhythm_diagnostic.TranscriptionRhythmDiagnosticMixin,
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
            "HomeIdentityBadge": home_widgets.HomeIdentityBadge,
            "EnsembleCapacityBadge": home_widgets.EnsembleCapacityBadge,
            "HomeBackdrop": home_widgets.HomeBackdrop,
            "HomeEntryDelegate": home_widgets.HomeEntryDelegate,
            "HomeFooter": home_widgets.HomeFooter,
        }
        source = (SOURCE_ROOT / "bdo_music_composer/ui/main_window.py").read_text(encoding="utf-8-sig")
        defined_classes = {
            node.name for node in ast.parse(source).body if isinstance(node, ast.ClassDef)
        }
        for name, implementation in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(pyside_bdo_gui, name), implementation)
                self.assertNotIn(name, defined_classes)

    def test_extracted_modules_do_not_import_main_gui(self) -> None:
        for relative_path in (
            "bdo_music_composer/app/audio_source_settings.py",
            "bdo_music_composer/app/conversion_validation_controller.py",
            "bdo_music_composer/app/crash_logging.py",
            "bdo_music_composer/app/application_metadata.py",
            "bdo_music_composer/app/release_notes.py",
            "bdo_music_composer/app/update_check.py",
            "bdo_music_composer/audio/preview_transport_controller.py",
            "bdo_music_composer/editor/model_revision.py",
            "bdo_music_composer/project/project_lifecycle_controller.py",
            "bdo_music_composer/transcription/transcription_workspace_controller.py",
            "bdo_music_composer/ui/editor/editor_shortcut_hud.py",
            "bdo_music_composer/ui/editor/editor_ui_helpers.py",
            "bdo_music_composer/ui/dialogs/acknowledgements_dialog.py",
            "bdo_music_composer/ui/dialogs/application_settings_dialog.py",
            "bdo_music_composer/ui/dialogs/conversion_check_dialog.py",
            "bdo_music_composer/ui/dialogs/optimizer_dialog.py",
            "bdo_music_composer/ui/dialogs/release_notes_dialog.py",
            "bdo_music_composer/ui/dialogs/track_settings_dialogs.py",
            "bdo_music_composer/ui/home_widgets.py",
            "bdo_music_composer/ui/startup_widgets.py",
            "bdo_music_composer/ui/transcription_rhythm_diagnostic.py",
            "bdo_music_composer/ui/theme/fluent_theme.py",
            "bdo_music_composer/ui/theme/main_window_style.py",
            "bdo_music_composer/ui/transcription_ui_helpers.py",
            "bdo_music_composer/ui/ui_controls.py",
            "bdo_music_composer/ui/ui_notifications.py",
            "bdo_music_composer/ui/update_check_qt.py",
            "bdo_music_composer/ui/editor/editor_articulation_data.py",
            "bdo_music_composer/editor/editor_commands.py",
            "bdo_music_composer/editor/editor_import.py",
            "bdo_music_composer/editor/editor_models.py",
            "bdo_music_composer/editor/interval_index.py",
            "bdo_music_composer/ui/editor/midi_note_editor.py",
            "bdo_music_composer/ui/editor/piano_roll_canvas.py",
            "bdo_music_composer/editor/preview_midi_writer.py",
            "bdo_music_composer/editor/velocity_curve.py",
            "bdo_music_composer/audio/reference_audio_controller.py",
            "bdo_music_composer/ui/editor/timeline_canvas.py",
            "bdo_music_composer/transcription/transcription_commit_plan.py",
            "bdo_music_composer/ui/transcription/transcription_workers.py",
        ):
            with self.subTest(path=relative_path):
                tree = ast.parse(
                    (SOURCE_ROOT / relative_path).read_text(encoding="utf-8")
                )
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

    def test_preview_midi_writer_keeps_compatibility_export(self) -> None:
        from bdo_music_composer.editor import preview_midi_writer
        import bdo_music_composer.ui.main_window as pyside_bdo_gui

        self.assertIs(
            pyside_bdo_gui.build_filtered_midi,
            preview_midi_writer.build_filtered_midi,
        )

    def test_home_constants_keep_compatibility_exports(self) -> None:
        from bdo_music_composer.ui import home_widgets
        import bdo_music_composer.ui.main_window as pyside_bdo_gui

        for name in (
            "HOME_BACKGROUND_IMAGE",
            "HOME_INSTRUMENT_IDS_ROLE",
            "SHAI_ENSEMBLE_MARK_IMAGE",
        ):
            with self.subTest(name=name):
                self.assertIs(
                    getattr(pyside_bdo_gui, name),
                    getattr(home_widgets, name),
                )

    def test_main_gui_stays_below_orchestration_line_budget(self) -> None:
        source = (SOURCE_ROOT / "bdo_music_composer/ui/main_window.py").read_text(encoding="utf-8-sig")
        self.assertLessEqual(len(source.splitlines()), 8_600)

    def test_crash_logging_installation_uses_the_packaged_owner(self) -> None:
        from bdo_music_composer.app import crash_logging
        import bdo_music_composer.ui.main_window as pyside_bdo_gui

        self.assertIs(
            pyside_bdo_gui.install_crash_logging,
            crash_logging.install_crash_logging,
        )

    def test_game_profile_is_lazy_and_cached(self) -> None:
        from unittest.mock import patch

        from bdo_music_composer.app import game_profile_provider
        import bdo_music_composer.ui.main_window as pyside_bdo_gui

        marker = object()
        game_profile_provider.get_bdo_profile.cache_clear()
        try:
            with patch.object(
                game_profile_provider,
                "load_bdo_profile",
                return_value=marker,
            ) as loader:
                self.assertIs(pyside_bdo_gui.get_bdo_profile(), marker)
                self.assertIs(pyside_bdo_gui.get_bdo_profile(), marker)
            loader.assert_called_once()
        finally:
            game_profile_provider.get_bdo_profile.cache_clear()

        source = (SOURCE_ROOT / "bdo_music_composer/ui/main_window.py").read_text(encoding="utf-8-sig")
        module = ast.parse(source)
        top_level_profile_reads = [
            call
            for node in module.body
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in {"load_bdo_profile", "get_bdo_profile"}
        ]
        self.assertEqual(top_level_profile_reads, [])
        self.assertIs(
            pyside_bdo_gui.get_bdo_profile,
            game_profile_provider.get_bdo_profile,
        )

    def test_config_filename_helper_reexports_the_storage_owner(self) -> None:
        from bdo_music_composer.app import application_config
        import bdo_music_composer.ui.main_window as pyside_bdo_gui

        self.assertIs(
            pyside_bdo_gui.safe_filename,
            application_config.safe_filename,
        )

    def test_audio_source_helpers_keep_compatibility_exports(self) -> None:
        from bdo_music_composer.app import audio_source_settings
        import bdo_music_composer.ui.main_window as pyside_bdo_gui

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
        source = (
            SOURCE_ROOT / "bdo_music_composer/ui/editor/midi_note_editor.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("canvas._candidate_starts", source)
        self.assertNotIn("canvas._transcription_candidate_ids", source)
        self.assertIn("session.eligible_candidate_ids(", source)


if __name__ == "__main__":
    unittest.main()
