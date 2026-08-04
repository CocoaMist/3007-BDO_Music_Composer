# BDO Music Composer v1.1.0

> Status: immutable release record. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.1.0 focuses on editor responsiveness, reference-audio timing integrity,
transcription guidance, and preserving the user's complete creative workspace.

## Highlights

- Unified reference-audio, project, playback, and analysis time conversion so
  imported audio duration, seeking, focus projection, and transport resync use
  one explicit clock model.
- Reworked note-block, pitch-line, rhythm-projection, candidate-selection, and
  current-track focus synchronization to invalidate stale time projections
  after edits or projection changes.
- Kept dense timeline and piano-roll painting visible-range indexed, reduced
  redundant UI refreshes, and added regression coverage for large projects and
  paint-path performance.
- Added reference tempo, melody guidance, timbre grouping, transcription
  evidence, rhythm alignment, and MusiCPT-oriented backend boundaries while
  keeping experimental behavior explicit.
- Added workspace tempo controls, timeline velocity curves, multiplayer
  rehearsal synchronization, track ordering, and safer project autosave
  coordination.
- Persisted editor and analysis presentation preferences, including reference
  layers, velocity editing, timeline presentation, and other workspace UI
  settings. Removed the misleading multi-track velocity adjustment control.
- Expanded preview-effect, real-time audio, import/export round-trip, project
  schema, localization, accessibility, focus, and dense-project regression
  coverage.

## Verification

The public artifact is accepted only after the full unit/UI/codec/audio suite,
repository hygiene check, deterministic public-license inventory gate, frozen
transcription self-test, and isolated ten-second startup smoke test pass. The
final executable size and SHA-256 are recorded in the GitHub release assets and
release description.

## Important notes

- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- The Windows executable is not code-signed and may trigger a SmartScreen
  unknown-publisher warning.
- Preview audio and game-effect simulation remain approximations unless backed
  by explicit in-game A/B evidence.
- Projects, Owner IDs, character names, reference audio, local game samples,
  autosaves, and exported scores remain local and are not included in the
  source repository or release artifact.
