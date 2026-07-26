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

The single Windows BDO Music Composer package includes local audio
transcription through the upstream Basic Pitch package, ONNX Runtime, librosa,
and their transitive dependencies listed by `requirements-transcription.txt`.
Source checkouts install the same runtime through
`scripts/install_transcription.ps1`. These packages retain their own upstream
terms and notices.

The bundled stack is expected to include Basic Pitch (Apache-2.0 source
license), ONNX Runtime (MIT), librosa (ISC), mir_eval (MIT), pretty_midi (MIT),
resampy (ISC), scikit-learn (BSD-3-Clause), SciPy (BSD-3-Clause), and their
transitive/native dependencies, including SoundFile (BSD-3-Clause) and
python-soxr/libsoxr (LGPL-2.1-or-later). These labels are an engineering
inventory, not a completed legal review. In particular, the Basic Pitch ONNX
model and native libraries bundled inside scientific Python wheels require an
exact-artifact notice and redistribution review.

The semantic-block, harmony, deterministic voice-grouping, and BDO Top-3
features do not add another pretrained model or a separate product edition.
They operate within the existing Basic Pitch/scientific dependency set already
covered by the generated build inventory. References to Sonic Visualiser, Tony,
Chordino, MT3, YourMT3, Essentia, and Omnizart describe interaction or research
context only; no source code, model, or runtime from those projects is copied or
bundled by this implementation.

The development-only transcription benchmark can download BabySlakh from
Zenodo record 4603844. BabySlakh is licensed CC BY 4.0. Its audio and MIDI are
stored only in the user's local benchmark cache and are not committed,
packaged, or redistributed with this application.

Optional timbre matching reads only game samples that the user provides
locally. The application does not distribute those samples. Its Local AppData
cache contains content-keyed aggregate feature profiles, not WAV payloads,
audio clips, sample paths, or reference-audio paths; neither that cache nor the
reference audio is included in project files or the Windows executable.

Every `BDO-Music-Composer.exe` build runs
`scripts/audit_transcription_licenses.py`. It records the installed transitive
dependency graph, versions, declared licenses, available license files, and
hashes of the ONNX model and ONNX Runtime native libraries. Available notice
files and the generated report are embedded in the executable. The checked-in
`packaging/transcription_release_policy.json` remains fail-closed, so public
distribution is not authorized until a reviewer approves that exact inventory
digest and confirms the complete notice set.
