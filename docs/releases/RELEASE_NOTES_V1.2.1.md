# BDO Music Composer v1.2.1

> Status: public-release candidate. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.2.1 simplifies preview audio to two explicit choices: the built-in general
source and a user-selected sample pack. The release page may provide the
optional CC0 approximation pack as a separate asset beside the Windows app.

## Highlights

- Reduced preview selection to **Built-in General Source** and **Sample Pack**.
  The chosen pack path is remembered locally and can be changed at any time.
- Fixed source switching so changing the pack or sample root invalidates stale
  decoded samples instead of continuing to play the previous source.
- Added bounded PCM WAV decoding for compatible 16-bit and 24-bit sample-pack
  content while keeping file I/O and decoding outside the audio callback.
- Kept the application usable without an external pack. Missing or invalid
  packs fail back to the built-in preview source without changing score data.

## Optional CC0 sample pack

The separately downloadable
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples` contains selected,
unmodified WAV bytes from:

- [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE), CC0,
  revision `6dd651d55dde97fd4028699be9d4481f26917891`;
- [Versilian Community Sample Library](https://github.com/sgossner/VCSL), CC0,
  revision `c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e`;
- [FreePats CC0 instrument banks](https://freepats.zenvoid.org/).

The pack manifest records provenance and SHA-256 per audio slot. It contains no
Black Desert client audio and is an approximate editing preview, not
game-original or A/B-verified sound.

- Size: `753,225,838` bytes
- SHA-256: `82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`

## Verification

The release candidate must pass the complete unit/UI/codec/audio suite,
repository hygiene, source compilation, the public dependency-inventory gate,
sample-pack contract validation, frozen Basic Pitch inference, and the frozen
ten-second GUI startup self-test. Authenticode publisher signing is optional;
unsigned releases may trigger a Windows SmartScreen warning.

Source verification on 2026-08-11 passed all 1,205 tests (one skipped), focused
audio/settings/update checks, source compilation, repository hygiene, and
sample-pack validation for all 1,465 manifest records.

## Important notes

- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- The sample pack is a separate optional asset and is not embedded in the EXE.
- Projects, Owner IDs, character names, external samples, autosaves, exports,
  private caches, and signing keys remain local.
- The application does not list, extract, convert, package, download, or
  distribute Black Desert client audio.
