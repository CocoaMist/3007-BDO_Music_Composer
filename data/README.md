# Data directory

This directory contains derived metadata used to map application instruments and articulations to Black Desert Online-compatible identifiers.

No Black Desert Online audio, textures, executables, or other proprietary game assets are distributed here. Preview audio must be supplied and configured by the user from a lawful local source.

Some research manifests retain historical absolute source paths. Those path fields are non-authoritative provenance metadata and are not used as portable installation locations. At runtime, missing sample paths are rebased under the user-configured `audio_root`, using the bank and source identifier stored in the mapping.

When adding or regenerating data:

1. Keep runtime mappings deterministic and reviewable.
2. Do not commit audio samples, extracted game assets, personal paths, account identifiers, or character names.
3. Record the generator, source assumptions, and schema changes.
4. Run the mapping and real-time audio regression tests.
