# BDO Music Composer v1.2.0

> Status: immutable release record. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.2.0 adds signed, recoverable single-EXE updates and a percussion-aware
note-editing surface while preserving the current editor model and BDO v9
export rules.

## Highlights

- Added a frozen-Windows self-updater that checks signed stable-channel
  manifests from GitHub and Gitee mirrors without treating either host as a
  trust root.
- Added background download with bounded reads, allow-listed HTTPS assets,
  SHA-256 and size validation, rollback prevention, and Local AppData staging.
- Kept the application as one distributed EXE. A staged new EXE performs the
  next-launch replacement while retaining the old EXE until the real new GUI
  reports healthy; failed launches and health checks roll back automatically.
- Added software-update preferences for automatic checks, background download,
  mirror selection, and manual checks. Source launches and packaged startup
  self-tests remain network-free.
- Added an external-key release tool that creates deterministic update
  manifests and detached RSA-3072 signatures. The private release key remains
  outside the repository and build artifacts.
- Added automatic percussion-roll presentation for canonical BDO drum tracks
  and imported GM channel-10 drum tracks, including named drum lanes,
  localized labels, diamond note markers, and unmapped-key warnings.
- Kept drum presentation separate from note normalization: imported GM pitches
  and articulation values are not silently rewritten, while canonical BDO drum
  notes continue to use pitches 48-64 and `ntype=99` where required.

## Verification

The source release passed the complete unit/UI/codec/audio suite with one
environment-dependent test skipped, plus focused signed-manifest,
replacement/rollback, percussion-editor, localization, compilation, startup,
and repository-hygiene checks. Public binaries still require the exact
dependency-license inventory gate, frozen Basic Pitch ONNX/CPU inference test,
isolated ten-second GUI startup test, SHA-256 generation, signed channel
publication, and final artifact inspection.

## Important notes

- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- The first version containing the updater must still be distributed normally;
  seamless updates apply to later signed releases.
- The Windows executable is not Authenticode-signed and may trigger a
  SmartScreen unknown-publisher warning. Update-manifest signatures protect
  update integrity but do not replace Windows publisher signing.
- Projects, Owner IDs, character names, reference audio, local game samples,
  autosaves, exports, and private caches remain local and are not included in
  the source repository or release artifact.
