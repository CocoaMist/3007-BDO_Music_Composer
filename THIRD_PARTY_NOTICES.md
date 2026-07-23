# Third-party notices

This project depends on third-party software, including PySide6/Qt, Mido, NumPy, and PyInstaller. Their respective licenses and notices apply; see the dependency metadata installed with each package and the official upstream projects.

The root MIT License applies only to original BDO Music Composer code owned by CocoaMist. It does not relicense third-party components.

Earlier repository revisions contained vendored/adapted code attributed to
Bishop-R's `midi-to-bdo`. That historical material remains subject to its
original terms. Starting with v0.3.0, the current source tree and release
artifacts contain no files or import-compatible modules from that vendor tree.

The MIDI parser and mappings under `bdo_midi/`, the adaptation layer under
`bdo_export/`, and the BDO v9 document model, reader/writer, and ICE
implementation under `bdo_codec/` are project implementations based on Mido's
public API, observed format behavior, local test vectors, and game-save
evidence.

Black Desert Online names and format references are used for interoperability. This repository is unofficial, is not affiliated with Pearl Abyss, and must not include proprietary game assets.
