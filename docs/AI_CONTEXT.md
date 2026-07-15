# AI context and change map

This document helps an AI agent find the correct subsystem without scanning every research file.

## Task router

| User request | Read first | Likely edit |
|---|---|---|
| Main window/timeline UI | `TimelineCanvas`, `MidiToBdoWindow._build_*` | `pyside_bdo_gui.py` |
| Piano-roll behavior | `PianoRollCanvas`, `MidiNoteEditorDialog` | `pyside_bdo_gui.py` |
| MIDI optimization | package README, configs/reports/tests | `optimization/` |
| Optimizer packages / Marnian | `optimization/README.md`, `docs/MARNIAN_MUSE_OPTIONAL_BOUNDARY.md` | `optimization/plugin_api.py`, `optimization/plugin_loader.py`, `optimization/plugin_host.py` |
| Articulation recommendation | profile + technique registry | `bdo_articulation_profiles.py`, `bdo_techniques.py` |
| Harmony/role analysis | theory context | `bdo_music_theory.py` |
| Lyrics | lyric expression mode | `bdo_lyrics.py` |
| Preview/audio timing | engine and tests | `bdo_realtime_audio.py` |
| Sample selection/offline render | renderer and mapping | `bdo_sample_renderer.py` |
| BDO export/binary format | export round-trip test + serializer | `tools/midi-to-bdo/midi2bdo.py` |
| Game rules / conversion issues | profile + validation tests | `bdo_profile.py`, `bdo_validation.py`, `data/profiles/` |
| BDO score inspection / comparison | score snapshot tests | `bdo_score.py`, `scripts/inspect_bdo.py` |
| Audio A/B research | coverage/alignment tests | `bdo_audio_research.py`, `bdo_experiments.py` |
| Localization | catalog tests | `i18n.py` |
| Windows build | spec/build script/path split | `packaging/windows/`, `project_paths.py` |

## Source-of-truth hierarchy

1. Automated tests for behavior already locked down.
2. Game-saved score comparisons and decoded mapping evidence.
3. `docs/NOTE_ARTICULATION_TRANSPOSE_ALGORITHM_LOCK.md` for locked algorithm decisions.
4. Domain notes under `docs/`.
5. Comments and UI copy.

Do not promote an inference to “verified” without game evidence.

## Important symbols

- `TrackState`: mutable track container.
- `Note`: immutable five-field note tuple from `midi2bdo`.
- `TimelineCanvas`: compact overview and main transport.
- `PianoRollCanvas`: per-note editing surface.
- `MidiNoteEditorDialog`: draft lifecycle and track-only playback.
- `MidiOptimizeDialog`: preview/report/apply workflow.
- `OptimizerConfig`: built-in optimizer behavior contract.
- `OptimizationRequest` / `OptimizationPreview`: stable optimizer-package API.
- `discover_host_algorithms`: unified built-in and `.bdoopt` discovery boundary.
- `BdoRealtimeAudioEngine`: preload, event schedule, voice pool, Qt output.
- `channel_groups_to_bdo`: canonical model-to-BDO conversion.
- `build_bdo_binary`: plaintext binary layout.
- `encrypt_bdo`: v9 prefix and ICE encryption.
- `Localizer`: exact-source widget translation.

## Common traps

- Re-reading the source MIDI during export discards manual editor changes.
- `duration_scale` must be folded into note durations before serialization.
- A BDO drum track is not a normal melodic track; avoid double GM remapping.
- `Path("")` resolves to the current directory; explicitly test empty configured paths.
- `sys._MEIPASS` is read-only/temporary from the app's perspective; do not write exports there.
- Qt widgets can store non-ASCII dynamic properties incorrectly on some Windows locale paths; localization keeps source strings in Python `WeakKeyDictionary` storage.
- One-file PyInstaller launches a parent and child process; stop both during startup tests before rebuilding.
- `out/` may still contain historically tracked files even though it is in `.gitignore`; check `git ls-files out` before publishing.

## Validation recipes

### Export

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_export_roundtrip -v
```

Verify edited pitch/start/duration/`ntype`, Owner ID round trip, track marker IDs, empty trailing tracks, and 8-byte alignment.

### Audio

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_realtime_audio -v
```

Look for exact event frames, seek voice restoration, bounded voices, preload deduplication, and limiter stability.

### Optimizer

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_midi_optimizer -v
```

Check scope isolation, pitch/count invariants, deterministic humanization, and preservation of manual `ntype`.

### Localization

Run `tests.test_i18n_catalog`, then create an offscreen `QApplication`, switch `Localizer` through all four locales, and inspect main/settings/editor widgets.

## Public-release checklist

- Add and review a root `LICENSE`.
- Verify and document the license/commit of `tools/midi-to-bdo`.
- Remove tracked `out/` scores and any Owner IDs from Git history.
- Do not publish extracted game audio or PAZ contents.
- Replace personal defaults with empty/configured paths.
- Run tests, `git diff --check`, and a clean PyInstaller startup test.
- Publish binaries through release assets, not Git history.
