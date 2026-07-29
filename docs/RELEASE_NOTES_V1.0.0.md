# BDO Music Composer v1.0.0

This is the first stable major release of BDO Music Composer. It brings the
live editor model, BDO v9 export, project persistence, approximate audio
preview, audio-assisted transcription, multilingual UI, and public-release
safety gates together in one complete Windows workflow.

> [!NOTE]
> v1.0.0 is the first public major release. Core workflows have passed the
> automated and frozen-application checks listed below, but minor bugs or
> environment-specific compatibility issues may still appear. They are being
> actively investigated and fixed. Please report reproducible problems through
> [GitHub Issues](https://github.com/CocoaMist/3007-BDO_Music_Composer/issues).

## Highlights

- Redesigned the home page and shared toolbar with a compact local character
  identity entry, project/score instrument summaries, and original home-page
  artwork. Page-transition seams and multilingual layout clipping were also
  fixed.
- Export-blocking problems are now marked directly on the affected instrument
  tracks. Duplicate instruments use a non-blocking attention color, while the
  global information panel appears only when status changes instead of leaving
  a permanent error banner above the timeline.
- Fixed the piano-roll marquee selection overlay obscuring the canvas and added
  a regression test for custom painter-state isolation.
- Added bounded, built-in generic MIDI approximation sounds for systems without
  local game samples. Users can switch between automatic selection, local BDO
  samples, and the built-in source; fallback sounds are never presented as
  authentic in-game audio.
- Unified volume, articulation, sample routing, seeking, pause behavior, and
  bounded voice lifecycles across real-time and offline preview. High-load
  interpolation and Reverb/Delay/Chorus hot paths were optimized.
- Export and autosave now use immutable snapshots, single-writer coalescing,
  and same-directory atomic replacement. Home-page discovery reads only a
  bounded, privacy-safe index, preventing background work from racing the live
  editor or damaging user-owned destination files.
- Application shutdown now explicitly stops reference-audio decoding, clears
  the media source, and detaches the platform audio output. Preview also checks
  for an output device before entering the Windows audio backend, allowing
  systems without an available audio device to fail fast and exit cleanly.
- Completed Simplified Chinese, Traditional Chinese, English, Japanese, and
  Korean UI coverage, with reproducible regression/performance baselines for
  dense timelines, piano rolls, 100,000-note queries, and audio effects.
- Pinned the complete Windows/Python 3.12.10 dependency closure. Public builds
  use a deterministic schema-2 license inventory and fail closed whenever a
  dependency, model, or native-library digest changes.

## Verification

- 748 unit, UI, codec, export, and audio regression tests passed; 1 test was
  skipped as expected.
- `py_compile` passed for the primary entry points.
- The frozen Basic Pitch ONNX/CPU inference self-test passed.
- The same frozen executable passed an isolated 10-second GUI startup check.
- License inventory: schema 2, 37 runtime packages, 0 unresolved entries.
- Inventory SHA-256:
  `68fa9a2c6dd12608ff7ebe80a3a57be65efdf989a6cf55eca19cc70e732bf23b`.
- `BDO-Music-Composer.exe`: 182,813,391 bytes.
- Executable SHA-256:
  `9353bff6913f4146bc3a3c37f560b9d2ae27956e0db309bb48a443e2b9d48bc1`.

## Important notes

- This is an unofficial community tool. It is not affiliated with, endorsed by,
  or supported by Pearl Abyss, and it does not distribute game assets.
- The executable is not code-signed, so Windows SmartScreen may show an unknown
  publisher warning. Download it only from this repository's GitHub Releases
  page and verify the SHA-256 above.
- Built-in sounds, game effects, and articulation playback remain approximate
  previews. They are not described as verified without in-game A/B evidence.
- Experimental transcription fragment cleanup remains an explicit opt-in;
  `preserve` is still the safe default.
- Owner IDs, character names, projects, reference audio, local game samples,
  autosaves, and exported scores remain on the user's computer and are not
  included in the source repository or release artifact.
