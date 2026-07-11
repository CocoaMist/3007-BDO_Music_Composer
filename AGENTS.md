# AGENTS.md — AI and contributor operating guide

Read this file before editing the repository. Then read `docs/AI_CONTEXT.md` for the task-specific routing map.

## Mission

BDO Music Composer is an unofficial PySide6 MIDI editor and Black Desert music-score exporter. Correctness means preserving the user's current `TrackState`/`Note` model through preview, optimization, autosave, and BDO v9 export without silently falling back to the original MIDI.

## Start here

1. `README.md` — product scope, setup, limitations, and public-release warnings.
2. `docs/ARCHITECTURE.md` — components and end-to-end data flow.
3. `docs/AI_CONTEXT.md` — change routing, invariants, and validation matrix.
4. Relevant domain reference under `docs/` only after the three files above.

## Commands

```powershell
# Run the desktop app
.\.venv\Scripts\python.exe main.py

# Full regression suite
.\.venv\Scripts\python.exe -m unittest discover -s tests -q

# Syntax check for primary entry points
.\.venv\Scripts\python.exe -m py_compile main.py project_paths.py pyside_bdo_gui.py i18n.py

# Rebuild Windows one-file executable
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

## Architectural boundaries

- `pyside_bdo_gui.py`: UI widgets, mutable editor state, autosave, conversion orchestration. It is large; keep new domain logic out when a focused module exists.
- `optimization/`: pure-ish, extensible optimization subsystem. `builtin.py` is the production pipeline and `registry.py` is the extension boundary. Game-safe mode must preserve structural invariants.
- `bdo_midi_optimizer.py`: compatibility facade only; do not add new algorithm logic here.
- `bdo_music_theory.py`, `bdo_techniques.py`, `bdo_articulation_profiles.py`, `bdo_lyrics.py`: analysis and semantic recommendations.
- `bdo_realtime_audio.py`: real-time preview, sample caching, Qt audio-thread lifecycle. Do not add disk I/O to the callback path.
- `bdo_sample_renderer.py`: offline sample-map selection and rendering helpers.
- `tools/midi-to-bdo/midi2bdo.py`: vendored MIDI parser, BDO v9 binary writer, ICE encryption. Treat binary layout changes as high risk.
- `i18n.py`: exact-source runtime catalogs. Chinese UI literals are source keys; add translations for new fixed UI text.
- `project_paths.py`: source vs. frozen-resource paths. In a one-file build, writable output must not target `sys._MEIPASS`.

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
- Large piano-roll/timeline paint paths must remain visible-range indexed and batched.
- PyInstaller must include `assets/ui/timeline_background.png`, `assets/icons/app_icon.png`, and `data/mappings/bdo_wwise_midi_map.json`.
- User data, Owner IDs, game audio, exports, autosaves, and local config never belong in the executable or Git history.

## Change routing and required tests

| Change | Minimum validation |
|---|---|
| UI/layout only | `py_compile`, full unit suite, offscreen widget smoke test |
| Note editing/selection | editor smoke test plus export round trip |
| Optimizer/theory/articulation | optimizer tests and deterministic/idempotence checks |
| Audio engine | real-time audio tests; check callback allocations/I/O |
| Serializer/export | `tests/test_bdo_export_roundtrip.py` and binary structure checks |
| Localization | `tests/test_i18n_catalog.py` plus offscreen language-switch smoke test |
| Packaging/resources | clean PyInstaller build and 10+ second startup test |

## Repository safety

- Preserve unrelated working-tree changes. Never use `git reset --hard` or blanket checkout.
- Do not commit `out/`, `auto_save/`, `dist/`, `build/`, `.pyside_bdo_gui.json`, ZIP releases, or extracted game assets.
- BDO score files may expose Owner ID and character name. Treat them as private.
- Mapping/manifests may contain machine-local source paths. Do not add new personal paths; use configuration or environment variables.
- Do not invent a license or upstream permission. Public release is blocked until the maintainer adds a root `LICENSE` and verifies vendored-code licensing.

## Style

- Python 3.12; prefer type hints and small helpers.
- Keep binary constants named and documented. Avoid unexplained magic offsets.
- Use `pathlib.Path` for filesystem paths.
- Use `apply_patch` for text changes and preserve UTF-8.
- Comments should explain format/game constraints, not restate code.

## Definition of done

A change is done only when behavior is implemented, relevant tests pass, no private/generated artifacts are introduced, docs are updated when interfaces or invariants change, and the executable is rebuilt only when the user requests or needs a distributable artifact.
