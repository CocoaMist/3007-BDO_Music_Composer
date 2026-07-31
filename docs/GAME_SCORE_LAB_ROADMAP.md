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
- Time-aligned reference waveforms, shared transport/playhead, and explicit
  A–B ranges in the timeline and embedded transcription editor.
- Project and draft undo/redo, piano-roll ghost notes, an editable velocity
  lane, and bounded draft playback.
- Typed conversion settings, stable track-ID pitch transforms, immutable export
  snapshots, and a complete Qt-free `ProjectLoadPlan` prepared before UI commit.
- Recursively detached `ProjectMetadataSnapshot` save input, so nested UI
  mappings/lists cannot race the coalescing writer.
- Pure `TranscriptionCommitPlan` classification between editor-local drafts and
  the single formal Apply/OK transaction, followed by a two-stage executor that
  rolls back model/history failures and keeps autosave alive after view errors.
- One Qt-free `preview_midi_writer` owner for deterministic standard-MIDI
  projection; BDO v9 output remains on the separate export/codec path.
- `.bdoopt` algorithms remain an independent side path.

## Near-term stability work

1. Split model, view, and transport refresh domains so zoom/layout changes do
   not trigger unrelated validation or transcription work.
2. Extend the transcription executor's model-publish/compensable-effects pattern
   to `ProjectLoadPlan`; keep I/O, widgets, and mutable tracks out of pure plans.
3. Add a `TranscriptionWorkspacePresenter` that projects domain state into
   controls/text/layers without becoming another route or commit fact source.
4. Improve conversion-check actions and explanations before adding another
   authoring surface.

## Evidence-driven experiments

1. Grow the profile from actual game A/B cells, not assumptions.
2. Record target-soundcard real-sink XRUN/P95 evidence separately from the
   existing device-free algorithm benchmarks.
3. Use private BDO score corpora for lossless and edited round-trip checks
   without copying Owner IDs, character names, or score payloads into Git.
4. Keep transcription cleanup on `preserve` by default; promote an automatic
   profile only after a new untouched holdout passes every fixed quality and
   performance gate.

Every new claim must retain `verified`, `inferred`, or `approximate` evidence.
Game audio, private scores, Owner IDs, character names, and machine-local paths
remain outside Git history.
