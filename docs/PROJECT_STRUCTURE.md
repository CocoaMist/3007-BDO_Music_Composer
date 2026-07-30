# Project structure

- `main.py` — unified GUI/CLI entry point.
- `pyside_bdo_gui.py` — main-window orchestration, mutable project state, Qt
  worker lifecycle, and compatibility exports.
- `editor_models.py`, `timeline_canvas.py`, `piano_roll_canvas.py`, and
  `midi_note_editor.py` — shared editor state and visible-range editing surfaces.
- `application_settings_dialog.py`, `track_settings_dialogs.py`,
  `conversion_check_dialog.py`, `optimizer_dialog.py`, and
  `acknowledgements_dialog.py` — independently testable dialog domains.
- `reference_audio_controller.py` and `transcription_workers.py` — multimedia
  transport and background-only analysis lifecycles.
- `bdo_transcription_session.py` — candidate review/routing state plus stable
  ID, start-range, and overlap indexes rebuilt only with candidate replacement.
- `model_revision.py`, `conversion_validation_controller.py`,
  `transcription_workspace_controller.py`, `project_lifecycle_controller.py`,
  and `preview_transport_controller.py` — Qt-free revision, validation-cache,
  worker-generation, bounded mixed review history, project-loading, and
  preview-session/command state.
- `i18n.py` — Simplified/Traditional Chinese, English, Japanese, and Korean UI catalogs.
- `optimization/` — extensible optimizer package with built-in pipeline and registry.
- `bdo_midi_optimizer.py` — compatibility facade for the historical optimizer import path.
- `bdo_midi/` — independent MIDI parsing, note model, instrument maps, and transforms.
- `bdo_export/` — MIDI/editor adaptation to canonical BDO v9 codec documents.
- `bdo_codec/` — lossless BDO v9 reader/writer, document model, validation, and ICE.
- Other `bdo_*.py` files — analysis, articulation, lyrics, preview, and rendering modules.
- `assets/` — application-owned UI resources and Windows icon sources.
- `data/mappings/` — runtime BDO/Wwise mappings; manifests are research inputs and are not packaged.
- `scripts/` — command-line conversion and research utilities.
- `tests/` — automated regression tests.
- `README.md` plus `README.zh-CN.md`, `README.en.md`, `README.ja.md`, and
  `README.ko.md` — language hub and complete localized project guides.
- `docs/` — architecture, Agent handoff, format knowledge, algorithms,
  validation notes, optimization roadmap, and UI references.
- `packaging/windows/` — reproducible PyInstaller configuration.
- `build/`, `dist/`, `out/`, `auto_save/` — generated artifacts; not source-controlled.

The Windows one-file build embeds only required runtime resources. External game audio remains user-configured and is never copied into the executable.
