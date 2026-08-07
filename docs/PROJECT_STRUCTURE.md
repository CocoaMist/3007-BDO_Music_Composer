# Project structure

The repository root is intentionally an entry-only surface. `main.py` is the
only root Python module; application behavior belongs to a package, and
operational commands belong in `scripts/` or `tools/`.

## Dependency direction

```text
main.py
  -> bdo_music_composer.ui
  -> application workflows/controllers
  -> editor, audio, transcription, project, and export domains
  -> bdo_export adapter
  -> bdo_codec wire format
```

Package `__init__.py` files remain inert. Import concrete owner modules rather
than adding aggregate imports or recreating root compatibility shims.

## Application package

`bdo_music_composer/` is split by responsibility:

- `app/` — application configuration, metadata, crash logging, game-profile
  access, conversion controllers, project-load composition, bounded home
  discovery, and dormant internal update owners.
- `core/` — Qt-free application infrastructure: conversion settings, paths,
  game-profile data, program translations, and credits.
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

The desktop composition root is
`bdo_music_composer/ui/main_window.py`. It may re-export implementation owners
needed by the current UI tests, but other package modules must not import it.

## Independent packages

- `bdo_common/` — shared atomic I/O and track-effect wire semantics required by
  independent packages; it imports neither the desktop application nor Qt.
- `bdo_midi/` — independent MIDI parser, immutable note model, mappings, and
  pure transforms.
- `bdo_codec/` — independent BDO v9 document model, reader/writer, ICE, and
  structure validation.
- `bdo_export/` — editor/MIDI adaptation to canonical BDO documents.
- `optimization/` — extensible optimizer; `builtin.py` is the production
  pipeline and `registry.py` is the extension boundary.

These packages remain independent rather than being nested under the desktop
application package.

## Entrypoints and support directories

- `main.py` — the sole root Python entry point for desktop startup, command-line
  conversion dispatch, and packaged self-tests.
- `scripts/` — maintained operator and release commands. The external NDJSON
  bridge is `scripts/wpf_sidecar.py`.
- `tools/` — developer-only audits, benchmarks, evidence preparation, and the
  repository-structure gate.
- `tests/` — regression and executable architecture contracts.
- `assets/` and `data/` — packaged resources and mappings.
- `docs/` — current contracts, evidence, and historical records.
- `packaging/windows/` — reproducible PyInstaller configuration.
- `packaging/developer_sdk/` — deterministic, privacy-filtered source SDK
  builder and its packaging contract.

The retired root optimizer and transcription-widget facades are intentionally
gone. Import `optimization` and
`bdo_music_composer.ui.transcription.transcription_editor_qt` directly.

## Placement rules

1. Never add another root Python module. Extend an existing owner or place a
   focused owner in the matching `bdo_music_composer/` domain.
2. Supported commands go in `scripts/`; developer-only diagnostics go in
   `tools/`. List new files in the directory README.
3. Do not add package-level re-export hubs or root compatibility shims.
4. Generated outputs, private scores/audio, Owner IDs, local settings, sample
   caches, and downloaded game assets never enter Git history.
5. Preserve visible-range indexing and bounded background work when moving UI,
   audio, or transcription code.

The executable structure gate enforces the single-root-module contract and
rejects retired root imports:

```powershell
.\.venv\Scripts\python.exe tools\check_repository_hygiene.py
.\.venv\Scripts\python.exe -m unittest tests.test_repository_hygiene tests.test_architecture_dependencies tests.test_gui_module_boundaries -v
```

Do not use `git clean -fdX` for cleanup. Ignored paths include user-owned
autosaves, exports, settings, sample caches, private research, and build
environments.
