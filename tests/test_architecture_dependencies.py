from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> frozenset[str]:
    """Return statically declared imports without importing application code."""

    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    package_parts = list(path.relative_to(ROOT).parent.parts)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                if node.module:
                    modules.add(node.module)
                continue
            keep = len(package_parts) - (node.level - 1)
            base = package_parts[:max(0, keep)]
            if node.module:
                modules.add(".".join((*base, *node.module.split("."))))
            else:
                modules.update(
                    ".".join((*base, alias.name))
                    for alias in node.names
                )
    return frozenset(modules)


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _python_files(directory: str) -> tuple[Path, ...]:
    return tuple(sorted((ROOT / directory).rglob("*.py")))


def _function_spans(path: Path) -> tuple[tuple[str, int], ...]:
    """Return every function/method size so focused owners stay reviewable."""

    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return tuple(
        (node.name, int(node.end_lineno or node.lineno) - node.lineno + 1)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


class ArchitectureDependencyTests(unittest.TestCase):
    """Executable form of the ownership rules in docs/AI_EDITING_GUIDE.md."""

    def assert_forbidden_imports(
        self,
        paths: tuple[Path, ...],
        forbidden: frozenset[str],
    ) -> None:
        for path in paths:
            declared = _imports(path)
            violations = sorted(
                module
                for module in declared
                if any(
                    _matches_prefix(module, prefix)
                    for prefix in forbidden
                )
            )
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(
                    violations,
                    [],
                    "dependency points toward a UI/application owner; route "
                    "the change through the typed boundary documented in "
                    "docs/AI_EDITING_GUIDE.md",
                )

    def assert_function_span_budget(self, path: Path, budget: int) -> None:
        oversized = sorted(
            (name, span)
            for name, span in _function_spans(path)
            if span > budget
        )
        self.assertEqual(
            oversized,
            [],
            f"{path.relative_to(ROOT)} exceeds its {budget}-line focused "
            "function budget; extract a named helper with one responsibility",
        )

    def test_qt_free_editor_boundaries_do_not_import_ui(self) -> None:
        self.assert_forbidden_imports(
            _python_files("bdo_music_composer/editor")
            + (
                ROOT
                / "bdo_music_composer/transcription/transcription_commit_plan.py",
            ),
            frozenset({
                "PySide6",
                "bdo_music_composer.ui.main_window",
                "timeline_canvas",
                "piano_roll_canvas",
                "midi_note_editor",
                "i18n",
                "bdo_codec",
                "bdo_export",
                "export_workflow",
                "bdo_music_composer.app",
                "bdo_music_composer.project",
                "bdo_music_composer.ui",
            }),
        )

    def test_codec_does_not_depend_on_editor_export_or_ui_layers(self) -> None:
        self.assert_forbidden_imports(
            _python_files("bdo_codec"),
            frozenset({
                "PySide6",
                "pyside_bdo_gui",
                "editor_models",
                "editor_import",
                "game_score_model",
                "project_schema",
                "project_persistence",
                "project_lifecycle_controller",
                "export_workflow",
                "bdo_export",
                "bdo_music_composer",
            }),
        )

    def test_bdo_export_adapter_does_not_depend_on_application_or_ui(self) -> None:
        self.assert_forbidden_imports(
            _python_files("bdo_export"),
            frozenset({
                "PySide6",
                "pyside_bdo_gui",
                "editor_models",
                "editor_import",
                "game_score_model",
                "project_schema",
                "project_persistence",
                "project_lifecycle_controller",
                "export_workflow",
                "bdo_music_composer",
            }),
        )

    def test_project_boundaries_do_not_depend_on_codec_export_or_ui(self) -> None:
        self.assert_forbidden_imports(
            _python_files("bdo_music_composer/project"),
            frozenset({
                "PySide6",
                "pyside_bdo_gui",
                "bdo_codec",
                "bdo_export",
                "export_workflow",
                "bdo_music_composer.app",
                "bdo_music_composer.audio",
                "bdo_music_composer.transcription",
                "bdo_music_composer.ui",
            }),
        )

    def test_export_workflow_does_not_depend_on_ui_or_project_storage(self) -> None:
        self.assert_forbidden_imports(
            (
                ROOT / "bdo_music_composer/export/export_workflow.py",
                ROOT
                / "bdo_music_composer/export/export_verification.py",
            ),
            frozenset({
                "PySide6",
                "pyside_bdo_gui",
                "bdo_music_composer.project",
                "bdo_music_composer.ui",
            }),
        )

    def test_small_infrastructure_owners_remain_qt_free(self) -> None:
        self.assert_forbidden_imports(
            (
                ROOT / "bdo_music_composer/app/application_config.py",
                ROOT / "bdo_music_composer/app/game_profile_provider.py",
                ROOT / "bdo_music_composer/editor/interval_index.py",
            ),
            frozenset({
                "PySide6",
                "pyside_bdo_gui",
                "timeline_canvas",
                "piano_roll_canvas",
                "midi_note_editor",
                "bdo_codec",
                "bdo_export",
                "export_workflow",
                "bdo_music_composer.project",
                "bdo_music_composer.ui",
            }),
        )

    def test_packaged_non_ui_owners_remain_qt_free(self) -> None:
        qt_audio_adapters = {
            ROOT / "bdo_music_composer/audio/bdo_realtime_audio.py",
            ROOT / "bdo_music_composer/audio/reference_audio_controller.py",
        }
        paths = (
            _python_files("bdo_music_composer/app")
            + tuple(
                path
                for path in _python_files("bdo_music_composer/audio")
                if path not in qt_audio_adapters
            )
            + _python_files("bdo_music_composer/core")
            + _python_files("bdo_music_composer/editor")
            + _python_files("bdo_music_composer/export")
            + _python_files("bdo_music_composer/research")
            + _python_files("bdo_music_composer/transcription")
        )
        self.assert_forbidden_imports(
            paths,
            frozenset({"PySide6", "bdo_music_composer.ui.main_window"}),
        )

    def test_packaged_ui_components_do_not_import_composition_root(self) -> None:
        paths = _python_files("bdo_music_composer/ui")
        required_nested_paths = {
            ROOT / "bdo_music_composer/ui/dialogs/application_settings_dialog.py",
            ROOT / "bdo_music_composer/ui/dialogs/release_notes_dialog.py",
            ROOT / "bdo_music_composer/ui/editor/timeline_canvas.py",
            ROOT / "bdo_music_composer/ui/theme/fluent_theme.py",
        }
        self.assertTrue(
            required_nested_paths.issubset(paths),
            "recursive UI scan must include dialogs and theme subpackages",
        )
        self.assert_forbidden_imports(
            paths,
            frozenset({"bdo_music_composer.ui.main_window"}),
        )

    def test_packaged_initializers_are_inert(self) -> None:
        initializers = tuple(sorted(
            (ROOT / "bdo_music_composer").rglob("__init__.py")
        )) + (ROOT / "bdo_common/__init__.py",)
        self.assertTrue(initializers)
        for path in initializers:
            tree = ast.parse(
                path.read_text(encoding="utf-8-sig"),
                filename=str(path),
            )
            executable_nodes = [
                (type(node).__name__, node.lineno)
                for node in tree.body
                if not (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                )
            ]
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(
                    executable_nodes,
                    [],
                    "package initializers must stay inert: import concrete "
                    "owners instead of aggregating or eagerly importing them",
                )

    def test_main_gui_does_not_bypass_export_workflow(self) -> None:
        self.assert_forbidden_imports(
            (ROOT / "bdo_music_composer/ui/main_window.py",),
            frozenset({"bdo_codec", "bdo_export"}),
        )

    def test_focused_owners_keep_functions_within_review_budget(self) -> None:
        budgets = {
            "bdo_music_composer/editor/editor_import.py": 90,
            "bdo_music_composer/editor/game_score_model.py": 80,
            "bdo_music_composer/app/application_config.py": 45,
            "bdo_music_composer/app/game_profile_provider.py": 25,
            "bdo_music_composer/app/home_catalog.py": 80,
            "bdo_music_composer/editor/interval_index.py": 75,
            "bdo_music_composer/editor/preview_midi_writer.py": 90,
            "bdo_music_composer/transcription/transcription_commit_plan.py": 90,
            "bdo_export/source_reuse.py": 90,
            "bdo_music_composer/export/export_workflow.py": 100,
            "bdo_music_composer/export/export_verification.py": 100,
            "bdo_music_composer/project/project_schema.py": 95,
            "bdo_music_composer/app/project_document.py": 100,
            "bdo_music_composer/project/project_persistence.py": 100,
            "bdo_music_composer/export/bdo_validation.py": 90,
        }
        for relative_path, budget in budgets.items():
            with self.subTest(path=relative_path):
                self.assert_function_span_budget(ROOT / relative_path, budget)

    def test_known_ui_hotspots_do_not_grow_while_they_are_decomposed(self) -> None:
        for relative_path, budget in {
            "bdo_music_composer/ui/main_window.py": 450,
            "bdo_music_composer/ui/editor/timeline_canvas.py": 375,
        }.items():
            with self.subTest(path=relative_path):
                self.assert_function_span_budget(ROOT / relative_path, budget)

    def test_typed_transaction_hosts_stay_thin(self) -> None:
        spans = dict(
            _function_spans(ROOT / "bdo_music_composer/ui/main_window.py")
        )
        budgets = {
            "_prepare_transcription_commit_tracks": 60,
            "_build_transcription_commit_plan": 65,
            "_restore_transcription_track_checkpoint": 30,
            "_log_transcription_commit_failure": 15,
            "_refresh_transcription_commit_views": 30,
            "_finish_transcription_commit": 60,
            "_apply_transcription_commit_plan": 70,
            "_commit_note_editor": 80,
            "_load_project": 40,
            "_commit_project_load": 165,
            "_ensure_autosave_project": 50,
            "_flush_autosave": 80,
        }
        for function_name, budget in budgets.items():
            with self.subTest(function=function_name):
                self.assertIn(function_name, spans)
                self.assertLessEqual(spans[function_name], budget)


if __name__ == "__main__":
    unittest.main()
