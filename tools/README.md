# Developer tools: sharp objects live here

These are developer-only audits, benchmarks, validators, and preparation
utilities. The desktop app and packaged runtime must not depend on them.

## Temporary conversion

- [`bdo_to_midi.py`](bdo_to_midi.py) converts a BDO v9 score to a playable
  Type-1 MIDI file without integrating with the desktop application.  It
  embeds exact BDO note fields (`ntype`, both velocity bytes, and floating-point
  milliseconds) in per-track standard MIDI sequencer-specific metadata. Run:
  `python tools/bdo_to_midi.py input.bdo output.mid --verify`.
- [`bdo_to_midi_gui.py`](bdo_to_midi_gui.py) is the separate Windows UI for
  the same temporary converter. Build only this tool with
  `powershell -ExecutionPolicy Bypass -File packaging\\windows\\build_bdo_to_midi_tool.ps1`;
  it writes `out/tools/bdo-to-midi/BDO-to-MIDI.exe` and does not alter the
  desktop application's build.

## Repository and performance checks

- [`check_repository_hygiene.py`](check_repository_hygiene.py)
- [`check_readme_locales.py`](check_readme_locales.py)
- [`collect_runtime_compatibility.py`](collect_runtime_compatibility.py)
  emits path-free OS, Qt, DPI, and screen qualification evidence.
- [`qualify_desktop_ui.py`](qualify_desktop_ui.py) constructs the real main
  window in isolation and fails on missing interactive accessibility metadata,
  Windows x64 incompatibility, first-frame regressions, input-to-paint latency,
  or event-loop stalls. CI runs it at 100%, 150%, and 200% scale.
- [`benchmark_conversion_validation.py`](benchmark_conversion_validation.py)
- [`benchmark_dense_ui.py`](benchmark_dense_ui.py)
- [`benchmark_native_audio_core.py`](benchmark_native_audio_core.py)
  measures the optional original C++ differential mixer at explicit low-latency
  frame sizes; build it first with `packaging/native_audio/build.ps1`.
- [`benchmark_realtime_audio.py`](benchmark_realtime_audio.py)
- [`find_dead_code.py`](find_dead_code.py) reports candidate-dead functions
  and methods in the application package for manual review. It is intentionally
  read-only because textual scanning cannot prove that public or dynamically
  dispatched entry points are unused.
- [`benchmark_transcription_candidate_queries.py`](benchmark_transcription_candidate_queries.py)
- [`stress_project_reliability.py`](stress_project_reliability.py) runs a
  deterministic, temporary-directory-only adversarial workload against project
  undo/redo, autosave atomic replacement, malformed snapshots, diagnostic-log
  failure, and bounded history. Run `python tools/stress_project_reliability.py
  --seed 20260813 --iterations 120`.

## Game/audio evidence audits

- [`analyze_instrument_samples.py`](analyze_instrument_samples.py)
- [`audit_bdo_sample_mapping.py`](audit_bdo_sample_mapping.py)
- [`audit_game_playback_coverage.py`](audit_game_playback_coverage.py)
- [`audit_python_realtime_match.py`](audit_python_realtime_match.py)
- [`compare_audio_validation.py`](compare_audio_validation.py)
- [`generate_audio_validation_matrix.py`](generate_audio_validation_matrix.py)
- [`build_wwise_runtime_profile.py`](build_wwise_runtime_profile.py)
- [`map_wwise_midi_tracking.py`](map_wwise_midi_tracking.py)

## Local preparation

- [`index_wav_samples.py`](index_wav_samples.py)
- [`install_example_project.py`](install_example_project.py)
- [`sanitize_mapping_paths.py`](sanitize_mapping_paths.py)

The public repository does not provide restricted-content acquisition or
distribution tools. See [`docs/CONTENT_BOUNDARY.md`](../docs/CONTENT_BOUNDARY.md).

Downloaded utilities, private audio, local caches, and generated reports are
ignored workspace data. Do not add them to Git or package them with the app.
