# AGENTS.md — AI and contributor operating guide

Read this file before editing the repository. Then choose a complete localized
README from the root language hub, read `docs/AGENT_HANDOFF.md`, and use
`docs/AI_CONTEXT.md` for the task-specific routing map.

## Mission

BDO Music Composer is an unofficial PySide6 MIDI editor and Black Desert music-score exporter. Correctness means preserving the user's current `TrackState`/`Note` model through preview, optimization, autosave, and BDO v9 export without silently falling back to the original MIDI.

## Start here

1. `README.md` — language selector and Agent entry point.
2. One localized guide under `docs/locales/`: `zh-CN.md`, `en.md`, `ja.md`,
   or `ko.md`.
3. `docs/AGENT_HANDOFF.md` — safe takeover, implementation, validation, and handoff workflow.
4. `docs/ARCHITECTURE.md` — components and end-to-end data flow.
5. `docs/AI_CONTEXT.md` — change routing, invariants, and validation matrix.
6. `docs/README.md` — status-labelled documentation and evidence index.
7. Relevant domain reference under `docs/` only after the files above.

## Commands

```powershell
# Run the desktop app
.\.venv\Scripts\python.exe main.py

# Full regression suite
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -q

# Syntax check for primary entry points
.\.venv\Scripts\python.exe -m py_compile main.py src/bdo_music_composer/core/project_paths.py src/bdo_music_composer/ui/main_window.py src/bdo_music_composer/ui/i18n.py

# Syntax check for packaged application owners
.\.venv\Scripts\python.exe -m compileall -q src

# Repository structure and private/generated artifact guard
.\.venv\Scripts\python.exe tools\check_repository_hygiene.py

# Rebuild Windows one-file executable
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

## Architectural boundaries

- `src/bdo_music_composer/ui/main_window.py`: UI widgets, mutable editor state, and Qt worker lifecycle. It is large; keep new domain logic out when a focused module exists.
- `src/bdo_music_composer/`: packaged application owners split by
  `app/`, `audio/`, `editor/`, `project/`, `transcription/`, and `ui/`.
  Package initializers stay inert; import the concrete owner module directly.
- `src/bdo_music_composer/editor/`: Qt-free shared editor models, transactional
  imports, commands, interval queries, velocity curves, revision tracking, and
  standard-MIDI preview projection.
- `src/bdo_music_composer/app/application_metadata.py`: canonical
  application/repository identity.
- `src/bdo_music_composer/app/release_notes.py`,
  `src/bdo_music_composer/app/update_check.py`,
  `src/bdo_music_composer/ui/update_check_qt.py`, and
  `src/bdo_music_composer/ui/dialogs/release_notes_dialog.py`: dormant internal
  release-history and stable-release-check implementation. Production home and
  startup flows must not expose or invoke it. The optional local
  `data/releases/release_notes.json` record may be absent, stays Git-ignored,
  and is used only by explicit internal tests.
- `src/bdo_music_composer/update/`, `src/bdo_music_composer/ui/self_update_qt.py`, and
  `scripts/generate_update_manifest.py`: production frozen-Windows self-update.
  GitHub and Gitee are mirrors only; the exact manifest bytes must pass the
  embedded RSA-3072 trust root before an artifact URL or version is accepted.
  Source launches and packaged startup self-tests remain network-free.
- `src/bdo_music_composer/ui/dialogs/` and
  `src/bdo_music_composer/ui/theme/`: focused Qt dialogs plus the application-level
  semantic theme. Their package initializers stay inert.
- `src/bdo_music_composer/ui/editor/`: timeline, piano-roll, velocity-lane, note
  editor, shortcut HUD, and focused presentation helpers. Its initializer stays
  inert and paint paths remain visible-range indexed.
- `src/bdo_music_composer/ui/workspace_refresh_qt.py`: focused Qt executor for
  Qt-free workspace refresh plans. Do not duplicate its invalidation sequence in
  the main window.
- `src/bdo_music_composer/ui/performance_metrics.py` and
  `src/bdo_music_composer/ui/performance_probe_qt.py`: opt-in, bounded Windows UI
  latency diagnostics. Production startup must not enable them implicitly.
- `src/bdo_music_composer/export/export_workflow.py`: immutable editor-export snapshots plus atomic output/game-directory publication.
- `src/bdo_music_composer/project/project_persistence.py`: immutable autosave snapshots and background-safe serialization; `src/bdo_music_composer/app/home_catalog.py` owns bounded home-page discovery and reads only its small safe index.
- `src/bdo_common/atomic_io.py`: shared same-directory temporary-write/copy primitives. User-owned destinations must not be truncated in place.
- `src/optimization/`: pure-ish, extensible optimization subsystem. `builtin.py` is the production pipeline and `registry.py` is the extension boundary. Game-safe mode must preserve structural invariants.
- `src/bdo_common/`: inert shared package for Qt-free primitives required by the
  independent codec/export packages. Keep it free of application and UI imports.
- `src/bdo_common/extension_contract.py` and `extension_protocol.py`: fail-closed
  extension negotiation and bounded process-envelope primitives. Trusted
  in-process Python extensions are not a security sandbox.
- `src/bdo_music_composer/editor/bdo_music_theory.py`, `src/bdo_music_composer/editor/bdo_techniques.py`, `src/bdo_music_composer/editor/bdo_articulation_profiles.py`, `src/bdo_music_composer/editor/bdo_lyrics.py`: analysis and semantic recommendations.
- `src/bdo_music_composer/audio/bdo_realtime_audio.py`: real-time preview, sample caching, Qt audio-thread lifecycle. Do not add disk I/O to the callback path.
- `src/bdo_music_composer/audio/bdo_sample_renderer.py`: offline sample-map selection and rendering helpers.
- `src/bdo_music_composer/audio/native_audio_core.py` and
  `bdo_native_audio_core.cpp`: optional Windows native-audio experiment. It must
  reject unsupported effect-bus semantics and remain behind parity/promotion
  gates; benchmark speed alone does not authorize production use.
- `src/bdo_codec/`: independent BDO v9 model, reader/writer, ICE, validation, and CLI. Treat binary layout changes as high risk.
- `src/bdo_midi/`: independent MIDI parser, immutable note model, GM/BDO mappings, and pure note transforms.
- `src/bdo_export/`: editor/MIDI-to-document adapter; all binary output must delegate to `bdo_codec`.
- `src/bdo_music_composer/ui/i18n.py`: exact-source runtime catalogs. Chinese UI literals are source keys; add translations for new fixed UI text.
- `src/bdo_music_composer/core/project_paths.py`: source vs. frozen-resource paths. In a one-file build, writable output must not target `sys._MEIPASS`.

## Non-negotiable invariants

### Editor and export

- `Note` wire shape stays `Note(pitch, vel, start, dur, ntype)` unless a migration is designed and tested.
- Export uses the current editor model (`direct_tracks`), not a re-read of the imported MIDI.
- Manual create/delete/move/resize operations and `ntype=0` edits must survive export.
- Drum-set notes use canonical BDO pitches 48–64 and `ntype=99` where required.
- Marnian mode IDs are base instrument ID plus offsets `0..3` for `basic/stereo/super/superoct`.
- BDO v9 binary fields are little-endian, notes are 20 bytes (`<BBBBdd`), tracks split at 730 notes, each instrument has an empty trailing track, and encrypted payloads are 8-byte aligned.
- Never silently export a non-`/4` meter or a score without a valid Owner ID.

### Optimizer

- Game-safe optimization must not unexpectedly change note count, pitch multiset, instrument mapping, or unrelated tracks.
- Single-track optimization may read full-song context but writes only the target track.
- Existing manual articulations are preserved unless invalid for the selected instrument.
- Deterministic inputs must produce deterministic output.

### Real-time audio

- No file reads, JSON parsing, WAV decoding, or unbounded allocation in the audio callback.
- Sample preload and decode happen before playback or off the GUI/audio thread.
- Voice pool remains bounded; exact event-frame scheduling and limiter behavior are regression tested.
- Preview is approximate when DSP/game A/B evidence is missing; do not label it verified without evidence.

### UI, i18n, and packaging

- Keep Chinese as the source language for existing fixed UI strings; update English, Japanese, and Korean catalogs for new controls.
- Dynamic music data (track names, filenames, note names) must not be translated.
- Every `QMenu` popup must use the application-level semantic theme in
  `src/bdo_music_composer/ui/theme/fluent_theme.py`. Enabled, selected, disabled,
  submenu, and checked states
  must remain readable under the Windows 11 native style plus the fixed dark
  palette. Do not add per-menu stylesheets; preserve the contrast and rendered
  popup regression gates in `tests/test_fluent_theme.py`.
- Large piano-roll/timeline paint paths must remain visible-range indexed and batched.
- PyInstaller must include `assets/ui/timeline_background.png`,
  `assets/icons/app_icon.png`, and
  `data/mappings/bdo_wwise_midi_map.json`. Public packages must exclude the
  optional local `data/releases/release_notes.json` catalog.
- The dormant GitHub update checker has no production UI or startup entry. Only
  explicit internal tests may invoke it. Its implementation must remain
  asynchronous, unauthenticated, and bounded; never send Owner IDs or local
  paths, download/execute a release, or report “current” after a failed
  request. Startup self-tests stay network-free.
- The production self-updater runs only in the frozen Windows application. It
  may send only the public application version, downloads only allow-listed
  HTTPS GitHub/Gitee assets from a valid signed manifest, rejects rollback and
  hash/size/path/protocol mismatches, and stages only under local user data.
  The downloaded new single EXE performs `--apply-update-v1`; the old EXE must
  remain recoverable until the real new GUI reports healthy. Never place the
  release signing private key in this repository, an executable, or Git.
- Public application versions use `major.minor.patch`; a positive fourth
  numeric component is reserved for test revisions such as `1.2.0.1` and
  participates in update precedence after the first three components.
- User data, Owner IDs, game audio, exports, autosaves, and local config never belong in the executable or Git history.
- `docs/CONTENT_BOUNDARY.md` is the fail-closed product contract for client
  resources. Never add client-audio PAZ/WEM listing, extraction, conversion,
  pack-building, download, or distribution support. Optional preview sources
  must be independently licensed and user-selected.
- The optional local `data/releases/release_notes.json` internal record never
  belongs in public Git history or an installation package.

## Change routing and required tests

| Change | Minimum validation |
|---|---|
| UI/layout only | `py_compile`, full unit suite, offscreen widget smoke test |
| Note editing/selection | editor smoke test plus export round trip |
| Optimizer/theory/articulation | optimizer tests and deterministic/idempotence checks |
| Audio engine | real-time audio tests; check callback allocations/I/O |
| Serializer/export | `tests/test_bdo_codec.py`, `tests/test_bdo_export_roundtrip.py`, and binary structure checks |
| Localization | `tests/test_i18n_catalog.py` plus offscreen language-switch smoke test |
| Dormant internal release notes/update check | `tests/test_release_notes.py`, `tests/test_update_check.py`, `tests/test_update_check_qt.py`, `tests/test_release_notes_ui.py`, optional/missing local-record behavior, production-wiring exclusion, Git-history exclusion, and public-package resource exclusion |
| Signed frozen self-update | `tests/test_self_update.py`, `tests/test_self_update_ui.py`, `tests/test_i18n_catalog.py`, source/self-test network exclusion, signed-manifest negative cases, localized update-notes/progress presentation, staged replacement/rollback tests, and frozen startup/update smoke test |
| Packaging/resources | clean PyInstaller build and 10+ second startup test |

## Repository safety

- Preserve unrelated working-tree changes. Never use `git reset --hard` or blanket checkout.
- Never use `git clean -fdX` as generic cleanup: ignored paths include the
  virtual environment, autosaves, exports, local settings, sample caches, and
  private research workspaces.
- Do not commit `out/`, `auto_save/`, `dist/`, `build/`, `.pyside_bdo_gui.json`, ZIP releases, or extracted game assets.
- BDO score files may expose Owner ID and character name. Treat them as private.
- Mapping/manifests may contain machine-local source paths. Do not add new personal paths; use configuration or environment variables.
- Do not invent a license or upstream permission. The root `LICENSE` covers only
  original project code; third-party terms remain in `THIRD_PARTY_NOTICES.md`.
  Public builds must pass the exact-inventory gate in
  `packaging/transcription_release_policy.json`, and any dependency change
  requires a new maintainer review.

## Style

- Python 3.12; prefer type hints and small helpers.
- `main.py` is the only root Python module. New owners belong in a focused
  package; supported commands and developer tools belong in `scripts/` and
  `tools/` and must be listed in their directory `README.md`.
- Canonical version/repository identity lives in
  `src/bdo_music_composer/app/application_metadata.py`; do not recreate root
  compatibility shims.
- Keep binary constants named and documented. Avoid unexplained magic offsets.
- Use `pathlib.Path` for filesystem paths.
- Use `apply_patch` for text changes and preserve UTF-8.
- Comments should explain format/game constraints, not restate code.

## Definition of done

A change is done only when behavior is implemented, relevant tests pass, no private/generated artifacts are introduced, docs are updated when interfaces or invariants change, and the executable is rebuilt only when the user requests or needs a distributable artifact.
