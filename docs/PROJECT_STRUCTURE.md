# Project structure

The repository uses a deliberate hybrid layout:

- `bdo_music_composer/` contains the first packaged application slice;
- the root retains entry points, composition, and domain owners that have not
  yet crossed a clean package boundary;
- independently reusable format/optimization domains remain separate packages;
- scripts, developer tools, documentation, tests, and runtime resources have
  separate indexed directories.

The first migration reduced root Python files from 89 to 69. The next package
migration moved six Qt-free editor owners, then five dialog owners and two
theme owners. A follow-up UI-editor stage moved five related Qt owners into
`bdo_music_composer/ui/editor/`; version/repository identity was then
centralized in `bdo_music_composer/app/application_metadata.py`, reducing the
current budget from 56 to 52. No migration left root compatibility shims:
every production, test, tool, and documented import points at the canonical
owner. This remains a staged migration, not a mechanical `src/` rewrite. A
root of 7–10 files is a long-term direction, not the current structure.

## Dependency direction

```text
Qt composition and widgets
  -> application workflows/controllers
  -> editor and game domain
  -> BDO export adapter
  -> BDO wire codec
```

Project persistence is parallel application infrastructure. Independent
packages must not import the Qt composition root. The executable dependency
rules live in `tests/test_architecture_dependencies.py`.

## Packaged application layer

`bdo_music_composer/` is the canonical namespace for application owners that
already have a clean dependency boundary. Its `__init__.py` files are inert:
they must not eagerly import widgets, start Qt, populate caches, or duplicate
mutable module state.

- `app/` — immutable application/repository metadata, dormant internal release
  notes, pure GitHub stable-release parsing, atomic application configuration,
  audio-source settings, conversion validation orchestration, crash logging,
  lazy game-profile access, and process metrics.
- `audio/` — preview transport state and scheduling coordination.
- `editor/` — Qt-free editor commands, transactional imports, shared models,
  interval indexing, model revision tracking, standard-MIDI projection, and
  velocity curves.
- `project/` — project document planning, lifecycle, immutable persistence,
  schema, and migrations.
- `transcription/` — transcription workspace lifecycle coordination.
- `ui/` — reusable home/startup widgets, UI controls, notification
  presentation, dormant internal QtNetwork update transport, focused dialogs,
  editor surfaces, and application theme ownership. Its `dialogs/`, `editor/`,
  and `theme/` initializers are inert.

The six migrated editor owners are
`bdo_music_composer/editor/editor_commands.py`,
`bdo_music_composer/editor/editor_import.py`,
`bdo_music_composer/editor/editor_models.py`,
`bdo_music_composer/editor/interval_index.py`,
`bdo_music_composer/editor/preview_midi_writer.py`, and
`bdo_music_composer/editor/velocity_curve.py`. The seven migrated UI owners are
`bdo_music_composer/ui/dialogs/acknowledgements_dialog.py`,
`bdo_music_composer/ui/dialogs/application_settings_dialog.py`,
`bdo_music_composer/ui/dialogs/conversion_check_dialog.py`,
`bdo_music_composer/ui/dialogs/optimizer_dialog.py`,
`bdo_music_composer/ui/dialogs/track_settings_dialogs.py`,
`bdo_music_composer/ui/theme/fluent_theme.py`, and
`bdo_music_composer/ui/theme/main_window_style.py`.
The five colocated editor UI owners are
`bdo_music_composer/ui/editor/editor_shortcut_hud.py`,
`bdo_music_composer/ui/editor/editor_ui_helpers.py`,
`bdo_music_composer/ui/editor/timeline_canvas.py`,
`bdo_music_composer/ui/editor/piano_roll_canvas.py`, and
`bdo_music_composer/ui/editor/midi_note_editor.py`.
Application version/repository identity has one canonical owner:
`bdo_music_composer/app/application_metadata.py`. Optional machine-local
internal release history is owned by
`bdo_music_composer/app/release_notes.py`;
`bdo_music_composer/ui/dialogs/release_notes_dialog.py`,
`bdo_music_composer/app/update_check.py`, and
`bdo_music_composer/ui/update_check_qt.py` retain the dormant presentation,
stable-response policy, and asynchronous transport. Production home, startup,
menu, and navigation flows do not construct them; only explicit internal tests
may do so.

Import concrete owners, for example
`bdo_music_composer.project.project_persistence`; do not add aggregate imports
to package initializers and do not recreate the retired root paths.

## Root application layer

### Entrypoints and documented standalone modules

- `main.py` — canonical desktop and command-line entry point.
- `wpf_sidecar.py` — externally hosted NDJSON sidecar entry point.
- `bdo_experiments.py` — privacy-safe local A/B evidence metadata owner.
- `bdo_midi_optimizer.py` — compatibility facade for the historical optimizer
  import path; new production code imports `optimization`.
- `transcription_workspace_qt.py` — compatibility facade for historical
  transcription-widget imports; new code imports `transcription_editor_qt`.

The last two files are facades, not owners. They may be removed only after a
documented breaking-version decision. `tools/check_repository_hygiene.py`
rejects a new root module that has neither a production importer nor an
explicit standalone role here.

### Composition and presentation

- `pyside_bdo_gui.py` — Qt composition root, mutable window/project state,
  worker lifecycle, and compatibility exports.

Focused dialogs and semantic theme ownership now live in the canonical
`bdo_music_composer/ui/dialogs/` and `bdo_music_composer/ui/theme/` packages
listed above, not at the repository root.

### Editor and application workflow

- `bdo_music_composer/ui/editor/` — visible-range timeline, piano-roll,
  velocity-lane, and note-editor surfaces plus their focused presentation
  helpers.
- `home_catalog.py` — bounded home discovery over the small safe project index.

The Qt-free editor owners now live in `bdo_music_composer/editor/` as listed
above. The standard-MIDI projection remains separate from the BDO export path.

### Game score and export workflow

- `game_score_model.py` — formal/preview scope, game-native velocity,
  serialized instrument identity, and shared instrument mixer behavior.
- `export_workflow.py` — immutable editor export requests, preparation, and
  atomic output/game-directory publication.
- `export_verification.py` — Qt-free semantic, physical-layout, source-reuse,
  and publication consistency diagnostics.
- `bdo_validation.py` — ordered game-rule validation stages.

### Audio and transcription

- `bdo_realtime_audio.py`, `bdo_sample_renderer.py`,
  `bdo_instrument_samples.py`, and the smaller `bdo_audio_*` modules own
  preview audio, sample selection, mixing, and lifecycle.
- `bdo_transcription.py` and focused `bdo_transcription_*` modules own
  transcription evidence, post-processing, harmony, instruments, timbre,
  sessions, and policy.
- `transcription_commit_plan.py` owns pure formal-commit planning;
  `transcription_workers.py` owns background execution.

Other top-level `bdo_*.py` files are focused analysis, articulation, lyrics,
profile, score inspection, preview-effect, or research owners. The complete
behavior-to-owner routing table is in `AI_CONTEXT.md`; ownership and extraction
rules are in `AI_EDITING_GUIDE.md`.

## Independent packages

- `bdo_midi/` — independent MIDI parser, immutable note model, mappings, and
  pure transforms.
- `bdo_codec/` — independent BDO v9 wire model, reader/writer, ICE, and
  validation.
- `bdo_export/` — MIDI/editor adaptation to canonical BDO v9 documents;
  `source_reuse.py` owns lossless source matching and final-document summaries.
- `optimization/` — extensible optimizer package; `builtin.py` is the
  production pipeline and `registry.py` is the extension boundary.

These packages keep their current independent boundaries even if the
application layer is packaged later.

## Support directories

- `assets/` — application-owned UI resources and Windows icon sources.
- `data/mappings/` — packaged BDO/Wwise mappings.
- `data/manifests/` and `data/profiles/` — research manifests and runtime game
  constraints as documented by their callers.
- `data/releases/release_notes.json` — optional, machine-local, Git-ignored
  internal release-history record. It may be absent and must enter neither
  public Git history nor an installation package.
- `docs/` — indexed architecture, domain contracts, evidence, roadmaps, and
  historical records; start at [`README.md`](README.md).
- `scripts/` — indexed maintained CLI, release, and controlled validation
  entry points; see [`../scripts/README.md`](../scripts/README.md).
- `tools/` — indexed developer-only audits, benchmarks, and local evidence
  utilities; see [`../tools/README.md`](../tools/README.md).
- `tests/` — automated regression and architecture guards.
- `packaging/windows/` — reproducible PyInstaller configuration.

## Local-only workspace data

The following paths are intentionally ignored and are not source:

- `.venv/` and `__pycache__/` — reproducible runtime/bytecode caches.
- `build/` and `dist/` — generated packaging outputs.
- `out/` — exports, reports, screenshots, and crash diagnostics.
- `auto_save/` — private recovery projects and score data.
- `sample_cache/`, `transcription_cache/`, and game-art caches — local derived
  media.
- `.pyside_bdo_gui.json` and `.idea/` — machine-local settings.
- `tools/midi-to-bdo/` and its backup — ignored historical local tooling.

Do not use `git clean -fdX` as a repository-cleanup shortcut: it would remove
several of these user-owned or expensive-to-rebuild paths together.

## Placement rules

1. Add behavior to its current owner before creating another file.
2. Root Python files have a hard budget of 52. A new root module needs a
   production importer and must replace or migrate another root owner.
   External entry points,
   compatibility facades, and research owners require an explicit reason in
   this document and in the hygiene checker.
3. Supported operational commands belong in `scripts/`; developer-only audits,
   benchmarks, extraction, and data preparation belong in `tools/`.
4. New top-level documents, scripts, and tools must be listed in their
   directory `README.md`.
5. Generated outputs, private scores/audio, Owner IDs, local configuration, and
   downloaded game assets never enter Git history.
6. Compatibility facades only re-export one implementation; they do not copy
   algorithms or mutable state.

Run the structural gate after changing files or ownership:

```powershell
.\.venv\Scripts\python.exe tools\check_repository_hygiene.py
.\.venv\Scripts\python.exe -m unittest tests.test_repository_hygiene tests.test_architecture_dependencies tests.test_gui_module_boundaries -v
```

## Next migration boundary

The two-stage second package migration is complete. Future rounds should move
one coherent domain at a time—such as editor canvases, preview audio, or
transcription—only after its dependency direction is explicit. Reaching 7–10
root files is a long-term direction rather than a declared completion target
for the current stage. Import public identity from
`bdo_music_composer.app.application_metadata`; do not recreate a parallel root
owner. Retain
`bdo_midi/`, `bdo_export/`, `bdo_codec/`, and `optimization/` as independent
packages. Add a compatibility facade only for a documented external import
contract; internal historical paths must be updated directly.
