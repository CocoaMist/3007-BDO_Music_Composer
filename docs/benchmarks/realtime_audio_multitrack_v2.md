# Real-time multitrack mixer profile v2

This profile targets the remaining callback cost after same-source fixed tiles.
It uses user-local game samples only; no sample path or decoded asset is stored
in this report.

## Workload

- 36 kHz stereo Int16 output and 2,048-frame production render blocks.
- 22 mapped logical instrument banks, 176 requested simultaneous notes, 160
  resolved events, 67 distinct decoded Wwise samples, and 153 peak voices.
- Eight interleaved runs per variant. Each run measures 25 steady-state blocks
  after one attack/warm-up block; the same prepared events and PCM are used for
  both variants.
- Baseline disables only cross-source arena batching. Same-source tiles,
  scheduling, lifecycle, meters, limiter, and all admission rules remain on.

## Result

| Variant | Median block | P95 block | Maximum block |
|---|---:|---:|---:|
| Same-source tiles | 9.927 ms | 12.577 ms | 13.550 ms |
| Bounded cross-source arena | 7.926 ms | 9.919 ms | 10.441 ms |
| Reduction | 20.16% | 21.13% | 22.94% |

One block has a 56.89 ms audio budget. This is a device-free producer profile,
not evidence that every Windows audio driver is underrun-free. The real sink
must still be checked because scheduler and driver stalls are outside the
mixer benchmark.

## Locked behavior

The arena is built during cancellable preload and is capped at 192 MiB. It
replaces individual steady-state sample arrays with immutable views rather
than adding callback I/O. Projects above the cap use the existing same-source
and scalar paths. Logical voices remain independent, so note timing, pitch,
gain, articulation, lifecycle, Seek state, instance limits, meters, and voice
stealing do not change.

Fallback articulation envelopes now use two preallocated frame arrays.
Transport status copies its small snapshot while holding the mixer lock, then
sorts telemetry and builds dictionaries after releasing it. A dense mix that
has already consumed at least 45% of its previous block budget can temporarily
use 87.5% of the existing 128 ms physical queue; neither the buffer capacity
nor the 2,048-frame render ceiling grows.

## Reproduction

```powershell
$env:BDO_AUDIO_ROOT = '<local sample root>'
\.venv\Scripts\python.exe tools\benchmark_realtime_audio.py `
  --mode offline --workload multitrack --voices 176 --seconds 3 `
  --audio-root $env:BDO_AUDIO_ROOT

# Callback baseline; preload still packs the same bounded cache.
\.venv\Scripts\python.exe tools\benchmark_realtime_audio.py `
  --mode offline --workload multitrack --voices 176 --seconds 3 `
  --audio-root $env:BDO_AUDIO_ROOT --disable-cross-source-arena
```
