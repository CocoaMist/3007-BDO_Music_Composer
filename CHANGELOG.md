# Changelog

## 0.3.0 - 2026-07-23

- Replace the vendored MIDI-to-BDO runtime with independent `bdo_midi`,
  `bdo_export`, and `bdo_codec` packages.
- Preserve the editor's five-field note model while covering MIDI tempo,
  program, sustain, performance-control, lyric, and percussion behavior.
- Keep dual velocities, game track volume, eight-byte settings, articulations,
  physical 730-note tracks, and empty trailing tracks through canonical export.
- Remove historical `midi2bdo` and `_ice` imports from the application,
  developer tools, tests, and Windows packaging.

## 0.2.0 - 2026-07-15

- Reposition the project as a BDO score research and editing lab.
- Add versioned BDO profiles, unified validation issues, score snapshots, and structural diffing.
- Add versioned project schema migration, project-level editor commands, and optimizer plugin hosting.
- Redesign the piano roll around a full-width canvas with integrated ruler seeking and sample preload feedback.
- Add note audition, draw gestures, articulation shortcuts, ghost notes, and a practical velocity lane.
- Improve asynchronous real-time sample loading, cancellation, caching, and editor playback behavior.
- Coordinate the main timeline, settings, editor layout, localization, and scrollbars across light and dark themes.

## 0.1.0 - 2026-07-14

- Initial Windows release.
