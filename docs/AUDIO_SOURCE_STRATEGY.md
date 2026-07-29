# Audio source strategy

## Shipped source modes

The preview selector persists one of three policies under
`audio_sources.preview_mode`:

- `auto`: prefer a valid user-owned BDO sample directory and otherwise use the
  built-in generic renderer.
- `bdo`: lock the local BDO source and report why it is unavailable; never
  silently substitute another source.
- `generic`: lock the built-in, file-free General MIDI renderer.

The generic renderer is original project code. It synthesizes bounded,
deterministic instrument-family voices before playback and performs no file I/O
or allocation in the real-time callback. It covers every current logical BDO
instrument and generates separate BDO drum-piece one-shots. It is useful for
editing without a sample pack, but is not BDO game audio and must never be
presented as A/B-verified game timbre.

## Sampled General MIDI assessment

A sampled GM/GS bank could improve realism further, but it changes the release
inventory, executable size, native runtime, and third-party notice surface.
Therefore no downloaded SoundFont is vendored by this change.

The preferred future evaluation target is an MIT-licensed full-GM bank such as
[MuseScore_General or FluidR3](https://musescore.org/en/node/101), not a bank
with ambiguous or sample-specific redistribution restrictions.
[FluidSynth](https://www.fluidsynth.org/api/Introduction.html) is a capable
cross-platform SF2/SF3 runtime, but its
[LGPL dynamic-linking and user-replacement requirements](https://www.fluidsynth.org/wiki/LicensingFAQ/)
need a specific Windows one-file packaging design. The SoundFont's own terms
must be reviewed separately from the synthesizer's license.

Before a sampled bank can ship, all of these gates are required:

1. Pin the exact bank and renderer versions and record SHA-256 hashes.
2. Review every sample attribution and redistribution term; update
   `THIRD_PARTY_NOTICES.md`.
3. Add the renderer and bank to the exact-inventory release policy and obtain a
   new maintainer approval.
4. Keep decode/preload outside the audio callback, bound resident PCM, and pass
   the existing 64/176/256-voice benchmarks.
5. Verify all current logical instruments and BDO drum pieces have a deliberate
   preset mapping, with a deterministic fallback for missing presets.
6. Pass clean one-file startup, replacement/notice compliance, and listening
   tests before calling the source “high quality”.

Until those gates pass, the built-in family renderer is the safe zero-package
default and local `.bdosamples`/prepared BDO sources remain user-owned.
