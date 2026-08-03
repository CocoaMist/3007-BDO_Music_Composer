# AI context and change map

This document helps an AI agent find the correct subsystem without scanning every research file.

Before using this routing map, read the repository rules in `AGENTS.md`, choose
one complete localized README from the root language hub, and follow the
handoff workflow in `docs/AGENT_HANDOFF.md`. Current structural and performance
candidates are tracked in `docs/OPTIMIZATION_EXTENSION_ROADMAP.md`. Before
moving behavior between modules, read `docs/AI_EDITING_GUIDE.md` for ownership,
dependency direction, typed-boundary rules, and the staged decomposition plan.

The package migration is complete for root Python owners. `main.py` is the only
root module; application code is grouped by domain under
`bdo_music_composer/`, cross-package primitives live in `bdo_common/`, and
operator/developer commands live in `scripts/` and `tools/`. Every caller uses
the canonical path directly, with no root compatibility shim.

## Task router

| User request | Read first | Likely edit |
|---|---|---|
| Main-window composition / toolbar | `MidiToBdoWindow._build_*`, `MainWindowStyleMixin`, semantic theme | `bdo_music_composer/ui/main_window.py`, `bdo_music_composer/ui/theme/main_window_style.py`, `bdo_music_composer/ui/theme/fluent_theme.py` |
| Timeline behavior / painting | shared interval index, reference-audio protocol, track interactions | `bdo_music_composer/editor/interval_index.py`, `bdo_music_composer/ui/editor/timeline_canvas.py`, `bdo_music_composer/editor/editor_models.py`, thin signal adapters in `bdo_music_composer/ui/main_window.py` |
| Application settings / local source fields | dialog host contract and Qt-free source normalization | `bdo_music_composer/ui/dialogs/application_settings_dialog.py`, `bdo_music_composer/app/audio_source_settings.py`, thin apply adapter in `bdo_music_composer/ui/main_window.py` |
| Config JSON / safe output names | atomic storage, corrupt backup, unknown-field preservation | `bdo_music_composer/app/application_config.py`; callers only provide path and mapping |
| Track pitch / Aux / master-effect dialogs | structural track contract and raw-byte preservation | `bdo_music_composer/ui/dialogs/track_settings_dialogs.py`, `bdo_common/bdo_track_effects.py`, thin apply adapters in `bdo_music_composer/ui/main_window.py` |
| Home page/unified projects | bounded scanners, safe project index, extracted presentation widgets | `bdo_music_composer/app/home_catalog.py`, `bdo_music_composer/ui/home_widgets.py`, `bdo_music_composer/project/project_persistence.py`, thin composition in `bdo_music_composer/ui/main_window.py`, `bdo_music_composer/ui/i18n.py` |
| Dormant internal release notes / GitHub update check | optional machine-local catalog bounds, missing-record fallback, stable-only SemVer policy, no production UI route, Git-history/package exclusion, explicit network/privacy boundary | `bdo_music_composer/app/application_metadata.py`, `bdo_music_composer/app/release_notes.py`, `bdo_music_composer/app/update_check.py`, `bdo_music_composer/ui/update_check_qt.py`, `bdo_music_composer/ui/dialogs/release_notes_dialog.py`, optional Git-ignored `data/releases/release_notes.json` |
| Open/edit a BDO v9 score | `read_bdo_score`, `bdo_music_composer.editor.editor_import.tracks_from_bdo_snapshot`, `MidiToBdoWindow._load_bdo_info` | `bdo_music_composer/export/bdo_score.py`, `bdo_music_composer/editor/editor_import.py`, thin apply adapter in `bdo_music_composer/ui/main_window.py` |
| Piano-roll behavior and shortcuts | `PianoRollCanvas`, `VelocityLaneCanvas`, `MidiNoteEditorDialog`, the shared shortcut registry, mouse-transparent contextual hints, and the complete F1 reference | `bdo_music_composer/ui/editor/piano_roll_canvas.py`, `bdo_music_composer/ui/editor/midi_note_editor.py`, `bdo_music_composer/ui/editor/editor_shortcuts.py`, `bdo_music_composer/ui/editor/editor_shortcut_hud.py` |
| Instrument-specific editor lanes/roles | verified vs preview vs recommended boundaries | `bdo_music_composer/editor/bdo_instrument_adaptation.py`, `bdo_music_composer/editor/editor_models.py`, `bdo_music_composer/ui/editor/midi_note_editor.py` |
| Timeline instrument artwork | packaged original icons, local override, vector fallback | `assets/README.md`, `bdo_music_composer/ui/editor/bdo_instrument_lane_art_qt.py`, `bdo_music_composer/ui/editor/timeline_canvas.py` |
| Local game-art import | allow-listed PAZ/CSS/sprite import, local cache only | `tools/import_bdo_game_art.py` |
| Timeline process telemetry | current-process CPU/RAM plus callback-owned audio counters | `bdo_music_composer/app/process_metrics.py`, `MidiToBdoWindow._build_performance_strip` |
| Local homepage examples | sanitized local manifest, attribution, no bundled user MIDI | `tools/install_example_project.py`, `scan_example_projects` |
| MIDI optimization | package README, configs/reports/tests, Qt analysis boundary | `optimization/`, `bdo_music_composer/ui/dialogs/optimizer_dialog.py` |
| Optimizer packages / Marnian | `optimization/README.md`, `docs/MARNIAN_MUSE_OPTIONAL_BOUNDARY.md` | `optimization/plugin_api.py`, `optimization/plugin_loader.py`, `optimization/plugin_host.py` |
| Articulation recommendation | profile + technique registry | `bdo_music_composer/editor/bdo_articulation_profiles.py`, `bdo_music_composer/editor/bdo_techniques.py` |
| Harmony/role analysis | theory context | `bdo_music_composer/editor/bdo_music_theory.py` |
| Lyrics | lyric expression mode | `bdo_music_composer/editor/bdo_lyrics.py` |
| Preview/audio timing | shared lifecycle, engine and tests | `bdo_music_composer/audio/bdo_audio_lifecycle.py`, `bdo_music_composer/audio/bdo_realtime_audio.py`, `bdo_music_composer/audio/bdo_sample_renderer.py` |
| Reference-audio load/decode failures | bounded WAV/MP3 content probe, Qt playback/waveform owner, streamed transcription decode, spectrogram source gate | `bdo_music_composer/audio/reference_audio_format.py`, `bdo_music_composer/audio/reference_audio_controller.py`, `bdo_music_composer/transcription/bdo_transcription.py`, `bdo_music_composer/ui/transcription/bdo_spectrogram_qt.py` |
| Standard-MIDI preview/round-trip projection | deterministic event ordering, `/4` metadata, controls, lyrics, percussion channel, duration scaling | `bdo_music_composer/editor/preview_midi_writer.py`; `bdo_music_composer/ui/main_window.py` only re-exports the same function |
| Game mixer/effects | track volume, Aux/master byte layers, raw compatibility | `bdo_common/bdo_track_effects.py`, `docs/BDO_MIXER_EFFECTS.md` |
| Transcription backend/cache/re-decode | `TranscriptionBackend`, `EvidenceDescriptor`, cache tests | `bdo_music_composer/transcription/bdo_transcription.py`, `bdo_music_composer/ui/transcription/transcription_workers.py` |
| Fragment annotation/cleanup/lineage | `postprocess_frame_events`, v3 benchmark protocol, postprocess tests | `bdo_music_composer/transcription/bdo_transcription_postprocess.py`, `bdo_music_composer/transcription/bdo_transcription.py`, `bdo_music_composer/transcription/bdo_transcription_session.py` |
| Rhythm cleanup/alignment | cached-onset tempo/phase estimate, adaptive or strict 1/64 projection, deterministic same-pitch boundary decode, immutable raw candidates, single cancellable worker | `bdo_music_composer/transcription/rhythm_grid.py`, `bdo_music_composer/transcription/rhythm_alignment.py`, `bdo_music_composer/transcription/rhythm_decode.py`, `bdo_music_composer/transcription/rhythm_cleanup.py`, `bdo_music_composer/ui/transcription/transcription_workers.py`, `bdo_music_composer/ui/transcription_rhythm_diagnostic.py` |
| Candidate review/routing/project apply | session candidate indexes, mixed review plans, pure formal-commit plan, review/session tests | `bdo_music_composer/transcription/bdo_transcription_session.py`, `bdo_music_composer/transcription/transcription_commit_plan.py`, `bdo_music_composer/transcription/transcription_workspace_controller.py`, thin execution adapters in `bdo_music_composer/ui/main_window.py` and `bdo_music_composer/ui/editor/midi_note_editor.py` |
| Embedded transcription editor/canvas | `MidiNoteEditorDialog`, `PianoRollCanvas`, offscreen UI tests | `bdo_music_composer/ui/editor/midi_note_editor.py`, `bdo_music_composer/ui/editor/piano_roll_canvas.py`, `bdo_music_composer/ui/transcription/transcription_editor_qt.py` |
| Semantic blocks / transcription LOD | candidate visible indexes and paint-order tests | `PianoRollCanvas` in `bdo_music_composer/ui/editor/piano_roll_canvas.py` |
| Melody-line guides | `docs/TRANSCRIPTION_VOICE_GUIDES.md`; deterministic lead/bass/harmony LOD, lineage and visible block indexes | `bdo_music_composer/transcription/bdo_transcription_melody_lines.py`, `PianoRollCanvas` |
| Transcription key/chord analysis | `KeyEstimate`, `ChordSegment`, conservative `N` tests | `bdo_music_composer/transcription/bdo_transcription_harmony.py` |
| Phrase/voice grouping and BDO Top-3 | `VoiceGroup`, `BdoInstrumentMatch`, deterministic ranking tests | `bdo_music_composer/transcription/bdo_transcription_instruments.py` |
| Local BDO timbre feature cache | worker-only extraction, cache/privacy tests | `bdo_music_composer/transcription/bdo_transcription_timbre.py` |
| Manual harmony/voice/instrument review | assist-review isolation/recovery tests | `bdo_music_composer/transcription/bdo_transcription_assist.py`, `bdo_music_composer/project/project_schema.py` |
| Evidence background/tiles | `EvidenceTileController`, tile tests | `bdo_music_composer/ui/transcription/bdo_transcription_evidence_qt.py` |
| Reference spectrogram background | Qt-free FFT transform, cancellable visible tiles | `bdo_music_composer/audio/bdo_spectrogram.py`, `bdo_music_composer/ui/transcription/bdo_spectrogram_qt.py` |
| Reference offset/A–B/first beat | shared transport + project schema tests | `bdo_music_composer/ui/main_window.py`, `bdo_music_composer/project/project_schema.py` |
| Timeline track meters | `AudioStatus.track_levels`, `TimelineCanvas.set_track_levels` | `bdo_music_composer/audio/bdo_realtime_audio.py`, `bdo_music_composer/ui/main_window.py` |
| Sample selection/instrument ranges | canonical bank routing, renderer and mapping | `bdo_music_composer/audio/bdo_instrument_samples.py`, `bdo_music_composer/audio/bdo_sample_renderer.py` |
| BDO v9 codec/binary format | `docs/BDO_V9_CODEC.md`, codec tests | `bdo_codec/` |
| MIDI import / mappings | parser tests plus the transactional editor-import contract | `bdo_midi/`, `bdo_music_composer/editor/editor_import.py`, thin apply adapter in `bdo_music_composer/ui/main_window.py` |
| MIDI/editor-to-BDO adaptation | immutable export snapshot, source-document reuse, final-document summary, staged atomic publication | `bdo_music_composer/export/export_workflow.py`, `bdo_common/atomic_io.py`, `bdo_export/core.py`, `bdo_export/source_reuse.py` |
| Export consistency/debug mismatch | editor projection versus prepared/primary/game-copy fields, canonical 730 layout, lossless source bytes, redacted report | `bdo_music_composer/export/export_verification.py`, integration in `bdo_music_composer/export/export_workflow.py`, `tests/test_export_verification.py` |
| Formal game-score scope, velocity materialization, shared instrument mixer | game-model unit tests plus UI/export round trips | `bdo_music_composer/editor/game_score_model.py`, thin UI adapters |
| Conversion defaults/settings lifecycle | `docs/CONVERSION_SETTINGS.md`; new-score vs legacy/BDO source policy | `bdo_music_composer/core/conversion_settings.py`, thin adapters in `bdo_music_composer/ui/main_window.py` and `bdo_music_composer/export/export_workflow.py` |
| Global/per-track pitch projection | `docs/CONVERSION_SETTINGS.md`; stable track IDs, drum exemption, `12k` voice adaptation | `bdo_music_composer/editor/pitch_transform.py`, `bdo_music_composer/export/bdo_validation.py`, `bdo_music_composer/export/export_workflow.py`, preview adapters |
| Game rules / conversion issues | lazy profile provider, ordered focused validation stages | `bdo_music_composer/app/game_profile_provider.py`, `bdo_music_composer/core/bdo_profile.py`, `bdo_music_composer/export/bdo_validation.py`, `data/profiles/` |
| Revisioned conversion validation | explicit mutation boundary, cache-hit and notice tests | `bdo_music_composer/editor/model_revision.py`, `bdo_music_composer/app/conversion_validation_controller.py`, thin adapter in `bdo_music_composer/ui/main_window.py` |
| Transcription worker/review lifecycle | generation/restart, bounded mixed history, and stale-result tests | `bdo_music_composer/transcription/transcription_workspace_controller.py`, `bdo_music_composer/ui/transcription/transcription_workers.py` |
| Project loading/persistence lifecycle | complete `ProjectLoadPlan`, path-aware track import, generation gate, recursively frozen metadata, and atomic writer | `bdo_music_composer/app/project_document.py`, `bdo_music_composer/editor/editor_import.py`, `bdo_music_composer/project/project_lifecycle_controller.py`, `bdo_music_composer/project/project_persistence.py`; UI only reads text, maps errors, and commits |
| Preview transport lifecycle | session generation/state and real-time audio tests | `bdo_music_composer/audio/preview_transport_controller.py`, `bdo_music_composer/audio/bdo_realtime_audio.py` |
| BDO score inspection / comparison | score snapshot tests | `bdo_music_composer/export/bdo_score.py`, `scripts/inspect_bdo.py` |
| Audio A/B research | coverage/alignment tests | `bdo_music_composer/audio/bdo_audio_research.py`, `bdo_music_composer/research/bdo_experiments.py` |
| Localization / regional terminology | `docs/LOCALIZATION.md`, catalog and four-locale UI tests | `bdo_music_composer/ui/i18n.py`, fixed-text producers only |
| Credits / license links / citations | `THIRD_PARTY_NOTICES.md`, Basic Pitch license evidence | `bdo_music_composer/core/third_party_credits.py`, `bdo_music_composer/ui/dialogs/acknowledgements_dialog.py`, release docs |
| README languages / Agent handoff | root language hub, shared section markers, Agent workflow | `README.*.md`, `docs/AGENT_HANDOFF.md`, `tools/check_readme_locales.py` |
| Repository layout / file cleanup | single root entry, domain package placement, private/generated artifact policy | `docs/PROJECT_STRUCTURE.md`, directory `README.md` files, `tools/check_repository_hygiene.py` |
| Windows build | spec/build script/path split | `packaging/windows/`, `bdo_music_composer/core/project_paths.py` |
| Cross-module refactor / AI editability | ownership table, dependency direction, typed boundaries, architecture guards | `docs/AI_EDITING_GUIDE.md`, owner module, `tests/test_architecture_dependencies.py` |

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
- `TrackImportPresentation`: injected UI naming/color policy used by the
  Qt-free import adapter; it prevents format parsing from reaching into i18n or
  widget state.
- `EditorImportError`: stable code plus payload path for transactional MIDI,
  BDO, and project import failures. Authoritative malformed data must not
  produce a partial editor score.
- `formal_score_tracks` / `preview_tracks`: formal score always includes every
  lane; Mute/Solo are monitoring state only, and a muted solo lane stays silent.
- `serialized_game_instrument_id`: final game mixer identity, including Marnian
  mode offset. Volume and Aux ownership must use this key.
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
- `PreviewEffectProcessor`: preallocated, explicitly uncalibrated local
  Reverb/Delay/Chorus preview; exact export bytes remain in
  `bdo_common/bdo_track_effects.py`.
- `build_filtered_midi`: deterministic standard-MIDI projection owned by
  `bdo_music_composer/editor/preview_midi_writer.py`. The main-window name is
  an identity-preserving
  compatibility re-export, not another implementation and not BDO v9 export.
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
  reviewed candidates during full-song or interval replacement. It is also the
  sole owner of stable candidate order, ID lookup, start-range and overlap
  indexes; review-only state changes do not rebuild them.
- `TranscriptionReviewController`: Qt-free owner of the bounded interleaving
  order between session commands and immutable assist-review snapshots. It
  invalidates abandoned mixed redo branches but never mutates candidates,
  tracks, widgets, or persistence.
- `TranscriptionCommitPlan`: deterministic, Qt-free result of classifying local
  and pending candidate routes against frozen draft/formal track views. It owns
  final note and sidecar intent, invalid/orphaned/unresolved reports, and
  provisional-track intent; it never mutates tracks or performs the UI commit.
  The host publishes model/history state under rollback checkpoints, then treats
  refresh/status work as compensable so a view error cannot skip autosave.
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
- Production transcription is intentionally practical: load/change/remove
  audio, run full-song Basic Pitch with `standard` / `balanced` / `preserve`,
  independently show lightweight outlined reference blocks (with confidence
  rails) or sparse blue frame-level pitch ridges clipped near decoded
  candidates. The pitch guide has persisted `low` / `standard` / `high`
  display-only denoise; it must not mutate candidates, notes, or export data.
  select candidates, then ignore/restore/add them to the editable draft. A
  read-only game-fit check reports pitch, articulation, timing, velocity, and
  automatic 730-note publication chunks before the user continues ordinary
  editing. Phrase, harmony, voice,
  timbre, diagnostic evidence, experimental cleanup, and range re-decode UI is
  not constructed or exposed, and the semantic-assist worker is not started.
  Keep the underlying sidecar readers and pure domain modules compatible with
  older projects unless a schema migration explicitly removes them.
- `EvidenceTileController`: worker-side `QImage` evidence tiling with a bounded
  LRU; GUI painting only consumes ready tiles. Contour ridges are painted in
  bounded strength buckets and the canvas reuses its candidate-shaped clip
  until projection or viewport geometry changes.
- `SpectrogramTileController`: worker-only reference-audio reads and FFTs for
  visible five-second tiles. Its 24 MiB LRU is ephemeral; paint consumes ready
  images and no reference path, PCM, or spectral data enters project state.
- `TranscriptionAnalysisWorker`: cancellable Qt bridge around the
  Qt-free transcription service.
- `decode_score` / `encode_score`: lossless document decode and safe encoding.
- `channel_groups_to_bdo`: current editor-to-codec adapter in `bdo_export`.
- `ExportExpectation` / `ExportVerificationReport`: Qt-free, bounded diagnostic
  boundary for the current export. It compares every game-representable field
  and publication stage; note count alone is never an adequate round trip.
- `ConversionSettings`: immutable Qt-free owner of MIDI parse and export
  transforms. Its source constructors distinguish new-score preferences,
  legacy project neutrality, and BDO lossless import; UI properties are only a
  compatibility adapter.
- `ProjectOpenRequest`: immutable Qt-free routing facts built from a migrated
  project payload. It owns source-format normalization, recovery-copy
  precedence, legacy absolute-path compatibility, current-policy escape
  rejection, and typed missing-source errors for legacy payloads without a
  complete track snapshot. A complete snapshot remains openable without its
  provenance file.
- `ProjectLoadPlan`: complete Qt-free result from `prepare_project_load()` after
  JSON decode, schema migration, project-relative path validation, transactional
  track construction, and all conversion/mixer/pitch/reference/review metadata
  parsing. No raw project mapping survives into the UI commit.
- `ProjectMetadataSnapshot`: recursively detached project-save metadata. Its
  frozen JSON containers prevent later UI dictionary/list mutation from racing
  autosave; `to_payload()` returns fresh writer-owned mutable containers.
- `build_bdo_binary` / `encrypt_bdo`: probe-generator helpers delegated to `bdo_codec`.
- `Localizer`: exact-source widget translation.
- `APP_VERSION` / GitHub repository constants: immutable public identity owned
  by `bdo_music_composer/app/application_metadata.py`; do not recreate a
  parallel root identity module.
- `ReleaseNotesDocument`: deeply immutable, size/count/text-bounded local
  history parsed from an explicit fixture or the optional machine-local,
  Git-ignored `data/releases/release_notes.json`. The file may be absent and
  enters neither public Git history nor an installation package.
- `UpdateCheckController`: an explicit, one-request-at-a-time QtNetwork
  transport retained for explicit internal tests. Production home, startup,
  menu, and navigation flows must not construct it or the dormant dialog; the
  pure response/SemVer policy remains in `bdo_music_composer/app/update_check.py`.

`bdo_music_composer/ui/main_window.py` is the Qt composition root and compatibility facade. A
symbol re-exported there remains owned by its focused implementation module;
new production code imports the owner directly. See
`docs/AI_EDITING_GUIDE.md` before adding another main-window helper.

## Common traps

- Re-reading the source MIDI during export discards manual editor changes.
- Constructing complete `TrackState` values in the main window duplicates the
  transactional import contract. Route MIDI, BDO, and project payloads through
  `bdo_music_composer/editor/editor_import.py`, inject presentation values, and
  apply only a fully
  successful result.
- Re-reading MIDI/BDO while restoring a project also discards user-created
  lanes and resurrects deleted ones. The migrated project snapshot is
  authoritative; provenance is optional and only enables extra source checks
  or byte-lossless BDO reuse.
- Do not mutate window state while parsing individual project fields. Read the
  text, build one complete `ProjectLoadPlan`, map any stable code/path to a user
  message, then commit the plan once. Never supplement it from the raw mapping.
- Do not rebuild conversion-setting dictionaries in lifecycle/UI branches.
  Replace one `ConversionSettings` snapshot and use its payload/parse/export
  projections. Missing legacy fields must not inherit the previously open
  score, and a BDO import must retain a neutral transform for lossless export.
- Never pass mutable `TrackState` or note-list containers into `ConvertWorker`;
  freeze them before starting the thread. Keep the worker referenced until its
  `finished` signal and make close wait rather than destroying a live `QThread`.
- User-owned score/project destinations must be replaced through `atomic_io`;
  direct `write_bytes`/`copy2` can truncate the last known-good file.
- `duration_scale` must be folded into note durations before serialization.
- A BDO drum track is not a normal melodic track; avoid double GM remapping.
- Never append transcription output directly to `TrackState`. Write-to-Draft
  and explicit cross-track copies stay editor-local until the atomic Apply/OK
  gate; Cancel must not disturb review state that predates the dialog.
- `plan_transcription_commit()` is a pure decision boundary, not the transaction
  executor. The UI must preflight provisional tracks, take one project snapshot,
  apply final notes and sidecar state together, refresh/autosave once, and restore
  the old state if a later execution step fails.
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
- Candidate selection, A–B eligibility, restore, fragment selection and route
  staging must use `TranscriptionSession` indexed queries. Do not duplicate
  those rules with full-song loops or reach into canvas-private index arrays.
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
- Schema v10 stores transcription-review payload v4, including
  `cleanup_profile`, plus manual assist review. New state defaults to
  `preserve`; schemas v1–v7 and review payloads v1–v3 also migrate to
  `preserve`, because their profile values predate actual cleanup actions.
  Current v8/v9/v10 review-v4 values may retain an explicit experimental
  `balanced`/`clean` choice. Legacy projects also keep standard analysis mode
  so historical results do not change silently. Runtime
  lineage/flags/hidden candidates, automatic harmony, groups, matches,
  evidence, and sample features are cache/runtime results. Audio identity
  mismatch must orphan old assist decisions rather than
  silently applying them.
- Reference-layer settings v7 persist only lightweight view state:
  ghost-note and candidate visibility/opacity, contour denoise, plus one shared opacity for voice hints,
  Frame/Onset/Contour evidence, and spectrogram tiles.  It never serializes
  rendered tiles or audio data; v8 migration retains the former full-strength
  rendering while new projects use quieter defaults. New projects keep the
  derived voice hints off because dense recognition makes them noisy; when
  enabled they default to the primary role and connect only nearby notes with
  jumps of at most seven semitones. The raw pitch guide remains an explicit
  user switch.
- Schema v10 adds `pitch_transform`. Resolve it by stable `track_id`; never use
  track-list position as identity. Automatic/voice overrides are `12k`, drums
  resolve to zero, and preview/validation/export must consume the same plan.
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
  must not overwrite the other. All logical lanes with the same final
  serialized instrument ID share Volume/Aux; propagate only dirty Aux fields,
  preserve Master bytes, preflight before mutation, and never resolve an old
  conflict by taking the first lane. Do not simulate or label the game DSP as
  verified before controlled save differentials and audio A/B establish it.
- Schema v11 materializes legacy velocity policy and `volume_scale` into
  `Note.vel`, then stores `velocity_mode=preserve` and `volume_scale=1.0`.
  Preview, autosave and export must not apply another hidden velocity transform.
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
- Autosave JSON encoding and disk I/O belong to the single coalescing writer,
  not the GUI timer callback. Home discovery reads `project.index.json` or a
  bounded legacy prefix and applies its item limit before metadata parsing.
- A frozen outer request does not freeze nested dict/list values. Capture save
  metadata through `ProjectMetadataSnapshot.capture()` and its recursive JSON
  freezer; do not hand GUI-owned containers to the writer.
- `sys._MEIPASS` is read-only/temporary from the app's perspective; do not write exports there.
- Qt widgets can store non-ASCII dynamic properties incorrectly on some Windows locale paths; localization keeps source strings in Python `WeakKeyDictionary` storage.
- One-file PyInstaller launches a parent and child process; stop both during startup tests before rebuilding.
- `out/` may still contain historically tracked files even though it is in `.gitignore`; check `git ls-files out` before publishing.
- Do not connect the dormant release-notes dialog or update checker to
  production home, startup, menu, or navigation flows. Only explicit internal
  tests may construct the dialog and start one asynchronous stable-release
  query; ordinary startup and the packaged startup self-test remain
  network-free.
- Do not add authentication, auto-download, or execution to the update path.
  It sends only public request headers, constructs release links from the fixed
  repository identity, and must render timeout, rate-limit, TLS, malformed
  response, and other errors as unknown/failure rather than “current”.

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

### Project document and persistence

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_project_document tests.test_project_persistence tests.test_project_lifecycle_controller tests.test_midi_import_transaction -v
```

Verify that invalid JSON/fields/tracks/references fail with stable code/path
before UI mutation, complete snapshots open without provenance, nested metadata
is detached recursively, project paths remain portable, and writes stay atomic.

### Standard-MIDI projection

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_preview_midi_writer -v
```

Verify compatibility-export identity, duration scaling, same-tick note-off
ordering, channel routing, controls, lyrics, and no dependency on the GUI module.

### Audio

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_realtime_audio -v
```

Look for exact event frames, seek voice restoration, bounded voices, preload
deduplication, allocation-free effect routing, reset tails, and limiter
stability.

### Transcription

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_transcription -v
```

Check candidate conversion, cache invalidation and fail-closed cache loading
without invoking packaged model inference. Also run the session and evidence
tests:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bdo_transcription_session tests.test_transcription_commit_plan tests.test_transcription_editor_commit_ui tests.test_transcription_evidence_qt -v
```

Verify stable candidate IDs, threshold/cleanup-independent cache keys, exact
frame times, unified first/full/interval frame decoding, lineage-protected
 replacement, selected-first/A–B routing, deterministic non-mutating formal
 commit plans, explicit multi-track copy, strict
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

Run `tests.test_i18n_catalog`, then create an offscreen `QApplication`, switch `Localizer` through all five locales, and inspect main/settings/editor widgets.

### Dormant internal release notes and update check

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_release_notes tests.test_update_check tests.test_update_check_qt tests.test_release_notes_ui -v
```

Verify bounded local-resource parsing, all locale fallbacks, strict stable
SemVer comparison, explicit asynchronous request lifetime, startup-self-test
network disablement, and fail-closed timeout/rate-limit/TLS/invalid-payload
states. Also verify the missing-local-record fallback, that production UI
wiring exposes no entry, that `data/releases/release_notes.json` is absent from
Git history and public packages, and that the optional record remains
Git-ignored. The dormant dialog may be constructed only by the explicit
internal test harness.

## Public-release checklist

- Verify the existing root `LICENSE` still covers only original project code,
  and keep third-party terms in `THIRD_PARTY_NOTICES.md`.
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
