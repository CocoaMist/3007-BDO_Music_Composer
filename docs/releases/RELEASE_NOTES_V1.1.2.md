# BDO Music Composer v1.1.2

> Status: immutable release record. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.1.2 improves score-wide velocity editing, preview transport reliability,
conversion-error presentation, and extension support while preserving the
current editor model through preview and BDO v9 export.

## Highlights

- Added a score-wide velocity-base control with a selectable `-127..127`
  offset and optional equalization, plus the same operation in each track's
  context menu.
- Kept game track `Volume` independent from note velocity and updated both BDO
  per-note velocity bytes without losing the original relative dynamics when
  moving the base repeatedly or returning it to zero.
- Preserved pause requests made while preview samples are still loading, so
  load completion no longer restarts playback after the user has paused it.
- Replaced timeline pitch guesses with exact validator note identities. Only
  notes attached to current export errors are marked red; warnings, merge
  notices, and cleared issues no longer leave false or stale red blocks.
- Added scoped workspace refresh plans and per-track timeline index updates to
  reduce unnecessary full-timeline rebuilds after non-structural edits.
- Added a documented developer SDK with Qt-free score inspection/export APIs,
  optional reusable UI entry points, examples, and deterministic source-SDK
  packaging.
- Extracted velocity transactions and validation presentation from the main
  window, restored the architecture line-budget gate, and kept the supported
  1160-pixel multi-language workspace responsive.

## Verification

The source release passed the complete 1,152-test unit/UI/codec/audio suite
with one environment-dependent test skipped, plus repository hygiene and
compilation checks. The public artifact is accepted only after the exact
dependency-license inventory gate, frozen Basic Pitch ONNX/CPU inference test,
isolated ten-second GUI startup test, SHA-256 generation, and final artifact
inspection pass.

## Important notes

- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- The Windows executable is not code-signed and may trigger a SmartScreen
  unknown-publisher warning.
- Preview audio and game-effect simulation remain approximations unless backed
  by explicit in-game A/B evidence.
- Projects, Owner IDs, character names, reference audio, local game samples,
  autosaves, exports, and private caches remain local and are not included in
  the source repository or release artifact.
