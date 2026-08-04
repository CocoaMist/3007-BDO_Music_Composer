# BDO Music Composer v1.1.1

> Status: immutable release record. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.1.1 is a focused correctness update for BDO score round trips and velocity
editing. It also includes the interface screenshots added after v1.1.0.

## Highlights

- Kept game track `Volume` as the independent 0-100 instrument slider while
  preserving each note block's 0-127 `Velocity` data through editor changes,
  project state, and BDO import/export.
- Reconciled the game's paired per-note velocity bytes after move, resize,
  pitch, articulation, and explicit velocity edits without binding an edited
  note to the wrong source record.
- Preserved empty game-instrument lanes and their Volume/effect configuration
  instead of rebuilding them as default instruments when they contain no notes.
- Reused an untouched source score byte-for-byte when it contains unknown
  opaque data, and now fails safely instead of silently discarding that data
  when an edited score cannot be represented losslessly.
- Aligned independent export verification with the editor's empty-lane and
  source-preservation semantics.
- Clarified the timeline control label as track Volume and added regression
  coverage for score rebuilds, export workflows, editor commits, and velocity
  curves.
- Added current home, timeline, and piano-roll screenshots to the localized
  README guides.

## Verification

The public artifact is accepted only after the full unit/UI/codec/audio suite,
real-score round-trip checks, repository hygiene check, deterministic public
license-inventory gate, frozen transcription self-test, isolated ten-second
startup smoke test, and final archive privacy inspection pass.

## Important notes

- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- The Windows executable is not code-signed and may trigger a SmartScreen
  unknown-publisher warning.
- Projects, Owner IDs, character names, reference audio, local game samples,
  autosaves, and exported scores remain local and are not included in the
  source repository or release artifact.
