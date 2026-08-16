# Data: small rules, no private content

This directory stores small, versioned rules used to map instruments and
articulations to Black Desert Online-compatible identifiers. It is not a place
for user data or game assets.

`profiles/` contains versioned game constraints with explicit `verified`,
`inferred`, or `approximate` evidence. Profiles contain only portable rules and
must not include Owner IDs, character names, audio assets, or local paths.

No restricted game content is distributed here. External preview content must
come from a source the user is permitted to use.

Some research manifests retain historical absolute source paths. Those path fields are non-authoritative provenance metadata and are not used as portable installation locations. At runtime, missing sample paths are rebased under the user-configured `audio_root`, using the bank and source identifier stored in the mapping.

When adding or regenerating data:

1. Keep runtime mappings deterministic and reviewable.
2. Do not commit audio samples, extracted game assets, personal paths, account identifiers, or character names.
3. Record the generator, source assumptions, and schema changes.
4. Run the mapping and real-time audio regression tests.
