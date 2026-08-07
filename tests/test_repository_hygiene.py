from __future__ import annotations

from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
import unittest

from tools.check_repository_hygiene import (
    EXPECTED_ROOT_MODULES,
    PRODUCTION_DIRECTORIES,
    ROOT_MODULE_BUDGET,
    STANDALONE_ROOT_MODULES,
    forbidden_path_errors,
    retired_document_reference_errors,
    retired_reference_errors,
    root_module_errors,
    validate_repository,
)


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_current_source_tree_is_clean_and_discoverable(self) -> None:
        self.assertEqual(validate_repository(ROOT), [])

    def test_ci_compile_targets_use_canonical_existing_modules(self) -> None:
        workflow = (ROOT / ".github/workflows/windows-ci.yml").read_text(
            encoding="utf-8"
        )
        compile_line = next(
            line.strip()
            for line in workflow.splitlines()
            if " -m py_compile " in line
        )
        targets = compile_line.split(" -m py_compile ", 1)[1].split()
        self.assertEqual(
            targets,
            [
                "main.py",
                "bdo_music_composer\\core\\project_paths.py",
                "bdo_music_composer\\ui\\main_window.py",
                "bdo_music_composer\\ui\\i18n.py",
            ],
        )
        self.assertTrue(all((ROOT / target).is_file() for target in targets))

    def test_private_and_generated_artifacts_are_rejected(self) -> None:
        errors = forbidden_path_errors(
            (
                PurePosixPath("dist/BDO-Music-Composer.exe"),
                PurePosixPath("auto_save/private-score.bdo"),
                PurePosixPath("tests/__pycache__/test_x.pyc"),
                PurePosixPath("tools/midi-to-bdo/private.mid"),
            )
        )
        self.assertEqual(len(errors), 4)

    def test_standalone_root_modules_have_explained_roles(self) -> None:
        self.assertEqual(
            set(STANDALONE_ROOT_MODULES),
            {"main.py"},
        )
        self.assertTrue(all(STANDALONE_ROOT_MODULES.values()))

    def test_gitignore_protects_private_inputs_and_local_caches(self) -> None:
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (
            "*.bdo",
            "*.mid",
            "*.wav",
            "*.wem",
            "*.bnk",
            "*.paz",
            "*.log",
            "/data/releases/release_notes.json",
            ".mypy_cache/",
            ".ruff_cache/",
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, ignore_text)

    def test_application_package_is_in_the_production_graph(self) -> None:
        self.assertIn("bdo_music_composer", PRODUCTION_DIRECTORIES)
        actual_root_modules = {
            path.name for path in ROOT.glob("*.py")
        }
        self.assertLessEqual(len(actual_root_modules), ROOT_MODULE_BUDGET)
        self.assertEqual(actual_root_modules, EXPECTED_ROOT_MODULES)

    def test_root_budget_violation_is_reported_without_crashing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = tuple(
                PurePosixPath(f"module_{index}.py")
                for index in range(ROOT_MODULE_BUDGET + 1)
            )
            for path in paths:
                (root / path.name).write_text(
                    f'"""Synthetic module {path.stem}."""\n',
                    encoding="utf-8",
                )

            errors = root_module_errors(root, paths)

        self.assertTrue(
            any("exceeds" in error and "budget" in error for error in errors),
            errors,
        )

    def test_retired_import_patch_and_path_references_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {
                PurePosixPath("bad_import.py"): (
                    "from editor_models import TrackState\n"
                ),
                PurePosixPath("bad_editor_surface.py"): (
                    "from timeline_canvas import TimelineCanvas\n"
                ),
                PurePosixPath("bad_version.py"): (
                    "from version import __version__\n"
                ),
                PurePosixPath("bad_patch.py"): (
                    'TARGET = "editor_import.prepare_midi_import"\n'
                ),
                PurePosixPath("bad_path.py"): (
                    'SOURCE = "fluent_theme.py"\n'
                ),
            }
            for path, source in sources.items():
                (root / path.name).write_text(source, encoding="utf-8")

            errors = retired_reference_errors(root, sources)

        self.assertEqual(len(errors), 5, errors)

    def test_current_docs_reject_retired_paths_but_history_is_preserved(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = PurePosixPath("docs/current.md")
            canonical = PurePosixPath("docs/canonical.md")
            historical = PurePosixPath("docs/history/old.md")
            for path, text in (
                (current, "Use `editor_models.py`."),
                (
                    canonical,
                    "Use `bdo_music_composer/editor/editor_models.py`.",
                ),
                (historical, "Historically used `editor_models.py`."),
            ):
                disk_path = root.joinpath(*path.parts)
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                disk_path.write_text(text, encoding="utf-8")

            errors = retired_document_reference_errors(
                root,
                (current, canonical, historical),
            )

        self.assertEqual(
            errors,
            ["docs/current.md: documents retired root paths: editor_models.py"],
        )


if __name__ == "__main__":
    unittest.main()
