# Performance/native Phase 0–5 evidence — 2026-08-09

## Scope and environment

This record closes the staged evaluation defined by
`docs/PERFORMANCE_NATIVE_CORE_PLAN.md`. It distinguishes a completed phase
evaluation from production promotion: a gate may correctly finish with a
rejection when correctness, device, licensing, or packaging evidence is absent.

- Windows 11 `10.0.26200`, AMD Ryzen 9 5900X (12C/24T).
- CPython 3.12.10, PySide6 6.11.1, NumPy 2.4.6.
- Real UI run: Qt `windows`, 75.001 Hz, DPR 1.0.
- Real sink negotiated 36 kHz despite a 48 kHz benchmark request.
- Native prototype built with MSVC 14.50/C++20 from original project code; no
  third-party native dependency was added to the public inventory.

## Phase 0 — trustworthy measurement

Completed changes:

- dense UI reports P99, real Qt platform, DPR and refresh rate;
- the advertised 8k ghost-note layer is now actually loaded into the canvas;
- real-time benchmark accepts explicit render quanta and multiple synthetic
  PCM sources, and reports P50/P95/P99/P99.9/max;
- sink mode measures its own complete render distribution;
- a separate native-core benchmark records low-latency block load.

Real Windows results:

| Workload | P95 | P99 | Max |
|---|---:|---:|---:|
| 120 tracks / 48k notes timeline paint | 1.91 ms | 2.36 ms | 2.36 ms |
| 12k formal + 8k ghost piano roll paint | 7.39 ms | 8.01 ms | 8.01 ms |

The current machine passes the 60 Hz target. This is not evidence for 4K/200%
DPI, 120 Hz, integrated GPUs, or other users' machines.

## Phase 1 — bounded Python improvements

The 100k-candidate profile showed default `CandidateAnnotation` construction,
duplicate token normalisation, repeated dynamic candidate-field access, and
sorting projection as the dominant costs. The implementation now:

- fast-paths already-normalised internal frozensets while preserving defensive
  external-payload validation;
- constructs validated internal default annotations without re-parsing them;
- measures candidate fields once and reuses them for order/start/end indexes;
- replaces remaining production `_on_track_changed()` compatibility calls for
  transpose/settings/global BPM with explicit `ModelChange` intent.

The same-machine 100k build changed from 962 ms to 602 ms in the final serial
run (37.4% reduction); range queries remained at a 2 microsecond median with 11
inspections. The earlier `<300 ms` proposal was rejected because it would
encourage weakening the complete per-candidate annotation contract. The locked
gate is now at least 35% reduction with unchanged semantics.

## Phase 2 — original C++ differential prototype

Added an ABI-v1 C++20 mixer and lazy `ctypes` adapter with:

- immutable preload projection and copied PCM ownership;
- exact event-frame starts, linear interpolation, loops and seek restoration;
- a fixed 1–256 voice pool and deterministic oldest-voice steals;
- no render-time allocation, file I/O, logging, or callback into Python;
- explicit rejection of prepared events requiring unsupported articulation or
  Reverb/Delay/Chorus semantics;
- an ignored local DLL build, differential tests and benchmark tool.

At 48 kHz / 256 frame / 176 voices / 32 unique sources, 3,000 blocks:

| Renderer | Effects | P99 | P99 load | Max |
|---|---|---:|---:|---:|
| Python/NumPy production renderer | Reverb + Delay + Chorus | 10.464 ms | 196.2% | 28.777 ms |
| Native ABI-v1 prototype | not implemented | 0.574 ms | 10.8% | 1.161 ms |

The comparison proves native headroom is promising but is not an equal-feature
speedup claim. The native prototype does not yet implement the production fade,
BDO lifecycle, instance policy, meters, three effect buses, limiter and every
articulation route.

## Phase 3 — controlled integration gate

The optional adapter and build chain are complete, but production promotion is
**rejected** in this phase:

- unsupported semantic events fail closed rather than silently losing DSP;
- the DLL is not loaded at module import and is not included by PyInstaller;
- the Python engine remains the only production device owner and fallback;
- the public dependency/notices digest is unchanged;
- miniaudio, FluidSynth, JUCE and Tracktion were not added.

The initial 30-minute sink run reported exactly one underrun. A code audit found
that the initial `QAudioSink` Idle transition occurred before the first PCM write
without the suppression already used by reset. This startup state was falsely
counted as an XRUN. The initial-open path now suppresses Idle until the first
accepted write, with a regression test.

The corrected 30-minute real-device run:

- 176 voices, one synthetic sample source, no effects;
- actual 36 kHz, 4,608-frame physical buffer, 2,048-frame render blocks;
- 31,623 blocks, 0 underruns, no voice steals;
- P50 3.867 ms, P95 5.405 ms, P99 6.234 ms, P99.9 7.275 ms, max 8.647 ms.

This passes stable preview playback on this device. It does not certify native
production integration or 128/256-frame low latency.

## Phase 4 — GPU canvas decision

The real Windows UI gate passed with the complete ghost layer on the current
machine. Therefore the correct Phase 4 outcome is **do not migrate** the canvas:

- retain visible-range indexes and batched QPainter paths;
- do not create one Qt object per note;
- keep Qt Quick/C++ scene graph as a future conditional experiment only after a
  reproducible real-hardware failure.

## Phase 5 — regression, repository and release gates

Completed verification:

- full suite: 1,175 tests in 262.461 seconds, all passed, one conditional skip;
- Basic Pitch packaged ONNX/CPU self-test passed inside the suite;
- focused native tests: 6 passed after a clean native rebuild;
- primary `py_compile` and package `compileall` passed;
- `tools/check_repository_hygiene.py` passed;
- `git diff --check` passed.

No public executable was rebuilt because the user did not request a
distributable and the experimental DLL is intentionally outside the public
inventory. Production packaging, dependency constraints and the approved
release-policy digest remain unchanged.

## Final decision

- Phase 0: complete/pass.
- Phase 1: complete/pass with a 37.4% candidate-build improvement.
- Phase 2: complete/pass for the explicitly bounded differential prototype.
- Phase 3: complete/reject production promotion until full semantic parity,
  native device callback evidence and a new maintainer inventory review exist.
- Phase 4: complete/reject GPU migration because the measured trigger is absent.
- Phase 5: complete/pass for source regression and repository gates.

The project can reach C++-class low-latency headroom through a narrow native
core, but the current safe release remains the PySide6 application with its
tested Python/NumPy preview engine. The next native milestone is semantic parity,
not broader framework adoption or a full rewrite.
