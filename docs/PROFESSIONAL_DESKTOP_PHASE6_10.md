# 桌面端 Phase 6–10：过门禁才算完成

“完成”只表示仓库里有能执行的门禁和回归测试。证书、真实音频设备、辅助技术用户或
游戏 A/B 没测到，就明确写没测到，不能拿模拟代替。

## Strategy: preserve the foundation, create the advantage

The foundation is current-editor truth, atomic user-data publication,
deterministic BDO v9 output, local-only processing, bounded real-time work, and
fail-closed updates. The advantage is an explainable BDO semantic compiler and
an optional native mixer that can be promoted only after semantic parity.

## Phase 6 — trusted release

- GitHub Actions dependencies are pinned by immutable commit SHA.
- `packaging/windows/build.ps1 -PublicRelease` enforces the reviewed dependency
  inventory and release checks without requiring a publisher certificate.
- Optional `packaging/windows/sign-and-verify.ps1` signing uses SHA-256,
  requests an RFC 3161 timestamp, invokes SignTool verification, and checks
  Windows reports a `Valid` signature whenever a certificate thumbprint is
  supplied.
- Every build produces a SHA-256 checksum and deterministic SPDX 2.3 evidence
  through `scripts/generate_release_evidence.py`.
- `.github/workflows/windows-release.yml` builds and tests the reviewed release,
  generates evidence, and attaches hosted-build provenance. Optional publisher
  signing remains outside ordinary CI because no private signing material
  belongs in GitHub source or repository secrets.

Authenticode is an optional publisher-identity enhancement, not a public
release gate. Unsigned releases may still trigger Windows SmartScreen.

## Phase 7 — recovery and supportability

- Crash logs rotate at 2 MiB with two backups instead of growing without bound.
- `bdo_music_composer.app.support_bundle` creates a bounded, path-redacted ZIP
  containing only public runtime facts and the tail of the crash log. It never
  uploads automatically and excludes projects, Owner IDs, scores, audio,
  settings, and local paths.
- `BDO-Music-Composer.exe --export-support-bundle <path.zip>` and the source
  `scripts/export_support_bundle.py` entry publish that ZIP atomically to a
  path explicitly selected by the user.
- Frozen Windows launches register Application Restart. Existing immutable
  autosave remains the sole data-recovery owner; Windows restart registration
  does not create a second project writer.

## Phase 8 — desktop qualification

- `bdo_music_composer.ui.accessibility_audit` audits visible interactive
  QWidget controls for an accessible name and keyboard focus.
- `tools/qualify_desktop_ui.py` constructs the real main window in an isolated
  user-data root and emits a path-free compatibility report. It now fails on
  Windows x64 mismatch, excessive construction/first-frame time,
  input-to-paint P95 above 16.7 ms, or a post-startup event-loop stall.
- `.github/workflows/windows-qualification.yml` runs the gate at 100%, 150%,
  and 200% scale every week and on demand.
- `tools/collect_runtime_compatibility.py` records OS, architecture, Qt build,
  screen size, DPI, and device-pixel ratio without user paths.

External qualification gate: release evidence still requires manual Narrator,
high-contrast, keyboard-only, device unplug/replug, low-power PC, and at least
one real audio-device run. CI output must not be labelled as those manual
tests.

## Phase 9 — native audio promotion gate

- The C ABI now exposes explicit capability bits for stereo mixing, exact-frame
  scheduling, seek, looping, and bounded voices. The Python loader rejects an
  ABI or capability mismatch before allocating a mixer.
- `native_audio_parity.compare_audio_blocks` rejects shape differences,
  non-finite output, and audio outside strict maximum/RMS error thresholds.
- Windows CI builds the native core, runs differential tests, then compiles an
  AddressSanitizer configuration.
- Unsupported articulation, reverb, delay, chorus, and non-zero `ntype`
  continue to fail closed. Production playback therefore remains on the
  Python engine rather than silently losing semantics.

Promotion remains blocked until every production event/DSP branch has a golden
parity fixture, long-run real-device underruns are zero, and the full frozen
application can fall back safely after native load/device failure.

## Phase 10 — explainable BDO semantic layer

`bdo_music_composer.editor.bdo_semantic_diagnostics` provides two immutable
surfaces:

1. deterministic authoring diagnostics for physical-track splitting,
   non-positive duration, canonical drum semantics, and dense onset clusters;
2. a semantic note diff that reports additions/removals plus pitch, timing,
   velocity, and articulation changes.

The readiness score is an explainable authoring indicator, not proof of game
audio equivalence. Advice is read-only, carries confidence/evidence status,
and never mutates `TrackState`, optimization, autosave, preview, or export.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_release_evidence `
  tests.test_support_bundle `
  tests.test_windows_recovery `
  tests.test_accessibility_audit `
  tests.test_runtime_compatibility `
  tests.test_native_audio_core `
  tests.test_native_audio_parity `
  tests.test_bdo_semantic_diagnostics -v

powershell -ExecutionPolicy Bypass -File packaging\native_audio\build.ps1
powershell -ExecutionPolicy Bypass -File packaging\native_audio\build.ps1 `
  -Configuration Debug -AddressSanitizer
.\.venv\Scripts\python.exe tools\qualify_desktop_ui.py
```

The repository hygiene check, syntax gates, complete unit suite, and relevant
frozen executable tests remain mandatory before a distributable release.
