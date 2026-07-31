# Documentation index

This directory separates current contracts from research evidence, roadmaps,
and historical records. Start with the authoritative documents for a code
change; evidence and history explain decisions but do not override tests or
current invariants.

## Agent and architecture contracts

- [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md) — **authoritative** takeover,
  validation, and handoff workflow.
- [`AI_CONTEXT.md`](AI_CONTEXT.md) — **authoritative** task-to-owner routing
  map and validation matrix.
- [`AI_EDITING_GUIDE.md`](AI_EDITING_GUIDE.md) — **authoritative** dependency
  direction, typed boundaries, and staged extraction rules.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — **authoritative** end-to-end runtime
  data flow and component contracts.
- [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md) — **authoritative** directory
  roles, standalone entry points, and placement rules.
- [`OPTIMIZATION_EXTENSION_ROADMAP.md`](OPTIMIZATION_EXTENSION_ROADMAP.md) —
  **roadmap** for measured structural and performance work.

## Game format, editor, and export

- [`BDO_V9_CODEC.md`](BDO_V9_CODEC.md) — **authoritative** BDO v9 binary
  layout and lossless-codec contract.
- [`BDO_MUSIC_NOTES.md`](BDO_MUSIC_NOTES.md) — **reference** conversion and
  score-inspection workflow.
- [`BDO_COMPOSITION_AUTHORING.md`](BDO_COMPOSITION_AUTHORING.md) —
  **evidence** from the in-game composition surface.
- [`BDO_MIXER_EFFECTS.md`](BDO_MIXER_EFFECTS.md) — **evidence** and supported
  boundaries for Volume, Aux, and master effects.
- [`CONVERSION_SETTINGS.md`](CONVERSION_SETTINGS.md) — **authoritative**
  conversion-settings lifecycle and defaults.
- [`INSTRUMENT_EDITOR_ADAPTATION.md`](INSTRUMENT_EDITOR_ADAPTATION.md) —
  **authoritative/evidence** boundary between editor behavior and verified game
  behavior.
- [`NOTE_ARTICULATION_TRANSPOSE_ALGORITHM_LOCK.md`](NOTE_ARTICULATION_TRANSPOSE_ALGORITHM_LOCK.md)
  — **authoritative** locked note, articulation, and transpose rules.
- [`GAME_SCORE_LAB_ROADMAP.md`](GAME_SCORE_LAB_ROADMAP.md) — **roadmap** for
  game-score comparison and validation tooling.

## Music semantics and transcription

- [`BDO_ARTICULATION_RULES.md`](BDO_ARTICULATION_RULES.md) — **draft** BDO
  articulation matching rules.
- [`INSTRUMENT_ARTICULATION_GUIDE.md`](INSTRUMENT_ARTICULATION_GUIDE.md) —
  **reference** general instrument and MIDI articulation guidance.
- [`MIDI_TECHNIQUE_MODEL.md`](MIDI_TECHNIQUE_MODEL.md) — **authoritative**
  MIDI technique semantics used by recommendations.
- [`MUSIC_THEORY_KNOWLEDGE_BASE.md`](MUSIC_THEORY_KNOWLEDGE_BASE.md) —
  **reference** theory, orchestration, and realism knowledge.
- [`TRANSCRIPTION_VOICE_GUIDES.md`](TRANSCRIPTION_VOICE_GUIDES.md) —
  **authoritative** transcription voice-guide interaction boundary.
- [`MARNIAN_MUSE_OPTIONAL_BOUNDARY.md`](MARNIAN_MUSE_OPTIONAL_BOUNDARY.md) —
  **authoritative** optional optimizer-package boundary.
- [`DEEPSEEK_INTEGRATION.md`](DEEPSEEK_INTEGRATION.md) — **roadmap** for a
  future optional suggestion provider, not a deterministic pipeline.

## Audio, samples, localization, and release

- [`AUDIO_SOURCE_STRATEGY.md`](AUDIO_SOURCE_STRATEGY.md) — **authoritative**
  local audio-source and fallback strategy.
- [`BDO_SAMPLE_MAPPING_STATUS.md`](BDO_SAMPLE_MAPPING_STATUS.md) —
  **evidence/status** for local sample mapping.
- [`LOCALIZATION.md`](LOCALIZATION.md) — **authoritative** locale and
  terminology rules.
- [`BASIC_PITCH_LICENSE_REVIEW.md`](BASIC_PITCH_LICENSE_REVIEW.md) —
  **evidence** for the transcription dependency license gate.
- [`WINDOWS_PACKAGING.md`](WINDOWS_PACKAGING.md) — **authoritative** Windows
  build and release procedure.

## Historical records

- [`history/INDEPENDENT_MIDI_IMPLEMENTATION.md`](history/INDEPENDENT_MIDI_IMPLEMENTATION.md) —
  **historical** independent MIDI pipeline record.
- [`history/QUALITY_PERFORMANCE_AUDIT_2026-07-29.md`](history/QUALITY_PERFORMANCE_AUDIT_2026-07-29.md)
  — **historical evidence** for the dated quality/performance audit.
- [`releases/RELEASE_NOTES_V1.0.0.md`](releases/RELEASE_NOTES_V1.0.0.md) — **release** record
  for v1.0.0.

## Evidence collections

- [`benchmarks/`](benchmarks/) contains reproducible benchmark protocols and
  result snapshots, including
  [`fragment_cleanup_protocol.md`](benchmarks/fragment_cleanup_protocol.md) and
  [`realtime_audio_multitrack_v2.md`](benchmarks/realtime_audio_multitrack_v2.md).
- [`reference/game-ui/README.md`](reference/game-ui/README.md) describes the
  private-source-safe in-game UI evidence images. They are research evidence,
  not runtime assets.
