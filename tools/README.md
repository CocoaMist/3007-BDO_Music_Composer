# Developer tools

`tools/` contains developer-only audits, benchmarks, local evidence importers,
and one-off data preparation utilities. The desktop application and packaged
runtime must not depend on these entry points.

## Repository and performance checks

- [`check_repository_hygiene.py`](check_repository_hygiene.py)
- [`check_readme_locales.py`](check_readme_locales.py)
- [`benchmark_conversion_validation.py`](benchmark_conversion_validation.py)
- [`benchmark_dense_ui.py`](benchmark_dense_ui.py)
- [`benchmark_realtime_audio.py`](benchmark_realtime_audio.py)
- [`benchmark_transcription_candidate_queries.py`](benchmark_transcription_candidate_queries.py)

## Game/audio evidence audits

- [`analyze_instrument_samples.py`](analyze_instrument_samples.py)
- [`audit_bdo_sample_mapping.py`](audit_bdo_sample_mapping.py)
- [`audit_game_playback_coverage.py`](audit_game_playback_coverage.py)
- [`audit_python_realtime_match.py`](audit_python_realtime_match.py)
- [`compare_audio_validation.py`](compare_audio_validation.py)
- [`generate_audio_validation_matrix.py`](generate_audio_validation_matrix.py)
- [`build_wwise_runtime_profile.py`](build_wwise_runtime_profile.py)
- [`map_wwise_midi_tracking.py`](map_wwise_midi_tracking.py)

## Local import, extraction, and conversion

- [`convert_wem_to_wav.py`](convert_wem_to_wav.py)
- [`extract_wwise_wem.py`](extract_wwise_wem.py)
- [`import_bdo_game_art.py`](import_bdo_game_art.py)
- [`index_wav_samples.py`](index_wav_samples.py)
- [`install_example_project.py`](install_example_project.py)
- [`list_bdo_paz_audio.py`](list_bdo_paz_audio.py)
- [`sanitize_mapping_paths.py`](sanitize_mapping_paths.py)

## Native research helpers

- [`extract_bdo_bgm.cpp`](extract_bdo_bgm.cpp)
- [`extract_bdo_instruments.cpp`](extract_bdo_instruments.cpp)
- [`list_bdo_paz_audio.cpp`](list_bdo_paz_audio.cpp)
- [`validate_paz_key.cpp`](validate_paz_key.cpp)

Downloaded tools, extracted game assets, local caches, and generated reports are
ignored workspace data. Do not add them to Git or package them with the app.
