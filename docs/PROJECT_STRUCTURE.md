# 目录怎么走：根目录只做入口

根目录只放入口和仓库规则，唯一的根 Python 模块是 `main.py`。程序包去 `src/`，
依赖去 `requirements/`，语言指南去 `docs/locales/`，命令去 `scripts/` 或 `tools/`。

## Dependency direction

```text
main.py / installed editable project
  -> src/
  -> bdo_music_composer.ui
  -> application workflows/controllers
  -> editor, audio, transcription, project, and export domains
  -> bdo_export adapter
  -> bdo_codec wire format
```

Package `__init__.py` files remain inert. Import concrete owner modules rather
than adding aggregate imports or recreating root compatibility shims.

## Application package

`src/bdo_music_composer/` is split by responsibility:

- `app/` — application configuration, metadata, crash logging, game-profile
  access, conversion controllers, project-load composition, bounded home
  discovery, the two-path local composition-art workflow, and dormant internal
  update owners.
- `core/` — Qt-free application infrastructure: conversion settings, paths,
  game-profile data, program translations, credits, the canonical content
  boundary, and the bounded PAZ primitive used only by local composition art.
- `audio/` — real-time preview, sample selection/rendering, mixing, lifecycle,
  spectrogram data, and reference-audio control.
- `editor/` — Qt-free editor models, commands, imports, interval indexes,
  musical analysis, articulation, pitch transforms, and game-score projection.
- `export/` — score loading, validation, export preparation, verification, and
  atomic publication. Binary encoding still delegates to `bdo_codec` through
  `bdo_export`.
- `project/` — project schema, lifecycle, persistence, and migrations.
- `research/` — privacy-safe local experiment metadata only.
- `sdk/` — stable Qt-free integration API plus lazy optional UI helpers. Its
  package initializer stays inert; consumers import `core_api` or `ui_api`.
- `transcription/` — analysis, evidence policy, post-processing, harmony,
  instruments, timbre, sessions, and formal commit planning.
- `ui/` — the main-window composition root, runtime localization, and reusable Qt presentation.
  `ui/dialogs/`, `ui/editor/`, `ui/theme/`, and `ui/transcription/` contain
  focused widgets, styling, transcription views, and background Qt workers.
  `ui/global_velocity_gain_qt.py` and `ui/timeline_validation_host.py` keep
  velocity transactions and exact-note validation presentation out of the
  composition root.
  `ui/local_game_art_qt.py` is the image-codec adapter for the Qt-free validated
  local artwork workflow in `app/local_game_art.py`.

The desktop composition root is
`src/bdo_music_composer/ui/main_window.py`. It may re-export implementation owners
needed by the current UI tests, but other package modules must not import it.

## Independent packages

- `src/bdo_common/` — shared atomic I/O and track-effect wire semantics required by
  independent packages; it imports neither the desktop application nor Qt.
- `src/bdo_midi/` — independent MIDI parser, immutable note model, mappings, and
  pure transforms.
- `src/bdo_codec/` — independent BDO v9 document model, reader/writer, ICE, and
  structure validation.
- `src/bdo_export/` — editor/MIDI adaptation to canonical BDO documents.
- `src/optimization/` — extensible optimizer; `builtin.py` is the production
  pipeline and `registry.py` is the extension boundary.

These packages remain independent rather than being nested under the desktop
application package.

## Entrypoints and support directories

- `main.py` — the sole root Python entry point for desktop startup, command-line
  conversion dispatch, and packaged self-tests.
- `pyproject.toml` — editable-install and `src/` package discovery contract.
- `requirements/` — direct dependency groups and the Windows qualification
  closure.
- `scripts/` — maintained operator and release commands. The external NDJSON
  bridge is `scripts/wpf_sidecar.py`.
- `tools/` — developer-only audits, benchmarks, evidence validation, and the
  repository-structure gate. It contains no client-audio extraction or
  conversion command.
- `tests/` — regression and executable architecture contracts.
- `assets/` and `data/` — packaged resources and mappings.
- `docs/` — current contracts, evidence, and historical records.
- `docs/locales/` — concise user and contributor guides in four languages.
- `packaging/windows/` — reproducible PyInstaller configuration.
- `packaging/developer_sdk/` — deterministic, privacy-filtered source SDK
  builder and its packaging contract.

The retired root optimizer and transcription-widget facades are intentionally
gone. Import `optimization` and
`bdo_music_composer.ui.transcription.transcription_editor_qt` directly.

## Placement rules

1. Never add another root Python module. Extend an existing owner or place a
   focused owner in the matching `src/bdo_music_composer/` domain.
2. Supported commands go in `scripts/`; developer-only diagnostics go in
   `tools/`. List new files in the directory README.
3. Do not add package-level re-export hubs or root compatibility shims.
4. Generated outputs, private scores/audio, Owner IDs, local settings, sample
   caches, and downloaded game assets never enter Git history.
5. Preserve visible-range indexing and bounded background work when moving UI,
   audio, or transcription code.
6. Apply [`CONTENT_BOUNDARY.md`](CONTENT_BOUNDARY.md) to every audio source or
   client-resource extension. Client-audio extraction/conversion tools do not
   belong in any public directory.

The executable structure gate enforces the single-root-module contract and
rejects retired root imports:

```powershell
.\.venv\Scripts\python.exe tools\check_repository_hygiene.py
.\.venv\Scripts\python.exe -m unittest tests.test_repository_hygiene tests.test_architecture_dependencies tests.test_gui_module_boundaries -v
```

Do not use `git clean -fdX` for cleanup. Ignored paths include user-owned
autosaves, exports, settings, sample caches, private research, and build
environments.

Historical root-local caches and build outputs may be moved intact under the
ignored `.work/legacy/` holding area. This is a recoverable organization step,
not permission to delete user data. Active application data remains under the
platform user-data directory; release builds recreate their output directory
only when explicitly requested.
