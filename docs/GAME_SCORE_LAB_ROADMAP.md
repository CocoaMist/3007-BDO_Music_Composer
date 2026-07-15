# BDO game score laboratory roadmap

This repository is a hobby project for the maintainer and friends. It is not
trying to become a general DAW, hosted service, marketplace, or commercial
product. Work proceeds in small playable/researchable slices while keeping the
editor model and export path regression-safe.

## Development balance

- 60% BDO format, validation, score comparison, and game evidence;
- 25% editing quality of life;
- 15% optional optimizer and Marnian Muse experiments.

## Implemented foundation

- Versioned `BdoProfile` with evidence state and game limits.
- Structured, location-aware conversion issues and an export safety gate.
- Full BDO v9 score snapshots, post-export structural readback, and two-score diff.
- Project schema migration plus privacy-safe A/B experiment records.
- Wwise key/velocity-zone coverage and audio alignment measurements.
- Piano-roll ghost notes, an editable velocity lane, and draft loop playback.
- `.bdoopt` algorithms remain an independent side path.

## Next small experiments

1. Grow the profile from actual game A/B cells, not assumptions.
2. Add a waveform view for one game/local audio pair using the existing alignment report.
3. Move note-edit actions onto a project-level command stack one operation at a time.
4. Add explicit loop-range handles after whole-draft looping has been exercised.

Every new claim must retain `verified`, `inferred`, or `approximate` evidence.
Game audio, private scores, Owner IDs, character names, and machine-local paths
remain outside Git history.
