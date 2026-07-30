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

## Reviewed sampled-General-MIDI decision (2026-07-30)

A MIDI parser does not produce audio. Replacing the procedural renderer needs
two separately licensed pieces: a SoundFont synthesizer and an SF2/SF3 sample
bank. The review selected **FluidSynth plus an external SoundFont** as the
quality target, but did not add either one to the current executable.

| Candidate | Result | Reason |
|---|---|---|
| [FluidSynth](https://www.fluidsynth.org/) | Selected renderer | Mature SF2/SF3 implementation, robust real-time modulation, offline rendering, active Windows releases, and an embeddable shared-library API. |
| [TinySoundFont](https://github.com/schellingb/TinySoundFont) / `tinysoundfont==0.3.7` | Rejected as the quality backend | MIT and self-contained; its CPython 3.12 Windows extension is only about 304 KiB. However, the evaluated GM banks rely heavily on SF2.01 modulators, while TinySoundFont implements a smaller synthesis surface. Its wheel also declares PyAudio even though this app already owns Qt audio output. |
| MuseSampler | Rejected | Its integration API is visible in MuseScore, but the sampler and Muse Sounds are not open-source redistributable components. |

FluidSynth itself is LGPL-2.1-or-later. Its licensing FAQ requires a distributed
application to keep the dynamically linked library independently replaceable.
Embedding its DLL inside the current PyInstaller one-file payload is therefore
not the reviewed release shape. The intended boundary is an optional sidecar
component in Local AppData (or a future folder/installer distribution), loaded
off the callback thread and replaceable without rebuilding Music Composer.

### SoundFont assessment

The preferred reference bank is
[MuseScore General 0.2](https://vectorlinux.osuosl.org/pub/musescore/soundfont/MuseScore_General/):
its SF3 is about 38 MiB, covers GM/GS, documents its sample sources, and is
distributed under the MIT license with required copyright acknowledgements.
Its own README says accurate playback requires robust SF2.01 modulator support
and lists FluidSynth as a compatible renderer. FluidR3Mono is a smaller MIT
fallback for lower-memory installations.

[GeneralUser GS 2.0.3](https://github.com/mrbumpy409/GeneralUser-GS) sounds good
for its roughly 30.7 MiB memory footprint, but its upstream license explicitly
says that some source samples cannot be identified with complete certainty.
That is acceptable for user-supplied local evaluation, not for the default
public-release inventory.

No SoundFont is downloaded, copied into Git, or bundled in the EXE by the
current change. Selecting a bank must remain a local preview preference and
must never enter a project or BDO score.

## BDO to General MIDI preview map

The executable-independent policy lives in `bdo_midi/gm_preview.py`. Program
numbers below are zero-based, matching SoundFont APIs. Beginner and Florchestra
variants share a GM preset where General MIDI has no honest way to distinguish
the two game banks.

| BDO ID / type | GM bank:program | Preview role |
|---|---:|---|
| `00` beginner guitar | `0:24` | nylon acoustic guitar |
| `01` beginner flute | `0:73` | flute |
| `02` beginner recorder | `0:74` | recorder |
| `04` hand drum | `0:116` | melodic taiko; preserve legal BDO hit pitches |
| `05` cymbals | `128:0` | standard kit with explicit three-lane cymbal map |
| `06` beginner harp | `0:46` | orchestral harp |
| `07` beginner piano | `0:0` | acoustic grand piano |
| `08` beginner violin | `0:40` | violin |
| `0A` Florchestra guitar | `0:25` | steel acoustic guitar |
| `0B` Florchestra flute | `0:73` | flute |
| `0D` drum set | `128:0` | standard kit; BDO 48-64 use semantic reverse mapping |
| `0E` Marnibass | `0:38` | synth bass 1 |
| `0F` contrabass | `0:43` | contrabass |
| `10` harp | `0:46` | orchestral harp |
| `11` piano | `0:0` | acoustic grand piano |
| `12` violin | `0:40` | violin |
| `13` handpan | `0:114` | steel drums, the closest standard GM preset |
| `14` Wavy Planet | `0:81` | saw lead |
| `18` Illusion Tree | `8:80`, fallback `0:80` | sine variation, then square lead |
| `1C` Secret Note | `0:80` | square lead |
| `20` Sandwich | `0:89` | warm pad as an explicitly approximate triangle family |
| `24` Silver Wave | `0:27` | clean electric guitar |
| `25` Highway | `0:29` | overdriven guitar |
| `26` Hexe Marie | `0:30` | distortion guitar |
| `27` clarinet | `0:71` | clarinet |
| `28` horn | `0:60` | French horn |

Marnian `basic/stereo/super/superoct` identity is represented by bounded,
deterministic one/two/three-layer unison recipes. These are generic editing
approximations, not evidence of game oscillators or DSP. Unknown BDO instrument
IDs fail closed instead of silently becoming piano.

The drum-set reverse map is semantic rather than chromatic: kick maps to GM 36,
snare/side/flam to 37/38, five toms to 50/48/47/45/41, closed/pedal/open hi-hat
to 42/44/46, crash/ride to 49/51, and the two game roll lanes to snare 38. A
future renderer must implement the short/long roll repetition itself; the map
does not pretend that one GM note contains the BDO roll behavior.

## Integration gates

Before the selected renderer can replace the procedural fallback:

1. Pin exact FluidSynth, SoundFont, and sidecar hashes; generate notices and
   add them to the fail-closed release inventory.
2. Decide whether the public artifact changes from one file to a folder, or add
   a separately replaceable optional-component installer. Do not hide the LGPL
   DLL inside the one-file executable.
3. Load the SoundFont and allocate every render buffer before playback. No DLL
   discovery, SF3 decode, file I/O, or unbounded allocation may enter the audio
   callback.
4. Preserve exact event-frame scheduling, per-track meters/effect sends, the
   bounded voice pool, Seek, note audition, and cancellation semantics.
5. Validate every route and fallback against the pinned bank, then pass the
   existing 64/176/256-voice benchmarks and an offscreen/frozen startup test.
6. Run a listening matrix across all 26 logical instruments, four Marnian modes,
   17 drum lanes, low/high pitches, and at least three velocities. Label the
   result “generic SoundFont preview,” never BDO-verified audio.

Until those gates pass, the shipped procedural family renderer remains the
safe zero-package fallback and local `.bdosamples`/prepared BDO sources remain
the only game-timbre path.
