#!/usr/bin/env python3
"""Validate repository layout without deleting or rewriting user files.

The check has three deliberately narrow responsibilities:

* reject generated, private, or retired files from the versioned source tree;
* require every root Python module to have a production importer or an
  explicitly documented standalone role;
* require top-level documentation, scripts, and developer tools to appear in
  their directory index.

Ignored local data is outside this check. In particular, this command never
touches exports, autosaves, sample caches, local settings, or build outputs.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PROJECT_STRUCTURE_PATH = PurePosixPath("docs/PROJECT_STRUCTURE.md")

PRODUCTION_DIRECTORIES = frozenset(
    {
        "src",
        "scripts",
        "tools",
    }
)
ROOT_MODULE_BUDGET = 1
EXPECTED_ROOT_MODULES = frozenset({"main.py"})
EXPECTED_ROOT_FILES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "main.py",
        "pyproject.toml",
    }
)
EXPECTED_SOURCE_PACKAGES = frozenset(
    {
        "bdo_codec",
        "bdo_common",
        "bdo_export",
        "bdo_midi",
        "bdo_music_composer",
        "optimization",
    }
)

# These modules are entered externally or preserve a documented import path.
# A new exception must state a concrete public/research role and be documented
# in docs/PROJECT_STRUCTURE.md.
STANDALONE_ROOT_MODULES = {
    "main.py": "desktop and command-line entry point",
}

LOCAL_ONLY_TOP_LEVEL_DIRECTORIES = frozenset(
    {
        ".idea",
        ".venv",
        ".work",
        "auto_save",
        "build",
        "dist",
        "game_art_cache",
        "htmlcov",
        "out",
        "sample_cache",
        "transcription_cache",
    }
)
LOCAL_ONLY_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)
LOCAL_ONLY_PREFIXES = (
    ("tools", ".midi-to-bdo-git-backup"),
    ("tools", "midi-to-bdo"),
)
LOCAL_ONLY_FILENAMES = frozenset(
    {
        ".coverage",
        ".DS_Store",
        ".pyside_bdo_gui.json",
        "coverage.xml",
        "desktop.ini",
        "Thumbs.db",
    }
)
PROHIBITED_CONTENT_TOOL_FILENAMES = frozenset(
    {
        "convert_wem_to_wav.py",
        "extract_bdo_bgm.cpp",
        "extract_bdo_instruments.cpp",
        "extract_wwise_wem.py",
        "list_bdo_paz_audio.cpp",
        "list_bdo_paz_audio.py",
        "validate_paz_key.cpp",
    }
)
PRIVATE_OR_GENERATED_SUFFIXES = frozenset(
    {
        ".7z",
        ".bak",
        ".bdo",
        ".bdoopt",
        ".bdosamples",
        ".bnk",
        ".dll",
        ".exe",
        ".log",
        ".mid",
        ".midi",
        ".orig",
        ".paz",
        ".pyc",
        ".pyd",
        ".pyo",
        ".rar",
        ".rej",
        ".tmp",
        ".wav",
        ".wem",
        ".zip",
    }
)
RETIRED_ROOT_FILES = {
    "TO_AGENT.md": "use AGENTS.md and docs/AI_CONTEXT.md",
    "run_with_log.bat": "use main.py and the privacy-preserving crash logger",
    "application_config.py": "use bdo_music_composer.app.application_config",
    "audio_source_settings.py": "use bdo_music_composer.app.audio_source_settings",
    "conversion_validation_controller.py": (
        "use bdo_music_composer.app.conversion_validation_controller"
    ),
    "crash_logging.py": "use bdo_music_composer.app.crash_logging",
    "game_profile_provider.py": (
        "use bdo_music_composer.app.game_profile_provider"
    ),
    "process_metrics.py": "use bdo_music_composer.app.process_metrics",
    "version.py": (
        "use bdo_music_composer.app.application_metadata"
    ),
    "preview_transport_controller.py": (
        "use bdo_music_composer.audio.preview_transport_controller"
    ),
    "model_revision.py": "use bdo_music_composer.editor.model_revision",
    "project_document.py": (
        "use bdo_music_composer.app.project_document"
    ),
    "project_lifecycle_controller.py": (
        "use bdo_music_composer.project.project_lifecycle_controller"
    ),
    "project_persistence.py": (
        "use bdo_music_composer.project.project_persistence"
    ),
    "project_schema.py": "use bdo_music_composer.project.project_schema",
    "transcription_workspace_controller.py": (
        "use bdo_music_composer.transcription."
        "transcription_workspace_controller"
    ),
    "editor_shortcut_hud.py": (
        "use bdo_music_composer.ui.editor.editor_shortcut_hud"
    ),
    "editor_ui_helpers.py": (
        "use bdo_music_composer.ui.editor.editor_ui_helpers"
    ),
    "midi_note_editor.py": (
        "use bdo_music_composer.ui.editor.midi_note_editor"
    ),
    "piano_roll_canvas.py": (
        "use bdo_music_composer.ui.editor.piano_roll_canvas"
    ),
    "timeline_canvas.py": (
        "use bdo_music_composer.ui.editor.timeline_canvas"
    ),
    "home_widgets.py": "use bdo_music_composer.ui.home_widgets",
    "startup_widgets.py": "use bdo_music_composer.ui.startup_widgets",
    "transcription_ui_helpers.py": (
        "use bdo_music_composer.ui.transcription_ui_helpers"
    ),
    "ui_controls.py": "use bdo_music_composer.ui.ui_controls",
    "ui_notifications.py": "use bdo_music_composer.ui.ui_notifications",
    "editor_commands.py": (
        "use bdo_music_composer.editor.editor_commands"
    ),
    "editor_models.py": "use bdo_music_composer.editor.editor_models",
    "editor_import.py": "use bdo_music_composer.editor.editor_import",
    "interval_index.py": "use bdo_music_composer.editor.interval_index",
    "preview_midi_writer.py": (
        "use bdo_music_composer.editor.preview_midi_writer"
    ),
    "velocity_curve.py": "use bdo_music_composer.editor.velocity_curve",
    "acknowledgements_dialog.py": (
        "use bdo_music_composer.ui.dialogs.acknowledgements_dialog"
    ),
    "application_settings_dialog.py": (
        "use bdo_music_composer.ui.dialogs.application_settings_dialog"
    ),
    "conversion_check_dialog.py": (
        "use bdo_music_composer.ui.dialogs.conversion_check_dialog"
    ),
    "optimizer_dialog.py": (
        "use bdo_music_composer.ui.dialogs.optimizer_dialog"
    ),
    "track_settings_dialogs.py": (
        "use bdo_music_composer.ui.dialogs.track_settings_dialogs"
    ),
    "fluent_theme.py": (
        "use bdo_music_composer.ui.theme.fluent_theme"
    ),
    "main_window_style.py": (
        "use bdo_music_composer.ui.theme.main_window_style"
    ),
}
RETIRED_ROOT_FILES.update(
    {
        "atomic_io.py": "use bdo_common.atomic_io",
        "bdo_articulation_profiles.py": "use bdo_music_composer.editor.bdo_articulation_profiles",
        "bdo_audio_lifecycle.py": "use bdo_music_composer.audio.bdo_audio_lifecycle",
        "bdo_audio_mixing.py": "use bdo_music_composer.audio.bdo_audio_mixing",
        "bdo_audio_research.py": "use bdo_music_composer.audio.bdo_audio_research",
        "bdo_experiments.py": "use bdo_music_composer.research.bdo_experiments",
        "bdo_instrument_adaptation.py": "use bdo_music_composer.editor.bdo_instrument_adaptation",
        "bdo_instrument_lane_art_qt.py": "use bdo_music_composer.ui.editor.bdo_instrument_lane_art_qt",
        "bdo_instrument_samples.py": "use bdo_music_composer.audio.bdo_instrument_samples",
        "bdo_lyrics.py": "use bdo_music_composer.editor.bdo_lyrics",
        "bdo_midi_optimizer.py": "use optimization",
        "bdo_music_theory.py": "use bdo_music_composer.editor.bdo_music_theory",
        "bdo_preview_effects.py": "use bdo_music_composer.audio.bdo_preview_effects",
        "bdo_profile.py": "use bdo_music_composer.core.bdo_profile",
        "bdo_realtime_audio.py": "use bdo_music_composer.audio.bdo_realtime_audio",
        "bdo_sample_pack.py": "use bdo_music_composer.audio.bdo_sample_pack",
        "bdo_sample_renderer.py": "use bdo_music_composer.audio.bdo_sample_renderer",
        "bdo_score.py": "use bdo_music_composer.export.bdo_score",
        "bdo_spectrogram.py": "use bdo_music_composer.audio.bdo_spectrogram",
        "bdo_spectrogram_qt.py": "use bdo_music_composer.ui.transcription.bdo_spectrogram_qt",
        "bdo_techniques.py": "use bdo_music_composer.editor.bdo_techniques",
        "bdo_track_effects.py": "use bdo_common.bdo_track_effects",
        "bdo_transcription.py": "use bdo_music_composer.transcription.bdo_transcription",
        "bdo_transcription_assist.py": "use bdo_music_composer.transcription.bdo_transcription_assist",
        "bdo_transcription_evidence_qt.py": "use bdo_music_composer.ui.transcription.bdo_transcription_evidence_qt",
        "bdo_transcription_harmony.py": "use bdo_music_composer.transcription.bdo_transcription_harmony",
        "bdo_transcription_instruments.py": "use bdo_music_composer.transcription.bdo_transcription_instruments",
        "bdo_transcription_melody_lines.py": "use bdo_music_composer.transcription.bdo_transcription_melody_lines",
        "bdo_transcription_policy.py": "use bdo_music_composer.transcription.bdo_transcription_policy",
        "bdo_transcription_postprocess.py": "use bdo_music_composer.transcription.bdo_transcription_postprocess",
        "bdo_transcription_session.py": "use bdo_music_composer.transcription.bdo_transcription_session",
        "bdo_transcription_timbre.py": "use bdo_music_composer.transcription.bdo_transcription_timbre",
        "bdo_validation.py": "use bdo_music_composer.export.bdo_validation",
        "conversion_settings.py": "use bdo_music_composer.core.conversion_settings",
        "editor_articulation_data.py": "use bdo_music_composer.ui.editor.editor_articulation_data",
        "export_verification.py": "use bdo_music_composer.export.export_verification",
        "export_workflow.py": "use bdo_music_composer.export.export_workflow",
        "game_score_model.py": "use bdo_music_composer.editor.game_score_model",
        "gm_program_translations.py": "use bdo_music_composer.core.gm_program_translations",
        "home_catalog.py": "use bdo_music_composer.app.home_catalog",
        "i18n.py": "use bdo_music_composer.ui.i18n",
        "pitch_transform.py": "use bdo_music_composer.editor.pitch_transform",
        "project_paths.py": "use bdo_music_composer.core.project_paths",
        "pyside_bdo_gui.py": "use bdo_music_composer.ui.main_window",
        "reference_audio_controller.py": "use bdo_music_composer.audio.reference_audio_controller",
        "third_party_credits.py": "use bdo_music_composer.core.third_party_credits",
        "transcription_commit_plan.py": "use bdo_music_composer.transcription.transcription_commit_plan",
        "transcription_editor_qt.py": "use bdo_music_composer.ui.transcription.transcription_editor_qt",
        "transcription_workers.py": "use bdo_music_composer.ui.transcription.transcription_workers",
        "transcription_workspace_qt.py": "use bdo_music_composer.ui.transcription.transcription_editor_qt",
        "wpf_sidecar.py": "use scripts.wpf_sidecar",
    }
)
RETIRED_ROOT_MODULES = frozenset(
    Path(filename).stem
    for filename in RETIRED_ROOT_FILES
    if filename.endswith(".py")
)

INDEX_CONTRACTS = {
    PurePosixPath("docs/README.md"): ("docs", frozenset({".md"})),
    PurePosixPath("scripts/README.md"): ("scripts", None),
    PurePosixPath("tools/README.md"): ("tools", None),
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _disk_path(root: Path, path: PurePosixPath) -> Path:
    return root.joinpath(*path.parts)


def repository_paths(root: Path = ROOT) -> tuple[PurePosixPath, ...]:
    """Return existing tracked and prospective untracked source files."""

    result = subprocess.run(
        (
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ),
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {detail or result.returncode}")

    paths: set[PurePosixPath] = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        decoded = raw_path.decode("utf-8", errors="surrogateescape")
        path = PurePosixPath(decoded.replace("\\", "/"))
        if _disk_path(root, path).is_file():
            paths.add(path)
    return tuple(sorted(paths, key=str))


def _forbidden_reason(path: PurePosixPath) -> str | None:
    parts = path.parts
    lower_parts = tuple(part.lower() for part in parts)
    if path.as_posix() in RETIRED_ROOT_FILES:
        return RETIRED_ROOT_FILES[path.as_posix()]
    if lower_parts[0] in LOCAL_ONLY_TOP_LEVEL_DIRECTORIES:
        return "local/generated top-level directory"
    if any(part in LOCAL_ONLY_DIRECTORY_NAMES for part in lower_parts):
        return "cache directory"
    if any(part.endswith(".egg-info") for part in lower_parts):
        return "generated package metadata"
    if any(lower_parts[: len(prefix)] == prefix for prefix in LOCAL_ONLY_PREFIXES):
        return "ignored local third-party workspace"
    if path.name in LOCAL_ONLY_FILENAMES:
        return "machine-local/generated file"
    if path.name in PROHIBITED_CONTENT_TOOL_FILENAMES:
        return "client-audio extraction/conversion tool violates content boundary"
    if path.suffix.lower() in PRIVATE_OR_GENERATED_SUFFIXES:
        return "private input or generated binary/output"
    return None


def forbidden_path_errors(
    paths: Iterable[PurePosixPath],
) -> list[str]:
    errors: list[str] = []
    for path in paths:
        reason = _forbidden_reason(path)
        if reason:
            errors.append(f"{path.as_posix()}: {reason}")
    return errors


def retired_reference_errors(
    root: Path,
    paths: Iterable[PurePosixPath],
) -> list[str]:
    """Reject executable references to retired root module identities."""

    errors: list[str] = []
    checker_path = PurePosixPath("tools/check_repository_hygiene.py")
    for source in paths:
        if source.suffix.lower() != ".py":
            continue
        disk_source = _disk_path(root, source)
        try:
            tree = ast.parse(
                disk_source.read_text(encoding="utf-8-sig"),
                filename=str(disk_source),
            )
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(
                f"{source.as_posix()}: cannot inspect retired imports: {exc}"
            )
            continue

        references: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                references.update(
                    alias.name.split(".", 1)[0]
                    for alias in node.names
                    if alias.name.split(".", 1)[0] in RETIRED_ROOT_MODULES
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
            ):
                root_module = node.module.split(".", 1)[0]
                if root_module in RETIRED_ROOT_MODULES:
                    references.add(root_module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip().replace("\\", "/")
                references.update(
                    module
                    for module in RETIRED_ROOT_MODULES
                    if module != "version"
                    and value.startswith(f"{module}.")
                    and value != f"{module}.py"
                )
                if source != checker_path:
                    references.update(
                        Path(filename).stem
                        for filename in RETIRED_ROOT_FILES
                        if filename.endswith(".py") and value == filename
                    )
            elif isinstance(node, ast.Call) and node.args:
                function_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                argument = node.args[0]
                if (
                    function_name in {"__import__", "import_module"}
                    and isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                ):
                    root_module = argument.value.split(".", 1)[0]
                    if root_module in RETIRED_ROOT_MODULES:
                        references.add(root_module)
        if references:
            errors.append(
                f"{source.as_posix()}: references retired root modules: "
                + ", ".join(sorted(references))
            )
    return errors


def retired_document_reference_errors(
    root: Path,
    paths: Iterable[PurePosixPath],
) -> list[str]:
    """Keep current contributor docs on canonical package paths."""

    errors: list[str] = []
    retired_python_files = tuple(
        filename
        for filename in RETIRED_ROOT_FILES
        if filename.endswith(".py")
    )
    for source in paths:
        if source.suffix.lower() != ".md":
            continue
        if source == PurePosixPath("CHANGELOG.md"):
            continue
        if source.parts[:2] in {
            ("docs", "history"),
            ("docs", "releases"),
        }:
            continue
        text = _disk_path(root, source).read_text(encoding="utf-8-sig")
        stale = sorted(
            filename
            for filename in retired_python_files
            if re.search(
                rf"(?<![A-Za-z0-9_/\\]){re.escape(filename)}",
                text,
            )
        )
        if stale:
            errors.append(
                f"{source.as_posix()}: documents retired root paths: "
                + ", ".join(stale)
            )
    return errors


def _direct_top_level_imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
        ):
            imports.add(node.module.split(".", 1)[0])
    return frozenset(imports)


def root_module_errors(
    root: Path,
    paths: Iterable[PurePosixPath],
) -> list[str]:
    """Find root modules that have no production owner or documented role."""

    available_paths = tuple(paths)
    root_modules = {
        path.stem: path
        for path in available_paths
        if len(path.parts) == 1 and path.suffix.lower() == ".py"
    }
    errors: list[str] = []
    if len(root_modules) > ROOT_MODULE_BUDGET:
        errors.append(
            f"root Python module count {len(root_modules)} exceeds "
            f"the {ROOT_MODULE_BUDGET}-file budget; place the new owner "
            "inside the appropriate bdo_music_composer subpackage"
        )
    actual_root_files = {path.name for path in root_modules.values()}
    unexpected = sorted(actual_root_files - EXPECTED_ROOT_MODULES)
    missing = sorted(EXPECTED_ROOT_MODULES - actual_root_files)
    if unexpected:
        errors.append(
            "unexpected root Python modules: " + ", ".join(unexpected)
        )
    if missing:
        errors.append(
            "expected root Python modules are missing: " + ", ".join(missing)
        )
    inbound = {module: set() for module in root_modules}

    production_paths = (
        path
        for path in available_paths
        if path.suffix.lower() == ".py"
        and (
            len(path.parts) == 1
            or path.parts[0] in PRODUCTION_DIRECTORIES
        )
    )
    for source in production_paths:
        try:
            imported_modules = _direct_top_level_imports(
                _disk_path(root, source)
            )
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(
                f"{source.as_posix()}: cannot build import graph: {exc}"
            )
            continue
        for module in imported_modules.intersection(root_modules):
            if source != root_modules[module]:
                inbound[module].add(source)

    standalone_names = {
        PurePosixPath(filename).stem
        for filename in STANDALONE_ROOT_MODULES
    }
    for module, importers in sorted(inbound.items()):
        if not importers and module not in standalone_names:
            errors.append(
                f"{root_modules[module].as_posix()}: root module has no "
                "production importer; connect it to its owner, move it to "
                "scripts/tools, or document a real standalone contract"
            )

    structure_path = _disk_path(root, PROJECT_STRUCTURE_PATH)
    structure_text = (
        structure_path.read_text(encoding="utf-8")
        if structure_path.is_file()
        else ""
    )
    for filename, role in STANDALONE_ROOT_MODULES.items():
        path = PurePosixPath(filename)
        if path.stem not in root_modules:
            errors.append(
                f"{filename}: stale standalone-module exception ({role})"
            )
        if f"`{filename}`" not in structure_text:
            errors.append(
                f"{PROJECT_STRUCTURE_PATH.as_posix()}: missing standalone "
                f"module {filename} ({role})"
            )
    return errors


def root_surface_errors(paths: Iterable[PurePosixPath]) -> list[str]:
    """Keep the repository root small and all importable packages in src/."""

    available = tuple(paths)
    root_files = {path.name for path in available if len(path.parts) == 1}
    errors = [
        f"unexpected root file: {name}; move it to its owning directory"
        for name in sorted(root_files - EXPECTED_ROOT_FILES)
    ]
    errors.extend(
        f"missing required root file: {name}"
        for name in sorted(EXPECTED_ROOT_FILES - root_files)
    )
    source_packages = {
        path.parts[1]
        for path in available
        if len(path.parts) == 3
        and path.parts[0] == "src"
        and path.name == "__init__.py"
    }
    if source_packages != EXPECTED_SOURCE_PACKAGES:
        errors.append(
            "src package set mismatch: expected "
            + ", ".join(sorted(EXPECTED_SOURCE_PACKAGES))
            + "; found "
            + ", ".join(sorted(source_packages))
        )
    return errors


def _indexed_members(
    paths: Iterable[PurePosixPath],
    directory: str,
    suffixes: frozenset[str] | None,
    index_path: PurePosixPath,
) -> tuple[PurePosixPath, ...]:
    return tuple(
        path
        for path in paths
        if path.parent == PurePosixPath(directory)
        and path != index_path
        and (suffixes is None or path.suffix.lower() in suffixes)
    )


def index_errors(
    root: Path,
    paths: Iterable[PurePosixPath],
) -> list[str]:
    """Require discoverable top-level directory members."""

    available_paths = tuple(paths)
    errors: list[str] = []
    for index_path, (directory, suffixes) in INDEX_CONTRACTS.items():
        disk_index = _disk_path(root, index_path)
        if not disk_index.is_file():
            errors.append(f"{index_path.as_posix()}: missing directory index")
            continue
        text = disk_index.read_text(encoding="utf-8")
        for member in _indexed_members(
            available_paths,
            directory,
            suffixes,
            index_path,
        ):
            if member.name not in text:
                errors.append(
                    f"{index_path.as_posix()}: missing {member.name}"
                )
    return errors


def markdown_link_errors(
    root: Path,
    paths: Iterable[PurePosixPath],
) -> list[str]:
    """Find broken or repository-escaping local links in source Markdown."""

    repository_root = root.resolve()
    errors: list[str] = []
    for source in paths:
        if source.suffix.lower() != ".md":
            continue
        disk_source = _disk_path(root, source)
        text = disk_source.read_text(encoding="utf-8-sig")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if (
                not target
                or "://" in target
                or target.startswith("mailto:")
            ):
                continue
            resolved = (disk_source.parent / target).resolve()
            try:
                resolved.relative_to(repository_root)
            except ValueError:
                errors.append(
                    f"{source.as_posix()}: link escapes repository: "
                    f"{raw_target}"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"{source.as_posix()}: broken link {raw_target}"
                )
    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    """Return deterministic, human-readable repository hygiene errors."""

    paths = repository_paths(root)
    errors = forbidden_path_errors(paths)
    errors.extend(retired_reference_errors(root, paths))
    errors.extend(retired_document_reference_errors(root, paths))
    errors.extend(root_module_errors(root, paths))
    errors.extend(root_surface_errors(paths))
    errors.extend(index_errors(root, paths))
    errors.extend(markdown_link_errors(root, paths))
    return sorted(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root (defaults to the parent of this script)",
    )
    args = parser.parse_args()
    try:
        errors = validate_repository(args.root.resolve())
    except RuntimeError as exc:
        print(exc)
        return 2
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
