# Scripts we actually support

If a command is not listed here, do not treat it as a supported workflow.
Scripts parse arguments, call the real owner module, and report a result; they
do not become a second home for application logic.

## User and operator entry points

- [`bdo_convert.py`](bdo_convert.py) — MIDI-to-BDO command-line conversion.
- [`inspect_bdo.py`](inspect_bdo.py) — privacy-conscious BDO score inspection.
- [`scripts/wpf_sidecar.py`](./wpf_sidecar.py) — Qt-free NDJSON bridge for external WPF
  hosts.
- [`install_transcription.ps1`](install_transcription.ps1) — pinned optional
  transcription environment setup.

- [`export_support_bundle.py`](export_support_bundle.py) — writes a bounded,
  path-redacted diagnostic ZIP only to a user-selected destination.

## Release gates

- [`audit_transcription_licenses.py`](audit_transcription_licenses.py) —
  exact dependency inventory used by the Windows release gate.
- [`generate_update_manifest.py`](generate_update_manifest.py) — creates the
  exact-byte RSA-signed stable-channel manifest shared by GitHub and Gitee;
  the signing key must remain outside the repository.

- [`generate_release_evidence.py`](generate_release_evidence.py) — emits the
  release artifact SHA-256 and deterministic SPDX 2.3 evidence.

## Controlled evidence and private-corpus checks

- [`generate_bdo_codec_probes.py`](generate_bdo_codec_probes.py) — one-variable
  private BDO v9 probes.
- [`make_all_notes_verify_bdo.py`](make_all_notes_verify_bdo.py) — game test
  scores for instrument/pitch coverage.
- [`make_fx_verify_bdo.py`](make_fx_verify_bdo.py) — game test scores for
  articulation and FX coverage.
- [`verify_private_bdo_corpus.py`](verify_private_bdo_corpus.py) — redacted
  round-trip validation of a local score corpus.
- [`benchmark_babyslakh_transcription.py`](benchmark_babyslakh_transcription.py)
  — reproducible transcription benchmark driver.

These commands may read Owner IDs, game scores, audio, or private paths. Their
inputs and outputs belong outside Git, normally under an ignored local
directory.

## Legacy experiment

- [`optimize_midi_conductor.py`](optimize_midi_conductor.py) — fixed-profile
  MIDI experiment. It is not the production `optimization/` pipeline and must
  not be called by the application.
