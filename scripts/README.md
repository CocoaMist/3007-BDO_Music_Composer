# Supported scripts

`scripts/` contains maintained command-line, release, and controlled validation
entry points. Reusable application behavior must stay in its owning module;
scripts should only parse arguments, call that owner, and publish an explicit
result.

## User and operator entry points

- [`bdo_convert.py`](bdo_convert.py) — MIDI-to-BDO command-line conversion.
- [`inspect_bdo.py`](inspect_bdo.py) — privacy-conscious BDO score inspection.
- [`install_transcription.ps1`](install_transcription.ps1) — pinned optional
  transcription environment setup.

## Release gates

- [`audit_transcription_licenses.py`](audit_transcription_licenses.py) —
  exact dependency inventory used by the Windows release gate.

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
