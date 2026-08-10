# Performance refinement evidence — 2026-08-10

## Scope and boundary

This pass re-evaluates the current Python/Qt and experimental C++ performance
boundaries after Phase 0–10. It does not promote the native mixer, add a new
dependency, change `TrackState`/`Note`, or broaden the local PAZ boundary. The
application still exposes only allow-listed game-art import; it does not become
a general PAZ extractor.

Environment: Windows 11 `10.0.26200`, CPython 3.12.10, PySide6 6.11.1,
NumPy 2.4.6, Qt `windows`, DPR 1.0, reported refresh 60.006 Hz.

## Baseline diagnosis

| Workload | Result | Decision |
|---|---:|---|
| 100k transcription candidates: first index | 401.57 ms | Passes the locked improvement gate; keep Python owner |
| 100k candidate range query | 2.00 µs median / 11 inspections | Indexed query is not a hotspot |
| 100k conversion cold validation | 59.54 ms | Passes the <100 ms target |
| Conversion revision-cache hit | 0.30 µs median | Snapshot identity is effective |
| 120 tracks / 48k notes timeline paint | 1.72 ms P95 | Large 60 Hz margin |
| 12k notes + 8k ghosts piano-roll paint | 11.98 ms P95 / 12.43 ms P99 | Passes 60 Hz, but P95 was too close to the 12 ms engineering target |
| Python mixer, 176 voices, 32 sources, all effects, 48 kHz / 256 frames | 6.04 ms P99 / 113.2% block load | Does not meet the 70% P99 production gate |
| Experimental native ABI v1, unequal basic-mix workload | 0.253 ms P99 / 4.75% block load | Strong headroom, but not production-equivalent |

The Python audio result had zero synthetic offline underruns because the
producer can run slower than real time; its `1.132` P99 load still means it
cannot claim a stable 256-frame real-device budget with all effects.

## Piano-roll call-level finding

A 100-frame `cProfile` run found repeated per-frame work that carried no new
semantic information:

- the same track color was parsed once or twice for every visible note;
- note fill colors were recomputed for repeated `(velocity, ntype)` pairs;
- ghost colors were parsed for every visible ghost even when tracks shared a
  color;
- horizontal pitch guides already present in the cached background were drawn
  again when no transcription image overlaid them.

The paint path now resolves track semantics once per frame, caches bounded
visual combinations within that frame, and redraws cached pitch guides only
when a reference-evidence layer can cover them. Geometry, visible-range
indexes, velocity, articulation, selection, labels and evidence ordering are
unchanged.

## Same-load result after refinement

The final 100-iteration real-window run produced:

| Workload | Before | After | Change |
|---|---:|---:|---:|
| Piano-roll paint P95 | 11.98 ms | 7.85 ms | -34.5% |
| Piano-roll paint P99 | 12.43 ms | 8.17 ms | -34.3% |
| Piano-roll paint max | 12.43 ms | 8.57 ms | -31.1% |
| Timeline paint P95 | 1.72 ms | 1.61 ms | effectively unchanged |

This satisfies the optional 120 Hz P95 target on this machine, but it is not a
4K/200% DPI, integrated-GPU, or multi-machine certification. A deterministic
regression now verifies that one frame resolves the track color once and
computes each visible `(velocity, ntype)` fill combination once.

## Code capability assessment

The codebase can continue to improve without a rewrite because the important
owners are already separable: interval indexes, revision-scoped validation,
workspace refresh intent, immutable export snapshots, optional native ABI and
fail-closed parity gates. The strongest current engineering traits are explicit
domain invariants, deterministic tests, visible-range painting, background
workers and narrow experimental boundaries.

The remaining professional-grade gaps are concrete:

1. the Python all-effects mixer misses the 256-frame P99 gate;
2. native ABI v1 lacks BDO voice lifecycle, fades, instance policy, meters,
   three effect buses, limiter and full articulation parity;
3. UI evidence still needs 4K/200% DPI and lower-tier hardware runs;
4. `main_window.py` remains a large composition host and should continue
   routing new domain behavior into focused owners;
5. performance evidence should add input-to-paint latency and long-duration
   P99.9 distributions, not only isolated `grab()` timing.

The next native milestone is semantic parity, not another basic-mix speed
record. Production promotion remains rejected until equal-feature differential
tests, 512/256-frame real-device gates, packaging inventory and rollback tests
all pass.

## Next semantic tranche: audible lifecycle envelopes

The first post-audit native tranche adds one narrowly testable production
semantic rather than another unequal-feature benchmark:

- ABI v1 keeps `bdo_audio_add_event_v1` source/binary behavior and advertises a
  new voice-envelope capability;
- the capability-gated `bdo_audio_add_event_v2` accepts explicit audible,
  attack and release frame counts;
- seek reconstruction restores envelope age instead of restarting the ramp;
- Python retains separate V1/V2 immutable event projections and requires an
  explicit audible lifecycle when projecting prepared production events;
- reverb, delay, chorus, articulation and other unsupported prepared events
  still fail closed.

A prepared event with a four-frame attack, sixteen audible frames and a
four-frame release matched the Python production renderer within the locked
`1e-6` maximum / `1e-7` RMS parity tolerances, including silence after the
audible boundary. The normal native suite, MSVC `/W4` release build, ASan build
and an ASan envelope smoke test passed. The 176-voice / 32-source / 48 kHz /
256-frame basic workload remained well below budget at 0.348 ms P99 (6.53%
load); this remains an unequal-feature diagnostic until all production DSP and
voice policies are implemented.
