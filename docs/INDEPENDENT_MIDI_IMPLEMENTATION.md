# Independent MIDI-to-BDO implementation

Status: v0.3.0 release candidate, 2026-07-23.

## Boundary

- `bdo_midi` owns the five-field `Note`, Standard MIDI parsing, GM names,
  GM-to-BDO policy, drum mapping, and pure note transforms.
- `bdo_export` owns logical-track merging, velocity policy, articulation and
  second-velocity binding, game track settings/volume, physical splitting,
  summaries, and document construction.
- `bdo_codec` exclusively owns the BDO v9 binary layout and ICE transform.

The application, WPF sidecar, scripts, tests, and PyInstaller specification
import these packages directly. There is no `midi2bdo` or `_ice` compatibility
module, vendor-path insertion, or runtime fallback.

## Implementation evidence

The replacement was written around Mido's public message API, the project's
behavioral tests, decoded game-save evidence, and the documented BDO v9
invariants. A normalized line-sequence comparison against the historical
vendor file produced low similarity ratios of 0.007–0.069 for the four main
replacement modules; matching long lines were limited to ordinary validation
messages and direct function calls.

Automated coverage includes MIDI type 0/1 import, stable equal-tick ordering,
tempo defaults and changes, `/4` meter enforcement, program changes, channel
10 percussion, repeated notes, velocity-zero note-off, sustain, dangling
notes, pitch/pressure/control events, lyrics, all 128 GM programs, canonical
drum preservation, BDO physical-track boundaries, dual velocities, settings,
volume, articulations, and encrypted structure.

The private corpus gate reads local scores without logging identity fields.
The v0.3.0 baseline is 10 files and 10,569 note records with byte-identical
lossless decode/encode for every file.

## Release gate

Candidate builds must pass the full unit suite, syntax checks, offscreen UI
smoke tests, a clean PyInstaller build, archive scans for historical modules
and private/generated data, and a 10-second Windows startup check. Public
release remains gated on in-game import/save verification for normal melodic
tracks, drums, four Marnian modes, electric-guitar FX, game volume, and track
settings.
