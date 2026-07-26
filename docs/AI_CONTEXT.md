# AI context and change map

This document helps an AI agent find the correct subsystem without scanning every research file.

## Task router

| User request | Read first | Likely edit |
|---|---|---|
| Main window/timeline UI | `TimelineCanvas`, `MidiToBdoWindow._build_*`, `fluent_theme.py` | `pyside_bdo_gui.py`, `fluent_theme.py` |
| Home page/unified projects | `scan_game_scores`, `scan_local_projects`, `MidiToBdoWindow._build_home_page` | `pyside_bdo_gui.py`, `i18n.py` |
| Open/edit a BDO v9 score | `read_bdo_score`, `track_states_from_bdo_score`, `MidiToBdoWindow._load_bdo_info` | `bdo_score.py`, `pyside_bdo_gui.py` |
| Piano-roll behavior | `PianoRollCanvas`, `MidiNoteEditorDialog` | `pyside_bdo_gui.py` |
| Instrument-specific editor lanes/roles | verified vs preview vs recommended boundaries | `bdo_instrument_adaptation.py`, `pyside_bdo_gui.py` |
| Timeline instrument artwork | packaged original icons, local override, vector fallback | `assets/README.md`, `bdo_instrument_lane_art_qt.py`, `pyside_bdo_gui.py` |
| Local game-art import | allow-listed PAZ/CSS/sprite import, local cache only | `tools/import_bdo_game_art.py` |
| Timeline process telemetry | current-process CPU/RAM plus callback-owned audio counters | `process_metrics.py`, `MidiToBdoWindow._build_performance_strip` |
| Local homepage examples | sanitized local manifest, attribution, no bundled user MIDI | `tools/install_example_project.py`, `scan_example_projects` |
| MIDI optimization | package README, configs/reports/tests | `optimization/` |
| Optimizer packages / Marnian | `optimization/README.md`, `docs/MARNIAN_MUSE_OPTIONAL_BOUNDARY.md` | `optimization/plugin_api.py`, `optimization/plugin_loader.py`, `optimization/plugin_host.py` |
| Articulation recommendation | profile + technique registry | `bdo_articulation_profiles.py`, `bdo_techniques.py` |
| Harmony/role analysis | theory context | `bdo_music_theory.py` |
| Optional DeepSeek/LLM suggestions | `docs/DEEPSEEK_INTEGRATION.md`, privacy boundary | future focused `ai_assist/` provider package; never deterministic pipelines |
| Lyrics | lyric expression mode | `bdo_lyrics.py` |
| Preview/audio timing | shared lifecycle, engine and tests | `bdo_audio_lifecycle.py`, `bdo_realtime_audio.py`, `bdo_sample_renderer.py` |
| Game mixer/effects | track volume, Aux/master byte layers, raw compatibility | `bdo_track_effects.py`, `docs/BDO_MIXER_EFFECTS.md` |
| Transcription backend/cache/re-decode | `TranscriptionBackend`, `EvidenceDescriptor`, cache tests | `bdo_transcription.py` |
| Fragment annotation/cleanup/lineage | `postprocess_frame_events`, v3 benchmark protocol, postprocess tests | `bdo_transcription_postprocess.py`, `bdo_transcription.py`, `bdo_transcription_session.py` |
| Candidate review/routing/project apply | `TranscriptionSession`, review/session tests | `bdo_transcription_session.py`, `pyside_bdo_gui.py` |
| Embedded transcription editor/canvas | `MidiNoteEditorDialog`, `PianoRollCanvas`, offscreen UI tests | `pyside_bdo_gui.py`, `transcription_editor_qt.py` |
| Semantic blocks / transcription LOD | candidate visible indexes and paint-order tests | `PianoRollCanvas` in `pyside_bdo_gui.py` |
| Melody-line guides | `docs/TRANSCRIPTION_VOICE_GUIDES.md`; deterministic lead/bass/harmony LOD, lineage and visible block indexes | `bdo_transcription_melody_lines.py`, `PianoRollCanvas` |
| Transcription key/chord analysis | `KeyEstimate`, `ChordSegment`, conservative `N` tests | `bdo_transcription_harmony.py` |
| Phrase/voice grouping and BDO Top-3 | `VoiceGroup`, `BdoInstrumentMatch`, deterministic ranking tests | `bdo_transcription_instruments.py` |
| Local BDO timbre feature cache | worker-only extraction, cache/privacy tests | `bdo_transcription_timbre.py` |
| Manual harmony/voice/instrument review | assist-review isolation/recovery tests | `bdo_transcription_assist.py`, `project_schema.py` |
| Evidence background/tiles | `EvidenceTileController`, tile tests | `bdo_transcription_evidence_qt.py` |
| Reference spectrogram background | Qt-free FFT transform, cancellable visible tiles | `bdo_spectrogram.py`, `bdo_spectrogram_qt.py` |
| Reference offset/A–B/first beat | shared transport + project schema tests | `pyside_bdo_gui.py`, `project_schema.py` |
| Timeline track meters | `AudioStatus.track_levels`, `TimelineCanvas.set_track_levels` | `bdo_realtime_audio.py`, `pyside_bdo_gui.py` |
| Sample selection/instrument ranges | canonical bank routing, renderer and mapping | `bdo_instrument_samples.py`, `bdo_sample_renderer.py` |
| BDO v9 codec/binary format | `docs/BDO_V9_CODEC.md`, codec tests | `bdo_codec/` |
| MIDI import / mappings | MIDI parser tests | `bdo_midi/` |
| MIDI/editor-to-BDO adaptation | export round-trip tests | `bdo_export/` |
| Game rules / conversion issues | profile + validation tests | `bdo_profile.py`, `bdo_validation.py`, `data/profiles/` |
| BDO score inspection / comparison | score snapshot tests | `bdo_score.py`, `scripts/inspect_bdo.py` |
| Audio A/B research | coverage/alignment tests | `bdo_audio_research.py`, `bdo_experiments.py` |
| Localization / regional terminology | `docs/LOCALIZATION.md`, catalog and four-locale UI tests | `i18n.py`, fixed-text producers only |
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
- `Note`: immutable five-field note tuple from `bdo_midi`.
- `TimelineCanvas`: compact overview and main transport.
- `PianoRollCanvas`: per-note editing surface.
- `MidiNoteEditorDialog`: draft lifecycle and track-only playback.
- `InstrumentEditorAdaptation`: read-only, Qt-free instrument-family, role,
  range-evidence, drum-lane, articulation-route, and visual-key projection. It
  never mutates a `Note` and does not replace export validation.
- `InstrumentLaneArtwork`: bounded packaged-original/local image preload plus
  app-owned vector fallback. A local file overrides the matching family, each
  unique raster is decoded once, paint-time lookup is memory-only, and the
  configured path remains local configuration rather than project state.
- `import_game_instrument_art`: explicit local-only PAZ boundary that decrypts
  two allow-listed composition UI resources, validates sprite coordinates from
  the game's CSS, and atomically creates per-instrument PNG cache tiles. It is
  not a general PAZ extractor and never enters project state or packaging.
- `MidiOptimizeDialog`: preview/report/apply workflow.
- `OptimizerConfig`: built-in optimizer behavior contract.
- `OptimizationRequest` / `OptimizationPreview`: stable optimizer-package API.
- `discover_host_algorithms`: unified built-in and `.bdoopt` discovery boundary.
- `BdoRealtimeAudioEngine`: preload, event schedule, voice pool, Qt output.
- `VoiceLifecycle` / `voice_lifecycle`: Qt-free formal-note, audible-tail, and
  fade boundary shared by real-time playback, seeking, audition, and offline
  rendering. Recovered Wwise release and loop metadata override legacy
  instrument-family guesses; effective signal endpoints are preload/cache data.
- `TranscriptionCandidate` / `TranscriptionResult`: immutable,
  non-authoritative Basic Pitch output that stays outside `TrackState` until
  explicit acceptance.
- `TranscriptionCandidateAnnotation` / `TranscriptionPostprocessReport`:
  runtime-only fragment flags, lineage, dispositions, reversibly suppressed
  candidates, and aggregate audit counts.
- `FrameNoteEvent` / `postprocess_frame_events`: deterministic frame-domain
  exact deduplication and profile-selected NMS/merge/suppression before
  millisecond candidate conversion. `preview_frame_event_cleanup` is the
  separate non-applying diagnostic boundary.
- `EvidenceDescriptor`: validated cache identity, exact frame-time source, and
  layer shape/dtype/MIDI-bin metadata.
- `TranscriptionBackend`: full-song analysis and cached interval
  re-decoding boundary.
- `TranscriptionSessionState`: review-payload-v4 A–B, sensitivity,
  cleanup-profile, selection/rejection, and pending/applied routing sidecar.
- `TranscriptionSession`: deterministic review/routing operations and
  review-only undo/redo, with runtime `CandidateAnnotation` lineage protecting
  reviewed candidates during full-song or interval replacement.
- `KeyEstimate` / `ChordSegment` / `HarmonyAnalysis`: conservative,
  original-audio-time harmony output with explicit alternatives and manual
  lock overlays.
- `VoiceGroup` / `BdoInstrumentMatch` / `InstrumentMatchAnalysis`:
  deterministic phrase grouping and explainable Top-3 BDO arrangement
  suggestions; they are not source-instrument labels.
- `TimbreProfileIndex`: bounded, path-free summaries of user-local BDO samples;
  construction is worker-only and never enters paint or audio callbacks.
- `TranscriptionAssistReviewState`: assist-review-payload-v1 manual key, locked
  chord, manual voice, and confirmed BDO instrument sidecar with fail-closed
  orphan recovery.
- `MidiNoteEditorDialog` / `PianoRollCanvas`: the single transcription review
  surface as well as the formal-note draft editor; no second piano roll or
  transport exists.
- `EvidenceTileController`: worker-side `QImage` evidence tiling with a bounded
  LRU; GUI painting only consumes ready tiles.
- `SpectrogramTileController`: worker-only reference-audio reads and FFTs for
  visible five-second tiles. Its 24 MiB LRU is ephemeral; paint consumes ready
  images and no reference path, PCM, or spectral data enters project state.
- `TranscriptionAnalysisWorker`: cancellable Qt bridge around the
  Qt-free transcription service.
- `decode_score` / `encode_score`: lossless document decode and safe encoding.
- `channel_groups_to_bdo`: current editor-to-codec adapter in `bdo_export`.
- `build_bdo_binary` / `encrypt_bdo`: probe-generator helpers delegated to `bdo_codec`.
- `Localizer`: exact-source widget translation.

## Common traps

- Re-reading the source MIDI during export discards manual editor changes.
- `duration_scale` must be folded into note durations before serialization.
- A BDO drum track is not a normal melodic track; avoid double GM remapping.
- Never append transcription output directly to `TrackState`. Write-to-Draft
  and explicit cross-track copies stay editor-local until the atomic Apply/OK
  gate; Cancel must not disturb review state that predates the dialog.
- Routing resolves explicit/selected candidates first, then the active A–B
  range. With neither selection nor range it must return nothing, never the
  whole song.
- `reference_audio_offset_ms` maps audio time into project time;
  `beat_origin_ms` changes grid/quantization phase only. Do not use one as the
  other or move formal notes when either changes.
- Do not put confidence thresholds, cleanup profiles, postprocess versions,
  flags, or lineage into the v4 evidence cache key. These change candidate
  decoding/review only and must reuse the same audio/model evidence.
- Do not derive Basic Pitch frame times with `frame / 86`; persist and validate
  official frame times in `times_ms.npy`.
- Initial inference, full cached re-decode, and interval re-decode must share
  `_decode_evidence_candidates`. Decode the float16 evidence that is actually
  persisted, apply fragment postprocessing in frame coordinates, and only then
  convert through `times_ms.npy`; competing candidate conversion paths will
  diverge at quantization and interval boundaries.
- Cleanup duration thresholds are annotation features, never sufficient
  deletion evidence. `preserve` is the safe default and only removes exact
  duplicates. Selecting experimental `balanced` directly executes same-pitch
  NMS and evidence-gated false-split merges; selecting experimental `clean`
  additionally executes reversible isolated/weak/severe suppression. The
  selected profile is the only action switch—do not add another gate that can
  silently contradict it. Use `preview_frame_event_cleanup()` for a dry run.
  The historical holdout did not pass selection, so neither experiment may be
  called verified or become the default. Keep every suppression auditable and
  recoverable, and keep all candidate actions outside `TrackState` until
  Apply/OK.
- Candidate replacement must protect rejected/pending/applied review by both
  stable candidate ID and lineage intersection. A newly merged or derived
  candidate must not overwrite a manually reviewed source candidate.
- Evidence paint must not open/mmap NPY files, normalize matrices, run FFT/model
  work, or scan the full song. Workers generate `QImage` tiles and the GUI draws
  only visible cached tiles.
- Semantic blocks use instrument/voice hue, confidence opacity, chord-role
  strips, and review-state borders as separate channels. Do not reuse hue for
  rejection/confidence or reintroduce the continuous heat map as the default.
- Harmony and grouping consume original `audio_ms`; apply
  `reference_audio_offset_ms` only when projecting or committing. Do not shift
  candidate IDs, locked segments, or voice groups when the user changes offset.
- Harmony must return `N` for weak, fewer-than-triad, or ambiguous evidence.
  Manual/locked key and chord decisions are overlays and must survive ordinary
  reanalysis.
- A BDO Top-3 row is an arrangement suggestion, never proof of the instrument
  in the mix. Confirmation records review only; it must not auto-create, route,
  or mutate a track.
- The composition Web UI receives active instruments, pitch ranges, playable
  articulations, code count, note count, and maximum BPM from the native game
  client at runtime. Static CSS icons are identity evidence only. The 730-note
  value is a physical v9 track-chunk limit, not an account/song quota; an
  offline fallback such as 10,000 must not be presented as a verified game
  entitlement. Cross-instrument copy must not silently mimic the game's
  destructive out-of-range deletion/default-articulation reset.
- Local timbre extraction is background-only. Persist no WAV, clip, sample
  path, or reference path; keep at most 32 representative game samples per
  instrument, eight clean reference segments per voice group, a 16 MiB resident
  profile index, and a 45% confidence cap when local timbre evidence is absent.
- Keep `gm_to_bdo_instrument` as the single GM→BDO domain mapping entry point.
  UI and match presentation must not introduce another mapping table.
- Schema v9 stores transcription-review payload v4, including
  `cleanup_profile`, plus manual assist review. New state defaults to
  `preserve`; schemas v1–v7 and review payloads v1–v3 also migrate to
  `preserve`, because their profile values predate actual cleanup actions.
  Current v8/v9 review-v4 values may retain an explicit experimental
  `balanced`/`clean` choice. Legacy projects also keep standard analysis mode
  so historical results do not change silently. Runtime
  lineage/flags/hidden candidates, automatic harmony, groups, matches,
  evidence, and sample features are cache/runtime results. Audio identity
  mismatch must orphan old assist decisions rather than
  silently applying them.
- Schema v9 also persists only lightweight reference-layer view state:
  ghost-note visibility/opacity and one shared opacity for melody lines,
  Frame/Onset/Contour evidence, and spectrogram tiles.  It never serializes
  rendered tiles or audio data; v8 migration retains the former full-strength
  rendering while new projects use quieter defaults.
- Before changing/unloading reference audio, preserve applied formal notes but
  confirm loss of pending routes. A deleted target leaves an orphaned route; it
  must not silently retarget.
- Basic Pitch MIDI pitches are not BDO drum-piece mappings; keep automatic
  transcription disabled for percussion tracks.
- Stop reference and game-sample playback before model inference. Model
  loading and cache I/O must never enter the real-time audio callback.
- Do not fold `bdo_track_volume` into note velocity. It is a separate game
  mixer value: 0–100/default 70 for new edits, while imported wire bytes up to
  255 remain lossless until explicitly changed. Effect bytes 0/2/4 belong to
  per-instrument Aux sends and 1/3/5/6/7 to the shared master layer; one editor
  must not overwrite the other. Do not simulate or label the game DSP as
  verified before controlled save differentials and audio A/B establish it.
- Transcription analysis streams decode/resampling through anonymous Local
  AppData workspaces. Mixed mode must keep HPSS intermediates block-bounded,
  fuse each original/harmonic window pair immediately, and publish only one
  float16 evidence timeline with the manifest last. Do not reintroduce
  whole-song padding, concatenation, or duplicate evidence matrices.
- `Path("")` resolves to the current directory; explicitly test empty configured paths.
- `project.json` must never serialize external absolute MIDI/BDO/reference-audio
  paths. Recovery sources use canonicalized project-relative references; reject
  `..` and symlink escapes. Absolute reads exist only for pre-policy project
  compatibility and must be sanitized by the next autosave.
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

### Lossless codec

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_codec -v
.\.venv\Scripts\python.exe scripts\verify_private_bdo_corpus.py <private-music-directory>
```

The first command verifies artificial structure and safety fixtures. The second
must point at private local evidence and must never copy its inputs into Git.

### Audio

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_realtime_audio -v
```

Look for exact event frames, seek voice restoration, bounded voices, preload deduplication, and limiter stability.

### Transcription

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_transcription -v
```

Check candidate conversion, cache invalidation and fail-closed cache loading
without invoking packaged model inference. Also run the session and evidence
tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_transcription_session tests.test_transcription_evidence_qt -v
```

Verify stable candidate IDs, threshold/cleanup-independent cache keys, exact
frame times, unified first/full/interval frame decoding, lineage-protected
replacement, selected-first/A–B routing, explicit multi-track copy, strict
manifest rejection, and bounded tile caching. UI smoke tests must confirm the
safe `preserve` default, experimental labels, direct balanced/clean action
semantics, reversible hidden candidates, cache-only profile switching, one
piano roll and transport, synchronized A–B state, no whole-song fallback,
editor-local staging, and one undoable project operation for Apply/OK.

Run fragment cleanup and its frozen benchmark-contract tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_transcription_postprocess tests.test_babyslakh_benchmark -v
```

The v2 fusion report is not evidence for cleanup. The cleanup report requires
fragment reduction ≥20%, precision gain ≥0.005, onset-F1 drop ≤0.003,
onset-plus-offset-F1 drop ≤0.002, note recall drop ≤0.005, ≤8-frame true-note
recall drop ≤0.01, false merges ≤0.5%, worst-song onset-F1 drop ≤0.02, and
postprocessing share <5%, plus the separate clean safety gate. The historical
`fragment-cleanup-v2-annotation-only` Track00013–00020 holdout found 0/108
balanced passes, 104/108 clean-safety passes, and 0/108 joint selections. The
frozen fixed configuration's balanced branch had zero fragment or precision
improvement at 0.0193303202 timing share. Its clean branch suppressed
18/28,215 candidates, gained 0.00010135 precision and 0.00011290 onset F1,
preserved recall/short recall, and used 0.0199564656 timing share; clean safety
passed but selection failed. Its `selected_config=null` and
`annotation_only=true` mean no profile may be the verified/default automatic
mode. They do not constitute a passing evaluation of
`fragment-cleanup-v3-explicit-opt-in`, whose balanced/clean actions are
available only after explicit experimental selection. No new holdout pass is
claimed. See the
[compact historical result](benchmarks/babyslakh_transcription_v3_cleanup.json)
and [protocol](benchmarks/fragment_cleanup_protocol.md).

The current report-schema-v4 holdout evaluates the real
`fragment-cleanup-v3-explicit-opt-in` actions. Balanced passed 0/108 release
gates, clean passed 91/108 safety gates, and joint selection remained 0/108.
The fixed balanced profile reduced 28,215 candidates to 28,083 and
fragmentation by 0.0099938, improved precision by 0.0006365, changed onset F1
by -0.0002454, and used 0.0337613 of decode time. Clean reduced the count to
28,065 and passed its safety gate at 0.0358946 share. Every safety/performance
check passed, but balanced missed the 20% fragment-reduction and 0.005
precision-gain requirements. Thus `preserve` is the default; explicit
balanced/clean selection executes real reversible experimental actions, but
neither is verified or recommended. See the
[current compact result](benchmarks/babyslakh_transcription_v4_cleanup.json).

Run the semantic assist domain tests as a separate pure-logic boundary:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_transcription_harmony tests.test_bdo_transcription_instruments tests.test_bdo_transcription_timbre tests.test_bdo_transcription_assist -v
```

Verify conservative `N`, key/chord alternatives and locks, deterministic voice
IDs and roles, three-or-fewer BDO matches, pitch-range hard exclusions,
no-sample 45% capping, contamination filtering, path-free bounded caches,
assist-review payload-v1, and orphan/recovery behavior. Offscreen tests should
also cover default-hidden diagnostics, all three semantic LOD ranges,
chord/phrase navigation, review-queue location without selection, and Top-3
confirmation without track mutation.

### Optimizer

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_midi_optimizer -v
```

Check scope isolation, pitch/count invariants, deterministic humanization, and preservation of manual `ntype`.

### Localization

Run `tests.test_i18n_catalog`, then create an offscreen `QApplication`, switch `Localizer` through all four locales, and inspect main/settings/editor widgets.

## Public-release checklist

- Add and review a root `LICENSE`.
- Confirm source archives and binaries contain no historical `midi2bdo` or `_ice` modules.
- Remove tracked `out/` scores and any Owner IDs from Git history.
- Do not publish extracted game audio or PAZ contents.
- Keep the single `BDO-Music-Composer.exe` build reproducible and bundled with
  the Basic Pitch ONNX CPU runtime. Do not publish it until its exact dependency
  inventory, model redistribution terms, native-library notices, and complete
  third-party notice set are reviewed and approved by the fail-closed policy.
- Require both frozen-executable checks after every build:
  `--self-test-transcription` must complete synthetic ONNX/CPU inference and
  `--self-test-startup` must keep the GUI alive for at least 10 seconds.
- Replace personal defaults with empty/configured paths.
- Run tests, `git diff --check`, and a clean PyInstaller startup test.
- Publish binaries through release assets, not Git history.
