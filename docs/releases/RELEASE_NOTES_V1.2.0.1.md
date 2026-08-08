# BDO Music Composer v1.2.0.1

> Status: test release record. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.2.0.1 is the first positive fourth-component test revision. It validates
the signed dual-mirror single-EXE update path introduced in v1.2.0 and makes
the authenticated update notes visible while the package downloads.

## Highlights

- Added a non-modal update-details window that displays the signed,
  locale-appropriate release notes, selected mirror, download progress, and
  next-launch installation state without blocking editor work.
- Added a positive numeric fourth version component for test revisions.
  `1.2.0.1` sorts after `1.2.0` and before `1.2.1`; `.0` and leading-zero
  revisions are rejected.
- Connected the production updater to the live public Gitee mirror at
  `raionnyan/3007-BDO_Music_Composer` and corrected both raw channel paths to
  the repositories' real `master` branch.
- Retains the v1.2.0 signed-manifest verification, bounded background download,
  next-launch replacement, real-GUI health acknowledgement, automatic rollback,
  and percussion-aware piano-roll presentation.

## Verification

The source release passed 1,165 unit/UI/codec/audio tests with one
environment-dependent test skipped, plus repository hygiene and source startup
checks. The public artifact additionally requires the exact dependency-inventory gate, frozen
Basic Pitch ONNX/CPU inference, a ten-second frozen GUI startup test, identical
artifact hashes on GitHub and Gitee, detached manifest-signature verification,
and anonymous retrieval of both stable-channel copies.

## Important notes

- This is a test revision, not a new ordinary patch-numbering convention.
- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- Update-manifest signatures protect the update chain but do not replace
  Windows Authenticode publisher signing; SmartScreen may still warn.
- Projects, Owner IDs, character names, reference audio, local game samples,
  autosaves, exports, and private caches remain local.
